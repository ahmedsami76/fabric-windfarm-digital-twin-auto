#!/usr/bin/env python3
"""Build the files of Phase 3 from tools/agent_spec.py and tools/question_bank.py.

    python3 tools/build-phase3.py            write the files
    python3 tools/build-phase3.py --check    exit 1 if a file is out of date

Writes the notebooks 09 to 11, fabric/data-agent/*, fabric/ontology/ontology-spec.json,
fabric/operations-agent/*, fabric/kql/93-data-agent-examples.kql and docs/10-ontology.md.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import agent_spec as spec  # noqa: E402
import question_bank as bank  # noqa: E402

_p2 = importlib.util.spec_from_file_location("build_phase2", ROOT / "tools" / "build-phase2.py")
phase2 = importlib.util.module_from_spec(_p2)
_p2.loader.exec_module(phase2)

GENERATED = phase2.GENERATED.replace("build-phase2.py", "build-phase3.py").replace("model_spec.py", "agent_spec.py")
phase2.GENERATED = GENERATED          # render() folds the cells that start with this line
SCHEMA = json.loads((ROOT / "tools" / "lakehouse_schema.json").read_text())
NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9]{0,25}$")     # the stricter rule of the Fabric portal, without - and _
VALUE_TYPE = {"string": {"String"}, "double": {"Double"}, "int": {"BigInt"}, "long": {"BigInt"},
              "boolean": {"Boolean"}, "date": {"DateTime"}, "timestamp": {"DateTime"}}


# ------------------------------------------------------------------------------------------------ ontology
def stable_id(*parts: str) -> str:
    """A positive 18-digit number that is always the same for the same name."""
    return str(10 ** 17 + int(hashlib.sha1("/".join(parts).encode()).hexdigest()[:15], 16) % (9 * 10 ** 17))


def stable_guid(*parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "windfarm-ontology/" + "/".join(parts)))


def ontology_spec() -> dict:
    """The ontology with its identifiers. Workspace and item identifiers are filled in by notebook 11."""
    problems, types, entities = [], {}, []
    for e in spec.ENTITIES:
        columns = SCHEMA.get(e["table"], {})
        props = []
        for column, name, value_type in e["properties"]:
            if column not in columns:
                problems.append(f"{e['name']}: {e['table']} has no column {column}")
            elif value_type not in VALUE_TYPE[columns[column]]:
                problems.append(f"{e['name']}.{name}: {value_type} does not fit {columns[column]}")
            props.append({"id": stable_id(e["name"], name), "name": name, "valueType": value_type, "column": column})
        series = None
        if e.get("timeseries"):
            ts = e["timeseries"]
            series = {"table": ts["table"], "timestampColumn": ts["timestamp"], "keyColumn": ts["key"],
                      "bindingId": stable_guid(e["name"], "timeseries"),
                      "properties": [{"id": stable_id(e["name"], name), "name": name, "valueType": value_type, "column": column}
                                     for column, name, value_type in ts["properties"]]}
        for p in props + (series["properties"] if series else []):
            if not NAME.match(p["name"]):
                problems.append(f"{e['name']}.{p['name']}: a name is 1 to 26 letters and digits and starts with a letter")
            if types.setdefault(p["name"], p["valueType"]) != p["valueType"]:
                problems.append(f"property {p['name']} has two value types; a name can have one in the whole ontology")
        if props[0]["valueType"] not in ("String", "BigInt"):
            problems.append(f"{e['name']}: the key must be a String or a BigInt")
        display = [p["id"] for p in props if p["name"] == e["display"]]
        if not display:
            problems.append(f"{e['name']}: display property {e['display']} is not one of its properties")
        entities.append({"id": stable_id("entity", e["name"]), "name": e["name"], "meaning": e["meaning"], "table": e["table"],
                         "bindingId": stable_guid(e["name"], "static"), "keyPropertyId": props[0]["id"],
                         "displayPropertyId": display[0] if display else props[0]["id"], "properties": props,
                         "timeseries": series})
    by_name = {e["name"]: e for e in entities}
    names = set(by_name) | set(types)
    relationships = []
    for name, source, target, table, source_column, target_column in spec.RELATIONSHIPS:
        if name in names:
            problems.append(f"the name {name} is used twice")
        names.add(name)
        if source == target:
            problems.append(f"{name}: source and target must be different entity types")
        for column in (source_column, target_column):
            if column not in SCHEMA.get(table, {}):
                problems.append(f"{name}: {table} has no column {column}")
        relationships.append({"id": stable_id("relationship", name), "name": name, "source": source, "target": target,
                              "sourceEntityId": by_name[source]["id"], "targetEntityId": by_name[target]["id"],
                              "table": table, "sourceColumn": source_column, "targetColumn": target_column,
                              "sourceKeyPropertyId": by_name[source]["keyPropertyId"],
                              "targetKeyPropertyId": by_name[target]["keyPropertyId"],
                              "contextualizationId": stable_guid("relationship", name)})
    ids = [e["id"] for e in entities] + [r["id"] for r in relationships] \
        + [p["id"] for e in entities for p in e["properties"] + (e["timeseries"]["properties"] if e["timeseries"] else [])]
    if len(ids) != len(set(ids)):
        problems.append("two identifiers are the same")
    if problems:
        raise SystemExit("tools/agent_spec.py, ontology:\n  " + "\n  ".join(problems))
    return {"name": spec.ONTOLOGY, "lakehouse": spec.LAKEHOUSE, "kqlDatabase": spec.KQL_DATABASE,
            "entities": entities, "relationships": relationships}


def ontology_doc(o: dict) -> str:
    lines = ["# The ontology", "",
             "> Generated by `tools/build-phase3.py` from `tools/agent_spec.py`. Change it there.", "",
             f"The ontology **{o['name']}** names the things of the wind farm and how they are connected: "
             f"{len(o['entities'])} entity types and {len(o['relationships'])} relationship types. Notebook "
             "`11_build_ontology` creates it. Every entity type is bound to one table of the Lakehouse "
             f"`{o['lakehouse']}`; the turbine also gets its live signals from the KQL database `{o['kqlDatabase']}`.", "",
             "If the notebook cannot create the ontology, the tables below are the list to build it by hand: "
             "[step 6 of the Phase 3 guide](09-deployment-guide-phase3.md#step-6-ontology).", "",
             "## Entity types", "", "| Entity type | Meaning | Lakehouse table | Key | Shown as |", "|---|---|---|---|---|"]
    for e in o["entities"]:
        shown = next(p["name"] for p in e["properties"] if p["id"] == e["displayPropertyId"])
        lines.append(f"| {e['name']} | {e['meaning']} | `{e['table']}` | {e['properties'][0]['name']} | {shown} |")
    for e in o["entities"]:
        lines += ["", f"### {e['name']}", "", "| Property | Type | Column |", "|---|---|---|"]
        lines += [f"| {p['name']} | {p['valueType']} | `{e['table']}.{p['column']}` |" for p in e["properties"]]
        if e["timeseries"]:
            ts = e["timeseries"]
            lines += ["", f"Time series from the KQL database, table `{ts['table']}`. Timestamp column `{ts['timestampColumn']}`; "
                          f"the rows belong to the {e['name'].lower()} whose key equals column `{ts['keyColumn']}`.", "",
                      "| Property | Type | Column |", "|---|---|---|"]
            lines += [f"| {p['name']} | {p['valueType']} | `{ts['table']}.{p['column']}` |" for p in ts["properties"]]
    lines += ["", "## Relationship types", "",
              "Each relationship is read from one Lakehouse table that holds the key of both ends.", "",
              "| Relationship | From | To | Table | Column with the key of From | Column with the key of To |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['name']} | {r['source']} | {r['target']} | `{r['table']}` | `{r['sourceColumn']}` | `{r['targetColumn']}` |"
              for r in o["relationships"]]
    lines += ["", "## Rules the ontology follows", "",
              "- A name is 1 to 26 letters and digits. A property name that appears on two entity types has the same type on both.",
              "- A key is text or a whole number.",
              "- One entity type has one Lakehouse table. Live signals come from the KQL database and need that table first.",
              "- The Lakehouse tables have no spaces or special characters in column names. Fabric turns on Delta column mapping "
              "for such names, and the ontology cannot read tables with column mapping.",
              "- The data of the ontology is a copy in a graph. After the tables change, refresh the graph model of the ontology.", ""]
    return "\n".join(lines)


# -------------------------------------------------------------------------------------------- data agent
def variations() -> list[dict]:
    reference = {q["id"]: q["sql"].strip() for q in bank.QUESTIONS}
    out = []
    for vid, base, question, replacements in spec.VARIATIONS:
        sql = reference[base]
        for old, new in replacements:
            if old not in sql:
                raise SystemExit(f"tools/agent_spec.py: variation {vid}: '{old}' is not in the reference query of {base}")
            sql = sql.replace(old, new)
        out.append({"id": vid, "question": question, "sql": sql, "kind": "variation of " + base})
    return out


def agent_spec_json() -> dict:
    questions = {q["id"]: q["question"] for q in bank.QUESTIONS}
    missing = sorted(set(spec.TSQL_EXAMPLES) - set(questions))
    if missing:
        raise SystemExit(f"tools/agent_spec.py: no question {missing} in tools/question_bank.py")
    for table in spec.LAKEHOUSE_TABLES:
        if table not in SCHEMA:
            raise SystemExit(f"tools/agent_spec.py: {table} is not in tools/lakehouse_schema.json")
    return {
        "agent": {"name": spec.DATA_AGENT, "description": spec.AGENT_DESCRIPTION, "instructions": spec.AGENT_INSTRUCTIONS},
        "lakehouse": {"name": spec.LAKEHOUSE, "description": spec.LAKEHOUSE_DESCRIPTION,
                      "instructions": spec.LAKEHOUSE_INSTRUCTIONS, "tables": spec.LAKEHOUSE_TABLES,
                      "examples": [{"id": qid, "question": questions[qid], "query": sql} for qid, sql in spec.TSQL_EXAMPLES.items()]},
        "kql": {"name": spec.KQL_DATABASE, "description": spec.KQL_DESCRIPTION, "instructions": spec.KQL_INSTRUCTIONS,
                "tables": spec.KQL_TABLES,
                "examples": [{"question": q, "query": kql} for q, kql in spec.KQL_EXAMPLES.items()]},
        "ontology": spec.ONTOLOGY,
        "test": {"setupSql": bank.SETUP_SQL, "criticPrompt": spec.CRITIC_PROMPT,
                 "questions": [{"id": q["id"], "question": q["question"], "sql": q["sql"].strip(),
                                "kind": "example" if q["id"] in spec.TSQL_EXAMPLES else "no example"} for q in bank.QUESTIONS]
                              + variations(),
                 "live": [{"id": q["id"], "question": q["question"]} for q in bank.LIVE_QUESTIONS],
                 "unanswerable": [{"id": i, "question": q, "expected": a} for i, q, a in spec.UNANSWERABLE]},
    }


def examples_sql(a: dict) -> str:
    out = ["-- Example queries of the data agent for the Lakehouse (T-SQL, SQL analytics endpoint).",
           "-- Generated by tools/build-phase3.py from tools/agent_spec.py. Notebook 09 adds them to the agent.",
           "-- To add one by hand: data agent, Example queries, the Lakehouse, Add: paste the question and the query.", ""]
    for ex in a["lakehouse"]["examples"]:
        out += [f"-- {ex['id']}  {ex['question']}", ex["query"] + ";", ""]
    return "\n".join(out)


def examples_kql(a: dict) -> str:
    out = ["// ============================================================================",
           "// 93-data-agent-examples.kql : the example queries of the data agent for the KQL database.",
           "// Generated by tools/build-phase3.py from tools/agent_spec.py. Notebook 09 adds them to the agent.",
           "// Run one at a time in a query window on the KQL database to see what the agent learns from.",
           "// ============================================================================", ""]
    for ex in a["kql"]["examples"]:
        out += [f"// {ex['question']}", ex["query"], ""]
    return "\n".join(out)


NB09 = [
    ("markdown", f"""# 09 Build the data agent

