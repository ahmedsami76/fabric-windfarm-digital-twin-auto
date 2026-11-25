#!/usr/bin/env bash
# Clean-up (run on your workstation or in Azure Cloud Shell, signed in as yourself).
# Removes what a deployment of this repository created, in Azure and in Fabric.
#
#   bash infra/99-cleanup.sh                     show what exists and what would be removed; changes nothing
#   bash infra/99-cleanup.sh --azure             uninstall Azure IoT Operations, remove the VM identity's role
#                                                assignments, delete the resource group with everything in it
#   bash infra/99-cleanup.sh --fabric            delete the demo's items in the Fabric workspace (eventstream,
#                                                Eventhouse, Lakehouse, notebooks) and the workspace access of
#                                                the two edge identities; other items are left alone
#   bash infra/99-cleanup.sh --fabric-workspace  delete the whole Fabric workspace instead
#   bash infra/99-cleanup.sh --all               --fabric, then --azure
#
#   --yes        do not ask for confirmation
#   --no-wait    start the deletion of the resource group and return at once
#
# The script works with the first and with the current version of the repository, and without
# any other file of it: it needs only config/demo.env. If that file is lost, give the settings
# on the command line, for example:
#   SUBSCRIPTION_ID=... RESOURCE_GROUP=rg-windfarm-edge bash 99-cleanup.sh --azure
# It needs no SSH access to the VM and changes no file of the repository. With --azure it writes
# one small note, ~/.windfarm-demo-cleanup, with the IDs of the two edge identities, so that a
# later --fabric can still remove their workspace access after Azure has forgotten them.
set -euo pipefail

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
usage() { sed -n '2,/^set -euo pipefail/p' "${BASH_SOURCE[0]}" | grep '^#' | sed 's/^# \{0,1\}//'; }
# The Azure CLI prints "None" for a missing value in some versions and nothing in others.
value() { if [[ "${1:-}" == "None" ]]; then printf ''; else printf '%s' "${1:-}"; fi; }

# ---- arguments ---------------------------------------------------------------------------
DO_AZURE=""; DO_FABRIC=""; DO_WORKSPACE=""; ASSUME_YES=""; NO_WAIT=""
for arg in "$@"; do
  case "$arg" in
    --azure)            DO_AZURE=yes ;;
    --fabric)           DO_FABRIC=yes ;;
    --fabric-workspace) DO_WORKSPACE=yes ;;
    --all)              DO_AZURE=yes; DO_FABRIC=yes ;;
    --yes|-y)           ASSUME_YES=yes ;;
    --no-wait)          NO_WAIT=yes ;;
    -h|--help)          usage; exit 0 ;;
    *)                  usage; exit 2 ;;
  esac
done
[[ -z "$DO_FABRIC" || -z "$DO_WORKSPACE" ]] || die "Give --fabric (the demo's items) or --fabric-workspace (the whole workspace), not both."

# ---- settings ----------------------------------------------------------------------------
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$HERE/../config/demo.env}"
if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
elif [[ -z "${SUBSCRIPTION_ID:-}" || -z "${RESOURCE_GROUP:-}" ]]; then
  die "$ENV_FILE not found. Point ENV_FILE at your demo.env, or give at least SUBSCRIPTION_ID and RESOURCE_GROUP in front of the command."
fi
[[ -n "${SUBSCRIPTION_ID:-}" ]] || die "SUBSCRIPTION_ID is empty."
[[ -n "${RESOURCE_GROUP:-}" ]] || die "RESOURCE_GROUP is empty."
: "${VM_NAME:=vm-windfarm-edge}" "${CLUSTER_NAME:=arc-windfarm-edge}" "${AIO_INSTANCE_NAME:=aio-windfarm}"
: "${STORAGE_ACCOUNT_NAME:=}" "${FABRIC_WORKSPACE_NAME:=WindFarmDigitalTwin}" "${FABRIC_LAKEHOUSE_NAME:=WindFarmLH}"
# Fixed names from the deployment guide. Set them in front of the command if you chose others.
: "${EVENTHOUSE_NAME:=WindFarmEH}" "${EVENTSTREAM_NAME:=es-windfarm-edge}" "${COMMAND_EVENTSTREAM_NAME:=WindFarmCommands}"
NOTEBOOK_NAMES="90_deployment_gate 01_load_reference_data 02_generate_history 03_refresh_forecast 04_question_bank 05_build_model_tables 06_build_semantic_model 07_model_acceptance 08_build_report 09_build_data_agent 10_test_data_agent 11_build_ontology 12_send_edge_command 13_command_center"
# The items of Phases 2 to 5, by the names the guides and notebooks give them.
: "${SEMANTIC_MODEL_NAME:=WindFarm Operations}" "${REPORT_NAME:=WindFarm Operations Report}" "${DATA_AGENT_NAME:=WindFarmDataAgent}"
: "${ONTOLOGY_NAME:=WindFarmOntology}" "${OPERATIONS_AGENT_NAME:=WindFarmGearboxWatch}" "${APP_NAME:=WindFarmTwin}"
# How long to wait for a stopped VM to bring the cluster back online, in minutes.
: "${CONNECT_WAIT_MINUTES:=10}"
# How often the uninstall is tried while Azure cannot reach the cluster, and the pause in between.
: "${UNINSTALL_ATTEMPTS:=4}" "${UNINSTALL_RETRY_SECONDS:=150}"
# Where --azure notes the edge identities, so that a later --fabric can still find their workspace access.
STATE_FILE="${CLEANUP_STATE_FILE:-$HOME/.windfarm-demo-cleanup}"

