"""Explicit SMTP batch test for verified originals; no camera or cloud access."""
import argparse
import datetime as dt
import hashlib
import json
import os
import sqlite3
import time
from contextlib import closing
from email.utils import getaddresses
from pathlib import Path
from zoneinfo import ZoneInfo
from ucon_trailcam_smtp.mail_subject import camera_subject
from ucon_trailcam_smtp.smtp_transport import SafeSMTPFailure, smtp_failure_fields
from ucon_trailcam_smtp.safe_diagnostics import error_fields
from ucon_trailcam_smtp.smtp_retry import retry_due, rollback_unsent, clear_retry
from ucon_trailcam_smtp.smtp_pacing import Pacer, DEFAULT_INTERVAL, validate_interval


class DeliveryError(Exception):
    pass


def ready_rows(db, begin, end, limit, state='downloaded', camera_uid=None):
    if state not in ('downloaded', 'sent'):
        raise DeliveryError('Invalid selection state')
    scope = ' AND camera_uid=?' if camera_uid is not None else ''
    params = (state, begin, end) + ((camera_uid,) if camera_uid is not None else ())
    count, = db.execute('SELECT count(*) FROM events WHERE state=? '
                        'AND et_utc>=? AND et_utc<?' + scope, params).fetchone()
    if not count:
        return []
    return db.execute('''SELECT e.camera_uid,e.itemid,e.et_utc,e.metadata_json,
                         d.sd_time,d.path,d.sha256,d.size,d.width,d.height
                         FROM events e LEFT JOIN downloads d
                         ON e.camera_uid=d.camera_uid AND e.itemid=d.itemid
                         WHERE e.state=? AND e.et_utc>=? AND e.et_utc<?'''
                      + (' AND e.camera_uid=?' if camera_uid is not None else '')
                      + ' ORDER BY e.et_utc,e.camera_uid,e.itemid LIMIT ?',
                      (*params, limit)).fetchall()


def prepare(row, load_image, build_message, sender, recipient, *, camera_name=None):
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
    attachments = list(msg.iter_attachments())
    if (len(attachments) != 1 or attachments[0].get_content_type() != 'image/jpeg'
            or attachments[0].get_filename() != filename
            or attachments[0].get_payload(decode=True) != data):
        raise DeliveryError('MIME attachment differs from verified original')
    when = dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat()
    subject = (camera_subject(camera_name, [stamp]) if camera_name is not None
               else f'Ucon Wildkamera - {filename} - {when}')
    msg.replace_header('Subject', subject)
    return msg


def validate_destination(mode, host, recipient):
    if mode == 'grouped' and (host.lower().rstrip('.') == 'smtp.revierwelt.de' or any(
            addr.lower().endswith('@revierwelt.de') for _, addr in getaddresses([recipient]))):
        raise DeliveryError('Revierwelt requires SMTP_MODE=single')


def message_batches(prepared, mode, *, camera_name=None):
    if mode not in ('single', 'grouped'):
        raise DeliveryError('Invalid SMTP mode')
    if mode == 'single':
        return [([row], msg) for row, msg in prepared]
    if not prepared:
        return []
    rows = [row for row, _ in prepared]
    msg = prepared[0][1]
    sections = []
    for i, (_, individual) in enumerate(prepared, 1):
        attachment, = individual.iter_attachments()
        body = individual.get_body(preferencelist=('plain',))
        if body is None:
            raise DeliveryError('Missing plain-text event metadata')
        sections.append(f'Bild {i}: {attachment.get_filename()}\n{body.get_content()}')
        if i > 1:
            msg.add_attachment(attachment.get_payload(decode=True), maintype='image',
                               subtype='jpeg', filename=attachment.get_filename())
    msg.get_body(preferencelist=('plain',)).set_content('\n'.join(sections))
    subject = (camera_subject(camera_name, [row[2] for row in rows], grouped=True)
               if camera_name is not None else f'Ucon Wildkamera - {len(rows)} Originalbilder')
    msg.replace_header('Subject', subject)
    if len(list(msg.iter_attachments())) != len(rows):
        raise DeliveryError('Unexpected grouped attachment count')
    return [(rows, msg)]


