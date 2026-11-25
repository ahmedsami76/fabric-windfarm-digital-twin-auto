# Troubleshooting

Ordered along the data path, from the VM to the Lakehouse. Start at the first section whose symptom you see.

Commands in this document are typed on the workstation unless a line says "on the VM". To run a command on the VM, put `bash infra/vm.sh ssh` in front of it, or open a shell there with `bash infra/vm.sh ssh`.

## Quick diagnosis: where does the data stop?

| Check | Where | Command or place | Healthy result |
|---|---|---|---|
| 1. Simulator runs | Edge VM | `bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh status` | 12 turbines listed |
| 2. Messages reach the broker | Edge VM | `bash infra/vm.sh ssh bash ./edge/scripts/mqtt-peek.sh --count 20` | 20 JSON messages |
| 3. Data flow is healthy | Edge VM | `kubectl get dataflows.connectivity.iotoperations.azure.com,dataflowendpoints.connectivity.iotoperations.azure.com -n azure-iot-operations` | `windfarm-to-fabric` and `fabric-eventstream` listed |
| 4. Events reach Fabric | Fabric | Eventstream, data preview | Events with `messageType`, `data` and the other envelope fields |
| 5. Raw rows land | Fabric | Validation query 1 | Six message types, recent |
| 6. Typed rows land | Fabric | Validation queries 2 and 3 | 12 turbines |
| 7. OneLake copy exists | Fabric | Preview a shortcut table in the Lakehouse | Rows, at most about 10 minutes old |

## Any step

### `Permission denied` when you start a script

```text
bash: ./infra/vm.sh: Permission denied
bash: ./edge/scripts/inject-anomaly.sh: Permission denied
```

The command started the script file directly, without `bash` in front, and the file has no execute permission. Files lose it when an archive is unpacked on Windows, when it is unpacked with `python3 -m zipfile`, or when files are copied or merged one by one. `sudo` does not help: the permission belongs to the file, not to the user.

Start the script through `bash`, which needs no permission on the file:

```bash
bash infra/vm.sh status
```

Every command in these guides, and every hint a script prints, has this form. No script of the repository starts another one in a way that needs the permission, and `bash tools/check-scripts.sh` fails when a guide or a hint goes back to the direct form. This obstacle came up three times during the validated deployments, each time after an update archive was merged into an existing copy.

### A script says it runs on the edge VM, or on the workstation

```text
ERROR: This script runs on the edge VM (vm-windfarm-edge), and this machine is 'cc-1a2b3c'.
ERROR: This script runs on your workstation or in Azure Cloud Shell, not on the edge VM.
```

Each script checks where it is. The scripts of `infra/` create Azure resources as you and belong on the workstation. The scripts of `edge/scripts/` work on the cluster and belong on the VM; from the workstation, start them as `bash infra/vm.sh ssh bash ./edge/scripts/…`. The check compares the machine's host name with `VM_NAME`. To override it on purpose, set `ALLOW_ANY_HOST=1` for an edge script or `ALLOW_NON_USER_LOGIN=1` for a workstation script.

### The workstation lost its copy of the repository or of `config/demo.env`

Azure Cloud Shell keeps files only with a mounted storage account, and a new workstation has none of them. Unpack the archive again, sign in with `az login`, and rebuild the settings from what is deployed:

```bash
bash infra/rebuild-env.sh &&
bash infra/vm.sh reset-key &&
bash infra/vm.sh status
```

The first line reads resource group `rg-windfarm-edge`; give another name as an argument. The second installs this workstation's SSH key on the VM and creates one if there is none. The lines are chained with `&&`: when one stops, the next ones do not run on half a result.

`rebuild-env.sh` changes nothing in Azure. It lists the settings it could not find; the Custom Locations object ID is among them when the sign-in may not read Microsoft Entra ID. The script has scenario tests against stand-in commands and has not run against Azure yet.

### `CUSTOM_LOCATIONS_OID is empty`, or another setting is missing, on the VM

The VM has an older copy of `config/demo.env` than the workstation. Send it again: `bash infra/vm.sh push-env`.

## Edge VM

### Step 1: no VM size is offered, or `SkuNotAvailable`

```text
ERROR: None of these sizes is offered to your subscription in southcentralus: Standard_D8s_v5 Standard_D8s_v6 …
```

Step 1 tries every size in `VM_SIZE`, skips the ones that Azure lists as restricted for your subscription, and moves to the next one when Azure refuses a size at creation (`SkuNotAvailable`). This message means none of them worked. Nothing is wrong with the deployment.

1. List the 8-vCPU D-series sizes of the region. Sizes with `None` in the restrictions column are offered; a temporary capacity shortage does not show here.

   ```bash
   source config/demo.env &&
   az vm list-skus --location "$LOCATION" --resource-type virtualMachines --size Standard_D8 --output table
   ```

2. Put an x86 size with 8 vCPUs and 32 GB that the list shows as offered first in `VM_SIZE` in `config/demo.env`, and run the script again. A rerun reuses the resource group and the network resources of the failed attempt. Avoid Arm sizes (a `p` in the name, as in `Standard_D8ps_v6`).
3. If the script then reports `QuotaExceeded`, the size belongs to a VM family with no vCPU quota in your subscription. Pick a size from another family or request quota.
4. To change region instead, delete the resource group first (`az group delete --name "$RESOURCE_GROUP" --yes`), set `LOCATION` to another supported region and run the script again.

