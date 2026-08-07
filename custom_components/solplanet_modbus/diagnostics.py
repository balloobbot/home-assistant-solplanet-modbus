"""Diagnostics: the raw register map behind every entity."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from modbus_connection import ModbusError

from .coordinator import SolplanetConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SolplanetConfigEntry
) -> dict[str, Any]:
    """Return the live raw registers, keyed by address.

    The dump replays straight into modbus-connection's mock backend
    (``load_raw``), so an attached diagnostics file can back a regression
    test with no hardware.
    """
    coordinator = entry.runtime_data
    try:
        registers: dict[str, Any] = await coordinator.async_read_raw()
    except ModbusError as err:
        registers = {"error": str(err)}
    return {
        "inverters": [
            {
                "modbus_id": inverter.slot.modbus_id if inverter.slot else None,
                "base_address": inverter.slot.base_address if inverter.slot else None,
                "machine_type": inverter.info.machine_type,
                "phase_type": str(inverter.info.phase_type),
                "mppt_count": inverter.info.mppt_count,
                "string_current_count": inverter.info.string_current_count,
            }
            for inverter in coordinator.inverters
        ],
        "has_weather": coordinator.weather is not None,
        "has_meter": coordinator.meter is not None,
        "registers": registers,
    }
