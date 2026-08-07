"""Sensors: inverter production and diagnostics, site totals, weather, meter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    DEGREE,
    PERCENTAGE,
    EntityCategory,
    UnitOfApparentPower,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfFrequency,
    UnitOfIrradiance,
    UnitOfPower,
    UnitOfReactivePower,
    UnitOfSpeed,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.typing import StateType

from .coordinator import SolplanetConfigEntry, SolplanetCoordinator
from .entity import SolplanetInverterEntity, SolplanetSiteEntity
from .vendor.solplanet_modbus import DeviceState, Inverter, PhaseType

# -- description types -------------------------------------------------------


@dataclass(frozen=True, kw_only=True)
class InverterSensorDescription(SensorEntityDescription):
    """Describes a sensor read off one inverter."""

    value_fn: Callable[[Inverter], StateType]


@dataclass(frozen=True, kw_only=True)
class ComponentSensorDescription(SensorEntityDescription):
    """Describes a sensor read off one of the logger's own components."""

    value_fn: Callable[[Any], StateType]


# -- shorthands --------------------------------------------------------------


def _energy(
    key: str, value_fn: Callable[[Inverter], StateType]
) -> InverterSensorDescription:
    """A lifetime or daily kWh counter."""
    return InverterSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=value_fn,
    )


def _temperature(
    key: str, value_fn: Callable[[Inverter], StateType]
) -> InverterSensorDescription:
    """A diagnostic °C temperature."""
    return InverterSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=value_fn,
    )


def _voltage(
    key: str, value_fn: Callable[[Inverter], StateType], *, diagnostic: bool = False
) -> InverterSensorDescription:
    """An AC or DC volt reading."""
    return InverterSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC if diagnostic else None,
        value_fn=value_fn,
    )


def _current(
    key: str, value_fn: Callable[[Inverter], StateType]
) -> InverterSensorDescription:
    """An amp reading."""
    return InverterSensorDescription(
        key=key,
        translation_key=key,
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
        value_fn=value_fn,
    )


# -- inverter sensors --------------------------------------------------------

INVERTER_SENSORS: tuple[InverterSensorDescription, ...] = (
    InverterSensorDescription(
        key="state",
        translation_key="state",
        device_class=SensorDeviceClass.ENUM,
        options=[state.name.lower() for state in DeviceState],
        value_fn=lambda i: (
            state.name.lower() if (state := i.data.state) is not None else None
        ),
    ),
    InverterSensorDescription(
        key="active_power",
        translation_key="active_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda i: i.data.active_power,
    ),
    _energy("energy_today", lambda i: i.data.energy_today),
    _energy("energy_total", lambda i: i.data.energy_total),
    InverterSensorDescription(
        key="apparent_power",
        translation_key="apparent_power",
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        entity_registry_enabled_default=False,
        value_fn=lambda i: i.data.apparent_power,
    ),
    InverterSensorDescription(
        key="reactive_power",
        translation_key="reactive_power",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        entity_registry_enabled_default=False,
        value_fn=lambda i: i.data.reactive_power,
    ),
    InverterSensorDescription(
        key="power_factor",
        translation_key="power_factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda i: i.data.power_factor,
    ),
    InverterSensorDescription(
        key="grid_frequency",
        translation_key="grid_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        suggested_display_precision=2,
        value_fn=lambda i: i.data.grid_frequency,
    ),
    InverterSensorDescription(
        key="hours_total",
        translation_key="hours_total",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfTime.HOURS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda i: i.data.hours_total,
    ),
    InverterSensorDescription(
        key="connect_time",
        translation_key="connect_time",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda i: i.data.connect_time,
    ),
    # The code table UM0058 points at is missing from the manual, so the raw
    # code and its reconstructed label are both exposed — see the library.
    InverterSensorDescription(
        key="error_code",
        translation_key="error_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda i: i.data.error_code,
    ),
    InverterSensorDescription(
        key="error_description",
        translation_key="error_description",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda i: i.data.error_description,
    ),
    InverterSensorDescription(
        key="warning_code",
        translation_key="warning_code",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda i: i.data.warning_code,
    ),
    _temperature("internal_temperature", lambda i: i.data.internal_temperature),
    _temperature("boost_temperature", lambda i: i.data.boost_temperature),
    _temperature("phase_u_temperature", lambda i: i.data.phase_u_temperature),
    _temperature("phase_v_temperature", lambda i: i.data.phase_v_temperature),
    _temperature("phase_w_temperature", lambda i: i.data.phase_w_temperature),
    _temperature("dc_converter_temperature", lambda i: i.data.dc_converter_temperature),
    _voltage("bus_voltage", lambda i: i.data.bus_voltage, diagnostic=True),
)