The first run of this guide was offered no v4 or v5 sizes in `southcentralus` and used `Standard_D8s_v7`. That size has NVMe disks only; Azure chose the disk controller by itself and Ubuntu 24.04 worked without a change.

### Step 1: the Custom Locations object ID is not printed

Run the lookup by hand to see the reason:

```bash
az ad sp show --id bc313c14-388c-4e7d-a58e-70017303ee3b --query id --output tsv
```

| Result | Cause | Fix |
|---|---|---|
| A GUID | The lookup works now; the first attempt was too early | Put the GUID in `config/demo.env` as `CUSTOM_LOCATIONS_OID` |
| "does not exist" or "not found" | The `Microsoft.ExtendedLocation` provider is still registering, so the service principal is not in the tenant yet | Wait until `az provider show --namespace Microsoft.ExtendedLocation --query registrationState --output tsv` prints `Registered`, then run the lookup again |
| "Insufficient privileges" | The CLI session may not read service principals in Microsoft Entra ID. Typical causes: the automatic sign-in of Azure Cloud Shell, a service principal or managed identity sign-in, or an account with limited directory rights (for example a guest). | Try in this order. (1) In Cloud Shell, sign in interactively with `az login --use-device-code`, then run the lookup again. (2) Run the lookup on any machine where you can sign in through a browser with `az login --tenant <tenant-id>`; you only need the GUID it prints. (3) Read it in the Azure portal: Microsoft Entra ID, Enterprise applications, set the application type filter to "Microsoft Applications", search for the application ID `bc313c14-388c-4e7d-a58e-70017303ee3b` or the name "Custom Locations RP", copy **Object ID**. (4) Ask an administrator of the tenant to run the lookup and send you the GUID; it is not a secret. |

Do not change the GUID in the command; it is the same in every tenant. The value you need is the object ID it returns, which differs per tenant.

### SSH does not connect

Use `bash infra/vm.sh ssh` instead of `ssh`. It signs in as the right user, and when port 22 is closed it opens access the way your subscription allows before it connects. If it still fails, this shows the state:

```bash
bash infra/vm.sh status
```

**`Connection timed out`** has three usual causes.

- **Just-in-time access controls port 22.** In subscriptions that an organisation governs, Microsoft Defender for Cloud takes over the management ports of a new VM within hours: the rule that step 1 created disappears, and port 22 opens only on request, to one address, for a few hours. This happened on the first run of this guide, in a Microsoft-managed demo subscription: SSH worked for steps 2 and 3 and timed out two hours later. `bash infra/vm.sh ssh` and `push` ask for access by themselves; `bash infra/vm.sh jit 3` asks without connecting. If the request is refused, ask for fewer hours (`bash infra/vm.sh jit 1`), or request access in the Azure portal: the VM, **Connect**, **Request access**. Do not recreate the SSH rule by hand; it is removed again.
- **Power state is `VM deallocated`.** The daily shutdown stopped the VM. The time in `VM_AUTO_SHUTDOWN_UTC` is UTC, so `0200` is 20:00 in Houston. Start it with `bash infra/vm.sh start`; the address stays the same. To move the shutdown: `bash infra/vm.sh shutdown 0800` (or `off`).
- **Port 22 is open to a different address from the one you are on.** Cloud Shell can come from a new address in each session, and home and office connections change too. `bash infra/vm.sh ssh` corrects this.

**`Permission denied (publickey)`** has two causes.

- **The wrong user name.** The VM's administrator is `azureuser` (`VM_ADMIN`), not your own name. `bash infra/vm.sh ssh` uses it.
- **The key is gone.** Step 1 created the key in `~/.ssh` on the workstation. A Cloud Shell without a storage account loses it with the session, and another machine never had it. Install the key of the machine you are on:

  ```bash
  bash infra/vm.sh reset-key
  ```

**No SSH at all.** Where a policy forbids inbound SSH altogether, work through the VM agent:

```bash
bash infra/vm.sh run kubectl get pods -n azure-iot-operations
bash infra/vm.sh run bash ./edge/scripts/05-deploy-simulator.sh
bash infra/vm.sh run bash ./edge/scripts/simctl.sh status
bash infra/vm.sh run bash ./edge/scripts/mqtt-peek.sh --count 20
```

`run` is not interactive, takes at least 20 seconds, returns only the last 4,096 bytes of output and runs one command at a time. `bash infra/vm.sh push` needs SSH; without it, put the repository on GitHub and clone it on the VM with `bash infra/vm.sh run`, or connect through Azure Bastion. `bash infra/vm.sh nsg-log` shows who changed the firewall rules and which are in force.

After a start, K3s and everything on it come up by themselves. Allow about 5 minutes before the cluster shows as Connected. If a workstation step was running when the VM stopped, run that step again.

### Step 3: sign-in fails on the VM

