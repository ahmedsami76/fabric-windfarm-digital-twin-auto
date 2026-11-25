#!/usr/bin/env python3
"""Runs the Phase 2 table notebook in a local Spark session and checks its result.

    python3 tools/local-spark/run_phase2.py --lakehouse DIR

DIR is a Lakehouse stand-in in which notebooks 01 and 02 have run (run_notebooks.py --lakehouse DIR).
The script
  1. writes stand-ins for the two Eventhouse shortcuts, TurbineTelemetry and WeatherObservations:
     three hours of samples that start before the end of the history, with a gap for one turbine,
     a gap for all turbines, a fault and a curtailment;
  2. runs every code cell of 05_build_model_tables (with --no-live first: history only);
  3. checks the joined series and runs the Lakehouse query of every acceptance check of notebook 07.
What it cannot do: build or query the semantic model. Notebooks 06 to 08 run only in Fabric.
"""
import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "local-spark"))
sys.path.insert(0, str(REPO / "tools"))
from run_notebooks import session  # noqa: E402
import model_spec  # noqa: E402


def write_live(spark, as_of: dt.datetime) -> dict:
    """Stand-ins for the shortcut tables. Returns what the checks expect to find."""
    rng = np.random.default_rng(7)
    turbines = [r[0] for r in spark.sql("SELECT turbineId FROM ref_turbines ORDER BY turbineId").collect()]
    start = as_of - dt.timedelta(minutes=30)                      # 30 minutes overlap with the history
    step, seconds = 10, 3 * 3600 + 240                            # the last four minutes are an incomplete period
    offsets = np.arange(0, seconds, step)
    rows = []
    for i, turbine in enumerate(turbines):
        wind = 9.0 + 2.0 * np.sin(offsets / 2400.0 + i) + rng.normal(0, 0.4, offsets.size)
        power = np.clip(4200 * (np.clip(wind, 3, 12) ** 3 - 27) / (1728 - 27) * 0.95, -12, 4200)
        state = np.full(offsets.size, "RUNNING", dtype=object)
        if turbine == "WT-03":                                    # a fault for 40 minutes
            fault = (offsets >= 3600) & (offsets < 6000)
            state[fault], power[fault] = "FAULT", -12.0
        if turbine == "WT-04":                                    # curtailed to 300 kW for an hour, 20 minutes of it unseen
            limit = (offsets >= 4800) & (offsets < 8400)
            state[limit], power[limit] = "CURTAILED", np.minimum(power[limit], 300.0)
        keep = np.ones(offsets.size, dtype=bool)
        keep &= ~((offsets >= 7200) & (offsets < 8400))           # nobody sends for 20 minutes
        if turbine == "WT-06":
            keep &= ~((offsets >= 2400) & (offsets < 4800))       # one turbine silent for 40 minutes
        for o, w, p, s in zip(offsets[keep], wind[keep], power[keep], state[keep]):
            rows.append((start + dt.timedelta(seconds=int(o)), turbine, s, float(w), float(p)))
    pdf = pd.DataFrame(rows, columns=["Timestamp", "TurbineId", "State", "WindSpeed", "ActivePower"])
    for column, value in {"AmbientTemp": 14.0, "PowerSetpoint": 4200.0, "GearboxOilTemp": 58.0,
                          "GearboxBearingTemp": 64.0, "GearboxVibration": 2.1, "GeneratorWindingTemp": 80.0,
                          "MainBearingTemp": 45.0}.items():
        pdf[column] = value
    spark.sql("DROP TABLE IF EXISTS TurbineTelemetry")
    spark.createDataFrame(pdf).write.format("parquet").saveAsTable("TurbineTelemetry")
    weather = pd.DataFrame({"Timestamp": [start + dt.timedelta(seconds=int(o)) for o in offsets[::6]]})
    weather["AirDensity"], weather["WindSpeed"], weather["AmbientTemp"] = 1.10, 9.5, 14.0
    spark.sql("DROP TABLE IF EXISTS WeatherObservations")
    spark.createDataFrame(weather).write.format("parquet").saveAsTable("WeatherObservations")
    return {"turbines": len(turbines)}


def run_notebook(spark, lakehouse: Path, name: str) -> int:
    notebook = json.loads((REPO / "fabric" / "notebooks" / f"{name}.ipynb").read_text(encoding="utf-8"))
    namespace = {"spark": spark, "display": lambda df: df.show(40, truncate=50)}
    cells = 0
    for number, cell in enumerate(notebook["cells"]):
        if cell["cell_type"] != "code":
            continue
        source = "".join(cell["source"]).replace("/lakehouse/default", str(lakehouse))
        source = source.replace('.format("delta")', '.format("parquet")').replace('.option("overwriteSchema", "true")', "")
        started = time.time()
        exec(compile(source, f"{name}[{number}]", "exec"), namespace)
        cells += 1
        print(f"--- cell {number} ok in {time.time() - started:.1f}s", flush=True)
    return cells


def one(spark, query):
    return spark.sql(query).first()


