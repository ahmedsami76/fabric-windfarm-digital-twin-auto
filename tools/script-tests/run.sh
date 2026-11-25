#!/usr/bin/env bash
# Scenario tests for infra/vm.sh, infra/01-create-edge-vm.sh, infra/99-cleanup.sh, app/create-app.sh,
# app/create-principal.sh, infra/06-connect-edge-to-fabric.sh, infra/08-create-command-path.sh, infra/09-remediation-agent.sh,
# tools/check-scripts.sh and the checks on where a script runs. Nothing here touches Azure or a VM: the commands az, ssh, scp, curl and a
# few others are replaced by the stand-ins in tools/script-tests/stubs, which answer from
# files in a scratch folder and log every call.
#   bash tools/script-tests/run.sh
# These tests show that the scripts take the right decisions. They cannot show that
# Azure answers the way the stand-ins do.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
SCRATCH="$(mktemp -d)"
trap 'rm -rf "$SCRATCH"' EXIT
chmod +x "$HERE"/stubs/*
export STUB_DIR="$SCRATCH/state" PATH="$HERE/stubs:$PATH" ENV_FILE="$SCRATCH/demo.env"
sed -e 's/^SUBSCRIPTION_ID=""/SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000"/' -e 's/^STORAGE_ACCOUNT_NAME=""/STORAGE_ACCOUNT_NAME="stwindfarm"/' "$REPO/config/demo.env.example" > "$ENV_FILE"
pass=0; fail=0
reset() { rm -rf "$STUB_DIR"; mkdir -p "$STUB_DIR"; echo "VM running" > "$STUB_DIR/power"; echo 20.45.58.189 > "$STUB_DIR/ip"; }
check() {  # check NAME EXPECTED_EXIT PATTERN... ; output in $OUT, exit code in $RC
  local name="$1" want="$2"; shift 2; local ok=yes
  [[ "$RC" == "$want" ]] || ok=""
  for pat in "$@"; do
    if [[ "$pat" == "!"* ]]; then grep -q -- "${pat#!}" <<< "$OUT$(cat "$STUB_DIR/calls.log" 2>/dev/null)" && ok=""
    else grep -q -- "$pat" <<< "$OUT$(cat "$STUB_DIR/calls.log" 2>/dev/null)" || ok=""; fi
  done
  if [[ -n "$ok" ]]; then pass=$((pass+1)); echo "PASS $name"; else fail=$((fail+1)); echo "FAIL $name (exit $RC)"; echo "$OUT" | sed 's/^/     | /'; sed 's/^/     # /' "$STUB_DIR/calls.log"; fi
}
run() { OUT="$("$@" 2>&1)"; RC=$?; }

reset; touch "$STUB_DIR"/port_open
run bash "$REPO"/infra/vm.sh ssh;                       check "ssh, port open: connects as the administrator" 0 "ssh .*azureuser@20.45.58.189" "interactive shell" "!initiate" "!nsg rule update"
run bash "$REPO"/infra/vm.sh ssh bash ./edge/scripts/simctl.sh status
check "ssh COMMAND: runs in the repository folder" 1 "ssh -t .*azureuser@20.45.58.189 cd ~/fabric-windfarm-digital-twin && bash ./edge/scripts/simctl.sh status"

reset; echo "/subscriptions/s/resourceGroups/rg-windfarm-edge/providers/Microsoft.Security/locations/southcentralus/jitNetworkAccessPolicies/default" > "$STUB_DIR"/jitpolicy
printf '52.177.6.131\tMicrosoftDefenderForCloud-JITRule-1-ABC\n' > "$STUB_DIR"/openings
run bash "$REPO"/infra/vm.sh ssh;                       check "ssh, port closed, just-in-time policy: asks for access, then connects" 0 "jitNetworkAccessPolicies/default/initiate" "203.0.113.77" "interactive shell" "!nsg rule update"

reset; echo "198.51.100.9/32" > "$STUB_DIR"/rule; printf '198.51.100.9/32\tallow-ssh-from-admin\n' > "$STUB_DIR"/openings
run bash "$REPO"/infra/vm.sh ssh;                       check "ssh, port closed, own rule elsewhere: moves the rule, then connects" 0 "nsg rule update .*203.0.113.77/32" "interactive shell" "!initiate"

reset
run bash "$REPO"/infra/vm.sh ssh;                       check "ssh, port closed, no rule, no policy: stops with advice" 1 "Cannot open SSH access" "nsg-log" "!interactive shell" "!nsg rule create"

reset
run bash "$REPO"/infra/vm.sh ssh bash ./edge/scripts/simctl.sh status
check "ssh COMMAND, port closed, no rule, no policy: runs the command without SSH" 0 "running the command without SSH" "vm run-command invoke .*sudo -u azureuser -H bash -lc .cd ~/fabric-windfarm-digital-twin && bash ./edge/scripts/simctl.sh status" "!ssh -t" "!nsg rule create"

reset; echo "VM deallocated" > "$STUB_DIR"/power
run bash "$REPO"/infra/vm.sh ssh;                       check "ssh, VM stopped: says to start it" 1 "The VM is not running" "vm.sh start" "!interactive shell"

reset; touch "$STUB_DIR"/port_open; mkdir -p "$STUB_DIR"/home/fabric-windfarm-digital-twin/data/reference "$STUB_DIR"/home/fabric-windfarm-digital-twin/config
echo old > "$STUB_DIR"/home/fabric-windfarm-digital-twin/data/reference/maintenance_history.csv
echo keepme > "$STUB_DIR"/home/fabric-windfarm-digital-twin/notes-of-the-user.txt
run bash "$REPO"/infra/vm.sh push; H="$STUB_DIR/home/fabric-windfarm-digital-twin"
OUT="$OUT
exec:$([[ -x "$H/edge/scripts/simctl.sh" && -x "$H/infra/vm.sh" ]] && echo yes) stale:$([[ -e "$H/data/reference/maintenance_history.csv" ]] && echo present || echo gone) own:$([[ -f "$H/notes-of-the-user.txt" ]] && echo kept) git:$([[ -e "$H/.git" ]] && echo present || echo none) modules:$(find "$H" -name node_modules -o -name __pycache__ | wc -l) nb:$([[ -f "$H/fabric/notebooks/02_generate_history.ipynb" ]] && echo yes)"
check "push: copies, restores execute bits, removes stale files, keeps other files" 0 "exec:yes" "stale:gone" "own:kept" "git:none" "modules:0" "nb:yes"

# The settings in use are not config/demo.env (ENV_FILE, as for a deployment of tools/deploy.py): push puts them where the
# scripts on the VM read them, and sends none of the checkpoints of .deploy.
reset; touch "$STUB_DIR"/port_open; mkdir -p "$REPO/.deploy/zz9" && echo '{}' > "$REPO/.deploy/zz9/state.json"
run bash "$REPO"/infra/vm.sh push; H="$STUB_DIR/home/fabric-windfarm-digital-twin"; rm -rf "$REPO/.deploy/zz9"; rmdir "$REPO/.deploy" 2>/dev/null
OUT="$OUT
same:$(cmp -s "$ENV_FILE" "$H/config/demo.env" && echo yes) deploy:$([[ -e "$H/.deploy" ]] && echo sent || echo none)"
check "push with the settings elsewhere: they become config/demo.env on the VM, and .deploy stays here" 0 "same:yes" "deploy:none" "settings in use here"

reset; touch "$STUB_DIR"/port_open
run bash "$REPO"/infra/vm.sh push-env;                  check "push-env: copies the settings file" 0 "scp .*demo.env azureuser@20.45.58.189:fabric-windfarm-digital-twin/config/demo.env"

# A deployment of tools/deploy.py keeps its settings in .deploy/<suffix>/demo.env, and .deploy/current names the one in use.
# A script started by hand finds them: ENV_FILE first, then config/demo.env, then the current deployment.
POINTED="$SCRATCH/pointed"; mkdir -p "$POINTED/config" "$POINTED/infra" "$POINTED/.deploy/k3f" "$POINTED/app"
cp "$REPO/config/load-env.sh" "$POINTED/config/"; cp "$REPO/infra/99-cleanup.sh" "$POINTED/infra/"
sed -e 's/^RESOURCE_GROUP=.*/RESOURCE_GROUP="rg-windfarm-edge-k3f"/' -e 's/^FABRIC_WORKSPACE_NAME=.*/FABRIC_WORKSPACE_NAME="WindFarmDigitalTwin-k3f"/' "$ENV_FILE" > "$POINTED/.deploy/k3f/demo.env"
echo k3f > "$POINTED/.deploy/current"
reset
run env -u ENV_FILE bash -c 'source "$0"/config/load-env.sh && echo "group:$RESOURCE_GROUP file:${ENV_FILE#"$0"/}"' "$POINTED"
check "settings: without ENV_FILE and without config/demo.env, the current deployment's are used" 0 "group:rg-windfarm-edge-k3f file:.deploy/k3f/demo.env"
sed -e 's/^RESOURCE_GROUP=.*/RESOURCE_GROUP="rg-by-hand"/' "$ENV_FILE" > "$POINTED/config/demo.env"
run env -u ENV_FILE bash -c 'source "$0"/config/load-env.sh && echo "group:$RESOURCE_GROUP"' "$POINTED"
check "settings: config/demo.env, where it exists, comes before the current deployment" 0 "group:rg-by-hand"
run env ENV_FILE="$POINTED/.deploy/k3f/demo.env" bash -c 'source "$0"/config/load-env.sh && echo "group:$RESOURCE_GROUP"' "$POINTED"
check "settings: ENV_FILE comes before both" 0 "group:rg-windfarm-edge-k3f"
rm "$POINTED/config/demo.env"; echo gone > "$POINTED/.deploy/current"
run env -u ENV_FILE bash -c 'source "$0"/config/load-env.sh' "$POINTED"
check "settings: a current deployment whose settings are missing is an error that names the file" 1 ".deploy/gone/demo.env not found" "tools/deploy.py plan"
echo k3f > "$POINTED/.deploy/current"; reset
run env -u ENV_FILE bash "$POINTED"/infra/99-cleanup.sh
check "clean-up without ENV_FILE and without config/demo.env: reports on the current deployment" 0 "rg-windfarm-edge-k3f" "!rg-by-hand"

