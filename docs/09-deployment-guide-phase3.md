# Deployment guide, Phase 3: data agent, ontology and operations agent

Phase 3 lets people ask the wind farm questions in plain language, gives the data a vocabulary of business terms, and puts an agent on watch that tells the on-call engineer when a gearbox starts to go wrong.

**Status of this guide.** Regenerated on 21 November 2026 after its first deployment, on a paid capacity with Fabric Runtime 2.0. Steps 2 to 7 ran and I have seen their output; for steps 8 to 10 I have the user's word or less. Seven obstacles and one large finding about the data agent are worked into this version; [phase3-validation-log.md](phase3-validation-log.md) is the record, and [What was and was not tested](#what-was-and-was-not-tested) says exactly what was seen. All three features are in preview: Microsoft changes them often. When a step does not match what you see, send me the screen or the error.

## Contents

- [What you get](#what-you-get)
- [Before you start](#before-you-start)
- [Step 1: Capacity](#step-1-capacity)
- [Step 2: Tenant settings](#step-2-tenant-settings)
- [Step 3: Import the notebooks](#step-3-import-the-notebooks)
- [Step 4: Build the data agent](#step-4-build-the-data-agent)
- [Step 5: Test the data agent](#step-5-test-the-data-agent)
- [Step 6: Ontology](#step-6-ontology)
- [Step 7: Give the agent the ontology](#step-7-give-the-agent-the-ontology)
- [Step 8: Prepare the KQL database for the operations agent](#step-8-prepare-the-kql-database-for-the-operations-agent)
- [Step 9: Operations agent](#step-9-operations-agent)
- [Step 10: Show it](#step-10-show-it)
- [Design decisions](#design-decisions)
- [What was and was not tested](#what-was-and-was-not-tested)
- [If something fails](#if-something-fails)
- [Remove Phase 3](#remove-phase-3)

## What you get

| Item | Where | What it is |
|---|---|---|
| Data agent **WindFarmDataAgent** | Workspace | Answers questions from the Lakehouse (history, T-SQL) and the KQL database (live, KQL). Carries the site's definitions of availability, lost energy and capacity factor, 35 example queries for the Lakehouse and 6 for the KQL database |
| Test results, table `agent_evaluation` | Lakehouse `WindFarmLH` | The agent's answer to 52 questions, each judged against the result of the reference query |
| Ontology **WindFarmOntology** | Workspace | 10 entity types (site, turbine, component, work order, downtime event, alarm type, spare part, technician, procedure, contract), 12 relationship types, and the live signals of each turbine. [10-ontology.md](10-ontology.md) lists them |
| Operations agent **WindFarmGearboxWatch** | Workspace | Looks at the live telemetry every five minutes and sends a Teams message when a gearbox crosses an early-warning threshold, below the alarm of the turbine controller |
| Column descriptions, optional table `GearboxVsFleetLive` | KQL database `WindFarmEH` | What the operations agent needs to read the telemetry |

## Before you start

- Phases 1 and 2 are deployed. The simulator runs: the KQL database receives telemetry.
- You have a paid Fabric capacity, F2 or larger. A trial capacity runs neither the data agent nor the operations agent.
- You are an Admin of the workspace, and a Fabric administrator can change tenant settings (step 2).
- You have Microsoft Teams with the same account.
- The archive of this version is unpacked on the computer where your browser runs.
- If you merge an update archive into an existing copy, unpack it inside WSL: `python3 -m zipfile -e ARCHIVE.zip ~/fabric-windfarm-digital-twin-auto` (`unzip` is missing on a fresh Ubuntu). A merged copy has no execute permission on the script files. That does not matter as long as a script is started through `bash`, as every command in this guide is: `bash infra/vm.sh status`, not `./infra/vm.sh status`.

Time: about two hours, of which 30 to 40 minutes are waiting for notebooks.

Two things can stop this phase before it starts. Step 1 checks both.

| What | Why it matters |
|---|---|
| The paid capacity is in a different region than the trial capacity | Fabric does not move a workspace with Fabric items (Lakehouse, Eventhouse, eventstream) to a capacity in another region |
| The paid capacity is in East US | The operations agent is not available there. One walkthrough from April 2026 also lists South Central US; the Microsoft Learn page I read on 21 November 2026 lists only East US |

## Step 1: Capacity

**[Fabric]**

1. Open the **Admin portal** (gear icon), **Capacity settings**. Look at the tabs **Trial** and **Fabric capacity** and note the **Region** of the trial capacity the workspace is on and of your paid capacity.
2. If the regions are the same: open the workspace `WindFarmDigitalTwin`, **Workspace settings**, **Workspace type** (older tenants call it **License info**), choose **Fabric capacity**, select the paid capacity, **Apply**.
3. If the regions differ, choose one:
   - Create a paid capacity in the region of the trial capacity (Azure portal, **Microsoft Fabric**, **Create**; F2 is the smallest size that runs a data agent) and move the workspace to it as in point 2. Pause the capacity in the Azure portal when you do not use it: a paused capacity costs nothing, and nothing in the workspace works while it is paused.
   - Or create a new workspace on the existing paid capacity and repeat the Fabric steps of Phase 1 (steps 6 and 7 of its guide) and Phase 2 there. The Azure side stays as it is; only the data flow endpoint on the edge needs the connection details of the new eventstream. Count 60 to 90 minutes.

**Check.** After the move, open the KQL database and run `TurbineTelemetry | where Timestamp > ago(2m) | count`. A number above zero means the eventstream still delivers. Then open the report of Phase 2; it should show data.

## Step 2: Tenant settings

**[Fabric]** Admin portal, **Tenant settings**. Use the search box. A change can take up to an hour to take effect.

| Setting | Needed for | Notes |
|---|---|---|
| Users can use Copilot and other features powered by Azure OpenAI | Data agent, operations agent | On by default |
| Data sent to Azure OpenAI can be processed outside your capacity's geographic region, compliance boundary, or national cloud instance | Data agent, operations agent | Only if the capacity is outside the United States and the EU |
| Users can create and share Data agent item types (preview) | Data agent | Some tenants no longer show it; then it is on |
| Users can create Ontology (preview) items | Ontology | Also shown as "Enable Ontology item (preview)" |
| User can create Graph (preview) | Ontology | The ontology keeps its data in a graph. The label is singular; search for "Graph". Some tenants do not show this setting at all (seen on 21 November 2026). Then check the item instead: in the workspace, **New item**, search for "Graph". If **Graph model** is offered, nothing needs to be turned on |
| Enable Operations Agents (Preview) | Operations agent | Search for "Operations". Can also be set per capacity |

**Check.** In the workspace, **New item**: you can find **Data agent**, **Ontology** and **Operations agent**.

## Step 3: Import the notebooks

**[Fabric]**

1. In the workspace, select **Import**, **Notebook**, **From this computer** and upload these three files of `fabric/notebooks/`: `09_build_data_agent`, `10_test_data_agent`, `11_build_ontology`.
2. Open each one once, select **Add data items** in the explorer pane, add the Lakehouse `WindFarmLH` and make it the default Lakehouse.

Do not move or reorder cells. The first code cell of notebooks 09 and 10 installs libraries, which restarts Python: anything that ran before it is forgotten. That was obstacle 3 of Phase 2.

## Step 4: Build the data agent

**[Fabric]** Open `09_build_data_agent` and select **Run all**. The install takes two to three minutes.

What it does, in this order:

1. Runs each example query against the data: 35 in T-SQL on the SQL analytics endpoint of the Lakehouse, 6 in KQL on the KQL database. It prints `PASS` or `FAIL` per query. A query that fails is left out of the agent.
2. Creates the agent, sets its instructions, adds the Lakehouse and the KQL database, selects 22 tables of the Lakehouse and 4 of the KQL database, sets the description, the instructions and the example queries of each source.
3. Publishes the agent and prints its identifier and its MCP address.

**Check.**

| Output | Expected |
|---|---|
| Section 1 | 35 lines `PASS  SM-01 …` and 6 lines `PASS  KQL-…`, then `35 T-SQL and 6 KQL examples go into the agent.` |
| Section 2 | `WindFarmLH: selected 22 of 22 tables`, `WindFarmLH: 35 example queries`, `WindFarmEH: selected 4 of 4 tables`, `WindFarmEH: 6 example queries`, `ontology: none attached` |
| Section 3 | `Published: WindFarmDataAgent` and `Sources  : 2` |
| Section 4 | `instructions: 64 of 64 lines of this notebook are in the published agent`, two lines that end in `instructions current`, and `ontology attached: 0` |

This is the output of 21 November 2026. `KQL-2` passes with 0 rows when no alarm is active. The number of instruction lines changes when the instructions change; what matters is that none is missing.

Section 4 reads the agent back from Fabric, so it shows what the agent holds and not what the notebook meant to give it. Look at it before every test. On 21 November two test results were explained wrongly, by me, because nobody had looked: the agent had older instructions than I thought and an ontology attached that I did not know about.

A `FAIL` line in section 1 names an example query the endpoint did not accept. That example is left out and the rest goes on; send me the line.

If the notebook says `SELECT BY HAND`: open the agent in the workspace, expand the data source in the explorer on the left, tick the tables it lists (the full lists are in `fabric/data-agent/agent-spec.json` under `tables`), then run the last cell of the notebook to publish.

**Try it.** Open **WindFarmDataAgent** in the workspace and ask, one at a time:

- `What was the availability of each turbine over the last 90 days?` An example query exists for this one. Expect 12 rows, WT-01 to WT-12.
- `Which turbine lost the most energy to component faults in the last 12 months?` No example query; the agent has to work it out from the instructions.
- `What is every turbine doing right now?` Expect an answer from the KQL database with a time of a few seconds ago.

Select the query under an answer to see what the agent ran.

**By hand instead.** If the notebook cannot create the agent at all, create a **Data agent** named `WindFarmDataAgent`, add the two sources, tick the tables, and paste the files of `fabric/data-agent/`: `agent-instructions.txt` under **Agent instructions**; for each source its `…-description.txt` and `…-instructions.txt`; the example queries from `example-queries-lakehouse.sql` and `fabric/kql/93-data-agent-examples.kql`. Then **Publish**.

## Step 5: Test the data agent

**[Fabric]** Open `10_test_data_agent` and select **Run all**. A run took seven to eight minutes on 21 November 2026, with 42 questions and with 52.

1. Section 1 asks one question. If it fails, the agent is not published or the capacity does not run it; stop there.
2. Section 2 runs the reference query of each question in Spark, as notebook 04 does, and keeps the first rows as the expected answer.
3. Section 3 asks the agent the questions and has each answer judged by a language model, the judge that comes with the SDK, against the expected one. The notebook gives the judge its own brief: figures must agree within rounding; other wording, order or fewer columns are fine; a different period is not.
4. Section 4 asks the 4 live questions and prints the answers. They are not judged: the right answer changes every second.

The 52 questions are of four kinds, and the result is reported for each:

| Kind | Count | What it shows |
|---|---|---|
| `example` | 35 | The question is one of the agent's example queries. It shows that the agent finds its examples and uses them |
| `variation` | 10 | A question of the bank with another turbine, period or component, for example 30 days instead of 90. No example matches it exactly. This is what a real user asks |
| `no example` | 4 | Questions of the bank that have no example query |
| `not in the data` | 3 | The right answer is to say that the data does not record it |

**Before the test**, look at section 4 of notebook 09: it says which instructions, which examples and which ontology the published agent has.

**Check.** The cell after the test prints one line per question, the totals by kind, and two lists. This is the run of 21 November 2026 on the agent as this guide builds it:

```text
PASS    SM-01  figures    80%  example
FAIL    RE-04  figures    95%  example
PASS    VA-04  figures   100%  variation of RE-06
…
example          27 of 35
no example        2 of 4
variation         8 of 10
not in the data   2 of 3
all              39 of 52

FAIL although most reference figures are in the answer (read these): ['PE-06', 'RE-03', 'RE-04', 'AM-06']
PASS although almost none are (read these): ['OP-04']
```

`figures` is a second opinion that uses no language model: the share of the figures, dates and identifiers in the first five rows of the reference result that the answer contains. It cannot see one wrong figure among right ones, and an answer may rightly show fewer columns, so it is not a verdict. It points at the verdicts worth reading. The next cell prints every answer that did not pass next to what was expected.

**How to read the result.** Six runs on 21 November 2026 gave 18 of 42, then 40, 32, 32, 39 and 33 of 52. The step from 18 to 40 came from 21 added example queries. The runs at 32 and 33 had the ontology attached (step 7). Two runs of an unchanged agent gave the same total and thirteen different verdicts, and in every run the judge failed several answers whose figures were all correct. So the total is good to about two questions and a single verdict is not reliable. Expect about 39 of 52 from the judge for this agent; by my reading of the answers, four or five of the 52 are wrong in a given run. Treat a difference of a few questions between two runs as no difference, read the list the notebook prints under "FAIL although most reference figures are in the answer", and change the agent only for an error that shows up in more than one run.

**What the first run showed (21 November 2026).** With 13 example queries, 12 of the 13 questions that had one passed, and 5 of the 26 that had none. The agent did not work the definitions out from the instructions: it computed a performance index, a contract availability and a forecast error its own way, and the figures looked plausible. It sent three history questions to the live database, answered "0 bird strikes" and compared the site with a neighbour that does not exist. One failure was mine: the instructions defined revenue without the curtailment the offtaker pays for. This version has an example query for every question that failed, each compared with its reference query, sharper rules for the choice of source, the corrected revenue definition and a firmer rule for what the data does not record. [phase3-validation-log.md](phase3-validation-log.md) has the table.

## Step 6: Ontology

**[Fabric]** Open `11_build_ontology` and select **Run all**. It takes one to three minutes.

1. Section 1 checks every table and column the ontology uses, and that no table has Delta column mapping.
2. Section 2 builds the definition: 46 parts.
3. Section 3 sends it to Fabric and waits for the result.

**Check.**

| Output | Expected |
|---|---|
| Section 1 | `11 tables checked: all columns present, no column mapping.` |
| Section 2 | `46 parts: 10 entity types, 12 relationship types` |
| Section 3 | `Creating WindFarmOntology done.` and `Ontology item: …` |

On 21 November 2026 the notebook created the ontology at its first run. I know that only because the ontology could be attached to the agent afterwards: the output of the notebook and the view in the portal were not recorded. The three lines above and the checks below are therefore as designed, not as seen.

Then open **WindFarmOntology** in the workspace. Fabric builds the graph in the background; give it a few minutes.

- The canvas shows 10 entity types connected by 12 relationships.
- Select **Turbine**, **Entity type overview**: 12 instances. Open WT-07: its components, work orders and downtime events are linked, and the time series show gearbox vibration and temperatures.
- Select **WorkOrder**: about 320 instances.

If section 3 fails, send me the message: it names the part Fabric did not accept. Two switches at the top of the notebook help to narrow it down. `BIND_TELEMETRY = False` builds the ontology without the live signals. `LAKEHOUSE_SCHEMA = None` leaves the schema name `dbo` out of the table references.

**By hand instead.** [10-ontology.md](10-ontology.md) has every entity type, property, column and relationship as tables. In the workspace: **New item**, **Ontology**, then for each entity type **Add entity type**, **Bind data**, choose the Lakehouse table, keep the listed columns, set the key; then the relationships. It is about an hour of clicking.

**After the data changes.** The ontology keeps a copy of the data in a graph. After notebooks 01, 02 or 05 run again, open the ontology and refresh the graph model. The live signals come straight from the KQL database and need no refresh.

**What appears beside it.** With the ontology Fabric makes a Lakehouse of the ontology's own and its SQL endpoint, both named `WindFarmOntology_lh_` and 32 hexadecimal digits. Seen on 26 November 2026, when notebook 11 ran as a job for the first time. They belong to the ontology: leave them. (Until the twenty-first issue the deployment runner took the two for items that are not the demo's and stopped at its workspace step.)

## Step 7: Give the agent the ontology

**Measured result: leave the ontology off this agent.** Skip this step unless you want to repeat the measurement.

On 21 November 2026 the same test ran five times on the agent with 34 or 35 example queries:

| Ontology attached | Passed, of 52 |
|---|---|
| No | 40, 39 |
| Yes | 32, 32, 33 |

The last two runs, 39 without and 33 with, were made 30 minutes apart on an agent that was identical in everything else, read back from Fabric before each run. With the ontology attached the agent preferred it, and the ontology holds ten kinds of things, not the whole Lakehouse. So it reported that there is no on-call roster and that the 10-minute data is not available, and it worked out a "remaining useful life of about 14 years and 4 months" for the WT-07 gearbox from the design life of the component, which is exactly the answer the question was written to catch.

This is a finding about this ontology and this agent, not about ontologies. An ontology that covered every table the agent needs might help it. This one was built to describe the equipment, the work and their connections, and that is what it is used for from here on: as the graph to explore in the portal, and as the vocabulary for Phase 4.

**To repeat the measurement.**

1. Open `09_build_data_agent`, set `ATTACH_ONTOLOGY = True` in the third code cell, **Run all**. The last section ends with `ontology attached: 1`.
2. Run `10_test_data_agent` and note the totals.
3. Set `ATTACH_ONTOLOGY = False`, **Run all** again. The notebook takes the ontology off the agent; the last section ends with `ontology attached: 0`. Do not leave the demo agent with the ontology attached.

## Step 8: Prepare the KQL database for the operations agent

**[Fabric]** Open the KQL database `WindFarmEH` and a query window. Paste `fabric/kql/05-agent-readiness.kql`. It has four blocks separated by empty lines; put the cursor in a block and select **Run**.

| Block | Needed | What it does | Expected |
|---|---|---|---|
| 1 | Yes | Records the arrival time of each row and describes the columns of `TurbineTelemetry` | Three rows with `Result` = `Completed` |
| 2 | Check | The newest row per turbine with its arrival time | 12 rows, `ArrivedAt` a few seconds after `Timestamp` |
| 3 | Optional | Creates the table `GearboxVsFleetLive` and fills it as telemetry arrives | Five rows with `Result` = `Completed` |
| 4 | Check, after a minute | The latest comparison with the fleet | One row per running turbine; WT-07 first with about 1.3 mm/s |

Block 3 exists because the operations agent reads tables, not functions, so it cannot use `GearboxVsFleet()` of Phase 2. Skip blocks 3 and 4 if you only want rules 1 to 3 of step 9. If block 4 stays empty after two minutes, send me the result of `.show table GearboxVsFleetLive policy update` and of `.show ingestion failures | where Table == 'GearboxVsFleetLive' | top 5 by FailedOn`; the telemetry itself is not affected.

## Step 9: Operations agent

**[Fabric]**

**With the deployment runner.** `tools/deploy.py` with `--allow-preview operations-agent` does parts 1 and 2 below through Fabric's API: it creates the item with the instructions and the KQL database, stopped. You then open the agent and go on from generating the playbook. That way is new on 26 November 2026 and has not run on a tenant; see [The operations agent](15-deployment-runner.md#the-operations-agent). Everything below is the way by hand, which has.

1. On the Fabric home page select **…**, **Create**, section **Real-Time Intelligence**, **Operations agent**. Name it `WindFarmGearboxWatch`, choose the workspace, **Create**. If the item is not offered, see the region in step 1 and the tenant setting in step 2.
2. On **Agent setup**:
   - **Agent instructions**: paste `fabric/operations-agent/agent-setup.txt`. The page has one box for the business goals and the instructions together; Microsoft Learn still describes two. The file holds both, goals first. If you ran block 3 of step 8 and want the fleet rule, add the line of `optional-rule-4.txt` after rule 3.
   - **Knowledge**: select **Add data** and choose the KQL database `WindFarmEH`. An operations agent has one source.
   - **Actions**: leave empty. Without an action, the agent sends its message in Teams to the person who created it.
3. Select the save icon, then **Generate playbook**. The playbook on the right lists the properties the agent watches and its rules.
4. Read the rules before you start the agent:

   | Rule | Property | Object | Condition |
   |---|---|---|---|
   | 1 | GearboxVibration of `TurbineTelemetry` | TurbineId | Crosses above 4 |
   | 2 | GearboxVibration of `TurbineTelemetry` | TurbineId | Crosses above 5.5 |
   | 3 | GearboxOilTemp of `TurbineTelemetry` | TurbineId | Crosses above 72 |
   | 4, optional | VibrationVsFleet of `GearboxVsFleetLive` | TurbineId | Crosses above 2 |

   - If the page says **No playbook generated** and repeats the rules with a request such as "Provide or confirm the data source for duration above 4 mm per s", the instructions ask the agent to report something that is not a column of the table. That happened on 21 November 2026 with the sentence "say how long the value has been above the threshold", which is no longer in the file. Take the sentence it quotes out of the box, save, and generate again.
   - If a rule says **Is above** instead of **Crosses above**, the agent would send a message every five minutes while the condition lasts. Correct it in the instructions ("crosses above") and generate the playbook again.
   - For any rule, **Copy code** gives the KQL it runs. Paste it into a query window, replace the two time parameters with `ago(15m)` and `now()`, and run it.
5. In Teams, open **Apps**, search for **Fabric Operations Agent** and add it if it is not there yet. Without the app the agent cannot message you.
6. Back in Fabric, select **Start**.

**Check.** **Start** is greyed out and **Stop** is active, and **View activity** lists an evaluation every five minutes. With a healthy fleet no message arrives. If one arrives for WT-07 in strong wind, that is correct: its worn bearing runs close to the early warning.

I have not seen a generated playbook. The table of rules is what the instructions ask for; compare it with yours and send me the difference.

## Step 10: Show it

**A fault the controller does not report.** This is the case the agent exists for.

**[Workstation]** The case shows best at a wind of 7 to 9 m/s; the table below says why. If the site is outside that range, set the wind first. It returns to the site's weather after the hour.

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh wind --mean 8.5 --duration 60m
```

Then start the fault:

```bash
bash infra/vm.sh ssh bash ./edge/scripts/inject-anomaly.sh WT-03 gearbox_degradation 0.2 30m
```

The command answers with the new fault: `"intensity": 0.0`, `"remainingSeconds": 1800`. It starts at zero and ramps in, and the agent looks once every five minutes, so nothing can arrive in the first five minutes.

A fault of severity 0.2 raises the gearbox vibration of WT-03 from about 1.5 mm/s to an average between 4 and 5 mm/s. The controller alarms when a short average stays above 5.5 mm/s for 15 seconds, so it stays silent on vibration: no vibration alarm in 23 runs of the simulator at winds of 6 to 16 m/s.

How clearly the case shows depends on the wind, because a gearbox that works harder vibrates more and runs hotter. Measured in those runs, and on 23 November 2026 in the deployment:

| Wind | Vibration of WT-03 with the fault | Controller |
|---|---|---|
| 6 m/s | Average 3.7 to 4.1 mm/s; above 4.0 for 40 to 65 % of the readings | Silent. The agent's rule may take longer to fire |
| 7 to 9 m/s | Average 4.0 to 4.6 mm/s; above 4.0 for 55 to 93 % of the readings; a rare single reading passes 5.5 | Silent |
| 10 to 11 m/s | Average 4.4 to 4.8 mm/s; up to two readings in a hundred pass 5.5 (5.54 was read at 9.5 m/s in the deployment) | Silent on vibration. The oil temperature alarm at 78 °C came up in 2 of 6 runs |
| 13 m/s and more | Average 4.8 to 5.0 mm/s; single readings up to 6.0 | Silent on vibration. The oil temperature alarm came up in every run |

At 7 to 9 m/s the controller reports nothing and the agent does. In a stronger wind the controller's oil temperature alarm joins in, which is a true picture of the plant and a different story.

| Minutes after the command | What happens | Where to look |
|---|---|---|
| 0 to 5 | The fault ramps in | Real-time dashboard or `TurbineTelemetry` |
| 5 to 12 | The agent's next look finds vibration above 4 mm/s | Activity log of the agent |
| shortly after | Teams message: WT-03, the numbers, the recommendation, **Investigate further** | Teams |
| any time | No `GBX-VIB` alarm | `ActiveAlarms()` in the KQL database |
| 30 | The fault ramps out | |

Then ask the data agent: `Which turbine stands out from the fleet right now on gearbox temperature and vibration?` and `Has WT-03 had gearbox problems before?` The first answer comes from the live data, the second from the history.

**The full fault.** The runbook of Phase 1 ([02-demo-runbook.md](02-demo-runbook.md)) injects severity 0.8 on WT-07. Vibration passes 4 mm/s and 5.5 mm/s within the same minute, so the controller alarm and the agent's rules 1 and 2 come together. The agent is not faster than the controller here, and should not be shown as if it were: it looks every five minutes, the controller reacts in seconds. What the agent adds is the message with the evidence and the next step.

## Design decisions

**Names without spaces.** The data agent, the ontology and the operations agent have names of letters only. I could not confirm that every place a published agent appears in accepts a space, so the names avoid the question.

**The agent does not use the ontology.** Measured, not assumed: 39 and 40 of 52 without it, 32 to 33 with it. Step 7 has the numbers and the reason.

**The agent reads the Lakehouse tables, not the semantic model.** A data agent can also use the semantic model of Phase 2. I left it out, for three reasons read from the documentation on 21 November 2026. The part of the agent that writes DAX ignores the agent's instructions and takes its guidance only from "Prep data for AI" on the model, which is set by hand. A semantic model takes no example queries. And two sources that can answer the same question make it a matter of chance which one answers. The definitions the measures hold are written into the agent's instructions and its example queries instead, and notebook 10 measures whether the answers agree with the reference queries. Adding the model as a third source is one line in notebook 09 (`agent.add_staging_datasource("WindFarm Operations", type="semanticmodel")`) if you want to compare.

**"Now" is the newest record, not the clock.** The history ends where it was generated. The instructions tell the agent to count "last month" back from the newest record of `ops_scada_10min`, as the reference queries do, so both give the same answer on any day.

**Example queries are tested before use.** Notebook 09 runs each one and leaves out those that fail. An example that does not run teaches the agent a mistake.

**Definitions live in example queries, not in prose.** The first test showed that this agent does not derive a calculation from a written definition: 5 of 26 questions without an example passed, 12 of 13 with one. So every measure the site cares about has an example query that computes it, and the instructions keep to what examples cannot say: which source to use, what "now" and "last month" mean, and what the data does not hold. The test then asks variations of the examples, because passing a question that is itself an example proves little.

**Names are spelled exactly.** The SQL analytics endpoint is case sensitive: `turbineId` in the `ref_` tables, `TurbineId` in the `ops_` tables. The instructions say so, and `tools/check-tsql-examples.py` checks every example against the column list.

**The ontology is built from a definition, not from the semantic model.** Fabric can generate an ontology from a semantic model. Entity types made that way are, as far as the documentation shows, bound to the model, and Microsoft lists as a known issue that a data agent does not work with such bindings. Notebook 11 binds each entity type to its Lakehouse table and the turbine's signals to the Eventhouse table. The format of the definition comes from Microsoft's reference for ontology authoring (repository `microsoft/skills-for-fabric`, read on 21 November 2026).

**The operations agent reads the KQL database, not the ontology.** With an ontology as its source, an operations agent takes only plain property values and no rule with "and". The KQL database gives it the whole telemetry table.

**Thresholds come from the simulator.** 4.0 mm/s lies above every healthy turbine (below 2.5), above WT-07 with its worn bearing (below 3.8 in the tested winds) and below the controller alarm (5.5). A test runs the simulator at three wind speeds against these numbers.

## What was and was not tested

**Run in Fabric on 21 November 2026, with output I have seen**

| What | Result |
|---|---|
| Notebook 09 as a Spark notebook on Fabric Runtime 2.0 (Python 3.13) | Installs the SDK, creates and publishes the agent, selects 22 of 22 and 4 of 4 tables, attaches and removes the ontology. One error at the first run, fixed |
| The 35 T-SQL and 6 KQL example queries on the endpoints | All `PASS`; Fabric reports all 41 as `Valid` |
| Notebook 10 | Six runs: 18 of 42 with 13 example queries, then 40, 32, 32, 39 and 33 of 52 |
| Section 4 of notebook 09, the readback | Used before the last two test runs. Its first version stopped on the validation state of the examples, fixed |
| Operations agent: the item and its setup page | One box for goals and instructions. The first instructions were refused by the playbook generator, fixed |
| Fault injection of severity 0.2 from the workstation | Accepted by the simulator |

**Known indirectly or reported, not seen**

- Notebook 11 created the ontology: it could be attached to the agent. Its output and the ontology in the portal (entity types, instances, the live signals of a turbine) were not recorded.
- The playbook that the operations agent generated after the correction, and that the agent was started.
- The Teams message. About a quarter of an hour after the injection the user wrote "got it", which I take to mean that it arrived.
- Whether `05-agent-readiness.kql` was run.
- The regions of the trial and the paid capacity. The operations agent could be created, so the region allows it.

**Checked without Fabric**

| What | How |
|---|---|
| The 35 T-SQL examples return what the reference queries return | Both run through DuckDB on a copy of the Lakehouse tables: `tools/check-tsql-examples.py --lakehouse DIR`. Five deliberate mistakes were caught |
| Every table and column name is spelled as in the Lakehouse | Same tool, against `tools/lakehouse_schema.json` |
| KQL of the examples and of `05-agent-readiness.kql` | Syntax, with the Kusto language service |
| The ontology definition | Built with stand-in identifiers and checked part by part |
| The thresholds of the operations agent | The simulator at 6, 9 and 13 m/s, with and without a fault |
| Every notebook cell | Compiles. The calls to the two libraries were read from the source of the pinned versions |

**Not run at all**

- Block 3 of `05-agent-readiness.kql`, the update policy behind `GearboxVsFleetLive`, and rule 4 of the operations agent.
- The full fault of the Phase 1 runbook against the operations agent.
- Building the data agent or the ontology by hand from the files: the fallbacks of steps 4 and 6.
- Any of this on Fabric Runtime 1.3, or in another region.

## If something fails

| Symptom | Cause and fix |
|---|---|
| Workspace cannot move to the paid capacity: "includes Fabric items or you're attempting to move them across regions" | The capacity is in another region. Step 1, point 3 |
| **Data agent**, **Ontology** or **Operations agent** is missing under **New item** | Tenant setting off, or changed less than an hour ago. Step 2. For the operations agent also the region: step 1 |
| Notebook 09, install cell: dependency conflict | Send me the message. Then try the notebook with only `%pip install -q fabric-data-agent-sdk==0.1.36a0` |
| Notebook 09: `Expected one Lakehouse named WindFarmLH … found 0` | The notebook runs in another workspace, or the item has another name. The names are at the top of `tools/agent_spec.py` |
| Notebook 09, section 1: every KQL example fails with the same message | The check itself fails, not the queries. Set `VALIDATE_KQL = False` in the third code cell and run again; the examples were syntax-checked |
| Notebook 09: `did not appear among the data sources of the agent within 5 minutes` | Open the agent: if the source is there, run the notebook again. If not, add it by hand and run again |
| Notebook 09 or 10: error with `capacity` or `trial` in it | The workspace is still on the trial capacity. Step 1 |
| The agent answers a history question from the KQL database, or the reverse | Tell me the question. The routing rules are the first part of `agent-instructions.txt` |
| The agent says a column does not exist | Upper and lower case. Look at the query under the answer and send it to me |
| Notebook 11, section 1: `Delta column mapping is on` | A table was recreated with a column name that has a space. Run notebooks 01 and 02 again |
| Notebook 11, section 3: `failed: …` | Send me the message. Try `BIND_TELEMETRY = False`, then `LAKEHOUSE_SCHEMA = None` |
| Ontology opens, entity types show no instances | The graph is still building, or the Lakehouse has OneLake security turned on. Wait ten minutes, then refresh the graph model |
| Operations agent: no message after a fault | Agent not started; Teams app not added; the rule says something else than the table in step 9. Run the rule's code in a query window |
| Operations agent: a message every five minutes | The rule says **Is above**. Step 9, point 4 |
| The tenant setting for Graph cannot be found | Its label is "User can create Graph (preview)", and some tenants do not show it at all. If **Graph model** is offered under **New item**, nothing is needed. Step 2 |
| Notebook 09: `404 … EntityNotFound … No fewshots for data source` | A copy of the notebook from the first delivery of Phase 3. Use the file of this version |
| Notebook 09, section 4: `TypeError: unhashable type: 'dict'` | A copy of the notebook from an earlier delivery. Use the file of this version |
| The test total drops by six or seven from one run to the next | Look at the last line of notebook 09, section 4. `ontology attached: 1` explains it. Step 7 |
| An answer reads "Unexpected error: Service Unavailable" or "There's content here I can't work with" | The service, not the agent. Ask again |
| The agent says a table has no rows or does not exist, and the table is there | It happens in one run and not in the next. Ask again. If it repeats for the same question, send me the query under the answer |
| Operations agent: **No playbook generated**, with "Provide or confirm the data source for …" | The instructions ask for something that is not a column. Step 9, point 4 |
| `./infra/vm.sh: Permission denied` | The command started the script file directly, and a copied or merged file has no execute permission. Start it through `bash`: `bash infra/vm.sh …`, the form every command in this guide has |

## Remove Phase 3

Delete these items in the workspace: **WindFarmGearboxWatch**, **WindFarmDataAgent**, **WindFarmOntology** (Fabric removes its graph with it), and the notebooks 09 to 11. In the KQL database: `.drop table GearboxVsFleetLive ifexists`. In the Lakehouse: the tables `agent_evaluation` and `agent_evaluation_steps`. `infra/99-cleanup.sh --fabric` deletes the items of Phase 1 by name and leaves the items of Phases 2 and 3 in place; `--fabric-workspace` deletes the whole workspace with everything in it.
