# Deployment runner: validation log

The record of `tools/deploy.py`, written while it was built on 25 November 2026. As in the other logs: **seen** means output or a screen was sent to me, **reported** means the user said so, **not run** means nobody has run it. Of the runner, `preflight` was seen on a tenant twice on 25 November; everything else of it on a tenant is **not run**.

## What was asked

On 25 November at 01:55 the user asked for the repository to be consolidated and set aside, and for a second version with "one entry point that automates the supported steps and tells the operator exactly what to do when a manual step is required", with a written list of rules: read-only by default, apply only with the approval of a plan and its target, a resource group and a workspace of its own, no tenant settings, no capacity changes, no broad access, no deletion, checkpoints without secrets, bounded waits, no duplicates on resume, gates on observable results, preview behind opt-in, undocumented operations left manual, Phase 5a off by default and never a command, nothing deployed while building. And names of the form `rg-windfarm-edge-3x9`, generated.

## Decisions

| Decision | Why |
|---|---|
| The runner signs in as the operator, through the Azure CLI | Several operations accept a person only (the Custom Locations lookup, the agents, notebooks that use semantic link). The edge keeps its managed identities, as in the guides |
| The suffix goes on names that must be unique outside the workspace; items inside keep their names | The notebooks and the app find `WindFarmEH` and `WindFarmLH` by name, and nothing can take a name inside a workspace the runner made |
| An approval covers the target, the options, every step and the files it uses, and any drift; not which steps are done | So one approval resumes an interrupted apply, and anything that changes what would happen voids it |
| A gate that has passed keeps its result | A stopped VM at night is not a reason to refuse Phase 2. `status` shows the freshness of now |
| Unknown things in the group or the workspace stop the runner; `--acknowledge` names one that belongs | "Stop on unrelated resources" without a way forward would end a deployment on the first policy-made resource |
| Notebook 04 is imported and not run | It changes nothing, and a job's output is read by nobody |
| The capacity is the operator's to name. The runner takes one by itself only when it is the single usable one in sight (third issue) | The rules say to stop on ambiguous matches and never to create or reassign a capacity. "The only one listed" turned out not to mean "the one to use" (R19) |
| Three answers that hold for a day are asked once in twelve hours, "could not be read" included (third issue) | A run looks at every step, an apply twice. On a line where a question stands for a minute, asking it each time is most of the run (R25). A block is never kept, so nothing that has to be fixed is hidden |
| What the runner could not read is shown as `NOT CHECKED`, never as `done` (third issue) | A step is not complete because a command returned, and a check is not made because it did not stop anything (R21) |

## Found while building

