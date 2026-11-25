# Data contracts

The MQTT topics and message formats that the edge publishes, the commands the simulator accepts, and where each field lands in the Eventhouse.

## Topics

All topics start with `contoso/windfarm/{siteId}`. The site in this repository is `northwind-ridge`.

| Topic | Message type | Publisher | Cadence | Retained | Sent to Fabric |
|---|---|---|---|---|---|
| `…/{turbineId}/telemetry` | `telemetry` | Simulator | Every 5 s per turbine | No | Yes |
| `…/{turbineId}/alarm` | `alarm` | Simulator | When an alarm is raised or cleared | No | Yes |
| `…/{turbineId}/state` | `state` | Simulator | When the operating state changes | No | Yes |
| `…/{assetId}/asset` | `asset` | Simulator | At start and every 5 min | Yes | Yes |
| `…/MET-01/weather` | `weather` | Simulator | Every 10 s | No | Yes |
| `…/EDGE-01/heartbeat` | `heartbeat` | Simulator | Every 60 s | No | Yes |
| `…/{turbineId}/command` | `command` | Simulator, since version 1.2.0 (Phase 5c) | When an operating command was taken or refused: one message for each turbine it acted on | No | Yes |
| `…/_sim/request` | Command | `simctl` | On demand | No | No |
| `…/_sim/response/{requestId}` | Acknowledgement | Simulator | Per command | No | No |
| `…/_sim/status` | Simulator status | Simulator | Every 30 s | Yes | No |
| `…/_sim/events` | Anomaly ground truth | Simulator | When an anomaly starts or ends | No | No |
| `…/_control/request` | Operating command | The data flow `fabric-to-windfarm-control` of Phase 5a, from the Fabric eventstream `WindFarmCommands`; written there by notebook `12_send_edge_command` | On demand | No | No |
| `…/_control/response/{requestId}` | Acknowledgement | Simulator | Per command | No | No |

Messages are published with QoS 1. Turbine ids are `WT-01` to `WT-12`.

## Envelope

Every message sent to Fabric has the same seven fields.

```json
{
  "messageType": "telemetry",
  "schemaVersion": "1.0",
  "siteId": "northwind-ridge",
  "assetId": "WT-07",
  "timestamp": "2026-11-19T15:12:45.000Z",
  "seq": 154,
  "data": { }
}
```

| Field | Type | Meaning |
|---|---|---|
| `messageType` | string | `telemetry`, `alarm`, `state`, `asset`, `weather` or `heartbeat` |
| `schemaVersion` | string | Version of this contract |
| `siteId` | string | Site identifier |
| `assetId` | string | Turbine, met mast or edge server that the message is about |
| `timestamp` | string | UTC time at the source, ISO 8601 with milliseconds |
| `seq` | integer | Counter per asset, increasing by 1 with every message from that asset. A jump means messages were lost. |
| `data` | object | Payload; depends on `messageType` |

The envelope maps one to one to the columns of `RawEvents`.

## telemetry

Lands in `TurbineTelemetry`. Column names are the field names in Pascal case.