FABRIC_RESOURCE="https://api.fabric.microsoft.com"
FABRIC_API="$FABRIC_RESOURCE/v1"
FABRIC_ERR_FILE="$(mktemp)"       # what the last failed call to the Fabric API said
UNINSTALL_LOG="$(mktemp)"         # what the last uninstall attempt printed
trap 'rm -f "$FABRIC_ERR_FILE" "$UNINSTALL_LOG"' EXIT
CLUSTER_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Kubernetes/connectedClusters/${CLUSTER_NAME}"
LEFT_TO_DO=()

command -v az >/dev/null 2>&1 || die "The Azure CLI (az) is required."
if [[ "$(hostname 2>/dev/null || true)" == "$VM_NAME" ]]; then
  die "This script runs on your workstation or in Azure Cloud Shell, not on the edge VM."
fi
LOGIN_TYPE="$(az account show --query user.type --output tsv 2>/dev/null || true)"
[[ -n "$LOGIN_TYPE" ]] || die "The Azure CLI is not signed in. Run: az login"
if [[ "$LOGIN_TYPE" != "user" && -z "${ALLOW_NON_USER_LOGIN:-}" ]]; then
  die "The Azure CLI is signed in as a $LOGIN_TYPE. Sign in as yourself: az login"
fi
az account set --subscription "$SUBSCRIPTION_ID"

# confirm PROMPT EXPECTED: asks the user to type EXPECTED, unless --yes was given.
confirm() {
  local answer
  [[ -z "$ASSUME_YES" ]] || return 0
  [[ -t 0 ]] || die "This needs a confirmation and there is no terminal to ask on. Add --yes to run without questions."
  read -r -p "    $1: " answer
  [[ "$answer" == "$2" ]] || die "Not confirmed. Nothing was deleted."
}