| # | What I assumed | What is true | Source | Changed |
|---|---|---|---|---|
| R1 | The eventstream's direct ingestion with an existing mapping has no documented API (my reading of 23 November, when the definition reference showed only an event hub and a Lakehouse) | Microsoft has an article for exactly this: the destination takes `tableName`, `connectionName` (at most 40 characters) and `mappingRuleName`. Its `itemId` is the Eventhouse's item ID, not the KQL database's, which I would have guessed | Learn, "Create an Eventstream with an Eventhouse DirectIngestion destination by using APIs", 25 November | The runner creates the eventstream with that destination, and a gate follows it. The wizard is the fallback, printed with the block |
| R2 | A gate notebook hands its figures back as the job's exit value | A job instance has a state and a failure reason. No exit value | Learn, "Get Item Job Instance" | The notebook fails when a table is empty or stale, which is the verdict; the figures go to a file the runner reads if it can |
| R3 | Tables can be checked with the Lakehouse's List Tables | Marked preview | Learn, "List Tables" | Not used. The gate notebook reads the tables through Spark, which also proves that the shortcuts can be read |
| R4 | Notebooks 06 to 10 run as jobs like the others | Their first cell is `%pip install`. Microsoft says that is off in pipeline runs and how to turn it on there; for a run started through the API it says nothing | Learn, "Manage Apache Spark libraries in Microsoft Fabric" | The operator's by default. `--opt-in pip-jobs` passes the documented parameter and falls back to the person |
| R5 | A schedule can start "now or earlier" | "If the start time is in the past, it will trigger a job instantly": a second run beside the one the step makes | Learn, "Create Item Schedule" | Schedules start ten minutes ahead. A test |
| R6 | The runner reuses step 1 as it is | Step 1 registers resource providers (the whole subscription), and gives the VM's identity Reader on the subscription. Neither is the runner's to do | Reading the script as something the runner starts | `DEPLOY_RUNNER=1` leaves out registration, group creation and roles. Roles are a step of their own, on the resource group. **Unproven** that Arc onboarding passes with that |
| R7 | The app is deployed as it is | Its functions look for a workspace named `WindFarmDigitalTwin`, a constant; the runner's workspace has a suffix | Searching for the name before generating one | `app/create-app.sh` writes the name into the app's copy of `config.ts`; the overlay and its build stamp are unchanged. Two scenarios |
| R8 | The KQL splitter sends "blocks that begin with a command" | The repository's own reset file is such a block, of `.clear table` commands. The runner never names that file, and the splitter would have passed it | A test written to prove the opposite | A block with a command that removes, renames or replaces is never sent, and only five named files are read at all |
| R9 | A comment above a command travels with it | A management command begins with its dot. In the query window the cursor is placed in the block; over REST the text is the request | The stand-in for the Eventhouse, which looked at the first characters | Comments above a command are dropped; those inside a database script stay, as they ran |
| R10 | The secrecy test proves that no key is written | It searched for whole keys. A fault that wrote a key without its last character passed | Planting 22 faults | The test searches for the middle of each key too |
| R11 | The suite is stable | `test_every_cell_of_the_notebook…` of Phase 5c failed in both full runs of the suite that had the runner's tests in it, and passed alone and without them. Its simulator is set to the present, then stepped 300 times, which on a busy machine takes more than a second; the edge then seems to take a command before it was written, and the notebook rightly prints no number | The full suite with 38 tests more in it | The fixture's clock is five seconds ahead. The consolidated version that was set aside has the test as it was |
| R12 | The item ID in a notebook's run request and the job type's place | Microsoft documents two forms: the job type in the path (REST reference) and `?jobType=RunNotebook` (its notebook article). The second ran here on 24 November | The two pages, read the same day | The runner uses the form that ran |

## First run on a tenant

| When | Step | Result |
|---|---|---|
| 25 November 2026, 09:47 Houston | `python3 tools/deploy.py preflight --up-to phase4`, from `~/fabric-windfarm-digital-twin-auto` on WSL, first issue | **Seen**, a picture of the terminal: `Wrote config/demo.env with names ending in -064, for subscription ME-MngEnvMCAP866841-ahmedsami-1. Nothing was changed in Azure or Fabric. …`, then an empty line and the cursor. The user asked: "is this step expected to take long time?" So the archive unpacked, Python ran the package, the Azure CLI answered `az account show`, and the settings file was written from the example |
| 09:53 | The same run | **Seen**, pasted: `FAILED   az vm list-skus --location did not answer within 300 seconds.` Nothing else was printed. So the checks before it (tools, sign-in, roles, eight providers) answered within about a minute together, and the size check ran into its limit: R18. The checks after it were never made |

Found through that run:

