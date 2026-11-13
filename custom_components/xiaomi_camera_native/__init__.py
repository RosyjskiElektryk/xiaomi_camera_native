"""Direct Xiaomi MISS/CS2 cameras, with no go2rtc runtime dependency."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import logging
from typing import Any

from aiohttp import DummyCookieJar
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .const import CONF_DEVICES, CONF_PROFILES, CONF_REGION, DOMAIN
from .frontend import async_register_frontend
from .protocol.address import CameraAddressResolver, router_addresses
from .protocol.cloud import CameraDevice, XiaomiCloud
from .protocol.errors import AuthenticationError, CloudError
from .protocol.session import CameraSession, LoopbackServer, StreamOptions
from .protocol.dual_lens import DualLensCameraSession, DualLensTransport

PLATFORMS = [Platform.CAMERA, Platform.BUTTON, Platform.SELECT, Platform.SWITCH]
_LOGGER = logging.getLogger(__name__)


@dataclass
class RuntimeData:
    cloud: XiaomiCloud
    server: LoopbackServer
    sessions: dict[str, CameraSession]
    entry_data: dict[str, Any]
    entry_options: dict[str, Any]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Xiaomi account cookies must never mix with another integration/account.
    http = async_create_clientsession(hass, cookie_jar=DummyCookieJar())
    cloud = XiaomiCloud(http, entry.data[CONF_REGION])
    try:
        await cloud.authenticate(entry.data)
    except AuthenticationError as err:
        http.detach()
        raise ConfigEntryAuthFailed(str(err)) from None
    except CloudError as err:
        http.detach()
        raise ConfigEntryNotReady(str(err)) from None

    sessions: dict[str, CameraSession] = {}
    auth_requested = False
    known_data = deepcopy(dict(entry.data))
    known_options = deepcopy(dict(entry.options))
    resolver = CameraAddressResolver(
        cloud, lambda device: router_addresses(device, hass.states.async_all("device_tracker"))
    )

    def save_rotated_credentials() -> None:
        credentials = cloud.credentials.persistent()
        if any(entry.data.get(key) != value for key, value in credentials.items()):
            known_data.update(credentials)
            hass.config_entries.async_update_entry(entry, data={**entry.data, **credentials})

    def save_camera_address(device: CameraDevice, host: str) -> None:
        # If a user changed configuration while connect() was awaiting I/O,
        # let its pending reload win. Never absorb that edit into our baseline.
        if entry.data != known_data or entry.options != known_options:
            return
        data = deepcopy(known_data)
        options = deepcopy(known_options)
        for raw in data[CONF_DEVICES]:
            if raw["did"] == device.did:
                raw["host"] = host
        profile = options.get(CONF_PROFILES, {}).get(device.did, {})
        if "host" in profile:
            profile["host"] = host
        known_data.clear()
        known_data.update(data)
        known_options.clear()
        known_options.update(options)
        hass.config_entries.async_update_entry(entry, data=data, options=options)

    def request_reauth() -> None:
        nonlocal auth_requested
        if not auth_requested:
            auth_requested = True
            entry.async_start_reauth(hass)

    save_rotated_credentials()
    profiles = entry.options.get(CONF_PROFILES, {})
    for raw in entry.data[CONF_DEVICES]:
        device = CameraDevice(**raw)
        profile = {
            "quality": "auto" if device.model == "mxiang.camera.c301" else "hd",
            **profiles.get(device.did, {}),
        }
        options = StreamOptions.from_profile(profile)
        sessions[device.did] = CameraSession(
            cloud,
            device,
            options,
            get_ffmpeg_manager(hass).binary,
            on_state=save_rotated_credentials,
            on_auth_error=request_reauth,
            address_resolver=resolver,
            on_address_changed=save_camera_address,
        )
    # CW500 Dual has two video channels interleaved on one physical MISS socket.
    for did, original in tuple(sessions.items()):
        if original.device.model != "isa.camera.500dh":
            continue
        primary = DualLensCameraSession(
            cloud, original.device, original.options, original.ffmpeg,
            on_state=save_rotated_credentials, on_auth_error=request_reauth,
            address_resolver=resolver, on_address_changed=save_camera_address,
            transport=None, lens=0, stream_id=f"{did}_primary",
        )
        transport = DualLensTransport(primary)
        primary.dual_transport = transport
        secondary = DualLensCameraSession(
            cloud, original.device, original.options, original.ffmpeg,
            on_state=save_rotated_credentials, on_auth_error=request_reauth,
            address_resolver=resolver, on_address_changed=save_camera_address,
            transport=transport, lens=1, stream_id=f"{did}_secondary",
        )
        transport.sessions.append(secondary)
        await original.close()
        del sessions[did]
        sessions[primary.stream_id] = primary
        sessions[secondary.stream_id] = secondary
    server = LoopbackServer(sessions)
    try:
        await server.start()
        await async_register_frontend(hass)
        entry.runtime_data = RuntimeData(cloud, server, sessions, known_data, known_options)
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        # Only reconcile stale registry devices after the new platforms load.
        # A camera deselected in Rediscover must not leave an empty device.
        try:
            _cleanup_removed_camera_devices(hass, entry)
        except Exception:
            # A registry cleanup error must never bring down working streams.
            _LOGGER.exception("Failed to reconcile removed Xiaomi camera devices")
    except BaseException:
        await server.close()
        raise
    entry.async_on_unload(entry.add_update_listener(_options_updated))

    async def shutdown(_event) -> None:
        await server.close()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown))
    return True


async def _options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    # Internal IP/credential saves must not tear down a newly recovered stream.
    # Real profile edits and rediscovery still reload the integration.
    runtime = entry.runtime_data
    if entry.data == runtime.entry_data and entry.options == runtime.entry_options:
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.server.close()
        return True
    return False


def _configured_camera_ids(entry: ConfigEntry) -> set[str]:
    """IDs deliberately selected for this Xiaomi account, not cloud discoveries."""
    return {raw["did"] for raw in entry.data.get(CONF_DEVICES, ())}


def _is_removed_camera_device(entry: ConfigEntry, device: dr.DeviceEntry) -> bool:
    """Recognize only *our* previously selected cameras, never active devices."""
    owners = getattr(device, "config_entries", None)
    if owners is not None:
        if set(owners) != {entry.entry_id}:
            # Refuse shared devices and devices owned by other entries.
            return False
    elif getattr(device, "config_entry_id", None) != entry.entry_id:
        return False
    ids = {identifier for domain, identifier in device.identifiers if domain == DOMAIN}
    return bool(ids) and ids.isdisjoint(_configured_camera_ids(entry))


def _remove_camera_entities(hass: HomeAssistant, entry: ConfigEntry, device_id: str) -> None:
    """Forget removed camera and PTZ entities, including disabled entries."""
    registry = er.async_get(hass)
    for entity in er.async_entries_for_device(
        registry, device_id, include_disabled_entities=True
    ):
        if entity.config_entry_id == entry.entry_id and entity.platform == DOMAIN:
            registry.async_remove(entity.entity_id)


def _cleanup_removed_camera_devices(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Prune stale device records after a successful setup/reload/Rediscover."""
    registry = dr.async_get(hass)
    for device in tuple(dr.async_entries_for_config_entry(registry, entry.entry_id)):
        if not _is_removed_camera_device(entry, device):
            continue
        _remove_camera_entities(hass, entry, device.id)
        if registry.async_get(device.id) is not None:
            registry.async_remove_device(device.id)
        _LOGGER.debug("Removed orphaned Xiaomi camera device %s", device.id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, entry: ConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow deletion of orphaned cameras, but never a selected/live camera.

    Use Rediscover to deselect an active camera first. Core removes the
    registry device itself after this handler approves the removal.
    """
    if not _is_removed_camera_device(entry, device_entry):
        return False
    _remove_camera_entities(hass, entry, device_entry.id)
    return True
