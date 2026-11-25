# SOP-GBX-001: Gearbox high temperature or vibration

| | |
|---|---|
| Site | Northwind Ridge Wind Farm (fictional demo site) |
| Owner | Reliability engineer, drivetrain (ENG-01) |
| Applies to | GBX-OIL-TEMP-HIGH, GBX-OIL-TEMP-CRIT, GBX-OIL-TEMP-TRIP, GBX-VIB-HIGH, GBX-VIB-CRIT |
| Component | Gearbox FD-3P-97 (Fabrikam Drivetrain), three-stage, ratio 97:1 |
| Revision | 5, 2026-10-20 |

> Demo content. This procedure was written for a fictional site and must not be used to operate real equipment.

## Purpose

Protect the gearbox when oil temperature or drivetrain vibration rises, and separate a real mechanical problem from a sensor fault.

## Limits

| Signal | Normal at full load | Warning | Critical | Trip |
|---|---|---|---|---|
| Gearbox oil temperature | 60 to 70 degC | 78 degC | 88 degC, derate to 50% | 96 degC, stop |
| Gearbox vibration (RMS) | 1.5 to 2.5 mm/s | 5.5 mm/s | 8.0 mm/s, derate to 30% | none |
| Gearbox bearing temperature | 68 to 78 degC | no alarm, used as evidence | | |
| Gearbox oil pressure | 2.9 to 3.3 bar | no alarm, used as evidence | | |

The controller holds a protective derate for 5 minutes after the critical alarm clears. After a trip it restarts by itself only when every alarm has been clear for 10 minutes.

## Step 1: Confirm the fault

Check the last 30 minutes of the affected turbine against the two nearest turbines.

| Evidence | Mechanical fault (bearing or gear damage) | Cooling problem | Sensor fault |
|---|---|---|---|
| Oil temperature | Rising | Rising | Rising, flat or jumping |
| Vibration | Rising with oil temperature | Normal | Normal |
| Bearing temperature | Rising | Rising slowly | Normal |
| Oil pressure | Falling | Normal or falling slightly | Normal |
| Power against neighbours | Lower | Normal until derated | Normal until derated |

- Vibration and temperature rising together means a mechanical fault. Go to step 2.
- Oil temperature high with normal vibration and normal bearing temperature means a sensor fault is likely. Raise a work order to replace the PT100 sensor (part SP-SNS-PT100) and keep the turbine under observation. Do not curtail.
- Oil temperature and bearing temperature high with normal vibration means a cooling problem. Check the oil cooler fan (part SP-GBX-CLR-FAN) and filter differential pressure.

## Step 2: Protect the gearbox

1. Review the maintenance history of the gearbox. Rising iron particle counts in recent oil analyses make bearing damage the working assumption.
2. Consult the on-call reliability engineer (ENG-01) through Teams channel "Reliability On-Call". Share the evidence table.
3. With the engineer's approval, apply the action below.

| Condition | Action |
|---|---|
| Warning only, values stable | Keep running. Review again in 15 minutes. |
| Warning, vibration above 6.5 mm/s or still rising | Curtail the turbine to 50% of rated power. |
| Critical (controller derate active) | Curtail to 30% of rated power so the limit stays in place after the controller releases its derate. |
| Critical for more than 20 minutes, or bearing temperature above 95 degC | Controlled stop. Do not restart without an inspection. |
| Trip | Leave stopped. Follow step 3. |

A curtailed gearbox still earns revenue and usually stays within limits. A stop is preferred only when values keep rising while curtailed.

## Step 3: Follow-up

1. Raise a corrective work order on the gearbox with the alarm times and peak values.
2. Request a borescope inspection of the high-speed shaft bearing and an oil sample. Check stock of the bearing kit (part SP-GBX-HSS-BRG, 21 days lead time when not in stock).
3. If an inspection is already scheduled for this gearbox, ask the engineer whether to bring it forward.

## Restart and release criteria

The curtailment may be released, or the turbine restarted after a stop, when all of these hold:

- oil temperature below 75 degC and vibration below 4.5 mm/s for 15 minutes,
- the engineer has approved the release,
- a work order records the event.

## Cost of delay

Lost energy is estimated from the turbine's power against the average of its two nearest neighbours, priced at the site's power purchase price (38.50 USD per MWh). A gearbox exchange costs about 385,000 USD and 140 days lead time when no exchange unit is in stock, which is why early curtailment is preferred over running to failure.