| # | What I assumed | What is true | Source | Changed |
|---|---|---|---|---|
| R13 | Preflight looks, then prints its table | Looking is about fifteen calls to the Azure CLI, one after the other, with nothing printed until the last has answered. One of them, `az vm list-skus`, is known to take a minute or more. A person sees one line and an empty screen and cannot tell waiting from stuck. This is the user's experience of the night before (a script that stood at ` - Searching ..`), which I had written down as a lesson and did not apply to my own tool | The user's picture and question, a minute or two into the wait | One line for each check as it starts, and the seconds of any that took five or more. A test |
| R14 | The runner's calls to the Azure CLI cannot wait for a person | The CLI was started with the terminal as its keyboard and its output captured. When a command belongs to an extension that is not installed, the CLI asks whether to install it: the question would have gone into the captured output, and the CLI would have waited for an answer until the time limit, five minutes of silence. The next command, `plan`, asked `az connectedk8s show`, an extension the guides use on the VM and never on the workstation | Reading my own adapter after R13, for anything else that could stand still | The CLI is started without a keyboard. The cluster is read as a plain resource (`az resource show`), so no extension is needed for it. The one extension the runner does need, `azure-iot-ops`, is a preflight check with the command to install it. The stand-in for the CLI fails any test in which `az connectedk8s` is asked |
| R15 | A call that fails while looking ends the run with its message | It ended the whole preflight: one slow `az vm list-skus` would have cost every other line | The same reading | A check that cannot be made is that check's `BLOCKED` line, with the reason; the others are still made. A test |
| R16 | Eight `az provider show` calls could be one `az provider list` | One call, and a download of every provider with all its resource types. The eight small calls answered on the user's connection within a minute; the big one has not been tried there, and big downloads are what stand still on it (R18, and the extension index of the night before) | Having made the change, then reading R18 | Kept as eight calls, each asking for the one value. The tools check no longer starts the CLI at all |
| R18 | `az vm list-skus --location` asks Azure for the sizes of one region | It asks for the sizes of every region and filters on this computer. In Cloud Shell, where step 1 ran on 19 and 20 November, that is quick. From the user's workstation it had not answered after 300 seconds, and the first issue then ended the whole preflight (R15). Step 1's script asks the same, once for each size, with no limit: `apply` would have stood there next | The user's output, 25 November, 09:53 | One call to the Resource SKUs API with `$filter=location eq '…'`, the filter Microsoft documents, with a limit of two minutes. When it is not answered the check says so and passes, because step 1 tries the sizes in turn. The runner hands the script the sizes that passed (`VM_SIZE_OFFERED`), and the script then skips its own question; without it the script says that each answer can take minutes. Not asked again once the VM exists. Three tests, one scenario |
| R17 | "It takes a minute or three", in the runner's own output, in my first fix | A number nobody measured, in a tool whose rules say to promise no time without a measurement | Reading the fix before sending it | The line says "can take a few minutes", and the seconds each slow check took are printed, so the next run measures it |

## Second run on a tenant

| When | Step | Result |
|---|---|---|
| 25 November 2026, 10:09 Houston | `python3 tools/deploy.py preflight --up-to phase4`, second issue, the same folder with its `config/demo.env` (suffix 064) | **Seen**, pasted in full. All 15 checks were looked at and the table was printed. Seconds printed for three: `pre.rights` 180, `pre.providers` 11, `pre.region` 120. Target: tenant `3597dfed-…`, subscription `ME-MngEnvMCAP866841-ahmedsami-1`, resource group `rg-windfarm-edge-064 in southcentralus (not created yet)`, workspace `WindFarmDigitalTwin-064 (not created yet)`, capacity `0aa47150-3238-402f-9acb-88aa240d0bb7`, signed in as the tenant's admin account |
| | What passed and was right | Tools; sign-in; the extension `azure-iot-ops`; 8 resource providers registered; suffix 064 with `sawindfarm064` free; the Custom Locations object ID read from Microsoft Entra ID and written to the settings; the Fabric API answering; Node.js v22.23.5. Three tenant-settings steps shown as the operator's |
| | What was printed and was wrong | `pre.rights  done … could not read your roles (az role assignment list did not answer within 180 seconds.)`. `pre.region  done … could not be read (az rest --method get did not answer within 120 seconds.)`. `pre.capacity  done  capacity Premium Per User - Reserved (PP3, Central US), the only active one you see`, and that ID written into `config/demo.env`. `p3.capacity  done  capacity SKU PP3`. `Plan a45d1f787e4f` at the end of a preflight. Findings R19 to R25 |
| 10:10 | My answer | Not to run `plan` or `apply` with that settings file: the workspace would have been created on, or refused by, a capacity that cannot hold an Eventhouse |

