#!/usr/bin/env bash
# Step 4 (run on your workstation or in Azure Cloud Shell, signed in as yourself).
# Creates the Azure dependencies of Azure IoT Operations and deploys an instance
# with test settings to the Arc-enabled cluster. Takes about 15 to 25 minutes.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../config/load-env.sh"
need az
require SUBSCRIPTION_ID LOCATION RESOURCE_GROUP CLUSTER_NAME AIO_INSTANCE_NAME CUSTOM_LOCATION_NAME \
        STORAGE_ACCOUNT_NAME SCHEMA_REGISTRY_NAME SCHEMA_REGISTRY_NAMESPACE DEVICE_REGISTRY_NAMESPACE_NAME

require_user_login
# Not used by this step, but a wrong value makes it fail: step 3 enabled custom locations with it.
if [[ -n "${CUSTOM_LOCATIONS_OID:-}" ]]; then require_object_id CUSTOM_LOCATIONS_OID; fi
az account set --subscription "$SUBSCRIPTION_ID"
need_iot_ops_extension current

# Workstation scripts use only the core CLI and the azure-iot-ops extension. The
# connectedk8s and k8s-extension extensions are avoided here on purpose: in Azure
# Cloud Shell, "az connectedk8s" can crash with a 'cffi' version mismatch when it is
# loaded in the same process as azure-iot-ops (docs/troubleshooting.md).
CLUSTER_RESOURCE_ID="/subscriptions/${SUBSCRIPTION_ID}/resourceGroups/${RESOURCE_GROUP}/providers/Microsoft.Kubernetes/connectedClusters/${CLUSTER_NAME}"

log "Checking that the cluster is connected"
STATUS="$(az resource show --ids "$CLUSTER_RESOURCE_ID" \
  --query properties.connectivityStatus --output tsv)"
[[ "$STATUS" == "Connected" ]] || die "Cluster $CLUSTER_NAME is '$STATUS', expected 'Connected'. The VM may be stopped by its daily shutdown: run bash infra/vm.sh status, start it with bash infra/vm.sh start, wait about 5 minutes and run this script again."

log "Creating the storage account for the schema registry"
if ! az storage account show --name "$STORAGE_ACCOUNT_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az storage account create \
    --name "$STORAGE_ACCOUNT_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --enable-hierarchical-namespace \
    --output none
fi
STORAGE_ACCOUNT_RESOURCE_ID="$(az storage account show --name "$STORAGE_ACCOUNT_NAME" \
  --resource-group "$RESOURCE_GROUP" --query id --output tsv)"

log "Creating the schema registry"
if ! az iot ops schema registry show --name "$SCHEMA_REGISTRY_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az iot ops schema registry create \
    --name "$SCHEMA_REGISTRY_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --registry-namespace "$SCHEMA_REGISTRY_NAMESPACE" \
    --sa-resource-id "$STORAGE_ACCOUNT_RESOURCE_ID" \
    --output none
fi

log "Creating the Azure Device Registry namespace"
if ! az iot ops ns show --name "$DEVICE_REGISTRY_NAMESPACE_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  az iot ops ns create \
    --name "$DEVICE_REGISTRY_NAMESPACE_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --location "$LOCATION" \
    --output none
fi

SCHEMA_REGISTRY_RESOURCE_ID="$(az iot ops schema registry show --name "$SCHEMA_REGISTRY_NAME" \
  --resource-group "$RESOURCE_GROUP" --query id --output tsv)"
DEVICE_REGISTRY_NAMESPACE_RESOURCE_ID="$(az iot ops ns show --name "$DEVICE_REGISTRY_NAMESPACE_NAME" \
  --resource-group "$RESOURCE_GROUP" --query id --output tsv)"
[[ -n "$SCHEMA_REGISTRY_RESOURCE_ID" && -n "$DEVICE_REGISTRY_NAMESPACE_RESOURCE_ID" ]] \
  || die "Could not resolve the schema registry or Device Registry namespace."

# Before they deploy, init and create ask Azure Resource Health about the cluster and stop when
# the answer stays "Unavailable". Azure reports a cluster that way for some minutes after it was
# connected to Azure Arc, and again after init has installed its extensions, although every
# agent runs (validation log, obstacle 16). By default the commands ask 4 times in 90 seconds;
# here they ask for up to 20 minutes.
HEALTH_WAIT=(--health-checks-max 40 --health-checks-int 30)

# create refuses a cluster that already has Azure IoT Operations, so a second run of this
# script skips both commands when the instance exists.
if az iot ops show --name "$AIO_INSTANCE_NAME" --resource-group "$RESOURCE_GROUP" --output none 2>/dev/null; then
  log "Instance $AIO_INSTANCE_NAME exists: nothing to deploy"
else
  log "Initialising the cluster for Azure IoT Operations (several minutes)"
  info "While Azure reports the cluster as unavailable, this waits, up to 20 minutes."
  az iot ops init \
    --subscription "$SUBSCRIPTION_ID" \
    --resource-group "$RESOURCE_GROUP" \
    --cluster "$CLUSTER_NAME" \
    "${HEALTH_WAIT[@]}"

  log "Deploying the Azure IoT Operations instance (several minutes)"
  info "The same wait applies: Azure can report the cluster as unavailable again right after the previous step."
  CREATE_ARGS=(
    --subscription "$SUBSCRIPTION_ID"
    --resource-group "$RESOURCE_GROUP"
    --cluster "$CLUSTER_NAME"
    --name "$AIO_INSTANCE_NAME"
    --custom-location "$CUSTOM_LOCATION_NAME"
    --sr-resource-id "$SCHEMA_REGISTRY_RESOURCE_ID"
    --ns-resource-id "$DEVICE_REGISTRY_NAMESPACE_RESOURCE_ID"
    "${HEALTH_WAIT[@]}"
  )
  if [[ -n "${AIO_SKU:-}" ]]; then
    CREATE_ARGS+=(--sku "$AIO_SKU")
  fi
  az iot ops create "${CREATE_ARGS[@]}"
fi

log "Done"
az iot ops show --name "$AIO_INSTANCE_NAME" --resource-group "$RESOURCE_GROUP" \
  --query "{name:name, state:properties.provisioningState, location:location}" --output table

EXTENSIONS_URL="https://management.azure.com${CLUSTER_RESOURCE_ID}/providers/Microsoft.KubernetesConfiguration/extensions?api-version=2023-05-01"
EXTENSION_FILTER="value[?properties.extensionType=='microsoft.iotoperations']"
EXTENSION_NAME="$(az rest --method get --url "$EXTENSIONS_URL" \
  --query "${EXTENSION_FILTER}.name | [0]" --output tsv 2>/dev/null || true)"
EXTENSION_PRINCIPAL_ID="$(az rest --method get --url "$EXTENSIONS_URL" \
  --query "${EXTENSION_FILTER}.identity.principalId | [0]" --output tsv 2>/dev/null || true)"
info "Azure IoT Operations Arc extension (its managed identity has the same name):"
info "  name:      ${EXTENSION_NAME:-not found here; see the instance Overview page in the Azure portal}"
info "  object ID: ${EXTENSION_PRINCIPAL_ID:-not found here}"
info "You add this identity to the Fabric workspace in step 6.5 of the deployment guide."
