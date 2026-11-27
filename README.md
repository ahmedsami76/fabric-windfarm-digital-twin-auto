# Wind farm digital twin on Microsoft Fabric

An end-to-end demo that starts at a wind farm's edge server and ends in a live 3D digital twin with agents, built in phases. It reconstructs, from scratch, the kind of solution shown in Microsoft's "real-time 3D digital twin built on Microsoft Fabric" demo, and places it in an Azure IoT Operations architecture.

**Phase 1** is the ground everything stands on: an Azure VM as the edge server, Azure IoT Operations, a turbine simulator with fault injection, ingestion into a Fabric eventstream, Eventhouse and Lakehouse, and the data that the questions of a wind farm's staff need: two years of operating history, a forecast, a budget, contracts and reference data. **Phase 2** adds a star schema, a semantic model and a report; **Phase 3** a data agent, an ontology and an operations agent; **Phase 4** the 3D twin itself, as a Fabric app built with Rayfin. Phases 1 to 4 have been deployed. **Phase 5** is remediation with approval, in three steps: a command path from Fabric to the edge, the operations agent proposing a limit that a person approves in Teams, and the edge's own record of what it was told, shown in the twin. All three have run on the tenant; of the third, the demo run with the agent is still to do.

```
Edge server (Azure VM, K3s, Azure Arc)                Microsoft Fabric
+----------------------------------------+            +---------------------------------------+
| Turbine simulator --MQTT--> Azure IoT   |   Kafka    | Eventstream --> Eventhouse (KQL)      |
|                             Operations  | ---------> |                   | OneLake           |
|                             data flow   |            |                   v availability      |
| Site documents --> reference data sync  | ---------> | Lakehouse: live shortcuts, reference  |
+----------------------------------------+  OneLake   | tables, operating history, forecast   |
                                                      +---------------------------------------+
```

The site, Northwind Ridge Wind Farm, is fictional: 12 turbines of 4.2 MW on procedurally generated terrain. The history, the live data and the forecast share one weather and the same twelve machines, so that a question can combine "now" with "normally". All data is synthetic; the companies and people are invented.

## This version

This is the version with a deployment runner. It holds everything of the consolidated version of 25 November 2026 (every phase as built and run on a tenant between 19 and 25 November, deployed by hand from the guides in `docs/`), and adds `tools/deploy.py`, which carries out the supported steps of Phases 1 to 4 itself and tells you exactly what to do where a person has to act.

```bash
# the first deployment in a subscription: the choices as options, saved as the subscription's profile
python3 tools/deploy.py plan --edge-region southcentralus --approve-role-changes --save-profile
# the line the plan prints: it names the deployment and carries the approvals you gave
python3 tools/deploy.py apply --deployment <suffix> --approve <plan> --approve-role-changes --confirm phase1.tenant_settings
# every later deployment there: no option for a choice, no question
python3 tools/deploy.py plan --new --approve-role-changes
# provisioned, blocked or demo-ready
python3 tools/deploy.py status --deployment <suffix>
```

Nothing is filled in beforehand, and no settings file is prepared. A deployment gets three random characters when it is started and keeps its settings, checkpoint, plans and app build in `.deploy/<suffix>/`. One folder holds as many deployments as you start, in one tenant or in several.

**How a choice is settled**, in this order: an option of the run (`--edge-region`, `--capacity`, `--new-capacity --capacity-region`, `--workspace-id`, `--vm-size`, `--ssh-source`); the deployment's settings; the profile saved for the tenant and subscription (`--save-profile`); a default the cloud establishes as the only one, which is a single capacity that can hold the demo. A value that is not valid is refused; nothing else is put in its place. What is left is asked together in a terminal, or blocks the plan with the candidates and the option that settles it. A paid capacity is made only on `--new-capacity` with `--approve-capacity-creation`, for one deployment.

**To resume**, run the same apply line again: it looks before it does anything and makes nothing twice. Exit code 3 names what is yours to do, 4 means something is still running. After an apply that ended before Fabric answered a request to run a notebook, the runner lists the runs and takes `--adopt-job STEP=ID` or `--resubmit STEP`. A refused apply says what differs from the plan that was approved.

