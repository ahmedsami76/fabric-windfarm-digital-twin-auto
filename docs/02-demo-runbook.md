# Demo runbook: inject a fault and follow it

How to run the anomaly demo once Phase 1 is deployed, and how to tell the story around it from the history in the Lakehouse.

Commands are typed on the workstation, in the root folder of the repository; `bash infra/vm.sh ssh` runs them on the edge VM. To save typing during a demo, define a short form once per session:

```bash
sim() { bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh "$@"; }
```

The rest of this document uses `sim`. `sim status` is then the same as `bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh status`.

The KQL queries are in `fabric/kql/90-validation-queries.kql`; step 8 of the deployment guide shows the ones used here in full.

## Before the demo

| When | Do | Why |
|---|---|---|
| The day before | Run notebook `02_generate_history`, then `04_question_bank` | The history then ends today, and you have the expected answers |
| 30 minutes before | `bash infra/vm.sh status`. Start the VM if it is stopped (`bash infra/vm.sh start`), and check that the daily shutdown does not fall inside the demo. | Azure IoT Operations and the simulator need about 5 minutes to come up |
| 20 minutes before | `sim status` | Confirms the simulator runs, shows the wind, and opens SSH access for the session |
| 15 minutes before | `sim wind --mean 11 --duration 90m` | A gearbox fault barely shows on a turbine that idles in light wind. This holds the wind near 11 m/s. |
| 10 minutes before | Run queries 1 and 3 in Fabric | Confirms data is arriving and turbines are `RUNNING` |
| 10 minutes before | Open queries 7, 9, 10 and 11 in separate tabs | They are the ones you show |

The wind override does not make the data artificial: gusts, turbulence, wakes and direction changes continue around the new mean.

Where just-in-time access governs SSH, a grant lasts 3 hours. `sim status` renews it when needed, which takes up to a minute; do it before the audience watches.

## The demo

### 1. Show normal operation

Run query 3 (what every turbine is doing) and query 4 (site power). Point out that no two turbines read the same: each has its own wind, efficiency and sensor behaviour.

Then run query 10 (each turbine against the fleet). WT-07 is already at or near the top for vibration, with no alarm. Leave that unexplained for now.

### 2. Inject the fault

```bash
bash infra/vm.sh ssh bash ./edge/scripts/inject-anomaly.sh
```

This is the same as `sim inject WT-07 gearbox_degradation --severity 0.8 --duration 15m`. The fault ramps in over 4.5 minutes, holds, and ramps out by itself over the last 3 minutes.

### 3. Follow it

Typical timing with the wind held near 11 m/s, from eight test runs of simulator 1.1.0. It varies by about half a minute from run to run, because the wind does.

| Minutes after injection | At the turbine | What to show in Fabric |
|---|---|---|
| 0 to 2 | Vibration and oil temperature climb | Query 7: WT-07's vibration line leaves WT-06 and WT-08 behind |
| About 2 | `GBX-VIB-HIGH` (warning) | Query 11: the alarm appears on the timeline |
| About 3 | `GBX-OIL-TEMP-HIGH` (warning), then `GBX-VIB-CRIT`: the controller derates WT-07 to 30 percent of rated power. State changes to `DERATED`. | Query 9: WT-07's power drops below its neighbours. Query 10: WT-07 is at the top, with vibration several times the fleet median. |
| 4 to 6 | `GBX-OIL-TEMP-CRIT` | Query 12: four active alarms |
| 5 to 12 | The fault holds. WT-07 produces about 1,200 kW while its neighbours follow the wind. | This is the window in which an operations agent, which evaluates its rules every 5 minutes, sees the fault at least twice. |
| 13 to 15 | The fault ramps out. The alarms clear, critical first. | Query 11: the `cleared` rows, each with its duration |
| About 19 | The controller releases the derate 5 minutes after the critical alarm cleared. State returns to `RUNNING`. | Query 9: power rejoins the neighbours |

