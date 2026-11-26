"""Explicit per-camera SMTP routing test; no cloud or camera access."""
import argparse
import datetime as dt
import os
import re
import sqlite3
import tomllib
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

from queue_smtp import DeliveryError, ready_rows, process, validate_destination


@dataclass(frozen=True)
class Camera:
    name: str
    uid: str
    enabled: bool
    host: str
    port: int
    security: str
    sender: str
    recipient: str
    username: str
    password_env: str
    mode: str
    limit: int

    def route(self):
        return {key: getattr(self, key) for key in
                ('name', 'host', 'port', 'security', 'sender', 'recipient', 'mode')}


def string(obj, key, *, optional=False):
    value = obj.get(key, '' if optional else None)
    if not isinstance(value, str) or value != value.strip() or (not optional and not value):
        raise DeliveryError('Invalid or missing configuration string')
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise DeliveryError('Control character in configuration')
    return value


def mailbox(value):
    if not re.fullmatch(r'[A-Za-z0-9.!#$%&\'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z0-9-]+', value):
        raise DeliveryError('Use exactly one bare email address per sender and recipient')
    return value


def load_profiles(path):
    with Path(path).open('rb') as source:
        data = tomllib.load(source)
    if set(data) != {'cameras'} or not isinstance(data['cameras'], list) or not data['cameras']:
        raise DeliveryError('Expected a nonempty [[cameras]] list')
    profiles = []
    names, uids, rw = set(), set(), set()
    for entry in data['cameras']:
        if not isinstance(entry, dict) or set(entry) - {'name', 'uid', 'enabled', 'smtp'}:
            raise DeliveryError('Unknown camera option')
        name, uid = string(entry, 'name'), string(entry, 'uid')
        enabled = entry.get('enabled', True)
        if type(enabled) is not bool or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', name):
            raise DeliveryError('Invalid camera name or enabled flag')
        if name in names or uid in uids:
            raise DeliveryError('Duplicate camera name or UID')
        names.add(name)
        uids.add(uid)
        smtp = entry.get('smtp')
        if not isinstance(smtp, dict) or set(smtp) - {'host', 'port', 'security', 'from', 'to',
                                                     'username', 'password_env', 'mode', 'limit'}:
            raise DeliveryError('Unknown or missing SMTP options')
        host = string(smtp, 'host')
        if not re.fullmatch(r'[A-Za-z0-9.:-]+', host):
            raise DeliveryError('Invalid SMTP host')
        security = smtp.get('security', 'starttls')
        mode = smtp.get('mode', 'single')
        if security not in ('none', 'starttls', 'tls') or mode not in ('single', 'grouped'):
            raise DeliveryError('Invalid SMTP security or mode')
        port = smtp.get('port', {'none': 25, 'starttls': 587, 'tls': 465}[security])
        limit = smtp.get('limit', 3)
        if type(port) is not int or not 1 <= port <= 65535 or type(limit) is not int or not 1 <= limit <= 10:
            raise DeliveryError('Invalid SMTP port or batch limit')
        sender, recipient = mailbox(string(smtp, 'from')), mailbox(string(smtp, 'to'))
        username, password_env = string(smtp, 'username', optional=True), string(smtp, 'password_env', optional=True)
        if bool(username) != bool(password_env) or (password_env and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', password_env)):
            raise DeliveryError('SMTP username requires a password environment variable')
        validate_destination(mode, host, recipient)
        if recipient.lower().endswith('@revierwelt.de'):
            if recipient.lower() in rw:
                raise DeliveryError('Duplicate Revierwelt recipient')
            rw.add(recipient.lower())
        profiles.append(Camera(name, uid, enabled, host, port, security, sender, recipient,
                               username, password_env, mode, limit))
    return profiles


def route_batch(db, profiles, begin, end, *, preview_sent=False, send_enabled=False,
                load_image, build_message, send_message, environ=None, emit=print):
    if preview_sent and send_enabled:
        raise DeliveryError('Sent preview cannot send')
    environ = os.environ if environ is None else environ
    state = 'sent' if preview_sent else 'downloaded'
    selected = [p for p in profiles if p.enabled]
    known = {p.uid for p in selected}
    rows = db.execute('SELECT DISTINCT camera_uid FROM events WHERE state=? AND et_utc>=? AND et_utc<?',
                      (state, begin, end)).fetchall()
    emit(f'Unselected or disabled cameras with eligible events: {sum(uid not in known for uid, in rows)}')
    # Resolve all needed credentials before any transmission. Preview needs none.
    jobs = []
    for p in selected:
        uncertain, = db.execute("SELECT count(*) FROM events WHERE camera_uid=? AND state='uncertain'",
                                (p.uid,)).fetchone()
        if uncertain and not preview_sent:
            emit(f'Camera {p.name}: blocked by uncertain delivery; no SMTP')
            jobs.append((p, None, None))
            continue
        items = ready_rows(db, begin, end, p.limit, state, camera_uid=p.uid)
        password = None
        if send_enabled and items and p.password_env:
            password = environ.get(p.password_env)
            if not password:
                raise DeliveryError('Missing configured SMTP password environment variable')
        jobs.append((p, items, password))
    failed = False
    for p, items, password in jobs:
        if items is None:
            failed = True
            continue
        emit(f'Camera {p.name}: ready={len(items)}, mode={p.mode}, security={p.security}')
        if not items:
            continue
        if send_enabled and p.security == 'none':
            emit('WARNING: unencrypted SMTP explicitly configured for this camera')
        def send(msg):
            send_message(msg, p.host, p.port, p.security, p.username or None, password)
        try:
            code = process(db, items, load_image=load_image, build_message=build_message,
                           sender=p.sender, recipient=p.recipient, mode=p.mode,
                           send=send if send_enabled else None, route=p.route(), emit=emit)
        except Exception as exc:
            emit(f'Camera {p.name}: failed ({type(exc).__name__}); details suppressed')
            failed = True
        else:
            # Stop the invocation on uncertain SMTP outcome (including Ctrl+C).
            if code:
                return code
    return int(failed)


def main():
    from queue_download import batch_lock
    from smtp_probe import load_image, build_message, send_message
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--queue-db', required=True, type=Path)
    parser.add_argument('--day', required=True, type=dt.date.fromisoformat)
    parser.add_argument('--tz', default='Europe/Berlin')
    parser.add_argument('--camera', help='Select one configured camera name')
    parser.add_argument('--preview-sent', action='store_true')
    parser.add_argument('--send', action='store_true')
    args = parser.parse_args()
    if args.preview_sent and args.send:
        parser.error('--preview-sent cannot be combined with --send')
    try:
        profiles = load_profiles(args.config)
        if args.camera:
            profiles = [p for p in profiles if p.name == args.camera]
            if not profiles:
                raise DeliveryError('Unknown configured camera')
        tz = ZoneInfo(args.tz)
        begin = int(dt.datetime.combine(args.day, dt.time.min, tzinfo=tz).timestamp())
        end = int(dt.datetime.combine(args.day + dt.timedelta(days=1), dt.time.min, tzinfo=tz).timestamp())
        with batch_lock(args.queue_db), closing(sqlite3.connect(args.queue_db, timeout=10)) as db:
            if not args.send:
                print('Validation only; no SMTP or state changes.')
            return route_batch(db, profiles, begin, end, preview_sent=args.preview_sent,
                               send_enabled=args.send, load_image=load_image,
                               build_message=build_message, send_message=send_message)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Camera SMTP stopped: {type(exc).__name__}; details suppressed. Check configuration and queue.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