Found through that run:

| # | What I assumed | What is true | Source | Changed |
|---|---|---|---|---|
| R19 | "The only active capacity you see" is the capacity to use | Fabric lists the capacities a person administers or contributes to. On this tenant that is one, `Premium Per User - Reserved`, SKU `PP3`. Premium Per User "doesn't provision a Fabric capacity" and cannot hold a Lakehouse or a notebook; A and EM SKUs hold Power BI items only. The workspace of the deployment by hand, with its Eventhouse and its agents, evidently runs on a capacity that is not in that list. The runner took the one it saw, called the check `done`, and wrote the ID into the settings: the first write to a file of the user's that was wrong | The user's output; Learn, "Microsoft Fabric concepts and licenses" and "Capacities - List Capacities", 25 November | The SKU decides. A Premium Per User, A or EM capacity is never chosen and, when named, blocks. One usable capacity is taken only when no workspace of the person runs on a capacity outside the list. The block prints both lists: each capacity with what it can hold, and each unlisted one with the workspaces on it. The target shows name and SKU. Six tests |
| R20 | A capacity that is not a trial is a paid one | The Phase 3 check tested for the trial SKU and passed everything else, a Premium Per User capacity included | The same line of output | The check knows the same kinds. A capacity Fabric does not list is `NOT CHECKED` there too, with what the agents need |
| R21 | A check that passes without having been made may be shown as `done`, with the reason in its text | `pre.rights  done … could not read your roles`. The word is what a person reads; the text beside it said the opposite. The specification asks that a step is not marked complete merely because a command returned; a check is not done merely because it did not stop anything | The user's output | Two words more: `NOT CHECKED` for what the runner could not read, `confirmed by you` for what passes on a `--confirm`. In the plan, in the lines of apply, and counted separately. A test |
| R22 | Preflight is a plan for fewer steps, so it ends like one | It printed `Plan a45d1f787e4f`. No apply takes that: the identifier of a plan covers its steps, and an apply has others. An identifier that cannot be approved invites the attempt | The user's output | Preflight prints the table without an identifier, and the command that makes a plan |
| R23 | `az role assignment list` is one question about one person | It lists the assignments and then fetches every role definition of the subscription to print role names, and asks Microsoft Graph for the names of the principals. Its reference says of the first: "This operation is expensive." It did not answer in 180 seconds. The step `p1.vm_identity_roles` asked the same command twice each time it was looked at: an apply would have stood there for six minutes and then stopped | The user's output; Learn, `az role assignment`, 25 November | Roles are read with the operation Role Assignments - List For Scope through `az rest`, with a documented filter (`atScope() and assignedTo('…')` for the person, which follows groups; `principalId eq '…'` for the VM's identity), and compared by the role IDs of Azure's built-in roles. Roles are assigned by ID with the kind of principal, so the CLI looks nothing up. The stand-in fails any test in which `az role assignment list` is asked. Unproven on a tenant |
| R24 | The Resource SKUs call with its location filter is a small question | It is one region instead of all, and still every SKU of every resource type in it. It did not arrive within 120 seconds. And when it does not, the second issue left the script to ask `az vm list-skus` for each size, without a limit: the wait I had removed from preflight would have come back in apply | The user's output; reading `act_edge_vm` again | One minute for the question. When it is not answered, the script is started with `VM_SIZE_SKIP_CHECK=1`: it asks nothing, tries each size of `VM_SIZE` in its order, and moves on when Azure refuses one, which it already did. One scenario, two tests |
| R25 | Each run looks at everything, so each run asks everything | Two questions without an answer cost five minutes in preflight, the same in every plan, and twice that in every apply, which looks at the steps for its plan and again as it runs them. Nothing about the answers changes in that time | Adding up the seconds of the user's output | Three answers are kept in the checkpoint for twelve hours, "could not be read" included: roles, providers, VM sizes. Each with what it depends on; `--recheck` asks again; a check that found something missing is never kept. Three tests |
| R26 | A plan only reads | A plan may write to the checkpoint: a resource it recognises by its mark, and now the kept answers. It writes the copy it read at its start. While an apply runs, that copy is older than the apply's, and writing it would take the apply's progress back | Looking at where the kept answers are written | While a live process holds the lock, preflight, plan and status read the checkpoint and write nothing to it, and say so. A test |

