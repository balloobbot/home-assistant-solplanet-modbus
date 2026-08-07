"""Binary sensors: whether an inverter reports a fault in itself."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SolplanetConfigEntry, SolplanetCoordinator
from .entity import SolplanetInverterEntity
from .vendor.solplanet_modbus import FaultState, Inverter

FAULT = BinarySensorEntityDescription(
    key="fault",
    translation_key="fault",
    device_class=BinarySensorDeviceClass.PROBLEM,
)


class SolplanetFaultSensor(SolplanetInverterEntity, BinarySensorEntity):
    """Register 1376: the inverter's own view of whether it has faulted."""

    entity_description = FAULT

    def __init__(self, coordinator: SolplanetCoordinator, inverter: Inverter) -> None:
        """Initialize the fault sensor for one inverter."""
        super().__init__(coordinator, inverter, FAULT.key)
        self.entity_description = FAULT

    @property
    def is_on(self) -> bool | None:
        """Whether the inverter reports an internal fault."""
        state = self.inverter.data.fault_state
        if state is None:
            return None
        return state is FaultState.INTERNAL_FAULT


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolplanetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up one fault sensor per inverter."""
    coordinator = entry.runtime_data
    async_add_entities(
        SolplanetFaultSensor(coordinator, inverter)
        for inverter in coordinator.inverters
    )
