"""Exercise release switching only in synthetic temporary installations."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deploy.release_layout import ReleaseError, switch_release


class ReleaseLayoutTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'opt'
        self.root.mkdir()
        (self.root / 'releases').mkdir()
        self.state = self.base / 'state'
        self.state.mkdir()
        self.db = self.state / 'events.sqlite3'
        self.db.write_bytes(b'synthetic database receipt')
        self.config = self.base / 'config.toml'
        self.config.write_bytes(b'synthetic private configuration')
        self.media = self.state / 'original.jpg'
        self.media.write_bytes(b'synthetic original')
        self.old = self.prepare('v1')
        self.new = self.prepare('v2')

    def prepare(self, release):
        directory = self.root / 'releases' / release
        executable = directory / 'venv/bin/ucon-trailcam-smtp'
        executable.parent.mkdir(parents=True)
        executable.write_text('#!/bin/sh\nexit 99\n', encoding='utf-8')
        executable.chmod(0o755)
        (directory / '.ready').write_text(release + '\n', encoding='ascii')
        return directory

    def selected(self):
        return os.readlink(self.root / 'current')

    def test_first_selection_and_idempotence(self):
        self.assertIsNone(switch_release(self.root, 'v1'))
        self.assertEqual(self.selected(), 'releases/v1')
        inode = (self.root / 'current').lstat().st_ino
        self.assertEqual(switch_release(self.root, 'v1'), 'v1')
        self.assertEqual((self.root / 'current').lstat().st_ino, inode)

    def test_update_then_code_only_rollback_preserves_private_state(self):
        before = {p: p.read_bytes() for p in (self.db, self.config, self.media)}
        switch_release(self.root, 'v1')
        self.assertEqual(switch_release(self.root, 'v2'), 'v1')
        self.assertEqual(self.selected(), 'releases/v2')
        # Simulate a new accepted delivery after the update.
        self.db.write_bytes(b'new confirmed receipt')
        before[self.db] = self.db.read_bytes()
        self.assertEqual(switch_release(self.root, 'v1'), 'v2')
        self.assertEqual(self.selected(), 'releases/v1')
        self.assertTrue(self.old.is_dir() and self.new.is_dir())
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)

    def test_invalid_release_ids_are_refused(self):
        for release in ('', '.', '..', '../v1', '/tmp/v1', 'v1/v2', 'v 1', 'v..1'):
            with self.subTest(release=release), self.assertRaises(ReleaseError):
                switch_release(self.root, release)
        self.assertFalse((self.root / 'current').exists())

    def test_missing_or_mismatched_ready_marker_keeps_previous(self):
        switch_release(self.root, 'v1')
        marker = self.new / '.ready'
        marker.unlink()
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'v2')
        marker.write_text('v1\n', encoding='ascii')
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'v2')
        self.assertEqual(self.selected(), 'releases/v1')

    def test_missing_or_nonexecutable_entrypoint_keeps_previous(self):
        switch_release(self.root, 'v1')
        executable = self.new / 'venv/bin/ucon-trailcam-smtp'
        executable.chmod(0o600)
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'v2')
        executable.unlink()
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'v2')
        self.assertEqual(self.selected(), 'releases/v1')

    def test_symlinked_release_and_entrypoint_are_refused(self):
        (self.root / 'releases' / 'alias').symlink_to(self.old)
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'alias')
        executable = self.new / 'venv/bin/ucon-trailcam-smtp'
        executable.unlink()
        executable.symlink_to(self.old / 'venv/bin/ucon-trailcam-smtp')
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'v2')

    def test_invalid_existing_current_is_not_overwritten(self):
        current = self.root / 'current'
        current.write_text('operator file', encoding='ascii')
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'v1')
        self.assertEqual(current.read_text(encoding='ascii'), 'operator file')
        current.unlink()
        current.symlink_to(self.old)
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'v1')
        self.assertEqual(os.readlink(current), str(self.old))
        current.unlink()
        current.symlink_to('releases/missing')
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'v1')
        self.assertEqual(os.readlink(current), 'releases/missing')

    def test_failed_atomic_replace_preserves_previous(self):
        switch_release(self.root, 'v1')
        with patch('deploy.release_layout.os.replace', side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                switch_release(self.root, 'v2')
        self.assertEqual(self.selected(), 'releases/v1')
        self.assertEqual(list(self.root.glob('.switch-*')), [])


if __name__ == '__main__':
    unittest.main()
