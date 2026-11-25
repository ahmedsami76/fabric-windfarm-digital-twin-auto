#!/usr/bin/env python3
"""Checks the T-SQL the wind farm twin sends to the Lakehouse: fabric/sql/94-twin-app-queries.sql.

    python3 tools/check-twin-sql.py

1. Names: every table is one of the six shortcut tables, and every column the statements name is a
   column of the Eventhouse table of that name (fabric/kql/01-tables.kql), spelled the same way. The
   SQL analytics endpoint tells capitals from small letters.
2. Syntax: every statement parses as T-SQL (sqlglot).
3. Meaning: the statements run in DuckDB on a small made-up site and must return what the KQL
   versions are written to return: the newest row per turbine, the alarms ActiveAlarms() would list,
   the newest observation, one trend row a minute, the count of the connection check.

Needs: pip install sqlglot duckdb. What it cannot show: that the SQL analytics endpoint accepts every
function and type. Only a run on the endpoint shows that; the file says how to run it there.
"""
from __future__ import annotations

import datetime as dt
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SQL_FILE = ROOT / "fabric" / "sql" / "94-twin-app-queries.sql"
TABLES_FILE = ROOT / "fabric" / "kql" / "01-tables.kql"
SHORTCUTS = {"TurbineTelemetry", "WeatherObservations", "AlarmEvents", "TurbineStateChanges", "AssetRegistry", "EdgeHeartbeats"}


def statements() -> list[str]:
    text = "\n".join(line for line in SQL_FILE.read_text(encoding="utf-8").splitlines() if not line.startswith("--"))
    return [s.strip() for s in text.split(";") if s.strip()]


def table_columns() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for name, body in re.findall(r"\.create-merge table (\w+) \(([^)]*)\)", TABLES_FILE.read_text(encoding="utf-8")):
        found[name] = {part.split(":")[0].strip() for part in body.split(",")}
    return found


def name_problems(sql: str, columns: dict[str, set[str]]) -> list[str]:
    import sqlglot
    from sqlglot import exp

    tree = sqlglot.parse_one(sql, read="tsql")
    ctes = {c.alias for c in tree.find_all(exp.CTE)}
    tables = {t.name for t in tree.find_all(exp.Table)} - ctes
    problems = [f"table {t} is not a shortcut table" for t in sorted(tables - SHORTCUTS)]
    known = set().union(*(columns.get(t, set()) for t in tables)) if tables else set()
    made = {a.alias for a in tree.find_all(exp.Alias)} | {"rn", "StartedAt"}
    for column in sorted({c.name for c in tree.find_all(exp.Column)}):
        if column not in known and column not in made:
            problems.append(f"column {column} is in none of {sorted(tables)}")
    return problems


def site(con, now: dt.datetime) -> None:
    """Three turbines, a restart of the edge 20 minutes ago, alarms before and after it."""
    ago = lambda **kw: now - dt.timedelta(**kw)  # noqa: E731
    con.execute("CREATE TABLE TurbineTelemetry (Timestamp TIMESTAMP, TurbineId VARCHAR, State VARCHAR, " + ", ".join(
        f"{c} DOUBLE" for c in TELEMETRY) + ")")
    rows = []
    for turbine, newest_min in (("WT-01", 6), ("WT-02", 7), ("WT-03", 90)):  # WT-03 is silent for 90 minutes
        for k in range(0, 30):
            ts = ago(minutes=newest_min, seconds=20 * k)
            rows.append([ts, turbine, "RUNNING"] + [float(100 * (i + 1) + k) for i in range(len(TELEMETRY))])
    con.executemany(f"INSERT INTO TurbineTelemetry VALUES ({', '.join('?' * (3 + len(TELEMETRY)))})", rows)
    con.execute("CREATE TABLE WeatherObservations (Timestamp TIMESTAMP, WindSpeed DOUBLE, WindDirection DOUBLE, WindGust DOUBLE, AmbientTemp DOUBLE, AirDensity DOUBLE)")
    con.executemany("INSERT INTO WeatherObservations VALUES (?, ?, ?, ?, ?, ?)", [[ago(minutes=m), 8.0 + m, 200.0, 11.0, 12.0, 1.1] for m in (6, 7, 8)])
    con.execute("CREATE TABLE EdgeHeartbeats (Timestamp TIMESTAMP, UptimeSeconds BIGINT)")
    con.executemany("INSERT INTO EdgeHeartbeats VALUES (?, ?)", [[ago(minutes=7), 13 * 60], [ago(minutes=6), 14 * 60]])  # started 20 minutes ago
    con.execute("CREATE TABLE AlarmEvents (Timestamp TIMESTAMP, TurbineId VARCHAR, AlarmId VARCHAR, AlarmCode VARCHAR, Status VARCHAR, Severity VARCHAR, "
                "Component VARCHAR, Description VARCHAR, Value DOUBLE, Threshold DOUBLE, Unit VARCHAR, SopId VARCHAR)")
    alarm = lambda minutes, turbine, alarm_id, code, status: [ago(minutes=minutes), turbine, alarm_id, code, status, "warning", "gearbox", "text", 6.0, 5.5, "mm/s", "SOP-GBX-001"]  # noqa: E731
    con.executemany("INSERT INTO AlarmEvents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", [
        alarm(15, "WT-01", "a-open", "GBX-VIB-HIGH", "raised"),          # raised after the start, not cleared: listed
        alarm(14, "WT-02", "a-cleared", "GBX-VIB-HIGH", "raised"),
        alarm(9, "WT-02", "a-cleared", "GBX-VIB-HIGH", "cleared"),       # cleared: not listed
        alarm(50, "WT-01", "a-old", "GBX-OIL-TEMP-HIGH", "raised"),      # from before the start: not listed
        alarm(20.5, "WT-03", "a-edge", "GBX-OIL-TEMP-HIGH", "raised"),   # within a minute before the start: listed
        alarm(8, "WT-03", "a-comms", "COMMS-RESTORED", "raised"),        # never an alarm
        alarm(10, "WT-02", "a-later", "GBX-VIB-CRIT", "raised"),         # the newer of two open ones: listed first
    ])


