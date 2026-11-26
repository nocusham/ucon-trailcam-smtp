import unittest
from types import SimpleNamespace
from camera_selection import SelectionError, select_device, profile_uid, relay_credentials


class CameraSelectionTests(unittest.TestCase):
    def setUp(self):
        self.a = {'device_uid': 'a', 'device_pwd': 'password-a'}
        self.b = {'device_uid': 'b', 'device_pwd': 'password-b'}

    def test_uid_independent_of_order(self):
        for devices in ([self.a, self.b], [self.b, self.a]):
            self.assertIs(select_device(devices, uid='a'), self.a)

    def test_missing_and_duplicate_uid_refused(self):
        for devices in ([self.b], [self.a, self.a], None):
            with self.assertRaises(SelectionError):
                select_device(devices, uid='a')

    def test_legacy_index(self):
        self.assertIs(select_device([self.a, self.b], 1), self.b)
        for index in (-1, 2):
            with self.assertRaises(SelectionError):
                select_device([self.a, self.b], index)

    def test_profile_enabled_only(self):
        profiles = [SimpleNamespace(name='one', uid='a', enabled=True),
                    SimpleNamespace(name='two', uid='b', enabled=False)]
        self.assertEqual(profile_uid(profiles, 'one'), 'a')
        for name in ('two', 'unknown'):
            with self.assertRaises(SelectionError):
                profile_uid(profiles, name)

    def test_relay_credentials_same_record(self):
        self.assertEqual(relay_credentials(select_device([self.b, self.a], uid='a')),
                         ('a', 'password-a', ''))
        with self.assertRaises(SelectionError):
            relay_credentials({'device_uid': 'a'})
