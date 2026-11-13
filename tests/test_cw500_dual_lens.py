"""Offline regression checks for CW500 dual-lens protocol and entity wiring."""

import ast
import asyncio
import unittest
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from collections.abc import AsyncIterator

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / "custom_components/xiaomi_camera_native"


class XiaomiError(Exception):
    pass


class AuthenticationError(XiaomiError):
    pass


class TransportError(XiaomiError):
    pass


def load_packet_class():
    tree = ast.parse((COMP / "protocol/miss.py").read_text())
    packet = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "VideoPacket"
    )
    future = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]
    namespace = {"dataclass": dataclass, "__name__": "cw500_packet_test"}
    exec(
        compile(ast.fix_missing_locations(ast.Module(
            body=future + [packet], type_ignores=[]
        )), "video-packet", "exec"),
        namespace,
    )
    return namespace["VideoPacket"]


def load_transport_class():
    source = COMP / "protocol/dual_lens.py"
    tree = ast.parse(source.read_text())
    transport = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DualLensTransport"
    )
    future = [
        node for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
    ]
    namespace = {
        "asyncio": asyncio,
        "asynccontextmanager": asynccontextmanager,
        "AsyncIterator": AsyncIterator,
        "suppress": suppress,
        "replace": replace,
        "AuthenticationError": AuthenticationError,
        "TransportError": TransportError,
        "XiaomiError": XiaomiError,
    }
    exec(
        compile(ast.fix_missing_locations(ast.Module(
            body=future + [transport], type_ignores=[]
        )), "dual-lens-transport", "exec"),
        namespace,
    )
    return namespace["DualLensTransport"]


@dataclass(frozen=True)
class FakeOptions:
    host: str = ""
    quality: str = "hd"


class FakeClient:
    def __init__(self, packets):
        self.connection = SimpleNamespace(protocol="cs2+tcp")
        self.packets = iter(packets)
        self.start_args = None
        self.closed = False

    async def start_media_both(self, *args):
        self.start_args = args

    async def read_video(self):
        item = next(self.packets)
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, client=None):
        self.options = FakeOptions()
        self.device = SimpleNamespace(model="isa.camera.500dh")
        self.host = "192.168.0.126"
        self.address_source = "configured"
        self.address_updates = 0
        self.protocol = None
        self._refresh_address = False
        self.client = client

    async def _connect_client(self, *, start_video):
        assert start_video is False
        return self.client


class CW500DualLensTests(unittest.TestCase):
    def test_packet_lens_tag_uses_only_measured_flag_bits(self):
        VideoPacket = load_packet_class()
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

    def test_transport_routes_interleaved_packets_over_one_client(self):
        VideoPacket = load_packet_class()
        primary_packet = VideoPacket(4, 1, 0x000E << 16, 100, b"primary")
        secondary_packet = VideoPacket(4, 2, 0x014E << 16, 100, b"secondary")
        client = FakeClient([primary_packet, secondary_packet, TransportError("end")])
        primary_session = FakeSession(client)
        secondary_session = FakeSession()
        Transport = load_transport_class()
        transport = Transport(primary_session)
        transport.sessions.append(secondary_session)
        primary_queue = asyncio.Queue()
        secondary_queue = asyncio.Queue()
        transport._queues[0].add(primary_queue)
        transport._queues[1].add(secondary_queue)

        async def run():
            await transport._run()

        asyncio.run(run())
        self.assertIs(primary_queue.get_nowait(), primary_packet)
        self.assertIs(secondary_queue.get_nowait(), secondary_packet)
        self.assertIsInstance(primary_queue.get_nowait(), TransportError)
        self.assertIsInstance(secondary_queue.get_nowait(), TransportError)
        self.assertEqual(client.start_args, ("isa.camera.500dh", "hd", "hd"))
        self.assertTrue(client.closed)
        self.assertEqual(primary_session.protocol, "cs2+tcp")
        self.assertEqual(secondary_session.protocol, "cs2+tcp")
        self.assertEqual(secondary_session.host, primary_session.host)

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
        self.assertIn('session.device.did if stream_id.endswith("_primary") else stream_id', camera)
        self.assertIn("self._server.source(self._stream_id)", camera)

    def test_release_metadata_is_aligned(self):
        import json

        manifest = json.loads((COMP / "manifest.json").read_text())
        const = (COMP / "const.py").read_text()
        self.assertEqual(manifest["version"], "0.3.14")
        self.assertIn('VERSION = "0.3.14"', const)
        self.assertIn('"isa.camera.500dh": "Xiaomi Outdoor Camera CW500 Dual"', const)


if __name__ == "__main__":
    unittest.main()
