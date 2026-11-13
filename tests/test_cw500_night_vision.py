"""Offline structural checks for CW500 night-vision and fill-light controls."""

from __future__ import annotations

import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components" / "xiaomi_camera_native"


class Cw500NightVisionTests(unittest.TestCase):
    def test_miot_property_endpoints_and_identifiers(self):
        cloud = (COMP / "protocol" / "cloud.py").read_text()
        self.assertIn('"/miotspec/prop/set"', cloud)
        self.assertIn('"/miotspec/prop/get"', cloud)
        self.assertIn('"siid": siid, "piid": piid', cloud)

    def test_night_vision_selector_uses_documented_property_and_modes(self):
        source = (COMP / "select.py").read_text()
        self.assertIn('"Off": 0', source)
        self.assertIn('"IR": 1', source)
        self.assertIn('"Auto": 2', source)
        self.assertIn('"Auto full-colour": 3', source)
        self.assertIn('"Always full-colour": 4', source)
        self.assertIn('"Smart full-colour": 5', source)
        self.assertIn('self._session.device.did, 2, 3', source)
        self.assertIn('self._session.device.did, 6, 16, False', source)

    def test_fill_light_switch_uses_other_functions_property(self):
        source = (COMP / "switch.py").read_text()
        self.assertIn('self._session.device.did, 6, 16', source)
        self.assertIn('self._attr_is_on = bool(value)', source)

    def test_controls_are_created_once_for_primary_cw500_lens(self):
        for name in ("select.py", "switch.py"):
            source = (COMP / name).read_text()
            self.assertIn('session.device.model == "isa.camera.500dh"', source)
            self.assertIn('getattr(session, "lens", None) == 0', source)

    def test_platforms_and_translations(self):
        setup = (COMP / "__init__.py").read_text()
        self.assertIn("Platform.SELECT", setup)
        self.assertIn("Platform.SWITCH", setup)
        for name in ("strings.json", "translations/en.json"):
            data = json.loads((COMP / name).read_text())
            self.assertIn("night_vision_mode", data["entity"]["select"])
            self.assertIn("fill_light", data["entity"]["switch"])


if __name__ == "__main__":
    unittest.main()
