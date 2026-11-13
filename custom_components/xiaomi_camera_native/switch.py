"""Fill-light switch for Xiaomi Outdoor Camera CW500 Dual."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TARGET_MODELS
from .protocol.errors import XiaomiError


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    sessions = entry.runtime_data.sessions.values()
    primary = next(
        (
            session
            for session in sessions
            if session.device.model == "isa.camera.500dh"
            and getattr(session, "lens", None) == 0
        ),
        None,
    )
    if primary is not None:
        async_add_entities([XiaomiFillLightSwitch(primary)])


class XiaomiFillLightSwitch(SwitchEntity):
    """MIoT other-functions/hl-filllight-switch property."""

    _attr_has_entity_name = True
    _attr_should_poll = True
    entity_description = SwitchEntityDescription(
        key="fill_light",
        translation_key="fill_light",
        icon="mdi:flashlight",
    )

    def __init__(self, session) -> None:
        self._session = session
        self._attr_unique_id = f"{session.device.did}_fill_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, session.device.did)},
            name=session.device.name,
            manufacturer="Xiaomi",
            model=TARGET_MODELS.get(session.device.model, session.device.model),
        )

    async def async_update(self) -> None:
        value = await self._session.cloud.get_miot_property(
            self._session.device.did, 6, 16
        )
        self._attr_is_on = bool(value)

    async def async_turn_on(self, **kwargs) -> None:
        await self._set_fill_light(True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._set_fill_light(False)

    async def _set_fill_light(self, enabled: bool) -> None:
        try:
            await self._session.cloud.set_miot_property(
                self._session.device.did, 6, 16, enabled
            )
            self._attr_is_on = enabled
            self.async_write_ha_state()
        except XiaomiError as err:
            raise HomeAssistantError(str(err)) from None
