import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
from io import BytesIO
from queue_download import (batch_lock, load_rows, eligible, check_existing,
                            download_batch)


def validate(data):
    with Image.open(BytesIO(data)) as im:
        im.verify()
    with Image.open(BytesIO(data)) as im:
        im.load()
        return im.format.lower().replace('jpeg', 'jpg'), *im.size


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.db = self.root / 'events.sqlite3'
        with closing(sqlite3.connect(self.db)) as db, db:
            db.execute('CREATE TABLE events(camera_uid TEXT,itemid TEXT,et_utc INTEGER,state TEXT,metadata_json TEXT)')
            db.executemany('INSERT INTO events VALUES (?,?,?,?,?)', [
                ('own', 'a', 100, 'pending', json.dumps({'type': 1})),
                ('own', 'b', 200, 'pending', json.dumps({'type': 1})),
                ('own', 'c', 300, 'pending', json.dumps({'type': 2})),
                ('other', 'a', 100, 'pending', json.dumps({'type': 1}))])
        self.events = [SimpleNamespace(start_time=t, event_type=4, length=65535) for t in (100, 200, 300)]
        self.session = SimpleNamespace(stage_notes=[])
        self.calls = []

    def download(self, session, event, kind, dest, preserve_filename):
        self.assertEqual(kind, 3)
        self.assertTrue(preserve_filename)
        self.calls.append(event.start_time)
        target = dest.with_name('original.jpg')
        Image.new('RGB', (12, 8)).save(target, 'JPEG')
        return target

    def run_batch(self, download=None, limit=3):
        rows = load_rows(self.db, 'own', 1, 400)
        check_existing(self.db, 'own', rows, 1, 400, validate)
        return download_batch(self.session, self.db, 'own', rows, 1, 400, self.events,
                              self.root / 'media', limit, download or self.download, validate)

    def states(self):
        return [r[2] for r in load_rows(self.db, 'own', 1, 400)]

    def test_batch_and_skip_after_restart(self):
        self.assertEqual(self.run_batch(), 0)
        self.assertEqual(self.states(), ['downloaded', 'downloaded', 'pending'])
        self.run_batch()
        self.assertEqual(self.calls, [100, 200])
        with closing(sqlite3.connect(self.db)) as db:
            paths = db.execute('SELECT path FROM downloads').fetchall()
        self.assertEqual(len(paths), 2)
        self.assertNotEqual(paths[0], paths[1])
        self.assertTrue(all(Path(r[0]).name == 'original.jpg' for r in paths))

    def test_partial_failure_persists_first(self):
        def fail_second(session, event, kind, dest, preserve_filename):
            if event.start_time == 200:
                raise TimeoutError
            return self.download(session, event, kind, dest, preserve_filename)
        with self.assertRaises(TimeoutError):
            self.run_batch(fail_second)
        self.assertEqual(self.states(), ['downloaded', 'pending', 'pending'])
        self.run_batch()
        self.assertEqual(self.calls, [100, 200])

    def test_missing_and_ambiguous_do_not_download(self):
        self.events.pop(1)
        self.events.append(SimpleNamespace(start_time=101, event_type=4, length=65535))
        self.assertEqual(self.run_batch(), 2)
        self.assertEqual(self.calls, [])

    def test_modified_file_refused(self):
        self.run_batch(limit=1)
        with closing(sqlite3.connect(self.db)) as db:
            path, = db.execute('SELECT path FROM downloads').fetchone()
        Image.new('RGB', (20, 10)).save(path, 'JPEG')
        with self.assertRaises(ValueError):
            self.run_batch()
        self.assertEqual(self.calls, [100])

    def test_exclusive_batch_lock(self):
        with batch_lock(self.db):
            with self.assertRaises(BlockingIOError):
                with batch_lock(self.db):
                    pass
        with batch_lock(self.db):
            pass

    def test_invalid_image_never_committed(self):
        def invalid(session, event, kind, dest, preserve_filename):
            dest.write_bytes(b'not a photo')
            return dest
        with self.assertRaises(OSError):
            self.run_batch(invalid)
        self.assertEqual(self.states(), ['pending'] * 3)
