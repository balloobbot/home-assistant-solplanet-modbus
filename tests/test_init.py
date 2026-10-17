"""Setup, unload, device registry and coordinator failure handling."""

from __future__ import annotations

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from modbus_connection import ModbusConnectionError
from modbus_connection.mock import MockModbusConnection
from pytest_homeassistant.common import MockConfigEntry

from custom_components.solplanet_modbus.const import (
    CONF_CONNECTION_TYPE,
    CONF_MODE,
    CONF_UNIT_ID,
    CONNECTION_TYPE_SERIAL,
    DOMAIN,
    FAILURES_BEFORE_RECONNECT,
    MODE_INVERTER,
)
from custom_components.solplanet_modbus.diagnostics import (
    async_get_config_entry_diagnostics,
)

from .conftest import ENTRY_DATA, INPUT, ConnectionFactory


async def test_setup_and_unload(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    assert config_entry.state is ConfigEntryState.LOADED
    assert await hass.config_entries.async_unload(config_entry.entry_id)
    await hass.async_block_till_done()
    assert config_entry.state is ConfigEntryState.NOT_LOADED


async def test_setup_retries_when_the_logger_is_unreachable(
    hass: HomeAssistant,
) -> None:
    """A logger that rejects the identity read is not ready, not broken."""

    def failing(data: object) -> MockModbusConnection:
        connection = MockModbusConnection()
        connection.for_unit(ENTRY_DATA[CONF_UNIT_ID]).fail_requests(
            ModbusConnectionError("device is offline")
        )
        return connection

    entry = MockConfigEntry(domain=DOMAIN, title="Ai-Logger", data=ENTRY_DATA)
    entry.add_to_hass(hass)
    with patch(
        "custom_components.solplanet_modbus.connection.build_connection",
        side_effect=failing,
    ):
        assert not await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_each_inverter_becomes_its_own_device(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """Inverters are separate devices hanging off the logger's."""
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, config_entry.entry_id)
    by_name = {device.name: device for device in devices}

    assert set(by_name) == {"Ai-Logger (192.168.1.50)", "ASW8000 3", "ASW8000 51"}

    inverter = by_name["ASW8000 3"]
    assert inverter.serial_number == "QA10010022920081"
    assert inverter.model == "ASW8000"
    assert inverter.manufacturer == "Solplanet"  # the brand register
    assert inverter.sw_version == "V1.0.5"
    # Identified by serial, so the device survives a re-scan onto another slot.
    assert inverter.identifiers == {(DOMAIN, "QA10010022920081")}

    site = by_name["Ai-Logger (192.168.1.50)"]
    assert inverter.via_device_id == site.id


async def test_a_failed_poll_makes_entities_unavailable(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: ConnectionFactory,
) -> None:
    """The link dropping is not a reload — the entry stays loaded."""
    mock_connection.unit.fail_requests(ModbusConnectionError("device is offline"))
    coordinator = config_entry.runtime_data
    await coordinator.async_refresh()
    await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.LOADED
    assert not coordinator.last_update_success
    assert hass.states.get("sensor.asw8000_3_active_power").state == "unavailable"


async def test_a_single_inverter_entry_has_no_site_devices(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> None:
    """A bare inverter has no logger, so no site totals, meter or controls."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ASW8000",
        data={
            CONF_MODE: MODE_INVERTER,
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_SERIAL,
            "serial_device": "/dev/ttyUSB0",
            "baudrate": 9600,
            "parity": "n",
            CONF_UNIT_ID: 3,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data
    assert coordinator.ailogger is None
    assert coordinator.site is None
    assert coordinator.meter is None
    assert coordinator.controls is None
    assert len(coordinator.inverters) == 1
    # Reached directly, so its window is unshifted and it has no slot.
    assert coordinator.inverters[0].slot is None
    assert hass.states.get("sensor.asw8000_active_power").state == "5389"


async def test_the_diagnostics_dump_replays_into_the_mock(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The raw dump round-trips through the mock backend it came from."""
    diagnostics = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diagnostics["has_meter"] is True
    assert diagnostics["has_weather"] is True
    assert [entry["modbus_id"] for entry in diagnostics["inverters"]] == [3, 51]
    assert diagnostics["registers"]["input"][36101] == INPUT[36101]

    replayed = MockModbusConnection()
    replayed.for_unit(1).load_raw(diagnostics["registers"])
    assert replayed.for_unit(1).input[36101] == INPUT[36101]


async def test_a_run_of_failed_polls_recycles_the_link(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: ConnectionFactory,
) -> None:
    """A logger taken over by another client leaves the socket open but mute."""
    connection = mock_connection.connections[-1]
    coordinator = config_entry.runtime_data
    mock_connection.unit.fail_requests(ModbusConnectionError("device is offline"))

    for _ in range(FAILURES_BEFORE_RECONNECT - 1):
        await coordinator.async_refresh()
    assert connection.connected  # not yet: most failures heal on their own

    await coordinator.async_refresh()
    assert not connection.connected  # torn down, ready to be rebuilt

    # close() would be permanent; disconnect() leaves the connection usable, so
    # the next successful poll brings everything back without an entry reload.
    mock_connection.unit.fail_requests(None)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert hass.states.get("sensor.asw8000_3_active_power").state == "5389"


async def test_an_isolated_failure_does_not_recycle_the_link(
    config_entry: MockConfigEntry, mock_connection: ConnectionFactory
) -> None:
    """One bad poll among good ones is not a stuck link."""
    connection = mock_connection.connections[-1]
    coordinator = config_entry.runtime_data

    for _ in range(FAILURES_BEFORE_RECONNECT * 2):
        mock_connection.unit.fail_requests(ModbusConnectionError("blip"))
        await coordinator.async_refresh()
        mock_connection.unit.fail_requests(None)
        await coordinator.async_refresh()

    assert connection.connected
    assert coordinator.last_update_success
