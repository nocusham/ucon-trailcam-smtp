"""Synthetic checks for the offline source review normalization."""
import ast
import unittest

from deploy.audit_runtime import definitions, shape, statements, imports, commit_id


class RuntimeAuditTests(unittest.TestCase):
    def test_moved_imports_normalize_without_changing_names(self):
        old = ast.parse('def f():\n from probe import DiagnosticRelay, relay_compat\n return DiagnosticRelay')
        new = ast.parse('def f():\n from ucon_trailcam_smtp.sdk_relay import DiagnosticRelay, relay_compat\n return DiagnosticRelay')
        self.assertEqual(shape(definitions(old)['f']), shape(definitions(new)['f']))

    def test_logic_and_alias_changes_remain_visible(self):
        old = ast.parse('def f():\n from smtp_probe import load_image as load\n return load(1)')
        new = ast.parse('def f():\n from ucon_trailcam_smtp.mail_message import load_image as load\n return load(2)')
        self.assertNotEqual(shape(definitions(old)['f']), shape(definitions(new)['f']))
        alias = ast.parse('def f():\n from ucon_trailcam_smtp.mail_message import load_image as other\n return other(1)')
        self.assertNotEqual(shape(definitions(old)['f']), shape(definitions(alias)['f']))

    def test_module_statement_and_import_inventory(self):
        old = ast.parse('"""old docs"""\nfrom p4p_camera_sdk.sdcard import build_list_event\nLIMIT = 3')
        new = ast.parse('"""new docs"""\nfrom ucon_trailcam_smtp.sdk_sdcard import build_list_event\nLIMIT = 4')
        self.assertEqual(imports(old), imports(new))
        self.assertNotEqual(statements(old), statements(new))

    def test_full_commit_and_duplicate_definition_guards(self):
        self.assertEqual(commit_id('a' * 40), 'a' * 40)
        with self.assertRaises(ValueError):
            commit_id('main')
        with self.assertRaises(ValueError):
            definitions(ast.parse('def f(): pass\ndef f(): pass'))


if __name__ == '__main__':
    unittest.main()
