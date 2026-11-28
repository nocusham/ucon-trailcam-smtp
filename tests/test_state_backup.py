"""Synthetic backup fixtures; no service, network or private state access."""
from contextlib import closing
import fcntl
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest

from deploy.state_backup import BackupError, create_backup, verify_backup, rehearse


class StateBackupTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.config = self.root / 'config'
        self.state = self.root / 'state'
        self.media = self.state / 'media'
        self.config.mkdir(mode=0o700)
        self.state.mkdir(mode=0o700)
        self.media.mkdir(mode=0o700)
        (self.config / 'config.toml').write_text('# synthetic config\n')
        (self.config / 'config.toml').chmod(0o600)
        secret = self.config / '.env'
        secret.write_text('SYNTHETIC=fixture\n')
        secret.chmod(0o600)
        self.db = self.state / 'events.sqlite3'
        self.lock = self.state / 'events.sqlite3.lock'
        self.lock.touch(mode=0o600)
        self.original = self.media / 'image.jpg'
        self.original.write_bytes(b'synthetic original')
        self.original.chmod(0o600)
        self.db.touch(mode=0o600)
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript("""
                CREATE TABLE events(camera_uid TEXT,itemid TEXT,state TEXT);
                CREATE TABLE cloud_runtime(id INTEGER,failures INTEGER,next_due INTEGER);
                CREATE TABLE cloud_cursors(camera_uid TEXT,start_utc INTEGER,last_end INTEGER);
                CREATE TABLE downloads(camera_uid TEXT,itemid TEXT,path TEXT,sha256 TEXT,size INTEGER);
                CREATE TABLE deliveries(camera_uid TEXT,itemid TEXT,message_id TEXT,accepted_utc INTEGER);
                INSERT INTO events VALUES ('synthetic','a','sent'),('synthetic','b','pending');
                INSERT INTO cloud_runtime VALUES (1,0,0);
                INSERT INTO cloud_cursors VALUES ('synthetic',100,200);
                INSERT INTO deliveries VALUES ('synthetic','a','fixture-message',123);
            """)
            db.execute('INSERT INTO downloads VALUES (?,?,?,?,?)', (
                'synthetic','a',str(self.original),
                hashlib.sha256(self.original.read_bytes()).hexdigest(),
                self.original.stat().st_size))
        self.backup = self.root / 'backup'
        self.recovery = self.root / 'rehearsal'

    def create(self):
        return create_backup(self.config, self.state, self.backup)

    def test_backup_preserves_receipts_config_and_media(self):
        before = self.db.read_bytes()
        self.assertEqual(self.create(), {'pending':1,'sent':1})
        manifest = verify_backup(self.backup)
        self.assertEqual(manifest['event_counts'], {'pending':1,'sent':1})
        with closing(sqlite3.connect(self.backup / 'state/events.sqlite3')) as db:
            self.assertEqual(db.execute('SELECT accepted_utc FROM deliveries').fetchone(), (123,))
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual((self.backup / 'config/.env').stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.backup / 'state/media/image.jpg').read_bytes(), self.original.read_bytes())

    def test_wal_committed_rows_are_in_snapshot(self):
        with closing(sqlite3.connect(self.db)) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("INSERT INTO events VALUES ('synthetic','c','pending')")
            db.commit()
            self.assertTrue(Path(str(self.db) + '-wal').exists())
            self.assertEqual(self.create(), {'pending':2,'sent':1})
        self.assertFalse((self.backup / 'state/events.sqlite3-wal').exists())

    def test_locked_queue_refuses_backup(self):
        with self.lock.open('rb') as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BackupError):
                self.create()
        self.assertFalse(self.backup.exists())

    def test_rehearsal_does_not_rewind_current_receipt_or_copy_secrets(self):
        self.create()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE deliveries SET accepted_utc=456')
        self.assertEqual(rehearse(self.backup,self.recovery), {'pending':1,'sent':1})
        with closing(sqlite3.connect(self.db)) as db:
            self.assertEqual(db.execute('SELECT accepted_utc FROM deliveries').fetchone(), (456,))
        with closing(sqlite3.connect(self.recovery / 'events.sqlite3.inert')) as db:
            self.assertEqual(db.execute('SELECT accepted_utc FROM deliveries').fetchone(), (123,))
            self.assertEqual(db.execute('SELECT path FROM downloads').fetchone(), (str(self.original),))
        self.assertFalse((self.recovery / '.env').exists())
        self.assertFalse((self.recovery / 'config').exists())
        self.assertFalse((self.recovery / 'events.sqlite3').exists())

    def test_tampered_backup_refused_before_rehearsal(self):
        self.create()
        (self.backup / 'state/media/image.jpg').write_bytes(b'changed')
        with self.assertRaises(BackupError):
            rehearse(self.backup,self.recovery)
        self.assertFalse(self.recovery.exists())

    def test_extra_file_and_existing_destination_refused(self):
        self.create()
        with self.assertRaises(BackupError):
            self.create()
        (self.backup / 'extra').write_bytes(b'not in manifest')
        (self.backup / 'extra').chmod(0o600)
        with self.assertRaises(BackupError):
            verify_backup(self.backup)

    def test_missing_or_changed_original_prevents_manifest(self):
        self.original.write_bytes(b'changed')
        with self.assertRaises(BackupError):
            self.create()
        self.assertFalse((self.backup / 'manifest.json').exists())

    def test_symlink_media_refused(self):
        (self.media / 'alias').symlink_to(self.original)
        with self.assertRaises(BackupError):
            self.create()
        self.assertFalse((self.backup / 'manifest.json').exists())

    def test_explicit_cleanup_receipt_allows_absent_sent_original(self):
        self.original.unlink()
        with closing(sqlite3.connect(self.db)) as db, db:
            db.executescript("""
                CREATE TABLE media_cleanup(camera_uid TEXT,itemid TEXT,removed_utc INTEGER,size INTEGER);
                INSERT INTO media_cleanup VALUES ('synthetic','a',200,18);
            """)
        self.assertEqual(self.create(), {'pending':1,'sent':1})
        self.assertEqual(rehearse(self.backup,self.recovery), {'pending':1,'sent':1})

    def test_inconsistent_delivery_receipt_refused(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('UPDATE deliveries SET accepted_utc=NULL')
        with self.assertRaises(BackupError):
            self.create()
        self.assertFalse((self.backup / 'manifest.json').exists())

    def test_overlapping_destination_refused(self):
        with self.assertRaises(BackupError):
            create_backup(self.config,self.state,self.state / 'backup')
        self.assertFalse((self.state / 'backup').exists())

    def test_uncertain_receipt_preserved(self):
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute("UPDATE events SET state='uncertain' WHERE itemid='a'")
            db.execute('UPDATE deliveries SET accepted_utc=NULL')
        self.assertEqual(self.create(), {'pending':1,'uncertain':1})
        self.assertEqual(rehearse(self.backup,self.recovery), {'pending':1,'uncertain':1})


if __name__ == '__main__':
    unittest.main()