| Message | Cause | Fix |
|---|---|---|
| Device-code sign-in is blocked, or "Your device is required to be managed" | Conditional Access in your tenant | Switch to `identity` mode: set `AZ_LOGIN_MODE="identity"` in `config/demo.env` on the VM, assign the two roles with the commands below, then run step 3 again |
| `az login --identity` fails | The VM has no managed identity, or the role assignments have not propagated | Check `az vm identity show`; wait 5 minutes; run step 3 again |
| Authorization error from `az connectedk8s connect` | The identity lacks the "Kubernetes Cluster - Azure Arc Onboarding" role on the resource group | Assign it (step 1 does this in `identity` mode) |

Commands to assign the roles for `identity` mode (workstation):

```bash
source config/demo.env &&
PRINCIPAL_ID=$(az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --query identity.principalId --output tsv) &&
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Kubernetes Cluster - Azure Arc Onboarding" \
  --scope "$(az group show --name "$RESOURCE_GROUP" --query id --output tsv)" &&
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Reader" --scope "/subscriptions/$SUBSCRIPTION_ID"
```

### Step 3: custom locations are not enabled

Symptom: step 4 fails with `Custom Locations Error: "Microsoft.ExtendedLocation" resource provider does not have the required permissions to create a namespace on the cluster`, or step 3 stops because the feature was not enabled.

Two causes, both silent in `az connectedk8s enable-features` when the VM signs in with its managed identity: the command cannot validate the object ID and uses the given value as it is; and it only warns when it leaves the feature out. In the second deployment the setting held the name of the custom location, `cl-windfarm-edge`, instead of the object ID. The scripts now refuse a value that is not an object ID, and step 3 stops when the feature was left out. A value that has the right form but is not the Custom Locations object ID of your tenant still shows only in step 4.

To repair a cluster after step 4 has failed this way: correct `CUSTOM_LOCATIONS_OID` in `config/demo.env`, run `bash infra/vm.sh push-env`, run step 3 again, then step 4 again.

1. Confirm `CUSTOM_LOCATIONS_OID` in `config/demo.env` on the VM is the value step 1 printed. Get it again on the workstation with
   `az ad sp show --id bc313c14-388c-4e7d-a58e-70017303ee3b --query id -o tsv`.
2. In `identity` mode, confirm the VM identity has Reader on the subscription. Without it the CLI cannot confirm that the `Microsoft.ExtendedLocation` provider is registered and skips the feature.
3. Run step 3 again (`bash infra/vm.sh ssh bash ./edge/scripts/03-arc-enable.sh`). It skips the connect step when the cluster is already connected.

### Alternative for step 3: onboard from the workstation

If neither sign-in mode works on the VM, run the Arc commands on the workstation, as yourself, through an SSH tunnel to the cluster's API server. You need `kubectl` on the workstation (Cloud Shell has it).

```bash
# Workstation: a tunnel to the cluster. Go on only when the last line lists the node.
source config/demo.env &&
VM_IP="$(az vm show --show-details --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --query publicIps --output tsv)" &&
scp "${VM_ADMIN}@${VM_IP}:/etc/rancher/k3s/k3s.yaml" ./k3s.yaml &&
ssh -f -N -L 6443:127.0.0.1:6443 "${VM_ADMIN}@${VM_IP}" &&
export KUBECONFIG=$PWD/k3s.yaml &&
kubectl get nodes
```

```bash
# Workstation: connect the cluster to Azure Arc
az connectedk8s connect --name "$CLUSTER_NAME" --location "$LOCATION" \
  --resource-group "$RESOURCE_GROUP" --subscription "$SUBSCRIPTION_ID" \
  --enable-oidc-issuer --enable-workload-identity --disable-auto-upgrade &&
az connectedk8s show --resource-group "$RESOURCE_GROUP" --name "$CLUSTER_NAME" \
  --query oidcIssuerProfile.issuerUrl --output tsv &&
az connectedk8s enable-features --name "$CLUSTER_NAME" --resource-group "$RESOURCE_GROUP" \
  --custom-locations-oid "$CUSTOM_LOCATIONS_OID" --features cluster-connect custom-locations
```

Then, on the VM (`bash infra/vm.sh ssh` opens a shell there), write the issuer URL printed above into the K3s configuration and restart K3s. Paste the URL in place of the text in capitals:

```bash
ISSUER_URL="PASTE THE ISSUER URL HERE"
sudo tee /etc/rancher/k3s/config.yaml >/dev/null <<EOF
kube-apiserver-arg:
  - service-account-issuer=${ISSUER_URL}
  - service-account-max-token-expiration=24h
EOF
sudo systemctl restart k3s
```

### Step 4 or step 6: `AuthorizationFailed` for a client you do not recognise

You ran a workstation script on the edge VM. There the Azure CLI is signed in as the VM's managed identity, which may onboard the cluster to Azure Arc and nothing else. Scripts in `infra/` run on your workstation or in Azure Cloud Shell, signed in as you; scripts in `edge/scripts/` run on the VM.

### Step 4: `Version mismatch: this is the 'cffi' package version …` in Cloud Shell

```text
Version mismatch: this is the 'cffi' package version 2.1.1, located in '…/cliextensions/azure-iot-ops/cffi/api.py'.
When we import the top-level '_cffi_backend' extension module, we get version 2.0.0, located in '/usr/lib64/az/…'.
```