| Field | Unit | Meaning |
|---|---|---|
| `state` | | Operating state; see "Operating states" |
| `windSpeed` | m/s | Wind speed at the nacelle anemometer |
| `windDirection` | deg | Direction the wind comes from, 0 to 360 |
| `ambientTemp` | degC | Outside air temperature |
| `activePower` | kW | Power delivered. About -12 kW when not generating (own consumption). |
| `reactivePower` | kvar | Reactive power |
| `powerSetpoint` | kW | Power limit in force: 4,200 normally, lower when curtailed or derated |
| `rotorSpeed` | rpm | Rotor speed, 12.3 at rated |
| `generatorSpeed` | rpm | Generator speed (rotor speed times the gear ratio of 97) |
| `pitchAngle` | deg | Mean blade pitch; about 0.6 below rated wind, 88 when feathered |
| `nacelleDirection` | deg | Direction the nacelle points |
| `yawError` | deg | Wind direction relative to the nacelle, as measured by the wind vane |
| `gearboxOilTemp` | degC | Gearbox oil sump temperature |
| `gearboxBearingTemp` | degC | Gearbox high-speed shaft bearing temperature |
| `gearboxOilPressure` | bar | Gearbox lubrication pressure |
| `gearboxVibration` | mm/s | Gearbox vibration velocity, RMS |
| `generatorWindingTemp` | degC | Generator stator winding temperature |
| `generatorBearingTemp` | degC | Generator drive-end bearing temperature |
| `mainBearingTemp` | degC | Main bearing temperature |
| `nacelleTemp` | degC | Air temperature inside the nacelle |
| `transformerTemp` | degC | Transformer temperature |
| `towerVibration` | mm/s | Tower top vibration velocity, RMS |
| `hydraulicPressure` | bar | Pitch hydraulic system pressure |
| `gridVoltage` | V | Voltage at the generator terminals, nominal 690 |
| `gridFrequency` | Hz | Grid frequency, nominal 60 |
| `energyTotal` | kWh | Lifetime energy counter |

Telemetry is absent while a turbine has lost communication. The gap is visible as missing rows and as a jump in `seq`.

### Operating states

| State | Meaning |
|---|---|
| `RUNNING` | Generating normally |
| `DERATED` | Generating under a protective limit set by the controller after a critical alarm |
| `CURTAILED` | Generating under a remote setpoint |
| `IDLE` | Wind below cut-in (3 m/s) |
| `PAUSED` | Short automatic pause, for example a cable untwist |
| `STOPPED_HIGH_WIND` | Wind above cut-out (25 m/s) |
| `STOPPED` | Stopped by an operator command |
| `MAINTENANCE` | Stopped by an operator command for maintenance |
| `FAULT` | Stopped by a protection trip |

## alarm

Lands in `AlarmEvents`. An alarm produces one message with `status` `raised` and later one with `status` `cleared`; both carry the same `alarmId`.

| Field | Meaning |
|---|---|
| `alarmId` | Identifier shared by the raised and cleared messages |
| `alarmCode` | Code from the alarm catalogue |
| `status` | `raised` or `cleared` |
| `severity` | `info`, `warning` or `critical` |
| `component` | Component the alarm belongs to |
| `description` | Text of the alarm |
| `value` | Measured value when the alarm changed status; null for event alarms |
| `threshold` | Limit that was crossed; null for event alarms |
| `unit` | Unit of `value` and `threshold` |
| `durationSeconds` | On `cleared`: how long the alarm was active |
| `clearedBy` | Only on alarms that the simulator clears because it is shutting down: `simulator shutdown`. Not stored in a column; it stays in `RawEvents.data`. |
| `sop` | Operating procedure that applies (column `SopId`) |

The alarm catalogue, with thresholds and controller actions, is in `data/reference/alarm_codes.csv` and is generated from `simulator/windfarm_sim/alarms.py`, so the two cannot drift apart.

Alarms raised while a turbine is offline are buffered and sent, with their original timestamps, when communication returns. `COMMS-RESTORED` is a one-off event: it is raised and never cleared.

When the simulator stops in an orderly way (a redeployment, a shutdown of the VM), it sends `cleared` for every alarm that is still raised. If it is killed without the chance to do so, the function `ActiveAlarms()` still gives the right answer: it ignores alarms raised before the simulator's latest start, which it derives from `EdgeHeartbeats`.

## state

Lands in `TurbineStateChanges`.

| Field | Meaning |
|---|---|
| `previousState` | State before the change |
| `state` | New state |
| `reason` | Short reason, for example `protective derate` |

## asset

Lands in `AssetRegistry`. Sent for each turbine and for the met mast. Use `CurrentAssets()` for the latest row per asset.

