"""Regression checks for moving pure diagnostic entrypoints out of runtime."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from smtp_settings import read_smtp_settings


class RuntimeBoundaryTests(unittest.TestCase):
    def test_no_runtime_imports_of_pure_diagnostic_entrypoints(self):
        root = Path(__file__).resolve().parents[1]
        tools = {'probe', 'cloud_probe', 'smtp_probe'}
        unexpected = []
        for path in sorted(root.glob('*.py')):
            if path.stem in tools:
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or '']
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    continue
                if any(name.split('.')[0] in tools | {'tools'} for name in names):
                    unexpected.append(f'{path.name}:{node.lineno}')
        self.assertEqual(unexpected, [])

    def test_legacy_probe_imports_share_tool_modules(self):
        import importlib

        for name in ('probe', 'cloud_probe', 'smtp_probe'):
            with self.subTest(name=name):
                legacy = importlib.import_module(name)
                tool = importlib.import_module(f'tools.{name}')
                self.assertIs(legacy, tool)
                self.assertEqual(Path(tool.__file__).parent.name, 'tools')

    def test_smtp_probe_reexports_shared_settings_reader(self):
        import smtp_probe

        self.assertIs(smtp_probe.read_smtp_settings, read_smtp_settings)

    def test_shared_settings_defaults_and_password_prompt(self):
        values = {'SMTP_HOST': 'example.invalid', 'SMTP_FROM': 'from@example.invalid',
                  'SMTP_TO': 'to@example.invalid', 'SMTP_USERNAME': 'fixture'}
        with patch('smtp_settings.read_secret_values', return_value=values), \
                patch('smtp_settings.getpass.getpass', return_value='fixture-password') as prompt:
            self.assertEqual(read_smtp_settings(),
                             ('from@example.invalid', 'to@example.invalid',
                              'example.invalid', 587, 'starttls',
                              'fixture', 'fixture-password'))
            prompt.assert_called_once_with('SMTP password: ')

    def test_shared_settings_rejects_password_without_username(self):
        values = {'SMTP_HOST': 'example.invalid', 'SMTP_FROM': 'from@example.invalid',
                  'SMTP_TO': 'to@example.invalid', 'SMTP_PASSWORD': 'fixture-password'}
        with patch('smtp_settings.read_secret_values', return_value=values), \
                patch('smtp_settings.getpass.getpass') as prompt:
            with self.assertRaisesRegex(ValueError, 'SMTP_USERNAME is required'):
                read_smtp_settings()
            prompt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
