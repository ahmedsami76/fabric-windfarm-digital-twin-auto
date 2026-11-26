#!/usr/bin/env bash
# Sets up the service principal the wind farm twin reads the Eventhouse as, so that its values are
# seconds old. Without it the twin reads the copies of the tables in the Lakehouse, minutes old.
#
# Why it is needed: a Fabric app runs as its owner and gets no token from Fabric that the Eventhouse
# accepts (docs/11-deployment-guide-phase4.md, "How the live values reach the app"). A service
# principal gets one from Microsoft Entra ID by itself.
#
#   bash app/create-principal.sh            create the app registration (or reuse it), make a new secret,
#                                           let it read the workspace, hand the three secrets to the Fabric app
#   bash app/create-principal.sh --show     say what exists; changes nothing
#   bash app/create-principal.sh --remove   delete the app registration, its access and the three secrets
#
# Run it on the workstation, as yourself (not with sudo), after "az login" in the tenant of the Fabric
# workspace and after the app has been deployed once (step 4 of the guide). It creates in Microsoft
# Entra ID: one app registration named windfarm-twin-eventhouse-reader with one client secret, valid
# one year. It gives that principal the Viewer role on the workspace WindFarmDigitalTwin, and nothing
# else anywhere. The secret is never printed and is not kept in a file.
#
# For a deployment of tools/deploy.py the registration carries the deployment's suffix, for example
# windfarm-twin-eventhouse-reader-3x9: every deployment has a registration of its own, because making
# a secret replaces the one before it (az ad app credential reset), and another deployment's twin
# would lose its secret. The runner starts this script itself (step p4.eventhouse_principal).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# The app's folder: APP_DIR when it is given; else the one beside this script, which a deployment by hand has; else the
# folder of the deployment tools/deploy.py is working on, .deploy/<suffix>/app/windfarm-twin.
APP="${APP_DIR:-$HERE/windfarm-twin}"
if [[ -z "${APP_DIR:-}" && ! -d "$APP" && -f "$HERE/../.deploy/current" ]]; then
  APP="$HERE/../.deploy/$(tr -d '[:space:]' < "$HERE/../.deploy/current")/app/windfarm-twin"
fi
# The workspace's name: FABRIC_WORKSPACE_NAME when it is given, else what the settings file says (the one ENV_FILE names,
# else config/demo.env, else the settings of the deployment tools/deploy.py is working on), else the name of the guides.
SETTINGS="${ENV_FILE:-$HERE/../config/demo.env}"
if [[ ! -f "$SETTINGS" && -f "$HERE/../.deploy/current" ]]; then
  SETTINGS="$HERE/../.deploy/$(tr -d '[:space:]' < "$HERE/../.deploy/current")/demo.env"
