# Deployment runner: validation log

The record of `tools/deploy.py`, written while it was built on 25 November 2026. As in the other logs: **seen** means output or a screen was sent to me, **reported** means the user said so, **not run** means nobody has run it. Of the runner, `preflight` was seen on a tenant three times on 25 November; everything else of it on a tenant is **not run**.

## What was asked

On 25 November at 01:55 the user asked for the repository to be consolidated and set aside, and for a second version with "one entry point that automates the supported steps and tells the operator exactly what to do when a manual step is required", with a written list of rules: read-only by default, apply only with the approval of a plan and its target, a resource group and a workspace of its own, no tenant settings, no capacity changes, no broad access, no deletion, checkpoints without secrets, bounded waits, no duplicates on resume, gates on observable results, preview behind opt-in, undocumented operations left manual, Phase 5a off by default and never a command, nothing deployed while building. And names of the form `rg-windfarm-edge-3x9`, generated.

On 25 November at 15:51, after the plan had been reduced to one `sed` line and a command, the user wrote: "I would like a little more automation here. instead of running sed command to I'd rather : [ask: would you like to create a new fabric capacity or use one of the existing ones {yes, no}, if yes randomly pick a name and create F16 one in a proper region, if not enumerate all the existing capacities, and ask the user to pick one - next workspace - do the same - etc]". That changes two rules of the first list, by the person who wrote it: "never create or reassign capacity", and a workspace of the runner's own. The fourth issue follows the new instruction and keeps what is left of the old ones: see the decisions marked fourth issue.

On 25 November at 16:35, a few minutes after the fourth issue went out, the user wrote: "one more thing, I don't want a pre-populated .env file. I want you to generate the random 3 alphanum suffix in the runtime. I might be building this demo over and over in the same tenant or new tenants". The archive held no settings file, only the template, and the suffix was already drawn by the first plan. What his sentence is right about is what happened after that: the first plan left a filled-in `config/demo.env` in the folder, one file for one deployment, in the place where the guides have a person fill one in; and a second build needed a second copy of the folder. The fifth issue makes the deployment, not the folder, the unit: see the decisions marked fifth issue and R39 to R46.

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
| The runner asks, in preflight and plan, in a terminal; an answer is a line of the settings and of the plan, never a change in Azure or Fabric (fourth issue) | The user asked for questions in place of edits to the settings file. The rules "read-only by default" and "apply only with the approval of a plan and its target" stand: a question changes what the plan says, and the plan is still read and approved. Without a terminal nothing is asked, so a pipeline behaves as before |
| A capacity is made only on a yes to that question and with its own approval; it is never paused, resumed, resized or deleted by the runner (fourth issue) | The first list said "never create or reassign capacity". Its author now asks for creation as a choice. A capacity costs money while it runs, so making one gets the treatment the list gave role changes: its own approval, which the yes gives for the plan of the same run and `--approve-capacity-creation` gives otherwise. Everything else of the old rule stays |
| The new capacity lives in the demo's resource group, with the deployment's tag and the suffix in its name (fourth issue) | Ownership by resource ID and a mark, as for everything else the runner makes; and the clean-up that removes the group removes the capacity, so that nothing that costs money is left behind without a record |
| F16, as asked; another SKU by a setting, not by a question (fourth issue) | The user named the SKU. A question about it would be one more thing to answer for the one person who has run this |
| The region for a new capacity: the edge's own, unless Microsoft's region table lists something the demo uses as missing there; then the next one that lacks nothing. A dated copy of the table is in the code (fourth issue) | "A proper region" had to mean something that can be checked. The table changes; a copy with its date can be wrong, so it proposes and cautions, and blocks only when a phase that was asked for needs what the table lists as missing (R30) |
| An existing workspace is taken only when it is empty and on the chosen capacity, and is held by its ID (fourth issue) | The first list asked for a dedicated workspace, known by ID and recorded ownership, and for a stop on unrelated resources. An empty workspace that the person picked is dedicated from then on. One with items is not, whatever the items are called |
| The resource group is not asked about (fourth issue) | The runner's proof that a group is its own is the tag it sets when it creates the group. Taking an existing group means writing to a resource somebody else made. Not built until it is asked for |
| The settings of a deployment are kept beside its checkpoint, `.deploy/<suffix>/demo.env`. The runner reads and writes nothing in `config/` (fifth issue) | The user wants no settings file prepared, and builds the demo again and again. Settings and checkpoint are two halves of one record: which names, and what was made under them. Kept together and by suffix, a second deployment cannot overwrite the first, and `config/demo.env` goes back to meaning one thing, a deployment by hand |
| They stay a file in the shell's format (fifth issue) | Every script reads its settings by sourcing a file, and the runner starts those scripts. Settings kept only inside the checkpoint would have to be written out as such a file for each script anyway, and a person could no longer read them or hand them to a script |
| One folder holds many deployments. `.deploy/current` names the one that commands work on; `plan --new` starts one, `--deployment SUFFIX` goes back to one (fifth issue) | "Over and over in the same tenant or new tenants". A new copy of the folder for every build was the only way before, and `--new-names` was refused as soon as anything existed |
| A new deployment in the same subscription takes over four things: the region of the edge, the VM sizes and their order, the shutdown hour, the Custom Locations object ID. Never a name, the capacity or the workspace (fifth issue) | The four are what a person settles once for a subscription, and the last is a lookup that needs a directory right. A capacity may be gone or paused by the next build and a workspace is the deployment's own, so those two are asked again. In another subscription nothing is taken over: none of it need hold there |
| The runner offers a new deployment by itself only in a terminal, and only in two cases: signed in to another subscription, or the deployment's resource group is gone (fifth issue) | Both mean that going on with the current names leads nowhere, and both are what "the next build" looks like in practice: a new tenant, or a clean-up. Without a keyboard it starts nothing by itself, so a pipeline never changes its target because of what it found |
| A script started by hand takes the file `ENV_FILE` names, then `config/demo.env`, then the current deployment's settings (fifth issue) | A deployment by hand in the same folder keeps working exactly as its guides say, and beside a deployment of the runner the same commands work without an option. The clean-up shows what it would remove before it removes anything, by name |
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

