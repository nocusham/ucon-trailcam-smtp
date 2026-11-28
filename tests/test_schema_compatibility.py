"""Use real runtime startup DDL and synthetic optional-table catalog entries."""
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from deploy.schema_compatibility import DDL, REQUIRED, check_schema
from deploy.state_backup import BackupError
from ucon_trailcam_smtp.event_queue import open_queue
from ucon_trailcam_smtp.cloud_intake import init_intake
from ucon_trailcam_smtp.camera_telemetry import init_telemetry
from ucon_trailcam_smtp.download_retry import init_retry


class SchemaCompatibilityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = open_queue(Path(tmp.name) / 'fixture.sqlite3')
        self.addCleanup(self.db.close)
        init_intake(self.db, ['fixture'], 100)
        init_telemetry(self.db)
        init_retry(self.db)

    def test_actual_startup_schema(self):
        before = self.db.serialize()
        self.assertEqual(check_schema(self.db), {'schema_contract':1,'tables':6})
        self.assertEqual(self.db.serialize(), before)

    def test_optional_tables(self):
        for name in sorted(DDL.keys() - REQUIRED):
            self.db.execute(DDL[name])
            check_schema(self.db)
        self.assertEqual(check_schema(self.db)['tables'], 11)

    def test_missing_required_table(self):
        self.db.execute('DROP TABLE camera_telemetry')
        with self.assertRaisesRegex(BackupError, 'missing queue tables'):
            check_schema(self.db)

    def test_unknown_table(self):
        self.db.execute('CREATE TABLE unknown(x)')
        with self.assertRaisesRegex(BackupError, 'queue tables'):
            check_schema(self.db)

    def test_changed_column(self):
        self.db.execute('ALTER TABLE events ADD COLUMN unexpected TEXT')
        with self.assertRaisesRegex(BackupError, 'schema differs'):
            check_schema(self.db)

    def test_unexpected_index_view_and_trigger(self):
        for create, drop in (
            ('CREATE INDEX extra ON events(state)', 'DROP INDEX extra'),
            ('CREATE VIEW extra AS SELECT * FROM events', 'DROP VIEW extra'),
            ('CREATE TRIGGER extra AFTER INSERT ON events BEGIN SELECT 1; END',
             'DROP TRIGGER extra'),
        ):
            with self.subTest(create=create):
                self.db.execute(create)
                with self.assertRaisesRegex(BackupError, 'schema differs'):
                    check_schema(self.db)
                self.db.execute(drop)

    def test_version_and_application_id(self):
        for pragma in ('user_version', 'application_id'):
            self.db.execute(f'PRAGMA {pragma}=1')
            with self.assertRaisesRegex(BackupError, 'version or application ID'):
                check_schema(self.db)
            self.db.execute(f'PRAGMA {pragma}=0')


if __name__ == '__main__':
    unittest.main()
