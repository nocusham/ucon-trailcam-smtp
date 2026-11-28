"""Mixed-owner offline backup for trusted, fully quiescent production state.

No CLI. Administrator-controlled code and ancestors, no concurrent writers
(including manual workers), no hostile mounts or filesystems. Never open the
live database with SQLite as root: copy the stopped DB and any WAL to a
private scratch directory, then use the existing SQLite snapshot helper.
Do not restore or activate anything here.
"""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import shutil
import stat
import tempfile

from deploy.production_layout import APP
from deploy.state_backup import (
    BackupError, disjoint, finalize_backup, new_destination, snapshot,
)


def _metadata(path):
    return path.lstat()


def _check(path, owner, kind, modes, device=None):
    info = _metadata(path)
    if (stat.S_IFMT(info.st_mode) != kind
            or (info.st_uid, info.st_gid) != owner
            or stat.S_IMODE(info.st_mode) not in modes
            or (kind == stat.S_IFREG and info.st_nlink != 1)
            or (device is not None and info.st_dev != device)
            or os.listxattr(path, follow_symlinks=False)):
        raise BackupError('Unsafe backup source type, ownership, mode or attributes')
    return info


def _directory(path, owner, mode, device=None):
    return _check(path, owner, stat.S_IFDIR, (mode,), device)


def _file(path, owner, modes=(0o600,), device=None):
    return _check(path, owner, stat.S_IFREG, modes, device)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _copy(source, target, owner, modes=(0o600,), device=None):
    before = _file(source, owner, modes, device)
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as reader:
        if _identity(os.fstat(reader.fileno())) != _identity(before):
            raise BackupError('Source changed before copying')
        out = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(out, 'wb') as writer:
            shutil.copyfileobj(reader, writer)
        if _identity(os.fstat(reader.fileno())) != _identity(before):
            raise BackupError('Source changed during copying')


def _copy_media(source, target, service, device):
    before = _directory(source, service, 0o700, device)
    target.mkdir(mode=0o700)
    for child in sorted(source.iterdir()):
        if stat.S_ISDIR(child.lstat().st_mode):
            _copy_media(child, target / child.name, service, device)
        else:
            _copy(child, target / child.name, service, device=device)
    if _identity(source.lstat()) != _identity(before):
        raise BackupError('Media directory changed during copying')


def _present(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _paths(root, administrator, service):
    root = Path(root).absolute()
    if root.resolve() != root:
        raise BackupError('Expected a trusted filesystem root')
    for relative in ('.', 'etc', 'var', 'var/lib', 'var/backups'):
        _directory(root / relative, administrator, 0o755)
    config = root / 'etc' / APP
    state = root / 'var/lib' / APP
    backups = root / 'var/backups' / APP
    _directory(config, (administrator[0], service[1]), 0o750)
    state_info = _directory(state, service, 0o700)
    _directory(state / 'media', service, 0o700, state_info.st_dev)
    _directory(backups, administrator, 0o700)
    return config, state, backups, state_info.st_dev


@contextmanager
def _locked_backup(root, destination, administrator, service):
    """Private implementation also exercised with same-owner test fixtures."""
    if (os.geteuid(), os.getegid()) != administrator:
        raise BackupError('Incorrect backup identity')
    config, state, backups, device = _paths(root, administrator, service)
    destination = new_destination(destination)
    if destination.parent != backups:
        raise BackupError('Backup must be in the private administrator directory')
    disjoint(config, state, destination)
    if _present(config / 'service-enabled'):
        raise BackupError('Activation marker must be absent')
    db = state / 'events.sqlite3'
    lock = state / 'events.sqlite3.lock'
    before = _file(lock, service, device=device)
    fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        if _identity(os.fstat(stream.fileno())) != _identity(before):
            raise BackupError('Queue lock changed')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError('Queue is locked; stop all workers before backup') from None
        # Refuse a rollback journal rather than guess whether recovery is
        # needed. WAL is copied only from a stopped, exclusively held queue.
        if _present(Path(str(db) + '-journal')):
            raise BackupError('Rollback journal requires separate recovery review')
        wal = Path(str(db) + '-wal')
        shm = Path(str(db) + '-shm')
        if _present(shm):
            _file(shm, service, device=device)
        destination.mkdir(mode=0o700)
        (destination / 'config').mkdir(mode=0o700)
        (destination / 'state').mkdir(mode=0o700)
        _copy(config / 'config.toml', destination / 'config/config.toml',
              (administrator[0], service[1]), (0o640,))
        _copy(config / '.env', destination / 'config/.env', service, (0o400, 0o600))
        with tempfile.TemporaryDirectory(prefix='.sqlite-', dir=destination) as work:
            scratch = Path(work) / 'events.sqlite3'
            _copy(db, scratch, service, device=device)
            if _present(wal):
                _copy(wal, Path(str(scratch) + '-wal'), service, device=device)
            # Rebuild WAL index in private scratch; never copy live SHM.
            snapshot(scratch, destination / 'state/events.sqlite3')
        _copy_media(state / 'media', destination / 'state/media', service, device)
        if _identity(lock.lstat()) != _identity(before):
            raise BackupError('Queue lock changed during backup')
        counts = finalize_backup(destination, state / 'media')
        yield counts


@contextmanager
def locked_production_backup(destination, service_uid, service_gid):
    """Root-only fixed-path backup library; caller owns maintenance lock."""
    if (os.geteuid(), os.getegid()) != (0, 0):
        raise BackupError('Administrator identity required')
    if (type(service_uid) is not int or type(service_gid) is not int
            or service_uid <= 0 or service_gid <= 0):
        raise BackupError('Service identity must be non-root')
    with _locked_backup(Path('/'), destination, (0, 0),
                        (service_uid, service_gid)) as counts:
        yield counts
