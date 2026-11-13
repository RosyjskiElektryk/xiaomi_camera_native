"""Shared MISS transport and logical sessions for CW500 dual-lens video."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from dataclasses import replace

from .errors import AuthenticationError, TransportError, XiaomiError
from .media import MpegTsMuxer
from .miss import PAN_TILT_OPERATIONS, VideoPacket
from .session import CameraSession

_QUEUE_SIZE = 256
_PTZ_SETTLE_TIME = 0.4


class DualLensTransport:
    """Demultiplex both interleaved CW500 streams from one authenticated socket.

    The camera's media flags carry a lens discriminator. Masking the observed
    high-order flag bits with 0x0140 yields 0x0000 for the primary lens and
    0x0140 for the secondary lens; codec/quality bits are deliberately ignored.
    """

    def __init__(self, primary_session: CameraSession) -> None:
        self._primary = primary_session
        self.sessions: list[CameraSession] = [primary_session]
        self._queues: dict[int, set[asyncio.Queue]] = {0: set(), 1: set()}
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._closed = False
        self._client = None
        self._ptz_lock = asyncio.Lock()

    @asynccontextmanager
    async def subscribe(
        self, lens: int
    ) -> AsyncIterator[asyncio.Queue[VideoPacket | XiaomiError | None]]:
        if lens not in (0, 1):
            raise ValueError("CW500 lens must be 0 or 1")
        queue: asyncio.Queue[VideoPacket | XiaomiError | None] = asyncio.Queue(
            _QUEUE_SIZE
        )
        async with self._lock:
            if self._closed:
                raise TransportError("CW500 dual-lens transport is closed")
            self._queues[lens].add(queue)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
        try:
            yield queue
        finally:
            task = None
            async with self._lock:
                self._queues[lens].discard(queue)
                if not self._queues[0] and not self._queues[1]:
                    task = self._task
                    self._task = None
                    if task is not None and not task.done():
                        task.cancel()
            if task is not None and not task.done():
                await asyncio.gather(task, return_exceptions=True)

    def _publish(self, lens: int, packet: VideoPacket) -> None:
        for queue in tuple(self._queues[lens]):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(TransportError("CW500 video consumer fell behind"))
                self._queues[lens].discard(queue)
                continue
            queue.put_nowait(packet)

    def _end_streams(self, error: XiaomiError | None = None) -> None:
        for queues in self._queues.values():
            for queue in tuple(queues):
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(error)

    def _sync_session_connection(self, client) -> None:
        """Copy connection metadata after address discovery has completed."""
        source = self._primary
        for session in self.sessions:
            session.host = source.host
            session.address_source = source.address_source
            session.address_updates = source.address_updates
            session.protocol = client.connection.protocol
            session._refresh_address = source._refresh_address
            session.options = replace(session.options, host=source.options.host)

    async def pan_tilt(self, direction: str) -> None:
        """Send one PTZ step over the active shared socket, or a control-only
        socket while both video entities are idle. Commands are never retried.
        """
        if not isinstance(direction, str) or direction not in PAN_TILT_OPERATIONS:
            raise TransportError("Pan/tilt direction must be left, right, up or down")
        async with self._ptz_lock:
            if self._closed:
                raise TransportError("CW500 dual-lens transport is closed")
            client = self._client
            temporary = client is None
            if temporary:
                client = await self._primary._connect_client(start_video=False)
            assert client is not None
            try:
                await client.pan_tilt(direction)
                await asyncio.sleep(_PTZ_SETTLE_TIME)
            finally:
                if temporary:
                    await client.close()

    async def _run(self) -> None:
        client = None
        try:
            # Serialize connection startup/teardown with PTZ so a control-only
            # connection cannot race the shared video connection.
            async with self._ptz_lock:
                client = await self._primary._connect_client(start_video=False)
                self._sync_session_connection(client)
                self._client = client
                await client.start_media_both(
                    self._primary.device.model,
                    self._primary.options.quality,
                    self._primary.options.quality,
                )
            while True:
                packet = await client.read_video()
                if packet.lens_tag == 0x0000:
                    self._publish(0, packet)
                elif packet.lens_tag == 0x0140:
                    self._publish(1, packet)
                # Unknown flag combinations are ignored, never misrouted.
        except asyncio.CancelledError:
            raise
        except AuthenticationError as err:
            self._end_streams(err)
        except XiaomiError as err:
            self._end_streams(err)
        except (OSError, TimeoutError):
            self._end_streams(TransportError("CW500 local connection failed"))
        except Exception:
            # Never expose raw exceptions: they can contain local endpoint data.
            self._end_streams(TransportError("CW500 dual-lens transport failed"))
        finally:
            async with self._ptz_lock:
                if self._client is client:
                    self._client = None
                if client is not None:
                    with suppress(Exception):
                        await client.close()

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            task, self._task = self._task, None
            self._end_streams(TransportError("CW500 dual-lens transport is closed"))
            if task is not None and not task.done():
                task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)


class DualLensCameraSession(CameraSession):
    """One Home Assistant camera entity backed by a shared CW500 connection."""

    def __init__(
        self,
        *args,
        transport: DualLensTransport | None,
        lens: int,
        stream_id: str,
        **kwargs,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.dual_transport = transport
        self.lens = lens
        self.stream_id = stream_id

    @property
    def supports_pan_tilt(self) -> bool:
        """Only the physical primary CW500 lens has a motor."""
        return self.lens == 0 and super().supports_pan_tilt

    async def _send_pan_tilt(self, direction: str) -> None:
        if self.lens != 0 or self.dual_transport is None:
            raise TransportError("PTZ is available only on the CW500 primary lens")
        await self.dual_transport.pan_tilt(direction)

    async def _capture(self, muxer: MpegTsMuxer) -> None:
        self._state("connecting")
        if self.dual_transport is None:
            raise TransportError("CW500 dual-lens transport is not initialized")
        async with self.dual_transport.subscribe(self.lens) as queue:
            while True:
                item = await asyncio.wait_for(queue.get(), 20)
                if isinstance(item, XiaomiError):
                    raise item
                if item is None:
                    raise TransportError("CW500 dual-lens stream disconnected")
                packet = item
                self.codec = "H.264" if packet.codec == 4 else "H.265"
                video = muxer.feed(packet)
                if video is None:
                    continue
                self.frames += 1
                if self.status != "streaming":
                    self.last_error = None
                    self._state("streaming")
                elif self.frames % 100 == 0:
                    self.on_state()
                if self.options.video_mode == "h264":
                    self._enqueue_video(video)
                else:
                    if video.keyframe:
                        self._cache.clear()
                        self._cache_valid = True
                    if self._cache_valid:
                        self._cache.extend(video.data)
                        if len(self._cache) > 4 * 1024 * 1024:
                            self._cache.clear()
                            self._cache_valid = False
                    self._publish(video.data)

    async def close(self) -> None:
        if self.dual_transport is not None:
            await self.dual_transport.close()
        await super().close()
