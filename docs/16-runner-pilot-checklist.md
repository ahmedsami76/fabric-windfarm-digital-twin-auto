# Pilot checklist for the deployment runner

A checklist for one person to run the runner end to end on a tenant for the first time, and to write down what it shows. Nothing in it has been run for you: the runner's seventh issue was built and exercised offline only. Every command is typed in the repository folder, on the workstation, signed in as yourself.

It follows the order asked for on 25 November 2026: an existing approved capacity, a fresh resource group and workspace, Phase 5a off, Phase 1 applied, a notebook run interrupted and resumed, the plan applied again to look for duplicates, the same deployment extended through Phase 4, and the twin itself confirmed.

No time is promised for any step. Note the clock at each one: those are the first measurements.

## What stands on what evidence

| | Offline, against stand-ins | On a tenant so far | The pilot has to show |
|---|---|---|---|
| `preflight` | yes | yes: four runs on 25 November, second to third issue | the same with every call pinned to the subscription, and the two directory reads through Microsoft Graph |
| `plan` | yes | the sixth issue's plan ran to its end on 25 November (plan `f3cdc565c27f`, questions answered in a terminal) | a plan settled from options and a profile with no question; the saved plan file |
| `apply` | yes: 140 tests | 25 and 26 November, deployment 66i: **Phase 1 to its end, 25 of 25 steps, at 16:50 on 26 November**. Everything made by the runner but Azure IoT Operations, which its script made from Cloud Shell. The telemetry gate passed at 14:03 (60 readings from 12 turbines), the Lakehouse gate at 16:50 (21 tables with rows) | steps 3 to 10 below |
| Interrupted notebook run, resumed | yes | no: Phase 1 went past its notebooks without a stop | step 4, at the first notebook of step 7 |
| Second apply adds nothing | yes | no | step 5 |
| Scripts under the runner, pinned | yes, against a stand-in `az` | no. The scripts themselves ran by hand, 19 to 25 November | that `az iot ops` and `az connectedk8s` accept `--subscription` (they are extension commands and could not be tried here) |
| Phases 2 to 4 under the runner | yes | by hand: yes | step 7 |
| Demo-ready | its rules, yes | no | step 8: the deployed twin's own check |
| Clean-up report for both kinds of capacity | yes: 6 scenarios | the first version of the script ran once, on 20 November | step 10, preview only |

## Before you start

- [ ] The files of the seventh issue are in the folder. The offline checks pass on your workstation:

```bash
cd simulator && python3 -m pytest -q tests/test_deploy_runner.py && cd .. && bash tools/script-tests/run.sh
```

  It ends with `140 passed` and with `passed 187, failed 0`, and prints nothing but `PASS` lines in between. Seen on the workstation of the earlier tenant runs on 25 November at 23:09, with the seventh issue: `111 passed in 9.84s`, then `passed 164, failed 1` of the 165 scenarios it had. The one failure was the repository's own check of its scripts under GNU awk, not the runner; the eighth issue corrects it and adds two scenarios (R64 in the [validation log](runner-validation-log.md)).

- [ ] `az login` as yourself, and `az extension add --name azure-iot-ops --yes` if preflight ever said it is missing.
- [ ] The line from this computer to Azure carries a few megabytes in a few seconds. The first pilot, on 26 November, ran from a workstation under WSL that received 5 kB a second, and the Azure IoT Operations script could not finish there. This prints the rate, and shows nothing of the token:

```bash
az account get-access-token --query accessToken --output tsv | sed 's/^/Authorization: Bearer /' | curl -sS -H @- -o /dev/null -w '%{size_download} bytes, %{speed_download} B/s\n' --max-time 30 "https://management.azure.com/subscriptions/$(az account show --query id --output tsv)/providers?api-version=2021-04-01"
```

  About 3.5 million bytes within the 30 seconds is enough. With less, the runner blocks at `p1.iot_operations` and hands you that one script to run from Azure Cloud Shell.