Creates the data agent **{spec.DATA_AGENT}** and publishes it. Run all cells. Run it again after a change of the
instructions or the example queries: it keeps the agent and replaces both.

1. Runs every example query against the data first. A query that fails is left out and listed.
2. Creates the agent, sets its instructions, adds the Lakehouse and the KQL database, selects the tables,
   sets the instructions and the example queries of each source.
3. Publishes the agent.

Attach the Lakehouse `{spec.LAKEHOUSE}` as the default Lakehouse before you run it. The workspace must be on a paid
capacity (F2 or higher); a trial capacity does not run data agents."""),
    ("code", f"%pip install -q {spec.SDK_PIN} {spec.LABS_PIN}"),
    ("code", GENERATED + "\nimport json\n\nSPEC = json.loads(r'''" + "__AGENT__" + "''')"),
    ("code", """import time

import sempy.fabric as fabric

AGENT = SPEC["agent"]["name"]
LAKEHOUSE = SPEC["lakehouse"]["name"]
KQL_DATABASE = SPEC["kql"]["name"]
ATTACH_ONTOLOGY = False     # step 7 of the guide: set to True after notebook 11, then run this notebook again
VALIDATE_KQL = True         # False adds the KQL examples without running them first

workspace_id = fabric.get_notebook_workspace_id()
items = fabric.list_items()


