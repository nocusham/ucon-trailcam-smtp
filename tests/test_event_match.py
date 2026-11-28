import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from ucon_trailcam_smtp.event_match import match_events, queued_times


def photo(t, kind=4, length=65535):
    return SimpleNamespace(start_time=t, event_type=kind, length=length)


class MatchTests(unittest.TestCase):
    def test_exact_and_offset_and_non_pir(self):
        self.assertEqual(match_events([100, 200, 300],
                         [photo(100), photo(199), photo(300, 3), photo(301, length=10)]),
                         [(100, 'matched', 100), (200, 'matched', 199), (300, 'missing', None)])

    def test_multiple_candidates_even_with_exact(self):
        self.assertEqual(match_events([100], [photo(100), photo(101)]),
                         [(100, 'ambiguous', None)])

    def test_shared_candidate_and_duplicate_time(self):
        for stamps in ([100, 101], [100, 100]):
            self.assertEqual(match_events(stamps, [photo(100)]),
                             [(t, 'ambiguous', None) for t in stamps])

    def test_tolerance_boundary(self):
        self.assertEqual(match_events([100, 200], [photo(102), photo(203)]),
                         [(100, 'matched', 102), (200, 'missing', None)])

    def test_readonly_camera_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'queue.sqlite3'
            with closing(sqlite3.connect(path)) as db, db:
                db.execute('CREATE TABLE events (camera_uid TEXT, et_utc INTEGER)')
                db.executemany('INSERT INTO events VALUES (?,?)',
                               [('own', 100), ('own', 200), ('other', 101), ('own', 99)])
            self.assertEqual(queued_times(path, 'own', 100, 200), [100])
            missing = Path(tmp) / 'missing.sqlite3'
            with self.assertRaises(sqlite3.OperationalError):
                queued_times(missing, 'own', 0, 200)
            self.assertFalse(missing.exists())
