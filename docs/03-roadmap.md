# Roadmap

Phases 1 to 4 are in this repository and have been deployed. Phase 5 is delivered in three steps: 5a and 5b have run and were reported as working; 5c ran on 25 November and its steps 1 to 5 were seen working, with the demo run through the agent still to do. Its section below says what was planned, what was built differently and why, and what is still to be proven; the sections on Phases 2 to 4 say what each delivered and what it left open. Product facts were checked against the Microsoft Fabric documentation in November 2026; several of these features are in preview and may change.

| Phase | Delivers | State |
|---|---|---|
| 1. Edge to Eventhouse and Lakehouse | Edge VM, Azure IoT Operations, simulator with fault injection, eventstream, Eventhouse, Lakehouse, reference data, two years of operating history, forecast, question bank | Built. The edge-to-Fabric path was run live once; the history and the helper scripts added afterwards were tested without Azure and Fabric. |
| 2. Prepare and model | Enriched tables and KQL views, semantic model | Delivered; deployed on 20 November 2026 |
| 3. Ontology and agents | Data agent with a test, ontology, operations agent that detects the fault | Delivered; deployed on 21 November 2026 |
| 4. Rayfin app | 3D digital twin with live data, an exploded view of each turbine and chat | Delivered; deployed on 23 November 2026. Both routes for the live values worked |
| 5. Remediation with approval | Operations agent proposes a fix, an engineer approves, the edge applies it | In three steps. 5a, the command path from Fabric to the edge, was built on 23 November 2026 and reported as working on 24 November ([12-deployment-guide-phase5a.md](12-deployment-guide-phase5a.md)). 5b, the approval, was built and first run on 24 November and reported as working that evening: the message arrived, it was approved, WT-03 was curtailed ([13-deployment-guide-phase5b.md](13-deployment-guide-phase5b.md)). 5c, the record of the command and the command in the twin, was built on 25 November and run the same night: the record, the function and the twin were seen working, the run with the agent is still to do ([14-deployment-guide-phase5c.md](14-deployment-guide-phase5c.md)). It delivers less than the plan below said, and says what |

**The deployment runner (25 November 2026).** `tools/deploy.py` automates the supported steps of Phases 1 to 4, with an opt-in for a switched-off command path of Phase 5a. Built and tested against stand-ins; its first run on a tenant is the next thing to do with it. [15-deployment-runner.md](15-deployment-runner.md) lists what that run decides.

## Phase 2: Prepare and model

**Built and deployed once on 20 November 2026.** [07-deployment-guide-phase2.md](07-deployment-guide-phase2.md) is its guide, [phase2-validation-log.md](phase2-validation-log.md) the record of that run and of what is still to confirm.

**Delivered**

- KQL functions in the Eventhouse: `Scada10Min()` with the columns and definitions of `ops_scada_10min`, `AlarmIntervals()`, `GearboxVsFleet()`.
- One continuous 10-minute series, `fact_scada_10min`: the generated history, with complete live periods on top.
- A notebook that builds the star schema in the Lakehouse: dates, turbines, site, and nine fact tables.
- A Direct Lake semantic model with 12 relationships and 39 measures, built by a notebook from `tools/model_spec.py`, and a notebook that tests it against the Lakehouse for eleven questions of the question bank.
- A three-page Power BI report, built by a notebook.

**Different from the plan**

- The live roll-up for the model runs in Spark, not as a KQL materialized view; the reasons are in the guide's design decisions.
- The model is kept as Python data, not as TMDL.
- Contractual availability (AM-03) is not a measure; it goes to Phase 3 as a reference query.
- Not delivered: dimension tables for components, alarm codes and contracts; a Real-Time Dashboard. They can be added when Phase 3 needs them.

**Still open**

- The Lakehouse shortcuts to the Eventhouse use passthrough identity. The model no longer depends on them, because notebook 05 copies the live data into Lakehouse tables. The question remains for the data agent and the app if they read the shortcuts.
- `Scada10Min()` in KQL and the roll-up in notebook 05 implement the same rules twice; nothing compares their results yet.

## Phase 3: Ontology and agents

**Delivered and deployed on 21 November 2026.** [09-deployment-guide-phase3.md](09-deployment-guide-phase3.md) is its guide, [phase3-validation-log.md](phase3-validation-log.md) the record of the deployment: seven obstacles and six test runs of the data agent.

**Delivered**

