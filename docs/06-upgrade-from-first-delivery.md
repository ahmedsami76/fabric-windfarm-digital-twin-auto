# Upgrade a deployment of the first delivery

Follow this document if you deployed Phase 1 from the first version of this repository and it is still running. Nothing in Azure is recreated: the VM, the cluster, Azure IoT Operations, the eventstream, the Eventhouse and the Lakehouse stay as they are. You replace the repository, redeploy the simulator, rerun one KQL script and load the new data.

Allow 45 minutes. If you start from nothing, follow [01-deployment-guide-phase1.md](01-deployment-guide-phase1.md) instead.

> These steps were tested without Azure and Fabric, not on a live deployment. Each step ends with a check; if a check fails, stop there and see [troubleshooting.md](troubleshooting.md).

## What changes

| Area | First delivery | After the upgrade |
|---|---|---|
| Working with the VM | `ssh azureuser@…` and `scp` by hand; SSH lost when just-in-time access took over | `bash infra/vm.sh ssh` and `bash infra/vm.sh push`, which open access themselves |
| Simulator | 1.0.0: wind drifts between random levels; every start draws new turbines | 1.1.0: the wind follows the site's weather, with seasons and a daily cycle; the turbines keep their character; WT-05, WT-07 and WT-09 carry a standing condition; alarms are cleared when the simulator stops; the broker's certificate is read at every connect |
| Eventhouse | `ActiveAlarms()` shows an alarm for ever when the simulator stopped while it was raised | `ActiveAlarms()` ignores alarms from before the simulator's latest start |
| Reference data | 12 tables, with four work orders in `ref_maintenance_history` | 13 tables: contracts, people, warranty dates and 40 alarm codes added; `ref_maintenance_history` removed |
| History | None | 12 `ops_` tables with two years of operating history, a forecast and a budget |
| Questions | None | 43 questions with reference queries |

The tables of the Eventhouse do not change, and the live data you have collected stays.

## Step 1: Replace the repository on the workstation

**[Workstation]** In Cloud Shell, upload the new `fabric-windfarm-digital-twin.zip` with **Manage files**, **Upload**. If an archive of the same name is still there, delete it first (`rm -f ~/fabric-windfarm-digital-twin.zip`).

```bash
cd ~ &&
mv fabric-windfarm-digital-twin fabric-windfarm-digital-twin-v1 &&
python3 -m zipfile -e fabric-windfarm-digital-twin.zip . &&
cd fabric-windfarm-digital-twin &&
cp ../fabric-windfarm-digital-twin-v1/config/demo.env config/demo.env
```

The lines are chained with `&&`, so that a line that fails stops the rest.

The last line carries your settings over. If the old folder is gone (a Cloud Shell without storage loses its files), take the settings from the VM instead; the address of the VM is on its **Overview** page in the Azure portal:

```bash
VM_IP="the public address of the VM"
scp "azureuser@${VM_IP}:fabric-windfarm-digital-twin/config/demo.env" config/demo.env
```

Then set the simulator version in `config/demo.env`:

```bash
sed -i 's/^SIM_IMAGE=.*/SIM_IMAGE="windfarm-simulator:1.1.0"/' config/demo.env && grep SIM_IMAGE config/demo.env
```

Also unpack the new archive on the computer where your browser runs: you import the notebooks and paste one KQL script from there.

**Check.**

```bash
bash infra/vm.sh status
```

It shows the power state, the address, the daily shutdown and whether SSH is open to you. Two things to act on:

- **Power state is not "VM running":** run `bash infra/vm.sh start` and wait 5 minutes.
- **Daily shutdown at 02:00 UTC:** that was the default of the first delivery, and it is 20:00 in Houston. Move it to a time when you sleep, for example `bash infra/vm.sh shutdown 0800`, and set `VM_AUTO_SHUTDOWN_UTC="0800"` in `config/demo.env`.

## Step 2: Copy the repository to the VM

**[Workstation]**

```bash
bash infra/vm.sh push
```

If port 22 is closed, the command asks for just-in-time access, or moves the SSH rule to your address, and then copies. It replaces the repository's folders on the VM, including `config/demo.env`, and gives the scripts their execute permission.

**Check.**

```bash
bash infra/vm.sh ssh grep SIM_IMAGE config/demo.env
```

It prints `SIM_IMAGE="windfarm-simulator:1.1.0"`.

