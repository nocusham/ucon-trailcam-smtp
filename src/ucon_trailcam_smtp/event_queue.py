"""Persistent, discovery-only event queue; no download or delivery worker."""
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from ucon_trailcam_smtp.event_metadata import event_metadata


class QueueError(Exception):
    pass


def open_queue(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(fd)
    db = sqlite3.connect(path, timeout=10)
    try:
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS events (
                camera_uid TEXT NOT NULL,
                itemid TEXT NOT NULL,
                et_utc INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY (camera_uid, itemid)
            )''')
        return db
    except Exception:
        db.close()
        raise


def ingest_events(path, uid, items):
    """Store only matching, valid events; never reset existing state."""
    added = known = rejected = 0
    with closing(open_queue(path)) as db, db:
        # Serialize writers before checking identity.
        db.execute('BEGIN IMMEDIATE')
        for item in items:
            if not isinstance(item, dict) or item.get('uid', item.get('device_uid')) != uid:
                rejected += 1
                continue
            ident, stamp = item.get('itemid'), item.get('et_utc')
            if (not isinstance(ident, str) or not ident.strip() or len(ident) > 512
                    or type(stamp) is not int or not 0 < stamp <= 4102444800):
                rejected += 1
                continue
            try:
                metadata = json.dumps(event_metadata(item), ensure_ascii=False, allow_nan=False)
            except (ValueError, TypeError):
                rejected += 1
                continue
            if len(metadata.encode('utf-8')) > 1_048_576:
                rejected += 1
                continue
            previous = db.execute('SELECT et_utc FROM events WHERE camera_uid=? AND itemid=?',
                                  (uid, ident)).fetchone()
            if previous is not None:
                if previous[0] != stamp:
                    raise QueueError('Event ID reused with a different timestamp; batch rolled back')
                known += 1
                continue
            db.execute('INSERT INTO events (camera_uid,itemid,et_utc,metadata_json) VALUES (?,?,?,?)',
                       (uid, ident, stamp, metadata))
            added += 1
        pending = db.execute("SELECT count(*) FROM events WHERE camera_uid=? AND state='pending'",
                             (uid,)).fetchone()[0]
    return added, known, rejected, pending