reset; HOME_BACKUP="$HOME"; export HOME="$STUB_DIR/fakehome"; mkdir -p "$HOME"
run bash "$REPO"/infra/vm.sh reset-key;                 check "reset-key without a key: creates one and installs it" 0 "ssh-keygen" "vm user update .*--username azureuser --ssh-key-value ssh-rsa AAAATESTKEY"
run bash "$REPO"/infra/vm.sh reset-key /nonexistent.pub; check "reset-key with a missing file: stops" 1 "not found"
export HOME="$HOME_BACKUP"

reset
run bash "$REPO"/infra/vm.sh run bash ./edge/scripts/mqtt-peek.sh --count 5
check "run: goes through the VM agent in the repository folder" 0 "sudo -u azureuser -H bash -lc 'cd ~/fabric-windfarm-digital-twin && bash ./edge/scripts/mqtt-peek.sh --count 5'"

reset; echo "/subscriptions/s/resourceGroups/rg-windfarm-edge/providers/Microsoft.Security/locations/southcentralus/jitNetworkAccessPolicies/default" > "$STUB_DIR"/jitpolicy
run bash "$REPO"/infra/vm.sh status;                    check "status with a just-in-time policy: points to vm.sh ssh" 0 "Just-in-time access" "vm.sh ssh opens access" "Administrator:  azureuser"
run bash "$REPO"/infra/vm.sh allow-my-ip;               check "allow-my-ip under a just-in-time policy: refuses" 1 "Not changing the rule" "!nsg rule create"
run bash "$REPO"/infra/vm.sh jit 2;                     check "jit 2: asks for two hours" 0 "initiate" "Granted"
run bash "$REPO"/infra/vm.sh bogus;                     check "unknown action: prints the usage" 2 "infra/vm.sh push" "infra/vm.sh reset-key"

# ---- step 1
reset; rm -f "$STUB_DIR"/power
printf 'Standard_D8s_v5\tNotAvailableForSubscription\nStandard_D8s_v6\tNone\nStandard_D8s_v7\tNone\n' > "$STUB_DIR"/skus
echo Standard_D8s_v6 > "$STUB_DIR"/refused; echo 99999999-aaaa-bbbb-cccc-000000000000 > "$STUB_DIR"/oid
run bash "$REPO"/infra/01-create-edge-vm.sh
check "step 1: skips a restricted size, moves on when Azure refuses one, creates with the next" 0 "Standard_D8s_v5: not offered" "Standard_D8s_v6: refused by Azure" "Created with size Standard_D8s_v7" "CUSTOM_LOCATIONS_OID=\"99999999" "vm.sh push" "user name for SSH" "!vm create .*Standard_D8s_v5" "!vm create .*Standard_D8as"
: > "$STUB_DIR"/calls.log
run bash "$REPO"/infra/01-create-edge-vm.sh
check "step 1 again: keeps the existing VM" 0 "exists already (Standard_D8s_v7)" "!vm create"

reset; rm -f "$STUB_DIR"/power; printf 'Standard_D8s_v5\tNotAvailableForSubscription\n' > "$STUB_DIR"/skus
run bash "$REPO"/infra/01-create-edge-vm.sh
check "step 1, nothing offered: stops and says what to do" 1 "None of these sizes is offered" "az vm list-skus" "!vm create" "Each answer can take minutes"

# The sizes were checked by whoever starts the script (tools/deploy.py): the slow question to Azure is not asked again.
reset; rm -f "$STUB_DIR"/power; printf 'Standard_D8s_v5\tNotAvailableForSubscription\n' > "$STUB_DIR"/skus
echo Standard_D8s_v6 > "$STUB_DIR"/refused; echo 99999999-aaaa-bbbb-cccc-000000000000 > "$STUB_DIR"/oid
run env VM_SIZE_OFFERED="Standard_D8s_v6 Standard_D8s_v7" bash "$REPO"/infra/01-create-edge-vm.sh
check "step 1 with sizes already checked: asks no list of sizes, still moves on when Azure refuses one" 0 "!vm list-skus" "!Each answer can take minutes" "Standard_D8s_v6: refused by Azure" "Created with size Standard_D8s_v7"

# Nobody could ask which sizes are offered: every size of VM_SIZE is tried as it stands, and Azure's refusal moves on.
reset; rm -f "$STUB_DIR"/power; printf 'Standard_D8s_v5\nStandard_D8s_v6\n' > "$STUB_DIR"/refused
echo 99999999-aaaa-bbbb-cccc-000000000000 > "$STUB_DIR"/oid
run env VM_SIZE_SKIP_CHECK=1 bash "$REPO"/infra/01-create-edge-vm.sh
check "step 1 without the question about sizes: tries each size and lets Azure refuse" 0 "!vm list-skus" "!Each answer can take minutes" "Not asking Azure which sizes you are offered" "Standard_D8s_v5: refused by Azure" "Standard_D8s_v6: refused by Azure" "Created with size Standard_D8s_v7"

reset; rm -f "$STUB_DIR"/power; printf 'Standard_D8s_v5\tNone\n' > "$STUB_DIR"/skus
run bash "$REPO"/infra/01-create-edge-vm.sh
check "step 1, object ID not readable: warns with the CLI message" 0 "Could not read the Custom Locations object ID" "Insufficient privileges"
sed -i.bak 's/^CUSTOM_LOCATIONS_OID=""/CUSTOM_LOCATIONS_OID="77777777-aaaa-bbbb-cccc-000000000000"/' "$ENV_FILE"; : > "$STUB_DIR"/calls.log
run bash "$REPO"/infra/01-create-edge-vm.sh
check "step 1, object ID already set: does not look it up" 0 "77777777-aaaa-bbbb-cccc-000000000000   (from config/demo.env)" "!ad sp show"

# ---- where a script runs
reset; echo vm-windfarm-edge > "$STUB_DIR"/hostname
run bash "$REPO"/infra/vm.sh status;                    check "workstation script on the edge VM: stops" 1 "not on the edge VM"
run bash "$REPO"/infra/04-deploy-iot-operations.sh;     check "step 4 on the edge VM: stops" 1 "not on the edge VM" "!iot ops"
reset
run bash "$REPO"/edge/scripts/05-deploy-simulator.sh;   check "edge script on the workstation: stops and says how to connect" 1 "runs on the edge VM" "vm.sh ssh"
run bash "$REPO"/edge/scripts/07-sync-reference-data.sh; check "step 7 on the workstation: stops" 1 "runs on the edge VM"
# The mistake of the second deployment: the name of the custom location in the object ID setting.
reset
run env CUSTOM_LOCATIONS_OID_OVERRIDE=cl-windfarm-edge bash -c 'sed -e "s/^CUSTOM_LOCATIONS_OID=.*/CUSTOM_LOCATIONS_OID=\"cl-windfarm-edge\"/" "$ENV_FILE" > "$ENV_FILE.bad"; ENV_FILE="$ENV_FILE.bad" bash "$0"/infra/01-create-edge-vm.sh' "$REPO"
check "step 1, object ID setting holds a name: stops before creating anything" 1 "must be an object ID" "CUSTOM_LOCATION_NAME" "!vm create" "!group create"
run env bash -c 'sed -e "s/^CUSTOM_LOCATIONS_OID=.*/CUSTOM_LOCATIONS_OID=\"bc313c14-388c-4e7d-a58e-70017303ee3b\"/" "$ENV_FILE" > "$ENV_FILE.bad"; ENV_FILE="$ENV_FILE.bad" bash "$0"/infra/01-create-edge-vm.sh' "$REPO"
check "step 1, object ID setting holds the application ID: stops" 1 "application ID of the Custom Locations service" "!vm create"

