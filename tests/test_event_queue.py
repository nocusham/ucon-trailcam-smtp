import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
from ucon_trailcam_smtp.event_queue import ingest_events, QueueError


def event(ident='a', stamp=123, uid='own'):
    return {'uid': uid, 'itemid': ident, 'et_utc': stamp, 'battery': 87,
            'img_url': 'https://example.invalid/private', 'ai_result': {}}


class EventQueueTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'data' / 'events.sqlite3'

    def test_persistence_and_dedup(self):
        self.assertEqual(ingest_events(self.path, 'own', [event(), event('b', 124)]), (2, 0, 0, 2))
        self.assertEqual(ingest_events(self.path, 'own', [event(), event('b', 124)]), (0, 2, 0, 2))
        with closing(sqlite3.connect(self.path)) as db:
            data = json.loads(db.execute('SELECT metadata_json FROM events WHERE itemid=?', ('a',)).fetchone()[0])
            self.assertEqual(data['battery'], 87)
            self.assertNotIn('img_url', data)
            self.assertEqual(len(data), 6)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_scope_and_invalid_records(self):
        self.assertEqual(ingest_events(self.path, 'own', [event(uid='other'), event('', 123),
                         event('bad', True), event()]), (1, 0, 3, 1))
        self.assertEqual(ingest_events(self.path, 'other', [event(uid='other')]), (1, 0, 0, 1))

    def test_existing_state_untouched(self):
        ingest_events(self.path, 'own', [event()])
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("UPDATE events SET state='sent'")
        self.assertEqual(ingest_events(self.path, 'own', [event()]), (0, 1, 0, 0))

    def test_conflict_rolls_back_batch(self):
        ingest_events(self.path, 'own', [event()])
        with self.assertRaises(QueueError):
            ingest_events(self.path, 'own', [event('b'), event(stamp=124)])
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 1)