# Created only for a three-phase inverter; a single-phase one reports zero or
# the unimplemented sentinel for all of these.
THREE_PHASE_SENSORS: tuple[InverterSensorDescription, ...] = (
    _voltage("l2_voltage", lambda i: i.data.l2_voltage),
    _current("l2_current", lambda i: i.data.l2_current),
    _voltage("l3_voltage", lambda i: i.data.l3_voltage),
    _current("l3_current", lambda i: i.data.l3_current),
    _voltage("rs_line_voltage", lambda i: i.data.rs_line_voltage, diagnostic=True),
    _voltage("rt_line_voltage", lambda i: i.data.rt_line_voltage, diagnostic=True),
    _voltage("st_line_voltage", lambda i: i.data.st_line_voltage, diagnostic=True),
)

SINGLE_PHASE_SENSORS: tuple[InverterSensorDescription, ...] = (
    _voltage("l1_voltage", lambda i: i.data.l1_voltage),
    _current("l1_current", lambda i: i.data.l1_current),
)


def _pv_sensors(index: int) -> tuple[InverterSensorDescription, ...]:
    """Voltage and current of PV input ``index`` (1-based)."""
    return (
        InverterSensorDescription(
            key=f"pv{index}_voltage",
            translation_key="pv_voltage",
            translation_placeholders={"number": str(index)},
            device_class=SensorDeviceClass.VOLTAGE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricPotential.VOLT,
            suggested_display_precision=1,
            value_fn=lambda i, n=index - 1: i.data.pv_inputs[n].voltage,
        ),
        InverterSensorDescription(
            key=f"pv{index}_current",
            translation_key="pv_current",
            translation_placeholders={"number": str(index)},
            device_class=SensorDeviceClass.CURRENT,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
            suggested_display_precision=2,
            value_fn=lambda i, n=index - 1: i.data.pv_inputs[n].current,
        ),
    )


def _string_sensor(index: int) -> InverterSensorDescription:
    """Current of monitored string ``index`` (1-based)."""
    return InverterSensorDescription(
        key=f"string{index}_current",
        translation_key="string_current",
        translation_placeholders={"number": str(index)},
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda i, n=index - 1: i.data.strings[n].current,
    )


# -- site, weather and meter sensors -----------------------------------------

SITE_SENSORS: tuple[ComponentSensorDescription, ...] = (
    ComponentSensorDescription(
        key="site_active_power",
        translation_key="site_active_power",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        value_fn=lambda c: c.active_power,
    ),
    ComponentSensorDescription(
        key="site_reactive_power",
        translation_key="site_reactive_power",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.reactive_power,
    ),
)

WEATHER_SENSORS: tuple[ComponentSensorDescription, ...] = (
    ComponentSensorDescription(
        key="irradiance",
        translation_key="irradiance",
        device_class=SensorDeviceClass.IRRADIANCE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfIrradiance.WATTS_PER_SQUARE_METER,
        suggested_display_precision=1,
        value_fn=lambda c: c.irradiance,
    ),
    ComponentSensorDescription(
        key="cell_temperature",
        translation_key="cell_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda c: c.cell_temperature,
    ),
    ComponentSensorDescription(
        key="external_temperature_1",
        translation_key="external_temperature_1",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        value_fn=lambda c: c.external_temperature_1,
    ),
    ComponentSensorDescription(
        key="external_temperature_2",
        translation_key="external_temperature_2",
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.external_temperature_2,
    ),
    ComponentSensorDescription(
        key="humidity",
        translation_key="humidity",
        device_class=SensorDeviceClass.HUMIDITY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        value_fn=lambda c: c.humidity,
    ),
    ComponentSensorDescription(
        key="wind_direction",
        translation_key="wind_direction",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=DEGREE,
        value_fn=lambda c: c.wind_direction,
    ),
    # UM0058 gives this no gain but bounds it at 6000, which only makes sense at
    # a 0.01 scale. Exposed raw, as the document describes it — see the README.
    ComponentSensorDescription(
        key="wind_speed_raw",
        translation_key="wind_speed_raw",
        device_class=SensorDeviceClass.WIND_SPEED,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfSpeed.METERS_PER_SECOND,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: c.wind_speed_raw,
    ),
)


def _meter_power(key: str, attribute: str) -> ComponentSensorDescription:
    """A watt reading from the SDM630."""
    return ComponentSensorDescription(
        key=f"meter_{key}",
        translation_key=f"meter_{key}",
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.WATT,
        suggested_display_precision=1,
        value_fn=lambda c, a=attribute: getattr(c, a),
    )


def _meter_energy(key: str, attribute: str) -> ComponentSensorDescription:
    """A kWh counter from the SDM630."""
    return ComponentSensorDescription(
        key=f"meter_{key}",
        translation_key=f"meter_{key}",
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        suggested_display_precision=1,
        value_fn=lambda c, a=attribute: getattr(c, a),
    )


def _meter_voltage(key: str, attribute: str) -> ComponentSensorDescription:
    """A volt reading from the SDM630."""
    return ComponentSensorDescription(
        key=f"meter_{key}",
        translation_key=f"meter_{key}",
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        suggested_display_precision=1,
        entity_registry_enabled_default=False,
        value_fn=lambda c, a=attribute: getattr(c, a),
    )


