"""Synthetic read-only historical preview; no network or SMTP."""
import datetime as dt
import json
import sqlite3
import unittest
from unittest.mock import patch

from ucon_trailcam_smtp.history import collect_preview, date_range
from ucon_trailcam_smtp.trailcam_service import main


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE events(camera_uid,itemid,et_utc,metadata_json,state)')
        self.calls = []
        self.remote = []

    def add(self, ident, stamp, state, uid='a', kind=1):
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                            (uid,ident,stamp,json.dumps({'type':kind}),state))

    def photo(self, ident, stamp, uid='a', kind=1):
        return {'uid':uid,'itemid':ident,'et_utc':stamp,'type':kind}

    async def query(self, uid, begin, end):
        self.calls.append((uid,begin,end))
        return {'items':[i for i in self.remote if begin <= i['et_utc'] <= end]}

    async def test_union_boundary_scope_and_readonly(self):
        self.add('sent',100,'sent')
        self.add('old',101,'sent_history')
        self.add('pending',102,'pending')
        self.add('uncertain',103,'uncertain')
        self.add('expired',104,'expired')
        self.add('ready',105,'downloaded')
        self.add('other',100,'sent','b')
        self.add('video',100,'pending',kind=2)
        self.remote = [self.photo('sent',100), self.photo('boundary',3700),
                       self.photo('outside',7300),self.photo('other',100,'b'),
                       self.photo('video',100,kind=2)]
        before = self.db.serialize()
        counts = await collect_preview(self.db,'a',100,7300,self.query)
        self.assertEqual(self.calls,[('a',100,3700),('a',3700,7300)])
        self.assertEqual(counts['total'],7)
        self.assertEqual(counts['unknown_history'],1)
        self.assertEqual(counts['local_only'],5)
        self.assertEqual(counts['cloud_and_local'],1)
        for state in ('pending','downloaded','sent','sent_history','uncertain','expired'):
            self.assertEqual(counts[state],1)
        self.assertEqual(self.db.serialize(),before)

    async def test_local_cloud_conflict_and_no_state_change(self):
        self.add('a',100,'sent')
        self.remote = [self.photo('a',101)]
        before = self.db.serialize()
        with self.assertRaisesRegex(ValueError,'identity conflict'):
            await collect_preview(self.db,'a',100,200,self.query)
        self.assertEqual(self.db.serialize(),before)

    async def test_cloud_conflict_and_invalid_response(self):
        self.remote = [self.photo('a',100),self.photo('a',101)]
        with self.assertRaisesRegex(ValueError,'identity conflict'):
            await collect_preview(self.db,'a',100,200,self.query)
        async def bad(*args):
            return {'items':None}
        with self.assertRaises(ValueError):
            await collect_preview(self.db,'a',100,200,bad)

    async def test_no_fixed_range_cap_and_bounded_requests(self):
        begin = 100
        end = begin+32*86400
        counts = await collect_preview(self.db,'a',begin,end,self.query,emit=lambda _:None)
        self.assertEqual(counts['total'],0)
        self.assertEqual(len(self.calls),32*24)
        self.assertEqual(self.calls[-1][-1],end)
        self.assertTrue(all(e-b<=3600 for _,b,e in self.calls))

    def test_date_range_inclusive_dst_and_future_clamp(self):
        day = dt.date(2026,3,29)
        begin,end = date_range(day,day,'Europe/Berlin',2000000000)
        self.assertEqual(end-begin,23*3600)
        self.assertEqual(date_range(day,day,'Europe/Berlin',begin+10),(begin,begin+11))
        with self.assertRaises(ValueError):
            date_range(day,day-dt.timedelta(days=1),'Europe/Berlin',2000000000)
        with self.assertRaises(ValueError):
            date_range(day,day,'Europe/Berlin',begin-1)

    def test_service_dispatch_without_live_actions(self):
        with patch('ucon_trailcam_smtp.history.main',return_value=17) as history:
            self.assertEqual(main(['history','--help']),17)
        history.assert_called_once_with(['--help'])

    async def test_failed_window_aborts_without_partial_result(self):
        self.add('a',100,'sent')
        before = self.db.serialize()
        async def fail(uid,b,e):
            if b>100:
                raise RuntimeError('fixture failure')
            return {'items':[self.photo('new',101)]}
        with self.assertRaises(RuntimeError):
            await collect_preview(self.db,'a',100,7300,fail)
        self.assertEqual(self.db.serialize(),before)
