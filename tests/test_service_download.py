import json
import sqlite3
import unittest
from ucon_trailcam_smtp.download_retry import init_retry, reserve, RetryPolicy
from ucon_trailcam_smtp.service_download import plan_download, parse_batch_limit, effective_batch_limit
from types import SimpleNamespace


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

    def test_automatic_capture_age_and_boundary(self):
        now = 100 * 86400
        cutoff = now - 90 * 86400
        self.insert('expired', cutoff - 1)
        self.insert('boundary', cutoff)
        self.insert('recent', cutoff + 1)
        self.assertEqual(plan_download(self.db, 'a', now, 3),
                         (cutoff, cutoff + 3600, ['boundary','recent']))
        self.assertEqual(self.db.execute('SELECT count(*) FROM events').fetchone(), (3,))

    def test_configured_age_excludes_expired_originals(self):
        now = 100 * 86400
        self.insert('old', now - 2 * 86400)
        self.assertIsNone(plan_download(self.db, 'a', now, 3, automatic_days=1))

    def test_experimental_cap_and_bounded_window(self):
        for i in range(101):
            self.insert(f'photo-{i:03}', 100 + i * 10)
        begin, end, selected = plan_download(self.db, 'a', 5000, 100)
        self.assertEqual((begin, end), (100, 3700))
        self.assertEqual(selected, [f'photo-{i:03}' for i in range(100)])
        self.assertEqual(len(plan_download(self.db, 'a', 5000, 3)[2]), 3)
        for bad in (0, 101, True, 2.5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                plan_download(self.db, 'a', 5000, bad)

    def test_batch_config_and_explicit_override(self):
        self.assertEqual(parse_batch_limit(None), 3)
        self.assertEqual(parse_batch_limit({}, 10), 10)
        self.assertEqual(parse_batch_limit({'batch_limit': 100}, 3), 100)
        profile = SimpleNamespace(download_batch_limit=5)
        self.assertEqual(effective_batch_limit(profile), 5)
        self.assertEqual(effective_batch_limit(profile, 20), 20)
        for raw in ({'batch_limit': True}, {'batch_limit': 0}, {'batch_limit': 101},
                    {'batch_limit': '3'}, {'unknown': 3}, [], 3):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_batch_limit(raw)

    def test_bound_and_cooldown(self):
        self.insert('old', 100)
        self.insert('later', 4000)
        self.assertEqual(plan_download(self.db, 'a', 5000, 3), (100, 3700, ['old']))
        reserve(self.db, 'a', ['old'], 5000, RetryPolicy())
        self.assertEqual(plan_download(self.db, 'a', 5001, 3), (4000, 5002, ['later']))
