"""Synthetic SMTP dispatch; no network, sleep or real credentials."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from PIL import Image
from ucon_trailcam_smtp.camera_smtp import Camera
from ucon_trailcam_smtp.history_send import send_export,preflight,eligible
from ucon_trailcam_smtp.history_receipts import camera_uncertain
from ucon_trailcam_smtp.smtp_pacing import Pacer,NANOSECONDS
from ucon_trailcam_smtp.smtp_transport import SafeSMTPFailure
from ucon_trailcam_smtp.smtp_retry import retry_due


class HistorySendTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE events(camera_uid,itemid,et_utc,metadata_json,state);
            CREATE TABLE deliveries(camera_uid,itemid,message_id,started_utc,accepted_utc);
        """)
        self.profile=Camera('fixture','a',True,'smtp.example.invalid',587,'starttls',
                            's@example.invalid','r@example.invalid','user','PASS','single',3)
        self.now=1000
        self.pacer=Pacer(self.db,30,clock=lambda:self.now*NANOSECONDS)
        self.send=Mock()
        self.sleeps=0

    def add(self,ident,stamp,state='pending'):
        folder=self.root/ident
        folder.mkdir()
        path=folder/'original.jpg'
        Image.new('RGB',(12,8)).save(path,'JPEG')
        data=path.read_bytes()
        meta=dict(itemid=ident,et_utc=stamp,type=1)
        if state!='unknown_history':
            with self.db:
                self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',('a',ident,stamp,json.dumps(meta),state))
        rec=dict(camera_uid='a',itemid=ident,et_utc=stamp,prior_state=state,metadata=meta,
                 sd_time=stamp,file=path.relative_to(self.root).as_posix(),
                 sha256=hashlib.sha256(data).hexdigest(),size=len(data),width=12,height=8)
        with (self.root/'manifest.jsonl').open('a') as out:
            out.write(json.dumps(rec)+'\n')
        return path

    def sleep(self,n):
        self.sleeps+=1
        self.now+=n

    def run_send(self,**kw):
        return send_export(self.db,self.profile,self.root,self.pacer,self.send,
                           sleep=self.sleep,now=lambda:self.now,emit=lambda _:None,**kw)

    def test_order_and_shared_pacing(self):
        self.add('b',200)
        self.add('a',100)
        self.assertTrue(self.pacer.reserve())
        self.assertEqual(self.run_send(),0)
        self.assertEqual(self.sleeps,60)
        self.assertEqual(self.send.call_count,2)
        self.assertEqual(self.db.execute('SELECT itemid,accepted_utc FROM historical_deliveries ORDER BY accepted_utc').fetchall(),
                         [('a',1030),('b',1060)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM deliveries').fetchone(),(0,))

    def test_unknown_and_known_require_explicit_flags(self):
        self.add('a',100,'unknown_history')
        with self.assertRaises(ValueError):
            self.run_send()
        self.send.assert_not_called()
        self.assertEqual(self.run_send(allow_unknown=True),0)
        self.assertFalse(eligible('sent',allow_unknown=True))
        self.assertFalse(eligible('unknown_history',resend=True))
        self.assertFalse(eligible('uncertain',True,True))

    def test_safe_failure_rolls_back_and_cooldown(self):
        self.add('a',100)
        self.send.side_effect=SafeSMTPFailure('fixture')
        self.assertEqual(self.run_send(),1)
        self.assertFalse(camera_uncertain(self.db,'a'))
        self.assertEqual(self.db.execute('SELECT count(*) FROM historical_deliveries').fetchone(),(0,))
        self.assertFalse(retry_due(self.db,'a',self.now))
        self.assertFalse(self.pacer.due())

    def test_uncertain_blocks_later_mail_and_preflight(self):
        self.add('a',100)
        self.add('b',200)
        self.send.side_effect=RuntimeError('fixture')
        self.assertEqual(self.run_send(),1)
        self.send.assert_called_once()
        self.assertTrue(camera_uncertain(self.db,'a'))
        with self.assertRaises(ValueError):
            preflight(self.db,self.profile,{'PASS':'test'},now=self.now)
        self.assertEqual(self.db.execute('SELECT accepted_utc FROM historical_deliveries').fetchall(),[(None,)])

    def test_changed_export_stops_before_any_attempt(self):
        self.add('a',100)
        path=self.add('b',200)
        Image.new('RGB',(14,8)).save(path,'JPEG')
        with self.assertRaises(Exception):
            self.run_send()
        self.send.assert_not_called()
        self.assertTrue(self.pacer.due())

    def test_grouped_uses_one_slot(self):
        from dataclasses import replace
        self.profile=replace(self.profile,mode='grouped')
        self.add('a',100)
        self.add('b',200)
        self.assertEqual(self.run_send(),0)
        self.send.assert_called_once()
        self.assertEqual(len(list(self.send.call_args.args[0].iter_attachments())),2)
        self.assertEqual(self.db.execute('SELECT count(DISTINCT message_id) FROM historical_deliveries').fetchone(),(1,))

    def test_preflight_password_and_original_uncertain(self):
        with self.assertRaises(ValueError):
            preflight(self.db,self.profile,{},now=self.now)
        self.assertEqual(preflight(self.db,self.profile,{'PASS':'test'},now=self.now),'test')
        self.add('a',100,'uncertain')
        with self.assertRaises(ValueError):
            preflight(self.db,self.profile,{'PASS':'test'},now=self.now)
