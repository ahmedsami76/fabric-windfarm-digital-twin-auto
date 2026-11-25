#!/usr/bin/env bash
# Rebuilds config/demo.env from what is deployed (run on your workstation, signed in as yourself).
# For a workstation that lost its copy of the settings, or a new one.
#
#   bash infra/rebuild-env.sh [RESOURCE_GROUP]           default: rg-windfarm-edge
#   bash infra/rebuild-env.sh --force [RESOURCE_GROUP]   replace an existing config/demo.env; the old one is kept as demo.env.bak
#
# The script starts from config/demo.env.example and fills in what Azure knows: subscription,
# region, the names of the VM, the cluster, the instance, the custom location, the storage
# account, the schema registry and the namespace, the VM's size and daily shutdown, the Custom
# Locations object ID, and the eventstream address and topic of the data flow. It changes nothing
# in Azure. Settings that Azure does not hold keep the value of the example file; the script
# lists them at the end.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$HERE/.." && pwd)"
ENV_FILE="${ENV_FILE:-$REPO_ROOT/config/demo.env}"
EXAMPLE="$REPO_ROOT/config/demo.env.example"

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }
# The Azure CLI prints "None" for a missing value in some versions and nothing in others.
value() { if [[ "${1:-}" == "None" ]]; then printf ''; else printf '%s' "${1:-}"; fi; }
ask()   { value "$("$@" 2>/dev/null || true)"; }

FORCE=""; RG=""
for arg in "$@"; do
  case "$arg" in
    --force)   FORCE=yes ;;
    -h|--help) sed -n '2,/^set -euo pipefail/p' "${BASH_SOURCE[0]}" | grep '^#' | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*)        die "Unknown option $arg" ;;
    *)         RG="$arg" ;;
  esac
done
RG="${RG:-rg-windfarm-edge}"

command -v az >/dev/null 2>&1 || die "The Azure CLI (az) is required."
command -v python3 >/dev/null 2>&1 || die "python3 is required."
[[ -f "$EXAMPLE" ]] || die "$EXAMPLE not found. Run this script from a complete copy of the repository."
[[ -n "$(az account show --query user.type --output tsv 2>/dev/null || true)" ]] || die "The Azure CLI is not signed in. Run: az login"
if [[ -e "$ENV_FILE" && -z "$FORCE" ]]; then
  die "$ENV_FILE exists. Add --force to replace it; the old file is kept as demo.env.bak."
fi

SUBSCRIPTION="$(ask az account show --query id --output tsv)"
if [[ "$(az group exists --name "$RG" --output tsv 2>/dev/null)" != "true" ]]; then
  die "Resource group $RG does not exist in subscription $SUBSCRIPTION. Choose the subscription with: az account set --subscription <ID>"
fi

log "Reading resource group $RG in subscription $SUBSCRIPTION"
RESOURCES="$(az resource list --resource-group "$RG" --query "[].[type, name]" --output tsv)"
name_of() { awk -F'\t' -v t="$1" 'tolower($1) == tolower(t) {print $2; exit}' <<< "$RESOURCES"; }

SETTINGS=()
NOT_FOUND=()
keep() {   # keep KEY VALUE: use VALUE for KEY; an empty VALUE is reported and the example's value stays
  if [[ -n "$2" ]]; then SETTINGS+=("$1=$2"); info "$1 = $2"; else NOT_FOUND+=("$1"); fi
}

keep SUBSCRIPTION_ID "$SUBSCRIPTION"
keep LOCATION "$(ask az group show --name "$RG" --query location --output tsv)"
SETTINGS+=("RESOURCE_GROUP=$RG")

VM="$(name_of Microsoft.Compute/virtualMachines)"
keep VM_NAME "$VM"
if [[ -n "$VM" ]]; then
  keep VM_SIZE "$(ask az vm show --resource-group "$RG" --name "$VM" --query hardwareProfile.vmSize --output tsv)"
  keep VM_ADMIN "$(ask az vm show --resource-group "$RG" --name "$VM" --query osProfile.adminUsername --output tsv)"
  SCHEDULE="$(ask az resource show --resource-group "$RG" --name "shutdown-computevm-$VM" \
    --resource-type Microsoft.DevTestLab/schedules \
    --query "join(' ', [properties.status, properties.dailyRecurrence.time])" --output tsv)"
  if [[ "${SCHEDULE%% *}" == "Enabled" && "${SCHEDULE##* }" =~ ^[0-9]{4}$ ]]; then
    SETTINGS+=("VM_AUTO_SHUTDOWN_UTC=${SCHEDULE##* }"); info "VM_AUTO_SHUTDOWN_UTC = ${SCHEDULE##* }"
  else
    SETTINGS+=("VM_AUTO_SHUTDOWN_UTC="); info "VM_AUTO_SHUTDOWN_UTC = (none: the VM has no daily shutdown)"
  fi
