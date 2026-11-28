"""Synthetic metadata for distinct administrator and service identities."""
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from deploy.production_layout import APP, LayoutError, check_layout


class ProductionLayoutTests(unittest.TestCase):
    def setUp(self):
        self.root = Path('/synthetic-layout')
        self.uid, self.gid = 1234, 2345
        self.opt = f'opt/{APP}'
        self.etc = f'etc/{APP}'
        self.state = f'var/lib/{APP}'
        self.release = self.opt + '/releases/v1'
        self.files = {}
        for name in ('.', 'opt', 'etc', 'var', 'var/lib', self.opt,
                     self.opt + '/releases', 'etc/systemd', 'etc/systemd/system',
                     self.release, self.release + '/venv', self.release + '/venv/bin'):
            self.add(name, stat.S_IFDIR, 0o755)
        self.add(self.release + '/.ready', stat.S_IFREG, 0o644)
        self.add(self.release + '/venv/bin/' + APP, stat.S_IFREG, 0o755)
        self.add(self.etc, stat.S_IFDIR, 0o750, gid=self.gid)
        self.add(self.etc + '/config.toml', stat.S_IFREG, 0o640, gid=self.gid)
        self.add(self.etc + '/.env', stat.S_IFREG, 0o400, self.uid, self.gid)
        self.add('etc/systemd/system/' + APP + '.service', stat.S_IFREG, 0o644)
        for name in (self.state, self.state + '/media'):
            self.add(name, stat.S_IFDIR, 0o700, self.uid, self.gid)

    def add(self, name, kind, mode, uid=0, gid=0, links=1):
        self.files[self.root / name] = SimpleNamespace(
            st_mode=kind | mode, st_uid=uid, st_gid=gid, st_nlink=links)

    def inspect(self, initialized=False, uid=None, target='releases/v1'):
        def metadata(path):
            try:
                return self.files[path]
            except KeyError:
                raise FileNotFoundError from None
        with patch('deploy.production_layout._metadata', side_effect=metadata), \
                patch('deploy.production_layout.os.readlink', return_value=target):
            check_layout(self.root, 'v1', self.uid if uid is None else uid,
                         self.gid, initialized=initialized)

    def test_first_install_mixed_ownership(self):
        self.inspect()
        self.add(self.etc + '/.env', stat.S_IFREG, 0o600, self.uid, self.gid)
        self.inspect()

    def test_initialized_state_and_current_pointer(self):
        for name in ('events.sqlite3', 'events.sqlite3.lock'):
            self.add(self.state + '/' + name, stat.S_IFREG, 0o600, self.uid, self.gid)
        self.add(self.opt + '/current', stat.S_IFLNK, 0o777)
        self.inspect(initialized=True)
        with self.assertRaisesRegex(LayoutError, 'must be absent'):
            self.inspect()

    def test_service_cannot_own_code_or_write_release(self):
        for mode, uid, gid in ((0o755, self.uid, self.gid), (0o775, 0, 0)):
            with self.subTest(mode=mode, uid=uid):
                self.add(self.release, stat.S_IFDIR, mode, uid, gid)
                with self.assertRaisesRegex(LayoutError, 'releases/v1'):
                    self.inspect()

    def test_config_and_credentials_permissions(self):
        self.add(self.etc + '/config.toml', stat.S_IFREG, 0o660, gid=self.gid)
        with self.assertRaisesRegex(LayoutError, 'config.toml'):
            self.inspect()
        self.add(self.etc + '/config.toml', stat.S_IFREG, 0o640, gid=self.gid)
        for mode, uid in ((0o644, self.uid), (0o400, 0)):
            with self.subTest(mode=mode, uid=uid):
                self.add(self.etc + '/.env', stat.S_IFREG, mode, uid, self.gid)
                with self.assertRaisesRegex(LayoutError, r'/\.env'):
                    self.inspect()

    def test_symlinked_ancestor_and_hardlinked_secret(self):
        self.add('var/lib', stat.S_IFLNK, 0o777)
        with self.assertRaisesRegex(LayoutError, 'var/lib'):
            self.inspect()
        self.add('var/lib', stat.S_IFDIR, 0o755)
        self.add(self.etc + '/.env', stat.S_IFREG, 0o400, self.uid, self.gid, links=2)
        with self.assertRaisesRegex(LayoutError, r'/\.env'):
            self.inspect()

    def test_marker_even_dangling_symlink_refused(self):
        for kind in (stat.S_IFREG, stat.S_IFLNK):
            self.add(self.etc + '/service-enabled', kind, 0o644)
            with self.assertRaisesRegex(LayoutError, 'must be absent.*service-enabled'):
                self.inspect()

    def test_missing_or_wrong_state_files_refused(self):
        with self.assertRaisesRegex(LayoutError, 'Missing required path.*events.sqlite3'):
            self.inspect(initialized=True)
        self.add(self.state + '/events.sqlite3', stat.S_IFREG, 0o600, self.uid, self.gid)
        self.add(self.state + '/events.sqlite3.lock', stat.S_IFREG, 0o644, self.uid, self.gid)
        with self.assertRaisesRegex(LayoutError, 'events.sqlite3.lock'):
            self.inspect(initialized=True)

    def test_invalid_current_target_refused(self):
        self.add(self.opt + '/current', stat.S_IFLNK, 0o777)
        for target in ('/tmp/v1', 'releases/../v1', 'releases/missing'):
            with self.subTest(target=target), self.assertRaises(ValueError):
                self.inspect(target=target)

    def test_root_service_identity_refused(self):
        with self.assertRaisesRegex(LayoutError, 'non-root'):
            self.inspect(uid=0)


if __name__ == '__main__':
    unittest.main()
