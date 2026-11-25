# Phase 3 validation log

The record of Phase 3: what was found out before the first run, what was checked without Fabric, and what went wrong and was changed during the deployment of 21 November 2026 on the user's tenant. The sections follow the order of events.

## Progress

| Step of the guide | Result | Notes |
|---|---|---|
| 1. Capacity | Done, not reported | The workspace runs on a paid capacity: data agent and operations agent work. The regions were not reported |
| 2. Tenant settings | Done | Obstacles 1 and 2 |
| 3. Import the notebooks | Done | Notebooks 09 and 10 ran |
| 4. Build the data agent (notebook 09) | Passed at the second attempt | Obstacles 3 and 4. Output seen at 16:30 and 20:37: all 35 T-SQL and 6 KQL examples `PASS` and `Valid`, 22 of 22 and 4 of 4 tables selected |
| 5. Test the data agent (notebook 10) | Six runs | 18 of 42, then 40, 32, 32, 39, 33 of 52. Working level without the ontology: about 39 by the judge |
| 6. Ontology (notebook 11) | Ran; details not reported | Evidence: notebook 09 attached the ontology `bc8c7ac3-…` to the agent. Not seen: the notebook's output, the entity types and their instances in the portal |
| 7. Give the agent the ontology | Measured: do not | 39 and 40 of 52 without it, 32, 32 and 33 with it. See "Test B" |
| 8. Prepare the KQL database | Not reported | |
| 9. Operations agent | Set up; playbook not seen | Obstacles 5 and 6 |
| 10. Show it | Fault injected; message reported | Obstacle 7. The user wrote "got it" about a quarter of an hour after the injection, which I take to mean that the Teams message arrived |

## Found before the first run

These would have been obstacles. Each was found by reading the documentation, the released code or the simulator's output before anything was built.

| # | What I had planned or said | What is true | Source | Changed |
|---|---|---|---|---|
| 1 | "The ontology and the data agent can be built on the trial capacity" (said on 20 November) | A data agent needs a paid capacity, F2 or larger. An operations agent does not run on a trial either | Microsoft Learn, data agent concept and operations agent pages | Corrected the same day; step 1 of the guide |
| 2 | Move the workspace to the paid capacity as step 0 | A workspace with Fabric items cannot move to a capacity in another region | Microsoft Learn, multi-geo and capacity reassignment pages | Step 1 checks both regions first and gives two ways out |
| 3 | Operations agent in any region | Not available in East US; one walkthrough of April 2026 also lists South Central US, where the Azure side of this demo runs | Microsoft Learn limitations page, read 21 November 2026 | Step 1 names it. The region of the Fabric capacity decides, not the region of the VM |
| 4 | Generate the ontology from the semantic model, then complete it | Entity types generated from a model are, as far as the documentation shows, bound to the model, and a data agent does not work with such bindings | Microsoft Learn, ontology troubleshooting, known issues | Notebook 11 builds the ontology from a definition, bound to Lakehouse and Eventhouse tables |
| 5 | Ground the data agent in the semantic model's measures | The part of the agent that writes DAX ignores the agent's instructions; a semantic model takes no example queries and no source instructions | Microsoft Learn, semantic model best practices for data agent | The agent reads the Lakehouse tables; the definitions are in its instructions and examples |
| 6 | Translate all 39 reference queries from Spark SQL to T-SQL | A mechanical translation left nine functions T-SQL does not have (`ADD_MONTHS`, `ARG_MAX`, `MAKE_DATE`, `FILTER` and others) | sqlglot 30.33 on the question bank | 13 examples written by hand in plain T-SQL and compared with the reference queries on a copy of the data |
| 7 | Column names as in the Spark queries | The SQL analytics endpoint is case sensitive; the `ref_` tables use `turbineId`, the `ops_` tables `TurbineId`. Spark and DuckDB do not notice | Column list of the Lakehouse tables | The instructions say so; the checker follows each alias to its table |
| 8 | Write the notebook from the data agent samples on Microsoft Learn | The released SDK (0.1.36a0) has two generations of calls. The older ones (`add_datasource`, `publish`, `update_configuration`) are marked deprecated in its code | Source of the released wheel | The notebook uses the current calls only: `update_settings`, `add_staging_datasource`, `publish_staging`, and the staging data source for instructions, tables and examples |
| 9 | Adding a data source returns the data source | It returns the raw answer of a background operation, and accepts "already there" silently | Same source | The notebook waits until the source appears and finds it by the identifier of the item |
| 10 | The operations agent uses the views of Phase 2 (`GearboxVsFleet()`) | It reads tables only: no functions, no materialized views. One source per agent. With an ontology as source: no aggregation and no "and" | Microsoft Learn limitations page | Source is the KQL database; optional table `GearboxVsFleetLive` filled by an update policy for the fleet rule |
| 11 | The agent warns before the controller alarm | With the default fault (severity 0.8) vibration passes the agent's 4.0 mm/s and the controller's 5.5 mm/s within one minute, and the agent looks every five minutes | Simulator, three wind speeds | The guide says so. The early warning is shown with severity 0.2, which stays between the two thresholds |
| 12 | Site name "Red Mesa", work order states "In progress" and "Waiting for parts" in the agent's instructions | The site is Northwind Ridge; the states are Open, Scheduled, Closed. I had written them from memory | The data | Corrected; every category the instructions name was read from the tables |

