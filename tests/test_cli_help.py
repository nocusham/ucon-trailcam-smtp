"""Offline compatibility checks for the manual diagnostic CLI entrypoints."""
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def normalized_help(text, tool):
    """Ignore only argparse's generated usage program name and wrapping."""
    usage, separator, body = text.partition('\n\n')
    if not separator:
        raise ValueError('Missing help body')
    usage = ' '.join(usage.split())
    for prefix in (f'usage: python -m tools.{tool}', f'usage: {tool}.py'):
        if usage == prefix or usage.startswith(prefix + ' '):
            return usage[len(prefix):].strip(), body
    raise ValueError(f'Unexpected usage prefix for {tool}')


class ToolHelpTests(unittest.TestCase):
    def test_legacy_and_module_help_match(self):
        env = dict(os.environ, COLUMNS='100', PYTHONDONTWRITEBYTECODE='1')
        for tool in ('probe', 'cloud_probe', 'smtp_probe'):
            with self.subTest(tool=tool):
                legacy = subprocess.run(
                    [sys.executable, f'{tool}.py', '--help'], cwd=ROOT,
                    env=env, capture_output=True, text=True, check=True, timeout=15)
                module = subprocess.run(
                    [sys.executable, '-m', f'tools.{tool}', '--help'], cwd=ROOT,
                    env=env, capture_output=True, text=True, check=True, timeout=15)
                self.assertEqual(legacy.stderr, '')
                self.assertEqual(module.stderr, '')
                self.assertEqual(normalized_help(legacy.stdout, tool),
                                 normalized_help(module.stdout, tool))


if __name__ == '__main__':
    unittest.main()
