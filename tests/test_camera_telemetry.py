import sqlite3
import unittest
from ucon_trailcam_smtp.camera_telemetry import init_telemetry, record_snapshot, fresh_scopes, record_history, prune_history
from ucon_trailcam_smtp.health_alerts import AlertSettings, due_notices, build_alert


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


    def test_history_fresh_unchanged_values_and_no_secrets(self):
        info = {'latest_active_utc': self.now-60, 'battery': 95, 'signal': 3,
                'online_state':'2', 'is_battery_charging':False, 'is_low_power':True,
                'secret':'private'}
        devices = [{'device_uid':'a','dynamic_info':info,'device_pwd':'private'},
                   {'device_uid':'other','dynamic_info':info}]
        record_history(self.db,['a'],devices,self.now)
        record_history(self.db,['a'],devices,self.now+900)
        record_history(self.db,['a'],devices,self.now+900)
        self.assertEqual(self.db.execute('SELECT * FROM camera_telemetry_history ORDER BY observed_utc').fetchall(),
                         [('a',self.now,self.now-60,95,3,'2',0,1),
                          ('a',self.now+900,self.now-60,95,3,'2',0,1)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM camera_telemetry').fetchone(),(0,))

    def test_history_missing_values_not_carried_forward(self):
        self.snap(info={'latest_active_utc':self.now-60,'battery':100})
        record_history(self.db,['a'],[{'device_uid':'a','dynamic_info':{
            'battery':True,'signal':-1,'latest_active_utc':self.now+5000,'online_state':'private'}}],self.now+900)
        self.assertEqual(self.db.execute('SELECT latest_active_utc,battery,signal,online_state,charging,low_power '
                                        'FROM camera_telemetry_history').fetchone(),(None,)*6)
        self.assertEqual(self.db.execute('SELECT battery FROM camera_telemetry').fetchone(),(100,))

    def test_history_camera_scope_and_atomic_validation(self):
        devices = [{'device_uid':'a'}, {'device_uid':'b'}]
        with self.assertRaises(ValueError):
            record_history(self.db,['a','missing'],devices,self.now)
        record_history(self.db,['a','b'],devices,self.now)
        self.assertEqual(self.db.execute('SELECT camera_uid FROM camera_telemetry_history ORDER BY camera_uid').fetchall(),
                         [('a',),('b',)])
        with self.assertRaises(ValueError):
            record_history(self.db,['a'],devices+[devices[0]],self.now+1)

    def test_history_retention_boundary_preview_and_latest_state(self):
        self.snap(info={'battery':99})
        days = 90
        cutoff = self.now-days*86400
        devices = [{'device_uid':'a','dynamic_info':{'battery':80}}]
        for t in (cutoff-1,cutoff,cutoff+1,self.now):
            record_history(self.db,['a'],devices,t)
        before = self.db.serialize()
        self.assertEqual(prune_history(self.db,self.now,days,emit=lambda _:None),2)
        self.assertEqual(self.db.serialize(),before)
        self.assertEqual(prune_history(self.db,self.now,days,apply=True,emit=lambda _:None),2)
        self.assertEqual(self.db.execute('SELECT observed_utc FROM camera_telemetry_history ORDER BY observed_utc').fetchall(),
                         [(cutoff+1,),(self.now,)])
        self.assertEqual(self.db.execute('SELECT battery FROM camera_telemetry').fetchone(),(99,))

    def test_history_config_and_missing_table(self):
        from ucon_trailcam_smtp.media_retention import parse_retention
        self.assertEqual(parse_retention(None).telemetry_days,90)
        self.assertEqual(parse_retention({'telemetry_days':7}).telemetry_days,7)
        for v in (True,0,3651,'90'):
            with self.subTest(v=v), self.assertRaises(ValueError):
                parse_retention({'telemetry_days':v})
        self.assertEqual(prune_history(self.db,self.now,apply=True),0)
