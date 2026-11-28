"""Remove verified accepted and expired definitely unsent local originals."""
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
from ucon_trailcam_smtp.safe_diagnostics import error_fields


@dataclass(frozen=True)
class Retention:
    enabled: bool = True
    days: int = 1  # Legacy day-based configuration.
    automatic_days: int = 90
    sent_image_hours: int | None = None
    metadata_days: int = 90
    delivery_receipt_days: int = 90
    incomplete_days: int = 7

    @property
    def image_seconds(self):
        return self.sent_image_hours * 3600 if self.sent_image_hours is not None else self.days * 86400


def parse_retention(raw):
    if raw is None:
        return Retention()
    if not isinstance(raw, dict) or set(raw) - {'enabled', 'days', 'automatic_days', 'sent_image_hours',
                                                     'metadata_days', 'delivery_receipt_days', 'incomplete_days'}:
        raise ValueError('Invalid retention configuration')
    enabled, days = raw.get('enabled', True), raw.get('days', 1)
    if type(enabled) is not bool or type(days) is not int or not 1 <= days <= 3650:
        raise ValueError('Invalid retention options')
    automatic_days = raw.get('automatic_days', 90)
    if type(automatic_days) is not int or not 1 <= automatic_days <= 3650:
        raise ValueError('Invalid automatic image age limit')
    hours = raw.get('sent_image_hours')
    if 'sent_image_hours' in raw and ('days' in raw or type(hours) is not int or not 1 <= hours <= 87600):
        raise ValueError('Invalid sent image hours or conflicting legacy days')
    metadata_days = raw.get('metadata_days', 90)
    receipt_days = raw.get('delivery_receipt_days', 90)
    incomplete_days = raw.get('incomplete_days', 7)
    if any(type(v) is not int or not 1 <= v <= 3650 for v in (metadata_days, receipt_days, incomplete_days)):
        raise ValueError('Invalid metadata, delivery receipt or incomplete attempt retention days')
    return Retention(enabled, days, automatic_days, hours, metadata_days, receipt_days, incomplete_days)


def capture_cutoff(now, automatic_days=90):
    """Inclusive lower capture-time bound for automatic processing."""
    if type(now) is not int or now < 0 or type(automatic_days) is not int or not 1 <= automatic_days <= 3650:
        raise ValueError('Invalid automatic capture window')
    return max(0, now - automatic_days * 86400)


def table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def candidates(db, cutoff):
    if not all(table_exists(db, t) for t in ('events', 'downloads', 'deliveries')):
        return []
    has_cleanup = table_exists(db, 'media_cleanup')
    join = (' LEFT JOIN media_cleanup c USING(camera_uid,itemid)' if has_cleanup else '')
    # A verified pending deletion must be reconciled even if the user
    # has subsequently increased the retention interval.
    age = ('((c.itemid IS NULL AND s.accepted_utc<=?) OR c.removed_utc=0)'
           if has_cleanup else 's.accepted_utc<=?')
    return db.execute('''SELECT e.camera_uid,e.itemid,d.path,d.sha256,d.size
        FROM events e JOIN downloads d USING(camera_uid,itemid)
        JOIN deliveries s USING(camera_uid,itemid)'''
        + join + " WHERE e.state='sent' AND s.accepted_utc>0 AND " + age
        + ' ORDER BY s.accepted_utc,e.camera_uid,e.itemid', (cutoff,)).fetchall()


def no_receipt(db, table, alias='e'):
    if not table_exists(db, table):
        return ''
    return (f' AND NOT EXISTS (SELECT 1 FROM {table} x WHERE '
            f'x.camera_uid={alias}.camera_uid AND x.itemid={alias}.itemid)')


