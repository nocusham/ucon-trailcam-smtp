"""Development-only offline backup and inert recovery rehearsal.

Use only trusted, operator-owned private directories. Stop all writers first.
The existing queue lock excludes cooperating workers, not arbitrary writers.
Never use a rehearsal directory as an active installation.
"""
import argparse
from contextlib import closing, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys


class BackupError(ValueError):
    pass


def directory(path):
    path = Path(path).absolute()
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or path.resolve() != path
            or info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise BackupError('Expected a real operator-owned directory')
    return path


def regular(path):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or info.st_uid != os.geteuid() or info.st_mode & 0o022):
        raise BackupError('Expected an operator-owned regular file')
    return info


def disjoint(*paths):
    for i, a in enumerate(paths):
        for b in paths[i + 1:]:
            if a.is_relative_to(b) or b.is_relative_to(a):
                raise BackupError('Source and destination directories must be disjoint')


def new_destination(path):
    path = Path(path).absolute()
    directory(path.parent)
    if path.resolve() != path or path.exists() or path.is_symlink():
        raise BackupError('Destination must not exist')
    return path


@contextmanager
def queue_lock(db):
    # Same lock path and flock protocol as queue_download.batch_lock.
    # Require an existing lock; never create or delete one for backup.
    lock = Path(str(db) + '.lock')
    regular(lock)
    fd = os.open(lock, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError('Queue is locked; stop all workers before backup') from None
        yield


def fingerprint(path):
    regular(path)
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'sha256': digest, 'size': path.stat().st_size}


def copy_file(source, target):
    regular(source)
    with source.open('rb') as reader:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as writer:
            shutil.copyfileobj(reader, writer)


def copy_tree(source, target):
    directory(source)
    target.mkdir(mode=0o700)
    for item in sorted(source.iterdir()):
        if item.is_dir() and not item.is_symlink():
            copy_tree(item, target / item.name)
        else:
            copy_file(item, target / item.name)


def read_db(path):
    return sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)


def snapshot(source, target):
    regular(source)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(fd)
    with closing(read_db(source)) as original, closing(sqlite3.connect(target)) as dest:
        original.backup(dest)
        # Produce a standalone DB, not a raw copy of a potentially WAL-backed file.
        dest.execute('PRAGMA journal_mode=DELETE').fetchone()
        dest.commit()


def inventory(root):
    result = {}
    def walk(folder):
        directory(folder)
        if folder.stat().st_mode & 0o077:
            raise BackupError('Backup directory is not private')
        for path in sorted(folder.iterdir()):
            rel = path.relative_to(root).as_posix()
            if path.is_dir() and not path.is_symlink():
                walk(path)
            elif rel != 'manifest.json':
                if regular(path).st_mode & 0o077:
                    raise BackupError('Backup file is not private')
                result[rel] = fingerprint(path)
    walk(root)
    return result


def check_state(db_path, media, original_media):
    regular(db_path)
    with closing(read_db(db_path)) as db:
        if db.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise BackupError('SQLite integrity check failed')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'events', 'cloud_runtime', 'cloud_cursors'} <= tables:
            raise BackupError('Missing required intake tables')
        if db.execute("SELECT 1 FROM events WHERE state IS NULL OR state NOT IN ('pending','downloaded','sent','uncertain') LIMIT 1").fetchone():
            raise BackupError('Unknown event state')
        counts = dict(db.execute('SELECT state,count(*) FROM events GROUP BY state'))
        if counts.get('sent', 0) or counts.get('uncertain', 0):
            if 'deliveries' not in tables:
                raise BackupError('Missing delivery receipts')
        if 'deliveries' in tables:
            if db.execute("""SELECT 1 FROM events e LEFT JOIN deliveries d USING(camera_uid,itemid)
                WHERE (e.state='sent' AND (d.accepted_utc IS NULL OR d.accepted_utc<=0))
                   OR (e.state='uncertain' AND (d.itemid IS NULL OR d.accepted_utc IS NOT NULL))
                   OR (e.state IN ('pending','downloaded') AND d.itemid IS NOT NULL)
                LIMIT 1""").fetchone():
                raise BackupError('Event and delivery receipt disagree')
            if db.execute("""SELECT 1 FROM deliveries d LEFT JOIN events e USING(camera_uid,itemid)
                WHERE e.itemid IS NULL LIMIT 1""").fetchone():
                raise BackupError('Orphan delivery receipt')
        if any(counts.get(s, 0) for s in ('sent', 'downloaded', 'uncertain')):
            if 'downloads' not in tables or db.execute("""SELECT 1 FROM events e
                LEFT JOIN downloads d USING(camera_uid,itemid)
                WHERE e.state IN ('sent','downloaded','uncertain') AND d.itemid IS NULL LIMIT 1""").fetchone():
                raise BackupError('Missing original receipt')
        if 'media_cleanup' in tables and db.execute(
                'SELECT 1 FROM media_cleanup WHERE removed_utc<=0 LIMIT 1').fetchone():
            raise BackupError('Unfinished media deletion; reconcile cleanup before backup')
        if 'downloads' in tables:
            cleaned = ('EXISTS (SELECT 1 FROM media_cleanup c WHERE c.camera_uid=d.camera_uid AND c.itemid=d.itemid)'
                       if 'media_cleanup' in tables else '0')
            rows = db.execute('SELECT e.state,d.path,d.sha256,d.size,' + cleaned +
                              ' FROM downloads d LEFT JOIN events e USING(camera_uid,itemid)')
            seen = set()
            for state, raw, digest, size, removed in rows:
                path = Path(raw)
                if not path.is_absolute() or '..' in path.parts or not path.is_relative_to(original_media):
                    raise BackupError('Original receipt outside source media directory')
                relative = path.relative_to(original_media)
                if not relative.parts or relative in seen or state not in ('sent','downloaded','uncertain'):
                    raise BackupError('Invalid original receipt')
                seen.add(relative)
                local = media / relative
                if removed:
                    if state != 'sent' or local.exists() or local.is_symlink():
                        raise BackupError('Cleanup receipt disagrees with media')
                elif fingerprint(local) != {'sha256': digest, 'size': size}:
                    raise BackupError('Original differs from receipt')
    return counts