def item_id(name, kind):
    found = items[(items["Display Name"] == name) & (items["Type"] == kind)]
    if len(found) != 1:
        raise RuntimeError(f"Expected one {kind} named {name} in this workspace, found {len(found)}.")
    return str(found["Id"].iloc[0])


lakehouse_id = item_id(LAKEHOUSE, "Lakehouse")
kql_id = item_id(KQL_DATABASE, "KQLDatabase")
print("workspace", workspace_id, "| lakehouse", lakehouse_id, "| KQL database", kql_id)"""),
    ("markdown", """## 1. Run the example queries

An example that fails teaches the agent a mistake. Each one runs here first: the T-SQL examples on the SQL
analytics endpoint of the Lakehouse, the KQL examples on the KQL database."""),
    ("code", """from sempy_labs import ConnectLakehouse

good_sql, good_kql, failed = {}, {}, []
with ConnectLakehouse(lakehouse=LAKEHOUSE) as endpoint:
    for example in SPEC["lakehouse"]["examples"]:
        try:
            result = endpoint.query(example["query"])
            rows = 0 if result is None else len(result)
            good_sql[example["question"]] = example["query"]
            print(f"PASS  {example['id']}  {rows} rows")
        except Exception as error:                      # the endpoint's message says what it did not accept
            failed.append(example["id"])
            print(f"FAIL  {example['id']}  {str(error)[:300]}")