# ============================================================================== Azure
rg_exists() { [[ "$(az group exists --name "$RESOURCE_GROUP" --output tsv 2>/dev/null)" == "true" ]]; }
vm_power() {
  value "$(az vm show --show-details --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --query powerState --output tsv 2>/dev/null || true)"
}
cluster_status() {
  value "$(az resource show --ids "$CLUSTER_ID" --query properties.connectivityStatus --output tsv 2>/dev/null || true)"
}
instance_name() {
  value "$(az resource list --resource-group "$RESOURCE_GROUP" --resource-type Microsoft.IoTOperations/instances \
    --query "[0].name" --output tsv 2>/dev/null || true)"
}
rg_resources() {      # one resource per line: type <TAB> name
  az resource list --resource-group "$RESOURCE_GROUP" --query "[].[type, name]" --output tsv 2>/dev/null | sort || true
}
# Sets VM_PRINCIPAL_ID, AIO_EXTENSION_NAME and AIO_EXTENSION_PRINCIPAL_ID from Azure, as far as they still exist.
read_identities() {
  local both
  VM_PRINCIPAL_ID="$(value "$(az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
    --query identity.principalId --output tsv 2>/dev/null || true)")"
  # The CLI prints the two values on two lines.
  both="$(az rest --method get \
    --url "https://management.azure.com${CLUSTER_ID}/providers/Microsoft.KubernetesConfiguration/extensions?api-version=2023-05-01" \
    --query "value[?properties.extensionType=='microsoft.iotoperations'] | [0].[name, identity.principalId]" \
    --output tsv 2>/dev/null || true)"
  AIO_EXTENSION_NAME="$(value "$(sed -n 1p <<< "$both")")"
  AIO_EXTENSION_PRINCIPAL_ID="$(value "$(sed -n 2p <<< "$both")")"
}
# Fills in, from the note of an earlier --azure run, what Azure can no longer tell.
read_saved_identities() {
  local key val
  [[ -f "$STATE_FILE" ]] || return 0
  while IFS='=' read -r key val; do
    case "$key" in
      VM_PRINCIPAL_ID)            [[ -n "${VM_PRINCIPAL_ID:-}" ]] || VM_PRINCIPAL_ID="$val" ;;
      AIO_EXTENSION_NAME)         [[ -n "${AIO_EXTENSION_NAME:-}" ]] || AIO_EXTENSION_NAME="$val" ;;
      AIO_EXTENSION_PRINCIPAL_ID) [[ -n "${AIO_EXTENSION_PRINCIPAL_ID:-}" ]] || AIO_EXTENSION_PRINCIPAL_ID="$val" ;;
    esac
  done < "$STATE_FILE"
}
save_identities() {
  [[ -n "${VM_PRINCIPAL_ID}${AIO_EXTENSION_PRINCIPAL_ID}" ]] || return 0
  printf 'VM_PRINCIPAL_ID=%s\nAIO_EXTENSION_NAME=%s\nAIO_EXTENSION_PRINCIPAL_ID=%s\n' \
    "$VM_PRINCIPAL_ID" "$AIO_EXTENSION_NAME" "$AIO_EXTENSION_PRINCIPAL_ID" > "$STATE_FILE" 2>/dev/null \
    || warn "Could not write $STATE_FILE. Run --fabric before the identities are gone from Azure, or remove their workspace access in the Fabric portal."
}
# The VM identity's role assignments, one per line: id <TAB> role <TAB> scope
vm_role_assignments() {
  [[ -n "${VM_PRINCIPAL_ID:-}" ]] || return 0
  az role assignment list --all --fill-principal-name false \
    --query "[?principalId=='${VM_PRINCIPAL_ID}'].[id, roleDefinitionName, scope]" --output tsv 2>/dev/null || true
}

describe_azure() {
  local resources power status instance roles
  log "Azure: resource group $RESOURCE_GROUP"
  if ! rg_exists; then
    info "The resource group does not exist. Nothing to remove in Azure."
    return 0
  fi
  resources="$(rg_resources)"
  power="$(vm_power)"; status="$(cluster_status)"; instance="$(instance_name)"
  info "Resources in the group:     $(grep -c . <<< "$resources" || true)"
  info "VM $VM_NAME:        ${power:-not found}"
  info "Cluster $CLUSTER_NAME:  ${status:-not found}"
  info "Azure IoT Operations:       ${instance:-no instance}"
  read_identities
  roles="$(vm_role_assignments)"
  if [[ -n "$roles" ]]; then
    info "Role assignments of the VM identity:"
    while IFS=$'\t' read -r _ role scope; do info "  $role on $scope"; done <<< "$roles"
  fi
  info "--azure would: uninstall Azure IoT Operations (starting the VM first if it is stopped), remove these"
  info "role assignments, and delete the resource group with everything in it."
}