def expired_candidates(db, cutoff):
    if not table_exists(db, 'downloads'):
        return []
    has_cleanup = table_exists(db, 'media_cleanup')
    join = ' LEFT JOIN media_cleanup c USING(camera_uid,itemid)' if has_cleanup else ''
    selection = ("((e.state='downloaded' AND e.et_utc<? AND c.itemid IS NULL) "
                 "OR (e.state='expired' AND c.removed_utc=0))" if has_cleanup
                 else "e.state='downloaded' AND e.et_utc<?")
    return db.execute('SELECT e.camera_uid,e.itemid,d.path,d.sha256,d.size '
                      'FROM events e JOIN downloads d USING(camera_uid,itemid)' + join
                      + ' WHERE ' + selection + no_receipt(db, 'deliveries')
                      + no_receipt(db, 'delivery_routes')
                      + ' ORDER BY e.et_utc,e.camera_uid,e.itemid', (cutoff,)).fetchall()


def expire_pending(db, cutoff, *, apply):
    # Retain metadata for later independent pruning. A pending event must
    # have no original or delivery receipt, including contradictory state.
    selection = ("e.state='pending' AND e.et_utc<?" + no_receipt(db, 'downloads')
                 + no_receipt(db, 'deliveries') + no_receipt(db, 'delivery_routes')
                 + no_receipt(db, 'media_cleanup'))
    rows = db.execute('SELECT e.camera_uid,e.itemid FROM events e WHERE ' + selection
                      + ' ORDER BY e.et_utc,e.camera_uid,e.itemid LIMIT 100', (cutoff,)).fetchall()
    if not apply:
        return len(rows)
    with db:
        db.execute('BEGIN IMMEDIATE')
        for uid, ident in rows:
            cur = db.execute("UPDATE events AS e SET state='expired' WHERE e.camera_uid=? "
                             "AND e.itemid=? AND " + selection, (uid, ident, cutoff))
            if cur.rowcount != 1:
                raise ValueError('Expired pending selection changed')
            discard_expired_retry(db, uid, ident)
    return len(rows)


def discard_expired_retry(db, uid, ident):
    if not table_exists(db, 'download_retries'):
        return
    failed = db.execute('SELECT failures FROM download_retries WHERE camera_uid=? AND itemid=?',
                        (uid, ident)).fetchone()
    db.execute('DELETE FROM download_retries WHERE camera_uid=? AND itemid=?', (uid, ident))
    if failed and failed[0] > 0 and table_exists(db, 'health_incidents'):
        # Expiration is not evidence that the camera recovered.
        remaining = db.execute("""SELECT 1 FROM download_retries r JOIN events e USING(camera_uid,itemid)
            WHERE e.camera_uid=? AND e.state='pending' AND r.failures>0 LIMIT 1""", (uid,)).fetchone()
        if remaining is None:
            db.execute("DELETE FROM health_incidents WHERE category='camera' AND scope=?", (uid,))


def deletion_intent(db, uid, ident, size):
    if not table_exists(db, 'media_cleanup'):
        return False
    row = db.execute('SELECT removed_utc,size FROM media_cleanup WHERE camera_uid=? AND itemid=?',
                     (uid, ident)).fetchone()
    if row is None:
        return False
    if row != (0, size):
        raise ValueError('Unexpected cleanup receipt')
    return True


def finish_cleanup(db, uid, ident, now, size):
    with db:
        cur = db.execute('UPDATE media_cleanup SET removed_utc=? WHERE camera_uid=? AND itemid=? '
                         'AND removed_utc=0 AND size=?', (now, uid, ident, size))
        if cur.rowcount != 1:
            raise ValueError('Missing verified deletion intent')


def safe_directory(fd):
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError('Managed media directory not private to service owner')


