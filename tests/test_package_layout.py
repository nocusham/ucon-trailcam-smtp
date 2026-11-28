"""Regression checks for the src layout and source/installed credentials."""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from ucon_trailcam_smtp.local_credentials import _default_secret_path, read_secret_values
from tests.test_cli_help import normalized_help


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = 'ucon_trailcam_smtp'
CLI = ('trailcam_service', 'cloud_intake', 'camera_smtp', 'queue_smtp',
       'health_alerts', 'media_retention')


class PackageLayoutTests(unittest.TestCase):
    def test_source_checkout_default_secrets_path(self):
        self.assertEqual(_default_secret_path(), ROOT / '.env')

    def test_installed_package_does_not_search_implicit_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            module = Path(tmp) / 'site-packages' / PACKAGE / 'local_credentials.py'
            module.parent.mkdir(parents=True)
            accidental = module.with_name('.env')
            accidental.write_text('UCON_ACCOUNT=unexpected\n', encoding='utf-8')
            accidental.chmod(0o600)
            with patch(PACKAGE + '.local_credentials.__file__', str(module)):
                self.assertIsNone(_default_secret_path())
                self.assertEqual(read_secret_values({'UCON_ACCOUNT': 'fixture'}),
                                 {'UCON_ACCOUNT': 'fixture'})
                self.assertEqual(read_secret_values({}, path=accidental),
                                 {'UCON_ACCOUNT': 'unexpected'})

    def test_legacy_runtime_module_identity(self):
        for name in CLI:
            with self.subTest(name=name):
                self.assertIs(importlib.import_module(name),
                              importlib.import_module(f'{PACKAGE}.{name}'))

    def test_package_imports_without_repository_root(self):
        modules = sorted(path.stem for path in (ROOT / 'src' / PACKAGE).glob('*.py')
                         if path.stem != '__init__')
        self.assertGreater(len(modules), 30)
        env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'),
                   PYTHONDONTWRITEBYTECODE='1')
        code = ('import importlib, sys\n'
                'for name in sys.argv[1:]:\n'
                '    importlib.import_module(name)\n')
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, '-c', code, *(f'{PACKAGE}.{name}' for name in modules)],
                cwd=tmp, env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')
        self.assertEqual(result.stderr, '')

    def test_runtime_module_help_matches_legacy(self):
        env = dict(os.environ, COLUMNS='100', PYTHONPATH=str(ROOT / 'src'),
                   PYTHONDONTWRITEBYTECODE='1')
        for name in CLI:
            with self.subTest(name=name):
                legacy = subprocess.run(
                    [sys.executable, f'{name}.py', '--help'], cwd=ROOT,
                    env=env, capture_output=True, text=True, check=True, timeout=15)
                module = subprocess.run(
                    [sys.executable, '-m', f'{PACKAGE}.{name}', '--help'], cwd=ROOT,
                    env=env, capture_output=True, text=True, check=True, timeout=15)
                self.assertEqual(legacy.stderr, '')
                self.assertEqual(module.stderr, '')
                self.assertEqual(normalized_help(legacy.stdout, name, namespace=PACKAGE),
                                 normalized_help(module.stdout, name, namespace=PACKAGE))


if __name__ == '__main__':
    unittest.main()
