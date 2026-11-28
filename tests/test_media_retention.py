import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from ucon_trailcam_smtp.media_retention import Retention, parse_retention, cleanup


class RetentionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'media'
        self.root.mkdir(mode=0o700)
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE events(camera_uid,itemid,state,et_utc);
            CREATE TABLE downloads(camera_uid,itemid,path,sha256,size);
            CREATE TABLE deliveries(camera_uid,itemid,accepted_utc);''')
        self.now = 40*86400
        self.policy = Retention(True, 30)

    def add(self, ident, state='sent', accepted=100, *, uid='a', stamp=100):
        key = hashlib.sha256(json.dumps([uid, ident]).encode()).hexdigest()
        path = self.root / key / 'attempt-test' / 'original.jpg'
        path.parent.parent.mkdir(mode=0o700)
        path.parent.mkdir(mode=0o700)
        payload = b'original test bytes'
        path.write_bytes(payload)
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?,?)', (uid, ident, state, stamp))
            self.db.execute('INSERT INTO downloads VALUES (?,?,?,?,?)', (uid, ident, str(path), hashlib.sha256(payload).hexdigest(), len(payload)))
            self.db.execute('INSERT INTO deliveries VALUES (?,?,?)', (uid, ident, accepted))
        return path

    def run_cleanup(self, apply=False):
        return cleanup(self.db, self.root, self.policy, self.now, apply=apply, emit=lambda _: None)

    def test_configuration(self):
        self.assertEqual(parse_retention(None), Retention())
        for bad in ({'days': True}, {'days': 0}, {'enabled': 1}, {'other': 1}):
            with self.assertRaises(ValueError):
                parse_retention(bad)
        with self.assertRaises(ValueError):
            cleanup(self.db, self.root, Retention(False), self.now, apply=True)

    def test_automatic_age_configuration(self):
        from ucon_trailcam_smtp.media_retention import capture_cutoff
        self.assertEqual(parse_retention(None).automatic_days, 90)
        self.assertEqual(parse_retention({'automatic_days': 7}).automatic_days, 7)
        self.assertEqual(capture_cutoff(100 * 86400, 90), 10 * 86400)
        self.assertEqual(capture_cutoff(100, 90), 0)
        for value in (True, 0, -1, 3651, '90', 1.5):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_retention({'automatic_days': value})

    def test_default_24_hours_and_legacy_compatibility(self):
        self.assertTrue(parse_retention(None).enabled)
        self.assertEqual(parse_retention(None).image_seconds, 86400)
        self.assertEqual(parse_retention({'sent_image_hours': 2}).image_seconds, 7200)
        self.assertEqual(parse_retention({'enabled': False, 'days': 30}).image_seconds, 30 * 86400)
        self.assertFalse(parse_retention({'enabled': False}).enabled)
        for raw in ({'sent_image_hours': 0}, {'sent_image_hours': True},
                    {'sent_image_hours': 87601}, {'sent_image_hours': 24, 'days': 1}):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_retention(raw)

    def test_exact_acceptance_boundary(self):
        self.policy = parse_retention(None)
        old = self.add('boundary', accepted=self.now - 86400)
        new = self.add('recent', accepted=self.now - 86399)
        size = old.stat().st_size
        self.assertEqual(self.run_cleanup(True), (1, size, 0))
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_interrupted_after_unlink_reconciled_without_guessing(self):
        from unittest.mock import patch
        path = self.add('old')
        size = path.stat().st_size
        with patch('ucon_trailcam_smtp.media_retention.finish_cleanup',
                   side_effect=sqlite3.OperationalError('simulated interruption')):
            with self.assertRaises(sqlite3.OperationalError):
                self.run_cleanup(True)
        self.assertFalse(path.exists())
        self.assertEqual(self.db.execute('SELECT removed_utc,size FROM media_cleanup').fetchone(), (0,size))
        self.assertEqual(self.run_cleanup(True), (1,size,0))
        self.assertEqual(self.db.execute('SELECT removed_utc,size FROM media_cleanup').fetchone(), (self.now,size))

    def test_interrupted_before_unlink_retries_verified_file(self):
        from unittest.mock import patch
        path = self.add('old')
        size = path.stat().st_size
        with patch('ucon_trailcam_smtp.media_retention.os.unlink', side_effect=PermissionError):
            self.assertEqual(self.run_cleanup(True), (0,0,1))
        self.assertTrue(path.exists())
        self.assertEqual(self.db.execute('SELECT removed_utc FROM media_cleanup').fetchone(), (0,))
        # Even a longer configured interval cannot lose the committed intent.
        self.policy = Retention(True, 365)
        self.assertEqual(self.run_cleanup(True), (1,size,0))
        self.assertFalse(path.exists())

    def test_expire_pending_and_downloaded_but_not_boundary_or_uncertain(self):
        self.now = 100 * 86400
        cutoff = self.now - 90 * 86400
        expired = self.add('old', 'downloaded', stamp=cutoff-1)
        boundary = self.add('boundary', 'downloaded', stamp=cutoff)
        uncertain = self.add('uncertain', 'uncertain', None, stamp=100)
        conflict = self.add('conflict', 'downloaded', stamp=100)
        with self.db:
            self.db.execute("DELETE FROM deliveries WHERE itemid IN ('old','boundary')")
            self.db.execute("INSERT INTO events VALUES ('a','pending-old','pending',100)")
            self.db.execute("INSERT INTO events VALUES ('a','pending-new','pending',?)", (cutoff,))
        size = expired.stat().st_size
        self.assertEqual(self.run_cleanup(), (1,size,0))
        self.assertTrue(expired.exists())
        self.assertEqual(self.db.execute("SELECT state FROM events WHERE itemid='pending-old'").fetchone(), ('pending',))
        self.assertEqual(self.run_cleanup(True), (1,size,0))
        self.assertFalse(expired.exists())
        self.assertTrue(all(p.exists() for p in (boundary,uncertain,conflict)))
        self.assertEqual(dict(self.db.execute('SELECT itemid,state FROM events')), {
            'old':'expired','boundary':'downloaded','uncertain':'uncertain',
            'conflict':'downloaded','pending-old':'expired','pending-new':'pending'})
        self.assertEqual(self.run_cleanup(True), (0,0,0))

    def test_expired_intent_survives_config_change_and_interruption(self):
        from unittest.mock import patch
        self.now = 100 * 86400
        path = self.add('old', 'downloaded', stamp=100)
        with self.db:
            self.db.execute('DELETE FROM deliveries')
        size = path.stat().st_size
        with patch('ucon_trailcam_smtp.media_retention.finish_cleanup',
                   side_effect=sqlite3.OperationalError('interruption')):
            with self.assertRaises(sqlite3.OperationalError):
                self.run_cleanup(True)
        self.assertFalse(path.exists())
        self.assertEqual(self.db.execute('SELECT state FROM events').fetchone(), ('expired',))
        self.assertEqual(self.db.execute('SELECT removed_utc FROM media_cleanup').fetchone(), (0,))
        self.policy = Retention(True, 30, 365)
        self.assertEqual(self.run_cleanup(True), (1,size,0))
        self.assertEqual(self.db.execute('SELECT removed_utc FROM media_cleanup').fetchone(), (self.now,))

    def test_expired_pending_retires_download_alarm_without_recovery(self):
        from ucon_trailcam_smtp.download_retry import init_retry, reserve, record_failure, RetryPolicy
        from ucon_trailcam_smtp.health_alerts import observe
        self.now = 100 * 86400
        # Retry helper requires actual event metadata.
        self.db.execute("ALTER TABLE events ADD COLUMN metadata_json TEXT DEFAULT '{\"type\":1}'")
        init_retry(self.db)
        with self.db:
            self.db.execute("INSERT INTO events(camera_uid,itemid,state,et_utc) VALUES ('a','old','pending',100)")
        reserve(self.db, 'a', ['old'], 200, RetryPolicy())
        record_failure(self.db, 'a', 'old', 201, 'missing', RetryPolicy())
        observe(self.db, 'camera', 'a', healthy=False, now=201)
        with self.db:
            self.db.execute("UPDATE health_incidents SET last_notice=201")
        self.run_cleanup(True)
        self.assertEqual(self.db.execute('SELECT state FROM events').fetchone(), ('expired',))
        self.assertEqual(self.db.execute('SELECT count(*) FROM download_retries').fetchone(), (0,))
        self.assertEqual(self.db.execute('SELECT count(*) FROM health_incidents').fetchone(), (0,))

    def test_preview_no_changes(self):
        path = self.add('old')
        self.assertEqual(self.run_cleanup(), (1, path.stat().st_size, 0))
        self.assertTrue(path.exists())
        self.assertIsNone(self.db.execute("SELECT name FROM sqlite_master WHERE name='media_cleanup'").fetchone())

    def test_only_old_accepted_sent_and_receipts_retained(self):
        old = self.add('old')
        paths = [self.add('recent', accepted=self.now-100), self.add('uncertain', 'uncertain'),
                 self.add('downloaded', 'downloaded'), self.add('pending', 'pending'),
                 self.add('unaccepted', accepted=None)]
        size = old.stat().st_size
        self.assertEqual(self.run_cleanup(True), (1, size, 0))
        self.assertFalse(old.exists())
        self.assertTrue(all(p.exists() for p in paths))
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone()[0], 6)
        self.assertEqual(self.db.execute('SELECT count(*) FROM downloads').fetchone()[0], 6)
        self.assertEqual(self.db.execute('SELECT count(*) FROM deliveries').fetchone()[0], 6)
        self.assertEqual(self.db.execute('SELECT itemid,size FROM media_cleanup').fetchall(), [('old', size)])
        self.assertEqual(self.run_cleanup(True), (0,0,0))

    def test_group_writable_directory_retained(self):
        path = self.add('old')
        path.parent.parent.chmod(0o770)
        self.assertEqual(self.run_cleanup(True), (0,0,1))
        self.assertTrue(path.exists())
        self.assertEqual(self.db.execute('SELECT count(*) FROM media_cleanup').fetchone()[0], 0)

    def test_fixture_permissions_independent_of_umask(self):
        old = os.umask(0o002)
        try:
            path = self.add('old')
            self.assertEqual(self.run_cleanup(), (1, path.stat().st_size, 0))
        finally:
            os.umask(old)

    def test_modified_original_retained(self):
        path = self.add('old')
        path.write_bytes(b'changed')
        self.assertEqual(self.run_cleanup(True), (0,0,1))
        self.assertTrue(path.exists())

    def test_outside_root_and_symlinks_retained(self):
        outside = self.root.parent / 'external.jpg'
        outside.write_bytes(b'original test bytes')
        a = self.add('a')
        b = self.add('b')
        a.unlink()
        a.symlink_to(outside)
        with self.db:
            self.db.execute('UPDATE downloads SET path=? WHERE itemid=?', (str(outside), 'b'))
        self.assertEqual(self.run_cleanup(True), (0,0,2))
        self.assertTrue(a.is_symlink() and b.exists() and outside.exists())

    def test_shared_file_not_deleted(self):
        a = self.add('a')
        self.add('b', 'downloaded')
        with self.db:
            self.db.execute('UPDATE downloads SET path=? WHERE itemid=?', (str(a), 'b'))
        self.assertEqual(self.run_cleanup(True), (0,0,1))
        self.assertTrue(a.exists())

    def test_missing_file_not_marked_removed(self):
        path = self.add('old')
        path.unlink()
        self.assertEqual(self.run_cleanup(True), (0,0,1))
        self.assertEqual(self.db.execute('SELECT count(*) FROM media_cleanup').fetchone()[0], 0)

    def test_symlink_directory_not_followed(self):
        path = self.add('old')
        elsewhere = self.root.parent / 'moved'
        path.parent.rename(elsewhere)
        path.parent.symlink_to(elsewhere, target_is_directory=True)
        self.assertEqual(self.run_cleanup(True), (0,0,1))
        self.assertTrue((elsewhere / path.name).exists())