def inspect_original(db, root, root_fd, row, *, apply, now, expire=False):
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
    pending = deletion_intent(db, uid, ident, size)
    directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as stack:
        key_fd = os.open(key, directory_flags, dir_fd=root_fd)
        stack.callback(os.close, key_fd)
        safe_directory(key_fd)
        attempt_fd = os.open(rel.parts[1], directory_flags, dir_fd=key_fd)
        stack.callback(os.close, attempt_fd)
        safe_directory(attempt_fd)
        try:
            fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=attempt_fd)
        except FileNotFoundError:
            if not pending:
                raise
            # The intent was committed after verifying the original, before
            # unlink. Only that exact missing path may be reconciled.
            if apply:
                os.fsync(attempt_fd)
                finish_cleanup(db, uid, ident, now, size)
        else:
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
                    if not pending:
                        with db:
                            db.execute('BEGIN IMMEDIATE')
                            if expire:
                                cur = db.execute("UPDATE events AS e SET state='expired' "
                                                 "WHERE e.camera_uid=? AND e.itemid=? AND e.state='downloaded'"
                                                 + no_receipt(db, 'deliveries') + no_receipt(db, 'delivery_routes'),
                                                 (uid, ident))
                                if cur.rowcount != 1:
                                    raise ValueError('Expired original selection changed')
                                discard_expired_retry(db, uid, ident)
                            db.execute('INSERT INTO media_cleanup VALUES (?,?,0,?)', (uid, ident, size))
                    os.unlink(path.name, dir_fd=attempt_fd)
                    os.fsync(attempt_fd)
                    finish_cleanup(db, uid, ident, now, size)
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
    if type(now) is not int or now <= 0:
        raise ValueError('Invalid cleanup timestamp')
    cutoff = capture_cutoff(now, policy.automatic_days)
    pending_count = expire_pending(db, cutoff, apply=apply)
    emit(f'Retention: expired_pending={pending_count}; apply={apply}.')
    rows = [(row, False) for row in candidates(db, now - policy.image_seconds)]
    # Finish interrupted expired deletions and process expired unsent originals.
    rows += [(row, True) for row in expired_candidates(db, cutoff)]
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
        for row, expire in rows:
            if count >= 100:
                break
            try:
                size = inspect_original(db, root, root_fd, row, apply=apply, now=now, expire=expire)
            except (OSError, ValueError, TypeError) as exc:
                emit(f'Retention candidate skipped; {error_fields(exc)}.')
                skipped += 1
                continue
            count += 1
            total += size
    emit(f'Retention: {"removed" if apply else "would_remove"}={count}, bytes={total}, skipped={skipped}; receipts retained.')
    return count, total, skipped


