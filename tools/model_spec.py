"""The semantic model of Phase 2, as data: tables, relationships, measures and acceptance checks.

One source for three things: notebook 06 builds the model from it, notebook 07 tests the model
with it, and docs/08-semantic-model.md lists it. tools/build-phase2.py writes all three.
"""

MODEL_NAME = "WindFarm Operations"
REPORT_NAME = "WindFarm Operations Report"

# Model table -> Lakehouse table written by notebook 05, and the columns it has.
TABLES = {
    "Date": ("dim_date", ["Date", "Year", "Quarter", "MonthNo", "Month", "YearMonth", "MonthStart",
                          "ContractYear", "DayOfWeekNo", "DayOfWeek"]),
    "Turbine": ("dim_turbine", ["TurbineId", "Name", "Model", "RatedPowerKw", "String", "Latitude", "Longitude",
                                "CommissionedDate"]),
    "Site": ("dim_site", ["SiteId", "SiteName", "Timezone", "CapacityMw", "PpaPriceUsdPerMwh",
                          "GridEmissionFactorKgCo2PerMwh"]),
    "Scada": ("fact_scada_10min", ["Timestamp", "Date", "TurbineId", "Source", "State", "AvailabilityCategory",
                                   "LossCause", "WindSpeed", "AmbientTemp", "AirDensity", "ActivePower",
                                   "PowerSetpoint", "PossiblePower", "GearboxOilTemp", "GearboxBearingTemp",
                                   "GearboxVibration", "GeneratorWindingTemp", "MainBearingTemp", "EnergyKwh",
                                   "PossibleEnergyKwh", "LostEnergyKwh"]),
    "Events": ("fact_turbine_events", ["EventId", "TurbineId", "StartTime", "EndTime", "StartDate", "DurationHours",
                                       "AvailabilityCategory", "Cause", "Component", "AlarmCode", "FailureMode",
                                       "ResponsibleParty", "Description", "LostEnergyMwh"]),
    "Work Orders": ("fact_work_orders", ["WorkOrderId", "TurbineId", "WorkType", "Priority", "Status", "OpenedDate",
                                         "ScheduledDate", "ClosedDate", "Summary", "LaborHours", "TotalCostUsd",
                                         "DowntimeHours", "WaitingForPartsHours", "CostBorneBy", "PmResult"]),
    "Curtailments": ("fact_curtailments", ["CurtailmentId", "StartTime", "StartDate", "DurationHours", "Reason",
                                           "InstructedBy", "Compensation", "LostEnergyMwh",
                                           "AvgRealTimePriceUsdPerMwh"]),
    "Budget": ("fact_monthly_budget", ["YearMonth", "MonthStart", "P50EnergyMwh", "P90EnergyMwh", "LongTermWindSpeed",
                                       "BudgetRevenueUsd", "BudgetCorrectiveMaintenanceUsd", "BudgetOpexUsd"]),
    "Market": ("fact_market_hourly", ["Timestamp", "Date", "DayAheadPriceUsdPerMwh", "RealTimePriceUsdPerMwh",
                                      "SiteEnergyMwh"]),
    "Forecast": ("fact_forecast_hourly", ["TargetTime", "Date", "ForecastPowerMw", "PowerMwP10", "PowerMwP90",
                                          "PossiblePowerMw", "ActualPowerMw", "AbsErrorMw"]),
    "Met": ("fact_met_10min", ["Timestamp", "Date", "Source", "WindSpeed", "AmbientTemp", "AirDensity"]),
    "KPIs": ("kpi", ["KpiId"]),
}

# (many side table, column, one side table, column, active)
RELATIONSHIPS = [
    ("Scada", "Date", "Date", "Date", True),
    ("Scada", "TurbineId", "Turbine", "TurbineId", True),
    ("Events", "StartDate", "Date", "Date", True),
    ("Events", "TurbineId", "Turbine", "TurbineId", True),
    ("Work Orders", "OpenedDate", "Date", "Date", True),
    ("Work Orders", "ScheduledDate", "Date", "Date", False),
    ("Work Orders", "TurbineId", "Turbine", "TurbineId", True),
    ("Curtailments", "StartDate", "Date", "Date", True),
    ("Budget", "MonthStart", "Date", "Date", True),
    ("Market", "Date", "Date", "Date", True),
    ("Forecast", "Date", "Date", "Date", True),
    ("Met", "Date", "Date", "Date", True),
]

