#!/usr/bin/env bash
# Edge VM helper (run on your workstation or in Azure Cloud Shell, signed in as yourself).
#
#   bash infra/vm.sh status              power state, address, SSH access, daily shutdown
#   bash infra/vm.sh start               start the VM and wait until it answers
#   bash infra/vm.sh stop                stop and deallocate the VM (ends the compute cost)
#   bash infra/vm.sh ssh                 open a shell on the VM (opens SSH access first if it is closed)
#   bash infra/vm.sh ssh COMMAND         run one command on the VM, in the repository folder, for example:
#                                        bash infra/vm.sh ssh bash ./edge/scripts/inject-anomaly.sh
#   bash infra/vm.sh push                copy this repository, with config/demo.env, to the VM
#   bash infra/vm.sh push-env            copy only config/demo.env to the VM
#   bash infra/vm.sh run COMMAND         run a command on the VM without SSH (through the VM agent)
#   bash infra/vm.sh jit [HOURS]         ask for just-in-time SSH access from the address you are on now
#   bash infra/vm.sh allow-my-ip         point the SSH rule at the address you are on now
#   bash infra/vm.sh reset-key [FILE]    install your public SSH key on the VM again
#   bash infra/vm.sh nsg-log [HOURS]     who changed the firewall rules, and the rules in force
#   bash infra/vm.sh shutdown HHMM|off   change or remove the daily shutdown (time in UTC)
#
# "ssh" and "push" work out by themselves how SSH is opened in your subscription: by
# just-in-time access where Microsoft Defender for Cloud controls port 22, otherwise by
# the rule that step 1 created. "run" needs no SSH at all: it is not interactive, takes
# at least 20 seconds and returns only the last 4,096 bytes of output.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../config/load-env.sh"

usage() { sed -n '2,23p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
ACTION="${1:-}"
case "$ACTION" in
  status|start|stop|ssh|push|push-env|run|jit|allow-my-ip|reset-key|nsg-log|shutdown) ;;
  *) usage; exit 2 ;;
esac

need az curl
require SUBSCRIPTION_ID RESOURCE_GROUP VM_NAME VM_ADMIN
require_user_login
az account set --subscription "$SUBSCRIPTION_ID"

NSG_NAME="${VM_NAME}NSG"
RULE_NAME="allow-ssh-from-admin"
# "az vm auto-shutdown" stores the schedule as a resource with this fixed name.
SCHEDULE_NAME="shutdown-computevm-${VM_NAME}"
# Folder of the repository on the VM, under the home folder of VM_ADMIN.
REMOTE_DIR="${VM_REPO_DIR:-fabric-windfarm-digital-twin}"
SSH_OPTIONS=(-o StrictHostKeyChecking=accept-new -o ConnectTimeout=15)

