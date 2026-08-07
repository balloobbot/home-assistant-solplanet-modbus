"""Switch: the Ai-Logger's inverter on/off command.

Write-only and site-wide, like the control numbers — see ``number.py``. Turning
this off stops every inverter the logger manages from producing, so it is
disabled by default: enable it only if you mean to have that switch reachable.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import (
    SwitchDeviceClass,
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.const import STATE_ON, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from modbus_connection import ModbusError

from .coordinator import SolplanetConfigEntry, SolplanetCoordinator
from .entity import SolplanetSiteEntity
from .vendor.solplanet_modbus import InverterControls

INVERTER_POWER = SwitchEntityDescription(
    key="inverter_power",
    translation_key="inverter_power",
    device_class=SwitchDeviceClass.SWITCH,
    entity_category=EntityCategory.CONFIG,
    entity_registry_enabled_default=False,
)


class SolplanetPowerSwitch(SolplanetSiteEntity, SwitchEntity, RestoreEntity):
    """Register 60002, showing the state last written rather than a reading."""

    entity_description = INVERTER_POWER

    def __init__(
        self, coordinator: SolplanetCoordinator, controls: InverterControls
    ) -> None:
        """Initialize the site-wide on/off switch."""
        super().__init__(coordinator, INVERTER_POWER.key)
        self._controls = controls
        self.entity_description = INVERTER_POWER
        self._attr_is_on: bool | None = None

    async def async_added_to_hass(self) -> None:
        """Restore the state this entity last wrote."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._attr_is_on = last_state.state == STATE_ON

    async def _async_write(self, turn_on: bool) -> None:
        """Send the command and remember it."""
        try:
            if turn_on:
                await self._controls.async_turn_on()
            else:
                await self._controls.async_turn_off()
        except ModbusError as err:
            raise HomeAssistantError(f"Could not write the control: {err}") from err
        self._attr_is_on = turn_on
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start every inverter the logger manages."""
        await self._async_write(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Stop every inverter the logger manages."""
        await self._async_write(False)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolplanetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the on/off switch, which only an Ai-Logger has."""
    coordinator = entry.runtime_data
    if (controls := coordinator.controls) is None:
        return
    async_add_entities([SolplanetPowerSwitch(coordinator, controls)])
