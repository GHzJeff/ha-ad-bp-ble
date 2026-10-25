# A&D Blood Pressure BLE for Home Assistant

Local Bluetooth support for the **A&D Medical UA-651BLE** blood pressure monitor in
Home Assistant: no cloud, no phone app. Readings appear as sensors (systolic,
diastolic, pulse, battery, measured time), and every reading, including ones taken
while Home Assistant couldn't reach the monitor, is delivered as an event you can log.

The UA-651BLE is sold in the US (Amazon, pharmacies) for roughly $50–70. The Medisana
monitors that the original integration was written for aren't available in the US.

> Based on [bkbilly/medisanabp_ble](https://github.com/bkbilly/medisanabp_ble) (MIT).
> The reading decoder and sensor structure are from that project; this version adds
> what the A&D needs (pairing, burst detection, multi-record delivery). See *What's different*.

**Not a medical device integration.** For personal tracking only; always rely on the
monitor's own display and your doctor.

## What you need

| Item | Notes |
|---|---|
| A&D UA-651BLE | Uses the standard Bluetooth Blood Pressure service (0x1810). Other A&D BLE models may work but are untested. |
| An **ESPHome Bluetooth proxy** (any ESP32, ~$10) | **Required.** Home Assistant's built-in Bluetooth (BlueZ) can't pair with this monitor (`AuthenticationFailed`), but ESPHome proxies pair fine. Use the official [ESPHome Bluetooth proxy](https://esphome.github.io/bluetooth-proxies/) firmware. |
| Home Assistant | Tested on 2026.10. |

**Place the proxy within 3-6 feet of where you take readings**, closer than any other
Bluetooth adapter. The pairing (bond) is stored on the proxy, so Home Assistant must
connect through that same proxy every time. (The integration also steers HA toward the
proxy if another adapter hears the monitor.)

## Install

**HACS (custom repository):** HACS → ⋮ → Custom repositories → add this repository's URL,
type *Integration* → install **A&D Blood Pressure BLE** → restart Home Assistant.

**Manual:** copy `custom_components/ad_bp_ble` into `/config/custom_components/` and restart.

## Pair the monitor (once per monitor)

1. Remove/forget the monitor on your phone (Android Settings → Connected devices, and any
   BLE scanner or A&D app). The monitor bonds with **one host at a time**.
2. Put the monitor next to the ESPHome proxy and hold **START** until **"Pr"** flashes.
3. Home Assistant discovers **A&D Blood Pressure BLE** (Settings → Devices & services →
   Discovered). Click **Add**. The integration connects, pairs, sets the monitor's clock and subscribes.
4. Take a reading. About a minute after the monitor finishes, the values appear in HA.

From then on, just take readings; the integration notices the monitor waking up and collects
them automatically. If a transfer fails, the reading stays on the monitor and comes through next time.

**Units tip:** if your HA uses US units, it may show pressure in inHg. Open each systolic/diastolic
sensor → ⚙ → set *Unit of measurement* to **mmHg**.

## What's different from medisanabp_ble

| Problem with the A&D | Change |
|---|---|
| Doesn't advertise its name to passive scanning | Discovered by the Blood Pressure service UUID (`0x1810`) instead of a name |
| Drops the connection on any write before bonding | Pairs **first** on every connection, then sets time, then subscribes |
| Expects the host to set its clock | Writes the current time to the Date Time characteristic (0x2A08) |
| Only advertises briefly after a reading, and the advertisement **never changes**, so HA's change-driven polling never fires | A 5-second watcher polls once per advertising burst (uses HA's last-seen time) |
| Sends every stored reading in one session | Fires one `ad_bp_ble_reading` event **per reading**, so offline readings aren't lost |
| HA's local adapter fails to pair, then gets preferred anyway | Steers the connection to the ESPHome proxy that holds the bond |

Uses a couple of private Home Assistant Bluetooth internals (the coordinator's poll
debouncer and scanner failure counts), so a future HA release could require an update.

## Events

Every reading fires `ad_bp_ble_reading`:

```yaml
address: "AA:BB:CC:DD:EE:FF"     # which monitor
time: "2026-10-12T09:24:35-07:00"
systolic: 122
diastolic: 79
pulse: 69
```

## Optional extras (in `examples/`)

| File | What it does |
|---|---|
| `automation_bp_log.yaml` | Logs each reading (deduplicated), routes two monitors to two people |
| `bp_log.py` | Appends to `/config/bp/blood_pressure_log.csv`, kept in time order and never pruned, so it opens in Excel for your doctor |
| `configuration_additions.yaml` | `shell_command` for the CSV + a rolling 60-day "Blood Pressure Log" sensor per person |
| `dashboard_bp_diary.yaml` | Diary card (today's readings, then daily averages with pulse) + 30-day graph |
| `garmin_watch_menu_bp_group.json` | Group for the [GarminHomeAssistant](https://github.com/house-of-abbey/GarminHomeAssistant) watch app: latest reading + 7 daily averages |

## Troubleshooting

- **Readings don't arrive:** turn on debug logging for `custom_components.ad_bp_ble` and check
  which adapter HA connected through. "Failed to connect after 4 attempts" usually means it
  tried a non-proxy adapter: move the proxy closer to where readings are taken.
- **Monitor shows an error after pairing:** re-pair in "Pr" mode next to the proxy.
- **Old readings missing:** readings taken while the monitor was bonded to something else
  (e.g. a phone) never reach HA.

## Credits

- Original integration: [bkbilly/medisanabp_ble](https://github.com/bkbilly/medisanabp_ble), MIT.
- A&D adaptation developed with AI assistance (Claude) and tested on a UA-651BLE.
