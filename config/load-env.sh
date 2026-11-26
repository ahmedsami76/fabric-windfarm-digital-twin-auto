#!/usr/bin/env bash
# Sourced by every script: loads the settings file and provides small helpers.
# The settings file is, in this order: the file ENV_FILE names; config/demo.env, which a deployment by hand
# has; the settings of the deployment that tools/deploy.py is working on, .deploy/<suffix>/demo.env, where
# .deploy/current holds the suffix. On the edge VM it is always config/demo.env.
# shellcheck shell=bash

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -z "${ENV_FILE:-}" ]]; then
  ENV_FILE="$REPO_ROOT/config/demo.env"
  if [[ ! -f "$ENV_FILE" && -f "$REPO_ROOT/.deploy/current" ]]; then
    ENV_FILE="$REPO_ROOT/.deploy/$(tr -d '[:space:]' < "$REPO_ROOT/.deploy/current")/demo.env"
  fi
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found. For a deployment by hand, copy config/demo.env.example to config/demo.env and fill it in. With the runner, python3 tools/deploy.py plan makes the settings of a deployment." >&2
  exit 1
fi
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

# Under the deployment runner every call of the Azure CLI names the deployment's subscription itself, and the CLI's
# active subscription is neither changed nor relied on: another terminal can change it while a script runs.
# By hand nothing changes: the scripts select the subscription of the settings with `az account set`, as before.
# `az ad`, `az extension`, `az config`, `az version`, `az login` and `az logout` take no --subscription (Azure CLI 2.93.0).
if [[ -n "${AZ_SUBSCRIPTION_PIN:-}" ]]; then
  az() {
    case "${1:-}" in
      ad|extension|config|version|login|logout) command az "$@" ;;
      account) if [[ "${2:-}" == "set" ]]; then return 0; fi; command az "$@" --subscription "$AZ_SUBSCRIPTION_PIN" ;;
      *) command az "$@" --subscription "$AZ_SUBSCRIPTION_PIN" ;;
    esac
  }
fi

log()  { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33mWARNING: %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

# require VAR [VAR ...]: stop with a clear message if a setting is empty.
require() {
  local name
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || die "$name is empty in $ENV_FILE"
  done
}

# need CMD [CMD ...]: stop if a command-line tool is missing.
# need_iot_ops_extension [current]: make sure the Azure CLI has the extension azure-iot-ops.
# Without an argument an installed extension is used as it is and the network is not asked. With
# "current", for a first deployment, a newer version is looked for, for three minutes at most: the
# search of "az extension add --upgrade" has no time limit of its own, and on 25 November 2026 it
# stood at " - Searching .." until the script was stopped by hand (Phase 5 log, obstacle D).
need_iot_ops_extension() {
  local limit=()
  if command -v timeout >/dev/null 2>&1; then limit=(timeout "${EXTENSION_SEARCH_SECONDS:-180}"); fi
  if az extension show --name azure-iot-ops --output none 2>/dev/null; then
    [[ "${1:-}" == "current" ]] || return 0
    ${limit[@]+"${limit[@]}"} az extension add --upgrade --yes --name azure-iot-ops \
      || warn "Looking for a newer version of the Azure CLI extension azure-iot-ops did not finish. Going on with the installed one."
    return 0
  fi
  info "Installing the Azure CLI extension azure-iot-ops"
  ${limit[@]+"${limit[@]}"} az extension add --yes --name azure-iot-ops \
    || die "The Azure CLI extension azure-iot-ops could not be installed. Check that this computer reaches the internet, then run: az extension add --name azure-iot-ops"
}

# require_object_id VAR: stop when the setting is not an object ID of Microsoft Entra ID.
# For CUSTOM_LOCATIONS_OID: with a managed identity sign-in, "az connectedk8s enable-features"
# cannot validate the value and uses it as it is, so a wrong value shows only in step 4, as
# "resource provider does not have the required permissions" (validation log, obstacle 17).
require_object_id() {
  local name="$1" value="${!1:-}"
  [[ -n "$value" ]] || die "$name is empty in $ENV_FILE"
  if [[ ! "$value" =~ ^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$ ]]; then
    die "$name in $ENV_FILE is '$value'. It must be an object ID: 36 characters like 01234567-89ab-cdef-0123-456789abcdef. It is not a name; the name of the custom location is CUSTOM_LOCATION_NAME. See 'the Custom Locations object ID is not printed' in docs/troubleshooting.md for the ways to get it."
  fi
  if [[ "$name" == "CUSTOM_LOCATIONS_OID" && "$value" == [bB][cC]313[cC]14-388[cC]-4[eE]7[dD]-[aA]58[eE]-70017303[eE][eE]3[bB] ]]; then
    die "$name in $ENV_FILE is the application ID of the Custom Locations service, which is the same in every tenant. The setting needs the object ID that 'az ad sp show --id $value --query id --output tsv' prints for your tenant."
  fi
}

need() {
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || die "'$cmd' is not installed or not on PATH"
  done
}

# on_edge_vm: true when this machine is the edge VM (its host name is VM_NAME).
on_edge_vm() {
  [[ -n "${VM_NAME:-}" && "$(hostname 2>/dev/null || true)" == "$VM_NAME" ]]
}

# require_edge_vm: for the scripts of edge/scripts. Stops when run anywhere else.
require_edge_vm() {
  [[ -n "${ALLOW_ANY_HOST:-}" ]] && return 0
  on_edge_vm || die "This script runs on the edge VM (${VM_NAME:-VM_NAME is empty}), and this machine is '$(hostname 2>/dev/null || true)'. Connect to the VM first with bash infra/vm.sh ssh, or run it from here with: bash infra/vm.sh ssh bash ./edge/scripts/$(basename "$0")"
}

# require_user_login: for the scripts of infra. Stops when run on the edge VM, or when
# the Azure CLI is signed in as a managed identity or service principal: these steps
# create resources and role assignments, which the edge VM's identity may not do.
require_user_login() {
  local kind
  if on_edge_vm && [[ -z "${ALLOW_NON_USER_LOGIN:-}" ]]; then
    die "This script runs on your workstation or in Azure Cloud Shell, not on the edge VM. Leave the VM (type: exit) and run it there."
  fi
  kind="$(az account show --query user.type --output tsv 2>/dev/null || true)"
  [[ -n "$kind" ]] || die "The Azure CLI is not signed in. Run: az login"
  if [[ "$kind" != "user" && -z "${ALLOW_NON_USER_LOGIN:-}" ]]; then
    die "The Azure CLI is signed in as a $kind, not as you. Run this script on your workstation or in Azure Cloud Shell, not on the edge VM. (If you are on the VM on purpose, sign in with 'az login --use-device-code' first.)"
  fi
}

# utc_time_elsewhere HHMM: say what a UTC time of day is in a few time zones, so a
# schedule given in UTC can be checked against your own working hours. Best effort:
# needs GNU date and prints nothing where that is missing (macOS).
utc_time_elsewhere() {
  local hhmm="$1" zone local_time out=""
  for zone in America/Los_Angeles America/Chicago America/New_York Europe/London Europe/Berlin Asia/Kolkata Asia/Singapore; do
    local_time="$(TZ="$zone" date -d "${hhmm:0:2}:${hhmm:2:2} UTC" +%H:%M 2>/dev/null)" || return 0
    out+="${out:+, }${local_time} ${zone##*/}"
  done
  printf '%s' "${out//_/ }"
}
