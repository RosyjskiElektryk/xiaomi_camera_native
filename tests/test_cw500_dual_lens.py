"""Offline structural regression checks for CW500 dual-lens integration wiring."""

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components/xiaomi_camera_native"


class CW500DualLensTests(unittest.TestCase):
    def test_packet_lens_tag_uses_only_measured_flag_bits(self):
        tree = ast.parse((COMP / "protocol/miss.py").read_text())
        packet = next(
            node for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "VideoPacket"
        )
        namespace = {"dataclass": dataclass}
        exec(
            compile(ast.fix_missing_locations(ast.Module(
                body=[node for node in tree.body if isinstance(node, ast.ImportFrom)
                      and node.module == "__future__"] + [packet],
                type_ignores=[],
            )), "video-packet", "exec"),
            namespace,
        )
        VideoPacket = namespace["VideoPacket"]
        primary = VideoPacket(4, 1, 0x000E << 16, 100, b"frame")
        secondary = VideoPacket(4, 2, 0x014E << 16, 100, b"frame")
        self.assertEqual(primary.lens_tag, 0x0000)
        self.assertEqual(secondary.lens_tag, 0x0140)

    def test_dual_start_command_requests_both_streams(self):
        source = (COMP / "protocol/miss.py").read_text()
        method = source.split("async def start_media_both", 1)[1].split(
            "async def read_video", 1
        )[0]
        self.assertIn('"videoquality": resolve(primary_quality)', method)
        self.assertIn('"videoquality2": resolve(secondary_quality)', method)
        self.assertIn("encode_media(self.key, payload)", method)
        self.assertIn("write_command(0x1001", method)
        self.assertIn('"isa.camera.500dh"', source)

    def test_one_socket_is_demultiplexed_into_two_logical_sessions(self):
        source = (COMP / "protocol/dual_lens.py").read_text()
        transport = source.split("class DualLensTransport:", 1)[1].split(
            "class DualLensCameraSession", 1
        )[0]
        self.assertEqual(transport.count("_connect_client(start_video=False)"), 1)
        self.assertIn("client.start_media_both(", transport)
        self.assertIn("packet.lens_tag == 0x0000", transport)
        self.assertIn("packet.lens_tag == 0x0140", transport)
        self.assertIn("self._publish(0, packet)", transport)
        self.assertIn("self._publish(1, packet)", transport)
        self.assertNotIn("MissClient.connect(", transport)

    def test_authentication_errors_reach_inherited_session_retry_policy(self):
        source = (COMP / "protocol/dual_lens.py").read_text()
        self.assertIn("except AuthenticationError as err:", source)
        self.assertIn("self._end_streams(err)", source)
        capture = source.split("async def _capture", 1)[1].split(
            "async def close", 1
        )[0]
        self.assertIn("if isinstance(item, XiaomiError):", capture)
        self.assertIn("raise item", capture)

    def test_setup_exposes_both_lenses_and_preserves_primary_id(self):
        setup = (COMP / "__init__.py").read_text()
        camera = (COMP / "camera.py").read_text()
        self.assertIn('lens=0, stream_id=f"{did}_primary"', setup)
        self.assertIn('lens=1, stream_id=f"{did}_secondary"', setup)
        self.assertIn("transport.sessions.append(secondary)", setup)
        self.assertIn("session.device.did if stream_id.endswith(\"_primary\") else stream_id", camera)
        self.assertIn('self._server.source(self._stream_id)', camera)

    def test_release_metadata_is_aligned(self):
        import json

        manifest = json.loads((COMP / "manifest.json").read_text())
        const = (COMP / "const.py").read_text()
        self.assertEqual(manifest["version"], "0.3.14")
        self.assertIn('VERSION = "0.3.14"', const)
        self.assertIn('"isa.camera.500dh": "Xiaomi Outdoor Camera CW500 Dual"', const)


if __name__ == "__main__":
    unittest.main()
