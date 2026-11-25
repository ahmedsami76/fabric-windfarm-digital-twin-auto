"""Phase 3 in one place: the data agent, the ontology and the operations agent.

tools/build-phase3.py turns this file into the notebooks 09 to 11, the files under fabric/data-agent,
fabric/ontology and fabric/operations-agent, and docs/10-ontology.md. Change things here, then run
    python3 tools/build-phase3.py
"""
from __future__ import annotations

LAKEHOUSE = "WindFarmLH"
KQL_DATABASE = "WindFarmEH"
EVENTHOUSE = "WindFarmEH"
SEMANTIC_MODEL = "WindFarm Operations"
DATA_AGENT = "WindFarmDataAgent"
ONTOLOGY = "WindFarmOntology"
OPERATIONS_AGENT = "WindFarmGearboxWatch"

# Versions the notebooks install. The calls in the notebooks were read from the source of exactly these.
SDK_PIN = "fabric-data-agent-sdk==0.1.36a0"
LABS_PIN = "semantic-link-labs==0.15.2"

# --------------------------------------------------------------------------------------------- data agent
AGENT_DESCRIPTION = ("Answers questions about the Northwind Ridge wind farm: production, availability, losses, faults, "
                     "maintenance, spare parts, contracts and the live state of the turbines.")

AGENT_INSTRUCTIONS = """\
You answer questions from the people who run one wind farm: the site manager, performance and reliability
engineers, the maintenance planner, the asset manager and the control room operator.

Which source to use
- The KQL database WindFarmEH holds the live data. Use it only when the question is about right now or the
  last 24 hours: what a turbine is doing, which alarms are active, current power, live temperature or vibration.
- The lakehouse WindFarmLH holds everything else. Use it for any period longer than 24 hours ("last week",
  "last 90 days", "this year", "by month"), for budgets, events, work orders, parts, contracts and people.
- Three kinds of question always go to the lakehouse, even when they sound like "now":
  what an alarm code means, what the controller does and which procedure applies (ref_alarm_codes, ref_sop_index);
  the forecast for the coming hours and days (ops_power_forecast);
  whether a turbine is misaligned, underperforming or drifting away from the fleet, which needs weeks of data.
- If a question needs both, answer the history from the lakehouse first, then the live part from the KQL
  database, and say which part came from where.

Time
- All times are UTC.
- In the lakehouse, "now" is the newest Timestamp in ops_scada_10min, not the clock. "Last 90 days" and
  "last 12 months" count back from that moment.
- "Last month" is the last complete calendar month. "Last 6 months" and "last 12 months" count back from
  "now" to the day, like "last 90 days"; they are not calendar months unless the question says "by month".
- "Year to date" runs from 1 January of the year of "now" to "now". A budget for the year to date counts the
  running month pro rata by days.
- Say which period the answer covers.

Definitions that must not change
- Energy is the sum of EnergyKwh. Report it in MWh (divide by 1000).
- Lost energy is the sum of LostEnergyKwh, by LossCause. Its value is lost MWh x ppaPriceUsdPerMwh for every
  cause, curtailment included, whether or not the offtaker paid for it.
- Time availability = 1 - (10-minute periods with AvailabilityCategory 'Forced outage', 'Scheduled maintenance'
  or 'Planned corrective action') / (all periods except 'Information unavailable').
- Energy availability = energy / (energy + lost energy with LossCause 'Component fault', 'Scheduled maintenance',
  'Corrective maintenance' or 'Technical derate'). Curtailment, icing, high wind and grid causes do not count
  against the turbine.
- Capacity factor = energy / (rated power x hours). One 10-minute period at rated power is ratedPowerKw / 6 kWh.
- A failure is an event with Cause 'Component fault'. Faults the controller reset by itself are
  Cause 'Auto-reset fault' and are counted separately.
- Revenue = (energy in MWh + compensated curtailment in MWh) x ppaPriceUsdPerMwh of ref_site. Compensated
  curtailment is the LostEnergyMwh of ops_curtailments where Compensated = 1: the offtaker pays for it as if
  it had been produced. Use market prices only when the question asks for them.
- Performance index = energy / possible energy over the periods with AvailabilityCategory 'Full performance'
  only. It is close to 1; a turbine at 0.95 underperforms. Never compute it over all periods.
- Forecast accuracy compares the day-ahead forecast (ForecastType 'Day-ahead') with possible power, hour by
  hour, as a percentage of site capacity, so that outages and curtailment do not count as forecast error.
- Repair cost is the TotalCostUsd of closed corrective work orders. CostBorneBy says who pays: 'Owner',
  'Warranty' or 'Service agreement'. Compare the owner's part with the corrective maintenance budget.
- A major failure is an event with FaultClass 'C'.
- A repeat offender is a turbine and component with many forced outages in the last 12 months. Count every
  forced outage for this, including the trips that reset by themselves, and show how many needed a technician.
- "At the same load" means: only periods with State 'RUNNING' and high ActivePower, as in the example queries,
  so that a turbine is not compared with others that ran harder or lighter.
- Alarms are counted from ops_alarm_log, one row per alarm, grouped through ref_alarm_codes. Stops and derates
  are counted from ops_turbine_events. They are different things: never add the two together.
- The contractual availability of the service agreement has its own rules (contract CT-SMA-001). Follow the
  example query for it exactly; do not use time availability in its place.

How to answer
- When an example query fits the question, keep its tables, its filters and its period, and change only what the
  question changes: the turbine, the component or the number of days.
- Give the number first, with its unit and period. Then one or two sentences on what stands out.
- Name the turbine (WT-01 to WT-12), the component or the work order. Do not answer in general terms.
- The data covers one site, Northwind Ridge, and nothing outside it: no other wind farms, no wildlife or
  environmental records, no remaining-life estimates, no staff records beyond the technician list.
- If no table has a column for the thing asked, say that the data does not record it and say what is missing.
  Do not answer 0, do not estimate, and do not put another figure in its place.
- If a query fails or returns no rows, look at the example queries again and try once more before you say that
  there is no data. A table that is in the schema has data.
- Do not give advice on electrical or mechanical safety. Point to the procedure (sopId) instead.
"""

LAKEHOUSE_DESCRIPTION = ("Everything except the last 24 hours. "
                         "History of the wind farm: 10-minute SCADA periods with energy, lost energy and availability "
                         "category, downtime events, work orders and parts, alarms, oil samples, blade inspections, "
                         "budget, market prices, the power forecast for the coming week, contracts, spare parts, technicians, "
                         "and the catalogue of alarm codes with the procedure for each.")

LAKEHOUSE_INSTRUCTIONS = """\
Names are case sensitive. Tables that start with ops_ use PascalCase columns (TurbineId, Timestamp, EnergyKwh).
Tables that start with ref_ use camelCase columns (turbineId, ratedPowerKw, sopId). Write names exactly as in the schema.
Put [Timestamp], [file], [role], [Year] and [Month] in square brackets.

"Now" is (SELECT MAX([Timestamp]) FROM ops_scada_10min). Never use GETDATE() or SYSUTCDATETIME().

ops_scada_10min: one row per turbine per 10 minutes. EnergyKwh, PossibleEnergyKwh and LostEnergyKwh are for that
period. AvailabilityCategory is one of 'Full performance', 'Partial performance', 'Technical standby',
'Out of environmental specification', 'Requested shutdown', 'Out of electrical specification', 'Forced outage',
'Scheduled maintenance', 'Information unavailable'. LossCause says what the lost energy was lost to: 'Component fault',
'Technical derate', 'Scheduled maintenance', 'Grid curtailment', 'Grid outage', 'Icing', 'High wind', 'Low wind',
'Cable untwist'.
ops_turbine_events: one row per stop or derate, with Cause, Component, ComponentCode ('GBX', 'GEN', 'PIT', 'YAW',
'CNV', 'HYD', 'BLD', 'TRF', 'TWR', 'CTL', 'GRID'), AlarmCode, DurationHours, LostEnergyMwh, ResponsibleParty
('Service provider', 'Operator', 'Grid operator', 'Environment') and the WorkOrderId that fixed it. FaultClass is
'A' for a trip that was reset without a repair, 'B' for a minor repair, 'C' for a major repair.
ops_work_orders: one row per work order. Status is 'Open', 'Scheduled' or 'Closed'. WorkType is 'Corrective',
'Preventive', 'Inspection' or 'OilAnalysis'. OpenedDate, ScheduledDate and ClosedDate are date-times; ScheduledDate
is the date the work is due. CostBorneBy is 'Owner', 'Warranty' or 'Service agreement'. WaitingForPartsHours is the
part of the downtime spent waiting. CoveredByWarranty is a bit (1 = yes).
ops_power_forecast: one row per hour (TargetTime, UTC). ForecastType 'Latest' is the newest forecast for the next
seven days: use it for anything about the coming days. ForecastType 'Day-ahead' is the forecast made the day before,
kept for every past hour: use it to measure forecast accuracy. WindSpeedP90 is the wind speed that is unlikely to be
exceeded. Site time is UTC converted with AT TIME ZONE 'UTC' AT TIME ZONE 'Central Standard Time'.
ops_oil_analysis: gearbox oil samples per turbine with SampleDate, IronPpm, CopperPpm, WaterPpm, Condition, LabComment.
ops_market_prices: one row per hour ([Timestamp] is the start of the hour) with day-ahead and real-time price.
ops_met_10min: the met mast, one row per 10 minutes. Join to ops_scada_10min on [Timestamp].
ops_work_order_parts: the parts each work order used. Join to ref_spare_parts on PartId = partId.
ops_alarm_log: one row per alarm with RaisedAt and ClearedAt. Join to ref_alarm_codes on AlarmCode = alarmCode.
ops_monthly_budget: one row per month. Join on [Year] and [Month], or on YearMonth ('yyyy-MM').
ops_curtailments: Compensated is a bit (1 = paid for).
ref_site has one row. CROSS JOIN it to get ppaPriceUsdPerMwh and capacityMw.
ref_turbines: 12 turbines, WT-01 to WT-12, ratedPowerKw each.
ref_alarm_codes and ref_sop_index: what an alarm means, what the controller does, and the procedure (sopId).
ref_oncall_roster and ref_technicians: who is on call. onCall is a bit. Join on onCallRoleId = roleId.
ref_components and ref_contracts: warranty per component. Join on warrantyContractId = contractId.

T-SQL only. No LIMIT (use TOP with ORDER BY), no DATE_TRUNC, no ADD_MONTHS, no LEAST or GREATEST (use CASE).
The % operator does not accept float columns: for an angle write x - 360 * FLOOR(x / 360).
The first day of a month is DATEFROMPARTS(YEAR(d), MONTH(d), 1). A month as a number is YEAR(d) * 100 + MONTH(d).
The Monday of a week is DATEADD(day, -(DATEDIFF(day, CAST('1900-01-01' AS date), CAST(d AS date)) % 7), CAST(d AS date)).
Text is compared exactly, upper and lower case included. ref_alarm_codes.component is lower case: 'gearbox',
'pitch system', 'yaw system', 'generator', 'converter', 'hydraulic system', 'blades', 'tower', 'controller', 'grid',
'environment', 'scada'. ops_turbine_events.Component starts with a capital: 'Gearbox', 'Pitch system', 'Yaw system',
'Generator', 'Converter', 'Hydraulic unit', 'Blade set', 'Tower', 'Transformer', 'Controller', 'Grid connection'.
ref_components.componentType starts with a capital too: 'Gearbox', 'Generator', 'Main bearing', 'Pitch system'.
When you are not sure how a text value is spelled, compare in lower case: LOWER(c.componentType) LIKE '%gearbox%'.
Divide with a decimal: 1.0 * a / b, never integer by integer. Return at most 25 rows.
"""