# Columns that only carry relationships or sorting.
HIDDEN = [("KPIs", "KpiId"), ("Scada", "Date"), ("Events", "StartDate"), ("Market", "Date"), ("Forecast", "Date"),
          ("Met", "Date"), ("Budget", "MonthStart"), ("Curtailments", "StartDate"), ("Date", "MonthNo"),
          ("Date", "DayOfWeekNo")]
SORT_BY = [("Date", "Month", "MonthNo"), ("Date", "DayOfWeek", "DayOfWeekNo")]

DOWN = '{"Forced outage", "Scheduled maintenance", "Planned corrective action"}'
OWN_LOSSES = '{"Component fault", "Scheduled maintenance", "Corrective maintenance", "Technical derate"}'
KNOWN = "KEEPFILTERS('Scada'[AvailabilityCategory] <> \"Information unavailable\")"
FAILURE = ("KEEPFILTERS('Events'[AvailabilityCategory] = \"Forced outage\"), "
           "KEEPFILTERS('Events'[Cause] = \"Component fault\")")
CLOSED_REPAIR = ("KEEPFILTERS('Work Orders'[WorkType] = \"Corrective\"), "
                 "KEEPFILTERS('Work Orders'[Status] = \"Closed\")")
BY_PLAN = "USERELATIONSHIP('Work Orders'[ScheduledDate], 'Date'[Date])"

