# Turbine simulator and history generator

One Python package, `windfarm_sim`, with two jobs:

- **Live.** It simulates the Northwind Ridge wind farm in real time: 12 turbines, a met mast and the alarm logic of the turbine controllers. It publishes MQTT messages in the formats described in [../docs/data-contracts.md](../docs/data-contracts.md).
- **History.** It generates two years of operating history for the same site: 10-minute data, the availability log, alarms, work orders, oil and blade records, curtailments, market prices, forecasts and a budget. In Fabric this runs inside notebook `02_generate_history`, which carries a copy of the code.

Both use the same climate model and the same turbine characteristics, so the past and the present describe one site.

## How it behaves

- **Wind.** The site's mean wind, direction, temperature and humidity come from the climate model (`climate.py`): a function of the date and time with seasons, a daily cycle, weather systems of several days and passing fronts. It is the same function the history and the forecast use, and it does not depend on the random seed. On top of it the simulator adds turbulence, gusts, terrain speed-up and wakes between turbines, so each turbine sees its own wind. `WIND_MODEL=regime` gives the simpler wind of version 1.0: a slow random process that shifts to a new level every few hours.
- **Turbines.** Power follows the wind through a power curve corrected for air density. Rotor speed, pitch and yaw follow the controller's logic. Temperatures follow load through first-order lags. Every turbine has its own efficiency, thermal behaviour and vibration level; these belong to the site and are the same at every start and in the history. Sensor offsets are drawn at start.
- **Standing conditions.** Three turbines carry a condition that the site history explains: a worn gearbox bearing on WT-07, a yaw offset on WT-05 and eroded blades on WT-09. They are listed in `site.json` and raise no alarm. `STANDING_CONDITIONS=false` turns them off, and with them the fixed turbine characteristics.
- **Controller.** Raises alarms from a moving average of what the sensors report, derates on critical alarms, trips on the highest limits and holds a lockout before restarting. When the simulator stops, it clears the alarms that are still raised.
- **Anomalies.** Seven kinds, injected by command. Each ramps in, holds and ramps out by itself, or holds until resolved.
- **Small events.** About once an hour somewhere on the site: a short communication drop, a cable untwist, a minor yaw offset or a sensor freeze.

Every start uses a new random seed unless `SEED` is set. The seed decides turbulence, sensor noise and the small events; it does not decide the weather or the turbines.

In the cluster the simulator reads the broker's CA certificate from the Azure IoT Operations trust bundle each time it connects, and exits after 10 minutes without a connection so that Kubernetes restarts it.

## Run it locally

```bash
pip install -r requirements-dev.txt

# Print messages to the terminal
SITE_FILE=../data/reference/site.json SINK=stdout python -m windfarm_sim

# Publish to a local MQTT broker without TLS or authentication (for example Mosquitto on port 1883)
SITE_FILE=../data/reference/site.json MQTT_HOST=localhost MQTT_PORT=1883 \
  MQTT_AUTH=none MQTT_TLS=false python -m windfarm_sim
```

With the second form running, control it from another terminal with the same environment variables:

```bash
python -m windfarm_sim.ctl status
python -m windfarm_sim.ctl inject WT-07 gearbox_degradation --duration 5m
```

## Settings

All settings are environment variables. In the cluster they come from the ConfigMap in `edge/k8s/simulator.yaml`.

| Variable | Default | Meaning |
|---|---|---|
| `SITE_FILE` | `data/reference/site.json` | Site definition |
| `SINK` | `mqtt` | `mqtt`, or `stdout` to print messages |
| `TOPIC_ROOT` | `contoso/windfarm` | First part of every topic |
| `TELEMETRY_INTERVAL_S` | `5` | Seconds between telemetry messages per turbine |
| `WEATHER_INTERVAL_S` | `10` | Seconds between weather messages |
| `REGISTRY_INTERVAL_S` | `300` | Seconds between asset messages |
| `HEARTBEAT_INTERVAL_S` | `60` | Seconds between heartbeats |
| `SEED` | empty | Fixed random seed; empty draws a new one at every start |
| `WIND_MODEL` | `climate` | `climate`: the site's weather, shared with the history. `regime`: the simple wind of version 1.0. |
| `STANDING_CONDITIONS` | `true` | Turbine characteristics and conditions of the site history |
| `WIND_MEAN` | `9.0` | Starting level of the mean wind, m/s (`regime` only) |
| `WIND_REGIME_MIN`, `WIND_REGIME_MAX` | `6.5`, `12.5` | Band within which the mean wind shifts (`regime` only) |
| `AMBIENT_MEAN_C` | `18` | Mean air temperature (`regime` only) |
| `SPONTANEOUS_EVENTS_PER_HOUR` | `1.0` | Small random events across the site; `0` turns them off |
| `MQTT_HOST`, `MQTT_PORT` | Azure IoT Operations broker, `18883` | Broker address |
| `MQTT_AUTH` | `k8s-sat` | `k8s-sat`, `none` or `userpass` |
| `MQTT_TLS` | `true` | TLS with server certificate verification |
| `MQTT_PROTOCOL` | `v5` | `v5` (required for `k8s-sat`) or `v311` |
| `MQTT_CA_FILE` | `/var/run/certs/ca.crt` | CA certificate of the broker, as mounted |
| `MQTT_CA_CONFIGMAP` | the Azure IoT Operations trust bundle | `namespace/name/key` of the ConfigMap to read the current CA from at every connect; empty uses only the file |
| `MQTT_SAT_FILE` | `/var/run/secrets/tokens/broker-sat` | Service account token |
| `MQTT_USERNAME`, `MQTT_PASSWORD` | empty | For `userpass` |
| `LOG_LEVEL` | `INFO` | |

