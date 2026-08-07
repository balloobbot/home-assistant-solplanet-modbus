"""Entity tests: what each platform exposes, and what the writes send."""

from __future__ import annotations

import pytest
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solplanet_modbus.const import (
    CONF_CONNECTION_TYPE,
    CONF_MODE,
    CONF_SERIAL_DEVICE,
    CONF_UNIT_ID,
    CONNECTION_TYPE_SERIAL,
    DOMAIN,
    MODE_INVERTER,
)

from .conftest import ConnectionFactory


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.asw8000_3_active_power", "5389"),
        ("sensor.asw8000_3_energy_today", "123.4"),
        ("sensor.asw8000_3_energy_total", "7000.0"),
        ("sensor.asw8000_3_grid_frequency", "50.01"),
        ("sensor.asw8000_3_status", "normal"),
        ("sensor.asw8000_3_l1_voltage", "231.2"),
        ("sensor.asw8000_3_l3_voltage", "230.5"),
        ("sensor.asw8000_3_pv_1_voltage", "345.0"),
        ("sensor.asw8000_3_pv_2_voltage", "338.0"),
        ("sensor.asw8000_3_internal_temperature", "41.5"),
        ("sensor.asw8000_3_error_code", "35"),
        ("sensor.asw8000_3_error", "Utility loss"),
        ("sensor.asw8000_51_energy_today", "98.7"),
        ("binary_sensor.asw8000_3_fault", "off"),
    ],
)
async def test_inverter_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, entity_id: str, expected: str
) -> None:
    assert hass.states.get(entity_id).state == expected


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.ai_logger_192_168_1_50_site_active_power", "10778"),
        ("sensor.ai_logger_192_168_1_50_weather_1_irradiance", "812.3"),
        ("sensor.ai_logger_192_168_1_50_weather_1_cell_temperature", "31.5"),
        ("sensor.ai_logger_192_168_1_50_weather_2_cell_temperature", "25.0"),
        ("sensor.ai_logger_192_168_1_50_meter_power", "-4328.0"),
        ("sensor.ai_logger_192_168_1_50_meter_imported_energy", "1234.5"),
    ],
)
async def test_site_entities(
    hass: HomeAssistant, config_entry: MockConfigEntry, entity_id: str, expected: str
) -> None:
    assert hass.states.get(entity_id).state == expected


async def test_meter_values_keep_their_float32_precision(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The SDM630 sends IEEE-754 singles, so 50.01 Hz is not exactly 50.01.

    The state keeps what the meter sent; ``suggested_display_precision`` is what
    rounds it for the UI.
    """
    state = hass.states.get("sensor.ai_logger_192_168_1_50_meter_frequency")
    assert float(state.state) == pytest.approx(50.01, abs=1e-4)


async def test_an_unimplemented_register_reads_unknown(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A PV inverter has no DC/DC converter, so its temperature is not a value."""
    entity_id = "sensor.asw8000_3_dc_dc_converter_temperature"
    assert hass.states.get(entity_id).state == STATE_UNKNOWN


async def test_only_the_reported_pv_inputs_and_strings_exist(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """The identity block bounds the entities: two trackers, not the reserved ten."""
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, config_entry.entry_id)
    keys = {entry.unique_id.split("_", 1)[1] for entry in entries}

    assert "pv1_voltage" in keys
    assert "pv2_current" in keys
    assert "pv3_voltage" not in keys  # mppt_count is 2
    assert "string1_current" in keys
    assert "string2_current" in keys
    assert "string3_current" not in keys  # string_current_count is 2


async def test_a_three_phase_inverter_gets_its_line_voltages(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    assert hass.states.get("sensor.asw8000_3_rs_line_voltage").state == "399.8"
    assert hass.states.get("sensor.asw8000_3_l2_current").state == "7.6"


async def test_the_power_limit_number_writes_and_remembers(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: ConnectionFactory,
) -> None:
    """Write-only, so the shown value is what was last sent, not a reading."""
    entity_id = "number.ai_logger_192_168_1_50_active_power_limit"
    assert hass.states.get(entity_id).state == STATE_UNKNOWN

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: entity_id, "value": 80},
        blocking=True,
    )

    assert mock_connection.unit.holding[60003] == 8000  # 80 % at a 0.01 gain
    assert hass.states.get(entity_id).state == "80.0"


async def test_the_power_switch_writes_the_documented_codes(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: ConnectionFactory,
) -> None:
    entity_id = "switch.ai_logger_192_168_1_50_inverters"
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        "switch", "turn_off", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert mock_connection.unit.holding[60002] == 2  # 2 = turn off

    await hass.services.async_call(
        "switch", "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=True
    )
    assert mock_connection.unit.holding[60002] == 1  # 1 = turn on
    assert hass.states.get(entity_id).state == "on"


async def test_a_power_factor_in_the_unusable_band_is_refused(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    mock_connection: ConnectionFactory,
) -> None:
    """Only 0.75..1 leading and -1..-0.75 lagging mean anything to an inverter."""
    entity_id = "number.ai_logger_192_168_1_50_power_factor_command"
    registry = er.async_get(hass)
    registry.async_update_entity(entity_id, disabled_by=None)
    await hass.config_entries.async_reload(config_entry.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(HomeAssistantError, match="excluded range"):
        await hass.services.async_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: entity_id, "value": 0.3},
            blocking=True,
        )
    assert 60001 not in mock_connection.unit.holding

    await hass.services.async_call(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: entity_id, "value": 0.95},
        blocking=True,
    )
    assert mock_connection.unit.holding[60001] == 9500


async def test_a_single_inverter_entry_has_no_control_entities(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> None:
    """The control registers are the logger's map; a bare inverter has none."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="ASW8000",
        data={
            CONF_MODE: MODE_INVERTER,
            CONF_CONNECTION_TYPE: CONNECTION_TYPE_SERIAL,
            CONF_SERIAL_DEVICE: "/dev/ttyUSB0",
            CONF_UNIT_ID: 3,
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    domains = {registry_entry.domain for registry_entry in entries}
    assert domains == {"sensor", "binary_sensor"}
    # ...and nothing site-wide either: no totals, weather or meter.
    assert not [e for e in entries if "site" in e.unique_id or "meter" in e.unique_id]