# ---- rebuilding the settings file (infra/rebuild-env.sh)
deployed() {
  reset; touch "$STUB_DIR/rg"; echo Standard_D8s_v7 > "$STUB_DIR/vmsize"; echo "Enabled 0800" > "$STUB_DIR/schedule"
  echo 040ca937-7748-471b-a3ea-31d1ebd5da8a > "$STUB_DIR/oid"
  printf '%s\n' esehabc123.servicebus.windows.net:9093 es_11111111-2222-3333-4444-555555555555 > "$STUB_DIR/eventstream"
  printf '%s\t%s\n' Microsoft.Compute/virtualMachines vm-windfarm-edge Microsoft.Kubernetes/connectedClusters arc-windfarm-edge \
    Microsoft.IoTOperations/instances aio-windfarm Microsoft.ExtendedLocation/customLocations cl-windfarm-edge \
    Microsoft.Storage/storageAccounts stwindfarm123 Microsoft.DeviceRegistry/schemaRegistries sr-windfarm \
    Microsoft.DeviceRegistry/namespaces adr-windfarm Microsoft.Network/publicIPAddresses vm-windfarm-edgePublicIP > "$STUB_DIR/resources"
}
NEW_ENV="$SCRATCH/rebuilt.env"
deployed; rm -f "$NEW_ENV"
run env ENV_FILE="$NEW_ENV" bash "$REPO"/infra/rebuild-env.sh
OUT="$OUT
file:$(grep -E '^(SUBSCRIPTION_ID|LOCATION|VM_SIZE|VM_AUTO_SHUTDOWN_UTC|STORAGE_ACCOUNT_NAME|SCHEMA_REGISTRY_NAMESPACE|CUSTOM_LOCATIONS_OID|CUSTOM_LOCATION_NAME|EVENTSTREAM_TOPIC|EVENTSTREAM_BOOTSTRAP_SERVER|SIM_IMAGE)=' "$NEW_ENV" | cut -d'#' -f1 | tr -d ' ' | tr '\n' ';')
lines:$(( $(wc -l < "$NEW_ENV") - $(wc -l < "$REPO/config/demo.env.example") ))"
check "rebuild-env: fills the settings file from what is deployed" 0 'SUBSCRIPTION_ID="00000000-0000-0000-0000-000000000000";' 'LOCATION="southcentralus";' 'VM_SIZE="Standard_D8s_v7";' 'VM_AUTO_SHUTDOWN_UTC="0800";' 'STORAGE_ACCOUNT_NAME="stwindfarm123";' 'SCHEMA_REGISTRY_NAMESPACE="sr-windfarm-ns";' 'CUSTOM_LOCATION_NAME="cl-windfarm-edge";' 'CUSTOM_LOCATIONS_OID="040ca937-7748-471b-a3ea-31d1ebd5da8a";' 'EVENTSTREAM_BOOTSTRAP_SERVER="esehabc123.servicebus.windows.net:9093";' 'EVENTSTREAM_TOPIC="es_11111111-2222-3333-4444-555555555555";' 'SIM_IMAGE="windfarm-simulator:1.2.0"' "lines:0" "!WARNING" "!nsg rule" "!vm start"
run env ENV_FILE="$NEW_ENV" bash "$REPO"/infra/01-create-edge-vm.sh --help >/dev/null 2>&1; run env ENV_FILE="$NEW_ENV" bash -c 'source "$0"/config/load-env.sh && require_object_id CUSTOM_LOCATIONS_OID && echo LOADS-OK "$CLUSTER_NAME"' "$REPO"
check "rebuild-env: the file it writes loads" 0 "LOADS-OK arc-windfarm-edge"

run env ENV_FILE="$NEW_ENV" bash "$REPO"/infra/rebuild-env.sh
check "rebuild-env, settings file exists: stops without --force" 1 "Add --force" "!Writing"
deployed; rm -f "$STUB_DIR/oid" "$STUB_DIR/eventstream" "$STUB_DIR/schedule"
run env ENV_FILE="$NEW_ENV" bash "$REPO"/infra/rebuild-env.sh --force
OUT="$OUT
file:$(grep -E '^(CUSTOM_LOCATIONS_OID|EVENTSTREAM_TOPIC|VM_AUTO_SHUTDOWN_UTC)=' "$NEW_ENV" | cut -d'#' -f1 | tr -d ' ' | tr '\n' ';') bak:$([[ -f "$NEW_ENV.bak" ]] && echo kept)"
check "rebuild-env --force, no directory access, no data flow, no shutdown: says what to set by hand" 0 'CUSTOM_LOCATIONS_OID="";' 'EVENTSTREAM_TOPIC="";' 'VM_AUTO_SHUTDOWN_UTC="";' "bak:kept" "Not found in Azure" "CUSTOM_LOCATIONS_OID: this sign-in may not read" "EVENTSTREAM_TOPIC: the data flow"
reset
run env ENV_FILE="$SCRATCH/none.env" bash "$REPO"/infra/rebuild-env.sh rg-other
check "rebuild-env, resource group missing: stops" 1 "Resource group rg-other does not exist" "az account set"

# ---- clean-up (infra/99-cleanup.sh)
export CLEANUP_STATE_FILE="$SCRATCH/cleanup-note"
CLEAN="$REPO/infra/99-cleanup.sh"
azure_state() {       # a complete deployment in Azure
  reset; rm -f "$CLEANUP_STATE_FILE"; touch "$STUB_DIR/rg"
  printf '%s\t%s\n' Microsoft.Compute/virtualMachines vm-windfarm-edge Microsoft.Kubernetes/connectedClusters arc-windfarm-edge \
    Microsoft.IoTOperations/instances aio-windfarm Microsoft.Storage/storageAccounts stwindfarm \
    Microsoft.Network/networkSecurityGroups vm-windfarm-edgeNSG Microsoft.ExtendedLocation/customLocations cl-windfarm-edge > "$STUB_DIR/resources"
  echo aio-windfarm > "$STUB_DIR/instance"; echo Connected > "$STUB_DIR/cluster"
  printf 'azure-iot-operations-ab1cd\naaaaaaaa-0000-0000-0000-00000000e0e0\n' > "$STUB_DIR/extension"
  printf '%s\t%s\t%s\n' /subscriptions/s/providers/Microsoft.Authorization/roleAssignments/sub-reader Reader /subscriptions/s \
    /subscriptions/s/resourceGroups/rg-windfarm-edge/providers/Microsoft.Authorization/roleAssignments/rg-onboard "Kubernetes Cluster - Azure Arc Onboarding" /subscriptions/s/resourceGroups/rg-windfarm-edge > "$STUB_DIR/roles"
}
fabric_state() {      # the demo's workspace, on the second page of the workspace list, with items that are not the demo's
  mkdir -p "$STUB_DIR/fabric"
  echo '{"value":[{"id":"ws-other","displayName":"Sales"}],"continuationUri":"https://api.fabric.microsoft.com/v1/workspaces?continuationToken=abc"}' > "$STUB_DIR/fabric/workspaces.json"
  echo '{"value":[{"id":"ws-demo","displayName":"WindFarmDigitalTwin"}]}' > "$STUB_DIR/fabric/workspaces2.json"
  cat > "$STUB_DIR/fabric/items.json" <<'JSON'
{"value":[
 {"id":"it-eh","type":"Eventhouse","displayName":"WindFarmEH"},
 {"id":"it-kdb","type":"KQLDatabase","displayName":"WindFarmEH"},
 {"id":"it-qs","type":"KQLQueryset","displayName":"WindFarmEH_queryset"},
 {"id":"it-lh","type":"Lakehouse","displayName":"WindFarmLH"},
 {"id":"it-sql","type":"SQLEndpoint","displayName":"WindFarmLH"},
 {"id":"it-es","type":"Eventstream","displayName":"es-windfarm-edge"},
 {"id":"it-nb1","type":"Notebook","displayName":"01_load_reference_data"},
 {"id":"it-nb2","type":"Notebook","displayName":"02_generate_history"},
 {"id":"it-mine","type":"Notebook","displayName":"My own analysis"},
 {"id":"it-rep","type":"Report","displayName":"Sales report"}]}
JSON
  cat > "$STUB_DIR/fabric/access.json" <<'JSON'
{"value":[
 {"id":"u-1","principal":{"id":"u-1","displayName":"Sami","type":"User"},"role":"Admin"},
 {"id":"11111111-2222-3333-4444-555555555555","principal":{"id":"11111111-2222-3333-4444-555555555555","displayName":"vm-windfarm-edge","type":"ServicePrincipal"},"role":"Contributor"},
 {"id":"aaaaaaaa-0000-0000-0000-00000000e0e0","principal":{"id":"aaaaaaaa-0000-0000-0000-00000000e0e0","displayName":"azure-iot-operations-ab1cd","type":"ServicePrincipal"},"role":"Contributor"},
 {"id":"sp-other","principal":{"id":"sp-other","displayName":"reporting-app","type":"ServicePrincipal"},"role":"Member"}]}
JSON
}
order() {             # order A B: true when the first call matching A comes before the first call matching B
  local a b
  a="$(grep -n -m1 -- "$1" "$STUB_DIR/calls.log" | cut -d: -f1)"; b="$(grep -n -m1 -- "$2" "$STUB_DIR/calls.log" | cut -d: -f1)"
  [[ -n "$a" && -n "$b" && "$a" -lt "$b" ]]
}

azure_state; fabric_state
run bash "$CLEAN"
check "clean-up without options: shows what exists and changes nothing" 0 "Nothing was changed" "VM running" "Connected" "aio-windfarm" "Reader on /subscriptions/s" "Eventstream es-windfarm-edge" "Notebook My own analysis" "!group delete" "!iot ops delete" "!--method delete" "!role assignment delete" "!vm start"

azure_state
run bash "$CLEAN" --azure --yes
order "iot ops delete" "group delete" && order "role assignment delete" "group delete" && OUT="$OUT ORDER-OK"
OUT="$OUT note:$(tr '\n' ' ' < "$CLEANUP_STATE_FILE" 2>/dev/null)"
check "--azure: uninstalls, removes both role assignments, deletes the group, in that order" 0 "iot ops delete --name aio-windfarm --resource-group rg-windfarm-edge --include-deps --yes$" "role assignment delete --ids /subscriptions/s/providers/Microsoft.Authorization/roleAssignments/sub-reader" "role assignment delete --ids .*rg-onboard" "group delete --name rg-windfarm-edge --yes$" "Nothing of this deployment is left in Azure" "ORDER-OK" "note:VM_PRINCIPAL_ID=11111111-2222-3333-4444-555555555555 AIO_EXTENSION_NAME=azure-iot-operations-ab1cd AIO_EXTENSION_PRINCIPAL_ID=aaaaaaaa-0000-0000-0000-00000000e0e0" "!vm start" "!--force" "!extension add"

azure_state; echo "VM deallocated" > "$STUB_DIR/power"; echo Offline > "$STUB_DIR/cluster"; touch "$STUB_DIR/connect_on_start"
run bash "$CLEAN" --azure --yes
order "vm start" "iot ops delete" && OUT="$OUT ORDER-OK"
check "--azure with the VM stopped: starts it, waits for the cluster, then uninstalls normally" 0 "vm start" "iot ops delete --name aio-windfarm .*--include-deps --yes$" "group delete" "ORDER-OK" "!--force"

