# SOP-OPS-000: Alarm triage and escalation

| | |
|---|---|
| Site | Northwind Ridge Wind Farm (fictional demo site) |
| Owner | Site manager (MGR-01) |
| Applies to | All turbine alarms |
| Revision | 3, 2026-09-15 |

> Demo content. This procedure was written for a fictional site and must not be used to operate real equipment.

## Purpose

Give the control room one way to classify an alarm, decide who must be consulted and record what was done.

## Severity classes

| Severity | Meaning | Response time | Who acts |
|---|---|---|---|
| Info | Expected controller event (cable untwist, high-wind stop, communication restored, curtailment) | None | Control room notes it |
| Warning | A limit was crossed; the turbine keeps running | Review within 15 minutes | Control room operator (OPS-01 or OPS-02) |
| Critical | The controller derated or stopped the turbine to protect a component | Act within 5 minutes | Control room operator, with the on-call engineer |

## Triage steps

1. Identify the turbine, the alarm code and the component from the alarm list.
2. Check whether the alarm is confirmed by a second signal. A single signal with no supporting evidence is treated as a possible sensor fault until proven otherwise.
3. Compare the turbine with its neighbours on the same string for the same period. A fault shows on one turbine; weather shows on all of them.
4. Open the component SOP named on the alarm (column `sopId` of the alarm catalogue).
5. Check open and recent work orders for the component.

## Escalation matrix

| Situation | Consult before acting | Channel |
|---|---|---|
| Warning, confirmed by a second signal | Lead technician (TECH-01) | Teams: Site Maintenance |
| Critical on gearbox, main bearing or blades | Reliability engineer, drivetrain (ENG-01) | Teams: Reliability On-Call |
| Critical on generator, converter or transformer | Electrical engineer (ENG-02), or ENG-01 out of hours | Teams: Reliability On-Call |
| Turbine tripped twice within 24 hours | Reliability engineer and site manager | Teams: Reliability On-Call |
| Three or more turbines affected at once | Site manager (MGR-01) | Teams: Site Leadership |

## Actions that need approval

| Action | May be taken by | Approval needed |
|---|---|---|
| Acknowledge an alarm | Control room | None |
| Remote curtailment of one turbine | Control room | On-call engineer |
| Remote stop of one turbine | Control room | On-call engineer, except for an immediate safety risk |
| Remote reset and restart after a trip | Control room | On-call engineer, after the component SOP restart criteria are met |
| Create a work order | Control room or engineer | None |

An automated agent may propose any of these actions. It may carry out a curtailment, stop, reset or restart only after the named engineer has approved that specific action for that specific turbine.

## Records

Every critical alarm ends with a log entry: turbine, alarm, evidence checked, who was consulted, action, time of return to normal operation, and the work order number if one was raised.
