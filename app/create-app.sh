#!/usr/bin/env bash
# Creates the Fabric app of Phase 4 next to this script, in app/windfarm-twin, from three parts:
#   1. the Universal App template of Rayfin, written by Microsoft's scaffolder at a pinned version,
#   2. the functions pack of that template,
#   3. the files of app/overlay: the 3D twin, its panels and its seven functions,
# and adds the two libraries the overlay needs: three.js for the page, the SQL driver for the functions.
# Nothing here touches Fabric. Deploying is the next step: docs/11-deployment-guide-phase4.md.
#
#   bash app/create-app.sh             create the app, or bring an existing app/windfarm-twin up to date
#   bash app/create-app.sh --overlay   only copy the files of app/overlay again (after a repository update
#                                      that needs no new library; the script says so when it does)
#
# Run it on the workstation, as yourself (not with sudo). It needs Node.js 22 (22.13 or newer) or 24:
# step 2 of the guide installs it.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Where the app is built. By hand: beside this script. The deployment runner gives every deployment a folder of its
# own (APP_DIR), so that two deployments never build in one folder: the app's copy of config.ts names one workspace.
APP="${APP_DIR:-$HERE/windfarm-twin}"
RAYFIN_VERSION="${RAYFIN_VERSION:-2.0.1}"   # the version the overlay was written and checked against
THREE_VERSION="0.187.0"
MSSQL_VERSION="12.8.1"         # Rayfin's guide asks for 12.6.0 or newer: older ones fail against Fabric endpoints
MSSQL_TYPES_VERSION="12.3.0"
MODE="${1:-all}"
# A line under the app that says its last full run ended with its check passed, and for which build of the overlay.
# The deployment runner reads it: the twin's files are copied early, so their presence says nothing about the end.
READY="$APP/.twin-ready"
# npm waits five minutes for an answer that does not come and tries three times in all (its defaults, read from npm
# 10.9.9). On a line that drops single connections that is a quarter of an hour of silence for one install, seen on
# 26 November 2026. One minute and six tries here; both can be set from outside, for a line that is slow and not
# dropping: npm_config_fetch_timeout=300000 bash app/create-app.sh
export npm_config_fetch_timeout="${npm_config_fetch_timeout:-60000}"
export npm_config_fetch_retries="${npm_config_fetch_retries:-5}"

say()  { printf '\n==> %s\n' "$*"; }
stop() { printf '\nSTOP: %s\n' "$*" >&2; exit 1; }

case "$MODE" in all|--overlay) ;; *) stop "Unknown option $MODE. Use no option, or --overlay.";; esac
[[ -z "${SUDO_USER:-}" ]] || stop "Do not run this with sudo: the app would belong to root and the sign-in of Rayfin would be root's."

