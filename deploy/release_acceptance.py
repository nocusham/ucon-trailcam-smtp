"""Bind offline acceptance to independently approved release bytes.

No root CLI, schema migration, service start or state restore. Only trusted
administrator-controlled code, approved artifacts and quiescent writers.
The digest identifies the complete copied venv, not its provenance.
"""
from dataclasses import dataclass
import grp
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import tempfile

from deploy.prepare_release import deployment_lock
from deploy.production_backup import _directory, _file, _paths
from deploy.production_layout import APP
from deploy.release_handoff import _check_node
from deploy.release_layout import ReleaseError, _current_release, _ready_release, _release_id
from deploy.schema_compatibility import SCHEMA_VERSION, check_backup_schema
from deploy.service_control import production_service_control
from deploy.state_backup import verify_backup


@dataclass(frozen=True)
class ReleaseApproval:
    release: str
    tree_sha256: str
    schema_contract: int

    def __post_init__(self):
        _release_id(self.release)
        if (not isinstance(self.tree_sha256, str)
                or not re.fullmatch(r'[0-9a-f]{64}', self.tree_sha256)
                or type(self.schema_contract) is not int
                or self.schema_contract != SCHEMA_VERSION):
            raise ReleaseError('Invalid release approval')


def service_identity():
    account = pwd.getpwnam(APP)
    group = grp.getgrnam(APP)
    if account.pw_uid <= 0 or group.gr_gid <= 0 or account.pw_gid != group.gr_gid:
        raise ReleaseError('Unexpected service identity')
    return account.pw_uid, group.gr_gid


def release_tree_digest(install, release, administrator, *, ready):
    """Review a trusted, frozen tree without executing it.

    Include every venv entry, relative path, mode and regular file hash.
    The readiness marker is checked separately and excluded from the digest.
    A digest is not an authorization or a signature. No hostile traversal.
    """
    install = Path(install).absolute()
    release = _release_id(release)
    if install.resolve() != install:
        raise ReleaseError('Unexpected installation path')
    for path in (install, install / 'releases'):
        _directory(path, administrator, 0o755)
    folder = install / 'releases' / release
    _directory(folder, administrator, 0o755)
    names = {'venv', '.ready'} if ready else {'venv'}
    if {p.name for p in folder.iterdir()} != names:
        raise ReleaseError('Unexpected release layout')
    if ready:
        _file(folder / '.ready', administrator, (0o600, 0o644))
        _ready_release(install, release)
    for relative in ('venv', 'venv/bin', 'venv/lib'):
        _directory(folder / relative, administrator, 0o755, folder.stat().st_dev)
    for relative in ('venv/bin/python', 'venv/bin/' + APP):
        _file(folder / relative, administrator, (0o755,), folder.stat().st_dev)
    _file(folder / 'venv/pyvenv.cfg', administrator, (0o644,), folder.stat().st_dev)
    device = folder.stat().st_dev
    entries = []

    def walk(path):
        relative = path.relative_to(folder).as_posix()
        info = _check_node(path, administrator, device)
        mode = stat.S_IMODE(info.st_mode)
        if stat.S_ISDIR(info.st_mode) and mode == 0o755:
            entries.append((relative, 'directory', mode))
            for child in sorted(path.iterdir()):
                walk(child)
        elif stat.S_ISREG(info.st_mode) and mode in (0o644, 0o755):
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            entries.append((relative, 'file', mode, info.st_size, digest))
        elif (stat.S_ISLNK(info.st_mode) and relative == 'venv/lib64'
                and os.readlink(path) == 'lib'):
            entries.append((relative, 'symlink', 'lib'))
        else:
            raise ReleaseError('Unexpected release tree entry')
    walk(folder / 'venv')
    return hashlib.sha256(json.dumps(entries, separators=(',', ':'),
                                     ensure_ascii=True).encode('ascii')).hexdigest()


def verify_release(install, approval, administrator, *, ready):
    if not isinstance(approval, ReleaseApproval):
        raise ReleaseError('Explicit release approval required')
    if release_tree_digest(install, approval.release, administrator,
                           ready=ready) != approval.tree_sha256:
        raise ReleaseError('Release tree differs from approval')


def configuration_identity(config, administrator, service):
    """Private fingerprints; never print or persist outside private state."""
    _directory(config, (administrator[0], service[1]), 0o750)
    result = {}
    for name, owner, modes in (
        ('config.toml', (administrator[0], service[1]), (0o640,)),
        ('.env', service, (0o400, 0o600)),
    ):
        path = config / name
        info = _file(path, owner, modes)
        with path.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        result['config/' + name] = {'size': info.st_size, 'sha256': digest}
    return result


