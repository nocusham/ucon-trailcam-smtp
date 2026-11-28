"""Synthetic integration of historical acceptance and managed retention."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ucon_trailcam_smtp.history_receipts import reserve, finish, protected
from ucon_trailcam_smtp.media_retention import cleanup, prune_metadata, parse_retention
from ucon_trailcam_smtp.history import local_events

DAY=86400


class HistoryRetentionTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)/'media'
        self.root.mkdir(mode=0o700)
        self.external=Path(tmp.name)/'export.jpg'
        self.external.write_bytes(b'export preserved')
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE events(camera_uid,itemid,et_utc,metadata_json,state);
            CREATE TABLE downloads(camera_uid,itemid,path,sha256,size);
            CREATE TABLE deliveries(camera_uid,itemid,accepted_utc);
        """)
        self.now=200*DAY
        self.policy=parse_retention(None)

    def add(self,ident,stamp,accepted,state='downloaded',original=True):
        meta=dict(itemid=ident,et_utc=stamp,type=1,battery=90)
        path=None
        with self.db:
            if state is not None:
                self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',('a',ident,stamp,json.dumps(meta),state))
            if original:
                key=hashlib.sha256(json.dumps(['a',ident]).encode()).hexdigest()
                path=self.root/key/'attempt-test'/'original.jpg'
                path.parent.mkdir(mode=0o700,parents=True)
                path.write_bytes(b'original')
                self.db.execute('INSERT INTO downloads VALUES (?,?,?,?,?)',
                    ('a',ident,str(path),hashlib.sha256(b'original').hexdigest(),8))
        rec=dict(camera_uid='a',itemid=ident,et_utc=stamp,metadata=meta,
                 path=str(self.external),sha256=hashlib.sha256(self.external.read_bytes()).hexdigest(),size=self.external.stat().st_size)
        reserve(self.db,'a',[rec],ident,accepted if accepted else self.now-1,{},allow_unknown=True)
        if accepted:
            finish(self.db,'a',ident,accepted,1)
        return path

    def clean(self,apply=True):
        return cleanup(self.db,self.root,self.policy,self.now,apply=apply,emit=lambda _:None)

    def prune(self,apply=True):
        return prune_metadata(self.db,self.root,self.policy,self.now,apply=apply,emit=lambda _:None)

    def test_manual_original_acceptance_boundary_and_export_untouched(self):
        a=self.add('a',self.now-100*DAY,self.now-DAY)
        b=self.add('b',self.now-100*DAY,self.now-DAY+1)
        before=self.db.serialize()
        self.assertEqual(self.clean(False),(1,8,0))
        self.assertEqual(self.db.serialize(),before)
        self.assertEqual(self.clean(),(1,8,0))
        self.assertFalse(a.exists())
        self.assertTrue(b.exists() and self.external.exists())
        self.assertEqual(dict(self.db.execute('SELECT itemid,state FROM events')),{'a':'sent_manual','b':'sent_manual'})
        self.assertEqual(local_events(self.db,'a',1,self.now),{'a':(self.now-100*DAY,'sent_history'),'b':(self.now-100*DAY,'sent_history')})

    def test_unresolved_protects_original_and_metadata(self):
        a=self.add('a',100,None)
        before=self.db.serialize()
        self.assertEqual(self.clean(),(0,0,0))
        self.prune()
        self.assertEqual(self.db.serialize(),before)
        self.assertTrue(a.exists() and self.external.exists())

    def test_failed_cleanup_keeps_last_receipt(self):
        a=self.add('a',100,self.now-100*DAY)
        a.write_bytes(b'changed!')
        self.assertEqual(self.clean(),(0,0,1))
        self.prune()
        self.assertTrue(protected(self.db,'a','a'))
        self.assertTrue(a.exists())

    def test_reconciled_cleanup_and_receipt_retirement(self):
        self.add('a',100,self.now-100*DAY)
        self.assertEqual(self.clean(),(1,8,0))
        self.prune()
        self.assertFalse(protected(self.db,'a','a'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone(),(0,))
        self.assertEqual(self.db.execute('SELECT count(*) FROM downloads').fetchone(),(0,))
        self.assertTrue(self.external.exists())

    def test_cloud_only_marker_survives_short_receipt_period(self):
        self.policy=parse_retention({'delivery_receipt_days':7,'metadata_days':7})
        stamp=self.now-20*DAY
        self.add('a',stamp,self.now-10*DAY,state=None,original=False)
        self.clean()
        self.prune()
        self.assertFalse(protected(self.db,'a','a'))
        self.assertEqual(local_events(self.db,'a',1,self.now),{'a':(stamp,'sent_history')})
        self.now+=71*DAY
        self.prune()
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone(),(0,))

    def test_pending_manual_success_never_returns_to_automatic_queue(self):
        self.policy=parse_retention({'delivery_receipt_days':7})
        self.add('a',self.now-20*DAY,self.now-10*DAY,state='pending',original=False)
        self.clean()
        self.prune()
        self.assertEqual(self.db.execute('SELECT state FROM events').fetchone(),('sent_history',))
        self.assertFalse(protected(self.db,'a','a'))

    def test_interrupted_unlink_reconciles(self):
        a=self.add('a',100,self.now-100*DAY)
        with patch('ucon_trailcam_smtp.media_retention.finish_cleanup',side_effect=sqlite3.OperationalError):
            with self.assertRaises(sqlite3.OperationalError):
                self.clean()
        self.assertFalse(a.exists())
        self.prune()
        self.assertTrue(protected(self.db,'a','a'))
        self.assertEqual(self.clean(),(1,8,0))
        self.prune()
        self.assertFalse(protected(self.db,'a','a'))


    def test_automatic_and_manual_receipt_ages_remain_independent(self):
        stamp=self.now-100*DAY
        path=self.add('a',stamp,self.now-2*DAY)
        with self.db:
            self.db.execute("UPDATE events SET state='sent' WHERE itemid='a'")
            self.db.execute("INSERT INTO deliveries VALUES ('a','a',?)",(self.now-99*DAY,))
        self.assertEqual(self.clean(),(1,8,0))
        self.prune()
        self.assertFalse(path.exists())
        self.assertEqual(self.db.execute('SELECT count(*) FROM deliveries').fetchone(),(0,))
        self.assertTrue(protected(self.db,'a','a'))
        self.assertEqual(local_events(self.db,'a',1,self.now),{'a':(stamp,'sent_history')})
        self.now+=89*DAY
        self.prune()
        self.assertFalse(protected(self.db,'a','a'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone(),(0,))
