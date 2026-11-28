"""Local synthetic release acceptance; no real root or systemd operations."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from deploy.production_layout import APP
from deploy.release_acceptance import (
    ReleaseApproval, UpdateGate, _accept_candidate, configuration_identity,
    release_tree_digest, run_service_config_check, verify_release,
)
from deploy.production_update import production_update
from deploy.release_layout import ReleaseError


class ReleaseAcceptanceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.install = self.root / 'install'
        self.config = self.root / 'config'
        self.identity = (os.geteuid(), os.getegid())
        for path, mode in ((self.install,0o755),(self.install/'releases',0o755),
                           (self.config,0o750)):
            path.mkdir(mode=mode)
            path.chmod(mode)
        self.file(self.config/'config.toml', b'# fixture', 0o640)
        self.file(self.config/'.env', b'FIXTURE=synthetic', 0o600)
        for release in ('v1','v2'):
            folder = self.install/'releases'/release
            for relative in ('.','venv','venv/bin','venv/lib'):
                path = folder/relative
                path.mkdir(mode=0o755)
                path.chmod(0o755)
            self.file(folder/'venv/bin/python', b'never run', 0o755)
            self.file(folder/'venv/bin'/APP, b'fixture console', 0o755)
            self.file(folder/'venv/pyvenv.cfg', b'fixture', 0o644)
        self.old, self.new = [self.approval(r) for r in ('v1','v2')]
        self.check = Mock(return_value=True)
        self.stopped = Mock(return_value=True)

    @staticmethod
    def file(path, content, mode):
        path.write_bytes(content)
        path.chmod(mode)

    def approval(self, release):
        return ReleaseApproval(release, release_tree_digest(
            self.install,release,self.identity,ready=False),1)

    def accept(self, approval):
        return _accept_candidate(self.install, approval, self.config,
                                 self.identity,self.identity,self.check,self.stopped)

    def test_acceptance_marker_not_selection(self):
        self.assertTrue(self.accept(self.new))
        self.assertEqual((self.install/'releases/v2/.ready').read_bytes(), b'v2\n')
        verify_release(self.install,self.new,self.identity,ready=True)
        self.assertFalse((self.install/'current').exists())
        self.assertFalse((self.config/'service-enabled').exists())

    def test_changed_tree_refused_before_execution(self):
        self.file(self.install/'releases/v2/venv/bin/python',b'changed',0o755)
        with self.assertRaisesRegex(ReleaseError,'tree differs'):
            self.accept(self.new)
        self.check.assert_not_called()

    def test_unsafe_symlink_refused(self):
        (self.install/'releases/v2/venv/lib/link').symlink_to(self.config/'.env')
        with self.assertRaisesRegex(ReleaseError,'tree entry'):
            self.accept(self.new)

    def test_config_changed_or_check_failed(self):
        self.check.return_value = False
        with self.assertRaisesRegex(ReleaseError,'configuration check failed'):
            self.accept(self.new)
        def change(*args):
            self.file(self.config/'.env',b'FIXTURE=changed',0o600)
            return True
        self.check.side_effect = change
        with self.assertRaisesRegex(ReleaseError,'Configuration changed'):
            self.accept(self.new)
        self.assertFalse((self.install/'releases/v2/.ready').exists())

    def test_no_quiescence_or_existing_ready(self):
        self.stopped.return_value = False
        with self.assertRaisesRegex(ReleaseError,'writers must be stopped'):
            self.accept(self.new)
        self.stopped.return_value = True
        self.accept(self.new)
        with self.assertRaisesRegex(ReleaseError,'Unexpected release layout'):
            self.accept(self.new)

    def gate(self, review=None):
        self.accept(self.old)
        self.accept(self.new)
        self.check.reset_mock()
        return UpdateGate(self.install,self.config,self.identity,self.identity,
                          self.old,self.new,self.check,review or Mock(return_value=True))

    def manifest(self):
        return {'files':configuration_identity(self.config,self.identity,self.identity),
                'event_counts':{'sent':1}}

    def test_gate_binds_both_versions_backup_and_configuration(self):
        gate = self.gate()
        manifest = self.manifest()
        with patch('deploy.release_acceptance.check_backup_schema',return_value={'schema_contract':1}), \
                patch('deploy.release_acceptance.verify_backup',return_value=manifest):
            with self.assertRaisesRegex(ReleaseError,'No matching'):
                gate.verify_final('v1','v2',self.root/'backup')
            self.assertTrue(gate.approve('v1','v2',self.root/'backup'))
            self.assertEqual(self.check.call_count,2)
            self.assertTrue(gate.verify_final('v1','v2',self.root/'backup'))
            with self.assertRaisesRegex(ReleaseError,'No matching'):
                gate.verify_final('v1','v2',self.root/'other')
            self.file(self.config/'.env',b'FIXTURE=changed',0o600)
            with self.assertRaisesRegex(ReleaseError,'Configuration differs'):
                gate.verify_final('v1','v2',self.root/'backup')

    def test_gate_refuses_schema_or_operator_failure(self):
        gate = self.gate(Mock(return_value=False))
        with patch('deploy.release_acceptance.check_backup_schema',side_effect=ValueError('schema')):
            with self.assertRaisesRegex(ValueError,'schema'):
                gate.approve('v1','v2',self.root/'backup')
        self.check.assert_not_called()
        with patch('deploy.release_acceptance.check_backup_schema',return_value={'schema_contract':1}), \
                patch('deploy.release_acceptance.verify_backup',return_value=self.manifest()):
            with self.assertRaisesRegex(ReleaseError,'Operator compatibility'):
                gate.approve('v1','v2',self.root/'backup')

    def test_gate_rechecks_release_after_operator_review(self):
        def change(*args):
            self.file(self.install/'releases/v2/venv/bin/python',b'changed',0o755)
            return True
        gate = self.gate(change)
        with patch('deploy.release_acceptance.check_backup_schema',return_value={'schema_contract':1}), \
                patch('deploy.release_acceptance.verify_backup',return_value=self.manifest()):
            with self.assertRaisesRegex(ReleaseError,'tree differs'):
                gate.approve('v1','v2',self.root/'backup')

    def test_invalid_approval_and_public_update_requires_binding(self):
        for args in (('v1','bad',1),('v1','a'*64,2),('../v1','a'*64,1)):
            with self.assertRaises(ReleaseError):
                ReleaseApproval(*args)
        with patch('deploy.production_update.os.geteuid',return_value=0), \
                patch('deploy.production_update.os.getegid',return_value=0):
            with self.assertRaisesRegex(ReleaseError,'matching release approvals'):
                production_update('v2','v1','backup','a'*64',
                                  confirm_no_other_writers=self.stopped,
                                  approve_compatibility=self.check)

    def test_service_check_uses_distinct_identity_and_no_output(self):
        with patch('deploy.release_acceptance.os.geteuid',return_value=0), \
                patch('deploy.release_acceptance.os.getegid',return_value=0), \
                patch('deploy.release_acceptance.subprocess.run') as run:
            self.assertTrue(run_service_config_check(self.install,self.new,self.config,(1234,2345)))
            args,kwargs = run.call_args
            self.assertEqual(args[0][0],str(self.install/'releases/v2/venv/bin/python'))
            self.assertEqual(args[0][1:4],['-I','-B','-c'])
            self.assertEqual((kwargs['user'],kwargs['group'],kwargs['extra_groups']),(1234,2345,[]))
            self.assertEqual(kwargs['stdout'],subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'],subprocess.DEVNULL)
            self.assertNotIn('UCON_SECRETS_FILE',kwargs['env'])


if __name__ == '__main__':
    unittest.main()
