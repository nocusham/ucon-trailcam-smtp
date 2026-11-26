import hashlib
import json
import sqlite3
import tempfile
import unittest
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from io import BytesIO
from queue_smtp import DeliveryError, ready_rows, process


class QueueSMTPTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = sqlite3.connect(Path(self.tmp.name) / 'test.sqlite3')
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE events(camera_uid,itemid,et_utc,state,metadata_json);
            CREATE TABLE downloads(camera_uid,itemid,sd_time,path,sha256,size,width,height);''')
        self.path = Path(self.tmp.name) / 'native.jpg'
        Image.new('RGB', (12, 8)).save(self.path, 'JPEG')
        data = self.path.read_bytes()
        for ident, stamp, state in [('a', 100, 'downloaded'), ('b', 200, 'downloaded'), ('c', 300, 'pending')]:
            event = {'itemid': ident, 'et_utc': stamp, 'type': 1, 'battery': 87}
            self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)', ('own', ident, stamp, state, json.dumps(event)))
            if state == 'downloaded':
                self.db.execute('INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?)',
                                ('own', ident, stamp, str(self.path), hashlib.sha256(data).hexdigest(), len(data), 12, 8))
        self.db.commit()

    def load(self, path):
        data = path.read_bytes()
        with Image.open(BytesIO(data)) as im:
            im.load()
            return data, im.format.lower().replace('jpeg', 'jpg'), *im.size, path.name

    def build(self, sender, recipient, image, event):
        msg = EmailMessage()
        msg['Subject'] = 'test'
        msg['Message-ID'] = f'<{event["itemid"]}@example.invalid>'
        msg.set_content(json.dumps(event))
        msg.add_attachment(image[0], maintype='image', subtype='jpeg', filename=image[4])
        return msg

    def run_batch(self, send=None, begin=1, end=400):
        return process(self.db, ready_rows(self.db, begin, end, 3), load_image=self.load,
                       build_message=self.build, sender='s@example.invalid', recipient='r@example.invalid',
                       send=send, emit=lambda _: None)

    def states(self):
        return [r[0] for r in self.db.execute('SELECT state FROM events ORDER BY et_utc')]

    def test_validation_only(self):
        self.assertEqual(self.run_batch(), 0)
        self.assertEqual(self.states(), ['downloaded', 'downloaded', 'pending'])
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='deliveries'").fetchone())

    def test_success_and_no_resend(self):
        send = Mock()
        self.assertEqual(self.run_batch(send), 0)
        self.assertEqual(self.states(), ['sent', 'sent', 'pending'])
        self.assertEqual(send.call_count, 2)
        msg = send.call_args_list[0].args[0]
        attachment, = msg.iter_attachments()
        self.assertEqual(attachment.get_filename(), 'native.jpg')
        self.assertEqual(attachment.get_payload(decode=True), self.path.read_bytes())
        self.assertEqual(self.db.execute('SELECT count(*) FROM deliveries WHERE accepted_utc IS NOT NULL').fetchone()[0], 2)
        self.run_batch(send)
        self.assertEqual(send.call_count, 2)

    def test_uncertain_before_send_and_failure(self):
        def fail(msg):
            self.assertEqual(self.states()[0], 'uncertain')
            raise TimeoutError
        self.assertEqual(self.run_batch(fail), 1)
        self.assertEqual(self.states(), ['uncertain', 'downloaded', 'pending'])
        self.assertIsNone(self.db.execute('SELECT accepted_utc FROM deliveries').fetchone()[0])
        self.assertEqual(len(ready_rows(self.db, 1, 400, 3)), 1)

    def test_corrupted_file_stops_before_send(self):
        Image.new('RGB', (20, 8)).save(self.path, 'JPEG')
        send = Mock()
        with self.assertRaises(DeliveryError):
            self.run_batch(send)
        send.assert_not_called()
        self.assertEqual(self.states()[0], 'downloaded')

    def test_missing_receipt_or_bad_metadata(self):
        self.db.execute("DELETE FROM downloads WHERE itemid='b'")
        self.db.commit()
        send = Mock()
        with self.assertRaises(DeliveryError):
            self.run_batch(send)
        send.assert_not_called()
        self.assertEqual(self.states()[0], 'downloaded')

    def test_day_and_limit(self):
        self.assertEqual(len(ready_rows(self.db, 1, 400, 1)), 1)
        send = Mock()
        self.run_batch(send, begin=150, end=250)
        self.assertEqual(self.states(), ['downloaded', 'sent', 'pending'])
        send.assert_called_once()