LAKEHOUSE_TABLES = [
    "ops_scada_10min", "ops_turbine_events", "ops_work_orders", "ops_work_order_parts", "ops_alarm_log",
    "ops_oil_analysis", "ops_blade_inspections", "ops_monthly_budget", "ops_curtailments", "ops_market_prices",
    "ops_power_forecast", "ops_met_10min", "ref_site", "ref_turbines", "ref_components", "ref_contracts",
    "ref_alarm_codes", "ref_sop_index", "ref_spare_parts", "ref_technicians", "ref_oncall_roster", "ref_power_curve",
]

KQL_DESCRIPTION = ("Live data of the wind farm from the edge, a few seconds old: telemetry of every turbine, weather at the "
                   "met mast, alarms as they are raised and cleared, and state changes. Only for right now and the last 24 "
                   "hours. Not for periods of days or months, not for what an alarm code means, not for forecasts.")

KQL_INSTRUCTIONS = """\
TurbineTelemetry: one row per turbine every few seconds. ActivePower and PowerSetpoint are kW, WindSpeed is m/s,
temperatures are degrees Celsius, GearboxVibration is mm/s. State is RUNNING, DERATED, CURTAILED, IDLE, PAUSED,
STOPPED, STOPPED_HIGH_WIND, MAINTENANCE or FAULT.
The latest row per turbine: TurbineTelemetry | where Timestamp > ago(10m) | summarize arg_max(Timestamp, *) by TurbineId.
AlarmEvents: one row when an alarm is raised (Status 'raised') and one when it clears (Status 'cleared'), linked
by AlarmId. An alarm is active when its latest row has Status 'raised'. SopId is the procedure.
TurbineStateChanges: one row each time a turbine changes state, with the Reason.
WeatherObservations: the met mast, one row every few seconds.
Always filter on Timestamp first (ago(15m), ago(1h), ago(24h)). Site power is the sum over turbines of the
average ActivePower per turbine, divided by 1000 for MW. All times are UTC.
Use this source only for the last 24 hours. It does not explain alarm codes, it holds no forecast, and it holds
no history: for those, use the lakehouse.
"""

KQL_TABLES = ["TurbineTelemetry", "AlarmEvents", "TurbineStateChanges", "WeatherObservations"]

_ASOF = "WITH asof AS (SELECT MAX([Timestamp]) AS AsOf FROM ops_scada_10min)"
_DOWN = "('Forced outage', 'Scheduled maintenance', 'Planned corrective action')"
_TECHNICAL = "('Component fault', 'Scheduled maintenance', 'Corrective maintenance', 'Technical derate')"

