"""Base entities: one Home Assistant device per inverter, one for the logger."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolplanetCoordinator
from .vendor.solplanet_modbus import Inverter

MANUFACTURER = "Solplanet"


class SolplanetInverterEntity(CoordinatorEntity[SolplanetCoordinator]):
    """An entity belonging to one inverter."""

    _attr_has_entity_name = True

    def __init__(
        self, coordinator: SolplanetCoordinator, inverter: Inverter, key: str
    ) -> None:
        """Initialize identity from the inverter's own identity block."""
        super().__init__(coordinator)
        self.inverter = inverter
        info = inverter.info
        device_key = coordinator.inverter_key(inverter)
        self._attr_unique_id = f"{device_key}_{key}"

        name = info.machine_type or "Inverter"
        if inverter.slot is not None:
            name = f"{name} {inverter.slot.modbus_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device_key)},
            manufacturer=info.brand or info.manufacturer or MANUFACTURER,
            model=info.machine_type,
            name=name,
            serial_number=info.serial_number or None,
            sw_version=info.master_software_version or None,
            # An inverter reached through a logger hangs off it; one reached
            # directly is a device in its own right.
            via_device=(DOMAIN, coordinator.config_entry.entry_id)
            if coordinator.ailogger is not None
            else None,
        )


class SolplanetSiteEntity(CoordinatorEntity[SolplanetCoordinator]):
    """An entity belonging to the Ai-Logger itself rather than to an inverter.

    The site totals, the weather station, the meter and the control registers
    are all the logger's, so they share one device. UM0058 exposes no identity
    for the logger, hence the config entry as its identifier.
    """

    _attr_has_entity_name = True

    def __init__(self, coordinator: SolplanetCoordinator, key: str) -> None:
        """Initialize identity from the config entry."""
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            model="Ai-Logger",
            name=entry.title,
        )
