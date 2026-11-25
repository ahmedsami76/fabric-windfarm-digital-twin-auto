#!/usr/bin/env bash
# Step 6 (run on your workstation or in Azure Cloud Shell, signed in as yourself).
# Creates the Azure IoT Operations data flow endpoint for the Fabric eventstream
# and the data flow that forwards the wind farm topics to it.
#
#   bash infra/06-connect-edge-to-fabric.sh                     create them, or write them anew after a change to
#                                                               edge/dataflows/windfarm-to-fabric.template.json
#   bash infra/06-connect-edge-to-fabric.sh --new-eventstream   point a data flow that exists at another eventstream
#
# A data flow that exists is replaced. So before anything is written, the eventstream named in
# config/demo.env is compared with the one the running data flow sends to. When they differ the script
# stops: going on would send the telemetry somewhere else. --new-eventstream says that this is intended.
#
# Before the first run: the eventstream with a custom endpoint source must exist, and
# the Azure IoT Operations Arc extension identity must be a Contributor on the
# Fabric workspace (deployment guide, steps 6.4 and 6.5).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../config/load-env.sh"
need az sed
require SUBSCRIPTION_ID RESOURCE_GROUP AIO_INSTANCE_NAME EVENTSTREAM_BOOTSTRAP_SERVER EVENTSTREAM_TOPIC
MODE="${1:-}"
case "$MODE" in ""|--new-eventstream) ;; *) die "Unknown option $MODE. Use no option, or --new-eventstream." ;; esac

ENDPOINT_NAME="${FABRIC_ENDPOINT_NAME:-fabric-eventstream}"
DATAFLOW_NAME="${DATAFLOW_NAME:-windfarm-to-fabric}"
HOST="$EVENTSTREAM_BOOTSTRAP_SERVER"
[[ "$HOST" == *:* ]] || HOST="${HOST}:9093"
lower() { tr '[:upper:]' '[:lower:]' <<< "$1"; }

require_user_login
az account set --subscription "$SUBSCRIPTION_ID"
need_iot_ops_extension

DEPLOYED_TOPIC="$(az iot ops dataflow show --resource-group "$RESOURCE_GROUP" --instance "$AIO_INSTANCE_NAME" --profile default \
  --name "$DATAFLOW_NAME" --query "properties.operations[?operationType=='Destination'] | [0].destinationSettings.dataDestination" \
  --output tsv 2>/dev/null || true)"
if [[ -n "$DEPLOYED_TOPIC" ]]; then
  DEPLOYED_HOST="$(az iot ops dataflow endpoint show --resource-group "$RESOURCE_GROUP" --instance "$AIO_INSTANCE_NAME" \
    --name "$ENDPOINT_NAME" --query properties.kafkaSettings.host --output tsv 2>/dev/null || true)"
  log "The data flow $DATAFLOW_NAME exists"
  info "It sends to:       $DEPLOYED_TOPIC at ${DEPLOYED_HOST:-an endpoint that was not found}"
  info "The settings name: $EVENTSTREAM_TOPIC at $HOST"
  if [[ "$DEPLOYED_TOPIC" != "$EVENTSTREAM_TOPIC" || ( -n "$DEPLOYED_HOST" && "$(lower "$DEPLOYED_HOST")" != "$(lower "$HOST")" ) ]]; then
    if [[ "$MODE" != "--new-eventstream" ]]; then
      die "The settings in $ENV_FILE name another eventstream than the one the data flow sends to. Nothing was changed. If the settings are out of date, 'bash infra/rebuild-env.sh --force' reads them from what is deployed. If you moved to another eventstream on purpose, run: bash infra/06-connect-edge-to-fabric.sh --new-eventstream"
    fi
    warn "The telemetry goes to $EVENTSTREAM_TOPIC at $HOST from now on, as asked with --new-eventstream."
  else
    info "The same eventstream. The endpoint and the data flow are written anew; the telemetry may pause for some seconds."
  fi
else
  # A first run. The name is all there is to check: every topic seen so far starts with these two letters.
  [[ "$EVENTSTREAM_TOPIC" == es* ]] || warn "EVENTSTREAM_TOPIC is '$EVENTSTREAM_TOPIC'. The topic names of an eventstream seen so far start with 'es'. Check the value against the Kafka tab of the custom endpoint (deployment guide, step 6.3)."
fi

log "Creating data flow endpoint $ENDPOINT_NAME -> $HOST (system-assigned managed identity)"
az iot ops dataflow endpoint create fabric-realtime \
  --resource-group "$RESOURCE_GROUP" \
  --instance "$AIO_INSTANCE_NAME" \
  --name "$ENDPOINT_NAME" \
  --host "$HOST" \
  --auth-type SystemAssignedManagedIdentity \
  --output none

log "Creating data flow $DATAFLOW_NAME"
RENDER_DIR="$REPO_ROOT/edge/dataflows/rendered"
mkdir -p "$RENDER_DIR"
CONFIG_FILE="$RENDER_DIR/$DATAFLOW_NAME.json"
sed -e "s|__ENDPOINT_NAME__|$ENDPOINT_NAME|" -e "s|__EVENTSTREAM_TOPIC__|$EVENTSTREAM_TOPIC|" \
  "$REPO_ROOT/edge/dataflows/windfarm-to-fabric.template.json" > "$CONFIG_FILE"
az iot ops dataflow apply \
  --resource-group "$RESOURCE_GROUP" \
  --instance "$AIO_INSTANCE_NAME" \
  --profile default \
  --name "$DATAFLOW_NAME" \
  --config-file "$CONFIG_FILE" \
  --output none

log "Done"
az iot ops dataflow show --resource-group "$RESOURCE_GROUP" --instance "$AIO_INSTANCE_NAME" \
  --profile default --name "$DATAFLOW_NAME" \
  --query "{name:name, mode:properties.mode, state:properties.provisioningState}" --output table
info "It forwards $(grep -c 'contoso/windfarm/' "$CONFIG_FILE") topics: $(grep -o 'contoso/windfarm/+/+/[a-z]*' "$CONFIG_FILE" | sed 's|.*/||' | tr '\n' ' ')"
info "Open the eventstream in Fabric. Events should appear in its data preview within a minute or two."
info "If nothing arrives, see docs/troubleshooting.md, section 'No events in the eventstream'."
