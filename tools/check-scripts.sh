#!/usr/bin/env bash
# Guards for the shell scripts of this repository. Exit code 1 when a rule is broken.
#   bash tools/check-scripts.sh
#
# Rule 1. Scripts that run on the workstation or in Azure Cloud Shell (infra/) may use
#   the Azure CLI itself and the azure-iot-ops extension, and no other extension. In
#   Cloud Shell, "az connectedk8s" can crash with a 'cffi' version mismatch when it is
#   loaded together with azure-iot-ops (docs/troubleshooting.md).
# Rule 2. A script starts another script of the repository through "bash", never
#   directly, so that a copy without execute permissions still works.
# Rule 3. No guide, and no usage line or hint of a script, shows a repository script
#   started directly ("./infra/vm.sh status"). The form is "bash infra/vm.sh status".
#   A copy that was unpacked on Windows, unpacked with "python3 -m zipfile" or merged
#   file by file has no execute permission, and the direct form then answers
#   "Permission denied"; that happened three times during the validated deployments.
#   The validation logs are records and are not checked. Two forms are allowed because
#   they name the mistake: "not `./…sh`" and "./…sh: Permission denied".
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORBIDDEN='az[[:space:]]+(connectedk8s|k8s-extension|customlocation|k8s-configuration)([[:space:]]|$)'
FORBIDDEN_ADD='az[[:space:]]+extension[[:space:]]+add.*--name[[:space:]]+(connectedk8s|k8s-extension|customlocation)'
# A line that begins (after indentation, or after "exec") with a path ending in .sh.
DIRECT_CALL='^[[:space:]]*(exec[[:space:]]+)?"?(\$\{?[A-Za-z_]+\}?|\.{1,2})/[^[:space:]"]*\.sh"?([[:space:]]|$)'
# A repository script named with "./" in front, anywhere in a line.
SCRIPT_PATH='\./(infra|edge/scripts|tools|app|config)/[A-Za-z0-9._/-]*\.sh'
# A usage line in the header of a script: "#   infra/vm.sh status".
BARE_USAGE='^#[[:space:]]+(infra|edge/scripts|tools|app|config)/[A-Za-z0-9._-]+\.sh([[:space:]]|$)'

status=0
report() {  # report RULE FILE HITS
  printf 'FAIL rule %s: %s\n%s\n' "$1" "${2#"$REPO_ROOT"/}" "$3"
  status=1
}
direct_starts() {  # direct_starts FILE: numbered lines that show a script started directly
  sed -E -e "s#bash ${SCRIPT_PATH}##g" -e "s#not \`${SCRIPT_PATH}##g" -e "s#${SCRIPT_PATH}: Permission denied##g" "$1" \
    | grep -n -E "(^|[^A-Za-z0-9_}\"/.~-])${SCRIPT_PATH}" || true
}
for script in "$REPO_ROOT"/infra/*.sh "$REPO_ROOT"/edge/scripts/*.sh "$REPO_ROOT"/tools/*.sh "$REPO_ROOT"/app/*.sh "$REPO_ROOT"/config/*.sh; do
  # Comment lines may mention the commands; only executable lines count for rules 1 and 2.
  code="$(grep -n -v -E '^[[:space:]]*#' "$script" || true)"
  ok=yes
  if [[ "$script" == "$REPO_ROOT"/infra/* ]]; then
    if hits="$(grep -E "^[0-9]+:.*($FORBIDDEN|$FORBIDDEN_ADD)" <<< "$code")"; then report 1 "$script" "$hits"; ok=""; fi
  fi
  if hits="$(sed -E 's/^([0-9]+):/\1\t/' <<< "$code" | awk -F'\t' -v re="$DIRECT_CALL" '$2 ~ re {print $1 ": " $2}')" && [[ -n "$hits" ]]; then
    report 2 "$script" "$hits"; ok=""
  fi
  # Rule 3 counts comment lines too: the header of a script is its usage text.
  hits="$(direct_starts "$script"; grep -n -E "$BARE_USAGE" "$script" || true)"
  if [[ -n "$hits" ]]; then report 3 "$script" "$hits"; ok=""; fi
  if [[ -n "$ok" ]]; then printf 'ok   %s\n' "${script#"$REPO_ROOT"/}"; fi
done
while IFS= read -r -d '' doc; do
  case "$doc" in *validation-log*) continue ;; esac
  hits="$(direct_starts "$doc")"
  if [[ -n "$hits" ]]; then report 3 "$doc" "$hits"; else printf 'ok   %s\n' "${doc#"$REPO_ROOT"/}"; fi
done < <(find "$REPO_ROOT" \( -name node_modules -o -name .git -o -name .pytest_cache -o -path "$REPO_ROOT/app/windfarm-twin" -o -path "$REPO_ROOT/app/out" \) -prune \
           -o -type f \( -name '*.md' -o -name 'demo.env.example' \) -print0 | sort -z)
exit "$status"