# Azure IoT Operations is uninstalled before the resource group is deleted, the order Microsoft
# documents. Every step of the uninstall has to reach the cluster through its Azure Arc agents.
# After a VM start that takes some minutes, also after Azure shows the cluster as Connected, so
# the uninstall is tried again while Azure reports that it cannot reach the cluster. If it never
# can, the clean-up goes on: the cluster is deleted with the VM, so nothing is left behind on it.
uninstall_iot_operations() {
  local status instance power waited=0 attempt=1
  local -a args
  status="$(cluster_status)"
  instance="$(instance_name)"
  if [[ -z "$status" ]]; then
    info "No Arc-enabled cluster in the resource group: nothing to uninstall."
    return 0
  fi
  if [[ -z "$instance" && -z "${AIO_EXTENSION_NAME:-}" ]]; then
    info "Azure IoT Operations is not installed on the cluster: nothing to uninstall."
    return 0
  fi
  # A stopped VM is started first, whatever Azure still says about the cluster: the status
  # "Connected" stays for some minutes after the VM has stopped.
  power="$(vm_power)"
  if [[ -n "$power" && "$power" != "VM running" ]]; then
    log "Starting the VM (it is: $power), so that Azure IoT Operations can be uninstalled in an orderly way"
    if az vm start --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --output none; then
      info "Giving K3s and the Azure Arc agents two minutes to start"
      sleep 120
    else
      warn "The VM could not be started."
    fi
    status="$(cluster_status)"
    power="$(vm_power)"
  fi
  if [[ "$status" != "Connected" && "$power" == "VM running" ]]; then
    info "Waiting up to $CONNECT_WAIT_MINUTES minutes for the cluster to connect"
    while [[ "$status" != "Connected" && "$waited" -lt $((CONNECT_WAIT_MINUTES * 3)) ]]; do
      sleep 20
      waited=$((waited + 1))
      status="$(cluster_status)"
    done
  fi
  if ! az extension show --name azure-iot-ops --output none 2>/dev/null; then
    info "Installing the Azure CLI extension azure-iot-ops"
    az extension add --yes --name azure-iot-ops --output none || warn "The extension azure-iot-ops could not be installed."
  fi

  while true; do
    instance="$(instance_name)"
    if [[ -n "$instance" ]]; then args=(--name "$instance"); else args=(--cluster "$CLUSTER_NAME"); fi
    args+=(--resource-group "$RESOURCE_GROUP" --include-deps --yes)
    # Without --force the command refuses when Azure shows the cluster as not connected. That
    # status can lag behind, so the attempt is made all the same. --force skips only that check:
    # the uninstall still has to reach the cluster.
    [[ "$status" == "Connected" ]] || args+=(--force)
    log "Uninstalling Azure IoT Operations and its dependencies from the cluster (attempt $attempt of $UNINSTALL_ATTEMPTS; cluster: $status)"
    if az iot ops delete "${args[@]}" 2>&1 | tee "$UNINSTALL_LOG"; then
      return 0
    fi
    if ! grep -q -E "ClusterNetworkUnavailable|hybrid connection|not connected to Azure" "$UNINSTALL_LOG"; then
      warn "The uninstall of Azure IoT Operations failed; the error is above. Going on: deleting the resource group removes the VM, the cluster on it and the Azure resources of Azure IoT Operations."
      return 0
    fi
    # Azure could not reach the cluster. Waiting helps only while the VM is running.
    if [[ "$attempt" -ge "$UNINSTALL_ATTEMPTS" || "$(vm_power)" != "VM running" ]]; then
      break
    fi
    info "Azure cannot reach the cluster yet. After a VM start the Azure Arc agents need some minutes to connect."
    info "Trying again in $UNINSTALL_RETRY_SECONDS seconds."
    sleep "$UNINSTALL_RETRY_SECONDS"
    attempt=$((attempt + 1))
    status="$(cluster_status)"
  done
  warn "Azure IoT Operations was not uninstalled, because Azure could not reach the cluster. Going on: deleting the resource group removes the VM, the cluster on it and the Azure resources of Azure IoT Operations, so nothing of it is left on a cluster."
}

remove_vm_role_assignments() {
  local roles id role scope
  roles="$(vm_role_assignments)"
  if [[ -z "$roles" ]]; then
    info "No role assignments of the VM identity found."
    return 0
  fi
  log "Removing the role assignments of the VM identity"
  while IFS=$'\t' read -r id role scope; do
    [[ -n "$id" ]] || continue
    if az role assignment delete --ids "$id" --output none; then
      info "$role on $scope"
    else
      warn "Could not remove '$role' on $scope."
      LEFT_TO_DO+=("Azure portal: remove the role assignment '$role' of the deleted VM identity on $scope (Access control (IAM), shown as 'Identity not found').")
    fi
  done <<< "$roles"
}

