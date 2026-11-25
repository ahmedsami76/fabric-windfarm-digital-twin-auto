"""The question bank: what the people who run a wind farm ask, and a reference query for each question.

One source for three things:
  * notebook fabric/notebooks/04_question_bank.ipynb (built by tools/build-notebooks.py),
  * the tables in docs/04-use-cases-and-data-audit.md,
  * fabric/kql/92-question-bank-live.kql (the questions answered from the Eventhouse).

SQL is Spark SQL and runs in a Fabric notebook against the Lakehouse. "Now" is the newest
record in ops_scada_10min (view q_asof), so the answers do not depend on the clock of the session.
All times are UTC unless a query converts them.
"""
from __future__ import annotations

PERSONAS = {
    "SM": ("Site manager", "Runs the site day to day. Answers for production, availability, safety of the plan and cost."),
    "PE": ("Performance engineer", "Finds turbines that produce less than they should and explains why."),
    "RE": ("Reliability engineer", "Finds what fails, how often, what is developing, and what it did last time."),
    "MP": ("Maintenance planner", "Plans work, people and parts, and picks the time that costs the least production."),
    "AM": ("Asset and commercial manager", "Answers to the owner: revenue, budget, contracts, market, forecast."),
    "OP": ("Control room operator", "Watches the site live and makes the first decision when an alarm comes in."),
}

# View every query can use.
SETUP_SQL = """CREATE OR REPLACE TEMP VIEW q_asof AS
SELECT max(Timestamp) AS AsOf FROM ops_scada_10min"""

TECHNICAL = "('Component fault', 'Scheduled maintenance', 'Corrective maintenance', 'Technical derate')"
DOWN = "('Forced outage', 'Scheduled maintenance', 'Planned corrective action')"