# Example queries for the lakehouse, in T-SQL. Key: id of the question in tools/question_bank.py. Each returns
# what the Spark SQL of that question returns; tools/check-tsql-examples.py compares the two.
TSQL_EXAMPLES = {
    "SM-01": f"""{_ASOF},
m AS (SELECT DATEADD(month, -1, DATEFROMPARTS(YEAR(AsOf), MONTH(AsOf), 1)) AS MonthStart,
             DATEFROMPARTS(YEAR(AsOf), MONTH(AsOf), 1) AS MonthEnd FROM asof)
SELECT MAX(b.YearMonth) AS YearMonth,
       ROUND(SUM(s.EnergyKwh) / 1000, 0) AS EnergyMwh,
       MAX(b.P50EnergyMwh) AS BudgetP50Mwh,
       MAX(b.P90EnergyMwh) AS BudgetP90Mwh,
       ROUND(100 * SUM(s.EnergyKwh) / 1000 / MAX(b.P50EnergyMwh), 1) AS PctOfBudget
FROM ops_scada_10min AS s
CROSS JOIN m
JOIN ops_monthly_budget AS b ON b.[Year] = YEAR(m.MonthStart) AND b.[Month] = MONTH(m.MonthStart)
WHERE s.[Timestamp] >= m.MonthStart AND s.[Timestamp] < m.MonthEnd""",
    "SM-03": f"""{_ASOF}
SELECT s.TurbineId,
       ROUND(100 * (1 - 1.0 * SUM(CASE WHEN s.AvailabilityCategory IN {_DOWN} THEN 1 ELSE 0 END) / COUNT(*)), 2) AS TimeAvailabilityPct,
       ROUND(100 * SUM(s.EnergyKwh) / (SUM(s.EnergyKwh)
             + SUM(CASE WHEN s.LossCause IN {_TECHNICAL} THEN s.LostEnergyKwh ELSE 0 END)), 2) AS EnergyAvailabilityPct,
       ROUND(SUM(CASE WHEN s.AvailabilityCategory = 'Forced outage' THEN 1 ELSE 0 END) / 6.0, 1) AS ForcedOutageHours,
       ROUND(SUM(s.EnergyKwh) / 1000, 0) AS EnergyMwh
FROM ops_scada_10min AS s
CROSS JOIN asof AS a
WHERE s.[Timestamp] >= DATEADD(day, -90, a.AsOf) AND s.AvailabilityCategory <> 'Information unavailable'
GROUP BY s.TurbineId
ORDER BY TimeAvailabilityPct""",
    "SM-04": f"""{_ASOF}
SELECT s.LossCause,
       ROUND(SUM(s.LostEnergyKwh) / 1000, 0) AS LostEnergyMwh,
       ROUND(SUM(s.LostEnergyKwh) / 1000 * MAX(st.ppaPriceUsdPerMwh), 0) AS ValueAtContractPriceUsd,
       ROUND(100 * SUM(s.LostEnergyKwh) / SUM(SUM(s.LostEnergyKwh)) OVER (), 1) AS SharePct
FROM ops_scada_10min AS s
CROSS JOIN asof AS a
CROSS JOIN ref_site AS st
WHERE s.[Timestamp] >= DATEADD(month, -12, a.AsOf) AND s.LostEnergyKwh > 0
GROUP BY s.LossCause
ORDER BY LostEnergyMwh DESC""",
    "SM-05": f"""{_ASOF}
SELECT w.WorkOrderId, w.TurbineId, w.WorkType, w.Priority, w.Status,
       CAST(w.ScheduledDate AS date) AS ScheduledDay,
       DATEDIFF(day, a.AsOf, w.ScheduledDate) AS DaysFromNow,
       CASE WHEN w.ScheduledDate < a.AsOf THEN 'Overdue'
            WHEN w.ScheduledDate < DATEADD(day, 30, a.AsOf) THEN 'Next 30 days'
            ELSE 'Later' END AS Timing,
       w.Summary, t.name AS LeadTechnician
FROM ops_work_orders AS w
CROSS JOIN asof AS a
LEFT JOIN ref_technicians AS t ON t.technicianId = w.LeadTechnicianId
WHERE w.Status <> 'Closed'
ORDER BY w.ScheduledDate""",
    "SM-06": """SELECT partId, description, componentCode, quantityOnHand, reorderPoint, leadTimeDays, unitCostUsd
FROM ref_spare_parts
WHERE quantityOnHand <= reorderPoint
ORDER BY leadTimeDays DESC""",
    "RE-01": f"""{_ASOF}
SELECT e.Component,
       COUNT(*) AS Failures,
       ROUND(SUM(e.DurationHours), 0) AS DowntimeHours,
       ROUND(AVG(e.DurationHours), 1) AS MeanTimeToRepairHours,
       ROUND(SUM(e.LostEnergyMwh), 0) AS LostEnergyMwh,
       ROUND(SUM(w.TotalCostUsd), 0) AS RepairCostUsd
FROM ops_turbine_events AS e
LEFT JOIN ops_work_orders AS w ON w.WorkOrderId = e.WorkOrderId
CROSS JOIN asof AS a
WHERE e.Cause = 'Component fault' AND e.StartTime >= DATEADD(month, -12, a.AsOf)
GROUP BY e.Component
ORDER BY LostEnergyMwh DESC""",
    "RE-02": f"""{_ASOF}
SELECT t.turbineId AS TurbineId,
       COUNT(CASE WHEN e.Cause = 'Component fault' THEN 1 END) AS Failures,
       COUNT(CASE WHEN e.Cause = 'Auto-reset fault' THEN 1 END) AS AutoResets,
       ROUND(COALESCE(SUM(CASE WHEN e.Cause = 'Component fault' THEN e.DurationHours END), 0), 0) AS DowntimeHours,
       ROUND(AVG(CASE WHEN e.Cause = 'Component fault' THEN e.DurationHours END), 1) AS MeanTimeToRepairHours,
       ROUND((8760 - COALESCE(SUM(CASE WHEN e.Cause = 'Component fault' THEN e.DurationHours END), 0))
             / NULLIF(COUNT(CASE WHEN e.Cause = 'Component fault' THEN 1 END), 0), 0) AS MeanTimeBetweenFailuresHours
FROM ref_turbines AS t
CROSS JOIN asof AS a
LEFT JOIN ops_turbine_events AS e
       ON e.TurbineId = t.turbineId AND e.AvailabilityCategory = 'Forced outage'
      AND e.StartTime >= DATEADD(month, -12, a.AsOf)
GROUP BY t.turbineId
ORDER BY Failures DESC, TurbineId""",
    "RE-09": f"""{_ASOF}
SELECT c.componentType, COUNT(*) AS Components, c.warrantyEndDate,
       DATEDIFF(day, a.AsOf, c.warrantyEndDate) AS DaysLeft,
       c.warrantyContractId, k.counterparty, k.terms
FROM ref_components AS c
CROSS JOIN asof AS a
LEFT JOIN ref_contracts AS k ON k.contractId = c.warrantyContractId
WHERE c.warrantyEndDate >= CAST(a.AsOf AS date)
GROUP BY c.componentType, c.warrantyEndDate, a.AsOf, c.warrantyContractId, k.counterparty, k.terms
ORDER BY c.warrantyEndDate, c.componentType""",
    "MP-04": f"""{_ASOF},
used AS (
    SELECT p.PartId, SUM(p.Quantity) AS Quantity
    FROM ops_work_order_parts AS p
    JOIN ops_work_orders AS w ON w.WorkOrderId = p.WorkOrderId
    CROSS JOIN asof AS a
    WHERE w.OpenedDate >= DATEADD(month, -12, a.AsOf) AND w.Status = 'Closed'
    GROUP BY p.PartId)
SELECT TOP 12 sp.partId, sp.description,
       COALESCE(u.Quantity, 0) AS UsedInLast12Months,
       sp.quantityOnHand, sp.reorderPoint, sp.leadTimeDays,
       ROUND(sp.quantityOnHand / (u.Quantity / 12.0), 1) AS MonthsOfStock
FROM ref_spare_parts AS sp
LEFT JOIN used AS u ON u.PartId = sp.partId
ORDER BY UsedInLast12Months DESC, sp.partId""",
    "AM-02": f"""{_ASOF}
SELECT c.Reason, c.InstructedBy, c.Compensated,
       COUNT(*) AS Events,
       ROUND(SUM(c.DurationHours), 0) AS Hours,
       ROUND(SUM(c.LostEnergyMwh), 0) AS CurtailedMwh,
       ROUND(SUM(CASE WHEN c.Compensated = 1 THEN 0 ELSE c.LostEnergyMwh END) * MAX(st.ppaPriceUsdPerMwh), 0) AS RevenueLostUsd,
       ROUND(AVG(c.AvgRealTimePriceUsdPerMwh), 1) AS MeanRealTimePrice
FROM ops_curtailments AS c
CROSS JOIN asof AS a
CROSS JOIN ref_site AS st
WHERE c.StartTime >= DATEADD(month, -12, a.AsOf)
GROUP BY c.Reason, c.InstructedBy, c.Compensated
ORDER BY CurtailedMwh DESC""",
    "OP-01": """SELECT c.alarmCode, c.severity, c.description, c.threshold, c.unit, c.controllerAction, c.sopId,
       s.title AS ProcedureTitle, s.[file]
FROM ref_alarm_codes AS c
LEFT JOIN ref_sop_index AS s ON s.sopId = c.sopId
WHERE c.alarmCode LIKE 'GBX-VIB%' OR c.alarmCode LIKE 'GBX-OIL-TEMP%'
ORDER BY c.threshold""",
    "OP-02": """SELECT r.escalationOrder, r.[role], r.shift, r.contactChannel, STRING_AGG(t.name, ', ') AS People
FROM ref_oncall_roster AS r
LEFT JOIN ref_technicians AS t ON t.onCallRoleId = r.roleId
WHERE r.onCall = 1
GROUP BY r.escalationOrder, r.[role], r.shift, r.contactChannel
ORDER BY r.escalationOrder, r.shift""",
    "OP-03": f"""{_ASOF}
SELECT l.TurbineId,
       COUNT(*) AS GearboxAlarms,
       COUNT(CASE WHEN c.severity = 'critical' THEN 1 END) AS OfWhichCritical,
       CAST(MAX(l.RaisedAt) AS date) AS LastRaised
FROM ops_alarm_log AS l
JOIN ref_alarm_codes AS c ON c.alarmCode = l.AlarmCode
CROSS JOIN asof AS a
WHERE c.component = 'gearbox' AND l.RaisedAt >= DATEADD(month, -12, a.AsOf)
GROUP BY l.TurbineId
ORDER BY GearboxAlarms DESC""",
}

_MONTHKEY = "YEAR({0}) * 100 + MONTH({0})"
_MONTHLABEL = "CONCAT(YEAR({0}), '-', RIGHT(CONCAT('0', MONTH({0})), 2))"
_HOUR = "DATEADD(hour, DATEDIFF(hour, CAST('2000-01-01' AS datetime2), {0}), CAST('2000-01-01' AS datetime2))"
_MONTHSTART = "DATEFROMPARTS(YEAR(a.AsOf), MONTH(a.AsOf), 1)"

