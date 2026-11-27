#!/usr/bin/env bash
# Phase 5a (run on your workstation, signed in as yourself): the path for commands from
# Fabric to the edge.
#
#   bash infra/08-create-command-path.sh            create what is missing
#   bash infra/08-create-command-path.sh --show     say what exists; change nothing
#   bash infra/08-create-command-path.sh --remove   delete the data flow, the endpoint and the eventstream
#
# What it creates, in this order:
#   1. In the Fabric workspace, the eventstream WindFarmCommands: a custom endpoint as its
#      source (a notebook writes commands to it), the default stream, and a custom endpoint
#      as its destination (the edge reads from it). An eventstream of that name that
#      already exists is used as it is, so one made by hand in the portal works too.
#   2. In Azure IoT Operations, the data flow endpoint fabric-commands: the destination of
#      that eventstream, read with the Kafka protocol as the identity of the Azure IoT
#      Operations extension. That identity is a Contributor of the workspace since step 6.5
#      of the Phase 1 guide.
#   3. The data flow fabric-to-windfarm-control: from that endpoint to the topic
#      <TOPIC_ROOT>/<SITE_ID>/_control/request on the local MQTT broker, where the simulator
#      listens. That topic takes curtail, release, stop, start and reset, and nothing else.
#
# It reads the connection details of the eventstream from the Fabric API. Nothing has to be
# copied from the portal, and no key is stored: the edge signs in with its identity.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../config/load-env.sh"

MODE="create"
case "${1:-}" in
  "") ;;
  --show) MODE="show" ;;
  --remove) MODE="remove" ;;
  *) die "Unknown option $1. Use no option, --show or --remove." ;;
esac

need az python3 sed
require SUBSCRIPTION_ID RESOURCE_GROUP AIO_INSTANCE_NAME
: "${FABRIC_WORKSPACE_NAME:=WindFarmDigitalTwin}"
: "${COMMAND_DATAFLOW_MODE:=Enabled}"
case "$COMMAND_DATAFLOW_MODE" in Enabled|Disabled) ;; *) die "COMMAND_DATAFLOW_MODE is '$COMMAND_DATAFLOW_MODE'. It is Enabled or Disabled.";; esac
: "${COMMAND_EVENTSTREAM_NAME:=WindFarmCommands}"
: "${COMMAND_ENDPOINT_NAME:=fabric-commands}"
: "${COMMAND_DATAFLOW_NAME:=fabric-to-windfarm-control}"
: "${TOPIC_ROOT:=contoso/windfarm}"
: "${SITE_ID:=northwind-ridge}"
CONTROL_TOPIC="$TOPIC_ROOT/$SITE_ID/_control/request"
FABRIC_RESOURCE="https://api.fabric.microsoft.com"
FABRIC_API="$FABRIC_RESOURCE/v1"
SOURCE_NODE="CommandIn"
DESTINATION_NODE="CommandOut"
ERR_FILE="$(mktemp)"
trap 'rm -f "$ERR_FILE"' EXIT

require_user_login
az account set --subscription "$SUBSCRIPTION_ID"

# ---------------------------------------------------------------------------------------- Fabric API
said() { tr '\n' ' ' < "$ERR_FILE" | cut -c1-600; }
fabric_get() { az rest --resource "$FABRIC_RESOURCE" --method get --url "$FABRIC_API/$1" --output json 2>"$ERR_FILE"; }

# Small readers of JSON on standard input. Each prints one value, or nothing.
#   id_by_name NAME   the id of the entry of "value" with that displayName
#   key_of KEY        the value of a top-level key
#   custom_endpoint KIND   the id of the first custom endpoint under "sources" or "destinations"
json_read() { python3 -c 'import json, sys
mode, arg = sys.argv[1], sys.argv[2]
d = json.load(sys.stdin)
if mode == "id_by_name":
    v = next((e.get("id") for e in d.get("value", []) if e.get("displayName") == arg), None)
elif mode == "key_of":
    v = d.get(arg)
else:
    v = next((n.get("id") for n in d.get(arg, []) if n.get("type") == "CustomEndpoint"), None)
print("" if v is None else v)' "$1" "$2"; }

find_workspace() {
  local all
  all="$(fabric_get "workspaces")" || die "The Fabric API did not answer: $(said) Sign in with 'az login' as the account that owns the workspace."
  json_read id_by_name "$FABRIC_WORKSPACE_NAME" <<< "$all"
}
find_eventstream() {  # prints the id, or nothing
  local all
  all="$(fabric_get "workspaces/$WORKSPACE_ID/eventstreams")" || die "Could not list the eventstreams of the workspace: $(said)"
  json_read id_by_name "$COMMAND_EVENTSTREAM_NAME" <<< "$all"
}

EVENTSTREAM_JSON='{
  "sources": [ { "name": "__SOURCE__", "type": "CustomEndpoint", "properties": {} } ],
  "destinations": [ { "name": "__DESTINATION__", "type": "CustomEndpoint", "properties": {}, "inputNodes": [ { "name": "__STREAM__" } ] } ],
  "streams": [ { "name": "__STREAM__", "type": "DefaultStream", "properties": {}, "inputNodes": [ { "name": "__SOURCE__" } ] } ],
  "operators": [],
  "compatibilityLevel": "1.0"
}'