Check progress at the edge at any time with `sim status`.

### 4. Tell the story behind it

The fault you injected is the moment a slow problem turns acute. The history in the Lakehouse holds the slow problem, and the questions of notebook `04_question_bank` find it. Show them in this order.

| Step | Question | What it shows |
|---|---|---|
| 1 | RE-05, gearboxes against the fleet | Over the last 30 days WT-07's gearbox ran warmer and rougher than every other one. No alarm limit was reached. |
| 2 | RE-06, the trend by week | The drift began about four months ago and is still growing. |
| 3 | RE-07, oil samples | Iron in WT-07's gearbox oil has risen in each of the last three samples; the laboratory recommends a borescope inspection. WT-02 showed the same pattern before its bearing failed. |
| 4 | RE-08, the precedent | WT-02's high-speed bearing failed after those warnings. The turbine was down for about ten days and the repair cost about 121,000 dollars. |
| 5 | SM-05, the plan | The borescope inspection of WT-07 is planned two weeks from now. One bearing kit is in stock (SM-06). |
| 6 | RE-09, the warranty | The drivetrain warranty ends on 31 December 2026. Before that date the supplier pays for a bearing replacement; after it, the owner does. |
| 7 | MP-01, the window | The forecast for the coming week shows on which working day stopping one turbine costs the least. |

The decision the data leads to: bring the inspection forward into the next calm day, and claim the bearing under warranty before the year ends. That is the kind of conclusion the data agent and the operations agent of the later phases are meant to reach, and the procedure for it is `SOP-GBX-001` in `ref_sop_documents`.

Other stories for other audiences are listed in [04-use-cases-and-data-audit.md](04-use-cases-and-data-audit.md): the misaligned WT-05, the eroded blades of WT-09, the missed availability guarantee, curtailment as the largest loss.

## Options for `inject`

```bash
sim inject TURBINE KIND [--severity 0.05..1.0] [--duration 15m] [--hold]
```

### Severity, for `gearbox_degradation`

| Severity | Result |
|---|---|
| 0.3 to 0.5 | Warnings only. Vibration alarm; oil temperature alarm at higher load. Small loss of efficiency. |
| 0.6 to 0.7 | Warnings; the critical vibration alarm becomes likely at 0.7. |
| 0.8 to 0.9 | Critical alarms, derate to 30 percent, a clear production gap. The default is 0.8. |
| 1.0 | As above. In strong wind the oil temperature can also reach the trip limit: the turbine stops (state `FAULT`) and restarts by itself only after all alarms have been clear for 10 minutes. |

On WT-07 every level acts a little earlier than on other turbines, because its gearbox is already worn.

### Duration

The default is 15 minutes. Shorter faults work, but below about 10 minutes an operations agent may see the fault in only one of its 5-minute evaluations, or miss the critical phase. Use `90s`, `20m`, `1h` and so on.

`--hold` keeps the fault active until you end it. Later phases use this to let the operations agent propose and apply a fix:

```bash
sim inject WT-07 gearbox_degradation --hold
sim resolve WT-07
```

### Fault kinds

`sim kinds` lists them.

| Kind | What happens | How it is found |
|---|---|---|
| `gearbox_degradation` | Vibration, oil and bearing temperature rise; oil pressure and efficiency fall; derate or trip | Alarms `GBX-…`; several signals move together |
| `generator_overheat` | Winding and bearing temperature rise with load; derate to 50 percent at the critical limit | Alarms `GEN-WIND-TEMP-…`. Needs wind: at low load the temperature may stay below the limits. |
| `pitch_fault` | One blade lags: pitch asymmetry, power loss, tower vibration, low hydraulic pressure; derate to 40 percent | Alarms `PITCH-ASYM`, `TWR-VIB-HIGH`, `HYD-PRESS-LOW` |
| `yaw_misalignment` | The nacelle points 10 to 30 degrees off the wind; power falls by up to a third | No alarm. The nacelle direction differs from the neighbours and power is lower at the same wind. A case for analytics, not thresholds. |
| `sensor_drift` | The gearbox oil temperature reading drifts up; nothing is physically wrong | `GBX-OIL-TEMP-HIGH` without any rise in vibration or bearing temperature. At high severity the false reading can trigger a real derate. |
| `sensor_freeze` | The gearbox oil temperature reading flatlines | A signal with zero variance |
| `comms_loss` | The turbine stops reporting | Missing rows (query 13), then a `COMMS-RESTORED` event |

