"""Phase 3: the data agent, the ontology and the operations agent must be consistent with the data.

What these tests cannot do is talk to Fabric: no test here creates an agent or an ontology, and none
runs T-SQL on a SQL endpoint. Notebook 09 runs every example query in Fabric before it uses it, and
notebook 10 asks the agent the questions.
"""
import base64
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import agent_spec as spec  # noqa: E402
import question_bank as bank  # noqa: E402

SCHEMA = json.loads((ROOT / "tools" / "lakehouse_schema.json").read_text())
NOTEBOOKS = ["09_build_data_agent", "10_test_data_agent", "11_build_ontology"]


def code_cells(name):
    notebook = json.loads((ROOT / "fabric" / "notebooks" / f"{name}.ipynb").read_text())
    return ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]


def kql_tables():
    text = (ROOT / "fabric" / "kql" / "01-tables.kql").read_text()
    return {name: dict(re.findall(r"(\w+): (\w+)", columns))
            for name, columns in re.findall(r"\.create-merge table (\w+) \(([^)]*)\)", text)}


def test_generated_files_are_current():
    done = subprocess.run([sys.executable, str(ROOT / "tools" / "build-phase3.py"), "--check"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_notebook_cells_compile_and_install_first(name):
    cells = code_cells(name)
    uses_sdk = any("fabric.dataagent" in c or "sempy_labs" in c for c in cells)
    if uses_sdk:        # %pip restarts the interpreter: anything defined before it is gone
        assert cells[0].startswith("%pip install"), f"{name}: the install cell must be the first code cell"
        assert spec.SDK_PIN in cells[0] and spec.LABS_PIN in cells[0]
    for index, cell in enumerate(cells):
        if not cell.startswith("%pip"):
            compile(cell, f"{name} cell {index}", "exec")


def test_agent_tables_exist_with_exact_names():
    for table in spec.LAKEHOUSE_TABLES:
        assert table in SCHEMA, table
    live = kql_tables()
    for table in spec.KQL_TABLES:
        assert table in live, table
    # every table a reference query of the question bank reads is one the agent may read
    for q in bank.QUESTIONS:
        for table in [t.strip() for t in q["tables"].split(",")]:
            assert table in spec.LAKEHOUSE_TABLES, f"{q['id']} reads {table}, which the agent cannot see"


def test_tsql_examples_use_exact_names_and_parse():
    pytest.importorskip("sqlglot")
    module_spec = importlib.util.spec_from_file_location("check_tsql", ROOT / "tools" / "check-tsql-examples.py")
    check = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(check)
    for qid, sql in spec.TSQL_EXAMPLES.items():
        assert check.name_problems(sql) == [], qid
        upper = sql.upper()
        for word in ("GETDATE", "SYSUTCDATETIME", "LIMIT ", "DATE_TRUNC", "ADD_MONTHS", "COLLECT_LIST"):
            assert word not in upper, f"{qid}: {word.strip()} is not T-SQL or breaks the 'now' of the data"


def test_variations_and_judge_brief():
    spec_json = json.loads((ROOT / "fabric" / "data-agent" / "agent-spec.json").read_text())
    questions = spec_json["test"]["questions"]
    kinds = [q["kind"].split(" of ")[0] for q in questions]
    assert kinds.count("variation") == len(spec.VARIATIONS) and kinds.count("example") == len(spec.TSQL_EXAMPLES)
    assert len({q["question"] for q in questions}) == len(questions), "the test joins answers to questions by their text"
    examples = {e["question"] for e in spec_json["lakehouse"]["examples"]}
    reference = {q["id"]: q["sql"].strip() for q in bank.QUESTIONS}
    for q in questions:
        if q["kind"].startswith("variation"):
            assert q["question"] not in examples, f"{q['id']} is an example query: it tests nothing"
            assert q["sql"] != reference[q["kind"].split(" of ")[1]], f"{q['id']}: its query is the query of the base question"
    prompt = spec.CRITIC_PROMPT.format(query="Q", expected_answer="a,b\n1,2")       # the SDK fills in exactly these two
    assert "Q" in prompt and "a,b" in prompt and prompt.rstrip().endswith("Yes, No, or Unclear.")


def test_kql_examples_use_known_tables_and_columns():
    live = kql_tables()
    for question, query in spec.KQL_EXAMPLES.items():
        first = re.search(r"^(?:let \w+ = )?(\w+)", query).group(1)
        assert first in spec.KQL_TABLES, f"{question}: starts from {first}"
        assert "()" not in query.replace("count()", "").replace("percentile(", ""), f"{question}: examples use tables, not stored functions"
        for column in re.findall(r"\b(Gearbox\w+|ActivePower|PowerSetpoint|WindSpeed|AlarmCode|SopId|PreviousState|Reason)\b", query):
            assert column in live[first] or any(column in cols for cols in live.values()), f"{question}: {column}"


def test_unanswerable_questions_have_no_table():
    names = " ".join(c for cols in SCHEMA.values() for c in cols).lower()
    for _, question, _ in spec.UNANSWERABLE:
        assert not any(word in names for word in ("bird", "remaininglife", "neighbour")), question


def build_ontology_parts(bind_telemetry=True):
    cells = code_cells("11_build_ontology")
    scope = {"json": json, "base64": base64, "workspace_id": "ws", "lakehouse_id": "lh", "eventhouse_id": "eh",
             "cluster_uri": "https://example.kusto.fabric.microsoft.com", "LAKEHOUSE_SCHEMA": "dbo", "BIND_TELEMETRY": bind_telemetry}
    exec(cells[0], scope)                                           # SPEC
    exec(next(c for c in cells if c.startswith("def part(")), scope)
    return {p["path"]: json.loads(base64.b64decode(p["payload"])) for p in scope["parts"]}, scope["SPEC"]


def test_ontology_definition_matches_the_tables():
    parts, _ = build_ontology_parts()
    live = kql_tables()
    entities = {path.split("/")[1]: body for path, body in parts.items() if re.fullmatch(r"EntityTypes/\d+/definition.json", path)}
    assert len(entities) == len(spec.ENTITIES)
    ids, names, types = [], set(), {}
    for entity_id, entity in entities.items():
        assert entity["id"] == entity_id and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,25}", entity["name"])
        properties = {p["id"]: p for p in entity["properties"] + entity["timeseriesProperties"]}
        assert entity["entityIdParts"][0] in properties and entity["displayNamePropertyId"] in properties
        assert properties[entity["entityIdParts"][0]]["valueType"] in ("String", "BigInt")
        ids += [entity_id] + list(properties)
        names.add(entity["name"])
        for p in properties.values():
            assert re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,25}", p["name"]), p["name"]
            assert types.setdefault(p["name"], p["valueType"]) == p["valueType"], f"{p['name']} has two types"
        bindings = [b["dataBindingConfiguration"] for path, b in parts.items() if path.startswith(f"EntityTypes/{entity_id}/DataBindings/")]
        static = [b for b in bindings if b["dataBindingType"] == "NonTimeSeries"]
        assert len(static) == 1, f"{entity['name']}: exactly one static binding"
        table = static[0]["sourceTableProperties"]["sourceTableName"]
        for binding in static[0]["propertyBindings"]:
            assert binding["sourceColumnName"] in SCHEMA[table], f"{table}.{binding['sourceColumnName']}"
            assert binding["targetPropertyId"] in properties
        for series in [b for b in bindings if b["dataBindingType"] == "TimeSeries"]:
            source = series["sourceTableProperties"]
            assert source["sourceType"] == "KustoTable" and source["itemId"] == "eh"
            columns = live[source["sourceTableName"]]
            assert columns[series["timestampColumnName"]] == "datetime"
            bound = {b["sourceColumnName"]: b["targetPropertyId"] for b in series["propertyBindings"]}
            assert set(bound) <= set(columns)
            assert entity["entityIdParts"][0] in bound.values(), "the time series must be tied to the key of the entity"
            for column, target in bound.items():
                kind = properties[target]["valueType"]
                assert {"datetime": "DateTime", "string": "String", "real": "Double", "long": "BigInt"}[columns[column]] == kind
    relationships = {path.split("/")[1]: body for path, body in parts.items() if re.fullmatch(r"RelationshipTypes/\d+/definition.json", path)}
    assert len(relationships) == len(spec.RELATIONSHIPS)
    for relationship_id, relationship in relationships.items():
        source, target = entities[relationship["source"]["entityTypeId"]], entities[relationship["target"]["entityTypeId"]]
        assert source is not target and relationship["name"] not in names | set(types)
        names.add(relationship["name"])
        ids.append(relationship_id)
        (context,) = [b for path, b in parts.items() if path.startswith(f"RelationshipTypes/{relationship_id}/Contextualizations/")]
        columns = SCHEMA[context["dataBindingTable"]["sourceTableName"]]
        (s,), (t,) = context["sourceKeyRefBindings"], context["targetKeyRefBindings"]
        assert s["sourceColumnName"] in columns and t["sourceColumnName"] in columns
        assert s["targetPropertyId"] == source["entityIdParts"][0] and t["targetPropertyId"] == target["entityIdParts"][0]
    assert len(ids) == len(set(ids)) and all(i.isdigit() and 15 <= len(i) <= 18 for i in ids)
    assert all("\\" not in path for path in parts)


