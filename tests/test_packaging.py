"""Focused HACS release packaging tests (not runtime/hardware tests)."""

import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / 'tools' / 'validate_package.py'

spec = importlib.util.spec_from_file_location('validate_package', MOD)
validate_package = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(validate_package)


class HACSMetadataTests(unittest.TestCase):
    def test_repository_structure(self):
        self.assertEqual(validate_package.inspect_repository(ROOT), [])

    def test_domain_version_and_links(self):
        manifest = json.loads((ROOT / 'custom_components/xiaomi_camera_native/manifest.json').read_text())
        self.assertEqual(manifest['domain'], 'xiaomi_camera_native')
        self.assertEqual(manifest['version'], '0.3.14')
        self.assertTrue(manifest['documentation'].startswith('https://'))
        self.assertTrue(manifest['issue_tracker'].startswith('https://'))

    def test_hacs_display_name(self):
        hacs = json.loads((ROOT / 'hacs.json').read_text())
        self.assertEqual(hacs['name'], 'Xiaomi Camera Native')
        self.assertTrue(hacs['render_readme'])


if __name__ == '__main__':
    unittest.main()