# Added after the first test of the agent (21 November 2026): the questions it answered wrongly without an example.
TSQL_EXAMPLES.update({
    "SM-02": f"""{_ASOF},
e AS (SELECT {_MONTHKEY.format('s.[Timestamp]')} AS MonthKey,
             SUM(s.EnergyKwh) AS EnergyKwh, SUM(t.ratedPowerKw / 6e0) AS RatedKwh
      FROM ops_scada_10min AS s
      JOIN ref_turbines AS t ON t.turbineId = s.TurbineId
      CROSS JOIN asof AS a
      WHERE s.[Timestamp] >= DATEADD(month, -12, {_MONTHSTART}) AND s.[Timestamp] < {_MONTHSTART}
      GROUP BY {_MONTHKEY.format('s.[Timestamp]')})
SELECT b.YearMonth,
       ROUND(e.EnergyKwh / 1000, 0) AS EnergyMwh,
       b.P50EnergyMwh AS BudgetP50Mwh,
       ROUND(100 * e.EnergyKwh / 1000 / b.P50EnergyMwh, 1) AS PctOfBudget,
       ROUND(100 * e.EnergyKwh / e.RatedKwh, 1) AS CapacityFactorPct
FROM e
JOIN ops_monthly_budget AS b ON b.[Year] * 100 + b.[Month] = e.MonthKey
ORDER BY b.YearMonth""",
    "PE-01": f"""{_ASOF}
SELECT s.TurbineId,
       ROUND(SUM(s.EnergyKwh) / SUM(s.PossibleEnergyKwh), 4) AS PerformanceIndex,
       ROUND((SUM(s.PossibleEnergyKwh) - SUM(s.EnergyKwh)) / 1000, 0) AS ShortfallMwh,
       ROUND(COUNT(*) / 6e0, 0) AS HoursInFullPerformance
FROM ops_scada_10min AS s
CROSS JOIN asof AS a
WHERE s.[Timestamp] >= DATEADD(day, -90, a.AsOf) AND s.AvailabilityCategory = 'Full performance'
GROUP BY s.TurbineId
ORDER BY PerformanceIndex""",
    "PE-02": f"""{_ASOF},
binned AS (
    SELECT s.TurbineId, s.ActivePower,
           ROUND(s.WindSpeed * POWER(s.AirDensity / 1.225, 1e0 / 3), 0) AS WindBin
    FROM ops_scada_10min AS s
    CROSS JOIN asof AS a
    WHERE s.[Timestamp] >= DATEADD(day, -180, a.AsOf) AND s.AvailabilityCategory = 'Full performance')
SELECT b.WindBin AS WindSpeedBin,
       MAX(r.powerKw) AS ManufacturerKw,
       ROUND(AVG(CASE WHEN b.TurbineId <> 'WT-09' THEN b.ActivePower END), 0) AS RestOfFleetKw,
       ROUND(AVG(CASE WHEN b.TurbineId = 'WT-09' THEN b.ActivePower END), 0) AS Wt09Kw,
       ROUND(100 * (AVG(CASE WHEN b.TurbineId = 'WT-09' THEN b.ActivePower END)
                    / AVG(CASE WHEN b.TurbineId <> 'WT-09' THEN b.ActivePower END) - 1), 1) AS Wt09VsFleetPct
FROM binned AS b
JOIN ref_power_curve AS r ON r.windSpeed = b.WindBin
WHERE b.WindBin BETWEEN 4 AND 13
GROUP BY b.WindBin
ORDER BY b.WindBin""",
    "PE-03": f"""{_ASOF},
d AS (
    SELECT s.TurbineId,
           (s.NacelleDirection - m.WindDirection + 540)
           - 360 * FLOOR((s.NacelleDirection - m.WindDirection + 540) / 360) - 180 AS OffsetDeg
    FROM ops_scada_10min AS s
    JOIN ops_met_10min AS m ON m.[Timestamp] = s.[Timestamp]
    CROSS JOIN asof AS a
    WHERE s.[Timestamp] >= DATEADD(day, -60, a.AsOf) AND s.State = 'RUNNING' AND m.WindSpeed BETWEEN 6 AND 12)
SELECT TurbineId, ROUND(AVG(OffsetDeg), 1) AS MeanOffsetDeg, COUNT(*) AS Records
FROM d
GROUP BY TurbineId
ORDER BY ABS(AVG(OffsetDeg)) DESC""",
    "PE-04": f"""{_ASOF}
SELECT {_MONTHLABEL.format('s.[Timestamp]')} AS YearMonth,
       ROUND(SUM(CASE WHEN s.TurbineId = 'WT-05' THEN s.EnergyKwh END)
             / SUM(CASE WHEN s.TurbineId = 'WT-05' THEN s.PossibleEnergyKwh END), 3) AS Wt05,
       ROUND(SUM(CASE WHEN s.TurbineId = 'WT-09' THEN s.EnergyKwh END)
             / SUM(CASE WHEN s.TurbineId = 'WT-09' THEN s.PossibleEnergyKwh END), 3) AS Wt09,
       ROUND(SUM(CASE WHEN s.TurbineId NOT IN ('WT-05', 'WT-09') THEN s.EnergyKwh END)
             / SUM(CASE WHEN s.TurbineId NOT IN ('WT-05', 'WT-09') THEN s.PossibleEnergyKwh END), 3) AS RestOfFleet
FROM ops_scada_10min AS s
CROSS JOIN asof AS a
WHERE s.[Timestamp] >= DATEADD(month, -11, {_MONTHSTART}) AND s.AvailabilityCategory = 'Full performance'
GROUP BY YEAR(s.[Timestamp]), MONTH(s.[Timestamp])
ORDER BY YEAR(s.[Timestamp]), MONTH(s.[Timestamp])""",
    "PE-05": f"""{_ASOF},
j AS (
    SELECT FLOOR(((m.WindDirection + 15) - 360 * FLOOR((m.WindDirection + 15) / 360)) / 30) * 30 AS SectorDeg,
           s.TurbineId, s.WindSpeed AS TurbineWind, m.WindSpeed AS MastWind
    FROM ops_scada_10min AS s
    JOIN ops_met_10min AS m ON m.[Timestamp] = s.[Timestamp]
    CROSS JOIN asof AS a
    WHERE s.[Timestamp] >= DATEADD(month, -12, a.AsOf) AND s.AvailabilityCategory = 'Full performance'
      AND m.WindSpeed BETWEEN 5 AND 12),
r AS (
    SELECT SectorDeg, TurbineId, AVG(TurbineWind) / AVG(MastWind) AS Ratio, COUNT(*) AS Records
    FROM j
    GROUP BY SectorDeg, TurbineId),
k AS (
    SELECT SectorDeg, TurbineId, Ratio, Records,
           ROW_NUMBER() OVER (PARTITION BY SectorDeg ORDER BY Ratio) AS Position
    FROM r)
SELECT CAST(SectorDeg AS int) AS SectorDeg,
       ROUND(100.0 * SUM(Records) / SUM(SUM(Records)) OVER (), 1) AS ShareOfTimePct,
       ROUND(AVG(Ratio), 3) AS FarmToMastWindRatio,
       MAX(CASE WHEN Position = 1 THEN TurbineId END) AS MostAffectedTurbine,
       ROUND(MIN(Ratio), 3) AS ItsRatio
FROM k
GROUP BY SectorDeg
ORDER BY SectorDeg""",
    "PE-07": f"""{_ASOF},
e AS (
    SELECT {_MONTHKEY.format('[Timestamp]')} AS MonthKey,
           SUM(EnergyKwh) / 1000 AS EnergyMwh,
           SUM(CASE WHEN LossCause IN {_TECHNICAL} THEN LostEnergyKwh ELSE 0 END) / 1000 AS TurbineLossMwh,
           SUM(CASE WHEN LossCause = 'Grid curtailment' THEN LostEnergyKwh ELSE 0 END) / 1000 AS CurtailmentMwh,
           SUM(CASE WHEN LossCause IN ('Icing', 'High wind', 'Grid outage') THEN LostEnergyKwh ELSE 0 END) / 1000 AS WeatherAndGridLossMwh
    FROM ops_scada_10min
    GROUP BY {_MONTHKEY.format('[Timestamp]')}),
w AS (
    SELECT {_MONTHKEY.format('[Timestamp]')} AS MonthKey, AVG(WindSpeed) AS MeanWindSpeed
    FROM ops_met_10min
    GROUP BY {_MONTHKEY.format('[Timestamp]')})
SELECT b.YearMonth,
       ROUND(e.EnergyMwh, 0) AS EnergyMwh,
       b.P50EnergyMwh AS BudgetP50Mwh,
       ROUND(e.EnergyMwh - b.P50EnergyMwh, 0) AS VarianceMwh,
       ROUND(w.MeanWindSpeed, 2) AS MeanWindSpeed,
       b.LongTermWindSpeed,
       ROUND(100 * w.MeanWindSpeed / b.LongTermWindSpeed, 1) AS WindIndexPct,
       ROUND(e.TurbineLossMwh, 0) AS TurbineLossMwh,
       ROUND(e.CurtailmentMwh, 0) AS CurtailmentMwh,
       ROUND(e.WeatherAndGridLossMwh, 0) AS WeatherAndGridLossMwh
FROM e
JOIN w ON w.MonthKey = e.MonthKey
JOIN ops_monthly_budget AS b ON b.[Year] * 100 + b.[Month] = e.MonthKey
CROSS JOIN asof AS a
WHERE e.MonthKey < {_MONTHKEY.format('a.AsOf')}
  AND e.MonthKey >= {_MONTHKEY.format('DATEADD(month, -6, a.AsOf)')}
ORDER BY e.MonthKey""",
    "RE-03": f"""{_ASOF},
f AS (
    SELECT e.TurbineId, e.Component, e.Cause, e.DurationHours, e.LostEnergyMwh, e.FailureMode,
           ROW_NUMBER() OVER (PARTITION BY e.TurbineId, e.Component ORDER BY e.StartTime DESC) AS Recency
    FROM ops_turbine_events AS e
    CROSS JOIN asof AS a
    WHERE e.AvailabilityCategory = 'Forced outage' AND e.Component IS NOT NULL
      AND e.StartTime >= DATEADD(month, -12, a.AsOf))
SELECT TOP 8 TurbineId, Component,
       COUNT(*) AS Faults,
       COUNT(CASE WHEN Cause = 'Component fault' THEN 1 END) AS NeededATechnician,
       ROUND(SUM(DurationHours), 0) AS DowntimeHours,
       ROUND(SUM(LostEnergyMwh), 0) AS LostEnergyMwh,
       MAX(CASE WHEN Recency = 1 THEN FailureMode END) AS LatestFailureMode
FROM f
GROUP BY TurbineId, Component
ORDER BY Faults DESC, DowntimeHours DESC""",
    "RE-04": f"""{_ASOF},
n AS (
    SELECT l.AlarmCode, l.TurbineId, COUNT(*) AS Times
    FROM ops_alarm_log AS l
    CROSS JOIN asof AS a
    WHERE l.RaisedAt >= DATEADD(day, -90, a.AsOf)
    GROUP BY l.AlarmCode, l.TurbineId),
k AS (
    SELECT AlarmCode, TurbineId, Times,
           ROW_NUMBER() OVER (PARTITION BY AlarmCode ORDER BY Times DESC, TurbineId) AS Position
    FROM n)
SELECT TOP 10 k.AlarmCode, c.description AS Description, c.severity AS Severity,
       SUM(k.Times) AS Times,
       COUNT(*) AS TurbinesAffected,
       MAX(CASE WHEN k.Position = 1 THEN k.TurbineId END) AS MostAffectedTurbine,
       MAX(k.Times) AS TimesOnThatTurbine
FROM k
JOIN ref_alarm_codes AS c ON c.alarmCode = k.AlarmCode
GROUP BY k.AlarmCode, c.description, c.severity
ORDER BY Times DESC""",
    "RE-05": f"""{_ASOF},
x AS (
    SELECT s.TurbineId,
           AVG(s.GearboxBearingTemp) AS BearingTemp, AVG(s.GearboxOilTemp) AS OilTemp, AVG(s.GearboxVibration) AS Vibration
    FROM ops_scada_10min AS s
    CROSS JOIN asof AS a
    WHERE s.[Timestamp] >= DATEADD(day, -30, a.AsOf) AND s.State = 'RUNNING' AND s.ActivePower > 3000
    GROUP BY s.TurbineId)
SELECT TurbineId,
       ROUND(BearingTemp, 1) AS GearboxBearingTemp,
       ROUND(BearingTemp - AVG(BearingTemp) OVER (), 1) AS BearingTempVsFleet,
       ROUND(OilTemp, 1) AS GearboxOilTemp,
       ROUND(OilTemp - AVG(OilTemp) OVER (), 1) AS OilTempVsFleet,
       ROUND(Vibration, 2) AS GearboxVibration,
       ROUND(Vibration - AVG(Vibration) OVER (), 2) AS VibrationVsFleet
FROM x
ORDER BY BearingTempVsFleet DESC""",
    "RE-06": f"""{_ASOF},
w AS (
    SELECT DATEADD(day, -(DATEDIFF(day, CAST('1900-01-01' AS date), CAST(s.[Timestamp] AS date)) % 7),
                   CAST(s.[Timestamp] AS date)) AS WeekStarting,
           s.TurbineId, s.GearboxBearingTemp, s.GearboxVibration
    FROM ops_scada_10min AS s
    CROSS JOIN asof AS a
    WHERE s.[Timestamp] >= DATEADD(day, -182, a.AsOf) AND s.State = 'RUNNING' AND s.ActivePower > 2000)
SELECT WeekStarting,
       ROUND(AVG(CASE WHEN TurbineId = 'WT-07' THEN GearboxBearingTemp END), 1) AS Wt07BearingTemp,
       ROUND(AVG(CASE WHEN TurbineId <> 'WT-07' THEN GearboxBearingTemp END), 1) AS FleetBearingTemp,
       ROUND(AVG(CASE WHEN TurbineId = 'WT-07' THEN GearboxVibration END), 2) AS Wt07Vibration,
       ROUND(AVG(CASE WHEN TurbineId <> 'WT-07' THEN GearboxVibration END), 2) AS FleetVibration
FROM w
GROUP BY WeekStarting
ORDER BY WeekStarting""",
    "RE-07": """SELECT TurbineId, SampleDate, IronPpm, CopperPpm, WaterPpm, ParticleCountIso4406, Condition, LabComment
FROM ops_oil_analysis
WHERE TurbineId IN ('WT-02', 'WT-07')
ORDER BY TurbineId, SampleDate""",
    "RE-08": """SELECT TOP 5 e.TurbineId, CAST(e.StartTime AS date) AS FailureDate, e.FailureMode,
       ROUND(e.DurationHours, 0) AS DowntimeHours,
       ROUND(e.LostEnergyMwh, 0) AS LostEnergyMwh,
       w.WorkOrderId, w.Summary,
       ROUND(w.TotalCostUsd, 0) AS TotalCostUsd,
       w.CostBorneBy,
       ROUND(w.WaitingForPartsHours / 24, 1) AS DaysWaitingForPartsOrCrane,
       w.Findings
FROM ops_turbine_events AS e
JOIN ops_work_orders AS w ON w.WorkOrderId = e.WorkOrderId
WHERE e.ComponentCode = 'GBX' AND e.FaultClass = 'C'
ORDER BY w.TotalCostUsd DESC""",
    "MP-01": """WITH f AS (
    SELECT CAST(p.TargetTime AT TIME ZONE 'UTC' AT TIME ZONE 'Central Standard Time' AS datetime2) AS LocalTime,
           p.WindSpeed, p.WindSpeedP90, p.PowerMw, p.IcingRisk, st.turbineCount, st.ppaPriceUsdPerMwh
    FROM ops_power_forecast AS p
    CROSS JOIN ref_site AS st
    WHERE p.ForecastType = 'Latest')
SELECT CAST(LocalTime AS date) AS WorkDay,
       DATENAME(weekday, LocalTime) AS DayOfWeek,
       ROUND(AVG(WindSpeed), 1) AS MeanWindSpeed,
       ROUND(MAX(WindSpeedP90), 1) AS HighestLikelyWindSpeed,
       SUM(CASE WHEN WindSpeedP90 < 10 THEN 1 ELSE 0 END) AS HoursCalmEnoughForBladeWork,
       ROUND(SUM(PowerMw) / MAX(turbineCount), 1) AS MwhLostIfOneTurbineIsStopped,
       ROUND(SUM(PowerMw) / MAX(turbineCount) * MAX(ppaPriceUsdPerMwh), 0) AS RevenueLostUsd,
       MAX(CAST(IcingRisk AS int)) AS IcingRisk
FROM f
WHERE DATEPART(hour, LocalTime) BETWEEN 7 AND 16 AND DATENAME(weekday, LocalTime) <> 'Sunday'
GROUP BY CAST(LocalTime AS date), DATENAME(weekday, LocalTime)
HAVING COUNT(*) = 10
ORDER BY MwhLostIfOneTurbineIsStopped""",
    "MP-02": f"""{_ASOF},
r AS (
    SELECT CASE WHEN w.Status = 'Closed' AND w.ClosedDate <= DATEADD(day, 7, w.ScheduledDate) THEN '1 Done within a week of the plan'
                WHEN w.Status = 'Closed' THEN '2 Done late'
                ELSE '3 Not done, overdue' END AS Result
    FROM ops_work_orders AS w
    CROSS JOIN asof AS a
    WHERE w.WorkType = 'Preventive' AND w.ScheduledDate >= DATEADD(month, -12, a.AsOf) AND w.ScheduledDate < a.AsOf)
SELECT Result, COUNT(*) AS WorkOrders, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) AS SharePct
FROM r
GROUP BY Result
ORDER BY Result""",
    "MP-03": """SELECT TOP 10 w.WorkOrderId, w.TurbineId, CAST(w.OpenedDate AS date) AS Opened, w.Summary,
       ROUND(w.WaitingForPartsHours / 24, 1) AS DaysWaiting,
       ROUND(w.DowntimeHours, 0) AS DowntimeHours,
       ROUND(e.LostEnergyMwh, 0) AS LostEnergyMwh,
       STRING_AGG(p.PartId, ', ') AS PartsUsed
FROM ops_work_orders AS w
JOIN ops_turbine_events AS e ON e.EventId = w.EventId
LEFT JOIN ops_work_order_parts AS p ON p.WorkOrderId = w.WorkOrderId
WHERE w.WaitingForPartsHours >= 48
GROUP BY w.WorkOrderId, w.TurbineId, w.OpenedDate, w.Summary, w.WaitingForPartsHours, w.DowntimeHours, e.LostEnergyMwh
ORDER BY w.WaitingForPartsHours DESC""",
    "MP-05": f"""{_ASOF}
SELECT t.name AS LeadTechnician, t.[role] AS TechnicianRole,
       COUNT(*) AS WorkOrdersLed,
       COUNT(CASE WHEN w.WorkType = 'Corrective' THEN 1 END) AS Corrective,
       COUNT(CASE WHEN w.WorkType = 'Preventive' THEN 1 END) AS Preventive,
       ROUND(SUM(w.LaborHours), 0) AS CrewLabourHours
FROM ops_work_orders AS w
JOIN ref_technicians AS t ON t.technicianId = w.LeadTechnicianId
CROSS JOIN asof AS a
WHERE w.Status = 'Closed' AND w.OpenedDate >= DATEADD(day, -90, a.AsOf)
GROUP BY t.name, t.[role]
ORDER BY CrewLabourHours DESC""",
    "AM-01": f"""{_ASOF},
y AS (SELECT DATEFROMPARTS(YEAR(AsOf), 1, 1) AS YearStart, AsOf FROM asof),
e AS (SELECT SUM(s.EnergyKwh) / 1000 AS EnergyMwh
      FROM ops_scada_10min AS s CROSS JOIN y WHERE s.[Timestamp] >= y.YearStart),
c AS (SELECT SUM(CASE WHEN u.Compensated = 1 THEN u.LostEnergyMwh ELSE 0 END) AS DeemedMwh,
             SUM(CASE WHEN u.Compensated = 1 THEN 0 ELSE u.LostEnergyMwh END) AS UnpaidCurtailmentMwh
      FROM ops_curtailments AS u CROSS JOIN y WHERE u.StartTime >= y.YearStart),
b AS (SELECT SUM(CASE WHEN m.[Month] < MONTH(y.AsOf) THEN m.BudgetRevenueUsd
                      ELSE m.BudgetRevenueUsd * DAY(y.AsOf) / DAY(EOMONTH(y.AsOf)) END) AS BudgetRevenueUsd
      FROM ops_monthly_budget AS m CROSS JOIN y
      WHERE m.[Year] = YEAR(y.AsOf) AND m.[Month] <= MONTH(y.AsOf))
SELECT ROUND(e.EnergyMwh, 0) AS EnergyMwh,
       ROUND(c.DeemedMwh, 0) AS DeemedGenerationMwh,
       ROUND((e.EnergyMwh + c.DeemedMwh) * st.ppaPriceUsdPerMwh, 0) AS RevenueUsd,
       ROUND(b.BudgetRevenueUsd, 0) AS BudgetRevenueUsd,
       ROUND(100 * (e.EnergyMwh + c.DeemedMwh) * st.ppaPriceUsdPerMwh / b.BudgetRevenueUsd, 1) AS PctOfBudget,
       ROUND(c.UnpaidCurtailmentMwh * st.ppaPriceUsdPerMwh, 0) AS RevenueLostToUnpaidCurtailmentUsd
FROM e CROSS JOIN c CROSS JOIN b CROSS JOIN ref_site AS st""",
    "AM-03": f"""{_ASOF},
cy AS (SELECT CAST(DATEFROMPARTS(YEAR(AsOf) - CASE WHEN MONTH(AsOf) >= 7 THEN 1 ELSE 2 END, 7, 1) AS datetime2) AS YearStart FROM asof),
k AS (SELECT guaranteedAvailabilityPct AS Guarantee, liquidatedDamagesUsdPerMwh AS DamagesRate,
             scheduledMaintenanceAllowanceHoursPerTurbineYear AS Allowance
      FROM ref_contracts WHERE contractId = 'CT-SMA-001'),
h AS (SELECT s.TurbineId,
             COUNT(*) / 6e0 AS PeriodHours,
             SUM(CASE WHEN s.AvailabilityCategory IN ('Forced outage', 'Planned corrective action') THEN 1 ELSE 0 END) / 6e0 AS OutageHours,
             SUM(CASE WHEN s.AvailabilityCategory = 'Scheduled maintenance' THEN 1 ELSE 0 END) / 6e0 AS ScheduledHours,
             SUM(CASE WHEN s.AvailabilityCategory IN ('Out of electrical specification', 'Out of environmental specification',
                                                      'Requested shutdown', 'Information unavailable') THEN 1 ELSE 0 END) / 6e0 AS ExcludedHours,
             SUM(s.PossibleEnergyKwh) / 1000 AS PossibleMwh
      FROM ops_scada_10min AS s CROSS JOIN cy
      WHERE s.[Timestamp] >= cy.YearStart AND s.[Timestamp] < DATEADD(month, 12, cy.YearStart)
      GROUP BY s.TurbineId),
x AS (SELECT e.TurbineId, SUM(e.DurationHours) AS NotTheProvidersHours
      FROM ops_turbine_events AS e CROSS JOIN cy
      WHERE e.AvailabilityCategory = 'Forced outage' AND e.ResponsibleParty <> 'Service provider'
        AND e.StartTime >= cy.YearStart AND e.StartTime < DATEADD(month, 12, cy.YearStart)
      GROUP BY e.TurbineId),
t AS (SELECT h.TurbineId, h.PossibleMwh,
             100 * (1 - (h.OutageHours - COALESCE(x.NotTheProvidersHours, 0)
                         + CASE WHEN h.ScheduledHours > k.Allowance THEN h.ScheduledHours - k.Allowance ELSE 0 END)
                        / (h.PeriodHours - h.ExcludedHours - COALESCE(x.NotTheProvidersHours, 0))) AS AvailabilityPct
      FROM h LEFT JOIN x ON x.TurbineId = h.TurbineId CROSS JOIN k),
z AS (SELECT AVG(AvailabilityPct) AS MeanPct, MIN(AvailabilityPct) AS LowestPct, SUM(PossibleMwh) AS PossibleMwh FROM t)
SELECT CAST(cy.YearStart AS date) AS ContractYearStart,
       ROUND(z.MeanPct, 2) AS ContractualAvailabilityPct,
       k.Guarantee AS GuaranteePct,
       ROUND(z.LowestPct, 2) AS LowestTurbinePct,
       (SELECT TOP 1 TurbineId FROM t ORDER BY AvailabilityPct) AS LowestTurbine,
       ROUND(CASE WHEN k.Guarantee > z.MeanPct THEN k.Guarantee - z.MeanPct ELSE 0 END / 100 * z.PossibleMwh, 0) AS EnergyBelowGuaranteeMwh,
       ROUND(CASE WHEN k.Guarantee > z.MeanPct THEN k.Guarantee - z.MeanPct ELSE 0 END / 100 * z.PossibleMwh * k.DamagesRate, 0) AS LiquidatedDamagesUsd
FROM z CROSS JOIN k CROSS JOIN cy""",
    "AM-04": f"""{_ASOF},
y AS (SELECT DATEFROMPARTS(YEAR(AsOf), 1, 1) AS YearStart, AsOf FROM asof),
w AS (SELECT SUM(CASE WHEN o.CostBorneBy = 'Owner' THEN o.TotalCostUsd ELSE 0 END) AS OwnerUsd,
             SUM(CASE WHEN o.CostBorneBy = 'Warranty' THEN o.TotalCostUsd ELSE 0 END) AS WarrantyUsd,
             COUNT(CASE WHEN o.CostBorneBy = 'Owner' THEN 1 END) AS Repairs
      FROM ops_work_orders AS o CROSS JOIN y
      WHERE o.WorkType = 'Corrective' AND o.Status = 'Closed' AND o.OpenedDate >= y.YearStart),
b AS (SELECT SUM(CASE WHEN m.[Month] < MONTH(y.AsOf) THEN m.BudgetCorrectiveMaintenanceUsd
                      ELSE m.BudgetCorrectiveMaintenanceUsd * DAY(y.AsOf) / DAY(EOMONTH(y.AsOf)) END) AS BudgetUsd
      FROM ops_monthly_budget AS m CROSS JOIN y
      WHERE m.[Year] = YEAR(y.AsOf) AND m.[Month] <= MONTH(y.AsOf)),
e AS (SELECT SUM(s.EnergyKwh) / 1000 AS EnergyMwh
      FROM ops_scada_10min AS s CROSS JOIN y WHERE s.[Timestamp] >= y.YearStart)
SELECT w.Repairs,
       ROUND(w.OwnerUsd, 0) AS RepairCostPaidByOwnerUsd,
       ROUND(b.BudgetUsd, 0) AS BudgetUsd,
       ROUND(100 * w.OwnerUsd / b.BudgetUsd, 1) AS PctOfBudget,
       ROUND(w.OwnerUsd / e.EnergyMwh, 2) AS RepairCostUsdPerMwh,
       ROUND(w.WarrantyUsd, 0) AS CoveredByWarrantyUsd
FROM w CROSS JOIN b CROSS JOIN e""",
    "AM-05": f"""{_ASOF},
actual AS (
    SELECT {_HOUR.format('[Timestamp]')} AS HourStart,
           SUM(PossiblePower) / 6 / 1000 AS PossibleMw, SUM(ActivePower) / 6 / 1000 AS ActualMw
    FROM ops_scada_10min
    GROUP BY {_HOUR.format('[Timestamp]')})
SELECT {_MONTHLABEL.format('f.TargetTime')} AS YearMonth,
       ROUND(100 * AVG(ABS(f.PowerMw - x.PossibleMw)) / MAX(st.capacityMw), 1) AS MeanAbsoluteErrorPctOfCapacity,
       ROUND(100 * AVG(f.PowerMw - x.PossibleMw) / MAX(st.capacityMw), 1) AS BiasPctOfCapacity,
       ROUND(100 * AVG(CASE WHEN x.PossibleMw BETWEEN f.PowerMwP10 AND f.PowerMwP90 THEN 1e0 ELSE 0e0 END), 0) AS HoursInsideP10P90BandPct,
       ROUND(100 * AVG(ABS(f.PowerMw - x.ActualMw)) / MAX(st.capacityMw), 1) AS ErrorAgainstActualPctOfCapacity
FROM ops_power_forecast AS f
JOIN actual AS x ON x.HourStart = f.TargetTime
CROSS JOIN ref_site AS st
CROSS JOIN asof AS a
WHERE f.ForecastType = 'Day-ahead'
  AND f.TargetTime >= DATEADD(month, -6, {_MONTHSTART}) AND f.TargetTime < {_MONTHSTART}
GROUP BY YEAR(f.TargetTime), MONTH(f.TargetTime)
ORDER BY YEAR(f.TargetTime), MONTH(f.TargetTime)""",
    "AM-06": f"""{_ASOF},
h AS (
    SELECT {_HOUR.format('[Timestamp]')} AS HourStart, SUM(EnergyKwh) / 1000 AS EnergyMwh
    FROM ops_scada_10min
    GROUP BY {_HOUR.format('[Timestamp]')})
SELECT ROUND(SUM(h.EnergyMwh), 0) AS EnergyMwh,
       MAX(st.ppaPriceUsdPerMwh) AS ContractPrice,
       ROUND(SUM(h.EnergyMwh * p.RealTimePriceUsdPerMwh) / SUM(h.EnergyMwh), 2) AS CapturedRealTimePrice,
       ROUND(AVG(p.RealTimePriceUsdPerMwh), 2) AS MeanRealTimePrice,
       ROUND(SUM(h.EnergyMwh * (st.ppaPriceUsdPerMwh - p.RealTimePriceUsdPerMwh)), 0) AS ContractValueOverMarketUsd,
       COUNT(CASE WHEN p.RealTimePriceUsdPerMwh < 0 THEN 1 END) AS HoursWithNegativePrice
FROM h
JOIN ops_market_prices AS p ON p.[Timestamp] = h.HourStart
CROSS JOIN ref_site AS st
CROSS JOIN asof AS a
WHERE h.HourStart >= DATEADD(month, -12, a.AsOf)""",
})

