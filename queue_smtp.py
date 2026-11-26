"""Explicit SMTP batch test for verified originals; no camera or cloud access."""
import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path
from zoneinfo import ZoneInfo


class DeliveryError(Exception):
    pass


def ready_rows(db, begin, end, limit):
    count, = db.execute("SELECT count(*) FROM events WHERE state='downloaded' "
                        'AND et_utc>=? AND et_utc<?', (begin, end)).fetchone()
    if not count:
        return []
    return db.execute('''SELECT e.camera_uid,e.itemid,e.et_utc,e.metadata_json,
                         d.sd_time,d.path,d.sha256,d.size,d.width,d.height
                         FROM events e LEFT JOIN downloads d
                         ON e.camera_uid=d.camera_uid AND e.itemid=d.itemid
                         WHERE e.state='downloaded' AND e.et_utc>=? AND e.et_utc<?
                         ORDER BY e.et_utc,e.camera_uid,e.itemid LIMIT ?''',
                      (begin, end, limit)).fetchall()


def prepare(row, load_image, build_message, sender, recipient):
    uid, ident, stamp, raw, sd, path, digest, size, width, height = row
    event = json.loads(raw)
    if (not isinstance(event, dict) or event.get('itemid') != ident
            or type(event.get('et_utc')) is not int or event['et_utc'] != stamp
            or type(event.get('type')) is not int or event['type'] != 1
            or type(sd) is not int or abs(sd - stamp) > 2 or not path):
        raise DeliveryError('Missing or inconsistent original receipt or event metadata')
    image = load_image(Path(path))
    data, ext, w, h, filename = image
    if (ext != 'jpg' or (hashlib.sha256(data).hexdigest(), len(data), w, h)
            != (digest, size, width, height)):
        raise DeliveryError('Original failed receipt verification')
    msg = build_message(sender, recipient, image, event)
    msg.replace_header('Subject', 'Ucon Wildkamera - Originalbild (Test)')
    return msg


def begin_delivery(db, row, message_id):
    uid, ident, stamp = row[:3]
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS deliveries (
            camera_uid TEXT NOT NULL, itemid TEXT NOT NULL,
            message_id TEXT NOT NULL, started_utc INTEGER NOT NULL,
            accepted_utc INTEGER, PRIMARY KEY(camera_uid,itemid))''')
        cur = db.execute("UPDATE events SET state='uncertain' WHERE camera_uid=? "
                         "AND itemid=? AND et_utc=? AND state='downloaded'", (uid, ident, stamp))
        if cur.rowcount != 1:
            raise DeliveryError('Event state changed before sending')
        db.execute('INSERT INTO deliveries VALUES (?,?,?,?,NULL)',
                   (uid, ident, message_id, int(time.time())))


def finish_delivery(db, row):
    uid, ident = row[:2]
    with db:
        db.execute('BEGIN IMMEDIATE')
        cur = db.execute("UPDATE events SET state='sent' WHERE camera_uid=? "
                         "AND itemid=? AND state='uncertain'", (uid, ident))
        receipt = db.execute('UPDATE deliveries SET accepted_utc=? WHERE camera_uid=? '
                             'AND itemid=? AND accepted_utc IS NULL', (int(time.time()), uid, ident))
        if cur.rowcount != 1 or receipt.rowcount != 1:
            raise DeliveryError('Cannot commit SMTP acceptance')


def process(db, rows, *, load_image, build_message, sender, recipient, send=None, emit=print):
    # Verify the exact bytes attached to the message before any SMTP operation.
    prepared = [(row, prepare(row, load_image, build_message, sender, recipient)) for row in rows]
    completed = 0
    for row, msg in prepared:
        stamp = dt.datetime.fromtimestamp(row[2], dt.timezone.utc).isoformat()
        emit(f'Original verified: {stamp} | {row[8]}x{row[9]} | {row[7]} bytes')
        if send is None:
            continue
        # Commit before crossing the external side-effect boundary. If interrupted,
        # leave uncertain and never automatically resend, even if no mail was sent.
        begin_delivery(db, row, str(msg['Message-ID']))
        try:
            send(msg)
            finish_delivery(db, row)
        except (Exception, KeyboardInterrupt) as exc:
            emit(f'SMTP outcome uncertain ({type(exc).__name__}); stopped. Check inbox before manual resolution.')
            return 1
        completed += 1
        emit(f'SMTP accepted; state=sent: {stamp}')
    emit(f'Queue SMTP: verified={len(prepared)}, sent={completed}; no camera connection.')
    return 0


def main():
    from queue_download import batch_lock
    from smtp_probe import load_image, build_message, send_message, read_smtp_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue-db', required=True, type=Path)
    parser.add_argument('--day', required=True, type=dt.date.fromisoformat)
    parser.add_argument('--tz', default='Europe/Berlin')
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--send', action='store_true', help='Actually send verified originals')
    args = parser.parse_args()
    if not 1 <= args.limit <= 10:
        parser.error('--limit must be 1–10')
    try:
        tz = ZoneInfo(args.tz)
        begin = int(dt.datetime.combine(args.day, dt.time.min, tzinfo=tz).timestamp())
        end = int(dt.datetime.combine(args.day + dt.timedelta(days=1), dt.time.min, tzinfo=tz).timestamp())
        with batch_lock(args.queue_db), closing(sqlite3.connect(args.queue_db, timeout=10)) as db:
            uncertain, = db.execute("SELECT count(*) FROM events WHERE state='uncertain' "
                                     'AND et_utc>=? AND et_utc<?', (begin, end)).fetchone()
            rows = ready_rows(db, begin, end, args.limit)
            print(f'Queue SMTP: ready={len(rows)}, uncertain={uncertain}, limit={args.limit}')
            if uncertain:
                print('Uncertain delivery requires manual review; not resending or starting another batch.')
                return 1
            if not rows:
                print('No downloaded originals in selected interval; no SMTP connection.')
                return 0
            sender = 'sender@example.invalid'
            recipient = 'recipient@example.invalid'
            send = None
            if args.send:
                sender, recipient, host, port, security, username, password = read_smtp_settings()
                send = lambda msg: send_message(msg, host, port, security, username, password)
            else:
                print('Validation only: no SMTP connection or delivery state change.')
            return process(db, rows, load_image=load_image, build_message=build_message,
                           sender=sender, recipient=recipient, send=send)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Queue SMTP stopped: {type(exc).__name__}. Details suppressed; check queue state.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