## Checked without Fabric

| Check | Result on 21 November 2026 |
|---|---|
| `python3 tools/check-tsql-examples.py --lakehouse DIR` | 35 of 35 examples return the rows of their reference query (13 at the start of the day). Five deliberate mistakes (two spellings, a period, a flag, a reversed date difference) were all caught after one gap in the checker was closed |
| `node tools/kql-syntax-check.js fabric/kql/*.kql` | No diagnostics, including `05-agent-readiness.kql` and `93-data-agent-examples.kql` |
| `pytest simulator/tests/test_phase3.py` | 16 tests: generated files current, cells compile, install cell first, names exact, variations and the judge's brief, ontology definition consistent with the tables, thresholds against the simulator at 6, 9 and 13 m/s. 80 tests in all |
| Ontology definition | 46 parts built with stand-in identifiers: 10 entity types, 11 bindings, 12 relationship types with their link tables |

## Obstacles of the first deployment

Seven, in the order they came up. The sections after the table give the test runs between them.

| # | Step | What happened | Cause | Changed |
|---|---|---|---|---|
| 1 | 2 | The tenant setting "Users can create Graphs (preview)" could not be found (21 November, 00:42) | The guide had the label from a community post. The admin portal and Microsoft Learn's tenant settings index call it "User can create Graph (preview)", singular | Label corrected in the guide. The same check gave the label of the operations agent setting, "Enable Operations Agents (Preview)", which the guide had left open |
| 2 | 2 | With the corrected label the setting is still not there: a search for "graph" in the tenant settings lists nine settings, none of them for Graph (screenshot, 00:44) | Not known. The tenant does not show the setting; whether it was retired or has not arrived is open | The guide now says to check under **New item** whether a graph item is offered, and to go on if it is. In this tenant **Graph model** and **Graph queryset** are offered (screenshot, 00:45), so Graph is available without the setting |
| 3 | 4 | Notebook 09, section 2, after `WindFarmLH: selected 22 of 22 tables`: `FabricHTTPException 404 … EntityNotFound … No fewshots for data source … found` from `delete_all_fewshots()` (00:51) | The notebook clears the example queries before it adds them, so that a rerun does not double them. On a new data source there are none, and Fabric answers that with an error instead of doing nothing. The SDK passes the error on | The notebook ignores exactly this answer and goes on. Up to this point the run confirmed: the SDK installs in a Spark notebook, the agent is created, the Lakehouse is added and found, and the table selection works (22 of 22) |
| 4 | 4 | The readback section of notebook 09 stopped with `TypeError: unhashable type: 'dict'` after printing `instructions: 64 of 64 lines` (20:16) | The column `validationStatus` of the example queries holds a dictionary per row, not a word. My stand-in for the test had put words there | The cell turns the value into text before counting. The agent had been built and published by the cells before; only the readback was affected |
| 5 | 9 | The setup page of the operations agent has one box, **Agent instructions** ("Define the business goals and explicit instructions or procedures"), then **Knowledge** with **Add data**, then **Actions**. The user asked where the business goals go (21:11) | The guide named a separate box **Business goals**, as Microsoft Learn describes it | New file `fabric/operations-agent/agent-setup.txt` with goals and instructions together; the guide names the controls as they are. That the item can be created also settles the region question for this capacity |
| 6 | 9 | **Generate playbook** answered "No playbook generated". It had understood the three rules, and for each one asked: "Provide or confirm the data source for duration above 4 mm per s (Elapsed time that gearbox vibration has remained above 4 mm/s at trigger evaluation)" (21:16) | My instruction 6 asked the agent to "say how long the value has been above the threshold". The generator took that as a quantity it must read from a column, and no column holds it | Instruction 6 asks only for values that are columns of `TurbineTelemetry`. A test reads every column the instructions name |
| 7 | 10 | `./infra/vm.sh ssh …` on the WSL workstation answered `Permission denied` (21:41) | The scripts in the merged copy had lost their execute permission, as in the first delivery of Phase 1. How the files of the update archives were copied into the folder is not known | `chmod +x infra/*.sh edge/scripts/*.sh config/load-env.sh tools/*.sh`. The guide says to unpack archives inside WSL. `tools/check-scripts.sh` has a third rule that reports a script without the permission |