Examples:

```bash
sim inject WT-03 generator_overheat --severity 0.9 --duration 20m
sim inject WT-10 pitch_fault
sim inject WT-12 yaw_misalignment --severity 1.0 --duration 30m
sim inject WT-04 sensor_drift --severity 0.9
sim inject WT-02 comms_loss --duration 3m
```

Several faults can run at once, on the same turbine or on different ones.

## Operating commands

These are the actions a control room has. In Phase 5 one of them comes from the cloud: the operations agent proposes a curtailment, and after a person approves it in Teams the command arrives here ([13-deployment-guide-phase5b.md](13-deployment-guide-phase5b.md)).

```bash
sim curtail WT-07 --percent 30 --duration 30m   # limit power
sim release WT-07                               # remove the limit
sim stop WT-07 --reason maintenance             # stop the turbine
sim start WT-07                                 # return it to service
sim reset WT-07                                 # clear a latched trip or derate
```

Since simulator 1.2.0 (Phase 5c) the edge reports each of these to Fabric, whoever gave it: the table `EdgeCommands` holds one row per turbine and command, and `CommandLog(1h)` in the KQL database says what became of each. A command given here shows there with `Source` = `edge`. A restart of the simulator ends every limit and stop that was set.

## What is fixed and what varies

| What | Behaviour | How to control it |
|---|---|---|
| The weather | Follows the site's climate, the same one as the history and the forecast: seasons, a daily cycle, fronts. It is a function of the date and time, not of the random seed. | `sim wind --mean 11 --duration 60m` holds the mean; `sim wind --clear` returns to the climate. `WIND_MODEL: "regime"` in `edge/k8s/simulator.yaml` gives the simple wind of version 1.0.0. |
| The turbines | Each turbine's efficiency, temperature level and vibration level are those of the site history, at every start | `STANDING_CONDITIONS: "false"` in the ConfigMap gives turbines drawn afresh at every start and removes the conditions of WT-05, WT-07 and WT-09 |
| Turbulence, sensor noise, small site events | Different at every start. The simulator draws a new seed and logs it. | Set `SEED` in the ConfigMap to repeat a run exactly |
| Small site events | About one per hour across the site: a communication drop of 30 to 75 seconds, a cable untwist pause, a minor yaw offset or a brief sensor freeze | `SPONTANEOUS_EVENTS_PER_HOUR: "0"` in the ConfigMap for a quiet site |
| Publishing rate | Telemetry every 5 seconds per turbine, weather every 10 seconds | `TELEMETRY_INTERVAL_S`, `WEATHER_INTERVAL_S` |

After changing the ConfigMap, run `bash infra/vm.sh push`, then `bash infra/vm.sh ssh bash ./edge/scripts/05-deploy-simulator.sh`.

## Reset after the demo

```bash
sim resolve all      # end any fault that is still active
sim release all      # remove curtailments
sim start all        # restart manually stopped turbines
sim wind --clear     # return the wind to the site's weather
```

The data of the demo stays in the Eventhouse, which is usually what you want for the next audience. To start from empty tables, see `fabric/kql/99-reset-demo-data.kql`.

The history in the Lakehouse does not contain the fault you injected: it is generated, not recorded. Joining the live data into the history is part of Phase 2.
