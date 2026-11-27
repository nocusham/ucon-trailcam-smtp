"""Remove only receipt-verified, SMTP-accepted local originals under a managed root."""
import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import ExitStack, closing
from dataclasses import dataclass
from pathlib import Path
from safe_diagnostics import error_fields


@dataclass(frozen=True)
class Retention:
    enabled: bool = False
    days: int = 30


def parse_retention(raw):
    if raw is None:
        return Retention()
    if not isinstance(raw, dict) or set(raw) - {'enabled', 'days'}:
        raise ValueError('Invalid retention configuration')
    enabled, days = raw.get('enabled', False), raw.get('days', 30)
    if type(enabled) is not bool or type(days) is not int or not 1 <= days <= 3650:
        raise ValueError('Invalid retention options')
    return Retention(enabled, days)


def table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def candidates(db, cutoff):
    if not all(table_exists(db, t) for t in ('events', 'downloads', 'deliveries')):
        return []
    skip = (' AND NOT EXISTS (SELECT 1 FROM media_cleanup c WHERE c.camera_uid=e.camera_uid AND c.itemid=e.itemid)'
            if table_exists(db, 'media_cleanup') else '')
    return db.execute('''SELECT e.camera_uid,e.itemid,d.path,d.sha256,d.size
        FROM events e JOIN downloads d USING(camera_uid,itemid)
        JOIN deliveries s USING(camera_uid,itemid)
        WHERE e.state='sent' AND s.accepted_utc>0 AND s.accepted_utc<=?'''
        + skip + ' ORDER BY s.accepted_utc,e.camera_uid,e.itemid', (cutoff,)).fetchall()


def safe_directory(fd):
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Managed media directory not private to service owner')


def inspect_original(db, root, root_fd, row, *, apply, now):
    uid, ident, raw_path, digest, size = row
    key = hashlib.sha256(json.dumps([uid, ident]).encode()).hexdigest()
    path = Path(raw_path)
    rel = path.relative_to(root)
    if (len(rel.parts) != 3 or rel.parts[0] != key
            or not re.fullmatch(r'attempt-[A-Za-z0-9_-]+', rel.parts[1])
            or path.suffix.lower() not in ('.jpg', '.jpeg')
            or '..' in rel.parts or type(size) is not int or not 0 < size <= 16*1024*1024):
        raise ValueError('Unexpected managed media path or size')
    if db.execute('SELECT count(*) FROM downloads WHERE path=?', (raw_path,)).fetchone()[0] != 1:
        raise ValueError('Shared original path')
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        key_fd = os.open(key, directory_flags, dir_fd=root_fd)
        stack.callback(os.close, key_fd)
        safe_directory(key_fd)
        attempt_fd = os.open(rel.parts[1], directory_flags, dir_fd=key_fd)
        stack.callback(os.close, attempt_fd)
        safe_directory(attempt_fd)
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=attempt_fd)
        with os.fdopen(fd, 'rb') as source:
            info = os.fstat(source.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or info.st_size != size):
                raise ValueError('Unexpected original file identity')
            data = source.read(size+1)
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError('Original differs from receipt')
            current = os.stat(path.name, dir_fd=attempt_fd, follow_symlinks=False)
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                    info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
                raise ValueError('Original changed during verification')
            if apply:
                os.unlink(path.name, dir_fd=attempt_fd)
                with db:
                    db.execute('INSERT INTO media_cleanup VALUES (?,?,?,?)', (uid, ident, now, size))
        if apply:
            # Remove only empty, known attempt/key directories; never recurse.
            for name, parent in ((rel.parts[1], key_fd), (key, root_fd)):
                try:
                    os.rmdir(name, dir_fd=parent)
                except OSError:
                    pass
    return size


def cleanup(db, root, policy, now, *, apply=False, emit=print):
    if apply and not policy.enabled:
        raise ValueError('Enable retention explicitly before deleting files')
    rows = candidates(db, now - policy.days*86400)
    if not rows:
        emit('Retention: eligible=0; removed=0; no file changes.')
        return 0, 0, 0
    root = Path(root).resolve(strict=True)
    if apply:
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS media_cleanup (
                camera_uid TEXT NOT NULL,itemid TEXT NOT NULL,removed_utc INTEGER NOT NULL,
                size INTEGER NOT NULL,PRIMARY KEY(camera_uid,itemid))''')
    count = total = skipped = 0
    with ExitStack() as stack:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, root_fd)
        safe_directory(root_fd)
        for row in rows:
            if count >= 100:
                break
            try:
                size = inspect_original(db, root, root_fd, row, apply=apply, now=now)
            except (OSError, ValueError, TypeError) as exc:
                emit(f'Retention candidate skipped; {error_fields(exc)}.')
                skipped += 1
                continue
            count += 1
            total += size
    emit(f'Retention: {"removed" if apply else "would_remove"}={count}, bytes={total}, skipped={skipped}; receipts retained.')
    return count, total, skipped


def main():
    import tomllib
    from queue_download import batch_lock
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--queue-db', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true', help='Actually remove eligible files')
    args = parser.parse_args()
    try:
        with args.config.open('rb') as source:
            policy = parse_retention(tomllib.load(source).get('retention'))
        with batch_lock(args.queue_db), closing(sqlite3.connect(
                args.queue_db.resolve().as_uri() + ('?mode=rw' if args.apply else '?mode=ro'), uri=True)) as db:
            _, _, skipped = cleanup(db, args.output_dir, policy, int(time.time()), apply=args.apply)
        return int(bool(skipped))
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Retention stopped; {error_fields(exc)}.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
