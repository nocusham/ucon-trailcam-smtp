"""Exercise handoff with disposable same-owner files, never root operations."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deploy.release_handoff import _handoff, handoff_candidate, build_candidate
from deploy.release_layout import ReleaseError


class ReleaseHandoffTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.releases = self.root / 'releases'
        self.releases.mkdir(mode=0o700)
        self.source = self.releases / 'v1'
        self.source.mkdir(mode=0o700)
        self.venv = self.source / 'venv'
        self.venv.mkdir(mode=0o700)
        self.bin = self.venv / 'bin'
        self.bin.mkdir(mode=0o700)
        (self.venv / 'lib').mkdir(mode=0o700)
        self.file(self.venv / 'pyvenv.cfg', b'fixture config', 0o600)
        self.file(self.bin / 'python', b'fixture executable', 0o700)
        self.file(self.bin / 'ucon-trailcam-smtp', b'fixture console', 0o700)
        self.identity = (os.geteuid(), os.getegid())
        self.state = self.root / 'state'
        self.state.write_bytes(b'newest receipt')

    @staticmethod
    def file(path, content, mode):
        path.write_bytes(content)
        path.chmod(mode)

    def handoff(self):
        return _handoff(self.root, 'v1', self.identity, self.identity)

    def test_fresh_inodes_and_normalized_modes_at_same_path(self):
        original = self.bin / 'python'
        before = original.stat().st_ino
        # An open source descriptor still refers to the quarantined inode.
        with original.open('r+b') as old:
            quarantine = self.handoff()
            self.assertNotEqual(original.stat().st_ino, before)
            self.assertEqual((quarantine / 'venv/bin/python').stat().st_ino, before)
            old.seek(0)
            old.write(b'changed')
            old.flush()
        self.assertEqual(original.read_bytes(), b'fixture executable')
        self.assertEqual(original.stat().st_mode & 0o777, 0o755)
        self.assertEqual((self.venv / 'pyvenv.cfg').stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.source.stat().st_mode & 0o777, 0o755)
        self.assertFalse((self.source / '.ready').exists())
        self.assertFalse((self.root / 'current').exists())
        self.assertEqual(self.state.read_bytes(), b'newest receipt')

    def test_only_expected_relative_lib64_symlink_allowed(self):
        (self.venv / 'lib64').symlink_to('lib')
        self.handoff()
        self.assertEqual(os.readlink(self.venv / 'lib64'), 'lib')

    def test_unexpected_symlink_refused(self):
        (self.venv / 'lib/escape').symlink_to(self.state)
        with self.assertRaisesRegex(ReleaseError, 'symlink'):
            self.handoff()
        self.assertEqual(self.state.read_bytes(), b'newest receipt')
        self.assertFalse((self.source / '.ready').exists())

    def test_hardlink_refused(self):
        os.link(self.bin / 'python', self.bin / 'another')
        with self.assertRaisesRegex(ReleaseError, 'Hardlinked'):
            self.handoff()

    def test_unsafe_mode_refused(self):
        (self.bin / 'python').chmod(0o4755)
        with self.assertRaisesRegex(ReleaseError, 'Unsafe source mode'):
            self.handoff()

    def test_fifo_refused_without_opening(self):
        os.mkfifo(self.venv / 'lib/pipe', 0o600)
        with self.assertRaisesRegex(ReleaseError, 'file type'):
            self.handoff()

    def test_ready_marker_refused(self):
        self.file(self.source / '.ready', b'v1\n', 0o600)
        with self.assertRaisesRegex(ReleaseError, 'no readiness marker'):
            self.handoff()

    def test_bad_interpreter_symlink_refused(self):
        (self.bin / 'python').unlink()
        (self.bin / 'python').symlink_to('/usr/bin/python3')
        with self.assertRaisesRegex(ReleaseError, 'copied executable'):
            self.handoff()

    def test_failed_copy_never_renames_source(self):
        with patch('deploy.release_handoff._copy_file', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                self.handoff()
        self.assertEqual((self.bin / 'python').read_bytes(), b'fixture executable')
        self.assertFalse((self.source / '.ready').exists())

    def test_failed_final_rename_restores_original(self):
        rename = os.rename
        def fail_once(source, destination):
            if Path(source).name == 'copy':
                raise OSError('fixture')
            rename(source, destination)
        with patch('deploy.release_handoff.os.rename', side_effect=fail_once):
            with self.assertRaises(OSError):
                self.handoff()
        self.assertTrue((self.bin / 'python').is_file())
        self.assertFalse((self.source / '.ready').exists())

    def test_public_privilege_guards(self):
        with patch('deploy.release_handoff.os.geteuid', return_value=1234):
            with self.assertRaisesRegex(ReleaseError, 'Administrator identity'):
                handoff_candidate(self.root, 'v1', 1234, 1234)
        with patch('deploy.release_handoff.os.geteuid', return_value=0):
            with self.assertRaisesRegex(ReleaseError, 'must not run as root'):
                build_candidate(self.source, self.state, '0' * 64, self.root)


if __name__ == '__main__':
    unittest.main()
