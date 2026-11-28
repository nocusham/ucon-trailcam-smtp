"""Real synthetic SQLite backup and release-switch transaction tests."""
from contextlib import closing
import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from deploy.release_layout import ReleaseError, switch_release
from deploy.state_backup import BackupError, verify_backup
from deploy.update_transaction import coordinate_switch


class UpdateTransactionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.root = self.base / 'install'
        self.config = self.base / 'config'
        self.state = self.base / 'state'
        self.backup = self.base / 'backup'
        for directory in (self.root, self.root / 'releases', self.config,
                          self.state, self.state / 'media'):
            directory.mkdir(mode=0o700)
        for release in ('v1', 'v2', 'v3'):
            folder = self.root / 'releases' / release
            for directory in (folder, folder / 'venv', folder / 'venv/bin'):
                directory.mkdir(mode=0o700)
            exe = folder / 'venv/bin/ucon-trailcam-smtp'
            self.file(exe, b'never executed', 0o700)
            self.file(folder / '.ready', (release + '\n').encode())
        switch_release(self.root, 'v1')
        self.file(self.config / 'config.toml', b'# synthetic\n')
        self.file(self.config / '.env', b'FIXTURE=synthetic\n')
        self.db = self.state / 'events.sqlite3'
        self.lock = self.state / 'events.sqlite3.lock'
        self.file(self.db, b'')
        self.file(self.lock, b'')
        self.image = self.state / 'media/image.jpg'
        self.file(self.image, b'synthetic original')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript("""
                CREATE TABLE events(camera_uid TEXT,itemid TEXT,state TEXT);
                CREATE TABLE cloud_runtime(id INTEGER,failures INTEGER,next_due INTEGER);
                CREATE TABLE cloud_cursors(camera_uid TEXT,start_utc INTEGER,last_end INTEGER);
                CREATE TABLE downloads(camera_uid TEXT,itemid TEXT,path TEXT,sha256 TEXT,size INTEGER);
                CREATE TABLE deliveries(camera_uid TEXT,itemid TEXT,accepted_utc INTEGER);
                INSERT INTO events VALUES ('fixture','a','sent');
                INSERT INTO cloud_runtime VALUES (1,0,0);
                INSERT INTO cloud_cursors VALUES ('fixture',100,200);
                INSERT INTO deliveries VALUES ('fixture','a',123);
            """)
            db.execute('INSERT INTO downloads VALUES (?,?,?,?,?)',
                       ('fixture', 'a', str(self.image),
                        hashlib.sha256(self.image.read_bytes()).hexdigest(),
                        self.image.stat().st_size))
        self.stop = Mock(return_value=True)
        self.stopped = Mock(return_value=True)
        self.approve = Mock(return_value=True)

    @staticmethod
    def file(path, content, mode=0o600):
        path.write_bytes(content)
        path.chmod(mode)

    def selected(self):
        return os.readlink(self.root / 'current')

    def change(self, target='v2', previous='v1', backup=None):
        return coordinate_switch(self.root, self.config, self.state, backup or self.backup,
                                 target, expected_previous=previous, quiesce=self.stop,
                                 is_quiescent=self.stopped, approve_compatibility=self.approve)

    def receipt(self, path):
        with closing(sqlite3.connect(path)) as db:
            return db.execute('SELECT accepted_utc FROM deliveries').fetchone()[0]

    def test_update_and_explicit_rollback_preserve_latest_receipt(self):
        before = self.db.read_bytes()
        result = self.change()
        self.assertEqual(result, {'previous':'v1','selected':'v2','event_counts':{'sent':1}})
        self.assertEqual(self.selected(), 'releases/v2')
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.receipt(self.backup / 'state/events.sqlite3'), 123)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE deliveries SET accepted_utc=456')
        backup2 = self.base / 'rollback-backup'
        before = self.db.read_bytes()
        self.change('v1','v2',backup2)
        self.assertEqual(self.selected(), 'releases/v1')
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(self.receipt(backup2 / 'state/events.sqlite3'), 456)
        self.assertEqual(self.receipt(self.backup / 'state/events.sqlite3'), 123)
        self.assertEqual(self.image.read_bytes(), b'synthetic original')
        self.assertFalse((self.config / 'service-enabled').exists())

    def test_both_locks_held_during_approval_and_switch(self):
        def assert_locked(*args):
            for path in (self.lock, self.root / '.deployment.lock'):
                with path.open('rb') as stream:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def approve(previous, target, backup):
            self.assertEqual((previous,target), ('v1','v2'))
            self.assertEqual(verify_backup(backup)['event_counts'], {'sent':1})
            assert_locked()
            return True
        def switch(*args, **kwargs):
            assert_locked()
            return switch_release(*args, **kwargs)
        self.approve.side_effect = approve
        with patch('deploy.update_transaction.switch_release', side_effect=switch):
            self.change()
        for path in (self.lock, self.root / '.deployment.lock'):
            with path.open('rb') as stream:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_stop_failure_refuses_backup_and_switch(self):
        self.stop.return_value = False
        with self.assertRaisesRegex(ReleaseError, 'stop failed'):
            self.change()
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.selected(), 'releases/v1')
        self.approve.assert_not_called()

    def test_not_quiescent_refuses_backup(self):
        self.stopped.return_value = False
        with self.assertRaisesRegex(ReleaseError, 'writers must be stopped'):
            self.change()
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.selected(), 'releases/v1')

    def test_marker_even_dangling_link_refused_before_stop(self):
        (self.config / 'service-enabled').symlink_to('absent')
        with self.assertRaisesRegex(ReleaseError, 'marker must be absent'):
            self.change()
        self.stop.assert_not_called()

    def test_queue_lock_refuses_backup(self):
        with self.lock.open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(BackupError, 'Queue is locked'):
                self.change()
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.selected(), 'releases/v1')

    def test_invalid_original_refuses_switch(self):
        self.image.write_bytes(b'changed')
        with self.assertRaises(BackupError):
            self.change()
        self.assertFalse((self.backup / 'manifest.json').exists())
        self.assertEqual(self.selected(), 'releases/v1')
        self.approve.assert_not_called()

    def test_approval_refused_retains_backup_and_current(self):
        self.approve.return_value = None
        with self.assertRaisesRegex(ReleaseError, 'Compatibility approval required'):
            self.change()
        self.assertEqual(verify_backup(self.backup)['event_counts'], {'sent':1})
        self.assertEqual(self.selected(), 'releases/v1')

    def test_tampered_backup_during_approval_refuses_switch(self):
        def tamper(previous, target, backup):
            (backup / 'state/media/image.jpg').write_bytes(b'tampered')
            return True
        self.approve.side_effect = tamper
        with self.assertRaisesRegex(BackupError, 'digest mismatch'):
            self.change()
        self.assertEqual(self.selected(), 'releases/v1')

    def test_quiescence_lost_after_approval_refuses_switch(self):
        self.stopped.side_effect = [True,False]
        with self.assertRaisesRegex(ReleaseError, 'writers must be stopped'):
            self.change()
        self.assertEqual(self.selected(), 'releases/v1')
        self.assertEqual(verify_backup(self.backup)['event_counts'], {'sent':1})

    def test_stale_current_or_unready_target_refused_before_stop(self):
        with self.assertRaisesRegex(ReleaseError, 'Current release changed'):
            self.change(previous='v3')
        (self.root / 'releases/v2/.ready').unlink()
        with self.assertRaisesRegex(ReleaseError, 'incomplete'):
            self.change()
        self.stop.assert_not_called()
        self.assertFalse(self.backup.exists())

    def test_pointer_compare_and_swap_detects_intervening_selection(self):
        # Simulate an operator bypassing the outer deployment lock.
        def intervene(*args):
            switch_release(self.root, 'v3')
            return True
        self.approve.side_effect = intervene
        with self.assertRaisesRegex(ReleaseError, 'Current release changed'):
            self.change()
        self.assertEqual(self.selected(), 'releases/v3')

    def test_failed_switch_retains_backup_and_current(self):
        with patch('deploy.update_transaction.switch_release', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                self.change()
        self.assertEqual(self.selected(), 'releases/v1')
        self.assertEqual(self.receipt(self.backup / 'state/events.sqlite3'), 123)
        self.assertEqual(self.receipt(self.db), 123)


if __name__ == '__main__':
    unittest.main()