- [ ] A line that carries megabytes can still drop single connections: on 26 November, between 14:45 and 15:02, three applies in a row each ended on one call that got no answer. From the twelfth issue the runner asks a read again before it gives up, and never sends a change twice; from the thirteenth, so does `bash infra/vm.sh push` with its question to the VM agent. When an apply still ends with `could not be looked at` or `Could not reach …, in 3 tries`, nothing was changed by that call: run the same line again.
- [ ] The capacity to reuse is **Active** in the Azure portal: `fabcentralussm01` (ID `d21d9da9-4054-4790-bc82-71aad3a91152`). The runner resumes none.
- [ ] Two terminals are open in the repository folder. The second is for step 9.
- [ ] Nothing is deleted in this pilot, and Phase 5a stays off: no command below has `--enable-phase5a-isolated-simulator`.

Deployment 064, whose sixth-issue plan was for a capacity of its own, is left as it is. The pilot starts a new deployment, with a fresh resource group and workspace.

## 1. Plan, with no question

```bash
python3 tools/deploy.py plan --new --edge-region southcentralus --capacity d21d9da9-4054-4790-bc82-71aad3a91152 --vm-size "Standard_D8s_v7 Standard_D8s_v6" --approve-role-changes --save-profile
```

- [ ] No question was asked.
- [ ] `New deployment XXX` names a suffix. Write it down: every later command carries `--deployment XXX`.
- [ ] The target shows your tenant, subscription `226b67c3-…`, a resource group `rg-windfarm-edge-XXX` *not created yet*, a workspace *not created yet*, and the capacity by name and SKU.
- [ ] `chosen by` names an option for the region, the capacity and the VM sizes.
- [ ] `0 blocked`. One step is yours: `phase1.tenant_settings`.
- [ ] A line `Profile saved for subscription …`.
- [ ] The apply line begins `python3 tools/deploy.py apply --deployment XXX --approve …`.
- [ ] `.deploy/XXX/plans/<plan>.json` exists and holds no token or key. Open it: it is what the approval covers.

Send: the whole output.

## 2. Apply Phase 1

The line the plan printed, with the confirmation of the tenant settings:

```bash
python3 tools/deploy.py apply --deployment XXX --approve PLAN --approve-role-changes --confirm phase1.tenant_settings
```

- [ ] The target block is the one of the plan.
- [ ] It stops somewhere. That is expected on a first run: exit code 3 names what is yours to do, exit code 4 means something is still running, exit code 1 is a failure with the tool's own last lines. After each stop, do what it says and run **the same line** again.
- [ ] While a script runs for a long time without output, a line `. still running after N s` appears about once a minute.

The points to watch, in the order an apply meets them. Each is unproven:

| Step | What is new under the runner |
|---|---|
| `pre.rights`, `pre.custom_locations` | read through Microsoft Graph with a token for the deployment's tenant, no longer through `az ad` |
| `p1.edge_vm` | the script's `az` calls carry `--subscription`; the VM sizes are tried in the order you gave |
| `p1.vm_identity_roles` | read with a filter on the principal, assigned by role ID |
| `p1.arc`, `p1.iot_operations` | Arc onboarding with Reader on the resource group only; `az iot ops` with `--subscription` |
| `p1.eventhouse` to `p1.eventstream` | the Fabric API calls of Phase 1; the eventstream from a definition |
| `p1.gate_telemetry` | fresh telemetry measured in the Eventhouse |
| `p1.reference_tables`, `p1.history`, `p1.forecast` | notebooks 01 to 03 as jobs |

Send: the output of every run of the line, also the ones that stopped.

## 3. Check that the CLI's active subscription decides nothing

In the **second** terminal, while nothing is running:

```bash
az account list --query "[].{name:name, id:id, isDefault:isDefault}" --output table
```

If you have a second subscription, make it the active one with `az account set --subscription OTHER`, then in the first terminal:

```bash
python3 tools/deploy.py status --deployment XXX
```

- [ ] The target still shows subscription `226b67c3-…`, and the steps of the deployment.
- [ ] Set the active subscription back afterwards: `az account set --subscription 226b67c3-3fe5-430b-88c7-6076efe3c114`.

