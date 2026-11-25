#!/usr/bin/env bash
# Subscribe to the wind farm topics on the Azure IoT Operations broker from a
# diagnostic pod (run on the edge VM).
#   bash edge/scripts/mqtt-peek.sh                              everything under contoso/windfarm, until Ctrl+C
#   bash edge/scripts/mqtt-peek.sh 'contoso/windfarm/+/WT-07/#' one turbine, until Ctrl+C
#   bash edge/scripts/mqtt-peek.sh --count 20 [TOPIC]           print 20 messages and stop (works without a
#                                                               terminal, for example through bash infra/vm.sh run)
#   bash edge/scripts/mqtt-peek.sh --delete                     remove the diagnostic pod
set -euo pipefail
command -v kubectl >/dev/null 2>&1 || {
  echo "ERROR: kubectl not found. This script runs on the edge VM: connect with bash infra/vm.sh ssh" >&2
  exit 1
}
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NS="azure-iot-operations"

if [[ "${1:-}" == "--delete" ]]; then
  kubectl delete -f "$HERE/../k8s/mqtt-client.yaml" --ignore-not-found
  exit 0
fi
COUNT=""
if [[ "${1:-}" == "--count" ]]; then
  COUNT="${2:-}"
  [[ "$COUNT" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: give a number of messages, for example: --count 20" >&2; exit 2; }
  shift 2
fi
TOPIC="${1:-contoso/windfarm/#}"
[[ "$TOPIC" != *"'"* ]] || { echo "ERROR: the topic must not contain a single quote" >&2; exit 2; }

kubectl apply -f "$HERE/../k8s/mqtt-client.yaml" >/dev/null
kubectl wait --for=condition=Ready pod/mqtt-client -n "$NS" --timeout=180s >/dev/null
# The pod installs the mosquitto tools when it starts; wait until they are there.
for _ in $(seq 1 30); do
  kubectl exec mqtt-client -n "$NS" -- sh -c 'command -v mosquitto_sub' >/dev/null 2>&1 && break
  sleep 2
done

SUBSCRIBE="mosquitto_sub --host aio-broker --port 18883 --topic '$TOPIC' --verbose \
  --cafile /var/run/certs/ca.crt -D CONNECT authentication-method 'K8S-SAT' \
  -D CONNECT authentication-data \"\$(cat /var/run/secrets/tokens/broker-sat)\""
if [[ -n "$COUNT" ]]; then
  # -C stops after that many messages, -W gives up after 60 seconds without them.
  kubectl exec mqtt-client -n "$NS" -- sh -c "$SUBSCRIBE -C $COUNT -W 60"
else
  echo "Subscribing to $TOPIC (Ctrl+C to stop)"
  kubectl exec -it mqtt-client -n "$NS" -- sh -c "$SUBSCRIBE"
fi
