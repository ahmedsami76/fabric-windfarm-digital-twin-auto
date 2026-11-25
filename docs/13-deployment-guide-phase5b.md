# Deployment guide, Phase 5b: the agent proposes, a person approves, the turbine follows

Phase 3 gave the operations agent eyes: it notices a gearbox that starts to run rough and tells an engineer in Teams. Phase 5a built the way back to the edge and proved it with a command sent by hand. Phase 5b joins the two. The agent's message now says what limiting the turbine would cost and what a gearbox costs, and proposes the action **Curtail turbine**. When the engineer approves it in Teams, the notebook of Phase 5a sends the command and the turbine is limited to 30 percent of its rated power for an hour.

**Status of this guide.** Written on 24 November 2026, and first run the same evening; [What was and was not tested](#what-was-and-was-not-tested) has what that run showed. In short: the rehearsal of step 3 works and is slow to start (two to three minutes); the script of step 4 is refused by Fabric, so **step 4 is done by hand for now**; step 5 produced a playbook with one rule; and step 6 was **reported as working**: the message arrived in Teams, it was approved, and WT-03 was curtailed. I saw the outputs of steps 3 to 5 and not the message, the approval or the turbine. [Phase 5c](14-deployment-guide-phase5c.md) adds the record of the command and shows it in the twin. What follows in this paragraph is how the guide was written. **Nothing in it had run against a tenant then.** Phase 5a was reported to me as working on the same evening ("WT-07 curtailed"); I have seen no output of that run. The simulator's side is measured: what the proposed curtailment does to a gearbox with a small fault, at five winds. The Fabric side is built from Microsoft's documentation as read on 24 November: how an action is added to an operations agent, the published form of an agent's definition, and the job that runs a notebook with parameters. The seven things that only a run can show are listed in [What was and was not tested](#what-was-and-was-not-tested), and the steps are ordered so that each of them fails alone and says where: first the table, then the notebook as a job without the agent, then the agent.

## Contents

- [What you get](#what-you-get)
- [Before you start](#before-you-start)
- [Step 1: The table the agent decides on](#step-1-the-table-the-agent-decides-on)
- [Step 2: Replace the notebook](#step-2-replace-the-notebook)
- [Step 3: Rehearse the action without the agent](#step-3-rehearse-the-action-without-the-agent)
- [Step 4: Give the agent its instructions and the action](#step-4-give-the-agent-its-instructions-and-the-action)
- [Step 5: Generate the playbook and start the agent](#step-5-generate-the-playbook-and-start-the-agent)
- [Step 6: Show it](#step-6-show-it)
- [Step 7: After the run](#step-7-after-the-run)
- [If something fails](#if-something-fails)
- [How it works](#how-it-works)
- [What was and was not tested](#what-was-and-was-not-tested)
- [Go back to Phase 3](#go-back-to-phase-3)

## What you get

| Item | Where | What it is |
|---|---|---|
| Table **GearboxDecisionLive** | KQL database `WindFarmEH` | One row per running turbine about every 20 seconds: its gearbox readings, and next to them what limiting it to 30 percent would cost per hour and per day, what a gearbox exchange costs, how long one takes to arrive, and how many days of warranty are left. Filled by an update policy as the telemetry arrives |
| Operations agent **WindFarmGearboxWatch**, changed | Fabric workspace | One rule on that table: gearbox vibration crosses above 4 mm/s. Its message begins with the cost of acting and of not acting, and proposes the action |
| Action **Curtail turbine** | On the agent | Runs the notebook `12_send_edge_command` with four values: `turbine`, `percent`, `duration`, `requested_by`. It can limit a turbine. It cannot stop one |
| Notebook **12_send_edge_command**, new version | Fabric workspace | Names no turbine by itself, and installs its two libraries without the `%pip` magic, which is switched off when a notebook runs as a job |
| `infra/09-remediation-agent.sh` | Repository | Gives the agent its instructions and the action through the Fabric API, shows how the agent is set up, rehearses the action, and puts a saved setup back |

```text
 Eventhouse                      Operations agent              Teams            Fabric            Edge
+---------------------+   every   +--------------------+       +---------+      +-------------+   +-----------+
| TurbineTelemetry    |  5 min    | rule: vibration    | msg   | cost    | yes  | notebook 12 |   | data flow |
|   | update policy   |---------->| crosses above 4    |------>| numbers |----->| as a job    |-->| control   |
|   v                 |           | action: Curtail    |       | approve |      | (Phase 5a)  |   | topic     |
| GearboxDecisionLive |           |   turbine          |       +---------+      +-------------+   | simulator |
+---------------------+           +--------------------+                                          +-----------+
        ^                                                                                               |
        +------------------------- telemetry: state CURTAILED, power 1,260 kW, oil temperature falling -+
```

**What the action can do.** One thing: limit the power of the one turbine it names, to a percentage, for a time that ends by itself. The command is not among the values a caller of the notebook can set, so it is always `curtail`. Nobody can turn an approval into a stop by typing into its values.

## Before you start

- **Phase 3 is deployed**: the operations agent `WindFarmGearboxWatch` exists, you created it, and the Teams app **Fabric Operations Agent** is installed (step 9 of the Phase 3 guide). An agent acts with the rights of the person who created it, and its messages go to that person unless you changed the recipient.
- **Phase 5a works**: a command sent with the notebook reached the turbine. `bash infra/08-create-command-path.sh --show` lists the eventstream, the endpoint and the data flow.
- **The edge VM is running** (`bash infra/vm.sh status`). It stops every day at 08:00 UTC, which is 02:00 in Houston.
- You are signed in on the workstation with `az login` **as the account that created the agent**. The Fabric API takes the calls of step 4 from a signed-in user only, not from a service principal or a managed identity.
- The twin of Phase 4 is not needed, and shows the whole story without a query if you have it open.

Time: about 30 minutes for steps 1 to 5. Step 6 takes 25 to 35 minutes of clock time, most of it waiting.

## Step 1: The table the agent decides on

**[Fabric]** Open a query window on the KQL database `WindFarmEH`, as for step 8 of the Phase 3 guide, and open `fabric/kql/06-remediation-readiness.kql` from the repository copy next to it.

1. Paste **Block 1** (from `.execute database script <|` to the line that ends in `"PropagateIngestionProperties": false}]'`) and run it. It creates the table, describes its columns for the agent, and sets the update policy that fills it.
2. Wait one minute. An update policy acts on telemetry that arrives after it was set, not on what is already there.
3. Paste **Block 2** and run it.

**Check.** One row for each turbine that is running, each with a `Timestamp` of the last minute:

| Column | What to expect |
|---|---|
| `GearboxVibration` | About 1.5 to 2.5 mm/s; WT-07 about 1 mm/s more |
| `ActivePower`, `PowerAfterCurtailKw` | The second is the first, capped at 1260 |
| `CurtailCostPerHourUsd` | 0 while the turbine delivers less than 1,260 kW. Above that, the difference at 38.50 USD per MWh: a turbine at 3,090 kW shows 70 |
| `CurtailCostPerDayUsd` | 24 times that |
| `WarrantyDaysLeft` | The days until 31 December 2026: 36 on 25 November (UTC) |

A turbine that is curtailed, stopped or idle has no row while it is so. That is intended: it keeps the agent from proposing a curtailment for a turbine that is already curtailed.

**Send me** the rows of Block 2. The KQL passed a syntax check here and has not run in an Eventhouse.

## Step 2: Replace the notebook

The notebook of Phase 5a changed in three ways that matter now, so the copy in the workspace has to be replaced.

- **It no longer uses `%pip`.** Fabric switches that magic off when a notebook runs outside an interactive session; the error is `%pip magic command is disabled`. Microsoft documents this for pipeline runs. Whether a run started by the operations agent counts the same I could not find, so the notebook does not depend on it: it installs its two libraries with pip as a plain command, and only when the session does not have them.
- **It names no turbine by itself.** `turbine` was `WT-07`. A run that passes no turbine would then curtail WT-07, whatever the agent meant. It is now empty, and such a run is refused before anything is sent.
- **A caller can set four of its values, and the command is not one of them.** When an action is added to the agent, Fabric lists every name of the notebook's first code cell as a parameter of the action; none can be left out, and each could then be set by the agent, or by whoever edits the values before approving. That showed on 24 November 2026, with eight names in the cell. The cell now holds `turbine`, `percent`, `duration` and `requested_by`. The command, `dry_run` and the rest stand in the second code cell, which runs after a caller's values are set and so cannot be overridden by them.

**[Fabric]** In the workspace:

1. On **12_send_edge_command**, select **…**, **Delete**.
2. **Import**, **Notebook**, **From this computer**, and choose `fabric/notebooks/12_send_edge_command.ipynb` from the repository copy.
3. Open it. In the first code cell set `turbine = "WT-07"`, in the second `dry_run = True`, and select **Run all**.

**Check.** The cell that starts with `# The command, checked` prints the command, and the last code cell prints `dry_run is True: nothing was sent.` Then set both values back (`turbine = ""`, `dry_run = False`) and let the notebook save. If you leave `WT-07` in, a run without a turbine curtails WT-07 again.

From here on this notebook belongs to the agent. To send commands by hand, for a test or a demo, use the notebook `13_command_center`: one line per command, the state of the turbines, and a check that each command took effect. It is described in [the Phase 5a guide](12-deployment-guide-phase5a.md#the-command-center-commands-by-hand-from-then-on).

The action of step 4 points to this notebook by its id. Do this step before step 4; if you ever import the notebook again, run step 4 again as well.

## Step 3: Rehearse the action without the agent

This runs the notebook the way the agent's action will: as a job, with the four values passed as text. It sends a real command, to one turbine, for two minutes.

**[Workstation]**

```bash
bash infra/09-remediation-agent.sh --rehearse WT-07
```

**Check.** The script prints each state of the job with the seconds since the request, and ends with `The job completed … seconds after the request.`

```text
==> Rehearsal: notebook 12_send_edge_command as a job, for WT-07
Started 12_send_edge_command as a job: curtail WT-07 to 30 percent for 2m. The limit ends by itself.
    … s  NotStarted
    … s  InProgress
    … s  Completed
```

Within a minute of `Completed`, WT-07 is `CURTAILED` (the ring in the twin turns blue; or the query at the end of the notebook), and two minutes later it runs again by itself.

On 24 November 2026 two runs took 196 and 137 seconds, of which 153 and 105 passed in `NotStarted`, before the notebook ran at all. That is the time Fabric needed to start a session for the job. Expect the turbine to follow an approval by two to three minutes until that is shortened.

**Send me** this output. The seconds are the first measurement of how long the action takes, which nobody knows yet. The step also decides points 2 and 3 of [the open list](#what-was-and-was-not-tested): that the notebook's values can be set from outside, and that it installs what it needs when it runs as a job.

If it ends as `Failed`, open the notebook's run (in the workspace: **Monitor**, or **Recent runs** on the notebook) and look for the first cell with an error. [If something fails](#if-something-fails) lists the three I expect.

## Step 4: Give the agent its instructions and the action

**On 24 November 2026 Fabric refused this command** with `400: UnknownError` and no reason, after the script had read and saved the agent's definition. Nothing is changed when that happens. Until the cause is found, **do the part headed [By hand](#by-hand)**, and skip the command.

**[Workstation]**

```bash
bash infra/09-remediation-agent.sh
```

It reads the agent's definition from the Fabric API, saves it unchanged under `fabric/operations-agent/saved/`, replaces the instructions with `fabric/operations-agent/phase5b-agent-setup.txt`, adds the action, and reads the result back. The data source, the recipient of the messages and anything else in the definition stay as they are. The agent is left **stopped**.

**Check.** The output ends like this (ids and time will differ):

```text
Saved the agent's definition as it was: fabric/operations-agent/saved/WindFarmGearboxWatch-20261125T021341Z.json
Wrote the Phase 5b instructions and the action. Reading the definition back:
Operations agent WindFarmGearboxWatch (…) in workspace WindFarmDigitalTwin
  Definition part: Configurations.json
  Running: no
  Instructions: 2810 characters. First rule: Alert me when the gearbox vibration of a turbine crosses above 4 mm/s.
  Data source …: KustoDatabase WindFarmEH
  Messages go to: …
  Action …: 'Curtail turbine' (FabricJobAction), runs SynapseNotebook 12_send_edge_command as RunNotebook. Parameters: turbine, percent, duration, requested_by
  Playbook in the definition: empty
Instructions and action are those of Phase 5b.
The agent was running and is now stopped.
```

`bash infra/09-remediation-agent.sh --show` prints the same description at any time and changes nothing. **Send me its output**, after this step and whichever way you did it: it is the agent as Fabric has it, which no screenshot shows as completely.

### By hand

Use this if the script ends with `The agent was not changed through the Fabric API`, or if you prefer to see the page. It is the route Microsoft's page describes. The names in bold are the page's own where I could read them; where a label differs on your screen, the values are what matters.

**[Fabric]** Open **WindFarmGearboxWatch**.

1. Select **Stop**.
2. On **Agent setup**, in **Agent instructions**, replace the whole text with the content of `fabric/operations-agent/phase5b-agent-setup.txt`. **Knowledge** stays the KQL database `WindFarmEH`.
3. Under **Actions**, select **Add action**, then **Fabric item**. Browse to the notebook `12_send_edge_command` and select it. If the page then asks for a function or a job, take the one that runs the notebook. A dialog **Add action** opens on its first page, **Action details**.
4. Enter the **Action name** `Curtail turbine` and the **Action description** from `fabric/operations-agent/phase5b-action.txt`.
5. Under **Parameters**, Fabric has listed the notebook's parameters by itself, each with the type `string`; names and types cannot be changed. There must be exactly four: `turbine`, `percent`, `duration`, `requested_by`. Enter the **Description** of each from that file; **Next** stays grey until every row has one.

   If the list shows eight rows, with `command`, `reason`, `dry_run` and `EVENTSTREAM` among them, the notebook in the workspace is the one from before this change. **Cancel**, do step 2 again, and come back.
6. Select **Next**, check the page **Review and create**, and create the action. Then select the save icon of the agent.

Then `bash infra/09-remediation-agent.sh --show` on the workstation: it says whether what the page saved is what this guide means, parameter by parameter.

## Step 5: Generate the playbook and start the agent

**[Fabric]** Open **WindFarmGearboxWatch**.

1. Look at **Agent setup**: the instructions begin with `*** Business Goals ***` and hold one operational rule, and **Actions** lists **Curtail turbine**.
2. Select **Generate playbook**, also when a playbook is shown: the one on the page may still be the one of Phase 3.
3. Read the playbook before you start the agent:

   | Rule | Property | Object | Condition | Action |
   |---|---|---|---|---|
   | 1 | GearboxVibration of `GearboxDecisionLive` | TurbineId | Crosses above 4 | Curtail turbine |

   - **No playbook generated**, with a request to confirm a data source: the instructions name something that is not a column. Every name in them is a column of `GearboxDecisionLive`, so the first thing to check is that Block 1 of step 1 ran in this database. Send me the sentence the page quotes.
   - A rule that says **Is above**: the agent would write every five minutes. It has to say **Crosses above**.
   - More than one rule, or a rule on `TurbineTelemetry`: the playbook is still the old one. Generate it again.
4. Select **Start**.

**Check.** **Stop** is active and **View activity** lists an evaluation every five minutes. With a healthy fleet no message arrives: in the simulator no healthy turbine came above 2.2 mm/s in this table at winds of 11 to 13 m/s, and WT-07, with its worn bearing, not above 3.3.

**Then save what Fabric now holds.** On the workstation:

```bash
bash infra/09-remediation-agent.sh --save
```

It changes nothing. It prints how the agent is set up and writes its definition, with the playbook the portal has just generated, to a file under `fabric/operations-agent/saved/`. **Send me that file and what the command printed.** The definition holds the rule and the action as Fabric writes them, which is published nowhere, and with it the script of step 4 can be corrected to write the same thing.

**Send me** also a picture of the playbook. I have not seen a generated one, neither in Phase 3 nor now, and how the rule names the action is the part I know least about.

## Step 6: Show it

**The wind first, and why it is not the wind of Phase 3.** The Phase 3 story, "the controller is silent and the agent notices", shows best at 7 to 9 m/s. A curtailment to 30 percent changes nothing there: at 8.5 m/s the turbine delivers about 1,050 kW, already below the limit of 1,260 kW. The proposal would cost nothing and relieve nothing. The action has something to act on from about 11 m/s, and the picture is clearest at 13:

| Wind | Before: vibration, oil, power | Curtailed to 30 percent | Cost of the limit |
|---|---|---|---|
| 8.5 m/s | 4.5 mm/s, 74 °C, 1,045 kW | 4.4 mm/s, 72 °C, 740 kW (the wind, not the limit) | 0 |
| 10 m/s | 4.8 mm/s, 77 °C, 1,770 kW | 4.6 mm/s, 73 °C, 1,150 kW | about 20 USD an hour |
| 11 m/s | 4.9 mm/s, 79 °C, 2,390 kW | 4.7 mm/s, 74 °C, 1,245 kW | about 44 USD an hour |
| 12 m/s | 5.0 mm/s, 81 °C, 3,090 kW | 4.7 mm/s, 74 °C, 1,260 kW | about 70 USD an hour |
| 13 m/s | 5.1 mm/s, 82 °C, 3,630 kW | 4.7 mm/s, 74 °C, 1,260 kW | about 91 USD an hour |

Measured in the simulator on WT-03 with a fault of severity 0.2 that was held, averages over five minutes, a quarter of an hour after each change. In this wind the turbine controller joins in: its warning `GBX-OIL-TEMP-HIGH` comes at 78 °C. It is a warning. The controller does nothing about it until 88 °C, where it derates the turbine to half. That gap is where a person with the numbers in front of them can do better than wait, and it is the story of this phase.

**[Workstation]** Set the wind. It takes about eight minutes to get there, and returns to the site's weather after the time given.

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh wind --mean 13 --duration 90m
```

Ten minutes later, start the fault. It ramps in over five minutes, lasts an hour, and ends by itself.

```bash
bash infra/vm.sh ssh bash ./edge/scripts/inject-anomaly.sh WT-03 gearbox_degradation 0.2 60m
```

What happens then. The minutes of the first four rows are from ten runs of the simulator at 12 and 13 m/s; those of the agent and of Fabric are not known, and are what I ask you to read off a clock.

| Minutes after the fault | What happens | Where to look |
|---|---|---|
| 3 to 4 | The vibration of WT-03 crosses 4.0 mm/s in `GearboxDecisionLive` | Block 3 of the KQL file. Twin: the halo and the nacelle of WT-03 turn amber, the ring stays green |
| 5 to 6 | The controller raises `GBX-OIL-TEMP-HIGH`: in all five runs at 13 m/s, in three of five at 12 | Twin: the halo turns red, the alarm is in the list. `ActiveAlarms()` in the KQL database |
| 4 to 9, plus the agent's own time | The agent's next look finds the crossing and writes | **View activity** of the agent, then Teams |
| on approval | The notebook runs as a job; the seconds are those of step 3 | The notebook's **Recent runs**; the control topic, as in step 3 of the Phase 5a guide |
| within a minute of the job | WT-03 is `CURTAILED` at 1,260 kW | Twin: the ring turns blue inside the red halo. Telemetry: `State`, `PowerSetpoint` |
| 4 to 9 after the curtailment | The oil temperature falls under 75 °C and the controller's warning clears by itself | Twin: the halo goes from red back to amber. The alarm leaves the list |
| from then on | Vibration stays between 4 and 5.5 mm/s, oil at 72 to 74 °C | Twin: blue ring, amber halo. The gearbox is relieved. It is not repaired |

**The message.** It should begin with the money and name the action, in the agent's own words. With the figures of a turbine near its rated power at 13 m/s:

- limiting WT-03 costs 90 to 110 USD an hour, 2,200 to 2,600 USD a day
- a gearbox exchange costs 385,000 USD and takes 140 days to arrive
- 36 days of warranty are left (on 25 November)
- then WT-03 with its vibration, oil temperature, bearing temperature and power
- the recommended action **Curtail turbine** with `turbine` WT-03, `percent` 30, `duration` 60m
- an inspection in the next low-wind period, procedure SOP-GBX-001

The figures are read from the newest row of WT-03 at that moment. The power moves with the wind, so the cost in your message will differ from this example; it should match `CurtailCostPerHourUsd` of that row.

**Approve it.** Microsoft's published page says the message offers **Yes** to approve and **No** to reject, shows the values the agent chose, and lets you change them before you approve. The current source of that page no longer describes the buttons, so take what your message shows. Changing `percent` to 50 before approving is a good moment in front of an audience: the person, not the agent, has the last word on the number.

**Then ask the data agent**: `Has a gearbox bearing been replaced on this site before, what did it cost and how long was the turbine down?` The history holds such a repair on WT-02. That answer comes from the data. It is deliberately not written into the operations agent's instructions.

The data agent is not in Teams. The message you approved came from the operations agent, which is a different item. Ask the data agent where Phases 3 and 4 put it: in the chat panel of the twin, or in Fabric, on the page of **WindFarmDataAgent**. Microsoft describes a way to bring a data agent into Teams, by publishing it to the Agent Store of Microsoft 365 Copilot; that needs Microsoft 365 Copilot licences and has not been tried in this demo.

**Send me:** a picture of the Teams message, with the values of the action visible; what the approval looks like; the notebook's run from **Recent runs** if it failed; and four times read off a clock: fault started, message arrived, approved, ring blue. If the halo turned red and back, those two times as well.

## Step 7: After the run

The fault ends an hour after it started and the curtailment an hour after the approval. To end both now:

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh resolve WT-03
```

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh release WT-03
```

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh wind --clear
```

If you do not need the agent between demos, select **Stop**: a running agent evaluates every five minutes and uses capacity for it.

One thing to know when you leave it running. A curtailed turbine has no rows in `GearboxDecisionLive`. When the hour ends and the fault is still there, the turbine returns to full power with its vibration already above 4 mm/s, and the rule, which waits for a crossing, may not speak again. Whether it does depends on how the agent treats the gap, which I do not know. Phase 5c records what the turbine was told and when the limit ended; a rule that comes back to a case that is still open is not built, and [its guide says so](14-deployment-guide-phase5c.md#what-this-phase-leaves-open).

## If something fails

| Symptom | Where it stopped | Do |
|---|---|---|
| Step 1: Block 1 answers with an error | The KQL database | Send me the error. The block is one script; nothing is half done when it fails on the first command |
| Step 1: Block 2 returns no rows after two minutes | The update policy does not fire, or no telemetry arrives | `TurbineTelemetry \| where Timestamp > ago(2m) \| count` first: 0 means the VM or the simulator is stopped. Otherwise `.show table GearboxDecisionLive policy update` and send me the result |
| Step 3: `No notebook named 12_send_edge_command`, or `2 notebooks are named …` | The workspace | Import it (step 2), or delete the copy that is not in use |
| Step 3: the job ends as `Failed`, and the run shows `'' is not a turbine` | The values did not reach the notebook | The first code cell lost its mark as the parameter cell on import. In the notebook: **…** on that cell, **Toggle parameter cell**. Then the rehearsal again. Tell me, so the file can be corrected |
| Step 3: `Failed`, the run shows `pip could not install …` | The install inside a job | The message carries pip's reason. Send it to me. The way around is an Environment with `azure-eventhub` and `websocket-client` attached to the notebook; the notebook installs nothing when it finds them |
| Step 3: `Failed`, the run shows an error in the cell `# Where to write` | The Fabric API, called from a job | Send me the message. This call worked in the interactive run of 24 November |
| Step 3 or 4: `The Fabric API answered 401` or `403` | The sign-in | `az login` as the account that created the agent and owns the workspace. A service principal is refused by design |
| Step 4: `The agent was not changed through the Fabric API`, with Fabric's words above it | The update of the definition. Seen on 24 November 2026 with `400: UnknownError` | Do [By hand](#by-hand). Send me Fabric's words. The saved file under `fabric/operations-agent/saved/` is the agent as it was; nothing was changed |
| `--restore`: `The definition is invalid: rule '…' monitors class '…', but 'playbook.ontologyDefinitions' defines class '…' 3 times` | Fabric checks a definition when it is written, and a playbook its own portal generated does not pass | Nothing was changed. Go back by hand: [Go back to Phase 3](#go-back-to-phase-3) |
| Step 4: `The definition read back differs from what was written` | Fabric took the change and stores it differently | Send me the lines under `Differs from Phase 5b`. Then look at the agent in the portal |
| Step 4: `The definition of the agent has no part with a configuration` | The definition has a form this tool does not know | Nothing was written. Send me the names of the parts it prints, and do [By hand](#by-hand) |
| Step 5: **No playbook generated** | The agent cannot tie a sentence to a column | Step 1 ran in another database, or not at all. Otherwise send me the sentence the page quotes |
| Step 6: no message 15 minutes after the fault | The agent | **View activity**: does it evaluate every five minutes? Block 3 of the KQL file: did a row pass 4.0 after a row at or below it? If both are so, send me the activity entry of that time |
| Step 6: the message proposes no action, or the wrong values | The agent's reading of its instructions | Send me the message. Instruction 6 names the columns the values come from |
| Step 6: approved, and the turbine does not change | The job, or the path of Phase 5a | **Recent runs** of the notebook: a failed run names the cell. A successful run and no change: the table at the end of the Phase 5a guide, hop by hop |
| Step 6: the cost in the message is 0 | The wind | The turbine delivers less than 1,260 kW. Set the wind as in step 6 and wait the eight minutes |

## How it works

**One table for the rule and for the figures.** An operations agent reads tables, not functions, and reports what is in the columns of the table it watches; Phase 3 found that an instruction about something that is not a column stops the playbook. So the cost of the decision is written next to the reading that triggers it, row by row, as the telemetry arrives. The agent computes nothing. It reads five numbers and repeats them.

**Where each figure comes from.** The KQL is generated from the reference data, and a test fails when the two differ.

| Figure | Value | Source |
|---|---|---|
| Rated power, and the limit at 30 percent | 4,200 kW, 1,260 kW | `turbines.csv` |
| Price of the energy not delivered | 38.50 USD per MWh | `contracts.csv`, the power purchase agreement CT-PPA-001 |
| Gearbox exchange unit | 385,000 USD, 140 days | `spare_parts.csv`, SP-GBX-UNIT |
| End of the drivetrain warranty | 31 December 2026 | `components.csv`, the same for all twelve gearboxes |

The cost of the limit is the power above 1,260 kW at that price, for the hour, and 24 times that for the day "if the wind stayed as it is". It is a statement about now, not a forecast. After 31 December 2026 `WarrantyDaysLeft` is 0 or negative, and the agent is told to say that the warranty has ended.

**What the comparison is and is not.** The two sides of the message are not alike: the cost of limiting is certain and small, the cost of a failure is large and uncertain, and nothing in the data says how likely a rough-running gearbox is to fail in the next weeks. The message puts the two next to each other and leaves the weighing to the engineer. The warranty date decides who pays for a failure. It does not decide whether to risk one.

**Thirty percent, for sixty minutes.** 30 percent is the limit the turbine controller applies itself when the vibration reaches 8 mm/s; the agent proposes the same step earlier, while the controller only warns. Sixty minutes is long enough to see the effect and short enough that a forgotten approval does not hold a turbine down for a day. Both travel as values of the action, and the person who approves can change them.

**The action cannot stop a turbine.** Fabric makes every name of the notebook's parameter cell a parameter of the action, so that cell holds four names and the command is not one of them. It is set in the next cell, after a caller's values, and a caller that passes `command` anyway changes nothing; a test does exactly that. The notebook refuses a curtailment without a turbine, without an end, with a percentage outside 0 to 100, and for more than one turbine: the word `all`, which the command center accepts, is refused here.

**Whose rights.** An operations agent acts with the rights of the person who created it, and so does the notebook it starts. The person who approves in Teams needs write permission on the agent, and is not the one the notebook runs as. `requestedBy` in the command therefore says `operations agent WindFarmGearboxWatch, approved in Teams`, a text the agent passes. Who approved is known to Teams and to the agent's activity, not to the command. Phase 5c records the command at the edge with this text; it cannot record the approver, because Fabric does not hand that name to the notebook.

**Why the agent is changed through the API.** Microsoft publishes the form of an agent's definition, and the API to read and write it, for signed-in users. The script changes two things in that definition, the instructions and one action, and writes everything else back as it read it. It saves the definition first. The gain over typing into the page is that parameter names cannot be mistyped and that `--show` can say, in a line, how the agent is really set up. The playbook is still generated in the portal. The published form calls it "reserved for future expansion", and the script writes it empty and leaves the agent stopped, so that no rule made from the Phase 3 instructions runs under the new ones. That description turned out to be incomplete on the first evening: what Fabric returns for an agent made in the portal holds the playbook itself, with its rules and the objects they watch, and Fabric checks it when it is written back. Whether the empty playbook is what Fabric refused in step 4 is not known yet.

**Why a rehearsal.** The agent starts the notebook as a job of type `RunNotebook`, which is what the definition names. The Job Scheduler API starts the same job from the workstation. So the notebook, its install and its values can be proven before the agent exists in the picture, and a failure in step 6 can then be only the agent's.

**A turbine that is curtailed is not watched.** The table holds running and derated turbines only. Without that, the agent would find the vibration of a curtailed turbine still above 4 mm/s and propose the curtailment again.

## What was and was not tested

**Run, without Fabric and Azure**

| What | How | Result |
|---|---|---|
| What the proposed curtailment does | The simulator with a fault of severity 0.2 held on WT-03, then the command the action sends, at 8.5, 10, 11, 12 and 13 m/s. From 10 m/s on: vibration falls by more than 0.1 mm/s, the oil temperature by more than 3 °C and back under the controller's 78 °C, the vibration stays above 4.0, and at 13 m/s the controller's warning, which was up, clears. At 8.5 m/s the turbine is already under the limit and the cost is 0 | Pass. The table in step 6 is from these runs |
| The timetable of step 6 | Ten runs at 12 and 13 m/s with the fault of the guide (60 minutes, ramping in), 20-second averages as the update policy makes them, approval ten minutes after the fault | The minutes in the table. In nine runs at 11 to 13 m/s no healthy turbine crossed 4.0 mm/s |
| The figures | The KQL constants against `data/reference`, and the cost formula in Python against the same numbers | Pass |
| The instructions | Every quoted name is a column of the table; the rule says "crosses above"; the values of the action are named as the action names them | Pass |
| The notebook | Its cells executed against stand-ins with the four values as text, as a job passes them; a run without a turbine is refused and sends nothing; no cell uses a magic; the install on demand, including the case where pip installs into the user's folder | Pass |
| `tools/operations_agent.py` | 18 tests against a stand-in that speaks HTTP like the Fabric API as documented: lists with continuation, the definition as a long-running operation, the update, a notebook job. Saves before it writes; keeps the data source, the recipient and other actions; a second run changes nothing; a refusal changes nothing and is reported in Fabric's words; a definition it cannot read is not written over; `--restore` puts the saved one back; the token goes to the Fabric API only and is never printed | Pass. A stand-in is my reading of the documentation |
| `infra/09-remediation-agent.sh` | 10 scenarios for its options and sign-in checks, and one run from end to end against the stand-in | Pass |
| The KQL | A syntax check with the Kusto language library | No diagnostics. Not run in an Eventhouse |

**Read in Microsoft's documentation on 24 November 2026, not run**

- An action is added in **Agent setup** with **Add action**; a **Fabric item** action can run a notebook; it has an **Action name**, an **Action description** and optional parameters that the agent passes when it invokes the action.
- The agent uses the delegated identity of its creator, and an approved action runs with the creator's permissions.
- The definition of an operations agent: `configuration` with `instructions`, `dataSources`, `actions` and `messageDestination`; `playbook`; `shouldRun`. An action of kind `FabricJobAction` has a `connection` with `jobArtifactId`, `jobWorkspaceId`, `itemType` and `jobType`, and parameters with a name and a description. The page gives `Notebook` and `RunNotebook` as examples of the last two; for a notebook the portal writes `SynapseNotebook` (seen on 24 November). `goals` was removed in June 2026; goals belong in `instructions`.
- `getDefinition` for an operations agent is a long-running call for signed-in users. Its page names the part `OperationsAgentV1.json` where the definition article says `Configurations.json`; the tool finds the part by its content.
- A notebook job is started with `…/items/{id}/jobs/instances?jobType=RunNotebook` and `executionData.parameters`, each value with a type.
- `%pip` is switched off by default in pipeline runs of a notebook.

**Seen in the first run, 24 November 2026**

| Step | What was seen |
|---|---|
| 3 | The rehearsal's output, twice: `Completed` after 196 and after 137 seconds, with 153 and 105 seconds in `NotStarted`. So the job call from the workstation works and the notebook finishes as a job. Not seen: whether WT-07 followed, and whether the notebook was already the one of step 2 |
| 4 | The script listed the agents and the notebooks, read the agent's definition and saved it. Fabric refused the update: `400: UnknownError. An error occurred while processing the operation`. Cause open |
| 4, by hand, done | `--show` at 22:38: the instructions are those of Phase 5b word for word; the action `Curtail turbine` runs `SynapseNotebook 12_send_edge_command` as `RunNotebook` with the parameters `turbine`, `percent`, `duration`, `requested_by`; the agent is stopped and its playbook empty; the definition's part is named `Configurations.json`; the action and the data source are kept under their ids |
| 4, by hand | A picture of the dialog **Add action**, page **Action details**: **Action name**, **Action description**, and under **Parameters** eight rows that Fabric had read from the notebook's first code cell, `command` among them, each of type `string` and each asking for a description. The notebook was changed for it the same hour: four names in that cell |
| 5 | `--save` at 22:45: the agent is running, and its definition now holds a playbook of 15,762 characters with one rule (`playbook.RuleDefinitions: 1 entries`) and 14 entries under `playbook.OntologyDefinitions`. Not seen yet: the rule's own text |
| 6 | **Reported**, 24 November, 23:14 and after: the Teams message of the operations agent arrived; it was approved; WT-03 was curtailed ("Approved, WT-03 curtailed"). Seen: the data agent's answer to the guide's question, with work order `WO-2025-0119`, 121,430 USD and 215.2 hours. Not seen: the message and its values, the approval, the notebook's run, the turbine, and any time on a clock |
| `--restore` | Tried with the file just saved, to see whether an unchanged definition is accepted. Refused, with a reason: `rule 'Rule Gearbox Vibration Early Warning' monitors class 'TurbineRunSample', but 'playbook.ontologyDefinitions' defines class 'TurbineRunSample' 3 times`. So the API does take and check updates, and the definition holds the playbook |

**Unproven: what your run decides**

1. **The update policy on the tenant.** That `GearboxDecisionLive` fills as written. Step 1.
2. **The values of a job reach the notebook.** That the first code cell is taken as the parameter cell after import. Step 3.
3. **pip as a plain command inside a job.** Step 3.
4. **The update of the agent's definition.** That Fabric accepts it for an agent made in the portal, and what the page shows afterwards. Step 4, with the way by hand next to it. Refused on the first evening; one cause is known and corrected (the item type of a notebook is `SynapseNotebook`, not `Notebook`), and whether it was the only one is not.
5. **The playbook.** That one rule on `GearboxDecisionLive` comes out, and that the rule or the message carries the action. Step 5.
6. **The agent's values.** That it passes the turbine of the row, 30, `60m` and the text for `requested_by`, and that the message leads with the cost. A language model writes the message; the instructions ask, they cannot force. Step 6.
7. **The times.** How long the job takes, how long the agent takes after its look, and whether the red halo clears in the deployment as in the simulator. Steps 3 and 6.

After the first run, items 1, 2, 3, 5 and 6 count as reported with step 6: a limit that reached WT-03 through the agent needs the table, the values, the install and the playbook to have worked. None of them was seen by itself. Item 4 stands as it is, and item 7 has one number, the job's start.

Not looked at in this phase: who approved, and a second proposal when a curtailment ends with the fault still there (step 7); neither is built in Phase 5c either. Since the consolidation of 25 November `bash infra/99-cleanup.sh --fabric` removes the operations agent; this table goes with the Eventhouse.

## Go back to Phase 3

**[Fabric]** By hand, which is the way that is known to work: open **WindFarmGearboxWatch**, select **Stop**, replace the instructions with the content of `fabric/operations-agent/agent-setup.txt`, remove the action **Curtail turbine**, save, select **Generate playbook**, compare the rules with the three of the Phase 3 guide, and select **Start**.

`bash infra/09-remediation-agent.sh --restore FILE` writes a saved definition back in one step, when Fabric accepts it. On 24 November 2026 it did not accept the definition it had returned a minute earlier: the playbook the portal had generated in Phase 3 defines one object three times, once for each rule, and Fabric's check on the way in wants it once. The command says so and changes nothing.

To remove the table, run the two commented lines at the end of `fabric/kql/06-remediation-readiness.kql` without their `//`. The notebook can stay: it is the one of Phase 5a with two improvements.
