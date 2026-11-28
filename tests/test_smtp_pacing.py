import sqlite3
import tempfile
import unittest
from pathlib import Path
from ucon_trailcam_smtp.smtp_pacing import Pacer, parse_interval, NANOSECONDS


class PacingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'queue.sqlite3'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(lambda: self.db.close())
        self.now = 100 * NANOSECONDS
        self.pacer = Pacer(self.db, clock=lambda: self.now)

    def test_interval_and_restart(self):
        self.assertTrue(self.pacer.due())
        self.assertTrue(self.pacer.reserve())
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.pacer = Pacer(self.db, clock=lambda: self.now)
        self.now += 30 * NANOSECONDS - 1
        self.assertFalse(self.pacer.due())
        self.assertFalse(self.pacer.reserve())
        self.now += 1
        self.assertTrue(self.pacer.reserve())

    def test_manual_override_and_clock_rollback(self):
        self.assertTrue(self.pacer.reserve())
        self.now += 10 * NANOSECONDS
        self.assertTrue(Pacer(self.db, 10, clock=lambda: self.now).reserve())
        self.now -= NANOSECONDS
        self.assertFalse(self.pacer.reserve())
        self.now += 31 * NANOSECONDS
        self.assertTrue(self.pacer.reserve())

    def test_validation_and_readonly_due(self):
        self.assertEqual(parse_interval(None), 30)
        self.assertEqual(parse_interval({'interval_seconds': 1}), 1)
        for raw in ({'interval_seconds': True}, {'interval_seconds': 0},
                    {'interval_seconds': 3601}, {'unknown': 1}, []):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_interval(raw)
        self.assertTrue(self.pacer.due())
        self.assertIsNone(self.db.execute("SELECT 1 FROM sqlite_master WHERE name='smtp_pacing'").fetchone())
