"""Home Assistant camera entities backed by the direct protocol client."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TARGET_MODELS
from .protocol.session import CameraSession, LoopbackServer
from .protocol.snapshot import (
    SNAPSHOT_CACHE_SECONDS,
    SNAPSHOT_RETRY_SECONDS,
    SNAPSHOT_TIMEOUT,
    async_get_snapshot,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    runtime = entry.runtime_data
    async_add_entities(
        NativeXiaomiCamera(session, runtime.server, stream_id)
        for stream_id, session in runtime.sessions.items()
    )


class NativeXiaomiCamera(Camera):
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_brand = "Xiaomi"
    _attr_should_poll = False

    def __init__(self, session: CameraSession, server: LoopbackServer, stream_id: str) -> None:
        super().__init__()
        self._session = session
        self._server = server
        self._attr_unique_id = (
            session.device.did if stream_id.endswith("_primary") else stream_id
        )
        self._stream_id = stream_id
        if stream_id.endswith("_primary"):
            self._attr_name = "Główny obiektyw"
        elif stream_id.endswith("_secondary"):
            self._attr_name = "Dodatkowy obiektyw"
        self._attr_model = TARGET_MODELS.get(session.device.model, session.device.model)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, session.device.did)},
            name=session.device.name,
            manufacturer="Xiaomi",
            model=self._attr_model,
        )
        # Home Assistant accepts a small set of stream options, not arbitrary
        # libavformat flags. MPEG-TS works with the built-in defaults.
        self.stream_options = {}
        self._fast_snapshot_enabled = True
        self._snapshot_lock = asyncio.Lock()
        self._snapshot_cache: tuple[tuple[int | None, int | None], float, bytes] | None = None
        self._snapshot_retry_at = 0.0
        self._last_snapshot_error: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        previous = self._session.on_state

        def changed() -> None:
            previous()
            self.async_write_ha_state()

        self._session.on_state = changed
        self.async_on_remove(lambda: setattr(self._session, "on_state", previous))

    @property
    def is_streaming(self) -> bool:
        return self._session.status == "streaming"

    @property
    def extra_state_attributes(self) -> dict:
        session = self._session
        attributes = {
            "connection_status": session.status,
            "transport": session.protocol,
            "source_codec": session.codec,
            "video_mode": session.options.video_mode,
            "max_h264_height": session.options.height,
            "frames_received": session.frames,
            "reconnects": session.reconnects,
            "encoder_restarts": session.encoder_restarts,
            "encoder_dropped_frames": session.encoder_dropped_frames,
            "last_error": session.last_error,
            "pan_tilt_supported": session.supports_pan_tilt,
            "pan_tilt_experimental": session.pan_tilt_experimental,
            "last_ptz_error": session.last_ptz_error,
            "fast_snapshot_enabled": self._fast_snapshot_enabled,
            "last_snapshot_error": self._last_snapshot_error,
            "ip_address": session.host,
            "auto_update_ip": session.options.auto_update_ip,
            "address_source": session.address_source,
            "address_updates": session.address_updates,
        }
        if session.supports_pan_tilt and getattr(self, "hass", None) is not None:
            registry = er.async_get(self.hass)
            buttons = {}
            for direction in ("left", "right", "up", "down"):
                entity_id = registry.async_get_entity_id(
                    "button", DOMAIN, f"{session.device.did}_ptz_{direction}"
                )
                entry = registry.async_get(entity_id) if entity_id else None
                if entry is not None and entry.disabled_by is None:
                    buttons[direction] = entity_id
            if buttons:
                # Resolve through the registry so renamed buttons keep working.
                attributes["xiaomi_pan_tilt_buttons"] = buttons
        return attributes

    async def stream_source(self) -> str:
        # The stream URL is local to HA, not a go2rtc or Xiaomi cloud URL.
        return self._server.source(self._stream_id)

    def _set_snapshot_error(self, error: str | None) -> None:
        if self._last_snapshot_error == error:
            return
        self._last_snapshot_error = error
        if getattr(self, "entity_id", None):
            self.async_write_ha_state()

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        # One budget includes lock waiting and both probe modes. A stalled
        # camera must not trigger two successive full-length snapshot waits.
        loop = asyncio.get_running_loop()
        key = (width, height)
        try:
            async with asyncio.timeout(SNAPSHOT_TIMEOUT):
                async with self._snapshot_lock:
                    cached = self._snapshot_cache
                    if (
                        cached
                        and cached[0] == key
                        and loop.time() - cached[1] < SNAPSHOT_CACHE_SECONDS
                    ):
                        return cached[2]
                    if loop.time() < self._snapshot_retry_at:
                        return None
                    source = await self.stream_source()
                    try:
                        image = await async_get_snapshot(
                            self._session.ffmpeg,
                            source,
                            width=width,
                            height=height,
                            fast=self._fast_snapshot_enabled,
                        )
                    except TimeoutError:
                        raise
                    except Exception:
                        image = None
                    if image is None and self._fast_snapshot_enabled:
                        # Only a reader which exits unsuccessfully gets an
                        # immediate standard-probe retry. A timeout propagates
                        # to the shared deadline instead of starting a retry.
                        self._fast_snapshot_enabled = False
                        _LOGGER.debug("Fast snapshot unavailable; using standard input analysis")
                        image = await async_get_snapshot(
                            self._session.ffmpeg, source, width=width, height=height, fast=False
                        )
                    if image is not None:
                        self._snapshot_cache = (key, loop.time(), image)
                        self._set_snapshot_error(None)
                        return image
                    self._set_snapshot_error("FFmpeg did not produce a complete snapshot")
        except TimeoutError:
            self._set_snapshot_error("Snapshot timed out waiting for video")
        except Exception:
            # Do not expose commands, loopback tokens, or exception payloads.
            self._set_snapshot_error("Snapshot capture failed")
        self._snapshot_retry_at = loop.time() + SNAPSHOT_RETRY_SECONDS
        _LOGGER.debug("Snapshot unavailable; waiting briefly before another capture")
        return None
