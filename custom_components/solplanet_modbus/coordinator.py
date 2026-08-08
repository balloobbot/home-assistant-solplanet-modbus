"""DataUpdateCoordinator polling the site's live registers."""

from __future__ import annotations

import contextlib
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from modbus_connection import ModbusConnection, ModbusError, ModbusUnit
from modbus_connection.model import ComponentGroup

from .const import (
    CONF_INVERTERS,
    CONF_METER,
    CONF_MODE,
    CONF_WEATHER,
    DOMAIN,
    FAILURES_BEFORE_RECONNECT,
    MODE_AILOGGER,
    SCAN_INTERVAL,
)
from .vendor.solplanet_modbus import (
    AiLogger,
    EnergyMeter,
    Inverter,
    InverterControls,
    SystemPower,
    WeatherStation,
)

_LOGGER = logging.getLogger(__name__)

type SolplanetConfigEntry = ConfigEntry[SolplanetCoordinator]


class SolplanetCoordinator(DataUpdateCoordinator[None]):
    """Poll every inverter, plus whatever else the entry covers.

    Two shapes sit behind the same attributes. An Ai-Logger serves the whole
    site — several inverters, the summed power, and optionally a weather station
    and an SDM630 meter — from one flat register map. A bare inverter serves
    only its own block, which is the same layout at the same addresses, so it is
    simply a site of one with nothing around it.

    The identity registers are read once during setup: they describe the
    hardware and never change while it runs, and re-reading 124 registers per
    inverter every cycle would double the traffic for nothing.

    A dropped link is not an entry reload: the connection re-establishes itself
    on the next request, so a failed poll marks the entities unavailable and the
    next successful one brings them back.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SolplanetConfigEntry,
        connection: ModbusConnection,
        unit: ModbusUnit,
    ) -> None:
        """Build the device objects the entry describes."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self._connection = connection
        self._failures = 0
        self.unit = unit
        self.ailogger: AiLogger | None = None
        self.site: SystemPower | None = None
        self.weather: WeatherStation | None = None
        self.meter: EnergyMeter | None = None
        self.controls: InverterControls | None = None

        if entry.data.get(CONF_MODE) == MODE_AILOGGER:
            logger = AiLogger(
                unit,
                entry.data[CONF_INVERTERS],
                weather=entry.data.get(CONF_WEATHER, False),
                meter=entry.data.get(CONF_METER, False),
            )
            self.ailogger = logger
            self.inverters = logger.inverters
            self.site = logger.system
            self.weather = logger.weather
            self.meter = logger.meter
            # The control registers live in the logger's map, not an inverter's.
            self.controls = logger.controls
        else:
            self.inverters = (Inverter(unit),)

    def inverter_key(self, inverter: Inverter) -> str:
        """A stable id for one inverter, for unique ids and device identifiers.

        Prefers the serial number. An inverter that did not answer the identity
        read falls back to where it sits, so its entities keep working and keep
        their ids across restarts.
        """
        if serial := inverter.info.serial_number:
            return serial
        entry_id = self.config_entry.entry_id
        if inverter.slot is not None:
            return f"{entry_id}_{inverter.slot.modbus_id}"
        return entry_id

    async def async_read_info(self) -> None:
        """Read every inverter's identity block once.

        Raises ``ModbusError`` if the device rejects a block.
        """
        if self.ailogger is not None:
            await self.ailogger.async_read_info()
        else:
            await self.inverters[0].async_update_info()

    async def async_read_raw(self) -> dict[str, dict[int, int | bool]]:
        """Return every modeled register word by address, freshly read."""
        components: list[Any] = [
            component
            for inverter in self.inverters
            for component in (inverter.info, inverter.data)
        ]
        components += [
            component
            for component in (self.site, self.weather, self.meter)
            if component is not None
        ]
        return await ComponentGroup(self.unit, components).async_read_raw()

    async def _async_update_data(self) -> None:
        """Refresh every polled component in pooled block reads."""
        try:
            if self.ailogger is not None:
                await self.ailogger.async_update()
            else:
                await self.inverters[0].async_update()
        except ModbusError as err:
            await self._recycle_a_stuck_link()
            raise UpdateFailed(f"Error reading the inverters: {err}") from err
        self._failures = 0

    async def _recycle_a_stuck_link(self) -> None:
        """Tear the link down once a run of polls has failed.

        A link the transport drops re-establishes itself on the next request, so
        most failures need nothing. This is for the case that does not heal on
        its own: the logger accepts one client at a time, so another one taking
        it over can leave this socket open but unanswered. Dropping it deliberately
        makes the next poll build a fresh one; unlike ``close()`` the connection
        stays usable, so nothing has to reload the config entry.
        """
        self._failures += 1
        if self._failures < FAILURES_BEFORE_RECONNECT:
            return
        self._failures = 0
        _LOGGER.debug(
            "Recycling the connection after %s failed polls", FAILURES_BEFORE_RECONNECT
        )
        # The link is dropped whether or not tearing it down cleanly worked.
        with contextlib.suppress(ModbusError):
            await self._connection.disconnect()
