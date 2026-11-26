import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
import hashlib

import test_queue_smtp
from camera_smtp import Camera, load_profiles, route_batch
from queue_smtp import DeliveryError, process, ready_rows


class CameraRoutingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_queue_smtp.QueueSMTPTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.db = self.fixture.db
        self.db.execute("UPDATE events SET camera_uid='second' WHERE itemid='b'")
        self.db.execute("UPDATE downloads SET camera_uid='second' WHERE itemid='b'")
        self.second_path = Path(self.fixture.tmp.name) / 'second.jpg'
        Image.new('RGB', (12, 8), 'red').save(self.second_path, 'JPEG')
        payload = self.second_path.read_bytes()
        self.db.execute("UPDATE downloads SET path=?,sha256=?,size=? WHERE itemid='b'",
                        (str(self.second_path), hashlib.sha256(payload).hexdigest(), len(payload)))
        self.db.commit()
        self.a = Camera('one', 'own', True, 'smtp.one.invalid', 587, 'starttls',
                        's@one.invalid', 'r@one.invalid', 'user1', 'PASS1', 'single', 3)
        self.b = Camera('two', 'second', True, 'smtp.two.invalid', 465, 'tls',
                        's@two.invalid', 'r@two.invalid', 'user2', 'PASS2', 'grouped', 3)

    def build(self, sender, recipient, image, event):
        msg = self.fixture.build(sender, recipient, image, event)
        msg['From'] = sender
        msg['To'] = recipient
        return msg

    def route(self, profiles, send, **kwargs):
        return route_batch(self.db, profiles, 1, 400, load_image=self.fixture.load,
                           build_message=self.build, send_message=send,
                           emit=lambda _: None, **kwargs)

    def test_scoped_routing_and_receipt(self):
        send = Mock()
        self.assertEqual(self.route([self.b, self.a], send, send_enabled=True,
                                    environ={'PASS1': 'a', 'PASS2': 'b'}), 0)
        self.assertEqual(send.call_count, 2)
        for call, p, secret in zip(send.call_args_list, [self.b, self.a], ['b', 'a']):
            msg, host, port, security, user, password = call.args
            self.assertEqual((host, port, security, user, password),
                             (p.host, p.port, p.security, p.username, secret))
            self.assertEqual(str(msg['From']), p.sender)
            self.assertEqual(str(msg['To']), p.recipient)
            attachment, = msg.iter_attachments()
            expected = self.second_path if p.uid == 'second' else self.fixture.path
            self.assertEqual(attachment.get_payload(decode=True), expected.read_bytes())
            snapshot, = self.db.execute('SELECT route_json FROM delivery_routes WHERE camera_uid=?', (p.uid,)).fetchone()
            self.assertEqual(json.loads(snapshot), p.route())
            self.assertNotIn('password', snapshot)

    def test_unknown_disabled_and_preview(self):
        send = Mock()
        self.assertEqual(self.route([self.a, replace(self.b, enabled=False)], send), 0)
        send.assert_not_called()
        self.assertEqual(self.fixture.states(), ['downloaded', 'downloaded', 'pending'])
        self.route([self.a], send, send_enabled=True, environ={'PASS1': 'a'})
        self.assertEqual(self.fixture.states(), ['sent', 'downloaded', 'pending'])
        self.route([self.a], send, preview_sent=True)
        self.assertEqual(send.call_count, 1)

    def test_missing_password_stops_before_any_send(self):
        send = Mock()
        with self.assertRaises(DeliveryError):
            self.route([self.a, self.b], send, send_enabled=True, environ={'PASS1': 'a'})
        send.assert_not_called()
        self.assertEqual(self.fixture.states(), ['downloaded', 'downloaded', 'pending'])

    def test_uncertain_other_camera_does_not_block(self):
        self.db.execute("UPDATE events SET state='uncertain' WHERE itemid='a'")
        self.db.commit()
        send = Mock()
        self.assertEqual(self.route([self.a, self.b], send, send_enabled=True, environ={'PASS2': 'b'}), 1)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(self.fixture.states(), ['uncertain', 'sent', 'pending'])

    def test_mixed_rows_refused_even_single_mode(self):
        with self.assertRaises(DeliveryError):
            process(self.db, ready_rows(self.db, 1, 400, 3), load_image=self.fixture.load,
                    build_message=self.fixture.build, sender=self.a.sender, recipient=self.a.recipient)

    def test_config_validation(self):
        path = Path(self.fixture.tmp.name) / 'profiles.toml'
        def entry(name, uid, recipient, mode='single'):
            return f'''[[cameras]]
name = "{name}"
uid = "{uid}"
[cameras.smtp]
host = "smtp.example.invalid"
from = "s@example.invalid"
to = "{recipient}"
mode = "{mode}"
'''
        first = entry('one', 'a', 'a@revierwelt.de')
        path.write_text(first + entry('two', 'b', 'r@example.invalid', 'grouped'))
        self.assertEqual([p.mode for p in load_profiles(path)], ['single', 'grouped'])
        for bad in (first + entry('two', 'b', 'A@revierwelt.de'),
                    first + entry('two', 'a', 'r@example.invalid'),
                    entry('one', 'a', 'a@revierwelt.de', 'grouped'),
                    entry('one', 'a', 'a@x.invalid,b@x.invalid'),
                    first + 'password = "secret"\n'):
            path.write_text(bad)
            with self.assertRaises(DeliveryError):
                load_profiles(path)

    def test_public_revierwelt_password_and_exclusive_source(self):
        path = Path(self.fixture.tmp.name) / 'profiles.toml'
        config = '''[[cameras]]
name = "one"
uid = "own"
[cameras.smtp]
host = "smtp.revierwelt.de"
port = 5025
from = "s@example.invalid"
to = "r@revierwelt.de"
username = "public-user"
password = "mail"
'''
        path.write_text(config)
        p, = load_profiles(path)
        self.assertEqual(p.password, 'mail')
        self.assertNotIn('password', p.route())
        self.assertNotIn('mail\'', repr(p).split('password_env=')[1])
        send = Mock()
        self.assertEqual(self.route([p], send, send_enabled=True, environ={}), 0)
        self.assertEqual(send.call_args.args[-1], 'mail')
        for bad in (config + 'password_env = "PASS1"\n',
                    config.replace('smtp.revierwelt.de', 'smtp.example.invalid'),
                    config.replace('password = "mail"', 'password = "secret"')):
            path.write_text(bad)
            with self.assertRaises(DeliveryError):
                load_profiles(path)

    def test_camera_password_loaded_from_file(self):
        path = Path(self.fixture.tmp.name) / '.env'
        path.write_text('PASS1=local-secret\n')
        path.chmod(0o600)
        from unittest.mock import patch
        import os
        send = Mock()
        with patch.dict(os.environ, {'UCON_SECRETS_FILE': str(path)}, clear=True):
            self.assertEqual(self.route([self.a], send, send_enabled=True), 0)
        self.assertEqual(send.call_args.args[-1], 'local-secret')
