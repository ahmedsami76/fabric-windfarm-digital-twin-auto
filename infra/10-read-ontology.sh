#!/usr/bin/env bash
# The ontology (run on your workstation, signed in as yourself): read the definition of every ontology
# item of the demo's workspace, as Fabric gives it, and save it. Changes nothing in Fabric.
#
#   bash infra/10-read-ontology.sh
#
# What it is for. Notebook 11 creates WindFarmOntology in the old ontology experience, which Microsoft
# retires on 31 January 2027. The new experience has another definition, and Microsoft's reference does
# not show everything a tenant's portal writes into it. So the definition is read from a tenant:
#   1. In the workspace open WindFarmOntology. In its banner about the new experience, select the
#      button that creates a copy in the new experience.
#   2. Run this script. It reads both items and prints what each definition holds.
#   3. Send the one archive it names, under fabric/ontology/saved/.
#
# It makes two kinds of call: the list of the workspace's items, and Get Ontology Definition for each
# ontology (a preview). The token comes from the Azure CLI, is passed on in the environment of one
# command, and is not stored or printed.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../config/load-env.sh"

[[ -z "${1:-}" ]] || die "Unknown option $1. This script takes none: bash infra/10-read-ontology.sh"

need az python3
: "${FABRIC_WORKSPACE_NAME:=WindFarmDigitalTwin}"
export FABRIC_WORKSPACE_NAME
FABRIC_RESOURCE="https://api.fabric.microsoft.com"
ERR_FILE="$(mktemp)"
trap 'rm -f "$ERR_FILE"' EXIT

require_user_login
if ! TOKEN="$(az account get-access-token --resource "$FABRIC_RESOURCE" --query accessToken --output tsv 2>"$ERR_FILE")" || [[ -z "$TOKEN" ]]; then
  die "The Azure CLI gave no token for the Fabric API: $(tr '\n' ' ' < "$ERR_FILE" | cut -c1-400) Sign in with 'az login'."
fi

log "Ontology items of workspace $FABRIC_WORKSPACE_NAME: their definitions, read and saved"
RC=0
FABRIC_TOKEN="$TOKEN" python3 "$REPO_ROOT/tools/ontology_definitions.py" || RC=$?
if [[ "$RC" -eq 3 ]]; then
  warn "Not every definition was read. Send me the lines above: they say which, and what Fabric answered."
fi
exit "$RC"
