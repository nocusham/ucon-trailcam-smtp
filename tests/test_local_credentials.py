import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_credentials import CredentialError, read_secret_values
from ucon_auth import read_credentials


class LocalCredentialsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / '.env'

    def write(self, content):
        self.path.write_text(content, encoding='utf-8')
        self.path.chmod(0o600)

    def test_literal_special_chars_and_file_precedence(self):
        password = " $x#'\"\\;= & $(false) "
        self.write('# comment\nUCON_PASSWORD=' + password + '\n')
        values = read_secret_values({'UCON_PASSWORD': 'old', 'SMTP_PASSWORD': 'fallback'}, path=self.path)
        self.assertEqual(values['UCON_PASSWORD'], password)
        self.assertEqual(values['SMTP_PASSWORD'], 'fallback')

    def test_private_mode_required(self):
        self.write('UCON_PASSWORD=secret\n')
        self.path.chmod(0o644)
        with self.assertRaises(CredentialError):
            read_secret_values({}, path=self.path)
        self.path.chmod(0o400)
        self.assertEqual(read_secret_values({}, path=self.path)['UCON_PASSWORD'], 'secret')

    def test_reject_symlinks_and_explicit_missing(self):
        target = self.path.with_name('target')
        target.write_text('PASS=secret')
        target.chmod(0o600)
        self.path.symlink_to(target)
        with self.assertRaises(CredentialError):
            read_secret_values({}, path=self.path)
        self.path.unlink()
        with self.assertRaises(CredentialError):
            read_secret_values({'UCON_SECRETS_FILE': str(self.path)})

    def test_reject_bad_lines_without_disclosing_secret(self):
        for bad in ('export PASS=private', 'PASS=private\nPASS=other', 'PASS=private\x00'):
            self.write(bad)
            with self.assertRaises(CredentialError) as caught:
                read_secret_values({}, path=self.path)
            self.assertNotIn('private', str(caught.exception))

    def test_ucon_reads_file_without_prompt(self):
        self.write('UCON_ACCOUNT=local@example.invalid\nUCON_PASSWORD=local-secret\n')
        with patch.dict(os.environ, {'UCON_SECRETS_FILE': str(self.path)}, clear=True):
            self.assertEqual(read_credentials(interactive=False), ('local@example.invalid', 'local-secret'))

    def test_no_prompt_if_noninteractive(self):
        with patch('ucon_auth.read_secret_values', return_value={}), patch('builtins.input') as prompt:
            with self.assertRaises(ValueError):
                read_credentials(interactive=False)
            prompt.assert_not_called()