| Field | Meaning |
|---|---|
| `name`, `assetType` | Display name; `WindTurbine` or `MetMast` |
| `model`, `manufacturer`, `serialNumber` | Turbines only |
| `ratedPowerKw`, `rotorDiameterM`, `hubHeightM` | Turbines only |
| `latitude`, `longitude`, `elevationM` | Position (WGS 84) and ground elevation |
| `localX`, `localY` | Metres east and north of the site origin; the coordinates the 3D app uses |
| `string` | Collector string, A to C (column `CollectorString`) |
| `commissionedDate` | Turbines only |

## weather

Lands in `WeatherObservations`.

| Field | Unit | Meaning |
|---|---|---|
| `windSpeed` | m/s | Free-stream wind speed at hub height |
| `windDirection` | deg | Direction the wind comes from |
| `windGust` | m/s | Gust speed |
| `ambientTemp` | degC | Air temperature |
| `pressure` | hPa | Sea-level pressure |
| `humidity` | % | Relative humidity |
| `airDensity` | kg/m3 | Air density at the site |

## heartbeat

Lands in `EdgeHeartbeats`.

| Field | Meaning |
|---|---|
| `simulatorVersion` | Version of the simulator |
| `uptimeSeconds` | Seconds since the simulator started |
| `turbinesReporting`, `turbinesTotal` | Turbines currently communicating, and the total |
| `messagesPublished` | Messages published since start |

## command

The edge's record of an operating command, since simulator 1.2.0. Lands in `EdgeCommands`; the function `CommandLog()` puts each row next to what the telemetry showed afterwards (`fabric/kql/07-command-log.kql`, [14-deployment-guide-phase5c.md](14-deployment-guide-phase5c.md)).

One message for each turbine a `curtail`, `release`, `stop`, `start` or `reset` acted on, whether it came from Fabric over `…/_control/request` or from `simctl`. A command to all turbines gives twelve messages with one `requestId`. A refused command gives one message: under the turbine it named, or under `EDGE-01` when it named none that exists. `inject`, `resolve`, `wind` and `status` are not operating commands and are not reported, except that one of them arriving on `…/_control/request` is reported as refused. The envelope's `timestamp` is when the edge handled the command.

| Field | Column | Meaning |
|---|---|---|
| `requestId` | `RequestId` | The identifier the sender gave the command |
| `command` | `Command` | `curtail`, `release`, `stop`, `start` or `reset` |
| `source` | `Source` | `cloud`: it came over the control topic. `edge`: it was given at the edge |
| `requestedBy` | `RequestedBy` | Who asked, as the sender wrote it; at most 120 characters. Empty when the command did not say |
| `issuedAt` | `IssuedAt` | When the sender wrote the command, by the sender's clock. Null for commands given at the edge |
| `ok` | `Ok` | True: taken. False: refused |
| `error` | `Error` | Why it was refused |
| `percent`, `limitKw` | `Percent`, `LimitKw` | `curtail`: the share of rated power the turbine may still produce, and the same in kW |
| `durationSeconds`, `endsAt` | `DurationSeconds`, `EndsAt` | `curtail`, `stop`: how long it lasts and when it ends by itself. Null: until released or started |
| `reason` | `Reason` | `stop`: `operator` or `maintenance`. Otherwise a note that came with the command |
| `turbinesInCommand` | `TurbinesInCommand` | How many turbines the command acted on; 0 for a refused one |

```json
{"messageType":"command","schemaVersion":"1.0","siteId":"northwind-ridge","assetId":"WT-03","timestamp":"2026-11-25T04:12:07.412Z","seq":5121,"data":{"requestId":"a1b2c3d4e5f6","command":"curtail","source":"cloud","requestedBy":"operations agent WindFarmGearboxWatch, approved in Teams","issuedAt":"2026-11-25T04:12:04Z","ok":true,"error":null,"percent":30.0,"limitKw":1260.0,"durationSeconds":3600,"endsAt":"2026-11-25T05:12:07.412Z","reason":null,"turbinesInCommand":1}}
```

## Commands

