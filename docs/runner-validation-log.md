# Deployment runner: validation log

The record of `tools/deploy.py`, written while it was built on 25 November 2026. As in the other logs: **seen** means output or a screen was sent to me, **reported** means the user said so, **not run** means nobody has run it. For the runner, everything on a tenant is **not run**.

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

## Checked

| Check | Result |
|---|---|
| `pytest simulator/tests/test_deploy_runner.py` | 48 tests against `deploy_fakes.py` |
| 22 faults planted in the runner, one at a time | 21 failed a test at once; one after the test was strengthened (R10) |
| `bash tools/script-tests/run.sh` | 142 scenarios: 4 new, for the app's workspace name and for the command path created switched off |
| `python3 tools/build-deploy-gate.py --check`, `python3 tools/build-runner-docs.py --check` | The gate notebook and the table of steps are what their generators write |
| The whole gate of the repository | Passes; see the README |
| `python3 tools/deploy.py plan` on a computer without the Azure CLI | Says so and ends with exit code 1; writes nothing |

## Not run

Everything on a tenant. The fourteen points of [15-deployment-runner.md](15-deployment-runner.md), "Unproven on a tenant", in the order a first run meets them.

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
| `simulator/tests/test_deploy_runner.py`, `simulator/tests/deploy_fakes.py` | The 48 tests and the pretend Azure and Fabric they run against |
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
