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
        self.db.executescript('''CREATE TABLE events(camera_uid,itemid,state);
            CREATE TABLE downloads(camera_uid,itemid,path,sha256,size);
            CREATE TABLE deliveries(camera_uid,itemid,accepted_utc);''')
        self.now = 40*86400
        self.policy = Retention(True, 30)

    def add(self, ident, state='sent', accepted=100, *, uid='a'):
        key = hashlib.sha256(json.dumps([uid, ident]).encode()).hexdigest()
        path = self.root / key / 'attempt-test' / 'original.jpg'
        path.parent.parent.mkdir(mode=0o700)
        path.parent.mkdir(mode=0o700)
        payload = b'original test bytes'
        path.write_bytes(payload)
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?)', (uid, ident, state))
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
            cleanup(self.db, self.root, Retention(), self.now, apply=True)

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
