"""Persistent, optional health notifications (service integration is separate)."""
import argparse
import datetime as dt
import re
import tomllib
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path
from ucon_trailcam_smtp.smtp_transport import smtp_failure_fields


@dataclass(frozen=True)
class AlertSettings:
    enabled: bool = False
    login_minutes: int = 15
    api_minutes: int = 30
    camera_hours: int = 24
    repeat_hours: int = 24
    retry_minutes: int = 60
    recovery: bool = True
    host: str = ''
    port: int = 587
    security: str = 'starttls'
    sender: str = ''
    recipient: str = ''
    username: str = ''
    password_env: str = ''

    def threshold(self, category):
        return {'login': self.login_minutes * 60, 'api': self.api_minutes * 60,
                'camera': self.camera_hours * 3600, 'inactivity': 0}[category]


def parse_alerts(raw):
    if raw is None:
        return AlertSettings()
    if not isinstance(raw, dict) or set(raw) - {
            'enabled', 'login_minutes', 'api_minutes', 'camera_hours',
            'repeat_hours', 'retry_minutes', 'recovery', 'smtp'}:
        raise ValueError('Invalid alerts configuration')
    defaults = AlertSettings()
    opts = {}
    for key in ('enabled', 'recovery'):
        value = raw.get(key, getattr(defaults, key))
        if type(value) is not bool:
            raise ValueError('Invalid alerts boolean')
        opts[key] = value
    for key in ('login_minutes', 'api_minutes', 'camera_hours', 'repeat_hours', 'retry_minutes'):
        value = raw.get(key, getattr(defaults, key))
        if type(value) is not int or not 1 <= value <= (720 if key.endswith('_hours') else 10080):
            raise ValueError('Invalid alert interval')
        opts[key] = value
    smtp = raw.get('smtp')
    if smtp is None and not opts['enabled']:
        return AlertSettings(**opts)
    if not isinstance(smtp, dict) or set(smtp) - {
            'host', 'port', 'security', 'from', 'to', 'username', 'password_env'}:
        raise ValueError('Invalid alert SMTP configuration')
    def value(key, optional=False):
        text = smtp.get(key, '' if optional else None)
        if (not isinstance(text, str) or text != text.strip() or (not optional and not text)
                or any(ord(c) < 32 or ord(c) == 127 for c in text)):
            raise ValueError('Invalid alert SMTP string')
        return text
    host = value('host')
    sender, recipient = value('from'), value('to')
    for address in (sender, recipient):
        if not re.fullmatch(r'[A-Za-z0-9.!#$%&*+/=?^_~\-]+@[A-Za-z0-9.-]+\.[A-Za-z0-9-]+', address):
            raise ValueError('Alert SMTP requires one bare email address')
    if (not re.fullmatch(r'[A-Za-z0-9.:-]+', host) or host.lower().rstrip('.') == 'smtp.revierwelt.de'
            or recipient.lower().endswith('@revierwelt.de')):
        raise ValueError('Alert SMTP must not use a Revierwelt destination')
    security = smtp.get('security', 'starttls')
    if security not in ('starttls', 'tls'):
        raise ValueError('Alert SMTP requires TLS')
    port = smtp.get('port', 465 if security == 'tls' else 587)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid alert SMTP port')
    username, password_env = value('username', True), value('password_env', True)
    if bool(username) != bool(password_env) or (password_env and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', password_env)):
        raise ValueError('Alert SMTP authentication requires a password reference')
    return AlertSettings(**opts, host=host, port=port, security=security, sender=sender,
                         recipient=recipient, username=username, password_env=password_env)


def load_alerts(path):
    with Path(path).open('rb') as source:
        return parse_alerts(tomllib.load(source).get('alerts'))


def init_health(db):
    with db:
        db.execute('''CREATE TABLE IF NOT EXISTS health_incidents (
            category TEXT NOT NULL, scope TEXT NOT NULL, first_failure INTEGER NOT NULL,
            last_failure INTEGER NOT NULL, failures INTEGER NOT NULL, code INTEGER,
            blocked INTEGER NOT NULL, recovered_at INTEGER, last_attempt INTEGER,
            last_notice INTEGER, PRIMARY KEY(category,scope))''')


def observe(db, category, scope, *, healthy, now, code=None, blocked=False):
    """Record actual checks only. A blocked login is a confirmed rejected credential."""
    if (category not in ('login', 'api', 'camera', 'inactivity') or not isinstance(scope, str) or not scope
            or (category in ('login', 'api') and scope != 'ucon') or type(healthy) is not bool
            or type(now) is not int or now < 0 or (code is not None and type(code) is not int)
            or (blocked and (healthy or category != 'login' or code != 20005))):
        raise ValueError('Invalid health observation')
    with db:
        db.execute('BEGIN IMMEDIATE')
        old = db.execute('SELECT first_failure,last_failure,recovered_at,last_notice FROM health_incidents '
                         'WHERE category=? AND scope=?', (category, scope)).fetchone()
        if old is not None and now < max(old[1], old[2] or 0):
            raise ValueError('Health observation is out of order')
        if healthy:
            if old is None or old[2] is not None:
                return
            if old[3] is None:
                db.execute('DELETE FROM health_incidents WHERE category=? AND scope=?', (category, scope))
            else:
                db.execute('UPDATE health_incidents SET recovered_at=?,last_attempt=NULL '
                           'WHERE category=? AND scope=?', (now, category, scope))
        elif old is None or old[2] is not None:
            db.execute('INSERT OR REPLACE INTO health_incidents VALUES (?,?,?,?,?,?,?,NULL,NULL,NULL)',
                       (category, scope, now, now, 1, code, int(blocked)))
        else:
            db.execute('UPDATE health_incidents SET last_failure=?,failures=failures+1,code=?,blocked=? '
                       'WHERE category=? AND scope=?', (now, code, int(blocked), category, scope))


@dataclass(frozen=True)
class Notice:
    category: str
    scope: str
    label: str
    first_failure: int
    last_failure: int
    failures: int
    code: int | None
    recovered_at: int | None


def due_notices(db, settings, now, cameras, *, inactivity_scopes=()):
    """Camera map contains enabled UID -> safe local alias only."""
    if not settings.enabled:
        return []
    rows = db.execute('SELECT category,scope,first_failure,last_failure,failures,code,blocked,'
                      'recovered_at,last_attempt,last_notice FROM health_incidents ORDER BY first_failure,category,scope')
    result = []
    for cat, scope, first, last, count, code, blocked, recovery, attempt, notice in rows:
        if cat in ('camera', 'inactivity') and scope not in cameras:
            continue
        if cat == 'inactivity' and scope not in inactivity_scopes:
            continue
        if attempt is not None and now - attempt < settings.retry_minutes * 60:
            continue
        if recovery is not None:
            if not settings.recovery or notice is None:
                continue
        else:
            # Time passing or a process reboot alone is not evidence of failure.
            # Only a confirmed rejected login can mature without another check.
            if (now - first < settings.threshold(cat) or
                    (not blocked and (count < 2 or last - first < settings.threshold(cat)))):
                continue
            if notice is not None and now - notice < settings.repeat_hours * 3600:
                continue
        result.append(Notice(cat, scope, cameras[scope] if cat in ('camera', 'inactivity') else 'Ucon',
                             first, last, count, code, recovery))
    return result


def utc(stamp):
    return dt.datetime.fromtimestamp(stamp, dt.timezone.utc).isoformat()


def build_alert(settings, notice=None):
    msg = EmailMessage()
    msg['From'] = settings.sender
    msg['To'] = settings.recipient
    msg['Date'] = formatdate(usegmt=True)
    msg['Message-ID'] = make_msgid()
    if notice is None:
        msg['Subject'] = 'Wildkamera: Test der Fehlerbenachrichtigung'
        msg.set_content('Dies ist ein manueller SMTP-Alarmtest. Keine Kamerastörung festgestellt.')
    else:
        state = 'Entwarnung' if notice.recovered_at is not None else 'Störung'
        label = {'login': 'Anmeldung', 'api': 'Cloud-API', 'camera': 'Originaldownload', 'inactivity': 'Ausbleibende Aktivität'}[notice.category]
        msg['Subject'] = f'Wildkamera: {state} – {notice.label} / {label}'
        body = (f'{state}: {notice.label} / {label}\nErster Fehler: {utc(notice.first_failure)}\n'
                f'Letzter Fehler: {utc(notice.last_failure)}\nFehlgeschlagene Prüfungen: {notice.failures}\n')
        if notice.category == 'inactivity':
            body += ('Neue Aktivität gemeldet.\n' if notice.recovered_at is not None else
                     'Keine aktuelle Aktivität gemeldet; dies ist kein Nachweis, dass die Kamera offline ist.\n')
        if notice.code is not None:
            body += f'API-Code: {notice.code}\n'
        if notice.recovered_at is not None:
            body += f'Erfolgreiche Prüfung: {utc(notice.recovered_at)}\n'
        msg.set_content(body)
    return msg


def dispatch_due(db, settings, now, cameras, send, *, emit=print, inactivity_scopes=()):
    """Single service worker under its DB lock; commit attempt before network I/O."""
    accepted = failed = 0
    for n in due_notices(db, settings, now, cameras, inactivity_scopes=inactivity_scopes):
        with db:
            db.execute('UPDATE health_incidents SET last_attempt=? WHERE category=? AND scope=?',
                       (now, n.category, n.scope))
        try:
            send(build_alert(settings, n))
        except Exception as exc:
            failed += 1
            emit(f'Alert SMTP failed; {smtp_failure_fields(exc)}; retry throttled')
            continue
        with db:
            if n.recovered_at is not None:
                db.execute('DELETE FROM health_incidents WHERE category=? AND scope=?', (n.category, n.scope))
            else:
                db.execute('UPDATE health_incidents SET last_notice=? WHERE category=? AND scope=?',
                           (now, n.category, n.scope))
        accepted += 1
    return accepted, failed


def smtp_sender(settings, environ=None):
    from ucon_trailcam_smtp.local_credentials import read_secret_values
    from ucon_trailcam_smtp.mail_message import send_message
    values = read_secret_values() if environ is None else environ
    password = values.get(settings.password_env) if settings.username else None
    if settings.username and not password:
        raise ValueError('Missing alert SMTP password')
    return lambda msg: send_message(msg, settings.host, settings.port, settings.security,
                                    settings.username or None, password)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--send-test', action='store_true', help='Send exactly one explicit alert test')
    args = parser.parse_args()
    try:
        settings = load_alerts(args.config)
        if not settings.enabled:
            print('Alert SMTP disabled; no message sent.')
            return int(args.send_test)
        print(f'Alerts enabled: login={settings.login_minutes}m, API={settings.api_minutes}m, '
              f'camera={settings.camera_hours}h, repeat={settings.repeat_hours}h, '
              f'retry={settings.retry_minutes}m, recovery={settings.recovery}')
        if args.send_test:
            smtp_sender(settings)(build_alert(settings))
            print('Alert SMTP test accepted; check inbox.')
        else:
            print('Configuration valid; no SMTP connection or database changes.')
        return 0
    except (Exception, KeyboardInterrupt) as exc:
        print(f'Alert test failed; {smtp_failure_fields(exc)}.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