by_hand() {
  info "To make it by hand instead, in the workspace $FABRIC_WORKSPACE_NAME:"
  info "  1. New item, Eventstream, name $COMMAND_EVENTSTREAM_NAME."
  info "  2. Add source, Custom endpoint, name $SOURCE_NODE, Add."
  info "  3. Add destination, Custom endpoint, name $DESTINATION_NODE, Save. Connect the stream to it if it is not connected."
  info "  4. Publish."
  info "Then run this script again: it uses the eventstream it finds."
}

create_eventstream() {
  local body payload
  payload="$(sed -e "s/__SOURCE__/$SOURCE_NODE/g" -e "s/__DESTINATION__/$DESTINATION_NODE/g" -e "s/__STREAM__/$COMMAND_EVENTSTREAM_NAME-stream/g" <<< "$EVENTSTREAM_JSON" | base64 | tr -d '\n')"
  body="$(python3 -c 'import json, sys
print(json.dumps({"displayName": sys.argv[1],
                  "description": "Commands from Fabric to the edge of the wind farm (Phase 5). Written by notebook 12, read by Azure IoT Operations.",
                  "definition": {"parts": [{"path": "eventstream.json", "payload": sys.argv[2], "payloadType": "InlineBase64"}]}}))' "$COMMAND_EVENTSTREAM_NAME" "$payload")"
  if ! az rest --resource "$FABRIC_RESOURCE" --method post --url "$FABRIC_API/workspaces/$WORKSPACE_ID/eventstreams" \
       --headers "Content-Type=application/json" --body "$body" --output none 2>"$ERR_FILE"; then
    warn "Fabric did not create the eventstream from its definition. It said: $(said)"
    by_hand
    exit 3
  fi
}

# node_id KIND: the id of the custom endpoint among the sources or the destinations.
node_id() { json_read custom_endpoint "$1" <<< "$TOPOLOGY"; }

# ------------------------------------------------------------------------------------------- remove
if [[ "$MODE" == "remove" ]]; then
  log "Removing the command path"
  need_iot_ops_extension
  az iot ops dataflow delete --resource-group "$RESOURCE_GROUP" --instance "$AIO_INSTANCE_NAME" --profile default \
    --name "$COMMAND_DATAFLOW_NAME" --yes --output none 2>"$ERR_FILE" && info "Data flow $COMMAND_DATAFLOW_NAME deleted." \
    || info "Data flow $COMMAND_DATAFLOW_NAME: not deleted ($(said))"
  az iot ops dataflow endpoint delete --resource-group "$RESOURCE_GROUP" --instance "$AIO_INSTANCE_NAME" \
    --name "$COMMAND_ENDPOINT_NAME" --yes --output none 2>"$ERR_FILE" && info "Endpoint $COMMAND_ENDPOINT_NAME deleted." \
    || info "Endpoint $COMMAND_ENDPOINT_NAME: not deleted ($(said))"
  WORKSPACE_ID="$(find_workspace)"
  if [[ -n "$WORKSPACE_ID" ]]; then
    EVENTSTREAM_ID="$(find_eventstream)"
    if [[ -n "$EVENTSTREAM_ID" ]]; then
      az rest --resource "$FABRIC_RESOURCE" --method delete --url "$FABRIC_API/workspaces/$WORKSPACE_ID/eventstreams/$EVENTSTREAM_ID" --output none 2>"$ERR_FILE" \
        && info "Eventstream $COMMAND_EVENTSTREAM_NAME deleted." || warn "Eventstream $COMMAND_EVENTSTREAM_NAME: not deleted ($(said))"
    else
      info "Eventstream $COMMAND_EVENTSTREAM_NAME: none in the workspace."
    fi
  fi
  info "Turbines that a command curtailed or stopped stay so until released: bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh release all"
  exit 0