attempts() { OUT="$OUT attempts:$(grep -c "iot ops delete" "$STUB_DIR/calls.log");"; }

# The error of the first real run: Azure shows the cluster as connected, but cannot reach it yet.
azure_state; echo 2 > "$STUB_DIR/unreachable"
run bash "$CLEAN" --azure --yes; attempts
order "iot ops delete" "group delete" && OUT="$OUT ORDER-OK"
check "--azure, Azure cannot reach the cluster yet: tries again until the uninstall gets through" 0 "ClusterNetworkUnavailable" "Trying again in 150 seconds" "attempt 3 of 4" "attempts:3;" "ORDER-OK" "Nothing of this deployment is left in Azure" "!WARNING" "!--force"

azure_state; echo 99 > "$STUB_DIR/unreachable"
run bash "$CLEAN" --azure --yes; attempts
check "--azure, Azure never reaches the cluster: gives up after four attempts and deletes the group" 0 "attempts:4;" "was not uninstalled, because Azure could not reach the cluster" "group delete --name rg-windfarm-edge --yes" "Nothing of this deployment is left in Azure"

azure_state; echo "VM deallocated" > "$STUB_DIR/power"; echo Offline > "$STUB_DIR/cluster"
run bash "$CLEAN" --azure --yes; attempts
check "--azure, cluster stays offline after the VM start: tries with --force, gives up, deletes the group" 0 "vm start" "Waiting up to 10 minutes" "iot ops delete --name aio-windfarm .*--include-deps --yes --force" "attempts:4;" "was not uninstalled" "group delete"

# Azure's status lags behind: shown as offline, but reachable.
azure_state; echo Offline > "$STUB_DIR/cluster"; touch "$STUB_DIR/reachable_anyway"
run bash "$CLEAN" --azure --yes; attempts
check "--azure, cluster shown as offline but reachable: the attempt with --force gets through" 0 "iot ops delete --name aio-windfarm .*--yes --force" "attempts:1;" "group delete" "!WARNING" "!vm start"

# A second run after the VM is gone and the cluster's Azure resources were left.
azure_state; rm -f "$STUB_DIR/power"; echo Offline > "$STUB_DIR/cluster"
run bash "$CLEAN" --azure --yes; attempts
check "--azure, VM gone and cluster resources left: one attempt, no waiting, then the group" 0 "attempts:1;" "was not uninstalled" "group delete --name rg-windfarm-edge --yes" "!vm start" "!Trying again" "!Waiting up to"

# The VM was stopped a moment ago: Azure still shows the cluster as connected.
azure_state; echo "VM deallocated" > "$STUB_DIR/power"
run bash "$CLEAN" --azure --yes
order "vm start" "iot ops delete" && OUT="$OUT ORDER-OK"
check "--azure, VM stopped but cluster still shown as connected: starts the VM first all the same" 0 "vm start" "two minutes" "ORDER-OK" "group delete" "!--force"

azure_state; touch "$STUB_DIR/no_cli_extension"
run bash "$CLEAN" --azure --yes
order "extension add --yes --name azure-iot-ops" "iot ops delete" && OUT="$OUT ORDER-OK"
check "--azure without the CLI extension: installs it before the uninstall" 0 "ORDER-OK" "group delete"

azure_state; : > "$STUB_DIR/instance"
run bash "$CLEAN" --azure --yes
check "--azure, instance already gone: cleans up the cluster by name" 0 "iot ops delete --cluster arc-windfarm-edge --resource-group rg-windfarm-edge --include-deps --yes$" "group delete"

azure_state; touch "$STUB_DIR/uninstall_fails"
run bash "$CLEAN" --azure --yes; attempts
check "--azure, uninstall fails for another reason: no second attempt, warns, still deletes the group" 0 "AuthorizationFailed" "The uninstall of Azure IoT Operations failed" "attempts:1;" "group delete --name rg-windfarm-edge --yes" "!Trying again"

azure_state; touch "$STUB_DIR/group_delete_fails"
run bash "$CLEAN" --azure --yes
check "--azure, group deletion fails: says what is left and ends with exit code 3" 3 "Deleting the resource group failed" "Left for you to do" "vm-windfarm-edge  (Microsoft.Compute/virtualMachines)"

azure_state
run bash "$CLEAN" --azure --yes --no-wait
check "--azure --no-wait: starts the deletion and returns" 0 "group delete --name rg-windfarm-edge --yes --no-wait" "Deletion started"

azure_state; rm -f "$STUB_DIR/rg"
run bash "$CLEAN" --azure --yes
check "--azure, no resource group: nothing to do" 0 "does not exist" "!group delete" "!iot ops delete"

azure_state; printf '%s\t%s\n' Microsoft.Web/sites someones-app Microsoft.Sql/servers someones-db > "$STUB_DIR/resources"
run bash "$CLEAN" --azure --yes
check "--azure, a group that is not the demo's: refuses" 1 "does not look like this demo" "!group delete" "!iot ops delete"

azure_state
run bash "$CLEAN" --azure < /dev/null
check "--azure without --yes and without a terminal: refuses" 1 "Add --yes" "!group delete" "!iot ops delete" "!role assignment delete"

azure_state; fabric_state
run bash "$CLEAN" --fabric --yes
order "items/it-es?hardDelete=true" "items/it-nb1" && order "items/it-nb2" "items/it-qs" && order "items/it-qs" "items/it-lh" && order "items/it-lh" "items/it-eh" && OUT="$OUT ORDER-OK"
OUT="$OUT deleted:$(sort "$STUB_DIR/fabric/deleted" | tr '\n' ' ')END"
check "--fabric: deletes the demo's six items for good, in order, and the two identities' access; leaves the rest" 0 "ORDER-OK" "deleted:11111111-2222-3333-4444-555555555555 aaaaaaaa-0000-0000-0000-00000000e0e0 it-eh it-es it-lh it-nb1 it-nb2 it-qs END" "workspaces?continuationToken=abc" "Left alone" "Notebook My own analysis" "Report Sales report" "roleAssignments/11111111" "!group delete" "!it-mine?" "!items/it-kdb" "!items/it-sql" "!roleAssignments/u-1" "!roleAssignments/sp-other"

azure_state; fabric_state; echo it-lh > "$STUB_DIR/fabric/no_hard"
run bash "$CLEAN" --fabric --yes
check "--fabric, permanent delete refused for the Lakehouse: normal delete, and says where the item is now" 0 "items/it-lh?hardDelete=true" "items/it-lh --output none" "Lakehouse WindFarmLH: deleted, but not permanently" "Recycle bin" "Eventhouse WindFarmEH: deleted$"

azure_state; fabric_state; echo it-eh > "$STUB_DIR/fabric/no_hard"
run bash "$CLEAN" --fabric --yes
check "--fabric, permanent delete refused for the Eventhouse: normal delete, which is final for that type" 0 "items/it-eh --output none" "Eventhouse WindFarmEH: deleted$" "!not permanently" "!Recycle bin"

azure_state; fabric_state; echo it-eh > "$STUB_DIR/fabric/undeletable"
run bash "$CLEAN" --fabric --yes
check "--fabric, an item that cannot be deleted: tries the three routes, reports it, exit code 3" 3 "items/it-eh?hardDelete=true" "eventhouses/it-eh" "Eventhouse WindFarmEH could not be deleted" "Left for you to do"

azure_state; fabric_state; touch "$STUB_DIR/fabric_no_token"
run bash "$CLEAN" --fabric --yes
check "--fabric, no token for the Fabric API: prints the portal steps, deletes nothing" 3 "could not be used from this session" "AADSTS65001" "Manage access" "Left for you to do" "!--method delete"

azure_state; fabric_state; echo '{"value":[{"id":"ws-other","displayName":"Sales"}]}' > "$STUB_DIR/fabric/workspaces.json"
run bash "$CLEAN" --fabric --yes
check "--fabric, workspace not found: nothing to do" 0 "No workspace named WindFarmDigitalTwin" "!--method delete"

azure_state; fabric_state      # the same workspace after Phases 2 to 5, with one report and one model that are not the demo's
python3 - "$STUB_DIR/fabric/items.json" <<'PY'
import json, sys
path = sys.argv[1]; doc = json.load(open(path))
doc["value"] += [
 {"id": "it-nb6", "type": "Notebook", "displayName": "06_build_semantic_model"},
 {"id": "it-nb13", "type": "Notebook", "displayName": "13_command_center"},
 {"id": "it-sm", "type": "SemanticModel", "displayName": "WindFarm Operations"},
 {"id": "it-smlh", "type": "SemanticModel", "displayName": "WindFarmLH"},
 {"id": "it-smx", "type": "SemanticModel", "displayName": "Sales model"},
 {"id": "it-rp", "type": "Report", "displayName": "WindFarm Operations Report"},
 {"id": "it-da", "type": "DataAgent", "displayName": "WindFarmDataAgent"},
 {"id": "it-on", "type": "Ontology", "displayName": "WindFarmOntology"},
 {"id": "it-oa", "type": "OperationsAgent", "displayName": "WindFarmGearboxWatch"},
 {"id": "it-app", "type": "SomeAppType", "displayName": "WindFarmTwin"},
 {"id": "it-cmd", "type": "Eventstream", "displayName": "WindFarmCommands"}]