## First test of the data agent (21 November 2026, 01:13)

Notebook 10 asked 42 questions in 7 minutes 56 seconds. 18 passed, 24 did not. The user sent every failed answer next to its expected result.

| | Asked | Passed |
|---|---|---|
| Questions that are an example query | 13 | 12 |
| Questions of the bank without an example | 26 | 5 |
| Questions the data cannot answer | 3 | 1 |

| Group | Questions | What the agent did | Changed |
|---|---|---|---|
| Wrong source | PE-03, RE-04, OP-01 | Asked the live database a question about 60 or 90 days of history, or about what an alarm code means, and found two alarms or none | The instructions give the live database the last 24 hours only and name three kinds of question that always go to the Lakehouse. Both source descriptions say the same. Example queries for PE-03 and RE-04 |
| Own definition | PE-01, PE-02, PE-04, PE-07, RE-03, RE-06, AM-03, AM-04, AM-05 | Computed a performance index over all periods (0.80 to 0.89 instead of 0.95 to 1.00), a contract availability from time availability (damages of 141,083 USD instead of 25,711), a forecast error from summed megawatts (minus 83 percent). RE-06 said the WT-07 gearbox runs cooler than the fleet | An example query for each. The definitions of performance index, forecast accuracy, repair cost and major failure are also in the instructions |
| Query failed or found nothing | PE-05, RE-07, RE-08, MP-01, MP-02, AM-06 | Looked for the forecast in the weather table, for a "major" flag, for a due date; one query failed on the type of a column | An example query for each. The Lakehouse instructions describe the forecast, oil sample, price and work order tables and four T-SQL habits (no `%` on float, no `LIMIT`) |
| My instruction was wrong | AM-01 | Followed "revenue = energy times contract price" and came out about 166,000 USD short | Revenue now includes compensated curtailment, as the contract and the reference query have it. Example query |
| Same figures, other shape | SM-02, MP-03, MP-05 | SM-02 started one month later and included the running month; MP-03 and MP-05 showed other columns | "By month" means complete calendar months. Example queries. The judge has a brief of its own: figures within rounding, other columns and order allowed, another period not |
| Should have said "not in the data" | NO-01, NO-03 | "0 bird strikes"; compared the site with "the neighbouring wind farm (Northwind Ridge Wind Farm)", which is the site itself | The instructions say what the data covers and that a missing record is not a zero |

What this run established:

- The whole chain works in Fabric: the SDK in a Spark notebook on Runtime 2.0 (Python 3.13), creating, configuring and publishing the agent, table selection, and the SDK's evaluation with its judge.
- This agent uses example queries well and written definitions badly. Twelve of thirteen against five of twenty-six is not a small difference, and the wrong answers were fluent and looked right.
- A test whose questions are all example queries would now prove little. The test has ten variations (another turbine, period or component), reported on their own line.

