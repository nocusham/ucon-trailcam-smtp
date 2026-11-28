"""Offline runtime parser tests using only artificial credentials."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from deploy.config_compatibility import check_config
from ucon_trailcam_smtp.local_credentials import CredentialError


CONFIG = """[[cameras]]
name = "fixture"
uid = "synthetic"
enabled = true
[cameras.smtp]
host = "smtp.example.invalid"
from = "sender@example.invalid"
to = "recipient@example.invalid"
username = "fixture"
password_env = "SMTP_PASSWORD"
"""

SECRETS = "UCON_ACCOUNT=fixture\nUCON_PASSWORD=synthetic\nSMTP_PASSWORD=synthetic\n"


class ConfigCompatibilityTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.config = root / 'config.toml'
        self.secrets = root / '.env'
        self.config.write_text(CONFIG)
        self.secrets.write_text(SECRETS)
        self.secrets.chmod(0o600)

    def test_valid_configuration(self):
        self.assertEqual(check_config(self.config,self.secrets),
                         {'enabled_cameras':1,'alerts_enabled':False})

    def test_disabled_cameras_refused(self):
        self.config.write_text(CONFIG.replace('enabled = true','enabled = false'))
        with self.assertRaisesRegex(ValueError,'No enabled cameras'):
            check_config(self.config,self.secrets)

    def test_missing_cloud_secret(self):
        self.secrets.write_text(SECRETS.replace('UCON_PASSWORD=synthetic\n',''))
        with self.assertRaisesRegex(ValueError,'Missing cloud credentials'):
            check_config(self.config,self.secrets)

    def test_no_environment_fallback(self):
        self.secrets.write_text(SECRETS.replace('SMTP_PASSWORD=synthetic\n',''))
        with patch.dict(os.environ, {'SMTP_PASSWORD':'fixture-fallback'}):
            with self.assertRaisesRegex(ValueError,'Missing camera SMTP'):
                check_config(self.config,self.secrets)

    def test_unsafe_secret_mode(self):
        self.secrets.chmod(0o644)
        with self.assertRaises(CredentialError):
            check_config(self.config,self.secrets)

    def test_alert_password_required_only_when_enabled(self):
        self.config.write_text(CONFIG + """
[alerts]
enabled = true
[alerts.smtp]
host = "smtp.example.invalid"
from = "sender@example.invalid"
to = "recipient@example.invalid"
username = "fixture"
password_env = "ALERT_PASSWORD"
""")
        with self.assertRaisesRegex(ValueError,'Missing alert SMTP'):
            check_config(self.config,self.secrets)
        with self.secrets.open('a') as out:
            out.write('ALERT_PASSWORD=synthetic\n')
        self.assertTrue(check_config(self.config,self.secrets)['alerts_enabled'])


if __name__ == '__main__':
    unittest.main()