With one subscription only, skip this step and say so.

## 4. Interrupt a notebook run, and resume

Do this during `p1.history` (notebook 02), which runs for minutes. If the apply of step 2 already went past it, do it at the first notebook of step 7 instead.

- [ ] When the line `running  p1.history` has been on the screen for half a minute, press **Ctrl+C**.
- [ ] The runner prints one line, `STOPPED  by Ctrl+C`, and no Python traceback.
- [ ] Run the same apply line again.
- [ ] It does **not** print `running  p1.history` with a new run. It waits for the run it had recorded, or takes its result if the run has finished in the meantime.
- [ ] In Fabric, open notebook `02_generate_history`, **Run history**: exactly one run.

If instead it prints `An earlier apply set out to run … and ended before it learned whether Fabric took the request`, you interrupted in the short moment between the request and its answer. That is the other case the runner is built for: read the runs it lists, and add `--adopt-job p1.history=ID` if one of them is yours or `--resubmit p1.history` if none is. Note which it was.

Send: both outputs, and what Run history showed.

## 5. Apply again, and look for duplicates

When the apply has ended with exit code 0, run the same line once more.

- [ ] Every line begins with `done`, `confirmed`, `unchecked` or `optional`. No line begins with `running`.
- [ ] In Azure, the resource group holds one VM, one cluster, one instance, one storage account. Its **Access control (IAM)** shows the VM's identity with two roles, each once.
- [ ] In Fabric, the workspace holds each item once; **Manage access** shows the two identities of the edge once each.
- [ ] Notebook `03_refresh_forecast` has one schedule. Each of notebooks 01, 02 and 03 has one run in its history (plus any from step 4, if you chose `--resubmit`).

## 6. Where Phase 1 stands

```bash
python3 tools/deploy.py status --deployment XXX
```

- [ ] `provisioned   yes`.
- [ ] `demo-ready    yes`, with the readings of the Eventhouse *measured now*.
- [ ] Stop the VM, wait five minutes, run status again: `provisioned   yes`, `demo-ready    no`, with `no fresh telemetry now`. Then start it again. Both commands name the deployment's settings, so that they do not go by the current deployment:

```bash
ENV_FILE=.deploy/XXX/demo.env bash infra/vm.sh stop
```

```bash
ENV_FILE=.deploy/XXX/demo.env bash infra/vm.sh start
```

## 7. Extend the same deployment through Phase 4

```bash
python3 tools/deploy.py plan --deployment XXX --up-to phase4 --approve-role-changes --allow-preview data-agent-sdk --allow-preview operations-agent
```

The two previews are yours to allow or to leave out. Without the first, notebook 09 is yours; without the second, the whole operations agent is, as in the Phase 3 guide.

Then the apply line it prints. It stops at each thing that is a person's, in this order, and names the confirmation to add once it is done:

