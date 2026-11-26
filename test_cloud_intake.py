import sqlite3
import tempfile
import unittest
from pathlib import Path

from cloud_intake import Intake, init_intake, login_blocked, resume_login, window
from health_alerts import AlertSettings, due_notices


class ApiError(Exception):
    def __init__(self, message, *, stage=None, api_code=None, http_status=None):
        super().__init__(message)
        self.stage, self.api_code, self.http_status = stage, api_code, http_status


class IntakeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'intake.db'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(lambda: self.db.close())
        with self.db:
            self.db.execute('CREATE TABLE events(camera_uid TEXT,itemid TEXT,PRIMARY KEY(camera_uid,itemid))')
        init_intake(self.db, ['a'], 1000)
        self.logins = 0
        self.calls = []
        self.login_error = None
        self.api_error = None
        self.items = []
        self.worker = self.make_worker()

    def make_worker(self):
        async def discover():
            self.logins += 1
            if self.login_error:
                raise self.login_error
            return {}, [{'device_uid': 'a'}]

        async def query(headers, uid, begin, end):
            self.calls.append((uid, begin, end))
            if self.api_error:
                raise self.api_error
            return {'items': self.items}

        def store(uid, items):
            added = 0
            with self.db:
                for item in items:
                    added += self.db.execute('INSERT OR IGNORE INTO events VALUES (?,?)', (uid, item['itemid'])).rowcount
            return added, len(items)-added, 0, self.db.execute('SELECT count(*) FROM events').fetchone()[0]

        return Intake(self.db, ['a'], discover=discover, query=query, store=store, api_error=ApiError, emit=lambda _: None)

    def restart(self):
        self.db.close()
        self.db = sqlite3.connect(self.path)
        init_intake(self.db, ['a'], 9999)
        self.worker = self.make_worker()

    async def test_fresh_baseline_and_photo_filter(self):
        self.items = [{'uid': uid, 'et_utc': t, 'itemid': ident, 'type': kind} for uid, t, ident, kind in
                      [('a', 999, 'old', 1), ('a', 1001, 'photo', 1), ('a', 1001, 'video', 2),
                       ('b', 1001, 'other', 1), ('a', 1100, 'future', 1)]]
        self.assertEqual(await self.worker.cycle(1060), 'ok')
        self.assertEqual(self.db.execute('SELECT itemid FROM events').fetchall(), [('photo',)])
        self.assertEqual(self.calls, [('a', 1000, 1060)])

    async def test_no_zero_width_api_window(self):
        self.assertEqual(await self.worker.cycle(1000), 'ok')
        self.assertEqual(self.calls, [])
        self.assertEqual(await self.worker.cycle(1060), 'ok')
        self.assertEqual(self.calls, [('a', 1000, 1060)])

    async def test_restart_overlap_and_bounded_catchup(self):
        await self.worker.cycle(1600)
        self.restart()
        await self.worker.cycle(10000)
        self.assertEqual(self.calls[-1], ('a', 1300, 5200))
        await self.worker.cycle(10060)
        self.assertEqual(self.calls[-1], ('a', 4900, 8800))
        self.assertEqual(self.logins, 2)

    async def test_api_failure_preserves_cursor_and_cooldown(self):
        await self.worker.cycle(1060)
        self.api_error = ApiError('failure', stage='cloud event list', http_status=503)
        self.assertEqual(await self.worker.cycle(1120), 'error')
        self.restart()
        self.api_error = None
        self.assertEqual(await self.worker.cycle(1239), 'deferred')
        self.assertEqual(await self.worker.cycle(1240), 'ok')
        self.assertEqual(self.calls[-1], ('a', 1000, 1240))

    async def test_wrong_password_block_persists_and_alarm_matures(self):
        self.login_error = ApiError('rejected', stage='login', api_code=20005)
        self.assertEqual(await self.worker.cycle(1000), 'blocked')
        self.restart()
        self.assertEqual(await self.worker.cycle(1900), 'blocked')
        self.assertEqual(self.logins, 1)
        self.assertEqual(len(due_notices(self.db, AlertSettings(enabled=True), 1900, {})), 1)
        self.assertTrue(login_blocked(self.db))
        resume_login(self.db)
        self.login_error = None
        self.assertEqual(await self.worker.cycle(1901), 'ok')
        self.assertFalse(login_blocked(self.db))
        self.assertEqual(self.logins, 2)
        self.assertEqual(due_notices(self.db, AlertSettings(enabled=True), 1901, {}), [])

    async def test_session_reused_then_expired(self):
        await self.worker.cycle(1000)
        await self.worker.cycle(1060)
        self.assertEqual(self.logins, 1)
        self.api_error = ApiError('expired', stage='cloud event list', http_status=401)
        await self.worker.cycle(1120)
        self.api_error = None
        await self.worker.cycle(1240)
        self.assertEqual(self.logins, 2)

    async def test_code_20005_outside_login_does_not_block(self):
        self.api_error = ApiError('error', stage='cloud event list', api_code=20005)
        self.assertEqual(await self.worker.cycle(1001), 'error')
        self.assertFalse(login_blocked(self.db))

    def test_existing_historical_queue_refused(self):
        db = sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        with db:
            db.execute('CREATE TABLE events(itemid TEXT)')
            db.execute("INSERT INTO events VALUES ('history')")
        with self.assertRaisesRegex(ValueError, 'historical'):
            init_intake(db, ['a'], 1000)

    def test_clock_rollback_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Clock moved'):
            window(self.db, 'a', 999)

    async def test_refresh_only_every_15_minutes_and_no_stale_callback(self):
        snapshots = []
        refreshes = []

        async def refresh(headers):
            refreshes.append(headers)
            return [{'device_uid': 'a'}]

        self.worker.refresh_devices = refresh
        self.worker.on_devices = lambda devices, now, covered: snapshots.append((now, covered))
        await self.worker.cycle(1000)
        await self.worker.cycle(1060)
        self.assertEqual(snapshots, [(1000, set())])
        self.api_error = ApiError('failed', stage='cloud event list', http_status=503)
        await self.worker.cycle(1900)
        self.assertEqual(snapshots, [(1000, set())])
        self.api_error = None
        await self.worker.cycle(2020)
        self.assertEqual(snapshots, [(1000, set()), (2020, {'a'})])
        self.assertEqual(len(refreshes), 2)
        self.assertEqual(self.logins, 1)