json.dump(doc, open(path, "w"))
PY
run bash "$CLEAN" --fabric --yes
order "items/it-rp?hardDelete=true" "items/it-sm?hardDelete=true" && order "items/it-oa" "items/it-lh" && order "items/it-da" "items/it-eh" && order "items/it-app" "items/it-lh" && order "items/it-sm?" "items/it-lh" && OUT="$OUT ORDER-OK"
OUT="$OUT deleted:$(sort "$STUB_DIR/fabric/deleted" | tr '\n' ' ')END"
check "--fabric after Phases 2 to 5: the model, the report, the agents, the ontology, the app and every notebook go, before what they read; others stay" 0 "ORDER-OK" \
  "deleted:11111111-2222-3333-4444-555555555555 aaaaaaaa-0000-0000-0000-00000000e0e0 it-app it-cmd it-da it-eh it-es it-lh it-nb1 it-nb13 it-nb2 it-nb6 it-oa it-on it-qs it-rp it-sm END" \
  "SemanticModel Sales model" "Report Sales report" "!items/it-smx" "!items/it-smlh" "!items/it-rep"

azure_state; fabric_state
run bash "$CLEAN" --fabric-workspace --yes
check "--fabric-workspace: deletes the workspace and nothing else" 0 "--method delete --url https://api.fabric.microsoft.com/v1/workspaces/ws-demo --output none" "Workspace deleted" "!items/it-" "!roleAssignments/" "!group delete"

azure_state; fabric_state
run bash "$CLEAN" --all --yes
order "items/it-eh" "group delete" && order "roleAssignments/aaaaaaaa" "iot ops delete" && OUT="$OUT ORDER-OK"
check "--all: Fabric first, while Azure still knows the identities, then Azure" 0 "ORDER-OK" "roleAssignments/11111111" "iot ops delete" "group delete" "keep CUSTOM_LOCATIONS_OID"

# Azure was cleaned up earlier: the identities are gone there, and Fabric no longer shows their names.
azure_state; fabric_state; rm -f "$STUB_DIR/rg" "$STUB_DIR/extension"; touch "$STUB_DIR/no_vm"
printf 'VM_PRINCIPAL_ID=11111111-2222-3333-4444-555555555555\nAIO_EXTENSION_NAME=azure-iot-operations-ab1cd\nAIO_EXTENSION_PRINCIPAL_ID=aaaaaaaa-0000-0000-0000-00000000e0e0\n' > "$CLEANUP_STATE_FILE"
sed -i.bak -e 's/"displayName":"vm-windfarm-edge"/"displayName":""/' -e 's/"displayName":"azure-iot-operations-ab1cd"/"displayName":""/' "$STUB_DIR/fabric/access.json"
run bash "$CLEAN" --fabric --yes
check "--fabric after --azure: finds the identities' access through the saved note" 0 "roleAssignments/11111111-2222-3333-4444-555555555555" "roleAssignments/aaaaaaaa-0000-0000-0000-00000000e0e0" "(identity deleted)" "!roleAssignments/sp-other"

azure_state; fabric_state
run env ENV_FILE=/nonexistent/demo.env SUBSCRIPTION_ID=00000000-0000-0000-0000-000000000000 RESOURCE_GROUP=rg-windfarm-edge bash "$CLEAN"
check "clean-up without demo.env, settings on the command line: works with the default names" 0 "Nothing was changed" "arc-windfarm-edge" "Eventstream es-windfarm-edge"
run env ENV_FILE=/nonexistent/demo.env bash "$CLEAN"
check "clean-up without demo.env and without settings: says what it needs" 1 "give at least SUBSCRIPTION_ID and RESOURCE_GROUP"

azure_state
run bash "$CLEAN" --fabric --fabric-workspace
check "--fabric with --fabric-workspace: refuses the combination" 1 "not both" "!--method delete"
echo vm-windfarm-edge > "$STUB_DIR/hostname"
run bash "$CLEAN" --azure --yes
check "clean-up on the edge VM: stops" 1 "not on the edge VM" "!group delete"

# ---- app/create-app.sh: the Fabric app of Phase 4 is put together from the template, its functions pack
# and the overlay. node, npm and npx are stand-ins (stubs-app); a copy of the app folder is used, so the
# repository gets no app/windfarm-twin.
chmod +x "$HERE"/stubs-app/*
APPDIR="$SCRATCH/app"; CREATE="$APPDIR/create-app.sh"
app_reset() { reset; rm -rf "$APPDIR"; mkdir -p "$APPDIR"; cp -R "$REPO/app/overlay" "$APPDIR/overlay"; cp "$REPO/app/create-app.sh" "$CREATE"; }
app_run() { OUT="$(PATH="$HERE/stubs-app:$PATH" bash "$CREATE" "$@" 2>&1)"; RC=$?; }
W="$APPDIR/windfarm-twin"

app_reset; app_run
OUT="$OUT
app:$(grep -c "TwinApp" "$W/packages/frontend/src/App.tsx") twin:$([[ -f "$W/packages/frontend/src/twin/scene/SceneEngine.ts" ]] && echo yes) fn:$(grep -c "getLiveState" "$W/packages/functions/src/function_app.ts") title:$(grep -c "Northwind Ridge" "$W/packages/frontend/index.html")"
check "create-app, fresh: scaffolds at the pinned version, adds the pack, copies the twin, installs three.js, checks" 0 "create-rayfin@2.0.1 --project-name windfarm-twin --template blankapp" "npm run pack:add -- functions (in windfarm-twin)" "app:[1-9]" "twin:yes" "fn:[1-9]" "title:1" "three@0.187.0" "@types/three@0.187.0" "-w @rayfin-app/functions mssql@12.8.1" "@types/mssql@12.3.0" "npm run typecheck (in windfarm-twin)" "npx rayfin up --workspace WindFarmDigitalTwin" "create-principal.sh"

: > "$STUB_DIR/calls.log"; echo "// edited by hand" > "$W/packages/frontend/src/twin/TwinApp.tsx"; app_run
OUT="$OUT
restored:$(grep -c "edited by hand" "$W/packages/frontend/src/twin/TwinApp.tsx")"
check "create-app, run again: keeps the app, adds nothing twice, copies the overlay again" 0 "keeping it" "already there" "already a dependency" "already a dependency of the functions" "restored:0" "npm run typecheck (in windfarm-twin)" "!create-rayfin" "!pack:add" "!npm install"

: > "$STUB_DIR/calls.log"; app_run --overlay
check "create-app --overlay: copies only" 0 "Copied the twin" "!create-rayfin" "!npm run typecheck (in" "!npm install"

: > "$STUB_DIR/calls.log"; OUT="$(PATH="$HERE/stubs-app:$PATH" FABRIC_WORKSPACE_NAME="WindFarmDigitalTwin-3x9" bash "$CREATE" 2>&1)"; RC=$?
OUT="$OUT
named:$(grep -c "^export const WORKSPACE_NAME = 'WindFarmDigitalTwin-3x9';" "$W/packages/functions/src/config.ts") overlay:$(grep -c "^export const WORKSPACE_NAME = 'WindFarmDigitalTwin';" "$APPDIR/overlay/packages/functions/src/config.ts")"
check "create-app with a generated workspace name: the app's copy names it, the overlay is untouched, the hint names it" 0 "named:1" "overlay:1" "The app looks for the workspace WindFarmDigitalTwin-3x9" "npx rayfin up --workspace WindFarmDigitalTwin-3x9 --item-name WindFarmTwin"

: > "$STUB_DIR/calls.log"; mkdir -p "$SCRATCH/.deploy/m2p"; echo m2p > "$SCRATCH/.deploy/current"
sed -e 's/^FABRIC_WORKSPACE_NAME=.*/FABRIC_WORKSPACE_NAME="WindFarmDigitalTwin-m2p"/' "$ENV_FILE" > "$SCRATCH/.deploy/m2p/demo.env"
OUT="$(env -u ENV_FILE PATH="$HERE/stubs-app:$PATH" bash "$CREATE" 2>&1)"; RC=$?
OUT="$OUT
named:$(grep -c "^export const WORKSPACE_NAME = 'WindFarmDigitalTwin-m2p';" "$W/packages/functions/src/config.ts")"
check "create-app by hand beside a deployment of the runner: the workspace is the current deployment's" 0 "named:1" "The app looks for the workspace WindFarmDigitalTwin-m2p"
rm -rf "$SCRATCH/.deploy"

: > "$STUB_DIR/calls.log"; OUT="$(PATH="$HERE/stubs-app:$PATH" FABRIC_WORKSPACE_NAME="Wind'Farm" bash "$CREATE" 2>&1)"; RC=$?
check "create-app, a workspace name with a quote in it: refused, nothing written" 1 "has a character this script does not write"

# An app made before the Lakehouse route: its functions package has no SQL driver yet.
sed -i 's| "mssql": "12.8.1",||' "$W/packages/functions/package.json"; : > "$STUB_DIR/calls.log"; app_run --overlay
check "create-app --overlay, an update that needs a new library: copies, then says to run without the option" 1 "Copied the twin" "Run this script without --overlay" "!npm install"
: > "$STUB_DIR/calls.log"; app_run
check "create-app, run again on an app without the SQL driver: adds it, and nothing else" 0 "Adding the SQL driver" "-w @rayfin-app/functions mssql@12.8.1" "already a dependency" "npm run typecheck (in windfarm-twin)" "!three@" "!create-rayfin"

app_reset; echo "v20.19.0" > "$STUB_DIR/node_version"; app_run
check "create-app, Node.js 20: stops before anything is created" 1 "Node.js 20.19.0 is too old" "Step 2 of docs/11-deployment-guide-phase4.md" "!create-rayfin"

app_reset; echo "v26.13.1" > "$STUB_DIR/node_version"; app_run
check "create-app, Node.js 26 (what 'nvm install --lts' gives): says it is not on Rayfin's list, and goes on" 0 "Node.js 26.13.1 is not on that list" "nvm install 22" "create-rayfin@2.0.1"

app_reset; echo "v24.11.0" > "$STUB_DIR/node_version"; app_run
check "create-app, Node.js 24: no note" 0 "create-rayfin@2.0.1" "!not on that list"