azure_cleanup() {
  local resources
  log "Azure: resource group $RESOURCE_GROUP in subscription $SUBSCRIPTION_ID"
  if ! rg_exists; then
    info "The resource group does not exist. Nothing to remove in Azure."
    return 0
  fi
  resources="$(rg_resources)"
  # A guard against a wrong RESOURCE_GROUP: the group must be empty or hold something of this demo.
  if [[ -n "$resources" ]] && ! grep -q -E "/(virtualMachines|connectedClusters)"$'\t'"(${VM_NAME}|${CLUSTER_NAME})$" <<< "$resources" \
     && ! { [[ -n "$STORAGE_ACCOUNT_NAME" ]] && grep -q -E "storageAccounts"$'\t'"${STORAGE_ACCOUNT_NAME}$" <<< "$resources"; }; then
    die "Resource group $RESOURCE_GROUP holds $(grep -c . <<< "$resources") resources, but neither the VM $VM_NAME, the cluster $CLUSTER_NAME nor the demo's storage account. It does not look like this demo's group; not deleting it. Check RESOURCE_GROUP in $ENV_FILE."
  fi
  info "$(grep -c . <<< "$resources" || true) resources will be deleted, among them:"
  grep -E "virtualMachines|connectedClusters|IoTOperations/instances|storageAccounts|schemaRegistries|DeviceRegistry/namespaces|customLocations" <<< "$resources" \
    | while IFS=$'\t' read -r type name; do info "  $name  ($type)"; done || true
  confirm "Type the name of the resource group to delete it with everything in it" "$RESOURCE_GROUP"

  read_identities
  save_identities
  uninstall_iot_operations
  remove_vm_role_assignments

  log "Deleting resource group $RESOURCE_GROUP"
  if [[ -n "$NO_WAIT" ]]; then
    az group delete --name "$RESOURCE_GROUP" --yes --no-wait
    info "Deletion started. Check later with: az group exists --name $RESOURCE_GROUP"
    return 0
  fi
  info "This takes 5 to 20 minutes. If the session closes meanwhile, the deletion goes on; check later with:"
  info "  az group exists --name $RESOURCE_GROUP"
  if ! az group delete --name "$RESOURCE_GROUP" --yes; then
    warn "Deleting the resource group failed. What is left in it:"
    rg_resources | while IFS=$'\t' read -r type name; do info "  $name  ($type)"; done || true
    LEFT_TO_DO+=("Run this script with --azure again. If the same resources stay, delete them in the Azure portal, then the resource group.")
    return 0
  fi
  if rg_exists; then
    warn "The resource group still exists."
    LEFT_TO_DO+=("Check the resource group $RESOURCE_GROUP in the Azure portal.")
  else
    info "Deleted. Nothing of this deployment is left in Azure."
  fi
}

# ============================================================================== Fabric
# The Fabric REST API answers in pages; this prints the "value" lists of all pages as one JSON list.
PY_MERGE='import json, sys
page = json.load(open(sys.argv[1])); merged = json.load(open(sys.argv[2]))
merged += page.get("value", [])
json.dump(merged, open(sys.argv[2], "w"))
print(page.get("continuationUri") or "")'
fabric_list() {
  local url="$FABRIC_API/$1" page all
  page="$(mktemp)"; all="$(mktemp)"
  echo "[]" > "$all"
  while [[ -n "$url" ]]; do
    if ! az rest --resource "$FABRIC_RESOURCE" --method get --url "$url" --output json > "$page" 2>"$FABRIC_ERR_FILE"; then
      rm -f "$page" "$all"
      return 1
    fi
    url="$(python3 -c "$PY_MERGE" "$page" "$all")"
  done
  cat "$all"
  rm -f "$page" "$all"
}
fabric_delete() { az rest --resource "$FABRIC_RESOURCE" --method delete --url "$FABRIC_API/$1" --output none 2>"$FABRIC_ERR_FILE"; }

# Prints the id of the workspace named FABRIC_WORKSPACE_NAME; returns 1 when the API cannot be reached.
PY_WORKSPACE='import json, sys
found = [w["id"] for w in json.load(sys.stdin) if w.get("displayName") == sys.argv[1]]
print(found[0] if len(found) == 1 else ("" if not found else "AMBIGUOUS"))'
find_workspace() {
  local all
  all="$(fabric_list "workspaces")" || return 1
  python3 -c "$PY_WORKSPACE" "$FABRIC_WORKSPACE_NAME" <<< "$all"
}

# One line per item of the workspace: order <TAB> action <TAB> type <TAB> name <TAB> id
#   action "delete": an item of the demo; "with-parent": removed together with its parent;
#   "keep": not created by the demo.
PY_ITEMS='import json, sys
eventhouse, eventstreams, lakehouse = sys.argv[1], set(sys.argv[2].split()), sys.argv[3]
notebooks = set(sys.argv[4].split())
model, report, data_agent, ontology, operations_agent, app = sys.argv[5:11]
# Agents, the app and the report go first: they read the model, the Lakehouse and the Eventhouse.
order = {"OperationsAgent": 0, "DataAgent": 0, "Ontology": 0, "Report": 0, "SemanticModel": 1, "Eventstream": 1,
         "Notebook": 2, "KQLQueryset": 3, "Lakehouse": 4, "Eventhouse": 5}
by_name = {"SemanticModel": model, "Report": report, "DataAgent": data_agent, "Ontology": ontology,
           "OperationsAgent": operations_agent}
