"""Fixed-unit maintenance adapter, not a privileged command-line interface.

Use trusted administrator-controlled code and hold the deployment lock.
The caller must prevent concurrent starts and manual writers. Reported
systemd state is not proof of cgroup emptiness or exclusive maintenance.
"""
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess

from deploy.release_layout import ReleaseError
from deploy.production_layout import APP


UNIT = APP + '.service'
FRAGMENT = '/etc/systemd/system/' + UNIT
PROPERTIES = (
    'LoadState', 'ActiveState', 'SubState', 'MainPID', 'ControlPID',
    'Job', 'FragmentPath', 'DropInPaths', 'NeedDaemonReload',
    'KillMode', 'SendSIGKILL',
)


def _run(args):
    return subprocess.run(
        ['/usr/bin/systemctl', '--system', '--no-pager', '--no-ask-password', *args],
        check=True, capture_output=True, text=True, encoding='utf-8',
        timeout=210, cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8',
                                 'LC_ALL': 'C.UTF-8'},
    ).stdout


def _parse_properties(output):
    values = {}
    for line in output.splitlines():
        name, sep, value = line.partition('=')
        if not sep or name not in PROPERTIES or name in values:
            raise ReleaseError('Unexpected systemd property output')
        values[name] = value
    if set(values) != set(PROPERTIES):
        raise ReleaseError('Incomplete systemd property output')
    return values


class _ServiceControl:
    """Internal testable adapter; root/runner are not public host options."""

    def __init__(self, root, administrator, unit_sha256, runner):
        if not isinstance(unit_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', unit_sha256):
            raise ReleaseError('Expected approved unit SHA256')
        self.root = Path(root)
        self.administrator = administrator
        self.unit_sha256 = unit_sha256
        self.runner = runner
        self.config = self.root / 'etc' / APP
        self.marker = self.config / 'service-enabled'

    def _directory(self, path, *, shared=False):
        info = path.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.administrator[0]
                or (not shared and info.st_gid != self.administrator[1])
                or stat.S_IMODE(info.st_mode) != (0o750 if shared else 0o755)
                or os.listxattr(path, follow_symlinks=False)):
            raise ReleaseError('Unsafe administrator directory')

    def _regular(self, path, mode):
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_uid, info.st_gid) != self.administrator
                or stat.S_IMODE(info.st_mode) != mode
                or os.listxattr(path, follow_symlinks=False)):
            raise ReleaseError('Unsafe administrator file')

    def _verify_unit(self):
        for path in (self.root, self.root / 'etc', self.root / 'etc/systemd',
                     self.root / 'etc/systemd/system'):
            self._directory(path)
        self._directory(self.config, shared=True)
        fragment = self.root / FRAGMENT.lstrip('/')
        self._regular(fragment, 0o644)
        if hashlib.sha256(fragment.read_bytes()).hexdigest() != self.unit_sha256:
            raise ReleaseError('Installed unit digest does not match approval')

    def _properties(self):
        self._verify_unit()
        values = _parse_properties(self.runner([
            'show', '--all', '--property=' + ','.join(PROPERTIES), UNIT,
        ]))
        required = {'LoadState': 'loaded', 'FragmentPath': FRAGMENT,
                    'DropInPaths': '', 'NeedDaemonReload': 'no',
                    'KillMode': 'control-group', 'SendSIGKILL': 'yes'}
        if any(values[name] != expected for name, expected in required.items()):
            raise ReleaseError('Unexpected loaded unit or systemd configuration')
        return values

    def _marker_absent(self):
        try:
            self.marker.lstat()
        except FileNotFoundError:
            return True
        return False

    def inhibit_start(self):
        """Remove only the approved root-owned activation marker.

        No mask, disable, daemon-reload or automatic marker restoration.
        Removing the condition marker does not stop an existing process.
        """
        self._properties()
        if not self._marker_absent():
            self._regular(self.marker, 0o644)
            self.marker.unlink()
        if not self._marker_absent():
            raise ReleaseError('Activation marker still present')
        return True

    def is_quiescent(self):
        """Check the expected unit and reported inactive state, fail closed."""
        values = self._properties()
        return (self._marker_absent()
                and values['ActiveState'] == 'inactive'
                and values['SubState'] == 'dead'
                and values['MainPID'] == '0'
                and values['ControlPID'] == '0'
                and values['Job'] in ('', '0'))

    def quiesce(self):
        """Stop synchronously after start inhibition, then verify state."""
        self._properties()
        if not self._marker_absent():
            raise ReleaseError('Inhibit start before stopping the unit')
        self.runner(['stop', UNIT])
        if not self.is_quiescent():
            raise ReleaseError('Unit did not reach the required inactive state')
        return True


def production_service_control(unit_sha256):
    """Root-only factory for fixed target paths; no arbitrary unit/runner.

    The digest must identify independently approved unit bytes. Caller
    must hold the deployment lock and establish a trusted root context.
    No host operation is performed until a method is called.
    """
    if (os.geteuid(), os.getegid()) != (0, 0):
        raise ReleaseError('Administrator identity required')
    return _ServiceControl(Path('/'), (0, 0), unit_sha256, _run)