## Step 3: Redeploy the simulator

**[Workstation, on the VM]** Let a running fault finish first, or end it:

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh resolve all
```

Then build and start version 1.1.0. It takes a few minutes; live data pauses while the simulator restarts.

```bash
bash infra/vm.sh ssh bash ./edge/scripts/05-deploy-simulator.sh
```

**Check.**

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh status
```

The first two lines show `simulator 1.1.0` and `wind model climate`, and the last line names three standing conditions: `WT-05 yaw_offset, WT-07 gearbox_wear, WT-09 blade_erosion`.

In Fabric, run validation query 1 (in `fabric/kql/90-validation-queries.kql`): `Latest` is within the last minute.

## Step 4: Update the Eventhouse function

**[Fabric]** Open a query window on the KQL database `WindFarmEH`. Paste the whole content of the new `fabric/kql/02-update-policies.kql`, place the cursor inside the block and select **Run**. Every row shows `Completed`. The script replaces the functions and leaves the tables and their data alone.

**Check.**

```kusto
ActiveAlarms()
```

It returns no rows, unless a fault is running. Alarms that were left "active" by an earlier stop of the simulator are gone.

## Step 5: Upload the new reference data

**[Workstation, on the VM]**

```bash
bash infra/vm.sh ssh bash ./edge/scripts/07-sync-reference-data.sh
```

**Check [Fabric].** `Files/reference` in the Lakehouse now also holds `contracts.csv` and `technicians.csv`. The file `maintenance_history.csv` of the first delivery is still there and no longer used; delete it in the Lakehouse.

## Step 6: Replace and run the notebooks

**[Fabric]**

1. In the workspace, delete the notebook `01_load_reference_data` of the first delivery.
2. Select **Import**, **Notebook**, **From this computer** and upload the four files of `fabric/notebooks/`.
3. Open each notebook once, add the Lakehouse `WindFarmLH` in the explorer pane and make it the default Lakehouse.
4. Run them in order, each with **Run all**:

   | Notebook | Takes | Check |
   |---|---|---|
   | `01_load_reference_data` | 2 minutes | The last cell lists 13 tables, among them 40 alarm codes, 11 people and 4 contracts. The table `ref_maintenance_history` is removed. |
   | `02_generate_history` | 2 to 4 minutes | Capacity factor 33 to 37 percent, time-based availability 96.5 to 98 percent; a borescope inspection is planned for WT-07 |
   | `03_refresh_forecast` | 1 minute | The coming 48 hours of forecast. Then select **Run**, **Schedule** and set it to once a day. |
   | `04_question_bank` | 2 minutes | Question PE-01 shows WT-05 and WT-09 at the bottom; RE-05 shows WT-07 at the top |

Steps 7.5 to 7.9 of the deployment guide describe the notebooks in more detail.

## Step 7: See that live and history agree

**[Fabric]** In the KQL database, run question OP-08 from `fabric/kql/92-question-bank-live.kql`. It compares each gearbox with the fleet over the last 15 minutes. WT-07 is at or near the top for vibration, as it is in question RE-05 of the notebook over the last 30 days of history. If the wind is low, set it first:

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh wind --mean 11 --duration 60m
```

## What you will notice afterwards

- **The wind has weather.** It follows the site's climate: stronger at night and in spring, fronts that pass, calm days. Before a demo, hold it with `simctl.sh wind --mean 11`, as before.
- **The demo fault is a little faster.** WT-07 starts from a worn gearbox, so the first alarm comes about 2 minutes after the injection and the derate after about 3. The runbook has the new timeline.
- **Rated power.** In strong wind the turbines now reach their full 4,200 kW. In version 1.0.0 the thin air at the site's altitude kept them a few percent below it, which was an error of the model.
- **Old live data stays.** Telemetry from before the upgrade was produced by version 1.0.0, with different turbine characteristics. Comparisons of "now" with "the last weeks" in the Eventhouse are clean from the day of the upgrade. To start from empty tables instead, see `fabric/kql/99-reset-demo-data.kql`.

## Going back

The first delivery is still in `~/fabric-windfarm-digital-twin-v1`. To return to it: go to that folder, copy it to the VM (`scp -r`, as its guide describes), set `SIM_IMAGE` back and run its `edge/scripts/05-deploy-simulator.sh` on the VM. The new Lakehouse tables do no harm to the first delivery.
