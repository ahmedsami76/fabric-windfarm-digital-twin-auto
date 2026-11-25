#!/usr/bin/env bash
# Step 7 (run on the edge VM).
# Uploads the site's reference data (asset master data, contracts, people, GIS
# layers, terrain) and SOP documents to the Files area of the Fabric Lakehouse.
# Run it again whenever the files change; only new or changed files are uploaded.
#
# Before running: the VM's managed identity (named after the VM) must be a
# Contributor on the Fabric workspace (deployment guide, step 6.5).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../../config/load-env.sh"
require_edge_vm
need python3
require FABRIC_WORKSPACE_NAME FABRIC_LAKEHOUSE_NAME

VENV="$HOME/.venvs/reference-sync"
if [[ ! -x "$VENV/bin/python" ]]; then
  log "Creating Python environment"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install --quiet --upgrade pip
  "$VENV/bin/pip" install --quiet -r "$REPO_ROOT/edge/reference-sync/requirements.txt"
fi

log "Syncing reference data to $FABRIC_WORKSPACE_NAME / $FABRIC_LAKEHOUSE_NAME"
"$VENV/bin/python" "$REPO_ROOT/edge/reference-sync/sync_to_onelake.py" \
  --workspace "$FABRIC_WORKSPACE_NAME" --lakehouse "$FABRIC_LAKEHOUSE_NAME" "$@"