Checked after the change, without Fabric: all 34 T-SQL examples return the rows of their reference query on the copy of the data, three runs in a row; the ten variation queries return rows; 80 tests pass. Not checked: whether the SQL endpoint accepts `AT TIME ZONE`, `DATENAME`, `EOMONTH`, `STRING_AGG` and `DATEFROMPARTS` in the new examples. Notebook 09 prints a `FAIL` line for each one it does not.

## Second test of the data agent (21 November 2026, 01:49)

52 questions in 7 minutes 34 seconds: **40 passed** (first test: 18 of 42). Examples 29 of 34, variations 4 of 10, no example 4 of 5, not in the data 3 of 3. The sources were chosen correctly every time, and `MP-01` passed, so the SQL endpoint accepts `AT TIME ZONE` and `DATENAME`.

Reading the 12 answers that did not pass:

| Verdict on the verdict | Questions | Why |
|---|---|---|
| The agent was right; a tie | PE-01, RE-04, VA-05 | Two turbines share the value (WT-05 and WT-09 at 0.9513; WT-01 and WT-07 with 49 alarms). The reference query picks one of them arbitrarily, the agent the other |
| The agent was right; my question was loose | VA-03, VA-04 | "By month" without a period: it showed all months, with the same figures. "Last 26 weeks": it cut the weeks at other days than the reference's 182 days, so the first week differs |
| Right figures, other shape or within 1 percent | MP-05, VA-07, VA-10 | Hours by kind of work instead of counts, with the same totals; counts that match the reference; 1,980.7 against 1,987 MWh |
| Wrong | RE-03, RE-05, AM-06, VA-09 | RE-03 followed my instruction "a failure is a component fault" instead of its example. RE-05 had no example and compared in its own way. AM-06 used complete months instead of the last 12 months from now. VA-09 added stops to alarms: 27 "pitch alarms" for WT-10 where there are 16 |

So four real errors in 52, of which one came from a conflict between an instruction of mine and an example of mine.

Changed: an example for RE-05; three definitions in the instructions (repeat offender, "at the same load", alarms are not stops); the two loose variation questions name their period; the judge is told that ties may come in either order and that a partly covered first or last period may differ. 35 T-SQL examples, all compared with their reference queries. Not sent yet: the `PASS`/`FAIL` lines of notebook 09.

## Third test of the data agent (21 November 2026, afternoon)

With the changes of the second test: 52 questions in 7 minutes 32 seconds, **32 passed** (second test: 40). Examples 22 of 35, variations 5 of 10, no example 3 of 4, not in the data 2 of 3. The score went down after I added guidance. Reading the 20 answers that did not pass gave three causes, and only one of them is the agent.

| Cause | Questions | What happened |
|---|---|---|
| The judge failed a right answer | PE-01, RE-03, RE-04, AM-05, VA-05, probably SM-05 | The figures in the answer are the figures of the reference (PE-01: all twelve; AM-05: all six monthly errors). The tie rule I gave the judge did not change its verdict on PE-01, RE-04 and VA-05 |
| My new rules collided with my examples | SM-04, AM-06, VA-04, VA-10 | "Use complete calendar months" made it answer "last 6 months" in calendar months. "Above 3000 kW" for "same load" replaced the example's 2000 kW. The corrected revenue rule made it value curtailment at the unpaid part only |
| The agent, differently from last time | SM-06, PE-02, PE-04, PE-05, PE-06, PE-07, RE-05, VA-03, VA-09, NO-01 | SM-06 said there is no spare parts table; it answered the same question correctly in both earlier runs. PE-06 passed before with 163 hours and now gives 116. PE-02, PE-04 and RE-05 used another period than their example. VA-09 found no pitch alarms: `ref_alarm_codes.component` is lower case and the comparison is case sensitive |

What this run established:

- **One run of this test is not a measurement to the question.** The same agent, asked the same question with the same example, answers correctly in one run and refuses in the next. A difference of a few questions between two runs is not evidence that a change helped or hurt.
- **The judge is a second source of noise.** In this run at least five right answers were failed.
- **Every sentence added to the instructions is a possible conflict with an example.** Three of my four additions of the second round did harm somewhere.