power_state() {
  az vm show --show-details --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --query powerState --output tsv
}
public_ip() {
  az vm show --show-details --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --query publicIps --output tsv
}
# Sets VM_STATE and IP with one call to Azure (each call takes a few seconds).
read_state_and_address() {
  local both
  both="$(az vm show --show-details --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" \
    --query "[powerState, publicIps]" --output tsv | paste -sd '\t' -)"
  VM_STATE="${both%%$'\t'*}"
  IP="${both##*$'\t'}"
}
# The address the rule of step 1 allows SSH from; empty when that rule does not exist.
rule_source() {
  az network nsg rule show --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" --name "$RULE_NAME" \
    --query "sourceAddressPrefix || join(',', sourceAddressPrefixes)" --output tsv 2>/dev/null || true
}
# The address this machine reaches the internet from (or the range set in demo.env).
my_address() {
  if [[ -n "${SSH_SOURCE_CIDR:-}" ]]; then
    printf '%s' "$SSH_SOURCE_CIDR"
  else
    printf '%s/32' "$(curl -fsS https://api.ipify.org)"
  fi
}
# Prints "Enabled 0800", "Disabled 0800" or nothing when no schedule exists.
shutdown_schedule() {
  az resource show --resource-group "$RESOURCE_GROUP" --name "$SCHEDULE_NAME" \
    --resource-type Microsoft.DevTestLab/schedules \
    --query "join(' ', [properties.status, properties.dailyRecurrence.time])" --output tsv 2>/dev/null || true
}
describe_shutdown() {
  local schedule status hhmm elsewhere
  schedule="$(shutdown_schedule)"
  status="${schedule%% *}"
  hhmm="${schedule##* }"
  if [[ "$status" != "Enabled" || ! "$hhmm" =~ ^[0-9]{4}$ ]]; then
    printf 'none; the VM runs, and costs, until you stop it'
    return
  fi
  elsewhere="$(utc_time_elsewhere "$hhmm")"
  printf 'every day at %s:%s UTC%s' "${hhmm:0:2}" "${hhmm:2:2}" "${elsewhere:+ ($elsewhere)}"
}
port_22_open() {
  local ip="$1"
  if command -v timeout >/dev/null 2>&1; then
    timeout 5 bash -c "exec 3<>/dev/tcp/${ip}/22" 2>/dev/null
  elif command -v nc >/dev/null 2>&1; then
    nc -z -w 5 "$ip" 22 >/dev/null 2>&1
  else
    bash -c "exec 3<>/dev/tcp/${ip}/22" 2>/dev/null
  fi
}
# Every source that may reach port 22 now, one per line: source <TAB> rule name.
ssh_openings() {
  az network nsg rule list --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" \
    --query "[?direction=='Inbound' && access=='Allow' && destinationPortRange=='22'].[sourceAddressPrefix, name]" \
    --output tsv 2>/dev/null || true
}
# Resource ID of the just-in-time policy for this resource group; empty when there is none.
jit_policy_id() {
  az security jit-policy list --query "[?contains(id, '/${RESOURCE_GROUP}/')].id | [0]" --output tsv 2>/dev/null || true
}
# Says whether SSH from this machine is allowed; returns 1 when it is not.
check_ssh_rule() {
  local mine openings source name found="" jit=""
  mine="$(my_address)"
  mine="${mine%/32}"
  openings="$(ssh_openings)"
  while IFS=$'\t' read -r source name; do
    [[ -n "$source" ]] || continue
    if [[ "$name" == *JITRule* ]]; then jit=yes; fi
    if [[ "${source%/32}" == "$mine" || "$source" == "*" || "$source" == "Internet" ]]; then found="$name"; fi
  done <<< "$openings"
  if [[ -n "$found" ]]; then
    info "SSH:            open to your address, $mine (rule $found)"
    if [[ "$found" == *JITRule* ]]; then
      info "                this is a just-in-time opening and closes by itself; bash infra/vm.sh ssh renews it"
    fi
    return 0
  fi
  if [[ -n "$openings" ]]; then
    warn "SSH is open to $(cut -f1 <<< "$openings" | paste -sd, -), but you are on $mine."
  else
    warn "SSH is not open to any address."
  fi
  if [[ -n "$jit" || -n "$(jit_policy_id)" ]]; then
    warn "Just-in-time access (Microsoft Defender for Cloud) controls port 22 on this VM."
  fi
  warn "./infra/vm.sh ssh opens access and connects. Without SSH: bash infra/vm.sh run COMMAND"
  return 1
}
# request_jit HOURS: just-in-time access to port 22 from this machine.
request_jit() {
  local hours="$1" policy mine until vm_id
  policy="$(jit_policy_id)"
  [[ -n "$policy" ]] || die "No just-in-time policy covers $RESOURCE_GROUP. Use bash infra/vm.sh allow-my-ip instead."
  mine="$(my_address)"
  mine="${mine%/32}"
  # GNU date first, then the BSD form for macOS.
  until="$(date -u -d "+${hours} hours" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v "+${hours}H" +%Y-%m-%dT%H:%M:%SZ)"
  vm_id="$(az vm show --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --query id --output tsv)"
  log "Asking for just-in-time access: port 22 from $mine until $until"
  az rest --method post --url "https://management.azure.com${policy}/initiate?api-version=2020-01-01" \
    --body "{\"virtualMachines\":[{\"id\":\"${vm_id}\",\"ports\":[{\"number\":22,\"allowedSourceAddressPrefix\":\"${mine}\",\"endTimeUtc\":\"${until}\"}]}],\"justification\":\"Wind farm demo deployment\"}" \
    --output none \
    || die "The request was refused. If it asked for too many hours, ask for fewer: bash infra/vm.sh jit 1"
  info "Granted. The rule can take a minute to apply."
}
# Points the rule of step 1 at this machine, creating it when asked to.
point_rule_here() {
  local mine
  mine="$(my_address)"
  log "Allowing SSH from $mine only"
  if [[ -n "$(rule_source)" ]]; then
    az network nsg rule update --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" --name "$RULE_NAME" \
      --source-address-prefixes "$mine" --output none
  else
    az network nsg rule create --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" --name "$RULE_NAME" \
      --priority 1000 --direction Inbound --access Allow --protocol Tcp \
      --source-address-prefixes "$mine" --destination-port-ranges 22 --output none
  fi
}
# ensure_access: reads the VM's state and address into VM_STATE and IP, and makes sure this
# machine can reach port 22, opening access the way this subscription allows. Stops with
# advice when it cannot.
# run_without_ssh COMMAND: runs a command in the repository folder on the VM through the VM agent.
run_without_ssh() {
  [[ "$*" != *"'"* ]] || die "The command must not contain single quotes; use double quotes inside it."
  log "Running on the VM as ${VM_ADMIN}, without SSH (takes at least 20 seconds; the output appears at the end)"
  az vm run-command invoke --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --command-id RunShellScript \
    --scripts "sudo -u ${VM_ADMIN} -H bash -lc 'cd ~/${REMOTE_DIR} && $*'" \
    --query "value[0].message" --output tsv
}

