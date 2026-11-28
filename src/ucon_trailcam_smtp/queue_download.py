"""Explicit, bounded original-photo batch test; no SMTP or automatic retries."""
import fcntl
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path

from ucon_trailcam_smtp.event_match import match_events
from ucon_trailcam_smtp.download_attempts import register_attempt


@contextmanager
def batch_lock(path):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError('Test queue does not exist')
    with os.fdopen(os.open(str(path) + '.lock', os.O_CREAT | os.O_RDWR, 0o600), 'r+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def load_rows(path, uid, begin, end):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        return db.execute('SELECT itemid,et_utc,state,metadata_json FROM events '
                          'WHERE camera_uid=? AND et_utc>=? AND et_utc<? ORDER BY et_utc,itemid',
                          (uid, begin - 4, end + 4)).fetchall()


def eligible(row, begin, end):
    _, stamp, state, raw = row
    kind = json.loads(raw).get('type')
    return begin <= stamp < end and state == 'pending' and type(kind) is int and kind == 1


def digest_file(path, validate):
    with Path(path).open('rb') as source:
        data = source.read(16 * 1024 * 1024 + 1)
    if len(data) > 16 * 1024 * 1024:
        raise ValueError('Original exceeds size limit')
    ext, width, height = validate(data)
    if ext != 'jpg':
        raise ValueError('Original is not a JPEG')
    return hashlib.sha256(data).hexdigest(), len(data), width, height


def check_existing(path, uid, rows, begin, end, validate):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as db:
        for ident, stamp, state, _ in rows:
            if begin <= stamp < end and state == 'downloaded':
                receipt = db.execute('SELECT path,sha256,size,width,height FROM downloads '
                                     'WHERE camera_uid=? AND itemid=?', (uid, ident)).fetchone()
                if receipt is None or digest_file(receipt[0], validate) != tuple(receipt[1:]):
                    raise ValueError('Stored original missing or changed; manual repair required')


def record_download(path, uid, ident, stamp, sd, dest, details, *, attempt=None):
    with closing(sqlite3.connect(path, timeout=10)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS downloads (
            camera_uid TEXT NOT NULL, itemid TEXT NOT NULL, sd_time INTEGER NOT NULL,
            path TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL,
            width INTEGER NOT NULL, height INTEGER NOT NULL,
            PRIMARY KEY(camera_uid,itemid), UNIQUE(camera_uid,sd_time))''')
        cur = db.execute("UPDATE events SET state='downloaded' WHERE camera_uid=? "
                         "AND itemid=? AND et_utc=? AND state='pending'", (uid, ident, stamp))
        if cur.rowcount != 1:
            raise ValueError('Queue entry changed during download')
        db.execute('INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?)',
                   (uid, ident, sd, str(dest.resolve()), *details))
        if attempt is not None:
            if dest.resolve().parent != attempt:
                raise ValueError('Original is outside its registered attempt')
            cur = db.execute('DELETE FROM download_attempts WHERE path=? AND camera_uid=? AND itemid=?',
                             (str(attempt), uid, ident))
            if cur.rowcount != 1:
                raise ValueError('Missing registered download attempt')


def download_batch(session, path, uid, rows, begin, end, events, output, limit, download, validate,
                   *, retry_ids=None, on_failure=None):
    results = match_events([r[1] for r in rows], events)
    pending = [(r, m) for r, m in zip(rows, results) if eligible(r, begin, end)]
    if retry_ids is not None:
        rank = {ident: i for i, ident in enumerate(retry_ids)}
        pending = sorted(((r, m) for r, m in pending if r[0] in rank), key=lambda pair: rank[pair[0][0]])
    if on_failure is not None:
        for r, m in pending:
            if m[1] != 'matched':
                on_failure(r[0], m[1])
    selected = [(r, m) for r, m in pending if m[1] == 'matched'][:limit]
    missing = sum(m[1] != 'matched' for r, m in pending)
    completed = 0
    for (ident, stamp, _, _), (_, _, sd) in selected:
        event, = [e for e in events if e.start_time == sd and e.event_type == 4 and e.length == 65535]
        key = hashlib.sha256(json.dumps([uid, ident]).encode()).hexdigest()
        root = Path(output).resolve()
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        folder = root / key
        folder.mkdir(mode=0o700, exist_ok=True)
        attempt = Path(tempfile.mkdtemp(prefix='attempt-', dir=folder))
        # A unique attempt directory prevents overwrite after interruption.
        register_attempt(path, uid, ident, attempt)
        try:
            dest = download(session, event, 3, attempt / f'event4_{sd}_original.jpg',
                            preserve_filename=True)
        except TimeoutError:
            if on_failure is not None:
                on_failure(ident, 'download_timeout')
            raise
        details = digest_file(dest, validate)
        record_download(path, uid, ident, stamp, sd, dest, details, attempt=attempt)
        completed += 1
        session.stage_notes.append(f'Queue original committed: cloud={stamp}, SD={sd}, '
                                   f'{details[2]}x{details[3]}, {details[1]} bytes')
    session.stage_notes.append(f'Batch: downloaded={completed}, unmatched={missing}, '
                               f'deferred={len(pending)-missing-completed}; no SMTP.')
    return missing