## Third run on a tenant

| When | Step | Result |
|---|---|---|
| 25 November 2026, about four hours before 15:40 | `preflight` with the third issue | **Not seen.** Known only from the next run, which showed three answers as `[asked 4 h ago]` |
| 15:40 Houston | `python3 tools/deploy.py preflight --up-to phase4`, third issue, `config/demo.env` unchanged | **Seen**, pasted in full. Target with `capacity  Premium Per User - Reserved (PP3, Central US)  0aa47150-…`. `pre.rights  done  roles on the subscription: Owner, User Access Administrator [asked 4 h ago; --recheck asks again]`. `pre.providers  done … [asked 4 h ago …]`. `pre.region  NOT CHECKED … (az rest --method get did not answer within 60 seconds.) … [asked 4 h ago …]`. `pre.capacity  BLOCKED  FABRIC_CAPACITY_ID names Premium Per User - Reserved (PP3, Central US): a Premium Per User capacity …`, with two capacities listed: `d21d9da9-4054-4790-bc82-71aad3a91152  fabcentralussm01 (F32, Central US)  -> can hold the demo: a Fabric capacity`, and the Premium Per User one as `cannot hold the demo`. No list of capacities outside it. `p3.capacity  BLOCKED`. `9 done, 0 confirmed by you, 1 not checked, 0 for the runner, 3 for you, 0 waiting for an approval, 2 blocked, 0 optional.` No plan identifier; `Preflight is not a plan. …` |

What that run proved, of the points that were unproven:

- **The roles, read with the light question** (R23): `az ad signed-in-user show`, and Role Assignments - List For Scope through `az rest` with the filter `atScope() and assignedTo('…')` in `--url-parameters`. Answered, and the two role IDs were named rightly.
- **Kept answers** (R25) across runs on his computer: three answers shown from the checkpoint, none asked again.
- **The capacity by its SKU** (R19) on real data: `F32` and `PP3` read as what they are; the target shows name and SKU.
- **The words** (R21, R22): `NOT CHECKED` with its count, no plan identifier after preflight.

And what it did not: the question about VM sizes went unanswered a third time, now within 60 seconds. On this workstation that check is `NOT CHECKED` every time.

Found through that run:

| # | What I assumed | What is true | Source | Changed |
|---|---|---|---|---|
| R27 | The workspace of the deployment by hand "evidently runs on a capacity that is not in that list" (my words in R19), so the block would show a line `used by: WindFarmDigitalTwin`, and the capacity would pass as `NOT CHECKED` | Fabric lists an F32 for him, `fabcentralussm01` in Central US, and no workspace of his runs outside the list. At 10:09 the second issue had called the Premium Per User capacity "the only active one you see", and it looked at active capacities only: the F32 was most likely paused then, which nobody checked. I had made one explanation out of one line of output and told him what to look for on that basis; he found no such line and sent the output, as asked | The user's output of 15:40 | Nothing in the runner: the block printed the right list. The instruction to him was corrected: the ID of the F32 goes into `FABRIC_CAPACITY_ID`. A paused capacity is said to be paused and is not resumed (a test of the third issue) |
| R28 | A step without an action is the operator's | The gate on fresh telemetry has no action, because it is a measurement, and the plan showed it as `YOUR STEP` with the line `> See the plan line above.`, and counted it under "for you". Nothing for a person to do there | Replaying his situation against the stand-ins before sending him on to `plan` | A gate that the runner measures shows as `will be measured` and counts as the runner's. A test. **Not in the archive he has**: his first plan shows the old line |
| R29 | A capacity the agents cannot use means a workspace to move | For a capacity that cannot hold the demo at all, `p3.capacity` said to move the workspace to another capacity, before any workspace exists | The user's output | It points to the choice of `pre.capacity`. A test. Not in the archive he has |

Open after that run:

- **Quota.** The new VM stands beside the VM of the deployment by hand, in the same region and most likely of the same size family, and needs 8 vCPUs more. Preflight does not look at quota. He was given `az vm list-usage` to look for himself. To build: a check `pre.quota` (the regional total and the family of the first size of `VM_SIZE`), `NOT CHECKED` when the family cannot be told from the size's name.
- **The plan and the apply**, which have still not run on a tenant.

## Found while building the fourth issue

