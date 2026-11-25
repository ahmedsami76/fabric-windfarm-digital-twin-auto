#!/usr/bin/env bash
# Step 5 (run on the edge VM).
# Builds the simulator image, loads it into K3s and starts the simulator, which
# publishes to the Azure IoT Operations MQTT broker. Run it again after changing
# the simulator code or edge/k8s/simulator.yaml.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../../config/load-env.sh"
require_edge_vm
need kubectl docker
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
SIM_IMAGE="${SIM_IMAGE:-windfarm-simulator:1.2.0}"
SIM_NAMESPACE="${SIM_NAMESPACE:-windfarm}"
AIO_NAMESPACE="azure-iot-operations"
CA_CONFIGMAP="azure-iot-operations-aio-ca-trust-bundle"

log "Checking the MQTT broker"
kubectl get service aio-broker -n "$AIO_NAMESPACE" >/dev/null \
  || die "Service aio-broker not found. Deploy Azure IoT Operations first (step 4)."

log "Building image $SIM_IMAGE"
sudo docker build -f "$REPO_ROOT/simulator/Dockerfile" -t "$SIM_IMAGE" "$REPO_ROOT"

log "Importing the image into K3s"
sudo docker save "$SIM_IMAGE" | sudo k3s ctr images import -

log "Creating namespace and copying the broker CA certificate"
kubectl create namespace "$SIM_NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
TMP_CA="$(mktemp -d)"
kubectl get configmap "$CA_CONFIGMAP" -n "$AIO_NAMESPACE" -o jsonpath='{.data.ca\.crt}' > "$TMP_CA/ca.crt"
[[ -s "$TMP_CA/ca.crt" ]] || die "Could not read ca.crt from ConfigMap $AIO_NAMESPACE/$CA_CONFIGMAP."
kubectl create configmap aio-ca-trust-bundle -n "$SIM_NAMESPACE" --from-file=ca.crt="$TMP_CA/ca.crt" \
  --dry-run=client -o yaml | kubectl apply -f -
rm -rf "$TMP_CA"

log "Deploying the simulator"
sed -E -e "s|image: windfarm-simulator:[0-9.]+|image: ${SIM_IMAGE}|" \
    -e "s|namespace: windfarm$|namespace: ${SIM_NAMESPACE}|" \
    -e "s|^  name: windfarm$|  name: ${SIM_NAMESPACE}|" \
    "$REPO_ROOT/edge/k8s/simulator.yaml" | kubectl apply -f -
kubectl rollout restart deployment/windfarm-simulator -n "$SIM_NAMESPACE"
kubectl rollout status deployment/windfarm-simulator -n "$SIM_NAMESPACE" --timeout=180s

log "Simulator log (waiting 40 seconds for the first status line)"
sleep 40
kubectl logs deployment/windfarm-simulator -n "$SIM_NAMESPACE" --tail=15

log "Done"
info "From the workstation:"
info "  Status:        bash infra/vm.sh ssh bash ./edge/scripts/simctl.sh status"
info "  Watch topics:  bash infra/vm.sh ssh bash ./edge/scripts/mqtt-peek.sh --count 20"
