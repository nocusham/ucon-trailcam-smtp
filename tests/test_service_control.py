"""Synthetic filesystem and mocked systemctl; never stop a real service."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from deploy.production_layout import APP
from deploy.release_layout import ReleaseError
from deploy.service_control import (
    FRAGMENT, PROPERTIES, UNIT, _ServiceControl, _parse_properties, _run,
    production_service_control,
)


class ServiceControlTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.root.chmod(0o755)
        for path in ('etc', 'etc/systemd', 'etc/systemd/system'):
            folder = self.root / path
            folder.mkdir(mode=0o755)
            folder.chmod(0o755)
        self.config = self.root / 'etc' / APP
        self.config.mkdir(mode=0o750)
        self.config.chmod(0o750)
        self.marker = self.config / 'service-enabled'
        self.fragment = self.root / FRAGMENT.lstrip('/')
        self.fragment.write_bytes(b'synthetic approved unit')
        self.fragment.chmod(0o644)
        self.values = {
            'LoadState': 'loaded', 'ActiveState': 'inactive', 'SubState': 'dead',
            'MainPID': '0', 'ControlPID': '0', 'Job': '0',
            'FragmentPath': FRAGMENT, 'DropInPaths': '', 'NeedDaemonReload': 'no',
            'KillMode': 'control-group', 'SendSIGKILL': 'yes',
        }
        self.commands = []
        self.runner = Mock(side_effect=self.respond)
        self.control = _ServiceControl(
            self.root, (os.geteuid(), os.getegid()),
            hashlib.sha256(self.fragment.read_bytes()).hexdigest(), self.runner)

    def respond(self, args):
        self.commands.append(args)
        if args[0] == 'show':
            return '\n'.join(f'{k}={v}' for k, v in self.values.items())
        if args == ['stop', UNIT]:
            self.values.update(ActiveState='inactive', SubState='dead', MainPID='0')
            return ''
        raise AssertionError('Unexpected command')

    def enable_marker(self):
        self.marker.touch(mode=0o644)
        self.marker.chmod(0o644)

    def test_inhibit_stop_and_check_order(self):
        self.enable_marker()
        self.values.update(ActiveState='active', SubState='running', MainPID='123')
        self.assertTrue(self.control.inhibit_start())
        self.assertFalse(self.marker.exists())
        self.assertTrue(self.control.quiesce())
        self.assertTrue(self.control.is_quiescent())
        self.assertEqual([c[0] for c in self.commands],
                         ['show','show','stop','show','show'])
        self.assertTrue(all(c[-1] == UNIT for c in self.commands))

    def test_inhibit_absent_marker_is_idempotent(self):
        self.assertTrue(self.control.inhibit_start())
        self.assertTrue(self.control.inhibit_start())
        self.assertFalse(self.marker.exists())

    def test_stop_requires_marker_absent(self):
        self.enable_marker()
        with self.assertRaisesRegex(ReleaseError, 'Inhibit start'):
            self.control.quiesce()
        self.assertTrue(self.marker.exists())
        self.assertNotIn('stop', [c[0] for c in self.commands])

    def test_unsafe_marker_refused_without_unlink(self):
        self.marker.symlink_to('missing')
        with self.assertRaisesRegex(ReleaseError, 'Unsafe administrator file'):
            self.control.inhibit_start()
        self.assertTrue(self.marker.is_symlink())
        self.marker.unlink()
        self.enable_marker()
        self.marker.chmod(0o666)
        with self.assertRaises(ReleaseError):
            self.control.inhibit_start()

    def test_changed_unit_digest_refused(self):
        self.enable_marker()
        self.fragment.write_bytes(b'changed')
        with self.assertRaisesRegex(ReleaseError, 'unit digest'):
            self.control.inhibit_start()
        self.assertTrue(self.marker.exists())
        self.runner.assert_not_called()

    def test_unexpected_unit_properties_fail_closed(self):
        self.enable_marker()
        for key, bad in (('LoadState','not-found'), ('FragmentPath','/tmp/unit'),
                         ('DropInPaths','/tmp/override.conf'),
                         ('NeedDaemonReload','yes'), ('KillMode','process'),
                         ('SendSIGKILL','no')):
            with self.subTest(key=key):
                original = self.values[key]
                self.values[key] = bad
                with self.assertRaisesRegex(ReleaseError, 'Unexpected loaded unit'):
                    self.control.inhibit_start()
                self.values[key] = original
                self.assertTrue(self.marker.exists())

    def test_active_pid_or_pending_job_refused(self):
        for key, bad in (('ActiveState','active'), ('SubState','running'),
                         ('MainPID','123'), ('ControlPID','456'), ('Job','99')):
            with self.subTest(key=key):
                original = self.values[key]
                self.values[key] = bad
                self.assertFalse(self.control.is_quiescent())
                self.values[key] = original
        self.enable_marker()
        self.assertFalse(self.control.is_quiescent())

    def test_stop_failure_does_not_restore_marker(self):
        self.enable_marker()
        self.control.inhibit_start()
        def fail(args):
            if args[0] == 'stop':
                raise subprocess.CalledProcessError(1, args)
            return self.respond(args)
        self.runner.side_effect = fail
        with self.assertRaises(subprocess.CalledProcessError):
            self.control.quiesce()
        self.assertFalse(self.marker.exists())

    def test_stop_success_but_pending_job_refused(self):
        self.values['Job'] = '99'
        with self.assertRaisesRegex(ReleaseError, 'required inactive state'):
            self.control.quiesce()
        self.assertFalse(self.marker.exists())

    def test_invalid_show_output(self):
        valid = '\n'.join(f'{key}={self.values[key]}' for key in PROPERTIES)
        self.assertEqual(_parse_properties(valid), self.values)
        for malformed in ('', valid + '\nMainPID=0',
                          valid + '\nUnexpected=x', 'not a property'):
            with self.subTest(output=malformed), self.assertRaises(ReleaseError):
                _parse_properties(malformed)

    def test_unsafe_ancestor_refused(self):
        (self.root / 'etc/systemd').chmod(0o775)
        with self.assertRaisesRegex(ReleaseError, 'Unsafe administrator directory'):
            self.control.is_quiescent()
        self.runner.assert_not_called()

    def test_root_factory_guard_and_fixed_command(self):
        with patch('deploy.service_control.os.geteuid', return_value=1234):
            with self.assertRaisesRegex(ReleaseError, 'Administrator identity'):
                production_service_control('a' * 64)
        with patch('deploy.service_control.subprocess.run') as run:
            run.return_value.stdout = 'fixture'
            self.assertEqual(_run(['stop', UNIT]), 'fixture')
            args, kwargs = run.call_args
            self.assertEqual(args[0], ['/usr/bin/systemctl', '--system', '--no-pager',
                                      '--no-ask-password', 'stop', UNIT])
            self.assertTrue(kwargs['check'])
            self.assertEqual(kwargs['cwd'], '/')
            self.assertNotIn('UCON_SECRETS_FILE', kwargs['env'])
            self.assertEqual(kwargs['timeout'], 210)


if __name__ == '__main__':
    unittest.main()