fi

# ------------------------------------------------------------------------------- eventstream (step 1)
log "Fabric: workspace $FABRIC_WORKSPACE_NAME, eventstream $COMMAND_EVENTSTREAM_NAME"
WORKSPACE_ID="$(find_workspace)"
[[ -n "$WORKSPACE_ID" ]] || die "No workspace named $FABRIC_WORKSPACE_NAME is visible to this sign-in. Check FABRIC_WORKSPACE_NAME in config/demo.env and the account of 'az login'."
EVENTSTREAM_ID="$(find_eventstream)"
if [[ -z "$EVENTSTREAM_ID" ]]; then
  if [[ "$MODE" == "show" ]]; then
    info "Eventstream: none. Run this script without an option to create the command path."
    exit 0
  fi
  info "Creating the eventstream: custom endpoint $SOURCE_NODE -> default stream -> custom endpoint $DESTINATION_NODE"
  create_eventstream
  # The answer of a long-running creation may come before the item is listed.
  for _ in $(seq 1 "${EVENTSTREAM_TRIES:-12}"); do
    EVENTSTREAM_ID="$(find_eventstream)"
    [[ -n "$EVENTSTREAM_ID" ]] && break
    sleep "${EVENTSTREAM_WAIT_SECONDS:-10}"
  done
  [[ -n "$EVENTSTREAM_ID" ]] || die "Fabric accepted the eventstream and does not list it after two minutes. Look in the workspace, then run this script again."
  info "Created: $EVENTSTREAM_ID"
  CREATED_NOW=1
else
  info "It exists: $EVENTSTREAM_ID"
  CREATED_NOW=""
fi

# An eventstream that was created a moment ago is listed before Fabric has built its nodes from the definition: seen on
# 26 November 2026, when the topology read in the same second held neither endpoint. So after a creation the topology is
# asked for until both custom endpoints are in it, for two minutes at most. One that existed before is read once.
read_topology() {
  TOPOLOGY="$(fabric_get "workspaces/$WORKSPACE_ID/eventstreams/$EVENTSTREAM_ID/topology")" || die "Could not read the topology of the eventstream: $(said)"
  SOURCE_ID="$(node_id sources)"
  DESTINATION_ID="$(node_id destinations)"
}
read_topology
if [[ -n "$CREATED_NOW" && ( -z "$SOURCE_ID" || -z "$DESTINATION_ID" ) ]]; then
  info "Its two custom endpoints are not in its topology yet. Asking again, for up to $(( ${TOPOLOGY_TRIES:-12} * ${TOPOLOGY_WAIT_SECONDS:-10} )) seconds."
  for _ in $(seq 1 "${TOPOLOGY_TRIES:-12}"); do
    sleep "${TOPOLOGY_WAIT_SECONDS:-10}"
    read_topology
    [[ -n "$SOURCE_ID" && -n "$DESTINATION_ID" ]] && break
  done
fi
[[ -n "$SOURCE_ID" ]] || warn "The eventstream has no custom endpoint as a source. Notebook 12 needs one to write commands to. Add it in the portal (Add source, Custom endpoint, Publish)."
if [[ -z "$DESTINATION_ID" ]]; then
  warn "The eventstream has no custom endpoint as a destination, so the edge has nothing to read from."
  by_hand
  exit 3
fi

# A new destination needs a moment before its connection can be read.
CONNECTION=""
for _ in $(seq 1 "${CONNECTION_TRIES:-12}"); do
  CONNECTION="$(fabric_get "workspaces/$WORKSPACE_ID/eventstreams/$EVENTSTREAM_ID/destinations/$DESTINATION_ID/connection")" && break
  CONNECTION=""
  [[ "$MODE" == "show" ]] && break
  sleep "${CONNECTION_WAIT_SECONDS:-10}"