fi

keep CLUSTER_NAME "$(name_of Microsoft.Kubernetes/connectedClusters)"
INSTANCE="$(name_of Microsoft.IoTOperations/instances)"
keep AIO_INSTANCE_NAME "$INSTANCE"
keep CUSTOM_LOCATION_NAME "$(name_of Microsoft.ExtendedLocation/customLocations)"
keep STORAGE_ACCOUNT_NAME "$(name_of Microsoft.Storage/storageAccounts)"
REGISTRY="$(name_of Microsoft.DeviceRegistry/schemaRegistries)"
keep SCHEMA_REGISTRY_NAME "$REGISTRY"
if [[ -n "$REGISTRY" ]]; then
  keep SCHEMA_REGISTRY_NAMESPACE "$(ask az resource show --resource-group "$RG" --name "$REGISTRY" \
    --resource-type Microsoft.DeviceRegistry/schemaRegistries --query properties.namespace --output tsv)"
fi
keep DEVICE_REGISTRY_NAMESPACE_NAME "$(name_of Microsoft.DeviceRegistry/namespaces)"

# The object ID of the Custom Locations service in this tenant. The application ID is the same everywhere.
keep CUSTOM_LOCATIONS_OID "$(ask az ad sp show --id bc313c14-388c-4e7d-a58e-70017303ee3b --query id --output tsv)"

if [[ -n "$INSTANCE" ]]; then
  if ! az extension show --name azure-iot-ops --output none 2>/dev/null; then
    info "Installing the Azure CLI extension azure-iot-ops"
    az extension add --yes --name azure-iot-ops --output none || warn "The extension azure-iot-ops could not be installed."
  fi
  keep EVENTSTREAM_BOOTSTRAP_SERVER "$(ask az iot ops dataflow endpoint show --resource-group "$RG" --instance "$INSTANCE" \
    --name "${FABRIC_ENDPOINT_NAME:-fabric-eventstream}" --query properties.kafkaSettings.host --output tsv)"
  keep EVENTSTREAM_TOPIC "$(ask az iot ops dataflow show --resource-group "$RG" --instance "$INSTANCE" --profile default \
    --name "${DATAFLOW_NAME:-windfarm-to-fabric}" \
    --query "properties.operations[?operationType=='Destination'] | [0].destinationSettings.dataDestination" --output tsv)"
else
  NOT_FOUND+=(EVENTSTREAM_BOOTSTRAP_SERVER EVENTSTREAM_TOPIC)
fi

log "Writing $ENV_FILE"
if [[ -e "$ENV_FILE" ]]; then
  cp "$ENV_FILE" "$ENV_FILE.bak"
  info "The old file is kept as $ENV_FILE.bak"
fi
python3 - "$EXAMPLE" "$ENV_FILE" "${SETTINGS[@]}" <<'PY'
import re
import sys

example, target, pairs = sys.argv[1], sys.argv[2], dict(p.split("=", 1) for p in sys.argv[3:])
lines = []
for line in open(example, encoding="utf-8"):
    match = re.match(r'^([A-Z_]+)="[^"]*"(.*)$', line.rstrip("\n"))
    if match and match.group(1) in pairs:
        line = f'{match.group(1)}="{pairs.pop(match.group(1))}"{match.group(2)}\n'
    lines.append(line)
if pairs:
    sys.exit("settings missing from the example file: " + ", ".join(pairs))
open(target, "w", encoding="utf-8").writelines(lines)
PY
chmod 600 "$ENV_FILE"

log "Done"
if [[ ${#NOT_FOUND[@]} -gt 0 ]]; then
  warn "Not found in Azure, left as in the example file. Set them by hand in $ENV_FILE:"
  for key in "${NOT_FOUND[@]}"; do
    case "$key" in
      CUSTOM_LOCATIONS_OID)  info "  $key: this sign-in may not read Microsoft Entra ID. See 'the Custom Locations object ID is not printed' in docs/troubleshooting.md." ;;
      EVENTSTREAM_*)         info "  $key: the data flow of step 6.6 was not found. Copy the value from the eventstream's custom endpoint in Fabric." ;;
      *)                     info "  $key: no such resource in $RG yet." ;;
    esac
  done
fi
info "Not stored in Azure, taken from the example file: SSH_SOURCE_CIDR, AIO_SKU, AZ_LOGIN_MODE, FABRIC_WORKSPACE_NAME,"
info "FABRIC_LAKEHOUSE_NAME, SIM_IMAGE, SIM_NAMESPACE. Change them if you had changed them."
info "Next: bash infra/vm.sh status    and, to give the VM the same settings: bash infra/vm.sh push-env"