QUESTIONS = [
    # ------------------------------------------------------------------ site manager
    dict(id="SM-01", question="How much energy did we produce last month, and how does that compare with the budget?",
         tables="ops_scada_10min, ops_monthly_budget",
         sql="""
WITH m AS (SELECT add_months(date_trunc('month', AsOf), -1) AS MonthStart, date_trunc('month', AsOf) AS MonthEnd FROM q_asof)
SELECT date_format(m.MonthStart, 'yyyy-MM')                               AS Month,
       round(sum(s.EnergyKwh) / 1000, 0)                                  AS EnergyMwh,
       max(b.P50EnergyMwh)                                                AS BudgetP50Mwh,
       max(b.P90EnergyMwh)                                                AS BudgetP90Mwh,
       round(100 * sum(s.EnergyKwh) / 1000 / max(b.P50EnergyMwh), 1)      AS PctOfBudget
FROM ops_scada_10min s
CROSS JOIN m
JOIN ops_monthly_budget b ON b.YearMonth = date_format(m.MonthStart, 'yyyy-MM')
WHERE s.Timestamp >= m.MonthStart AND s.Timestamp < m.MonthEnd
GROUP BY m.MonthStart"""),
    dict(id="SM-02", question="Show production, budget and capacity factor by month for the last 12 months.",
         tables="ops_scada_10min, ops_monthly_budget, ref_turbines",
         sql="""
SELECT date_format(s.Timestamp, 'yyyy-MM')                                AS Month,
       round(sum(s.EnergyKwh) / 1000, 0)                                  AS EnergyMwh,
       max(b.P50EnergyMwh)                                                AS BudgetP50Mwh,
       round(100 * sum(s.EnergyKwh) / 1000 / max(b.P50EnergyMwh), 1)      AS PctOfBudget,
       round(100 * sum(s.EnergyKwh) / sum(t.ratedPowerKw / 6.0), 1)       AS CapacityFactorPct
FROM ops_scada_10min s
JOIN ref_turbines t ON t.turbineId = s.TurbineId
JOIN ops_monthly_budget b ON b.YearMonth = date_format(s.Timestamp, 'yyyy-MM')
CROSS JOIN q_asof a
WHERE s.Timestamp >= add_months(date_trunc('month', a.AsOf), -12) AND s.Timestamp < date_trunc('month', a.AsOf)
GROUP BY date_format(s.Timestamp, 'yyyy-MM')
ORDER BY Month"""),
    dict(id="SM-03", question="What was the availability of each turbine over the last 90 days? Which turbines are below 97 percent?",
         tables="ops_scada_10min",
         sql=f"""
SELECT s.TurbineId,
       round(100 * (1 - sum(CASE WHEN s.AvailabilityCategory IN {DOWN} THEN 1 ELSE 0 END) / count(*)), 2) AS TimeAvailabilityPct,
       round(100 * sum(s.EnergyKwh) / (sum(s.EnergyKwh)
             + sum(CASE WHEN s.LossCause IN {TECHNICAL} THEN s.LostEnergyKwh ELSE 0 END)), 2)             AS EnergyAvailabilityPct,
       round(sum(CASE WHEN s.AvailabilityCategory = 'Forced outage' THEN 1 ELSE 0 END) / 6.0, 1)          AS ForcedOutageHours,
       round(sum(s.EnergyKwh) / 1000, 0)                                                                  AS EnergyMwh
FROM ops_scada_10min s
CROSS JOIN q_asof a
WHERE s.Timestamp >= a.AsOf - INTERVAL 90 DAYS AND s.AvailabilityCategory <> 'Information unavailable'
GROUP BY s.TurbineId
ORDER BY TimeAvailabilityPct"""),
    dict(id="SM-04", question="What did we lose energy to in the last 12 months, and what was it worth?",
         tables="ops_scada_10min, ref_site",
         sql="""
SELECT s.LossCause,
       round(sum(s.LostEnergyKwh) / 1000, 0)                                         AS LostEnergyMwh,
       round(sum(s.LostEnergyKwh) / 1000 * max(st.ppaPriceUsdPerMwh), 0)             AS ValueAtContractPriceUsd,
       round(100 * sum(s.LostEnergyKwh) / sum(sum(s.LostEnergyKwh)) OVER (), 1)      AS SharePct
FROM ops_scada_10min s
CROSS JOIN q_asof a
CROSS JOIN ref_site st
WHERE s.Timestamp >= add_months(a.AsOf, -12) AND s.LostEnergyKwh > 0
GROUP BY s.LossCause
ORDER BY LostEnergyMwh DESC"""),
    dict(id="SM-05", question="Which work orders are open, overdue or planned for the next 30 days?",
         tables="ops_work_orders, ref_technicians",
         sql="""
SELECT w.WorkOrderId, w.TurbineId, w.WorkType, w.Priority, w.Status,
       to_date(w.ScheduledDate)                                           AS ScheduledDay,
       datediff(w.ScheduledDate, a.AsOf)                                  AS DaysFromNow,
       CASE WHEN w.ScheduledDate < a.AsOf THEN 'Overdue'
            WHEN w.ScheduledDate < a.AsOf + INTERVAL 30 DAYS THEN 'Next 30 days'
            ELSE 'Later' END                                              AS Timing,
       w.Summary, t.name AS LeadTechnician
FROM ops_work_orders w
CROSS JOIN q_asof a
LEFT JOIN ref_technicians t ON t.technicianId = w.LeadTechnicianId
WHERE w.Status <> 'Closed'
ORDER BY w.ScheduledDate"""),
    dict(id="SM-06", question="Which spare parts are at or below their reorder point, and how long would a new one take to arrive?",
         tables="ref_spare_parts",
         sql="""
SELECT partId, description, componentCode, quantityOnHand, reorderPoint, leadTimeDays, unitCostUsd
FROM ref_spare_parts
WHERE quantityOnHand <= reorderPoint
ORDER BY leadTimeDays DESC"""),

    # ------------------------------------------------------------------ performance engineer
    dict(id="PE-01", question="Which turbines produce less than they should for the wind they get? Rank them by performance index for the last 90 days.",
         tables="ops_scada_10min",
         sql="""
SELECT s.TurbineId,
       round(sum(s.EnergyKwh) / sum(s.PossibleEnergyKwh), 4)                AS PerformanceIndex,
       round((sum(s.PossibleEnergyKwh) - sum(s.EnergyKwh)) / 1000, 0)       AS ShortfallMwh,
       round(count(*) / 6.0, 0)                                             AS HoursInFullPerformance
FROM ops_scada_10min s
CROSS JOIN q_asof a
WHERE s.Timestamp >= a.AsOf - INTERVAL 90 DAYS AND s.AvailabilityCategory = 'Full performance'
GROUP BY s.TurbineId
ORDER BY PerformanceIndex"""),
    dict(id="PE-02", question="Compare the measured power curve of WT-09 with the rest of the fleet and with the manufacturer's curve.",
         tables="ops_scada_10min, ref_power_curve",
         note="Wind speed is normalised to standard air density (1.225 kg/m3), as IEC 61400-12-1 prescribes for pitch-regulated turbines.",
         sql="""
WITH binned AS (
    SELECT s.TurbineId, s.ActivePower,
           round(s.WindSpeed * pow(s.AirDensity / 1.225, 1.0 / 3)) AS WindBin
    FROM ops_scada_10min s
    CROSS JOIN q_asof a
    WHERE s.Timestamp >= a.AsOf - INTERVAL 180 DAYS AND s.AvailabilityCategory = 'Full performance')
SELECT b.WindBin                                                                       AS WindSpeedBin,
       max(r.powerKw)                                                                  AS ManufacturerKw,
       round(avg(CASE WHEN b.TurbineId <> 'WT-09' THEN b.ActivePower END), 0)          AS RestOfFleetKw,
       round(avg(CASE WHEN b.TurbineId = 'WT-09' THEN b.ActivePower END), 0)           AS Wt09Kw,
       round(100 * (avg(CASE WHEN b.TurbineId = 'WT-09' THEN b.ActivePower END)
                    / avg(CASE WHEN b.TurbineId <> 'WT-09' THEN b.ActivePower END) - 1), 1) AS Wt09VsFleetPct
FROM binned b
JOIN ref_power_curve r ON r.windSpeed = b.WindBin
WHERE b.WindBin BETWEEN 4 AND 13
GROUP BY b.WindBin
ORDER BY b.WindBin"""),
    dict(id="PE-03", question="Is any turbine misaligned with the wind? Compare each nacelle direction with the wind direction at the met mast.",
         tables="ops_scada_10min, ops_met_10min",
         sql="""
SELECT s.TurbineId,
       round(avg(pmod(s.NacelleDirection - m.WindDirection + 540, 360) - 180), 1)  AS MeanOffsetDeg,
       count(*)                                                                    AS Records
FROM ops_scada_10min s
JOIN ops_met_10min m ON m.Timestamp = s.Timestamp
CROSS JOIN q_asof a
WHERE s.Timestamp >= a.AsOf - INTERVAL 60 DAYS AND s.State = 'RUNNING' AND m.WindSpeed BETWEEN 6 AND 12
GROUP BY s.TurbineId
ORDER BY abs(avg(pmod(s.NacelleDirection - m.WindDirection + 540, 360) - 180)) DESC"""),
    dict(id="PE-04", question="When did WT-05 and WT-09 start to underperform? Show their performance index by month against the rest of the fleet.",
         tables="ops_scada_10min",
         sql="""
SELECT date_format(s.Timestamp, 'yyyy-MM') AS Month,
       round(sum(CASE WHEN s.TurbineId = 'WT-05' THEN s.EnergyKwh END)
             / sum(CASE WHEN s.TurbineId = 'WT-05' THEN s.PossibleEnergyKwh END), 3)  AS Wt05,
       round(sum(CASE WHEN s.TurbineId = 'WT-09' THEN s.EnergyKwh END)
             / sum(CASE WHEN s.TurbineId = 'WT-09' THEN s.PossibleEnergyKwh END), 3)  AS Wt09,
       round(sum(CASE WHEN s.TurbineId NOT IN ('WT-05', 'WT-09') THEN s.EnergyKwh END)
             / sum(CASE WHEN s.TurbineId NOT IN ('WT-05', 'WT-09') THEN s.PossibleEnergyKwh END), 3) AS RestOfFleet
FROM ops_scada_10min s
CROSS JOIN q_asof a
WHERE s.Timestamp >= add_months(date_trunc('month', a.AsOf), -11) AND s.AvailabilityCategory = 'Full performance'
GROUP BY date_format(s.Timestamp, 'yyyy-MM')
ORDER BY Month"""),
    dict(id="PE-05", question="From which wind directions do the turbines get the least wind compared with the met mast, and which turbine is affected most?",
         tables="ops_scada_10min, ops_met_10min",
         note="A ratio below 1 is mostly wake from upwind turbines; a ratio above 1 is terrain speed-up.",
         sql="""
WITH r AS (
    SELECT floor(pmod(m.WindDirection + 15, 360) / 30) * 30 AS SectorDeg, s.TurbineId,
           avg(s.WindSpeed) / avg(m.WindSpeed) AS Ratio, count(*) AS Records
    FROM ops_scada_10min s
    JOIN ops_met_10min m ON m.Timestamp = s.Timestamp
    CROSS JOIN q_asof a
    WHERE s.Timestamp >= add_months(a.AsOf, -12) AND s.AvailabilityCategory = 'Full performance'
      AND m.WindSpeed BETWEEN 5 AND 12
    GROUP BY floor(pmod(m.WindDirection + 15, 360) / 30) * 30, s.TurbineId)
SELECT cast(SectorDeg AS int)                                    AS SectorDeg,
       round(100 * sum(Records) / sum(sum(Records)) OVER (), 1)  AS ShareOfTimePct,
       round(avg(Ratio), 3)                                      AS FarmToMastWindRatio,
       min_by(TurbineId, Ratio)                                  AS MostAffectedTurbine,
       round(min(Ratio), 3)                                      AS ItsRatio
FROM r
GROUP BY SectorDeg
ORDER BY SectorDeg"""),
    dict(id="PE-06", question="How many hours and how much energy did we lose to icing and to high-wind shutdowns, by month?",
         tables="ops_scada_10min",
         sql="""
SELECT date_format(s.Timestamp, 'yyyy-MM')        AS Month,
       s.LossCause,
       round(count(*) / 6.0, 0)                   AS TurbineHours,
       round(sum(s.LostEnergyKwh) / 1000, 0)      AS LostEnergyMwh
FROM ops_scada_10min s
CROSS JOIN q_asof a
WHERE s.Timestamp >= add_months(a.AsOf, -12) AND s.LossCause IN ('Icing', 'High wind')
GROUP BY date_format(s.Timestamp, 'yyyy-MM'), s.LossCause
ORDER BY Month, s.LossCause"""),
    dict(id="PE-07", question="Why were we above or below budget in each of the last six months: the wind, the turbines, or curtailment?",
         tables="ops_scada_10min, ops_met_10min, ops_monthly_budget",
         note="Wind index = mean wind speed of the month divided by the long-term mean for that month. Energy changes about twice as fast as the wind index.",
         sql=f"""
WITH e AS (
    SELECT date_format(Timestamp, 'yyyy-MM') AS Month,
           sum(EnergyKwh) / 1000 AS EnergyMwh,
           sum(CASE WHEN LossCause IN {TECHNICAL} THEN LostEnergyKwh ELSE 0 END) / 1000 AS TurbineLossMwh,
           sum(CASE WHEN LossCause = 'Grid curtailment' THEN LostEnergyKwh ELSE 0 END) / 1000 AS CurtailmentMwh,
           sum(CASE WHEN LossCause IN ('Icing', 'High wind', 'Grid outage') THEN LostEnergyKwh ELSE 0 END) / 1000 AS WeatherAndGridLossMwh
    FROM ops_scada_10min
    GROUP BY date_format(Timestamp, 'yyyy-MM')),
w AS (
    SELECT date_format(Timestamp, 'yyyy-MM') AS Month, avg(WindSpeed) AS MeanWindSpeed
    FROM ops_met_10min
    GROUP BY date_format(Timestamp, 'yyyy-MM'))
SELECT e.Month,
       round(e.EnergyMwh, 0)                               AS EnergyMwh,
       b.P50EnergyMwh                                      AS BudgetP50Mwh,
       round(e.EnergyMwh - b.P50EnergyMwh, 0)              AS VarianceMwh,
       round(w.MeanWindSpeed, 2)                           AS MeanWindSpeed,
       b.LongTermWindSpeed,
       round(100 * w.MeanWindSpeed / b.LongTermWindSpeed, 1) AS WindIndexPct,
       round(e.TurbineLossMwh, 0)                          AS TurbineLossMwh,
       round(e.CurtailmentMwh, 0)                          AS CurtailmentMwh,
       round(e.WeatherAndGridLossMwh, 0)                   AS WeatherAndGridLossMwh
FROM e
JOIN w ON w.Month = e.Month
JOIN ops_monthly_budget b ON b.YearMonth = e.Month
CROSS JOIN q_asof a
WHERE e.Month < date_format(a.AsOf, 'yyyy-MM') AND e.Month >= date_format(add_months(a.AsOf, -6), 'yyyy-MM')
ORDER BY e.Month"""),

    # ------------------------------------------------------------------ reliability engineer
    dict(id="RE-01", question="Which components cost us the most downtime and energy in the last 12 months?",
         tables="ops_turbine_events, ops_work_orders",
         sql="""
SELECT e.Component,
       count(*)                                AS Failures,
       round(sum(e.DurationHours), 0)          AS DowntimeHours,
       round(avg(e.DurationHours), 1)          AS MeanTimeToRepairHours,
       round(sum(e.LostEnergyMwh), 0)          AS LostEnergyMwh,
       round(sum(w.TotalCostUsd), 0)           AS RepairCostUsd
FROM ops_turbine_events e
LEFT JOIN ops_work_orders w ON w.WorkOrderId = e.WorkOrderId
CROSS JOIN q_asof a
WHERE e.Cause = 'Component fault' AND e.StartTime >= add_months(a.AsOf, -12)
GROUP BY e.Component
ORDER BY LostEnergyMwh DESC"""),
    dict(id="RE-02", question="What are the mean time between failures and the mean time to repair of each turbine over the last 12 months?",
         tables="ops_turbine_events, ref_turbines",
         note="A failure here is a fault that needed a technician (Cause = 'Component fault'). Faults that the controller reset by itself are counted separately.",
         sql="""
SELECT t.turbineId                                                                          AS TurbineId,
       count(CASE WHEN e.Cause = 'Component fault' THEN 1 END)                              AS Failures,
       count(CASE WHEN e.Cause = 'Auto-reset fault' THEN 1 END)                             AS AutoResets,
       round(coalesce(sum(CASE WHEN e.Cause = 'Component fault' THEN e.DurationHours END), 0), 0) AS DowntimeHours,
       round(avg(CASE WHEN e.Cause = 'Component fault' THEN e.DurationHours END), 1)        AS MeanTimeToRepairHours,
       round((8760 - coalesce(sum(CASE WHEN e.Cause = 'Component fault' THEN e.DurationHours END), 0))
             / nullif(count(CASE WHEN e.Cause = 'Component fault' THEN 1 END), 0), 0)       AS MeanTimeBetweenFailuresHours
FROM ref_turbines t
CROSS JOIN q_asof a
LEFT JOIN ops_turbine_events e
       ON e.TurbineId = t.turbineId AND e.AvailabilityCategory = 'Forced outage' AND e.StartTime >= add_months(a.AsOf, -12)
GROUP BY t.turbineId
ORDER BY Failures DESC, TurbineId"""),
    dict(id="RE-03", question="Do we have repeat offenders: the same component failing again and again on the same turbine?",
         tables="ops_turbine_events",
         sql="""
SELECT e.TurbineId, e.Component,
       count(*)                                                     AS Faults,
       count(CASE WHEN e.Cause = 'Component fault' THEN 1 END)      AS NeededATechnician,
       round(sum(e.DurationHours), 0)                               AS DowntimeHours,
       round(sum(e.LostEnergyMwh), 0)                               AS LostEnergyMwh,
       max_by(e.FailureMode, e.StartTime)                           AS LatestFailureMode
FROM ops_turbine_events e
CROSS JOIN q_asof a
WHERE e.AvailabilityCategory = 'Forced outage' AND e.Component IS NOT NULL AND e.StartTime >= add_months(a.AsOf, -12)
GROUP BY e.TurbineId, e.Component
ORDER BY Faults DESC
LIMIT 8"""),
    dict(id="RE-04", question="What are the ten most frequent alarms of the last 90 days, and on which turbine does each one occur most?",
         tables="ops_alarm_log, ref_alarm_codes",
         sql="""
WITH n AS (
    SELECT l.AlarmCode, l.TurbineId, count(*) AS Times
    FROM ops_alarm_log l
    CROSS JOIN q_asof a
    WHERE l.RaisedAt >= a.AsOf - INTERVAL 90 DAYS
    GROUP BY l.AlarmCode, l.TurbineId)
SELECT n.AlarmCode, c.description AS Description, c.severity AS Severity,
       sum(n.Times)                     AS Times,
       count(*)                         AS TurbinesAffected,
       max_by(n.TurbineId, n.Times)     AS MostAffectedTurbine,
       max(n.Times)                     AS TimesOnThatTurbine
FROM n
JOIN ref_alarm_codes c ON c.alarmCode = n.AlarmCode
GROUP BY n.AlarmCode, c.description, c.severity
ORDER BY Times DESC
LIMIT 10"""),
    dict(id="RE-05", question="Is any gearbox running hotter or rougher than the rest of the fleet at the same load?",
         tables="ops_scada_10min",
         sql="""
WITH x AS (
    SELECT s.TurbineId,
           avg(s.GearboxBearingTemp) AS BearingTemp, avg(s.GearboxOilTemp) AS OilTemp, avg(s.GearboxVibration) AS Vibration
    FROM ops_scada_10min s
    CROSS JOIN q_asof a
    WHERE s.Timestamp >= a.AsOf - INTERVAL 30 DAYS AND s.State = 'RUNNING' AND s.ActivePower > 3000
    GROUP BY s.TurbineId)
SELECT TurbineId,
       round(BearingTemp, 1)                                AS GearboxBearingTemp,
       round(BearingTemp - avg(BearingTemp) OVER (), 1)     AS BearingTempVsFleet,
       round(OilTemp, 1)                                    AS GearboxOilTemp,
       round(OilTemp - avg(OilTemp) OVER (), 1)             AS OilTempVsFleet,
       round(Vibration, 2)                                  AS GearboxVibration,
       round(Vibration - avg(Vibration) OVER (), 2)         AS VibrationVsFleet
FROM x
ORDER BY BearingTempVsFleet DESC"""),
    dict(id="RE-06", question="Since when has the WT-07 gearbox been drifting away from the fleet? Show the trend by week.",
         tables="ops_scada_10min",
         sql="""
SELECT to_date(date_trunc('week', s.Timestamp))                                                AS WeekStarting,
       round(avg(CASE WHEN s.TurbineId = 'WT-07' THEN s.GearboxBearingTemp END), 1)            AS Wt07BearingTemp,
       round(avg(CASE WHEN s.TurbineId <> 'WT-07' THEN s.GearboxBearingTemp END), 1)           AS FleetBearingTemp,
       round(avg(CASE WHEN s.TurbineId = 'WT-07' THEN s.GearboxVibration END), 2)              AS Wt07Vibration,
       round(avg(CASE WHEN s.TurbineId <> 'WT-07' THEN s.GearboxVibration END), 2)             AS FleetVibration
FROM ops_scada_10min s
CROSS JOIN q_asof a
WHERE s.Timestamp >= a.AsOf - INTERVAL 182 DAYS AND s.State = 'RUNNING' AND s.ActivePower > 2000
GROUP BY to_date(date_trunc('week', s.Timestamp))
ORDER BY WeekStarting"""),
    dict(id="RE-07", question="What do the gearbox oil samples of WT-07 show, and how do they compare with WT-02 before its bearing failed?",
         tables="ops_oil_analysis",
         sql="""
SELECT TurbineId, SampleDate, IronPpm, CopperPpm, WaterPpm, ParticleCountIso4406, Condition, LabComment
FROM ops_oil_analysis
WHERE TurbineId IN ('WT-02', 'WT-07')
ORDER BY TurbineId, SampleDate"""),
    dict(id="RE-08", question="Have we had a major gearbox failure before? What happened, how long was the turbine down and what did it cost?",
         tables="ops_turbine_events, ops_work_orders",
         sql="""
SELECT e.TurbineId, to_date(e.StartTime) AS FailureDate, e.FailureMode,
       round(e.DurationHours, 0)            AS DowntimeHours,
       round(e.LostEnergyMwh, 0)            AS LostEnergyMwh,
       w.WorkOrderId, w.Summary,
       round(w.TotalCostUsd, 0)             AS TotalCostUsd,
       w.CostBorneBy,
       round(w.WaitingForPartsHours / 24, 1) AS DaysWaitingForPartsOrCrane,
       w.Findings
FROM ops_turbine_events e
JOIN ops_work_orders w ON w.WorkOrderId = e.WorkOrderId
WHERE e.ComponentCode = 'GBX' AND e.FaultClass = 'C'
ORDER BY w.TotalCostUsd DESC
LIMIT 5"""),
    dict(id="RE-09", question="Which components are still under warranty, until when, and under which contract?",
         tables="ref_components, ref_contracts",
         sql="""
SELECT c.componentType, count(*) AS Components, c.warrantyEndDate,
       datediff(c.warrantyEndDate, a.AsOf) AS DaysLeft,
       c.warrantyContractId, k.counterparty, k.terms
FROM ref_components c
CROSS JOIN q_asof a
LEFT JOIN ref_contracts k ON k.contractId = c.warrantyContractId
WHERE c.warrantyEndDate >= to_date(a.AsOf)
GROUP BY c.componentType, c.warrantyEndDate, datediff(c.warrantyEndDate, a.AsOf), c.warrantyContractId, k.counterparty, k.terms
ORDER BY c.warrantyEndDate, c.componentType"""),
    dict(id="RE-10", question="Which blade findings of category 3 or worse are still open, and is the repair planned?",
         tables="ops_blade_inspections, ops_work_orders",
         note="Severity categories run from 1 (cosmetic) to 5 (stop the turbine).",
         sql="""
SELECT b.TurbineId, b.Blade, b.InspectionDate, b.FindingType, b.SeverityCategory, b.SpanPositionM,
       b.RecommendedAction, b.Status, b.RepairWorkOrderId,
       to_date(w.ScheduledDate) AS RepairScheduledDay, w.Status AS RepairStatus
FROM ops_blade_inspections b
LEFT JOIN ops_work_orders w ON w.WorkOrderId = b.RepairWorkOrderId
WHERE b.Status <> 'Closed' AND b.SeverityCategory >= 3
ORDER BY b.SeverityCategory DESC, b.TurbineId, b.Blade"""),

    # ------------------------------------------------------------------ maintenance planner
    dict(id="MP-01", question="On which working day of the coming week would stopping one turbine for maintenance cost the least production, and is the wind low enough to work?",
         tables="ops_power_forecast, ref_site",
         note="Working hours 07:00 to 17:00 site time, Monday to Saturday. Technicians do not climb above 18 m/s; blade and crane work needs less than 10 m/s.",
         sql="""
WITH f AS (
    SELECT from_utc_timestamp(p.TargetTime, st.timezone) AS LocalTime, p.WindSpeed, p.WindSpeedP90, p.PowerMw, p.IcingRisk,
           st.turbineCount, st.ppaPriceUsdPerMwh
    FROM ops_power_forecast p
    CROSS JOIN ref_site st
    WHERE p.ForecastType = 'Latest')
SELECT to_date(LocalTime)                                             AS Day,
       date_format(LocalTime, 'EEEE')                                 AS Weekday,
       round(avg(WindSpeed), 1)                                       AS MeanWindSpeed,
       round(max(WindSpeedP90), 1)                                    AS HighestLikelyWindSpeed,
       sum(CASE WHEN WindSpeedP90 < 10 THEN 1 ELSE 0 END)             AS HoursCalmEnoughForBladeWork,
       round(sum(PowerMw) / max(turbineCount), 1)                     AS MwhLostIfOneTurbineIsStopped,
       round(sum(PowerMw) / max(turbineCount) * max(ppaPriceUsdPerMwh), 0) AS RevenueLostUsd,
       bool_or(IcingRisk)                                             AS IcingRisk
FROM f
WHERE hour(LocalTime) BETWEEN 7 AND 16 AND dayofweek(LocalTime) <> 1
GROUP BY to_date(LocalTime), date_format(LocalTime, 'EEEE')
HAVING count(*) = 10
ORDER BY MwhLostIfOneTurbineIsStopped"""),
    dict(id="MP-02", question="How good is our preventive maintenance compliance? Of the preventive work due in the last 12 months, how much was done on time?",
         tables="ops_work_orders",
         sql="""
SELECT CASE WHEN w.Status = 'Closed' AND w.ClosedDate <= w.ScheduledDate + INTERVAL 7 DAYS THEN '1 Done within a week of the plan'
            WHEN w.Status = 'Closed' THEN '2 Done late'
            ELSE '3 Not done, overdue' END                         AS Result,
       count(*)                                                    AS WorkOrders,
       round(100 * count(*) / sum(count(*)) OVER (), 1)            AS SharePct
FROM ops_work_orders w
CROSS JOIN q_asof a
WHERE w.WorkType = 'Preventive' AND w.ScheduledDate >= add_months(a.AsOf, -12) AND w.ScheduledDate < a.AsOf
GROUP BY 1
ORDER BY Result"""),
    dict(id="MP-03", question="Which repairs were held up by waiting for parts, and what did the waiting cost in lost energy?",
         tables="ops_work_orders, ops_turbine_events, ops_work_order_parts",
         sql="""
SELECT w.WorkOrderId, w.TurbineId, to_date(w.OpenedDate) AS Opened, w.Summary,
       round(w.WaitingForPartsHours / 24, 1)        AS DaysWaiting,
       round(w.DowntimeHours, 0)                    AS DowntimeHours,
       round(e.LostEnergyMwh, 0)                    AS LostEnergyMwh,
       concat_ws(', ', collect_list(p.PartId))      AS PartsUsed
FROM ops_work_orders w
JOIN ops_turbine_events e ON e.EventId = w.EventId
LEFT JOIN ops_work_order_parts p ON p.WorkOrderId = w.WorkOrderId
WHERE w.WaitingForPartsHours >= 48
GROUP BY w.WorkOrderId, w.TurbineId, to_date(w.OpenedDate), w.Summary, w.WaitingForPartsHours, w.DowntimeHours, e.LostEnergyMwh
ORDER BY w.WaitingForPartsHours DESC
LIMIT 10"""),
    dict(id="MP-04", question="Which spare parts did we use most in the last 12 months, and how many months of stock do we hold?",
         tables="ops_work_order_parts, ops_work_orders, ref_spare_parts",
         sql="""
WITH used AS (
    SELECT p.PartId, sum(p.Quantity) AS Quantity
    FROM ops_work_order_parts p
    JOIN ops_work_orders w ON w.WorkOrderId = p.WorkOrderId
    CROSS JOIN q_asof a
    WHERE w.OpenedDate >= add_months(a.AsOf, -12) AND w.Status = 'Closed'
    GROUP BY p.PartId)
SELECT sp.partId, sp.description,
       coalesce(u.Quantity, 0)                                   AS UsedInLast12Months,
       sp.quantityOnHand, sp.reorderPoint, sp.leadTimeDays,
       round(sp.quantityOnHand / (u.Quantity / 12.0), 1)         AS MonthsOfStock
FROM ref_spare_parts sp
LEFT JOIN used u ON u.PartId = sp.partId
ORDER BY UsedInLast12Months DESC, sp.partId
LIMIT 12"""),
    dict(id="MP-05", question="How was the technicians' time spent in the last 90 days: who led which kind of work?",
         tables="ops_work_orders, ref_technicians",
         sql="""
SELECT t.name AS LeadTechnician, t.role AS Role,
       count(*)                                                        AS WorkOrdersLed,
       count(CASE WHEN w.WorkType = 'Corrective' THEN 1 END)           AS Corrective,
       count(CASE WHEN w.WorkType = 'Preventive' THEN 1 END)           AS Preventive,
       round(sum(w.LaborHours), 0)                                     AS CrewLabourHours
FROM ops_work_orders w
JOIN ref_technicians t ON t.technicianId = w.LeadTechnicianId
CROSS JOIN q_asof a
WHERE w.Status = 'Closed' AND w.OpenedDate >= a.AsOf - INTERVAL 90 DAYS
GROUP BY t.name, t.role
ORDER BY CrewLabourHours DESC"""),

    # ------------------------------------------------------------------ asset and commercial manager
    dict(id="AM-01", question="What is our revenue for the year to date, and how does it compare with the budget?",
         tables="ops_scada_10min, ops_curtailments, ops_monthly_budget, ref_site",
         note="Revenue = energy at the contract price, plus economic curtailment, which the offtaker pays as deemed generation. The budget of the running month is counted pro rata.",
         sql="""
WITH y AS (SELECT date_trunc('year', AsOf) AS YearStart, AsOf FROM q_asof),
e AS (SELECT sum(s.EnergyKwh) / 1000 AS EnergyMwh FROM ops_scada_10min s CROSS JOIN y WHERE s.Timestamp >= y.YearStart),
c AS (SELECT sum(CASE WHEN c.Compensated THEN c.LostEnergyMwh ELSE 0 END) AS DeemedMwh,
             sum(CASE WHEN c.Compensated THEN 0 ELSE c.LostEnergyMwh END) AS UnpaidCurtailmentMwh
      FROM ops_curtailments c CROSS JOIN y WHERE c.StartTime >= y.YearStart),
b AS (SELECT sum(CASE WHEN b.YearMonth < date_format(y.AsOf, 'yyyy-MM') THEN b.BudgetRevenueUsd
                      ELSE b.BudgetRevenueUsd * day(y.AsOf) / day(last_day(y.AsOf)) END) AS BudgetRevenueUsd
      FROM ops_monthly_budget b CROSS JOIN y
      WHERE b.Year = year(y.AsOf) AND b.YearMonth <= date_format(y.AsOf, 'yyyy-MM'))
SELECT round(e.EnergyMwh, 0)                                                       AS EnergyMwh,
       round(c.DeemedMwh, 0)                                                       AS DeemedGenerationMwh,
       round((e.EnergyMwh + c.DeemedMwh) * st.ppaPriceUsdPerMwh, 0)                AS RevenueUsd,
       round(b.BudgetRevenueUsd, 0)                                                AS BudgetRevenueUsd,
       round(100 * (e.EnergyMwh + c.DeemedMwh) * st.ppaPriceUsdPerMwh / b.BudgetRevenueUsd, 1) AS PctOfBudget,
       round(c.UnpaidCurtailmentMwh * st.ppaPriceUsdPerMwh, 0)                     AS RevenueLostToUnpaidCurtailmentUsd
FROM e CROSS JOIN c CROSS JOIN b CROSS JOIN ref_site st"""),
    dict(id="AM-02", question="How much were we curtailed in the last 12 months, why, and how much of it were we paid for?",
         tables="ops_curtailments, ref_site",
         sql="""
SELECT c.Reason, c.InstructedBy, c.Compensated,
       count(*)                                                                       AS Events,
       round(sum(c.DurationHours), 0)                                                 AS Hours,
       round(sum(c.LostEnergyMwh), 0)                                                 AS CurtailedMwh,
       round(sum(CASE WHEN c.Compensated THEN 0 ELSE c.LostEnergyMwh END) * max(st.ppaPriceUsdPerMwh), 0) AS RevenueLostUsd,
       round(avg(c.AvgRealTimePriceUsdPerMwh), 1)                                     AS MeanRealTimePrice
FROM ops_curtailments c
CROSS JOIN q_asof a
CROSS JOIN ref_site st
WHERE c.StartTime >= add_months(a.AsOf, -12)
GROUP BY c.Reason, c.InstructedBy, c.Compensated
ORDER BY CurtailedMwh DESC"""),
    dict(id="AM-03", question="Did the service provider meet the availability guarantee in the last contract year, and what are the liquidated damages if not?",
         tables="ops_scada_10min, ops_turbine_events, ref_contracts",
         note="Contract year 1 July to 30 June. Follows the terms of contract CT-SMA-001: outages caused by the grid or by force majeure are excluded, scheduled maintenance counts only above the allowance.",
         sql="""
WITH cy AS (
    SELECT cast(make_date(year(AsOf) - CASE WHEN month(AsOf) >= 7 THEN 1 ELSE 2 END, 7, 1) AS timestamp) AS YearStart FROM q_asof),
k AS (
    SELECT guaranteedAvailabilityPct AS Guarantee, liquidatedDamagesUsdPerMwh AS DamagesRate,
           scheduledMaintenanceAllowanceHoursPerTurbineYear AS Allowance
    FROM ref_contracts WHERE contractId = 'CT-SMA-001'),
h AS (
    SELECT s.TurbineId,
           count(*) / 6.0 AS PeriodHours,
           sum(CASE WHEN s.AvailabilityCategory IN ('Forced outage', 'Planned corrective action') THEN 1 ELSE 0 END) / 6.0 AS OutageHours,
           sum(CASE WHEN s.AvailabilityCategory = 'Scheduled maintenance' THEN 1 ELSE 0 END) / 6.0 AS ScheduledHours,
           sum(CASE WHEN s.AvailabilityCategory IN ('Out of electrical specification', 'Out of environmental specification',
                                                    'Requested shutdown', 'Information unavailable') THEN 1 ELSE 0 END) / 6.0 AS ExcludedHours,
           sum(s.PossibleEnergyKwh) / 1000 AS PossibleMwh
    FROM ops_scada_10min s CROSS JOIN cy
    WHERE s.Timestamp >= cy.YearStart AND s.Timestamp < add_months(cy.YearStart, 12)
    GROUP BY s.TurbineId),
x AS (
    SELECT e.TurbineId, sum(e.DurationHours) AS NotTheProvidersHours
    FROM ops_turbine_events e CROSS JOIN cy
    WHERE e.AvailabilityCategory = 'Forced outage' AND e.ResponsibleParty <> 'Service provider'
      AND e.StartTime >= cy.YearStart AND e.StartTime < add_months(cy.YearStart, 12)
    GROUP BY e.TurbineId),
t AS (
    SELECT h.TurbineId, h.PossibleMwh,
           100 * (1 - (h.OutageHours - coalesce(x.NotTheProvidersHours, 0) + greatest(h.ScheduledHours - k.Allowance, 0))
                      / (h.PeriodHours - h.ExcludedHours - coalesce(x.NotTheProvidersHours, 0))) AS AvailabilityPct
    FROM h LEFT JOIN x ON x.TurbineId = h.TurbineId CROSS JOIN k)
SELECT to_date(max(cy.YearStart))                                                   AS ContractYearStart,
       round(avg(t.AvailabilityPct), 2)                                             AS ContractualAvailabilityPct,
       max(k.Guarantee)                                                             AS GuaranteePct,
       round(min(t.AvailabilityPct), 2)                                             AS LowestTurbinePct,
       min_by(t.TurbineId, t.AvailabilityPct)                                       AS LowestTurbine,
       round(greatest(max(k.Guarantee) - avg(t.AvailabilityPct), 0) / 100 * sum(t.PossibleMwh), 0) AS EnergyBelowGuaranteeMwh,
       round(greatest(max(k.Guarantee) - avg(t.AvailabilityPct), 0) / 100 * sum(t.PossibleMwh) * max(k.DamagesRate), 0) AS LiquidatedDamagesUsd
FROM t CROSS JOIN k CROSS JOIN cy"""),
    dict(id="AM-04", question="What have repairs cost us this year, compared with the budget, and what was covered by warranty?",
         tables="ops_work_orders, ops_monthly_budget, ops_scada_10min",
         note="CostBorneBy says who pays: the owner (corrective work), the warranty, or the service agreement (scheduled work, inside the fixed fee).",
         sql="""
WITH y AS (SELECT date_trunc('year', AsOf) AS YearStart, AsOf FROM q_asof),
w AS (SELECT sum(CASE WHEN w.CostBorneBy = 'Owner' THEN w.TotalCostUsd ELSE 0 END)    AS OwnerUsd,
             sum(CASE WHEN w.CostBorneBy = 'Warranty' THEN w.TotalCostUsd ELSE 0 END) AS WarrantyUsd,
             count(CASE WHEN w.CostBorneBy = 'Owner' THEN 1 END)                      AS Repairs
      FROM ops_work_orders w CROSS JOIN y
      WHERE w.WorkType = 'Corrective' AND w.Status = 'Closed' AND w.OpenedDate >= y.YearStart),
b AS (SELECT sum(CASE WHEN b.YearMonth < date_format(y.AsOf, 'yyyy-MM') THEN b.BudgetCorrectiveMaintenanceUsd
                      ELSE b.BudgetCorrectiveMaintenanceUsd * day(y.AsOf) / day(last_day(y.AsOf)) END) AS BudgetUsd
      FROM ops_monthly_budget b CROSS JOIN y
      WHERE b.Year = year(y.AsOf) AND b.YearMonth <= date_format(y.AsOf, 'yyyy-MM')),
e AS (SELECT sum(s.EnergyKwh) / 1000 AS EnergyMwh FROM ops_scada_10min s CROSS JOIN y WHERE s.Timestamp >= y.YearStart)
SELECT w.Repairs,
       round(w.OwnerUsd, 0)                         AS RepairCostPaidByOwnerUsd,
       round(b.BudgetUsd, 0)                        AS BudgetUsd,
       round(100 * w.OwnerUsd / b.BudgetUsd, 1)     AS PctOfBudget,
       round(w.OwnerUsd / e.EnergyMwh, 2)           AS RepairCostUsdPerMwh,
       round(w.WarrantyUsd, 0)                      AS CoveredByWarrantyUsd
FROM w CROSS JOIN b CROSS JOIN e"""),
    dict(id="AM-05", question="How accurate was the day-ahead power forecast in each of the last six months?",
         tables="ops_power_forecast, ops_scada_10min, ref_site",
         note="The forecast is for what the wind allows. It is compared with possible power, so that outages and curtailment do not count as forecast error.",
         sql="""
WITH actual AS (
    SELECT date_trunc('hour', Timestamp) AS Hour,
           sum(PossiblePower) / 6 / 1000 AS PossibleMw, sum(ActivePower) / 6 / 1000 AS ActualMw
    FROM ops_scada_10min
    GROUP BY date_trunc('hour', Timestamp))
SELECT date_format(f.TargetTime, 'yyyy-MM')                                                       AS Month,
       round(100 * avg(abs(f.PowerMw - x.PossibleMw)) / max(st.capacityMw), 1)                    AS MeanAbsoluteErrorPctOfCapacity,
       round(100 * avg(f.PowerMw - x.PossibleMw) / max(st.capacityMw), 1)                         AS BiasPctOfCapacity,
       round(100 * avg(CASE WHEN x.PossibleMw BETWEEN f.PowerMwP10 AND f.PowerMwP90 THEN 1.0 ELSE 0.0 END), 0) AS HoursInsideP10P90BandPct,
       round(100 * avg(abs(f.PowerMw - x.ActualMw)) / max(st.capacityMw), 1)                      AS ErrorAgainstActualPctOfCapacity
FROM ops_power_forecast f
JOIN actual x ON x.Hour = f.TargetTime
CROSS JOIN ref_site st
CROSS JOIN q_asof a
WHERE f.ForecastType = 'Day-ahead'
  AND f.TargetTime >= add_months(date_trunc('month', a.AsOf), -6) AND f.TargetTime < date_trunc('month', a.AsOf)
GROUP BY date_format(f.TargetTime, 'yyyy-MM')
ORDER BY Month"""),
    dict(id="AM-06", question="What would our energy have earned on the real-time market in the last 12 months, compared with the contract price?",
         tables="ops_scada_10min, ops_market_prices, ref_site",
         sql="""
WITH h AS (
    SELECT date_trunc('hour', Timestamp) AS Hour, sum(EnergyKwh) / 1000 AS EnergyMwh
    FROM ops_scada_10min
    GROUP BY date_trunc('hour', Timestamp))
SELECT round(sum(h.EnergyMwh), 0)                                                         AS EnergyMwh,
       max(st.ppaPriceUsdPerMwh)                                                          AS ContractPrice,
       round(sum(h.EnergyMwh * p.RealTimePriceUsdPerMwh) / sum(h.EnergyMwh), 2)           AS CapturedRealTimePrice,
       round(avg(p.RealTimePriceUsdPerMwh), 2)                                            AS MeanRealTimePrice,
       round(sum(h.EnergyMwh * (st.ppaPriceUsdPerMwh - p.RealTimePriceUsdPerMwh)), 0)     AS ContractValueOverMarketUsd,
       count(CASE WHEN p.RealTimePriceUsdPerMwh < 0 THEN 1 END)                           AS HoursWithNegativePrice
FROM h
JOIN ops_market_prices p ON p.Timestamp = h.Hour
CROSS JOIN ref_site st
CROSS JOIN q_asof a
WHERE h.Hour >= add_months(a.AsOf, -12)"""),
    dict(id="AM-07", question="How much carbon dioxide did the site avoid this year?",
         tables="ops_scada_10min, ref_site",
         note="Energy times the assumed emission intensity of the grid in ref_site.",
         sql="""
SELECT round(sum(s.EnergyKwh) / 1000, 0)                                                 AS EnergyMwh,
       max(st.gridEmissionFactorKgCo2PerMwh)                                             AS GridKgCo2PerMwh,
       round(sum(s.EnergyKwh) / 1000 * max(st.gridEmissionFactorKgCo2PerMwh) / 1000, 0)  AS TonnesCo2Avoided
FROM ops_scada_10min s
CROSS JOIN q_asof a
CROSS JOIN ref_site st
WHERE s.Timestamp >= date_trunc('year', a.AsOf)"""),

    # ------------------------------------------------------------------ control room operator (history side)
    dict(id="OP-01", question="A gearbox vibration alarm came in. What does it mean, what will the controller do, and which procedure applies?",
         tables="ref_alarm_codes, ref_sop_index",
         sql="""
SELECT c.alarmCode, c.severity, c.description, c.threshold, c.unit, c.controllerAction, c.sopId, s.title AS Procedure, s.file
FROM ref_alarm_codes c
LEFT JOIN ref_sop_index s ON s.sopId = c.sopId
WHERE c.alarmCode LIKE 'GBX-VIB%' OR c.alarmCode LIKE 'GBX-OIL-TEMP%'
ORDER BY c.threshold"""),
    dict(id="OP-02", question="Who is on call, and in which order do I escalate?",
         tables="ref_oncall_roster, ref_technicians",
         sql="""
SELECT r.escalationOrder, r.role, r.shift, r.contactChannel, concat_ws(', ', collect_list(t.name)) AS People
FROM ref_oncall_roster r
LEFT JOIN ref_technicians t ON t.onCallRoleId = r.roleId
WHERE r.onCall = true
GROUP BY r.escalationOrder, r.role, r.shift, r.contactChannel
ORDER BY r.escalationOrder, r.shift"""),
    dict(id="OP-03", question="How often did gearbox alarms come up on each turbine in the last 12 months? Is WT-07 different?",
         tables="ops_alarm_log, ref_alarm_codes",
         sql="""
SELECT l.TurbineId,
       count(*)                                            AS GearboxAlarms,
       count(CASE WHEN c.severity = 'critical' THEN 1 END) AS OfWhichCritical,
       to_date(max(l.RaisedAt))                            AS LastRaised
FROM ops_alarm_log l
JOIN ref_alarm_codes c ON c.alarmCode = l.AlarmCode
CROSS JOIN q_asof a
WHERE c.component = 'gearbox' AND l.RaisedAt >= add_months(a.AsOf, -12)
GROUP BY l.TurbineId
ORDER BY GearboxAlarms DESC"""),
    dict(id="OP-04", question="What does the forecast say for the next 24 hours: how much power, and is there a risk of icing or a high-wind shutdown?",
         tables="ops_power_forecast, ref_site",
         sql="""
SELECT date_format(from_utc_timestamp(p.TargetTime, st.timezone), 'EEE HH:mm') AS SiteTime,
       p.WindSpeed, p.WindSpeedP90, p.PowerMw, p.PowerMwP10, p.PowerMwP90, p.AmbientTemp, p.IcingRisk,
       p.WindSpeedP90 >= 22                                                    AS HighWindRisk
FROM ops_power_forecast p
CROSS JOIN ref_site st
WHERE p.ForecastType = 'Latest' AND p.HorizonHours <= 24
ORDER BY p.TargetTime"""),
]

