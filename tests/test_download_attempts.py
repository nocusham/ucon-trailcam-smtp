"""Synthetic incomplete attempt cleanup under a private managed root."""
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ucon_trailcam_smtp.download_attempts import register_attempt, cleanup_attempts
from ucon_trailcam_smtp.media_retention import parse_retention


DAY = 86400


class AttemptTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'media'
        self.root.mkdir(mode=0o700)
        self.path = Path(tmp.name) / 'queue.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE events(camera_uid,itemid,state);
            CREATE TABLE downloads(camera_uid,itemid,path);
            CREATE TABLE deliveries(camera_uid,itemid,accepted_utc);
        """)
        self.now = 20 * DAY

    def add(self, ident, *, age=7, name='photo.jpg', register=True):
        key = hashlib.sha256(json.dumps(['cam',ident]).encode()).hexdigest()
        attempt = self.root / key / 'attempt-test'
        attempt.parent.mkdir(mode=0o700)
        attempt.mkdir(mode=0o700)
        if name is not None:
            (attempt / name).write_bytes(b'partial')
            os.utime(attempt / name, (self.now-age*DAY,)*2)
        os.utime(attempt, (self.now-age*DAY,)*2)
        if register:
            register_attempt(self.path, 'cam', ident, attempt)
            with self.db:
                self.db.execute('UPDATE download_attempts SET created_utc=? WHERE path=?',
                                (self.now-age*DAY, str(attempt)))
        return attempt

    def cleanup(self, apply=True, days=7):
        return cleanup_attempts(self.db,self.root,self.now,days,apply=apply,emit=lambda _:None)

    def test_config(self):
        self.assertEqual(parse_retention(None).incomplete_days,7)
        self.assertEqual(parse_retention({'incomplete_days':3}).incomplete_days,3)
        for value in (0, True, '7', 3651):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_retention({'incomplete_days':value})

    def test_preview_boundary_and_empty_directory(self):
        a = self.add('old')
        b = self.add('empty', name=None)
        c = self.add('young', age=6)
        d = self.add('legacy', register=False)
        before = self.db.serialize()
        self.assertEqual(self.cleanup(False),(2,0))
        self.assertEqual(self.db.serialize(),before)
        self.assertTrue(all(p.exists() for p in (a,b,c,d)))
        self.assertEqual(self.cleanup(),(2,0))
        self.assertFalse(a.exists() or b.exists())
        self.assertTrue(c.exists() and d.exists())
        self.assertEqual(self.db.execute('SELECT count(*) FROM download_attempts').fetchone(),(1,))

    def test_recent_activity_preserved(self):
        a = self.add('old')
        os.utime(a/'photo.jpg',(self.now-1,)*2)
        self.assertEqual(self.cleanup(),(0,0))
        self.assertTrue(a.exists())

    def test_committed_and_uncertain_protected(self):
        a = self.add('committed')
        b = self.add('uncertain')
        c = self.add('receipt')
        with self.db:
            self.db.execute('INSERT INTO downloads VALUES (?,?,?)',('cam','committed',str(a/'photo.jpg')))
            self.db.execute("INSERT INTO events VALUES ('cam','uncertain','uncertain')")
            self.db.execute("INSERT INTO deliveries VALUES ('cam','receipt',NULL)")
        self.assertEqual(self.cleanup(),(0,3))
        self.assertTrue(all(p.exists() for p in (a,b,c)))

    def test_unknown_contents_and_symlink_and_hardlink_preserved(self):
        a = self.add('unknown',name='notes.txt')
        b = self.add('symlink',name=None)
        c = self.add('hardlink',name=None)
        outside = self.root.parent/'outside.jpg'
        outside.write_bytes(b'outside')
        (b/'photo.jpg').symlink_to(outside)
        os.link(outside,c/'photo.jpg')
        for p in (b,c):
            os.utime(p,(self.now-7*DAY,)*2)
        self.assertEqual(self.cleanup(),(0,3))
        self.assertTrue(outside.exists() and a.exists() and b.exists() and c.exists())

    def test_missing_attempt_reconciled(self):
        a = self.add('missing',name=None)
        a.rmdir()
        self.assertEqual(self.cleanup(),(1,0))
        self.assertEqual(self.db.execute('SELECT count(*) FROM download_attempts').fetchone(),(0,))