def check_tables(spark, live: bool) -> None:
    for name, (table, columns) in model_spec.TABLES.items():
        have = spark.table(table).columns
        assert have == columns, f"{table}: columns {have} differ from the model definition {columns}"
        assert spark.table(table).count() > 0, f"{table} is empty"
    for many, column, one_side, key, _ in model_spec.RELATIONSHIPS:
        a, b = model_spec.TABLES[many][0], model_spec.TABLES[one_side][0]
        orphans = spark.sql(f"SELECT count(*) FROM {a} x LEFT ANTI JOIN {b} y ON x.{column} = y.{key} "
                            f"WHERE x.{column} IS NOT NULL").first()[0]
        assert orphans == 0, f"{many}[{column}] has {orphans} values without a row in {one_side}[{key}]"
        duplicates = spark.sql(f"SELECT count(*) - count(DISTINCT {key}) FROM {b}").first()[0]
        assert duplicates == 0, f"{one_side}[{key}] is not unique"
    sources = {r[0]: r[1] for r in spark.sql("SELECT Source, count(*) FROM fact_scada_10min GROUP BY Source").collect()}
    print("rows by source:", sources)
    if not live:
        assert set(sources) == {"History"}
        same = one(spark, "SELECT (SELECT sum(EnergyKwh) FROM fact_scada_10min), (SELECT sum(EnergyKwh) FROM ops_scada_10min)")
        assert abs(same[0] - same[1]) < 1e-6 * same[1], "history-only series differs from ops_scada_10min"
        return
    assert sources.get("Live", 0) > 0
    # The fault: four periods of forced outage on WT-03, with lost energy.
    fault = one(spark, "SELECT count(*), sum(LostEnergyKwh), sum(EnergyKwh) FROM fact_scada_10min "
                       "WHERE Source = 'Live' AND TurbineId = 'WT-03' AND AvailabilityCategory = 'Forced outage'")
    assert fault[0] == 4 and fault[1] > 0 and fault[2] == 0, f"fault periods: {fault}"
    # The curtailment: four periods of partial performance on WT-04 with telemetry, cause grid curtailment.
    limited = one(spark, "SELECT count(*), sum(LostEnergyKwh) FROM fact_scada_10min WHERE Source = 'Live' "
                         "AND TurbineId = 'WT-04' AND LossCause = 'Grid curtailment'")
    assert limited[0] == 4 and limited[1] > 0, f"curtailed periods: {limited}"
    # The silences after the end of the history become "Information unavailable"; before it, history stays.
    silent = one(spark, "SELECT count(*) FROM fact_scada_10min WHERE Source = 'Live' AND State = 'UNKNOWN'")
    assert silent[0] == 2 * 12 + 4, f"periods without telemetry after the history (two for all, four more for WT-06): {silent}"
    overlap = one(spark, "SELECT count(*) FROM fact_scada_10min s JOIN (SELECT max(Timestamp) AS AsOf FROM ops_scada_10min) a "
                         "WHERE s.Source = 'Live' AND s.Timestamp <= a.AsOf")
    assert overlap[0] == 4 * 12, f"live periods that replaced generated ones: {overlap}"
    running = one(spark, "SELECT avg(EnergyKwh / PossibleEnergyKwh), min(AirDensity), max(AirDensity) FROM fact_scada_10min "
                         "WHERE Source = 'Live' AND AvailabilityCategory = 'Full performance' AND PossibleEnergyKwh > 0")
    assert 0.9 < running[0] < 1.2 and running[1] == running[2] == 1.1, f"live full performance: {running}"


def run_acceptance_sql(spark) -> None:
    last_day = one(spark, "SELECT max(Date) FROM fact_scada_10min")[0]

    def months_back(day, months):
        month = day.year * 12 + day.month - 1 - months
        return dt.date(month // 12, month % 12 + 1, 1)
    d = {"end": last_day + dt.timedelta(days=1), "d90": last_day - dt.timedelta(days=90),
         "month": last_day.replace(day=1), "year": last_day.replace(month=1, day=1),
         "m6": months_back(last_day, 6), "m12": months_back(last_day, 12),
         "y12": months_back(last_day, 12).replace(day=min(last_day.day, 28))}
    for check in model_spec.acceptance_checks(d):
        pdf = spark.sql(check["sql"]).toPandas()
        values = [c for c in pdf.columns if c not in check["keys"]]
        assert len(pdf) >= 1 and pdf[values[0]].notna().all(), f"{check['id']}: empty result\n{pdf}"
        assert not pdf.duplicated(check["keys"]).any() if check["keys"] else len(pdf) == 1, f"{check['id']}: keys repeat"
        print(f"{check['id']:14s} {len(pdf):3d} rows   " + ", ".join(f"{c}={pdf[c].iloc[0]:.4g}" for c in values))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lakehouse", required=True, metavar="DIR")
    args = parser.parse_args()
    lakehouse = Path(args.lakehouse).resolve()
    os.environ["TZ"] = "UTC"                                      # the stand-in telemetry is written in UTC
    time.tzset()
    os.chdir(lakehouse)
    spark = session(lakehouse)
    spark.conf.set("spark.sql.session.timeZone", "UTC")
    print(f"Spark {spark.version}, Python {sys.version.split()[0]}, ANSI mode {spark.conf.get('spark.sql.ansi.enabled')}")

    print("\n=================== 05_build_model_tables, history only")
    spark.sql("DROP TABLE IF EXISTS TurbineTelemetry")
    spark.sql("DROP TABLE IF EXISTS WeatherObservations")
    cells = run_notebook(spark, lakehouse, "05_build_model_tables")
    check_tables(spark, live=False)

    print("\n=================== 05_build_model_tables, with live telemetry")
    as_of = dt.datetime.strptime(one(spark, "SELECT date_format(max(Timestamp), 'yyyy-MM-dd HH:mm:ss') FROM ops_scada_10min")[0],
                                 "%Y-%m-%d %H:%M:%S")
    write_live(spark, as_of)
    cells += run_notebook(spark, lakehouse, "05_build_model_tables")
    check_tables(spark, live=True)

    print("\n=================== Lakehouse side of the acceptance checks of notebook 07")
    run_acceptance_sql(spark)
    print(f"\n{cells} code cells ran without error; all checks passed")
    spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
