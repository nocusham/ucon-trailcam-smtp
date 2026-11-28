"""Real temporary backup copies; no root, host service or private data."""
from contextlib import closing
import fcntl
import hashlib
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from deploy.production_layout import APP
from deploy.production_backup import _locked_backup, _check, locked_production_backup
from deploy.production_update import _coordinate, production_update
from deploy.release_layout import ReleaseError, switch_release
from deploy.state_backup import BackupError, verify_backup


class ProductionBackupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.identity = (os.geteuid(), os.getegid())
        self.root.chmod(0o755)
        for name, mode in (
            ('etc',0o755), ('var',0o755), ('var/lib',0o755),
            ('var/backups',0o755), ('etc/'+APP,0o750),
            ('var/lib/'+APP,0o700), ('var/lib/'+APP+'/media',0o700),
            ('var/backups/'+APP,0o700), ('opt',0o755),
            ('opt/'+APP,0o755), ('opt/'+APP+'/releases',0o755),
        ):
            path = self.root / name
            path.mkdir(mode=mode)
            path.chmod(mode)
        self.config = self.root / 'etc' / APP
        self.state = self.root / 'var/lib' / APP
        self.backups = self.root / 'var/backups' / APP
        self.install = self.root / 'opt' / APP
        self.destination = self.backups / 'backup1'
        self.file(self.config / 'config.toml', b'# fixture\n', 0o640)
        self.file(self.config / '.env', b'FIXTURE=synthetic\n', 0o400)
        self.db = self.state / 'events.sqlite3'
        self.lock = self.state / 'events.sqlite3.lock'
        self.file(self.db, b'')
        self.file(self.lock, b'')
        self.image = self.state / 'media/image.jpg'
        self.file(self.image, b'fixture original')
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript("""
                CREATE TABLE events(camera_uid TEXT,itemid TEXT,state TEXT);
                CREATE TABLE cloud_runtime(id INTEGER,failures INTEGER,next_due INTEGER);
                CREATE TABLE cloud_cursors(camera_uid TEXT,start_utc INTEGER,last_end INTEGER);
                CREATE TABLE downloads(camera_uid TEXT,itemid TEXT,path TEXT,sha256 TEXT,size INTEGER);
                CREATE TABLE deliveries(camera_uid TEXT,itemid TEXT,accepted_utc INTEGER);
                INSERT INTO events VALUES ('fixture','a','sent');
                INSERT INTO deliveries VALUES ('fixture','a',123);
            """)
            db.execute('INSERT INTO downloads VALUES (?,?,?,?,?)', (
                'fixture','a',str(self.image),
                hashlib.sha256(self.image.read_bytes()).hexdigest(),
                self.image.stat().st_size))
        for release in ('v1','v2'):
            folder = self.install / 'releases' / release
            (folder / 'venv/bin').mkdir(parents=True)
            self.file(folder / 'venv/bin' / APP, b'never run', 0o755)
            self.file(folder / '.ready', (release+'\n').encode())
        switch_release(self.install, 'v1')

    @staticmethod
    def file(path, content, mode=0o600):
        path.write_bytes(content)
        path.chmod(mode)

    def backup(self):
        return _locked_backup(self.root, self.destination, self.identity, self.identity)

    def selected(self):
        return os.readlink(self.install / 'current')

    def test_private_backup_and_lock_retention(self):
        before = self.db.read_bytes()
        with self.backup() as counts:
            self.assertEqual(counts, {'sent':1})
            self.assertEqual(verify_backup(self.destination)['event_counts'], counts)
            with self.lock.open('rb') as stream:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual((self.destination / 'config/.env').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.destination.stat().st_mode & 0o777), 0o700)
        self.assertEqual((self.config / '.env').stat().st_mode & 0o777, 0o400)
        with self.lock.open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_wal_copy_keeps_committed_data_without_live_sqlite_open(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("INSERT INTO events VALUES ('fixture','b','pending')")
            db.commit()
            wal = Path(str(self.db)+'-wal')
            shm = Path(str(self.db)+'-shm')
            for path in (wal,shm):
                path.chmod(0o600)
            before = {p: p.read_bytes() for p in (self.db,wal,shm)}
            with self.backup() as counts:
                self.assertEqual(counts, {'pending':1,'sent':1})
            for path, content in before.items():
                self.assertEqual(path.read_bytes(), content)
        self.assertFalse((self.destination / 'state/events.sqlite3-wal').exists())
        self.assertFalse(any(self.destination.glob('.sqlite-*')))

    def test_rollback_journal_refused(self):
        self.file(Path(str(self.db)+'-journal'), b'fixture')
        with self.assertRaisesRegex(BackupError, 'Rollback journal'):
            with self.backup():
                self.fail('Unexpected backup')
        self.assertFalse(self.destination.exists())

    def test_source_symlink_and_bad_secret_mode_refused(self):
        self.image.unlink()
        self.image.symlink_to(self.config / '.env')
        with self.assertRaises(BackupError):
            with self.backup():
                self.fail('Unexpected backup')
        self.assertFalse((self.destination / 'manifest.json').exists())

    def test_distinct_owner_metadata(self):
        # Ownership metadata only is simulated; no chown needed.
        info = SimpleNamespace(st_mode=stat.S_IFREG|0o640, st_uid=0,
                               st_gid=2345, st_nlink=1, st_dev=1)
        with patch('deploy.production_backup._metadata', return_value=info), \
                patch('deploy.production_backup.os.listxattr', return_value=[]):
            _check(self.config / 'config.toml', (0,2345), stat.S_IFREG, (0o640,))
            with self.assertRaises(BackupError):
                _check(self.config / 'config.toml', (1234,2345), stat.S_IFREG, (0o640,))

    def test_wrong_backup_location_and_active_marker(self):
        with self.assertRaisesRegex(BackupError, 'private administrator directory'):
            with _locked_backup(self.root, self.root/'elsewhere', self.identity, self.identity):
                self.fail('Unexpected backup')
        self.file(self.config/'service-enabled', b'', 0o644)
        with self.assertRaisesRegex(BackupError, 'marker must be absent'):
            with self.backup():
                self.fail('Unexpected backup')

    def test_queue_contention_refused(self):
        with self.lock.open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(BackupError, 'Queue is locked'):
                with self.backup():
                    self.fail('Unexpected backup')

    def test_integrated_update_and_rollback_preserve_latest_state(self):
        control = Mock()
        control.inhibit_start.return_value = True
        control.quiesce.return_value = True
        control.is_quiescent.return_value = True
        def approve(old, new, backup):
            self.assertTrue(verify_backup(backup))
            for path in (self.lock, self.install/'.deployment.lock'):
                with path.open('rb') as stream:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        # Named production ownership contract tested separately; here real
        # files have one unprivileged owner, while service control is mocked.
        with patch('deploy.production_update.check_layout') as layout:
            result = _coordinate(self.root,'v2','v1','backup1',self.identity,
                                 self.identity,control,lambda:True,approve)
            self.assertEqual(result['selected'],'v2')
            self.assertEqual(self.selected(),'releases/v2')
            with closing(sqlite3.connect(self.db)) as db, db:
                db.execute('UPDATE deliveries SET accepted_utc=456')
            before = self.db.read_bytes()
            _coordinate(self.root,'v1','v2','backup2',self.identity,
                        self.identity,control,lambda:True,approve)
            self.assertEqual(layout.call_count,4)
        self.assertEqual(self.selected(),'releases/v1')
        self.assertEqual(self.db.read_bytes(),before)
        with closing(sqlite3.connect(self.backups/'backup2/state/events.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT accepted_utc FROM deliveries').fetchone(),(456,))
        self.assertFalse((self.config/'service-enabled').exists())

    def test_external_writer_or_refused_approval_blocks_update(self):
        control = Mock()
        control.inhibit_start.return_value = True
        control.quiesce.return_value = True
        control.is_quiescent.return_value = True
        with patch('deploy.production_update.check_layout'):
            with self.assertRaisesRegex(ReleaseError,'All writers'):
                _coordinate(self.root,'v2','v1','backup1',self.identity,
                            self.identity,control,lambda:False,lambda *args:True)
            self.assertFalse(self.destination.exists())
            with self.assertRaisesRegex(ReleaseError,'Compatibility approval'):
                _coordinate(self.root,'v2','v1','backup1',self.identity,
                            self.identity,control,lambda:True,lambda *args:False)
        self.assertEqual(self.selected(),'releases/v1')
        self.assertEqual(verify_backup(self.destination)['event_counts'],{'sent':1})

    def test_root_guards(self):
        with patch('deploy.production_backup.os.geteuid',return_value=1234):
            with self.assertRaisesRegex(BackupError,'Administrator identity'):
                with locked_production_backup(self.destination,1234,2345):
                    self.fail('Unexpected backup')
            with self.assertRaisesRegex(ReleaseError,'Administrator identity'):
                production_update('v2','v1','backup1','a'*64,
                                  confirm_no_other_writers=lambda:True,
                                  approve_compatibility=lambda *args:True)


if __name__ == '__main__':
    unittest.main()
