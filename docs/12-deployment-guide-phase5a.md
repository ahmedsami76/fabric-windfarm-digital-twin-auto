# Deployment guide, Phase 5a: a command from Fabric reaches the edge

Phases 1 to 4 move data one way, from the turbines to Fabric. Phase 5 adds the way back: the operations agent proposes an action, an engineer approves it, and the edge applies it. Phase 5a builds and proves the path that command travels, alone, with a command you send by hand. Phase 5b puts the agent and the approval in front of it.

**Status of this guide.** Written on 23 November 2026. **First run on 24 November: the notebook found the eventstream, read where to write from the Fabric API, built the command, and stopped at the send**, because a library the send needs was not installed. That was corrected (obstacle A in [phase5-validation-log.md](phase5-validation-log.md)), and the same evening the run was **reported to me as working: WT-07 was curtailed**. I have seen no output of that second run, so the four points below count as reported, not as seen. The notebook changed once more for Phase 5b: it names no turbine by itself and has no install cell; steps 2 and 4 describe the current one. The simulator's side has been there since Phase 1 and is tested. Everything between the notebook and the simulator is built from the documentation and from the source of the Azure CLI extension, and four things in it are unproven: they are listed in [What was and was not tested](#what-was-and-was-not-tested), and each step says what to send me when it does not behave as written. That is the purpose of this step: to find out, on a path with one moving part at a time, before an agent is put on top.

## Contents

