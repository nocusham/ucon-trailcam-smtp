import json
import sqlite3
import unittest
from ucon_trailcam_smtp.download_retry import init_retry, reserve, RetryPolicy
from ucon_trailcam_smtp.service_download import plan_download


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        with self.db:
            self.db.execute('CREATE TABLE events(camera_uid TEXT,itemid TEXT,et_utc INTEGER,state TEXT,metadata_json TEXT,PRIMARY KEY(camera_uid,itemid))')
        init_retry(self.db)

    def insert(self, ident, stamp, state='pending', uid='a', kind=1):
        with self.db:
            self.db.execute('INSERT INTO events VALUES (?,?,?,?,?)', (uid, ident, stamp, state, json.dumps({'type':kind})))

    def test_no_due(self):
        self.insert('sent', 1, 'sent')
        self.insert('video', 2, kind=2)
        self.insert('other', 3, uid='b')
        self.insert('future', 500)
        self.assertIsNone(plan_download(self.db, 'a', 100, 3))

    def test_cross_midnight_without_full_day_scan(self):
        self.insert('before', 86399)
        self.insert('after', 86401)
        self.assertEqual(plan_download(self.db, 'a', 86410, 3), (86399, 86411, ['before','after']))

    def test_bound_and_cooldown(self):
        self.insert('old', 100)
        self.insert('later', 4000)
        self.assertEqual(plan_download(self.db, 'a', 5000, 3), (100, 3700, ['old']))
        reserve(self.db, 'a', ['old'], 5000, RetryPolicy())
        self.assertEqual(plan_download(self.db, 'a', 5001, 3), (4000, 5002, ['later']))
