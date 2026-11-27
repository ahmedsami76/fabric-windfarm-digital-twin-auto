# The deployment runner

`tools/deploy.py` deploys the demo step by step, from an empty subscription and an existing Fabric capacity to the twin in a workspace. It starts the scripts and notebooks of this repository in the order of the guides, looks at Azure and Fabric before and after every step, and stops with an exact instruction wherever a person has to act.

**Status. Written on 25 November 2026. Its first command, `preflight`, ran on a tenant four times that day; three of the runs were sent to me. They showed errors of the runner, corrected in the second and third issue; the run of 15:40 showed the third issue reading the roles and the capacities rightly. The fourth issue added what was asked for after that run: the runner asks its questions itself (the region, the capacity, the workspace, the VM size), and can make a Fabric capacity when you say so. This fifth issue answers the request of 16:35: no settings file is prepared or kept in `config/`; every deployment gets its three random characters when it is started and keeps its settings beside its checkpoint, so one folder serves build after build, in one tenant or in several. See [Deployments](#deployments). At 17:17 the questions ran on a tenant for the first time, and the one about a new capacity said that F16 is not offered in Central US, where the same subscription runs an F16: the runner had read one entry of Azure's list of SKUs instead of all. This sixth issue reads the list whole, never takes a list that does not name the SKU for a refusal, shows the list with every such message, and leaves a region the list does not name to you. With it, a plan ran to its end on a tenant at about 17:50, for a new F16 in Central US. This seventh issue is a hardening asked for at 18:08: choices are settled from options, settings, a saved profile and what the cloud shows before anybody is asked; an approval covers a saved plan with everything that changes what runs; every call is pinned to the deployment's subscription; an apply names its deployment; a notebook run is taken only when the runner knows it to be its own; a script has a time limit by the clock; and `provisioned`, `blocked` and `demo-ready` are three words. On 25 and 26 November the seventh issue ran on a tenant for the first time, as the pilot of [16-runner-pilot-checklist.md](16-runner-pilot-checklist.md): a plan from options with no question, and the first `apply`, which made the resource group, the VM, the roles of its identity, K3s and the Azure Arc connection, and stopped three times on the way. Each stop is a finding of the [validation log](runner-validation-log.md) (R68 to R70) and a change of this ninth issue: a list of role assignments that lags, a workstation that large answers from Azure do not reach, and a subscription whose policy closes SSH. Azure IoT Operations was deployed by the runner's script, started by hand from Azure Cloud Shell. With the ninth issue the simulator was deployed through the VM agent, and the runner made its first Fabric items: the workspace, the Eventhouse with its tables and policies, the Lakehouse, the shortcuts. Fourteen of the twenty-five steps of Phase 1 were complete on that tenant then. The eventstream stopped on an address Fabric named on a regional host (R72), which the tenth issue asks about on the API. The eventstream then stood there with a failed destination: Fabric wants the KQL database's ID where Microsoft's article has the Eventhouse's (R74). The eleventh issue names the database, and writes the definition of such an eventstream again. With it the live path stood: at 14:03 on 26 November the runner measured 60 readings from 12 turbines in the Eventhouse, the newest 9 s old, and nineteen of the twenty-five steps were complete. The three applies after that each ended on a single call that got no answer, on a line that carried megabytes a second (R76). The twelfth issue asks a read again, never sends a change twice, and keeps a complete step complete when it could not be looked at for a moment. Its first apply, at 15:48, ended at the first script it started: the question `push` asks the VM agent got no answer for five minutes (R77). The thirteenth issue gives that question a time limit and three tries, and asks six slow questions of one look together (R78). With it, on 26 November at 16:50, Phase 1 ran to its end under the runner on that tenant: 25 of 25 steps, the reference upload, the notebooks as jobs, the schedule and the Lakehouse gate among them. The report of that apply could not measure the telemetry, because the Fabric token had ended (R80); the fourteenth issue asks for a new one and makes the request once more. At 17:13 the twin's live route was asked for as a step of the runner ("live from KQL and delayed with lakehouse", as in the deployment by hand): this fifteenth issue makes the service principal for it, under the approval of role changes, and deploys the app a second time. See [The twin's live route](#the-twins-live-route). With it the first steps of Phase 2 ran on the tenant at 18:05: the prepared views, the import of four notebooks, and notebook 05 as a job. That apply was given a confirmation for a result that did not exist yet, and kept it (R84); with the sixteenth issue a confirmation of a result counts only once the step it speaks of is complete. At 20:33 the rest of Phase 2 and Phase 3 up to the operations agent ran on the tenant: notebooks 06 to 09, whose first cell is `%pip install`, ran as jobs at the first try with `--opt-in pip-jobs` (R86), and the data agent was built by one of them. Asked that evening: the same without an option, and the two agents made by the runner. This seventeenth issue runs those notebooks itself unless you say `--no-pip-jobs`, and with `--allow-preview operations-agent` it creates the operations agent with its instructions and its data source through the API Microsoft documents (a preview); the playbook, the start and Teams stay yours, because nothing documented does them. See [The operations agent](#the-operations-agent). The creation has not run on a tenant: the agent of the pilot was made by hand before the issue arrived, and the runner found it and read its definition. At 21:34 Phase 4 began under the runner: the app was built in the deployment's folder, with one `npm install` that stood for sixteen minutes on that line, and `npx rayfin up` deployed it. The runner then called the step failed, because the workspace lists the app as two items of one name and its look wanted exactly one (R91). This eighteenth issue finds the app as one item or as two, counts a scaffold as done only after the script's own check has passed (R89), and makes npm wait one minute and try six times (R90). With it, at 22:09, the runner found the deployed app (two items, of the types AppBackend and UserDataFunction), made the service principal for the live route, handed its secret to the app and deployed the app a second time: 42 of 43 steps. The last, the runner's own question to the Lakehouse's SQL endpoint, did not get asked: its probe looked for the SQL driver beside itself, where a deployment by hand has the app, and not in the deployment's folder (R93). The nineteenth issue tells the probe where the app is, and with it, at 22:24 on 26 November, the deployment was complete: `provisioned yes: 43 of 43 steps`, Phases 1 to 4, begun on 25 November at 23:56. Asked then: Phase 5 as well, with 5b and 5c in the runner's scope. This twentieth issue provisions everything of Phase 5 that sends nothing, behind one option, and leaves switching the command path on, the agent's new setup, and every command and fault to a person. See [Phase 5](#phase-5). Its first applies, at 23:11 and 23:14 on 26 November, built the ontology with notebook 11 as a job and then stopped twice on defects of the runner: the script for the command path read a new eventstream's layout before Fabric had built it (R94), and the check for foreign items in the workspace took the Lakehouse that Fabric makes for an ontology for a stranger (R95). This twenty-first issue corrects both. Before it was copied, with the two acknowledgements the block offered, the command path's script went through at its second start, at 23:34, and every step of Phase 5 that is the runner's was done on that tenant. At 23:51 the runner read the agent a person had changed by hand and found the Phase 5b instructions, the action and a playbook of one rule, and no start; started, the deployment stood complete with Phase 5 at 23:57, by the operator's word: 50 of 50 steps. The report of 23:51 said "a started agent" two lines under a block that said "is not started" (R96). This twenty-second issue writes that sentence from the agent's definition, read in the same run; it changes nothing the runner sends or makes.** Everything the runner does was exercised against stand-ins on the computer it was written on (143 tests, 331 planted faults, all caught); the 111 tests of the seventh issue also passed on the workstation of the tenant runs, on 25 November at 23:09. Most of what it starts, the scripts of `infra/` and `edge/` and the notebooks, ran on a tenant between 19 and 25 November, started by hand. [What has been proven where](#what-has-been-proven-where) keeps the two apart, and [Unproven on a tenant](#unproven-on-a-tenant) lists what your next run decides. Expect it to find something; send me what it prints.

It does not replace the guides. Each step names the guide's step it comes from, and the guides remain the way to deploy by hand or to understand what a step does.

## What it will never do

- Change a tenant setting.
- Make a Fabric capacity unless you answered yes to that question and approved the step. It never pauses, resumes, resizes or deletes a capacity, and never moves a workspace to another one.
- Work in a resource group that it did not create itself, or in a workspace that it did not create, with one exception: an existing workspace that you chose in answer to its question and that is empty.
- Grant a role outside the demo's resource group or workspace, or grant any role without `--approve-role-changes`.
- Make anything in Microsoft Entra ID but one app registration of the deployment's own, with its service principal and one secret, for the twin's live route; and not that without `--approve-role-changes`, or with `--lakehouse-only`.
- Register a resource provider: that changes the whole subscription, and is left to you with the commands.
- Delete anything. Removing a deployment stays with `bash infra/99-cleanup.sh`.
- Run notebook 12 or 13, publish to the control topic, or inject a fault. It has no code that could.
- Switch the command path of Phase 5 on, or change an operations agent that exists: its instructions, its actions, its playbook, whether it runs.
- Click through a portal. Where there is no documented API, it says what to do and waits.
- Write an operations agent's playbook, start an agent, or send a request in a form Microsoft has not written down. With `--allow-preview operations-agent` it creates the agent stopped, with an empty playbook, as the reference says to.
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
| `needs approval` | Waits for `--approve-role-changes` or `--allow-preview` |
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
| `--confirm STEP` | You confirm what the runner cannot read: `phase1.tenant_settings`, `phase3.tenant_settings`, `phase4.tenant_settings`, `p2.acceptance`, `p5a.isolation`. The checkpoint keeps who and when. A confirmation of a result (`p2.acceptance`, `p3.data_agent_test`, `p3.agent_message`) counts only when it is given with the step it speaks of complete: given earlier, it is not kept, and the apply says so |
| `--allow-preview ontology` | Let the runner run notebook 11. Without it the ontology is optional and yours |
| `--allow-preview data-agent-sdk` | Let the runner run notebook 09, which builds the data agent with a preview SDK. Without it that notebook is yours |
| `--allow-preview operations-agent` | Let the runner create the operations agent with its instructions and its data source, stopped. A preview API. Without it the whole agent is yours. See [The operations agent](#the-operations-agent) |
| `--no-pip-jobs` | Leave notebooks 06 to 09 to you. Without it the runner runs them as jobs: seen to work on one tenant on 26 November 2026, and written down by Microsoft for pipeline runs only. `--opt-in pip-jobs` of the sixteenth issue is still accepted and changes nothing |
| `--enable-phase5a-isolated-simulator` | Also provision the command path of Phase 5a, switched off |
| `--enable-phase5-isolated-simulator` | Also provision Phases 5a, 5b and 5c: the command path switched off, the two tables and the function, notebooks 12 and 13 imported and never run. See [Phase 5](#phase-5) |
| `--lakehouse-only` | Phase 4 without the service principal: nothing is made in Microsoft Entra ID, and the twin shows the Lakehouse's copy, minutes behind. For a tenant that does not let you register an application. Part of what a plan covers |
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

1. **An option of this run**: `--edge-region`, `--capacity` or `--new-capacity --capacity-region`, `--workspace-id`, `--vm-size`, `--ssh-source`. **Seen on 25 and 26 November:** a plan and four applies ran with every call pinned; `az iot ops` commands take the option.
2. **The settings of the deployment**, `.deploy/<suffix>/demo.env`: what an earlier plan settled, or what you wrote there. **Seen on 25 November:** both reads answered.
3. **The profile** saved for the tenant and subscription with `--save-profile`. **Seen on 25 and 26 November.** The saved plan file itself was not looked at.
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
| With which approvals | the role grants the plan lists, and the approvals and opt-ins of the run: roles, capacity, previews, `--no-pip-jobs`, Phase 5a, a label for regenerating the history |
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

A complete step that a run could not look at, because its question got no answer, stays complete: no answer is no finding. The run still ends there with exit code 3, `provisioned` says `no … this run did not get to look at all of them`, and the `blocked` line names the step as `complete and could not be looked at just now`. The next apply that sees it takes the note away. A step that was looked at and is not in order is blocked, as before.

Demo-ready needs, for Phase 1: telemetry in the Eventhouse **measured now**, from twelve turbines, the newest reading at most three minutes old; and the Lakehouse's tables measured as populated. A stopped edge is provisioned and not demo-ready.

For Phase 3 it also needs your word that the operations agent's message reached Teams: `--confirm p3.agent_message`. An item of the agent exists as soon as it has been created; that is not proof that the agent is configured, running or delivering. With `--allow-preview operations-agent` the runner also reads the agent's definition and wants a playbook and an agent that is started; whether its message arrives is still yours to say.

For Phase 4 it needs the deployed app's own connection check. The runner's gate after the deployment is a query **with the operator's token**: it shows that the data is there for you, not that the app, which reads as another identity, reaches it. The runner has no documented way to ask the deployed app, so it asks you once: open the app, select the badge, and pass what the check shows with the next apply.

```bash
python3 tools/deploy.py apply --deployment 3x9 --approve PLAN --up-to phase4 --approve-role-changes --app-check 455aa9777780,eventhouse,40
```

The three values are the build the check names, the route that says PASS, and the age of the newest reading in seconds. The twin is demo-ready when the build is the one the repository is at, and the reading is at most 15 minutes old on the Lakehouse route or 2 minutes on the Eventhouse route. A check that names another build, or older data, is a failed connection for a demo, and the report says which. A deployment with the service principal is to show the live values: a check that passes on the Lakehouse route only means the twin has fallen back, and is not demo-ready. With `--lakehouse-only` the Lakehouse route is what is asked for.

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

## The twin's live route

A Fabric app runs as its owner and gets no token the Eventhouse accepts. So the twin has two routes for its values: the Lakehouse's copy of the tables, minutes behind, which needs nothing; and the Eventhouse itself, seconds behind, which it reads as a service principal. Since the fifteenth issue the runner sets up both, as the deployment by hand of 23 November had them.

- **What is made**, by `p4.eventhouse_principal`, after `--approve-role-changes`: in Microsoft Entra ID one app registration named `windfarm-twin-eventhouse-reader-<suffix>`, its service principal, and one client secret valid for a year; in Fabric the Viewer role for that principal in the demo's workspace, and three secrets of the app (tenant, client ID, client secret). Then `p4.deploy_secrets` deploys the app once more, so that its functions read them.
- **A registration for each deployment.** Making a secret replaces the one before it. Under one shared name, every new deployment would have taken the twin of the one before it off its live route.
- **The secret.** `app/create-principal.sh` makes it and hands it to the app's tool in a file that it deletes; the runner deletes that file too if a stopped run left it. The runner never reads the secret, and it is neither printed nor in the checkpoint. What the checkpoint holds is when the registration's newest secret was made, which is how a later apply sees that somebody has replaced it since.
- **What the runner cannot see**: whether the Eventhouse answers the principal. That is the twin's own connection check, which you read and pass with `--app-check BUILD,eventhouse,SECONDS`.
- **A tenant that does not let you register an application, or make a client secret**: the step blocks with Microsoft Entra ID's words. `plan … --lakehouse-only` leaves the principal out; the twin then runs on the Lakehouse route, and that route is what demo-ready asks for.
- **The directory commands follow the Azure CLI's active subscription.** `az ad` takes no `--subscription`. Under the runner the script goes on only when the active subscription is in the deployment's tenant, and says how to select it when it is not.
- **Removing a deployment** leaves the registration: it is in the directory, not in the resource group or the workspace. `bash infra/99-cleanup.sh` says so in its last lines, with the command to delete it.

## Who the runner is

Every call the runner makes is made as you, with the sign-in of the Azure CLI. It refuses a service principal. The reason is the steps that accept a person only: the lookup of the Custom Locations object ID in Microsoft Entra ID, the notebooks of Phase 2 that build the model with semantic link, the data agent, the operations agent. One identity for a run also means one answer to "who did this".

Where the demo itself runs, it uses managed identities and no keys, as the guides do: the VM's identity onboards the cluster and uploads the reference files, and the identity of the Azure IoT Operations extension sends to the eventstream.

Most Fabric operations the runner uses also accept a service principal or a managed identity; the table under [Sources](#sources) says which were read. Running those parts under a federated workload identity, in a pipeline, is possible and not built: it would need two sign-ins in one run, and the first live run should come first.

## How it knows the target is its own

- **The resource group** carries the tag `windfarm-demo-deployment` with the suffix, and its ID is in the checkpoint. A group of that name without the tag is never used.
- **The workspace** has the suffix in its description, and its ID is in the checkpoint. A workspace of that name that the runner did not make is never used. A workspace you chose is held by its ID, in the settings and in the checkpoint, and was empty when the runner took it.
- **A capacity the runner made** is in the demo's resource group and carries the same tag. A capacity of that name without the tag is never used.
- **Inside them**, a resource of a provider the demo does not use, or an item the demo does not create, stops the runner until you move it or name it with `--acknowledge`. What the demo's own items bring with them is the demo's: the SQL endpoint of the Lakehouse, the two items of the deployed app, and the Lakehouse with its SQL endpoint that Fabric makes for an ontology (`WindFarmOntology_lh_` and 32 hexadecimal digits; seen on 26 November 2026, when the runner still stopped on it).
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
| `p1.eventstream` | Eventstream with direct ingestion into RawEvents | the runner | eventstream es-windfarm-edge: a custom endpoint, and the Eventhouse as destination with the mapping RawEvents_mapping | Learn: Create an Eventstream with an Eventhouse DirectIngestion destination by using APIs; Update Eventstream Definition |
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
| `p2.semantic_model` | Semantic model built (notebook 06) | the runner; you with `--no-pip-jobs` | runs 06_build_semantic_model as a job, with %pip switched on by the parameter Microsoft documents for pipelines | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p2.acceptance` | Model tested against the Lakehouse (notebook 07) | the runner; you with `--no-pip-jobs` | runs 07_model_acceptance as a job, with %pip switched on by the parameter Microsoft documents for pipelines | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p2.report` | Report built (notebook 08) | the runner; you with `--no-pip-jobs` | runs 08_build_report as a job, with %pip switched on by the parameter Microsoft documents for pipelines | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p2.schedule` | Model tables refreshed every hour | the runner | one hourly schedule for notebook 05 | Job Scheduler - Create Item Schedule (Cron, interval in minutes) |
| `p2.gate` | GATE: model tables populated | gate | one run of the gate notebook | Job Scheduler - Run On Demand Item Job; the job's state is the verdict |

**Phase 3**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `p3.capacity` | A paid capacity for the agents | check | nothing | GET /v1/capacities |
| `phase3.tenant_settings` | Tenant settings for Phase 3 | you | nothing | Fabric admin portal |
| `p3.notebooks` | Notebooks 09 to 11 imported | the runner | three notebooks | Notebook - Create Notebook (definition, ipynb) |
| `p3.data_agent` | Data agent built (notebook 09) | you; the runner with `--allow-preview data-agent-sdk` | runs 09_build_data_agent as a job, with %pip switched on by the parameter Microsoft documents for pipelines | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p3.data_agent_test` | Data agent tested (notebook 10) | you, optional | nothing | Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only |
| `p3.ontology` | Ontology built (notebook 11, preview) | you, optional; the runner with `--allow-preview ontology` | runs notebook 11, which creates the ontology item | Job Scheduler - Run On Demand Item Job (RunNotebook) |
| `p3.agent_readiness` | KQL database prepared for the operations agent | the runner | descriptions of the columns, and the table GearboxVsFleetLive with its update policy | Kusto REST API, .execute database script |
| `p3.operations_agent_item` | Operations agent created, with its instructions and its data source | the runner, only with `--allow-preview operations-agent` | the operations agent WindFarmGearboxWatch: the instructions of fabric/operations-agent/agent-setup.txt, the KQL database as its data source, no action, no playbook, not started | Operations Agent - Create Operations Agent (preview, a person only); Operations agent definition |
| `p3.operations_agent` | Operations agent set up and started, Teams app installed | you; less of it with `--allow-preview operations-agent` | nothing | none: portal only (preview) |

**Phase 4**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `phase4.tenant_settings` | Tenant setting Fabric Apps | you | nothing | Fabric admin portal |
| `p4.node` | Node.js on this computer | check | nothing | node --version |
| `p4.scaffold` | App created from Microsoft's template, with the twin laid over it | the runner | the app's folder of this deployment on this computer, .deploy/<suffix>/app/windfarm-twin; nothing in Fabric | app/create-app.sh |
| `p4.deploy` | App deployed to the workspace | the runner | the Fabric app item WindFarmTwin, its page and its seven functions | npx rayfin up --workspace NAME --item-name NAME (Rayfin 2.0.1) |
| `p4.eventhouse_principal` | Real-time values: a service principal that reads the Eventhouse | the runner, after `--approve-role-changes` | in Microsoft Entra ID: one app registration named windfarm-twin-eventhouse-reader-<suffix>, its service principal, and one client secret valid for a year, which replaces any earlier secret of that registration. In Fabric: the Viewer role for that principal in the demo's workspace, and three secrets of the app. The secret is never shown or stored | app/create-principal.sh (az ad app create, az ad sp create, az ad app credential reset; Workspaces - Add Workspace Role Assignment; npx rayfin secret set); read with Microsoft Graph, GET /applications |
| `p4.deploy_secrets` | App deployed again, so that its functions read the secrets | the runner | the app's page and functions, deployed a second time | npx rayfin up --workspace NAME --item-name NAME (Rayfin 2.0.1) |
| `p4.gate_data_route` | GATE: the Lakehouse answers the twin's query (asked with the operator's token) | gate | nothing; one query against the SQL endpoint of the Lakehouse | SQL analytics endpoint, with a token for https://database.windows.net |
| `p4.connection_check` | The app's own connection check: what makes the twin demo-ready | you, optional | nothing | the app |

**Phase 5a, only with `--enable-phase5a-isolated-simulator` or `--enable-phase5-isolated-simulator`**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `p5a.isolation` | This edge is an isolated simulator | you | nothing | none: a statement only a person can make |
| `p5a.command_path` | Command path provisioned, switched off | the runner | eventstream WindFarmCommands, endpoint fabric-commands, and the data flow fabric-to-windfarm-control with mode Disabled | infra/08-create-command-path.sh; az iot ops dataflow apply with "mode": "Disabled" |
| `p5a.notebook` | Notebook 12 imported, not run | the runner | imports the notebook. It is never run by the runner | Notebook - Create Notebook (definition, ipynb) |
| `p5a.enable` | Switch the command path on and send a command (yours) | you, optional | nothing | docs/12-deployment-guide-phase5a.md |

**Phases 5b and 5c, only with `--enable-phase5-isolated-simulator`**

| Step | What | Who | Changes | Rests on |
|---|---|---|---|---|
| `p5b.decision_table` | Table the agent decides on, with what a curtailment costs | the runner | the table GearboxDecisionLive, its descriptions, and the update policy that fills it from the telemetry | Kusto REST API, .execute database script |
| `p5c.command_log` | The edge's record of every command: table and function | the runner | the table EdgeCommands with its update policy, and the function CommandLog | Kusto REST API, .execute database script |
| `p5c.notebook` | Notebook 13, the command center, imported, not run | the runner | imports the notebook. It is never run by the runner | Notebook - Create Notebook (definition, ipynb) |
| `p5b.agent` | Operations agent changed to its Phase 5b setup: instructions, action, playbook, started | you | nothing | Operations Agent - Get Operations Agent Definition (preview), for the look; the change itself: portal |
| `p5.show` | Switch the command path on and show Phase 5 (yours) | you, optional | nothing | the guides of Phases 5a, 5b and 5c |

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
| Notebooks 06, 07, 08, only with `--no-pip-jobs` or after a job of theirs failed | Open each, **Run all** | The semantic model and the report as items; for 07 your `--confirm p2.acceptance` |
| Notebook 09, until you pass `--allow-preview data-agent-sdk` | Open it, **Run all** | The data agent as an item |
| Operations agent and Teams, without `--allow-preview operations-agent` | Step 9 of the Phase 3 guide | An item of type OperationsAgent named `WindFarmGearboxWatch`. Not whether it runs, and nothing of Teams |
| Operations agent, with `--allow-preview operations-agent` | Open the agent the runner created, **Generate playbook**, read the rules, install the Teams app, **Start** | The agent's definition: a playbook, the number of its rules, and whether the agent is to run. Nothing of Teams |
| Sign-in of the app's tool | `npx rayfin login` in `app/windfarm-twin` | It runs `npx rayfin up` again |
| Service principal for real-time values | Nothing: the runner makes it (`p4.eventhouse_principal`), after `--approve-role-changes`. With `--lakehouse-only` it is yours and optional: `bash app/create-principal.sh` | The app registration by its name, its service principal, its role in the workspace, and whether its newest secret is the one the runner handed to the app |
| The agent's Phase 5b setup, with `--enable-phase5-isolated-simulator` | Step 4 ("By hand") and step 5 of the Phase 5b guide: instructions, the action `Curtail turbine`, playbook, Start | The agent's definition: the instructions, the action and its notebook, a playbook, started |
| Command path, Phase 5a | Confirm the edge is an isolated simulator; later switch the path on and send | Your `--confirm p5a.isolation`; the data flow's mode |

**Notebooks 06 to 09 and `%pip`.** Their first cell is `%pip install`. Microsoft documents that inline installation is switched off in notebook runs started by a pipeline, and how to switch it on there with the parameter `_inlineInstallationEnabled`. For a run started through the Job Scheduler API it says nothing. The runner passes that parameter. On 26 November 2026, on one tenant with Runtime 2.0, notebooks 06, 07, 08 and 09 ran to their end that way at the first try (R86), and since the seventeenth issue the runner does it without being asked. That is one observation, not a statement of Microsoft's: when such a job fails, the step blocks with the way by hand, and `--no-pip-jobs` leaves the notebooks to you from the start. Notebook 10, the data agent's test, is optional and always yours: it takes minutes of questions, and its result is for you to read.

## The operations agent

Asked on 26 November 2026: can the runner make the operations agent as well. What Microsoft documents, read that day:

- **Create Operations Agent**, `POST /v1/workspaces/{workspaceId}/operationsAgents`: a preview, for a signed-in person only, with an optional definition.
- **The definition**, one part named `Configurations.json`: `configuration` with the `instructions`, the `dataSources`, the `actions` and an optional message destination; `playbook`; and `shouldRun`. Of the playbook the article says it is reserved, and to send an empty object when it is not authored.

So the instructions and the data source can be sent, and the rules cannot: they are the playbook, which the portal generates from the instructions. With `--allow-preview operations-agent` the runner does the first and leaves the second:

| | Who | How |
|---|---|---|
| The item `WindFarmGearboxWatch`, the text of `fabric/operations-agent/agent-setup.txt` as its instructions, the KQL database as its one data source, no action, an empty playbook, `shouldRun` false | the runner, step `p3.operations_agent_item` | one request, in the documented form, with the data source kept under the database's ID as the portal keeps it. When Fabric refuses it, the step blocks with Fabric's line and the steps by hand; the runner tries no other form |
| The playbook | you | open the agent, **Generate playbook**, and read the three rules against the table in step 9 of the Phase 3 guide |
| The Teams app, and **Start** | you | as in the Phase 3 guide. The agent writes to the person who created it, and the runner created it as you |
| The look afterwards | the runner, step `p3.operations_agent` | Get Operations Agent Definition: is there a playbook, how many rules, is the agent to run |

It never writes a playbook and never starts an agent. Writing the playbook back from the definition files saved on 24 November would be a request Microsoft has not described, and an agent started by a program with rules nobody read is not what the demo is for.

**Not known until it runs on a tenant**, and a refusal would not surprise: on 24 November this tenant's Fabric refused an update of an agent's definition with `400: UnknownError` and no reason (obstacle B of [phase5-validation-log.md](phase5-validation-log.md)), and an empty playbook was one of the things that request held. What is open: whether Create takes the definition as the article has it (the reference's own sample names the part `OperationsAgentV1.json`; the runner sends `Configurations.json` with the sample's format `OperationsAgentV1`); whether the portal shows the instructions and the data source of an agent made this way and generates a playbook for it; whether the one text of `agent-setup.txt`, which the portal takes in one box, reads the same when it arrives through `instructions`; and under which key a definition read back carries its rules. The runner counts them under `RuleDefinitions`, which is what a definition read on this tenant on 24 November held; a playbook without that key counts as a playbook whose rules it does not count. An agent you made by hand under the same name is found and not made again.

## Interruption, time limits, drift

- **The checkpoint** is `.deploy/<suffix>/state.json`: every step with its state, the time, and what was measured. It is written in one move, ignored by git, and holds no secret. Keep it: it is the record that the resources are this deployment's.
- **One apply at a time, on one computer.** A lock file beside the checkpoint refuses a second apply to the same deployment on this computer, and the lock of an apply that died is taken over. Once it holds the lock, an apply reads the checkpoint and the settings again and trusts nothing it read before. **The lock is a file: it does not reach another computer.** Two people applying the same deployment from two computers are not kept apart by it; each has its own copy of the checkpoint. Run a deployment from one computer. To move it, copy the folder `.deploy/<suffix>/` and stop using the old one.
- **A plan while an apply runs** reads the checkpoint and writes nothing to it, and says so. Its copy is older than the one the apply keeps writing.
- **Answers that are kept.** Your roles, the resource providers and the VM sizes are asked once in twelve hours. Each answer is kept with what it depends on (the subscription, who you are, `LOCATION`, `VM_SIZE`): change one and the question is asked again. `--recheck` asks all three again.
- **A capacity Azure is still making** after 15 minutes ends the apply with exit code 4. The approval holds: a capacity to be made is part of the plan by its name, SKU and region, before and after it exists.
- **Long operations.** When Fabric answers "accepted", the address to ask about is written to the checkpoint before the first wait. Apply waits up to 15 minutes for an operation and 45 for a notebook, then ends with exit code 4. The next apply asks about the same operation and starts no second one. For a request that creates an item no intent is written first: the item's name is the key, and the step looks for the item by name before it creates anything, so a request that was taken and never answered is found as the item it made. When Fabric names that address on a regional host (`wabi-…-redirect.analysis.windows.net`, seen on 26 November) and not on the API as its reference shows, the runner asks the API about the same operation: the token is sent to the Fabric API and nowhere else.
- **A notebook run is the runner's only when the runner knows it.** Before the request to run a notebook leaves, the intent is written to the checkpoint; when Fabric answers, the run's ID replaces it. A run whose ID is in the checkpoint is asked about on resume, also when it finished while nobody waited, and its result is taken: no second run.
- **An apply that ended between the request and the answer** leaves an intent without an ID. Whether Fabric took the request is then not known, and Run On Demand Item Job documents no key by which a run could be matched to a request. The notebooks write data. So the runner neither starts another run nor takes one it finds: it blocks, lists the runs Fabric has since then, and you say which it was, `--adopt-job p1.history=ID`, or that there was none, `--resubmit p1.history`.
- **A run in progress that the checkpoint knows nothing of** is somebody's, not the runner's. It blocks on it and names `--adopt-job` for the case that it is yours.
- **A computer that large answers from Azure do not reach.** `az iot ops init` and `create` fetch answers of several megabytes and wait for them without a limit of their own. Before the runner starts their script it asks Azure for one such answer, the list of resource providers, and gives it 45 seconds. When it does not arrive, the step blocks and hands you the script with the exact command: run it where Azure answers quickly, Azure Cloud Shell for example, with the deployment's settings file; it skips what exists. The next apply finds the instance and goes on. Seen on 26 November: a workstation under WSL received 5 kB a second from Azure and 6 MB a second through Windows on the same machine, and the script stood for ninety minutes twice before it was run from Cloud Shell.
- **A subscription that closes SSH.** Some subscriptions remove the SSH rule of step 1 some hours after it was made, by a policy. A command for the VM then goes through the VM agent, as before. The repository cannot be copied that way, so `bash infra/vm.sh push` asks the VM, through the agent, whether its copy of what the edge scripts use (`edge/`, `simulator/`, `data/`) is the one in this folder. When it is, nothing needs copying and the settings are written through the agent; when it is not, the script stops and says that SSH is needed once. The runner never puts the rule back.
- **A call that gets no answer.** A read is asked again; a change is never sent twice. Through the Azure CLI, a call that changes nothing (`show`, `list`, `rest --method get`, a token) and has two minutes or more gets three tries within its time: a sixth of it, a third, a half, so that a read which is slow and not stuck still has half of the time in one piece; with a minute or more it gets two, a third and two thirds. A call that changes something is made once, with all of its time. To the Fabric API, OneLake, Microsoft Graph and the Eventhouse, a connection that fails before the request has been sent is made again, three tries in all, whatever the request: nothing has been acted on. A read whose answer does not come is asked again; a request that changes something and was sent is not, and the step reports `did not answer a request it was sent`: look before you run the apply again, which the apply does by itself. A query of the Eventhouse counts as a read, a management command does not. Seen on 26 November: three applies in a row ended on one hung connection each, while connections to the same hosts were made in a quarter of a second. A management command of the Eventhouse that only shows something counts as a read too, and the first try of a read has a minute at most. Of the `az` calls inside the scripts, one is asked again: the question `bash infra/vm.sh push` puts to the VM agent when SSH is closed, which has 150 seconds and three tries (`VM_AGENT_TRY_SECONDS`, `VM_AGENT_TRIES`); on 26 November it stood for five minutes and ended the step. The others are made once, as when you run the scripts by hand; a script that fails on one is started again by the next apply, and skips what exists. A command for the VM that got no result says that its fate is not known.
- **A token that ends during an apply.** The runner asks the Azure CLI for a new Fabric token every twenty minutes, and the CLI hands out the one in its cache until that one ends. A request Fabric refuses with 401 is therefore made once more with a token asked for at that moment; a 401 is a request that was not acted on. Seen on 26 November, at the end of an apply of about fifty minutes.
- **Role assignments that Azure lists a little later.** The step that gives the VM's identity its two roles waits up to two minutes for them to appear in Azure's list before it calls the result missing.
- **The app's libraries on a line that drops connections.** npm waits five minutes for an answer that does not come and tries three times. Seen on 26 November: one install of `app/create-app.sh` printed nothing for sixteen minutes and then went through. The script now tells npm to wait one minute and to try six times; for a line that is slow and not dropping, give it more: `npm_config_fetch_timeout=300000` in front of the command. Stopped half way, the script goes on from where it was at its next start: it looks for each library by itself. It writes `.twin-ready` into the app's folder last, after its check has passed, and the runner counts the app as built only with that line; the twin's files alone, which are copied early, are not proof.
- **A script has a time limit by the clock**, also when it prints nothing: its output is read apart from the clock. About once a minute of silence the runner says that it is still waiting. At the limit, and on Ctrl+C, the script and everything it started on this computer are stopped. What it began in Azure goes on there, and the next apply looks before it does anything.
- **History.** Notebook 02 is run once. `--regenerate-history 2026-12-01` runs it again, once for that label.
- **Schedules** are created to start ten minutes ahead: Microsoft's reference says a start in the past triggers a job at once. One schedule for a notebook; two switched on is a block.
- **Drift.** A step the checkpoint calls complete whose result is gone shows as `DRIFT` in the plan, changes the plan's identifier, and so needs your approval again.

## Secrets

The runner asks the Azure CLI for tokens (Fabric, the Eventhouse, storage, SQL) and hands each to its redactor at once. Every line it prints, every line of a script's output it shows, and every byte of the checkpoint passes that redactor, which removes the values it was told and anything shaped like a token, a key or a connection string. From Fabric's answer about the eventstream's endpoint, which holds keys, it takes the two names the edge needs and keeps nothing else. The edge authenticates with its managed identity, as in the guides; no key is used anywhere.

## Phase 5

Off unless you ask for it by its own option; `--up-to` ends at Phase 4. Phase 5 is the way back: a command from Fabric to a turbine (5a), the operations agent proposing a curtailment that a person approves in Teams (5b), and the edge's record of every command, shown in the twin (5c).

| Option | What the runner provisions |
|---|---|
| `--enable-phase5a-isolated-simulator` | Phase 5a only |
| `--enable-phase5-isolated-simulator` | Phases 5a, 5b and 5c. Asked for on 26 November 2026, with Phases 1 to 4 complete under the runner; until then 5b and 5c were out of its scope |

Both wait for your `--confirm p5a.isolation`: your statement that nothing but this demo's simulator listens on the edge's broker.

**What the runner does**, all of it things that send nothing:

- `infra/08-create-command-path.sh` with `COMMAND_DATAFLOW_MODE=Disabled`: the eventstream `WindFarmCommands`, the endpoint and the data flow exist, and the data flow is switched off, so no message from Fabric becomes a command on the edge.
- Notebook 12 imported, and with the second option notebook 13, the command center. Neither is ever run by the runner: it has no way to start them.
- With the second option, the database scripts of `fabric/kql/06-remediation-readiness.kql` (the table `GearboxDecisionLive`, which holds what a curtailment costs next to the gearbox readings) and `fabric/kql/07-command-log.kql` (the table `EdgeCommands` and the function `CommandLog`).

Three parts of Phase 5c need no step: the simulator the runner deploys reports its commands, the data flow of Phase 1 forwards them, and the twin of Phase 4 shows them once the table is there.

**What stays yours**, and why:

| | How | What the runner looks at |
|---|---|---|
| The agent's Phase 5b setup: new instructions, the action `Curtail turbine` on notebook 12, a new playbook, Start | In the portal: step 4, the part headed "By hand", and step 5 of [13-deployment-guide-phase5b.md](13-deployment-guide-phase5b.md). The block prints the steps | The agent's definition: the instructions word for word, the action with its notebook and four parameters, a playbook, started (`p5b.agent`). It changes nothing of the agent |
| Switching the command path on | `bash infra/08-create-command-path.sh` | The data flow's mode, which the report at the end of an apply names. A switched-off path is provisioned and not demo-ready |
| The rehearsal, every command, every fault, the approval in Teams | The guides of Phases [5a](12-deployment-guide-phase5a.md), [5b](13-deployment-guide-phase5b.md) and [5c](14-deployment-guide-phase5c.md) | Nothing |

The agent's setup is a person's because Phase 5b changes a running agent in place: it replaces the three rules of Phase 3 by one, and gives the agent an action that limits a turbine. The script that does it through Fabric's API, `bash infra/09-remediation-agent.sh`, was refused by Fabric on 24 November 2026; what I take for the cause is corrected and has not run since, and the form of an action it writes is not the one Microsoft's article shows. The runner does not start it. You can: it saves the agent's definition first and changes nothing when it is refused.

While the agent is stopped for that change, the look of Phase 3 at the same agent does not call its finished step undone: with the option, an agent that carries the Phase 5b action or instructions is `p5b.agent`'s to judge.

**Seen on a tenant so far**, 26 November from 23:11: the plan with its six steps for the runner and two for a person; the confirmation; and the script for the command path creating the eventstream `WindFarmCommands` from its definition. It then read the eventstream's topology in the same second, found no endpoint in it, and stopped (R94). Started again at 23:34, it found both endpoints, made the endpoint on the edge and the data flow, switched off, and the steps after it ran: notebook 12 imported, the two database scripts, notebook 13 imported. So Fabric builds the endpoints from the definition, some seconds after it lists the eventstream; since the twenty-first issue the script asks for the topology of an eventstream it has just created until both are in it, for two minutes at most, and that wait has not been needed on a tenant yet. At 23:51 the look at the agent read one a person had changed by hand: `the agent has the Phase 5b instructions, the action and a playbook with 1 rule, and is not started`. After the start the operator reported 50 of 50 steps (23:57; that output was not sent). Not seen under the runner or after it: the command path switched on, a command, the rehearsal, the agent's proposal and an approval. Those ran on 23 to 25 November in the deployment by hand.

## The `%pip` notebooks and a Fabric Environment

Asked on 25 November 2026, when notebooks 06 to 10 were still the operator's because of their first cell: can a Fabric Environment with pinned libraries take the place of `%pip install`? **Since 26 November the question is less pressing**: the notebooks ran as jobs with `%pip` as it is (see "Notebooks 06 to 09 and `%pip`" above). What follows is kept for a tenant where they do not.

**What Microsoft documents**, read that day: an Environment item can be created through the public API, with or without a definition; its libraries are given as an `environment.yml` among the definition's parts (`Libraries/PublicLibraries/environment.yml`) or uploaded to its staging state; and a publish operation applies them. Notebooks and Spark job definitions attach to an environment. So the supported parts exist.

**Why it is not built in this issue.** It is more than one call, and each part is unproven here:

1. The five notebooks would change. Their install cell would have to do nothing when the libraries are there, and they are generated from `tools/build-phase2.py` and `tools/build-phase3.py`; their present form is the one that ran on the tenant.
2. Publishing an environment runs as a Spark job of its own, which has to be waited for and can fail on a library. `semantic-link-labs` 0.15.2 and the alpha `fabric-data-agent-sdk` 0.1.36a0 on Runtime 2.0 have only been installed with `%pip` here.
3. How a notebook is attached to an environment through the API: the notebook's definition carries it, and I did not find the form written out for a run request. The runner does not guess a payload.
4. Notebooks 06 to 09 use semantic link and the data agent SDK as the person who runs them. As jobs started by the runner they ran once each, on 26 November.

**What would settle it**: one environment made by hand in the pilot's workspace with the two libraries, attached to notebook 06, and one run of it as a job. If that passes, the runner can create and publish the environment and import the notebooks attached to it, behind an opt-in. Until then the job with `%pip` is what the runner does, and the hand-off is what it falls back to.

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
| Step 7 of the Phase 4 guide: you run `bash app/create-principal.sh`; the registration is named `windfarm-twin-eventhouse-reader` | The runner starts the script, with a registration named for the deployment, `windfarm-twin-eventhouse-reader-<suffix>`, and then deploys the app again | The request of 26 November, 17:13. One name for every deployment would have let each new deployment replace the secret the one before it runs on |
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
| The engine: plan, approval, checkpoint, lock, resume, redaction | not applicable | yes | The settings file of a first run (then still in `config/`) and `preflight` to its end: yes, 25 November, with the second issue. `plan` to its end, with its identifier and the apply line: yes, 25 November, with the sixth. `apply`: yes, 25 and 26 November, deployment 66i, **Phase 1 to its end, 25 of 25 steps**, stopped and resumed more than a dozen times. `status`: **no** |
| The prerequisite checks | their commands and operations, yes | yes | Tools, sign-in, extension, eight providers, the storage name, the Custom Locations object ID, the Fabric API, Node.js, the roles with the light question, the capacities by SKU, answers kept between runs: yes, 25 November. The VM sizes: asked three times, **never answered** on that workstation. A capacity Fabric does not list: **no** |
| Scripts `infra/01`, `04`, `06`, `edge/scripts/02`, `03`, `05`, `07`, `app/create-app.sh`, `npx rayfin up` | their commands, yes | started by the runner: yes | by hand: yes, 19 to 25 November. Started by the runner on 26 November: `infra/01` with `DEPLOY_RUNNER=1`, the scripts for the edge host, the Arc connection and the simulator (on the VM, through the VM agent), and `infra/06`. `infra/04`, started by the runner, did not finish on that workstation and ran from Azure Cloud Shell by hand. The reference upload (`edge/scripts/07`, through the VM agent): yes, 26 November. `app/create-app.sh` and `npx rayfin up`, started by the runner: yes, 26 November, 21:34 |
| Workspace, Eventhouse, KQL database, Lakehouse, shortcuts, role assignment, notebook import, schedules through the Fabric API | yes, each read on 25 November | yes | Workspace, Eventhouse, KQL database, Lakehouse, OneLake availability, shortcuts, workspace role assignments, the import of five notebooks, the daily schedule of notebook 03: yes, 26 November |
| Eventstream with direct ingestion and a named mapping | yes, with the Eventhouse's ID as the destination's `itemId`, which Fabric refuses (R74) | yes | yes, 26 November, with the KQL database's ID; the definition of the existing eventstream was written again with Update Eventstream Definition, and readings from twelve turbines arrived in the table |
| Endpoint of the eventstream read through the Fabric API | yes | yes | yes, by notebook 12 |
| KQL and queries over the Kusto REST interface with the Azure CLI's token | for Azure Data Explorer, yes | yes | with a notebook's token and with a service principal: yes. From a workstation: yes, 26 November: the two database scripts, the policy commands and the gate's query |
| Notebooks as jobs | yes | yes | notebook 12, from a script: yes. Notebooks 01, 02, 03 and 05 and the gate notebook, by the runner: yes, 26 November. Notebook 11: **no** |
| Gate notebook, and reading its result file over the OneLake API | the APIs, yes | its logic, yes | yes, 26 November: `21 tables with rows; TurbineTelemetry newest 0.7 min old` |
| Lakehouse route probe with the Azure CLI's token | the driver's sign-in, yes | the hand-over, and since the nineteenth issue the probe itself with a stand-in for the driver | the same query by the app: yes. From a workstation: **no**: on 26 November the probe ended before it asked, for want of the driver where it looked (R93) |
| Notebook 11 as a job, and what the ontology brings with it | Run On Demand Item Job, yes; the ontology's own Lakehouse: not found written | yes, since the twenty-first issue with the Lakehouse | yes, 26 November, 23:11: `ontology WindFarmOntology exists`, and a Lakehouse and SQL endpoint named after it |
| Notebooks 06 to 09 as jobs with `%pip` | for pipelines only | yes | yes, 26 November, once each, at the first try (R86). One tenant, Runtime 2.0 |
| The operations agent created from a definition, and its definition read | Create Operations Agent and the definition article, yes: a preview, for a person only | yes | Created: **no**. Read by the runner: yes, 26 November, for an agent made by hand: `a playbook, started`, the rules not counted because they are a map there (R88); and at 23:51 with its Phase 5b setup: the instructions, the action and `a playbook with 1 rule` found, the start missing |
| Data flow created with mode `Disabled` | yes | yes | **no** |
| The questions of plan | not applicable | yes, with scripted answers | The region of the edge and the capacity, in a terminal: yes, 25 November, where the capacity question showed the runner's error with the list of SKUs. The workspace and the VM size: **no** |
| A Fabric capacity made through the Microsoft.Fabric operations (create, read, name check, SKU list) | yes, read on 25 November | yes | The SKU list and the name check: yes, 25 November (the list misread at 17:17, read rightly at 17:50; it has one entry for each region). Create and read: **no** |
| An existing empty workspace taken into a deployment | the two list operations, yes | yes | **no** |
| The vCPU quota read with `az vm list-usage` | yes | yes | **no** |
| Several deployments in one folder: started, switched, the settings of the earlier issues moved, the scripts finding the current one | not applicable | yes | A second deployment started with `plan --new` beside the first, each with its own settings, and commands that name theirs: yes, 25 and 26 November. The move of earlier settings: **no** |
| Choices from options, a profile and discovery; the saved plan and what differs; the named apply | not applicable | yes | A plan from options with no question, the profile saved, the named apply: yes, 25 and 26 November. A repeat deployment from the profile alone, and the report of what differs: **no** |
| Calls pinned with `--subscription`; the directory read through Microsoft Graph | the option, on the commands of the CLI itself with version 2.93.0 here; the two Graph requests, yes | yes | yes, 25 and 26 November, `az iot ops` commands among them |
| Scripts under the runner with `AZ_SUBSCRIPTION_PIN` | the option, as above | yes, against a stand-in `az` | `infra/01` and `infra/06`: yes, 26 November |
| A notebook run journalled, adopted, resubmitted | Run On Demand Item Job and the job instances, yes; no key to match a run to a request is documented | yes | **no** |
| A script stopped at its limit with what it started | not applicable | yes, with real processes on Linux | yes, 26 November, on WSL: `infra/04` at its 90 minutes |
| Demo-ready: telemetry now, the app's own check given by a person | not applicable | yes | Telemetry measured at the end of each apply: yes, 26 November. The app's own check: **no** |
| The service principal for the twin's live route, made by the runner, and the app deployed a second time | the commands of the script and the two Graph reads, yes | yes | yes, 26 November, 22:09: the registration `windfarm-twin-eventhouse-reader-66i`, its principal, Viewer in the workspace at the script's second try, `Secrets applied (3/3 uploaded)` without a terminal, the registration read back through Microsoft Graph, the second deployment. Whether the Eventhouse answers the principal: **not seen**, it is the twin's own check |
| The clean-up's report of a shared and of an own capacity | not applicable | yes, 6 scenarios | **no** |

## Unproven on a tenant

In the order a run meets them:

1. **`--subscription` on every call.** The runner adds it to each call of the Azure CLI except the groups that refuse it (`ad`, `extension`, `config`, `version`, `login`, `logout`: tried with version 2.93.0). The commands the runner and its scripts use from the CLI itself take it. For the commands of the extensions, `az iot ops …` in `infra/04`, `06` and `08` and `az connectedk8s` on the VM, it could not be tried here. If one refuses the option, its script ends at that call with `unrecognized arguments`, before it changes anything; send me the line. **Seen on 25 and 26 November:** every call the runs reached took it, `az iot ops` commands among them.
2. **The directory through Microsoft Graph.** `GET /me` and `GET /servicePrincipals(appId='…')` with the token `az account get-access-token --resource-type ms-graph` gives for the deployment's subscription. The same reads worked through `az ad` on 25 November. If Graph refuses, the roles show as `NOT CHECKED` and the Custom Locations object ID blocks with the command to read it by hand. **Seen on 25 November:** both reads answered.
3. **A plan without a question**, from options and a profile; the saved plan file; an apply that names its deployment. **Seen on 25 and 26 November.** The saved plan file itself was not looked at.
4. **An interrupted notebook run.** That the run's ID from the `Location` header is the one `Get Item Job Instance` knows, that a run which finished meanwhile is still found by it, and what `List Item Job Instances` shows of a run that was requested and not yet started.
5. **A script stopped at its limit on WSL.** The runner ends the script's whole session; tried with real processes on Linux only. **Seen on 26 November:** `infra/04` was stopped at its 90 minutes, after a line about once a minute.
6. **The app in a folder of the deployment.** The scaffolder is started in `.deploy/<suffix>/app/` with the project name `windfarm-twin`; it has only ever run beside the script. A folder whose path begins with a dot has not been tried with the app's tools. **Seen on 26 November:** the scaffolder, the functions pack, the overlay and the check ran in `.deploy/66i/app/`, and `npx rayfin up` deployed from there.
7. **The twin's own check** as the source for `--app-check`: that the build the check names is the one in `app/overlay/packages/functions/src/build.ts`.
8. **The move of settings from the earlier issues.** A folder that ran an earlier issue has `config/demo.env` with a suffix. The next run moves it to `.deploy/<suffix>/demo.env` and goes on with the same deployment and the same checkpoint. This ran against a copy of that layout only. Likewise unproven: a second deployment beside a first, and the scripts started by hand finding the current one.
9. **The questions in a real terminal.** Seen on 25 November up to the region of a new capacity. The workspace and the VM size were answered by a script of answers only.
10. **The vCPU quota.** The shape of what `az vm list-usage` answers, and the names of the size families in it, which the runner derives from a size's name (`standardDSv7Family` for `Standard_D8s_v7`). A family it does not find is `NOT CHECKED`. **Seen on 25 November:** the row of the family was found (`100 free of 100`), while the region counted 8 vCPUs in use; which family those are counted under is not explained.
11. **A capacity made by the runner**, when you choose one: what the field `restrictions` in Azure's list of SKUs means (seen empty for every region on 25 November; the reference does not describe it, and the runner does not read it), the request through `az rest` with a JSON body, what Azure answers and how long it takes, the name under which Fabric lists the capacity (the runner looks for its Azure name), and what Azure says when the quota of capacity units does not cover it (the runner looks for the word quota).
12. **An existing workspace you chose**: nothing new is asked of Fabric for it, and nothing of it has run.
13. **A capacity Fabric does not list for you.** Whether Create Workspace accepts it, and what Fabric answers when it does not. The runner turns an answer with 401, 403 or the word capacity into a block; any other answer shows as a failure with Fabric's own words.
14. **How a trial capacity appears in the list of capacities.** The runner takes the SKU `FT` with a number, or `Trial`, for one; Microsoft's reference shows F SKUs only.
15. **`infra/01` under the runner**: without the provider registration, the group creation and the role assignments; and with `VM_SIZE_SKIP_CHECK=1`, where `az vm create` itself has to refuse the sizes you are not offered. The script moves on at the words `SkuNotAvailable`, `not available in location` and `NotAvailableForSubscription`; any other refusal ends it with Azure's message. **Seen on 26 November** with `VM_SIZE_SKIP_CHECK=1`: the first size was created; a refused size has still not been met.
16. **The roles of the VM's identity**, read with the filter `principalId eq '…'` and assigned by role ID. (The same operation with the filter for a person answered on 25 November.) **Seen on 26 November:** assigned, and read some seconds too early by the seventh issue (R68).
17. **Arc onboarding with Reader on the resource group** instead of the subscription. **Seen on 26 November: it passes.**
18. **The Eventhouse's own database.** The runner waits two minutes for the database Fabric gives a new Eventhouse, then creates one. Whether the API-created Eventhouse brings one is not written where I read. **Seen on 26 November:** the step ended with `Eventhouse and KQL database WindFarmEH`; which of the two ways gave the database was not printed.
19. **The Kusto audience for the Azure CLI's token** on a Fabric Eventhouse. **Seen on 26 November:** the two database scripts and the policy commands ran with it.
20. **The eventstream definition**: a custom endpoint with empty properties, and the destination with the Eventhouse's item ID as Microsoft's article has it. That article does not say how the database is chosen; this demo's Eventhouse has one. Microsoft warns that a property set which does not fit is accepted and ingests nothing; the gate after it is there for that, and the fallback is the wizard. **Seen on 26 November:** the custom endpoint and the stream are `Running`; the destination failed with the Eventhouse's ID in it, `… is not a database artifact`. **Seen at 14:03:** with the KQL database's ID, written with Update Eventstream Definition into the existing eventstream, the destination is `Running`.
21. **Whether ingestion created this way reads JSON without a format label**, which the wizard needed set by hand. **Seen on 26 November:** the definition names no format, and the gate measured 60 readings from 12 turbines in the Eventhouse, the newest 9 s old.
22. **Shortcuts to KQL tables through the API** before the first write of OneLake availability. **Seen on 26 November:** six shortcuts made, after OneLake availability was switched on.
23. **Notebook import**: the part named `notebook-content.ipynb` (the REST reference; an older article says `artifact.content.ipynb`), and the default Lakehouse taking effect for a job. **Seen on 26 November:** five notebooks imported, and the jobs wrote their tables into the Lakehouse.
24. **Notebooks 01, 02, 03, 05 as jobs**: they have only run interactively. Parameters reaching the gate notebook's cell. **Seen on 26 November:** notebooks 01, 02 and 03 and the gate notebook ran as jobs to their end; notebook 02 took about eleven minutes. Notebook 05 has not.
25. **The schedule payload** with unzoned times and `UTC`, which is how Microsoft's samples write it while its text asks for a `Z`. **Seen on 26 November:** accepted; `03_refresh_forecast has one schedule (Daily)`. Its first scheduled run has not been looked at.
26. **The result file of the gate** over the OneLake API. The verdict does not depend on it. **Seen on 26 November:** read.
27. **The SQL probe** with a token for `https://database.windows.net`. **Seen on 26 November:** not asked. The probe found no driver, because it looked in `app/windfarm-twin` and the deployment's app is in `.deploy/<suffix>/app/windfarm-twin` (R93). Corrected; the question itself is still unproven from a workstation.
28. **`npx rayfin up` started without a terminal**, and how it says that it is not signed in. The runner recognises the words sign in, log in, keychain and 401; anything else is reported as a failure with the tool's own lines. **Seen on 26 November:** it ran without a terminal, signed in from an earlier day, and every component reported `success`. How it says that it is not signed in has still not been seen.
29. **The times.** No step has been timed under the runner, so this document promises none. Every check that takes five seconds or more prints its seconds. Measured so far, on 25 November from a workstation under WSL: the eight provider questions took 11 s together, and the questions about roles and VM sizes ran into their limits of 180 s and 120 s without an answer. Why answers of several megabytes do not arrive on that workstation is not known. `apply` sends about 3.5 MB from it to the VM (the repository, over SSH) and notebooks of about 120 KB each to Fabric, and Phase 4 installs the app's packages from npm there: how those fare is not known either.
30. **The service principal under the runner.** The script ran by hand on 23 November. New under the runner: the read of app registrations through Microsoft Graph with the Azure CLI's token (`GET /applications` with a filter on the name); the script's check that the CLI's active subscription is in the deployment's tenant, which is all that can be done about `az ad`; `npx rayfin secret set` started without a terminal; the second `npx rayfin up`, 150 seconds or more after the first; and how soon Microsoft Entra ID lists a secret that was just made (the runner waits up to two minutes). Not known from the run by hand either: whether Viewer in the workspace is enough for the Eventhouse to answer the principal, or whether the database needs it named as a viewer; the script prints that command, and the twin's own check is what tells. **Seen on 26 November, 22:09:** all of it ran: the Graph read, the script with its tenant check, the secrets set without a terminal, the second deployment. Fabric did not know the new principal at the first try and did at the second, fifteen seconds later. Still open: whether the workspace role is enough for the Eventhouse.
31. **The operations agent through the API** (`--allow-preview operations-agent`): the four points at the end of [The operations agent](#the-operations-agent). Nothing of it has run on a tenant. **Seen on 26 November:** the look only, for an agent made by hand.
32. **Phase 4 under the runner**, all of it: `app/create-app.sh` in the deployment's own folder, the two deployments of the app, the gate, `--app-check`. **Seen on 26 November:** the scaffold and the first deployment. The workspace lists the deployed app as two items named `WindFarmTwin`; their types have not been seen, and the done line of `p4.deploy` prints them. Not yet: the service principal, the second deployment, the gate, `--app-check`. **Seen at 22:09:** the two types are AppBackend and UserDataFunction; the service principal and the second deployment ran. Not yet: the gate, `--app-check`.
33. **Phase 5 under the runner**: `infra/08` creating the data flow with the mode `Disabled`; the two database scripts of Phases 5b and 5c over the Kusto REST interface; notebooks 12 and 13 imported with the Lakehouse in their metadata; the look at an agent with an action in its definition; and whether the twin's service principal, a viewer of the workspace, may run `CommandLog` in this deployment. **Seen on 26 November:** all of it but the last. The eventstream created from its definition, its topology read too early (R94) and whole at the second start; the data flow `Disabled`, `Succeeded`; both database scripts; both notebooks imported; and the look at an agent changed by hand, which found the instructions equal, the action on notebook 12 and one rule, and named the missing start. Open: whether the twin's service principal may run `CommandLog`, and everything that sends a command.

## Tests

`simulator/tests/test_deploy_runner.py`, 143 tests against `simulator/tests/deploy_fakes.py`, a pretend Azure and Fabric that answer in the documented shapes and record every change:

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
| A line that drops single connections (twelfth issue) | a read through the Azure CLI asked up to three times within its time, a change once; a connection to Fabric, OneLake or the Eventhouse made again, and a request that went out not sent twice; a complete step that could not be looked at still counted, the note gone once it is seen; a step that is not complete blocked as before; no connection not called a sign-in problem, and a refusal not called a connection problem |
| The twin's live route (fifteenth issue) | the service principal waits for the approval of role changes, is named for the deployment, and is made once; the app is deployed again after its secrets, not sooner than two minutes after the first time; a second apply makes no secret and no deployment; a secret replaced since, a secret that has ended and a principal without its role are seen; a directory that lists the new secret late is waited for; no file with the secret stays behind; a tenant that registers no applications blocks with the way to go on without; `--lakehouse-only` makes nothing in the directory and is part of what was approved; a twin that passes on its fallback route only is not demo-ready |
| Fewer steps for a person (seventeenth issue) | notebooks 06 to 08 run by the runner without an option, and their runs counted as the proof; notebook 09 a person's until its preview is allowed; `--no-pip-jobs` in the apply line; the operations agent created once, in the documented form, stopped and without a playbook; no playbook, a playbook and not started, and started, each seen in the definition; a playbook of an unknown form not counted; a definition that cannot be read never called done; a refused definition handed back with Fabric's line and the steps by hand; an agent made by hand found and not made again; without the preview, the step of the earlier issues |
| After the first steps of Phase 4 on a tenant (eighteenth issue) | a script for the app that stops half way leaves no built app: the next apply runs it again and deploys nothing before; a mark from another build of the overlay does not count; a deployed app found as two items of its name and as one, and a report of that name not taken for it; a playbook's rules counted in a list and in a map |
| The probe of the Lakehouse route (nineteenth issue) | the probe itself, run by Node.js with a stand-in for the driver: it finds the driver in the folder it is given, and says where it looked when there is none; the runner hands it the deployment's app folder; a probe that cannot ask is not called an endpoint that is behind |
| Phases 5b and 5c (twentieth issue) | absent without their option, and the option part of what was approved and of the apply line; the two database scripts sent, notebooks 12 and 13 imported and never run, the path switched off; the agent never changed by the runner, and its Phase 5b setup looked for in its definition: the Phase 3 setup, no playbook, not started, an action on another notebook, an unreadable definition, each seen; the look of Phase 3 not blocking while the agent is being changed; a finished Phase 5 applied again changes nothing; a path that is switched off is not demo-ready |
| After the first applies with Phase 5 (twenty-first issue) | the Lakehouse and SQL endpoint an ontology brings with it are the demo's, and a Lakehouse named a little like them is not; in the scenarios of the scripts: a new eventstream whose endpoints are not in its topology at once is asked about again, one whose endpoints never come stops after the wait, and one that existed before is read once |
| After the deployment stood complete with Phase 5 (twenty-second issue) | the report's sentence about the operations agent at each state of the agent: no playbook and not started, a playbook and not started, a playbook and started, a definition that cannot be read; never "a started agent" for one that is stopped; one notebook counted as one |
| And | approval of exactly one plan; a changed file and drift void it; role changes wait and stay on the resource group; Phase 5a absent by default, switched off when present, notebooks 12 and 13 impossible to run; the history once and once per label; the schedule in the future; preflight; the KQL splitter; the gate notebook's logic; the real adapters |

Three hundred and thirty-one faults were planted, one at a time. Of the twenty-two of the first issue, twenty-one made a test fail at once; the twenty-second, a key written into the settings with its last character cut off, passed until the test also searched for the middle of each key. The twenty-eight of the third issue each made a test fail at once. Of the forty-three of the fourth issue, in the questions, the new capacity, the chosen workspace and the quota, thirty-nine made a test fail at once; four passed until a test was made to look at the right place: questions asked by `apply`, questions asked while an apply runs, Phase 3 reading a capacity that is still to be made, and the quota asked about a VM that exists. Of the forty-five of the fifth issue, thirty-seven in the runner and eight in the way the scripts find their settings (those against the scenarios of `tools/script-tests/run.sh`), forty-four made a test fail at once; one passed until a test looked for it: a checkpoint folder without settings counted as a deployment. The thirteen of the sixth issue, in the reading of the list of SKUs and the question about a region, each made a test fail at once. Of the forty-four of the seventh issue, thirty-seven in the runner (the pin, how a choice is settled, the saved plan, the journal of a notebook run, the script's limit, readiness) and seven in the scripts (the subscription named for them, the clean-up, the app's folder), forty-two made a test or a scenario fail at once; two passed until a test looked for them: an option for the region moving a deployment that has its resource group, and a deployment called demo-ready for a phase of which nothing is built. The five of the eighth issue, in the check of the scripts, each made a scenario fail at once. Of eleven planted for the ninth issue, ten made a test or a scenario fail at once: in `push` without SSH, the look at the line before the IoT Operations script, the wait for the roles, the first confirmation, the hint, and the profile. The eleventh changed nothing, because the condition it broke was one the engine already guarantees; the condition was removed. The five of the tenth issue, in the address of an operation, each made a test fail at once, and so did the five of the eleventh, in the eventstream's destination. Of the twenty-three of the twelfth issue, in the calls that are asked again and in what a failed look does to a complete step, twenty-one made a test or a scenario fail at once; two passed until a test looked for them: a refusal about a complete step taken for a question without an answer, and a refusal by Fabric called a problem of the connection. Of the ten of the thirteenth issue, in the look at the mirroring policies and in the question to the VM agent, nine made a test or a scenario fail at once; the tenth, three tries without an answer going on to a wrong message, after a scenario was sharpened. The seven of the fourteenth issue, in the renewal of a token and in which read is asked how often, each made a test or a scenario fail at once. Of the fifteen of the fifteenth issue, in the service principal's step, the second deployment and the script, twelve made a test or a scenario fail at once; three passed until a test looked for them: a directory that lags, a principal without its role, and a secret that has ended. Of the six of the sixteenth issue, in when a confirmation counts, five made a test fail at once and one after the test looked at one more line. The fourteen of the seventeenth issue, in which notebooks the runner runs, in what it sends for the operations agent and in what it takes for a started agent, each made a test fail at once. Of the thirteen of the eighteenth issue, six in the runner's looks at the app and the agent and seven in `app/create-app.sh`, twelve made a test or a scenario fail at once and one after a test looked for it: a report with the app's name taken for the app. Three of them were at first counted as caught by a test that failed for a reason of its own, a wrong word of mine in its last line; with the test corrected, each was planted again and caught. The five of the nineteenth issue, in the probe of the Lakehouse route and its gate, each made a test fail at once. So did the twelve of the twentieth issue, in the option for Phase 5, the look at the agent's Phase 5b setup, and what the runner may send or start. Of the five of the twenty-first issue, two in the check for foreign items and three in the script for the command path, four made a test or a scenario fail at once; the fifth, a wait for the topology that goes on after the endpoints are there, after a scenario also counted the questions. The six of the twenty-second issue, five in the report's sentence about the operations agent and one in the count of notebooks, each made a test fail at once.

```bash
cd simulator && python3 -m pytest -q tests/test_deploy_runner.py
```

## Sources

Microsoft Learn, read on 25 November 2026.

- [Create an Eventstream with an Eventhouse DirectIngestion destination by using APIs](https://learn.microsoft.com/en-us/fabric/real-time-intelligence/event-streams/api-kusto-pull-destination): the destination's properties; the item ID is the Eventhouse's; the connection name has at most 40 characters.
- [Items - Update Eventstream Definition](https://learn.microsoft.com/en-us/rest/api/fabric/eventstream/items/update-eventstream-definition), read on 26 November 2026: replaces the whole definition; users, service principals and managed identities; not marked preview. The article above was read again the same day: it takes the Eventhouse's ID for the destination's `itemId`, which Fabric refused on that day; the runner uses the KQL database's.
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
- [Operations Agent - Create Operations Agent](https://learn.microsoft.com/en-us/rest/api/fabric/operationsagent/items/create-operations-agent) and [Get Operations Agent Definition](https://learn.microsoft.com/en-us/rest/api/fabric/operationsagent/items/get-operations-agent-definition), read on 26 November 2026: preview; a signed-in person only; an optional definition. [Operations agent definition](https://learn.microsoft.com/en-us/rest/api/fabric/articles/item-management/definitions/operations-agent-definition): the part `Configurations.json`; `configuration`, `playbook` (reserved; an empty object when not authored) and `shouldRun`.
- [Get servicePrincipal](https://learn.microsoft.com/en-us/graph/api/serviceprincipal-get): `GET /servicePrincipals(appId='{appId}')`, with `$select`.
- Azure CLI 2.93.0, installed here and run without a sign-in: which commands take `--subscription` (`az version`, `az account …`, `az rest`, the resource commands) and which end with "unrecognized arguments" (`az extension list`, `az config get`); `az account get-access-token --resource-type ms-graph`.
- [Create a data flow in Azure IoT Operations](https://learn.microsoft.com/en-us/azure/iot-operations/connect-to-cloud/howto-create-dataflow) and the [Dataflow REST reference](https://learn.microsoft.com/en-us/rest/api/iotoperations/dataflow/create-or-update): `mode`, `Enabled` or `Disabled`.