if VALIDATE_KQL:
    databases = fabric.FabricRestClient().get(f"v1/workspaces/{workspace_id}/kqlDatabases").json()["value"]
    query_uri = next(d["properties"]["queryServiceUri"] for d in databases if d["id"] == kql_id)
    token = notebookutils.credentials.getToken(query_uri)
    for number, example in enumerate(SPEC["kql"]["examples"], start=1):
        try:
            rows = (spark.read.format("com.microsoft.kusto.spark.synapse.datasource")
                    .option("accessToken", token).option("kustoCluster", query_uri)
                    .option("kustoDatabase", KQL_DATABASE).option("kustoQuery", example["query"]).load().count())
            good_kql[example["question"]] = example["query"]
            print(f"PASS  KQL-{number}  {rows} rows")
        except Exception as error:
            failed.append(f"KQL-{number}")
            print(f"FAIL  KQL-{number}  {str(error)[:300]}")
else:
    good_kql = {example["question"]: example["query"] for example in SPEC["kql"]["examples"]}

print(f"\\n{len(good_sql)} T-SQL and {len(good_kql)} KQL examples go into the agent." + (f" Left out: {failed}" if failed else ""))"""),
    ("markdown", """## 2. Create and configure the agent"""),
    ("code", """from fabric.dataagent.client import create_data_agent, get_data_agent

agent = create_data_agent(AGENT)                       # returns the existing agent if there is one
agent.update_settings(ai_instructions=SPEC["agent"]["instructions"])


def source_of(item):
    \"\"\"The data source of the agent that points at this item, or None.\"\"\"
    for source in agent.list_datasources():
        if item in json.dumps(source.get_configuration(), default=str):
            return source
    return None


def add_source(name, kind, item):
    if source_of(item) is None:
        agent.add_staging_datasource(name, type=kind)
    for _ in range(60):                                # adding a source is a background operation
        source = source_of(item)
        if source is not None:
            return source
        time.sleep(5)
    raise RuntimeError(f"{name} did not appear among the data sources of the agent within 5 minutes.")


def children(source, parent=None):
    found, token = [], None
    while True:
        page = source.get_elements(root_id=parent, continuation_token=token)
        found += (page.get("value") or page.get("elements") or []) if isinstance(page, dict) else list(page)
        token = page.get("continuationToken") if isinstance(page, dict) else None
        if not token:
            return found


def label(element):
    return element.get("displayName") or element.get("name") or ""


def select_tables(source, wanted):
    \"\"\"Select the wanted tables and unselect the others. Returns the names it selected.\"\"\"
    level = children(source)
    for _ in range(4):                                 # the tables are one to three levels below the source
        names = {label(e) for e in level}
        if names & set(wanted):
            for element in level:
                source.update_element(element["id"], is_selected=label(element) in wanted)
            return sorted(names & set(wanted))
        level = [child for element in level for child in children(source, element["id"])]
    return []


def configure(name, kind, item, part, examples):
    source = add_source(name, kind, item)
    source.update_configuration(instructions=part["instructions"], description=part["description"])
    try:
        selected = select_tables(source, part["tables"])
    except Exception as error:
        selected = []
        print(f"  could not select tables: {str(error)[:300]}")
    missing = sorted(set(part["tables"]) - set(selected))
    print(f"{name}: selected {len(selected)} of {len(part['tables'])} tables" + (f". SELECT BY HAND: {missing}" if missing else ""))
    try:                                               # replace the examples of an earlier run
        source.delete_all_fewshots()
    except Exception as error:                         # Fabric answers 404 "No fewshots" when there are none yet
        if "No fewshots" not in str(error) and "EntityNotFound" not in str(error):
            raise
    source.add_fewshots(examples)
    print(f"{name}: {len(examples)} example queries")
    return source


configure(LAKEHOUSE, "lakehouse", lakehouse_id, SPEC["lakehouse"], good_sql)
configure(KQL_DATABASE, "kqldatabase", kql_id, SPEC["kql"], good_kql)

attached = agent.list_ontologies()
if ATTACH_ONTOLOGY and not attached:
    print("ontology attached:", agent.add_staging_ontology(SPEC["ontology"]))
elif ATTACH_ONTOLOGY:
    print("ontology: already attached")
else:                                                  # the switch is off: take an attached ontology away again
    for ontology in attached:
        agent.delete_staging_ontology(getattr(ontology, "_id", None) or ontology.id)
    print("ontology:", f"removed {len(attached)}" if attached else "none attached")"""),
    ("markdown", """## 3. Publish

If the cell above printed `SELECT BY HAND`, open the agent in the workspace first, tick those tables under the data
source, and then run this cell."""),
    ("code", """agent.publish_staging(description=SPEC["agent"]["description"])
agent_id = get_data_agent(AGENT)["id"]
print(f"Published: {AGENT}")
print(f"Agent id : {agent_id}")
print(f"MCP      : https://api.fabric.microsoft.com/v1/mcp/workspaces/{workspace_id}/dataagents/{agent_id}/agent")
print("Sources  :", len(agent.list_datasources(stage="published")))"""),
    ("markdown", """## 4. What the published agent holds

Read back from Fabric, not from this notebook: the length of the instructions, the example queries of each source and
whether an ontology is attached. Send these lines with every test result; a test says little without them."""),
    ("code", """published = json.dumps(agent.get_settings(stage="published"))
lines = [line.strip() for line in SPEC["agent"]["instructions"].splitlines() if line.strip()]
missing = [line for line in lines if json.dumps(line)[1:-1] not in published]
print(f"instructions: {len(lines) - len(missing)} of {len(lines)} lines of this notebook are in the published agent"
      + (f". MISSING, for example: {missing[0][:80]}" if missing else ""))
for source in agent.list_datasources(stage="published"):
    configuration = json.dumps(source.get_configuration(stage="published"))
    name = LAKEHOUSE if lakehouse_id in configuration else KQL_DATABASE if kql_id in configuration else "another source"
    examples = source.get_fewshots(stage="published")
    states = {k: int(v) for k, v in examples["validationStatus"].astype(str).value_counts().items()} if "validationStatus" in examples.columns else {}
    part = SPEC["lakehouse"] if name == LAKEHOUSE else SPEC["kql"]
    stale = [line.strip() for line in part["instructions"].splitlines() if line.strip() and json.dumps(line.strip())[1:-1] not in configuration]
    print(f"{name}: {len(examples)} example queries {states}; instructions " + ("current" if not stale else f"NOT CURRENT, {len(stale)} lines missing"))
print("ontology attached:", len(agent.list_ontologies(stage="published")))"""),
]