app_reset; app_run
check "create-app, Node.js 22: no note" 0 "!not on that list" "!too old"

app_reset; echo "10.9.9" > "$STUB_DIR/npm_version"; app_run
check "create-app, npm 10: says what was seen with it, and goes on" 0 "edgesOut" "npm install -g npm@12" "create-rayfin@2.0.1"

app_reset; touch "$STUB_DIR/scaffold_fails"; app_run
check "create-app, the scaffolder creates nothing: stops and says so" 1 "ended without creating" "!pack:add"

app_reset; touch "$STUB_DIR/pack_fails"; app_run
check "create-app, the functions pack creates nothing: stops and says so" 1 "did not create packages/functions" "!typecheck"

app_reset; touch "$STUB_DIR/typecheck_fails"; app_run
check "create-app, the check fails: the app is not called ready" 1 "not ready to deploy" "!The app is ready"

app_reset; mkdir -p "$W"; echo notes > "$W/notes.txt"; app_run
check "create-app, a folder of that name that is no app: leaves it alone" 1 "not a Rayfin project" "!create-rayfin"

app_reset; app_run --force
check "create-app, unknown option: refuses" 1 "Unknown option --force" "!create-rayfin"

app_reset; app_run --overlay
check "create-app --overlay without an app: says to run without the option" 1 "not a Rayfin project"

# ---- app/create-principal.sh: the service principal for the Eventhouse route. az and npx are stand-ins
# (stubs-principal); a copy of the script stands next to a pretend app, so nothing real is touched.
chmod +x "$HERE"/stubs-principal/*
PRDIR="$SCRATCH/principal"; PRINCIPAL="$PRDIR/create-principal.sh"
pr_reset() { reset; rm -rf "$PRDIR"; mkdir -p "$PRDIR/windfarm-twin/rayfin"; echo "id: windfarm-twin" > "$PRDIR/windfarm-twin/rayfin/rayfin.yml"; cp "$REPO/app/create-principal.sh" "$PRINCIPAL"; }
pr_run() { OUT="$(PATH="$HERE/stubs-principal:$PATH" bash "$PRINCIPAL" "$@" 2>&1)"; RC=$?; }
pr_facts() { OUT="$OUT
received:$(tr '\n' ' ' < "$STUB_DIR/secrets_received" 2>/dev/null) file:$([[ -e "$PRDIR/windfarm-twin/rayfin/.env.secrets" ]] && echo left || echo gone) role:$(grep -o '"role": "[A-Za-z]*"' "$STUB_DIR/roles.json" 2>/dev/null)"; }

pr_reset; pr_run; pr_facts
check "create-principal, first run: registration, principal, Viewer role, secret, three secrets to the app" 0 \
  "Workspace WindFarmDigitalTwin is 638251b5" "ad app create --display-name windfarm-twin-eventhouse-reader" "ad sp create --id aaaaaaaa" \
  '"type": "ServicePrincipal"}, "role": "Viewer"' "ad app credential reset" "npx rayfin secret set --env-file rayfin/.env.secrets (in windfarm-twin)" \
  "received:KUSTO_TENANT_ID=11111111-2222-3333-4444-555555555555 KUSTO_CLIENT_ID=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee KUSTO_CLIENT_SECRET=S3cr3t~made.by-the_stub" \
  "file:gone" 'role:"role": "Viewer"' "npx rayfin up" ".add database WindFarmEH viewers ('aadapp=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee;11111111-2222-3333-4444-555555555555')"
SHOWN="$(grep -v '^received:' <<< "$OUT")$(cat "$STUB_DIR/calls.log")"
if grep -q 'S3cr3t' <<< "$SHOWN"; then fail=$((fail+1)); echo "FAIL create-principal: the secret appears in the output or in a command line"; else pass=$((pass+1)); echo "PASS create-principal: the secret is in neither the output nor a command line"; fi

: > "$STUB_DIR/calls.log"; pr_run; pr_facts
check "create-principal, run again: keeps the registration and the role, makes a new secret" 0 "keeping it" "It already has the role Viewer" "ad app credential reset" "npx rayfin secret set" "!ad app create" "!ad sp create" "!--method post" "file:gone"

pr_reset; touch "$STUB_DIR/not_signed_in"; pr_run
check "create-principal, not signed in to Azure: stops" 1 "Not signed in to Azure" "!ad app"

pr_reset; mkdir -p "$SCRATCH/.deploy/m2p"; echo m2p > "$SCRATCH/.deploy/current"
sed -e 's/^FABRIC_WORKSPACE_NAME=.*/FABRIC_WORKSPACE_NAME="WindFarmDigitalTwin-m2p"/' "$ENV_FILE" > "$SCRATCH/.deploy/m2p/demo.env"
OUT="$(env -u ENV_FILE PATH="$HERE/stubs-principal:$PATH" bash "$PRINCIPAL" 2>&1)"; RC=$?; rm -rf "$SCRATCH/.deploy"
check "create-principal by hand beside a deployment of the runner: it looks for the current deployment's workspace" 1 "does not see a workspace named WindFarmDigitalTwin-m2p" "!ad app create"

pr_reset; touch "$STUB_DIR/no_workspace"; pr_run
check "create-principal, the sign-in does not see the workspace: stops before anything is created" 1 "does not see a workspace named WindFarmDigitalTwin" "az login --tenant" "!ad app create"

pr_reset; touch "$STUB_DIR/no_app_rights"; pr_run
check "create-principal, the tenant does not allow app registrations: stops and names the Lakehouse" 1 "The app registration was not created" "Insufficient privileges" "stays on the Lakehouse" "!credential reset"

pr_reset; touch "$STUB_DIR/role_refused"; pr_run
check "create-principal, no right to give the role: stops before a secret is made, and says where to do it by hand" 1 "The role was not given" "Manage access" "!credential reset"

pr_reset; echo 2 > "$STUB_DIR/principal_unknown"; OUT="$(PATH="$HERE/stubs-principal:$PATH" ROLE_WAIT_SECONDS=0 bash "$PRINCIPAL" 2>&1)"; RC=$?; pr_facts
check "create-principal, Fabric does not know the new principal yet: waits, tries again, goes on" 0 "does not know the new principal yet (try 1 of 8)" "(try 2 of 8)" 'role:"role": "Viewer"' "npx rayfin secret set" "file:gone"

pr_reset; echo 99 > "$STUB_DIR/principal_unknown"; OUT="$(PATH="$HERE/stubs-principal:$PATH" ROLE_WAIT_SECONDS=0 ROLE_TRIES=3 bash "$PRINCIPAL" 2>&1)"; RC=$?
check "create-principal, Fabric never learns the principal: stops after the tries, before a secret is made" 1 "(try 2 of 3)" "The role was not given" "principal was not found" "run this script again" "!credential reset"

pr_reset; touch "$STUB_DIR/no_secrets"; pr_run; pr_facts
check "create-principal, the tenant forbids client secrets: stops, hands nothing to the app" 1 "No secret was made" "not allowed as per assigned policy" "!rayfin secret set" "file:gone"

pr_reset; touch "$STUB_DIR/rayfin_signed_out"; pr_run; pr_facts
check "create-principal, Rayfin not signed in: stops, says what to do, leaves no file with the secret" 1 "Rayfin did not take the secrets" "npx rayfin login" "file:gone"

pr_reset; echo aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee > "$STUB_DIR/appid"; echo 99999999-8888-7777-6666-555555555555 > "$STUB_DIR/spid"; pr_run --show
check "create-principal --show, a run that stopped before the role (the first real run): says that there is no role and what to do" 0 "application ID aaaaaaaa" "Role on the workspace: none. Run this script without an option" "!credential reset" "!--method post"

pr_reset; pr_run --show
check "create-principal --show, nothing set up: says so and changes nothing" 0 "No app registration named windfarm-twin-eventhouse-reader" "!ad app create" "!--method post" "!credential"
pr_run; : > "$STUB_DIR/calls.log"; pr_run --show
check "create-principal --show, set up: registration, principal, role and the secrets of the app" 0 "application ID aaaaaaaa" "service principal 99999999" "Role on the workspace: Viewer" "KUSTO_CLIENT_SECRET" "!credential reset" "!--method post"

: > "$STUB_DIR/calls.log"; pr_run --remove
check "create-principal --remove: role, registration and the three secrets" 0 "--method delete --url https://api.fabric.microsoft.com/v1/workspaces/638251b5-0826-4632-b8f1-642e05d39629/roleAssignments/99999999" "ad app delete --id aaaaaaaa" "secret delete KUSTO_TENANT_ID" "secret delete KUSTO_CLIENT_ID" "secret delete KUSTO_CLIENT_SECRET" "reads the Lakehouse"

pr_reset; rm -rf "$PRDIR/windfarm-twin"; pr_run
check "create-principal, no app yet: says to create and deploy it first" 1 "There is no app in" "create-app.sh" "!ad app create"

pr_reset; OUT="$(PATH="$HERE/stubs-principal:$PATH" SUDO_USER=sami bash "$PRINCIPAL" 2>&1)"; RC=$?
check "create-principal with sudo: refuses" 1 "Do not run this with sudo" "!az account"

pr_reset; pr_run --delete
check "create-principal, unknown option: refuses" 1 "Unknown option --delete"

