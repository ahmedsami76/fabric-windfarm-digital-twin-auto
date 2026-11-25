# Fabric artifacts for Phase 1

Run in this order. The deployment guide, steps 6 and 7, has the details.

| Order | File | Where | What it does |
|---|---|---|---|
| 1 | `kql/01-tables.kql` | KQL database | Creates `RawEvents` and six typed tables, the ingestion mapping, retention and batching policies |
| 2 | `kql/02-update-policies.kql` | KQL database | Creates the functions and update policies that fill the typed tables, and three helper functions. Safe to run again. |
| 3 | `kql/90-validation-queries.kql` | KQL database | 18 checks, run one at a time |
| 4 | `kql/03-onelake-availability.kql` | KQL database | Exposes the typed tables in OneLake, 5 minutes behind |
| 5 | `notebooks/01_load_reference_data.ipynb` | Notebook with the Lakehouse as default | Loads reference files into 13 `ref_` tables |
| 6 | `notebooks/02_generate_history.ipynb` | Notebook | Creates 12 `ops_` tables with two years of operating history, ending at the time of the run |
| 7 | `notebooks/03_refresh_forecast.ipynb` | Notebook, scheduled daily | Adds new day-ahead forecasts and replaces the latest forecast in `ops_power_forecast` |
| 8 | `notebooks/04_question_bank.ipynb` | Notebook | Answers 39 questions of the site's staff from the Lakehouse |
| any time | `kql/92-question-bank-live.kql` | KQL database | The four questions that are answered from live data |
| any time | `kql/94-twin-app-queries.kql` | KQL database | The queries the twin of Phase 4 runs on its Eventhouse route |
| any time | `sql/94-twin-app-queries.sql` | SQL analytics endpoint of the Lakehouse | The same questions in T-SQL, which the twin runs on its Lakehouse route |
| as needed | `kql/91-repair-wizard-columns.kql` | KQL database | Removes the columns the Get data wizard adds when it is finished with its own mapping (see troubleshooting) |
| as needed | `kql/99-reset-demo-data.kql` | KQL database | Empties all tables |

The notebooks and `kql/92-question-bank-live.kql` are generated files. Their sources are `tools/build-notebooks.py`, `tools/question_bank.py` and three modules of the simulator package; change those and run `python3 tools/build-notebooks.py`.

Each script that starts with `.execute database script` is one block with no empty lines. Paste the whole file, place the cursor in the block and run it.

The eventstream and the shortcuts are created in the portal; the guide gives the steps.

To run the notebooks without Fabric after editing their sources (tables are then written as Parquet, not Delta):

```bash
pip install pyspark pandas numpy pyarrow tabulate
python3 tools/local-spark/run_notebooks.py
```

To check the KQL files offline after editing them: the first command reads the grammar, the second also knows the tables of the database, and finds a column that does not exist or a value of the wrong type.

```bash
npm install --no-save @kusto/language-service-next
node tools/kql-syntax-check.js fabric/kql/*.kql
node tools/kql-semantic-check.js fabric/kql/*.kql
```

## Phase 2

| File | What it is |
|---|---|
| `kql/04-prepared-views.kql` | `Scada10Min()`, `AlarmIntervals()`, `GearboxVsFleet()` |
| `notebooks/05_build_model_tables.ipynb` | Star schema in the Lakehouse; history and live telemetry as one 10-minute series |
| `notebooks/06_build_semantic_model.ipynb` | Creates the Direct Lake model **WindFarm Operations** with semantic-link-labs |
| `notebooks/07_model_acceptance.ipynb` | Compares the model's measures with Spark SQL on the Lakehouse |
| `notebooks/08_build_report.ipynb` | Creates the three-page report |
| `semantic-model/model-spec.json` | The model definition that notebook 06 carries, for reading |

Notebooks 05 to 08, `model-spec.json` and `docs/08-semantic-model.md` are generated. Change `tools/model_spec.py` or `tools/build-phase2.py`, then run `python3 tools/build-phase2.py`.

To run notebook 05 and the Lakehouse side of the acceptance checks locally, after notebooks 01 and 02 have run in the same stand-in folder:

```bash
python3 tools/local-spark/run_notebooks.py --lakehouse /tmp/lakehouse --only 01 02
python3 tools/local-spark/run_phase2.py --lakehouse /tmp/lakehouse
```

## Phase 3

| File | What it is |
|---|---|
| `notebooks/09_build_data_agent.ipynb` | Runs the example queries, creates and publishes the data agent **WindFarmDataAgent** |
| `notebooks/10_test_data_agent.ipynb` | Asks the agent the question bank and has each answer judged against the reference query |
| `notebooks/11_build_ontology.ipynb` | Creates the ontology **WindFarmOntology** from its definition |
| `notebooks/12_send_edge_command.ipynb` | Phase 5: sends one operating command to one turbine through the eventstream **WindFarmCommands**. By hand in 5a; as the action **Curtail turbine** of the operations agent in 5b. A caller can set four values (`turbine`, `percent`, `duration`, `requested_by`); the command is `curtail` and can be changed only by hand, in the second code cell. Built by `tools/build-phase5.py` from `tools/edge_command.py` |
| `notebooks/13_command_center.ipynb` | Phase 5: commands by hand in one place. One line per command, the turbines' state as a table, and after each send what became of it: the edge's own line from its command log (Phase 5c), then the telemetry, with the seconds. `history()` prints the log. For a person; the operations agent does not run it |
| `data-agent/` | What notebook 09 carries, for reading and for pasting by hand: instructions, descriptions, example queries, `agent-spec.json` |
| `ontology/ontology-spec.json` | The ontology that notebook 11 carries, with its identifiers |
| `operations-agent/` | Business goals and instructions to paste into the operations agent (Phase 3). For Phase 5b: `phase5b-agent-setup.txt`, the goals and instructions with the one rule that proposes a curtailment, and `phase5b-action.txt`, the action for adding it by hand. `bash infra/09-remediation-agent.sh` gives both to the agent through the Fabric API and keeps the agent's earlier definition under `operations-agent/saved/` |
| `kql/05-agent-readiness.kql` | Column descriptions for the operations agent; optional table `GearboxVsFleetLive` |
| `kql/06-remediation-readiness.kql` | Phase 5b: the table `GearboxDecisionLive` and its update policy. The gearbox readings of each running turbine with what limiting it would cost and what a gearbox costs |
| `kql/07-command-log.kql` | Phase 5c: the table `EdgeCommands`, which holds the edge's record of every operating command it was given, its update policy, and the function `CommandLog(lookback)`, which says for each command what the telemetry showed afterwards |
| `kql/93-data-agent-examples.kql` | The KQL example queries of the data agent |
| `kql/94-twin-app-queries.kql` | The queries the functions of the Phase 4 app run, to run by hand |

Everything in this table except `05-agent-readiness.kql` is generated. Change `tools/agent_spec.py` or `tools/build-phase3.py`, then run `python3 tools/build-phase3.py`. The files of Phase 5 come from `tools/edge_command.py` and `tools/remediation_spec.py` through `python3 tools/build-phase5.py`; the figures in them are read from `data/reference`.

To check the T-SQL example queries against the reference queries of the question bank, after notebooks 01 and 02 have run in a stand-in folder (needs `pip install sqlglot duckdb`):

```bash
python3 tools/check-tsql-examples.py --lakehouse /tmp/lakehouse
```