What the output does not tell: which capacity the workspace `WindFarmDigitalTwin` runs on, and why answers of several megabytes do not arrive on this workstation while small ones take a second or two (the extension index on 24 November, `az vm list-skus`, the role definitions, the SKUs of one region). The next preflight prints the first. For the second, one timed download from the same shell would separate a slow line from a blocked one.

## Checked

| Check | Result |
|---|---|
| `pytest simulator/tests/test_deploy_runner.py` | 73 tests against `deploy_fakes.py` (48 at the first issue, 53 at the second) |
| 22 faults planted in the runner for the first issue, one at a time | 21 failed a test at once; one after the test was strengthened (R10) |
| 28 faults planted for the third issue: in the capacity check, the words, the kept answers, the roles, the lock | Each failed a test at once |
| `bash tools/script-tests/run.sh` | 144 scenarios: 6 new, for the app's workspace name, the command path created switched off, step 1 handed sizes that were checked, and step 1 told to ask nothing |
| `python3 tools/build-deploy-gate.py --check`, `python3 tools/build-runner-docs.py --check` | The gate notebook and the table of steps are what their generators write |
| The whole gate of the repository | Passes; see the README |
| `python3 tools/deploy.py plan` on a computer without the Azure CLI | Says so and ends with exit code 1; writes nothing |

## Not run

`plan`, `apply` and `status` on a tenant, and `preflight` with this issue. The eighteen points of [15-deployment-runner.md](15-deployment-runner.md), "Unproven on a tenant", in the order a first run meets them.

## Files

Against the consolidated version of 25 November 2026 (`fabric-windfarm-digital-twin-v1.zip`, 254 files): 16 new files and 15 changed ones. This version has 270.

| New | What it is |
|---|---|
| `tools/deploy.py` | The entry point |
| `tools/deployer/core.py` | The engine: steps and probes, the plan and its identifier, apply, the checkpoint, the lock, the redactor |
| `tools/deployer/cloud.py` | The adapters: Azure CLI, Fabric API (the client of Phase 5b), Eventhouse, OneLake, shell; long operations and notebook runs that survive an interruption |
| `tools/deployer/names.py` | The suffix, the generated names, reading and writing the settings file |
| `tools/deployer/steps.py` | The prerequisites and Phase 1 |
| `tools/deployer/steps_later.py` | Phases 2 to 4, the opt-in Phase 5a, and the whole list in order |
| `tools/deployer/cli.py`, `tools/deployer/__init__.py` | The command line: preflight, plan, apply, status |
| `tools/build-deploy-gate.py`, `fabric/notebooks/90_deployment_gate.ipynb` | The gate notebook and what builds it |
| `tools/build-runner-docs.py` | Writes the table of steps into the runner's document from the runner's own list |
| `app/probe-lakehouse-route.mjs` | Asks the SQL endpoint what the twin's Lakehouse route asks it |
| `simulator/tests/test_deploy_runner.py`, `simulator/tests/deploy_fakes.py` | The 73 tests and the pretend Azure and Fabric they run against |
| `docs/15-deployment-runner.md`, `docs/runner-validation-log.md` | The runner's document and this log |

