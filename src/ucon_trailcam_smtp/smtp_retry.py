"""Persistent per-camera cooldown and transactional rollback of proven unsent mail."""


def table_exists(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def retry_due(db, uid, now):
    if not table_exists(db, 'smtp_retries'):
        return True
    row = db.execute('SELECT next_due FROM smtp_retries WHERE camera_uid=?', (uid,)).fetchone()
    return row is None or now >= row[0]


def rollback_unsent(db, rows, message_id, now):
    """Caller proved no submission. Never use this for an ambiguous send result."""
    uid = rows[0][0]
    if any(row[0] != uid for row in rows):
        raise ValueError('Mixed SMTP retry batch')
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS smtp_retries (
            camera_uid TEXT PRIMARY KEY, failures INTEGER NOT NULL,
            last_failure INTEGER NOT NULL, next_due INTEGER NOT NULL)''')
        previous = db.execute('SELECT failures FROM smtp_retries WHERE camera_uid=?', (uid,)).fetchone()
        failures = (previous[0] if previous else 0) + 1
        delay = min(3600, 300 * 2 ** min(failures - 1, 10))
        for row in rows:
            camera, ident, stamp = row[:3]
            receipt = db.execute('DELETE FROM deliveries WHERE camera_uid=? AND itemid=? '
                                 'AND message_id=? AND accepted_utc IS NULL', (camera, ident, message_id))
            state = db.execute("UPDATE events SET state='downloaded' WHERE camera_uid=? AND itemid=? "
                               "AND et_utc=? AND state='uncertain'", (camera, ident, stamp))
            if receipt.rowcount != 1 or state.rowcount != 1:
                raise ValueError('Cannot safely restore unsent delivery')
            if table_exists(db, 'delivery_routes'):
                db.execute('DELETE FROM delivery_routes WHERE camera_uid=? AND itemid=?', (camera, ident))
        db.execute('INSERT OR REPLACE INTO smtp_retries VALUES (?,?,?,?)', (uid, failures, now, now + delay))
    return delay


def record_setup_failure(db, uid, now):
    """Shared camera cooldown for a proven pre-submission historical failure."""
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS smtp_retries (
            camera_uid TEXT PRIMARY KEY, failures INTEGER NOT NULL,
            last_failure INTEGER NOT NULL, next_due INTEGER NOT NULL)''')
        prior = db.execute('SELECT failures FROM smtp_retries WHERE camera_uid=?',(uid,)).fetchone()
        failures = (prior[0] if prior else 0)+1
        delay = min(3600,300*2**min(failures-1,10))
        db.execute('INSERT OR REPLACE INTO smtp_retries VALUES (?,?,?,?)',(uid,failures,now,now+delay))
    return delay


def clear_retry(db, uid):
    if table_exists(db, 'smtp_retries'):
        with db:
            db.execute('DELETE FROM smtp_retries WHERE camera_uid=?', (uid,))
