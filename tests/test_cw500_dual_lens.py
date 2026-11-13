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
        "PAN_TILT_OPERATIONS": {"left": 1, "right": 2, "up": 3, "down": 4},
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
        self.ptz_directions = []

    async def pan_tilt(self, direction):
        self.ptz_directions.append(direction)

    async def start_media_both(self, *args):
        self.start_args = args

    async def read_video(self):
        item = next(self.packets)
        await asyncio.sleep(0)
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
            task = asyncio.create_task(transport._run())
            primary, secondary = await asyncio.gather(
                asyncio.wait_for(primary_queue.get(), 1),
                asyncio.wait_for(secondary_queue.get(), 1),
            )
            await task
            return primary, secondary

        primary, secondary = asyncio.run(run())
        self.assertIs(primary, primary_packet)
        self.assertIs(secondary, secondary_packet)
        self.assertIsInstance(primary_queue.get_nowait(), TransportError)
        self.assertIsInstance(secondary_queue.get_nowait(), TransportError)
        self.assertEqual(client.start_args, ("isa.camera.500dh", "hd", "hd"))
        self.assertTrue(client.closed)
        self.assertEqual(primary_session.protocol, "cs2+tcp")
        self.assertEqual(secondary_session.protocol, "cs2+tcp")
        self.assertEqual(secondary_session.host, primary_session.host)

    def test_ptz_uses_active_shared_client_without_opening_another_socket(self):
        client = FakeClient([])
        primary_session = FakeSession(client)
        Transport = load_transport_class()
        transport = Transport(primary_session)
        transport._client = client

        async def run():
            await transport.pan_tilt("left")

        asyncio.run(run())
        self.assertEqual(client.ptz_directions, ["left"])
        self.assertFalse(client.closed)
        self.assertIs(transport._client, client)

    def test_ptz_uses_control_only_client_when_video_is_idle(self):
        client = FakeClient([])
        primary_session = FakeSession(client)
        Transport = load_transport_class()
        transport = Transport(primary_session)

        async def run():
            await transport.pan_tilt("right")

        asyncio.run(run())
        self.assertEqual(client.ptz_directions, ["right"])
        self.assertTrue(client.closed)

    def test_ptz_rejects_invalid_direction_without_connecting(self):
        primary_session = FakeSession(None)
        Transport = load_transport_class()
        transport = Transport(primary_session)

        async def run():
            with self.assertRaises(TransportError):
                await transport.pan_tilt("zoom")

        asyncio.run(run())
        self.assertIsNone(primary_session.client)

    def test_one_socket_is_demultiplexed_into_two_logical_sessions(self):
        source = (COMP / "protocol/dual_lens.py").read_text()
        transport = source.split("class DualLensTransport:", 1)[1].split(
            "class DualLensCameraSession", 1
        )[0]
        run_method = transport.split("async def _run", 1)[1].split(
            "async def close", 1
        )[0]
        self.assertEqual(run_method.count("_connect_client(start_video=False)"), 1)
        self.assertIn("async with self._ptz_lock:", run_method)
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

    def test_cw500_is_experimental_ptz_and_only_primary_session_is_motorized(self):
        miss = (COMP / "protocol/miss.py").read_text()
        dual = (COMP / "protocol/dual_lens.py").read_text()
        config = (COMP / "config_flow.py").read_text()
        self.assertIn('EXPERIMENTAL_PAN_TILT_MODELS = frozenset({"isa.camera.500dh"})', miss)
        self.assertIn('return self.lens == 0 and super().supports_pan_tilt', dual)
        self.assertIn('if device["model"] in EXPERIMENTAL_PAN_TILT_MODELS:', config)
        self.assertIn('await self.dual_transport.pan_tilt(direction)', dual)

    def test_release_metadata_is_aligned(self):
        import json

        manifest = json.loads((COMP / "manifest.json").read_text())
        const = (COMP / "const.py").read_text()
        self.assertEqual(manifest["version"], "0.3.15")
        self.assertIn('VERSION = "0.3.15"', const)
        self.assertIn('"isa.camera.500dh": "Xiaomi Outdoor Camera CW500 Dual"', const)


if __name__ == "__main__":
    unittest.main()