# Example queries for the KQL database. Tables only: no stored functions, so each example stands on its own.
KQL_EXAMPLES = {
    "What is every turbine doing right now?": """TurbineTelemetry
| where Timestamp > ago(10m)
| summarize arg_max(Timestamp, State, WindSpeed, ActivePower, PowerSetpoint, GearboxBearingTemp, GearboxVibration) by TurbineId
| order by TurbineId asc""",
    "Which alarms are active, and which procedure applies to each?": """AlarmEvents
| where Timestamp > ago(7d) and AlarmCode != 'COMMS-RESTORED'
| summarize arg_max(Timestamp, *) by AlarmId
| where Status == 'raised'
| project RaisedAt = Timestamp, TurbineId, AlarmCode, Severity, Description, Value, Threshold, Unit, SopId
| order by RaisedAt desc""",
    "How much is the site producing, and how has that changed over the last hour?": """TurbineTelemetry
| where Timestamp > ago(1h)
| summarize TurbinePowerKw = avg(ActivePower) by TurbineId, bin(Timestamp, 5m)
| summarize SitePowerMw = round(sum(TurbinePowerKw) / 1000, 2), TurbinesReporting = dcount(TurbineId) by Timestamp
| order by Timestamp asc""",
    "Which turbine stands out from the fleet right now on gearbox temperature and vibration?": """let recent = TurbineTelemetry
    | where Timestamp > ago(15m) and State in ('RUNNING', 'DERATED')
    | summarize BearingTemp = avg(GearboxBearingTemp), OilTemp = avg(GearboxOilTemp), Vibration = avg(GearboxVibration), PowerKw = avg(ActivePower) by TurbineId;
let fleetBearingTemp = toscalar(recent | summarize percentile(BearingTemp, 50));
let fleetVibration = toscalar(recent | summarize percentile(Vibration, 50));
recent
| project TurbineId, PowerKw = round(PowerKw, 0), BearingTemp = round(BearingTemp, 1),
          BearingTempVsFleet = round(BearingTemp - fleetBearingTemp, 1), OilTemp = round(OilTemp, 1),
          Vibration = round(Vibration, 2), VibrationVsFleet = round(Vibration - fleetVibration, 2)
| order by VibrationVsFleet desc""",
    "How did the gearbox vibration of WT-07 develop over the last 6 hours?": """TurbineTelemetry
| where Timestamp > ago(6h) and TurbineId == 'WT-07'
| summarize Vibration = round(avg(GearboxVibration), 2), OilTemp = round(avg(GearboxOilTemp), 1), PowerKw = round(avg(ActivePower), 0) by bin(Timestamp, 15m)
| order by Timestamp asc""",
    "Which turbines changed state in the last 24 hours, and why?": """TurbineStateChanges
| where Timestamp > ago(24h)
| project Timestamp, TurbineId, PreviousState, State, Reason
| order by Timestamp desc
| take 25""",
}