done
[[ -n "$CONNECTION" ]] || die "Fabric did not give the connection of the destination: $(said) An eventstream that was just created or changed must be published and running; open it in the portal and look."
NAMESPACE="$(json_read key_of fullyQualifiedNamespace <<< "$CONNECTION")"
EVENT_HUB="$(json_read key_of eventHubName <<< "$CONNECTION")"
CONSUMER_GROUP="$(json_read key_of consumerGroupName <<< "$CONNECTION")"
[[ -n "$NAMESPACE" && -n "$EVENT_HUB" && -n "$CONSUMER_GROUP" ]] || die "The connection of the destination is incomplete (namespace '$NAMESPACE', event hub '$EVENT_HUB', consumer group '$CONSUMER_GROUP'). The Fabric API answered in a form this script does not know."
HOST="$NAMESPACE:9093"
info "The edge reads from: $HOST"
info "  topic (event hub):  $EVENT_HUB"
info "  consumer group:     $CONSUMER_GROUP"
info "  source for notebook 12: ${SOURCE_ID:-none}"

# --------------------------------------------------------------------------------- the edge (steps 2, 3)
need_iot_ops_extension
if [[ "$MODE" == "show" ]]; then
  log "Azure IoT Operations instance $AIO_INSTANCE_NAME"
  az iot ops dataflow endpoint show --resource-group "$RESOURCE_GROUP" --instance "$AIO_INSTANCE_NAME" --name "$COMMAND_ENDPOINT_NAME" \
    --query "{endpoint:name, host:properties.kafkaSettings.host, consumerGroup:properties.kafkaSettings.consumerGroupId, state:properties.provisioningState}" --output table 2>"$ERR_FILE" \
    || info "Endpoint $COMMAND_ENDPOINT_NAME: none."
  az iot ops dataflow show --resource-group "$RESOURCE_GROUP" --instance "$AIO_INSTANCE_NAME" --profile default --name "$COMMAND_DATAFLOW_NAME" \
    --query "{dataflow:name, mode:properties.mode, state:properties.provisioningState}" --output table 2>"$ERR_FILE" \
    || info "Data flow $COMMAND_DATAFLOW_NAME: none."
  exit 0
fi

log "Edge: data flow endpoint $COMMAND_ENDPOINT_NAME (system-assigned managed identity, consumer group $CONSUMER_GROUP)"
az iot ops dataflow endpoint create fabric-realtime \
  --resource-group "$RESOURCE_GROUP" \
  --instance "$AIO_INSTANCE_NAME" \
  --name "$COMMAND_ENDPOINT_NAME" \
  --host "$HOST" \
  --auth-type SystemAssignedManagedIdentity \
  --group-id "$CONSUMER_GROUP" \
  --output none

log "Edge: data flow $COMMAND_DATAFLOW_NAME -> $CONTROL_TOPIC"
RENDER_DIR="$REPO_ROOT/edge/dataflows/rendered"
mkdir -p "$RENDER_DIR"
CONFIG_FILE="$RENDER_DIR/$COMMAND_DATAFLOW_NAME.json"
# COMMAND_DATAFLOW_MODE=Disabled creates the data flow switched off: everything is in place and no command
# reaches the simulator until this script is run again without it. tools/deploy.py always asks for Disabled.
[[ "$COMMAND_DATAFLOW_MODE" == "Enabled" ]] || info "The data flow is created switched off (COMMAND_DATAFLOW_MODE=Disabled)."
sed -e "s|__ENDPOINT_NAME__|$COMMAND_ENDPOINT_NAME|" -e "s|__COMMAND_TOPIC__|$EVENT_HUB|" -e "s|__CONTROL_TOPIC__|$CONTROL_TOPIC|" \
  -e "s|__DATAFLOW_MODE__|$COMMAND_DATAFLOW_MODE|" \
  "$REPO_ROOT/edge/dataflows/fabric-to-windfarm-control.template.json" > "$CONFIG_FILE"
az iot ops dataflow apply \
  --resource-group "$RESOURCE_GROUP" \
  --instance "$AIO_INSTANCE_NAME" \
  --profile default \
  --name "$COMMAND_DATAFLOW_NAME" \
  --config-file "$CONFIG_FILE" \
  --output none

log "Done"
az iot ops dataflow show --resource-group "$RESOURCE_GROUP" --instance "$AIO_INSTANCE_NAME" \
  --profile default --name "$COMMAND_DATAFLOW_NAME" \
  --query "{name:name, mode:properties.mode, state:properties.provisioningState}" --output table
info "Next: watch the control topic on the edge, then send a command with notebook 12 (guide, steps 3 and 4):"
info "  bash infra/vm.sh ssh bash ./edge/scripts/mqtt-peek.sh --count 2 '$TOPIC_ROOT/$SITE_ID/_control/#'"
info "What exists, at any time: bash infra/08-create-command-path.sh --show"