Nothing is wrong with the cluster or with your settings; the Azure CLI crashed before it contacted Azure. It is a conflict between two CLI extensions:

- The `azure-iot-ops` extension carries its own copy of the `cffi` library (2.1.1) and puts its folder first on Python's import path when it loads. The CLI in Cloud Shell has an older copy (2.0.0) already in memory.
- `az connectedk8s` is the only command involved that uses `cffi` (through `pycryptodome`). When both extensions are loaded in the same process, it picks up the newer Python files with the older compiled half and stops.
- Both are loaded together only when the CLI rebuilds its command index, which it does on the first command after any extension is installed or updated. In Cloud Shell `connectedk8s` is installed on first use, so the first `az connectedk8s` command is exactly that command.

**Fix: run the same command again.** The run that crashed has already rebuilt the index, so the next run loads only `connectedk8s` and works.

The scripts in `infra/` no longer call `az connectedk8s` or `az k8s-extension`; they use `az resource show` and `az rest`, which are part of the CLI itself. You can still meet the error when you type an `az connectedk8s` command by hand in Cloud Shell right after an extension was installed; the fix is the same. `az iot ops` commands are not affected: no module of that extension imports `cffi`.

Reproduced outside Azure with CLI 2.93.0, `azure-iot-ops` 2.11.2 and `connectedk8s` 1.11.6: crash with a stale index, success on the next run, and no crash for `az resource show`, `az rest`, `az k8s-extension list` or six `az iot ops` commands with a stale index.

### Step 4: the Cloud Shell session closes while the script runs

Cloud Shell ends a session after 20 minutes without interactive activity, also when a long command is still running, and step 4 takes 20 to 30 minutes. Keep the Cloud Shell tab in front and press Enter every few minutes while the script runs.

If the session closed anyway: the part that was running in Azure continues. Open Cloud Shell again, wait until the resource group shows no deployment in progress (**Settings**, **Deployments**), then run the script again from the repository folder. Steps that already finished are skipped or repeated without harm.

### Step 4: `The connected cluster … is currently unavailable. Status: Degraded`

`az iot ops init` asks Azure Resource Health about the cluster before it deploys, and stops when the answer stays `Unavailable`. Nothing has been installed at that point. Tell the causes apart on the workstation:

```bash
bash infra/vm.sh status
bash infra/vm.sh run kubectl get pods -n azure-arc
```

- **The VM is stopped.** The daily shutdown is the usual reason; its time is in UTC. Start the VM with `bash infra/vm.sh start` and move the shutdown with `bash infra/vm.sh shutdown 0800`.
- **The VM runs and every pod is `Running`.** The cluster was connected to Azure Arc a few minutes ago and Resource Health has not caught up. This happened twice in the second deployment: five minutes after step 3, and again at `az iot ops create`, right after `init` had installed its two extensions. Step 4 now lets both commands ask for up to 20 minutes. To see the status yourself: `az rest --method get --query "properties.[availabilityState, title]" --output tsv --url "https://management.azure.com/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$RESOURCE_GROUP/providers/Microsoft.Kubernetes/connectedClusters/$CLUSTER_NAME/providers/Microsoft.ResourceHealth/availabilityStatuses/current?api-version=2025-05-01"`. Run step 4 again when it prints `Available`.
- **A pod stays `Pending`, `ContainerCreating` or `CrashLoopBackOff`.** `bash infra/vm.sh ssh kubectl describe pod NAME -n azure-arc` shows why.

### Step 4: Azure IoT Operations deployment fails or times out

- Run the script again. Creation of the storage account, schema registry and namespace is skipped when they exist, `init` can be repeated, and both commands are skipped when the instance exists. `az iot ops create` itself refuses a cluster that already has Azure IoT Operations.
- `SCHEMA_REGISTRY_NAMESPACE` must be unique in the tenant and `STORAGE_ACCOUNT_NAME` globally. Change them if the error says the name is taken.
- On the VM, look for pods that are not running: `kubectl get pods -A | grep -v -E 'Running|Completed'`. Pods stuck in `Pending` usually mean the VM is too small; use a size with 8 vCPUs and 32 GB of memory, such as `Standard_D8s_v7`.
- On the VM, `az iot ops check` reports what is unhealthy.
- "Your device is required to be managed" on the workstation: run `az login` again and complete the sign-in in a browser.

### Step 5: the simulator does not start or does not connect

```bash
kubectl get pods -n windfarm
kubectl describe pod -n windfarm -l app=windfarm-simulator | tail -n 20
kubectl logs -n windfarm deploy/windfarm-simulator --tail=50
```

