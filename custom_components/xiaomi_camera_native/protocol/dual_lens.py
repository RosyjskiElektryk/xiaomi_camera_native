"""Shared MISS transport for the Xiaomi CW500's interleaved dual-lens video."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager, suppress
from collections.abc import AsyncIterator

from .errors import AuthenticationError, TransportError
from .media import MpegTsMuxer\nfrom .session import CameraSession


class DualLensTransport:
    """Demultiplex both CW500 video channels from one authenticated CS2 socket.

    The camera sends both elementary streams over channel 2. Lens identity is
    carried in the media flags: 0x0000 for the primary lens and 0x0140 for the
    secondary lens after applying the documented 0x0140 mask.
    """

    def __init__(self, primary_session) -> None:
        self._primary = primary_session
        self._queues: dict[int, set[asyncio.Queue]] = {0: set(), 1: set()}
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._closed = False

    @asynccontextmanager
    async def subscribe(self, lens: int) -> AsyncIterator[asyncio.Queue]:
        if lens not in (0, 1):
            raise ValueError("CW500 lens must be 0 or 1")
        queue: asyncio.Queue = asyncio.Queue(256)
        async with self._lock:
            if self._closed:
                raise TransportError("Dual-lens transport is closed")
            self._queues[lens].add(queue)
            if self._task is None or self._task.done():
                self._task = asyncio.create_task(self._run())
        try:
            yield queue
        finally:
            async with self._lock:
                self._queues[lens].discard(queue)
                if not self._queues[0] and not self._queues[1]:
                    task = self._task
                    self._task = None
                    if task is not None and not task.done():
                        task.cancel()
            if task is not None and not task.done():
                await asyncio.gather(task, return_exceptions=True)

    def _publish(self, lens: int, packet) -> None:
        for queue in tuple(self._queues[lens]):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)
                self._queues[lens].discard(queue)
                continue
            queue.put_nowait(packet)

    def _end_streams(self) -> None:
        for queues in self._queues.values():
            for queue in tuple(queues):
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)

    async def _run(self) -> None:
        client = None
        try:
            client = await self._primary._connect_client(start_video=False)
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
        except asyncio.CancelledError:
            raise
        except AuthenticationError:
            self._primary.on_auth_error()
            self._end_streams()
        except Exception:
            # Do not log exception payloads: transport errors may contain
            # endpoint details. Both logical sessions reconnect independently.
            self._end_streams()
        finally:
            if client is not None:
                with suppress(Exception):
                    await client.close()

    async def close(self) -> None:
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            task, self._task = self._task, None
            self._end_streams()
            if task is not None and not task.done():
                task.cancel()
        if task is not None:
            await asyncio.gather(task, return_exceptions=True)


from .session import CameraSession\n\n\nclass DualLensCameraSession(CameraSession):
    """Logical camera endpoint backed by the shared CW500 socket."""

    def __init__(self, *args, transport: DualLensTransport | None, lens: int, stream_id: str, **kwargs):
        super().__init__(*args, **kwargs)
        self.dual_transport = transport
        self.lens = lens
        self.stream_id = stream_id

    async def _capture(self, muxer: MpegTsMuxer) -> None:
        self._state("connecting")
        if self.dual_transport is None:
            raise TransportError("CW500 dual-lens transport is not initialized")
        async with self.dual_transport.subscribe(self.lens) as queue:
            while True:
                packet = await asyncio.wait_for(queue.get(), 20)
                if packet is None:
                    raise TransportError("CW500 dual-lens stream disconnected")
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