## Tools

| Command | Purpose |
|---|---|
| `python -m windfarm_sim` | Run in real time |
| `python -m windfarm_sim.ctl` (installed as `simctl`) | Send commands to a running simulator |
| `python -m windfarm_sim.generate` | Write sample data to a file, faster than real time |
| `python -m windfarm_sim.sitegen` | Regenerate the site and all reference data from a seed |
| `python -m windfarm_sim.history` | Write the operating history to CSV or Parquet files, with a summary of its headline numbers |

Regenerate the committed sample and reference data from the repository root:

```bash
PYTHONPATH=simulator python -m windfarm_sim.sitegen --out data/reference --seed 42
PYTHONPATH=simulator python -m windfarm_sim.generate --site data/reference/site.json \
  --minutes 45 --seed 7 --wind-mean 10.5 --start 2026-11-19T15:00:00Z \
  --inject "WT-07:gearbox_degradation:0.8:15m@10m" \
  --out data/samples/sample_events.json --truth data/samples/sample_ground_truth.jsonl
```

A different `--seed` for `sitegen` gives a different site layout and terrain. Rebuild the simulator image, sync the reference data and run notebooks 01 and 02 afterwards, so that the edge and the Lakehouse describe the same site. `--drivetrain-warranty-end 2027-12-31` moves the end of the gearbox warranty, for demonstrations after the original date.

## The history generator

```bash
python -m windfarm_sim.history --site ../data/reference/site.json --out /tmp/history
python -m windfarm_sim.history --site ../data/reference/site.json --out /tmp/history --as-of 2026-11-20T06:00:00Z --format parquet
```

It needs `pandas`, which the simulator itself does not; `requirements-dev.txt` installs it. Two years for 12 turbines take about 10 seconds and 1 GB of memory.

| What | How it is made |
|---|---|
| Weather | `climate.py`, evaluated every 10 minutes from the start of the history to `--as-of` (default: now) |
| Stops and outages | Random faults per turbine, class and day, with rates from `catalog.py`; scheduled services placed on days with little wind; icing, storms, grid outages and curtailment from the weather and the market |
| Repairs | Technicians arrive in working hours, not in wind above 18 m/s; a part that is out of stock adds its lead time; cost is labour, parts and other |
| Signals | Power from the same formula as the live turbine; temperatures and vibration from load, with each turbine's own character |
| Planted stories | `_History.stories()`: placed relative to `--as-of`, so that they stay recent |
| Forecast | The same climate seen in advance, with an error that grows with the horizon |

The past does not change when the history is generated again later: every random draw is keyed by turbine and day, and the weather is a function of time. Only the planted stories move, with `--as-of`.

After changing `catalog.py`, `climate.py` or `history.py`, rebuild the notebooks from the repository root, or the test `test_notebooks.py` fails:

```bash
python3 tools/build-notebooks.py
```

## Tests

```bash
python -m pytest
```

57 tests. They cover the physics, the alarm and anomaly logic, the commands and the message formats; the climate model; the history generator (its headline numbers, the planted stories, that the past is stable); what the live simulator shares with the history; that the committed reference data and notebooks match their generators; and that the code inside the notebooks runs without the package. One integration test runs the simulator and `simctl` against a local MQTT broker (`amqtt`, MQTT 3.1.1, no TLS). The service account token authentication used inside Azure IoT Operations can only be exercised on the edge cluster.

## Code map

| Module | Content |
|---|---|
| `config.py` | Settings from environment variables |
| `site.py` | Loads the site definition |
| `climate.py` | The site's weather as a function of time, the forecast, and the fixed characteristics of the turbines; shared by the live simulator and the history |
| `wind.py` | Wind field at the turbines: turbulence, gusts, terrain, wakes |
| `turbine.py` | Turbine physics, controller, alarms, states |
| `alarms.py` | Alarm catalogue; also the source of `alarm_codes.csv` |
| `anomalies.py` | Anomaly kinds and their effects |
| `engine.py` | Simulation loop, message building, command handling |
| `mqtt_io.py` | MQTT connection, including service account token authentication |
| `k8s.py` | Reads the broker's current CA certificate from the cluster |
| `__main__.py` | Real-time runner |
| `ctl.py` | `simctl` |
| `generate.py` | Offline sample generator |
| `sitegen.py` | Site and reference data generator |
| `catalog.py` | Spare parts, people, contracts, fault types and rates, standing conditions |
| `history.py` | Operating history generator |