Commands are JSON objects published to `…/_sim/request`. The simulator replies on `…/_sim/response/{requestId}` with `{"requestId", "command", "ok", "timestamp", "result" | "error"}`. The `simctl` tool wraps this exchange; see [02-demo-runbook.md](02-demo-runbook.md).

| Command | Fields | Effect | Accepted on `_control/request` |
|---|---|---|---|
| `status` | | Wind, power, turbine states, active anomalies | No |
| `kinds` | | Lists the anomaly kinds | No |
| `inject` | `turbine`, `kind`, `severity` (0.05 to 1), `duration` (for example `15m`), `hold` | Starts an anomaly | No |
| `resolve` | `turbine` or `all`, optional `kind` | Ends anomalies; they ramp out | No |
| `wind` | `mean` (m/s), `duration`; or `clear` | Steers the site wind for a demo | No |
| `curtail` | `turbine` or `all`, `percent`, optional `duration` | Limits power to a percentage of rated | Yes |
| `release` | `turbine` or `all` | Removes the limit | Yes |
| `stop` | `turbine`, optional `reason`, `duration` | Stops a turbine; `reason` `maintenance` gives state `MAINTENANCE` | Yes |
| `start` | `turbine` or `all` | Removes a manual stop | Yes |
| `reset` | `turbine` or `all` | Clears a latched trip and latched derates | Yes |

Example:

```json
{"command": "inject", "requestId": "a1b2c3", "turbine": "WT-07", "kind": "gearbox_degradation", "severity": 0.8, "duration": "15m"}
```

## Reference files

Uploaded to the Lakehouse `Files` area by the reference data sync and loaded into `ref_` tables by notebook `01_load_reference_data`. Column names in these tables start with a lower-case letter, as in the files.

| File | Table | Content |
|---|---|---|
| `reference/site.json` | | Complete site definition: turbines, model, terrain parameters, the climate seed and the standing conditions. Also built into the simulator image, and read by the history notebooks. |
| `reference/site.csv` | `ref_site` | Site attributes, time zone, contract price, grid emission intensity |
| `reference/turbines.csv` | `ref_turbines` | Turbine master data and positions |
| `reference/components.csv` | `ref_components` | 11 components per turbine, with install date, warranty end and warranty contract |
| `reference/alarm_codes.csv` | `ref_alarm_codes` | Alarm catalogue: 40 codes. `liveSimulated` is true for the 17 that the live simulator raises; the others occur in the history only. |
| `reference/power_curve.csv` | `ref_power_curve` | Reference power by wind speed, at standard air density |
| `reference/spare_parts.csv` | `ref_spare_parts` | Stock, reorder point, lead time and cost |
| `reference/technicians.csv` | `ref_technicians` | The people of the site: role, discipline, certificates, on-call role |
| `reference/oncall_roster.csv` | `ref_oncall_roster` | Roles, escalation order, Teams channels |
| `reference/contracts.csv` | `ref_contracts` | Power purchase agreement, service agreement, drivetrain warranty, interconnection agreement, with price, guarantee, fee and terms |
| `reference/sop_index.csv` | `ref_sop_index` | SOP list with the alarm codes each covers |
| `reference/gis/*.geojson` | `ref_gis_features` | Turbines, roads, infrastructure, site boundary |
| `reference/terrain/heightmap.json` | `ref_terrain_grid` | 129 by 129 elevation grid over 6 km by 6 km |
| `sop/*.md` | `ref_sop_documents` | Seven operating procedures |

All of it is generated by `python -m windfarm_sim.sitegen` from one seed, except the SOP documents, which are written by hand. The catalogue of parts, people, contracts and fault types is `simulator/windfarm_sim/catalog.py`.

`reference/maintenance_history.csv` and the table `ref_maintenance_history` of version 1.0 are gone. Work orders are operating history: `ops_work_orders`.

## Operating history tables