| # | What I assumed | What is true | Source | Changed |
|---|---|---|---|---|
| R30 | "A proper region" for a new capacity is the region of the edge | For South Central US, the region of this deployment's edge, Microsoft's table lists the operations agent as not available for a capacity. A capacity made there would have carried Phases 1, 2 and 4 and stopped Phase 3 at its last step. The user's own capacity is in Central US, where the table lists nothing as missing. A search result for the same page, without a date, listed more as missing in South Central US (Fabric App, Ontology); the page as fetched, dated 17 November 2026, does not, and the runner follows the dated page | Learn, "Fabric region availability", 25 November | The edge's region when the table lists nothing the demo uses as missing; else Central US for South Central US and East US 2 for East US. The reason is printed with the proposal. A region with a gap needs a yes, and blocks the plan once the phase that uses it is asked for |
| R31 | The quota of Fabric capacity units can be read before the capacity is asked for | The page on these quotas describes the portal; the operation behind its "API" tab was not in what I could read. Microsoft does say that a capacity needs enough quota and a registered provider | Learn, "Microsoft Fabric capacity quotas" and "Buy a Microsoft Fabric subscription" | Not checked beforehand, and said so. The capacity is the second thing an apply makes, straight after the resource group, so a refusal costs nothing; it becomes a block with the place to ask for more. The provider is a preflight check |
| R32 | The request for a capacity returns when the capacity exists | It returns when Azure has taken the request; the answer documents a state `Provisioning` and an operation to follow. The engine's rule for a step whose result is not there after its wait is FAILED, which would have been the word for a capacity that is merely not ready | The first run of the test with a capacity in `Provisioning` | The step waits within the limit of an operation, 15 minutes, and then ends the apply with "still running" and exit code 4. The next apply finds the capacity and waits for it; the stand-in fails any test in which a second request is sent |
| R33 | A plan's identifier covers the capacity by its ID | A capacity to be made has no ID until it exists. With the ID in the identifier, an apply that was interrupted after making the capacity would have been refused as "the plan has changed", for a change the plan itself made | Writing the test "the same approval still holds" before the code | A capacity to be made is part of the target by its name, SKU and region, before and after. Seen to hold in the test |
| R34 | The new capacity is the demo's, so the checks let it be | The resource group's check stops on any resource of a provider the demo does not use, and `Microsoft.Fabric` was not on its list: the runner would have stopped at its own capacity on the next apply | Reading the group's check for what the new step adds to it; a planted fault confirms that a test sees it | `Microsoft.Fabric` is one of the providers of the demo's group |
| R35 | Asking is harmless at any time | Two times are wrong: in `apply`, where the target has to be the one that was approved, and while an apply runs, where this run's copy of the checkpoint is older than the apply's (R26). The first tests of both passed with the fault planted, because nothing was left to ask in them | Planting the two faults | Questions only in preflight and plan and never beside a running apply. The tests now leave a question open on purpose |
| R36 | Putting another VM size first is a change of the question to Azure | The kept answer was filed under the list of sizes as written, so a new order would have sent the unanswered question again, and a minute of waiting with it | Building the question about the VM size | The sizes are part of the key as a set |
| R37 | A stopped VM gives its vCPUs back | "Quota is calculated based on the total number of cores in use both allocated and deallocated" (Microsoft). The VM of the deployment by hand counts against the new one whether it runs or not | Learn, "Virtual machine vCPU quotas", 25 November, read before telling the user what to do if the quota is short | A preflight check `pre.quota`: the region's total and the family of the size that is tried first, from `az vm list-usage`. The family's name is derived from the size's name; when the list has no such row the check says `NOT CHECKED` |
| R38 | Ctrl+C needs no thought | At a question it printed a Python traceback | Reading the entry point after adding the first thing a person waits at | One line, exit code 130, and what was true before: the next run looks before it does anything |

## Found while building the fifth issue

| # | What I assumed | What is true | Source | Changed |
|---|---|---|---|---|
| R39 | The runner already did what was asked: no settings file in the archive, the suffix drawn at the first plan | For the first build, yes. But the first plan wrote a filled-in `config/demo.env` into the folder, where it looks like the file the guides have a person prepare, and it was the only one the folder could hold | Listing the archive of the fourth issue, then reading the request again with a second build in mind | Deployments: settings under `.deploy/<suffix>/`, nothing of the runner in `config/`, `--new` and `--deployment` |
| R40 | `--new-names` covers a new start | It was refused once the deployment had made anything, which is exactly when a second build is wanted | The option's own text in the guide | Removed. `--new` starts a deployment at any time and leaves the earlier one as it is |
| R41 | Scripts started by hand need no change | They read `config/demo.env`. With the settings elsewhere, `bash infra/vm.sh ssh`, the clean-up, `app/create-app.sh` and `app/create-principal.sh` typed by hand would have stopped, or, in a folder that also has a deployment by hand, acted on that one without a word | Searching the scripts for `ENV_FILE` and for the file's name | One order in `config/load-env.sh`, `infra/99-cleanup.sh` and the two app scripts. Eight scenarios |
| R42 | `infra/vm.sh push` takes the settings to the VM with the rest | It sends the folder. With the settings in `.deploy/`, every deployment's settings and checkpoint would have gone to each VM, and `config/demo.env` on the VM, which the scripts there read, would have been missing | Reading `push` | `.deploy/` is not sent; the settings in use are written to `config/demo.env` on the VM. A scenario |
| R43 | An apply with the wrong plan identifier gets the usual refusal | After `plan --new`, the line to paste for the earlier deployment is still on the screen. "The plan is now …; something has changed" would have sent a person looking for a change that is not there | Playing two deployments through against the stand-ins | Each checkpoint keeps the identifier of its last plan; the refusal says whose plan it is and how to apply it |
| R44 | A copy of the template is a fine settings file | Its first lines say to copy it to `config/demo.env` and fill in the blanks, in a file that is to be neither copied nor filled in | Reading the first file the new code wrote | A deployment's file opens with what it is; so does a file moved from `config/` |
| R45 | Every folder under `.deploy/` is a deployment | A checkpoint whose settings are gone is not one: nothing says what its names were. A planted fault that counted it passed every test | The planted faults | The test for the move now has such a folder beside it |
| R46 | The refusal for another tenant gives usable advice | It said to "start a new deployment in a new copy of the settings" | Reading every message that names the settings | It gives the command, `plan --new` |

