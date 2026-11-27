"""Regression checks for the shared relay adapter; no network activity."""
import contextlib
import sys
import unittest
from types import SimpleNamespace

import p4p_camera_sdk.p4p_crypto as sdk_crypto
import p4p_camera_sdk.relay as sdk_module

from ucon_trailcam_smtp.h4_crypto import encode, decode
from ucon_trailcam_smtp.h4_traffic import TrafficStats, SocketModuleProxy
from ucon_trailcam_smtp.sdk_relay import DiagnosticRelay, relay_compat


class RelayAdapterTests(unittest.TestCase):
    def test_probe_reexports_shared_adapter(self):
        import probe

        self.assertIs(probe.DiagnosticRelay, DiagnosticRelay)
        self.assertIs(probe.relay_compat, relay_compat)
        self.assertTrue(issubclass(DiagnosticRelay, sdk_module.RelaySession))

    def check_patch_scope(self, fail):
        targets = [(sdk_module, name) for name in (
            'socket', 'encode', 'decode', 'wrap_relay_kcp', 'try_decode',
            'build_rlystreamreq', 'parse_rlystreamrsp',
        )] + [(sdk_crypto, name) for name in ('encode', 'decode')]
        originals = [getattr(module, name) for module, name in targets]
        stdout, stderr = sys.stdout, sys.stderr
        session = SimpleNamespace(started=0.0, traffic=TrafficStats(lambda: 'test'))
        expectation = self.assertRaises(TimeoutError) if fail else contextlib.nullcontext()
        with expectation:
            with relay_compat(session):
                self.assertIsInstance(sdk_module.socket, SocketModuleProxy)
                self.assertIs(sdk_module.socket.stats, session.traffic)
                for module in (sdk_module, sdk_crypto):
                    self.assertIs(module.encode, encode)
                    self.assertIs(module.decode, decode)
                for (module, name), original in zip(targets[3:7], originals[3:7]):
                    self.assertIsNot(getattr(module, name), original)
                self.assertIsNot(sys.stdout, stdout)
                self.assertIsNot(sys.stderr, stderr)
                if fail:
                    raise TimeoutError('synthetic timeout')
        for (module, name), original in zip(targets, originals):
            self.assertIs(getattr(module, name), original)
        self.assertIs(sys.stdout, stdout)
        self.assertIs(sys.stderr, stderr)

    def test_patch_scope_restored_on_normal_exit(self):
        self.check_patch_scope(False)

    def test_patch_scope_restored_on_timeout(self):
        self.check_patch_scope(True)


if __name__ == '__main__':
    unittest.main()
