#!/usr/bin/env bash
# Step 3 (run on the edge VM).
# Connects the K3s cluster to Azure Arc with the features Azure IoT Operations
# needs: OIDC issuer, workload identity, cluster connect and custom locations.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../../config/load-env.sh"
require_edge_vm
need az kubectl
require SUBSCRIPTION_ID LOCATION RESOURCE_GROUP CLUSTER_NAME
require_object_id CUSTOM_LOCATIONS_OID
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"

log "Signing in to Azure (mode: ${AZ_LOGIN_MODE:-identity})"
if [[ "${AZ_LOGIN_MODE:-identity}" == "device" ]]; then
  az account show >/dev/null 2>&1 || az login --use-device-code --output none
else
  az login --identity --output none
fi
az account set --subscription "$SUBSCRIPTION_ID"

log "Connecting cluster $CLUSTER_NAME to Azure Arc (this takes a few minutes)"
if az connectedk8s show --name "$CLUSTER_NAME" --resource-group "$RESOURCE_GROUP" >/dev/null 2>&1; then
  info "Cluster is already connected; skipping."
else
  az connectedk8s connect \
    --name "$CLUSTER_NAME" \
    --location "$LOCATION" \
    --resource-group "$RESOURCE_GROUP" \
    --subscription "$SUBSCRIPTION_ID" \
    --enable-oidc-issuer \
    --enable-workload-identity \
    --disable-auto-upgrade
fi

log "Configuring the K3s service account issuer"
ISSUER_URL="$(az connectedk8s show --resource-group "$RESOURCE_GROUP" --name "$CLUSTER_NAME" \
  --query oidcIssuerProfile.issuerUrl --output tsv)"
[[ -n "$ISSUER_URL" ]] || die "The cluster has no OIDC issuer URL yet. Wait a minute and run this script again."
sudo tee /etc/rancher/k3s/config.yaml >/dev/null <<K3SCONF
kube-apiserver-arg:
  - service-account-issuer=${ISSUER_URL}
  - service-account-max-token-expiration=24h
K3SCONF
info "Issuer: $ISSUER_URL"

log "Enabling cluster connect and custom locations"
# With a managed identity sign-in the command warns that it cannot validate the object ID;
# that is expected. It also only warns when it leaves custom locations out, and step 4 would
# then fail much later, so its messages are checked here.
FEATURES_LOG="$(mktemp)"
az connectedk8s enable-features \
  --name "$CLUSTER_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --custom-locations-oid "$CUSTOM_LOCATIONS_OID" \
  --features cluster-connect custom-locations 2>&1 | tee "$FEATURES_LOG"
ENABLED_LINE="$(grep -i "enabled features" "$FEATURES_LOG" || true)"
if grep -q -i -E "couldn't be enabled|was not enabled|wasn't enabled|Failed to enable Custom Locations" "$FEATURES_LOG" \
   || [[ -n "$ENABLED_LINE" && "$ENABLED_LINE" != *custom-locations* ]]; then
  rm -f "$FEATURES_LOG"
  die "The custom locations feature was not enabled; the reason is in the messages above. In identity mode the VM's identity needs the Reader role on the subscription, and a role given minutes ago may not be in force yet: wait five minutes and run this step again. See 'Step 3: custom locations are not enabled' in docs/troubleshooting.md."
fi
rm -f "$FEATURES_LOG"
info "Custom locations enabled for object ID $CUSTOM_LOCATIONS_OID. Azure does not check this value here: a wrong one shows in step 4."

log "Restarting K3s to apply the issuer settings"
sudo systemctl restart k3s
for _ in $(seq 1 36); do
  sleep 5
  kubectl get nodes >/dev/null 2>&1 && break
done
kubectl wait --for=condition=Ready node --all --timeout=180s

log "Done"
az connectedk8s show --name "$CLUSTER_NAME" --resource-group "$RESOURCE_GROUP" \
  --query "{name:name, connectivity:connectivityStatus, kubernetes:kubernetesVersion, distribution:distribution}" \
  --output table
kubectl get pods -n azure-arc
