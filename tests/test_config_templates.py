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
        self.assertEqual(profile.download_batch_limit, 3)
        with path.open('rb') as source:
            raw = tomllib.load(source)
        self.assertFalse(parse_alerts(raw['alerts']).enabled)
        self.assertTrue(parse_retention(raw['retention']).enabled)
        self.assertEqual(parse_retention(raw['retention']).image_seconds, 86400)
        self.assertEqual(parse_retention(raw['retention']).incomplete_days, 7)
        self.assertEqual(parse_retry(raw['download_retry']), parse_retry(None))
        from ucon_trailcam_smtp.smtp_pacing import parse_interval
        self.assertEqual(parse_interval(raw['smtp_pacing']), 30)

    def test_global_and_per_camera_download_limits(self):
        entry = (
            '[[cameras]]\nname = "one"\nuid = "fixture1"\n'
            '[cameras.smtp]\nhost = "smtp.example.invalid"\n'
            'from = "sender@example.invalid"\nto = "recipient@example.invalid"\n'
        )
        second = entry.replace('"one"', '"two"').replace('"fixture1"', '"fixture2"')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config.toml'
            path.write_text(entry + second)
            self.assertEqual([p.download_batch_limit for p in load_profiles(path)], [3, 3])
            path.write_text('[download]\nbatch_limit = 12\n' + entry + second +
                            '[cameras.download]\nbatch_limit = 100\n')
            profiles = load_profiles(path)
            self.assertEqual([p.download_batch_limit for p in profiles], [12, 100])
            self.assertEqual([p.limit for p in profiles], [3, 3])
            for suffix in ('[cameras.download]\nbatch_limit = 101\n',
                           '[cameras.download]\nbatch_limit = true\n',
                           '[cameras.download]\nunknown = 2\n'):
                path.write_text(entry + suffix)
                with self.subTest(suffix=suffix), self.assertRaises(ValueError):
                    load_profiles(path)

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