| Changed | What changed |
|---|---|
| `infra/01-create-edge-vm.sh` | With `DEPLOY_RUNNER=1`: no provider registration, no group creation, no role assignments. Without it, as before |
| `infra/08-create-command-path.sh`, `edge/dataflows/fabric-to-windfarm-control.template.json` | `COMMAND_DATAFLOW_MODE`, `Enabled` by default, `Disabled` for the runner |
| `app/create-app.sh` | Writes the workspace's name into the app's copy of `config.ts`, from `FABRIC_WORKSPACE_NAME` or `config/demo.env` |
| `app/create-principal.sh` | Takes the workspace's name from `FABRIC_WORKSPACE_NAME` |
| `infra/99-cleanup.sh` | Knows the gate notebook |
| `config/demo.env.example` | `DEPLOYMENT_SUFFIX` and `FABRIC_CAPACITY_ID`, empty for a deployment by hand |
| `.gitignore` | `.deploy/` |
| `tools/script-tests/run.sh` | Four scenarios: the app with a generated workspace name, and with a name it refuses; the command path switched off, and a mode that is neither |
| `simulator/tests/test_phase5_center.py` | A fixture whose clock no longer depends on how busy the machine is (R11) |
| `README.md`, `docs/00-architecture.md`, `docs/03-roadmap.md` | This version and the runner |
| `docs/01-deployment-guide-phase1.md`, `docs/09-deployment-guide-phase3.md` | The name of the archive and the folder |

### Second issue, 25 November 2026, after the first command on a tenant

Eleven files differ from the first issue. They can be copied over a folder in which `preflight` has run; `config/demo.env` and `.deploy/` stay as they are.

| File | What changed |
|---|---|
| `tools/deployer/cli.py` | A line for each check as it starts, and the seconds of the slow ones |
| `tools/deployer/core.py` | A check that cannot be made becomes that check's line; the time of each check is measured |
| `tools/deployer/cloud.py` | The Azure CLI is started without a keyboard, with three minutes for a question; a way to ask whether a tool is installed without starting it |
| `tools/deployer/steps.py` | `pre.extensions`; the VM sizes through the Resource SKUs API with its filter, handed to the script; the cluster read as a plain resource |
| `infra/01-create-edge-vm.sh` | `VM_SIZE_OFFERED`: sizes that were checked already are not asked about again. Without it, a line that says the question can take minutes |
| `tools/script-tests/run.sh` | One scenario for that (143) |
| `simulator/tests/test_deploy_runner.py`, `simulator/tests/deploy_fakes.py` | Five tests more (53) |
| `docs/15-deployment-runner.md`, `docs/runner-validation-log.md`, `README.md` | The first run, findings R13 to R18, the extension as a prerequisite |

### Third issue, 25 November 2026, after the second run on a tenant

Twelve files differ from the second issue. They can be copied over a folder in which `preflight` has run; `.deploy/` stays as it is. `config/demo.env` stays too, with one line to change by hand: `FABRIC_CAPACITY_ID`, where the second issue wrote the ID of the Premium Per User capacity.

| File | What changed |
|---|---|
| `tools/deployer/steps.py` | The capacity by its SKU, with both lists in the block; roles read with one small question and assigned by ID; one minute for the two questions a run can do without; the VM script told what was read, or to ask nothing |
| `tools/deployer/steps_later.py` | The Phase 3 capacity check knows the same kinds of capacity |
| `tools/deployer/core.py` | `NOT CHECKED` and `confirmed by you`; answers kept for twelve hours; a checkpoint that is only read while an apply runs |
| `tools/deployer/cli.py` | `--recheck`; the capacity by name and SKU in the target; no plan identifier after preflight; the notice when an apply is running |
| `infra/01-create-edge-vm.sh` | `VM_SIZE_SKIP_CHECK=1`: ask nothing, try each size, let Azure refuse |
| `tools/script-tests/run.sh` | One scenario for that (144) |
| `config/demo.env.example` | The comment of `FABRIC_CAPACITY_ID` says which kinds of capacity |
| `simulator/tests/test_deploy_runner.py`, `simulator/tests/deploy_fakes.py` | Twenty tests more (73); the stand-in answers the two role questions and fails on `az role assignment list` |
| `docs/15-deployment-runner.md`, `docs/runner-validation-log.md`, `README.md` | The second run, findings R19 to R26, the capacity, the two new words, `--recheck` |
