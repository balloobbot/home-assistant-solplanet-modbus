"""The Solplanet Ai-Logger (Modbus) integration.

Talks Modbus to a Solplanet (AISWEI) Ai-Logger — or straight to a single
inverter — through the vendored ``solplanet_modbus`` device library over
``modbus-connection``. The integration owns the connection; the library only
ever sees a ``ModbusUnit``.
"""

from __future__ import annotations

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from modbus_connection import ModbusError

from . import connection as connection_module
from .const import CONF_UNIT_ID, DEFAULT_INVERTER_UNIT_ID
from .coordinator import SolplanetConfigEntry, SolplanetCoordinator

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.NUMBER,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(hass: HomeAssistant, entry: SolplanetConfigEntry) -> bool:
    """Set up a Solplanet Ai-Logger from a config entry."""
    connection = connection_module.build_connection(entry.data)
    # The whole teardown; also runs when setup fails below. close() is
    # permanent, so a reload builds a fresh connection.
    entry.async_on_unload(connection.close)

    unit = connection.for_unit(entry.data.get(CONF_UNIT_ID, DEFAULT_INVERTER_UNIT_ID))
    coordinator = SolplanetCoordinator(hass, entry, unit)

    # One discovery read: the identity blocks name the devices and say how many
    # PV inputs, strings and phases each inverter actually has.
    try:
        await coordinator.async_read_info()
    except ModbusError as err:
        raise ConfigEntryNotReady(f"Could not read the inverters: {err}") from err

    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SolplanetConfigEntry) -> bool:
    """Unload a Solplanet config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
