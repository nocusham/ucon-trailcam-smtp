"""Build and validate original-image SMTP messages; no CLI or credentials."""
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from cloud_image import ImageError, MAX_IMAGE_BYTES, validate_image
from event_metadata import metadata_text
from smtp_transport import transmit

MIME_SUBTYPE = {'jpg': 'jpeg', 'png': 'png', 'webp': 'webp', 'gif': 'gif',
                'bmp': 'bmp', 'tiff': 'tiff'}


def load_image(path):
    with path.open('rb') as source:
        data = source.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError('Image size limit exceeded')
    ext, width, height = validate_image(data)
    return data, ext, width, height, path.name


def build_message(sender, recipient, image, event=None):
    data, ext, width, height, filename = image
    msg = EmailMessage()
    msg['From'] = sender
    msg['To'] = recipient
    msg['Subject'] = 'Ucon Wildkamera - SMTP-Test'
    msg['Date'] = formatdate(usegmt=True)
    msg['Message-ID'] = make_msgid()
    body = f'Manueller SMTP-Test. Bild: {width} x {height} Pixel, {len(data)} Bytes.\n'
    if event is not None:
        body += '\n' + metadata_text(event) + '\n'
    msg.set_content(body)
    msg.add_attachment(data, maintype='image', subtype=MIME_SUBTYPE[ext],
                       filename=filename)
    return msg


def send_message(msg, host, port, security, username=None, password=None):
    return transmit(msg, host, port, security, username, password)