Created in the Lakehouse by notebook `02_generate_history`; the forecast is kept current by `03_refresh_forecast`. Column names start with a capital letter, as in the Eventhouse. All times are UTC. Numbers that do not apply are NULL, not zero or an empty text.

[04-use-cases-and-data-audit.md](04-use-cases-and-data-audit.md) explains what the tables are for and defines the measures calculated from them.

### `ops_scada_10min`

One turbine in one 10-minute period. `Timestamp` is the start of the period. Signal columns are averages over the period unless the name says otherwise. In periods without communication the signals are empty and `AvailabilityCategory` is `Information unavailable`.

| Column | Meaning |
|---|---|
| `Timestamp` | Start of the 10-minute period, UTC |
| `TurbineId` | `WT-01` to `WT-12` |
| `State` | Operating state for most of the period: `RUNNING`, `DERATED`, `CURTAILED`, `IDLE`, `PAUSED`, `STOPPED`, `STOPPED_HIGH_WIND`, `MAINTENANCE`, `FAULT`, `UNKNOWN` |
| `AvailabilityCategory` | Category by IEC 61400-26; see the list in 04-use-cases-and-data-audit.md |
| `LossCause` | Why energy was lost in this period, or why none could be produced: `Component fault`, `Scheduled maintenance`, `Technical derate`, `Grid curtailment`, `Grid outage`, `Icing`, `High wind`, `Cable untwist`, `Low wind`. Empty in full performance. |
| `WindSpeed` | m/s, at the nacelle |
| `WindSpeedStd` | m/s, standard deviation within the period |
| `WindSpeedMax` | m/s, highest value in the period |
| `WindDirection` | deg, direction the wind comes from |
| `AmbientTemp` | degC |
| `AirDensity` | kg/m3 |
| `ActivePower` | kW |
| `ActivePowerMin` | kW, lowest value in the period |
| `ActivePowerMax` | kW, highest value in the period |
| `ReactivePower` | kvar |
| `PowerSetpoint` | kW, the limit in force: rated power, or less under curtailment or a derate |
| `PossiblePower` | kW, what the manufacturer's power curve gives for this wind and air density |
| `RotorSpeed` | rpm |
| `GeneratorSpeed` | rpm |
| `PitchAngle` | deg |
| `NacelleDirection` | deg, direction the nacelle points |
| `GearboxOilTemp` | degC |
| `GearboxBearingTemp` | degC, high-speed shaft bearing |
| `GearboxVibration` | mm/s RMS |
| `GeneratorWindingTemp` | degC |
| `GeneratorBearingTemp` | degC |
| `MainBearingTemp` | degC |
| `NacelleTemp` | degC |
| `EnergyKwh` | kWh delivered in the period |
| `PossibleEnergyKwh` | kWh that `PossiblePower` amounts to in the period |
| `LostEnergyKwh` | kWh lost to `LossCause`: possible minus delivered, in periods when the turbine was stopped or limited. Zero in full performance and in low wind. |

### `ops_met_10min`

The met mast in one 10-minute period: the wind before the turbines disturb it.

| Column | Meaning |
|---|---|
| `Timestamp` | Start of the period, UTC |
| `StationId` | `MET-01` |
| `WindSpeed` | m/s at hub height |
| `WindGust` | m/s |
| `WindDirection` | deg |
| `AmbientTemp` | degC |
| `Pressure` | hPa at the site |
| `Humidity` | % relative |
| `AirDensity` | kg/m3 |
| `IcingConditions` | True when it is cold and damp enough for ice to form on the blades |

### `ops_turbine_events`

One stop or outage of one turbine, from start to end: the availability log.

