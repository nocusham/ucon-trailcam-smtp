import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from cloud_image import ImageError
from smtp_probe import load_image, build_message, send_message


class SmtpProbeTests(unittest.TestCase):
    def test_image_validation_and_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'photo.bin'
            Image.new('RGB', (12, 8)).save(path, 'PNG')
            image = load_image(path)
            msg = build_message('sender@example.invalid', 'recipient@example.invalid', image)
            attachment, = msg.iter_attachments()
            self.assertEqual(attachment.get_content_type(), 'image/png')
            self.assertEqual(attachment.get_filename(), 'photo.bin')
            self.assertEqual(attachment.get_payload(decode=True), path.read_bytes())
            path.write_bytes(b'<html>not an image</html>')
            with self.assertRaises(ImageError):
                load_image(path)

    def test_starttls_before_auth_and_send(self):
        with patch('smtp_probe.smtplib.SMTP') as factory:
            client = factory.return_value.__enter__.return_value
            client.send_message.return_value = {}
            send_message(object(), 'example.invalid', 587, 'starttls', 'user', 'secret')
            self.assertEqual([call[0] for call in client.method_calls],
                             ['ehlo', 'starttls', 'ehlo', 'login', 'send_message'])

    def test_no_send_after_tls_failure(self):
        with patch('smtp_probe.smtplib.SMTP') as factory:
            client = factory.return_value.__enter__.return_value
            client.starttls.side_effect = OSError('TLS failure')
            with self.assertRaises(OSError):
                send_message(object(), 'example.invalid', 587, 'starttls', 'user', 'secret')
            client.login.assert_not_called()
            client.send_message.assert_not_called()

    def test_implicit_tls_without_auth(self):
        with patch('smtp_probe.smtplib.SMTP_SSL') as factory:
            client = factory.return_value.__enter__.return_value
            client.send_message.return_value = {}
            send_message(object(), 'example.invalid', 465, 'tls')
            factory.assert_called_once()
            client.login.assert_not_called()
            client.send_message.assert_called_once()

    def test_plain_smtp_explicit_mode(self):
        with patch('smtp_probe.smtplib.SMTP') as factory:
            client = factory.return_value.__enter__.return_value
            client.send_message.return_value = {}
            send_message(object(), 'example.invalid', 5025, 'none', 'user', 'secret')
            client.starttls.assert_not_called()
            client.login.assert_called_once_with('user', 'secret')
            client.send_message.assert_called_once()

    def test_plain_text_event_fields_and_filename(self):
        event = {'itemid': 'sample', 'et_utc': 123, 'battery': 87, 'type': 4,
                 'ai_result': {'animal': 'Reh'}, 'user_tag': {},
                 'img_url': 'https://example.invalid/secret'}
        image = (b'fixture', 'jpg', 12, 8, 'Original Foto.jpg')
        msg = build_message('sender@example.invalid', 'recipient@example.invalid', image, event)
        body = msg.get_body(preferencelist=('plain',))
        self.assertEqual(body.get_content_type(), 'text/plain')
        text = body.get_content()
        for line in ('itemid: "sample"', 'et_utc: 123', 'battery: 87', 'type: 4',
                     'ai_result: {"animal": "Reh"}', 'user_tag: {}'):
            self.assertIn(line, text)
        self.assertNotIn('secret', text)
        attachment, = msg.iter_attachments()
        self.assertEqual(attachment.get_filename(), 'Original Foto.jpg')
        self.assertEqual(attachment.get_payload(decode=True), b'fixture')