NB10 = [
    ("markdown", f"""# 10 Test the data agent

Asks the published agent **{spec.DATA_AGENT}** the questions of the question bank and compares each answer with the
result of the reference query of that question. Run all cells; the test takes about 10 minutes.

- {len(spec.TSQL_EXAMPLES)} questions that are example queries of the agent. They show that the agent finds and uses its examples.
- {len(spec.VARIATIONS)} variations: a question of the bank with another turbine, period or component. They show whether the
  agent can adapt an example, which is what a real user asks for.
- {len(bank.QUESTIONS) - len(spec.TSQL_EXAMPLES)} questions of the bank without an example. They show what the instructions alone carry.
- {len(spec.UNANSWERABLE)} questions the data cannot answer. The right answer is to say so.
- {len(bank.LIVE_QUESTIONS)} live questions. Their answers change every second, so they are printed for you to read, not scored.

The verdict on each answer comes from a language model, the judge of the SDK. Read the failed ones: a failure can be
a wrong answer, or a right answer in other words. Attach the Lakehouse `{spec.LAKEHOUSE}` as the default Lakehouse."""),
    ("code", f"%pip install -q {spec.SDK_PIN} {spec.LABS_PIN}"),
    ("code", GENERATED + "\nimport json\n\nSPEC = json.loads(r'''" + "__AGENT__" + "''')"),
    ("markdown", """## 1. One question first

If this cell fails, the agent is not published or the capacity does not run it. Fix that before the long test."""),
    ("code", """from fabric.dataagent.client import FabricOpenAIResponses

AGENT = SPEC["agent"]["name"]
client = FabricOpenAIResponses(artifact_name=AGENT, ai_skill_stage="production")
answer = client.responses.create(input="Which spare parts are at or below their reorder point?")
print(answer.output_text)"""),
    ("markdown", """## 2. The expected answers

The reference query of each question runs here, in Spark, on the same tables the agent reads."""),
    ("code", """import pandas as pd

spark.sql(SPEC["test"]["setupSql"])
rows = []
for q in SPEC["test"]["questions"]:
    result = spark.sql(q["sql"]).limit(15).toPandas()
    rows.append({"id": q["id"], "kind": q["kind"], "question": q["question"],
                 "expected_answer": "The answer must agree with this result of the reference query (first rows):\\n"
                                    + result.to_csv(index=False, float_format="%.6g")})
for q in SPEC["test"]["unanswerable"]:
    rows.append({"id": q["id"], "kind": "not in the data", "question": q["question"],
                 "expected_answer": "The agent must say that it cannot answer this from the data. " + q["expected"]
                                    + " An answer with a number is wrong."})
questions = pd.DataFrame(rows)
print(len(questions), "questions")"""),
    ("markdown", """## 3. Ask and judge"""),
    ("code", """from fabric.dataagent.evaluation import evaluate_data_agent, get_evaluation_details, get_evaluation_summary

TABLE = "agent_evaluation"          # results are appended to this table of the default Lakehouse
evaluation_id = evaluate_data_agent(questions[["question", "expected_answer"]], AGENT, table_name=TABLE,
                                    critic_prompt=SPEC["test"]["criticPrompt"], data_agent_stage="production", max_workers=3)
print("evaluation", evaluation_id)
summary = get_evaluation_summary(TABLE)
display(summary)"""),
    ("markdown", """The judge is a language model and makes mistakes in both directions. The next cell adds a second opinion that
needs no model: of the figures, dates and identifiers in the first five rows of the reference result, how many does
the answer contain? It cannot tell a wrong figure among right ones, and an answer may rightly show fewer columns, so
it is not a verdict. It is there to point at the verdicts worth reading: a `FAIL` with most figures present, or a
`PASS` with almost none."""),
    ("code", """import csv
import io
import re


def figures_found(expected, answer, rows=5):
    body = expected.split("(first rows):", 1)
    if len(body) < 2:
        return None                                   # a question the data cannot answer has no reference result
    numbers, tokens = [], []
    for row in list(csv.reader(io.StringIO(body[1].strip())))[1:rows + 1]:
        for cell in row:
            cell = cell.strip()
            try:
                value = float(cell)
            except ValueError:
                if any(ch.isdigit() for ch in cell) and len(cell) <= 20:
                    tokens.append(cell)               # an identifier or a date: WT-07, WO-2026-0121, 2026-10
                continue
            decimals = len(cell.split(".")[1]) if "." in cell and "e" not in cell.lower() else 0
            if abs(value) >= 3 or decimals:           # 0, 1 and 2 turn up in any text by chance
                numbers.append((value, max(1.5 * 10 ** -decimals, 0.005 * abs(value) if abs(value) >= 10 else 0)))
    if not numbers and not tokens:
        return None
    text = str(answer).replace("\u2011", "-").replace("\u2010", "-").replace("\u2212", "-")
    given = [float(n.replace(",", "")) for n in re.findall(r"(?<![\\w-])-?\\d[\\d,]*\\.?\\d*", text) if n.replace(",", "").strip("-.")]
    given += [-g for g in given]                      # "4.2 below" for -4.2
    hits = sum(any(abs(g - value) <= tolerance for g in given) for value, tolerance in numbers)
    hits += sum(token in text for token in tokens)
    return hits / (len(numbers) + len(tokens))"""),
    ("code", """details = get_evaluation_details(evaluation_id, TABLE, get_all_rows=True)
display(details)

# One line per question, to copy into the validation log.
merged = questions.merge(details[["question", "evaluation_judgement", "actual_answer"]], on="question", how="left")
verdicts = {True: "PASS", False: "FAIL"}
merged["figures"] = [figures_found(e, a) for e, a in zip(merged["expected_answer"], merged["actual_answer"])]
merged["group"] = merged["kind"].str.replace(r" of .*", "", regex=True)
merged["passed"] = merged["evaluation_judgement"] == True                # noqa: E712
share = lambda f: "      " if f is None or f != f else f"{100 * f:5.0f}%"   # noqa: E731
for _, row in merged.iterrows():
    print(f"{verdicts.get(row['evaluation_judgement'], 'UNCLEAR'):7} {row['id']:6} figures {share(row['figures'])}  {row['kind']}")
print()
for group, part in merged.groupby("group", sort=False):
    print(f"{group:16} {int(part['passed'].sum()):2} of {len(part)}")
print(f"{'all':16} {int(merged['passed'].sum()):2} of {len(merged)}")
doubt_fail = merged[~merged["passed"] & (merged["figures"] >= 0.7)]["id"].tolist()
doubt_pass = merged[merged["passed"] & (merged["figures"] <= 0.2)]["id"].tolist()
print(f"\\nFAIL although most reference figures are in the answer (read these): {doubt_fail}")
print(f"PASS although almost none are (read these): {doubt_pass}")"""),
    ("markdown", """The answers that did not pass, next to what was expected. Read them before you trust a `FAIL`."""),
    ("code", """expected = questions.set_index("id")["expected_answer"]
for _, row in merged[merged["evaluation_judgement"] != True].iterrows():          # noqa: E712
    print(f"=== {row['id']}  {row['kind']}  {row['question']}")
    print("AGENT   :", " ".join(str(row["actual_answer"]).split())[:600])
    print("EXPECTED:", " ".join(str(expected[row["id"]]).split())[:350], "\\n")"""),
    ("markdown", """## 4. Live questions

Compare each answer with the same question in `fabric/kql/92-question-bank-live.kql`, run at the same moment."""),
    ("code", """for q in SPEC["test"]["live"]:
    reply = client.responses.create(input=q["question"])
    print(f"--- {q['id']}  {q['question']}\\n{reply.output_text}\\n")"""),
]