TELEMETRY: list[str] = []


def run(con, sql: str):
    import sqlglot

    duck = sqlglot.transpile(sql, read="tsql", write="duckdb")[0]
    cursor = con.execute(duck)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def main() -> int:
    try:
        import duckdb
        import sqlglot  # noqa: F401
    except ImportError as error:
        print(f"SKIP: {error}. pip install sqlglot duckdb")
        return 0
    found = statements()
    if len(found) != 5:
        print(f"FAIL: expected 5 statements in {SQL_FILE.name}, found {len(found)}")
        return 1
    turbines, alarms, weather, trend, probe = found
    columns = table_columns()
    status = 0
    for label, sql in zip(("turbines", "alarms", "weather", "trend", "probe"), found):
        problems = name_problems(sql, columns)
        for problem in problems:
            print(f"FAIL names, {label}: {problem}")
            status = 1

    TELEMETRY[:] = [c for c in re.search(r"SELECT TurbineId, \[Timestamp\], State, ([^\n]*)\nFROM newest", turbines).group(1).split(", ")]
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)
    # DuckDB has no SYSUTCDATETIME(): it is given one that answers the moment the made-up site was built at.
    con.execute(f"CREATE MACRO sysutcdatetime() AS TIMESTAMP '{now.isoformat(sep=' ')}'")
    site(con, now)

    def expect(label: str, got, want) -> None:
        nonlocal status
        if got == want:
            print(f"ok   {label}")
        else:
            print(f"FAIL {label}\n     got  {got}\n     want {want}")
            status = 1

    rows = run(con, turbines)
    expect("turbines: one row each for the turbines heard in the last hour, the newest, by identifier",
           [(r["TurbineId"], round((now - r["Timestamp"]).total_seconds())) for r in rows], [("WT-01", 360), ("WT-02", 420)])
    expect("turbines: every value comes from that newest row", [r[TELEMETRY[0]] for r in rows], [100.0, 100.0])
    rows = run(con, alarms)
    expect("alarms: raised, not cleared, since the edge started (a minute of grace), newest first; never COMMS-RESTORED",
           [r["AlarmId"] for r in rows], ["a-later", "a-open", "a-edge"])
    expect("alarms: the columns of ActiveAlarms()", sorted(rows[0]) if rows else [],
           sorted(["RaisedAt", "TurbineId", "AlarmCode", "Severity", "Component", "Description", "Value", "Threshold", "Unit", "SopId", "AlarmId"]))
    con.execute("DELETE FROM EdgeHeartbeats")
    expect("alarms: without a heartbeat every open alarm is listed, as isnull(lastStart) does",
           [r["AlarmId"] for r in run(con, alarms)], ["a-later", "a-open", "a-edge", "a-old"])
    rows = run(con, weather)
    expect("weather: the newest observation", [(round((now - r["Timestamp"]).total_seconds()), r["WindSpeed"]) for r in rows], [(360, 14.0)])
    con.execute("CREATE TABLE t7 AS SELECT * FROM TurbineTelemetry WHERE TurbineId = 'WT-01'")
    con.execute("UPDATE TurbineTelemetry SET TurbineId = 'WT-07' WHERE TurbineId = 'WT-01'")
    rows = run(con, trend)
    minutes = [r["Timestamp"] for r in rows]
    want = con.execute("SELECT date_trunc('minute', Timestamp) AS m, AVG(ActivePower) FROM t7 GROUP BY m ORDER BY m").fetchall()
    expect("trend: one row a minute, on the minute, in order, with the average of that minute",
           [(m, round(r["ActivePower"], 6)) for m, r in zip(minutes, rows)], [(m, round(v, 6)) for m, v in want])
    rows = run(con, probe)
    expect("probe: rows, turbines and the newest row of the last hour",
           [(r["Rows"], r["Turbines"], round((now - r["Newest"]).total_seconds())) for r in rows], [(60, 2, 360)])
    print("T-SQL of the twin: " + ("all checks passed" if status == 0 else "FAILED"))
    return status


if __name__ == "__main__":
    sys.exit(main())