def verify_backup(root):
    root = directory(root)
    marker = root / 'manifest.json'
    if regular(marker).st_mode & 0o077:
        raise BackupError('Backup manifest is not private')
    manifest = json.loads(marker.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or manifest.get('format') != 1:
        raise BackupError('Unsupported backup manifest')
    files = inventory(root)
    if files != manifest.get('files'):
        raise BackupError('Backup inventory or digest mismatch')
    required = {'config/config.toml', 'config/.env', 'state/events.sqlite3'}
    if not required <= files.keys() or any(
            name not in required and not name.startswith('state/media/') for name in files):
        raise BackupError('Unexpected backup layout')
    original_media = Path(manifest['original_media'])
    if not original_media.is_absolute() or '..' in original_media.parts:
        raise BackupError('Invalid original media root')
    counts = check_state(root / 'state/events.sqlite3', directory(root / 'state/media'), original_media)
    if counts != manifest.get('event_counts'):
        raise BackupError('Backup event counts disagree')
    return manifest


def finalize_backup(destination, media):
    """Verify a private completed payload and publish its integrity manifest."""
    counts = check_state(destination / 'state/events.sqlite3',
                         destination / 'state/media', media)
    manifest = {'format': 1, 'original_media': str(media),
                'event_counts': counts, 'files': inventory(destination)}
    marker = destination / 'manifest.json'
    temporary = destination / '.manifest.pending'
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(manifest, stream, sort_keys=True, indent=2)
            stream.write('\n')
        os.replace(temporary, marker)
        verify_backup(destination)
    except BaseException:
        marker.unlink(missing_ok=True)
        raise
    return counts


@contextmanager
def locked_backup(config, state, destination):
    """Create a verified backup and retain the queue lock through the caller's checks.

    Same-owner development paths only. All writers must already be stopped.
    Do not call another queue-locking helper from inside this context.
    """
    config, state = directory(config), directory(state)
    destination = new_destination(destination)
    disjoint(config, state, destination)
    db, media = state / 'events.sqlite3', directory(state / 'media')
    regular(db)
    with queue_lock(db):
        destination.mkdir(mode=0o700)
        (destination / 'config').mkdir(mode=0o700)
        (destination / 'state').mkdir(mode=0o700)
        for name in ('config.toml', '.env'):
            if name == '.env' and regular(config / name).st_mode & 0o077:
                raise BackupError('Credential file is not private')
            copy_file(config / name, destination / 'config' / name)
        snapshot(db, destination / 'state/events.sqlite3')
        copy_tree(media, destination / 'state/media')
        counts = finalize_backup(destination, media)
        yield counts


def create_backup(config, state, destination):
    with locked_backup(config, state, destination) as counts:
        return counts


def rehearse(backup, destination):
    backup = directory(backup)
    destination = new_destination(destination)
    disjoint(backup, destination)
    manifest = verify_backup(backup)
    # Do not expose a runnable config, credential file, activation marker or
    # queue at the production path. The DB retains original absolute paths.
    destination.mkdir(mode=0o700)
    copy_file(backup / 'state/events.sqlite3', destination / 'events.sqlite3.inert')
    copy_tree(backup / 'state/media', destination / 'media')
    expected = {'events.sqlite3.inert': manifest['files']['state/events.sqlite3']}
    expected.update({name.removeprefix('state/'): digest
                     for name, digest in manifest['files'].items()
                     if name.startswith('state/media/')})
    if inventory(destination) != expected:
        raise BackupError('Rehearsal copy differs from backup')
    counts = check_state(destination / 'events.sqlite3.inert',
                         destination / 'media', Path(manifest['original_media']))
    if counts != manifest['event_counts']:
        raise BackupError('Rehearsal counts disagree')
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    for flag in ('config', 'state', 'destination'):
        create.add_argument('--' + flag, required=True, type=Path)
    verify = sub.add_parser('verify')
    verify.add_argument('--backup', required=True, type=Path)
    restore = sub.add_parser('rehearse')
    restore.add_argument('--backup', required=True, type=Path)
    restore.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Development backup tools must not run as root')
    os.umask(0o077)
    try:
        if args.command == 'create':
            counts = create_backup(args.config, args.state, args.destination)
        elif args.command == 'verify':
            counts = verify_backup(args.backup)['event_counts']
        else:
            counts = rehearse(args.backup, args.destination)
    except (OSError, ValueError, sqlite3.Error, KeyError, TypeError) as exc:
        print(f'Backup check failed ({type(exc).__name__}); no activation performed.', file=sys.stderr)
        return 1
    print('Backup check passed; event counts: ' + json.dumps(counts, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