def begin_delivery(db, rows, message_id, route=None):
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('''CREATE TABLE IF NOT EXISTS deliveries (
            camera_uid TEXT NOT NULL, itemid TEXT NOT NULL,
            message_id TEXT NOT NULL, started_utc INTEGER NOT NULL,
            accepted_utc INTEGER, PRIMARY KEY(camera_uid,itemid))''')
        if route is not None:
            db.execute('''CREATE TABLE IF NOT EXISTS delivery_routes (
                camera_uid TEXT NOT NULL, itemid TEXT NOT NULL,
                route_json TEXT NOT NULL, PRIMARY KEY(camera_uid,itemid))''')
        started = int(time.time())
        for row in rows:
            uid, ident, stamp = row[:3]
            cur = db.execute("UPDATE events SET state='uncertain' WHERE camera_uid=? "
                             "AND itemid=? AND et_utc=? AND state='downloaded'", (uid, ident, stamp))
            if cur.rowcount != 1:
                raise DeliveryError('Event state changed before sending')
            db.execute('INSERT INTO deliveries VALUES (?,?,?,?,NULL)',
                       (uid, ident, message_id, started))
            if route is not None:
                db.execute('INSERT INTO delivery_routes VALUES (?,?,?)',
                           (uid, ident, json.dumps(route, ensure_ascii=False)))


def finish_delivery(db, rows):
    with db:
        db.execute('BEGIN IMMEDIATE')
        accepted = int(time.time())
        for row in rows:
            uid, ident = row[:2]
            cur = db.execute("UPDATE events SET state='sent' WHERE camera_uid=? "
                             "AND itemid=? AND state='uncertain'", (uid, ident))
            receipt = db.execute('UPDATE deliveries SET accepted_utc=? WHERE camera_uid=? '
                                 'AND itemid=? AND accepted_utc IS NULL', (accepted, uid, ident))
            if cur.rowcount != 1 or receipt.rowcount != 1:
                raise DeliveryError('Cannot commit SMTP acceptance')


def process(db, rows, *, load_image, build_message, sender, recipient, send=None, emit=print,
            mode='single', route=None, pacer=None):
    if len({row[0] for row in rows}) > 1:
        raise DeliveryError('Mixed-camera SMTP batch refused; select a camera profile')
    if send is not None and rows and not retry_due(db, rows[0][0], int(time.time())):
        emit('SMTP retry not due; no SMTP connection.')
        return 1
    # Verify the exact bytes attached to the message before any SMTP operation.
    camera_name = route.get('name') if route is not None else None
    prepared = [(row, prepare(row, load_image, build_message, sender, recipient,
                              camera_name=camera_name)) for row in rows]
    for row, _ in prepared:
        stamp = dt.datetime.fromtimestamp(row[2], dt.timezone.utc).isoformat()
        emit(f'Original verified: {stamp} | {row[8]}x{row[9]} | {row[7]} bytes')
    batches = message_batches(prepared, mode, camera_name=camera_name)
    completed = messages = 0
    emit(f'SMTP plan: mode={mode}, messages={len(batches)}, images={len(prepared)}')
    for i, (group, msg) in enumerate(batches, 1):
        emit(f'Message {i}/{len(batches)}: attachments={len(list(msg.iter_attachments()))}')
        if camera_name is not None:
            emit(f"Subject: {msg['Subject']}")
        if send is None:
            continue
        if pacer is not None and not pacer.reserve():
            emit('SMTP interval not elapsed; remaining originals deferred.')
            break
        # All events belonging to this message transition together.
        begin_delivery(db, group, str(msg['Message-ID']), route)
        try:
            send(msg)
        except SafeSMTPFailure as exc:
            delay = rollback_unsent(db, group, str(msg['Message-ID']), int(time.time()))
            emit(f'SMTP setup failed before submission; {smtp_failure_fields(exc)}; state=downloaded; retry in {delay}s.')
            return 1
        except (Exception, KeyboardInterrupt) as exc:
            emit(f'SMTP outcome uncertain; stage=submission {smtp_failure_fields(exc)}; stopped. Check inbox before manual resolution.')
            return 1
        try:
            finish_delivery(db, group)
        except (Exception, KeyboardInterrupt) as exc:
            emit(f'SMTP acceptance not committed; stage=receipt_commit {error_fields(exc)}; stopped. Check inbox before manual resolution.')
            return 1
        clear_retry(db, group[0][0])
        completed += len(group)
        messages += 1
        emit(f'SMTP accepted; state=sent: images={len(group)}')
    emit(f'Queue SMTP: verified={len(prepared)}, sent={completed}, messages_sent={messages}; no camera connection.')
    return 0


