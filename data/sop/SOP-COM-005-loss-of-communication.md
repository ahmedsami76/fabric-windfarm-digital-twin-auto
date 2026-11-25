# SOP-COM-005: Loss of communication

| | |
|---|---|
| Site | Northwind Ridge Wind Farm (fictional demo site) |
| Owner | Control room (OPS-01, OPS-02) |
| Applies to | COMMS-RESTORED, and any gap in turbine data |
| Revision | 3, 2026-08-27 |

> Demo content. This procedure was written for a fictional site and must not be used to operate real equipment.

## Background

Each turbine controller reports to the site edge server over the site fibre ring. The edge server forwards the data to the cloud. A gap in the data does not mean the turbine has stopped: the controller keeps operating and protecting the turbine by itself. Alarms raised during a gap are buffered and forwarded with their original timestamps when communication returns.

## Classify the gap

| What is missing | Likely cause | Action |
|---|---|---|
| One turbine, less than 2 minutes | Switch or controller restart | None. Note it if it recurs more than three times a day. |
| One turbine, more than 10 minutes | Fibre, switch or controller fault | Work order for the site technician. Check the turbine from the substation meter. |
| All turbines on one string | String switch or fibre break | Call the lead technician (TECH-01). |
| All turbines and the met mast, heartbeat still arriving | Site network between turbines and edge server | Call the lead technician (TECH-01). |
| Everything including the edge heartbeat | Edge server or its cloud connection | Check the edge server and its outbound connection. The edge buffers data while the cloud link is down. |

## After communication returns

1. Review alarms that arrived with timestamps inside the gap.
2. Confirm that the turbine's energy counter advanced during the gap. If it did, the turbine kept producing.
3. Do not count the gap as downtime in availability reports when the energy counter shows production.