Changed: the three colliding rules are reduced to what the examples do ("last N months" counts back from now; "same load" follows the examples; lost energy is valued at the contract price for every cause); one line tells the agent to keep an example's tables, filters and period; the Lakehouse instructions list the exact spelling of component names in the two tables. Notebook 10 has a second opinion that uses no model: the share of the reference figures, dates and identifiers that the answer contains, printed next to each verdict, with a list of the verdicts it disagrees with. It is an aid for reading, not a verdict: it cannot see one wrong figure among right ones.

Not done, and why: no further example queries and no further rules. Until the test is run several times on an unchanged agent, there is no way to tell their effect from the noise.

## Fourth test of the data agent (21 November 2026, about 16:00)

52 questions in 8 minutes 15 seconds: **32 passed** again, but not the same 32. Examples 22 of 35, variations 5 of 10, no example 3 of 4, not in the data 2 of 3. Passed now and failed in the third run: SM-05, SM-06, PE-01, PE-05, VA-04, VA-09. Failed now and passed then: PE-03, MP-01, MP-02, OP-02, OP-03, VA-06, VA-07.

Several answers of this run do not use the example query that exists for exactly that question: SM-04 and PE-06 looked for `LossCause` in `ops_turbine_events` and found nothing; OP-02 said the data has no on-call roster; MP-01 said the forecast table returned no rows; PE-03 used the last 24 hours; VA-10 used calendar months although the instructions of update 2 say otherwise. Whether notebook 09 of update 2 was run before this test is not known, and its output has still not been seen, so it is open whether the published agent holds the 35 examples and the current instructions at all.

In the agent's chat the user asked the question of step 7, "Which spare parts did the work orders on the WT-02 gearbox use, and who led them?", and was told that there are none. The data has at least eight such work orders with parts. The agent filtered on a component type "containing gearbox"; the value is `Gearbox`, and text comparison on the SQL endpoint is case sensitive, which is the likely cause.

Next: read back from the published agent what it holds (instructions, tables, number of example queries per source) before changing anything else.

## Readback of the published agent (21 November 2026, 16:30)

The user ran a cell that reads the agent back from Fabric, and sent the output of notebook 09 for the first time.

- All 35 T-SQL examples and all 6 KQL examples ran on the endpoints (`PASS`). So `AT TIME ZONE`, `DATENAME`, `EOMONTH`, `STRING_AGG` and `DATEFROMPARTS` are accepted, and the table selection gave 22 of 22 and 4 of 4.
- The published agent holds 35 and 6 example queries, but the instructions of the **second** test, not of update 2: the rule "not calendar months" and the spelling of component names are missing. Notebook 09 of update 2 was not run. So the third and the fourth test ran on the same agent.
- The last line of notebook 09 reads `ontology attached: FabricDataAgentOntology(…)`. **The ontology exists and has been attached to the agent since the third test.** Notebook 11 therefore worked; I had not been told and had not asked.

This changes the reading of the third and fourth test:

| | Second test | Third test | Fourth test |
|---|---|---|---|
| Example queries | 34 | 35 | 35 |
| Instructions | first revision | second revision | second revision |
| Ontology attached | no | **yes** | **yes** |
| Passed | 40 of 52 | 32 of 52 | 32 of 52 |

- Two runs of an unchanged agent gave the same total and thirteen different verdicts. The total is steadier than the single question.
- The answers that looked like "the agent ignores its example" fit the ontology: it has ten entity types and no roster, no forecast, no 10-minute data. An agent that goes through it finds no on-call roster (OP-02), no forecast (MP-01), no spare parts (SM-06, third test), looks for a loss cause in the downtime events (SM-04, PE-06: the entity `DowntimeEvent`), and lists eleven components of WT-09 as a "drivetrain set" (VA-06). The chat answer about the WT-02 gearbox may have the same origin.
- This is not proven: the second revision of the instructions came in at the same time as the ontology. The next two runs separate them.

