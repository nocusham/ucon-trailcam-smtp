"""Persistent scheduling of explicit, known original-photo download attempts."""
import json
from dataclasses import dataclass

from ucon_trailcam_smtp.health_alerts import init_health, observe
from ucon_trailcam_smtp.history_receipts import protected, exclusion


@dataclass(frozen=True)
class RetryPolicy:
    initial_minutes: int = 5
    max_minutes: int = 360

    def delay(self, failures):
        return 60 * min(self.max_minutes, self.initial_minutes * 2 ** min(failures, 30))


def parse_retry(raw):
    if raw is None:
        return RetryPolicy()
    if not isinstance(raw, dict) or set(raw) - {'initial_minutes', 'max_minutes'}:
        raise ValueError('Invalid download retry configuration')
    initial, maximum = raw.get('initial_minutes', 5), raw.get('max_minutes', 360)
    if (type(initial) is not int or type(maximum) is not int
            or not 1 <= initial <= maximum <= 1440):
        raise ValueError('Invalid download retry interval')
    return RetryPolicy(initial, maximum)


def init_retry(db):
    init_health(db)
    with db:
        db.execute('''CREATE TABLE IF NOT EXISTS download_retries (
            camera_uid TEXT NOT NULL, itemid TEXT NOT NULL,
            last_attempt INTEGER NOT NULL, next_due INTEGER NOT NULL,
            failures INTEGER NOT NULL DEFAULT 0, first_failure INTEGER,
            last_failure INTEGER, failed_attempt INTEGER, reason TEXT,
            PRIMARY KEY(camera_uid,itemid))''')


def pending_photo(row, begin, end):
    ident, stamp, state, raw = row
    kind = json.loads(raw).get('type')
    return state == 'pending' and begin <= stamp < end and type(kind) is int and kind == 1


def due_ids(db, uid, rows, begin, end, now, limit):
    """Fair order by due time, then capture time; never select nonpending rows."""
    retries = dict(db.execute('SELECT itemid,next_due FROM download_retries WHERE camera_uid=?', (uid,)))
    candidates = [(retries.get(r[0], r[1]), r[1], r[0]) for r in rows
                  if pending_photo(r, begin, end) and retries.get(r[0], r[1]) <= now
                  and not protected(db,uid,r[0])]
    return [ident for _, _, ident in sorted(candidates)[:limit]]


def reserve(db, uid, ids, now, policy):
    """Persist cooldown before network; reservation alone is not a failure."""
    with db:
        db.execute('BEGIN IMMEDIATE')
        for ident in ids:
            row = db.execute('SELECT et_utc,state,metadata_json FROM events WHERE camera_uid=? AND itemid=?',
                             (uid, ident)).fetchone()
            if row is None or not pending_photo((ident, *row), 0, now + 1) or protected(db,uid,ident):
                raise ValueError('Retry selection changed')
            previous = db.execute('SELECT next_due,failures FROM download_retries WHERE camera_uid=? AND itemid=?',
                                  (uid, ident)).fetchone()
            if previous is not None and previous[0] > now:
                raise ValueError('Download not due')
            delay = policy.delay(previous[1] if previous else 0)
            db.execute('''INSERT INTO download_retries (camera_uid,itemid,last_attempt,next_due)
                VALUES (?,?,?,?) ON CONFLICT(camera_uid,itemid) DO UPDATE SET
                last_attempt=excluded.last_attempt,next_due=excluded.next_due''',
                       (uid, ident, now, now + delay))


def record_failure(db, uid, ident, now, reason, policy):
    """Only a real remote/list/match failure, once per reserved attempt."""
    if reason not in ('relay_timeout', 'missing', 'ambiguous', 'download_timeout'):
        raise ValueError('Unknown download failure reason')
    with db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('''SELECT r.last_attempt,r.failures,r.failed_attempt,e.state
            FROM download_retries r JOIN events e USING(camera_uid,itemid)
            WHERE r.camera_uid=? AND r.itemid=?''', (uid, ident)).fetchone()
        if row is None or row[3] != 'pending' or now < row[0] or row[2] == row[0]:
            raise ValueError('No outstanding reserved download attempt')
        db.execute('''UPDATE download_retries SET failures=failures+1,
            first_failure=COALESCE(first_failure,?),last_failure=?,failed_attempt=last_attempt,
            next_due=?,reason=? WHERE camera_uid=? AND itemid=?''',
                   (now, now, now + policy.delay(row[1]), reason, uid, ident))


def sync_download_health(db, uid, now, threshold):
    """Project failed pending originals into the existing per-camera alarm state.

    At least one individual event must span the threshold. A later successful
    photo cannot clear an older failed pending original. Resolved receipts are
    retained for audit but do not participate in the alarm.
    """
    rows = db.execute('''SELECT r.first_failure,r.last_failure,r.failures
        FROM download_retries r JOIN events e USING(camera_uid,itemid)
        WHERE r.camera_uid=? AND e.state='pending' AND r.failures>0''' + exclusion(db,'e'), (uid,)).fetchall()
    if not rows:
        observe(db, 'camera', uid, healthy=True, now=now)
        return
    qualifying = [r for r in rows if r[2] >= 2 and r[1] - r[0] >= threshold]
    if not qualifying:
        return
    first = min(r[0] for r in qualifying)
    last = max(r[1] for r in qualifying)
    count = sum(r[2] for r in qualifying)
    with db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute("SELECT recovered_at FROM health_incidents WHERE category='camera' AND scope=?", (uid,)).fetchone()
        if old is None or old[0] is not None:
            db.execute("INSERT OR REPLACE INTO health_incidents VALUES ('camera',?,?,?,?,NULL,0,NULL,NULL,NULL)",
                       (uid, first, last, count))
        else:
            db.execute("UPDATE health_incidents SET first_failure=MIN(first_failure,?),"
                       "last_failure=MAX(last_failure,?),failures=MAX(failures,?) WHERE category='camera' AND scope=?",
                       (first, last, count, uid))