def run_service_config_check(install, approval, config, service):
    """Use trusted checker source and the selected venv under the service UID.

    No root candidate execution, inherited secrets, shell or output capture.
    Trusted runtime required; this is not a network or filesystem sandbox.
    """
    if (os.geteuid(), os.getegid()) != (0, 0) or min(service) <= 0:
        raise ReleaseError('Distinct administrator and service identities required')
    interpreter = install / 'releases' / approval.release / 'venv/bin/python'
    source = Path(__file__).with_name('config_compatibility.py').read_text(encoding='utf-8')
    # -I ignores cwd/user site and Python environment; -B prevents bytecode
    # writes. The copied candidate has already been independently approved.
    subprocess.run(
        [str(interpreter), '-I', '-B', '-c', source,
         '--config', str(config / 'config.toml'), '--secrets', str(config / '.env')],
        user=service[0], group=service[1], extra_groups=[], umask=0o077,
        check=True, timeout=60, cwd='/', stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': '/nonexistent'},
    )
    return True


def _accept_candidate(install, approval, config, administrator, service,
                      config_check, require_stopped):
    """Caller holds deployment lock; no current change or activation."""
    if require_stopped() is not True:
        raise ReleaseError('All writers must be stopped')
    if _current_release(install) == approval.release:
        raise ReleaseError('Cannot accept the selected release')
    verify_release(install, approval, administrator, ready=False)
    before = configuration_identity(config, administrator, service)
    if config_check(install, approval, config, service) is not True:
        raise ReleaseError('Service configuration check failed')
    if require_stopped() is not True:
        raise ReleaseError('All writers must be stopped')
    if configuration_identity(config, administrator, service) != before:
        raise ReleaseError('Configuration changed during acceptance')
    verify_release(install, approval, administrator, ready=False)
    folder = install / 'releases' / approval.release
    fd, name = tempfile.mkstemp(prefix='.ready-', dir=folder)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write((approval.release + '\n').encode('ascii'))
        # Atomic publication without overwriting an existing marker.
        os.link(temporary, folder / '.ready')
    finally:
        temporary.unlink()
    return True


def accept_production_candidate(approval, unit_sha256, *, confirm_no_other_writers):
    """Root-only readiness acceptance, not permission to start a service."""
    if (os.geteuid(), os.getegid()) != (0, 0):
        raise ReleaseError('Administrator identity required')
    if not isinstance(approval, ReleaseApproval):
        raise ReleaseError('Explicit release approval required')
    root = Path('/')
    administrator = (0, 0)
    service = service_identity()
    install = root / 'opt' / APP
    for path in (root, root / 'opt', install, install / 'releases'):
        _directory(path, administrator, 0o755)
    control = production_service_control(unit_sha256)
    with deployment_lock(install):
        config, _, _, _ = _paths(root, administrator, service)

        def stopped():
            return (control.is_quiescent() is True
                    and confirm_no_other_writers() is True)
        return _accept_candidate(install, approval, config, administrator, service,
                                 run_service_config_check, stopped)


class UpdateGate:
    """Bind both release trees, schema and private config to one backup.

    Caller holds both locks, owns the maintenance boundary, and supplies
    independent approvals. Final verification runs immediately before switch.
    """
    def __init__(self, install, config, administrator, service, previous,
                 target, config_check, review):
        if (not isinstance(previous, ReleaseApproval)
                or not isinstance(target, ReleaseApproval)
                or previous.release == target.release):
            raise ReleaseError('Distinct explicit release approvals required')
        self.install, self.config = install, config
        self.administrator, self.service = administrator, service
        self.previous, self.target = previous, target
        self.config_check, self.review = config_check, review
        self._accepted = None

    def _verify(self, previous, target, backup):
        if (previous, target) != (self.previous.release, self.target.release):
            raise ReleaseError('Release IDs differ from approval')
        for approval in (self.previous, self.target):
            verify_release(self.install, approval, self.administrator, ready=True)
        schema = check_backup_schema(backup)
        manifest = verify_backup(backup)
        identity = configuration_identity(self.config, self.administrator, self.service)
        if any(manifest['files'].get(name) != value for name, value in identity.items()):
            raise ReleaseError('Configuration differs from verified backup')
        return (Path(backup).absolute(), manifest, schema, identity)

    def approve(self, previous, target, backup):
        self._accepted = None
        before = self._verify(previous, target, backup)
        for approval in (self.previous, self.target):
            if self.config_check(self.install, approval, self.config, self.service) is not True:
                raise ReleaseError('Service configuration check failed')
        if self.review(previous, target, backup) is not True:
            raise ReleaseError('Operator compatibility approval required')
        if self._verify(previous, target, backup) != before:
            raise ReleaseError('Inputs changed during approval')
        self._accepted = before
        return True

    def verify_final(self, previous, target, backup):
        if self._accepted is None or self._verify(previous, target, backup) != self._accepted:
            raise ReleaseError('No matching compatibility approval')
        return True
