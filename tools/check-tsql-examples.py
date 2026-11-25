#!/usr/bin/env python3
"""Check the T-SQL example queries of the data agent (tools/agent_spec.py) without a SQL endpoint.

1. Names: every table and column a query uses exists in tools/lakehouse_schema.json with exactly that
   spelling. The SQL analytics endpoint of a Lakehouse is case sensitive; Spark and DuckDB are not.
2. Syntax: every query parses as T-SQL (sqlglot).
3. Meaning, with --lakehouse DIR (the stand-in Lakehouse of tools/local-spark): the T-SQL query and the
   Spark SQL of the same question in tools/question_bank.py, both run through DuckDB, return the same rows.

    python3 tools/check-tsql-examples.py [--lakehouse /tmp/lh35]
Needs: pip install sqlglot duckdb.  What it cannot show: that the endpoint accepts every function. Notebook
09 runs each example on the endpoint before it adds it to the agent.
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_spec as spec  # noqa: E402
import question_bank as bank  # noqa: E402

LABEL_FIRST = {"SM-01"}             # the first column is a month label the example writes differently
LIST_LAST = {"OP-02", "MP-03"}      # the last column is a list whose order neither engine defines
# Spark counts Sunday as day 1 of the week, DuckDB as day 0. For the comparison the reference names the day instead.
REFERENCE_FOR_DUCKDB = {"MP-01": ("dayofweek(LocalTime) <> 1", "date_format(LocalTime, 'EEEE') <> 'Sunday'")}
TOP_TIES = {"RE-03": 2}             # TOP n ordered by this column; rows that tie at the cut can differ
TIED_PICK = {"RE-04": 5}            # column that names "the one with the most"; two can tie, and either is right
SCHEMA = json.loads((Path(__file__).resolve().parent / "lakehouse_schema.json").read_text())


def name_problems(sql: str) -> list[str]:
    """Identifiers that match a table or column except for upper and lower case."""
    import sqlglot
    from sqlglot import exp
    tree = sqlglot.parse_one(sql, read="tsql")
    ctes = {c.alias for c in tree.find_all(exp.CTE)}
    tables = {t.name for t in tree.find_all(exp.Table)} - ctes
    problems = [f"table {t} is not in the Lakehouse" for t in sorted(tables) if t not in SCHEMA]
    columns = {c for t in tables if t in SCHEMA for c in SCHEMA[t]}
    lower = {}
    for c in columns:
        lower.setdefault(c.lower(), set()).add(c)
    aliases = {a.alias for a in tree.find_all(exp.Alias)} | {"AsOf", "MonthStart", "MonthEnd", "Quantity"}
    owner = {t.alias_or_name: t.name for t in tree.find_all(exp.Table) if t.name in SCHEMA}
    for col in tree.find_all(exp.Column):
        name = col.name
        if col.table in owner:                      # s.TurbineId: check against the table behind the alias
            table = owner[col.table]
            if name not in SCHEMA[table]:
                close = [c for c in SCHEMA[table] if c.lower() == name.lower()]
                problems.append(f"column {col.table}.{name}: " + (f"{table} spells it {close[0]}" if close
                                                                   else f"{table} has no such column"))
            continue
        if name in columns or name in aliases:
            continue
        if name.lower() in lower:
            problems.append(f"column {name}: the Lakehouse spells it {sorted(lower[name.lower()])}")
        else:
            problems.append(f"column {name} is in none of the tables {sorted(tables)}")
    return problems


def rows(con, sql: str, read: str):
    import sqlglot
    duck = sqlglot.transpile(sql, read=read, write="duckdb")[0]
    # The stand-in files hold timestamps with a UTC marker, the SQL endpoint holds them without one.
    # "x AT TIME ZONE 'UTC' AT TIME ZONE zone" on the endpoint is "x AT TIME ZONE zone" on the stand-in.
    duck = duck.replace(" AT TIME ZONE 'UTC' AT TIME ZONE ", " AT TIME ZONE ")
    return con.execute(duck).fetchall()


def same(a, b) -> bool:
    import datetime as dt
    day = lambda v: v.date() if isinstance(v, dt.datetime) and v.time() == dt.time(0) else v      # noqa: E731
    if isinstance(a, (dt.date, dt.datetime)) and isinstance(b, (dt.date, dt.datetime)):
        return str(day(a)) == str(day(b))
    if isinstance(a, float) or isinstance(b, float):
        if a is None or b is None:
            return a is b
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=1e-9)
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) == bool(b)
    return str(a) == str(b)


def main(argv) -> int:
    lakehouse = Path(argv[argv.index("--lakehouse") + 1]) if "--lakehouse" in argv else None
    reference = {q["id"]: q["sql"] for q in bank.QUESTIONS}
    failed = 0
    con = None
    if lakehouse:
        import duckdb
        con = duckdb.connect()
        con.execute("SET TimeZone = 'UTC'")
        for table in SCHEMA:
            files = lakehouse / "Tables" / table
            if files.is_dir():
                con.execute(f"CREATE VIEW {table} AS SELECT * FROM read_parquet('{files}/*.parquet')")
        con.execute(bank.SETUP_SQL.replace("TEMP VIEW", "VIEW"))
        con.execute("CREATE MACRO pmod(a, b) AS (a - b * floor(a / b))")      # Spark's pmod, for the reference queries
    uncompared = 0
    for qid, sql in spec.TSQL_EXAMPLES.items():
        problems, notes = name_problems(sql), []
        if con is not None and not problems:
            try:
                got = rows(con, sql.replace("'Central Standard Time'", "'America/Chicago'"), "tsql")
                old, new = REFERENCE_FOR_DUCKDB.get(qid, ("", ""))
                assert old in reference[qid], f"{qid}: the reference query changed; update REFERENCE_FOR_DUCKDB"
                want = rows(con, reference[qid].replace(old, new) if old else reference[qid], "spark")
            except Exception as error:                # DuckDB cannot run one of the two: say so, do not pass it
                got = want = None
                notes.append(f"not compared: {str(error).splitlines()[0][:150]}")
            if got is not None:
                label = lambda rs: [r[1:] for r in rs] if qid in LABEL_FIRST else rs          # noqa: E731
                cells = lambda rs: [tuple(", ".join(sorted(str(v).split(", "))) if i == len(r) - 1 and qid in LIST_LAST else v  # noqa: E731
                                          for i, v in enumerate(r)) for r in rs]
                got, want = cells(label(got)), cells(label(want))
                if qid in TIED_PICK:
                    drop = lambda rs: [r[:TIED_PICK[qid]] + r[TIED_PICK[qid] + 1:] for r in rs]      # noqa: E731
                    got, want = drop(got), drop(want)
                equal = lambda x, y: len(x) == len(y) and all(len(g) == len(w) and all(same(u, v) for u, v in zip(g, w))  # noqa: E731
                                                               for g, w in zip(x, y))
                if qid in TOP_TIES and len(got) == len(want) and want:
                    key = TOP_TIES[qid]
                    cut = min(r[key] for r in want)
                    above = lambda rs: sorted((r for r in rs if r[key] > cut), key=str)       # noqa: E731
                    if sorted(r[key] for r in got) == sorted(r[key] for r in want):
                        got, want = above(got), above(want)
                        notes.append("rows that tie at the cut of TOP were left out of the comparison")
                if not want:
                    notes.append("not compared: the reference query returns no rows on this data")
                elif len(got) != len(want):
                    problems.append(f"{len(got)} rows, the reference query returns {len(want)}")
                elif not equal(got, want):
                    if equal(sorted(got, key=str), sorted(want, key=str)):
                        notes.append("same rows; the order differs where the sort key ties")
                    else:
                        i = next(i for i, (g, w) in enumerate(zip(got, want)) if not equal([g], [w]))
                        problems.append(f"row {i + 1} differs: {got[i]} / reference {want[i]}")
        print(f"{'FAIL' if problems else 'ok  '} {qid}" + "".join(f"\n       {p}" for p in problems + notes))
        uncompared += any(n.startswith("not compared") for n in notes)
        failed += bool(problems)
    print(f"{len(spec.TSQL_EXAMPLES) - failed} of {len(spec.TSQL_EXAMPLES)} examples ok"
          + (f"; {uncompared} of them checked for names and syntax only" if uncompared else "")
          + ("" if con is not None else " (names and syntax only; add --lakehouse DIR to compare results)"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
