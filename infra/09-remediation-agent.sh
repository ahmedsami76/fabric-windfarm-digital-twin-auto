#!/usr/bin/env bash
# Phase 5b (run on your workstation, signed in as yourself): the operations agent learns to
# propose a curtailment, and gets the action that carries it out when a person approves.
#
#   bash infra/09-remediation-agent.sh                    give the agent its Phase 5b instructions and the action
#   bash infra/09-remediation-agent.sh --show             say how the agent is set up; change nothing
#   bash infra/09-remediation-agent.sh --save             the same, and write the agent's definition to a file
#   bash infra/09-remediation-agent.sh --rehearse WT-07   run the action's notebook as a job, the way the agent does
#   bash infra/09-remediation-agent.sh --restore FILE     put back a saved definition, if Fabric accepts it
#
# What the first form does, in this order:
#   1. Reads the definition of the operations agent WindFarmGearboxWatch from the Fabric API and
#      saves it, unchanged, under fabric/operations-agent/saved/. --restore takes that file.
#   2. Replaces the agent's instructions with fabric/operations-agent/phase5b-agent-setup.txt and
#      adds the action 'Curtail turbine': the notebook 12_send_edge_command, with the parameters
#      turbine, percent, duration and requested_by. The data source, the recipient of the
#      messages and any other action are kept as they are.
#   3. Leaves the agent stopped and reads the definition back. You then open the agent in the
#      portal, generate the playbook, compare its rule with the guide, and start it.
#
# --rehearse sends a real command: the turbine is limited to 30 percent for 2 minutes and then
# released by itself. It shows that the notebook works as a job, with its values passed as text,
# before the agent is involved, and how long such a run takes.
#
# The Fabric API accepts these calls from a signed-in user only, not from a service principal or
# a managed identity. The token comes from the Azure CLI, is passed on in the environment of one
# command, and is not stored or printed.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../config/load-env.sh"

MODE="apply"; ARGUMENT=""
case "${1:-}" in
  "") ;;
  --show) MODE="show" ;;
  --save) MODE="save" ;;
  --rehearse) MODE="rehearse"; ARGUMENT="${2:-}"
    [[ -n "$ARGUMENT" ]] || die "Name the turbine: bash infra/09-remediation-agent.sh --rehearse WT-07" ;;
  --restore) MODE="restore"; ARGUMENT="${2:-}"
    [[ -n "$ARGUMENT" ]] || die "Name the file: bash infra/09-remediation-agent.sh --restore fabric/operations-agent/saved/FILE.json"
    [[ -f "$ARGUMENT" ]] || die "No file $ARGUMENT. The saved definitions are in fabric/operations-agent/saved/." ;;
  *) die "Unknown option $1. Use no option, --show, --save, --rehearse TURBINE or --restore FILE." ;;
esac

need az python3
: "${FABRIC_WORKSPACE_NAME:=WindFarmDigitalTwin}"
: "${OPERATIONS_AGENT_NAME:=WindFarmGearboxWatch}"
: "${EVENTHOUSE_NAME:=WindFarmEH}"
export FABRIC_WORKSPACE_NAME OPERATIONS_AGENT_NAME EVENTHOUSE_NAME
FABRIC_RESOURCE="https://api.fabric.microsoft.com"
ERR_FILE="$(mktemp)"
trap 'rm -f "$ERR_FILE"' EXIT

require_user_login
if ! TOKEN="$(az account get-access-token --resource "$FABRIC_RESOURCE" --query accessToken --output tsv 2>"$ERR_FILE")" || [[ -z "$TOKEN" ]]; then
  die "The Azure CLI gave no token for the Fabric API: $(tr '\n' ' ' < "$ERR_FILE" | cut -c1-400) Sign in with 'az login' as the account that created the agent."
fi

case "$MODE" in
  apply) log "Operations agent $OPERATIONS_AGENT_NAME: Phase 5b instructions and the action" ;;
  show) log "Operations agent $OPERATIONS_AGENT_NAME: how it is set up" ;;
  save) log "Operations agent $OPERATIONS_AGENT_NAME: how it is set up, and its definition to a file" ;;
  rehearse) log "Rehearsal: notebook 12_send_edge_command as a job, for $ARGUMENT" ;;
  restore) log "Operations agent $OPERATIONS_AGENT_NAME: putting back $ARGUMENT" ;;
esac

RC=0
if [[ -n "$ARGUMENT" ]]; then
  FABRIC_TOKEN="$TOKEN" python3 "$REPO_ROOT/tools/operations_agent.py" "$MODE" "$ARGUMENT" || RC=$?
else
  FABRIC_TOKEN="$TOKEN" python3 "$REPO_ROOT/tools/operations_agent.py" "$MODE" || RC=$?
fi

if [[ "$RC" -eq 3 && "$MODE" == "apply" ]]; then
  warn "The agent was not changed through the Fabric API."
  info "Do it by hand instead: step 4 of docs/13-deployment-guide-phase5b.md, the part headed 'By hand'. It takes about five minutes."
  info "The texts to paste are fabric/operations-agent/phase5b-agent-setup.txt and phase5b-action.txt."
elif [[ "$RC" -eq 1 && "$MODE" == "apply" ]]; then
  warn "The definition read back differs from what was written (the lines under 'Differs from Phase 5b')."
  info "Open the agent in the portal and compare; step 4 of the guide, the part headed 'By hand', says what each field should hold."
fi
if [[ "$RC" -eq 3 && "$MODE" == "restore" ]]; then
  warn "The saved definition was not put back. The agent is as it was."
  info "Fabric checks a definition when it is written. A playbook that the portal generated can fail that check"
  info "(seen on 24 November 2026: an object of the playbook defined once for each rule)."
  info "To go back by hand: open the agent, paste the instructions you want into Agent setup, remove the action"
  info "if you do not want it, and generate the playbook. The Phase 3 text is fabric/operations-agent/agent-setup.txt."
fi
exit "$RC"
