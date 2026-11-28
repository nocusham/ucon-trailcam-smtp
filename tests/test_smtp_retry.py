import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ucon_trailcam_smtp.smtp_retry import rollback_unsent, retry_due, clear_retry, record_setup_failure
from ucon_trailcam_smtp.smtp_transport import transmit, SafeSMTPFailure


class TransportTests(unittest.TestCase):
    def test_connection_failure_safe(self):
        with patch('ucon_trailcam_smtp.smtp_transport.smtplib.SMTP', side_effect=OSError('private')):
            with self.assertRaises(SafeSMTPFailure) as caught:
                transmit(object(), 'example.invalid', 587, 'starttls')
            self.assertNotIn('private', str(caught.exception))

    def test_tls_and_login_failure_safe(self):
        for method in ('starttls', 'login'):
            with patch('ucon_trailcam_smtp.smtp_transport.smtplib.SMTP') as factory:
                client = factory.return_value.__enter__.return_value
                getattr(client, method).side_effect = OSError('private')
                with self.assertRaises(SafeSMTPFailure):
                    transmit(object(), 'example.invalid', 587, 'starttls', 'user', 'secret')
                client.send_message.assert_not_called()

    def test_submission_timeout_not_safe(self):
        with patch('ucon_trailcam_smtp.smtp_transport.smtplib.SMTP') as factory:
            client = factory.return_value.__enter__.return_value
            client.send_message.side_effect = TimeoutError
            with self.assertRaises(TimeoutError) as caught:
                transmit(object(), 'example.invalid', 587, 'starttls')
            self.assertNotIsInstance(caught.exception, SafeSMTPFailure)

    def test_quit_failure_after_acceptance(self):
        with patch('ucon_trailcam_smtp.smtp_transport.smtplib.SMTP') as factory:
            factory.return_value.__enter__.return_value.send_message.return_value = {}
            factory.return_value.__exit__.side_effect = OSError('QUIT')
            transmit(object(), 'example.invalid', 587, 'starttls')


class RetryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'queue.db'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(lambda: self.db.close())
        self.db.executescript('''CREATE TABLE events(camera_uid,itemid,et_utc,state);
            CREATE TABLE deliveries(camera_uid,itemid,message_id,accepted_utc);
            CREATE TABLE delivery_routes(camera_uid,itemid,route_json);
            INSERT INTO events VALUES ('a','1',100,'uncertain'),('a','2',200,'uncertain'),('b','1',100,'uncertain');
            INSERT INTO deliveries VALUES ('a','1','msg',NULL),('a','2','msg',NULL),('b','1','other',NULL);
            INSERT INTO delivery_routes VALUES ('a','1','{}'),('a','2','{}'),('b','1','{}');''')
        self.rows = [('a','1',100),('a','2',200)]

    def test_group_rollback_and_restart(self):
        self.assertEqual(rollback_unsent(self.db, self.rows, 'msg', 1000), 300)
        self.assertEqual(self.db.execute('SELECT state FROM events ORDER BY camera_uid,itemid').fetchall(), [('downloaded',),('downloaded',),('uncertain',)])
        self.assertEqual(self.db.execute('SELECT camera_uid FROM deliveries').fetchall(), [('b',)])
        self.assertEqual(self.db.execute('SELECT camera_uid FROM delivery_routes').fetchall(), [('b',)])
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.assertFalse(retry_due(self.db, 'a', 1299))
        self.assertTrue(retry_due(self.db, 'a', 1300))
        self.assertTrue(retry_due(self.db, 'b', 1000))

    def test_wrong_receipt_rolls_back_whole_group(self):
        with self.db:
            self.db.execute("UPDATE deliveries SET accepted_utc=500 WHERE camera_uid='a' AND itemid='2'")
        with self.assertRaises(ValueError):
            rollback_unsent(self.db, self.rows, 'msg', 1000)
        self.assertEqual(self.db.execute("SELECT count(*) FROM events WHERE state='uncertain'").fetchone()[0], 3)
        self.assertEqual(self.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 3)

    def test_backoff_and_clear(self):
        with self.db:
            self.db.execute('CREATE TABLE smtp_retries(camera_uid TEXT PRIMARY KEY,failures,last_failure,next_due)')
            self.db.execute("INSERT INTO smtp_retries VALUES ('a',10,100,200)")
        self.assertEqual(rollback_unsent(self.db, self.rows, 'msg', 1000), 3600)
        self.assertFalse(retry_due(self.db, 'a', 4599))
        clear_retry(self.db, 'a')
        self.assertTrue(retry_due(self.db, 'a', 1001))

    def test_shared_cooldown_across_historical_and_automatic_failures(self):
        self.assertEqual(record_setup_failure(self.db, 'a', 1000), 300)
        self.assertEqual(rollback_unsent(self.db, self.rows, 'msg', 1300), 600)
        self.assertEqual(record_setup_failure(self.db, 'a', 1900), 1200)
        self.assertEqual(self.db.execute('SELECT * FROM smtp_retries').fetchall(),
                         [('a', 3, 1900, 3100)])
        self.assertFalse(retry_due(self.db, 'a', 3099))
        self.assertTrue(retry_due(self.db, 'a', 3100))
        self.assertTrue(retry_due(self.db, 'b', 1000))
        clear_retry(self.db, 'a')
        self.assertTrue(retry_due(self.db, 'a', 1900))
