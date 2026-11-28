"""Historical delivery evidence, independent of the original automatic receipt.

All writes require the existing queue lock. A reservation is uncertain
until confirmed accepted or proven not submitted.
"""
import json


def exists(db):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='historical_deliveries'").fetchone() is not None


def exclusion(db, alias, *, uncertain_only=False):
    if not exists(db):
        return ''
    return (' AND NOT EXISTS (SELECT 1 FROM historical_deliveries hd WHERE '
            f'hd.camera_uid={alias}.camera_uid AND hd.itemid={alias}.itemid'
            + (' AND hd.accepted_utc IS NULL' if uncertain_only else '') + ')')


def protected(db, uid, ident):
    return exists(db) and db.execute('SELECT 1 FROM historical_deliveries WHERE camera_uid=? '
                                     'AND itemid=? LIMIT 1', (uid,ident)).fetchone() is not None


def camera_uncertain(db, uid):
    return exists(db) and db.execute('SELECT 1 FROM historical_deliveries WHERE camera_uid=? '
                                     'AND accepted_utc IS NULL LIMIT 1', (uid,)).fetchone() is not None


def event_uncertain(db, uid, ident):
    return exists(db) and db.execute('SELECT 1 FROM historical_deliveries WHERE camera_uid=? '
                                     'AND itemid=? AND accepted_utc IS NULL LIMIT 1',(uid,ident)).fetchone() is not None


def observations(db, uid, begin, end):
    if not exists(db):
        return {}
    rows = db.execute('SELECT itemid,et_utc,accepted_utc,metadata_json FROM historical_deliveries '
                      'WHERE camera_uid=? AND et_utc>=? AND et_utc<? ORDER BY started_utc,message_id',
                      (uid,begin,end))
    result = {}
    for ident,stamp,accepted,raw in rows:
        previous = result.get(ident)
        if previous and previous[0]!=stamp:
            raise ValueError('Historical receipt identity conflict')
        state = 'uncertain' if accepted is None or (previous and previous[1]=='uncertain') else 'sent_history'
        result[ident]=(stamp,state,raw)
    return result


def reserve(db, uid, records, message_id, now, route, *, resend=False, allow_unknown=False):
    """Reserve a single message's verified records before SMTP, atomically."""
    if not records or not message_id or type(now) is not int or now<=0:
        raise ValueError('Invalid historical message reservation')
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS historical_deliveries (
            camera_uid TEXT NOT NULL, itemid TEXT NOT NULL, message_id TEXT NOT NULL,
            et_utc INTEGER NOT NULL, started_utc INTEGER NOT NULL, accepted_utc INTEGER,
            metadata_json TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
            size INTEGER NOT NULL, route_json TEXT NOT NULL,
            PRIMARY KEY(camera_uid,itemid,message_id))''')
        if camera_uncertain(db,uid) or db.execute(
                "SELECT 1 FROM events WHERE camera_uid=? AND state='uncertain' LIMIT 1",(uid,)).fetchone():
            raise ValueError('Camera has unresolved SMTP outcome')
        for rec in records:
            ident,stamp = rec['itemid'],rec['et_utc']
            if rec['camera_uid']!=uid or type(stamp) is not int or stamp<=0:
                raise ValueError('Historical message identity mismatch')
            event = db.execute('SELECT et_utc,state FROM events WHERE camera_uid=? AND itemid=?',
                               (uid,ident)).fetchone()
            prior = db.execute('SELECT et_utc FROM historical_deliveries WHERE camera_uid=? AND itemid=?',
                               (uid,ident)).fetchall()
            if (event and event[0]!=stamp) or any(p[0]!=stamp for p in prior):
                raise ValueError('Historical event timestamp conflict')
            accepted = None
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='deliveries'").fetchone():
                accepted = db.execute('SELECT accepted_utc FROM deliveries WHERE camera_uid=? AND itemid=?',
                                      (uid,ident)).fetchone()
            if accepted is not None and (type(accepted[0]) is not int or accepted[0]<=0):
                raise ValueError('Unresolved original SMTP receipt')
            known = bool(prior or accepted or (event and event[1] in ('sent','sent_history','sent_manual')))
            if known and not resend:
                raise ValueError('Known prior delivery requires --resend')
            if not known and event is None and not allow_unknown:
                raise ValueError('Unknown prior delivery requires --allow-unknown-history')
            if event and event[1] not in ('pending','downloaded','expired','sent','sent_history','sent_manual'):
                raise ValueError('Unexpected original event state')
            db.execute('INSERT INTO historical_deliveries VALUES (?,?,?,?,?,NULL,?,?,?,?,?)',
                       (uid,ident,message_id,stamp,now,json.dumps(rec['metadata'],ensure_ascii=False,allow_nan=False),
                        rec['path'],rec['sha256'],rec['size'],json.dumps(route,ensure_ascii=False,allow_nan=False)))


def finish(db, uid, message_id, now, count):
    if type(now) is not int or now<=0 or count<1:
        raise ValueError('Invalid historical acceptance')
    with db:
        db.execute('BEGIN IMMEDIATE')
        cur = db.execute('UPDATE historical_deliveries SET accepted_utc=? WHERE camera_uid=? '
                         'AND message_id=? AND accepted_utc IS NULL',(now,uid,message_id))
        if cur.rowcount!=count:
            raise ValueError('Historical receipt acceptance mismatch')


def rollback_unsent(db, uid, message_id, count):
    """Only call after transport proves the message was never submitted."""
    if count<1:
        raise ValueError('Invalid historical rollback')
    with db:
        db.execute('BEGIN IMMEDIATE')
        cur = db.execute('DELETE FROM historical_deliveries WHERE camera_uid=? AND message_id=? '
                         'AND accepted_utc IS NULL',(uid,message_id))
        if cur.rowcount!=count:
            raise ValueError('Historical receipt rollback mismatch')