- [ ] Notebooks 06, 07 and 08 run as jobs, started by the runner (seen on 26 November at 20:33, deployment 66i, then still with `--opt-in pip-jobs`). When one fails, the block has the steps by hand; for 07 by hand, `--confirm p2.acceptance` afterwards.
- [ ] `--confirm phase3.tenant_settings`; notebook 09 as a job (seen at 20:33).
- [ ] `p3.operations_agent_item`: `done`, or `blocked` with a line of Fabric's. **The creation has not been seen on a tenant** (on 26 November the agent had been made by hand, and the step found it). Either way send the lines.
- [ ] `blocked  p3.operations_agent … the agent has no playbook yet`, with four things to do. Open `WindFarmGearboxWatch` in the workspace. Note what you see: are the instructions there, is the KQL database under Knowledge, does **Generate playbook** work? Read the rules, install the Teams app, **Start**.
- [ ] Apply again: `done     p3.operations_agent: … a playbook with 3 rules, started`. A playbook with no number of rules means the definition names its rules in a way the runner does not know: send the line.
- [ ] `--confirm phase4.tenant_settings`.
- [ ] The app's tool is not signed in: the block prints the line, which now names the app's own folder, `.deploy/XXX/app/windfarm-twin`.
- [ ] `p4.eventhouse_principal`: the script's lines name the app registration `windfarm-twin-eventhouse-reader-XXX`, and no line shows a secret. Then `p4.deploy_secrets`: a line about waiting, and the app's tool a second time.
- [ ] `p4.scaffold`: an install that prints nothing for a minute or more is npm waiting on a connection; from the eighteenth issue it gives up on one after a minute and tries again. Seen on 26 November with npm's own five minutes: sixteen minutes of silence, then the rest in seconds.
- [ ] `done     p4.deploy: app WindFarmTwin is in the workspace: 2 items of that name (AppBackend, UserDataFunction)`, as seen on 26 November.
- [ ] `done     p4.gate_data_route: SQL probe with the operator's token: N rows from 12 turbines …`. **Not seen on a tenant yet**: on 26 November the probe did not find its driver (corrected in the nineteenth issue). If it blocks with a line about a sign-in or a permission, send the line; the twin's own check in step 8 does not depend on it.
- [ ] `app/windfarm-twin` beside the scripts was neither created nor changed.

Send: every output.

## 8. Confirm the twin itself

The runner's own check at the end of Phase 4 is a query with **your** token. It shows that the data is there, not that the deployed app reads it.

- [ ] Open the app `WindFarmTwin` in the workspace. Select the badge at the top right: the connection check.
- [ ] Read three things: the **build** it names, the **route** whose lines say PASS (the Eventhouse route: the runner has set up its service principal; the Lakehouse route passes as well and is the fallback), and the **age** of the newest reading.
- [ ] When the operations agent has sent a message to Teams and you have seen it, add `--confirm p3.agent_message`. Not before.

```bash
python3 tools/deploy.py apply --deployment XXX --approve PLAN --up-to phase4 --approve-role-changes --app-check BUILD,eventhouse,SECONDS
```

- [ ] `demo-ready    yes`, naming the build, the route, the age, and that you read them.
- [ ] If the lines "Eventhouse route" of the check do not pass, send the check as it is. A new principal can need a few minutes; the script's last lines name the one command for the database, in case the workspace role is not enough.
- [ ] Give a wrong build once, for example `--app-check 000000000000,eventhouse,60`: `demo-ready    no`, with the build the repository is at.

Send: a picture of the connection check, and the two outputs.

## 9. A changed plan is refused, and says what differs

Change one setting of the deployment by hand, for example the shutdown hour in `.deploy/XXX/demo.env` (`VM_AUTO_SHUTDOWN_UTC`), and run the last apply line again.

- [ ] `REFUSED`, with `What differs: settings.VM_AUTO_SHUTDOWN_UTC: was …, is now …`, and `Nothing was changed`.
- [ ] Put the value back. The same line is accepted again.

## 10. The clean-up, as a preview only

```bash
bash infra/99-cleanup.sh --deployment XXX
```

- [ ] `Acting on: resource group rg-windfarm-edge-XXX, workspace WindFarmDigitalTwin-XXX`.
- [ ] `Fabric capacity d21d9da9-…: existed before this deployment and is shared`, and that it is retained.
- [ ] `Nothing was changed`.

Removing the pilot's deployment is your decision and a separate command, with its own confirmation: `bash infra/99-cleanup.sh --deployment XXX --all`. It asks you to type the name of the workspace and of the resource group.

## What the pilot does not cover

- A capacity made by the runner (`--new-capacity`). It costs money and needs its own approval; try it on a deployment of its own.
- Phase 5a, and Phases 5b and 5c, which stay with their guides.
- Two applies from two computers at once. The lock that prevents two applies is a file on one computer.
- A Fabric Environment in place of the `%pip` cells: looked into, not built. See [15-deployment-runner.md](15-deployment-runner.md).

## What to send back

The outputs named at each step, the clock times you noted, and every place where what you saw differs from a box above. Each difference becomes a finding in [runner-validation-log.md](runner-validation-log.md).