Changed: notebook 09 removes an attached ontology when `ATTACH_ONTOLOGY` is `False`, does not attach it twice, and ends with a section that reads back from Fabric what the published agent holds (lines of the instructions found, example queries per source with their validation state, ontology attached or not). The Lakehouse instructions gain the spelling of `ref_components.componentType` and the advice to compare in lower case when unsure.

Lesson: I asked four times for the output of notebook 09 and went on without it each time, explaining test results from what I believed the agent held. The readback took one minute and overturned two of my explanations.

## Test A: current instructions, no ontology (21 November 2026, 20:30)

Readback from Fabric before the test: 64 of 64 instruction lines, 35 and 6 example queries all `Valid`, `ontology attached: 0`. Notebook 09 printed `ontology: none attached`, so the ontology had already been taken off the agent before this run.

52 questions in 6 minutes 21 seconds: **39 passed**. Examples 27 of 35, variations 8 of 10, no example 2 of 4, not in the data 2 of 3.

Reading the 13 that did not pass:

| Reading | Questions |
|---|---|
| Right; the reference figures are in the answer (the notebook's second opinion flagged four of them) | PE-06, RE-03, RE-04, AM-06, VA-05, VA-10 |
| The service failed, not the agent | PE-02 ("Unexpected error: Service Unavailable"), OP-02 ("There's content here I can't work with") |
| Said it cannot compare, then gave our own availability; the judge wants no number | NO-03 |
| Wrong | RE-05 (90 days instead of the example's 30), RE-09 and MP-02 ("no such records", although both passed in other runs), AM-07 (found no emission factor) |

By the judge 39 of 52; by my reading four wrong answers and two service failures. Against 32 and 32 with the ontology attached and the earlier instructions. Test B (the same agent with the ontology attached) is what separates the two changes.

## Test B: the same agent with the ontology attached (21 November 2026, 20:55)

Readback before the test: 64 of 64 instruction lines, 35 and 6 example queries `Valid`, `ontology attached: 1`. Nothing else differs from test A, 30 minutes earlier.

52 questions in 7 minutes 26 seconds: **33 passed**. Examples 24 of 35, variations 6 of 10, no example 2 of 4, not in the data 1 of 3.

| Ontology | Runs | Passed, of 52 |
|---|---|---|
| Not attached | second test, test A | 40, 39 |
| Attached | third test, fourth test, test B | 32, 32, 33 |

The answers show how: OP-02 again "the data does not include rota or on-call information"; PE-01 "I can't calculate this", the 10-minute data not being reachable; NO-01 "0 bird or wildlife strike events"; and NO-02 "the remaining useful life of the WT-07 gearbox is approximately 14 years and 4 months", worked out from the design life and the install date of the component in the ontology. The agent prefers the ontology when it has one, and this ontology holds ten entity types, not the Lakehouse.

**Decision: the demo agent runs without the ontology.** Notebook 09 with `ATTACH_ONTOLOGY = False` takes it off. Step 7 of the guide now states the result and keeps the steps only for repeating the measurement. The ontology stays as the graph of the equipment and the work, for the portal and for Phase 4.

What I had written in step 7 before the measurement, "I cannot predict whether that helps or confuses it", was the right amount of confidence. What I did wrong was to explain two test results (third and fourth) without knowing the ontology was attached.



## State at the end of Phase 3 (21 November 2026, 22:00)

- **Data agent** `WindFarmDataAgent`: Lakehouse (22 tables, 35 example queries) and KQL database (4 tables, 6 example queries), no ontology. About 39 of 52 test questions pass by the judge.
- **Ontology** `WindFarmOntology`: exists, 10 entity types and 12 relationship types by its definition. Not attached to the agent.
- **Operations agent** `WindFarmGearboxWatch`: set up from `agent-setup.txt` on the KQL database.
- The user was told to run notebook 09 once more with `ATTACH_ONTOLOGY = False` after test B. Whether that was done was not reported: section 4 of notebook 09 shows it.

## Still open

- What the guide lists under "Known indirectly or reported, not seen": the output of notebook 11 and the ontology in the portal, the playbook of the operations agent and its Teams message (a screenshot of each), whether `05-agent-readiness.kql` was run, the regions of the capacities.
- What the guide lists under "Not run at all": the optional fleet rule with its update policy, the full fault against the operations agent, the fallbacks by hand.
- `infra/99-cleanup.sh` does not delete the items of Phases 2 and 3 by name. The guide says which items to delete.
- From Phase 2, still not confirmed by output: the PASS lines of notebook 07, the three report pages, the check query of `04-prepared-views.kql`, the hand-over table of notebook 05.

## Lessons

- Preview features have limits that decide the design. Read the limitations page of each one before the plan, not before the build: findings 2, 3, 4, 5 and 10 changed what Phase 3 is.
- A translation that parses is not a translation that runs. The mechanical T-SQL was valid to the parser and useless to the endpoint.
- Two engines that ignore upper and lower case cannot test names for one that does not.
- Numbers in a demonstration script come from a run, not from a formula. The claim "the agent warns earlier" was false for the default fault and true for a smaller one; only the simulator showed which.
- Instructions tell an agent where to look; examples tell it how to calculate. I had put the calculations in the instructions. Measure before believing either: the first test took eight minutes and changed the design.
- A wrong definition in an instruction is followed faithfully. The revenue error was mine, and the agent reproduced it.
- Read back from the service what an agent holds before interpreting any test of it. I explained two test results from what I believed the agent had; a one-minute readback showed older instructions and an attached ontology.
- Change one thing between two runs, and run an unchanged agent twice before believing a difference. Test A and test B, 30 minutes apart, settled in one evening what four earlier runs had confused.
- A test judged by a language model gives a total that is good to about two questions and single verdicts that are not reliable. A second opinion that needs no model costs twenty lines.
- More context is not more accuracy. The ontology made the agent worse because the agent preferred it and it holds a tenth of the data. Three of four sentences I added to the instructions collided with examples.
- For an operations agent, every value the instructions ask it to report must be a column.
- Text for an agent is code. The instructions named a site and two states that do not exist; a test now reads every quoted column, and the categories were read from the data.

## Files of Phase 3

Against the repository at the end of Phase 2: 25 new files and 7 changed ones. No file was removed or renamed. Everything under `fabric/data-agent/`, `fabric/ontology/` and `fabric/operations-agent/`, the three notebooks, `93-data-agent-examples.kql` and `docs/10-ontology.md` are generated by `tools/build-phase3.py` from `tools/agent_spec.py`: change the specification, not the files.

| New | Changed |
|---|---|
| `docs/09-deployment-guide-phase3.md` | `README.md` |
| `docs/10-ontology.md` | `docs/00-architecture.md` |
| `docs/phase3-validation-log.md` | `docs/03-roadmap.md` |
| `fabric/data-agent/agent-instructions.txt` | `docs/troubleshooting.md` |
| `fabric/data-agent/agent-spec.json` | `fabric/README.md` |
| `fabric/data-agent/example-queries-lakehouse.sql` | `simulator/requirements-dev.txt` |
| `fabric/data-agent/kql-description.txt` | `tools/check-scripts.sh` |
| `fabric/data-agent/kql-instructions.txt` |  |
| `fabric/data-agent/lakehouse-description.txt` |  |
| `fabric/data-agent/lakehouse-instructions.txt` |  |
| `fabric/kql/05-agent-readiness.kql` |  |
| `fabric/kql/93-data-agent-examples.kql` |  |
| `fabric/notebooks/09_build_data_agent.ipynb` |  |
| `fabric/notebooks/10_test_data_agent.ipynb` |  |
| `fabric/notebooks/11_build_ontology.ipynb` |  |
| `fabric/ontology/ontology-spec.json` |  |
| `fabric/operations-agent/agent-instructions.txt` |  |
| `fabric/operations-agent/agent-setup.txt` |  |
| `fabric/operations-agent/business-goals.txt` |  |
| `fabric/operations-agent/optional-rule-4.txt` |  |
| `simulator/tests/test_phase3.py` |  |
| `tools/agent_spec.py` |  |
| `tools/build-phase3.py` |  |
| `tools/check-tsql-examples.py` |  |
| `tools/lakehouse_schema.json` |  |
