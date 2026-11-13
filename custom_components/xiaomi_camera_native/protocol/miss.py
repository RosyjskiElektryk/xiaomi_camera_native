"""MISS authentication, encrypted video commands and frame headers."""

from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass

from .cloud import Provisioning
from .crypto import decode_media, encode_media, shared_key
from .cs2 import CS2Connection
from .errors import ProtocolError, TransportError

PAN_TILT_OPERATIONS = {"left": 1, "right": 2, "up": 3, "down": 4}
# Models with physical PTZ evidence using Xiaomi Camera Native's native MISS controls:
# three owner-recorded tests (2026-10-24) and one independent user report (2026-11-12).
# The ip029a report confirms left/right/up/down on ONE camera and streaming on TWO.
# See docs/PTZ_HARDWARE_VERIFICATION_2026-10-24.md and
# docs/PTZ_HARDWARE_VERIFICATION_2026-11-12_ip029a.md.
PAN_TILT_MODELS = frozenset(
    {
        "chuangmi.camera.029a02",
        "chuangmi.camera.ip029a",
        "chuangmi.camera.046c04",
        "mxiang.camera.c301",
    }
)
# CW500 Dual is opt-in until its motor command is confirmed on physical hardware.
EXPERIMENTAL_PAN_TILT_MODELS = frozenset({"isa.camera.500dh"})


def pan_tilt_supported(model: str, *, experimental_enabled: bool = False) -> bool:
    """Allow verified PTZ by default; require explicit opt-in for field-test models."""
    return model in PAN_TILT_MODELS or (
        experimental_enabled is True and model in EXPERIMENTAL_PAN_TILT_MODELS
    )


@dataclass(frozen=True)
class VideoPacket:
    codec: int
    sequence: int
    flags: int
    timestamp_ms: int
    payload: bytes

    @property
    def lens_tag(self) -> int:
        """Return the measured CW500 lens identifier from the media flags."""
        return (self.flags >> 16) & 0x0140


class MissClient:
    def __init__(self, connection: CS2Connection, key: bytes) -> None:
        self.connection = connection
        self.key = key
        self._commands_task: asyncio.Task[None] | None = None

    @classmethod
    async def connect(
        cls,
        host: str,
        provisioning: Provisioning,
        *,
        model: str = "",
        transport: str = "auto",
        quality: str = "hd",
        port: int = 32108,
        start_video: bool = True,
    ) -> MissClient:
        key = shared_key(provisioning.device_public, provisioning.private)
        connection = await CS2Connection.connect(host, transport, port=port)
        self = cls(connection, key)
        try:
            request = json.dumps(
                {
                    "public_key": provisioning.public.hex(),
                    "sign": provisioning.signature,
                    "uuid": "",
                    "support_encrypt": 0,
                },
                separators=(",", ":"),
            ).encode()
            await connection.write_command(0x100, request)
            response = await connection.read_channel(0)
            if len(response) < 5:
                raise ProtocolError("Camera authentication response is too short")
            try:
                auth = json.loads(response[4:])
            except (ValueError, UnicodeError):
                raise ProtocolError("Invalid camera authentication response") from None
            if not isinstance(auth, dict) or auth.get("result") != "success":
                raise ProtocolError("Camera rejected the MISS session credentials")
            if start_video:
                await self.start_media(model, quality)
            self._commands_task = asyncio.create_task(self._drain_commands())
            return self
        except BaseException:
            await connection.close()
            raise

    async def start_media(self, model: str, quality: str) -> None:
        if quality == "hd":
            # CW500 profile 2 is only 640x360; profile 3 is 2560x1440.
            value = 3 if model in {
                "chuangmi.camera.046c04",
                "chuangmi.camera.72ac1",
                "isa.camera.500dh",
            } else 2
        elif quality in {"auto", "sd"}:
            value = 0 if quality == "auto" else 1
        elif quality in {"0", "1", "2", "3", "4", "5"}:
            value = int(quality)
        else:
            raise ProtocolError("Unsupported Xiaomi video quality")
        payload = (
            struct.pack(">I", 0x102)
            + json.dumps({"videoquality": value, "enableaudio": 0}, separators=(",", ":")).encode()
        )
        await self.connection.write_command(0x1001, encode_media(self.key, payload))

    async def start_media_both(
        self, model: str, primary_quality: str = "hd", secondary_quality: str = "hd"
    ) -> None:
        """Ask a supported dual-lens camera to interleave both video streams."""
        def resolve(quality: str) -> int:
            if quality == "hd":
                return 3 if model == "isa.camera.500dh" else 2
            if quality == "auto":
                return 0
            if quality == "sd":
                return 1
            if quality in {"0", "1", "2", "3", "4", "5"}:
                return int(quality)
            raise ProtocolError("Unsupported Xiaomi video quality")

        payload = (
            struct.pack(">I", 0x102)
            + json.dumps(
                {
                    "videoquality": resolve(primary_quality),
                    "videoquality2": resolve(secondary_quality),
                    "enableaudio": 0,
                },
                separators=(",", ":"),
            ).encode()
        )
        await self.connection.write_command(0x1001, encode_media(self.key, payload))

    async def read_video(self, timeout: float = 15) -> VideoPacket:
        while True:
            packet = await self.connection.read_channel(2, timeout)
            if len(packet) < 40:
                raise ProtocolError("Camera media header or cipher nonce is truncated")
            length, codec, seq, flags, timestamp = struct.unpack_from("<IIIIQ", packet)
            if length != len(packet) - 32:
                raise ProtocolError("Camera media payload length mismatch")
            if codec not in {4, 5}:
                continue
            payload = decode_media(self.key, packet[32:])
            return VideoPacket(codec, seq, flags, timestamp, payload)

    async def pan_tilt(self, direction: str) -> None:
        """Send exactly one motor step on the existing encrypted connection.

        The JSON operation is the MISS 0x112 command, not a MiOT property.
        Transport delivery does not establish the physical camera position;
        firmware does not consistently return an application acknowledgement.
        Never retry a motor step on a fresh connection after an error.
        """
        if not isinstance(direction, str) or direction not in PAN_TILT_OPERATIONS:
            raise ProtocolError("Pan/tilt direction must be left, right, up or down")
        payload = (
            struct.pack(">I", 0x112)
            + json.dumps(
                {"operation": PAN_TILT_OPERATIONS[direction]}, separators=(",", ":")
            ).encode()
        )
        await self.connection.write_command(0x1001, encode_media(self.key, payload))

    async def _drain_commands(self) -> None:
        # Some firmware periodically sends status responses on channel zero.
        # Keep that queue drained after authentication, without logging bodies.
        try:
            while True:
                await self.connection.read_channel(0, timeout=None)
        except TransportError:
            pass

    async def close(self) -> None:
        if self._commands_task is not None:
            self._commands_task.cancel()
            await asyncio.gather(self._commands_task, return_exceptions=True)
        await self.connection.close()