# (name, folder, format string, DAX, what it means)
MEASURES = [
    ("Energy MWh", "Energy", "#,0", "DIVIDE(SUM('Scada'[EnergyKwh]), 1000)",
     "Energy delivered by the turbines."),
    ("Possible Energy MWh", "Energy", "#,0", "DIVIDE(SUM('Scada'[PossibleEnergyKwh]), 1000)",
     "What the turbines would have delivered in the wind they had, by the power curve at the air density of the moment."),
    ("Lost Energy MWh", "Energy", "#,0", "DIVIDE(SUM('Scada'[LostEnergyKwh]), 1000)",
     "Possible minus delivered energy in periods when a turbine was stopped or limited. Split it by Scada[LossCause]."),
    ("Turbine Hours", "Energy", "#,0", "DIVIDE(COUNTROWS('Scada'), 6)",
     "Hours covered by the data, summed over the turbines."),
    ("Capacity Factor", "Energy", "0.0%",
     "DIVIDE(SUM('Scada'[EnergyKwh]), SUMX('Turbine', 'Turbine'[RatedPowerKw] * CALCULATE(COUNTROWS('Scada'))) / 6)",
     "Energy as a share of what the turbines would deliver at rated power all the time."),
    ("Average Wind Speed", "Energy", "0.0", "AVERAGE('Scada'[WindSpeed])", "Mean wind speed at the nacelles, m/s."),
    ("CO2 Avoided t", "Energy", "#,0",
     "DIVIDE([Energy MWh] * MAX('Site'[GridEmissionFactorKgCo2PerMwh]), 1000)",
     "Energy times the average emission intensity of the grid, in tonnes."),
    ("Time Availability", "Availability", "0.00%",
     f"VAR known = CALCULATE(COUNTROWS('Scada'), {KNOWN}) "
     f"VAR down = CALCULATE(COUNTROWS('Scada'), KEEPFILTERS('Scada'[AvailabilityCategory] IN {DOWN})) "
     "RETURN DIVIDE(known - down, known)",
     "Share of the time in which a turbine was not down for a fault or for maintenance."),
    ("Energy Availability", "Availability", "0.00%",
     f"VAR energy = CALCULATE(SUM('Scada'[EnergyKwh]), {KNOWN}) "
     f"VAR lost = CALCULATE(SUM('Scada'[LostEnergyKwh]), {KNOWN}, KEEPFILTERS('Scada'[LossCause] IN {OWN_LOSSES})) "
     "RETURN DIVIDE(energy, energy + lost)",
     "Share of the energy that was not lost to the turbine itself."),
    ("Forced Outage Hours", "Availability", "#,0.0",
     "DIVIDE(CALCULATE(COUNTROWS('Scada'), KEEPFILTERS('Scada'[AvailabilityCategory] = \"Forced outage\")), 6)",
     "Hours stopped by a fault."),
    ("Performance Index", "Performance", "0.000",
     "CALCULATE(DIVIDE(SUM('Scada'[EnergyKwh]), SUM('Scada'[PossibleEnergyKwh])), "
     "KEEPFILTERS('Scada'[AvailabilityCategory] = \"Full performance\"))",
     "Energy as a share of possible energy while the turbine ran without any limit. Below 1: worse than the power curve."),
    ("Average Gearbox Bearing Temp", "Performance", "0.0", "AVERAGE('Scada'[GearboxBearingTemp])", "degC."),
    ("Average Gearbox Vibration", "Performance", "0.00", "AVERAGE('Scada'[GearboxVibration])", "mm/s RMS."),
    ("Curtailed Energy MWh", "Curtailment", "#,0",
     "CALCULATE([Lost Energy MWh], KEEPFILTERS('Scada'[LossCause] = \"Grid curtailment\"))",
     "Energy not produced because the grid operator or the buyer limited the site."),
    ("Curtailment Share", "Curtailment", "0.0%",
     "DIVIDE([Curtailed Energy MWh], [Energy MWh] + [Lost Energy MWh])",
     "Curtailed energy as a share of energy plus all lost energy."),
    ("Deemed Generation MWh", "Curtailment", "#,0",
     "CALCULATE(SUM('Curtailments'[LostEnergyMwh]), KEEPFILTERS('Curtailments'[Compensation] = \"Paid\"))",
     "Curtailed energy that the buyer pays for. A site figure: it does not split by turbine."),
    ("Unpaid Curtailment MWh", "Curtailment", "#,0",
     "CALCULATE(SUM('Curtailments'[LostEnergyMwh]), KEEPFILTERS('Curtailments'[Compensation] = \"Not paid\"))",
     "Curtailed energy that nobody pays for. A site figure."),
    ("Failures", "Reliability", "#,0", f"CALCULATE(COUNTROWS('Events'), {FAILURE})",
     "Faults that needed a technician."),
    ("Failure Downtime Hours", "Reliability", "#,0", f"CALCULATE(SUM('Events'[DurationHours]), {FAILURE})",
     "Hours from each fault to the return to service."),
    ("MTTR Hours", "Reliability", "#,0.0", "DIVIDE([Failure Downtime Hours], [Failures])",
     "Mean time to repair, including waiting for access, parts and people."),
    ("MTBF Hours", "Reliability", "#,0", "DIVIDE([Turbine Hours] - [Failure Downtime Hours], [Failures])",
     "Mean time between failures: running hours per failure."),
    ("Downtime Events", "Reliability", "#,0", "COUNTROWS('Events')", "Stops and outages of every kind."),
    ("Open Work Orders", "Maintenance", "#,0",
     "CALCULATE(COUNTROWS('Work Orders'), KEEPFILTERS('Work Orders'[Status] <> \"Closed\"))",
     "Jobs that are not closed: open, in progress or planned."),
    ("Repair Cost Paid by Owner USD", "Maintenance", "#,0",
     f"CALCULATE(SUM('Work Orders'[TotalCostUsd]), {CLOSED_REPAIR}, KEEPFILTERS('Work Orders'[CostBorneBy] = \"Owner\"))",
     "Closed corrective work invoiced to the owner, by the day the job was opened."),
    ("Repair Cost Covered by Warranty USD", "Maintenance", "#,0",
     f"CALCULATE(SUM('Work Orders'[TotalCostUsd]), {CLOSED_REPAIR}, KEEPFILTERS('Work Orders'[CostBorneBy] = \"Warranty\"))",
     "Closed corrective work that a warranty paid."),
    ("Repair Cost USD per MWh", "Maintenance", "0.00", "DIVIDE([Repair Cost Paid by Owner USD], [Energy MWh])",
     "Owner-paid repairs per MWh produced."),
    ("PM Compliance", "Maintenance", "0.0%",
     f"VAR due = CALCULATE(COUNTROWS('Work Orders'), KEEPFILTERS(NOT ISBLANK('Work Orders'[PmResult])), {BY_PLAN}) "
     "VAR in_time = CALCULATE(COUNTROWS('Work Orders'), "
     f"KEEPFILTERS('Work Orders'[PmResult] = \"Done within a week of the plan\"), {BY_PLAN}) "
     "RETURN DIVIDE(in_time, due)",
     "Share of the preventive work due in the period that was done within a week of its planned date."),
    ("Contract Price USD per MWh", "Money", "0.00", "MAX('Site'[PpaPriceUsdPerMwh])",
     "Price of the power purchase agreement."),
    ("Revenue USD", "Money", "#,0", "([Energy MWh] + [Deemed Generation MWh]) * [Contract Price USD per MWh]",
     "Energy at the contract price, plus curtailed energy that the buyer pays for. A site figure."),
    ("Lost Energy Value USD", "Money", "#,0", "[Lost Energy MWh] * [Contract Price USD per MWh]",
     "Lost energy at the contract price."),
    ("Budget P50 MWh", "Budget", "#,0", "SUM('Budget'[P50EnergyMwh])", "Budget energy, whole months."),
    ("Budget P90 MWh", "Budget", "#,0", "SUM('Budget'[P90EnergyMwh])", "The cautious case, whole months."),
    ("Budget Revenue USD", "Budget", "#,0", "SUM('Budget'[BudgetRevenueUsd])", "P50 energy at the contract price."),
    ("Budget Repair Cost USD", "Budget", "#,0", "SUM('Budget'[BudgetCorrectiveMaintenanceUsd])",
     "Budget for corrective maintenance."),
    ("Energy vs Budget", "Budget", "0.0%", "DIVIDE([Energy MWh], [Budget P50 MWh])",
     "Energy as a share of the P50 budget. Meaningful for whole months."),
    ("Captured Price USD per MWh", "Market", "0.00",
     "DIVIDE(SUMX('Market', 'Market'[SiteEnergyMwh] * 'Market'[RealTimePriceUsdPerMwh]), SUM('Market'[SiteEnergyMwh]))",
     "The real-time market price weighted by when the site produced."),
    ("Mean Real-Time Price USD per MWh", "Market", "0.00", "AVERAGE('Market'[RealTimePriceUsdPerMwh])",
     "Plain average of the hourly real-time price."),
    ("Forecast Error", "Market", "0.0%", "DIVIDE(AVERAGE('Forecast'[AbsErrorMw]), MAX('Site'[CapacityMw]))",
     "Mean absolute difference between the day-ahead forecast and possible power, as a share of the site's capacity."),
    ("Wind Index", "Energy", "0.00", "DIVIDE(AVERAGE('Met'[WindSpeed]), AVERAGE('Budget'[LongTermWindSpeed]))",
     "Mean wind speed at the met mast relative to the long-term mean of the same months. Meaningful for whole months."),
]


