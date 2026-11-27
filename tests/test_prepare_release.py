"""Synthetic staging checks; no pip install or host changes during discovery."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from deploy.prepare_release import PROJECT_WHEEL, prepare_release
from deploy.release_layout import ReleaseError, switch_release


class PrepareReleaseTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / 'opt'
        (self.root / 'releases').mkdir(parents=True)
        self.house = self.base / 'wheelhouse'
        self.house.mkdir()
        self.wheel = self.base / PROJECT_WHEEL
        self.wheel.write_bytes(b'synthetic trusted project wheel')
        self.digest = hashlib.sha256(self.wheel.read_bytes()).hexdigest()
        self.state = self.base / 'events.sqlite3'
        self.state.write_bytes(b'accepted receipt')

    @staticmethod
    def fake_install(directory, wheel, wheelhouse):
        executable = directory / 'venv/bin/ucon-trailcam-smtp'
        executable.parent.mkdir(parents=True)
        executable.write_text('#!/bin/sh\nexit 99\n', encoding='ascii')
        executable.chmod(0o700)

    def prepare(self, release='v1', digest=None):
        return prepare_release(self.root, release, self.wheel,
                               self.digest if digest is None else digest, self.house)

    def test_successful_staging_does_not_activate(self):
        with patch('deploy.prepare_release._install_and_check', side_effect=self.fake_install):
            directory = self.prepare()
        self.assertEqual(directory, self.root / 'releases/v1')
        self.assertEqual((directory / '.ready').read_text(), 'v1\n')
        self.assertFalse((self.root / 'current').exists())
        self.assertEqual(self.state.read_bytes(), b'accepted receipt')

    def test_update_stages_without_changing_current_or_state(self):
        with patch('deploy.prepare_release._install_and_check', side_effect=self.fake_install):
            self.prepare()
            switch_release(self.root, 'v1')
            self.prepare('v2')
        self.assertEqual(os.readlink(self.root / 'current'), 'releases/v1')
        self.assertEqual(self.state.read_bytes(), b'accepted receipt')
        self.assertTrue((self.root / 'releases/v2/.ready').is_file())

    def test_failed_install_is_not_ready_or_selectable(self):
        with patch('deploy.prepare_release._install_and_check',
                   side_effect=subprocess.CalledProcessError(1, ['fixture'])):
            with self.assertRaises(subprocess.CalledProcessError):
                self.prepare()
        self.assertTrue((self.root / 'releases/v1').is_dir())
        self.assertFalse((self.root / 'releases/v1/.ready').exists())
        with self.assertRaises(ReleaseError):
            switch_release(self.root, 'v1')

    def test_wrong_digest_refused_before_installation(self):
        with patch('deploy.prepare_release._install_and_check') as install:
            with self.assertRaises(ReleaseError):
                self.prepare(digest='0' * 64)
            install.assert_not_called()
        self.assertFalse((self.root / 'releases/v1').exists())

    def test_existing_release_never_overwritten(self):
        with patch('deploy.prepare_release._install_and_check', side_effect=self.fake_install) as install:
            directory = self.prepare()
            marker = (directory / '.ready').read_bytes()
            with self.assertRaises(ReleaseError):
                self.prepare()
            self.assertEqual(install.call_count, 1)
        self.assertEqual((directory / '.ready').read_bytes(), marker)

    def test_symlink_release_directory_and_writable_root_refused(self):
        releases = self.root / 'releases'
        releases.rmdir()
        releases.symlink_to(self.house)
        with patch('deploy.prepare_release._install_and_check') as install:
            with self.assertRaises(ReleaseError):
                self.prepare()
            releases.unlink()
            releases.mkdir()
            self.root.chmod(0o777)
            with self.assertRaises(ReleaseError):
                self.prepare()
            install.assert_not_called()

    def test_missing_entrypoint_prevents_readiness(self):
        with patch('deploy.prepare_release._install_and_check'):
            with self.assertRaises(FileNotFoundError):
                self.prepare()
        self.assertFalse((self.root / 'releases/v1/.ready').exists())

    def test_invalid_id_refused_before_installation(self):
        with patch('deploy.prepare_release._install_and_check') as install:
            with self.assertRaises(ReleaseError):
                self.prepare('../outside')
            install.assert_not_called()
        self.assertFalse((self.root / 'outside').exists())


if __name__ == '__main__':
    unittest.main()
