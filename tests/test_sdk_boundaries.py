"""Keep SDK-specific imports in the explicitly defined adapter modules."""
import ast
from pathlib import Path
import unittest

import p4p_camera_sdk.credentials as credentials
import p4p_camera_sdk.sdcard as sdcard
import p4p_camera_sdk.sdcard_client as sdcard_client

import sdk_credentials
import sdk_sdcard


class SdkBoundaryTests(unittest.TestCase):
    def test_credentials_reexport_original_sdk_objects(self):
        for name in ('HOST', 'USER_AGENT', 'encode_password',
                     'CredentialClient', 'DeviceCredentials'):
            with self.subTest(name=name):
                self.assertIs(getattr(sdk_credentials, name),
                              getattr(credentials, name))

    def test_sdcard_reexports_original_sdk_objects(self):
        for module, names in (
            (sdcard, ('build_list_event', 'parse_event_record',
                      'build_download_sd_file', 'IOTYPE_GET_SD_STATUS_REQ',
                      'IOTYPE_GET_SD_STATUS_RSP', 'build_get_sd_status',
                      'IOTYPE_GET_ADVANCE_SETTINGS_REQ',
                      'IOTYPE_GET_ADVANCE_SETTINGS_RSP')),
            (sdcard_client, ('SdCardClient', 'SdCardEvent')),
        ):
            for name in names:
                with self.subTest(name=name):
                    self.assertIs(getattr(sdk_sdcard, name), getattr(module, name))

    def test_direct_sdk_imports_are_confined_to_boundaries(self):
        root = Path(__file__).resolve().parents[1]
        allowed = {'sdk_credentials.py', 'sdk_sdcard.py',
                   'sdk_relay.py', 'h4_crypto.py'}
        seen = set()
        unexpected = []
        for path in sorted([*root.glob('*.py'), *(root / 'tools').rglob('*.py')]):
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    names = [node.module or '']
                elif isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    continue
                if any(name == 'p4p_camera_sdk' or
                       name.startswith('p4p_camera_sdk.') for name in names):
                    relative = path.relative_to(root).as_posix()
                    seen.add(relative)
                    if relative not in allowed:
                        unexpected.append(f'{relative}:{node.lineno}')
        self.assertEqual(unexpected, [])
        self.assertEqual(seen, allowed)


if __name__ == '__main__':
    unittest.main()
