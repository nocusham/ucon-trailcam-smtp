"""Synthetic release archive checks; no third-party installation or publication."""
import json
from pathlib import Path
import tempfile
import unittest
import warnings
import zipfile

from deploy.release_bundle import (
    FILES, README, PAYLOAD, MANIFEST, PROJECT_WHEEL, WHEEL,
    build_bundle, verify_bundle, write_entry,
)


class ReleaseBundleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / 'source'
        for name in (*FILES, README):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('synthetic public fixture\n')
        module = self.source / 'src/ucon_trailcam_smtp/__init__.py'
        module.parent.mkdir(parents=True)
        module.write_text('# synthetic runtime\n')
        self.wheel = self.root / PROJECT_WHEEL
        prefix = 'ucon_trailcam_smtp-0.0.0.dev0.dist-info/'
        with zipfile.ZipFile(self.wheel, 'w') as wheel:
            wheel.writestr('ucon_trailcam_smtp/__init__.py', module.read_bytes())
            wheel.writestr(prefix + 'METADATA', 'Name: ucon-trailcam-smtp\nVersion: 0.0.0.dev0\n')
            wheel.writestr(prefix + 'WHEEL', 'synthetic')
            wheel.writestr(prefix + 'RECORD', '')
            wheel.writestr(prefix + 'entry_points.txt',
                           '[console_scripts]\nucon-trailcam-smtp = ucon_trailcam_smtp.trailcam_service:main\n')
            wheel.writestr(prefix + 'licenses/LICENSE', (self.source / 'LICENSE').read_bytes())
        self.commit = 'a' * 40
        self.bundle = self.root / 'bundle.zip'

    def build(self, destination=None):
        return build_bundle(self.source, self.wheel, self.commit, destination or self.bundle)

    def rewrite(self, transform):
        with zipfile.ZipFile(self.bundle) as archive:
            items = [(name, archive.read(name)) for name in archive.namelist()]
        with zipfile.ZipFile(self.bundle, 'w') as archive:
            for name, value in transform(items):
                write_entry(archive, name, value)

    def test_allowlist_excludes_private_and_development_files(self):
        for name in ('.env', 'data/events.sqlite3', 'tests/test_fixture.py',
                     'tools/probe.py', 'dist/p4p_camera_sdk.whl'):
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('must never enter bundle')
        manifest = self.build()
        self.assertEqual(set(manifest['files']), PAYLOAD)
        self.assertEqual(verify_bundle(self.bundle, self.commit), manifest)
        with zipfile.ZipFile(self.bundle) as archive:
            self.assertEqual(set(archive.namelist()), PAYLOAD | {MANIFEST})
            self.assertEqual(archive.read(WHEEL), self.wheel.read_bytes())

    def test_identical_inputs_produce_identical_zip(self):
        self.build()
        other = self.root / 'second.zip'
        self.build(other)
        self.assertEqual(self.bundle.read_bytes(), other.read_bytes())

    def test_existing_output_not_overwritten(self):
        self.bundle.write_bytes(b'operator file')
        with self.assertRaises(FileExistsError):
            self.build()
        self.assertEqual(self.bundle.read_bytes(), b'operator file')

    def test_missing_or_symlinked_input_refused(self):
        path = self.source / FILES[0]
        path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.build()
        path.symlink_to(self.source / FILES[1])
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.bundle.exists())

    def test_bad_wheel_rejected(self):
        with zipfile.ZipFile(self.wheel, 'a') as archive:
            archive.writestr('private.env', 'synthetic')
        with self.assertRaises(ValueError):
            self.build()
        self.assertFalse(self.bundle.exists())

    def test_changed_payload_detected(self):
        self.build()
        self.rewrite(lambda items: [(n, b'changed' if n == 'LICENSE' else v)
                                    for n, v in items])
        with self.assertRaisesRegex(ValueError, 'digest mismatch'):
            verify_bundle(self.bundle)

    def test_extra_missing_and_duplicate_paths_refused(self):
        self.build()
        original = self.bundle.read_bytes()
        for transform in (lambda items: items + [('../escape', b'x')],
                          lambda items: items[1:],
                          lambda items: items + [items[0]]):
            with self.subTest(transform=transform):
                self.bundle.write_bytes(original)
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    self.rewrite(transform)
                with self.assertRaisesRegex(ValueError, 'bundle paths'):
                    verify_bundle(self.bundle)

    def test_commit_validation(self):
        with self.assertRaises(ValueError):
            build_bundle(self.source, self.wheel, 'main', self.bundle)
        self.build()
        with self.assertRaisesRegex(ValueError, 'commit mismatch'):
            verify_bundle(self.bundle, 'b' * 40)


if __name__ == '__main__':
    unittest.main()
