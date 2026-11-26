"""Validate a local image and optionally send one SMTP test message."""
import argparse
import getpass
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from pathlib import Path

from cloud_image import ImageError, MAX_IMAGE_BYTES, validate_image

MIME_SUBTYPE = {'jpg': 'jpeg', 'png': 'png', 'webp': 'webp', 'gif': 'gif',
                'bmp': 'bmp', 'tiff': 'tiff'}


def load_image(path):
    with path.open('rb') as source:
        data = source.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError('Image size limit exceeded')
    ext, width, height = validate_image(data)
    return data, ext, width, height


def build_message(sender, recipient, image):
    data, ext, width, height = image
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Subject'] = 'Ucon Wildkamera - SMTP-Test'
    msg['Date'] = formatdate(usegmt=True)
    msg['Message-ID'] = make_msgid()
    msg.set_content(f'Manueller SMTP-Test. Bild: {width} x {height} Pixel, {len(data)} Bytes.\n')
    msg.add_attachment(data, maintype='image', subtype=MIME_SUBTYPE[ext],
                       filename=f'wildkamera-test.{ext}')
    return msg


def send_message(msg, host, port, security, username=None, password=None):
    context = ssl.create_default_context()
    if security == 'tls':
        connection = smtplib.SMTP_SSL(host, port, timeout=30, context=context)
    elif security == 'starttls':
        connection = smtplib.SMTP(host, port, timeout=30)
    else:
        raise ValueError('Unsupported SMTP security mode')
    with connection as client:
        if security == 'starttls':
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        if username:
            client.login(username, password)
        refused = client.send_message(msg)
        if refused:
            raise RuntimeError('SMTP recipient refused')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--send', action='store_true', help='Actually send one email')
    args = parser.parse_args()
    try:
        image = load_image(args.image)
        data, ext, width, height = image
        print(f'Validated {ext.upper()} image: {width}x{height}, {len(data)} bytes.')
        if not args.send:
            print('Validation only. No SMTP connection or message sent.')
            return 0
        host = os.environ.get('SMTP_HOST', '').strip()
        sender = os.environ.get('SMTP_FROM', '').strip()
        recipient = os.environ.get('SMTP_TO', '').strip()
        security = os.environ.get('SMTP_SECURITY', 'starttls').lower()
        if security not in ('tls', 'starttls') or not all((host, sender, recipient)):
            parser.error('Set SMTP_HOST, SMTP_FROM, SMTP_TO and SMTP_SECURITY=starttls or tls')
        port = int(os.environ.get('SMTP_PORT', '465' if security == 'tls' else '587'))
        if not 1 <= port <= 65535:
            parser.error('Invalid SMTP_PORT')
        username = os.environ.get('SMTP_USERNAME', '').strip()
        password = os.environ.get('SMTP_PASSWORD')
        if username and not password:
            password = getpass.getpass('SMTP password: ')
        if username and not password:
            parser.error('SMTP password is required when username is set')
        if password and not username:
            parser.error('SMTP_USERNAME is required when password is set')
        send_message(build_message(sender, recipient, image), host, port, security,
                     username or None, password)
    except (Exception, KeyboardInterrupt) as exc:
        print(f'SMTP probe failed: {type(exc).__name__}. Details suppressed; delivery may be uncertain.')
        return 1
    print('SMTP server accepted the test message. Check the recipient inbox.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
