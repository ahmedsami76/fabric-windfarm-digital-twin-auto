#!/usr/bin/env bash
# Step 2 (run on the edge VM).
# Installs everything the edge server needs before it is connected to Azure:
# Azure CLI, K3s, Helm, Docker (to build the simulator image) and the system
# settings that Azure IoT Operations requires. Safe to run again.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../../config/load-env.sh"
require_edge_vm

K3S_CHANNEL="${K3S_CHANNEL:-stable}"

log "Installing base packages"
sudo apt-get update -y
sudo apt-get install -y curl ca-certificates jq git python3-venv docker.io

log "Installing Azure CLI"
if ! command -v az >/dev/null 2>&1; then
  curl -fsSL https://aka.ms/InstallAzureCLIDeb | sudo bash
fi
az extension add --upgrade --yes --name connectedk8s
az extension add --upgrade --yes --name azure-iot-ops

log "Applying system settings required by Azure IoT Operations"
sudo tee /etc/sysctl.d/99-azure-iot-operations.conf >/dev/null <<'SYSCTL'
fs.inotify.max_user_instances=8192
fs.inotify.max_user_watches=524288
fs.file-max=100000
SYSCTL
sudo sysctl --system >/dev/null

log "Installing K3s (channel: $K3S_CHANNEL)"
if ! command -v k3s >/dev/null 2>&1; then
  curl -sfL https://get.k3s.io | INSTALL_K3S_CHANNEL="$K3S_CHANNEL" sh -s - \
    --disable=traefik --write-kubeconfig-mode 644
fi

log "Configuring kubectl for $USER"
mkdir -p "$HOME/.kube"
sudo cp /etc/rancher/k3s/k3s.yaml "$HOME/.kube/config"
sudo chown "$(id -u):$(id -g)" "$HOME/.kube/config"
chmod 600 "$HOME/.kube/config"
# shellcheck disable=SC2016  # the variable must expand when .bashrc runs, not now
grep -q 'KUBECONFIG=' "$HOME/.bashrc" || echo 'export KUBECONFIG=$HOME/.kube/config' >> "$HOME/.bashrc"
export KUBECONFIG="$HOME/.kube/config"

log "Installing Helm"
if ! command -v helm >/dev/null 2>&1; then
  curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
fi

log "Waiting for the cluster node to become Ready"
for _ in $(seq 1 36); do
  kubectl get nodes 2>/dev/null | grep -q . && break
  sleep 5
done
kubectl wait --for=condition=Ready node --all --timeout=180s
kubectl get nodes -o wide

log "Done"
info "K3s version: $(k3s --version | head -n1)"
info "Open a new shell (or run: export KUBECONFIG=\$HOME/.kube/config) before the next step."
