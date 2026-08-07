"""Fixtures: the integration over modbus-connection's in-memory mock.

``build_connection`` is the one seam between the integration and a real
transport; patching it to hand back a ``MockModbusConnection`` preloaded with
Ai-Logger-shaped registers runs the whole stack — config flow, setup,
coordinator, entities — against the mock, with no sockets and no hardware.

The site modelled here is two three-phase inverters, one each on COM1 and COM2,
plus a weather station and an SDM630 meter.
"""

from __future__ import annotations

import struct
import sys
from collections.abc import Generator
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from modbus_connection.mock import MockModbusConnection
from pytest_homeassistant_custom_component.common import MockConfigEntry

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from custom_components.solplanet_modbus.const import (  # noqa: E402
    CONF_CONNECTION_TYPE,
    CONF_FRAMER,
    CONF_INVERTERS,
    CONF_METER,
    CONF_MODE,
    CONF_UNIT_ID,
    CONF_WEATHER,
    CONNECTION_TYPE_NETWORK,
    DOMAIN,
    MODE_AILOGGER,
)
from custom_components.solplanet_modbus.vendor.solplanet_modbus import (  # noqa: E402
    AILOGGER_UNIT_ID,
    slot_for,
)

INVERTER_IDS = [3, 51]


def _string(text: str, length: int) -> dict[int, int]:
    """Encode ``text`` as ``length`` null-padded big-endian register words."""
    raw = text.encode("ascii").ljust(length * 2, b"\x00")
    return {i: (raw[i * 2] << 8) | raw[i * 2 + 1] for i in range(length)}


def _float(value: float) -> tuple[int, int]:
    """Encode ``value`` as an SDM630 big-endian IEEE-754 register pair."""
    high, low = struct.unpack(">HH", struct.pack(">f", value))
    return high, low


def inverter_registers(modbus_id: int, serial: str, today: int) -> dict[int, int]:
    """One inverter window's registers, keyed by absolute address."""
    offsets: dict[int, int] = {
        1000: 0x0033,  # device type, ASCII '3' -> three phase
        1001: modbus_id,
        1026: 14,  # grid code
        1027: 0,  # rated power -> 20000 W
        1028: 20000,
        1072: 3,  # model -> PV_THREE_PHASE_3_10KW
        1073: 2,  # MPPT count -> two PV entities per inverter
        1074: 2,  # string current count -> two string entities
        1300: 2300,
        1301: 5000,
        1302: 0,  # E-today
        1303: today,
        1304: 1,  # E-total -> 7000.0 kWh
        1305: 4464,
        1306: 0,  # H-total -> 8760 h
        1307: 8760,
        1308: 1,  # state -> NORMAL
        1309: 342,
        1310: 415,  # internal temperature -> 41.5 °C
        1311: 380,
        1312: 385,
        1313: 390,
        1314: 402,
        1315: 0x8000,  # no DC/DC converter -> unimplemented sentinel
        1316: 6500,
        1318: 3450,  # PV1 -> 345.0 V
        1319: 512,  # PV1 -> 5.12 A
        1320: 3380,  # PV2 -> 338.0 V
        1321: 498,
        1338: 256,  # string 1 -> 25.6 A
        1339: 261,
        1358: 2312,  # L1 -> 231.2 V
        1359: 78,
        1360: 2298,
        1361: 76,
        1362: 2305,
        1363: 77,
        1364: 3998,
        1365: 4001,
        1366: 3995,
        1367: 5001,  # grid frequency -> 50.01 Hz
        1368: 0,  # apparent power -> 5400 VA
        1369: 5400,
        1370: 0,  # active power -> 5389 W
        1371: 5389,
        1372: 0xFFFF,  # reactive power -> -120 var
        1373: 0x10000 - 120,
        1374: 99,
        1376: 0,  # no internal fault
        1377: 35,  # error code -> "Utility loss"
        1378: 0,
        1388: 7,
    }
    offsets |= {1002 + i: w for i, w in _string(serial, 16).items()}
    offsets |= {1018 + i: w for i, w in _string("ASW8000", 8).items()}
    offsets |= {1029 + i: w for i, w in _string("V1.0.5", 7).items()}
    offsets |= {1056 + i: w for i, w in _string("AISWEI", 8).items()}
    offsets |= {1064 + i: w for i, w in _string("Solplanet", 8).items()}
    base = slot_for(modbus_id).base_offset
    return {base + address: value for address, value in offsets.items()}


