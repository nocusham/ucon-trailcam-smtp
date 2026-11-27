import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from download_retry import (RetryPolicy, due_ids, init_retry, parse_retry, record_failure,
                            reserve, sync_download_health)
from health_alerts import AlertSettings, due_notices


class DownloadRetryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'test.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(lambda: self.db.close())
        with self.db:
            self.db.execute('CREATE TABLE events(camera_uid TEXT,itemid TEXT,et_utc INTEGER,state TEXT,metadata_json TEXT,PRIMARY KEY(camera_uid,itemid))')
            self.db.executemany('INSERT INTO events VALUES (?,?,?,?,?)', [
                ('a', 'old', 100, 'pending', json.dumps({'type': 1})),
                ('a', 'new', 200, 'pending', json.dumps({'type': 1})),
                ('a', 'video', 300, 'pending', json.dumps({'type': 2})),
                ('b', 'old', 100, 'pending', json.dumps({'type': 1}))])
        init_retry(self.db)
        self.policy = RetryPolicy()
        self.alerts = AlertSettings(enabled=True)

    def due(self, now, uid='a', limit=3):
        rows = self.db.execute('SELECT itemid,et_utc,state,metadata_json FROM events WHERE camera_uid=?', (uid,)).fetchall()
        return due_ids(self.db, uid, rows, 0, 1000, now, limit)

    def fail(self, ident, now, reason='download_timeout'):
        reserve(self.db, 'a', [ident], now, self.policy)
        record_failure(self.db, 'a', ident, now, reason, self.policy)

    def notices(self, now):
        sync_download_health(self.db, 'a', now, 86400)
        return due_notices(self.db, self.alerts, now, {'a': 'cam-a', 'b': 'cam-b'})

    def test_policy_validation(self):
        self.assertEqual(parse_retry(None), self.policy)
        self.assertEqual(self.policy.delay(0), 300)
        self.assertEqual(self.policy.delay(1), 600)
        self.assertEqual(self.policy.delay(100), 21600)
        for raw in ({'initial_minutes': True}, {'max_minutes': 1}, {'other': 2}):
            with self.assertRaises(ValueError):
                parse_retry(raw)

    def test_due_limit_and_uid_and_photo_filter(self):
        self.assertEqual(self.due(500, limit=1), ['old'])
        self.assertEqual(self.due(500), ['old', 'new'])
        self.assertEqual(self.due(500, uid='b'), ['old'])
        self.assertEqual(self.due(150), ['old'])

    def test_cooldown_persists_after_restart(self):
        self.fail('old', 500)
        self.db.close()
        self.db = sqlite3.connect(self.path)
        init_retry(self.db)
        self.assertEqual(self.due(799), ['new'])
        self.assertEqual(self.due(800), ['new', 'old'])
        self.fail('old', 800)
        self.assertEqual(self.due(1399), ['new'])
        self.assertEqual(self.due(1400), ['new', 'old'])

    def test_reservation_is_not_failure(self):
        reserve(self.db, 'a', ['old'], 500, self.policy)
        self.assertEqual(self.notices(100000), [])
        self.assertEqual(self.db.execute('SELECT failures FROM download_retries').fetchone()[0], 0)
        with self.assertRaises(ValueError):
            reserve(self.db, 'a', ['old'], 501, self.policy)

    def test_duplicate_failure_rejected(self):
        self.fail('old', 500)
        with self.assertRaises(ValueError):
            record_failure(self.db, 'a', 'old', 501, 'missing', self.policy)

    def test_single_failure_and_mixed_events_do_not_alarm(self):
        self.fail('old', 500)
        self.assertEqual(self.notices(86900), [])
        self.fail('new', 86900)
        self.assertEqual(self.notices(86900), [])

    def test_same_event_24h_alarm_and_recovery(self):
        self.fail('old', 500)
        self.fail('old', 86900, 'missing')
        self.assertEqual(len(self.notices(86900)), 1)
        with self.db:
            self.db.execute("UPDATE health_incidents SET last_notice=86900")
            self.db.execute("UPDATE events SET state='downloaded' WHERE camera_uid='a' AND itemid='new'")
        self.assertEqual(self.notices(86901), [])
        with self.db:
            self.db.execute("UPDATE events SET state='downloaded' WHERE camera_uid='a' AND itemid='old'")
        notice, = self.notices(86902)
        self.assertEqual(notice.recovered_at, 86902)
        self.assertEqual(self.due(86902), [])

    def test_reserve_rolls_back_if_other_row_invalid(self):
        with self.assertRaises(ValueError):
            reserve(self.db, 'a', ['old', 'video'], 500, self.policy)
        self.assertEqual(self.db.execute('SELECT count(*) FROM download_retries').fetchone()[0], 0)
