# Phase 1 validation log

The record of the first live deployment of Phase 1: what went wrong or was unclear, why, how it was resolved on the day, and what was changed in the repository as a result. The repository and the deployment guide were regenerated from this log on 20 November 2026; the last column says how each change was checked.

Environment of the live run, 19 November 2026: Azure Cloud Shell as the workstation; a Microsoft-managed demo subscription; region `southcentralus`; `AZ_LOGIN_MODE=identity`; VM size `Standard_D8s_v7`; CLI extension `azure-iot-ops` 2.11.2.

## Contents

- [Progress of the live run](#progress-of-the-live-run)
- [Second deployment, 20 November 2026](#second-deployment-20-november-2026)
- [Obstacles and what was changed](#obstacles-and-what-was-changed)
- [Decisions taken for the regeneration](#decisions-taken-for-the-regeneration)
- [Defects found while regenerating](#defects-found-while-regenerating)
- [Still open](#still-open)
- [Lessons](#lessons)

## Progress of the live run

| Step | Result | Notes |
|---|---|---|
| 1. Create the edge VM | Passed on the second attempt | Size changed to `Standard_D8s_v7` (obstacle 2). Custom Locations lookup failed (obstacle 3). |
| 2. Prepare the edge host | Passed | No issue reported |
| 3. Connect the cluster to Azure Arc | Passed | Managed identity sign-in |
| 4. Deploy Azure IoT Operations | Passed | Run 1 was on the VM (obstacle 5); run 2 in Cloud Shell hit a CLI crash (obstacle 7); passed afterwards |
| 5. Deploy the turbine simulator | Passed | SSH had been lost in between (obstacle 8). Telemetry from all 12 turbines and `MET-01` reached the eventstream. |
| 6.1 to 6.6 Fabric items, access, data flow | Passed | Events reached the eventstream about 10 seconds after their timestamp |
| 6.7 Eventstream to Eventhouse | Passed | The wizard proposed a mapping of its own (obstacle 9); caught before Finish |
| 6.8 Validate | Not reported | |
| 7. Lakehouse and reference data | Shortcuts created (obstacle 10); the results of 7.4 and 7.5 were not reported | |
| 8. Anomaly demo | Reported done | Obstacles 11, 12 and 13 on the way |
| 9. Stop, start, clean-up | Clean-up started on 20 November | Question asked (obstacle 14). Clean-up code was asked for the next day and run the same evening: the uninstall step failed (obstacle 15), the script went on and the resource group was deleted. The next section continues from there. |

The run took one evening: VM created at 19:35 Houston time, live data in Fabric at 22:01, fault injected at about 23:00.

## Second deployment, 20 November 2026

The first deployment was removed with `infra/99-cleanup.sh` at about 19:00 Houston time and Phase 1 was deployed again the same evening, from the regenerated version and with a new settings file. The user reported the guide as done at 22:02. "Reported" below means the user said so without sending output.

| Step | Result | Notes |
|---|---|---|
| Clean-up of the first deployment | Done | The uninstall of Azure IoT Operations failed (obstacle 15); the script went on and the resource group was deleted. The Fabric part deleted the items from Azure Cloud Shell (reported), so the Fabric REST API is usable there. |
| 1 to 3 | Passed, no output sent | The settings file held a name in `CUSTOM_LOCATIONS_OID`; steps 1 and 3 did not notice (obstacle 17). |
| 4. Deploy Azure IoT Operations | Passed after three attempts | Resource Health reported the young cluster as unavailable, twice (obstacle 16); then the wrong object ID showed (obstacle 17). `create` took 15:30. |
| 5. Deploy the turbine simulator | Passed, through `vm.sh run` | SSH rule gone again (obstacle 18). First real run of simulator 1.1.0: connected, 12 turbines publishing. |
| 6. Fabric items, access, data flow, eventstream to Eventhouse | Reported done | |
| 7. Lakehouse, reference data, notebooks | Reported done | 7.4 through `vm.sh run`. All four notebooks ran in Fabric and the checks of 7.6, 7.7 and 7.9 matched the guide (reported). The Spark runtime of the workspace is not known. |
| 8. Anomaly demo | Reported done with the guide | No details |
| After the run | Workstation moved to Ubuntu on WSL | Obstacles 19 and 20. SSH was opened again by the user; what had removed the rule is still not known. |

## Obstacles and what was changed

| # | Step | What happened | Cause | Changed in this version | Checked |
|---|---|---|---|---|---|
| 1 | 0 | Asked what `AIO_SKU` is | One-line comment only | Explained in `demo.env.example` and in step 0: the pricing tier, Standard or Essentials; blank uses the default, as the live run did | Read against the Azure IoT Operations pricing page |
| 2 | 1 | `SkuNotAvailable` for `Standard_D8s_v5` | The subscription is offered no v4 or v5 D-series sizes in the region | `VM_SIZE` is a list. Step 1 skips sizes that Azure lists as restricted, moves on when Azure refuses one at creation, says which size it used, and keeps an existing VM on a rerun. | Scenario tests; the query and its output format checked with the Azure CLI's own libraries |
| 3 | 1 | Custom Locations object ID not printed; by hand "Insufficient privileges" | Cloud Shell may not read Microsoft Entra ID; the script hid the error and did not wait for the provider registration | The script waits, prints the CLI's error, and skips the lookup when the ID is already in `demo.env`. Step 1 of the guide lists the four ways to get the ID. | Scenario tests |
| 4 | 1 | `scp … azureuser@<20.45.58.189>:~/` failed | An angle-bracket placeholder inside a command; bash reads `<` as redirection | No command in the guide contains an address to fill in. `./infra/vm.sh push` copies the repository; `./infra/vm.sh ssh` connects. | Scenario tests; the guide was searched for angle brackets in code blocks |
| 5 | 4 | `AuthorizationFailed` for the VM's identity | A workstation script was run on the VM | Scripts of `infra/` stop on the VM; scripts of `edge/scripts/` stop anywhere else; each says what to do. The guide has every command typed in one place, the workstation. | Scenario tests |
| 6 | all | Two copies of `config/demo.env` can drift apart | The file is copied once and edited later | `./infra/vm.sh push` and `push-env` send it again; the guide says when. Troubleshooting entry for the symptom. | Scenario tests |
| 7 | 4 | `az connectedk8s show` crashed in Cloud Shell: `'cffi' package version 2.1.1 … '_cffi_backend' … 2.0.0` | Two CLI extensions loaded in one process on a stale command index | Workstation scripts use the CLI itself and `azure-iot-ops` only; `tools/check-scripts.sh` enforces it | Reproduced and fixed outside Azure with CLI 2.93.0 |
| 7a | 4 | Cloud Shell ends a session after 20 minutes without keyboard activity | Found while analysing 7 | Said in step 0 and at step 4; a rerun of step 4 is safe | Not tested |
| 8 | all | SSH timed out two hours after it had worked | Just-in-time access (Microsoft Defender for Cloud) took over port 22 and removed the rule of step 1. The first diagnosis given, the daily shutdown, was wrong. | `./infra/vm.sh ssh` and `push` find out how access is opened in the subscription (just-in-time request, or the rule of step 1) and do it. `status` explains the state; `run` works without SSH. Step 0 warns managed subscriptions. | Scenario tests. The just-in-time request itself has not been run against Azure. |
| 8b | all | The daily shutdown default, 02:00 UTC, is 20:00 in Houston | The time is UTC and nothing said so | Default `0800`; step 0 makes the reader choose; step 1 prints the time in several zones; `./infra/vm.sh shutdown` changes it; step 4 says what "Offline" means | Scenario tests |
| 9 | 6.7 | The Get data wizard proposed its own mapping; two extra columns, `seq` empty | The wizard guesses types from the sample. The guide pointed to the wrong control. | Step 6.7 names the control (the mapping dropdown, toggle **Use existing mapping**), with two screenshots from the live run: what the wizard proposes, and the correct page. Query 18 checks the result; `91-repair-wizard-columns.kql` repairs it. | The corrected step was followed live, with the screenshot as evidence |
| 10 | 7.3 | A **Connection method** dialog that the guide did not mention | A newer step of the shortcut wizard | Step 7.3 names the dialog and the choice (Passthrough identity) | Followed live |
| 11 | 7.4 | `ssh sami@…`: `Permission denied (publickey)` | The VM's administrator is `azureuser`, not the user's own name | `./infra/vm.sh ssh` signs in as `VM_ADMIN`; step 1 prints the name; `./infra/vm.sh reset-key` installs a key again when it was lost | Scenario tests |
| 12 | 8 | `inject-anomaly.sh: … simctl.sh: Permission denied` | The scripts had lost their execute permission on the way to Cloud Shell | No script starts another directly (enforced by `tools/check-scripts.sh`); step 0 has a `chmod` line; `push` restores the permission on the VM; the guide starts edge scripts through `bash` | Scenario tests; tested in a copy without execute permissions |
| 12a | 0 | How the archive gets into Cloud Shell was not described | | Step 0 describes it | |
| 13 | 8 | Asked what "validation queries 7 to 12" are | The guide referred to queries by number in a file | Steps 6.8 and 8 show the queries in full, with the expected result | |
| 14 | 9 | Asked whether stopping the VM and pausing the capacity breaks anything | Covered in two sentences | Step 9 has the procedure, the order and what can go wrong over time | Not run live |
| 15 | 9, clean-up | First real run of `infra/99-cleanup.sh`, 20 November 2026 about 19:00 Houston time: `az iot ops delete` failed with `ClusterNetworkUnavailable`, "no agent is connected in the target arc resource". The script warned and went on to delete the resource group. | Azure could not reach the cluster through the Azure Arc agents. The script took `connectivityStatus: Connected` as proof that the cluster was reachable, or relied on `--force` for a cluster that was not; which of the two is not known, because the lines before the error were not reported. The extension's source shows that `--force` skips only the command's own status check and that the first deletion, the instance, always has to reach the cluster. The script made one attempt. | The uninstall is tried up to four times, 2.5 minutes apart, while Azure reports that it cannot reach the cluster and the VM is running; other errors are not retried. The warning says what was not done and why going on is safe. The stand-in for `az iot ops delete` now behaves as the extension's code does. Guide step 9 and troubleshooting describe the error. | 30 scenario tests against stand-ins, among them this error. Not rerun against Azure. In that run the resource group was deleted although nothing had been uninstalled, and the Fabric part deleted the items from Cloud Shell (reported by the user). The version with retries has not run against Azure. |
| 14a | 9 | An alarm raised when the simulator stops stays "active" for ever; the simulator's copy of the broker CA goes stale | Found while answering 14 | `ActiveAlarms()` ignores alarms from before the simulator's latest start; the simulator clears its alarms when it stops, reads the CA from the cluster at every connect, and restarts after 10 minutes offline | Automated tests; KQL syntax-checked. Not run on a cluster or an Eventhouse. |
| 16 | 4, second deployment | 20 November 2026, 20:17 Houston time: `az iot ops init` ended after 1:42 with "The connected cluster 'arc-windfarm-edge' is currently unavailable. Status: Degraded. Summary: One or more of the Azure Arc agent(s) deployed on your Kubernetes cluster seem to be not functional." At about 20:30 Resource Health said `Available`; the rerun passed `init` in 6:32 and then `az iot ops create` stopped with the same message after 1:46. | Azure Resource Health reported the cluster as unavailable for some minutes after it was connected to Azure Arc, and again right after `init` had installed cert-manager and the secret store. In between, the VM was running and all nine pods in `azure-arc` were `Running`. `init` and `create` ask Resource Health four times, 30 seconds apart, and stop when every answer is `Unavailable` (extension source, `work.py`). Why Resource Health reports this is not known. The daily shutdown, first suspected because of the time of day, was not the cause. | Step 4 calls `init` and `create` with `--health-checks-max 40 --health-checks-int 30`, a wait of up to 20 minutes, and skips both when the instance exists, because `create` refuses a cluster that already has Azure IoT Operations; troubleshooting had wrongly said that `create` can be repeated. Troubleshooting has an entry with the commands that tell a stopped VM, a young cluster and a failing pod apart. | Options checked against the help and source of extension 2.11.2. In the live run, `create` with these options passed the health check twice, at 20:46 and at 20:54. |
| 17 | 3 and 4, second deployment | 20:46 Houston time: with the longer health wait, `az iot ops create` passed the pre-flight checks and stopped after 0:59 with "Custom Locations Error: \"Microsoft.ExtendedLocation\" resource provider does not have the required permissions to create a namespace on the cluster". | `CUSTOM_LOCATIONS_OID` in `config/demo.env` held `cl-windfarm-edge`, the name of the custom location, which belongs in `CUSTOM_LOCATION_NAME` three lines above it. Step 3 passed it to `az connectedk8s enable-features`. Signed in with the VM's managed identity, the extension cannot validate the object ID and uses the given value as it is (extension source, `custom.py`), so step 3 ended without an error and the mistake showed two steps later. Resolved on the day by running `enable-features` again with the object ID through `az vm run-command`. | `require_object_id` in `config/load-env.sh`: steps 1, 3 and 4 stop when the setting is not an object ID or is the application ID of the service. Step 3 also stops when `enable-features` reports that it left custom locations out, which the extension does with a warning only. The example settings file says what the value looks like and names the setting it is confused with. Troubleshooting describes the error and the repair. | ShellCheck; the check function run against good and bad values; scenario test for step 1. In the live run, `create` passed afterwards: instance `aio-windfarm` created in 15:30, finished at about 21:09. The new checks themselves have not run against Azure. |
| 18 | 5, second deployment | 21:10 Houston time, first real run of `infra/vm.sh ssh` in the regenerated version: "Port 22 is closed, there is no just-in-time policy, and the SSH rule of step 1 is gone". Steps 2 and 3 had run over SSH about an hour earlier. | Not known yet. Something removed the SSH rule again, as in the first run (obstacle 8). Either no just-in-time policy exists yet, or `vm.sh` does not see it: it lists the policies with `az security jit-policy list`, hides the error of that command and matches the resource group name with exact case. | `./infra/vm.sh ssh COMMAND` now runs the command through the VM agent by itself when the VM runs, port 22 is closed and there is neither a just-in-time policy nor an SSH rule; the guide's commands then work unchanged. The user met the same stop again at step 7.4, 21:34. The detection of just-in-time policies is unchanged until its cause is known. The user ran step 5 through `./infra/vm.sh run bash ./edge/scripts/05-deploy-simulator.sh`, which needs no SSH, and it passed at 21:12: image of simulator 1.1.0 built on the VM, deployment rolled out, connected to the broker, first status line "wind 8.8 m/s, site power 18544 kW, published 89, dropped 0". That is the first real run of `vm.sh run`, of the 1.1.0 image and of step 5 without SSH. He was asked for the output of `./infra/vm.sh nsg-log` and of the policy list. | Scenario test for the fallback. Cause of the missing rule open. |
| 19 | Any, after the second deployment | Azure Cloud Shell had lost the repository folder with `config/demo.env` and the SSH key; the user moved to Ubuntu on WSL and asked for a way to rebuild the settings from what is deployed, and for the changed files only. | Cloud Shell keeps the home folder only with a mounted storage account. The guide said so in step 0; nothing checked it. | `infra/rebuild-env.sh` writes `config/demo.env` from the deployed resources: names, region, VM size and shutdown, Custom Locations object ID, eventstream address and topic. `infra/vm.sh reset-key` installs the new workstation's key. Step 0 names the check `ls ~/clouddrive` among three habits. Updates are delivered as a full archive and as an archive of the changed files. | Five scenario tests. The script's real run was not reported. |
| 20 | Any, on WSL | `sudo bash ./infra/vm.sh reset-key` answered "The Azure CLI is not signed in" directly after a successful `az login`. | Under `sudo` the Azure CLI runs as root, which has no sign-in; the key would have gone to root's home. | Step 0 says not to use `sudo` for the workstation scripts, and why. | Read |

## Decisions taken for the regeneration

Some "to do" notes of the live run proposed more than was done. These are the choices, with the reason.

| Proposal from the log | Decision | Reason |
|---|---|---|
| No step may need inbound SSH; step 1 creates no SSH rule (8a) | SSH stays the main route, through a helper that opens access. `./infra/vm.sh run` is the route without SSH. Step 1 still creates the rule. | The edge steps print long output over many minutes, and one of them can ask for a device code. The VM agent returns the last 4,096 bytes and is not interactive. Just-in-time access is the sanctioned way to SSH in a managed subscription, and the helper uses it. In an unmanaged subscription the rule of step 1 is what makes SSH work at all. |
| Rename `infra/` to `workstation/`; scripts print where they run (5a) | Not renamed. Scripts check where they run and stop with advice. The guide types every command on the workstation. | A rename would break the paths of a running deployment for no gain once the wrong place is impossible. |
| Make the wizard's guess harmless by changing `schemaVersion`; or create the destination through the REST API (9a) | Not done. Screenshots, query 18 and the repair script instead. | Changing the message format would break the deployed tables. The REST route is on the roadmap. |
| Deliver the validation queries as a KQL queryset item (13) | Not done. The queries are printed in the guide. | A queryset cannot be imported from a file in a way that was verified. |
| Start `init` and `create` so that a closed Cloud Shell session does not matter (7a) | Not done. A warning, and a rerun is safe. | No way to verify a detached run without Azure. |
| Find the broker CA's rotation period on the live cluster (14a) | Not needed any more | The simulator no longer depends on a copy. |

## Defects found while regenerating

Found by testing the new parts, before delivery.

| # | Defect | How it was found | Fix |
|---|---|---|---|
| R1 | Live turbines never reached rated power: the model multiplied the capped power curve by the air density, and the site is at 800 m. Version 1.0 had this too. | Comparing live output with the history at the same wind | The live model uses the history's formula: the wind speed is corrected for density, and rated power is the cap |
| R2 | Each start of the simulator drew new turbines, so "WT-09 produces 4 percent less" was lost in a spread of 4.5 percent between healthy turbines | The same comparison | The turbines' efficiency, thermal behaviour and vibration level are properties of the site, shared with the history |
| R3 | Step 1 would have rejected every VM size: the Azure CLI prints a two-value result on two lines, and the script expected one line with a tab. The stand-in `az` used in the tests printed a tab, so the tests passed. | Formatting sample data with the CLI's own output library | The script joins the lines; the stand-in now prints what the CLI prints |
| R4 | A history shorter than a few months failed, because a table without rows had no columns | A test with a two-month history | Every table has fixed columns |
| R5 | Two oil samples of a turbine had identical values | Reading the answers of the question bank | The random stream of a service visit depends on the visit |
| R6 | Performance and nacelle direction were too regular: every healthy turbine had the same index every month and stood exactly in the wind | Reading the answers | A slow drift of about one percent, and a small calibration error per nacelle |
| R7 | The local Spark session wrote a history that ended six hours before "now" | Reading the first answer | Not a defect of the notebooks: the test harness printed a time in the wrong zone. The notebooks set the session to UTC and notebook 03 reads times as epoch seconds, so they do not depend on the zone of the machine. |

## Still open

Questions to the user about the live run, for the record:

1. After the CLI crash in step 4 (obstacle 7): did a plain rerun pass?
2. How did SSH come back before step 5: a just-in-time request in the portal, or by itself?
3. Which of the four ways gave the Custom Locations object ID?
4. Was the daily shutdown moved from 02:00 UTC?
5. What did the checks of steps 6.8, 7.4 and 7.5 show?

Not verified on Azure or Fabric in this version: see "What has and has not been verified" in [00-architecture.md](00-architecture.md).

Clean-up: `infra/99-cleanup.sh` was added on 20 November 2026 on request and run the same evening (obstacle 15). Open: which lines preceded the uninstall error; whether the uninstall is needed at all for this demo, since the resource group was deleted cleanly without it and the cluster never outlives its group.

Second deployment, open: what removed the SSH rule and whether a just-in-time policy existed that `vm.sh` did not see (obstacle 18); why Azure Resource Health reports a young cluster as unavailable (obstacle 16); which Spark runtime ran the notebooks; whether the KQL added since the first run (`ActiveAlarms()`, `92-question-bank-live.kql`) was run.

Added on 23 November 2026, at the close-out of Phase 4, for three entries of this log:

- **Obstacle 12, scripts without the execute permission.** It came back twice (obstacle 7 of Phase 3, obstacle A of Phase 4). The `chmod` step this log introduced did not prevent that. Since the close-out of Phase 4 every command of every guide and every hint of a script starts a script through `bash`, and `bash tools/check-scripts.sh` fails on the direct form. The `chmod` steps are gone.
- **Obstacle 19, `infra/rebuild-env.sh`.** On 23 November the user asked for the command again after a restart of the environment; `bash infra/vm.sh` worked afterwards, so a settings file existed. Whether the script wrote it, and what it printed, was not reported. Its run against Azure still counts as not seen.
- **Question 4, the daily shutdown.** Answered by Phase 4: the VM of the current deployment stops at 08:00 UTC (`VM_AUTO_SHUTDOWN_UTC="0800"`), and did so in the middle of the Phase 4 deployment (its obstacle K).

Design question for Phase 2: whether readers without access to the Eventhouse must read through the Lakehouse shortcuts, which would need delegated instead of passthrough identity (obstacle 10).

## Lessons

Of both deployments.

- A script that passes ShellCheck and matches the documentation can still fail on the environment it runs in. Where a command can be exercised without Azure (argument parsing, extension loading, output formatting), exercise it before delivery, with the real tool and not a stand-in.
- A stand-in is only as good as its imitation of the output format. Take the format from the real tool's own code.
- Give the command that tells causes apart before giving a fix. The first diagnosis of obstacle 8 was a plausible guess, and wrong.
- Every manual choice in a portal wizard that decides whether the system works needs a picture of the right result and a query that checks it afterwards.
- One place to type commands. Two shells, on two machines, with two copies of the settings, produced several of the fourteen obstacles.
- The help text of an option is not its behaviour. `--force` is described as "force deletion even when the cluster is disconnected"; the code skips one check. Where a decision rests on an option, read the code, and build the stand-in from the code, not from the assumption.
- A status reported by Azure is not the capability it suggests. `Connected` did not mean that Azure could reach the cluster. Wait for the operation to work, with retries, instead of waiting for a status.
- Generated data shows its seams when someone reads it as an analyst would. Reading the answers to real questions found three defects that the tests had not.