| Column | Meaning |
|---|---|
| `EventId` | Key |
| `TurbineId` |  |
| `StartTime` | UTC |
| `EndTime` | UTC; empty while the event is still running |
| `DurationHours` |  |
| `AvailabilityCategory` | As in `ops_scada_10min` |
| `Cause` | `Component fault` (needed a technician), `Auto-reset fault` (the controller restarted by itself), `Scheduled maintenance`, `Icing`, `High wind`, `Grid outage`, `Cable untwist` |
| `ComponentCode` | `GBX`, `GEN`, `CNV`, `PIT`, `YAW`, `HYD`, `BLD`, `TRF`, `TWR`, `CTL`, `GRID`; joins to `ref_components.componentCode` |
| `Component` | Name of the component |
| `AlarmCode` | The alarm that stopped the turbine |
| `FaultClass` | `A` reset by the controller, `B` fixed on site in hours, `C` major repair |
| `FailureMode` | What failed |
| `ResponsibleParty` | `Service provider`, `Operator`, `Grid operator` or `Environment`; decides what counts against the availability guarantee |
| `Description` |  |
| `LostEnergyMwh` | Energy lost during the event |
| `WorkOrderId` | The repair, when there was one |

### `ops_alarm_log`

One alarm from raised to cleared.

| Column | Meaning |
|---|---|
| `AlarmId` | Key |
| `TurbineId` |  |
| `AlarmCode` | Joins to `ref_alarm_codes.alarmCode` |
| `RaisedAt` | UTC |
| `ClearedAt` | UTC; empty while active |
| `DurationMinutes` |  |
| `EventId` | The stop this alarm belongs to, when there is one |

### `ops_work_orders`

One job of the maintenance system.

| Column | Meaning |
|---|---|
| `WorkOrderId` | Key, `WO-year-number` |
| `TurbineId` |  |
| `ComponentId` | Joins to `ref_components.componentId` |
| `WorkType` | `Preventive`, `Corrective`, `Inspection`, `OilAnalysis` |
| `Priority` | `Normal`, `High` |
| `Status` | `Closed`, `Open`, `Scheduled`, `In progress` |
| `OpenedDate` | UTC |
| `ScheduledDate` | UTC; planned start. In the past for an open order means overdue. |
| `ClosedDate` | UTC |
| `Summary` |  |
| `Findings` | What the technician found and did |
| `FailureMode` |  |
| `LaborHours` | Person-hours of the crew |
| `CrewSize` |  |
| `LaborCostUsd` | At 95 USD per person-hour |
| `PartsCostUsd` |  |
| `OtherCostUsd` | Crane, contractor, rope access |
| `TotalCostUsd` |  |
| `DowntimeHours` | From the fault to the return to service |
| `WaitingForPartsHours` | Part of the downtime spent waiting for a part or a crane |
| `LeadTechnicianId` | Joins to `ref_technicians.technicianId` |
| `EventId` | The outage this job repaired |
| `SopId` | Procedure followed |
| `CoveredByWarranty` |  |
| `CostBorneBy` | `Owner`, `Warranty` or `Service agreement`; follows `ref_contracts` |

### `ops_work_order_parts`

One spare part used on one job.

| Column | Meaning |
|---|---|
| `WorkOrderId` |  |
| `PartId` | Joins to `ref_spare_parts.partId` |
| `Quantity` |  |
| `UnitCostUsd` |  |
| `TotalCostUsd` |  |

### `ops_oil_analysis`

One laboratory result for a gearbox oil sample. Samples are taken at each half-yearly service and when a result calls for it.

| Column | Meaning |
|---|---|
| `SampleId` | Key |
| `TurbineId` |  |
| `ComponentId` |  |
| `SampleDate` |  |
| `IronPpm` | Wear metal of bearings and gears; the main indicator |
| `CopperPpm` |  |
| `SiliconPpm` | Dust |
| `WaterPpm` |  |
| `ViscosityAt40C` | mm2/s |
| `ParticleCountIso4406` | Cleanliness code |
| `Condition` | `Normal`, `Monitor`, `Action` |
| `LabComment` |  |

### `ops_blade_inspections`

One finding on one blade, from the yearly drone inspection or a special inspection.