def main():
    from ucon_trailcam_smtp.queue_download import batch_lock
    from ucon_trailcam_smtp.mail_message import load_image, build_message, send_message
    from ucon_trailcam_smtp.smtp_settings import read_smtp_settings

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queue-db', required=True, type=Path)
    parser.add_argument('--day', required=True, type=dt.date.fromisoformat)
    parser.add_argument('--tz', default='Europe/Berlin')
    parser.add_argument('--limit', type=int, default=3)
    parser.add_argument('--mode', choices=('single', 'grouped'),
                        default=os.environ.get('SMTP_MODE', 'single'),
                        help='Single email per image (default) or grouped attachments')
    parser.add_argument('--preview-sent', action='store_true', help='Read-only MIME plan for previously sent originals')
    parser.add_argument('--send', action='store_true', help='Actually send verified originals')
    parser.add_argument('--smtp-interval', type=int, default=DEFAULT_INTERVAL,
                        help='Manual minimum interval between attempts, seconds (1–3600)')
    args = parser.parse_args()
    if args.mode not in ('single', 'grouped'):
        parser.error('SMTP_MODE must be single or grouped')
    if args.preview_sent and args.send:
        parser.error('--preview-sent cannot be combined with --send')
    if not 1 <= args.limit <= 10:
        parser.error('--limit must be 1–10')
    try:
        validate_interval(args.smtp_interval)
        tz = ZoneInfo(args.tz)
        begin = int(dt.datetime.combine(args.day, dt.time.min, tzinfo=tz).timestamp())
        end = int(dt.datetime.combine(args.day + dt.timedelta(days=1), dt.time.min, tzinfo=tz).timestamp())
        with batch_lock(args.queue_db), closing(sqlite3.connect(args.queue_db, timeout=10)) as db:
            cameras, = db.execute('SELECT count(DISTINCT camera_uid) FROM events').fetchone()
            if cameras > 1:
                raise DeliveryError('Multiple cameras require camera_smtp.py with explicit profiles')
            uncertain, = db.execute("SELECT count(*) FROM events WHERE state='uncertain' "
                                     'AND et_utc>=? AND et_utc<?', (begin, end)).fetchone()
            rows = ready_rows(db, begin, end, args.limit, 'sent' if args.preview_sent else 'downloaded')
            print(f'Queue SMTP: ready={len(rows)}, uncertain={uncertain}, limit={args.limit}')
            if uncertain and not args.preview_sent:
                print('Uncertain delivery requires manual review; not resending or starting another batch.')
                return 1
            if not rows:
                print('No eligible originals in selected interval; no SMTP connection.')
                return 0
            sender = 'sender@example.invalid'
            recipient = 'recipient@example.invalid'
            send = None
            if args.send:
                sender, recipient, host, port, security, username, password = read_smtp_settings()
                validate_destination(args.mode, host, recipient)
                send = lambda msg: send_message(msg, host, port, security, username, password)
            else:
                print('Validation only: no SMTP connection or delivery state change.')
            return process(db, rows, load_image=load_image, build_message=build_message,
                           sender=sender, recipient=recipient, send=send, mode=args.mode,
                           pacer=Pacer(db, args.smtp_interval) if args.send else None)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Queue SMTP stopped; {error_fields(exc)}. Check queue state.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