| Symptom | Cause | Fix |
|---|---|---|
| `ErrImageNeverPull` | The image is not in K3s | Run step 5 again; check `sudo k3s ctr images ls \| grep windfarm` |
| Pod stuck in `ContainerCreating`, event mentions ConfigMap `aio-ca-trust-bundle` | The CA copy is missing | Run step 5 again after Azure IoT Operations is fully deployed |
| Log: `broker refused the connection: Not authorized` or `Bad authentication method` | The service account token is not accepted | The token audience in `edge/k8s/simulator.yaml` must be `aio-internal`, the audience of the default BrokerAuthentication resource. Check `kubectl get brokerauthentication -n azure-iot-operations -o yaml`. |
| Log: certificate verify failed | The broker's CA changed, for example after redeploying Azure IoT Operations | Nothing: the simulator reads the CA from the cluster at every connect, and restarts itself after 10 minutes offline. If it persists, the simulator may lack the right to read the trust bundle: run step 5 again, which creates the role `windfarm-read-broker-ca`. |
| Log: `climate model unavailable … using the regime wind model` | The image was built without numpy | Build the image with step 5, which installs it. The simulator runs, but its wind no longer matches the history. |
| Log: name resolution failed | Azure IoT Operations is not deployed or the service name differs | `kubectl get service -n azure-iot-operations`; the broker service is `aio-broker` on port 18883 |
| `simctl` prints "no reply from the simulator" | The simulator pod is restarting or not connected | Check the pod log |

## No events in the eventstream

Work through these in order.