NB11 = [
    ("markdown", f"""# 11 Build the ontology

Creates the ontology **{spec.ONTOLOGY}**: {len(spec.ENTITIES)} entity types bound to tables of the Lakehouse `{spec.LAKEHOUSE}`,
{len(spec.RELATIONSHIPS)} relationship types, and the live signals of the turbine from the KQL database `{spec.KQL_DATABASE}`.
`docs/10-ontology.md` lists all of it. Run all cells. Run it again after a change: it keeps the ontology and replaces
its definition.

The notebook sends the definition of the ontology to Fabric (the item definition interface, in preview). It checks the
tables first, because three things make an ontology unreadable: a column that is missing, a column name with a space,
and Delta column mapping. Attach the Lakehouse `{spec.LAKEHOUSE}` as the default Lakehouse."""),
    ("code", GENERATED + "\nimport json\n\nSPEC = json.loads(r'''" + "__ONTOLOGY__" + "''')"),
    ("code", """import base64
import time

import sempy.fabric as fabric

ONTOLOGY = SPEC["name"]
LAKEHOUSE_SCHEMA = "dbo"       # None leaves the schema out of the bindings
BIND_TELEMETRY = True          # False creates the ontology without the live signals of the turbine

client = fabric.FabricRestClient()
workspace_id = fabric.get_notebook_workspace_id()
items = fabric.list_items()


def item_id(name, kind, required=True):
    found = items[(items["Display Name"] == name) & (items["Type"] == kind)]
    if len(found) == 1:
        return str(found["Id"].iloc[0])
    if required or len(found) > 1:
        raise RuntimeError(f"Expected one {kind} named {name} in this workspace, found {len(found)}.")
    return None


lakehouse_id = item_id(SPEC["lakehouse"], "Lakehouse")
kql_id = item_id(SPEC["kqlDatabase"], "KQLDatabase")
kql = next(d for d in client.get(f"v1/workspaces/{workspace_id}/kqlDatabases").json()["value"] if d["id"] == kql_id)
eventhouse_id = kql["properties"]["parentEventhouseItemId"]     # the bindings want the Eventhouse, not the database
cluster_uri = kql["properties"]["queryServiceUri"]
print("lakehouse", lakehouse_id, "| eventhouse", eventhouse_id, "|", cluster_uri)"""),
    ("markdown", """## 1. Check the tables"""),
    ("code", """problems = []
needed = {}
for entity in SPEC["entities"]:
    needed.setdefault(entity["table"], set()).update(p["column"] for p in entity["properties"])
for relationship in SPEC["relationships"]:
    needed.setdefault(relationship["table"], set()).update([relationship["sourceColumn"], relationship["targetColumn"]])
for table, columns in sorted(needed.items()):
    if not spark.catalog.tableExists(table):
        problems.append(f"{table}: the table is missing")
        continue
    present = set(spark.table(table).columns)
    problems += [f"{table}: column {c} is missing" for c in sorted(columns - present)]
    problems += [f"{table}: column name '{c}' has a character the ontology cannot read" for c in sorted(present)
                 if any(ch in c for ch in " ,;{}()\\n\\t=")]
    properties = {r["key"]: r["value"] for r in spark.sql(f"SHOW TBLPROPERTIES {table}").collect()}
    if properties.get("delta.columnMapping.mode", "none") != "none":
        problems.append(f"{table}: Delta column mapping is on ({properties['delta.columnMapping.mode']})")
print("\\n".join(problems) if problems else f"{len(needed)} tables checked: all columns present, no column mapping.")
if problems:
    raise RuntimeError("Fix the tables above first (notebooks 01 and 02 create them).")"""),
    ("markdown", """## 2. Build the definition"""),
    ("code", """def part(path, content):
    return {"path": path, "payload": base64.b64encode(json.dumps(content).encode()).decode(), "payloadType": "InlineBase64"}


def lakehouse_table(table):
    source = {"sourceType": "LakehouseTable", "workspaceId": workspace_id, "itemId": lakehouse_id, "sourceTableName": table}
    if LAKEHOUSE_SCHEMA:
        source["sourceSchema"] = LAKEHOUSE_SCHEMA
    return source


def property_json(p):
    return {"id": p["id"], "name": p["name"], "redefines": None, "baseTypeNamespaceType": None, "valueType": p["valueType"]}


parts = [part("definition.json", {})]
for entity in SPEC["entities"]:
    series = entity["timeseries"] if BIND_TELEMETRY else None
    folder = f"EntityTypes/{entity['id']}"
    parts.append(part(f"{folder}/definition.json", {
        "id": entity["id"], "namespace": "usertypes", "namespaceType": "Custom", "name": entity["name"],
        "baseEntityTypeId": None, "visibility": "Visible", "entityIdParts": [entity["keyPropertyId"]],
        "displayNamePropertyId": entity["displayPropertyId"],
        "properties": [property_json(p) for p in entity["properties"]],
        "timeseriesProperties": [property_json(p) for p in series["properties"]] if series else []}))
    parts.append(part(f"{folder}/DataBindings/{entity['bindingId']}.json", {
        "id": entity["bindingId"],
        "dataBindingConfiguration": {
            "dataBindingType": "NonTimeSeries",
            "propertyBindings": [{"sourceColumnName": p["column"], "targetPropertyId": p["id"]} for p in entity["properties"]],
            "sourceTableProperties": lakehouse_table(entity["table"])}}))
    if series:
        parts.append(part(f"{folder}/DataBindings/{series['bindingId']}.json", {
            "id": series["bindingId"],
            "dataBindingConfiguration": {
                "dataBindingType": "TimeSeries", "timestampColumnName": series["timestampColumn"],
                "propertyBindings": [{"sourceColumnName": p["column"], "targetPropertyId": p["id"]} for p in series["properties"]]
                                    + [{"sourceColumnName": series["keyColumn"], "targetPropertyId": entity["keyPropertyId"]}],
                "sourceTableProperties": {"sourceType": "KustoTable", "workspaceId": workspace_id, "itemId": eventhouse_id,
                                          "clusterUri": cluster_uri, "databaseName": SPEC["kqlDatabase"],
                                          "sourceTableName": series["table"]}}}))
for r in SPEC["relationships"]:
    folder = f"RelationshipTypes/{r['id']}"
    parts.append(part(f"{folder}/definition.json", {
        "namespace": "usertypes", "id": r["id"], "name": r["name"], "namespaceType": "Custom",
        "source": {"entityTypeId": r["sourceEntityId"]}, "target": {"entityTypeId": r["targetEntityId"]}}))
    parts.append(part(f"{folder}/Contextualizations/{r['contextualizationId']}.json", {
        "id": r["contextualizationId"], "dataBindingTable": lakehouse_table(r["table"]),
        "sourceKeyRefBindings": [{"sourceColumnName": r["sourceColumn"], "targetPropertyId": r["sourceKeyPropertyId"]}],
        "targetKeyRefBindings": [{"sourceColumnName": r["targetColumn"], "targetPropertyId": r["targetKeyPropertyId"]}]}))
print(len(parts), "parts:", len(SPEC["entities"]), "entity types,", len(SPEC["relationships"]), "relationship types")"""),
    ("markdown", """## 3. Create or update the ontology

Creating and updating run in the background in Fabric. The cell waits for the result and prints it; a failure prints
the message of Fabric, which names the part it did not accept."""),
    ("code", """def wait(response, what):
    if response.status_code in (200, 201):
        print(what, "done.")
        return
    if response.status_code != 202:
        raise RuntimeError(f"{what} failed: {response.status_code} {response.text[:1500]}")
    operation = response.headers.get("x-ms-operation-id")
    for _ in range(120):
        state = client.get(f"v1/operations/{operation}").json()
        if state.get("status") == "Succeeded":
            print(what, "done.")
            return
        if state.get("status") == "Failed":
            raise RuntimeError(f"{what} failed: {json.dumps(state.get('error', state))[:3000]}")
        time.sleep(5)
    raise RuntimeError(f"{what} is still running after 10 minutes: operation {operation}")


existing = item_id(ONTOLOGY, "Ontology", required=False)
if existing is None:
    platform = part(".platform", {"metadata": {"type": "Ontology", "displayName": ONTOLOGY}})
    wait(client.post(f"v1/workspaces/{workspace_id}/items",
                     json={"displayName": ONTOLOGY, "type": "Ontology", "definition": {"parts": [platform] + parts}}),
         f"Creating {ONTOLOGY}")
else:
    wait(client.post(f"v1/workspaces/{workspace_id}/items/{existing}/updateDefinition", json={"definition": {"parts": parts}}),
         f"Updating {ONTOLOGY}")

items = fabric.list_items()
print("Ontology item:", item_id(ONTOLOGY, "Ontology"))
print("Open it in the workspace. The graph of the ontology fills in the background; this takes a few minutes.")"""),
]