WEATHER: dict[int, int] = {
    986: 42,
    987: 8123,  # irradiance -> 812.3 W/m²
    988: 315,  # cell temperature -> 31.5 °C
    989: 224,
    990: 0xFFFF - 54,
    991: 47,
    992: 178,
    993: 38,
    994: 8090,
    995: 250,
}

SYSTEM: dict[int, int] = {
    36100: 0,
    36101: 10778,  # site active power -> 10778 W
    36102: 0xFFFF,
    36103: 0x10000 - 240,
}

_METER_VALUES: dict[int, float] = {
    36104: 238.7,
    36106: 239.1,
    36108: 237.9,
    36110: 6.05,
    36112: 6.11,
    36114: 5.98,
    36116: -1444.5,
    36118: -1460.9,
    36120: -1422.6,
    36156: -4328.0,
    36160: 4328.3,
    36164: 37.3,
    36166: 0.99,
    36174: 50.01,
    36176: 1234.5,
    36178: 8765.4,
}

INPUT: dict[int, int] = {
    **inverter_registers(3, "QA10010022920081", 1234),
    **inverter_registers(51, "QA10010022920082", 987),
    **WEATHER,
    **SYSTEM,
    **{
        address + offset: word
        for address, value in _METER_VALUES.items()
        for offset, word in enumerate(_float(value))
    },
}

ENTRY_DATA = {
    CONF_MODE: MODE_AILOGGER,
    CONF_CONNECTION_TYPE: CONNECTION_TYPE_NETWORK,
    CONF_HOST: "192.168.1.50",
    CONF_PORT: 9999,
    CONF_FRAMER: "socket",
    CONF_UNIT_ID: AILOGGER_UNIT_ID,
    CONF_INVERTERS: INVERTER_IDS,
    CONF_WEATHER: True,
    CONF_METER: True,
}


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Allow loading the custom integration."""


class ConnectionFactory:
    """Build a fresh preloaded mock per ``build_connection`` call.

    ``close()`` is permanent on a connection — the config flow probes and
    closes, then entry setup builds its own — so each call needs its own mock,
    exactly as each call builds its own real connection.
    """

    def __init__(self, registers: dict[int, int] | None = None) -> None:
        """Start with no connections built."""
        self.connections: list[MockModbusConnection] = []
        self.registers = INPUT if registers is None else registers

    def __call__(self, data: object) -> MockModbusConnection:
        """Return a new mock connection with Ai-Logger-shaped registers."""
        connection = MockModbusConnection()
        for unit_id in (AILOGGER_UNIT_ID, *INVERTER_IDS):
            connection.for_unit(unit_id).input.update(self.registers)
        self.connections.append(connection)
        return connection

    @property
    def unit(self):  # noqa: ANN201 - MockModbusUnit
        """The logger unit of the most recently built connection."""
        return self.connections[-1].for_unit(AILOGGER_UNIT_ID)


@pytest.fixture
def mock_connection() -> Generator[ConnectionFactory]:
    """Patch the connection seam to Ai-Logger-shaped in-memory mocks."""
    factory = ConnectionFactory()
    with patch(
        "custom_components.solplanet_modbus.connection.build_connection",
        side_effect=factory,
    ):
        yield factory


@pytest.fixture
async def config_entry(
    hass: HomeAssistant, mock_connection: ConnectionFactory
) -> MockConfigEntry:
    """A set-up Ai-Logger config entry over the mock connection."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Ai-Logger (192.168.1.50)", data=ENTRY_DATA
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