def _meter_current(key: str, attribute: str) -> ComponentSensorDescription:
    """An amp reading from the SDM630."""
    return ComponentSensorDescription(
        key=f"meter_{key}",
        translation_key=f"meter_{key}",
        device_class=SensorDeviceClass.CURRENT,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfElectricCurrent.AMPERE,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda c, a=attribute: getattr(c, a),
    )


METER_SENSORS: tuple[ComponentSensorDescription, ...] = (
    _meter_power("total_power", "total_power"),
    _meter_energy("import_energy", "import_energy"),
    _meter_energy("export_energy", "export_energy"),
    ComponentSensorDescription(
        key="meter_frequency",
        translation_key="meter_frequency",
        device_class=SensorDeviceClass.FREQUENCY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfFrequency.HERTZ,
        suggested_display_precision=2,
        value_fn=lambda c: c.frequency,
    ),
    ComponentSensorDescription(
        key="meter_total_power_factor",
        translation_key="meter_total_power_factor",
        device_class=SensorDeviceClass.POWER_FACTOR,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.total_power_factor,
    ),
    ComponentSensorDescription(
        key="meter_total_apparent_power",
        translation_key="meter_total_apparent_power",
        device_class=SensorDeviceClass.APPARENT_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfApparentPower.VOLT_AMPERE,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.total_apparent_power,
    ),
    ComponentSensorDescription(
        key="meter_total_reactive_power",
        translation_key="meter_total_reactive_power",
        device_class=SensorDeviceClass.REACTIVE_POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfReactivePower.VOLT_AMPERE_REACTIVE,
        entity_registry_enabled_default=False,
        value_fn=lambda c: c.total_reactive_power,
    ),
    _meter_power("l1_power", "l1_power"),
    _meter_power("l2_power", "l2_power"),
    _meter_power("l3_power", "l3_power"),
    _meter_voltage("l1_voltage", "l1_voltage"),
    _meter_voltage("l2_voltage", "l2_voltage"),
    _meter_voltage("l3_voltage", "l3_voltage"),
    _meter_current("l1_current", "l1_current"),
    _meter_current("l2_current", "l2_current"),
    _meter_current("l3_current", "l3_current"),
)


# -- entities ----------------------------------------------------------------


class SolplanetInverterSensor(SolplanetInverterEntity, SensorEntity):
    """A sensor reading off one inverter."""

    entity_description: InverterSensorDescription

    def __init__(
        self,
        coordinator: SolplanetCoordinator,
        inverter: Inverter,
        description: InverterSensorDescription,
    ) -> None:
        """Initialize from the description."""
        super().__init__(coordinator, inverter, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> StateType:
        """The decoded register value behind this sensor."""
        return self.entity_description.value_fn(self.inverter)


class SolplanetComponentSensor(SolplanetSiteEntity, SensorEntity):
    """A sensor reading off one of the logger's own components."""

    entity_description: ComponentSensorDescription

    def __init__(
        self,
        coordinator: SolplanetCoordinator,
        component: Any,
        description: ComponentSensorDescription,
        *,
        key_suffix: str = "",
        placeholders: dict[str, str] | None = None,
    ) -> None:
        """Initialize from the description and the component it reads."""
        super().__init__(coordinator, f"{description.key}{key_suffix}")
        self._component = component
        self.entity_description = description
        if placeholders is not None:
            self._attr_translation_placeholders = placeholders

    @property
    def native_value(self) -> StateType:
        """The decoded register value behind this sensor."""
        return self.entity_description.value_fn(self._component)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolplanetConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors the site actually has."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = []

    for inverter in coordinator.inverters:
        descriptions = [*INVERTER_SENSORS, *SINGLE_PHASE_SENSORS]
        if inverter.info.phase_type is PhaseType.THREE_PHASE:
            descriptions += THREE_PHASE_SENSORS
        # The identity block says how much of the reserved space is real: an
        # inverter with two trackers has no PV3-PV10 to report.
        for index in range(1, (inverter.info.mppt_count or 0) + 1):
            descriptions += _pv_sensors(index)
        for index in range(1, (inverter.info.string_current_count or 0) + 1):
            descriptions.append(_string_sensor(index))
        entities += [
            SolplanetInverterSensor(coordinator, inverter, description)
            for description in descriptions
        ]

    if coordinator.site is not None:
        entities += [
            SolplanetComponentSensor(coordinator, coordinator.site, description)
            for description in SITE_SENSORS
        ]

    if coordinator.weather is not None:
        for number, sensor in enumerate(coordinator.weather.sensors, start=1):
            entities += [
                SolplanetComponentSensor(
                    coordinator,
                    sensor,
                    description,
                    key_suffix=f"_{number}",
                    placeholders={"number": str(number)},
                )
                for description in WEATHER_SENSORS
            ]

    if coordinator.meter is not None:
        entities += [
            SolplanetComponentSensor(coordinator, coordinator.meter, description)
            for description in METER_SENSORS
        ]

    async_add_entities(entities)
