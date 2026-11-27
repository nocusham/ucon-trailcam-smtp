import tempfile
import unittest
from pathlib import Path

from ucon_trailcam_smtp.cloud_watch import watch


class ApiError(Exception):
    def __init__(self, status):
        super().__init__(f'HTTP {status}')
        self.http_status = status


class WatchTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, replies, *, change_uid=False):
        calls = []
        delays = []
        logs = []
        ticks = iter(range(100000, 100000 + len(replies) * 60, 60))
        login_count = 0

        async def auth(*args):
            nonlocal login_count
            login_count += 1
            return {'token': str(login_count)}, 'other' if change_uid and login_count > 1 else 'own'

        async def query(client, headers, uid, begin, end):
            calls.append((headers['token'], begin, end))
            reply = replies[len(calls) - 1]
            if isinstance(reply, Exception):
                raise reply
            return {'items': [{'uid': uid, 'itemid': ident, 'et_utc': 99999} for ident in reply]}

        async def sleep(delay):
            delays.append(delay)

        with tempfile.TemporaryDirectory() as tmp:
            code = await watch(None, 'a', 'p', 0, Path(tmp) / 'test.sqlite3',
                               authenticate=auth, list_events=query, api_error=ApiError,
                               cycles=len(replies), clock=lambda: next(ticks), sleep=sleep,
                               emit=logs.append)
        return code, calls, delays, logs

    async def test_reuse_session_overlap_and_dedup(self):
        code, calls, delays, logs = await self.exercise([['a'], ['a'], ['a', 'b']])
        self.assertEqual(code, 0)
        self.assertEqual(calls, [('1', 13600, 100000), ('1', 99700, 100060), ('1', 99760, 100120)])
        self.assertEqual(delays, [60, 60])
        self.assertIn('new=0, known=1', logs[2])
        self.assertIn('new=1, known=1', logs[3])

    async def test_transient_error_keeps_session_and_cursor(self):
        code, calls, delays, logs = await self.exercise([['a'], ApiError(503), ['a', 'b']])
        self.assertEqual(code, 1)
        self.assertEqual(calls[-1], ('1', 99700, 100120))
        self.assertEqual(delays, [60, 120])

    async def test_auth_error_reconnects(self):
        code, calls, delays, logs = await self.exercise([ApiError(401), ['a']])
        self.assertEqual(code, 1)
        self.assertEqual(calls[-1][0], '2')
        self.assertEqual(delays, [120])

    async def test_changed_camera_after_reauth_stops(self):
        with self.assertRaisesRegex(RuntimeError, 'Selected camera changed'):
            await self.exercise([ApiError(401), ['a']], change_uid=True)
