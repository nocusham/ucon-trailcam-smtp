import unittest
from unittest.mock import patch
from ucon_auth import read_credentials


class CredentialTests(unittest.TestCase):
    def test_environment_skips_prompts(self):
        with patch.dict('os.environ', {'UCON_ACCOUNT': 'example@example.invalid',
                                       'UCON_PASSWORD': ' synthetic secret '}, clear=True), \
             patch('builtins.input', side_effect=AssertionError('unexpected prompt')), \
             patch('getpass.getpass', side_effect=AssertionError('unexpected prompt')):
            self.assertEqual(read_credentials(), ('example@example.invalid', ' synthetic secret '))

    def test_interactive_fallback(self):
        with patch.dict('os.environ', {}, clear=True), \
             patch('builtins.input', return_value=' example@example.invalid '), \
             patch('getpass.getpass', return_value='synthetic'):
            self.assertEqual(read_credentials(), ('example@example.invalid', 'synthetic'))

    def test_partial_environment(self):
        with patch.dict('os.environ', {'UCON_ACCOUNT': 'example@example.invalid'}, clear=True), \
             patch('builtins.input', side_effect=AssertionError('unexpected prompt')), \
             patch('getpass.getpass', return_value='synthetic'):
            self.assertEqual(read_credentials(), ('example@example.invalid', 'synthetic'))

    def test_missing_password_rejected(self):
        with patch.dict('os.environ', {'UCON_ACCOUNT': 'example@example.invalid'}, clear=True), \
             patch('getpass.getpass', return_value=''):
            with self.assertRaises(ValueError):
                read_credentials()
