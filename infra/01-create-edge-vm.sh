#!/usr/bin/env bash
# Step 1 (run on your workstation or in Azure Cloud Shell, signed in as yourself).
# Creates the resource group and the Ubuntu VM that plays the on-site edge
# server, and prepares what the later steps need:
#   - registers the resource providers used by Azure Arc and Azure IoT Operations
#   - picks the first VM size of VM_SIZE that your subscription is offered
#   - opens SSH only to your own public IP
#   - gives the VM's managed identity the roles to onboard a cluster to Azure Arc
#     (only when AZ_LOGIN_MODE=identity)
#   - prints the Custom Locations object ID for config/demo.env
# Safe to run again: an existing VM is kept as it is.
#
# Started by tools/deploy.py, DEPLOY_RUNNER=1 is set, and three things are left out, because the runner
# handles them under its own rules: registering resource providers (a change to the whole subscription,
# left to a person), creating the resource group (the runner makes it, with its tag), and the role
# assignments (a step of their own, which needs its own approval and stays on the resource group).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../config/load-env.sh"
need az curl
require SUBSCRIPTION_ID LOCATION RESOURCE_GROUP VM_NAME VM_SIZE VM_ADMIN
require_user_login
# A value that is already set must be an object ID; checked before anything is created.
if [[ -n "${CUSTOM_LOCATIONS_OID:-}" ]]; then require_object_id CUSTOM_LOCATIONS_OID; fi

az account set --subscription "$SUBSCRIPTION_ID"

if [[ -n "${DEPLOY_RUNNER:-}" ]]; then
  az group show --name "$RESOURCE_GROUP" --output none 2>/dev/null \
    || die "Resource group $RESOURCE_GROUP does not exist. With DEPLOY_RUNNER set, tools/deploy.py creates it first."
else
  log "Registering resource providers (once per subscription)"
  for rp in Microsoft.ExtendedLocation Microsoft.Kubernetes Microsoft.KubernetesConfiguration \
            Microsoft.IoTOperations Microsoft.DeviceRegistry Microsoft.SecretSyncController \
            Microsoft.Storage Microsoft.Insights; do
    az provider register --namespace "$rp" --output none
    info "$rp"
  done

  log "Creating resource group $RESOURCE_GROUP in $LOCATION"
  az group create --name "$RESOURCE_GROUP" --location "$LOCATION" --output none
fi

EXISTING_SIZE="$(az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --query hardwareProfile.vmSize --output tsv 2>/dev/null || true)"
if [[ -n "$EXISTING_SIZE" ]]; then
  log "VM $VM_NAME exists already ($EXISTING_SIZE); keeping it"
else
  # VM_SIZE lists sizes in order of preference. Subscriptions differ in what they are
  # offered, so each size is checked, and the next one is tried when Azure refuses one.
  CREATED=""
  ERROR_FILE="$(mktemp)"
  # VM_SIZE_OFFERED: sizes somebody has already checked, in order. tools/deploy.py sets it after one quick,
  # filtered question to Azure. Without it this script asks for each size with `az vm list-skus`, which
  # fetches the sizes of every region: seconds in Cloud Shell, minutes from some workstations.
  [[ -n "${VM_SIZE_OFFERED:-}" ]] || info "Asking Azure which of these sizes you are offered: $VM_SIZE. Each answer can take minutes."
  for SIZE in ${VM_SIZE_OFFERED:-$VM_SIZE}; do
    if [[ -z "${VM_SIZE_OFFERED:-}" ]]; then
      # The CLI prints the two values on two lines; paste joins them: "name<TAB>reason".
      OFFER="$(az vm list-skus --location "$LOCATION" --resource-type virtualMachines --all --size "$SIZE" \
        --query "[?name=='$SIZE'] | [0].[name, restrictions[?type=='Location'] | [0].reasonCode]" --output tsv 2>/dev/null \
        | paste -sd '\t' - || true)"
      if [[ -z "$OFFER" ]]; then
        info "$SIZE: not known in $LOCATION, skipping"
        continue
      fi
      REASON="$(cut -f2 <<< "$OFFER")"
      if [[ -n "$REASON" && "$REASON" != "None" ]]; then
        info "$SIZE: not offered to this subscription in $LOCATION ($REASON), skipping"
        continue
      fi
    fi
    log "Creating VM $VM_NAME ($SIZE, Ubuntu 24.04 LTS)"
    if az vm create \
        --resource-group "$RESOURCE_GROUP" \
        --name "$VM_NAME" \
        --image "Canonical:ubuntu-24_04-lts:server:latest" \
        --size "$SIZE" \
        --admin-username "$VM_ADMIN" \
        --generate-ssh-keys \
        --os-disk-size-gb 128 \
        --storage-sku Premium_LRS \
        --public-ip-sku Standard \
        --nsg-rule NONE \
        --assign-identity "[system]" \
        --output none 2>"$ERROR_FILE"; then
      CREATED="$SIZE"
      break
    fi
    if grep -q -i -E "SkuNotAvailable|not available in location|NotAvailableForSubscription" "$ERROR_FILE"; then
      info "$SIZE: refused by Azure for this subscription, trying the next size"
      continue
    fi
    cat "$ERROR_FILE" >&2
    rm -f "$ERROR_FILE"
    die "Creating the VM failed (see the message above)."
  done
  rm -f "$ERROR_FILE"
  [[ -n "$CREATED" ]] || die "None of these sizes is offered to your subscription in $LOCATION: $VM_SIZE. List what is offered with: az vm list-skus --location $LOCATION --resource-type virtualMachines --size Standard_D8 --output table   Then put a size with 8 vCPU and 32 GB (x86, no restriction shown) first in VM_SIZE in config/demo.env and run this script again."
  info "Created with size $CREATED"