# ssh_impossible: true when the VM runs, port 22 is closed, and there is neither a just-in-time
# policy to ask nor an SSH rule to move. Sets IP and VM_STATE.
ssh_impossible() {
  read_state_and_address
  [[ "$VM_STATE" == "VM running" && -n "$IP" ]] || return 1
  if port_22_open "$IP"; then return 1; fi
  [[ -z "$(jit_policy_id)" && -z "$(rule_source)" ]]
}

ensure_access() {
  local ip
  read_state_and_address
  ip="$IP"
  [[ "$VM_STATE" == "VM running" ]] || die "The VM is not running (it is: ${VM_STATE:-unknown}). Start it with bash infra/vm.sh start"
  [[ -n "$ip" ]] || die "The VM has no public address."
  if port_22_open "$ip"; then return 0; fi
  if [[ -n "$(jit_policy_id)" ]]; then
    info "Port 22 is closed to this machine and just-in-time access is in force."
    request_jit 3
  elif [[ -n "$(rule_source)" ]]; then
    info "Port 22 is closed to this machine; the SSH rule points at another address."
    point_rule_here
  else
    warn "Port 22 is closed, there is no just-in-time policy, and the SSH rule of step 1 is gone:"
    warn "something removed it. bash infra/vm.sh nsg-log shows who. If it was a policy of your organisation,"
    warn "leave it removed and use bash infra/vm.sh run COMMAND, or Azure Bastion for a shell."
    die "Cannot open SSH access. To create the rule again anyway: bash infra/vm.sh allow-my-ip --create"
  fi
  for _ in $(seq 1 24); do
    if port_22_open "$ip"; then return 0; fi
    sleep 5
  done
  die "Port 22 still does not answer from this machine. bash infra/vm.sh status shows the rules in force; bash infra/vm.sh run COMMAND works without SSH. See 'SSH does not connect' in docs/troubleshooting.md."
}

