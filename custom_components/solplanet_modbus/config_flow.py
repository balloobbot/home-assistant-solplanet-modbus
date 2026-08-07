"""Config flow for the Solplanet Ai-Logger (Modbus) integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    SerialPortSelector,
    TextSelector,
)
from modbus_connection import ModbusError

from . import connection as connection_module
from .const import (
    CONF_BAUDRATE,
    CONF_CONNECTION_TYPE,
    CONF_FRAMER,
    CONF_INVERTERS,
    CONF_METER,
    CONF_MODE,
    CONF_PARITY,
    CONF_SCAN_PORTS,
    CONF_SERIAL_DEVICE,
    CONF_UNIT_ID,
    CONF_WEATHER,
    CONNECTION_TYPE_NETWORK,
    CONNECTION_TYPE_SERIAL,
    DEFAULT_BAUDRATE,
    DEFAULT_INVERTER_FRAMER,
    DEFAULT_INVERTER_PORT,
    DEFAULT_INVERTER_UNIT_ID,
    DEFAULT_LOGGER_FRAMER,
    DEFAULT_LOGGER_PORT,
    DEFAULT_PARITY,
    DOMAIN,
    MODE_AILOGGER,
    MODE_INVERTER,
    STEP_AILOGGER,
    STEP_INVERTER_NETWORK,
    STEP_INVERTER_SERIAL,
)
from .vendor.solplanet_modbus import (
    AILOGGER_UNIT_ID,
    AiLogger,
    ComPort,
    Inverter,
    slots_for_port,
)

_PORT = NumberSelector(
    NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
)
_LOGGER_UNIT_ID = NumberSelector(
    NumberSelectorConfig(min=1, max=247, step=1, mode=NumberSelectorMode.BOX)
)
# An inverter's own RS-485 address. The logger's port ranges (3-32, 51-80,
# 102-131) all sit inside this, and a standalone inverter can be anywhere.
_INVERTER_UNIT_ID = NumberSelector(
    NumberSelectorConfig(min=1, max=247, step=1, mode=NumberSelectorMode.BOX)
)
_FRAMER = SelectSelector(
    SelectSelectorConfig(
        options=["socket", "rtu"],
        mode=SelectSelectorMode.DROPDOWN,
        translation_key="framer",
    )
)
_BAUDRATE = SelectSelector(
    SelectSelectorConfig(
        options=["9600", "19200", "38400", "57600", "115200"],
        mode=SelectSelectorMode.DROPDOWN,
    )
)
_PARITY = SelectSelector(
    SelectSelectorConfig(
        options=["e", "n", "o"],
        mode=SelectSelectorMode.DROPDOWN,
        translation_key="parity",
    )
)
_SCAN_PORTS = SelectSelector(
    SelectSelectorConfig(
        options=[str(port.value) for port in ComPort],
        multiple=True,
        mode=SelectSelectorMode.LIST,
        translation_key="scan_ports",
    )
)

STEP_AILOGGER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(),
        vol.Required(CONF_PORT, default=DEFAULT_LOGGER_PORT): _PORT,
        vol.Required(CONF_UNIT_ID, default=AILOGGER_UNIT_ID): _LOGGER_UNIT_ID,
        vol.Required(CONF_SCAN_PORTS, default=[str(ComPort.COM1.value)]): _SCAN_PORTS,
        vol.Required(CONF_WEATHER, default=False): BooleanSelector(),
        vol.Required(CONF_METER, default=False): BooleanSelector(),
    }
)

STEP_INVERTER_NETWORK_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): TextSelector(),
        vol.Required(CONF_PORT, default=DEFAULT_INVERTER_PORT): _PORT,
        vol.Required(CONF_FRAMER, default=DEFAULT_INVERTER_FRAMER): _FRAMER,
        vol.Required(CONF_UNIT_ID, default=DEFAULT_INVERTER_UNIT_ID): _INVERTER_UNIT_ID,
    }
)

STEP_INVERTER_SERIAL_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_SERIAL_DEVICE): SerialPortSelector(),
        vol.Required(CONF_BAUDRATE, default=str(DEFAULT_BAUDRATE)): _BAUDRATE,
        vol.Required(CONF_PARITY, default=DEFAULT_PARITY): _PARITY,
        vol.Required(CONF_UNIT_ID, default=DEFAULT_INVERTER_UNIT_ID): _INVERTER_UNIT_ID,
    }
)


class SolplanetConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the setup flow: pick what is on the other end, describe it, probe."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick which device the integration talks to."""
        return self.async_show_menu(
            step_id="user",
            menu_options=[
                STEP_AILOGGER,
                STEP_INVERTER_SERIAL,
                STEP_INVERTER_NETWORK,
            ],
        )

    async def async_step_ailogger(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure an Ai-Logger, which serves the whole site over Modbus TCP."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_MODE: MODE_AILOGGER,
                CONF_CONNECTION_TYPE: CONNECTION_TYPE_NETWORK,
                CONF_FRAMER: DEFAULT_LOGGER_FRAMER,
                **user_input,
                CONF_PORT: int(user_input[CONF_PORT]),
                CONF_UNIT_ID: int(user_input[CONF_UNIT_ID]),
            }
            # The logger's map carries no identity of its own, so a second entry
            # for the same address is caught by address rather than by serial.
            self._async_abort_entries_match(
                {CONF_HOST: data[CONF_HOST], CONF_PORT: data[CONF_PORT]}
            )
            try:
                inverters = await self._async_discover(data)
            except ModbusError:
                errors["base"] = "cannot_connect"
            else:
                if not inverters:
                    errors["base"] = "no_inverters"
                else:
                    data[CONF_INVERTERS] = inverters
                    return self.async_create_entry(
                        title=f"Ai-Logger ({data[CONF_HOST]})", data=data
                    )

        return self.async_show_form(
            step_id=STEP_AILOGGER,
            data_schema=self.add_suggested_values_to_schema(
                STEP_AILOGGER_SCHEMA, user_input
            ),
            errors=errors,
        )

    async def async_step_inverter_network(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure one inverter behind an RS-485 to network gateway."""
        return await self._async_step_inverter(
            STEP_INVERTER_NETWORK,
            CONNECTION_TYPE_NETWORK,
            STEP_INVERTER_NETWORK_SCHEMA,
            user_input,
        )

    async def async_step_inverter_serial(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure one inverter on a directly attached RS-485 line."""
        return await self._async_step_inverter(
            STEP_INVERTER_SERIAL,
            CONNECTION_TYPE_SERIAL,
            STEP_INVERTER_SERIAL_SCHEMA,
            user_input,
        )

    async def _async_step_inverter(
        self,
        step_id: str,
        connection_type: str,
        schema: vol.Schema,
        user_input: dict[str, Any] | None,
    ) -> ConfigFlowResult:
        """Validate a single inverter by reading its identity block."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_MODE: MODE_INVERTER,
                CONF_CONNECTION_TYPE: connection_type,
                **user_input,
                CONF_UNIT_ID: int(user_input[CONF_UNIT_ID]),
            }
            if CONF_PORT in data:
                data[CONF_PORT] = int(data[CONF_PORT])
            if CONF_BAUDRATE in data:
                data[CONF_BAUDRATE] = int(data[CONF_BAUDRATE])
            try:
                serial_number, title = await self._async_probe_inverter(data)
            except ModbusError:
                errors["base"] = "cannot_connect"
            else:
                if serial_number:
                    await self.async_set_unique_id(serial_number)
                    self._abort_if_unique_id_configured()
                return self.async_create_entry(title=title, data=data)

        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )

    async def _async_discover(self, data: dict[str, Any]) -> list[int]:
        """Return the RS-485 addresses of the inverters the logger is scanning.

        Raises ``ModbusError`` when the logger cannot be reached.
        """
        connection = connection_module.build_connection(data)
        try:
            unit = connection.for_unit(data[CONF_UNIT_ID])
            slots = [
                slot
                for value in data[CONF_SCAN_PORTS]
                for slot in slots_for_port(ComPort(int(value)))
            ]
            found = await AiLogger.async_discover(unit, slots)
            return [inverter.modbus_id for inverter in found]
        finally:
            await connection.close()

    async def _async_probe_inverter(
        self, data: dict[str, Any]
    ) -> tuple[str | None, str]:
        """Read one inverter's identity; return (serial number, title).

        Raises ``ModbusError`` when the inverter cannot be reached.
        """
        connection = connection_module.build_connection(data)
        try:
            inverter = Inverter(connection.for_unit(data[CONF_UNIT_ID]))
            await inverter.async_update_info()
            info = inverter.info
            title = info.machine_type or f"Solplanet inverter {data[CONF_UNIT_ID]}"
            return info.serial_number, title
        finally:
            await connection.close()
