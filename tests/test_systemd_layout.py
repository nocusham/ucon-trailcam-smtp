"""Static deployment contract checks; no systemd manager or live operations."""
import configparser
from pathlib import Path
import shlex
import unittest


ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / 'deploy' / 'systemd' / 'ucon-trailcam-smtp.service'


class SystemdLayoutTests(unittest.TestCase):
    def setUp(self):
        self.unit = configparser.ConfigParser(interpolation=None)
        # systemd permits repeated Environment= directives.
        with UNIT.open(encoding='utf-8') as source:
            lines = source.read().splitlines()
        self.environ = [line.partition('=')[2] for line in lines
                        if line.startswith('Environment=')]
        self.unit.read_string('\n'.join(line for line in lines
                                       if not line.startswith('Environment=')))
        self.service = self.unit['Service']

    def test_dedicated_identity_and_private_state(self):
        self.assertEqual(self.service['User'], 'ucon-trailcam-smtp')
        self.assertEqual(self.service['Group'], self.service['User'])
        self.assertEqual(self.service['UMask'], '0077')
        self.assertEqual(self.service['StateDirectory'], 'ucon-trailcam-smtp')
        self.assertEqual(self.service['StateDirectoryMode'], '0700')
        self.assertEqual(self.service['WorkingDirectory'], '/var/lib/ucon-trailcam-smtp')
        self.assertEqual(self.service['ProtectSystem'], 'strict')
        self.assertEqual(self.service['ProtectHome'], 'yes')
        self.assertEqual(self.service['NoNewPrivileges'], 'yes')
        self.assertEqual(self.service['CapabilityBoundingSet'], '')
        self.assertEqual(self.service['AmbientCapabilities'], '')

    def test_explicit_activation_and_persistent_paths(self):
        self.assertEqual(self.unit['Unit']['ConditionPathExists'],
                         '/etc/ucon-trailcam-smtp/service-enabled')
        self.assertEqual(self.environ, [
            'UCON_SECRETS_FILE=/etc/ucon-trailcam-smtp/.env',
            'PYTHONUNBUFFERED=1', 'PYTHONDONTWRITEBYTECODE=1'])
        self.assertNotIn('EnvironmentFile', self.service)
        self.assertEqual(shlex.split(self.service['ExecStart']), [
            '/opt/ucon-trailcam-smtp/current/venv/bin/ucon-trailcam-smtp',
            '--config', '/etc/ucon-trailcam-smtp/config.toml',
            '--queue-db', '/var/lib/ucon-trailcam-smtp/events.sqlite3',
            '--output-dir', '/var/lib/ucon-trailcam-smtp/media',
            '--loop', '--interval', '60', '--batch-limit', '3',
            '--download', '--send', '--send-alerts'])

    def test_restart_stop_and_logging(self):
        self.assertEqual(self.service['Restart'], 'on-failure')
        self.assertEqual(self.service['RestartSec'], '30s')
        self.assertEqual(self.unit['Unit']['StartLimitBurst'], '3')
        self.assertEqual(self.unit['Unit']['StartLimitIntervalSec'], '300')
        self.assertEqual(self.service['KillSignal'], 'SIGINT')
        self.assertEqual(self.service['SuccessExitStatus'], '130')
        self.assertEqual(self.service['TimeoutStopSec'], '180s')
        self.assertEqual(self.service['StandardOutput'], 'journal')
        self.assertEqual(self.service['StandardError'], 'journal')


if __name__ == '__main__':
    unittest.main()