data_kinds = set(order) | {"KQLDatabase", "SQLEndpoint"}
for item in json.load(sys.stdin):
    kind, name = item.get("type", ""), item.get("displayName", "")
    # The app of Phase 4: its item type is not written down anywhere, so it is known by its name alone,
    # and only when the type is none of the kinds that hold data.
    is_app = bool(app) and name == app and kind not in data_kinds
    ours = ((kind == "Eventstream" and name in eventstreams) or (kind == "Notebook" and name in notebooks)
            or (kind == "KQLQueryset" and name.startswith(eventhouse)) or (kind == "Lakehouse" and name == lakehouse)
            or (kind == "Eventhouse" and name == eventhouse) or (kind in by_name and name == by_name[kind]) or is_app)
    child = ((kind == "KQLDatabase" and name == eventhouse)
             or (kind in ("SQLEndpoint", "SemanticModel") and name == lakehouse))
    action = "delete" if ours else "with-parent" if child else "keep"
    print("\t".join([str(0 if is_app else order.get(kind, 9)), action, kind, name, item.get("id", "")]))'
workspace_items() {
  local all
  all="$(fabric_list "workspaces/$1/items")" || return 1
  python3 -c "$PY_ITEMS" "$EVENTHOUSE_NAME" "$EVENTSTREAM_NAME $COMMAND_EVENTSTREAM_NAME" "$FABRIC_LAKEHOUSE_NAME" "$NOTEBOOK_NAMES" \
    "$SEMANTIC_MODEL_NAME" "$REPORT_NAME" "$DATA_AGENT_NAME" "$ONTOLOGY_NAME" "$OPERATIONS_AGENT_NAME" "$APP_NAME" <<< "$all" | sort
}

# One line per identity of the edge that has access to the workspace: id <TAB> name <TAB> role
PY_ACCESS='import json, sys
vm_name, extension_name = sys.argv[1], sys.argv[2]
known = {p for p in sys.argv[3:] if p}
for entry in json.load(sys.stdin):
    principal = entry.get("principal", {})
    name, kind = principal.get("displayName") or "", principal.get("type") or ""
    by_id = principal.get("id") in known
    by_name = kind.startswith("ServicePrincipal") and (name == vm_name or (extension_name and name == extension_name)
                                                       or name.startswith("azure-iot-operations-"))
    if by_id or by_name:
        print("\t".join([entry.get("id") or principal.get("id", ""), name or "(identity deleted)", entry.get("role", "")]))'
has_kept_items() { awk -F'\t' '$2 == "keep" {found = 1} END {exit !found}' <<< "$1"; }
edge_access() {
  local all
  all="$(fabric_list "workspaces/$1/roleAssignments")" || return 1
  python3 -c "$PY_ACCESS" "$VM_NAME" "${AIO_EXTENSION_NAME:-}" "${VM_PRINCIPAL_ID:-}" "${AIO_EXTENSION_PRINCIPAL_ID:-}" <<< "$all"
}

fabric_by_hand() {
  warn "The Fabric REST API could not be used from this session: $(tr '\n' ' ' < "$FABRIC_ERR_FILE" | cut -c1-300)"
  info "That is common in Azure Cloud Shell. Do this part in the Fabric portal instead, in workspace $FABRIC_WORKSPACE_NAME:"
  info "  1. Delete, in this order: eventstreams $EVENTSTREAM_NAME and $COMMAND_EVENTSTREAM_NAME; the notebooks; the KQL queryset of $EVENTHOUSE_NAME;"
  info "     Lakehouse $FABRIC_LAKEHOUSE_NAME; Eventhouse $EVENTHOUSE_NAME. (Menu ... of each item, Delete.)"
  info "  2. Manage access: remove $VM_NAME and the identity whose name starts with azure-iot-operations-."
  info "  Or delete the whole workspace: Workspace settings, General, Remove this workspace."
  info "The script can do this part where 'az login' was done in a browser, for example on your own computer:"
  info "copy this one file and config/demo.env there and run it with --fabric."
  LEFT_TO_DO+=("Fabric portal: delete the demo's items and the two identities' access in workspace $FABRIC_WORKSPACE_NAME (steps printed above).")
}