| Column | Meaning |
|---|---|
| `InspectionId` | Key |
| `TurbineId` |  |
| `Blade` | `A`, `B`, `C` |
| `InspectionDate` |  |
| `Method` | `Drone`, `Rope access` |
| `FindingType` |  |
| `SeverityCategory` | 1 (cosmetic) to 5 (stop the turbine) |
| `SpanPositionM` | Distance from the blade root |
| `RecommendedAction` |  |
| `Status` | `Open`, `Monitor`, `Closed` |
| `RepairWorkOrderId` |  |

### `ops_curtailments`

One instruction to limit the output of the whole site.

| Column | Meaning |
|---|---|
| `CurtailmentId` | Key |
| `StartTime` | UTC |
| `EndTime` | UTC |
| `DurationHours` |  |
| `SetpointMw` | The limit |
| `SetpointPctOfCapacity` |  |
| `Reason` | Economic (negative price), congestion, or a test |
| `InstructedBy` | `Offtaker` or `Grid operator` |
| `Compensated` | True when the buyer pays for the curtailed energy at the contract price |
| `AvgRealTimePriceUsdPerMwh` |  |
| `LostEnergyMwh` | Energy the site could have produced above the limit |

### `ops_market_prices`

One hour at the site's settlement point.

| Column | Meaning |
|---|---|
| `Timestamp` | Start of the hour, UTC |
| `SettlementPoint` | `HB_WEST` |
| `DayAheadPriceUsdPerMwh` |  |
| `RealTimePriceUsdPerMwh` |  |

### `ops_power_forecast`

One hour of one forecast for the site. `Day-ahead` forecasts are issued every day at 10:00 site time for the next day and are all kept. The `Latest` forecast covers the coming 168 hours and is replaced at every refresh.

| Column | Meaning |
|---|---|
| `IssuedAt` | UTC |
| `TargetTime` | Start of the forecast hour, UTC |
| `ForecastType` | `Day-ahead` or `Latest` |
| `HorizonHours` | Hours from issue to target |
| `WindSpeed` | m/s, expected |
| `WindSpeedP10` | m/s, low value: exceeded in 9 of 10 cases |
| `WindSpeedP90` | m/s, high value: exceeded in 1 of 10 cases |
| `PowerMw` | Expected site power if nothing is stopped or limited |
| `PowerMwP10` | Low value |
| `PowerMwP90` | High value |
| `AmbientTemp` | degC |
| `IcingRisk` |  |

### `ops_monthly_budget`

One month of the owner's budget, from the first month of the history to the end of the current year.

| Column | Meaning |
|---|---|
| `YearMonth` | `yyyy-MM` |
| `Year` |  |
| `Month` |  |
| `P50EnergyMwh` | Budget energy: the long-term expectation after normal losses |
| `P90EnergyMwh` | Cautious case |
| `LongTermWindSpeed` | m/s, long-term mean wind speed of this calendar month at the met mast |
| `BudgetAvailabilityPct` |  |
| `BudgetRevenueUsd` | P50 energy at the contract price |
| `BudgetFixedOpexUsd` | Service agreement fee, land lease, insurance, staff. No actuals in the data. |
| `BudgetCorrectiveMaintenanceUsd` | Compare with corrective work orders paid by the owner |
| `BudgetOpexUsd` | Sum of the two |

### How the history relates to the live tables

| History (`ops_scada_10min`) | Live (`TurbineTelemetry`) |
|---|---|
| One row per turbine per 10 minutes | One row per turbine per 5 seconds |
| `ActivePower`, `WindSpeed`, temperatures, `GearboxVibration`: averages | The same signals, as read |
| `PossiblePower`, `EnergyKwh`, `LostEnergyKwh`, `AvailabilityCategory`, `LossCause` | Not in the live data; Phase 2 derives them |
| `State` | `State`, with the same values |
| Not in the history | `YawError`, `GearboxOilPressure`, `TransformerTemp`, `TowerVibration`, `HydraulicPressure`, `GridVoltage`, `GridFrequency`, `EnergyTotal` |
