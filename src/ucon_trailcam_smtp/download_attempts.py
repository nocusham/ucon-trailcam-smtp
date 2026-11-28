"""Registry and cleanup of abandoned local download attempts."""
import hashlib
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import closing, ExitStack
from pathlib import Path

from ucon_trailcam_smtp.safe_diagnostics import error_fields


def register_attempt(db_path, uid, ident, attempt):
    """Commit ownership before transfer; caller holds the queue lock."""
    with closing(sqlite3.connect(db_path, timeout=10)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS download_attempts (
            path TEXT PRIMARY KEY, camera_uid TEXT NOT NULL, itemid TEXT NOT NULL,
            created_utc INTEGER NOT NULL)''')
        db.execute('INSERT INTO download_attempts VALUES (?,?,?,?)',
                   (str(attempt), uid, ident, int(time.time())))


def safe_directory(fd):
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Attempt directory is not owner-controlled')


def remove_attempt(root, root_fd, raw, uid, ident, cutoff, *, apply):
    rel = Path(raw).relative_to(root)
    key = hashlib.sha256(json.dumps([uid, ident]).encode()).hexdigest()
    if (len(rel.parts) != 2 or rel.parts[0] != key
            or not re.fullmatch(r'attempt-[A-Za-z0-9_-]+', rel.parts[1])):
        raise ValueError('Unexpected registered attempt path')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        try:
            key_fd = os.open(key, flags, dir_fd=root_fd)
        except FileNotFoundError:
            return True
        stack.callback(os.close, key_fd)
        safe_directory(key_fd)
        try:
            attempt_fd = os.open(rel.parts[1], flags, dir_fd=key_fd)
        except FileNotFoundError:
            return True
        stack.callback(os.close, attempt_fd)
        safe_directory(attempt_fd)
        if os.fstat(attempt_fd).st_mtime > cutoff:
            return False
        names = os.listdir(attempt_fd)
        if len(names) > 1 or any('..' in n or len(n) > 128 or not re.fullmatch(
                r'[A-Za-z0-9][A-Za-z0-9_.-]*\.(?i:jpg|jpeg)', n) for n in names):
            raise ValueError('Unexpected contents of registered attempt')
        for name in names:
            info = os.stat(name, dir_fd=attempt_fd, follow_symlinks=False)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or info.st_nlink != 1 or info.st_size > 16 * 1024 * 1024):
                raise ValueError('Unexpected incomplete file identity')
            if info.st_mtime > cutoff:
                return False
            if apply:
                current = os.stat(name, dir_fd=attempt_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                        info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
                    raise ValueError('Incomplete file changed during inspection')
                os.unlink(name, dir_fd=attempt_fd)
                os.fsync(attempt_fd)
        if apply:
            os.rmdir(rel.parts[1], dir_fd=key_fd)
            os.fsync(key_fd)
            try:
                os.rmdir(key, dir_fd=root_fd)
            except OSError:
                pass
    return True


def cleanup_attempts(db, root, now, days=7, *, apply=False, emit=print):
    """Only explicitly registered attempts; no guessing from folder names."""
    if type(days) is not int or not 1 <= days <= 3650 or type(now) is not int or now <= 0:
        raise ValueError('Invalid incomplete attempt retention')
    from ucon_trailcam_smtp.history_receipts import event_uncertain
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'download_attempts' not in tables:
        return 0, 0
    cutoff = now - days * 86400
    rows = db.execute('SELECT path,camera_uid,itemid FROM download_attempts '
                      'WHERE created_utc<=? ORDER BY created_utc,path', (cutoff,)).fetchall()
    if not rows:
        return 0, 0
    root = Path(root).resolve(strict=True)
    receipts = [Path(p) for p, in db.execute('SELECT path FROM downloads')] if 'downloads' in tables else []
    count = skipped = 0
    with ExitStack() as stack:
        root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, root_fd)
        safe_directory(root_fd)
        for raw, uid, ident in rows:
            if count >= 100:
                break
            try:
                if any(p.is_relative_to(Path(raw)) for p in receipts):
                    raise ValueError('Attempt contains a committed original')
                state = db.execute('SELECT state FROM events WHERE camera_uid=? AND itemid=?',
                                   (uid, ident)).fetchone()
                if state == ('uncertain',) or event_uncertain(db,uid,ident):
                    raise ValueError('Uncertain event protects its attempts')
                if 'deliveries' in tables and db.execute(
                        'SELECT 1 FROM deliveries WHERE camera_uid=? AND itemid=? AND accepted_utc IS NULL',
                        (uid, ident)).fetchone():
                    raise ValueError('Uncertain receipt protects its attempts')
                if not remove_attempt(root, root_fd, raw, uid, ident, cutoff, apply=apply):
                    continue
                if apply:
                    with db:
                        db.execute('DELETE FROM download_attempts WHERE path=?', (raw,))
            except (OSError, ValueError, TypeError) as exc:
                emit(f'Incomplete attempt skipped; {error_fields(exc)}.')
                skipped += 1
                continue
            count += 1
    emit(f'Incomplete attempts: {"removed" if apply else "would_remove"}={count}, skipped={skipped}.')
    return count, skipped