fi
WORKSPACE_NAME="${FABRIC_WORKSPACE_NAME:-}"
if [[ -z "$WORKSPACE_NAME" && -f "$SETTINGS" ]]; then
  WORKSPACE_NAME="$(sed -n 's/^FABRIC_WORKSPACE_NAME="\([^"]*\)".*/\1/p' "$SETTINGS" | head -n 1)"
fi
WORKSPACE_NAME="${WORKSPACE_NAME:-WindFarmDigitalTwin}"
# The registration's name: PRINCIPAL_NAME when it is given; else the name of the guides, with the suffix of the
# deployment when the settings have one.
SUFFIX=""
if [[ -f "$SETTINGS" ]]; then SUFFIX="$(sed -n 's/^DEPLOYMENT_SUFFIX="\([^"]*\)".*/\1/p' "$SETTINGS" | head -n 1)"; fi
NAME="${PRINCIPAL_NAME:-windfarm-twin-eventhouse-reader${SUFFIX:+-$SUFFIX}}"
DATABASE_NAME="WindFarmEH"
FABRIC="https://api.fabric.microsoft.com"
SECRETS_FILE="$APP/rayfin/.env.secrets"
MODE="${1:-create}"

say()  { printf '\n==> %s\n' "$*"; }
stop() { printf '\nSTOP: %s\n' "$*" >&2; exit 1; }

case "$MODE" in create|--show|--remove) ;; *) stop "Unknown option $MODE. Use no option, --show or --remove.";; esac
[[ -z "${SUDO_USER:-}" ]] || stop "Do not run this with sudo: root is not signed in to Azure or to Rayfin."
command -v az >/dev/null || stop "The Azure CLI (az) is not installed on this machine."
command -v python3 >/dev/null || stop "python3 is not installed on this machine."

ERR="$(mktemp)"
cleanup() { rm -f "$ERR"; if [[ -f "$SECRETS_FILE" ]]; then rm -f "$SECRETS_FILE"; fi; }
trap cleanup EXIT

TENANT_ID="$(az account show --query tenantId --output tsv 2>"$ERR")" || stop "Not signed in to Azure. Run: az login"
SIGNED_IN="$(az account show --query user.name --output tsv 2>/dev/null || echo unknown)"
echo "Signed in to Azure as $SIGNED_IN, tenant $TENANT_ID."
# Under tools/deploy.py the deployment's subscription is named. The directory commands (az ad) take no --subscription
# and follow the Azure CLI's active one, so this script goes on only when that one is in the deployment's tenant.
if [[ -n "${AZ_SUBSCRIPTION_PIN:-}" ]]; then
  PINNED_TENANT="$(az account show --query tenantId --output tsv --subscription "$AZ_SUBSCRIPTION_PIN" 2>"$ERR")" \
    || stop "The Azure CLI cannot use subscription $AZ_SUBSCRIPTION_PIN: $(tr '\n' ' ' < "$ERR")"
  [[ "$PINNED_TENANT" == "$TENANT_ID" ]] || stop "The Azure CLI's active subscription is in tenant $TENANT_ID, and this deployment is in tenant $PINNED_TENANT. The directory commands follow the active subscription. Nothing was created. Run: az account set --subscription $AZ_SUBSCRIPTION_PIN   and then the same command again."
fi

# On WSL Rayfin has no keychain for its sign-in (step 4 of the guide).
if [[ -z "${RAYFIN_ENCRYPTION_FALLBACK_ENABLED:-}" ]] && grep -qi microsoft /proc/version 2>/dev/null; then
  export RAYFIN_ENCRYPTION_FALLBACK_ENABLED=true
fi

# The identifier of the workspace, by name. Empty when this sign-in does not see it.
workspace_id() {
  local url="$FABRIC/v1/workspaces" page id=""
  page="$(mktemp)"
  while [[ -n "$url" ]]; do
    if ! az rest --resource "$FABRIC" --method get --url "$url" --output json > "$page" 2>"$ERR"; then rm -f "$page"; return 1; fi
    id="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(next((w["id"] for w in d.get("value",[]) if w.get("displayName")==sys.argv[2]),""))' "$page" "$WORKSPACE_NAME")"
    [[ -z "$id" ]] || break
    url="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("continuationUri") or "")' "$page")"
  done
  rm -f "$page"
  echo "$id"
}

app_id()    { az ad app list --filter "displayName eq '$NAME'" --query "[0].appId" --output tsv 2>"$ERR"; }
object_id() { az ad sp show --id "$1" --query id --output tsv 2>"$ERR"; }

# The role of the principal on the workspace, or nothing.
workspace_role() {
  az rest --resource "$FABRIC" --method get --url "$FABRIC/v1/workspaces/$1/roleAssignments" --output json 2>"$ERR" \
    | python3 -c 'import json,sys; print(next((a.get("role","") for a in json.load(sys.stdin).get("value",[]) if a.get("principal",{}).get("id")==sys.argv[1]),""))' "$2"
}

say "Looking for the workspace $WORKSPACE_NAME with this sign-in"
WORKSPACE_ID="$(workspace_id)" || stop "The Fabric API did not answer: $(tr '\n' ' ' < "$ERR")"
[[ -n "$WORKSPACE_ID" ]] || stop "This sign-in does not see a workspace named $WORKSPACE_NAME. Sign in to the tenant of your Fabric workspace: az login --tenant <tenant of Fabric>"
echo "Workspace $WORKSPACE_NAME is $WORKSPACE_ID."

APP_ID="$(app_id)" || stop "This sign-in may not read app registrations: $(tr '\n' ' ' < "$ERR")"

if [[ "$MODE" == "--show" ]]; then
  if [[ -z "$APP_ID" ]]; then echo "No app registration named $NAME. The twin reads the Lakehouse."; exit 0; fi
  OBJECT_ID="$(object_id "$APP_ID" || true)"
  echo "App registration $NAME: application ID $APP_ID, service principal ${OBJECT_ID:-missing}."
  if [[ -n "$OBJECT_ID" ]]; then
    ROLE="$(workspace_role "$WORKSPACE_ID" "$OBJECT_ID" || true)"
    echo "Role on the workspace: ${ROLE:-none. Run this script without an option: it gives the role and the secrets}"
  fi
  if [[ -f "$APP/rayfin/rayfin.yml" ]]; then
    echo "Secrets of the Fabric app:"
    (cd "$APP" && npx rayfin secret list) || echo "  could not be listed: sign in with npx rayfin login"
  fi
  exit 0
fi

[[ -f "$APP/rayfin/rayfin.yml" ]] || stop "There is no app in $APP yet. Run bash app/create-app.sh and deploy it first (steps 3 and 4 of the guide)."

if [[ "$MODE" == "--remove" ]]; then
  if [[ -n "$APP_ID" ]]; then
    OBJECT_ID="$(object_id "$APP_ID" || true)"
    if [[ -n "$OBJECT_ID" ]]; then
      say "Taking the principal off the workspace"
      az rest --resource "$FABRIC" --method delete --url "$FABRIC/v1/workspaces/$WORKSPACE_ID/roleAssignments/$OBJECT_ID" --output none 2>"$ERR" || echo "Not removed (it may have had no role): $(tr '\n' ' ' < "$ERR")"
    fi
    say "Deleting the app registration $NAME ($APP_ID)"
    az ad app delete --id "$APP_ID" 2>"$ERR" || stop "The app registration was not deleted: $(tr '\n' ' ' < "$ERR")"
  else
    echo "No app registration named $NAME."
  fi
  say "Deleting the three secrets of the Fabric app"
  for secret in KUSTO_TENANT_ID KUSTO_CLIENT_ID KUSTO_CLIENT_SECRET; do
    (cd "$APP" && npx rayfin secret delete "$secret") || echo "  $secret was not deleted (it may not exist)."
  done
  echo
  echo "Removed. The twin reads the Lakehouse from its next question on."
  exit 0
fi

if [[ -n "$APP_ID" ]]; then
  say "Found the app registration $NAME: keeping it"
else
  say "Creating the app registration $NAME"
  APP_ID="$(az ad app create --display-name "$NAME" --sign-in-audience AzureADMyOrg --query appId --output tsv 2>"$ERR")" \
    || stop "The app registration was not created: $(tr '\n' ' ' < "$ERR") If your tenant does not let you create one, the twin stays on the Lakehouse."
fi
echo "Application (client) ID: $APP_ID"

OBJECT_ID="$(object_id "$APP_ID" || true)"
if [[ -z "$OBJECT_ID" ]]; then
  say "Creating its service principal"
  OBJECT_ID="$(az ad sp create --id "$APP_ID" --query id --output tsv 2>"$ERR")" || stop "The service principal was not created: $(tr '\n' ' ' < "$ERR")"
fi
echo "Service principal (object ID): $OBJECT_ID"

say "Giving it the Viewer role on the workspace $WORKSPACE_NAME"
ROLE="$(workspace_role "$WORKSPACE_ID" "$OBJECT_ID" || true)"
if [[ -n "$ROLE" ]]; then
  echo "It already has the role $ROLE."
else
  # A principal created a moment ago is not known to Fabric at once: the first real run stopped here
  # (23 November 2026). So "not found" is tried again for up to two minutes; any other answer stops.
  ROLE_TRIES="${ROLE_TRIES:-8}"; ROLE_WAIT_SECONDS="${ROLE_WAIT_SECONDS:-15}"
  for (( try = 1; ; try++ )); do
    if az rest --resource "$FABRIC" --method post --url "$FABRIC/v1/workspaces/$WORKSPACE_ID/roleAssignments" \
      --body "{\"principal\": {\"id\": \"$OBJECT_ID\", \"type\": \"ServicePrincipal\"}, \"role\": \"Viewer\"}" --output none 2>"$ERR"; then
      break
    fi
    if (( try < ROLE_TRIES )) && grep -q -i -E 'not ?found|does not exist|unknown principal|invalid principal' "$ERR"; then
      echo "Fabric does not know the new principal yet (try $try of $ROLE_TRIES). Waiting $ROLE_WAIT_SECONDS seconds."
      sleep "$ROLE_WAIT_SECONDS"
      continue
    fi
    stop "The role was not given: $(tr '\n' ' ' < "$ERR") You need the Admin or Member role on the workspace. If Fabric says it cannot find the principal, wait a few minutes and run this script again. Or in the portal: the workspace, Manage access, Add people or groups, $NAME, Viewer."
  done
  echo "Done."
fi

say "Making a new client secret, valid one year (an earlier secret of this app registration stops working)"
SECRET="$(az ad app credential reset --id "$APP_ID" --display-name "windfarm-twin" --years 1 --query password --output tsv 2>"$ERR")" \
  || stop "No secret was made: $(tr '\n' ' ' < "$ERR") Some tenants do not allow client secrets; the twin then stays on the Lakehouse."
[[ -n "$SECRET" ]] || stop "Azure returned an empty secret."

say "Handing the three secrets to the Fabric app (npx rayfin secret set)"
( umask 077; printf 'KUSTO_TENANT_ID=%s\nKUSTO_CLIENT_ID=%s\nKUSTO_CLIENT_SECRET=%s\n' "$TENANT_ID" "$APP_ID" "$SECRET" > "$SECRETS_FILE" )
unset SECRET
if ! (cd "$APP" && npx rayfin secret set --env-file rayfin/.env.secrets); then
  stop "Rayfin did not take the secrets. If it is not signed in: cd $APP, npx rayfin login, then run this script again (it makes a new secret)."
fi
rm -f "$SECRETS_FILE"

cat <<EOF

The service principal is set up:
  app registration   $NAME
  application ID     $APP_ID
  tenant             $TENANT_ID
  access             Viewer on the workspace $WORKSPACE_NAME

Next (tools/deploy.py does this itself, as its next step):
  cd "$APP"
  npx rayfin up
Then reload the app and open the connection check. The lines "Eventhouse route" say whether it works;
a new principal can need a few minutes before Fabric knows it.

If the line "Eventhouse route: query" says the principal is not authorized to read the database, run
this in a KQL queryset on $DATABASE_NAME and check again:
  .add database $DATABASE_NAME viewers ('aadapp=$APP_ID;$TENANT_ID') 'wind farm twin'
If it says 401 or names a tenant setting: Fabric admin portal, Tenant settings, Developer settings,
"Service principals can call Fabric public APIs", on for the organization or for a group with this principal.
EOF
