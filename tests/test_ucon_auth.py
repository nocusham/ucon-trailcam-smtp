import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from ucon_trailcam_smtp.ucon_auth import read_credentials


class CredentialTests(unittest.TestCase):
    def setUp(self):
        # Never inspect the installation's actual .env, even when the tests
        # run in a configured checkout. Keep the real credential parser active.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env_path = Path(tmp.name) / '.env'
        isolated = patch('ucon_trailcam_smtp.local_credentials._default_secret_path', return_value=self.env_path)
        isolated.start()
        self.addCleanup(isolated.stop)

    def assert_credentials(self, expected):
        # Do not let unittest print the actual credentials on a regression.
        self.assertTrue(read_credentials() == expected, 'Unexpected credential source or value')

    def test_environment_skips_prompts(self):
        with patch.dict('os.environ', {'UCON_ACCOUNT': 'example@example.invalid',
                                       'UCON_PASSWORD': ' synthetic secret '}, clear=True), \
             patch('builtins.input', side_effect=AssertionError('unexpected prompt')), \
             patch('getpass.getpass', side_effect=AssertionError('unexpected prompt')):
            self.assert_credentials(('example@example.invalid', ' synthetic secret '))

    def test_interactive_fallback(self):
        with patch.dict('os.environ', {}, clear=True), \
             patch('builtins.input', return_value=' example@example.invalid '), \
             patch('getpass.getpass', return_value='synthetic'):
            self.assert_credentials(('example@example.invalid', 'synthetic'))

    def test_partial_environment(self):
        with patch.dict('os.environ', {'UCON_ACCOUNT': 'example@example.invalid'}, clear=True), \
             patch('builtins.input', side_effect=AssertionError('unexpected prompt')), \
             patch('getpass.getpass', return_value='synthetic'):
            self.assert_credentials(('example@example.invalid', 'synthetic'))

    def test_missing_password_rejected(self):
        with patch.dict('os.environ', {'UCON_ACCOUNT': 'example@example.invalid'}, clear=True), \
             patch('getpass.getpass', return_value=''):
            with self.assertRaises(ValueError):
                read_credentials()

    def test_isolated_default_file_precedes_environment(self):
        self.env_path.write_text('UCON_ACCOUNT=file@example.invalid\nUCON_PASSWORD=fixture-only\n', encoding='utf-8')
        self.env_path.chmod(0o600)
        with patch.dict('os.environ', {'UCON_ACCOUNT': 'env@example.invalid',
                                       'UCON_PASSWORD': 'env-fixture'}, clear=True), \
             patch('builtins.input', side_effect=AssertionError('unexpected prompt')), \
             patch('getpass.getpass', side_effect=AssertionError('unexpected prompt')):
            self.assert_credentials(('file@example.invalid', 'fixture-only'))
