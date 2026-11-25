# SOP-YAW-004: Yaw misalignment

| | |
|---|---|
| Site | Northwind Ridge Wind Farm (fictional demo site) |
| Owner | Reliability engineer, drivetrain (ENG-01) |
| Applies to | No controller alarm. Found by analysis. |
| Component | Yaw system CT-YAW-6D and nacelle wind vane |
| Revision | 2, 2026-05-11 |

> Demo content. This procedure was written for a fictional site and must not be used to operate real equipment.

## Background

The turbine points itself using the wind vane on the nacelle. If the vane is miscalibrated, the controller believes it faces the wind while the rotor is in fact turned away from it. The reported yaw error stays near zero, so no alarm is raised. The only signs are a power deficit and a nacelle direction that differs from the neighbouring turbines.

Power falls roughly with the cube of the cosine of the misalignment angle:

| Misalignment | Power lost |
|---|---|
| 5 deg | 1% |
| 10 deg | 4% |
| 15 deg | 10% |
| 20 deg | 17% |
| 30 deg | 35% |

## How to detect it

1. Over at least 30 minutes of steady wind between 6 and 11 m/s, compare the turbine's nacelle direction with the median nacelle direction of the turbines on the same string.
2. A persistent difference above 8 deg, together with power below the neighbours at similar wind speed, indicates misalignment.
3. Rule out a wake: a turbine directly downwind of another also produces less, but its nacelle direction matches its neighbours.

## Action

Misalignment costs energy but does not endanger the turbine. No curtailment or stop is needed.

1. Raise a work order for a wind vane calibration check (part SP-YAW-VANE if replacement is needed).
2. Estimate the lost energy from the table above and record it on the work order so that the visit can be prioritised.

WT-05 has an open work order for a deviation of about 9 deg found in October 2026.