def test_ontology_without_telemetry_has_no_time_series():
    parts, _ = build_ontology_parts(bind_telemetry=False)
    assert not any(b.get("dataBindingConfiguration", {}).get("dataBindingType") == "TimeSeries" for b in parts.values())
    assert all(not b.get("timeseriesProperties") for path, b in parts.items() if path.startswith("EntityTypes/") and path.endswith("definition.json"))


def simulate(tmp_path, wind, inject):
    out = tmp_path / f"events-{wind}.json"
    command = [sys.executable, "-m", "windfarm_sim.generate", "--minutes", "40", "--seed", "7", "--wind-mean", str(wind),
               "--no-spontaneous", "--out", str(out)] + (["--inject", inject] if inject else [])
    subprocess.run(command, cwd=ROOT, check=True, capture_output=True, env={"PYTHONPATH": str(ROOT / "simulator"), "PATH": "/usr/bin:/bin"})
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    telemetry = [r for r in rows if r.get("messageType") == "telemetry"]
    alarms = {r["data"]["alarmCode"] for r in rows if r.get("messageType") == "alarm"}
    return telemetry, alarms


@pytest.mark.parametrize("wind", [6, 9, 13])
def test_operations_agent_thresholds_fit_the_simulator(tmp_path, wind):
    """A healthy fleet stays below the early warning; a small fault crosses it and the controller stays silent."""
    telemetry, alarms = simulate(tmp_path, wind, "WT-03:gearbox_degradation:0.2:30m@5m")
    by_turbine = {}
    for row in telemetry:
        by_turbine.setdefault(row["assetId"], []).append(row["data"]["gearboxVibration"])
    for turbine, values in by_turbine.items():
        if turbine != "WT-03":
            assert max(values) < spec.EARLY_VIBRATION, f"{turbine} would raise the early warning without a fault"
    hold = by_turbine["WT-03"][len(by_turbine["WT-03"]) * 12 // 40: len(by_turbine["WT-03"]) * 30 // 40]
    assert sum(v > spec.EARLY_VIBRATION for v in hold) / len(hold) > 0.5, "the small fault must cross the early warning"
    assert not {a for a in alarms if a.startswith("GBX-VIB")}, "the controller must stay silent on vibration at severity 0.2"
    assert spec.EARLY_VIBRATION < spec.ALARM_VIBRATION


def test_full_fault_crosses_the_controller_threshold(tmp_path):
    telemetry, alarms = simulate(tmp_path, 9, "WT-07:gearbox_degradation:0.8:15m@10m")
    assert max(r["data"]["gearboxVibration"] for r in telemetry if r["assetId"] == "WT-07") > spec.ALARM_VIBRATION
    assert "GBX-VIB-HIGH" in alarms


def test_operations_agent_text_names_real_columns_and_thresholds():
    columns = kql_tables()["TurbineTelemetry"]
    for column in re.findall(r"'(\w+)'", spec.OPS_INSTRUCTIONS):
        assert column in columns or column == "TurbineTelemetry", column
    assert f"{spec.EARLY_VIBRATION:g} mm/s" in spec.OPS_INSTRUCTIONS and f"{spec.ALARM_VIBRATION:g} mm/s" in spec.OPS_INSTRUCTIONS
    readiness = (ROOT / "fabric" / "kql" / "05-agent-readiness.kql").read_text()
    for column in re.findall(r"^\s+(\w+): \"", readiness, flags=re.M):
        assert column in columns, f"05-agent-readiness.kql describes {column}, which TurbineTelemetry does not have"
    assert "VibrationVsFleet" in readiness and "VibrationVsFleet" in spec.OPS_RULE_4
    # the alarm thresholds quoted to the agent are the thresholds of the controller
    alarm_codes = (ROOT / "simulator" / "windfarm_sim" / "alarms.py").read_text()
    assert re.search(r'"GBX-VIB-HIGH".*?"gearboxVibration", 5\.5', alarm_codes, flags=re.S) and spec.ALARM_VIBRATION == 5.5
    assert re.search(r'"GBX-OIL-TEMP-HIGH".*?"gearboxOilTemp", 78\.0', alarm_codes, flags=re.S)
