import sqlite3
import unittest
from types import SimpleNamespace
from service_cycle import run_cycle


class CycleTests(unittest.IsolatedAsyncioTestCase):
    async def exercise(self, status='ok', enabled=True, fail=None):
        calls = []
        profiles = [SimpleNamespace(name=n) for n in ('a', 'b')]
        def record(name):
            calls.append(name)
            if fail == name:
                raise RuntimeError('private')
            if fail == 'db' and name == 'download-a':
                raise sqlite3.OperationalError('private')
            return 0
        async def cloud():
            record('cloud')
            return status
        code = await run_cycle(profiles, cloud=cloud, devices=lambda: ['same session'],
                               download=lambda p, d: record('download-'+p.name),
                               deliver=lambda p: record('mail-'+p.name),
                               alerts=lambda s: record('alarm-'+s), download_enabled=enabled,
                               emit=lambda _: None)
        return code, calls

    async def test_order(self):
        self.assertEqual(await self.exercise(), (0, ['cloud','download-a','download-b','mail-a','mail-b','alarm-ok']))

    async def test_login_block_keeps_mail_and_alarm(self):
        self.assertEqual(await self.exercise('blocked'), (1,['cloud','mail-a','mail-b','alarm-blocked']))

    async def test_no_download_without_explicit_flag(self):
        self.assertEqual(await self.exercise(enabled=False), (0,['cloud','mail-a','mail-b','alarm-ok']))

    async def test_download_failure_independent(self):
        self.assertEqual(await self.exercise(fail='download-a'), (1,['cloud','download-a','download-b','mail-a','mail-b','alarm-ok']))

    async def test_delivery_failure_independent(self):
        self.assertEqual(await self.exercise(fail='mail-a'), (1,['cloud','download-a','download-b','mail-a','mail-b','alarm-ok']))

    async def test_local_database_error_aborts(self):
        with self.assertRaises(sqlite3.OperationalError):
            await self.exercise(fail='db')