# Questions answered from the live data in the Eventhouse (KQL).
LIVE_QUESTIONS = [
    dict(id="OP-05", question="What is every turbine doing right now?",
         tables="TurbineTelemetry",
         kql="""TurbineLatest()
| project TurbineId, Timestamp, State, WindSpeed, ActivePower, PowerSetpoint, GearboxBearingTemp, GearboxVibration
| order by TurbineId asc"""),
    dict(id="OP-06", question="Which alarms are active, and which procedure applies to each?",
         tables="AlarmEvents, EdgeHeartbeats",
         kql="""ActiveAlarms()
| project RaisedAt, TurbineId, AlarmCode, Severity, Description, Value, Threshold, Unit, SopId
| order by RaisedAt desc"""),
    dict(id="OP-07", question="How much is the site producing, and how has that changed over the last hour?",
         tables="TurbineTelemetry",
         kql="""TurbineTelemetry
| where Timestamp > ago(1h)
| summarize TurbinePowerKw = avg(ActivePower) by TurbineId, bin(Timestamp, 1m)
| summarize SitePowerMw = round(sum(TurbinePowerKw) / 1000, 2), TurbinesReporting = dcount(TurbineId) by Timestamp
| order by Timestamp asc"""),
    dict(id="OP-08", question="Which turbine stands out from the fleet right now on gearbox temperature and vibration?",
         tables="TurbineTelemetry",
         note="Compare the result with RE-05, the same comparison over the last 30 days of history: a turbine that stands out in both has a standing condition, one that stands out only live has a new problem.",
         kql="""let recent = TurbineTelemetry
    | where Timestamp > ago(15m) and State in ('RUNNING', 'DERATED')
    | summarize BearingTemp = avg(GearboxBearingTemp), OilTemp = avg(GearboxOilTemp), Vibration = avg(GearboxVibration), PowerKw = avg(ActivePower) by TurbineId;
let fleetBearingTemp = toscalar(recent | summarize percentile(BearingTemp, 50));
let fleetVibration = toscalar(recent | summarize percentile(Vibration, 50));
recent
| project TurbineId, PowerKw = round(PowerKw, 0),
          BearingTemp = round(BearingTemp, 1), BearingTempVsFleet = round(BearingTemp - fleetBearingTemp, 1),
          OilTemp = round(OilTemp, 1),
          Vibration = round(Vibration, 2), VibrationVsFleet = round(Vibration - fleetVibration, 2)
| order by VibrationVsFleet desc"""),
]


def by_persona() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {key: [] for key in PERSONAS}
    for q in QUESTIONS + LIVE_QUESTIONS:
        out[q["id"][:2]].append(q)
    return out
