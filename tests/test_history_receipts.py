"""Historical evidence and automatic-delivery guards, no live SMTP."""
import json
import sqlite3
import unittest
from ucon_trailcam_smtp.history_receipts import reserve,finish,rollback_unsent,protected,camera_uncertain
from ucon_trailcam_smtp.history import local_events
from ucon_trailcam_smtp.queue_smtp import ready_rows,begin_delivery,DeliveryError
from ucon_trailcam_smtp.download_retry import init_retry,due_ids
from ucon_trailcam_smtp.media_retention import expire_pending


class HistoryReceiptTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE events(camera_uid,itemid,et_utc,metadata_json,state);
            CREATE TABLE downloads(camera_uid,itemid,sd_time,path,sha256,size,width,height);
            CREATE TABLE deliveries(camera_uid,itemid,message_id,started_utc,accepted_utc);
        """)
        init_retry(self.db)

    def record(self,ident,stamp=100):
        return dict(camera_uid='a',itemid=ident,et_utc=stamp,
                    metadata=dict(itemid=ident,et_utc=stamp,type=1),
                    path='/fixture/export.jpg',sha256='a'*64,size=123)

    def add(self,ident,state,stamp=100):
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                ('a',ident,stamp,json.dumps(self.record(ident,stamp)['metadata']),state))

    def reserve(self,ident='a',message='m',**kw):
        reserve(self.db,'a',[self.record(ident)],message,200,{},**kw)

    def test_unknown_requires_explicit_permission_and_is_visible(self):
        with self.assertRaisesRegex(ValueError,'allow-unknown-history'):
            self.reserve()
        self.reserve(allow_unknown=True)
        self.assertTrue(camera_uncertain(self.db,'a'))
        self.assertEqual(local_events(self.db,'a',1,300),{'a':(100,'uncertain')})
        finish(self.db,'a','m',201,1)
        self.assertEqual(local_events(self.db,'a',1,300),{'a':(100,'sent_history')})
        with self.assertRaisesRegex(ValueError,'resend'):
            self.reserve(message='m2',allow_unknown=True)

    def test_resend_preserves_primary_and_historical_acceptances(self):
        self.add('a','sent')
        with self.db:
            self.db.execute("INSERT INTO deliveries VALUES ('a','a','original',101,102)")
        with self.assertRaisesRegex(ValueError,'resend'):
            self.reserve()
        self.reserve(resend=True)
        finish(self.db,'a','m',201,1)
        self.reserve(message='m2',resend=True)
        rollback_unsent(self.db,'a','m2',1)
        self.assertEqual(self.db.execute('SELECT message_id,accepted_utc FROM historical_deliveries').fetchall(),[('m',201)])
        self.assertEqual(self.db.execute('SELECT message_id,accepted_utc FROM deliveries').fetchall(),[('original',102)])

    def test_unresolved_camera_blocks_new_reservation(self):
        self.add('a','pending')
        self.add('b','pending')
        self.reserve()
        with self.assertRaisesRegex(ValueError,'unresolved'):
            self.reserve('b','m2',resend=True,allow_unknown=True)
        self.assertFalse(camera_uncertain(self.db,'b'))
        rollback_unsent(self.db,'a','m',1)
        self.assertFalse(protected(self.db,'a','a'))

    def test_automatic_selection_and_begin_guard(self):
        self.add('a','downloaded')
        self.add('b','downloaded')
        self.reserve()
        finish(self.db,'a','m',201,1)
        self.assertEqual([r[1] for r in ready_rows(self.db,1,300,3)],['b'])
        with self.assertRaisesRegex(DeliveryError,'Historical receipt'):
            begin_delivery(self.db,[('a','a',100)],'auto')
        self.assertEqual(self.db.execute('SELECT count(*) FROM deliveries').fetchone(),(0,))

    def test_download_and_expiration_guard(self):
        self.add('a','pending')
        self.add('b','pending')
        self.reserve()
        finish(self.db,'a','m',201,1)
        rows=self.db.execute('SELECT itemid,et_utc,state,metadata_json FROM events').fetchall()
        self.assertEqual(due_ids(self.db,'a',rows,1,300,200,3),['b'])
        self.assertEqual(expire_pending(self.db,300,apply=True),1)
        self.assertEqual(dict(self.db.execute('SELECT itemid,state FROM events')),{'a':'pending','b':'expired'})

    def test_group_reservation_rolls_back_on_conflict(self):
        self.add('a','pending')
        with self.assertRaisesRegex(ValueError,'allow-unknown-history'):
            reserve(self.db,'a',[self.record('a'),self.record('b')],'m',200,{})
        self.assertFalse(protected(self.db,'a','a'))

    def test_uncertain_original_never_overridden(self):
        self.add('a','uncertain')
        with self.assertRaisesRegex(ValueError,'unresolved'):
            self.reserve(resend=True,allow_unknown=True)