- A data agent on the Lakehouse (history, T-SQL) and the KQL database (live, KQL), built by a notebook: instructions with the site's definitions, 34 T-SQL and 6 KQL example queries, each run against the data before it is used.
- A notebook that asks the agent 52 questions and has each answer judged against the result of a reference query: 34 that are example queries, 10 variations of them, 5 without an example and 3 the data cannot answer. The 4 live questions are asked and printed.
- An ontology of 10 entity types and 12 relationship types, built by a notebook from a definition, bound to Lakehouse tables, with the turbine's live signals from the Eventhouse.
- An operations agent on the live telemetry: goals, instructions and three threshold rules, with an optional fourth on a new table that compares each turbine with the fleet as the data arrives.
- A demonstration the plan did not have: a fault of severity 0.2, which the turbine controller does not report and the agent does.

**Different from the plan**

- The ontology is not generated from the semantic model. Entity types generated that way are, as far as the documentation shows, bound to the model, and a data agent does not work with such bindings (a known issue on Microsoft Learn). It is built from a definition and bound to the tables.
- The data agent reads the Lakehouse tables, not the semantic model and not, by default, the ontology. The guide's design decisions give the reasons; attaching the ontology was measured on 21 November 2026: 39 and 40 of 52 questions passed without it, 32 to 33 with it, so the agent runs without it.
- The example queries are written by hand in T-SQL: a mechanical translation from Spark SQL left functions that T-SQL does not have. There were 13 at first. The first test showed that the agent answers correctly where it has an example and mostly wrongly where it has only instructions, so there are now 34, and the test asks ten variations of them.
- The operations agent reads the KQL database, not the ontology: with an ontology as source it takes no rule with "and" and no aggregation.
- The agent's message carries the live evidence. The history behind it (the four-month drift, the oil samples, the precedent on WT-02, the warranty date) comes from the data agent, in the same demonstration, not from the operations agent itself.
- Contractual availability (AM-03) is a question of the test, not an example query.

**Still open**

- Not seen: the ontology in the portal, the playbook of the operations agent and its Teams message. Not run: the optional fleet rule with its update policy. The guide lists both under "What was and was not tested".
- The data agent answers about 39 of 52 test questions correctly by the judge of the SDK, and four or five wrongly by my reading. It is good enough to show with questions tried beforehand, not good enough to trust unseen.
- An operations agent looks every 5 minutes and the controller reacts in seconds, so for a full fault the agent is not earlier than the alarm. The early warning shows only for a small or slow fault.
- `infra/99-cleanup.sh` does not delete the items of Phases 2 and 3 by name.
- Publishing the data agent to Microsoft 365 Copilot or Teams, and calling it from the app of Phase 4 through its MCP address.

## Phase 4: Rayfin app

**Built on 21 November 2026, the exploded view on 22 November; deployed on 23 November 2026.** [11-deployment-guide-phase4.md](11-deployment-guide-phase4.md) is its guide, [phase4-validation-log.md](phase4-validation-log.md) the record of the deployment and its thirteen obstacles, [../app/README.md](../app/README.md) the description of the code.

**Delivers**

- A Fabric app created with the Rayfin CLI 2.0.1 from Microsoft's Universal App template: a React and Three.js page hosted in the workspace behind the Fabric sign-in, and seven functions.
- The site in 3D: terrain from `reference/terrain/heightmap.json`, roads from the GIS layer, the substation, the met mast, and a turbine at each registry position. Rotors turn at the reported speed, nacelles face the reported direction, blades feather when a turbine stops, a ring on the ground carries the state, and a halo around it and the nacelle carry the condition of the gearbox: amber past the early warning of the operations agent, red when the turbine controller has an alarm.
- An exploded view of each turbine: the cover of the nacelle lifts off and the turbine comes apart into the eleven components of `ref_components`, each with its live values and a colour that follows the alarms of the turbine controller on that component.
- Site figures, the list of turbines, a panel per turbine with live values and the trend of the last hour, the active alarms. With a turbine taken apart, the panel lists its components, and each row can put a question about that component to the data agent.
- A chat that sends questions to the data agent of Phase 3.
- A connection check inside the app, and the same twin on simulated values: in the app with `?sample`, and as one HTML file that needs nothing.

**How the app reads live data: decided twice.** The plan of 21 November was functions that query the KQL database as the identity of the app. The first deployment showed that a Fabric app gets no token the Eventhouse accepts. Since 23 November the app has two routes: the Lakehouse shortcuts through the SQL analytics endpoint, minutes behind and without set-up, and the KQL database as a service principal, under a minute behind. Both worked on the tenant: 2 minutes and 56 seconds at one reading each. Rayfin 2.0.1 has connector types for an Eventhouse and for a data agent, but holds both back; when they are released, or when an app can run as its own identity, the principal can go.

**Not yet**