def acceptance_checks(d):
    """Checks for notebook 07. d holds dates: as_of, d90, month, m6, m12, year, y12 (see the notebook).
    Each check runs a DAX query on the model and a Spark SQL query on the Lakehouse tables; the two
    must agree. Columns have the same names on both sides; keys lists the grouping columns."""
    def window(start, end):          # dates from start (included) to end (excluded), as a DAX filter
        return (f"FILTER(ALL('Date'[Date]), 'Date'[Date] >= DATE({start.year}, {start.month}, {start.day}) "
                f"&& 'Date'[Date] < DATE({end.year}, {end.month}, {end.day}))")
    end = d["end"]                   # the day after the last day with data
    down = "('Forced outage', 'Scheduled maintenance', 'Planned corrective action')"
    own = "('Component fault', 'Scheduled maintenance', 'Corrective maintenance', 'Technical derate')"
    return [
        {"id": "SM-01, SM-02", "title": "Energy, budget and capacity factor by month, last 12 whole months",
         "keys": ["YearMonth"],
         "dax": f"""EVALUATE SUMMARIZECOLUMNS('Date'[YearMonth], {window(d['m12'], d['month'])},
                 "Energy", [Energy MWh], "BudgetP50", [Budget P50 MWh], "CapacityFactor", [Capacity Factor])""",
         "sql": f"""SELECT d.YearMonth, sum(s.EnergyKwh) / 1000 AS Energy, max(b.P50EnergyMwh) AS BudgetP50,
                           sum(s.EnergyKwh) / sum(t.RatedPowerKw / 6.0) AS CapacityFactor
                    FROM fact_scada_10min s JOIN dim_date d ON d.Date = s.Date
                    JOIN dim_turbine t ON t.TurbineId = s.TurbineId
                    JOIN fact_monthly_budget b ON b.YearMonth = d.YearMonth
                    WHERE s.Date >= DATE'{d['m12']}' AND s.Date < DATE'{d['month']}' GROUP BY d.YearMonth"""},
        {"id": "SM-03", "title": "Availability of each turbine, last 90 days", "keys": ["TurbineId"],
         "dax": f"""EVALUATE SUMMARIZECOLUMNS('Turbine'[TurbineId], {window(d['d90'], end)},
                 "TimeAvailability", [Time Availability], "EnergyAvailability", [Energy Availability],
                 "ForcedOutageHours", [Forced Outage Hours])""",
         "sql": f"""SELECT TurbineId,
                           1 - sum(CASE WHEN AvailabilityCategory IN {down} THEN 1 ELSE 0 END) / count(*) AS TimeAvailability,
                           sum(EnergyKwh) / (sum(EnergyKwh) + sum(CASE WHEN LossCause IN {own} THEN LostEnergyKwh ELSE 0 END)) AS EnergyAvailability,
                           nullif(sum(CASE WHEN AvailabilityCategory = 'Forced outage' THEN 1 ELSE 0 END), 0) / 6.0 AS ForcedOutageHours
                    FROM fact_scada_10min
                    WHERE Date >= DATE'{d['d90']}' AND AvailabilityCategory <> 'Information unavailable' GROUP BY TurbineId"""},
        {"id": "PE-01", "title": "Performance index of each turbine, last 90 days", "keys": ["TurbineId"],
         "dax": f"""EVALUATE SUMMARIZECOLUMNS('Turbine'[TurbineId], {window(d['d90'], end)},
                 "PerformanceIndex", [Performance Index])""",
         "sql": f"""SELECT TurbineId, sum(EnergyKwh) / sum(PossibleEnergyKwh) AS PerformanceIndex
                    FROM fact_scada_10min
                    WHERE Date >= DATE'{d['d90']}' AND AvailabilityCategory = 'Full performance' GROUP BY TurbineId"""},
        {"id": "SM-04", "title": "Lost energy by cause and its value, last 12 months", "keys": ["LossCause"],
         "dax": f"""EVALUATE SUMMARIZECOLUMNS('Scada'[LossCause], {window(d['y12'], end)},
                 "LostEnergy", [Lost Energy MWh], "Value", [Lost Energy Value USD])""",
         "sql": f"""SELECT s.LossCause, sum(s.LostEnergyKwh) / 1000 AS LostEnergy,
                           sum(s.LostEnergyKwh) / 1000 * max(st.PpaPriceUsdPerMwh) AS Value
                    FROM fact_scada_10min s CROSS JOIN dim_site st
                    WHERE s.Date >= DATE'{d['y12']}' AND s.LostEnergyKwh > 0 GROUP BY s.LossCause"""},
        {"id": "AM-02", "title": "Curtailment share, deemed and unpaid curtailment, last 12 months", "keys": [],
         "dax": f"""EVALUATE CALCULATETABLE(ROW("CurtailmentShare", [Curtailment Share], "Deemed", [Deemed Generation MWh],
                 "Unpaid", [Unpaid Curtailment MWh]), {window(d['y12'], end)})""",
         "sql": f"""SELECT (SELECT sum(CASE WHEN LossCause = 'Grid curtailment' THEN LostEnergyKwh ELSE 0 END)
                                   / (sum(EnergyKwh) + sum(LostEnergyKwh))
                            FROM fact_scada_10min WHERE Date >= DATE'{d['y12']}') AS CurtailmentShare,
                           sum(CASE WHEN Compensation = 'Paid' THEN LostEnergyMwh END) AS Deemed,
                           sum(CASE WHEN Compensation = 'Not paid' THEN LostEnergyMwh END) AS Unpaid
                    FROM fact_curtailments WHERE StartDate >= DATE'{d['y12']}'"""},
        {"id": "RE-02", "title": "Failures and mean time to repair of each turbine, last 12 months",
         "keys": ["TurbineId"],
         "dax": f"""EVALUATE SUMMARIZECOLUMNS('Turbine'[TurbineId], {window(d['y12'], end)},
                 "Failures", [Failures], "DowntimeHours", [Failure Downtime Hours], "MTTR", [MTTR Hours])""",
         "sql": f"""SELECT TurbineId, count(*) AS Failures, sum(DurationHours) AS DowntimeHours, avg(DurationHours) AS MTTR
                    FROM fact_turbine_events
                    WHERE AvailabilityCategory = 'Forced outage' AND Cause = 'Component fault'
                      AND StartDate >= DATE'{d['y12']}' GROUP BY TurbineId"""},
        {"id": "AM-01, AM-07", "title": "Revenue and carbon dioxide avoided, year to date", "keys": [],
         "dax": f"""EVALUATE CALCULATETABLE(ROW("Energy", [Energy MWh], "Revenue", [Revenue USD], "Co2", [CO2 Avoided t]),
                 {window(d['year'], end)})""",
         "sql": f"""SELECT e.Energy, (e.Energy + coalesce(c.Deemed, 0)) * st.PpaPriceUsdPerMwh AS Revenue,
                           e.Energy * st.GridEmissionFactorKgCo2PerMwh / 1000 AS Co2
                    FROM (SELECT sum(EnergyKwh) / 1000 AS Energy FROM fact_scada_10min WHERE Date >= DATE'{d['year']}') e
                    CROSS JOIN (SELECT sum(CASE WHEN Compensation = 'Paid' THEN LostEnergyMwh END) AS Deemed
                                FROM fact_curtailments WHERE StartDate >= DATE'{d['year']}') c
                    CROSS JOIN dim_site st"""},
        {"id": "AM-04", "title": "Repair cost by who paid, year to date", "keys": [],
         "dax": f"""EVALUATE CALCULATETABLE(ROW("Owner", [Repair Cost Paid by Owner USD],
                 "Warranty", [Repair Cost Covered by Warranty USD], "PerMwh", [Repair Cost USD per MWh]),
                 {window(d['year'], end)})""",
         "sql": f"""SELECT w.Owner, w.Warranty, w.Owner / e.Energy AS PerMwh
                    FROM (SELECT sum(CASE WHEN CostBorneBy = 'Owner' THEN TotalCostUsd END) AS Owner,
                                 sum(CASE WHEN CostBorneBy = 'Warranty' THEN TotalCostUsd END) AS Warranty
                          FROM fact_work_orders
                          WHERE WorkType = 'Corrective' AND Status = 'Closed' AND OpenedDate >= DATE'{d['year']}') w
                    CROSS JOIN (SELECT sum(EnergyKwh) / 1000 AS Energy FROM fact_scada_10min WHERE Date >= DATE'{d['year']}') e"""},
        {"id": "MP-02", "title": "Preventive maintenance compliance, work due in the last 12 months", "keys": [],
         "dax": f"""EVALUATE CALCULATETABLE(ROW("PmCompliance", [PM Compliance]), {window(d['y12'], end)})""",
         "sql": f"""SELECT sum(CASE WHEN PmResult = 'Done within a week of the plan' THEN 1 ELSE 0 END) / count(*) AS PmCompliance
                    FROM fact_work_orders WHERE PmResult IS NOT NULL AND ScheduledDate >= DATE'{d['y12']}'"""},
        {"id": "AM-06", "title": "Captured and mean real-time price, last 12 months", "keys": [],
         "dax": f"""EVALUATE CALCULATETABLE(ROW("CapturedPrice", [Captured Price USD per MWh],
                 "MeanPrice", [Mean Real-Time Price USD per MWh]), {window(d['y12'], end)})""",
         "sql": f"""SELECT sum(SiteEnergyMwh * RealTimePriceUsdPerMwh) / sum(SiteEnergyMwh) AS CapturedPrice,
                           avg(RealTimePriceUsdPerMwh) AS MeanPrice
                    FROM fact_market_hourly WHERE Date >= DATE'{d['y12']}'"""},
        {"id": "AM-05", "title": "Day-ahead forecast error by month, last 6 whole months", "keys": ["YearMonth"],
         "dax": f"""EVALUATE SUMMARIZECOLUMNS('Date'[YearMonth], {window(d['m6'], d['month'])},
                 "ForecastError", [Forecast Error])""",
         "sql": f"""SELECT d.YearMonth, avg(f.AbsErrorMw) / max(st.CapacityMw) AS ForecastError
                    FROM fact_forecast_hourly f JOIN dim_date d ON d.Date = f.Date CROSS JOIN dim_site st
                    WHERE f.Date >= DATE'{d['m6']}' AND f.Date < DATE'{d['month']}' GROUP BY d.YearMonth"""},
    ]
