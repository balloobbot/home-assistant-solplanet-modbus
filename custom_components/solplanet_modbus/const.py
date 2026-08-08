"""Constants for the Solplanet Ai-Logger (Modbus) integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "solplanet_modbus"

CONF_CONNECTION_TYPE: Final = "connection_type"
CONF_MODE: Final = "mode"
CONF_FRAMER: Final = "framer"
CONF_SERIAL_DEVICE: Final = "serial_device"
CONF_BAUDRATE: Final = "baudrate"
CONF_PARITY: Final = "parity"
CONF_UNIT_ID: Final = "unit_id"
CONF_INVERTERS: Final = "inverters"
CONF_SCAN_PORTS: Final = "scan_ports"
CONF_WEATHER: Final = "weather"
CONF_METER: Final = "meter"

# How the connection is made.
CONNECTION_TYPE_NETWORK: Final = "network"
CONNECTION_TYPE_SERIAL: Final = "serial"

# What is on the other end. The logger aggregates a whole site into one map;
# a bare inverter serves only its own 1000-1389 block, which is the same layout.
MODE_AILOGGER: Final = "ailogger"
MODE_INVERTER: Final = "inverter"

# Menu steps, one per real deployment.
STEP_AILOGGER: Final = "ailogger"
STEP_INVERTER_NETWORK: Final = "inverter_network"
STEP_INVERTER_SERIAL: Final = "inverter_serial"

# The Ai-Logger is a Modbus TCP slave on port 9999 with native TCP framing, and
# carries every inverter under unit ID 239.
DEFAULT_LOGGER_PORT: Final = 9999
DEFAULT_LOGGER_FRAMER: Final = "socket"

# A bare inverter speaks Modbus RTU on RS-485 at 9600 8N1. UM0058 gives its
# factory Modbus address as 3, which is also where the logger's COM1 scan starts.
DEFAULT_INVERTER_PORT: Final = 502
DEFAULT_INVERTER_FRAMER: Final = "rtu"
DEFAULT_BAUDRATE: Final = 9600
DEFAULT_PARITY: Final = "n"
DEFAULT_INVERTER_UNIT_ID: Final = 3

# The logger polls each inverter about every 5 seconds, so a faster cycle just
# re-reads the same values.
SCAN_INTERVAL: Final = timedelta(seconds=30)

# Consecutive failed polls before the link is torn down and rebuilt. UM0058
# says the logger serves one client at a time; if another takes it over, ours
# can stay open while stopping being answered, and no amount of retrying on
# the same socket recovers that.
FAILURES_BEFORE_RECONNECT: Final = 3