fi

log "Allowing SSH from your address only"
SOURCE="${SSH_SOURCE_CIDR:-}"
if [[ -z "$SOURCE" ]]; then
  SOURCE="$(curl -fsS https://api.ipify.org)/32"
fi
az network nsg rule create \
  --resource-group "$RESOURCE_GROUP" \
  --nsg-name "${VM_NAME}NSG" \
  --name allow-ssh-from-admin \
  --priority 1000 \
  --direction Inbound --access Allow --protocol Tcp \
  --source-address-prefixes "$SOURCE" \
  --destination-port-ranges 22 \
  --output none
info "SSH allowed from $SOURCE"

if [[ -n "${VM_AUTO_SHUTDOWN_UTC:-}" ]]; then
  log "Scheduling daily auto-shutdown at ${VM_AUTO_SHUTDOWN_UTC} UTC"
  az vm auto-shutdown --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
    --time "$VM_AUTO_SHUTDOWN_UTC" --output none
  SHUTDOWN_NOTE="every day at ${VM_AUTO_SHUTDOWN_UTC:0:2}:${VM_AUTO_SHUTDOWN_UTC:2:2} UTC"
  SHUTDOWN_ELSEWHERE="$(utc_time_elsewhere "$VM_AUTO_SHUTDOWN_UTC")"
else
  SHUTDOWN_NOTE="not scheduled; stop the VM yourself with bash infra/vm.sh stop"
  SHUTDOWN_ELSEWHERE=""
fi

PRINCIPAL_ID="$(az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
  --query identity.principalId --output tsv)"
if [[ "${AZ_LOGIN_MODE:-identity}" == "identity" && -z "${DEPLOY_RUNNER:-}" ]]; then
  # The VM signs in with its managed identity to onboard the cluster to Azure Arc.
  # It needs the onboarding role on the resource group, and read access to the
  # subscription so the CLI can confirm that the resource providers are registered.
  log "Granting the VM's managed identity the roles for Arc onboarding"
  RG_ID="$(az group show --name "$RESOURCE_GROUP" --query id --output tsv)"
  az role assignment create \
    --assignee-object-id "$PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Kubernetes Cluster - Azure Arc Onboarding" \
    --scope "$RG_ID" \
    --output none
  info "Kubernetes Cluster - Azure Arc Onboarding on $RESOURCE_GROUP"
  az role assignment create \
    --assignee-object-id "$PRINCIPAL_ID" \
    --assignee-principal-type ServicePrincipal \
    --role "Reader" \
    --scope "/subscriptions/$SUBSCRIPTION_ID" \
    --output none
  info "Reader on the subscription (you can remove this after step 3 of the guide)"
fi

PUBLIC_IP="$(az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --show-details \
  --query publicIps --output tsv)"
OID="${CUSTOM_LOCATIONS_OID:-}"
OID_ERROR_FILE="$(mktemp)"
if [[ -z "$OID" ]]; then
  # The Custom Locations service principal appears in the tenant once the
  # Microsoft.ExtendedLocation provider has finished registering, so wait for that first.
  for _ in $(seq 1 30); do
    STATE="$(az provider show --namespace Microsoft.ExtendedLocation --query registrationState --output tsv 2>/dev/null || true)"
    [[ "$STATE" == "Registered" ]] && break
    sleep 10
  done
  # This lookup needs a signed-in user (not a service principal) with permission to read
  # service principals in Microsoft Entra ID. Azure Cloud Shell often lacks that permission.
  OID="$(az ad sp show --id bc313c14-388c-4e7d-a58e-70017303ee3b --query id --output tsv 2>"$OID_ERROR_FILE" || true)"
  OID_IS_NEW=yes
fi

log "Done"
info "VM public IP:              $PUBLIC_IP"
info "VM administrator:          $VM_ADMIN   (the user name for SSH; not your own name)"
info "Copy the repository:       bash infra/vm.sh push"
info "Connect:                   bash infra/vm.sh ssh"
info "VM managed identity name:  $VM_NAME   (object ID $PRINCIPAL_ID)"
info "VM shuts down:             $SHUTDOWN_NOTE"
if [[ -n "$SHUTDOWN_ELSEWHERE" ]]; then
  info "                           that is $SHUTDOWN_ELSEWHERE"
fi
info "                           start it again with bash infra/vm.sh start; change the time with bash infra/vm.sh shutdown HHMM"
if [[ -n "$OID" && -n "${OID_IS_NEW:-}" ]]; then
  info "Custom Locations OID:      $OID"
  info "Put this line in config/demo.env:  CUSTOM_LOCATIONS_OID=\"$OID\""
elif [[ -n "$OID" ]]; then
  info "Custom Locations OID:      $OID   (from config/demo.env)"
else
  warn "Could not read the Custom Locations object ID. Azure CLI said:"
  warn "  $(tr '\n' ' ' < "$OID_ERROR_FILE")"
  warn "See 'Step 1: the Custom Locations object ID is not printed' in docs/troubleshooting.md."
fi
rm -f "$OID_ERROR_FILE"
info "SSH is open to the address you are on now. Some subscriptions replace that rule with"
info "just-in-time access a few hours later; bash infra/vm.sh ssh and bash infra/vm.sh push deal with that."