- Confirmed from the tenant: the chat (whether the data agent answers for the identity of the app, for live questions too), and a connection check of the final build with the measured delay. Phase 5 deploys the app again and asks for both.
- A model of a real machine. The inside of the turbine is drawn from simple shapes at estimated sizes.
- An answer that appears while the agent is still working: functions cannot stream.

## Phase 5: Remediation with approval

**Delivers** (the plan of 23 November; "5b as built" below says where the built thing differs)

- The fault is injected with `--hold`, so it stays until something is done about it.
- The operations agent gathers the evidence that SOP-GBX-001 asks for, proposes an action (for example, curtail WT-07 to 30% for 15 minutes) and sends it to the on-call engineer in Teams with the cost of acting and of not acting. The cost comes from the data: the forecast and the contract price for the energy, the precedent on WT-02 for the repair.
- After approval, the action runs: a Power Automate flow or a Fabric notebook writes a command event to an eventstream. An Azure IoT Operations data flow, with that eventstream's custom endpoint as its Kafka source, publishes the command to the edge topic `…/_control/request`, and the simulator applies it.
- The agent confirms from telemetry that the action took effect, reviews at the review time, and records the event in a work order table.

**In three steps, each delivered and tested before the next.**

| Step | Delivers | Proves |
|---|---|---|
| 5a. The command path | A second eventstream for commands. An Azure IoT Operations data flow, created by script, with that eventstream's custom endpoint as its Kafka source and the broker topic `…/_control/request` as its destination. A notebook or a query that writes one command event by hand | That a command written in Fabric reaches the simulator and curtails a turbine. This is the part no documentation shows end to end, so it comes first and alone |
| 5b. The approval | A custom action of the operations agent that runs a Fabric notebook with the turbine, the percentage and the duration as parameters; the Teams message with the cost of acting and of not acting; the fault injected with `--hold` | That an engineer's Yes in Teams, with the values adjusted or not, becomes the command of 5a |
| 5c. Closing the loop | The agent confirms from telemetry that the setpoint took effect; a work order row records the event; the twin shows the curtailment and who approved it | That the record of the action is in the same data the agents and the twin read |

**What was read from the documentation on 23 November 2026, and is not yet built.** A custom action of an operations agent can be a Fabric item (a notebook, a pipeline, a user-defined function) or a Power Automate flow. The Teams message offers Yes and No, and the approver can change the parameter values before saying Yes. The agent acts with the identity of the person who created it, and the feature is in preview. In Azure IoT Operations a custom Kafka endpoint may be the source of a data flow when the default MQTT broker is the destination; the operations experience cannot create such a data flow, a Kubernetes manifest or Bicep can. The simulator already has the control topic, the curtailment and the alarm "Power limited by remote setpoint" with SOP-CUR-006.

**5a as built (23 November 2026).** `infra/08-create-command-path.sh` creates the eventstream `WindFarmCommands` from a definition, reads its connection from the Fabric API and creates the endpoint and the data flow with the Azure CLI, which turned out to accept a Kafka source; no manifest is applied on the VM. Notebook `12_send_edge_command` builds one command, checks it and writes it to the eventstream. The simulator needed no change.

**To be proven by its first run.** That Fabric accepts the eventstream definition; that the service takes a Kafka-source data flow from the CLI; that the message arrives on the control topic as the JSON that was written; that a notebook may write to the event hub behind the eventstream. On 24 November the run was reported as working, after one correction (a library the send needs); no output was sent, so the four count as reported.

**5b as built (24 November 2026).** Four things differ from the plan above.

- **The wind.** The plan was to show the approval in the story of Phase 3, at 7 to 9 m/s. Measured first: at 8.5 m/s the turbine delivers less than the limit of 30 percent, and the curtailment changes nothing. The approval is shown at 13 m/s, where the limit costs about 90 to 110 USD an hour and takes the gearbox oil from about 80 °C back to 74 °C. In that wind the controller's own warning comes about when the agent's message does, so the story is no longer "the agent is earlier": it is "the controller warns and waits until it must derate; a person with the cost in front of them need not wait".
- **The cost figures.** They stand in a table, `GearboxDecisionLive`, next to the reading that triggers the rule, filled by an update policy from the reference data: the contract price, the rated power, the price and lead time of a gearbox, the end of the warranty. The agent reads them and computes nothing. The forecast is not used: the cost is that of the present hour. The precedent on WT-02 is not written into the agent's instructions; the data agent answers it from the history when asked.
- **The action.** It is the notebook of 5a, with four values and without the command, so that it can limit a turbine and cannot stop one. Fabric makes every name of the notebook's parameter cell a parameter of the action, so that cell holds exactly those four. The notebook lost its `%pip` cell, which a job may not use, and its default turbine.
- **How the agent is changed.** Through the published definition of an operations agent and its API, by `infra/09-remediation-agent.sh`, which saves the definition first and can put it back. By hand in the portal as the second way. The fault is injected with a duration of an hour, not with `--hold`, so that a demo leaves nothing behind.

