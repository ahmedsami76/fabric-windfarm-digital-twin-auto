#!/usr/bin/env python3
"""Builds fabric/notebooks/90_deployment_gate.ipynb, the notebook tools/deploy.py runs to see whether tables have rows.

    python3 tools/build-deploy-gate.py           write the notebook
    python3 tools/build-deploy-gate.py --check   fail when the notebook in the repository is not what this builds

The runner cannot read a job's output: the Job Scheduler returns a state and, for a failure, a reason. So the notebook
passes or fails as a whole, and writes what it counted to a small file in the Lakehouse for the runner to read.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "fabric" / "notebooks" / "90_deployment_gate.ipynb"

INTRO = """# Deployment gate

Run by `tools/deploy.py` as a job after the steps that fill the Lakehouse. It reads every table it is given, counts the rows,
and for a live table looks at the age of the newest row. When a table is missing, empty or stale it **fails**, which is how the
runner learns the verdict. It writes what it counted to `Files/deployment/gate-<label>.json`.

It changes no table. You can run it by hand: put a list into `checks`, or leave it empty to see the form.
"""

PARAMETERS = '''# Filled in by the runner. By hand: a JSON list such as
# [{"table": "TurbineTelemetry", "min_rows": 1, "newest": "Timestamp", "within_minutes": 60}, {"table": "ref_turbines"}]
checks = "[]"
label = "manual"
'''

LOGIC = '''import json
from datetime import datetime, timezone


def run_checks(spark, checks, now=None):
    """Counts the rows of each table and, where asked, measures the age of its newest row. Reads only."""
    now = now or datetime.now(timezone.utc)
    tables, failures = [], []
    for check in checks:
        table = check["table"]
        entry = {"table": table, "rows": None, "age_minutes": None}
        try:
            frame = spark.read.table(table)
            entry["rows"] = frame.count()
            wanted = check.get("min_rows", 1)
            if entry["rows"] < wanted:
                failures.append(f"{table}: {entry['rows']} rows, expected at least {wanted}")
            column = check.get("newest")
            if column and entry["rows"]:
                newest = frame.agg({column: "max"}).collect()[0][0]
                if newest is not None:
                    if newest.tzinfo is None:
                        newest = newest.replace(tzinfo=timezone.utc)
                    entry["age_minutes"] = round((now - newest).total_seconds() / 60, 1)
                    limit = check.get("within_minutes", 60)
                    if entry["age_minutes"] > limit:
                        failures.append(f"{table}: the newest row is {entry['age_minutes']} minutes old, expected at most {limit}")
        except Exception as error:  # a table that does not exist, a shortcut that cannot be read
            failures.append(f"{table}: cannot be read ({str(error).splitlines()[0][:200]})")
        tables.append(entry)
    return {"checked_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "tables": tables, "failures": failures}


result = run_checks(spark, json.loads(checks))
result["label"] = label
for row in result["tables"]:
    age = "" if row["age_minutes"] is None else f"   newest {row['age_minutes']} min old"
    print(f"{row['table']:<28} {row['rows'] if row['rows'] is not None else 'unreadable':>10}{age}")
'''

VERDICT = '''import notebookutils

notebookutils.fs.put(f"Files/deployment/gate-{label}.json", json.dumps(result, indent=2), True)
if result["failures"]:
    raise RuntimeError("Deployment gate failed: " + "; ".join(result["failures"]))
print(f"Deployment gate passed: {len(result['tables'])} tables read.")
'''


def cell(kind: str, source: str, tags=None) -> dict:
    body = {"cell_type": kind, "id": hashlib.sha256(source.encode("utf-8")).hexdigest()[:12],
            "metadata": {"tags": tags} if tags else {}, "source": source.splitlines(keepends=True)}
    if kind == "code":
        body.update(execution_count=None, outputs=[])
    return body


def notebook() -> dict:
    return {"cells": [cell("markdown", INTRO), cell("code", PARAMETERS, ["parameters"]), cell("code", LOGIC), cell("code", VERDICT)],
            "metadata": {"kernelspec": {"display_name": "Synapse PySpark", "language": "Python", "name": "synapse_pyspark"},
                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 5}


def main(argv) -> int:
    text = json.dumps(notebook(), indent=1, ensure_ascii=False) + "\n"
    if "--check" in argv:
        if not TARGET.exists() or TARGET.read_text(encoding="utf-8") != text:
            print(f"{TARGET.relative_to(ROOT)} is not what tools/build-deploy-gate.py builds. Run it without --check.")
            return 1
        print("the gate notebook is up to date")
        return 0
    TARGET.write_text(text, encoding="utf-8")
    print(f"wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