def fill(cells, replace):
    done = []
    for kind, source in cells:
        for key, value in replace.items():
            source = source.replace(key, value)
        done.append((kind, source))
    return done


def main(argv) -> int:
    agent = agent_spec_json()
    ontology = ontology_spec()
    agent_json = json.dumps(agent, indent=1, ensure_ascii=False)
    ontology_json = json.dumps(ontology, indent=1, ensure_ascii=False)
    if "'''" in agent_json or "'''" in ontology_json:
        raise SystemExit("three single quotes in a row cannot go into the notebooks")
    notebooks, agent_dir, ops_dir = ROOT / "fabric" / "notebooks", ROOT / "fabric" / "data-agent", ROOT / "fabric" / "operations-agent"
    files = {
        notebooks / "09_build_data_agent.ipynb": phase2.render("09", fill(NB09, {"__AGENT__": agent_json})),
        notebooks / "10_test_data_agent.ipynb": phase2.render("10", fill(NB10, {"__AGENT__": agent_json})),
        notebooks / "11_build_ontology.ipynb": phase2.render("11", fill(NB11, {"__ONTOLOGY__": ontology_json})),
        agent_dir / "agent-spec.json": agent_json + "\n",
        agent_dir / "agent-instructions.txt": spec.AGENT_INSTRUCTIONS,
        agent_dir / "lakehouse-description.txt": spec.LAKEHOUSE_DESCRIPTION + "\n",
        agent_dir / "lakehouse-instructions.txt": spec.LAKEHOUSE_INSTRUCTIONS,
        agent_dir / "kql-description.txt": spec.KQL_DESCRIPTION + "\n",
        agent_dir / "kql-instructions.txt": spec.KQL_INSTRUCTIONS,
        agent_dir / "example-queries-lakehouse.sql": examples_sql(agent),
        ROOT / "fabric" / "kql" / "93-data-agent-examples.kql": examples_kql(agent),
        ROOT / "fabric" / "ontology" / "ontology-spec.json": ontology_json + "\n",
        ROOT / "docs" / "10-ontology.md": ontology_doc(ontology),
        ops_dir / "agent-setup.txt": "*** Business Goals ***\n" + spec.OPS_GOALS + "\n\n" + spec.OPS_INSTRUCTIONS,
        ops_dir / "business-goals.txt": spec.OPS_GOALS + "\n",
        ops_dir / "agent-instructions.txt": spec.OPS_INSTRUCTIONS,
        ops_dir / "optional-rule-4.txt": spec.OPS_RULE_4 + "\n",
    }
    stale = []
    for path, text in files.items():
        if "--check" in argv:
            if not path.is_file() or path.read_text(encoding="utf-8") != text:
                stale.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print("out of date: " + ", ".join(stale) + ". Run: python3 tools/build-phase3.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