1. **The simulator publishes.** `bash infra/vm.sh ssh bash ./edge/scripts/mqtt-peek.sh --count 20` shows messages. If not, see the section above.
2. **The data flow exists and is enabled.** In the operations experience (https://iotoperations.azure.com), open your instance and look at **Data flows** and **Data flow endpoints**. Or on the VM:

   ```bash
   kubectl get dataflows.connectivity.iotoperations.azure.com -n azure-iot-operations
   kubectl get pods -n azure-iot-operations | grep -i dataflow
   kubectl logs -n azure-iot-operations "$(kubectl get pods -n azure-iot-operations -o name | grep -i dataflow | head -n 1)" --tail=50
   ```

   Authentication or authorization errors in this log point to step 3 below. Connection errors point to step 4.
3. **The identity has access.** The Azure IoT Operations Arc extension identity must be a Contributor on the Fabric workspace (step 6.5), and both tenant settings from step 0 must be enabled. Changes can take several minutes to take effect. After fixing access, run `bash infra/06-connect-edge-to-fabric.sh` again. If events still do not arrive, restart the data flow pods on the VM; they are recreated at once: `kubectl get pods -n azure-iot-operations -o name | grep -i dataflow | xargs kubectl delete -n azure-iot-operations`.
4. **The endpoint values are right.** `EVENTSTREAM_BOOTSTRAP_SERVER` and `EVENTSTREAM_TOPIC` must come from the **Kafka** tab, section **Entra ID Authentication**, of the custom endpoint source. The host ends in `.servicebus.windows.net:9093`. The topic is the name the tab shows: on the tenant of this demo it is the first part of the host with `_eh` at its end (`esehdm7…_eh`); Microsoft's examples show the form `es_` followed by an identifier. The eventstream must be published. `bash infra/06-connect-edge-to-fabric.sh` compares both values with a data flow that is already running and stops when they differ.
5. **Fall back to key authentication.** If managed identity authentication cannot be made to work in your tenant, use the connection string of the custom endpoint instead. In the eventstream, open the **Kafka** tab, section **SAS Key Authentication**, and copy **Connection string-primary key**.

   ```bash
   # Edge VM: store the connection string as a Kubernetes secret
   read -r -s -p "Paste the connection string and press Enter: " FABRIC_CONNECTION_STRING; echo
   kubectl create secret generic fabric-es-sasl -n azure-iot-operations \
     --from-literal=username='$ConnectionString' \
     --from-literal=password="$FABRIC_CONNECTION_STRING"

   # Workstation: recreate the endpoint with SASL authentication
   source config/demo.env
   az iot ops dataflow endpoint create fabric-realtime \
     --resource-group "$RESOURCE_GROUP" --instance "$AIO_INSTANCE_NAME" \
     --name fabric-eventstream --host "$EVENTSTREAM_BOOTSTRAP_SERVER" \
     --auth-type Sasl --sasl-type Plain --secret-name fabric-es-sasl
   ```

   The user name is the literal text `$ConnectionString`, including the dollar sign; keep the single quotes. Microsoft documents a manually created secret like this for testing only. For production, enable secure settings and sync the secret from Azure Key Vault.

## Eventhouse

### The eventstream shows events but `RawEvents` stays empty

- The Eventhouse destination is not finished. In the eventstream's live view the destination still offers **Configure**: complete the wizard (step 6.7).
- Run `.show ingestion failures | where FailedOn > ago(1h)` in the KQL database and read the `Details` column.
- The wizard created a new table instead of using `RawEvents`. Delete that table and the destination, and repeat step 6.7 choosing the existing table.

### `RawEvents` has rows but `data` is empty or columns are null

The mapping did not match. The seven JSON fields must map to the seven columns of the same names, and `data` must stay one `dynamic` column, not be flattened into many columns. Remove the destination, repeat step 6.7, and pick the mapping `RawEvents_mapping` or, if the wizard only infers a mapping, keep the nesting level at 1.

### `RawEvents` has the columns `schemaVersion_1` and `seq_1`, or `seq` is empty

The Get data wizard of step 6.7 was finished with the mapping it proposed (`RawEvents_mapping_1`) instead of the existing `RawEvents_mapping`. The wizard guesses types from the sample; where its guess differs from the type of an existing column it does not use that column but adds a new one. Here it reads `schemaVersion` (`"1.0"`) as a number, while the column is a string, and `seq` as a different integer type from the column's `long`. New rows then have empty `schemaVersion` and `seq`, and `Seq` is empty in every typed table.

On the **Inspect the data** page you can see it before finishing: two extra columns at the right, and nothing under `schemaVersion` and `seq`.

To repair:

1. In the eventstream, select **Edit**, delete the Eventhouse destination and **Publish**.
2. Repeat step 6.7. In the mapping dropdown above the preview grid, turn on **Use existing mapping** and select `RawEvents_mapping`.
3. Run `fabric/kql/91-repair-wizard-columns.kql` to remove the two columns and the wizard's mapping.
4. Rows that arrived in between have an empty `Seq`. For a clean start run `fabric/kql/99-reset-demo-data.kql`.

Query 18 in `fabric/kql/90-validation-queries.kql` detects the situation. The repair script passes the offline syntax check and has not been run on Fabric.

### Typed tables stay empty

```kusto
.show table TurbineTelemetry policy update

Expand_TurbineTelemetry() | take 5

.show ingestion failures | where FailedOn > ago(1h) | project FailedOn, Table, Details
```

- No policy shown: run `fabric/kql/02-update-policies.kql` again.
- The function returns rows but the table is empty: the update policy was created after the rows arrived. Update policies apply to new data only; wait for new messages.
- The function fails: the column types of `RawEvents` differ from `01-tables.kql`, usually because the wizard changed them. Compare with `.show table RawEvents cslschema`.

### Latency is minutes, not seconds

The batching policy on `RawEvents` (20 seconds) was not applied. Run this and check the result:

```kusto
.show table RawEvents policy ingestionbatching
```

### A command in `03-onelake-availability.kql` is rejected

Turn OneLake availability on in the portal instead: select the table in the database explorer and set **Availability** to enabled in the **OneLake** section of the details pane, for each of the six typed tables. Then run the script again to set the 5-minute write delay.

## Lakehouse

### Shortcut tables are empty or missing

- OneLake availability writes in batches. With the 5-minute setting, allow up to 10 minutes after turning it on.
- Check how far OneLake is behind with validation query 17.
- A shortcut created before OneLake availability was on points at an empty folder. Delete the shortcut and create it again.

### Step 7.4: the reference data sync fails

| Error | Cause | Fix |
|---|---|---|
| 403 or `AuthorizationPermissionMismatch` | The VM identity is not a Contributor on the workspace, or the tenant setting for service principals is off | Step 6.5 and step 0; allow some minutes for the change |
| `DefaultAzureCredential failed to retrieve a token` | No identity available where you run the script | On the VM, check `az vm identity show`. On a workstation, run `az login` first. |
| Workspace or path not found | The workspace or Lakehouse name has spaces or special characters | Use the workspace ID and the Lakehouse ID (both are in the Lakehouse URL) as `FABRIC_WORKSPACE_NAME` and `FABRIC_LAKEHOUSE_NAME` |

### A notebook cannot find `Files/reference`, `site.json` or a table

| Message | Cause | Fix |
|---|---|---|
| `Path does not exist: … Files/reference` or `No such file or directory: '/lakehouse/default/Files/reference/site.json'` | The notebook has no default Lakehouse, or step 7.4 has not uploaded the files | Add `WindFarmLH` in the explorer pane and set it as default; run step 7.4; run all cells again |
| `TABLE_OR_VIEW_NOT_FOUND: ops_…` in notebook 03 or 04 | Notebook 02 has not run in this Lakehouse | Run `02_generate_history` |
| `TABLE_OR_VIEW_NOT_FOUND: ref_…` in notebook 04 | Notebook 01 has not run | Run `01_load_reference_data` |
| `UNRESOLVED_COLUMN` for `CostBorneBy`, `WaitingForPartsHours` or `LongTermWindSpeed` | The `ops_` tables were written by an older version of notebook 02 | Import the current notebook 02 and run it |
| Notebook 03: `ops_power_forecast holds no day-ahead forecast` | The table is empty or missing | Run notebook 02 once |

### Notebook 02 runs out of memory or is slow

The generator itself needs about 1 GB of memory on the driver and 10 seconds of computing (measured on Python 3.11 with pandas 2.1); converting the largest table to Spark needs about as much again. The rest of the run is starting Spark and writing 12 tables. A default Fabric starter pool is more than enough. If you reduced the pool to its smallest node size and the notebook fails in the cell **Generate**, set the history to start later: `tables = generate(site, as_of=AS_OF, start="2026-01-01T00:00:00Z")` in that cell.

### The history ends hours or days ago

The history ends when notebook 02 last ran. Run it again; every table is replaced. Schedule notebook 03 to keep the forecast current in between.

### The answers of the question bank differ from the example answers

They should differ a little: the stories in the history are placed relative to the day notebook 02 ran, and the example is from one particular day. The pattern should be the same: the same turbines at the top and bottom, numbers of the same size. If a result is empty where the example has rows, check that notebooks 01 and 02 both ran after the last change of the reference data.

## The demo

### The injected fault barely shows

`simctl inject` warns when the target turbine is not generating. In light wind the turbine idles, the drivetrain does not turn and a gearbox fault has little to show. Raise the wind, wait 5 minutes and inject again:

```bash
bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh wind --mean 11 --duration 60m
```

### WT-07 stands out before any fault is injected, or WT-05 and WT-09 produce less

That is intended. Three turbines carry a standing condition from the site's history: a worn gearbox bearing on WT-07 (warmer and rougher, no alarm), a yaw offset of about 9 degrees on WT-05 and eroded blades on WT-09 (both about 4 percent less power). `simctl.sh status` lists them. To run without them, set `STANDING_CONDITIONS` to `"false"` in `edge/k8s/simulator.yaml`, run `bash infra/vm.sh push` and step 5 again; the live data then no longer matches the history.

### An alarm stays active after the simulator was restarted

Run the current `fabric/kql/02-update-policies.kql` again. Its `ActiveAlarms()` ignores alarms raised before the simulator's latest start. The version of the first delivery did not.

### Alarms appear on turbines you did not touch

About once an hour the simulator produces a small event by itself: a short communication drop, a cable untwist pause (`YAW-UNTWIST`, state `PAUSED`), a minor yaw offset or a sensor freeze. They are part of the realism. To turn them off, set `SPONTANEOUS_EVENTS_PER_HOUR` to `0` in `edge/k8s/simulator.yaml` and run step 5 again.

### No data after the VM was restarted

Allow 5 minutes. Then check, on the VM (`bash infra/vm.sh ssh` opens a shell there): `kubectl get pods -A | grep -v -E 'Running|Completed'` and `bash ./edge/scripts/simctl.sh status`. On the workstation, `bash infra/vm.sh status` shows whether the VM is running, and this should return `Connected`:

```bash
source config/demo.env &&
az resource show --resource-type Microsoft.Kubernetes/connectedClusters --name "$CLUSTER_NAME" \
  --resource-group "$RESOURCE_GROUP" --query properties.connectivityStatus --output tsv
```

 The data flow resumes by itself once the broker and the cluster are up.

## Clean-up

### `99-cleanup.sh` says the Fabric REST API could not be used

The script calls the Fabric REST API with the sign-in of the Azure CLI, and the session could not get a token for it. Azure Cloud Shell is the usual place for this. Nothing was deleted in Fabric. Either follow the portal steps that the script printed, or run the Fabric part on a computer where you signed in with `az login` in a browser: copy `infra/99-cleanup.sh` and `config/demo.env` there and run `bash 99-cleanup.sh --fabric` with `ENV_FILE` pointing at the settings file.

### `ClusterNetworkUnavailable` during the clean-up

```
(ClusterNetworkUnavailable) Failed to establish a network connection with the kubernetes cluster '…/connectedClusters/arc-windfarm-edge'.
Exception Details: (None) Cannot connect to the hybrid connection because no agent is connected in the target arc resource.
```

`az iot ops delete` could not reach the cluster. Its first action, deleting the instance, goes from Azure through the Azure Arc agents to the cluster; with no agent connected it fails, and nothing has been uninstalled. Two usual causes: the VM was started a few minutes ago and the agents are still connecting, although Azure already shows the cluster as `Connected`; or the VM is stopped or gone.

The script tries again by itself, up to four times with 2.5 minutes in between, as long as the VM is running. If Azure never reaches the cluster, it goes on to delete the resource group. That is safe: the uninstall protects a cluster that is kept, and this cluster is deleted with its VM. Check the result with `az group exists --name "$RESOURCE_GROUP"`.

To give the agents more time, set the number of attempts or the pause in front of the command, for example `UNINSTALL_ATTEMPTS=8 bash infra/99-cleanup.sh --azure`. To see whether the agents are up, run `bash infra/vm.sh ssh kubectl get pods -n azure-arc`. The Azure Arc troubleshooting article ties this error message to the `clusterconnect-agent` pods.

The first version of the script, of 20 November 2026 in the early evening, made one attempt only and printed `The uninstall did not finish cleanly`. It went on to the resource group in the same way.

### The uninstall fails for another reason

The script prints the error of `az iot ops delete`, warns, and goes on to delete the resource group. If the group still exists afterwards, run `bash infra/99-cleanup.sh --azure` again: it uninstalls what is left and repeats the deletion.

### The resource group is not deleted

The script lists what is left and ends with exit code 3. Run it again after a few minutes; a resource that was still being removed by the uninstall can block the first attempt. If the same resources stay, delete them in the Azure portal, the custom location and the Azure IoT Operations instance first, then the group. A lock or a policy of the subscription can also block the deletion; the error message of `az group delete` names it.

### An item of the first run is still in the workspace after `--fabric`

The script deletes the items that have the names of the guides: `es-windfarm-edge` and `WindFarmCommands`, `WindFarmEH` and its queryset, `WindFarmLH`, the thirteen notebooks, and from the later phases `WindFarm Operations`, `WindFarm Operations Report`, `WindFarmDataAgent`, `WindFarmOntology`, `WindFarmGearboxWatch` and `WindFarmTwin`. The names of the later phases can be given in front of the command as well: `SEMANTIC_MODEL_NAME`, `REPORT_NAME`, `DATA_AGENT_NAME`, `ONTOLOGY_NAME`, `OPERATIONS_AGENT_NAME`, `APP_NAME`. An item that you named differently is listed under "Left alone". Delete it in the portal, or give the name in front of the command, for example `EVENTSTREAM_NAME=my-stream bash infra/99-cleanup.sh --fabric`. The same works for `EVENTHOUSE_NAME` and `FABRIC_LAKEHOUSE_NAME`.

### `--fabric` says an item was deleted, but not permanently

The permanent delete needs the Admin role in the workspace, and Fabric refused it. The script used the normal delete instead. With item recovery on in the tenant, which is the default, a Lakehouse, a notebook or a KQL queryset is then in the workspace's **Recycle bin** for the tenant's retention period, 3 days by default, and uses OneLake storage until then. A workspace Admin can delete it for good there; otherwise Fabric removes it when the period ends. An eventstream and an Eventhouse are never kept.

## Phase 2

The table "If something fails" at the end of [07-deployment-guide-phase2.md](07-deployment-guide-phase2.md) covers the notebooks 05 to 08. When a step fails in a way that the table does not cover, the error text and the cell's output are what is needed to fix it. [phase2-validation-log.md](phase2-validation-log.md) has the three obstacles of its first run.

## Phase 3

The table "If something fails" at the end of [09-deployment-guide-phase3.md](09-deployment-guide-phase3.md) covers the capacity, the tenant settings, the notebooks 09 to 11, the data agent's answers and the operations agent, including the seven obstacles of the deployment of 21 November 2026. Two habits from that deployment save the most time:

- Before reading a test result of the data agent, read section 4 of notebook 09. It says which instructions, examples and ontology the published agent has.
- Do not judge a change to the agent by one test run. The total moves by about two questions between runs of an unchanged agent, and single verdicts flip.

## Phase 4

The table "If something fails" at the end of [11-deployment-guide-phase4.md](11-deployment-guide-phase4.md) covers the creation of the app, the sign-in from WSL, the deployment and the app itself. Before anything else, open the connection check in the app (select the badge at the top right) and read its six lines: each names one thing the app needs from Fabric and says what Fabric answered.

One line of that check can fail without anything being wrong: `Lakehouse route: query … found no telemetry in the last 60 minutes`, while the Eventhouse route passes. The twin reads the Eventhouse, and the SQL endpoint of the Lakehouse follows new data only while something asks it ([SQL analytics endpoint performance considerations](https://learn.microsoft.com/en-us/fabric/data-engineering/sql-analytics-endpoint-performance)). Select **Check again** a few minutes later. Seen on 25 November 2026: failed at 01:30, passed at 01:34 with the newest row 2 minutes old. If it keeps failing, run `.show table TurbineTelemetry operations mirroring-status` in a query window on `WindFarmEH`: it says whether the Eventhouse still writes the copy the Lakehouse reads.

## Phase 5

Each of the three guides ends with a table "If something fails" that follows the command along its way, hop by hop: [12-deployment-guide-phase5a.md](12-deployment-guide-phase5a.md) from the notebook to the turbine, [13-deployment-guide-phase5b.md](13-deployment-guide-phase5b.md) from the table the agent watches to the approval, [14-deployment-guide-phase5c.md](14-deployment-guide-phase5c.md) from the edge's record back to the command center and the twin. Three commands say where things stand without changing anything:

- `bash infra/08-create-command-path.sh --show`: the eventstream, what the edge reads from, the endpoint and the data flow.
- `bash infra/09-remediation-agent.sh --show`: the operations agent as Fabric has it, its instructions, its action and the action's values, and what differs from Phase 5b.
- `bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh status`: the turbines, their states and the active faults, on the edge.

When an approved action changes nothing, run `bash infra/09-remediation-agent.sh --rehearse WT-07`. It runs the action's notebook as a job without the agent. If the turbine follows, the fault is on the agent's side of the approval; if not, on the notebook's.

Since Phase 5c the edge keeps a record, and it is the quickest way to tell which half of the loop is broken. In a query window on `WindFarmEH`:

```kusto
CommandLog(1h) | order by Timestamp desc
```

- **The command is there, `in force` or `confirmed`.** It arrived and the turbine followed. If something still looks wrong, it is in what shows it: the twin's connection check, or the browser's page being older than the functions.
- **The command is there, `refused`.** The column `Error` is the edge's reason.
- **The command is there, `taken by the edge, never seen in telemetry`.** The edge took it and the turbine's readings did not show it within five minutes. A turbine that does not report (a communication loss) is the usual case.
- **The command is not there, and the telemetry shows it.** The command arrived; the record did not come back. The simulator must be 1.2.0 (`simctl.sh status`) and the data flow must forward seven topics (`cat edge/dataflows/rendered/windfarm-to-fabric.json` after `bash infra/06-connect-edge-to-fabric.sh`).
- **The command is not there, and nothing changed.** It did not reach the edge: the table at the end of the Phase 5a guide, hop by hop.
- **The query itself fails.** Block 1 of `fabric/kql/07-command-log.kql` has not run in this database.