## Checked

| Check | Result |
|---|---|
| `pytest simulator/tests/test_deploy_runner.py` | 97 tests against `deploy_fakes.py` (48 at the first issue, 53 at the second, 73 at the third, 89 at the fourth) |
| 22 faults planted in the runner for the first issue, one at a time | 21 failed a test at once; one after the test was strengthened (R10) |
| 28 faults planted for the third issue: in the capacity check, the words, the kept answers, the roles, the lock | Each failed a test at once |
| 43 faults planted for the fourth issue: in the questions, the new capacity, the chosen workspace, the quota | 39 failed a test at once; 4 after the test was made to look at the right place (R35, and two assertions that matched other text) |
| 45 faults planted for the fifth issue: 37 in the runner (which deployment a command works on, what a new one takes over, the move of old settings, whose plan an identifier is, what the scripts are handed), 8 in the scripts' search for their settings | 44 failed a test or a scenario at once; one after a test was made to look for it (R45). The two faults of the fourth issue whose code moved from `cli.py` to `deployments.py` were planted again, and caught |
| The questions played through as text, for the tenant as it was at 15:40 | Read, and reworded twice |
| His folder as it is today (`config/demo.env` with the suffix 064 and a Premium Per User capacity in it, `.deploy/064/`), played through against the stand-ins, and a second build after it | The settings are moved once; the capacity is asked for again because the one in the settings cannot hold the demo; `--new` gives other names and leaves 064 as it was |
| `bash tools/script-tests/run.sh` | 152 scenarios. 6 new at the fourth issue (144), for the app's workspace name, the command path created switched off, step 1 handed sizes that were checked, and step 1 told to ask nothing. 8 new at the fifth: the settings found through `.deploy/current`, `config/demo.env` before that, `ENV_FILE` before both, a current deployment without settings, `push` with the settings elsewhere, the clean-up and the two app scripts beside a deployment of the runner |
| `python3 tools/build-deploy-gate.py --check`, `python3 tools/build-runner-docs.py --check` | The gate notebook and the table of steps are what their generators write |
| The whole gate of the repository | Passes; see the README |
| `python3 tools/deploy.py plan` on a computer without the Azure CLI | Says so and ends with exit code 1; writes nothing |

## Not run

`plan`, `apply` and `status` on a tenant, and everything of the fourth and fifth issue. The twenty-two points of [15-deployment-runner.md](15-deployment-runner.md), "Unproven on a tenant", in the order a first run meets them.

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

### Fourth issue, 25 November 2026: the questions

One new file and eleven changed ones against the third issue. They can be copied over a folder in which `preflight` has run; `config/demo.env` and `.deploy/` stay as they are. The settings file needs no edit by hand: the next plan asks.

