"""Numbers: the Ai-Logger's output power control registers.

These registers are write-only and a write reaches *every* inverter the logger
manages, so there is one set per config entry and they sit on the logger's
device. Nothing can be read back, so each entity remembers what it last wrote
and restores that across a restart — the value shown is what Home Assistant
last sent, not what the inverters confirm.

UM0058's fast active power command (register 60000) is deliberately absent: it
is a relative adjustment that has to be rewritten every 500 ms to stay in
effect, which is a control loop rather than a setpoint.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from modbus_connection import ModbusError

from .coordinator import SolplanetConfigEntry, SolplanetCoordinator
from .entity import SolplanetSiteEntity
from .vendor.solplanet_modbus import InverterControls, SolplanetValueValidationError


@dataclass(frozen=True, kw_only=True)
class SolplanetNumberDescription(NumberEntityDescription):
    """Describes a write-only control register."""

    set_fn: Callable[[InverterControls, float], Awaitable[None]]


NUMBERS: tuple[SolplanetNumberDescription, ...] = (
    SolplanetNumberDescription(
        key="active_power_limit",
        translation_key="active_power_limit",
        native_min_value=0,
        native_max_value=110,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.SLIDER,
        set_fn=lambda c, v: c.async_set_active_power_limit(v),
    ),
    SolplanetNumberDescription(
        key="reactive_power",
        translation_key="reactive_power_command",
        native_min_value=-65,
        native_max_value=65,
        native_step=1,
        native_unit_of_measurement=PERCENTAGE,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        set_fn=lambda c, v: c.async_set_reactive_power(v),
    ),
    # Only 0.75..1 leading and -1..-0.75 lagging mean anything; the band in
    # between is rejected by the library with a clear error.
    SolplanetNumberDescription(
        key="power_factor",
        translation_key="power_factor_command",
        native_min_value=-1,
        native_max_value=1,
        native_step=0.01,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
        entity_registry_enabled_default=False,
        set_fn=lambda c, v: c.async_set_power_factor(v),
    ),
)


class SolplanetControlNumber(SolplanetSiteEntity, NumberEntity, RestoreEntity):
    """A write-only control register, showing the value last written."""

    entity_description: SolplanetNumberDescription

    def __init__(
        self,
        coordinator: SolplanetCoordinator,
        controls: InverterControls,
        description: SolplanetNumberDescription,
    ) -> None:
        """Initialize from the description."""
        super().__init__(coordinator, description.key)
        self._controls = controls
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        """Restore the value this entity last wrote."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is None:
            return
        try:
            self._attr_native_value = float(last_state.state)
        except ValueError:  # unknown / unavailable, i.e. never written
            self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        """Write the value and remember it."""
        try:
            await self.entity_description.set_fn(self._controls, value)
        except SolplanetValueValidationError as err:
            raise HomeAssistantError(str(err)) from err
        except ModbusError as err:
            raise HomeAssistantError(f"Could not write the control: {err}") from err
        self._attr_native_value = value
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolplanetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the control numbers, which only an Ai-Logger has."""
    coordinator = entry.runtime_data
    if (controls := coordinator.controls) is None:
        return
    async_add_entities(
        SolplanetControlNumber(coordinator, controls, description)
        for description in NUMBERS
    )
