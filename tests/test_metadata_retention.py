"""Offline terminal metadata and delivery receipt retention."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from ucon_trailcam_smtp.event_queue import ingest_events, open_queue
from ucon_trailcam_smtp.media_retention import cleanup, prune_metadata, parse_retention


DAY = 86400


class MetadataRetentionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'media'
        self.root.mkdir(mode=0o700)
        self.path = Path(tmp.name) / 'queue.sqlite3'
        self.db = open_queue(self.path)
        self.addCleanup(self.db.close)
        self.now = 200 * DAY
        with self.db:
            self.db.executescript("""
                CREATE TABLE downloads(camera_uid,itemid,path,sha256,size);
                CREATE TABLE deliveries(camera_uid,itemid,accepted_utc);
                CREATE TABLE delivery_routes(camera_uid,itemid,route_json);
                CREATE TABLE download_retries(camera_uid,itemid,failures);
            """)

    def add(self, ident, state, capture, accepted=None, *, original=False):
        raw = json.dumps({'itemid':ident,'et_utc':capture,'type':1,'battery':87,'ai_result':'fixture'})
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)', ('cam',ident,capture,raw,state))
            if state in ('sent','uncertain'):
                self.db.execute('INSERT INTO deliveries VALUES (?,?,?)', ('cam',ident,accepted))
                self.db.execute('INSERT INTO delivery_routes VALUES (?,?,?)', ('cam',ident,'{}'))
            if original:
                key = hashlib.sha256(json.dumps(['cam',ident]).encode()).hexdigest()
                folder = self.root / key / 'attempt-fixture'
                folder.parent.mkdir(mode=0o700)
                folder.mkdir(mode=0o700)
                path = folder / 'original.jpg'
                path.write_bytes(b'original')
                self.db.execute('INSERT INTO downloads VALUES (?,?,?,?,?)',
                                ('cam',ident,str(path),hashlib.sha256(b'original').hexdigest(),8))
                return path

    def policy(self, **options):
        return parse_retention(options)

    def prune(self, policy=None, apply=True):
        return prune_metadata(self.db, self.root, policy or self.policy(), self.now,
                              apply=apply, emit=lambda _: None)

    def clean(self, policy=None):
        return cleanup(self.db, self.root, policy or self.policy(), self.now,
                       apply=True, emit=lambda _: None)

    def event(self, ident):
        return self.db.execute('SELECT state,metadata_json FROM events WHERE itemid=?', (ident,)).fetchone()

    def test_config_defaults_and_validation(self):
        self.assertEqual((self.policy().metadata_days,self.policy().delivery_receipt_days),(90,90))
        self.assertEqual((self.policy(metadata_days=7,delivery_receipt_days=30).metadata_days,
                          self.policy(metadata_days=7,delivery_receipt_days=30).delivery_receipt_days),(7,30))
        for key in ('metadata_days','delivery_receipt_days'):
            for value in (True,0,3651,'90'):
                with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                    self.policy(**{key:value})

    def test_compact_metadata_while_receipt_still_needed(self):
        path = self.add('a','sent',self.now-100*DAY,self.now-2*DAY,original=True)
        self.clean()
        before = self.db.serialize()
        self.assertEqual(self.prune(apply=False),(1,0,0))
        self.assertEqual(self.db.serialize(),before)
        self.assertEqual(self.prune(),(1,0,0))
        self.assertFalse(path.exists())
        state, raw = self.event('a')
        self.assertEqual(state,'sent')
        self.assertEqual(set(json.loads(raw)),{'itemid','et_utc','type'})
        self.assertEqual(self.db.execute('SELECT count(*) FROM deliveries').fetchone(),(1,))
        self.assertEqual(self.prune(),(0,0,0))

    def test_short_receipt_keeps_dedup_marker_and_replay(self):
        stamp = self.now-40*DAY
        self.add('a','sent',stamp,self.now-31*DAY,original=True)
        policy = self.policy(metadata_days=7,delivery_receipt_days=30)
        self.clean(policy)
        self.assertEqual(self.prune(policy),(1,1,0))
        self.assertEqual(self.event('a')[0],'sent_history')
        for table in ('deliveries','delivery_routes','downloads','media_cleanup'):
            self.assertEqual(self.db.execute(f'SELECT count(*) FROM {table}').fetchone(),(0,))
        self.assertEqual(ingest_events(self.path,'cam',[{'uid':'cam','itemid':'a','et_utc':stamp,'type':1}]),(0,1,0,0))
        self.now += 51*DAY
        self.assertEqual(self.prune(policy),(0,0,1))
        self.assertIsNone(self.event('a'))

    def test_long_metadata_kept_after_receipt_expiry(self):
        self.add('a','sent',self.now-100*DAY,self.now-99*DAY,original=True)
        policy = self.policy(metadata_days=120,delivery_receipt_days=30)
        self.clean(policy)
        self.assertEqual(self.prune(policy),(0,1,0))
        self.assertEqual(self.event('a')[0],'sent_history')
        self.assertEqual(json.loads(self.event('a')[1])['battery'],87)
        self.now += 20*DAY
        self.assertEqual(self.prune(policy),(0,0,1))

    def test_unresolved_and_unfinished_cleanup_preserved(self):
        for ident,state in [('pending','pending'),('downloaded','downloaded'),('uncertain','uncertain')]:
            self.add(ident,state,self.now-100*DAY,original=state!='pending')
        path = self.add('sent','sent',self.now-100*DAY,self.now-99*DAY,original=True)
        self.assertEqual(self.prune(),(0,0,0))
        self.assertTrue(path.exists())
        for ident in ('pending','downloaded','uncertain','sent'):
            self.assertEqual(json.loads(self.event(ident)[1])['battery'],87)
        self.clean()
        path.parent.parent.mkdir(mode=0o700)
        path.parent.mkdir(mode=0o700)
        path.write_bytes(b'reappeared')
        self.prune()
        self.assertEqual(self.event('sent')[0],'sent')

    def test_expired_and_accepted_boundary(self):
        self.add('expired','expired',self.now-90*DAY)
        self.add('sent','sent',self.now-100*DAY,self.now-90*DAY,original=True)
        self.clean()
        self.assertEqual(self.prune(),(1,0,1))
        self.assertIsNone(self.event('sent'))
        self.assertEqual(self.event('expired')[0],'expired')
        self.now += 1
        self.assertEqual(self.prune(),(0,0,1))