| File | What changed |
|---|---|
| `tools/deployer/choices.py` (new) | The questions: region of the edge, capacity, workspace, VM size; who answers, and what an answer writes |
| `tools/deployer/cli.py` | Asks before it looks; `--no-input`, `--ask`, `--approve-capacity-creation`; the apply command written out under the plan; a capacity to be made and a chosen workspace in the target; Ctrl+C as one line |
| `tools/deployer/steps.py` | The step `p1.capacity` and the checks before it; the dated table of Fabric regions; a chosen workspace, empty and on the chosen capacity; `pre.quota`; the VM sizes kept as a set; the text of the telemetry gate (R28) |
| `tools/deployer/steps_later.py` | Phase 3 reads a capacity that is to be made, and cautions about its region; the instruction for a capacity that cannot hold the demo (R29) |
| `tools/deployer/core.py` | The record of choices in the checkpoint; the approval of a capacity; a chosen workspace as part of what a plan covers; a gate the runner measures shown as `will be measured` (R28) |
| `tools/build-runner-docs.py` | The table of steps says who makes a capacity, and when |
| `config/demo.env.example` | Four settings the questions write: `FABRIC_CAPACITY_CREATE_SKU`, `FABRIC_CAPACITY_NAME`, `FABRIC_CAPACITY_REGION`, `FABRIC_WORKSPACE_ID` |
| `simulator/tests/test_deploy_runner.py`, `simulator/tests/deploy_fakes.py` | Sixteen tests more (89); a person who answers; Microsoft.Fabric in the pretend Azure; the usage list |
| `docs/15-deployment-runner.md`, `docs/runner-validation-log.md`, `README.md` | The questions, the new capacity, the run of 15:40, findings R27 to R38 |

### Fifth issue, 25 November 2026: no settings file, one folder for every build

One new file and eighteen changed ones against the fourth issue; 272 files. They can be copied over a folder that holds an earlier issue. `config/demo.env` and `.deploy/` are not in the archive and stay as they are; the next run moves a `config/demo.env` that the runner wrote to `.deploy/<suffix>/demo.env`, once, and says so.

| File | What changed |
|---|---|
| `tools/deployer/deployments.py` (new) | The deployments of a folder: where the settings and the checkpoint of each are, which one is current, starting one with a new suffix, what it takes over, the move of settings from `config/`, whose plan an identifier is |
| `tools/deployer/cli.py` | `--new` and `--deployment`; `--new-names` is gone; the line that names the deployment and the others of the folder; `status` lists them; the apply line names its deployment once the folder holds several, and an apply with another deployment's plan says so (R43); the advice for another tenant (R46) |
| `tools/deployer/core.py` | The settings file by its place in the folder, for messages |
| `tools/deployer/steps.py`, `tools/deployer/steps_later.py`, `tools/deployer/choices.py` | Messages name the deployment's own settings file and `plan --new`; the hand-over text for the service principal |
| `tools/deployer/names.py` | Its description |
| `config/load-env.sh` | Finds the settings: `ENV_FILE`, then `config/demo.env`, then the current deployment's (R41) |
| `infra/99-cleanup.sh`, `app/create-app.sh`, `app/create-principal.sh` | The same order |
| `infra/vm.sh` | `push` sends nothing of `.deploy/` and writes the settings in use to `config/demo.env` on the VM (R42) |
| `config/demo.env.example` | Its first lines say who copies it and who does not |
| `tools/script-tests/run.sh` | Eight scenarios more (152) |
| `simulator/tests/test_deploy_runner.py`, `simulator/tests/deploy_fakes.py` | Eight tests more (97); the bench follows the current deployment; the pretend shell fails a script that is not handed the settings of its deployment |
| `docs/15-deployment-runner.md`, `docs/runner-validation-log.md`, `README.md` | The section Deployments, the request of 16:35, findings R39 to R46; in the README also the count of all tests, which still said 88 |