# Sets WORKSPACE_ID; returns 1 when the Fabric part cannot go on.
open_workspace() {
  command -v python3 >/dev/null 2>&1 || die "python3 is required for the Fabric part."
  if ! WORKSPACE_ID="$(find_workspace)"; then
    fabric_by_hand
    return 1
  fi
  if [[ "$WORKSPACE_ID" == "AMBIGUOUS" ]]; then
    die "More than one workspace is named $FABRIC_WORKSPACE_NAME. Rename one, or delete the items in the Fabric portal."
  fi
  if [[ -z "$WORKSPACE_ID" ]]; then
    info "No workspace named $FABRIC_WORKSPACE_NAME that you can see. Nothing to remove in Fabric."
    return 1
  fi
}

describe_fabric() {
  local items access
  log "Fabric: workspace $FABRIC_WORKSPACE_NAME"
  open_workspace || return 0
  read_saved_identities
  items="$(workspace_items "$WORKSPACE_ID")" || { fabric_by_hand; return 0; }
  access="$(edge_access "$WORKSPACE_ID")" || access=""
  info "--fabric would delete:"
  awk -F'\t' '$2 == "delete" {printf "      %s %s\n", $3, $4}' <<< "$items"
  awk -F'\t' '$2 == "with-parent" {printf "      %s %s (goes with its parent)\n", $3, $4}' <<< "$items"
  if [[ -n "$access" ]]; then
    info "and remove the workspace access of:"
    awk -F'\t' '{printf "      %s (%s)\n", $2, $3}' <<< "$access"
  fi
  if has_kept_items "$items"; then
    info "and leave alone:"
    awk -F'\t' '$2 == "keep" {printf "      %s %s\n", $3, $4}' <<< "$items"
  fi
  info "--fabric-workspace would delete the workspace with all $(grep -c . <<< "$items" || true) items."
}

# delete_item TYPE NAME ID: permanently where the workspace allows it, otherwise the normal delete.
# Fabric keeps a Lakehouse, a notebook and a KQL queryset in the workspace's recycle bin after a
# normal delete; an eventstream and an Eventhouse are gone for good either way.
delete_item() {
  local kind="$1" name="$2" id="$3" collection="" recoverable=""
  case "$kind" in
    Eventstream) collection="eventstreams" ;;
    Eventhouse)  collection="eventhouses" ;;
    KQLQueryset) collection="kqlQuerysets"; recoverable=yes ;;
    Lakehouse)   collection="lakehouses";   recoverable=yes ;;
    Notebook)    collection="notebooks";    recoverable=yes ;;
    # Phases 2 to 5. Whether Fabric keeps these after a normal delete is not written down for every type.
    SemanticModel)   collection="semanticModels";   recoverable=unknown ;;
    Report)          collection="reports";          recoverable=unknown ;;
    DataAgent)       collection="dataAgents";       recoverable=unknown ;;
    Ontology)        collection="ontologies";       recoverable=unknown ;;
    OperationsAgent) collection="operationsAgents"; recoverable=unknown ;;
    *)               recoverable=unknown ;;
  esac
  if fabric_delete "workspaces/$WORKSPACE_ID/items/$id?hardDelete=true"; then
    info "$kind $name: deleted"
  elif fabric_delete "workspaces/$WORKSPACE_ID/items/$id" \
       || { [[ -n "$collection" ]] && fabric_delete "workspaces/$WORKSPACE_ID/$collection/$id"; }; then
    if [[ "$recoverable" == "unknown" ]]; then
      info "$kind $name: deleted; whether for good, Fabric did not say"
      SOFT_DELETED=yes
    elif [[ -n "$recoverable" ]]; then
      info "$kind $name: deleted, but not permanently"
      SOFT_DELETED=yes
    else
      info "$kind $name: deleted"
    fi
  else
    warn "$kind $name could not be deleted: $(tr '\n' ' ' < "$FABRIC_ERR_FILE" | cut -c1-240)"
    LEFT_TO_DO+=("Fabric portal: delete $kind $name in workspace $FABRIC_WORKSPACE_NAME.")
  fi
}

