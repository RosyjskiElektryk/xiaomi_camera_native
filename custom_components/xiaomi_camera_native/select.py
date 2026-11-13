"""Night-vision mode selector for Xiaomi Outdoor Camera CW500 Dual."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, TARGET_MODELS
from .protocol.cloud import CloudError
from .protocol.errors import AuthenticationError, XiaomiError

NIGHT_MODES = {
    "Off": 0,
    "IR": 1,
    "Auto": 2,
    "Auto full-colour": 3,
    "Always full-colour": 4,
    "Smart full-colour": 5,
}
NIGHT_MODE_BY_VALUE = {value: key for key, value in NIGHT_MODES.items()}


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
        async_add_entities([XiaomiNightVisionSelect(primary)])


class XiaomiNightVisionSelect(SelectEntity):
    """MIoT camera-control/night-shot property."""

    _attr_has_entity_name = True
    _attr_should_poll = True
    entity_description = SelectEntityDescription(
        key="night_vision_mode",
        translation_key="night_vision_mode",
        icon="mdi:weather-night",
    )
    _attr_options = list(NIGHT_MODES)

    def __init__(self, session) -> None:
        self._session = session
        self._attr_unique_id = f"{session.device.did}_night_vision_mode"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, session.device.did)},
            name=session.device.name,
            manufacturer="Xiaomi",
            model=TARGET_MODELS.get(session.device.model, session.device.model),
        )

    async def async_update(self) -> None:
        value = await self._session.cloud.get_miot_property(
            self._session.device.did, 2, 3
        )
        self._attr_current_option = NIGHT_MODE_BY_VALUE.get(value)

    async def async_select_option(self, option: str) -> None:
        if option not in NIGHT_MODES:
            raise HomeAssistantError("Unsupported CW500 night-vision mode")
        try:
            await self._session.cloud.set_miot_property(
                self._session.device.did, 2, 3, NIGHT_MODES[option]
            )
            if option == "Off":
                await self._session.cloud.set_miot_property(
                    self._session.device.did, 6, 16, False
                )
            self._attr_current_option = option
            self.async_write_ha_state()
        except XiaomiError as err:
            raise HomeAssistantError(str(err)) from None
