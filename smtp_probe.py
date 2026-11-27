"""Validate a local image and optionally send one SMTP test message."""
import argparse
import getpass
from pathlib import Path

from event_metadata import load_metadata
from local_credentials import read_secret_values
# Re-export the historical helpers for existing callers.
from mail_message import load_image, build_message, send_message

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--send', action='store_true', help='Actually send one email')
    parser.add_argument('--event-json', type=Path,
                        help='Attach six cloud event fields as plain-text email body')
    args = parser.parse_args()
    try:
        image = load_image(args.image)
        event = load_metadata(args.event_json) if args.event_json else None
        data, ext, width, height, filename = image
        print(f'Validated {ext.upper()} image: {width}x{height}, {len(data)} bytes.')
        if event is not None:
            print('Event metadata loaded (six fields; values not logged).')
        else:
            print('Manual image-only test: no event metadata supplied.')
        if not args.send:
            print('Validation only. No SMTP connection or message sent.')
            return 0
        sender, recipient, host, port, security, username, password = read_smtp_settings()
        send_message(build_message(sender, recipient, image, event), host, port, security,
                     username or None, password)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'SMTP probe failed: {type(exc).__name__}. Details suppressed; delivery may be uncertain.')
        return 1
    print('SMTP server accepted the test message. Check the recipient inbox.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
