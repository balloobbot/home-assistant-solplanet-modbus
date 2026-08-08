"""Config-flow tests: the menu, discovery, probing, unique ids and failures."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusConnection
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solplanet_modbus.const import (
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
    DOMAIN,
    MODE_AILOGGER,
    MODE_INVERTER,
    STEP_AILOGGER,
    STEP_INVERTER_NETWORK,
    STEP_INVERTER_SERIAL,
)

from .conftest import ENTRY_DATA, ConnectionFactory

AILOGGER_INPUT = {
    CONF_HOST: "192.168.1.50",
    CONF_PORT: 9999,
    CONF_UNIT_ID: 239,
    CONF_SCAN_PORTS: ["1", "2"],
    CONF_WEATHER: True,
    CONF_METER: True,
}

SERIAL_INPUT = {
    CONF_SERIAL_DEVICE: "/dev/ttyUSB0",
    CONF_BAUDRATE: "9600",
    CONF_PARITY: "n",
    CONF_UNIT_ID: 3,
}


async def _menu(hass: HomeAssistant, option: str) -> dict:
    """Open the flow and pick a menu option."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert set(result["menu_options"]) == {
        STEP_AILOGGER,
        STEP_INVERTER_SERIAL,
        STEP_INVERTER_NETWORK,
    }
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": option}
    )
    assert result["type"] is FlowResultType.FORM
    return result


async def test_ailogger_flow_discovers_the_inverters(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> None:
    """Scanning COM1 and COM2 finds the two inverters the fixture populates."""
    result = await _menu(hass, STEP_AILOGGER)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], AILOGGER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Ai-Logger (192.168.1.50)"
    assert result["data"] == {
        CONF_MODE: MODE_AILOGGER,
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_NETWORK,
        CONF_FRAMER: "socket",
        **AILOGGER_INPUT,
        CONF_INVERTERS: [3, 51],
    }
    # The probe's connection was closed; setup then built its own.
    assert not mock_connection.connections[0].connected


async def test_ailogger_flow_scans_only_the_chosen_ports(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> None:
    """COM1 alone is 30 windows, and finds only the inverter wired to it."""
    result = await _menu(hass, STEP_AILOGGER)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**AILOGGER_INPUT, CONF_SCAN_PORTS: ["1"]}
    )
    await hass.async_block_till_done()

    assert result["data"][CONF_INVERTERS] == [3]
    assert len(mock_connection.connections[0].for_unit(239).read_events) == 30


async def test_ailogger_flow_reports_an_empty_scan(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> None:
    """COM3 has nothing wired to it, which is a mistake worth naming."""
    result = await _menu(hass, STEP_AILOGGER)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**AILOGGER_INPUT, CONF_SCAN_PORTS: ["3"]}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "no_inverters"}


def _unreachable(unit_id: int):
    """A connection whose requests all fail, as an unplugged device's would.

    ``build_connection`` itself never fails: it performs no I/O, so an
    unreachable device only shows up when the first block is read.
    """

    def build(data: object) -> MockModbusConnection:
        connection = MockModbusConnection()
        connection.for_unit(unit_id).fail_requests(
            ModbusConnectionError("no route to host")
        )
        return connection

    return build


async def test_ailogger_flow_reports_an_unreachable_logger(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.solplanet_modbus.connection.build_connection",
        side_effect=_unreachable(239),
    ):
        result = await _menu(hass, STEP_AILOGGER)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], AILOGGER_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_a_second_logger_at_the_same_address_is_rejected(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> None:
    """The logger's map carries no identity, so duplicates go by address."""
    MockConfigEntry(domain=DOMAIN, data=ENTRY_DATA).add_to_hass(hass)

    result = await _menu(hass, STEP_AILOGGER)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], AILOGGER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_serial_flow_probes_a_single_inverter(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> None:
    """A USB RS-485 adapter reads the inverter's own 1000-1389 block."""
    result = await _menu(hass, STEP_INVERTER_SERIAL)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], SERIAL_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "ASW8000"  # the probed machine type
    assert result["result"].unique_id == "QA10010022920081"  # the probed serial
    assert result["data"] == {
        CONF_MODE: MODE_INVERTER,
        CONF_CONNECTION_TYPE: CONNECTION_TYPE_SERIAL,
        **SERIAL_INPUT,
        CONF_BAUDRATE: 9600,  # coerced from the dropdown's string
    }


async def test_serial_flow_rejects_an_inverter_already_configured(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> None:
    """The serial number is the inverter's identity, whatever the transport."""
    MockConfigEntry(domain=DOMAIN, unique_id="QA10010022920081", data={}).add_to_hass(
        hass
    )

    result = await _menu(hass, STEP_INVERTER_SERIAL)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], SERIAL_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_inverter_network_flow_defaults_to_rtu_over_tcp(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> None:
    """A gateway bridging RS-485 to the network is a transparent serial link."""
    result = await _menu(hass, STEP_INVERTER_NETWORK)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.1.60",
            CONF_PORT: 502,
            CONF_FRAMER: "rtu",
            CONF_UNIT_ID: 3,
        },
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MODE] == MODE_INVERTER
    assert result["data"][CONF_CONNECTION_TYPE] == CONNECTION_TYPE_NETWORK
    assert result["data"][CONF_FRAMER] == "rtu"


async def test_inverter_flow_reports_an_unreachable_inverter(
    hass: HomeAssistant,
) -> None:
    with patch(
        "custom_components.solplanet_modbus.connection.build_connection",
        side_effect=_unreachable(3),
    ):
        result = await _menu(hass, STEP_INVERTER_SERIAL)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SERIAL_INPUT
        )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_an_inverter_without_a_serial_still_configures(
    hass: HomeAssistant,
) -> None:
    """No serial number means no unique id, not a failed setup."""

    def blank(data: object) -> MockModbusConnection:
        connection = MockModbusConnection()
        connection.for_unit(3).input.update({1001: 3})
        return connection

    with patch(
        "custom_components.solplanet_modbus.connection.build_connection",
        side_effect=blank,
    ):
        result = await _menu(hass, STEP_INVERTER_SERIAL)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], SERIAL_INPUT
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Solplanet inverter 3"
    assert result["result"].unique_id is None