# Variations: a question of the bank with another turbine, period or component. None is an example query, so they
# show whether the agent can adapt an example. (id, id of the base question, question, replacements in its reference SQL)
VARIATIONS = [
    ("VA-01", "SM-03", "What was the availability of each turbine over the last 30 days?", [("INTERVAL 90 DAYS", "INTERVAL 30 DAYS")]),
    ("VA-02", "PE-01", "Rank the turbines by performance index for the last 30 days.", [("INTERVAL 90 DAYS", "INTERVAL 30 DAYS")]),
    ("VA-03", "PE-04", "Show the performance index of WT-03 and WT-09 against the rest of the fleet for each of the last 12 months, the running month included.",
     [("'WT-05'", "'WT-03'"), ("Wt05", "Wt03")]),
    ("VA-04", "RE-06", "Is the WT-02 gearbox drifting away from the fleet? Show the trend by week over the last 182 days.",
     [("'WT-07'", "'WT-02'"), ("Wt07", "Wt02")]),
    ("VA-05", "RE-04", "What are the five most frequent alarms of the last 30 days, and on which turbine does each one occur most?",
     [("INTERVAL 90 DAYS", "INTERVAL 30 DAYS"), ("LIMIT 10", "LIMIT 5")]),
    ("VA-06", "RE-01", "Which components cost us the most downtime and energy in the last 6 months?", [("add_months(a.AsOf, -12)", "add_months(a.AsOf, -6)")]),
    ("VA-07", "MP-05", "Who led which kind of work in the last 180 days?", [("INTERVAL 90 DAYS", "INTERVAL 180 DAYS")]),
    ("VA-08", "RE-07", "What do the gearbox oil samples of WT-08 show?", [("IN ('WT-02', 'WT-07')", "IN ('WT-08')")]),
    ("VA-09", "OP-03", "How often did pitch system alarms come up on each turbine in the last 12 months?",
     [("c.component = 'gearbox'", "c.component = 'pitch system'"), ("GearboxAlarms", "PitchAlarms")]),
    ("VA-10", "AM-02", "How much were we curtailed in the last 6 months, why, and how much of it were we paid for?",
     [("add_months(a.AsOf, -12)", "add_months(a.AsOf, -6)")]),
]

