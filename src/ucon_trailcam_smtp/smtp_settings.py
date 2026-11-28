"""Shared legacy SMTP settings reader for manual SMTP entrypoints."""
import getpass
from ucon_trailcam_smtp.local_credentials import read_secret_values


def read_smtp_settings():
    values = read_secret_values()
    host = values.get('SMTP_HOST', '').strip()
    sender = values.get('SMTP_FROM', '').strip()
    recipient = values.get('SMTP_TO', '').strip()
    security = values.get('SMTP_SECURITY', 'starttls').lower()
    if security not in ('tls', 'starttls', 'none') or not all((host, sender, recipient)):
        raise ValueError('Set SMTP_HOST, SMTP_FROM, SMTP_TO and SMTP_SECURITY=starttls, tls or none')
    port = int(values.get('SMTP_PORT', {'tls': '465', 'starttls': '587', 'none': '25'}[security]))
    if not 1 <= port <= 65535:
        raise ValueError('Invalid SMTP_PORT')
    username = values.get('SMTP_USERNAME', '').strip()
    password = values.get('SMTP_PASSWORD')
    if username and not password:
        password = getpass.getpass('SMTP password: ')
    if username and not password:
        raise ValueError('SMTP password is required when username is set')
    if password and not username:
        raise ValueError('SMTP_USERNAME is required when password is set')
    if security == 'none':
        print('WARNING: SMTP without TLS; message and any credentials are unencrypted.')
    return sender, recipient, host, port, security, username or None, password