fabric_cleanup() {
  local items access ours kind name id role
  log "Fabric: workspace $FABRIC_WORKSPACE_NAME"
  open_workspace || return 0
  [[ -n "${VM_PRINCIPAL_ID:-}" ]] || read_identities
  read_saved_identities
  items="$(workspace_items "$WORKSPACE_ID")" || { fabric_by_hand; return 0; }
  access="$(edge_access "$WORKSPACE_ID")" || access=""
  ours="$(awk -F'\t' '$2 == "delete"' <<< "$items")"
  if [[ -z "$ours" && -z "$access" ]]; then
    info "None of the demo's items and neither edge identity is in the workspace. Nothing to remove."
    return 0
  fi
  info "To delete:"
  [[ -z "$ours" ]] || awk -F'\t' '{printf "      %s %s\n", $3, $4}' <<< "$ours"
  [[ -z "$access" ]] || awk -F'\t' '{printf "      workspace access of %s (%s)\n", $2, $3}' <<< "$access"
  if has_kept_items "$items"; then
    info "Left alone, because the demo did not create them:"
    awk -F'\t' '$2 == "keep" {printf "      %s %s\n", $3, $4}' <<< "$items"
  fi
  confirm "Type the name of the workspace to delete these" "$FABRIC_WORKSPACE_NAME"

  SOFT_DELETED=""
  if [[ -n "$ours" ]]; then
    log "Deleting the demo's items"
    while IFS=$'\t' read -r _ _ kind name id; do
      [[ -n "$id" ]] || continue
      delete_item "$kind" "$name" "$id"
    done <<< "$ours"
  fi
  if [[ -n "$access" ]]; then
    log "Removing the workspace access of the edge identities"
    while IFS=$'\t' read -r id name role; do
      [[ -n "$id" ]] || continue
      if fabric_delete "workspaces/$WORKSPACE_ID/roleAssignments/$id"; then
        info "$name ($role)"
      else
        warn "Could not remove the access of $name: $(tr '\n' ' ' < "$FABRIC_ERR_FILE" | cut -c1-240)"
        LEFT_TO_DO+=("Fabric portal: Manage access in workspace $FABRIC_WORKSPACE_NAME, remove $name.")
      fi
    done <<< "$access"
  fi
  if [[ -n "$SOFT_DELETED" ]]; then
    info "Some items could not be deleted permanently; that needs the Admin role in the workspace. If item"
    info "recovery is on in the tenant, which is the default, they are now in the workspace's Recycle bin for the"
    info "tenant's retention period (3 days by default) and use OneLake storage until then. A workspace Admin"
    info "can delete them for good there."
  fi
}

workspace_cleanup() {
  local items
  log "Fabric: workspace $FABRIC_WORKSPACE_NAME"
  open_workspace || return 0
  items="$(workspace_items "$WORKSPACE_ID")" || items=""
  info "The whole workspace will be deleted, with all $(grep -c . <<< "$items" || true) items in it:"
  awk -F'\t' '{printf "      %s %s\n", $3, $4}' <<< "$items"
  confirm "Type the name of the workspace to delete it with everything in it" "$FABRIC_WORKSPACE_NAME"
  if fabric_delete "workspaces/$WORKSPACE_ID"; then
    info "Workspace deleted. Fabric keeps a deleted workspace for a retention period (7 days by default) before"
    info "it removes it for good; until then a Fabric administrator can restore it or remove it earlier."
  else
    warn "The workspace could not be deleted: $(tr '\n' ' ' < "$FABRIC_ERR_FILE" | cut -c1-240)"
    LEFT_TO_DO+=("Fabric portal: Workspace settings, General, Remove this workspace ($FABRIC_WORKSPACE_NAME). You must be an Admin of the workspace.")
  fi
}

# ============================================================================== main
VM_PRINCIPAL_ID=""; AIO_EXTENSION_NAME=""; AIO_EXTENSION_PRINCIPAL_ID=""; SOFT_DELETED=""
if [[ -z "${DO_AZURE}${DO_FABRIC}${DO_WORKSPACE}" ]]; then
  describe_azure
  describe_fabric
  log "Nothing was changed"
  info "To remove:  --azure   --fabric   --fabric-workspace   --all      (add --yes to skip the questions)"
  exit 0
fi

# Fabric first: the edge identities are looked up in Azure, which must still hold them.
if [[ -n "$DO_FABRIC" ]]; then fabric_cleanup; fi
if [[ -n "$DO_WORKSPACE" ]]; then workspace_cleanup; fi
if [[ -n "$DO_AZURE" ]]; then azure_cleanup; fi

log "Done"
if [[ ${#LEFT_TO_DO[@]} -gt 0 ]]; then
  info "Left for you to do:"
  for item in "${LEFT_TO_DO[@]}"; do info "  - $item"; done
fi
info "Not touched: files on this machine, your SSH key, resource provider registrations, the Fabric capacity."
info "Before you deploy again, in config/demo.env: keep CUSTOM_LOCATIONS_OID (it belongs to the tenant);"
info "empty EVENTSTREAM_BOOTSTRAP_SERVER and EVENTSTREAM_TOPIC (they belonged to the deleted eventstream)."
if [[ ${#LEFT_TO_DO[@]} -gt 0 ]]; then exit 3; fi
