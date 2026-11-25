# Deployment guide, Phase 2: prepared data, semantic model and report

Phase 2 turns the data of Phase 1 into something people and agents can ask: tables shaped for analysis, a semantic model with the site's measures, a test that the measures are right, and a small report.

**Status of this guide.** It was run once, on 20 November 2026, directly after it was written. That run met three obstacles in notebooks 06 and 07, all fixed in this version; [phase2-validation-log.md](phase2-validation-log.md) lists them. The user reported the guide as done; the outputs of the acceptance test and of the report notebook were not sent, so the table in [What was and was not tested](#what-was-and-was-not-tested) marks those two as reported, not as seen.

## Contents

- [What you get](#what-you-get)
- [Before you start](#before-you-start)
- [Step 1: Prepared views in the Eventhouse](#step-1-prepared-views-in-the-eventhouse)
- [Step 2: Import the notebooks](#step-2-import-the-notebooks)
- [Step 3: Build the model tables](#step-3-build-the-model-tables)
- [Step 4: Build the semantic model](#step-4-build-the-semantic-model)
- [Step 5: Test the model](#step-5-test-the-model)
- [Step 6: Build the report](#step-6-build-the-report)
- [Step 7: Keep it current](#step-7-keep-it-current)
- [Design decisions](#design-decisions)
- [What was and was not tested](#what-was-and-was-not-tested)
- [If something fails](#if-something-fails)

## What you get

| Item | Where | What it is |
|---|---|---|
| `Scada10Min()`, `AlarmIntervals()`, `GearboxVsFleet()` | Eventhouse `WindFarmEH` | Live data in the shape of the history: 10-minute periods with availability category, loss cause and lost energy; alarms as intervals; each gearbox against the fleet |
| 12 tables, `dim_` and `fact_` | Lakehouse `WindFarmLH` | A star schema. `fact_scada_10min` is one continuous series: the generated history, with the live telemetry on top |
| Semantic model **WindFarm Operations** | Workspace | Direct Lake on OneLake, 12 relationships, 39 measures. [08-semantic-model.md](08-semantic-model.md) lists them with their DAX |
| Report **WindFarm Operations Report** | Workspace | Three pages: site overview, turbine health, money and market |

## Before you start

- Phase 1 is deployed and notebooks `01_load_reference_data` and `02_generate_history` have run.
- The workspace is on a Fabric capacity. A trial capacity is enough.
- You are an Admin or Member of the workspace.
- The archive of this version is unpacked on the computer where your browser runs.

Time: about 30 minutes.

## Step 1: Prepared views in the Eventhouse

**[Fabric]** Open the KQL database `WindFarmEH` and a query window. Paste `fabric/kql/04-prepared-views.kql` and run its four commands one at a time: select a command, then **Run**.

**Check.** The last command, `Scada10Min(3h) | summarize …`, lists the periods of the last three hours by availability category. With all turbines running you see mostly `Full performance`, about 18 periods per turbine.

This step is independent of the rest: the semantic model does not read these functions. They serve questions about the last hours that should not wait for the Lakehouse, and Phase 3 uses them for the data agent.

## Step 2: Import the notebooks

**[Fabric]**

1. In the workspace, select **Import**, **Notebook**, **From this computer** and upload these four files of `fabric/notebooks/`: `05_build_model_tables`, `06_build_semantic_model`, `07_model_acceptance`, `08_build_report`.
2. Open each one once, select **Add data items** in the explorer pane, add the Lakehouse `WindFarmLH` and make it the default Lakehouse.

## Step 3: Build the model tables

**[Fabric]** Open `05_build_model_tables` and select **Run all**. It takes two to four minutes.

**Check.** The notebook checks itself and stops with an error if the series has a hole or a duplicate. Read three things in its output:

| Output | Expected |
|---|---|
| `Live periods: … complete 10-minute periods from … to …` | The time since you deployed the simulator. If it says `No live telemetry in the Lakehouse`, the shortcut `TurbineTelemetry` is missing or still empty (Phase 1, step 7.3) |
| Row counts | `fact_scada_10min` about 1.19 million, `dim_turbine` 12, `dim_site` 1, `fact_monthly_budget` 24 |
| Last table | Rows with `Source` = `Live` from the first live period on. Periods in which the VM was stopped show as `Information unavailable` |

## Step 4: Build the semantic model

**[Fabric]** Open `06_build_semantic_model` and select **Run all**. The first cell installs the library `semantic-link-labs` for the session, which takes a minute or two.

The notebook creates the model, adds relationships and measures, and refreshes the model. Running it again keeps the model and replaces its relationships and measures. After a change of the tables or their columns, delete the model in the workspace first, then run the notebook.

**Check.** The last cell shows one row per year with energy, capacity factor, time availability and revenue. Expect a capacity factor of 33 to 37 percent and an availability of 96.5 to 98 percent for the full year 2025.

## Step 5: Test the model

**[Fabric]** Open `07_model_acceptance` and select **Run all**.

The notebook asks the model and the Lakehouse the same eleven questions and compares the answers: a DAX query with the model's measures against a Spark SQL query on the tables. The questions come from the question bank; the name of each check says which.

**Check.** Every line starts with `PASS`, and the notebook ends with `All checks passed`. A `FAIL` line names the columns that differ and shows both results side by side. Send that output if a check fails; a failing check means a measure or a relationship is wrong, which is for the repository to fix.

## Step 6: Build the report

**[Fabric]** Open `08_build_report` and select **Run all**. Then open **WindFarm Operations Report** from the workspace.

This is the least tested part: the notebook writes the report's definition file directly. If it fails, or the report opens with broken visuals, send the error and build the report by hand from this list; it takes about 15 minutes. In the workspace, select the semantic model, **Create report**, and add:

| Page | Visual | Fields |
|---|---|---|
| Site overview | Five cards | Energy MWh, Capacity Factor, Time Availability, Curtailment Share, Revenue USD |
| | Slicer | Date[Year] |
| | Clustered column chart | Date[YearMonth]; Energy MWh, Budget P50 MWh |
| | Clustered bar chart | Scada[LossCause]; Lost Energy MWh |
| | Line chart | Date[YearMonth]; Time Availability, Energy Availability |
| | Line chart | Date[YearMonth]; Capacity Factor, Wind Index |
| Turbine health | Slicer | Date[Year] |
| | Table | Turbine[TurbineId]; Energy MWh, Capacity Factor, Time Availability, Performance Index, Failures, MTTR Hours, Average Gearbox Bearing Temp, Average Gearbox Vibration |
| | Line chart | Date[YearMonth], legend Turbine[TurbineId]; Average Gearbox Bearing Temp |
| | Line chart | Date[YearMonth], legend Turbine[TurbineId]; Performance Index |
| Money and market | Five cards | Revenue USD, Budget Revenue USD, Repair Cost Paid by Owner USD, Captured Price USD per MWh, PM Compliance |
| | Slicer | Date[Year] |
| | Clustered column chart | Date[YearMonth]; Revenue USD, Budget Revenue USD |
| | Table | Curtailments[Reason], Curtailments[Compensation]; Deemed Generation MWh, Unpaid Curtailment MWh |
| | Line chart | Date[YearMonth]; Captured Price USD per MWh, Mean Real-Time Price USD per MWh |

**What to look for.** On **Turbine health**, WT-07's bearing temperature line runs above the others and has been climbing; WT-05 and WT-09 are at the bottom of the performance index. On **Site overview**, grid curtailment is the largest loss. These are the planted stories of the data audit.

## Step 7: Keep it current

The model shows what notebook 05 last wrote. To follow the live data:

1. Open `05_build_model_tables`, select **Run**, **Schedule**, and set it to once an hour.
2. The model picks up the new table versions by itself when its setting **Keep your Direct Lake data up to date** is on. To be sure after a manual run, run the last cell of notebook 06, or notebook 07, which refreshes before it tests.

Live data reaches the model with a delay: the Eventhouse writes to OneLake every few minutes, and notebook 05 uses complete 10-minute periods only. For the last minutes, ask the Eventhouse: `Scada10Min(1h)`.

Run notebook 02 again when you want the planted stories to be recent before a demo, then notebook 05. Live periods are kept: they replace generated ones wherever both exist.

## Design decisions

- **The live roll-up for the model is done in Spark, not in KQL.** The roadmap planned a KQL materialized view read through a shortcut. A notebook is simpler to run and test, and it writes plain Lakehouse tables. `Scada10Min()` in the Eventhouse has the same definitions for live questions. The two are written twice, in Spark SQL and in KQL, and nothing compares them automatically yet.
- **The model reads only Lakehouse tables.** Notebook 05 copies what it needs from the Eventhouse shortcuts. A reader of the model therefore needs no access to the Eventhouse, which settles the open question of Phase 1 about passthrough shortcuts for the model. It stays open for anything that reads the shortcuts directly.
- **Live data wins over generated data.** Where a complete live period exists, it replaces the generated one, also after notebook 02 has been run again.
- **Dates are UTC days**, as in the question bank. A day in the report is not a day on the site's clock, which is six or five hours behind.
- **Site figures.** Deemed generation and revenue come from the curtailment log, which has no turbine. They do not split by turbine; a table by turbine shows the site's value in every row.
- **The model definition is Python data**, `tools/model_spec.py`, from which the notebooks and [08-semantic-model.md](08-semantic-model.md) are generated. The roadmap named TMDL. Once the model exists in your workspace, Fabric can export it as TMDL through Git integration.
- **Contractual availability (question AM-03) is not a measure.** Its rules (exclusions by responsible party, the 80-hour allowance per turbine and contract year) are in the question bank's SQL and are left for Phase 3 to give to the data agent as a reference query.

## What was and was not tested

| Part | How it was tested |
|---|---|
| Notebook 05 | Ran in Fabric on 20 November 2026: notebook 06 found its twelve tables. Its check output was not sent. Before that, all code cells ran with `tools/local-spark/run_phase2.py` on Spark 3.5.1 with Python 3.11 and on Spark 4.1.4 with Python 3.13 and ANSI mode on: once with the history alone, once with stand-ins for the two Eventhouse shortcuts (three hours of telemetry with a fault, a curtailment and two silences). Checked: the columns of every table against the model definition, every relationship key, the hand-over from history to live, the fault, the curtailment and the silent periods. Parquet instead of Delta. |
| Notebook 07, Lakehouse side | The eleven SQL queries ran in both sessions and returned plausible values |
| Notebook 06 | Ran in Fabric on 20 November 2026 after two cells were corrected (obstacle 1). This version has the corrected cells; as a whole notebook it has not run again. |
| Notebook 07 | Ran in Fabric on 20 November 2026 after an install cell was added (obstacles 2 and 3). Reported as done by the user; the PASS and FAIL lines were not sent. Seven tests check that every measure, relationship, check and report field refers to tables, columns and measures that exist, and that the install cell comes first. |
| Notebook 08 | Reported as done by the user on 20 November 2026; whether the report opened with all visuals was not confirmed. The report definition is built in the legacy `report.json` layout; the test checks that its fields exist in the model and that its JSON is well formed. |
| `04-prepared-views.kql` | Parsed with the Kusto language service. Not run in an Eventhouse. |
| `semantic-link-labs` calls | Checked against the source code of release 0.15.2, which the notebooks pin: argument names of every call, and what the library does when the model or the report exists. The first delivery had taken them from the online documentation, which describes unreleased code. Not exercised outside Fabric. |

## If something fails

| Symptom | Likely cause | What to do |
|---|---|---|
| Notebook 05: `No live telemetry in the Lakehouse` | The shortcut `TurbineTelemetry` is missing or has no data yet | Phase 1, steps 7.2 and 7.3. The model works with the history alone |
| Notebook 05: assertion `periods are missing from the series` | A case the roll-up does not cover | Send the printed check line |
| Notebook 06: the `%pip` cell fails | The session has no way to the package index, or the pinned version is not offered for the runtime's Python | Send the error. Try `%pip install -q semantic-link-labs` without the version |
| Notebook 06: `TypeError: got an unexpected keyword argument` | The installed library differs from version 0.15.2, whose code the notebook was checked against | Check the output of the `%pip` cell. The first delivery of this notebook failed this way with `overwrite`, an argument that exists in the library's online documentation and not in the release ([phase2-validation-log.md](phase2-validation-log.md)) |
| Notebook 06: an error that mentions XMLA or read-only | The capacity's XMLA endpoint does not allow writing | In the capacity settings, set the XMLA endpoint to read-write, then run the notebook again |
| A notebook ends with `NameError` for a name that an earlier cell defines | A `%pip install` cell ran after that cell. It restarts the Python interpreter, and what was defined before is lost | Keep the `%pip` cell as the first code cell and select **Run all** |
| Notebook 07: `FAIL` | A measure or relationship is wrong | Send the line and the table below it |
| Notebook 08 fails, or visuals show an error | The report definition is not what Power BI expects | Send the error; build the report by hand from the table in step 6 |
| Notebook 08 prints that the report already exists | The library does not overwrite a report | Delete the report in the workspace and run the last cell again |
