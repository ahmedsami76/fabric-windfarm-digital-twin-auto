#!/usr/bin/env bash
# One command for the demo: inject an anomaly that resolves by itself.
#   bash edge/scripts/inject-anomaly.sh                       # WT-07, gearbox_degradation, 0.8, 15m
#   bash edge/scripts/inject-anomaly.sh WT-03 generator_overheat 0.9 20m
set -euo pipefail
TURBINE="${1:-WT-07}"
KIND="${2:-gearbox_degradation}"
SEVERITY="${3:-0.8}"
DURATION="${4:-15m}"
HERE="$(dirname "${BASH_SOURCE[0]}")"
# Started through bash on purpose: the scripts must also work in a copy of the
# repository that lost its execute permissions (unpacked on Windows, for example).
bash "$HERE/simctl.sh" inject "$TURBINE" "$KIND" --severity "$SEVERITY" --duration "$DURATION"
echo
echo "Injected. Follow it with:  bash $HERE/simctl.sh status"
