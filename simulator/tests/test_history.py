"""The generated operating history: plausible KPIs, consistent tables, the planted stories."""
import csv
import json

import numpy as np
import pandas as pd
import pytest

from windfarm_sim import history
from windfarm_sim.site import load_site
from windfarm_sim.turbine import power_curve_kw
from windfarm_sim.wind import WindField

from conftest import SITE_FILE

AS_OF = "2026-11-20T05:00:00+00:00"
REFERENCE = SITE_FILE.parent


def _column(name: str, column: str) -> set:
    with open(REFERENCE / f"{name}.csv", newline="", encoding="utf-8") as f:
        return {row[column] for row in csv.DictReader(f)}


@pytest.fixture(scope="module")
def site():
    return json.loads(SITE_FILE.read_text())


@pytest.fixture(scope="module")
def tables(site):
    return history.generate(site, as_of=AS_OF)


@pytest.fixture(scope="module")
def kpi(tables, site):
    return history.summarise(tables, site)


def test_tables_and_sizes(tables, site):
    scada = tables["scada_10min"]
    steps = int((pd.Timestamp(AS_OF).timestamp() - pd.Timestamp(site["historyStart"]).timestamp()) // 600)
    assert len(scada) == steps * 12
    assert scada["Timestamp"].max() < pd.Timestamp("2026-11-20T05:00:00")
    assert set(scada["TurbineId"]) == {t["turbineId"] for t in site["turbines"]}
    for name in ("met_10min", "turbine_events", "alarm_log", "work_orders", "work_order_parts", "oil_analysis",
                 "blade_inspections", "curtailments", "market_prices", "power_forecast", "monthly_budget"):
        assert len(tables[name]) > 0, name


def test_headline_kpis_are_realistic(kpi):
    assert 30.0 < kpi["capacityFactorPct"] < 40.0
    assert 96.5 < kpi["timeAvailabilityPct"] < 98.5
    assert 96.0 < kpi["energyAvailabilityPct"] < 98.7
    assert 2.5 < kpi["curtailmentPctOfPossible"] < 7.0
    lost = kpi["lostEnergyMwhByCause"]
    assert lost["Grid curtailment"] > lost["Component fault"] > lost["Scheduled maintenance"]


def test_scada_values_are_physical(tables, site):
    s = tables["scada_10min"]
    rated = site["turbineModel"]["ratedPowerKw"]
    known = s[s["State"] != "UNKNOWN"]
    assert known["ActivePower"].max() <= rated * 1.011
    assert known["EnergyKwh"].max() <= rated / 6 * 1.011
    assert (known["LostEnergyKwh"] >= 0).all()
    stopped = known[known["AvailabilityCategory"].isin(["Forced outage", "Scheduled maintenance"])]
    assert stopped["ActivePower"].max() < 0.0 and stopped["RotorSpeed"].max() < 0.3
    running = known[known["State"] == "RUNNING"]
    assert running["GearboxOilTemp"].between(30, 95).all()
    assert 0.001 < s["ActivePower"].isna().mean() < 0.01          # some communication gaps, not many


def test_references_resolve(tables, site):
    events, orders, parts = tables["turbine_events"], tables["work_orders"], tables["work_order_parts"]
    linked = events.loc[events["WorkOrderId"] != "", "WorkOrderId"]
    assert set(linked) <= set(orders["WorkOrderId"])
    assert set(orders.loc[orders["EventId"] != "", "EventId"]) <= set(events["EventId"])
    assert set(parts["WorkOrderId"]) <= set(orders["WorkOrderId"])
    assert set(parts["PartId"]) <= _column("spare_parts", "partId")
    assert set(tables["alarm_log"]["AlarmCode"]) <= _column("alarm_codes", "alarmCode")
    assert set(events.loc[events["AlarmCode"] != "", "AlarmCode"]) <= _column("alarm_codes", "alarmCode")
    assert set(orders.loc[orders["LeadTechnicianId"] != "", "LeadTechnicianId"]) <= _column("technicians", "technicianId")
    assert set(orders.loc[orders["ComponentId"] != "", "ComponentId"]) <= _column("components", "componentId")
    assert set(orders.loc[orders["SopId"] != "", "SopId"]) <= _column("sop_index", "sopId")
    assert events["EventId"].is_unique and orders["WorkOrderId"].is_unique and tables["alarm_log"]["AlarmId"].is_unique
    cost = orders["LaborCostUsd"] + orders["PartsCostUsd"] + orders["OtherCostUsd"]
    assert np.allclose(cost, orders["TotalCostUsd"], atol=0.02)


def test_event_log_matches_scada(tables):
    events, s = tables["turbine_events"], tables["scada_10min"]
    by_cause = s.groupby("LossCause")["LostEnergyKwh"].sum() / 1000.0
    forced = events.loc[events["AvailabilityCategory"] == "Forced outage", "LostEnergyMwh"].sum()
    assert forced == pytest.approx(by_cause["Component fault"], rel=0.05)
    assert tables["curtailments"]["LostEnergyMwh"].sum() == pytest.approx(by_cause["Grid curtailment"], rel=0.02)


def test_planted_stories(tables):
    events, orders, oil = tables["turbine_events"], tables["work_orders"], tables["oil_analysis"]
    precedent = events[(events["TurbineId"] == "WT-02") & (events["AlarmCode"] == "GBX-VIB-CRIT")]
    assert len(precedent) == 1 and precedent["DurationHours"].iloc[0] > 150
    order = orders[orders["WorkOrderId"] == precedent["WorkOrderId"].iloc[0]].iloc[0]
    assert order["CoveredByWarranty"] and order["TotalCostUsd"] > 100_000
    iron = oil[oil["TurbineId"] == "WT-07"].sort_values("SampleDate")["IronPpm"].tolist()
    assert iron[-1] > iron[-2] > 60
    borescope = orders[(orders["TurbineId"] == "WT-07") & orders["Summary"].str.startswith("Borescope")].iloc[0]
    assert borescope["Status"] == "Scheduled" and borescope["ScheduledDate"] > pd.Timestamp("2026-11-20")
    overdue = orders[(orders["Status"] == "Open") & (orders["ScheduledDate"] < pd.Timestamp("2026-11-20"))]
    assert len(overdue) >= 2
    pitch = events[(events["ComponentCode"] == "PIT") & (events["AvailabilityCategory"] == "Forced outage")]
    assert pitch["TurbineId"].value_counts().idxmax() == "WT-10"
    blades = tables["blade_inspections"]
    worst = blades[(blades["SeverityCategory"] >= 4) & (blades["Status"] == "Open")]
    assert set(worst["TurbineId"]) == {"WT-09"} and (worst["RepairWorkOrderId"] != "").all()


def test_underperformers_and_wear_show_in_the_data(tables):
    s = tables["scada_10min"]
    recent = s[(s["Timestamp"] >= s["Timestamp"].max() - pd.Timedelta(days=60))
               & (s["AvailabilityCategory"] == "Full performance")]
    index = recent.groupby("TurbineId")["EnergyKwh"].sum() / recent.groupby("TurbineId")["PossibleEnergyKwh"].sum()
    assert set(index.nsmallest(2).index) == {"WT-05", "WT-09"}
    assert index["WT-05"] < 0.965 and index.drop(["WT-05", "WT-09"]).min() > 0.975
    loaded = s[(s["ActivePower"] > 2500) & s["TurbineId"].isin(["WT-07", "WT-06"])]
    vib = loaded.groupby([loaded["Timestamp"].dt.to_period("M"), "TurbineId"])["GearboxVibration"].mean().unstack()
    assert vib["WT-07"].iloc[-1] - vib["WT-07"].iloc[-7] > 0.7      # WT-07 is trending up
    assert abs(vib["WT-06"].iloc[-1] - vib["WT-06"].iloc[-7]) < 0.2  # its neighbour is not


def test_forecast_and_budget(tables):
    s, f, budget = tables["scada_10min"], tables["power_forecast"], tables["monthly_budget"]
    actual = s.groupby(s["Timestamp"].dt.floor("h"))["PossiblePower"].sum() / 6000.0
    day_ahead = f[f["ForecastType"] == "Day-ahead"].set_index("TargetTime").join(actual.rename("possible"), how="inner")
    error = (day_ahead["PowerMw"] - day_ahead["possible"]).abs().mean() / 50.4
    assert 0.05 < error < 0.16
    inside = ((day_ahead["possible"] >= day_ahead["PowerMwP10"]) & (day_ahead["possible"] <= day_ahead["PowerMwP90"])).mean()
    assert 0.65 < inside < 0.93
    latest = f[f["ForecastType"] == "Latest"]
    assert len(latest) == 168 and latest["TargetTime"].min() > pd.Timestamp("2026-11-20T05:00:00")
    months = s.groupby(s["Timestamp"].dt.to_period("M").astype(str))["EnergyKwh"].sum() / 1000.0
    full = budget.set_index("YearMonth").join(months.rename("actual")).dropna().iloc[:-1]
    assert (full["actual"] / full["P50EnergyMwh"]).between(0.7, 1.35).all()
    assert 0.9 < full["actual"].sum() / full["P50EnergyMwh"].sum() < 1.12


def test_the_past_does_not_change_when_generated_later(site, tables):
    later = history.generate(site, as_of="2026-11-27T11:00:00+00:00")
    day = (pd.Timestamp("2025-06-10"), pd.Timestamp("2025-06-11"))
    for turbine in ("WT-01", "WT-08", "WT-12"):
        a = tables["scada_10min"]
        b = later["scada_10min"]
        a = a[(a["TurbineId"] == turbine) & (a["Timestamp"] >= day[0]) & (a["Timestamp"] < day[1])]
        b = b[(b["TurbineId"] == turbine) & (b["Timestamp"] >= day[0]) & (b["Timestamp"] < day[1])]
        pd.testing.assert_frame_equal(a.reset_index(drop=True), b.reset_index(drop=True))
    quiet = ["WT-01", "WT-06", "WT-08", "WT-12"]
    cut = pd.Timestamp("2026-06-01")
    e1 = tables["turbine_events"]
    e2 = later["turbine_events"]
    e1 = e1[e1["TurbineId"].isin(quiet) & (e1["StartTime"] < cut)]["EventId"].tolist()
    e2 = e2[e2["TurbineId"].isin(quiet) & (e2["StartTime"] < cut)]["EventId"].tolist()
    assert e1 == e2
    p1 = tables["market_prices"]
    p2 = later["market_prices"].iloc[:len(p1)]
    pd.testing.assert_frame_equal(p1.iloc[:-48].reset_index(drop=True), p2.iloc[:-48].reset_index(drop=True))


def test_same_physics_as_the_live_simulator(site):
    model = load_site(SITE_FILE).model
    for v in (0.0, 2.9, 3.0, 5.5, 9.0, 11.99, 12.0, 18.0, 25.0, 25.1):
        assert float(history.power_curve_kw(v, site["turbineModel"])) == pytest.approx(power_curve_kw(v, model))
    import random
    live_site = load_site(SITE_FILE)
    field = WindField(live_site, random.Random(1), 9.0, 8.5, 9.5, 18.0)
    table = history.wake_table(site)
    for direction in (2.5, 92.5, 197.5, 272.5):
        field._wake_dir_bucket = None
        field._update_wakes(direction)
        live = [field._wake[t.turbine_id] for t in live_site.turbines]
        assert np.allclose(table[int(direction // 5)], live, atol=1e-9)
    assert np.allclose(history.speedup(site), [field._speedup[t.turbine_id] for t in live_site.turbines])


def test_latest_forecast_is_cheap_and_matches(site, tables):
    quick = history.latest_forecast(site, as_of=AS_OF)
    full = tables["power_forecast"]
    full = full[full["ForecastType"] == "Latest"].reset_index(drop=True)
    pd.testing.assert_frame_equal(quick.astype(full.dtypes.to_dict()), full, check_dtype=False)