def prune_metadata(db, root, policy, now, *, apply=False, emit=print):
    """Prune only terminal, reconciled events, independently of media age.

    The caller holds the queue lock. A sent_history event is an explicit
    minimal known-success marker after detailed delivery receipts expire.
    """
    if apply and not policy.enabled:
        raise ValueError('Enable retention explicitly before pruning')
    if type(now) is not int or now <= 0:
        raise ValueError('Invalid cleanup timestamp')
    meta_cutoff = capture_cutoff(now, policy.metadata_days)
    auto_cutoff = capture_cutoff(now, policy.automatic_days)
    receipt_cutoff = now - policy.delivery_receipt_days * 86400
    root = Path(root).resolve()
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    related = tuple(t for t in ('deliveries', 'delivery_routes', 'downloads',
                                'media_cleanup', 'download_retries') if t in tables)

    def one(table, columns, uid, ident):
        if table not in tables:
            return None
        return db.execute(f'SELECT {columns} FROM {table} WHERE camera_uid=? AND itemid=?',
                          (uid, ident)).fetchone()

    def remove_related(uid, ident):
        for table in related:
            db.execute(f'DELETE FROM {table} WHERE camera_uid=? AND itemid=?', (uid, ident))

    def cleaned(uid, ident):
        original = one('downloads', 'path,size', uid, ident)
        removal = one('media_cleanup', 'removed_utc,size', uid, ident)
        if original is None or removal is None or removal[0] <= 0 or removal[1] != original[1]:
            return False
        try:
            path = Path(original[0])
            key = hashlib.sha256(json.dumps([uid, ident]).encode()).hexdigest()
            rel = path.relative_to(root)
            if (len(rel.parts) != 3 or rel.parts[0] != key or '..' in rel.parts
                    or not re.fullmatch(r'attempt-[A-Za-z0-9_-]+', rel.parts[1])
                    or path.suffix.lower() not in ('.jpg', '.jpeg')):
                return False
            # Never discard the last receipt of a file that still exists,
            # or of a path redirected through a symlink.
            for parent in (root / key, root / key / rel.parts[1]):
                if parent.is_symlink():
                    return False
            path.lstat()
        except FileNotFoundError:
            return True
        except (OSError, TypeError, ValueError):
            return False
        return False

    compacted = retired = deleted = 0
    with db:
        if apply:
            db.execute('BEGIN IMMEDIATE')
        rows = db.execute("""SELECT camera_uid,itemid,et_utc,state,metadata_json FROM events
            WHERE state IN ('sent','expired','sent_history')
            ORDER BY et_utc,camera_uid,itemid""").fetchall()
        for uid, ident, stamp, state, raw in rows:
            if compacted + retired + deleted >= 1000:
                break
            old_metadata = stamp <= meta_cutoff
            outside_auto = stamp < auto_cutoff
            delivery = one('deliveries', 'accepted_utc', uid, ident)
            if state == 'sent':
                if not delivery or type(delivery[0]) is not int or delivery[0] <= 0:
                    continue
                if not cleaned(uid, ident):
                    # Preserve full data until actual file cleanup completed.
                    continue
                old_receipt = delivery[0] <= receipt_cutoff
                if old_receipt:
                    if apply:
                        remove_related(uid, ident)
                    if old_metadata and outside_auto:
                        if apply:
                            db.execute('DELETE FROM events WHERE camera_uid=? AND itemid=?', (uid, ident))
                        deleted += 1
                        continue
                    if apply:
                        db.execute("UPDATE events SET state='sent_history' WHERE camera_uid=? AND itemid=?",
                                   (uid, ident))
                    retired += 1
            else:
                if delivery is not None or one('delivery_routes', 'itemid', uid, ident) is not None:
                    continue
                original = one('downloads', 'itemid', uid, ident)
                removal = one('media_cleanup', 'itemid', uid, ident)
                if state == 'sent_history' and (original is not None or removal is not None):
                    continue
                if original is not None:
                    if not cleaned(uid, ident):
                        continue
                elif removal is not None:
                    continue
                if old_metadata and outside_auto:
                    if apply:
                        remove_related(uid, ident)
                        db.execute('DELETE FROM events WHERE camera_uid=? AND itemid=?', (uid, ident))
                    deleted += 1
                    continue
            if old_metadata:
                metadata = json.loads(raw)
                if not isinstance(metadata, dict):
                    raise ValueError('Invalid retained event metadata')
                minimal = json.dumps({'itemid': ident, 'et_utc': stamp,
                                      'type': metadata.get('type')}, ensure_ascii=False, allow_nan=False)
                if raw != minimal:
                    if apply:
                        db.execute('UPDATE events SET metadata_json=? WHERE camera_uid=? AND itemid=?',
                                   (minimal, uid, ident))
                    compacted += 1
    emit(f'Retention metadata: compacted={compacted}, retired_receipts={retired}, '
         f'deleted_events={deleted}; apply={apply}.')
    return compacted, retired, deleted


def main():
    import tomllib
    from ucon_trailcam_smtp.queue_download import batch_lock
    from ucon_trailcam_smtp.download_attempts import cleanup_attempts
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
            now = int(time.time())
            _, _, skipped = cleanup(db, args.output_dir, policy, now, apply=args.apply)
            prune_metadata(db, args.output_dir, policy, now, apply=args.apply)
            _, attempt_skipped = cleanup_attempts(db, args.output_dir, now, policy.incomplete_days,
                                                  apply=args.apply)
            skipped += attempt_skipped
        return int(bool(skipped))
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Retention stopped; {error_fields(exc)}.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
