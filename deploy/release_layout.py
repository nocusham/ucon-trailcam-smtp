"""Offline release-pointer primitives for a trusted operator-owned installation root.

The caller must stop the service and hold the future deployment transaction
lock across staging, backup and activation. These helpers never manage systemd
or private state. A ready marker is an operator assertion, not a signature.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import re
import stat
import tempfile


class ReleaseError(ValueError):
    pass


def _release_id(value):
    if (not isinstance(value, str)
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,79}', value)
            or '..' in value):
        raise ReleaseError('Invalid release identifier')
    return value


def _directory(path):
    if not path.is_dir() or path.is_symlink():
        raise ReleaseError('Expected an existing real directory')
    return path


def _regular(path):
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ReleaseError('Expected a regular nonsymlink file')
    return path


def _ready_release(root, release):
    release = _release_id(release)
    directory = _directory(_directory(root / 'releases') / release)
    try:
        marker = _regular(directory / '.ready')
        if marker.read_bytes() != (release + '\n').encode('ascii'):
            raise ReleaseError('Release readiness marker does not match')
        executable = _regular(_directory(_directory(directory / 'venv') / 'bin')
                              / 'ucon-trailcam-smtp')
        if not os.access(executable, os.X_OK):
            raise ReleaseError('Release console entrypoint is not executable')
    except FileNotFoundError:
        raise ReleaseError('Release is incomplete or not marked ready') from None
    return directory


def _current_release(root):
    current = root / 'current'
    try:
        mode = current.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISLNK(mode):
        raise ReleaseError('Current pointer is not a symlink')
    target = os.readlink(current)
    prefix = 'releases/'
    if not target.startswith(prefix):
        raise ReleaseError('Current pointer must be relative to releases/')
    release = _release_id(target[len(prefix):])
    _ready_release(root, release)
    return release


@contextmanager
def _pointer_lock(root):
    # The root and releases directory must be writable only by the trusted
    # operator (root in production). This is not an adversarial directory API.
    fd = os.open(root / '.release-switch.lock',
                 os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'rb') as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ReleaseError('Invalid release lock file')
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def switch_release(root, release):
    """Atomically select a prepared release, returning the previous ID or None.

    Does not copy, remove or restore releases, configuration, databases or media.
    A previous ID may be supplied again for an explicit code-only rollback.
    Atomic visibility is not a power-loss durability guarantee.
    """
    root = _directory(Path(root).absolute())
    release = _release_id(release)
    with _pointer_lock(root):
        _ready_release(root, release)
        previous = _current_release(root)
        if previous == release:
            return previous
        with tempfile.TemporaryDirectory(prefix='.switch-', dir=root) as tmp:
            candidate = Path(tmp) / 'current'
            candidate.symlink_to('releases/' + release)
            os.replace(candidate, root / 'current')
        return previous