# The brief for the judge of the SDK. {query} and {expected_answer} are filled in by the SDK. It must end in one word.
CRITIC_PROMPT = """You are checking the answer of a data assistant for a wind farm.

Question: {query}

Ground truth: {expected_answer}

Decide whether the most recent answer agrees with the ground truth.
It agrees when every figure it gives matches the ground truth within rounding: 1 percent, or the last digit shown.
It may show fewer rows or fewer columns than the ground truth, another order, other wording, or correctly converted units.
It does not agree when a figure contradicts the ground truth, when it covers a different period, or when it gives
no figures although the ground truth has them.
Rows that tie on the value they are ranked by may come in either order. Where the ground truth names the one
item with the highest count and the answer names another item with the same count, the answer agrees.
A first or last period that is only partly inside the time window may differ.
Where the ground truth says that the data cannot answer the question, the answer agrees only when it says so and
gives no number.
Return only one word: Yes, No, or Unclear."""

# Questions the data cannot answer. The agent must say so instead of inventing a number.
UNANSWERABLE = [
    ("NO-01", "How many bird strikes did we record last year?", "The data holds no wildlife or bird strike records."),
    ("NO-02", "What is the remaining useful life of the WT-07 gearbox in months?",
     "The data holds no remaining-life estimate. It holds vibration, temperatures, oil samples and past failures."),
    ("NO-03", "How does our availability compare with the neighbouring wind farm?",
     "The data covers one site only; there is no data for other wind farms."),
]

# ----------------------------------------------------------------------------------------------- ontology
# (source column, property name, value type). The first property is the key. Property names are unique
# in the whole ontology unless they have the same value type; tools/build-phase3.py checks that.
S, D, I, B, T = "String", "Double", "BigInt", "Boolean", "DateTime"

