# Solplanet Ai-Logger (Modbus) — Home Assistant integration

A Home Assistant custom integration for **Solplanet / AISWEI** solar inverters, read locally over Modbus. Point it at an **Ai-Logger** to get the whole site in one go, or wire an RS-485 adapter straight to a single inverter. No cloud, no app account.

Built on the [solplanet-modbus](https://github.com/balloobbot/solplanet-modbus) device library (vendored here until it is published to PyPI) and [modbus-connection](https://github.com/home-assistant-libs/modbus-connection). The register map follows [UM0058 Ai-logger Modbus TCP V03](https://github.com/balloobbot/solplanet-modbus/blob/main/docs/UM0058_Ai-logger-Modbus-TCP_EN_V03_0424.pdf).

> [!WARNING]
> **Alpha — built from the protocol document, not yet verified against real hardware.** Every address, scale and type is transcribed from UM0058 and covered by tests against an in-memory mock, but no physical logger or inverter has confirmed them. Take particular care with the **write** entities: a write reaches every inverter on the site. Test reports very welcome.

> If you have a single inverter with its own **WiFi dongle** and no Ai-Logger, you probably want [zbigniewmotyka/home-assistant-solplanet](https://github.com/zbigniewmotyka/home-assistant-solplanet) instead — it reads the dongle's JSON API. This integration covers the Modbus side.

## What you get

Each inverter becomes its own Home Assistant device, with the Ai-Logger as the hub they hang off:

- **Production sensors** — active power, energy today and total, operating hours, grid frequency, power factor, apparent and reactive power.
- **DC sensors** — per-PV-input voltage and current, and per-string current. Only the inputs the inverter actually reports are created: a two-tracker inverter gets two, not the ten the protocol reserves.
- **AC sensors** — per-phase voltage and current. The L2/L3 and line-to-line voltages appear only on a three-phase inverter.
- **Diagnostics** — internal, boost, per-phase and DC/DC converter temperatures, bus voltage, grid connect time, and the error code together with its label.
- **Fault binary sensor** — the inverter's own view of whether it has faulted.
- **Site sensors** (Ai-Logger only) — active and reactive power summed over every inverter.
- **Weather sensors** (optional) — irradiance, cell and ambient temperatures, humidity, wind.
- **Meter sensors** (optional) — an SDM630's power, imported and exported energy, frequency and per-phase values.
- **Controls** (Ai-Logger only, disabled by default) — active power limit, reactive power and power factor commands, plus a site-wide on/off switch.
- **Diagnostics download** — the live raw register map, which replays directly into the library's mock backend for hardware-free bug reproduction.

## Connecting

The setup menu offers three ways in, because the same register layout is reachable three ways.

### Ai-Logger (Modbus TCP)

The logger polls every inverter on its three RS-485 ports and republishes them all in one flat map, on **port 9999 with native Modbus TCP framing, under unit ID 239**. This is the normal choice for anything bigger than one inverter.

Setup scans the ports you tick for populated inverter windows. Each port reserves 30 windows and each is one request, so tick only the ports you actually have wired — scanning all three is 90 requests.

Two things the logger insists on, both handled for you but worth knowing: it serves **one client at a time** (stop anything else polling it first), and it polls each inverter about every five seconds, so the 30-second refresh here is already faster than the data changes.

### Single inverter — serial (RS-485)

An inverter's own Modbus map is the *same* 1000–1389 block the logger republishes: UM0058 states each window carries "inverter modbus protocol table 31001-31388", which is exactly these input registers. So a USB RS-485 adapter wired to the inverter reads the same fields at the same addresses, with the unit ID being the inverter's own Modbus address (**9600 baud, 8N1, address 3** from the factory).

> [!CAUTION]
> Do not wire this to an RS-485 bus an Ai-Logger is already polling. Two masters on one line collide, and you will get read errors on both.

### Single inverter — network gateway

The same thing through an RS-485-to-network gateway, which is a transparent serial bridge — hence RTU framing by default. Pick *native Modbus TCP* only if your gateway re-frames.

The connection is managed for you in all three cases: it opens on the first poll and re-establishes itself after a drop. A device that goes offline comes back on its own — no reload needed. If three polls in a row fail, the link is torn down and rebuilt as well, which covers the case a drop does not: the Ai-Logger accepts one client at a time, so another one taking it over can leave this socket open but unanswered.

## Installation

### HACS

1. Make sure [HACS](https://www.hacs.xyz/) is installed.
2. Add `https://github.com/balloobbot/home-assistant-solplanet-modbus` as a custom repository of type **Integration**.
3. Download **Solplanet Ai-Logger (Modbus)** and restart Home Assistant.
4. `Settings → Devices & services → Add integration → Solplanet Ai-Logger (Modbus)`.

### Manual

Copy `custom_components/solplanet_modbus` into `/config/custom_components/` and restart.

## Controlling output power

The control registers are **write-only** and site-wide: there is no per-inverter control register, and nothing can be read back. The entities therefore show *what Home Assistant last wrote*, restored across restarts — not what the inverters confirm. They are disabled by default; enable them deliberately.

UM0058's fast active power command (register 60000) is deliberately **not** exposed. It is a relative adjustment against current output, not a setpoint, and has to be rewritten every 500 ms to stay in effect — a control loop, not an entity. The underlying library has it if you need to build one.

## Known gaps in the protocol document

UM0058 promises three code tables it does not contain. The **error codes** are filled in from [zbigniewmotyka/home-assistant-solplanet](https://github.com/zbigniewmotyka/home-assistant-solplanet), which reads the same inverters against real hardware — so the *Error* sensor is a best-effort label and the raw *Error code* sensor sits beside it. The **grid code** and **warning code** have no table at all and stay raw numbers.

The weather station's wind speed is documented with no gain but a maximum of 6000, which only makes sense at a 0.01 scale. It is exposed unscaled as a diagnostic *wind speed (raw)* so the document and the integration agree — divide by 100 if a real sensor reads high. This is the value most worth checking against hardware.

## Vendored device library

`custom_components/solplanet_modbus/vendor/solplanet_modbus/` is a verbatim copy of the [solplanet-modbus](https://github.com/balloobbot/solplanet-modbus) library. It is vendored **temporarily**: once the library is on PyPI it moves to a `manifest.json` requirement and the vendor package goes away. Don't patch it here — change it upstream and re-copy.

## Develop / test

```bash
uv sync
uv run pytest
```

The tests use Home Assistant's `pytest-home-assistant` package against modbus-connection's in-memory mock backend — no hardware, no sockets. Python 3.14.2 or newer is required. Home Assistant and its pytest helpers are pinned to the same Core revision in `pyproject.toml` while the standalone test package is awaiting publication.