# --- tools/check-scripts.sh, rule 3: no guide and no hint shows a script started directly ---
CKDIR="$SCRATCH/check"
ck_reset() {
  rm -rf "$CKDIR"; mkdir -p "$CKDIR"/tools "$CKDIR"/infra "$CKDIR"/edge/scripts "$CKDIR"/app "$CKDIR"/config "$CKDIR"/docs
  cp "$REPO"/tools/check-scripts.sh "$CKDIR"/tools/
  printf '#!/usr/bin/env bash\n# Helper.\n#   bash infra/good.sh status\necho "Next: bash infra/good.sh start"\n' > "$CKDIR"/infra/good.sh
  printf 'Run `bash infra/good.sh status`.\n' > "$CKDIR"/docs/guide.md
  : > "$STUB_DIR/calls.log"
}
ck_run() { run bash "$CKDIR"/tools/check-scripts.sh; }

ck_reset; ck_run
check "check-scripts, every command through bash, scripts without the execute permission: passes" 0 "ok   infra/good.sh" "ok   docs/guide.md" "!FAIL"

ck_reset; printf 'Then:\n\n```bash\n./infra/good.sh status\n```\n' >> "$CKDIR"/docs/guide.md; ck_run
check "check-scripts, a guide starts a script directly: fails and names the line" 1 "FAIL rule 3: docs/guide.md" "5:./infra/good.sh status"

ck_reset; printf 'Start it with `./infra/good.sh ssh bash ./edge/scripts/x.sh`.\n' >> "$CKDIR"/docs/guide.md; ck_run
check "check-scripts, a direct start inside a sentence: fails" 1 "FAIL rule 3: docs/guide.md"

ck_reset; printf 'echo "Connect with: ./infra/good.sh ssh"\n' >> "$CKDIR"/infra/good.sh; ck_run
check "check-scripts, a hint of a script shows the direct form: fails" 1 "FAIL rule 3: infra/good.sh" "Connect with: ./infra/good.sh ssh"

ck_reset; printf '#!/usr/bin/env bash\n#   infra/usage.sh status      what it does\necho ok\n' > "$CKDIR"/infra/usage.sh; ck_run
check "check-scripts, a usage line without bash in front: fails" 1 "FAIL rule 3: infra/usage.sh" "infra/usage.sh status"

ck_reset; printf 'Type `bash infra/good.sh status`, not `./infra/good.sh status`.\n\n```text\nbash: ./infra/good.sh: Permission denied\n```\n\nFrom the workstation: `bash infra/good.sh ssh bash ./edge/scripts/x.sh`.\n' >> "$CKDIR"/docs/guide.md; ck_run
check "check-scripts, the mistake named as a mistake, the error text, and bash ./ on the VM: pass" 0 "ok   docs/guide.md" "!FAIL"

ck_reset; printf 'bash: ./infra/vm.sh: Permission denied, then I typed ./infra/vm.sh status\n' > "$CKDIR"/docs/phase9-validation-log.md; ck_run
check "check-scripts, a validation log is a record and is not checked" 0 "!validation-log" "!FAIL"

ck_reset; printf '"$REPO_ROOT/infra/good.sh" status\n' > "$CKDIR"/infra/caller.sh; ck_run
check "check-scripts, a script starts another one directly: rule 2 still fails" 1 "FAIL rule 2: infra/caller.sh"

# ---- infra/08-create-command-path.sh: the path for commands from Fabric to the edge (Phase 5a). az is a
# stand-in (stubs-commands) for the Fabric API and for the data flow commands of Azure IoT Operations.
chmod +x "$HERE"/stubs-commands/*
cp_reset() { reset; rm -rf "$REPO/edge/dataflows/rendered"; }
cp_run() { OUT="$(PATH="$HERE/stubs-commands:$PATH" bash "$REPO"/infra/08-create-command-path.sh "$@" 2>&1)"; RC=$?; }
cp_facts() { OUT="$OUT
applied:$(tr -d ' \n' < "$STUB_DIR/applied.json" 2>/dev/null) definition:$(python3 -c 'import base64, json, sys
body = json.load(open(sys.argv[1])); part = body["definition"]["parts"][0]
print(body["displayName"], part["path"], part["payloadType"], json.dumps(json.loads(base64.b64decode(part["payload"])), separators=(",", ":")))' "$STUB_DIR/posted.json" 2>/dev/null)"; }

cp_reset; OUT="$(PATH="$HERE/stubs-commands:$PATH" COMMAND_DATAFLOW_MODE=Disabled bash "$REPO"/infra/08-create-command-path.sh 2>&1)"; RC=$?; cp_facts
check "command path, switched off: the same data flow with the mode Disabled, and it says so" 0 'applied:{"mode":"Disabled","operations":' "created switched off"

cp_reset; OUT="$(PATH="$HERE/stubs-commands:$PATH" COMMAND_DATAFLOW_MODE=off bash "$REPO"/infra/08-create-command-path.sh 2>&1)"; RC=$?
check "command path, a mode that is neither: refused before the data flow is applied" 1 "It is Enabled or Disabled" "!dataflow apply"

cp_reset; cp_run; cp_facts
check "command path, nothing there: eventstream from its definition, endpoint with the consumer group, data flow from Kafka to the control topic" 0 \
  "Creating the eventstream" "--method post --url https://api.fabric.microsoft.com/v1/workspaces/638251b5-0826-4632-b8f1-642e05d39629/eventstreams" \
  'definition:WindFarmCommands eventstream.json InlineBase64 {"sources":\[{"name":"CommandIn","type":"CustomEndpoint","properties":{}}\],"destinations":\[{"name":"CommandOut","type":"CustomEndpoint","properties":{},"inputNodes":\[{"name":"WindFarmCommands-stream"}\]}\],"streams":\[{"name":"WindFarmCommands-stream","type":"DefaultStream","properties":{},"inputNodes":\[{"name":"CommandIn"}\]}\]' \
  "iot ops dataflow endpoint create fabric-realtime .*--name fabric-commands --host esehns-abc123.servicebus.windows.net:9093 --auth-type SystemAssignedManagedIdentity --group-id CommandOut-cg" \
  "iot ops dataflow apply .*--profile default --name fabric-to-windfarm-control" \
  'applied:{"mode":"Enabled","operations":\[{"operationType":"Source","sourceSettings":{"endpointRef":"fabric-commands","serializationFormat":"Json","dataSources":\["es_0f0f0f0f"\]}},{"operationType":"Destination","destinationSettings":{"endpointRef":"default","dataDestination":"contoso/windfarm/northwind-ridge/_control/request"}}\]}' \
  "bash infra/vm.sh ssh bash ./edge/scripts/mqtt-peek.sh" "!K3y" "!SharedAccessKey"

cp_reset; touch "$STUB_DIR/eventstream"; cp_run
check "command path, an eventstream of that name exists (made by hand): used as it is, not created again" 0 "It exists: eeeeeeee" "!--method post" "iot ops dataflow endpoint create fabric-realtime" "iot ops dataflow apply"

cp_reset; touch "$STUB_DIR/create_refused"; cp_run
check "command path, Fabric refuses the definition: says what Fabric said and how to make it by hand, changes nothing on the edge" 3 \
  "Fabric did not create the eventstream from its definition. It said: .*InvalidDefinition" "Add source, Custom endpoint, name CommandIn" "Add destination, Custom endpoint, name CommandOut" "Then run this script again" "!iot ops dataflow"

cp_reset; touch "$STUB_DIR/eventstream" "$STUB_DIR/no_destination"; cp_run
check "command path, the eventstream has no custom endpoint to read from: stops before the edge" 3 "no custom endpoint as a destination" "Add destination, Custom endpoint" "!iot ops dataflow"

cp_reset; echo 2 > "$STUB_DIR/connection_not_ready"; cp_run
check "command path, the connection of a new destination is not ready at once: asks again and goes on" 0 "The edge reads from: esehns-abc123.servicebus.windows.net:9093" "iot ops dataflow apply"

cp_reset; echo 99 > "$STUB_DIR/connection_not_ready"; touch "$STUB_DIR/eventstream"; cp_run
check "command path, the connection never comes: stops with what Fabric said" 1 "Fabric did not give the connection of the destination: .*not ready" "!iot ops dataflow"

cp_reset; cp_run --show
check "command path --show, nothing there: says so and changes nothing" 0 "Eventstream: none" "!--method post" "!iot ops"

cp_reset; cp_run; : > "$STUB_DIR/calls.log"; cp_run --show
check "command path --show, all there: eventstream, what the edge reads from, endpoint and data flow; changes nothing" 0 \
  "It exists: eeeeeeee" "consumer group:     CommandOut-cg" "fabric-commands .*Succeeded" "fabric-to-windfarm-control .*Enabled" "!--method post" "!endpoint create" "!dataflow apply" "!K3y"

: > "$STUB_DIR/calls.log"; cp_run --remove
check "command path --remove: data flow, endpoint, eventstream, and a word on turbines still curtailed" 0 \
  "iot ops dataflow delete .*--name fabric-to-windfarm-control" "iot ops dataflow endpoint delete .*--name fabric-commands" \
  "--method delete --url https://api.fabric.microsoft.com/v1/workspaces/638251b5-0826-4632-b8f1-642e05d39629/eventstreams/eeeeeeee" "simctl.sh release all"

cp_reset; touch "$STUB_DIR/no_workspace"; cp_run
check "command path, the workspace is not visible to the sign-in: stops and names the setting" 1 "No workspace named WindFarmDigitalTwin" "FABRIC_WORKSPACE_NAME" "!--method post" "!iot ops"

cp_reset; cp_run --delete
check "command path, unknown option: refuses" 1 "Unknown option --delete" "!az rest"
rm -rf "$REPO/edge/dataflows/rendered"

# ---- infra/06-connect-edge-to-fabric.sh: the telemetry's endpoint and data flow, also when it is run again
# (Phase 5c, for the seventh topic). The same stand-in for az.
ENV6="$SCRATCH/demo6.env"
sed -e 's/^EVENTSTREAM_BOOTSTRAP_SERVER=""/EVENTSTREAM_BOOTSTRAP_SERVER="esehtelemetry1.servicebus.windows.net:9093"/' -e 's/^EVENTSTREAM_TOPIC=""/EVENTSTREAM_TOPIC="esehtelemetry1_eh"/' "$ENV_FILE" > "$ENV6"
c6_run() { OUT="$(PATH="$HERE/stubs-commands:$PATH" ENV_FILE="$ENV6" bash "$REPO"/infra/06-connect-edge-to-fabric.sh "$@" 2>&1)"; RC=$?
  OUT="$OUT
applied:$(tr -d ' \n' < "$STUB_DIR/applied.json" 2>/dev/null) calls:$(grep -c "" "$STUB_DIR/calls.log" 2>/dev/null) installs:$(grep -c "extension add" "$STUB_DIR/calls.log" 2>/dev/null)"; }
c6_deployed() { echo "$1" > "$STUB_DIR/telemetry_topic"; echo "$2" > "$STUB_DIR/telemetry_host"; }

cp_reset; c6_run
check "connect, first run: endpoint by managed identity, data flow with the seven topics, no search for an extension" 0 \
  "iot ops dataflow endpoint create fabric-realtime .*--name fabric-eventstream --host esehtelemetry1.servicebus.windows.net:9093 --auth-type SystemAssignedManagedIdentity" \
  "iot ops dataflow apply .*--profile default --name windfarm-to-fabric" \
  'applied:{"mode":"Enabled","operations":\[{"operationType":"Source","sourceSettings":{"endpointRef":"default","serializationFormat":"Json","dataSources":\["contoso/windfarm/+/+/telemetry","contoso/windfarm/+/+/weather","contoso/windfarm/+/+/alarm","contoso/windfarm/+/+/state","contoso/windfarm/+/+/asset","contoso/windfarm/+/+/heartbeat","contoso/windfarm/+/+/command"\]}},{"operationType":"Destination","destinationSettings":{"endpointRef":"fabric-eventstream","dataDestination":"esehtelemetry1_eh"}}\]}' \
  "It forwards 7 topics: telemetry weather alarm state asset heartbeat command" "installs:0" "!WARNING" "!exists"

cp_reset; c6_deployed esehtelemetry1_eh ESEHtelemetry1.servicebus.windows.net:9093; c6_run
check "connect, run again with the eventstream it already sends to: says so and writes both anew" 0 "The data flow windfarm-to-fabric exists" \
  "It sends to:       esehtelemetry1_eh at ESEHtelemetry1.servicebus.windows.net:9093" "The same eventstream" "iot ops dataflow endpoint create fabric-realtime" "iot ops dataflow apply" "contoso/windfarm/+/+/command" "installs:0" "!WARNING"

cp_reset; c6_deployed es_11111111-2222-3333-4444-555555555555 esehtelemetry1.servicebus.windows.net:9093; c6_run
check "connect, the settings name another topic than the running data flow: stops before anything is written" 1 "name another eventstream than the one the data flow sends to" \
  "It sends to:       es_11111111-2222-3333-4444-555555555555" "The settings name: esehtelemetry1_eh" "Nothing was changed" "bash infra/rebuild-env.sh --force" "bash infra/06-connect-edge-to-fabric.sh --new-eventstream" \
  "!endpoint create" "!dataflow apply" "applied: "

cp_reset; c6_deployed esehtelemetry1_eh esehother9.servicebus.windows.net:9093; c6_run
check "connect, the settings name another host: stops as well" 1 "name another eventstream" "!endpoint create" "!dataflow apply"

cp_reset; c6_deployed es_11111111-2222-3333-4444-555555555555 esehold0.servicebus.windows.net:9093; c6_run --new-eventstream
check "connect --new-eventstream: moves the data flow, and says where the telemetry goes now" 0 "The telemetry goes to esehtelemetry1_eh at esehtelemetry1.servicebus.windows.net:9093 from now on" "iot ops dataflow endpoint create fabric-realtime" 'dataDestination":"esehtelemetry1_eh"'

cp_reset; touch "$STUB_DIR/no_cli_extension"; c6_run
check "connect, the CLI has no extension yet: installs it once, without the search for a newer one" 0 "Installing the Azure CLI extension azure-iot-ops" "installs:1" "iot ops dataflow apply" "!upgrade"

cp_reset; touch "$STUB_DIR/no_cli_extension" "$STUB_DIR/no_network"; c6_run
check "connect, no extension and no network: stops and says what to run" 1 "could not be installed" "az extension add --name azure-iot-ops" "!dataflow apply"

cp_reset; c6_run --force
check "connect, an option it does not know: stops" 1 "Unknown option --force" "calls: installs:"

cp_reset; sed -i 's/^EVENTSTREAM_TOPIC=.*/EVENTSTREAM_TOPIC="my-topic"/' "$ENV6"; c6_run
check "connect, first run with a topic that does not look like one: warns and goes on" 0 "EVENTSTREAM_TOPIC is 'my-topic'" "start with 'es'" "iot ops dataflow apply"
rm -rf "$REPO/edge/dataflows/rendered"

