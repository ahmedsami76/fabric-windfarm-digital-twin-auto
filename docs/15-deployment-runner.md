# The deployment runner

`tools/deploy.py` deploys the demo step by step, from an empty subscription and an existing Fabric capacity to the twin in a workspace. It starts the scripts and notebooks of this repository in the order of the guides, looks at Azure and Fabric before and after every step, and stops with an exact instruction wherever a person has to act.

**Status. Written on 25 November 2026. Its first command on a tenant, `preflight`, was run the same morning and ended after six minutes at one check, the VM sizes, which the Azure CLI did not answer; that check is a different call now and can no longer end a run. No other check of that run was seen, and nothing of `apply` has run.** Everything it does was exercised against stand-ins on the computer it was written on (53 tests, 22 planted faults, all caught). Most of what it starts, the scripts of `infra/` and `edge/` and the notebooks, ran on a tenant between 19 and 25 November, started by hand. [What has been proven where](#what-has-been-proven-where) keeps the two apart, and [Unproven on a tenant](#unproven-on-a-tenant) lists what your first run decides. Expect that first run to find something; send me what it prints.

It does not replace the guides. Each step names the guide's step it comes from, and the guides remain the way to deploy by hand or to understand what a step does.

## What it will never do

- Change a tenant setting, create a capacity, or move a workspace to another capacity.
- Work in a resource group or a workspace that it did not create itself.
- Grant a role outside the demo's resource group or workspace, or grant any role without `--approve-role-changes`.
- Register a resource provider: that changes the whole subscription, and is left to you with the commands.
- Delete anything. Removing a deployment stays with `bash infra/99-cleanup.sh`.
- Run notebook 12 or 13, publish to the control topic, or inject a fault. It has no code that could.
- Click through a portal. Where there is no documented API, it says what to do and waits.
- Print or store a token, a key or a connection string.

## Before you start

Unpack the archive and work in its folder. On the edge VM the scripts keep their copy under `~/fabric-windfarm-digital-twin`, whatever the folder is called here.

```bash
python3 -m zipfile -e fabric-windfarm-digital-twin-auto.zip . && cd fabric-windfarm-digital-twin-auto
```


- The Azure CLI, signed in as yourself: `az login`. A service principal is refused, because several steps accept a person only.
- The Azure CLI extension `azure-iot-ops` on this computer: `az extension add --name azure-iot-ops --yes`. A workstation that has run the guides has it. Preflight says when it is missing; the runner never lets the CLI install one on the way.
- Python 3.10 or newer, `bash`, `ssh`. For Phase 4, Node.js 22 as in step 2 of [11-deployment-guide-phase4.md](11-deployment-guide-phase4.md).
- A Fabric capacity that you may create workspaces on. For Phase 3 a paid one.
- No `config/demo.env` yet. The runner writes it. A settings file from a deployment made by hand is refused; move it away and keep it.

## Plan, apply, resume

Every command is typed in the repository folder.

**1. See what stands in the way.** Changes nothing.

```bash
python3 tools/deploy.py preflight --up-to phase4
```

While it looks, it prints one line for each check as it starts, and the seconds for any that took five or more. Looking is a dozen or more calls to the Azure CLI, each a few seconds. Every call has a time limit of three minutes; a check that cannot be made becomes one `BLOCKED` line, and the others are still made. (The first issue printed nothing until all were done, which looked like a hang, and then ended at the first call that ran out of time.)

**2. Read the plan.** Changes nothing in Azure or Fabric. The first plan writes `config/demo.env` with generated names; `LOCATION` and `VM_SIZE` in it are yours to change before the first apply.

```bash
python3 tools/deploy.py plan --approve-role-changes
```

The plan begins with the target: tenant, subscription, resource group, workspace, capacity, and who you are signed in as. Then every step with one of these words:

| Word | Meaning |
|---|---|
| `done` | It is there. The runner looked |
| `will run` | The runner does it on apply; the line below says what it changes |
| `YOUR STEP` | Only a person can do it; the lines below say exactly what |
| `needs approval` | Waits for `--approve-role-changes`, `--allow-preview` or `--opt-in` |
| `BLOCKED` | Something is wrong, and the lines below say what to do |
| `DRIFT, will be redone` | The checkpoint says done and the cloud says otherwise |
| `optional, yours` | Does not hold the deployment up |

It ends with `Plan 3f9c2a71b0de`, the identifier of what you have just read.

**3. Carry it out.** The same options, and the identifier.

```bash
python3 tools/deploy.py apply --approve 3f9c2a71b0de --approve-role-changes --confirm phase1.tenant_settings
```

Apply shows the target again, compares the plan with the one you approved, and refuses when anything differs: the tenant or subscription, the options, a file that a step uses, or something that changed in the cloud. Then it runs the steps in order and stops at the first that needs you, fails, or is still running.

**4. Resume.** Run the same apply again. It looks at every step before it does anything, so what is there is not made a second time. The same approval holds as long as nothing drifted.

| Exit code | Meaning | What to do |
|---|---|---|
| 0 | Everything up to the chosen phase is in place | |
| 1 | A step failed | Read its last lines, fix, apply again |
| 2 | Refused: wrong target, changed plan, another apply running | Read why; usually `plan` again |
| 3 | Blocked: a person has to act | Do what it says, apply again |
| 4 | Something in Fabric is still running | Apply again later; it asks about that first |

**5. See where things stand.** Changes nothing.

```bash
python3 tools/deploy.py status
```

### Options

| Option | For |
|---|---|
| `--up-to phase1` to `phase4` | The last phase to include. Default `phase1` |
| `--approve-role-changes` | The role assignments the plan lists: for the VM's identity on the resource group, by the Azure CLI for the schema registry on its storage account, and for the two identities of the edge in the workspace |
| `--confirm STEP` | You confirm what the runner cannot read: `phase1.tenant_settings`, `phase3.tenant_settings`, `phase4.tenant_settings`, `p2.acceptance`, `p5a.isolation`. The checkpoint keeps who and when |
| `--allow-preview ontology` | Let the runner run notebook 11. Without it the ontology is optional and yours |
| `--opt-in pip-jobs` | Let the runner try notebooks 06 to 10 as jobs. Not documented to work: see below. With it, notebook 09 also needs `--allow-preview data-agent-sdk` |
| `--enable-phase5a-isolated-simulator` | Also provision the command path of Phase 5a, switched off |
| `--regenerate-history LABEL` | Run notebook 02 again, once for this label |
| `--acknowledge ID` | A resource or item in the demo's group or workspace that the runner does not know belongs there |
| `--new-names` | With `plan`, while nothing exists: choose another suffix |

## Names

The first plan picks three random characters and puts them at the end of every name that has to be unique outside the demo's own workspace:

```bash
RESOURCE_GROUP="rg-windfarm-edge-3x9"
VM_NAME="vm-windfarm-edge-3x9"
STORAGE_ACCOUNT_NAME="sawindfarm3x9"
FABRIC_WORKSPACE_NAME="WindFarmDigitalTwin-3x9"
```

and likewise the cluster, the instance, the custom location, the schema registry and the device registry namespace. The subscription is the one the Azure CLI is on. The Custom Locations object ID and the capacity are looked up and written into the file; when you can see more than one active capacity, the runner lists them and you put one ID into `FABRIC_CAPACITY_ID`.

Items inside the workspace keep the names of the guides (`WindFarmEH`, `WindFarmLH`, `es-windfarm-edge`, the notebooks, `WindFarmTwin`). The notebooks and the app find them by name, and in a workspace that holds nothing else no name can be taken. The app is told the workspace's name when it is created: `bash app/create-app.sh` writes it into the app's copy of `config.ts`.

Do not edit the generated names. The runner refuses a settings file whose names no longer carry its suffix.

## Who the runner is

Every call the runner makes is made as you, with the sign-in of the Azure CLI. It refuses a service principal. The reason is the steps that accept a person only: the lookup of the Custom Locations object ID in Microsoft Entra ID, the notebooks of Phase 2 that build the model with semantic link, the data agent, the operations agent. One identity for a run also means one answer to "who did this".

Where the demo itself runs, it uses managed identities and no keys, as the guides do: the VM's identity onboards the cluster and uploads the reference files, and the identity of the Azure IoT Operations extension sends to the eventstream.

Most Fabric operations the runner uses also accept a service principal or a managed identity; the table under [Sources](#sources) says which were read. Running those parts under a federated workload identity, in a pipeline, is possible and not built: it would need two sign-ins in one run, and the first live run should come first.

## How it knows the target is its own

- **The resource group** carries the tag `windfarm-demo-deployment` with the suffix, and its ID is in the checkpoint. A group of that name without the tag is never used.
- **The workspace** has the suffix in its description, and its ID is in the checkpoint. A workspace of that name that the runner did not make is never used.
- **Inside them**, a resource of a provider the demo does not use, or an item the demo does not create, stops the runner until you move it or name it with `--acknowledge`.
- **The tenant and the subscription** of the first apply are kept. Signed in elsewhere later, every mode refuses.

## Every step

Generated from the runner's own list (`python3 tools/build-runner-docs.py`). "Rests on" is the documented operation or the script; the links are under [Sources](#sources).

<!-- steps: generated by tools/build-runner-docs.py -->

**Before anything is created**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `pre.tools` | The tools the scripts need | check | nothing | looks for az, bash and ssh on this computer |
| `pre.signin` | Signed in to Azure as a person, on the right subscription | check | nothing | az account show |
| `pre.extensions` | Azure CLI extension on this computer | check | nothing | az extension list |
| `pre.rights` | Your roles on the subscription | check | nothing | az role assignment list |
| `pre.providers` | Resource providers registered | check | nothing | az provider show |
| `pre.region` | Region and VM size | check | nothing | Resource SKUs - List, with its location filter |
| `pre.names` | Generated names are free | check | nothing | az storage account check-name |
| `pre.custom_locations` | Custom Locations object ID | check | nothing | az ad sp show |
| `pre.fabric` | The Fabric API answers you | check | nothing | GET /v1/workspaces |
| `pre.capacity` | One Fabric capacity, active | check | nothing | GET /v1/capacities |
| `phase1.tenant_settings` | Tenant settings for Phase 1 | you | nothing | Fabric admin portal; no API for a person who is not an administrator |

**Phase 1**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `p1.resource_group` | Resource group of the demo | the runner | creates the resource group with the tag windfarm-demo-deployment | az group create |
| `p1.edge_vm` | Edge VM | the runner | VM, network, SSH rule for your address, daily shutdown | infra/01-create-edge-vm.sh, without its provider registration and role assignments |
| `p1.vm_identity_roles` | Roles for the VM's identity, on the resource group only | the runner, after `--approve-role-changes` | 'Kubernetes Cluster - Azure Arc Onboarding' and 'Reader' for the VM's managed identity, both on the demo's resource group. The manual guide gives Reader on the subscription; the runner does not | az role assignment create |
| `p1.edge_host` | K3s and tools on the VM | the runner | installs K3s and the Azure CLI on the VM | edge/scripts/02-prepare-host.sh |
| `p1.arc` | Cluster connected to Azure Arc | the runner | Arc-enabled cluster with custom locations | edge/scripts/03-arc-enable.sh (az connectedk8s connect, enable-features) |
| `p1.iot_operations` | Azure IoT Operations | the runner, after `--approve-role-changes` | storage account, schema registry, device registry namespace, the instance. The Azure CLI gives the schema registry's identity 'Storage Blob Data Contributor' on that storage account | infra/04-deploy-iot-operations.sh (az iot ops init, create) |
| `p1.simulator` | Turbine simulator on the edge | the runner | builds the simulator image on the VM and starts it | edge/scripts/05-deploy-simulator.sh |
| `p1.workspace` | Fabric workspace of the demo | the runner | creates the workspace on the capacity shown | Workspaces - Create Workspace |
| `p1.eventhouse` | Eventhouse and KQL database | the runner | Eventhouse WindFarmEH with its database | Eventhouse - Create Eventhouse; KQL Database - Create KQL Database |
| `p1.kql_schema` | Tables, mapping and update policies | the runner | runs the two database scripts of step 6.2 | Kusto REST API, /v1/rest/mgmt, .execute database script |
| `p1.lakehouse` | Lakehouse | the runner | Lakehouse WindFarmLH | Lakehouse - Create Lakehouse |
| `p1.onelake_availability` | OneLake availability of the typed tables | the runner | turns OneLake availability on for six tables | Kusto REST API, .alter-merge table policy mirroring |
| `p1.shortcuts` | Shortcuts to the live tables | the runner | six shortcuts under Tables of the Lakehouse | OneLake Shortcuts - Create Shortcut (target: KQL database) |
| `p1.eventstream` | Eventstream with direct ingestion into RawEvents | the runner | eventstream es-windfarm-edge: a custom endpoint, and the Eventhouse as destination with the mapping RawEvents_mapping | Learn: Create an Eventstream with an Eventhouse DirectIngestion destination by using APIs |
| `p1.edge_connection` | Where the edge sends to | the runner | writes the bootstrap server and the topic into the settings file. No key is read out of the answer | Topology - Get Eventstream Source Connection |
| `p1.workspace_access` | Workspace access for the two identities of the edge | the runner, after `--approve-role-changes` | Contributor in the demo's workspace for the Azure IoT Operations extension and for the VM | Workspaces - Add Workspace Role Assignment |
| `p1.data_flow` | Data flow from the edge to the eventstream | the runner | endpoint fabric-eventstream and data flow windfarm-to-fabric | infra/06-connect-edge-to-fabric.sh |
| `p1.gate_telemetry` | GATE: fresh telemetry in the Eventhouse | gate | nothing | Kusto REST API, /v1/rest/query |
| `p1.reference_upload` | Reference data uploaded from the edge | the runner | Files/reference and Files/sop of the Lakehouse | edge/scripts/07-sync-reference-data.sh |
| `p1.notebooks` | Notebooks 01 to 04 and the gate notebook imported | the runner | five notebooks, each with the Lakehouse as its default | Notebook - Create Notebook (definition, ipynb) |
| `p1.reference_tables` | Reference tables loaded (notebook 01) | the runner | 13 ref_ tables | Job Scheduler - Run On Demand Item Job (RunNotebook) |
| `p1.history` | Two years of operating history (notebook 02) | the runner | 12 ops_ tables. Run once; again only with --regenerate-history LABEL, once for a label | Job Scheduler - Run On Demand Item Job (RunNotebook) |
| `p1.forecast` | Forecast refreshed and scheduled daily (notebook 03) | the runner | one run of notebook 03 and one daily schedule for it | Job Scheduler - Create Item Schedule |
| `p1.gate_lakehouse` | GATE: shortcuts readable, tables populated | gate | one run of the gate notebook, which reads and writes one small result file | Job Scheduler - Run On Demand Item Job; the job's state is the verdict |

**Phase 2**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `p2.prepared_views` | Prepared views in the Eventhouse | the runner | three functions in the folder Prepared | Kusto REST API, .create-or-alter function |
| `p2.notebooks` | Notebooks 05 to 08 imported | the runner | four notebooks, each with the Lakehouse as its default | Notebook - Create Notebook (definition, ipynb) |
| `p2.model_tables` | Model tables built (notebook 05) | the runner | the star schema in the Lakehouse | Job Scheduler - Run On Demand Item Job (RunNotebook) |
| `p2.semantic_model` | Semantic model built (notebook 06) | you; the runner with `--opt-in pip-jobs` | with --opt-in pip-jobs: runs 06_build_semantic_model as a job, with %pip switched on by the parameter Microsoft documents for pipelines | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p2.acceptance` | Model tested against the Lakehouse (notebook 07) | you; the runner with `--opt-in pip-jobs` | with --opt-in pip-jobs: runs 07_model_acceptance as a job, with %pip switched on by the parameter Microsoft documents for pipelines | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p2.report` | Report built (notebook 08) | you; the runner with `--opt-in pip-jobs` | with --opt-in pip-jobs: runs 08_build_report as a job, with %pip switched on by the parameter Microsoft documents for pipelines | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p2.schedule` | Model tables refreshed every hour | the runner | one hourly schedule for notebook 05 | Job Scheduler - Create Item Schedule (Cron, interval in minutes) |
| `p2.gate` | GATE: model tables populated | gate | one run of the gate notebook | Job Scheduler - Run On Demand Item Job; the job's state is the verdict |

**Phase 3**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `p3.capacity` | A paid capacity for the agents | check | nothing | GET /v1/capacities |
| `phase3.tenant_settings` | Tenant settings for Phase 3 | you | nothing | Fabric admin portal |
| `p3.notebooks` | Notebooks 09 to 11 imported | the runner | three notebooks | Notebook - Create Notebook (definition, ipynb) |
| `p3.data_agent` | Data agent built (notebook 09) | you; the runner with `--opt-in pip-jobs` and `--allow-preview data-agent-sdk` | with --opt-in pip-jobs: runs 09_build_data_agent as a job, with %pip switched on by the parameter Microsoft documents for pipelines | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p3.data_agent_test` | Data agent tested (notebook 10) | you, optional | nothing | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p3.ontology` | Ontology built (notebook 11, preview) | you, optional; the runner with `--allow-preview ontology` | runs notebook 11, which creates the ontology item | Job Scheduler - Run On Demand Item Job (RunNotebook) |
| `p3.agent_readiness` | KQL database prepared for the operations agent | the runner | descriptions of the columns, and the table GearboxVsFleetLive with its update policy | Kusto REST API, .execute database script |
| `p3.operations_agent` | Operations agent set up and started, Teams app installed | you | nothing | none: portal only (preview) |

**Phase 4**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `phase4.tenant_settings` | Tenant setting Fabric Apps | you | nothing | Fabric admin portal |
| `p4.node` | Node.js on this computer | check | nothing | node --version |
| `p4.scaffold` | App created from Microsoft's template, with the twin laid over it | the runner | the folder app/windfarm-twin on this computer; nothing in Fabric | app/create-app.sh |
| `p4.deploy` | App deployed to the workspace | the runner | the Fabric app item WindFarmTwin, its page and its seven functions | npx rayfin up --workspace NAME --item-name NAME (Rayfin 2.0.1) |
| `p4.gate_data_route` | GATE: a data route of the twin answers | gate | nothing; one query against the SQL endpoint of the Lakehouse | SQL analytics endpoint, with a token for https://database.windows.net |
| `p4.eventhouse_principal` | Real-time values: the service principal (optional) | you, optional | nothing | app/create-principal.sh |
| `p4.connection_check` | The app's own connection check (optional) | you, optional | nothing | the app |

**Phase 5a, only with `--enable-phase5a-isolated-simulator`**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `p5a.isolation` | This edge is an isolated simulator | you | nothing | none: a statement only a person can make |
| `p5a.command_path` | Command path provisioned, switched off | the runner | eventstream WindFarmCommands, endpoint fabric-commands, and the data flow fabric-to-windfarm-control with mode Disabled | infra/08-create-command-path.sh; az iot ops dataflow apply with "mode": "Disabled" |
| `p5a.notebook` | Notebook 12 imported, not run | the runner | imports the notebook. It is never run by the runner | Notebook - Create Notebook (definition, ipynb) |
| `p5a.enable` | Switch the command path on and send a command (yours) | you, optional | nothing | docs/12-deployment-guide-phase5a.md |

<!-- end of steps -->

A **gate** is a measurement, not a command: fresh telemetry in the Eventhouse (rows in the last five minutes, twelve turbines, the newest reading under three minutes old, sequence numbers present), tables with rows read through Spark by a notebook that fails when one is empty or stale, and the twin's Lakehouse route asked the question the app asks. A gate that has passed keeps its result with the time it was measured; `status` shows the freshness of now.

## Your steps, and what the runner looks at afterwards

| Step | What you do | What the runner looks for when you apply again |
|---|---|---|
| Resource providers | `az provider register --namespace …`, the lines the plan prints | The registration state of each |
| Tenant settings | A Fabric administrator checks the settings the plan lists | Your `--confirm`. It cannot read them; later steps fail in a telling way when one is off |
| Capacity | Put one ID into `FABRIC_CAPACITY_ID` when you see several | That it exists and is active |
| Eventstream destination, only if Fabric leaves it in `Warning` or no rows arrive | The Get data wizard with the existing mapping, as in step 6.7 of the Phase 1 guide; the block prints the steps | The destination's state, and rows in `RawEvents` |
| Notebooks 06, 07, 08, 09 | Open each, **Run all** | The semantic model, the report and the data agent as items; for 07 your `--confirm p2.acceptance` |
| Operations agent and Teams | Step 9 of the Phase 3 guide | An item of type OperationsAgent named `WindFarmGearboxWatch`. Not whether it runs, and nothing of Teams |
| Sign-in of the app's tool | `npx rayfin login` in `app/windfarm-twin` | It runs `npx rayfin up` again |
| Service principal for real-time values | `bash app/create-principal.sh`, optional | Nothing. The deployment is complete on the Lakehouse route |
| Command path, Phase 5a | Confirm the edge is an isolated simulator; later switch the path on and send | Your `--confirm p5a.isolation`; the data flow's mode |

**Why notebooks 06 to 10 are yours.** Their first cell is `%pip install`. Microsoft documents that inline installation is switched off in notebook runs started by a pipeline, and how to switch it on there with the parameter `_inlineInstallationEnabled`. For a run started through the Job Scheduler API it says nothing. `--opt-in pip-jobs` makes the runner pass that parameter and try; when the job fails it falls back to the instruction above. Nobody has tried it yet.

## Interruption, time limits, drift

- **The checkpoint** is `.deploy/<suffix>/state.json`: every step with its state, the time, and what was measured. It is written in one move, ignored by git, and holds no secret. Keep it: it is the record that the resources are this deployment's.
- **One apply at a time.** A lock file beside the checkpoint refuses a second apply on this computer. The lock of an apply that died is taken over. A second computer has no checkpoint, finds the resources marked as a deployment's, and adopts them only with the same settings file.
- **Long operations.** When Fabric answers "accepted", the address to ask about is written to the checkpoint before the first wait. Apply waits up to 15 minutes for an operation and 45 for a notebook, then ends with exit code 4. The next apply asks about the same operation and starts no second one.
- **A run it did not write down.** Before it starts a notebook, the runner asks Fabric whether a run of that notebook is queued or running, and waits for that one.
- **History.** Notebook 02 is run once. `--regenerate-history 2026-12-01` runs it again, once for that label.
- **Schedules** are created to start ten minutes ahead: Microsoft's reference says a start in the past triggers a job at once. One schedule for a notebook; two switched on is a block.
- **Drift.** A step the checkpoint calls complete whose result is gone shows as `DRIFT` in the plan, changes the plan's identifier, and so needs your approval again.

## Secrets

The runner asks the Azure CLI for tokens (Fabric, the Eventhouse, storage, SQL) and hands each to its redactor at once. Every line it prints, every line of a script's output it shows, and every byte of the checkpoint passes that redactor, which removes the values it was told and anything shaped like a token, a key or a connection string. From Fabric's answer about the eventstream's endpoint, which holds keys, it takes the two names the edge needs and keeps nothing else. The edge authenticates with its managed identity, as in the guides; no key is used anywhere.

## Phase 5a

Off unless you add `--enable-phase5a-isolated-simulator`. Then, after your `--confirm p5a.isolation`:

- `infra/08-create-command-path.sh` runs with `COMMAND_DATAFLOW_MODE=Disabled`: the eventstream `WindFarmCommands`, the endpoint and the data flow exist, and the data flow is switched off, so no message from Fabric becomes a command on the edge.
- Notebook 12 is imported and not run.
- Switching the path on (`bash infra/08-create-command-path.sh`) and every command are yours, from step 3 of [12-deployment-guide-phase5a.md](12-deployment-guide-phase5a.md).

Phases 5b and 5c are not the runner's. Deploy them from their guides.

## Where it differs from the guides

| Guide | Runner | Why |
|---|---|---|
| Step 1 registers eight resource providers | You register them | A change to the whole subscription |
| Step 1 asks `az vm list-skus` for each size | One call to the Resource SKUs API with its location filter; the script is handed the sizes that passed | `az vm list-skus` fetches the sizes of every region. From a workstation it did not answer in five minutes on 25 November |
| Step 1 gives the VM's identity Reader on the subscription | Reader on the resource group | The runner grants nothing outside the demo. **Unproven**: whether Arc onboarding from the VM then still passes its provider check. If step 3 fails on it, grant Reader on the subscription by hand for the length of that step |
| Step 6.4 and 6.7: the eventstream in the portal, the mapping chosen in a wizard | Created from a definition with the mapping named in it | Microsoft's article "Create an Eventstream with an Eventhouse DirectIngestion destination by using APIs" |
| Steps 6.5 and 7.3: access and shortcuts in the portal | The Fabric API | Documented operations |
| KQL pasted into a query window | Sent to the same database over the Kusto REST interface, the same text | |
| Notebooks imported by hand, Lakehouse attached by hand | Imported with the Lakehouse in their metadata | Microsoft's article on the notebook API |
| Notebook 04 run for the expected answers | Imported, not run | It changes nothing and nobody reads a job's output |

## What has been proven where

| | Documented by Microsoft | Run against stand-ins here | Run on a tenant |
|---|---|---|---|
| The engine: plan, approval, checkpoint, lock, resume, redaction | not applicable | yes | The settings file of a first run, with its generated names: yes, 25 November. Everything else: **no** |
| Scripts `infra/01`, `04`, `06`, `edge/scripts/02`, `03`, `05`, `07`, `app/create-app.sh`, `npx rayfin up` | their commands, yes | started by the runner: yes | by hand: yes, 19 to 25 November. Started by the runner, and `infra/01` with `DEPLOY_RUNNER=1`: **no** |
| Workspace, Eventhouse, KQL database, Lakehouse, shortcuts, role assignment, notebook import, schedules through the Fabric API | yes, each read on 25 November | yes | **no**. The workspace role assignment by a script of Phase 4: yes |
| Eventstream with direct ingestion and a named mapping | yes | yes | **no** |
| Endpoint of the eventstream read through the Fabric API | yes | yes | yes, by notebook 12 |
| KQL and queries over the Kusto REST interface with the Azure CLI's token | for Azure Data Explorer, yes | yes | with a notebook's token and with a service principal: yes. From a workstation: **no** |
| Notebooks as jobs | yes | yes | notebook 12, from a script: yes. Notebooks 01 to 05 and 11: **no** |
| Gate notebook, and reading its result file over the OneLake API | the APIs, yes | its logic, yes | **no** |
| Lakehouse route probe with the Azure CLI's token | the driver's sign-in, yes | the hand-over only | the same query by the app: yes. From a workstation: **no** |
| Notebooks 06 to 10 as jobs with `%pip` | for pipelines only | yes | **no**; by hand: yes |
| Data flow created with mode `Disabled` | yes | yes | **no** |

## Unproven on a tenant

In the order a first run meets them:

1. **`infra/01` under the runner**: without the provider registration, the group creation and the role assignments.
2. **Arc onboarding with Reader on the resource group** instead of the subscription.
3. **The Eventhouse's own database.** The runner waits two minutes for the database Fabric gives a new Eventhouse, then creates one. Whether the API-created Eventhouse brings one is not written where I read.
4. **The Kusto audience for the Azure CLI's token** on a Fabric Eventhouse.
5. **The eventstream definition**: a custom endpoint with empty properties, and the destination with the Eventhouse's item ID as Microsoft's article has it. That article does not say how the database is chosen; this demo's Eventhouse has one. Microsoft warns that a property set which does not fit is accepted and ingests nothing; the gate after it is there for that, and the fallback is the wizard.
6. **Whether ingestion created this way reads JSON without a format label**, which the wizard needed set by hand.
7. **Shortcuts to KQL tables through the API** before the first write of OneLake availability.
8. **Notebook import**: the part named `notebook-content.ipynb` (the REST reference; an older article says `artifact.content.ipynb`), and the default Lakehouse taking effect for a job.
9. **Notebooks 01, 02, 03, 05 as jobs**: they have only run interactively. Parameters reaching the gate notebook's cell.
10. **The schedule payload** with unzoned times and `UTC`, which is how Microsoft's samples write it while its text asks for a `Z`.
11. **The result file of the gate** over the OneLake API. The verdict does not depend on it.
12. **The SQL probe** with a token for `https://database.windows.net`.
13. **`npx rayfin up` started without a terminal**, and how it says that it is not signed in. The runner recognises the words sign in, log in, keychain and 401; anything else is reported as a failure with the tool's own lines.
14. **The times.** No step has been timed under the runner, so this document promises none. From the second issue on, every check that takes five seconds or more prints its seconds: the first numbers will come from your run.

## Tests

`simulator/tests/test_deploy_runner.py`, 53 tests against `simulator/tests/deploy_fakes.py`, a pretend Azure and Fabric that answer in the documented shapes and record every change:

| Asked for | Test |
|---|---|
| Wrong-target refusal | a settings file made by hand; a resource group and a workspace of the right name that the runner did not make; another subscription or tenant after the start; things in the group or workspace that are not the demo's |
| Interrupted deployment and resume | an operation Fabric has not finished; a run started by an apply that died; a failed script; a command that returns without its result; two applies at once and a dead one's lock |
| No duplicates on a second apply | every write of a full Phase 1 counted, and a second apply adds none: one group, one workspace, four jobs, one schedule, two plus two role assignments |
| Unsupported API handoffs | a destination in `Warning`; no rows after the wait; the gate notebook failing; each operator step of Phases 2 to 4 in turn; the fallback from a failed job to the person |
| Secret redaction | tokens, both keys, the connection string and the middle of each key searched in everything printed and written; a script that prints a secret; the redactor by itself; the checkpoint file |
| After the first run on a tenant | every check announced as it starts; one check that cannot be made is one line; a missing CLI extension is the operator's; the Azure CLI is started without a keyboard; the VM sizes asked with one filtered call, which cannot stop a run and is not asked again once the VM exists |
| And | approval of exactly one plan; a changed file and drift void it; role changes wait and stay on the resource group; Phase 5a absent by default, switched off when present, notebooks 12 and 13 impossible to run; the history once and once per label; the schedule in the future; preflight; the KQL splitter; the gate notebook's logic; the real adapters |

Twenty-two faults were planted in the runner one at a time. Twenty-one made a test fail at once. The twenty-second, a key written into the settings with its last character cut off, passed until the test also searched for the middle of each key.

```bash
cd simulator && python3 -m pytest -q tests/test_deploy_runner.py
```

## Sources

Microsoft Learn, read on 25 November 2026.

- [Create an Eventstream with an Eventhouse DirectIngestion destination by using APIs](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/api-kusto-pull-destination): the destination's properties; the item ID is the Eventhouse's; the connection name has at most 40 characters.
- [Eventstream REST API](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/eventstream-rest-api): `CustomEndpoint` as a source and a destination type; the two property sets of an Eventhouse destination, and the `Warning` state of a wrong one.
- [Eventstream definition](https://learn.microsoft.com/rest/api/fabric/articles/item-management/definitions/eventstream-definition): shows an event hub source and a Lakehouse destination only, which is why the first article matters.
- [Workspaces - Create Workspace](https://learn.microsoft.com/en-us/rest/api/fabric/core/workspaces/create-workspace), [Add Workspace Role Assignment](https://learn.microsoft.com/en-us/rest/api/fabric/core/workspaces/add-workspace-role-assignment), [Create KQL Database](https://learn.microsoft.com/en-us/rest/api/fabric/kqldatabase/items/create-kql-database), [Create Shortcut](https://learn.microsoft.com/en-us/rest/api/fabric/core/onelake-shortcuts/create-shortcut) and [List Shortcuts](https://learn.microsoft.com/en-us/rest/api/fabric/core/onelake-shortcuts/list-shortcuts), [Create Notebook](https://learn.microsoft.com/en-us/rest/api/fabric/notebook/items/create-notebook): users, service principals and managed identities are supported; none is marked preview.
- [Job Scheduler - Run On Demand Item Job](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/run-on-demand-item-job), [Get Item Job Instance](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/get-item-job-instance), [List Item Job Instances](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/list-item-job-instances), [Create Item Schedule](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/create-item-schedule), [List Item Schedules](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/list-item-schedules). A job instance has a state and a failure reason and no exit value, which is why the gate notebook passes or fails as a whole. The reference writes the job type into the path; Microsoft's notebook article writes it as `?jobType=RunNotebook`, the form that ran here on 24 November and the one the runner uses.
- [Lakehouse - List Tables](https://learn.microsoft.com/en-us/rest/api/fabric/lakehouse/tables/list-tables): marked preview, so not used; the gate notebook reads the tables instead.
- [Resource SKUs - List](https://learn.microsoft.com/en-us/rest/api/compute/resource-skus/list): `$filter=location eq '…'`, the only filter it supports; a size's `restrictions` of type `Location` with the reason.
- [Manage Apache Spark libraries in Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/data-engineering/library-management): inline installation in pipeline runs, and `_inlineInstallationEnabled`.
- [Create a data flow in Azure IoT Operations](https://learn.microsoft.com/en-us/azure/iot-operations/connect-to-cloud/howto-create-dataflow) and the [Dataflow REST reference](https://learn.microsoft.com/en-us/rest/api/iotoperations/dataflow/create-or-update): `mode`, `Enabled` or `Disabled`.