ENTITIES = [
    dict(name="Site", table="ref_site", display="SiteName", meaning="The wind farm.", properties=[
        ("siteId", "SiteId", S), ("siteName", "SiteName", S), ("operator", "Operator", S), ("timezone", "Timezone", S),
        ("capacityMw", "CapacityMw", D), ("turbineCount", "TurbineCount", I), ("ppaPriceUsdPerMwh", "PpaPriceUsdPerMwh", D)]),
    dict(name="Turbine", table="ref_turbines", display="TurbineName", meaning="One wind turbine, WT-01 to WT-12.", properties=[
        ("turbineId", "TurbineId", S), ("name", "TurbineName", S), ("siteId", "SiteId", S), ("model", "TurbineModel", S),
        ("manufacturer", "TurbineManufacturer", S), ("serialNumber", "TurbineSerialNumber", S), ("ratedPowerKw", "RatedPowerKw", D),
        ("hubHeightM", "HubHeightM", D), ("rotorDiameterM", "RotorDiameterM", D), ("latitude", "Latitude", D),
        ("longitude", "Longitude", D), ("string", "CollectorString", S), ("commissionedDate", "CommissionedDate", T)],
         timeseries=dict(table="TurbineTelemetry", timestamp="Timestamp", key="TurbineId", properties=[
             ("Timestamp", "TelemetryTime", T), ("State", "OperatingState", S), ("ActivePower", "ActivePowerKw", D),
             ("PowerSetpoint", "PowerSetpointKw", D), ("WindSpeed", "WindSpeedMs", D), ("GearboxOilTemp", "GearboxOilTempC", D),
             ("GearboxBearingTemp", "GearboxBearingTempC", D), ("GearboxVibration", "GearboxVibrationMmS", D),
             ("GeneratorWindingTemp", "GeneratorWindingTempC", D), ("MainBearingTemp", "MainBearingTempC", D)])),
    dict(name="Component", table="ref_components", display="ComponentType",
         meaning="A major component of a turbine: gearbox, generator, main bearing, blades and so on.", properties=[
        ("componentId", "ComponentId", S), ("turbineId", "TurbineId", S), ("componentCode", "ComponentCode", S),
        ("componentType", "ComponentType", S), ("manufacturer", "ComponentManufacturer", S), ("model", "ComponentModel", S),
        ("serialNumber", "ComponentSerialNumber", S), ("installDate", "InstallDate", T), ("designLifeYears", "DesignLifeYears", I),
        ("warrantyEndDate", "WarrantyEndDate", T), ("warrantyContractId", "ContractId", S)]),
    dict(name="WorkOrder", table="ops_work_orders", display="Summary", meaning="A maintenance job on a turbine.", properties=[
        ("WorkOrderId", "WorkOrderId", S), ("TurbineId", "TurbineId", S), ("ComponentId", "ComponentId", S), ("WorkType", "WorkType", S),
        ("Priority", "Priority", S), ("Status", "WorkOrderStatus", S), ("OpenedDate", "OpenedDate", T), ("ScheduledDate", "ScheduledDate", T),
        ("ClosedDate", "ClosedDate", T), ("Summary", "Summary", S), ("FailureMode", "FailureMode", S), ("LaborHours", "LaborHours", D),
        ("TotalCostUsd", "TotalCostUsd", D), ("DowntimeHours", "DowntimeHours", D), ("WaitingForPartsHours", "WaitingForPartsHours", D),
        ("CostBorneBy", "CostBorneBy", S), ("CoveredByWarranty", "CoveredByWarranty", B)]),
    dict(name="DowntimeEvent", table="ops_turbine_events", display="EventDescription",
         meaning="One stop or derate of a turbine, with its cause and the energy it cost.", properties=[
        ("EventId", "EventId", S), ("TurbineId", "TurbineId", S), ("StartTime", "StartTime", T), ("EndTime", "EndTime", T),
        ("DurationHours", "DurationHours", D), ("AvailabilityCategory", "AvailabilityCategory", S), ("Cause", "Cause", S),
        ("Component", "ComponentName", S), ("AlarmCode", "AlarmCode", S), ("FailureMode", "FailureMode", S),
        ("ResponsibleParty", "ResponsibleParty", S), ("Description", "EventDescription", S), ("LostEnergyMwh", "LostEnergyMwh", D)]),
    dict(name="AlarmType", table="ref_alarm_codes", display="AlarmDescription",
         meaning="A kind of controller alarm: its threshold, what the controller does, and the procedure.", properties=[
        ("alarmCode", "AlarmCode", S), ("component", "AlarmComponent", S), ("severity", "Severity", S),
        ("description", "AlarmDescription", S), ("signal", "Signal", S), ("threshold", "Threshold", D), ("unit", "Unit", S),
        ("controllerAction", "ControllerAction", S), ("sopId", "SopId", S)]),
    dict(name="SparePart", table="ref_spare_parts", display="PartDescription", meaning="A spare part held in stock.", properties=[
        ("partId", "PartId", S), ("description", "PartDescription", S), ("componentCode", "ComponentCode", S),
        ("quantityOnHand", "QuantityOnHand", I), ("reorderPoint", "ReorderPoint", I), ("leadTimeDays", "LeadTimeDays", I),
        ("unitCostUsd", "UnitCostUsd", I), ("location", "StockLocation", S)]),
    dict(name="Technician", table="ref_technicians", display="TechnicianName", meaning="A member of the maintenance crew.", properties=[
        ("technicianId", "TechnicianId", S), ("name", "TechnicianName", S), ("role", "TechnicianRole", S),
        ("discipline", "Discipline", S), ("certifications", "Certifications", S), ("crew", "Crew", S)]),
    dict(name="Procedure", table="ref_sop_index", display="ProcedureTitle",
         meaning="A standard operating procedure.", properties=[
        ("sopId", "SopId", S), ("title", "ProcedureTitle", S), ("file", "ProcedureFile", S)]),
    dict(name="Contract", table="ref_contracts", display="Counterparty",
         meaning="A commercial contract: power purchase, service or warranty.", properties=[
        ("contractId", "ContractId", S), ("contractType", "ContractType", S), ("counterparty", "Counterparty", S),
        ("startDate", "ContractStartDate", T), ("endDate", "ContractEndDate", T), ("priceUsdPerMwh", "PriceUsdPerMwh", D),
        ("guaranteedAvailabilityPct", "GuaranteedAvailabilityPct", D), ("annualFeeUsd", "AnnualFeeUsd", I)]),
]

# (name, source entity, target entity, link table, column with the source key, column with the target key)
RELATIONSHIPS = [
    ("SiteHasTurbine", "Site", "Turbine", "ref_turbines", "siteId", "turbineId"),
    ("TurbineHasComponent", "Turbine", "Component", "ref_components", "turbineId", "componentId"),
    ("WorkOrderOnTurbine", "WorkOrder", "Turbine", "ops_work_orders", "WorkOrderId", "TurbineId"),
    ("WorkOrderOnComponent", "WorkOrder", "Component", "ops_work_orders", "WorkOrderId", "ComponentId"),
    ("WorkOrderUsesPart", "WorkOrder", "SparePart", "ops_work_order_parts", "WorkOrderId", "PartId"),
    ("WorkOrderLedBy", "WorkOrder", "Technician", "ops_work_orders", "WorkOrderId", "LeadTechnicianId"),
    ("WorkOrderFollows", "WorkOrder", "Procedure", "ops_work_orders", "WorkOrderId", "SopId"),
    ("EventOnTurbine", "DowntimeEvent", "Turbine", "ops_turbine_events", "EventId", "TurbineId"),
    ("EventHasAlarmType", "DowntimeEvent", "AlarmType", "ops_turbine_events", "EventId", "AlarmCode"),
    ("EventRepairedBy", "DowntimeEvent", "WorkOrder", "ops_turbine_events", "EventId", "WorkOrderId"),
    ("AlarmHandledBy", "AlarmType", "Procedure", "ref_alarm_codes", "alarmCode", "sopId"),
    ("ComponentCoveredBy", "Component", "Contract", "ref_components", "componentId", "warrantyContractId"),
]

# ---------------------------------------------------------------------------------------- operations agent
# Thresholds. simulator/tests/test_phase3.py runs the simulator against them: a healthy fleet stays below
# EARLY_VIBRATION, and a fault of severity 0.2 crosses it without any vibration alarm from the controller.
EARLY_VIBRATION = 4.0       # mm/s. Controller warning: 5.5. Healthy turbines: below 2.5. WT-07 (worn): below 3.8.
ALARM_VIBRATION = 5.5       # mm/s, the controller's own warning threshold (GBX-VIB-HIGH)
EARLY_OIL_TEMP = 72.0       # degC. Controller warning: 78. Healthy turbines: below 68.
FLEET_VIBRATION_GAP = 2.0   # mm/s above the fleet median (optional rule 4)

OPS_GOALS = """\
Protect the gearboxes of the Northwind Ridge wind farm. A gearbox exchange costs about 385,000 USD and months of lost
production; a bearing replaced in time costs a fraction of that. Find a gearbox that starts to run rough or hot
before the turbine controller raises its own alarm, tell the on-call engineer which turbine it is and what the
numbers are, and recommend the next step. Do not raise the same condition again while it lasts."""

OPS_INSTRUCTIONS = f"""\
*** Operational Instructions ***
1. Alert me when the gearbox vibration of a turbine crosses above {EARLY_VIBRATION:g} mm/s. This is an early warning: the turbine controller only alarms at {ALARM_VIBRATION:g} mm/s.
2. Alert me when the gearbox vibration of a turbine crosses above {ALARM_VIBRATION:g} mm/s. This is urgent: the controller has raised alarm GBX-VIB-HIGH and derates the turbine at 8 mm/s.
3. Alert me when the gearbox oil temperature of a turbine crosses above {EARLY_OIL_TEMP:g} degrees Celsius. The controller alarms at 78 degrees.

*** Semantic Instructions ***
1. Information about a turbine can be found in the 'TurbineTelemetry' table. Each turbine is identified by the 'TurbineId' column (WT-01 to WT-12).
2. 'Timestamp' is the time of the measurement in UTC. There is one row per turbine every few seconds.
3. Gearbox vibration is the column 'GearboxVibration' in mm/s. Gearbox oil temperature is 'GearboxOilTemp' and gearbox bearing temperature is 'GearboxBearingTemp', both in degrees Celsius.
4. 'ActivePower' is the power of the turbine in kW and 'WindSpeed' is the wind speed in m/s. 'State' is the operating state: RUNNING, DERATED, CURTAILED, IDLE, PAUSED, STOPPED, STOPPED_HIGH_WIND, MAINTENANCE or FAULT.
5. Only consider rows where 'State' is RUNNING or DERATED. A stopped turbine has no meaningful vibration.
6. In the message, name the turbine and give its latest gearbox vibration, gearbox oil temperature, gearbox bearing temperature and power.
7. For rule 1 and rule 3, recommend: compare the turbine with the fleet, check the latest oil sample, and plan an inspection in the next low-wind period (procedure SOP-GBX-001).
8. For rule 2, recommend: derate the turbine to 50 percent and send the on-call technician (procedure SOP-GBX-001).
9. WT-07 has a worn gearbox bearing and runs about 1.3 mm/s above the fleet. That is known and is not a new condition unless it crosses a threshold above.
"""

OPS_RULE_4 = f"""\
4. Alert me when the vibration of a turbine is more than {FLEET_VIBRATION_GAP:g} mm/s above the fleet. Information about this can be found in the 'GearboxVsFleetLive' table, each turbine identified by the 'TurbineId' column; the value is the column 'VibrationVsFleet'."""
