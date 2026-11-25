# SOP-CUR-006: Remote curtailment, stop and restart

| | |
|---|---|
| Site | Northwind Ridge Wind Farm (fictional demo site) |
| Owner | Site manager (MGR-01) |
| Applies to | POWER-CURTAILED, MANUAL-STOP, and every remote control action |
| Revision | 4, 2026-10-01 |

> Demo content. This procedure was written for a fictional site and must not be used to operate real equipment.

## Purpose

Define how a turbine is limited, stopped and returned to service from the control room, and who must agree.

## Available remote actions

| Action | Effect | Typical use |
|---|---|---|
| Curtail to a percentage of rated power | The turbine pitches its blades to hold power at or below the setpoint. Rated power is 4,200 kW. | Protect a component while keeping some production. Grid operator instruction. |
| Release | Removes the setpoint. The turbine returns to normal operation. | End of a protective or grid curtailment. |
| Stop | Blades feather and the rotor is braked. The turbine consumes about 12 kW. | Maintenance, or a fault that curtailment does not contain. |
| Start | Removes a manual stop. The turbine starts when wind allows. | Return to service. |
| Reset | Clears a latched trip and latched derates. | After the cause of a trip has been understood. |

## Rules

1. One turbine at a time. Site-wide actions are taken only on instruction of the grid operator or the site manager.
2. Every curtailment, stop, reset and restart for a component fault needs the approval of the on-call engineer named in SOP-OPS-000. Record the engineer and the time.
3. State the reason and a review time when applying a curtailment. A curtailment without a review time is not allowed.
4. Never reset a trip more than once without an inspection.
5. Before a restart, confirm that the release criteria of the component SOP are met.

## Standard protective setpoints

| Situation | Setpoint | Review after |
|---|---|---|
| Gearbox warning, values rising | 50% | 15 minutes |
| Gearbox critical | 30% | 15 minutes |
| Generator warning | 70% | 15 minutes |
| Generator critical | 50% | 15 minutes |
| Pitch asymmetry with tower vibration | 60% | 15 minutes |

## Sequence for an automated agent

1. Detect the condition and collect the evidence required by the component SOP.
2. Send the on-call engineer a recommendation: turbine, evidence, proposed action, setpoint and review time, and the estimated cost of acting and of not acting.
3. Wait for approval. No approval means no action.
4. Apply the approved action and confirm from telemetry that it took effect within 2 minutes.
5. Review at the review time and propose release or a further step.
6. Record the event and raise or update the work order.
