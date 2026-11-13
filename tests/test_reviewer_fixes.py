"""Offline checks for HACS reviewer findings; no hardware accessed."""
import ast
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components/xiaomi_camera_native"
MODELS = {"chuangmi.camera.029a02", "chuangmi.camera.ip029a", "chuangmi.camera.046c04", "mxiang.camera.c301"}

class ReviewerTests(unittest.TestCase):
    def test_pan_tilt_allowlist_matches_verified_models(self):
        module = ast.parse((COMP / "protocol/miss.py").read_text())
        nodes = [stmt.value for stmt in module.body if isinstance(stmt, ast.Assign)
                 if any(isinstance(t, ast.Name) and t.id=="PAN_TILT_MODELS" for t in stmt.targets)]
        self.assertEqual(len(nodes), 1)
        self.assertEqual(ast.literal_eval(nodes[0].args[0]), MODELS)

    def test_translations(self):
        strings = json.loads((COMP / "strings.json").read_text())
        english = json.loads((COMP / "translations/en.json").read_text())
        self.assertEqual(strings, english)
        self.assertEqual(english["options"]["step"]["profile"]["data"]["auto_update_ip"],
                         "Automatically update camera IP")

    def test_versions(self):
        manifest = json.loads((COMP / "manifest.json").read_text())
        self.assertEqual(manifest["version"], "0.3.14")
        self.assertIn('VERSION = "0.3.14"', (COMP / "const.py").read_text())
        self.assertIn('camera-controls.js?v={VERSION}', (COMP / "frontend.py").read_text())
        workflow = (ROOT / ".github/workflows/release.yml").read_text()
        self.assertIn('[[ "$VERSION" == "0.3.14" ]]', workflow)
        self.assertIn('RELEASE_NOTES_0.3.14.md', workflow)
        self.assertIn("Xiaomi Camera Native 0.3.14", (COMP / "NOTICE").read_text())

    def test_license_and_test_evidence(self):
        root_license = (ROOT / "License").read_text()
        self.assertEqual(root_license, (COMP / "LICENSE").read_text())
        self.assertIn("Copyright (c) 2026 Kosztyk", root_license)
        self.assertIn("Copyright (c) 2022 Alexey Khit", root_license)
        report = (ROOT / "docs/PTZ_HARDWARE_VERIFICATION_2026-10-24.md").read_text()
        for model in MODELS - {"chuangmi.camera.ip029a"}:
            self.assertIn(model, report)
        ip029a_report = (ROOT / "docs/PTZ_HARDWARE_VERIFICATION_2026-11-12_ip029a.md").read_text()
        self.assertIn("chuangmi.camera.ip029a", ip029a_report)
        self.assertIn("one camera", ip029a_report.lower())

if __name__ == "__main__":
    unittest.main()
