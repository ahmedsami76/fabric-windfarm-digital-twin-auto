# The deployment runner

`tools/deploy.py` deploys the demo step by step, from an empty subscription and an existing Fabric capacity to the twin in a workspace. It starts the scripts and notebooks of this repository in the order of the guides, looks at Azure and Fabric before and after every step, and stops with an exact instruction wherever a person has to act.

**Status. Written on 25 November 2026. Its first command, `preflight`, ran on a tenant four times that day; three of the runs were sent to me. They showed errors of the runner, corrected in the second and third issue; the run of 15:40 showed the third issue reading the roles and the capacities rightly. The fourth issue added what was asked for after that run: the runner asks its questions itself (the region, the capacity, the workspace, the VM size), and can make a Fabric capacity when you say so. This fifth issue answers the request of 16:35: no settings file is prepared or kept in `config/`; every deployment gets its three random characters when it is started and keeps its settings beside its checkpoint, so one folder serves build after build, in one tenant or in several. See [Deployments](#deployments). At 17:17 the questions ran on a tenant for the first time, and the one about a new capacity said that F16 is not offered in Central US, where the same subscription runs an F16: the runner had read one entry of Azure's list of SKUs instead of all. This sixth issue reads the list whole, never takes a list that does not name the SKU for a refusal, shows the list with every such message, and leaves a region the list does not name to you. With it, a plan ran to its end on a tenant at about 17:50, for a new F16 in Central US. This seventh issue is a hardening asked for at 18:08: choices are settled from options, settings, a saved profile and what the cloud shows before anybody is asked; an approval covers a saved plan with everything that changes what runs; every call is pinned to the deployment's subscription; an apply names its deployment; a notebook run is taken only when the runner knows it to be its own; a script has a time limit by the clock; and `provisioned`, `blocked` and `demo-ready` are three words. None of the seventh issue has run on a tenant, and `apply` has not run at all: the runner has made nothing in Azure or Fabric yet. [16-runner-pilot-checklist.md](16-runner-pilot-checklist.md) is the first run, step by step.** Everything the runner does was exercised against stand-ins on the computer it was written on (111 tests, 195 planted faults, all caught); the 111 tests also passed on the workstation of the tenant runs, on 25 November at 23:09. Most of what it starts, the scripts of `infra/` and `edge/` and the notebooks, ran on a tenant between 19 and 25 November, started by hand. [What has been proven where](#what-has-been-proven-where) keeps the two apart, and [Unproven on a tenant](#unproven-on-a-tenant) lists what your next run decides. Expect it to find something; send me what it prints.

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
- Go by the Azure CLI's active subscription, or by `.deploy/current` in an apply.
- Choose a region, pick one of several capacities, or put another target in the place of one that is not valid.
- Take a notebook run it did not start for its own, or start one again when it does not know what became of the first.
- Call a deployment demo-ready because its things exist.

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

## The shortest way

**The first deployment in a subscription.** One plan with the choices as options, which also saves them as the profile of the subscription:

```bash
python3 tools/deploy.py plan --edge-region southcentralus --approve-role-changes --save-profile
```

The capacity needs no option when exactly one that can hold the demo is in sight; otherwise the plan blocks, lists the candidates, and you add `--capacity ID`. Read the plan, then run the line it prints, which names the deployment and carries the approvals you gave:

```bash
python3 tools/deploy.py apply --deployment 3x9 --approve 3f9c2a71b0de --approve-role-changes --confirm phase1.tenant_settings
```

**Every later deployment there.** No option for a choice and no question:

```bash
python3 tools/deploy.py plan --new --approve-role-changes
```

and the apply line it prints.

**To resume**, whatever stopped the apply, the same apply line again. What it says decides what you add:

| It ended with | Do | Then |
|---|---|---|
| exit code 3, `blocked`, a step of yours | what the block says | the same line, with the `--confirm STEP` it names where there is one |
| exit code 4, `waiting` | nothing | the same line, later |
| exit code 1, `FAILED` | fix what the last lines name | the same line |
| exit code 130, `STOPPED  by Ctrl+C` | nothing | the same line |
| `An earlier apply set out to run NOTEBOOK … and ended before it learned whether Fabric took the request` | read the runs it lists | the same line with `--adopt-job STEP=ID`, or with `--resubmit STEP` when none of them is that run |
| `REFUSED … What differs: …` | read what differs. If you meant the change: `plan` again with the same options, read it, apply that | |
| `REFUSED  The Azure CLI cannot use subscription …` | `az login --tenant TENANT` | the same line |

**To go further with the same deployment**: `plan --deployment 3x9 --up-to phase4 --approve-role-changes`, and its apply line.

**Where it stands**: `python3 tools/deploy.py status --deployment 3x9` says whether the deployment is provisioned, blocked, or [demo-ready](#provisioned-blocked-demo-ready).

A first run on a tenant is described step by step, with what to write down, in [16-runner-pilot-checklist.md](16-runner-pilot-checklist.md).

## Plan, apply, resume

Every command is typed in the repository folder.

**1. See what stands in the way.** Changes nothing.

```bash
python3 tools/deploy.py preflight --up-to phase4
```

While it looks, it prints one line for each check as it starts, and the seconds for any that took five or more. Looking is a dozen or more calls to the Azure CLI, each a few seconds. Every call has a time limit: one minute for the two questions a deployment can do without (your roles, the VM sizes), three minutes for the others. A check that cannot be made becomes one line, `NOT CHECKED` when the deployment can go on without it and `BLOCKED` otherwise, and the others are still made.

Three answers are kept in the checkpoint for twelve hours: your roles, the resource providers, the VM sizes. So is "could not be read". The next preflight, plan or apply shows them with `[asked 12 min ago; --recheck asks again]` instead of waiting again. A check that found something missing is never kept: it is asked until it passes.

Preflight shows the same table as a plan, for the prerequisites only, and no plan identifier: there is nothing in it to approve.

**2. Read the plan.** Changes nothing in Azure or Fabric. The first plan in a folder starts a deployment: it picks three random characters, makes every name from them and writes the settings to `.deploy/<suffix>/demo.env`. Then it settles the choices of the deployment, from options, settings, the profile of the subscription and what the cloud shows, and asks only what none of them settles: see [How a choice is settled](#how-a-choice-is-settled).

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
python3 tools/deploy.py apply --deployment 3x9 --approve 3f9c2a71b0de --approve-role-changes --confirm phase1.tenant_settings
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
| 130 | Stopped by Ctrl+C. The script the runner was running was stopped with it; what had begun in Azure or Fabric goes on there | The same command again: it looks first |

**5. See where things stand.** Changes nothing.

```bash
python3 tools/deploy.py status
```

### Options

| Option | For |
|---|---|
| `--up-to phase1` to `phase4` | The last phase to include. Default `phase1` |
| `--approve-capacity-creation` | Making the Fabric capacity you chose to have made. A yes to that question approves it for the plan of the same run; the apply command the plan prints carries the option |
| `--no-input` | Preflight and plan ask nothing. A choice that is still open blocks the plan, which lists the candidates and the options that settle it |
| `--ask` | In a terminal: go through every question whose subject does not exist yet, also the ones that were settled without you. This is the full question round of the fourth issue |
| `--approve-role-changes` | The role assignments the plan lists: for the VM's identity on the resource group, by the Azure CLI for the schema registry on its storage account, and for the two identities of the edge in the workspace |
| `--confirm STEP` | You confirm what the runner cannot read: `phase1.tenant_settings`, `phase3.tenant_settings`, `phase4.tenant_settings`, `p2.acceptance`, `p5a.isolation`. The checkpoint keeps who and when |
| `--allow-preview ontology` | Let the runner run notebook 11. Without it the ontology is optional and yours |
| `--opt-in pip-jobs` | Let the runner try notebooks 06 to 10 as jobs. Not documented to work: see below. With it, notebook 09 also needs `--allow-preview data-agent-sdk` |
| `--enable-phase5a-isolated-simulator` | Also provision the command path of Phase 5a, switched off |
| `--regenerate-history LABEL` | Run notebook 02 again, once for this label |
| `--acknowledge ID` | A resource or item in the demo's group or workspace that the runner does not know belongs there |
| `--new` | With `preflight` or `plan`: start another deployment in this folder, with a new random suffix. The earlier ones stay as they are. With `--subscription ID` in that subscription, else in the one the Azure CLI is on at that moment |
| `--deployment SUFFIX` | Work on this deployment of the folder. **`apply` always carries it**: it does not go by `.deploy/current`, which a plan in another terminal may have moved. The apply line a plan prints has it |
| `--edge-region`, `--capacity`, `--new-capacity` with `--capacity-region`, `--workspace-id`, `--vm-size`, `--ssh-source` | The choices of a deployment, as options of `preflight` and `plan`. See [How a choice is settled](#how-a-choice-is-settled) |
| `--save-profile`, `--no-profile` | Keep this deployment's region, existing capacity, VM sizes, shutdown hour and SSH range for the next deployments in the same tenant and subscription; leave the saved profile out of one run |
| `--adopt-job STEP=JOB`, `--resubmit STEP` | With `apply`, for a notebook run whose fate an earlier apply did not learn: this run is the step's, or start a new one. See [Interruption, time limits, drift](#interruption-time-limits-drift) |
| `--app-check BUILD,ROUTE,SECONDS` | With `apply`: what the deployed twin's own connection check shows. Part of [demo-ready](#provisioned-blocked-demo-ready) |
| `--confirm p3.agent_message` | You have seen the operations agent's message in Teams. Part of demo-ready |
| `--recheck` | Ask again what was asked within the last twelve hours and kept: your roles, the resource providers, the VM sizes |

## How a choice is settled

A deployment has five choices. Each is settled by the first of these that says something about it:

1. **An option of this run**: `--edge-region`, `--capacity` or `--new-capacity --capacity-region`, `--workspace-id`, `--vm-size`, `--ssh-source`.
2. **The settings of the deployment**, `.deploy/<suffix>/demo.env`: what an earlier plan settled, or what you wrote there.
3. **The profile** saved for the tenant and subscription with `--save-profile`.
4. **A default the cloud establishes as the only one.** There is one such case: a single capacity that can hold the demo, with no other in sight.

What none of the four settles is asked, together, when somebody is at a terminal. Otherwise the plan blocks at that choice, with the candidates and the option that settles it, and nothing has been written anywhere.

| Choice | Without an option, settings or profile | Never |
|---|---|---|
| Azure region of the edge | Open. The runner has no default geography: a new deployment is written without a region | another region put in the place of one that is not valid |
| Fabric capacity | The only one that can hold the demo, when there is exactly one and none of your workspaces runs on a capacity outside the list. Two candidates, or none, are open | the first of several; another capacity when the one that was named is paused or gone |
| A new capacity | Not made. Only with `--new-capacity` or a yes at the question, and then only with `--approve-capacity-creation` or that yes | taken from a profile or from another deployment |
| Workspace | A new one, with the deployment's name | an existing one, unless you name it by ID with `--workspace-id` or pick it with `--ask`, and it is empty and on the chosen capacity |
| VM sizes, SSH range | The sizes of the template, in its order. SSH from the public address of the computer that runs the apply | SSH from every address |

- **A value that is not valid is refused where it is given**, with the reason: a region Azure IoT Operations does not support, a capacity Fabric does not list for you or that cannot hold Fabric items, a workspace ID you cannot see.
- **Two options that contradict each other are refused**, and so is an option that contradicts what the deployment has made: the region after the resource group exists, the capacity after the workspace exists. A deployment stays where it is.
- **The two regions are separate.** The edge's region is checked against the regions of Azure IoT Operations, a new capacity's against Microsoft's table for Fabric and Azure's list for the SKU. Neither is derived from the other; for a new capacity the runner proposes one and you say it.
- **A profile is yours to approve by saving it**, and it is held to its tenant and subscription: a file saved for another tenant is refused. A capacity it names is written as it is; if that capacity has been paused or deleted since, the plan blocks on it and takes no other.
- **Choices are made in `preflight` and `plan`.** `apply` and `status` take none of these options and ask nothing.
- **The plan says where each choice came from**, in the line `chosen by` of the target.

## The questions

Since the seventh issue a question is the last resort, not the way in. Preflight and plan ask, in a terminal and before they look at anything, only what the options, the settings, the profile and the cloud did not settle: the region of the edge when none is known, and the capacity when not exactly one can hold the demo. Asked together, in one round. With `--ask` the runner goes through all four questions below, as the fourth issue did. Enter takes the answer in brackets. Every answer is written to the settings of the deployment, `.deploy/<suffix>/demo.env`, and kept in the checkpoint with who gave it, when, and that it was asked. No answer changes anything in Azure or Fabric: it becomes a line of the plan, and the plan still has to be approved.

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

A run with `--ask` in which every answer is Enter:

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

| `.deploy/<suffix>/plans/<plan>.json` | Every plan as it was shown: [what its approval covers](#what-an-approval-covers), without secrets |
| `.deploy/<suffix>/app/windfarm-twin/` | The app of Phase 4 as built for this deployment. Two deployments never build in one folder |
| `.deploy/profiles/<subscription>.json` | What `--save-profile` kept for a tenant and subscription |

`.deploy/` is ignored by git and holds no secret.

**The first plan in a folder** starts a deployment and says so:

```text
New deployment 3x9: every name ends in -3x9, for subscription Demo subscription. Its settings are in .deploy/3x9/demo.env. Nothing was changed in Azure or Fabric.
Deployment 3x9. Settings and checkpoint: .deploy/3x9/. A new one beside it: add --new.
```

**The next build, in the same folder.** In the same tenant, or in another one after `az login` there:

```bash
python3 tools/deploy.py plan --new --approve-role-changes
```

It draws a suffix that no deployment of the folder has, and leaves the earlier deployments as they are: their settings, their checkpoints, and whatever they made in Azure and Fabric. Nothing is taken over from an earlier deployment by itself. What you want the next ones to reuse, you save once as the profile of the subscription (`--save-profile`): the region of the edge, an existing capacity, the VM sizes and their order, the shutdown hour, the SSH range. With a profile, `plan --new` asks nothing. Names, the workspace, and the choice to have a capacity made are never in a profile: a paid capacity is chosen and approved for one deployment.

**Back to an earlier one.** `--deployment` goes with every mode and makes that deployment the current one. `status` lists the deployments of the folder, each with its subscription and whether it has made its resource group.

```bash
python3 tools/deploy.py status --deployment 3x9
```

**The runner never starts or changes to another deployment by itself.** When the Azure CLI is on another subscription, that changes nothing: every call names the deployment's own subscription. When the deployment's resource group is gone, which is what a clean-up leaves, the plan shows `DRIFT`. A new deployment is `plan --new`, typed by you.

**A plan belongs to its deployment.** The apply line a plan prints always names the deployment, and an apply without `--deployment` is refused. An apply that names the plan of another deployment of the folder is refused and says whose plan it is.

**Scripts you start by hand.** The runner hands every script it starts the settings of its deployment by name, in `ENV_FILE`. A script you start yourself, `bash infra/vm.sh ssh` for example, takes the file `ENV_FILE` names, else `config/demo.env` where there is one, else the settings of the current deployment. Beside a deployment of the runner they therefore work as the guides write them. For another deployment of the folder, name its file:

```bash
ENV_FILE="$PWD/.deploy/3x9/demo.env" bash infra/vm.sh status
```

**On the edge VM** the scripts read `config/demo.env`, as before. `bash infra/vm.sh push` writes the settings in use here to that place on the VM and sends nothing of `.deploy/`. Every deployment has a VM of its own, so each VM holds the settings of one deployment.

**From the earlier issues.** Up to the fourth issue the runner kept the settings of its one deployment in `config/demo.env`. The next run moves such a file to `.deploy/<suffix>/demo.env`, once, and says so. A `config/demo.env` you made by hand has no suffix: it stays where it is, and the runner does not use it.

**Removing a deployment** stays with `bash infra/99-cleanup.sh`. It finds its settings as every script started by hand does, and without an option it changes nothing and shows what it would remove, the resource group and the workspace by name: read that before you add `--all`. The folder `.deploy/<suffix>/` remains as the record of what was made; delete it when you no longer want it listed.

## What an approval covers

A plan is saved, without secrets, as `.deploy/<suffix>/plans/<plan>.json`. Its identifier is a digest of what that file holds under `covers`:

| Part | What |
|---|---|
| Who and where | the deployment, the operator the Azure CLI is signed in as, the tenant, the subscription, the resource group, the workspace (and the ID of an existing one), the capacity (an existing one by its ID; one to be made by its name, SKU and region), the region of the edge |
| How | the VM sizes in their order, the SSH range, every other setting of the deployment |
| With which approvals | the role grants the plan lists, and the approvals and opt-ins of the run: roles, capacity, previews, `pip-jobs`, Phase 5a, a label for regenerating the history |
| With which files | for every step, a digest of each script, notebook and KQL file it uses, and of what a script reads or ships: `config/load-env.sh` for every script, `infra/vm.sh` for the edge scripts, the simulator's code and the reference data for the simulator's step, the whole of `app/overlay` for the app; and the runner's own code |
| In which state | the steps whose result has gone missing (drift) |

An apply computes the same from what is there now, under its lock, and compares. When anything differs it refuses, names what differs, and keeps nothing of the command: a `--confirm` given with a refused apply is not written to the checkpoint.

Three things are deliberately not part of it. Which steps are done already, so that one approval resumes an interrupted apply. What the apply itself writes on its way, the eventstream's endpoint and topic and the ID of a capacity it made. And a `--confirm`, which is your statement about a step and not a change of the plan. Something that turns up later and was not in the plan is not covered: a resource that appears in the group stops the runner, and a step that would now do something else has another digest.

## One subscription for a deployment

A deployment is in one subscription, written into its settings when it is started. From then on:

- **Every call of the Azure CLI names that subscription**, with `--subscription`. The CLI's active subscription, which `az account set` in any terminal changes for all of them, decides nothing.
- **Tokens are asked for that subscription**, so they are for its tenant: for Fabric, the Eventhouse, storage, SQL and Microsoft Graph.
- **The two reads of the directory go to Microsoft Graph** with such a token: who is signed in, and the object ID of the Custom Locations service. `az ad` takes no subscription and follows the active one.
- **The scripts are started with the subscription by name** (`AZ_SUBSCRIPTION_PIN`). Their own `az account set` is then left out and each of their calls carries `--subscription`. Started by hand they select the subscription of the settings, as before.
- **An apply names its deployment** and is handed the settings by name, so `.deploy/current` decides nothing either.

When the sign-in does not reach the deployment's subscription, every mode refuses and says how to sign in. It never falls back to the subscription the CLI is on.

Seen with Azure CLI 2.93.0: `az ad`, `az extension`, `az config`, `az version`, `az login` and `az logout` take no `--subscription`, so none is added there. Whether the commands of the extensions `azure-iot-ops` and `connectedk8s` take it could not be tried here: see [Unproven on a tenant](#unproven-on-a-tenant).

## Provisioned, blocked, demo-ready

`status`, and the end of every apply, say three things apart:

| Word | Means | Rests on |
|---|---|---|
| **provisioned** | every step up to the chosen phase is complete: the things exist | the checkpoint |
| **blocked** | a step waits for you, failed, or is still running | the checkpoint, with the step and its reason |
| **demo-ready** | the demo can be shown now | measured at this moment, or read by you and given to the runner |

Demo-ready needs, for Phase 1: telemetry in the Eventhouse **measured now**, from twelve turbines, the newest reading at most three minutes old; and the Lakehouse's tables measured as populated. A stopped edge is provisioned and not demo-ready.

For Phase 3 it also needs your word that the operations agent's message reached Teams: `--confirm p3.agent_message`. An item of the agent exists as soon as it has been created in the portal; that is not proof that the agent is configured, running or delivering.

For Phase 4 it needs the deployed app's own connection check. The runner's gate after the deployment is a query **with the operator's token**: it shows that the data is there for you, not that the app, which reads as another identity, reaches it. The runner has no documented way to ask the deployed app, so it asks you once: open the app, select the badge, and pass what the check shows with the next apply.

```bash
python3 tools/deploy.py apply --deployment 3x9 --approve PLAN --up-to phase4 --approve-role-changes --app-check 455aa9777780,lakehouse,120
```

The three values are the build the check names, the route that says PASS, and the age of the newest reading in seconds. The twin is demo-ready when the build is the one the repository is at, and the reading is at most 15 minutes old on the Lakehouse route or 2 minutes on the Eventhouse route. A check that names another build, or older data, is a failed connection for a demo, and the report says which.

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
| `pre.rights` | Your roles on the subscription | check | nothing | Role Assignments - List For Scope, filter atScope() and assignedTo(); Microsoft Graph, GET /me |
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
| `p4.scaffold` | App created from Microsoft's template, with the twin laid over it | the runner | the app's folder of this deployment on this computer, .deploy/<suffix>/app/windfarm-twin; nothing in Fabric | app/create-app.sh |
| `p4.deploy` | App deployed to the workspace | the runner | the Fabric app item WindFarmTwin, its page and its seven functions | npx rayfin up --workspace NAME --item-name NAME (Rayfin 2.0.1) |
| `p4.gate_data_route` | GATE: the Lakehouse answers the twin's query (asked with the operator's token) | gate | nothing; one query against the SQL endpoint of the Lakehouse | SQL analytics endpoint, with a token for https://database.windows.net |
| `p4.eventhouse_principal` | Real-time values: the service principal (optional) | you, optional | nothing | app/create-principal.sh |
| `p4.connection_check` | The app's own connection check: what makes the twin demo-ready | you, optional | nothing | the app |

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
- **One apply at a time, on one computer.** A lock file beside the checkpoint refuses a second apply to the same deployment on this computer, and the lock of an apply that died is taken over. Once it holds the lock, an apply reads the checkpoint and the settings again and trusts nothing it read before. **The lock is a file: it does not reach another computer.** Two people applying the same deployment from two computers are not kept apart by it; each has its own copy of the checkpoint. Run a deployment from one computer. To move it, copy the folder `.deploy/<suffix>/` and stop using the old one.
- **A plan while an apply runs** reads the checkpoint and writes nothing to it, and says so. Its copy is older than the one the apply keeps writing.
- **Answers that are kept.** Your roles, the resource providers and the VM sizes are asked once in twelve hours. Each answer is kept with what it depends on (the subscription, who you are, `LOCATION`, `VM_SIZE`): change one and the question is asked again. `--recheck` asks all three again.
- **A capacity Azure is still making** after 15 minutes ends the apply with exit code 4. The approval holds: a capacity to be made is part of the plan by its name, SKU and region, before and after it exists.
- **Long operations.** When Fabric answers "accepted", the address to ask about is written to the checkpoint before the first wait. Apply waits up to 15 minutes for an operation and 45 for a notebook, then ends with exit code 4. The next apply asks about the same operation and starts no second one. For a request that creates an item no intent is written first: the item's name is the key, and the step looks for the item by name before it creates anything, so a request that was taken and never answered is found as the item it made.
- **A notebook run is the runner's only when the runner knows it.** Before the request to run a notebook leaves, the intent is written to the checkpoint; when Fabric answers, the run's ID replaces it. A run whose ID is in the checkpoint is asked about on resume, also when it finished while nobody waited, and its result is taken: no second run.
- **An apply that ended between the request and the answer** leaves an intent without an ID. Whether Fabric took the request is then not known, and Run On Demand Item Job documents no key by which a run could be matched to a request. The notebooks write data. So the runner neither starts another run nor takes one it finds: it blocks, lists the runs Fabric has since then, and you say which it was, `--adopt-job p1.history=ID`, or that there was none, `--resubmit p1.history`.
- **A run in progress that the checkpoint knows nothing of** is somebody's, not the runner's. It blocks on it and names `--adopt-job` for the case that it is yours.
- **A script has a time limit by the clock**, also when it prints nothing: its output is read apart from the clock. About once a minute of silence the runner says that it is still waiting. At the limit, and on Ctrl+C, the script and everything it started on this computer are stopped. What it began in Azure goes on there, and the next apply looks before it does anything.
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

## The `%pip` notebooks and a Fabric Environment

Notebooks 06 to 10 are yours to run because their first cell is `%pip install` (see "Why notebooks 06 to 10 are yours" above). Asked on 25 November 2026: can a Fabric Environment with pinned libraries take the place of those cells?

**What Microsoft documents**, read that day: an Environment item can be created through the public API, with or without a definition; its libraries are given as an `environment.yml` among the definition's parts (`Libraries/PublicLibraries/environment.yml`) or uploaded to its staging state; and a publish operation applies them. Notebooks and Spark job definitions attach to an environment. So the supported parts exist.

**Why it is not built in this issue.** It is more than one call, and each part is unproven here:

1. The five notebooks would change. Their install cell would have to do nothing when the libraries are there, and they are generated from `tools/build-phase2.py` and `tools/build-phase3.py`; their present form is the one that ran on the tenant.
2. Publishing an environment runs as a Spark job of its own, which has to be waited for and can fail on a library. `semantic-link-labs` 0.15.2 and the alpha `fabric-data-agent-sdk` 0.1.36a0 on Runtime 2.0 have only been installed with `%pip` here.
3. How a notebook is attached to an environment through the API: the notebook's definition carries it, and I did not find the form written out for a run request. The runner does not guess a payload.
4. Notebooks 06 to 09 use semantic link and the data agent SDK as the person who runs them. They have never run as jobs.

**What would settle it**: one environment made by hand in the pilot's workspace with the two libraries, attached to notebook 06, and one run of it as a job. If that passes, the runner can create and publish the environment and import the notebooks attached to it, behind an opt-in. Until then `--opt-in pip-jobs` stays the experiment, and the hand-off stays the supported way.

## Where it differs from the guides

| Guide | Runner | Why |
|---|---|---|
| Step 1 registers eight resource providers | You register them | A change to the whole subscription |
| Step 1 asks `az vm list-skus` for each size | One call to the Resource SKUs API with its location filter, with one minute to answer. The script is handed the sizes that passed (`VM_SIZE_OFFERED`). When the question goes unanswered the script is told to ask nothing (`VM_SIZE_SKIP_CHECK=1`): it tries each size of `VM_SIZE` in its order, and Azure refuses the ones you are not offered | `az vm list-skus` fetches the sizes of every region. From a workstation it did not answer in five minutes on 25 November, and the filtered call did not answer in two minutes an hour later. Put a size you know you are offered first in `VM_SIZE` |
| Roles are read and assigned with `az role assignment`, by name | Read with the operation Role Assignments - List For Scope and a filter; assigned with `az role assignment create`, the role by its ID | `az role assignment list` fetches every role definition to print names, which its own reference calls expensive. From the same workstation it did not answer in three minutes |
| The capacity and the workspace are made in the portal before step 6 | Asked for by plan: an existing capacity or a new F16; a new workspace or an existing empty one | The request of 25 November, 15:51 |
| Step 0: `config/demo.env`, copied from the example and filled in | No file to fill in. `.deploy/<suffix>/demo.env`, written when a deployment is started, one for each deployment of the folder | The request of 25 November, 16:35: the demo is built again and again, in one tenant or in several |
| The directory is read with `az ad` | Microsoft Graph, with a token for the deployment's subscription | `az ad` takes no `--subscription` and follows the CLI's active one |
| The scripts select the subscription with `az account set` | Under the runner each of their `az` calls names it, and the active subscription is left alone | Another terminal can change the active subscription while a script runs |
| The app is built in `app/windfarm-twin` | In `.deploy/<suffix>/app/windfarm-twin`, one folder for each deployment | The app's copy of `config.ts` names one workspace, and the app's tool keeps its state in the folder |
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
| The engine: plan, approval, checkpoint, lock, resume, redaction | not applicable | yes | The settings file of a first run (then still in `config/`) and `preflight` to its end: yes, 25 November, with the second issue. `plan` to its end, with its identifier and the apply line: yes, 25 November, with the sixth. `apply`, `status`: **no** |
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
| A Fabric capacity made through the Microsoft.Fabric operations (create, read, name check, SKU list) | yes, read on 25 November | yes | The SKU list and the name check: yes, 25 November (the list misread at 17:17, read rightly at 17:50; it has one entry for each region). Create and read: **no** |
| An existing empty workspace taken into a deployment | the two list operations, yes | yes | **no** |
| The vCPU quota read with `az vm list-usage` | yes | yes | **no** |
| Several deployments in one folder: started, switched, the settings of the earlier issues moved, the scripts finding the current one | not applicable | yes | **no** |
| Choices from options, a profile and discovery; the saved plan and what differs; the named apply | not applicable | yes | **no** |
| Calls pinned with `--subscription`; the directory read through Microsoft Graph | the option, on the commands of the CLI itself with version 2.93.0 here; the two Graph requests, yes | yes | **no** |
| Scripts under the runner with `AZ_SUBSCRIPTION_PIN` | the option, as above | yes, against a stand-in `az` | **no** |
| A notebook run journalled, adopted, resubmitted | Run On Demand Item Job and the job instances, yes; no key to match a run to a request is documented | yes | **no** |
| A script stopped at its limit with what it started | not applicable | yes, with real processes on Linux | **no**: not on WSL |
| Demo-ready: telemetry now, the app's own check given by a person | not applicable | yes | **no** |
| The clean-up's report of a shared and of an own capacity | not applicable | yes, 6 scenarios | **no** |

## Unproven on a tenant

In the order a run meets them:

1. **`--subscription` on every call.** The runner adds it to each call of the Azure CLI except the groups that refuse it (`ad`, `extension`, `config`, `version`, `login`, `logout`: tried with version 2.93.0). The commands the runner and its scripts use from the CLI itself take it. For the commands of the extensions, `az iot ops …` in `infra/04`, `06` and `08` and `az connectedk8s` on the VM, it could not be tried here. If one refuses the option, its script ends at that call with `unrecognized arguments`, before it changes anything; send me the line.
2. **The directory through Microsoft Graph.** `GET /me` and `GET /servicePrincipals(appId='…')` with the token `az account get-access-token --resource-type ms-graph` gives for the deployment's subscription. The same reads worked through `az ad` on 25 November. If Graph refuses, the roles show as `NOT CHECKED` and the Custom Locations object ID blocks with the command to read it by hand.
3. **A plan without a question**, from options and a profile; the saved plan file; an apply that names its deployment.
4. **An interrupted notebook run.** That the run's ID from the `Location` header is the one `Get Item Job Instance` knows, that a run which finished meanwhile is still found by it, and what `List Item Job Instances` shows of a run that was requested and not yet started.
5. **A script stopped at its limit on WSL.** The runner ends the script's whole session; tried with real processes on Linux only.
6. **The app in a folder of the deployment.** The scaffolder is started in `.deploy/<suffix>/app/` with the project name `windfarm-twin`; it has only ever run beside the script. A folder whose path begins with a dot has not been tried with the app's tools.
7. **The twin's own check** as the source for `--app-check`: that the build the check names is the one in `app/overlay/packages/functions/src/build.ts`.
8. **The move of settings from the earlier issues.** A folder that ran an earlier issue has `config/demo.env` with a suffix. The next run moves it to `.deploy/<suffix>/demo.env` and goes on with the same deployment and the same checkpoint. This ran against a copy of that layout only. Likewise unproven: a second deployment beside a first, and the scripts started by hand finding the current one.
9. **The questions in a real terminal.** Seen on 25 November up to the region of a new capacity. The workspace and the VM size were answered by a script of answers only.
10. **The vCPU quota.** The shape of what `az vm list-usage` answers, and the names of the size families in it, which the runner derives from a size's name (`standardDSv7Family` for `Standard_D8s_v7`). A family it does not find is `NOT CHECKED`.
11. **A capacity made by the runner**, when you choose one: what the field `restrictions` in Azure's list of SKUs means (seen empty for every region on 25 November; the reference does not describe it, and the runner does not read it), the request through `az rest` with a JSON body, what Azure answers and how long it takes, the name under which Fabric lists the capacity (the runner looks for its Azure name), and what Azure says when the quota of capacity units does not cover it (the runner looks for the word quota).
12. **An existing workspace you chose**: nothing new is asked of Fabric for it, and nothing of it has run.
13. **A capacity Fabric does not list for you.** Whether Create Workspace accepts it, and what Fabric answers when it does not. The runner turns an answer with 401, 403 or the word capacity into a block; any other answer shows as a failure with Fabric's own words.
14. **How a trial capacity appears in the list of capacities.** The runner takes the SKU `FT` with a number, or `Trial`, for one; Microsoft's reference shows F SKUs only.
15. **`infra/01` under the runner**: without the provider registration, the group creation and the role assignments; and with `VM_SIZE_SKIP_CHECK=1`, where `az vm create` itself has to refuse the sizes you are not offered. The script moves on at the words `SkuNotAvailable`, `not available in location` and `NotAvailableForSubscription`; any other refusal ends it with Azure's message.
16. **The roles of the VM's identity**, read with the filter `principalId eq '…'` and assigned by role ID. (The same operation with the filter for a person answered on 25 November.)
17. **Arc onboarding with Reader on the resource group** instead of the subscription.
18. **The Eventhouse's own database.** The runner waits two minutes for the database Fabric gives a new Eventhouse, then creates one. Whether the API-created Eventhouse brings one is not written where I read.
19. **The Kusto audience for the Azure CLI's token** on a Fabric Eventhouse.
20. **The eventstream definition**: a custom endpoint with empty properties, and the destination with the Eventhouse's item ID as Microsoft's article has it. That article does not say how the database is chosen; this demo's Eventhouse has one. Microsoft warns that a property set which does not fit is accepted and ingests nothing; the gate after it is there for that, and the fallback is the wizard.
21. **Whether ingestion created this way reads JSON without a format label**, which the wizard needed set by hand.
22. **Shortcuts to KQL tables through the API** before the first write of OneLake availability.
23. **Notebook import**: the part named `notebook-content.ipynb` (the REST reference; an older article says `artifact.content.ipynb`), and the default Lakehouse taking effect for a job.
24. **Notebooks 01, 02, 03, 05 as jobs**: they have only run interactively. Parameters reaching the gate notebook's cell.
25. **The schedule payload** with unzoned times and `UTC`, which is how Microsoft's samples write it while its text asks for a `Z`.
26. **The result file of the gate** over the OneLake API. The verdict does not depend on it.
27. **The SQL probe** with a token for `https://database.windows.net`.
28. **`npx rayfin up` started without a terminal**, and how it says that it is not signed in. The runner recognises the words sign in, log in, keychain and 401; anything else is reported as a failure with the tool's own lines.
29. **The times.** No step has been timed under the runner, so this document promises none. Every check that takes five seconds or more prints its seconds. Measured so far, on 25 November from a workstation under WSL: the eight provider questions took 11 s together, and the questions about roles and VM sizes ran into their limits of 180 s and 120 s without an answer. Why answers of several megabytes do not arrive on that workstation is not known. `apply` sends about 3.5 MB from it to the VM (the repository, over SSH) and notebooks of about 120 KB each to Fabric, and Phase 4 installs the app's packages from npm there: how those fare is not known either.

## Tests

`simulator/tests/test_deploy_runner.py`, 111 tests against `simulator/tests/deploy_fakes.py`, a pretend Azure and Fabric that answer in the documented shapes and record every change:

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
| One folder, many deployments (fifth issue) | nothing prepared, and nothing ever written into `config/`; a second deployment beside the first, each with its own settings and checkpoint, the first untouched; a suffix never drawn twice; `--deployment`, an unknown suffix, several deployments with none current, a deployment whose folder was deleted; an apply with the plan of another deployment; a new deployment in another subscription only on request, with nothing taken from here; a vanished resource group shown as drift, and the deployment never swapped for another (the last two rewritten at the seventh issue, which removed what was taken over and the two questions); the settings of the earlier issues moved once, a file made by hand left alone, a stray copy never replacing a deployment's own; every script handed the settings of its deployment |
| After the first questions on a tenant (sixth issue) | every entry of a SKU in Azure's list is read, whichever way the list is laid out; a list without the SKU is not a refusal; a region the list does not name is said with the list, taken only on a yes, shown as not checked, and the yes holds for that region only |
| Hardening (seventh issue) | a repeat deployment with no question and no option, from a saved profile; an ambiguous capacity and a missing region stop with the candidates and write nothing; a pinned capacity that is gone blocks and no other is taken; the choice to make a capacity is not inherited and needs its own approval; a deployment that has its resource group is not moved by an option; a capacity to be made is shown in the plan with its SKU, region, resource group, administrator and what is billed; a changed VM size, SSH range, setting, shipped file or operator voids the approval and the refusal says what differs, and a confirmation given with it is not kept; every call names the deployment's subscription whatever the CLI is on, and a sign-in that does not reach it is refused; apply names its deployment; two deployments build the app in two folders; an apply that ended before Fabric answered neither repeats nor takes a run by itself; a run that finished meanwhile is taken; a finished plan applied again adds nothing; a silent script is stopped at its limit with what it had started; stale telemetry, another build or old data in the app, and a phase that is not built, are not demo-ready; the checkpoint is read again under the lock |
| And | approval of exactly one plan; a changed file and drift void it; role changes wait and stay on the resource group; Phase 5a absent by default, switched off when present, notebooks 12 and 13 impossible to run; the history once and once per label; the schedule in the future; preflight; the KQL splitter; the gate notebook's logic; the real adapters |

One hundred and ninety-five faults were planted, one at a time. Of the twenty-two of the first issue, twenty-one made a test fail at once; the twenty-second, a key written into the settings with its last character cut off, passed until the test also searched for the middle of each key. The twenty-eight of the third issue each made a test fail at once. Of the forty-three of the fourth issue, in the questions, the new capacity, the chosen workspace and the quota, thirty-nine made a test fail at once; four passed until a test was made to look at the right place: questions asked by `apply`, questions asked while an apply runs, Phase 3 reading a capacity that is still to be made, and the quota asked about a VM that exists. Of the forty-five of the fifth issue, thirty-seven in the runner and eight in the way the scripts find their settings (those against the scenarios of `tools/script-tests/run.sh`), forty-four made a test fail at once; one passed until a test looked for it: a checkpoint folder without settings counted as a deployment. The thirteen of the sixth issue, in the reading of the list of SKUs and the question about a region, each made a test fail at once. Of the forty-four of the seventh issue, thirty-seven in the runner (the pin, how a choice is settled, the saved plan, the journal of a notebook run, the script's limit, readiness) and seven in the scripts (the subscription named for them, the clean-up, the app's folder), forty-two made a test or a scenario fail at once; two passed until a test looked for them: an option for the region moving a deployment that has its resource group, and a deployment called demo-ready for a phase of which nothing is built.

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
- [Job Scheduler - Run On Demand Item Job](https://learn.microsoft.com/en-us/rest/api/fabric/core/job-scheduler/run-on-demand-item-job), read again on 25 November for the seventh issue: the answer carries `Location` and `Retry-After`; no request header or body property is documented by which a caller could mark a request or find its run again.
- [Manage the environment through public APIs](https://learn.microsoft.com/en-us/fabric/data-engineering/environment-public-api), [Create Environment](https://learn.microsoft.com/en-us/rest/api/fabric/environment/items/create-environment) and [Create, configure, and use an environment in Fabric](https://learn.microsoft.com/en-us/fabric/data-engineering/create-and-use-environment): an environment with a definition, `Libraries/PublicLibraries/environment.yml`, staging libraries, publish; publishing runs as a Spark job; notebooks attach to an environment.
- [Get servicePrincipal](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-get): `GET /servicePrincipals(appId='{appId}')`, with `$select`.
- Azure CLI 2.93.0, installed here and run without a sign-in: which commands take `--subscription` (`az version`, `az account …`, `az rest`, the resource commands) and which end with "unrecognized arguments" (`az extension list`, `az config get`); `az account get-access-token --resource-type ms-graph`.
- [Create a data flow in Azure IoT Operations](https://learn.microsoft.com/en-us/azure/iot-operations/connect-to-cloud/howto-create-dataflow) and the [Dataflow REST reference](https://learn.microsoft.com/en-us/rest/api/iotoperations/dataflow/create-or-update): `mode`, `Enabled` or `Disabled`.