# The functions find the workspace by its name. The overlay names the one of the guides; a deployment made by
# tools/deploy.py has a name of its own, taken from FABRIC_WORKSPACE_NAME or from the settings file: the one
# ENV_FILE names, else config/demo.env, else the settings of the deployment the runner is working on. Only the
# copy in the app is changed, so the overlay and its build stamp stay what they are.
workspace_name() {
  local name="${FABRIC_WORKSPACE_NAME:-}" settings="${ENV_FILE:-$HERE/../config/demo.env}"
  if [[ ! -f "$settings" && -f "$HERE/../.deploy/current" ]]; then
    settings="$HERE/../.deploy/$(tr -d '[:space:]' < "$HERE/../.deploy/current")/demo.env"
  fi
  if [[ -z "$name" && -f "$settings" ]]; then
    name="$(sed -n 's/^FABRIC_WORKSPACE_NAME="\([^"]*\)".*/\1/p' "$settings" | head -n 1)"
  fi
  echo "${name:-WindFarmDigitalTwin}"
}
name_workspace() {
  local name file="$APP/packages/functions/src/config.ts"
  name="$(workspace_name)"
  [[ "$name" =~ ^[A-Za-z0-9_.-]+$ ]] || stop "The workspace name '$name' has a character this script does not write into the app. Use letters, digits, dot, dash, underscore."
  [[ -f "$file" ]] || return 0
  sed -i "s/^export const WORKSPACE_NAME = '.*';/export const WORKSPACE_NAME = '$name';/" "$file"
  grep -q "^export const WORKSPACE_NAME = '$name';" "$file" || stop "Could not write the workspace name into $file."
  [[ "$name" == "WindFarmDigitalTwin" ]] || say "The app looks for the workspace $name"
}

copy_overlay() {
  [[ -f "$APP/rayfin/rayfin.yml" ]] || stop "$APP is not a Rayfin project (no rayfin/rayfin.yml)."
  [[ -d "$APP/packages/functions" ]] || stop "$APP has no packages/functions. Run this script without --overlay."
  cp -R "$HERE/overlay/." "$APP/"
  name_workspace
  # The tab of the browser: the template calls every app "Fabric App".
  if [[ -f "$APP/packages/frontend/index.html" ]]; then
    sed -i.bak 's|<title>Fabric App</title>|<title>Northwind Ridge Wind Farm</title>|' "$APP/packages/frontend/index.html" && rm -f "$APP/packages/frontend/index.html.bak"
  fi
  echo "Copied the twin into ${APP#"$HERE"/}: packages/frontend/src/App.tsx, packages/frontend/src/twin, packages/functions/src."
}

has_sql_driver() { grep -q '"mssql"' "$APP/packages/functions/package.json" 2>/dev/null; }
# Is NAME a dependency in FILE? Each library is looked for by itself: an install that was stopped half way leaves
# one of a pair behind (seen on 26 November 2026: three.js there, its types not).
has_dep() { grep -q "\"$2\"[[:space:]]*:" "$1" 2>/dev/null; }
# Add what is missing of a library and its types to one package of the app. $1 package.json, $2 workspace, $3 what to
# say, then NAME VERSION KIND (KIND is "" or -D) for each.
add_libraries() {
  local file="$1" workspace="$2" title="$3" said=0 name version kind; shift 3
  while (( $# )); do
    name="$1"; version="$2"; kind="$3"; shift 3
    has_dep "$file" "$name" && continue
    (( said )) || { say "$title"; said=1; }
    # shellcheck disable=SC2086
    (cd "$APP" && npm install --no-audit --no-fund $kind -w "$workspace" "$name@$version") \
      || stop "npm could not install $name@$version. Nothing in Fabric was touched. If its lines name a timeout (ETIMEDOUT, ERR_SOCKET_TIMEOUT), the connection dropped: run this again, it goes on from here."
  done
  (( said ))
}

rm -f "$READY"      # whatever this run does to the app, it is ready again only when the check at the end has passed

if [[ "$MODE" == "--overlay" ]]; then
  say "Copying the files of app/overlay"
  copy_overlay
  has_sql_driver || stop "The files are copied, but the functions now need a library this app does not have yet (the SQL driver). Run this script without --overlay: bash app/create-app.sh"
  echo "Now run, in $APP: npm run typecheck, then npx rayfin up"
  exit 0
fi

say "Checking Node.js and npm"
command -v node >/dev/null || stop "Node.js is not installed. Install version 22 as step 2 of docs/11-deployment-guide-phase4.md shows, then run this again."
NODE_VERSION="$(node --version)"; NODE_VERSION="${NODE_VERSION#v}"
NODE_MAJOR="${NODE_VERSION%%.*}"; NODE_REST="${NODE_VERSION#*.}"; NODE_MINOR="${NODE_REST%%.*}"
if (( NODE_MAJOR < 22 )) || (( NODE_MAJOR == 22 && NODE_MINOR < 13 )); then
  stop "Node.js $NODE_VERSION is too old: the Rayfin template needs 22.13 or newer. Step 2 of docs/11-deployment-guide-phase4.md installs version 22."
fi
NPM_VERSION="$(npm --version)"
echo "Node.js $NODE_VERSION, npm $NPM_VERSION"
if (( NODE_MAJOR != 22 && NODE_MAJOR != 24 )); then
  echo "Note: the Rayfin $RAYFIN_VERSION packages name Node.js 20, 22 and 24 as supported, and this app was built and tested on 22."
  echo "      Node.js $NODE_VERSION is not on that list. If a later step fails: nvm install 22, then run this again."
fi
if (( ${NPM_VERSION%%.*} < 11 )); then
  echo "Note: with npm 10.9.9 the install of this template stopped with \"Cannot read properties of null (reading 'edgesOut')\""
  echo "      when it was tried for this guide; npm 12 installed it. If you see that message: npm install -g npm@12"
fi

if [[ -f "$APP/rayfin/rayfin.yml" ]]; then
  say "Found an existing app in ${APP#"$HERE"/}: keeping it"
else
  [[ ! -e "$APP" ]] || stop "$APP exists but is not a Rayfin project. Move it away, then run this again."
  say "Creating the app from the Rayfin template (create-rayfin $RAYFIN_VERSION)"
  echo "If it asks a question, accept what it proposes."
  mkdir -p "$(dirname "$APP")"
  (cd "$(dirname "$APP")" && npx -y "@microsoft/create-rayfin@$RAYFIN_VERSION" --project-name "$(basename "$APP")" --template blankapp)
  [[ -f "$APP/rayfin/rayfin.yml" ]] || stop "The scaffolder ended without creating $APP/rayfin/rayfin.yml. Send me what it printed."
fi

if [[ -d "$APP/packages/functions" ]]; then
  say "The functions pack is already there"
else
  [[ -f "$APP/scripts/scaffold.mjs" ]] || stop "This app has no scripts/scaffold.mjs: it was not made from the Universal App template (blankapp)."
  say "Adding the functions pack of the template"
  (cd "$APP" && npm run pack:add -- functions)
  [[ -d "$APP/packages/functions" ]] || stop "The functions pack did not create packages/functions. Send me what it printed."
fi

say "Copying the files of app/overlay"
copy_overlay

add_libraries "$APP/packages/frontend/package.json" @rayfin-app/frontend "Adding three.js $THREE_VERSION to the frontend" \
  three "$THREE_VERSION" "" "@types/three" "$THREE_VERSION" -D || say "three.js is already a dependency"

add_libraries "$APP/packages/functions/package.json" @rayfin-app/functions "Adding the SQL driver (mssql $MSSQL_VERSION) to the functions: they read the Lakehouse with it" \
  mssql "$MSSQL_VERSION" "" "@types/mssql" "$MSSQL_TYPES_VERSION" -D || say "The SQL driver is already a dependency of the functions"

say "Checking the app: functions against their generated types, then every package with the compiler"
if ! (cd "$APP" && npm run typecheck); then
  stop "The check failed, so the app is not ready to deploy. The lines above name the file. Send them to me."
fi
sed -n "s/.*'\([0-9a-f]\{12\}\)'.*/\1/p" "$APP/packages/functions/src/build.ts" 2>/dev/null | head -n 1 > "$READY"

cat <<EOF

The app is ready in ${APP#"$HERE"/}. It has not been deployed. Next, from that folder:

  cd "$APP"
  export RAYFIN_ENCRYPTION_FALLBACK_ENABLED=true    # on WSL, which has no keychain: step 4 of the guide
  npx rayfin login
  npx rayfin up --workspace $(workspace_name) --item-name WindFarmTwin

docs/11-deployment-guide-phase4.md, step 4, goes on from here. The live values then come from the
Lakehouse, minutes old. For values that are seconds old: bash app/create-principal.sh (step 7).
EOF
