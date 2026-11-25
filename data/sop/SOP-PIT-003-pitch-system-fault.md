# SOP-PIT-003: Pitch system fault

| | |
|---|---|
| Site | Northwind Ridge Wind Farm (fictional demo site) |
| Owner | Lead wind technician (TECH-01) |
| Applies to | PITCH-ASYM, PITCH-ASYM-CRIT, HYD-PRESS-LOW, TWR-VIB-HIGH |
| Component | Pitch system WH-PITCH-3A and hydraulic unit WH-HPU-200 (Woodgrove Hydraulics) |
| Revision | 4, 2026-07-08 |

> Demo content. This procedure was written for a fictional site and must not be used to operate real equipment.

## Background

Each blade has its own hydraulic pitch actuator. When one actuator lags or sticks, the blades no longer share the load evenly. The rotor becomes unbalanced, the tower vibrates once per revolution, and the turbine produces less power than its neighbours.

## Limits

| Signal | Normal | Warning | Critical |
|---|---|---|---|
| Blade pitch asymmetry | below 1 deg | 5 deg | 11 deg, derate to 40% |
| Hydraulic pressure | 180 to 192 bar | 160 bar | none |
| Tower vibration (RMS) | 0.3 to 0.9 mm/s | 2.5 mm/s | none |

## Step 1: Confirm the fault

Pitch asymmetry together with low hydraulic pressure and raised tower vibration confirms an actuator or valve problem. Tower vibration alone during gusty wind above 20 m/s is expected and needs no action.

## Step 2: Act

| Condition | Action |
|---|---|
| PITCH-ASYM only | Keep running. Review in 15 minutes. |
| PITCH-ASYM with TWR-VIB-HIGH | Curtail to 60% with approval of the on-call engineer. |
| PITCH-ASYM-CRIT | Keep the controller derate. Consult ENG-01. Stop the turbine if tower vibration exceeds 4 mm/s. |
| HYD-PRESS-LOW below 150 bar | Controlled stop. The blades may not reach the feathered position reliably. |

## Step 3: Follow-up

Raise a corrective work order. Usual causes, in order of frequency: sticking proportional valve (part SP-PIT-VLV), low accumulator pre-charge (part SP-PIT-ACC), failing hydraulic pump (part SP-HYD-PMP). WT-10 had a sticking valve on blade B in June 2026.

## Release criteria

Asymmetry below 2 deg, hydraulic pressure above 175 bar and tower vibration below 1.5 mm/s for 15 minutes, with engineer approval.