**To be proven by the first run of 5b.** The update policy on the tenant; that a job's values reach the notebook and that it installs its libraries in a job; that Fabric accepts the changed definition; that the playbook has the one rule and carries the action; that the agent passes the turbine of the row and leads with the cost; and how long each part takes. [phase5-validation-log.md](phase5-validation-log.md) has the findings so far.

**The command center (24 November 2026).** Asked for by the user after 5b: a way to keep sending commands by hand once notebook 12 belongs to the agent. Notebook `13_command_center` does it, and also waits for each command in the telemetry and says how long it took, which was the first piece of 5c's confirmation. Not built: the same controls in the 3D twin. They are possible, and two things have to be settled first: everyone the app is shared with would send commands with the owner's rights, and whether a function of the app may start a notebook job with its Fabric token is not known.

**The first run of 5b (24 November 2026).** Steps 3 to 5 were seen: the notebook runs as a job and takes two to three minutes to start; Fabric refuses the script's change to the agent, so the action was added by hand, where the portal turned out to make every name of the notebook's parameter cell a parameter; the playbook came out with one rule. Step 6 was reported: the message arrived, it was approved, WT-03 was curtailed. Not seen: the message, the approval, the turbine, any time on a clock. Open from that run: why the script is refused, and whether the Python kernel shortens the start.

**5c as built (25 November 2026).** The plan was: the agent confirms from telemetry, a work order row records the event, the twin shows the curtailment and who approved it. Built:

- **The record is kept by the edge.** The simulator, version 1.2.0, reports every operating command it is given as one more kind of message, `command`, on the telemetry's path. So the record also has commands Fabric never sent, and it says `taken` or `refused` in the edge's own words. The table `EdgeCommands` holds it.
- **The confirmation is a function, not a message of the agent.** `CommandLog()` puts each command next to the telemetry after it: confirmed, in force, ended, with the seconds from Fabric to the edge and from the edge back as a reading.
- **The command center reads it** after each send, and prints the log with `history()`.
- **The twin shows it**: who limited a turbine, since when, until when, confirmed or not; the commands of the day in a tab beside the alarms. It sends nothing, which the user chose on 24 November.
- **A second check for the KQL**, against the tables' columns and types, because this function joins tables and grammar alone could not check it.

**What 5c does not deliver, of what was planned.** The agent sends no second message and does not return to a case that is still open when the limit ends. Who approved is not recorded: Fabric does not hand that name to the notebook, so the record has the text the agent passes. There is no work order for the event. And a command that never reaches the edge has no line anywhere. [The guide lists these](14-deployment-guide-phase5c.md#what-this-phase-leaves-open) with what each would take.

**To be proven by the first run of 5c.** That Azure IoT Operations takes the data flow of Phase 1 a second time, with a seventh topic; that the KQL runs and `CommandLog` says what its tested Python copy says; that the command center reads the KQL database from a notebook; and that the twin's service principal may run the function.

**The first run of 5c (25 November 2026, 00:45 to 01:35).** All four held, as far as two pictures of the twin can show: a limit given at the edge and one sent from Fabric were in the log with who asked, the function called them `ended` and `in force` with a confirmation after 2 seconds, and the service principal ran it. One obstacle: the script of Phase 1, run a second time, stood at the Azure CLI's search for a newer extension, which has no time limit; it no longer searches, and it now compares the settings with the running data flow before it replaces it. Two things the pictures showed besides: the controller's note about a limit was counted as an alarm in red (corrected), and the Lakehouse's SQL endpoint falls behind while nobody asks it, so the fallback route needs a minute or two to wake. Still to do: step 6, the run through the agent.

## Further options

- Voice questions in the app, as in the original demo video, with a real-time speech model in Microsoft Foundry.
- Real terrain from open LiDAR data instead of the procedural site.
- An OPC UA server in front of the simulator and the Azure IoT Operations connector for OPC UA, with assets registered in Azure Device Registry.
- Secure settings for Azure IoT Operations (Key Vault secret sync, user-assigned identities) and broker authorization policies.
- More than one site, to show fleet-level comparison.
- A site meter with electrical losses, a condition monitoring system with vibration spectra, and safety records: the data sets that [04-use-cases-and-data-audit.md](04-use-cases-and-data-audit.md) lists as not modelled.
- The Eventhouse destination of the eventstream created through the Fabric REST API instead of the Get data wizard, which would remove the one manual choice that can break the data model (step 6.7).
