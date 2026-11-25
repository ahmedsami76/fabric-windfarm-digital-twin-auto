# The deployment runner

`tools/deploy.py` deploys the demo step by step, from an empty subscription and an existing Fabric capacity to the twin in a workspace. It starts the scripts and notebooks of this repository in the order of the guides, looks at Azure and Fabric before and after every step, and stops with an exact instruction wherever a person has to act.

**Status. Written on 25 November 2026. Its first command, `preflight`, ran on a tenant four times that day; three of the runs were sent to me. They showed errors of the runner, corrected in the second and third issue; the run of 15:40 showed the third issue reading the roles and the capacities rightly. The fourth issue added what was asked for after that run: the runner asks its questions itself (the region, the capacity, the workspace, the VM size), and can make a Fabric capacity when you say so. This fifth issue answers the request of 16:35: no settings file is prepared or kept in `config/`; every deployment gets its three random characters when it is started and keeps its settings beside its checkpoint, so one folder serves build after build, in one tenant or in several. See [Deployments](#deployments). At 17:17 the questions ran on a tenant for the first time, and the one about a new capacity said that F16 is not offered in Central US, where the same subscription runs an F16: the runner had read one entry of Azure's list of SKUs instead of all. This sixth issue reads the list whole, never takes a list that does not name the SKU for a refusal, shows the list with every such message, and leaves a region the list does not name to you. Of `plan`, the questions up to that point have run on a tenant; the plan itself and `apply` have not.** Everything the runner does was exercised against stand-ins on the computer it was written on (100 tests, 151 planted faults, all caught). Most of what it starts, the scripts of `infra/` and `edge/` and the notebooks, ran on a tenant between 19 and 25 November, started by hand. [What has been proven where](#what-has-been-proven-where) keeps the two apart, and [Unproven on a tenant](#unproven-on-a-tenant) lists what your next run decides. Expect it to find something; send me what it prints.

It does not replace the guides. Each step names the guide's step it comes from, and the guides remain the way to deploy by hand or to understand what a step does.

## What it will never do

- Change a tenant setting.
- Make a Fabric capacity unless you answered yes to that question and approved the step. It never pauses, resumes, resizes or deletes a capacity, and never moves a workspace to another one.
- Work in a resource group that it did not create itself, or in a workspace that it did not create, with one exception: an existing workspace that you chose in answer to its question and that is empty.
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
- A capacity that can hold Fabric items and that you may create workspaces on: an F SKU, a trial, or a P SKU with Fabric enabled. For Phase 3 a paid one. A Premium Per User, A or EM capacity holds Power BI items only, and the runner refuses it. Or none: the runner makes an F16 when you say so. See [The capacity](#the-capacity).
- Nothing to fill in. No settings file ships with the repository and none is prepared: the first plan starts a deployment, picks its three random characters and writes its settings to `.deploy/<suffix>/demo.env`. `config/demo.env` is the file of a deployment made by hand, from the guides; the runner neither reads nor writes it. See [Deployments](#deployments).

## Plan, apply, resume

Every command is typed in the repository folder.

**1. See what stands in the way.** Changes nothing.

```bash
python3 tools/deploy.py preflight --up-to phase4
```

While it looks, it prints one line for each check as it starts, and the seconds for any that took five or more. Looking is a dozen or more calls to the Azure CLI, each a few seconds. Every call has a time limit: one minute for the two questions a deployment can do without (your roles, the VM sizes), three minutes for the others. A check that cannot be made becomes one line, `NOT CHECKED` when the deployment can go on without it and `BLOCKED` otherwise, and the others are still made.

Three answers are kept in the checkpoint for twelve hours: your roles, the resource providers, the VM sizes. So is "could not be read". The next preflight, plan or apply shows them with `[asked 12 min ago; --recheck asks again]` instead of waiting again. A check that found something missing is never kept: it is asked until it passes.

Preflight shows the same table as a plan, for the prerequisites only, and no plan identifier: there is nothing in it to approve.

**2. Answer the questions and read the plan.** Changes nothing in Azure or Fabric. The first plan in a folder starts a deployment: it picks three random characters, makes every name from them and writes the settings to `.deploy/<suffix>/demo.env`. In a terminal it then asks what is yours to decide, before it looks at anything: see [The questions](#the-questions).

```bash
python3 tools/deploy.py plan --approve-role-changes
```

The plan begins with the target: tenant, subscription, resource group, workspace, capacity, and who you are signed in as. Then every step with one of these words:

| Word | Meaning |
|---|---|
| `done` | It is there. The runner looked |
| `confirmed by you` | It passes on your `--confirm`. The runner cannot read it |
| `NOT CHECKED` | The runner could not read it: a question without an answer, or a capacity Fabric does not list for you. It does not stop the deployment; the step that depends on it says so if it fails |
| `will run` | The runner does it on apply; the line below says what it changes |
| `will be measured` | A gate: the runner measures it when the steps before it are done, and waits for it |
| `YOUR STEP` | Only a person can do it; the lines below say exactly what |
| `needs approval` | Waits for `--approve-role-changes`, `--allow-preview` or `--opt-in` |
| `BLOCKED` | Something is wrong, and the lines below say what to do |
| `DRIFT, will be redone` | The checkpoint says done and the cloud says otherwise |
| `optional, yours` | Does not hold the deployment up |

It ends with `Plan 3f9c2a71b0de`, the identifier of what you have just read, and with the apply command written out, options included.

**3. Carry it out.** The command the plan printed, with `--confirm` for the steps of yours that are done.

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
| `--approve-capacity-creation` | Making the Fabric capacity you chose to have made. A yes to that question approves it for the plan of the same run; the apply command the plan prints carries the option |
| `--no-input` | Preflight and plan ask nothing. Where an answer is missing the plan blocks and names the setting |
| `--ask` | In a terminal: ask again every question whose subject does not exist yet |
| `--approve-role-changes` | The role assignments the plan lists: for the VM's identity on the resource group, by the Azure CLI for the schema registry on its storage account, and for the two identities of the edge in the workspace |
| `--confirm STEP` | You confirm what the runner cannot read: `phase1.tenant_settings`, `phase3.tenant_settings`, `phase4.tenant_settings`, `p2.acceptance`, `p5a.isolation`. The checkpoint keeps who and when |
| `--allow-preview ontology` | Let the runner run notebook 11. Without it the ontology is optional and yours |
| `--opt-in pip-jobs` | Let the runner try notebooks 06 to 10 as jobs. Not documented to work: see below. With it, notebook 09 also needs `--allow-preview data-agent-sdk` |
| `--enable-phase5a-isolated-simulator` | Also provision the command path of Phase 5a, switched off |
| `--regenerate-history LABEL` | Run notebook 02 again, once for this label |
| `--acknowledge ID` | A resource or item in the demo's group or workspace that the runner does not know belongs there |
| `--new` | With `preflight` or `plan`: start another deployment in this folder, with a new random suffix. The earlier ones stay as they are |
| `--deployment SUFFIX` | Work on another deployment of this folder, in any mode, and make it the current one |
| `--recheck` | Ask again what was asked within the last twelve hours and kept: your roles, the resource providers, the VM sizes |

## The questions

Preflight and plan ask them, in a terminal, before they look at anything. Enter takes the answer in brackets. Every answer is written to the settings of the deployment, `.deploy/<suffix>/demo.env`, and kept in the checkpoint with who gave it and when. No answer changes anything in Azure or Fabric: it becomes a line of the plan, and the plan still has to be approved.

| Question | What you can answer | What the answer does |
|---|---|---|
| Azure region of the edge | One of the nine regions Azure IoT Operations supports, by number or name | `LOCATION` |
| Fabric capacity: create a new one? | Yes: a region for it, with one proposed. No: one from the list of capacities that can hold the demo; the others are listed with the reason | A new capacity becomes the step `p1.capacity` of the plan. An existing one becomes `FABRIC_CAPACITY_ID` |
| Fabric workspace: create a new one? | Yes: the generated name. No: one of the workspaces on the capacity you chose, provided it is empty | A chosen workspace is held by its ID in `FABRIC_WORKSPACE_ID` and keeps its name |
| VM size | A size you know your subscription is offered, to be tried first | The order of `VM_SIZE`. Asked only when Azure did not say which sizes you are offered |

- **Asked once.** A question is asked again when its answer no longer holds, for example a capacity in the settings that cannot hold the demo, and with `--ask`.
- **Not asked about what exists.** Once the resource group, the capacity, the workspace or the VM is there, its question is closed: a deployment stays where it is.
- **Not asked without a keyboard, with `--no-input`, in `apply` and in `status`,** and not while an apply is running. The output may go through a pipe, for example to `tee`. The plan then blocks where an answer is missing and names the setting to fill in, as before.
- **Ctrl+C or a closed terminal at a question** ends the run with one line. The answers given up to there are kept.

A run in which every answer is Enter:

```text
A few questions first. Enter takes the answer in brackets. The answers go into the settings of this deployment; nothing is changed in Azure or Fabric by them.

Azure region of the edge: the VM and Azure IoT Operations
    ...
    6. southcentralus   (now)
  Region [6]

Fabric capacity
  Fabric lists 2 for you, 1 of which can hold the demo.
  Create a new Fabric capacity for this demo (F16)? [y/N]
  Capacities you can use:
    1. fabcentralussm01 (F32, Central US)   d21d9da9-4054-4790-bc82-71aad3a91152
    -  Premium Per User - Reserved (PP3, Central US): cannot hold the demo: a Premium Per User capacity. It holds Power BI items only
  Capacity [1]

Fabric workspace
  Create a new workspace for this demo, WindFarmDigitalTwin-064? [Y/n]

Chosen: edge in southcentralus; capacity fabcentralussm01 (F32, Central US); workspace WindFarmDigitalTwin-064, to be made. Written to .deploy/064/demo.env. Nothing was changed in Azure or Fabric.
```

## Names

A deployment gets three random characters at the moment it is started, by the first plan in a folder or by `plan --new`. They go at the end of every name that has to be unique outside the demo's own workspace:

```bash
RESOURCE_GROUP="rg-windfarm-edge-3x9"
VM_NAME="vm-windfarm-edge-3x9"
STORAGE_ACCOUNT_NAME="sawindfarm3x9"
FABRIC_WORKSPACE_NAME="WindFarmDigitalTwin-3x9"
```

and likewise the cluster, the instance, the custom location, the schema registry and the device registry namespace, and `fabwindfarm3x9` for a capacity the runner makes. The subscription is the one the Azure CLI is on. The Custom Locations object ID is looked up and written into the settings. The capacity and the workspace are yours to choose: plan asks, as described under [The questions](#the-questions).

Items inside the workspace keep the names of the guides (`WindFarmEH`, `WindFarmLH`, `es-windfarm-edge`, the notebooks, `WindFarmTwin`). The notebooks and the app find them by name, and in a workspace that holds nothing else no name can be taken. The app is told the workspace's name when it is created: `bash app/create-app.sh` writes it into the app's copy of `config.ts`.

Do not edit the generated names. The runner refuses a settings file whose names no longer carry its suffix.

## Deployments

Nothing is prepared before a run. A deployment is a suffix, and everything the runner keeps about it is in one folder of its own:

| File | What it is |
|---|---|
| `.deploy/<suffix>/demo.env` | The settings of that deployment: the generated names, your answers, and what the runner looked up or created since (the Custom Locations object ID, the endpoint and topic of the eventstream) |
| `.deploy/<suffix>/state.json` | Its checkpoint |
| `.deploy/current` | The suffix of the deployment that commands work on |

`.deploy/` is ignored by git and holds no secret.

**The first plan in a folder** starts a deployment and says so:

```text
New deployment 3x9: every name ends in -3x9, for subscription Demo subscription. Its settings are in .deploy/3x9/demo.env. Nothing was changed in Azure or Fabric.
Deployment 3x9. Settings and checkpoint: .deploy/3x9/. A new one beside it: add --new.
```

**The next build, in the same folder.** In the same tenant, or after `az login` to another one:

```bash
python3 tools/deploy.py plan --new --approve-role-changes
```

It draws a suffix that no deployment of the folder has, and leaves the earlier deployments as they are: their settings, their checkpoints, and whatever they made in Azure and Fabric. In the same subscription it takes over what you settled once and would settle the same way again: the region of the edge, the VM sizes and their order, the hour of the VM's automatic shutdown, and the Custom Locations object ID. Names are never taken over, and neither are the capacity and the workspace: those two questions are asked again. In another subscription nothing is taken over.

**Back to an earlier one.** `--deployment` goes with every mode and makes that deployment the current one. `status` lists the deployments of the folder, each with its subscription and whether it has made its resource group.

```bash
python3 tools/deploy.py status --deployment 3x9
```

**When the runner offers a new deployment by itself.** In a terminal, in two cases: the Azure CLI is on another subscription than the current deployment's, or the current deployment made its resource group and that group no longer exists, which is what a clean-up leaves. Without a keyboard it starts nothing: the first case is refused with the command to type, the second shows as `DRIFT` in the plan.

**A plan belongs to its deployment.** Once the folder holds more than one, the apply line a plan prints ends in `--deployment` with its suffix, so a line kept for later still goes where it was meant to. An apply that names the plan of another deployment of the folder is refused and says whose plan it is.

**Scripts you start by hand.** The runner hands every script it starts the settings of its deployment by name, in `ENV_FILE`. A script you start yourself, `bash infra/vm.sh ssh` for example, takes the file `ENV_FILE` names, else `config/demo.env` where there is one, else the settings of the current deployment. Beside a deployment of the runner they therefore work as the guides write them. For another deployment of the folder, name its file:

```bash
ENV_FILE="$PWD/.deploy/3x9/demo.env" bash infra/vm.sh status
```

**On the edge VM** the scripts read `config/demo.env`, as before. `bash infra/vm.sh push` writes the settings in use here to that place on the VM and sends nothing of `.deploy/`. Every deployment has a VM of its own, so each VM holds the settings of one deployment.

**From the earlier issues.** Up to the fourth issue the runner kept the settings of its one deployment in `config/demo.env`. The next run moves such a file to `.deploy/<suffix>/demo.env`, once, and says so. A `config/demo.env` you made by hand has no suffix: it stays where it is, and the runner does not use it.

**Removing a deployment** stays with `bash infra/99-cleanup.sh`. It finds its settings as every script started by hand does, and without an option it changes nothing and shows what it would remove, the resource group and the workspace by name: read that before you add `--all`. The folder `.deploy/<suffix>/` remains as the record of what was made; delete it when you no longer want it listed.

## The capacity

The runner creates the workspace on the capacity you chose: one that exists, or one it makes for this deployment.

**A capacity that exists.** The runner reads two lists as you: the capacities Fabric lists for you, which are the ones you administer or contribute to, and your workspaces with the capacity each runs on. From the SKU it tells what a capacity can hold:

| SKU | What it is | For the demo |
|---|---|---|
| `F2`, `F64`, … | A Fabric capacity | Yes |
| `FT1`, `Trial` | A Fabric trial capacity | Phases 1, 2 and 4. Not Phase 3: the data agent and the operations agent need a paid capacity |
| `P1`, `P2`, … | Power BI Premium | Yes, once Fabric is enabled on it |
| `PP3` | Premium Per User | No. It holds Power BI items only |
| `A1`, `EM1`, … | Power BI Embedded | No. They hold Power BI items only |

In a terminal you pick from that list. Without one: when exactly one active capacity that can hold Fabric items is in sight, and none of your workspaces runs on a capacity outside the list, the runner writes that one into the settings and shows it in the target; in every other case it blocks, prints both lists, and you put one ID into `FABRIC_CAPACITY_ID`. A capacity that is paused is said to be paused; the runner resumes none. A capacity Fabric does not list for you and that one of your workspaces runs on can be chosen: the runner cannot read its SKU or its state, shows `NOT CHECKED`, and creating the workspace shows whether you may use it. That takes the contributor role on the capacity, which an administrator of the capacity sets in the Fabric admin portal: **Capacity settings**, the kind of capacity, the capacity, **Details**, **Contributor permissions**.

**A capacity the runner makes.** Only when you answered yes to the question, and only with `--approve-capacity-creation` or that yes in the same run.

- **What.** One capacity named `fabwindfarm` and the suffix, SKU F16, in the demo's own resource group, with the deployment's tag, and with you as its administrator. A guest cannot be the administrator of a capacity, so a guest is told to choose an existing one. To have another SKU made, change `FABRIC_CAPACITY_CREATE_SKU` in the settings before the plan.
- **It costs money for as long as it runs.** The runner makes it and never pauses, resizes or deletes it. Pausing is yours: Azure portal, **Microsoft Fabric**, the capacity, **Pause**. A paused capacity stops the runner with that word; it resumes none. `bash infra/99-cleanup.sh --azure` deletes the resource group and the capacity with it; delete the workspace first (`--fabric-workspace`).
- **Where.** The runner proposes the edge's own region, unless Microsoft's region table lists something the demo uses as not available for a capacity there. For an edge in `southcentralus` the table of 17 November 2026 lists no operations agent, so the runner proposes Central US; for `eastus`, East US 2. You can name another region. The table is a copy with its date, kept in `tools/deployer/steps.py`; a region that lacks what a later phase uses needs your yes, and blocks the plan once that phase is asked for.
- **What preflight looks at first.** That the resource provider `Microsoft.Fabric` is registered (yours to register, like the others), that Azure's list of SKUs names the region for the SKU, and that the name is free.
- **When the list does not name the region.** The question says so, with the regions the list does name, and asks whether to take the region all the same. On a yes the plan shows the capacity as `NOT CHECKED` and the request for the capacity decides: it is the second thing an apply makes, straight after the resource group, so a refusal by Azure costs nothing. A region written into the settings by hand, without that yes, blocks. A list that does not name the SKU at all is "Azure did not say", and is `NOT CHECKED` too.
- **What it cannot look at.** The subscription's quota of Fabric capacity units: no operation for it is written where I read. When Azure refuses the capacity over the quota, the step blocks with the place to ask for more (Azure portal, **Quotas**, **Microsoft Fabric**, **New Quota Request**), before the VM or anything after it is made.
- **While Azure makes it.** The step waits up to 15 minutes. After that the apply ends with exit code 4, and the next apply waits for the same capacity; it never asks for a second one.

The target block of every plan and apply shows the capacity by name and SKU: one that exists, one to be made, or one Fabric does not list for you.

**The workspace.** New, with the generated name, or an existing one you chose. The runner takes an existing workspace only when it is on the capacity you chose and holds no item, so that everything in it is the demo's; it looks again at apply. It is held by its ID. With a new capacity the workspace is new too: a workspace stays on its capacity, and the runner moves none. Removing a deployment treats a chosen workspace like a made one: `bash infra/99-cleanup.sh --fabric` removes the demo's items and leaves the workspace, `--fabric-workspace` deletes the workspace named in the settings.

## Who the runner is

Every call the runner makes is made as you, with the sign-in of the Azure CLI. It refuses a service principal. The reason is the steps that accept a person only: the lookup of the Custom Locations object ID in Microsoft Entra ID, the notebooks of Phase 2 that build the model with semantic link, the data agent, the operations agent. One identity for a run also means one answer to "who did this".

Where the demo itself runs, it uses managed identities and no keys, as the guides do: the VM's identity onboards the cluster and uploads the reference files, and the identity of the Azure IoT Operations extension sends to the eventstream.

Most Fabric operations the runner uses also accept a service principal or a managed identity; the table under [Sources](#sources) says which were read. Running those parts under a federated workload identity, in a pipeline, is possible and not built: it would need two sign-ins in one run, and the first live run should come first.

## How it knows the target is its own

- **The resource group** carries the tag `windfarm-demo-deployment` with the suffix, and its ID is in the checkpoint. A group of that name without the tag is never used.
- **The workspace** has the suffix in its description, and its ID is in the checkpoint. A workspace of that name that the runner did not make is never used. A workspace you chose is held by its ID, in the settings and in the checkpoint, and was empty when the runner took it.
- **A capacity the runner made** is in the demo's resource group and carries the same tag. A capacity of that name without the tag is never used.
- **Inside them**, a resource of a provider the demo does not use, or an item the demo does not create, stops the runner until you move it or name it with `--acknowledge`.
- **The tenant and the subscription** of a deployment are kept. Signed in elsewhere later, every mode refuses to work on that deployment; in a terminal, plan offers to start a new one there.

## Every step

Generated from the runner's own list (`python3 tools/build-runner-docs.py`). "Rests on" is the documented operation or the script; the links are under [Sources](#sources).

<!-- steps: generated by tools/build-runner-docs.py -->

**Before anything is created**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `pre.tools` | The tools the scripts need | check | nothing | looks for az, bash and ssh on this computer |
| `pre.signin` | Signed in to Azure as a person, on the right subscription | check | nothing | az account show |
| `pre.extensions` | Azure CLI extension on this computer | check | nothing | az extension list |
| `pre.rights` | Your roles on the subscription | check | nothing | Role Assignments - List For Scope, filter atScope() and assignedTo(); az ad signed-in-user show |
| `pre.providers` | Resource providers registered | check | nothing | az provider show |
| `pre.region` | Region and VM size | check | nothing | Resource SKUs - List, with its location filter |
| `pre.quota` | vCPU quota for the VM | check | nothing | az vm list-usage |
| `pre.names` | Generated names are free | check | nothing | az storage account check-name |
| `pre.custom_locations` | Custom Locations object ID | check | nothing | az ad sp show |
| `pre.fabric` | The Fabric API answers you | check | nothing | GET /v1/workspaces |
| `pre.capacity` | A capacity that can hold Fabric items, active | check | nothing | GET /v1/capacities and GET /v1/workspaces; SKUs as in the Fabric licenses article. For a capacity to be made: Fabric Capacities - List Skus and Check Name Availability |
| `phase1.tenant_settings` | Tenant settings for Phase 1 | you | nothing | Fabric admin portal; no API for a person who is not an administrator |

**Phase 1**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `p1.resource_group` | Resource group of the demo | the runner | creates the resource group with the tag windfarm-demo-deployment | az group create |
| `p1.capacity` | Fabric capacity of the deployment's own, when you chose a new one | the runner, only when you chose a new capacity, after `--approve-capacity-creation` | a Fabric capacity in the demo's resource group, with you as its administrator. It costs money for as long as it runs; the runner never pauses, resizes or deletes it | Fabric Capacities - Create Or Update (Microsoft.Fabric, 2023-11-01) through az rest |
| `p1.edge_vm` | Edge VM | the runner | VM, network, SSH rule for your address, daily shutdown | infra/01-create-edge-vm.sh, without its provider registration and role assignments |
| `p1.vm_identity_roles` | Roles for the VM's identity, on the resource group only | the runner, after `--approve-role-changes` | 'Kubernetes Cluster - Azure Arc Onboarding' and 'Reader' for the VM's managed identity, both on the demo's resource group. The manual guide gives Reader on the subscription; the runner does not | az role assignment create, the role by its ID; read with Role Assignments - List For Scope |
| `p1.edge_host` | K3s and tools on the VM | the runner | installs K3s and the Azure CLI on the VM | edge/scripts/02-prepare-host.sh |
| `p1.arc` | Cluster connected to Azure Arc | the runner | Arc-enabled cluster with custom locations | edge/scripts/03-arc-enable.sh (az connectedk8s connect, enable-features) |
| `p1.iot_operations` | Azure IoT Operations | the runner, after `--approve-role-changes` | storage account, schema registry, device registry namespace, the instance. The Azure CLI gives the schema registry's identity 'Storage Blob Data Contributor' on that storage account | infra/04-deploy-iot-operations.sh (az iot ops init, create) |
| `p1.simulator` | Turbine simulator on the edge | the runner | builds the simulator image on the VM and starts it | edge/scripts/05-deploy-simulator.sh |
| `p1.workspace` | Fabric workspace of the demo | the runner | creates the workspace on the capacity shown; or, when you chose an existing empty workspace, takes that one into the deployment and creates none | Workspaces - Create Workspace |
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
| Capacity | Answer the question of plan; without a terminal, put one ID into `FABRIC_CAPACITY_ID` | That Fabric lists it for you, that its SKU can hold Fabric items, and that it is active. A capacity Fabric does not list and one of your workspaces runs on passes as `NOT CHECKED` |
| Quota, for the VM or for a new capacity | Ask for more in the Azure portal, under **Quotas** | The vCPUs in use and their limit again; for a capacity, the creation itself |
| Eventstream destination, only if Fabric leaves it in `Warning` or no rows arrive | The Get data wizard with the existing mapping, as in step 6.7 of the Phase 1 guide; the block prints the steps | The destination's state, and rows in `RawEvents` |
| Notebooks 06, 07, 08, 09 | Open each, **Run all** | The semantic model, the report and the data agent as items; for 07 your `--confirm p2.acceptance` |
| Operations agent and Teams | Step 9 of the Phase 3 guide | An item of type OperationsAgent named `WindFarmGearboxWatch`. Not whether it runs, and nothing of Teams |
| Sign-in of the app's tool | `npx rayfin login` in `app/windfarm-twin` | It runs `npx rayfin up` again |
| Service principal for real-time values | `bash app/create-principal.sh`, optional | Nothing. The deployment is complete on the Lakehouse route |
| Command path, Phase 5a | Confirm the edge is an isolated simulator; later switch the path on and send | Your `--confirm p5a.isolation`; the data flow's mode |

**Why notebooks 06 to 10 are yours.** Their first cell is `%pip install`. Microsoft documents that inline installation is switched off in notebook runs started by a pipeline, and how to switch it on there with the parameter `_inlineInstallationEnabled`. For a run started through the Job Scheduler API it says nothing. `--opt-in pip-jobs` makes the runner pass that parameter and try; when the job fails it falls back to the instruction above. Nobody has tried it yet.

## Interruption, time limits, drift

- **The checkpoint** is `.deploy/<suffix>/state.json`: every step with its state, the time, and what was measured. It is written in one move, ignored by git, and holds no secret. Keep it: it is the record that the resources are this deployment's.
- **One apply at a time.** A lock file beside the checkpoint refuses a second apply on this computer. The lock of an apply that died is taken over. A second computer has neither the settings nor the checkpoint and would start a deployment of its own. To go on with this one there, copy the folder `.deploy/<suffix>/` into the repository folder on that computer.
- **A plan while an apply runs** reads the checkpoint and writes nothing to it, and says so. Its copy is older than the one the apply keeps writing.
- **Answers that are kept.** Your roles, the resource providers and the VM sizes are asked once in twelve hours. Each answer is kept with what it depends on (the subscription, who you are, `LOCATION`, `VM_SIZE`): change one and the question is asked again. `--recheck` asks all three again.
- **A capacity Azure is still making** after 15 minutes ends the apply with exit code 4. The approval holds: a capacity to be made is part of the plan by its name, SKU and region, before and after it exists.
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
| Step 1 asks `az vm list-skus` for each size | One call to the Resource SKUs API with its location filter, with one minute to answer. The script is handed the sizes that passed (`VM_SIZE_OFFERED`). When the question goes unanswered the script is told to ask nothing (`VM_SIZE_SKIP_CHECK=1`): it tries each size of `VM_SIZE` in its order, and Azure refuses the ones you are not offered | `az vm list-skus` fetches the sizes of every region. From a workstation it did not answer in five minutes on 25 November, and the filtered call did not answer in two minutes an hour later. Put a size you know you are offered first in `VM_SIZE` |
| Roles are read and assigned with `az role assignment`, by name | Read with the operation Role Assignments - List For Scope and a filter; assigned with `az role assignment create`, the role by its ID | `az role assignment list` fetches every role definition to print names, which its own reference calls expensive. From the same workstation it did not answer in three minutes |
| The capacity and the workspace are made in the portal before step 6 | Asked for by plan: an existing capacity or a new F16; a new workspace or an existing empty one | The request of 25 November, 15:51 |
| Step 0: `config/demo.env`, copied from the example and filled in | No file to fill in. `.deploy/<suffix>/demo.env`, written when a deployment is started, one for each deployment of the folder | The request of 25 November, 16:35: the demo is built again and again, in one tenant or in several |
| Nobody looks at the vCPU quota | Preflight reads it for the size that is tried first | A second VM beside an existing one is the common case of a refusal, and a stopped VM still counts |
| Step 1 gives the VM's identity Reader on the subscription | Reader on the resource group | The runner grants nothing outside the demo. **Unproven**: whether Arc onboarding from the VM then still passes its provider check. If step 3 fails on it, grant Reader on the subscription by hand for the length of that step |
| Step 6.4 and 6.7: the eventstream in the portal, the mapping chosen in a wizard | Created from a definition with the mapping named in it | Microsoft's article "Create an Eventstream with an Eventhouse DirectIngestion destination by using APIs" |
| Steps 6.5 and 7.3: access and shortcuts in the portal | The Fabric API | Documented operations |
| KQL pasted into a query window | Sent to the same database over the Kusto REST interface, the same text | |
| Notebooks imported by hand, Lakehouse attached by hand | Imported with the Lakehouse in their metadata | Microsoft's article on the notebook API |
| Notebook 04 run for the expected answers | Imported, not run | It changes nothing and nobody reads a job's output |

## What has been proven where

| | Documented by Microsoft | Run against stand-ins here | Run on a tenant |
|---|---|---|---|
| The engine: plan, approval, checkpoint, lock, resume, redaction | not applicable | yes | The settings file of a first run (then still in `config/`) and `preflight` to its end: yes, 25 November, with the second issue. `plan`, `apply`, `status`: **no** |
| The prerequisite checks | their commands and operations, yes | yes | Tools, sign-in, extension, eight providers, the storage name, the Custom Locations object ID, the Fabric API, Node.js, the roles with the light question, the capacities by SKU, answers kept between runs: yes, 25 November. The VM sizes: asked three times, **never answered** on that workstation. A capacity Fabric does not list: **no** |
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
| The questions of plan | not applicable | yes, with scripted answers | The region of the edge and the capacity, in a terminal: yes, 25 November, where the capacity question showed the runner's error with the list of SKUs. The workspace and the VM size: **no** |
| A Fabric capacity made through the Microsoft.Fabric operations (create, read, name check, SKU list) | yes, read on 25 November | yes | The SKU list answered within its minute on 25 November and was misread; what it holds was not seen. The rest: **no** |
| An existing empty workspace taken into a deployment | the two list operations, yes | yes | **no** |
| The vCPU quota read with `az vm list-usage` | yes | yes | **no** |
| Several deployments in one folder: started, switched, the settings of the earlier issues moved, the scripts finding the current one | not applicable | yes | **no** |

## Unproven on a tenant

In the order a run meets them:

1. **The move of settings from the earlier issues.** A folder that ran an earlier issue has `config/demo.env` with a suffix. The next run moves it to `.deploy/<suffix>/demo.env` and goes on with the same deployment and the same checkpoint. This ran against a copy of that layout only. Likewise unproven: a second deployment beside a first, and the scripts started by hand finding the current one.
2. **The questions in a real terminal.** Seen on 25 November up to the region of a new capacity. The workspace and the VM size were answered by a script of answers only.
3. **The vCPU quota.** The shape of what `az vm list-usage` answers, and the names of the size families in it, which the runner derives from a size's name (`standardDSv7Family` for `Standard_D8s_v7`). A family it does not find is `NOT CHECKED`.
4. **A capacity made by the runner**, when you choose one: how Azure's list of SKUs is laid out (one entry for a SKU with all its regions, or one for each region; the runner reads both; the run of 25 November fits the second and does not prove it), the request through `az rest` with a JSON body, what Azure answers and how long it takes, the name under which Fabric lists the capacity (the runner looks for its Azure name), and what Azure says when the quota of capacity units does not cover it (the runner looks for the word quota).
5. **An existing workspace you chose**: nothing new is asked of Fabric for it, and nothing of it has run.
6. **A capacity Fabric does not list for you.** Whether Create Workspace accepts it, and what Fabric answers when it does not. The runner turns an answer with 401, 403 or the word capacity into a block; any other answer shows as a failure with Fabric's own words.
7. **How a trial capacity appears in the list of capacities.** The runner takes the SKU `FT` with a number, or `Trial`, for one; Microsoft's reference shows F SKUs only.
8. **`infra/01` under the runner**: without the provider registration, the group creation and the role assignments; and with `VM_SIZE_SKIP_CHECK=1`, where `az vm create` itself has to refuse the sizes you are not offered. The script moves on at the words `SkuNotAvailable`, `not available in location` and `NotAvailableForSubscription`; any other refusal ends it with Azure's message.
9. **The roles of the VM's identity**, read with the filter `principalId eq '…'` and assigned by role ID. (The same operation with the filter for a person answered on 25 November.)
10. **Arc onboarding with Reader on the resource group** instead of the subscription.
11. **The Eventhouse's own database.** The runner waits two minutes for the database Fabric gives a new Eventhouse, then creates one. Whether the API-created Eventhouse brings one is not written where I read.
12. **The Kusto audience for the Azure CLI's token** on a Fabric Eventhouse.
13. **The eventstream definition**: a custom endpoint with empty properties, and the destination with the Eventhouse's item ID as Microsoft's article has it. That article does not say how the database is chosen; this demo's Eventhouse has one. Microsoft warns that a property set which does not fit is accepted and ingests nothing; the gate after it is there for that, and the fallback is the wizard.
14. **Whether ingestion created this way reads JSON without a format label**, which the wizard needed set by hand.
15. **Shortcuts to KQL tables through the API** before the first write of OneLake availability.
16. **Notebook import**: the part named `notebook-content.ipynb` (the REST reference; an older article says `artifact.content.ipynb`), and the default Lakehouse taking effect for a job.
17. **Notebooks 01, 02, 03, 05 as jobs**: they have only run interactively. Parameters reaching the gate notebook's cell.
18. **The schedule payload** with unzoned times and `UTC`, which is how Microsoft's samples write it while its text asks for a `Z`.
19. **The result file of the gate** over the OneLake API. The verdict does not depend on it.
20. **The SQL probe** with a token for `https://database.windows.net`.
21. **`npx rayfin up` started without a terminal**, and how it says that it is not signed in. The runner recognises the words sign in, log in, keychain and 401; anything else is reported as a failure with the tool's own lines.
22. **The times.** No step has been timed under the runner, so this document promises none. Every check that takes five seconds or more prints its seconds. Measured so far, on 25 November from a workstation under WSL: the eight provider questions took 11 s together, and the questions about roles and VM sizes ran into their limits of 180 s and 120 s without an answer. Why answers of several megabytes do not arrive on that workstation is not known. `apply` sends about 3.5 MB from it to the VM (the repository, over SSH) and notebooks of about 120 KB each to Fabric, and Phase 4 installs the app's packages from npm there: how those fare is not known either.

## Tests

`simulator/tests/test_deploy_runner.py`, 100 tests against `simulator/tests/deploy_fakes.py`, a pretend Azure and Fabric that answer in the documented shapes and record every change:

| Asked for | Test |
|---|---|
| Wrong-target refusal | a settings file made by hand; a resource group and a workspace of the right name that the runner did not make; another subscription or tenant after the start; things in the group or workspace that are not the demo's |
| Interrupted deployment and resume | an operation Fabric has not finished; a run started by an apply that died; a failed script; a command that returns without its result; two applies at once and a dead one's lock |
| No duplicates on a second apply | every write of a full Phase 1 counted, and a second apply adds none: one group, one workspace, four jobs, one schedule, two plus two role assignments |
| Unsupported API handoffs | a destination in `Warning`; no rows after the wait; the gate notebook failing; each operator step of Phases 2 to 4 in turn; the fallback from a failed job to the person |
| Secret redaction | tokens, both keys, the connection string and the middle of each key searched in everything printed and written; a script that prints a secret; the redactor by itself; the checkpoint file |
| After the first run on a tenant | every check announced as it starts; one check that cannot be made is one line; a missing CLI extension is the operator's; the Azure CLI is started without a keyboard; the VM sizes asked with one filtered call, which cannot stop a run and is not asked again once the VM exists |
| After the second run on a tenant | a Premium Per User, A or EM capacity is never chosen and never accepted; one usable capacity with no other in sight is taken, two candidates are a choice; a capacity Fabric does not list passes as not checked and the workspace decides; what could not be checked is never called done, in the plan, in apply and in status; preflight shows no plan; roles read with one small question and assigned by ID, and `az role assignment list` fails the test if it is asked; an unanswered question is not asked again by every run, is asked again on `--recheck`, after twelve hours and when a setting it depends on changes; a block is never kept; a plan during an apply writes nothing to the checkpoint; a gate the runner measures is not shown as the operator's step |
| The questions of plan (fourth issue) | a capacity picked from the list, and asked for again when the one in the settings cannot hold the demo; a new capacity made only when chosen and approved, once, in the demo's group, before the VM, and the same approval holding after it exists; what stands in the way of one said first (provider, SKU not offered, name taken, a guest, a region that lacks what a phase uses); no quota, a paused capacity and a capacity that is not the deployment's stop the step; a capacity Azure is still making is waited for and not made twice; an existing workspace taken only when empty and on the chosen capacity, also when named by hand, and looked at again at apply; the two regions asked and checked; the VM size asked once Azure could not say; nobody at the terminal, `--no-input`, a closed terminal, Ctrl+C, an apply in progress; the vCPU quota |
| One folder, many deployments (fifth issue) | nothing prepared, and nothing ever written into `config/`; a second deployment beside the first, each with its own settings and checkpoint, the first untouched; what is taken over within a subscription, and nothing across subscriptions; a suffix never drawn twice; `--deployment`, an unknown suffix, several deployments with none current, a deployment whose folder was deleted; an apply with the plan of another deployment; another subscription and a vanished resource group asked about in a terminal and not without one; the settings of the earlier issues moved once, a file made by hand left alone, a stray copy never replacing a deployment's own; every script handed the settings of its deployment |
| After the first questions on a tenant (sixth issue) | every entry of a SKU in Azure's list is read, whichever way the list is laid out; a list without the SKU is not a refusal; a region the list does not name is said with the list, taken only on a yes, shown as not checked, and the yes holds for that region only |
| And | approval of exactly one plan; a changed file and drift void it; role changes wait and stay on the resource group; Phase 5a absent by default, switched off when present, notebooks 12 and 13 impossible to run; the history once and once per label; the schedule in the future; preflight; the KQL splitter; the gate notebook's logic; the real adapters |

One hundred and fifty-one faults were planted, one at a time. Of the twenty-two of the first issue, twenty-one made a test fail at once; the twenty-second, a key written into the settings with its last character cut off, passed until the test also searched for the middle of each key. The twenty-eight of the third issue each made a test fail at once. Of the forty-three of the fourth issue, in the questions, the new capacity, the chosen workspace and the quota, thirty-nine made a test fail at once; four passed until a test was made to look at the right place: questions asked by `apply`, questions asked while an apply runs, Phase 3 reading a capacity that is still to be made, and the quota asked about a VM that exists. Of the forty-five of the fifth issue, thirty-seven in the runner and eight in the way the scripts find their settings (those against the scenarios of `tools/script-tests/run.sh`), forty-four made a test fail at once; one passed until a test looked for it: a checkpoint folder without settings counted as a deployment. The thirteen of the sixth issue, in the reading of the list of SKUs and the question about a region, each made a test fail at once.

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
- [Microsoft Fabric concepts and licenses](https://learn.microsoft.com/en-us/fabric/enterprise/licenses): F SKUs and the trial hold Fabric items; P SKUs support Fabric; Premium Per User "doesn't provision a Fabric capacity"; A and EM SKUs "only support Power BI items".
- [Capacities - List Capacities](https://learn.microsoft.com/en-us/rest/api/fabric/core/capacities/list-capacities): the capacities the caller administers or contributes to, each with SKU, region and state. [Workspaces - List Workspaces](https://learn.microsoft.com/en-us/rest/api/fabric/core/workspaces/list-workspaces): each workspace with the ID of its capacity. [Manage your Fabric capacity](https://learn.microsoft.com/en-us/fabric/admin/capacity-settings): the contributor role and where it is set.
- [List Azure role assignments using the REST API](https://learn.microsoft.com/en-us/azure/role-based-access-control/role-assignments-list-rest): the filters `atScope()`, `assignedTo('…')`, which follows groups, and `principalId eq '…'`. [Azure built-in roles](https://learn.microsoft.com/en-us/azure/role-based-access-control/built-in-roles): the six role IDs the runner knows. [az role assignment](https://learn.microsoft.com/en-us/cli/azure/role/assignment): filling in role names "is expensive"; `create` takes a role name or ID.
- Microsoft.Fabric in Azure, API version 2023-11-01: [Fabric Capacities - Create Or Update](https://learn.microsoft.com/en-us/rest/api/microsoftfabric/fabric-capacities/create-or-update) (the name's pattern, the body with `sku`, `location` and the administrators, the states), [Check Name Availability](https://learn.microsoft.com/en-us/rest/api/microsoftfabric/fabric-capacities/check-name-availability), [List Skus](https://learn.microsoft.com/en-us/rest/api/microsoftfabric/fabric-capacities/list-skus) (the SKUs for a new capacity with the locations of each; the sample has one region in every entry, written as `West Europe`).
- [Fabric region availability](https://learn.microsoft.com/en-us/fabric/admin/region-availability), the page of 17 November 2026: for South Central US it lists the operations agent as not available; for Central US nothing. [Buy a Microsoft Fabric subscription](https://learn.microsoft.com/en-us/fabric/enterprise/buy-subscription): the provider `Microsoft.Fabric` has to be registered, the administrator has to belong to the tenant, and a guest cannot be one. [Microsoft Fabric capacity quotas](https://learn.microsoft.com/en-us/fabric/enterprise/fabric-quotas): where the quota is seen and asked for. [Pause and resume your capacity](https://learn.microsoft.com/en-us/fabric/enterprise/pause-resume).
- [Virtual machine vCPU quotas](https://learn.microsoft.com/en-us/azure/virtual-machines/quotas): the two quotas a new VM has to fit, deallocated VMs counted, and `az vm list-usage`.
- [Resource SKUs - List](https://learn.microsoft.com/en-us/rest/api/compute/resource-skus/list): `$filter=location eq '…'`, the only filter it supports; a size's `restrictions` of type `Location` with the reason.
- [Manage Apache Spark libraries in Microsoft Fabric](https://learn.microsoft.com/en-us/fabric/data-engineering/library-management): inline installation in pipeline runs, and `_inlineInstallationEnabled`.
- [Create a data flow in Azure IoT Operations](https://learn.microsoft.com/en-us/azure/iot-operations/connect-to-cloud/howto-create-dataflow) and the [Dataflow REST reference](https://learn.microsoft.com/en-us/rest/api/iotoperations/dataflow/create-or-update): `mode`, `Enabled` or `Disabled`.
