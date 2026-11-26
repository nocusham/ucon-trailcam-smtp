import sqlite3
import unittest
from camera_telemetry import init_telemetry, record_snapshot, fresh_scopes
from health_alerts import AlertSettings, due_notices, build_alert


class TelemetryTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        init_telemetry(self.db)
        self.now = 1800000000

    def snap(self, now=None, info=None, **kwargs):
        return record_snapshot(self.db, 'a', {'device_uid': 'a', 'device_pwd': 'private',
                               'dynamic_info': info if info is not None else {}},
                               self.now if now is None else now, **kwargs)

    def notices(self, now):
        return due_notices(self.db, AlertSettings(enabled=True), now, {'a': 'cam'},
                           inactivity_scopes=fresh_scopes(self.db, {'a'}, now))

    def test_disabled_by_default_and_allowlist(self):
        self.assertEqual(self.snap(info={'latest_active_utc': self.now-700000, 'battery': 100,
                                         'signal': 2, 'online_state': '2', 'secret': 'private'}), 'disabled')
        self.assertEqual(self.notices(self.now), [])
        self.assertNotIn('private', str(self.db.execute('SELECT * FROM camera_telemetry').fetchall()))

    def test_activity_warning_two_fresh_checks_and_recovery(self):
        stamp = self.now-7*86400
        self.assertEqual(self.snap(info={'latest_active_utc': stamp}, enabled=True), 'inactive')
        self.assertEqual(self.notices(self.now), [])
        self.snap(self.now+900, {'latest_active_utc': stamp}, enabled=True)
        notice, = self.notices(self.now+900)
        self.assertEqual(notice.category, 'inactivity')
        self.assertIn('kein Nachweis', build_alert(AlertSettings(sender='a@x.invalid',recipient='b@x.invalid'), notice).get_content())
        self.assertEqual(self.notices(self.now+3000), [])
        self.assertEqual(due_notices(self.db, AlertSettings(enabled=True), self.now+900, {'a':'cam'}), [])
        with self.db:
            self.db.execute('UPDATE health_incidents SET last_notice=?', (self.now+900,))
        self.snap(self.now+1800, {'latest_active_utc': self.now+1700}, enabled=True)
        notice, = self.notices(self.now+1800)
        self.assertEqual(notice.recovered_at, self.now+1800)

    def test_invalid_or_regressed_stamp_not_fallback(self):
        self.snap(info={'latest_active_utc': self.now-10}, enabled=True)
        for offset, info in [(900, {}), (1800, {'latest_active_utc': 0}),
                             (2700, {'latest_active_utc': self.now-20}),
                             (3600, {'latest_active_utc': self.now+99999})]:
            self.assertEqual(self.snap(self.now+offset, info, enabled=True, coverage_end=self.now+offset), 'unknown')
        self.assertEqual(self.db.execute('SELECT latest_active_utc FROM camera_telemetry').fetchone()[0], self.now-10)

    def test_photo_fallback_requires_coverage_and_resets_after_gap(self):
        self.assertEqual(self.snap(enabled=True), 'unknown')
        start = self.now+900
        self.assertEqual(self.snap(start, {}, enabled=True, days=1, coverage_end=start), 'watching')
        for t in range(start+900, start+86400+900, 900):
            status = self.snap(t, {}, enabled=True, days=1, coverage_end=t)
        self.assertEqual(status, 'inactive')
        self.assertEqual(self.notices(start+86400), [])
        t = start+86400+900
        self.snap(t, {}, enabled=True, days=1, coverage_end=t)
        self.assertEqual(len(self.notices(t)), 1)
        self.assertEqual(self.snap(t+7200, {}, enabled=True, days=1, coverage_end=t+7200), 'watching')
        self.assertEqual(self.notices(t+7200), [])

    def test_photo_fallback_new_photo_resets_age(self):
        self.snap(enabled=True, coverage_end=self.now)
        t = self.now+900
        self.snap(t, {}, enabled=True, photo_utc=t-20, coverage_end=t)
        self.assertEqual(self.db.execute('SELECT activity_utc FROM camera_telemetry').fetchone()[0], t-20)

    def test_other_uid_and_invalid_values(self):
        with self.assertRaises(ValueError):
            record_snapshot(self.db, 'a', {'device_uid':'b'}, self.now)
        self.snap(info={'battery': True, 'signal': -1, 'online_state': 'private', 'latest_active_utc': True}, enabled=True)
        self.assertEqual(self.db.execute('SELECT battery,signal,online_state,latest_active_utc,status FROM camera_telemetry').fetchone(), (None,None,None,None,'unknown'))

    def test_same_time_replay_does_not_increment(self):
        info={'latest_active_utc': self.now-700000}
        self.snap(info=info, enabled=True)
        self.assertEqual(self.snap(info=info, enabled=True), 'unchanged')
        self.assertEqual(self.notices(self.now), [])