- [What you get](#what-you-get)
- [Before you start](#before-you-start)
- [Step 1: Create the command path](#step-1-create-the-command-path)
- [Step 2: Import the notebook](#step-2-import-the-notebook)
- [Step 3: Watch the control topic](#step-3-watch-the-control-topic)
- [Step 4: Send a command](#step-4-send-a-command)
- [Step 5: See it take effect](#step-5-see-it-take-effect)
- [Step 6: Release](#step-6-release)
- [The command center: commands by hand, from then on](#the-command-center-commands-by-hand-from-then-on)
- [If something fails](#if-something-fails)
- [How it works](#how-it-works)
- [What was and was not tested](#what-was-and-was-not-tested)
- [Remove Phase 5a](#remove-phase-5a)

## What you get

| Item | Where | What it is |
|---|---|---|
| Eventstream **WindFarmCommands** | Fabric workspace | A custom endpoint as source (`CommandIn`), the default stream, a custom endpoint as destination (`CommandOut`). Nothing else: no table, no transformation |
| Notebook **12_send_edge_command** | Fabric workspace | Builds one command, checks it, and writes it to `CommandIn`. One command per run; since Phase 5b it is also what the operations agent runs |
| Notebook **13_command_center** | Fabric workspace | The same by hand and in one place: each command is one line, the turbines' state is a table, and after a send the notebook waits until the telemetry shows the command and says how long that took |
| Data flow endpoint `fabric-commands` | Azure IoT Operations | `CommandOut`, read with the Kafka protocol as the identity of the Azure IoT Operations extension |
| Data flow `fabric-to-windfarm-control` | Azure IoT Operations | From that endpoint to the topic `contoso/windfarm/northwind-ridge/_control/request` on the local MQTT broker |
| `infra/08-create-command-path.sh` | Repository | Creates the eventstream, the endpoint and the data flow; shows them; removes them |

```text
Fabric                                               Edge (Azure IoT Operations)
+-------------------------------------------+        +------------------------------------------+
| Notebook 12 --> CommandIn                  |        | data flow fabric-to-windfarm-control      |
|                 eventstream WindFarmCommands|  Kafka |   Kafka source --> MQTT broker            |
|                 CommandOut ----------------|------->|   topic .../_control/request --> simulator |
+-------------------------------------------+        +------------------------------------------+
```

The simulator applies the command and the telemetry of Phase 1 carries the result back: state `CURTAILED`, the power setpoint, the lower power. In the twin of Phase 4 the ring of the turbine turns blue.

**What a command can do.** The control topic takes five commands: `curtail`, `release`, `stop`, `start`, `reset`. It refuses everything else; injecting a fault or changing the wind is possible only from the edge itself, through `simctl`. The notebook refuses a command without a turbine, a curtailment without an end, and a percentage outside 0 to 100, before anything is sent.

## Before you start

- Phase 1 is deployed and the simulator runs. **The edge VM is running**: `bash infra/vm.sh status`. It stops every day at 08:00 UTC unless you changed that.
- You are signed in on the workstation with `az login`, as the account that owns the Fabric workspace.
- The identity of the Azure IoT Operations extension is a Contributor of the workspace. Step 6.5 of the Phase 1 guide did that, and the telemetry would not arrive without it.
- The repository copy has the files of this phase (the list is in [phase5-validation-log.md](phase5-validation-log.md)).
- Phases 2 to 4 are not needed. With the twin of Phase 4 open you see the result without a query.

Time: about 15 minutes.

## Step 1: Create the command path

**[Workstation]** From the repository folder:

```bash
bash infra/08-create-command-path.sh
```

It does three things and says so as it goes: creates the eventstream `WindFarmCommands` in the workspace, reads from the Fabric API where the edge has to connect, and creates the endpoint and the data flow in Azure IoT Operations. You copy nothing from the portal.

**Check.** The last lines are a small table and two hints:

```text
==> Done
Name                        Mode     State
--------------------------  -------  ---------
fabric-to-windfarm-control  Enabled  Succeeded
```

Above it, the script has printed what the edge reads from: a host ending in `.servicebus.windows.net:9093`, a topic starting with `es_`, and a consumer group.

**If it stops with "Fabric did not create the eventstream from its definition".** This is the first unproven thing: the form of a custom endpoint in an eventstream definition is not in Microsoft's reference, and I wrote it by analogy with the other node types. The script prints what Fabric said, and four portal steps to make the eventstream by hand. Do those, then run the script again: it uses an eventstream it finds. Send me what Fabric said, so that the definition can be corrected.

**If it says "Its two custom endpoints are not in its topology yet".** That is not a failure. Fabric lists a new eventstream before it has built its nodes from the definition, so after creating one the script asks for the topology again, for two minutes at most. On 26 November 2026 the script still read it once, in the same second, found no endpoint, and stopped with the four steps by hand for an eventstream that was only not ready. If it stops with "has no custom endpoint as a destination" after the wait, run it once more before you do anything by hand: it uses the eventstream it finds.

`bash infra/08-create-command-path.sh --show` prints what exists at any time and changes nothing. The script can be run again: it keeps the eventstream and writes the endpoint and the data flow anew.

## Step 2: Import the notebook

**[Fabric]** In the workspace: **Import**, **Notebook**, **From this computer**, and choose `fabric/notebooks/12_send_edge_command.ipynb` from the repository copy on the computer where the browser runs. It needs no Lakehouse attached.

## Step 3: Watch the control topic

**[Workstation]** In a second terminal, so that you see the command arrive on the edge:

```bash
bash infra/vm.sh ssh bash ./edge/scripts/mqtt-peek.sh --count 2 'contoso/windfarm/northwind-ridge/_control/#'
```

It waits. When a command arrives it prints two messages and ends: the request, and the simulator's answer on `…/_control/response/…` with `"ok": true`.

## Step 4: Send a command

**[Fabric]** Open **12_send_edge_command**. The first code cell holds the values a caller sets, and the second what the notebook does:

```python
turbine = ""
percent = 30
duration = "10m"
requested_by = ""
```

```python
command = "curtail"
reason = ""
dry_run = False
```

Set `turbine = "WT-07"`, leave the rest, and select **Run all**. The notebook names no turbine by itself, so that a run that forgets the turbine is refused instead of curtailing one. The last code cell installs two libraries the first time it runs in a session; that takes some seconds.

**Check.** The last code cell prints:

```text
Sent: curtail for WT-07, request 3f9a1c0b7d2e, at 2026-11-23T16:00:00Z UTC.
```

To see what would be sent without sending it, set `dry_run = True` in the second code cell.

## Step 5: See it take effect

Three places, from the nearest to the farthest. Use the first one that shows nothing to find where the command stopped.

| Where | What you see | Within |
|---|---|---|
| The terminal of step 3 | The request with `"command":"curtail","turbine":"WT-07","percent":30.0`, then the response with `"ok": true` and `"curtailed": ["WT-07"]` | Seconds |
| **[Workstation]** `bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh status` | Under `turbines`, WT-07 with `"state": "CURTAILED"` and a power at or below 1260 kW | Half a minute |
| **[Fabric]** KQL queryset on `WindFarmEH`, the query below | `State` is `CURTAILED`, `PowerSetpoint` 1260, `ActivePower` falling towards it | A minute |
| The twin of Phase 4 | The ring of WT-07 turns blue; its panel says Curtailed and 30% of rated | A minute |

```kusto
TurbineTelemetry
| where TurbineId == 'WT-07' and Timestamp > ago(5m)
| project Timestamp, State, PowerSetpoint, ActivePower
| top 5 by Timestamp desc
```

1260 kW is 30 percent of the 4,200 kW the turbine is rated at. In a weak wind the turbine produces less than that anyway: the state and the setpoint still change, the ring still turns blue, and the power stays where it was. For a power that visibly falls have a wind above 10 m/s (`bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh wind --mean 11 --duration 60m`).

**Send me, whatever the outcome:** the output of step 1, the two messages of step 3 (or the fact that none came), and the five rows of the query. With those three I can tell which of the four unproven things held. And two times, read off a clock: from **Run all** to the line `Sent`, and from `Sent` to the ring turning blue. Phase 5b is designed around them.

## Step 6: Release

The curtailment ends by itself after its ten minutes. To end it now, set `command = "release"` in the second code cell, leave `turbine = "WT-07"` in the first, and run the notebook again. `percent` and `duration` are ignored for `release`. Set the command back to `curtail` afterwards: since Phase 5b the operations agent runs this notebook, and it is meant to curtail. The command center below sends a release in one line, without touching this notebook. From the edge, without Fabric: `bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh release all`.

## The command center: commands by hand, from then on

Steps 4 to 6 prove the path with notebook 12, which sends one command per run. For sending by hand after that, for a test or in front of people, use the second notebook. There are two reasons for a second one.

- **Notebook 12 has two masters since Phase 5b.** The operations agent runs it as its action, and the values in its first code cell are what a run falls back on. A turbine you leave there after a test becomes the turbine of any run that passes none. The command center has no such cell and is never run by the agent.
- **One line per command, and the answer with it.** The connection is made once per session. After that each cell is one command, and the notebook then reads the telemetry until the command shows, or says that it did not.

**Since Phase 5c the notebook also reads the edge's command log.** Once [that phase](14-deployment-guide-phase5c.md) is deployed, a send is answered twice: first by the edge (it took the command, or it refused it and why), then by the telemetry. `history()` prints the log. On a database without the log the notebook says so once and behaves as described here.

**[Fabric]** In the workspace: **Import**, **Notebook**, **From this computer**, and choose `fabric/notebooks/13_command_center.ipynb`. It needs no Lakehouse attached. Open it and run the first two code cells; the second ends with the state of the turbines:

```text
Commands go to the eventstream WindFarmCommands (….servicebus.windows.net).
The turbines' state is read from WindFarmEH. Commands are sent as ….
Turbine  State             Limit kW Power kW Wind m/s Vib mm/s Oil degC  Age s
------------------------------------------------------------------------------
WT-01    RUNNING                  -     3482     12.1     1.98     63.9      8
…
```

Then run any of the cells below it, or change one and run it:

```python
send("curtail", "WT-07", percent=30, duration="10m")
send("release", "WT-07")
send("stop", "WT-05", duration="5m", reason="maintenance")
send("start", "WT-05")
send("reset", "WT-03")
status()
```

After a send the cell prints the command, the line `Sent: …`, and then one of three things:

| It prints | Meaning |
|---|---|
| `WT-07: limit of 1260 kW in force, seen … s after the send (state CURTAILED, setpoint 1260 kW, …)` | The command arrived and the telemetry shows it. The seconds are the whole way: eventstream, edge, simulator, and the telemetry back into the Eventhouse |
| `WT-07: not seen after 150 s (…)` | It did not show. The table below says where to look, hop by hop |
| `WT-07: already so before the command (…)` | The turbine already looked like that, for example a release on a turbine that was not curtailed. The command was sent; the telemetry cannot tell you whether it arrived. With the command log of Phase 5c this case is settled by the edge's line, and the notebook prints that instead |
| `WT-07: the edge took the command … s after it was written (at …Z), in the log … s after the send.` | Phase 5c: the edge's own record of this command has reached the database. The first number is the way from Fabric to the edge |
| `The edge refused the command: …` | Phase 5c: the edge's reason. Nothing is waited for |
| `The edge's log has no entry for this command.` | Phase 5c: after 150 seconds. With the telemetry showing the command, the log's way back is broken, not the command's. Without it, the command did not arrive |

`send(…, dry_run=True)` builds and shows the command and sends nothing; `send(…, wait=False)` sends and does not wait. The word `all` in the place of the turbine means all twelve.

The last cell draws the same as a panel: two lists, a slider, **Send**, **Status** and **Command log**, and a log. It is optional and the least certain part: whether a Fabric notebook shows it and runs its buttons I have not seen. The cells above do not depend on it.

**Send me** the lines a `curtail` prints. `seen … s after the send` is the time from Fabric to the turbine and back, which has not been measured yet.

Three ways to send a command by hand now exist, and they test different things:

| From | Command | What it proves |
|---|---|---|
| The command center | `send("curtail", "WT-07", percent=30, duration="10m")` | The whole path, with its time |
| The workstation | `bash infra/09-remediation-agent.sh --rehearse WT-07` | Notebook 12 as a job with its values passed in, as the agent runs it (Phase 5b) |
| The edge | `bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh curtail WT-07 --percent 30 --duration 10m` | The simulator alone, without Fabric |

## If something fails

Follow the command along its way. Each row is one hop.

| Symptom | Where it stopped | Do |
|---|---|---|
| Step 1: `No workspace named WindFarmDigitalTwin is visible to this sign-in` | Before anything | `az login` as the account that owns the workspace; or correct `FABRIC_WORKSPACE_NAME` in `config/demo.env` |
| Step 1: `Fabric did not create the eventstream from its definition` | Fabric, creating the eventstream | Make it by hand with the four steps the script prints, run the script again. Send me Fabric's words |
| Step 1: `The eventstream has no custom endpoint as a destination`, right after `Created:` | The eventstream is listed and its nodes are not built yet. The script waits for them for two minutes (since 26 November 2026) | Run the script again. Only if the same lines come back a few minutes later, add the two endpoints by hand as the script says |
| Step 1: `Fabric did not give the connection of the destination` | Fabric, the eventstream is not running | Open the eventstream in the portal. If it is in edit mode, **Publish**. Then the script again |
| Step 1: `'consumerGroupId' is required in kafka source dataflow endpoint configuration` | The Azure CLI, before it sends the data flow | The endpoint was created without the consumer group. Send me the line of the script's output that starts with `consumer group:` |
| Step 1: an error from `az iot ops dataflow apply` that names the source or the endpoint type | Azure IoT Operations refuses a Kafka source from the CLI | The second unproven thing. Send me the error. The same data flow can be created from a Kubernetes manifest, which Microsoft's page names as supported |
| Step 4: `The Fabric API answered 4…` in the cell that starts with `# Where to write` | The notebook asks Fabric where to write | The message has Fabric's reason. 403: you need at least Contributor on the workspace |
| Step 4: `'' is not a turbine. Use WT-01 to WT-12, or the word all.` | The notebook, before anything is sent | Set `turbine` in the first code cell |
| Step 4: the last cell fails with `ImportError: Please install websocket-client library to use sync websocket transport` | The notebook is the one of 23 November, whose first cell installs one library | Delete it and import the current notebook (step 2 of the [Phase 5b guide](13-deployment-guide-phase5b.md)) |
| Step 4: the last cell fails with `pip could not install …` | The install of the two libraries | The message carries pip's reason. Send it to me |
| Command center: `The KQL database answered 401` or `403` | The notebook reads the turbines' state as you | You need at least Viewer on the KQL database, which a workspace member has. Send me the message |
| Command center: `not seen after 150 s`, and the twin or `simctl status` shows the turbine did change | The telemetry is late or the VM's clock is off | `status()` shows the age of the newest reading. Send me that table |
| Step 4: the last cell fails with `ConnectError`, `AuthenticationError` or a timeout | The notebook cannot reach or may not write to the event hub of the eventstream | Send me the error. A workspace with outbound access protection blocks this call |
| Step 4 says `Sent`, step 3 shows nothing | Between the eventstream and the edge | In the portal, open **WindFarmCommands**: the data preview of the stream shows the command if it arrived. If it is there, the data flow is not reading: the two commands below |
| Step 3 shows the request and no response, or a response with `"ok": false` | The simulator refused it | The response carries the reason. A request that is not the JSON the notebook wrote was changed on the way: send me both messages |
| Step 3 shows request and response, the turbine does not change | Nothing is wrong with the path | The state changes in any wind. If only the power does not fall, the wind is too weak for the limit to bite (step 5). Otherwise another command released the turbine |

The data flow on the edge, when the eventstream has the command and the topic does not. Open a shell on the VM with `bash infra/vm.sh ssh`, then there:

```bash
kubectl get dataflows.connectivity.iotoperations.azure.com -n azure-iot-operations
```

```bash
kubectl logs -n azure-iot-operations "$(kubectl get pods -n azure-iot-operations -o name | grep -i dataflow | head -n 1)" --tail=80
```

The first lists both data flows, the one of Phase 1 and `fabric-to-windfarm-control`. Send me what the second one prints. An authentication error there means the identity of the extension may not read from the eventstream; a decode or publish error means the message did not survive the translation from Kafka to MQTT, which is the third unproven thing.

## How it works

**Why an eventstream.** A command needs a way from Fabric to a machine behind a firewall that accepts no inbound connection. The edge already reaches out to Fabric for its telemetry; the command travels the same way in the other direction: the edge reads it. An eventstream with a custom endpoint as its destination is, to the edge, a Kafka topic, and Azure IoT Operations can use a Kafka topic as the source of a data flow as long as the local MQTT broker is the destination.

**No key anywhere.** The edge signs in to the eventstream with the managed identity of the Azure IoT Operations extension, as it does for the telemetry. The notebook asks the Fabric API for the connection of `CommandIn` each time it runs and uses it for one send; the key is not printed, not stored and not in the repository. Whoever can run the notebook in this workspace can already read that key in the eventstream's own details pane.

**The script asks instead of you copying.** Phase 1 had you copy a bootstrap server and a topic name from the portal into `config/demo.env`. For the commands the script reads the same values, and the consumer group, from the Fabric API (`…/eventstreams/{id}/destinations/{id}/connection`).

**The command is checked twice.** Once in the notebook, by code that the repository's tests hand to the simulator's own handler; and once by the simulator, which answers every request on `…/_control/response/{requestId}` with `ok` and the reason.

**A turbine is always named.** The simulator reads a command without a turbine as "all twelve". Both notebooks require a turbine. The command center takes all of them when the word `all` is written; notebook 12, which the agent runs, acts on one turbine at a time and refuses `all`.

**A curtailment always ends.** The notebook refuses `curtail` without a duration, so a forgotten command cannot hold a turbine down for good.

**The values may be written as people write them.** `Curtail`, `30%` and `10 minutes` mean what they say, and a value the command does not take is left out, not refused: to release, change the command and leave the rest. In the first version of the notebook the cell decided by the command's name as typed. `Curtail` was then refused, and `Stop` lost its duration without a word and became a stop without an end. A review found the first on 23 November, before the notebook had run; the second came out when I ran its example.

## What was and was not tested

**Run, without Fabric and Azure**

| What | How | Result |
|---|---|---|
| The command the notebook builds | 47 tests. Each of the five commands is handed to the simulator's handler of the control topic and applied: a curtailed turbine goes to `CURTAILED` at 1,260 kW and returns by itself, a stopped one to `MAINTENANCE`; its neighbour does not change. Fourteen commands that would do more than asked are refused before sending. The command may be written in any case, and a percentage or a duration as people write them (`30%`, `10 minutes`); a `Stop` keeps its end. Five mistakes planted in the code were each caught | Pass |
| The notebook's cells | Executed top to bottom against stand-ins for the notebook utilities, the Fabric REST client and the event hub: the three calls it makes, the one event it sends, `dry_run`, a run without a turbine, and that no key reaches the output | Pass. A stand-in is my idea of the other side |
| The send with the two pinned libraries | The real client opens a connection over WebSocket to an address where nothing listens, and has to fail on the network, not on a missing library. This check was added after the first run: before it I had built the client and never opened a connection | Pass |
| The command center | 27 tests. Its cells run top to bottom against stand-ins that are joined to a simulator: the pretend event hub hands each event to the simulator's control handler, and the pretend KQL database answers from the simulator's turbines. All five commands take effect and are seen; a command lost on the way is reported as not seen; a turbine that already looked like the command's effect is named and not counted; what the notebook refuses is not sent; the panel sends what the cells send | Pass. Not run in Fabric: reading the KQL database from a notebook over REST, and the panel |
| `infra/08-create-command-path.sh` | 11 scenarios against a stand-in for the Fabric API and the data flow commands: first run, an eventstream made by hand, a refused definition, no destination, a connection that comes late or never, `--show`, `--remove`, no workspace | Pass |
| The options of the `az iot ops` commands | Read in the source of the extension, version 2.11.2: `--group-id` on `create fabric-realtime`; and that `dataflow apply` accepts a Kafka endpoint as source when it has a consumer group and the other side is the local broker | As the script uses them |

**Read in Microsoft's documentation on 23 November 2026, not run**

- A Kafka endpoint can be the source of a data flow when the default MQTT broker is the destination, and needs a consumer group. The operations experience cannot create such a data flow; Kubernetes and Bicep can.
- An eventstream is created from a definition through `POST …/eventstreams`; the connection of a custom endpoint is read through `…/destinations/{id}/connection` and `…/sources/{id}/connection`.
- A principal with Contributor on the workspace can read from a custom endpoint with Microsoft Entra ID authentication.

**Seen in the first run, 24 November 2026**

From the export of the notebook after **Run all**, on Fabric Runtime with Python 3.13:

- The install cell restarts the kernel, and the parameter cell below it keeps its values. (That notebook had a `%pip` cell. The current one has none: Phase 5b.)
- The Fabric API answers the notebook's three calls in the form the code expects: the list of eventstreams, the topology with a custom endpoint as source, and the connection of that source with namespace, event hub and key.
- The eventstream `WindFarmCommands` exists and has a custom endpoint as its source. Whether the script made it from the definition or it was made by hand, I was not told.
- The command was built as designed, with the name of the signed-in user as `requestedBy`.
- The send stopped with `ImportError: Please install websocket-client library`: obstacle A.

**Unproven when this was written. Reported as working on 24 November, not seen**

1. **The eventstream definition.** The JSON of a custom endpoint node is not in the reference. If Fabric refuses it, the eventstream is made by hand in four steps and everything after it is unaffected.
2. **A Kafka source through the CLI.** The extension's own check allows it; whether the service takes it from the CLI as it does from Bicep is not shown anywhere I could read.
3. **The message on the way.** That the eventstream hands on the event unchanged, and that the data flow turns the Kafka record into an MQTT message whose payload is the JSON the notebook wrote. Microsoft lists a known issue with Kafka headers written by an AMQP sender when they are translated to MQTT; the notebook sends no properties of its own, and what the eventstream adds is not known.
4. **The notebook's send.** That a Fabric notebook may open a connection to the event hub behind the eventstream on port 443, and that the connection string the API returns is accepted.

The report "WT-07 curtailed" means all four held on that tenant, whichever way the eventstream was made. Still not known: whether the script made the eventstream from its definition or it was made by hand, what the messages on the control topic looked like, and how long a command takes end to end. Step 3 of the Phase 5b guide measures the last.

## Remove Phase 5a

**[Workstation]**

```bash
bash infra/08-create-command-path.sh --remove
```

It deletes the data flow, the endpoint and the eventstream. Delete the notebooks **12_send_edge_command** and **13_command_center** in the workspace by hand, or leave them: without the eventstream they stop with a message. `bash infra/99-cleanup.sh --fabric` removes all three as well.
