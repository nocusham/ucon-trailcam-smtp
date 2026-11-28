"""Read-only metadata contract for a prepared, disabled production layout.

Development review helper, not a privileged installer or activation gate.
The caller must supply a trusted root and stop all writers. lstat checks
are point-in-time observations, not race-safe traversal of hostile trees.
ACLs, mount policy, supplementary groups, code contents, the full venv
tree, receipt consistency and actual service-user access need later checks.
"""
from pathlib import Path
import os
import stat

from deploy.release_layout import _release_id


APP = 'ucon-trailcam-smtp'


class LayoutError(ValueError):
    pass


def _metadata(path):
    return path.lstat()


def check_layout(root, release, service_uid, service_gid, *, initialized):
    """Check selected paths without reading file contents or changing permissions.

    Root means the filesystem root (or a trusted synthetic filesystem root).
    UID/GID 0 designate the administrator; the service has distinct nonzero
    IDs. initialized describes whether the queue has been initialized, not
    whether a service has run. The activation marker must be absent.
    """
    root = Path(root)
    if not root.is_absolute() or '..' in root.parts:
        raise LayoutError('Expected an absolute trusted filesystem root')
    if (type(service_uid) is not int or type(service_gid) is not int
            or service_uid <= 0 or service_gid <= 0):
        raise LayoutError('Service identity must be non-root')
    if type(initialized) is not bool:
        raise LayoutError('Specify initialized state explicitly')
    release = _release_id(release)

    def check(relative, kind, owner, modes):
        path = root / relative
        try:
            info = _metadata(path)
        except FileNotFoundError:
            raise LayoutError(f'Missing required path: {relative}') from None
        if (stat.S_IFMT(info.st_mode) != kind
                or (info.st_uid, info.st_gid) != owner
                or stat.S_IMODE(info.st_mode) not in modes
                or (kind == stat.S_IFREG and info.st_nlink != 1)):
            raise LayoutError(f'Incorrect type, ownership or mode: {relative}')

    def absent(relative):
        try:
            _metadata(root / relative)
        except FileNotFoundError:
            return
        raise LayoutError(f'Path must be absent: {relative}')

    admin = (0, 0)
    service = (service_uid, service_gid)
    shared = (0, service_gid)
    opt = f'opt/{APP}'
    etc = f'etc/{APP}'
    state = f'var/lib/{APP}'
    releases = opt + '/releases'
    public_dir = (0o755,)
    private_dir = (0o700,)
    # Check the named ancestor directories before their children. No recursive
    # traversal or following symlinks in these named paths.
    for relative in ('.', 'opt', 'etc', 'var', 'var/lib', opt, releases,
                     'etc/systemd', 'etc/systemd/system'):
        check(relative, stat.S_IFDIR, admin, public_dir)

    def check_release(identifier):
        folder = releases + '/' + identifier
        for relative in (folder, folder + '/venv', folder + '/venv/bin'):
            check(relative, stat.S_IFDIR, admin, public_dir)
        check(folder + '/.ready', stat.S_IFREG, admin, (0o600, 0o644))
        check(folder + '/venv/bin/' + APP, stat.S_IFREG, admin, (0o755,))

    check_release(release)
    current = opt + '/current'
    try:
        info = _metadata(root / current)
    except FileNotFoundError:
        pass
    else:
        if not stat.S_ISLNK(info.st_mode) or (info.st_uid, info.st_gid) != admin:
            raise LayoutError('Current pointer must be an administrator-owned symlink')
        target = os.readlink(root / current)
        if not target.startswith('releases/'):
            raise LayoutError('Current pointer must target a relative release')
        selected = _release_id(target[len('releases/'):])
        if selected != release:
            check_release(selected)

    check(etc, stat.S_IFDIR, shared, (0o750,))
    check(etc + '/config.toml', stat.S_IFREG, shared, (0o640,))
    check(etc + '/.env', stat.S_IFREG, service, (0o400, 0o600))
    absent(etc + '/service-enabled')
    check('etc/systemd/system/' + APP + '.service', stat.S_IFREG, admin, (0o644,))
    for relative in (state, state + '/media'):
        check(relative, stat.S_IFDIR, service, private_dir)
    for relative in (state + '/events.sqlite3', state + '/events.sqlite3.lock'):
        if initialized:
            check(relative, stat.S_IFREG, service, (0o600,))
        else:
            absent(relative)