# The search for a newer extension, which only step 4 still makes, has no time limit of its own. A stand-in
# for az that never answers it, and the real timeout.
SLOW="$SCRATCH/slow"; mkdir -p "$SLOW"
printf '#!/usr/bin/env bash\necho "az $*" >> "$STUB_DIR/calls.log"\ncase "$*" in "extension add --upgrade"*) exec sleep 60 ;; esac\n' > "$SLOW/az"; chmod +x "$SLOW/az"
cp_reset; run env PATH="$SLOW:${PATH#"$HERE/stubs:"}" EXTENSION_SEARCH_SECONDS=1 bash -c 'source "$0"/config/load-env.sh && need_iot_ops_extension current && echo WENT-ON' "$REPO"
check "the search for a newer extension never answers: given up after its time, and the script goes on with the installed one" 0 "did not finish. Going on with the installed one" "WENT-ON"
cp_reset; run env PATH="$SLOW:${PATH#"$HERE/stubs:"}" bash -c 'source "$0"/config/load-env.sh && need_iot_ops_extension && echo WENT-ON; cat "$STUB_DIR/calls.log"' "$REPO"
check "an installed extension is used as it is: one local question, no search" 0 "WENT-ON" "az extension show --name azure-iot-ops --output none" "!extension add"

# ---- infra/09-remediation-agent.sh: the operations agent's instructions and action (Phase 5b). Here: its
# options, who may run it, and that the token stays out of sight. What it does with the Fabric API is tested
# against a stand-in that speaks HTTP, in simulator/tests/test_phase5b.py. FABRIC_API points to a port
# where nothing listens, so no scenario can reach Fabric.
chmod +x "$HERE"/stubs-agent/*
ra_reset() { reset; echo user > "$STUB_DIR/signed_in_as"; }
ra_run() { OUT="$(PATH="$HERE/stubs-agent:$PATH" FABRIC_API="http://127.0.0.1:9/v1" AGENT_SAVE_DIR="$SCRATCH/saved" bash "$REPO"/infra/09-remediation-agent.sh "$@" 2>&1)"; RC=$?; }

ra_reset; ra_run
check "agent, the Fabric API cannot be reached: says so, points to the way by hand, shows no token" 3 \
  "Phase 5b instructions and the action" "ERROR: Could not reach the Fabric API at http://127.0.0.1:9/v1" "Do it by hand instead: step 4 of docs/13-deployment-guide-phase5b.md" \
  "account get-access-token --resource https://api.fabric.microsoft.com --query accessToken --output tsv" "!S3cret"

ra_reset; ra_run --show
check "agent --show, the Fabric API cannot be reached: says so, and does not speak of doing it by hand" 3 "how it is set up" "Could not reach the Fabric API" "!by hand" "!S3cret"

ra_reset; ra_run --rehearse WT-07
check "agent --rehearse WT-07: the turbine reaches the tool" 3 "Rehearsal: notebook 12_send_edge_command as a job, for WT-07" "Could not reach the Fabric API" "!S3cret"

ra_reset; ra_run --rehearse
check "agent --rehearse without a turbine: asks for it, asks for no token" 1 "Name the turbine: bash infra/09-remediation-agent.sh --rehearse WT-07" "!get-access-token"

ra_reset; ra_run --restore
check "agent --restore without a file: asks for it" 1 "Name the file: bash infra/09-remediation-agent.sh --restore" "!get-access-token"

ra_reset; ra_run --restore "$SCRATCH/nothing.json"
check "agent --restore with a file that is not there: says where the saved ones are" 1 "No file .*nothing.json" "fabric/operations-agent/saved/" "!get-access-token"

ra_reset; ra_run --delete
check "agent, unknown option: refuses" 1 "Unknown option --delete. Use no option, --show, --save, --rehearse TURBINE or --restore FILE." "!az account"

ra_reset; ra_run --save
check "agent --save, the Fabric API cannot be reached: says so, writes no file" 3 "its definition to a file" "Could not reach the Fabric API" "!Saved" "!S3cret"

ra_reset; : > "$STUB_DIR/signed_in_as"; ra_run
check "agent, the Azure CLI is not signed in: says how to sign in" 1 "The Azure CLI is not signed in. Run: az login" "!get-access-token"

ra_reset; echo servicePrincipal > "$STUB_DIR/signed_in_as"; ra_run
check "agent, signed in as a service principal: refuses, because Fabric takes these calls from a user only" 1 "signed in as a servicePrincipal, not as you" "!get-access-token"

ra_reset; touch "$STUB_DIR/token_refused"; ra_run
check "agent, no token for the Fabric API: says what the sign-in said" 1 "The Azure CLI gave no token for the Fabric API: .*AADSTS50076" "az login"

echo; echo "passed $pass, failed $fail"; [[ $fail -eq 0 ]]