case "$ACTION" in
  status)
    log "Edge VM $VM_NAME"
    VM_STATE="$(power_state)"
    info "Power state:    $VM_STATE"
    info "Public address: $(public_ip)"
    info "Administrator:  $VM_ADMIN"
    info "Daily shutdown: $(describe_shutdown)"
    check_ssh_rule || true
    if [[ "$VM_STATE" != "VM running" ]]; then
      info "Start it with:  bash infra/vm.sh start"
    fi
    ;;

  start)
    VM_STATE="$(power_state)"
    if [[ "$VM_STATE" == "VM running" ]]; then
      log "The VM is already running"
    else
      log "Starting the VM (it was: ${VM_STATE:-unknown})"
      az vm start --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --output none
    fi
    info "Public address: $(public_ip)"
    info "Daily shutdown: $(describe_shutdown)"
    check_ssh_rule || true
    info "Connect with:   bash infra/vm.sh ssh"
    info "K3s, Azure IoT Operations and the simulator start by themselves. Allow about 5 minutes"
    info "before the cluster shows as Connected again and data flows."
    ;;

  stop)
    log "Stopping and deallocating the VM"
    az vm deallocate --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --output none
    info "Stopped. The disk and the public address are kept and still cost a little."
    ;;

  ssh)
    shift
    need ssh
    # A command needs no shell: when SSH cannot be opened, it goes through the VM agent instead.
    if [[ $# -gt 0 ]] && ssh_impossible; then
      warn "Port 22 is closed, there is no just-in-time policy and no SSH rule: running the command without SSH."
      warn "./infra/vm.sh nsg-log shows what removed the rule; docs/troubleshooting.md, 'SSH does not connect'."
      run_without_ssh "$@"
      exit $?
    fi
    ensure_access
    if [[ $# -eq 0 ]]; then
      exec ssh "${SSH_OPTIONS[@]}" "${VM_ADMIN}@${IP}"
    fi
    exec ssh -t "${SSH_OPTIONS[@]}" "${VM_ADMIN}@${IP}" "cd ~/${REMOTE_DIR} && $*"
    ;;

  push)
    need ssh tar
    ensure_access
    log "Copying the repository to ${VM_ADMIN}@${IP}:~/${REMOTE_DIR}"
    # The folders that belong to the repository are replaced, so files that no longer
    # exist here disappear there too. Scripts get their execute permission back.
    UNPACK="mkdir -p ~/${REMOTE_DIR} && cd ~/${REMOTE_DIR} && rm -rf simulator edge infra fabric data docs tools"
    UNPACK+=" && tar -xzf - && chmod +x infra/*.sh edge/scripts/*.sh tools/*.sh"
    # shellcheck disable=SC2029  # UNPACK is meant to be expanded here, not on the VM
    tar -C "$REPO_ROOT" --exclude=.git --exclude=node_modules --exclude=__pycache__ --exclude=.pytest_cache \
        --exclude='*.egg-info' -czf - . \
      | ssh "${SSH_OPTIONS[@]}" "${VM_ADMIN}@${IP}" "$UNPACK"
    info "Done. config/demo.env on the VM is now the same as the one here."
    ;;

  push-env)
    need scp
    ensure_access
    log "Copying config/demo.env to the VM"
    scp "${SSH_OPTIONS[@]}" "$ENV_FILE" "${VM_ADMIN}@${IP}:${REMOTE_DIR}/config/demo.env"
    info "Done."
    ;;

  run)
    shift
    [[ $# -gt 0 ]] || die "Give the command to run on the VM, for example: bash infra/vm.sh run bash ./edge/scripts/simctl.sh status"
    run_without_ssh "$@"
    ;;

  nsg-log)
    HOURS="${2:-24}"
    [[ "$HOURS" =~ ^[0-9]+$ ]] || die "Give a number of hours, for example: bash infra/vm.sh nsg-log 48"
    log "Changes to network security groups in $RESOURCE_GROUP, last $HOURS hours"
    az monitor activity-log list --resource-group "$RESOURCE_GROUP" --offset "${HOURS}h" --max-events 1000 \
      --query "sort_by([?contains(operationName.value, 'networkSecurityGroups') && status.value=='Succeeded'], &eventTimestamp)[].{time:eventTimestamp, operation:operationName.value, by:caller}" \
      --output table
    info "A 'securityRules/delete' or a 'networkSecurityGroups/write' by someone other than you is a policy or a"
    info "security service of your organisation. Do not put the rule back in that case."
    log "Rules in force on $NSG_NAME"
    az network nsg rule list --resource-group "$RESOURCE_GROUP" --nsg-name "$NSG_NAME" --include-default \
      --query "sort_by(@, &priority)[].{priority:priority, name:name, access:access, direction:direction, port:destinationPortRange, source:sourceAddressPrefix}" \
      --output table
    ;;

  jit)
    HOURS="${2:-3}"
    [[ "$HOURS" =~ ^[1-9][0-9]?$ ]] || die "Give a whole number of hours, for example: bash infra/vm.sh jit 3"
    request_jit "$HOURS"
    info "Connect with: bash infra/vm.sh ssh"
    ;;

  allow-my-ip)
    if [[ "${2:-}" != "--create" && -n "$(jit_policy_id)" ]]; then
      warn "Just-in-time access (Microsoft Defender for Cloud) controls port 22 on this VM."
      warn "A rule of your own may be removed again. Ask for access instead: bash infra/vm.sh jit"
      die "Not changing the rule. To do it anyway: bash infra/vm.sh allow-my-ip --create"
    fi
    if [[ -z "$(rule_source)" && "${2:-}" != "--create" ]]; then
      warn "The SSH rule $RULE_NAME no longer exists on $NSG_NAME. Step 1 created it, so something removed it."
      warn "Run bash infra/vm.sh nsg-log to see who. If it was a policy or a security service of your organisation,"
      warn "leave it removed and use bash infra/vm.sh run COMMAND, or Azure Bastion for an interactive shell."
      die "Not creating the rule again. To create it anyway: bash infra/vm.sh allow-my-ip --create"
    fi
    point_rule_here
    info "Done. Connect with: bash infra/vm.sh ssh"
    ;;

  reset-key)
    KEY="${2:-$HOME/.ssh/id_rsa.pub}"
    if [[ ! -f "$KEY" ]]; then
      [[ -z "${2:-}" ]] || die "$KEY not found."
      need ssh-keygen
      log "No SSH key at $KEY: creating one"
      mkdir -p "$HOME/.ssh"
      ssh-keygen -q -t rsa -b 4096 -N "" -f "${KEY%.pub}"
    fi
    log "Installing $KEY for $VM_ADMIN on the VM"
    az vm user update --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --username "$VM_ADMIN" \
      --ssh-key-value "$(cat "$KEY")" --output none
    info "Done. Connect with: bash infra/vm.sh ssh"
    ;;

  shutdown)
    WHEN="${2:-}"
    if [[ "$WHEN" == "off" ]]; then
      log "Removing the daily shutdown"
      az vm auto-shutdown --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --off --output none
      info "The VM now runs, and costs, until you stop it: bash infra/vm.sh stop"
      WHEN=""
    elif [[ "$WHEN" =~ ^([01][0-9]|2[0-3])[0-5][0-9]$ ]]; then
      log "Setting the daily shutdown to ${WHEN:0:2}:${WHEN:2:2} UTC"
      az vm auto-shutdown --resource-group "$RESOURCE_GROUP" --name "$VM_NAME" --time "$WHEN" --output none
      ELSEWHERE="$(utc_time_elsewhere "$WHEN")"
      if [[ -n "$ELSEWHERE" ]]; then
        info "That is $ELSEWHERE."
      fi
    else
      die "Give a UTC time as HHMM, for example 0800, or 'off'."
    fi
    info "Set VM_AUTO_SHUTDOWN_UTC=\"$WHEN\" in config/demo.env too, so that a rerun of step 1 keeps it."
    ;;
esac
