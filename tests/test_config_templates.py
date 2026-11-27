"""Validate public templates without opening any private configuration."""
from pathlib import Path
import tempfile
import tomllib
import unittest

from ucon_trailcam_smtp.camera_smtp import load_profiles
from ucon_trailcam_smtp.health_alerts import parse_alerts
from ucon_trailcam_smtp.download_retry import parse_retry
from ucon_trailcam_smtp.media_retention import parse_retention
from ucon_trailcam_smtp.local_credentials import read_secret_values


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'config'


class ConfigTemplateTests(unittest.TestCase):
    def test_public_configuration_parses_with_safe_defaults(self):
        path = CONFIG / 'config.example.toml'
        profiles = load_profiles(path)
        self.assertEqual(len(profiles), 1)
        profile = profiles[0]
        self.assertEqual(profile.uid, 'REPLACE_WITH_CAMERA_UID')
        self.assertEqual(profile.name, 'testkamera')
        self.assertEqual(profile.host, 'smtp.example.invalid')
        self.assertEqual(profile.security, 'starttls')
        self.assertEqual(profile.mode, 'single')
        with path.open('rb') as source:
            raw = tomllib.load(source)
        self.assertFalse(parse_alerts(raw['alerts']).enabled)
        self.assertFalse(parse_retention(raw['retention']).enabled)
        self.assertEqual(parse_retry(raw['download_retry']), parse_retry(None))

    def test_public_credentials_are_empty_and_parse_as_literals(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '.env'
            path.write_bytes((CONFIG / '.env.example').read_bytes())
            path.chmod(0o600)
            self.assertEqual(read_secret_values({}, path=path), {
                'UCON_ACCOUNT': '', 'UCON_PASSWORD': '', 'SMTP_PASSWORD': '',
            })

    def test_templates_exist_only_in_config_directory(self):
        for name in ('config.example.toml', '.env.example'):
            with self.subTest(name=name):
                self.assertTrue((CONFIG / name).is_file())
                self.assertFalse((ROOT / name).exists())


if __name__ == '__main__':
    unittest.main()