**Three words, kept apart**: *provisioned* (the things exist), *blocked* (a step waits, failed or still runs), *demo-ready* (fresh telemetry measured now, usable Lakehouse data, and for the twin the deployed app's own connection check, given with `--app-check`).

[docs/15-deployment-runner.md](docs/15-deployment-runner.md) has every step with who does it, the handoffs, what an approval covers, and what has been proven where. [docs/16-runner-pilot-checklist.md](docs/16-runner-pilot-checklist.md) is the first run on a tenant, step by step, for a person to carry out.

**On a tenant the runner has deployed Phase 1 to its end** (25 and 26 November, the pilot of [docs/16-runner-pilot-checklist.md](docs/16-runner-pilot-checklist.md); what the runs found is in [docs/runner-validation-log.md](docs/runner-validation-log.md)): `preflight`, `plan`, and an `apply` that made the resource group, the VM, the roles of its identity, K3s and the Azure Arc connection. Azure IoT Operations was deployed by the runner's script started by hand from Azure Cloud Shell, because the workstation of that run received large answers from Azure too slowly. On 26 November the runner also made the workspace, the Eventhouse with its tables, the Lakehouse and its shortcuts, the eventstream, the connection of the edge and the data flow there, and measured 60 readings from 12 turbines in the Eventhouse: and then uploaded the reference data, imported and ran the notebooks, and passed the Lakehouse gate: all twenty-five steps of Phase 1, at 16:50 on 26 November. Several runs on the way ended on a single call that got no answer from that workstation; since the twelfth issue such a call is asked again where asking twice changes nothing. Phase 2 ran under the runner to its end, and Phase 3 up to the operations agent (26 November, 20:33): the notebooks that install packages with `%pip` ran as jobs, and one of them built the data agent. With `--allow-preview operations-agent` the runner also creates the operations agent with its instructions and its data source; the playbook, the start and Teams stay a person's, and that step has not run on a tenant. Phase 4 ran under the runner as well, and at 22:24 on 26 November the deployment was complete: `provisioned yes: 43 of 43 steps`. Since then the runner also provisions Phase 5 behind an option of its own (`--enable-phase5-isolated-simulator`): everything that sends nothing; switching the command path on, the agent's new setup and every command stay a person's. On 26 November the runner's part of Phase 5 ran on the tenant, and with the agent changed and started by hand the deployment stood at 50 of 50 steps at 23:57, the last by the operator's word. For Phase 4 the runner sets up the twin's live route: a service principal of the deployment's own that reads the Eventhouse, as the deployment by hand has it. The runner was exercised against stand-ins: 143 tests, and 331 planted faults that the tests caught. The scripts and notebooks it starts ran on a tenant, started by hand. The guides remain the way to deploy by hand; the runner generates its own names, keeps its settings apart from the `config/demo.env` of a deployment by hand, and never works in what such a deployment made.

What has not run on a tenant, besides the runner: step 6 of Phase 5c (the story through the agent with the record), the script route of Phase 5b's step 4 (the way by hand was used), the clean-up of the items of Phases 2 to 5 (scenario-tested), and the second build of the twin of Phase 5c (`455aa9777780`).

## Status

| Part | State |
|---|---|
| Phase 1, edge to Fabric, steps 1 to 8 of the deployment guide | Deployed live twice in November 2026: the first version of this repository on the 19th, this version on the 20th. 20 obstacles were met in the two runs; all are addressed except two open questions (see the validation log). |
| Simulator, history generator, site generator | 57 automated tests at the time of Phase 1, with simulator 1.1.0, which ran live in the second deployment. The simulator is 1.2.0 since Phase 5c: it reports the commands it is given. The test suite of all phases has 218 tests |
| Notebooks 01 to 04 and the question bank | Run in local Spark sessions on the versions of both Fabric runtimes, and in Fabric in the second deployment, where the checks matched the guide (reported by the user) |
| KQL added since the first run (`ActiveAlarms()`, four live questions) | Syntax-checked; a run in the Eventhouse is not confirmed |
| `infra/vm.sh`, `infra/rebuild-env.sh` | 31 scenario tests against stand-in commands, 4 for where a script finds its settings, and 2 for the subscription the runner names for it. Live: `run` works; `ssh` found no way in when the SSH rule had been removed, cause open |
| `tools/deploy.py`, the deployment runner | 143 tests against a pretend Azure and Fabric; 331 planted faults, all caught. On a tenant: `preflight`, `plan`, and `apply` for **all of Phase 1, 25 of 25 steps**, then **Phase 2 to its end and Phase 3 up to the operations agent**, notebooks 06 to 09 run as jobs by the runner, on 25 and 26 November; what the runs found is corrected. Then Phase 4 to its end, the service principal for the live route among it: **43 of 43 steps on 26 November at 22:24**. Then Phase 5 behind its option, everything that sends nothing: **50 of 50 steps at 23:57**, the agent's new setup done by hand. The operations agent created through the API (an opt-in), `status`, and an interrupted notebook run have not run under the runner. [docs/15-deployment-runner.md](docs/15-deployment-runner.md) |
| `infra/99-cleanup.sh` | 42 scenario tests, 10 of them new on 25 November: the deployment named with `--deployment`, and a shared capacity told from one the deployment made. Run live once, in its first version: Fabric items and resource group removed; the uninstall step failed and now retries. Since 25 November `--fabric` also knows the items of Phases 2 to 5 (the notebooks 05 to 13, the semantic model, the report, the data agent, the ontology, the operations agent, the app, the command eventstream): scenario-tested, not run |
| Checks added after the second deployment (object ID format, step 3 feature check, longer health wait in step 4, `ssh` falling back to `run`) | Scenario tests and ShellCheck; not yet run against Azure |
| Phase 2: prepared views, model tables, semantic model, acceptance test, report | Deployed once, on 20 November 2026; three obstacles, all fixed. The user reported every step as done; the outputs of the acceptance test and of the report were not sent, so the measures and the report count as run, not as verified. See [docs/phase2-validation-log.md](docs/phase2-validation-log.md) |
| Phase 3: data agent, its test, ontology, operations agent | Deployed on the user's tenant on 21 November 2026. The data agent was built and tested six times: about 39 of 52 test questions pass by the judge of the SDK. The ontology was created, and measured to make the agent worse, so the agent runs without it. The operations agent was set up; its playbook and its Teams message were reported, not seen. Seven obstacles, all in [docs/phase3-validation-log.md](docs/phase3-validation-log.md) |
| Phase 4: the twin as a Fabric app (`app/`) | Deployed on the user's tenant on 23 November 2026. The twin shows the live site in 3D, with an exploded view of each turbine and a chat to the data agent. A Fabric app cannot read the Eventhouse directly, which the deployment showed; the live values come by two routes instead, and both worked: through the Lakehouse (2 minutes behind at the one reading) and, as a service principal, from the Eventhouse (56 seconds). Thirteen obstacles, all addressed. Seen: seven connection checks and two screenshots. Reported and not seen: the successful deployments themselves and the chat. 104 tests cover the app's code against stand-ins for Fabric; `app/preview/windfarm-twin-preview.html` is the twin on sample data. See [docs/phase4-validation-log.md](docs/phase4-validation-log.md) |
| Phase 5a: the command path from Fabric to the edge (`infra/08-create-command-path.sh`, notebook 12) | Built on 23 November 2026, first run on the user's tenant on 24 November. The first run stopped at the send because a library was missing (seen, corrected); after that the run was **reported as working: WT-07 was curtailed**. No output of the working run was sent. Notebook `13_command_center` sends commands by hand, one line each, and says what became of each; built on 24 November, not reported as run in Fabric yet. See [docs/phase5-validation-log.md](docs/phase5-validation-log.md) |
| Phase 5b: the operations agent proposes a curtailment with its cost, a person approves it in Teams, the notebook of 5a sends it (`infra/09-remediation-agent.sh`, table `GearboxDecisionLive`) | Built and first run on 24 November 2026. Seen: the notebook runs as a job, slowly (two to three minutes before it starts); Fabric refuses the script's change to the agent (cause open), so the action was added by hand; the playbook has one rule. **Reported as working: the message arrived in Teams, it was approved, WT-03 was curtailed.** Not seen: the message, the approval, the turbine. [docs/13-deployment-guide-phase5b.md](docs/13-deployment-guide-phase5b.md) |
| Phase 5c: the edge records every command it is given, a function says what the telemetry showed afterwards, the command center and the twin show it (simulator 1.2.0, table `EdgeCommands`, function `CommandLog`) | Built on 25 November 2026 and run the same night. **Steps 1 to 5 work on the tenant, seen in the twin**: commands given at the edge and from Fabric are in the log with who asked, the function calls them in force and ended, the twin shows the card. One obstacle, a script that stood at a search of the Azure CLI. Step 6, the run with the agent, has not run. Not built, of what the roadmap planned: a second message of the agent, the name of the approver, a work order. [docs/14-deployment-guide-phase5c.md](docs/14-deployment-guide-phase5c.md) |

"What has and has not been verified" in [docs/00-architecture.md](docs/00-architecture.md) has the details.

## Start here

| Document | Purpose |
|---|---|
| [docs/01-deployment-guide-phase1.md](docs/01-deployment-guide-phase1.md) | Step-by-step deployment from an empty subscription and workspace |
| [docs/07-deployment-guide-phase2.md](docs/07-deployment-guide-phase2.md) | Phase 2: prepared views, model tables, semantic model, its test, and a report |
| [docs/08-semantic-model.md](docs/08-semantic-model.md) | The model's tables, relationships and 39 measures with their DAX |
| [docs/09-deployment-guide-phase3.md](docs/09-deployment-guide-phase3.md) | Phase 3: data agent and its test, ontology, operations agent, and how to show them |
| [docs/10-ontology.md](docs/10-ontology.md) | The ontology's entity types, properties and relationships with the tables behind them |
| [docs/11-deployment-guide-phase4.md](docs/11-deployment-guide-phase4.md) | Phase 4: create the Fabric app, deploy it, check its connections, show it |
| [docs/12-deployment-guide-phase5a.md](docs/12-deployment-guide-phase5a.md) | Phase 5a: send a command from Fabric to a turbine and see it take effect |
| [docs/13-deployment-guide-phase5b.md](docs/13-deployment-guide-phase5b.md) | Phase 5b: the operations agent proposes a curtailment with what it costs, you approve it in Teams, the turbine follows |
| [docs/14-deployment-guide-phase5c.md](docs/14-deployment-guide-phase5c.md) | Phase 5c: the edge records what it was told, and the command center and the twin show who asked and whether the turbine followed |
| [app/README.md](app/README.md) | The twin: what is in the folder, how it gets its values, what the picture means |
| [docs/06-upgrade-from-first-delivery.md](docs/06-upgrade-from-first-delivery.md) | Bring a deployment of the first version up to this one |
| [docs/02-demo-runbook.md](docs/02-demo-runbook.md) | How to inject a fault, what to show, and the story in the history behind it |
| [docs/04-use-cases-and-data-audit.md](docs/04-use-cases-and-data-audit.md) | Who asks what at a wind farm, how the measures are defined, which data answers which question, and what is not modelled |
| [docs/05-question-bank.md](docs/05-question-bank.md) | 43 questions from six roles; [docs/question-bank-example-answers.md](docs/question-bank-example-answers.md) shows the answers for one run |
| [docs/00-architecture.md](docs/00-architecture.md) | The whole solution across all phases, design decisions, security, what was verified |
| [docs/data-contracts.md](docs/data-contracts.md) | Topics, message formats, commands, reference files, history tables column by column |
| [docs/troubleshooting.md](docs/troubleshooting.md) | What to check when a step does not behave as described |
| [docs/03-roadmap.md](docs/03-roadmap.md) | Phase 5, further options, and what Phases 2 to 4 delivered |
| [docs/phase1-validation-log.md](docs/phase1-validation-log.md), [docs/phase2-validation-log.md](docs/phase2-validation-log.md), [docs/phase3-validation-log.md](docs/phase3-validation-log.md), [docs/phase4-validation-log.md](docs/phase4-validation-log.md), [docs/phase5-validation-log.md](docs/phase5-validation-log.md) | The obstacles of the live deployments and what was changed for each; what was seen, what was reported, and what was checked before a first run |

## Repository layout

| Path | Content |
|---|---|
| `config/` | `demo.env.example`, the template of the one settings file all scripts read. A deployment by hand copies it to `config/demo.env`; the runner makes a copy for each of its deployments under `.deploy/` |
| `infra/` | Scripts that run on your workstation: create the VM, deploy Azure IoT Operations, connect the edge to Fabric; `vm.sh` to start, stop, reach and update the VM; `rebuild-env.sh` to rebuild the settings file from what is deployed; `99-cleanup.sh` to remove a deployment |
| `edge/scripts/` | Scripts that run on the edge VM, started from the workstation through `infra/vm.sh ssh`: prepare the host, connect to Azure Arc, deploy the simulator, sync reference data, control the simulator |
| `edge/k8s/` | Kubernetes manifests for the simulator and a diagnostic MQTT client |
| `edge/dataflows/` | The Azure IoT Operations data flow definition |
| `edge/reference-sync/` | Uploads reference files to OneLake |
| `simulator/` | The turbine simulator, the climate model, the history generator and the site generator (Python), their tests and the Dockerfile |
| `data/reference/` | Generated site definition, master data, contracts, people, GIS layers and terrain |
| `data/sop/` | Operating procedures |
| `data/samples/` | 45 minutes of sample messages with one gearbox fault, and its ground truth |
| `fabric/kql/` | Eventhouse tables, update policies, OneLake availability, validation queries, live questions; for Phase 5 the table the agent decides on and the command log |
| `fabric/notebooks/` | Eleven notebooks. 01 to 04, Phase 1: load the reference tables, generate the history, refresh the forecast, answer the question bank. 05 to 08, Phase 2: model tables, semantic model, its test, report. 09 to 11, Phase 3: build the data agent, test it, build the ontology |
| `fabric/data-agent/`, `fabric/ontology/`, `fabric/operations-agent/` | Phase 3: the data agent's instructions and example queries, the ontology's definition, the operations agent's goals and instructions. Generated from `tools/agent_spec.py` |
| `app/` | Phase 4: the twin. `overlay/` holds the page (React, Three.js) and the seven functions; `create-app.sh` puts them on Microsoft's Rayfin template; `create-principal.sh` sets up the service principal for real-time values; `preview/` is the twin on sample data in one file; `test/` the tests of its code |
| `tools/` | Builds the notebooks from their sources; the question bank; the semantic model's definition (`model_spec.py`) and the builder of the Phase 2 notebooks; the definition of the agents and the ontology (`agent_spec.py`), the builder of the Phase 3 files and the check of the T-SQL example queries; local Spark runs of the notebooks; offline KQL checks, one for the grammar and one against the tables' columns and types; guards and scenario tests for the shell scripts |

## The demo in one minute

On the workstation, in the root folder of the repository:

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh wind --mean 11 --duration 60m
bash infra/vm.sh ssh bash ./edge/scripts/inject-anomaly.sh     # gearbox degradation on WT-07, clears by itself after 15 minutes
```

In Fabric, the validation queries show WT-07's gearbox vibration and oil temperature pulling away from its neighbours, the alarms, the controller derating the turbine, the production gap, and the return to normal. The question bank then shows that this was coming: four months of drift, rising iron in the oil, the same failure on WT-02 a year earlier, an inspection planned in two weeks and a warranty that ends on 31 December.

## Try it without Azure and Fabric

```bash
cd simulator
pip install -r requirements-dev.txt
python -m pytest                                                              # 361 tests
SITE_FILE=../data/reference/site.json SINK=stdout python -m windfarm_sim | head -n 20   # live messages
python -m windfarm_sim.history --site ../data/reference/site.json --out /tmp/history    # two years of history as CSV
cd .. && bash tools/script-tests/run.sh                                       # the shell scripts against stand-in commands
explorer.exe app/preview    # on WSL: then open windfarm-twin-preview.html, the 3D twin on sample data
```

See [simulator/README.md](simulator/README.md).
