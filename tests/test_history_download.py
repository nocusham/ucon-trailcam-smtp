"""Historical export isolation and verified original reuse."""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
from ucon_trailcam_smtp.history_download import export_history


class HistoryDownloadTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE events(camera_uid,itemid,et_utc,metadata_json,state);
            CREATE TABLE downloads(camera_uid,itemid,sd_time,path,sha256,size,width,height);
            CREATE TABLE deliveries(camera_uid,itemid,accepted_utc);
            CREATE TABLE media_cleanup(camera_uid,itemid,removed_utc,size);
        """)
        self.local={}
        self.remote={}
        self.events=[]
        self.calls=[]

    def raw(self,ident,stamp):
        return json.dumps({'itemid':ident,'et_utc':stamp,'type':1})

    def add(self,ident,stamp,state,*,original=False):
        raw=self.raw(ident,stamp)
        self.local[ident]=(stamp,state)
        self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',('a',ident,stamp,raw,state))
        if original:
            path=self.root/(ident+'.jpg')
            Image.new('RGB',(12,8)).save(path,'JPEG')
            data=path.read_bytes()
            self.db.execute('INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?)',
                            ('a',ident,stamp,str(path),hashlib.sha256(data).hexdigest(),len(data),12,8))
            return path

    def cloud(self,ident,stamp):
        self.remote[ident]=(stamp,self.raw(ident,stamp))

    def sd(self,*stamps):
        self.events=[SimpleNamespace(start_time=t,event_type=4,length=65535) for t in stamps]

    @contextmanager
    def relay(self,begin,end):
        self.calls.append((begin,end))
        def fetch(event,dest):
            Image.new('RGB',(12,8)).save(dest,'JPEG')
            return dest
        yield self.events,fetch

    def run_export(self,limit=3):
        before=self.db.serialize()
        code=export_history(self.db,'a',self.local,self.remote,self.root/'exports',
                            limit,self.relay,emit=lambda _:None)
        self.assertEqual(self.db.serialize(),before)
        folder=next((self.root/'exports').iterdir())
        records=[json.loads(line) for line in (folder/'manifest.jsonl').read_text().splitlines()]
        return code,folder,records

    def test_reuses_verified_copy_without_relay(self):
        original=self.add('a',100,'sent',original=True)
        code,root,records=self.run_export()
        self.assertEqual((code,self.calls),(0,[]))
        self.assertEqual(records[0]['source'],'local')
        self.assertEqual((root/records[0]['file']).read_bytes(),original.read_bytes())
        self.assertEqual((root/records[0]['file']).stat().st_mode&0o777,0o600)

    def test_missing_historical_and_unknown_export_without_queue_import(self):
        self.add('a',100,'expired')
        self.cloud('b',200)
        self.sd(100,200)
        code,root,records=self.run_export(limit=1)
        self.assertEqual(code,0)
        self.assertEqual(len(self.calls),2)
        self.assertEqual([r['prior_state'] for r in records],['expired','unknown_history'])
        self.assertTrue(all((root/r['file']).exists() for r in records))

    def test_cleaned_original_downloaded_again(self):
        path=self.add('a',100,'sent',original=True)
        size=path.stat().st_size
        path.unlink()
        self.db.execute('INSERT INTO media_cleanup VALUES (?,?,?,?)',('a','a',200,size))
        self.sd(100)
        code,_,records=self.run_export()
        self.assertEqual(code,0)
        self.assertEqual(records[0]['source'],'sd')
        self.assertFalse(path.exists())

    def test_modified_original_refused_not_silently_replaced(self):
        path=self.add('a',100,'downloaded',original=True)
        Image.new('RGB',(13,8)).save(path,'JPEG')
        with self.assertRaisesRegex(ValueError,'verification'):
            self.run_export()
        self.assertEqual(self.calls,[])

    def test_uncertain_and_ambiguous_and_missing_skipped(self):
        self.add('a',100,'uncertain')
        self.cloud('b',200)
        self.cloud('c',201)
        self.cloud('d',400)
        self.sd(100,200)
        code,_,records=self.run_export()
        self.assertEqual(code,1)
        self.assertEqual(records,[])

    def test_sd_claim_by_other_event_protects_identity(self):
        self.cloud('a',100)
        self.db.execute('INSERT INTO downloads VALUES (?,?,?,?,?,?,?,?)',
                        ('a','other',100,'/unused','digest',1,1,1))
        self.sd(100)
        code,_,records=self.run_export()
        self.assertEqual((code,records),(1,[]))
