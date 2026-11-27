"""The steps of the deployment, in order: what each looks at, what it changes, and what it leaves to a person.

A step's probe changes nothing in Azure or Fabric. (Two preflight probes write a value they have looked up into the
settings file on this computer, and say so.) A step's act writes and is followed by the probe again: the step is
complete when the probe says so. docs/15-deployment-runner.md has the same list with the documentation
each step rests on and how far it has been proven.
"""
from __future__ import annotations

import base64
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from . import names
from .cloud import UNREACHED, CloudError, operation, run_notebook
from .core import PHASES, Blocked, Probe, Refused, Step, StillRunning, blocked, done, kept, todo, unverified

TAG = "windfarm-demo-deployment"
PROVIDERS = ("Microsoft.ExtendedLocation", "Microsoft.Kubernetes", "Microsoft.KubernetesConfiguration", "Microsoft.IoTOperations",
             "Microsoft.DeviceRegistry", "Microsoft.SecretSyncController", "Microsoft.Storage", "Microsoft.Insights")
# Regions in which Azure IoT Operations supports Arc clusters (Microsoft Learn, read November 2026).
IOT_OPERATIONS_REGIONS = ("eastus", "eastus2", "westus", "westus2", "westus3", "southcentralus", "westeurope", "northeurope",
                          "germanywestcentral")
CUSTOM_LOCATIONS_APP = "bc313c14-388c-4e7d-a58e-70017303ee3b"
# Built-in roles by the ID that is the same in every tenant (Microsoft Learn, Azure built-in roles, read 25 November 2026).
# The runner reads and assigns roles by ID: asking Azure for the names means downloading every role definition.
ROLE_NAMES = {"8e3af657-a8ff-443c-a75c-2fe8c4bcb635": "Owner", "b24988ac-6180-42a0-ab88-20f7382dd24c": "Contributor",
              "acdd72a7-3385-48ef-bd42-f606fba81ae7": "Reader", "18d7d88d-d35e-4fb5-a5c3-7773c20a72d9": "User Access Administrator",
              "f58310d9-a9f6-439a-9e8d-f62e7b41a168": "Role Based Access Control Administrator",
              "34e09817-6cbe-4d01-b1a2-e0eac5743d41": "Kubernetes Cluster - Azure Arc Onboarding"}
ROLE_IDS = {role: guid for guid, role in ROLE_NAMES.items()}
QUICK = 60      # seconds for a question preflight can do without: unanswered, the step says NOT CHECKED and the run goes on
# Resource providers whose resources belong in the demo's resource group: what the scripts create, and what
# Azure and a managed subscription add to it by themselves (just-in-time access, monitoring).
RG_PROVIDERS = ("microsoft.compute", "microsoft.network", "microsoft.devtestlab", "microsoft.kubernetes",
                "microsoft.kubernetesconfiguration", "microsoft.extendedlocation", "microsoft.iotoperations",
                "microsoft.deviceregistry", "microsoft.storage", "microsoft.secretsynccontroller", "microsoft.managedidentity",
                "microsoft.security", "microsoft.insights", "microsoft.eventgrid", "microsoft.alertsmanagement",
                "microsoft.fabric")      # the capacity of the deployment's own, when the operator chose to have one made
LIVE_TABLES = ("TurbineTelemetry", "WeatherObservations", "AlarmEvents", "TurbineStateChanges", "AssetRegistry", "EdgeHeartbeats")
ALL_TABLES = ("RawEvents",) + LIVE_TABLES
GATE_NOTEBOOK = "90_deployment_gate"
NOTEBOOKS = {
    "phase1": ("01_load_reference_data", "02_generate_history", "03_refresh_forecast", "04_question_bank", GATE_NOTEBOOK),
    "phase2": ("05_build_model_tables", "06_build_semantic_model", "07_model_acceptance", "08_build_report"),
    "phase3": ("09_build_data_agent", "10_test_data_agent", "11_build_ontology"),
    "phase5a": ("12_send_edge_command",),
    "phase5bc": ("13_command_center",),
}
MODEL, REPORT, DATA_AGENT, ONTOLOGY, OPERATIONS_AGENT = ("WindFarm Operations", "WindFarm Operations Report", "WindFarmDataAgent",
                                                         "WindFarmOntology", "WindFarmGearboxWatch")
STORY = ("13_command_center",)   # of Phases 5b and 5c: not the runner's, and no reason to stop when a person imported it


# --------------------------------------------------------------------------------------------- helpers
def name(ctx, key: str) -> str:
    return ctx.cfg.get(key) or names.FIXED.get(key, "")


def suffix(ctx) -> str:
    return ctx.cfg["DEPLOYMENT_SUFFIX"]


def account(ctx) -> dict:
    return ctx.remember("account", lambda: ctx.az.json("account", "show"))


def workspace_id(ctx) -> str | None:
    return ctx.target("workspace_id")


def workspaces(ctx) -> list:
    return ctx.remember("workspaces", lambda: ctx.fabric.listing("workspaces"))


def role_assignments(ctx, scope: str, whose: str, timeout: int = QUICK) -> list[tuple[str, str]]:
    """(role, scope) of the role assignments one filter selects: the role by name when it is one of ROLE_NAMES, by its
    ID otherwise.

    One question with a small answer, to the operation Role Assignments - List For Scope. `az role assignment list`
    asks the same and then fetches every role definition of the subscription to print names (its own reference calls
    that expensive): on 25 November 2026 it did not answer a workstation within three minutes.
    """
    rows = ctx.az.json("rest", "--method", "get",
                       "--url", f"https://management.azure.com{scope}/providers/Microsoft.Authorization/roleAssignments",
                       "--url-parameters", "api-version=2022-04-01", f"$filter={whose}",
                       "--query", "value[].{role: properties.roleDefinitionId, scope: properties.scope}", timeout=timeout) or []
    found = []
    for row in rows:
        guid = str(row.get("role") or "").rsplit("/", 1)[-1].lower()
        found.append((ROLE_NAMES.get(guid, guid), str(row.get("scope") or "")))
    return found


def covers(assigned_at: str, scope: str) -> bool:
    """A role assigned at a scope holds for everything below it."""
    above, below = assigned_at.rstrip("/").lower(), scope.rstrip("/").lower()
    return below == above or below.startswith(above + "/")


def items(ctx) -> list:
    ws = workspace_id(ctx)
    return ctx.remember("items", lambda: ctx.fabric.listing(f"workspaces/{ws}/items")) if ws else []


def item(ctx, kind: str, display_name: str) -> dict | None:
    """The one item of that kind and name. Two of them is a reason to stop, not to pick."""
    found = [entry for entry in items(ctx) if entry.get("type") == kind and entry.get("displayName") == display_name]
    if len(found) > 1:
        raise Refused(f"The workspace has {len(found)} items of type {kind} named {display_name}. The runner does not choose. "
                      "Remove the one that is not the demo's.")
    return found[0] if found else None


def need_item(ctx, kind: str, display_name: str) -> dict:
    found = item(ctx, kind, display_name)
    if not found:
        raise CloudError(f"{kind} {display_name} is not in the workspace.")
    return found


def after(step_id: str) -> Probe:
    return todo(f"after {step_id}")


def kql_database(ctx) -> tuple[str, str] | None:
    """The query address of the KQL database and its name, or None while it does not exist."""
    database = item(ctx, "KQLDatabase", name(ctx, "EVENTHOUSE_NAME"))
    if not database:
        return None
    details = ctx.remember("kqldb", lambda: ctx.fabric.get(f"workspaces/{workspace_id(ctx)}/kqlDatabases/{database['id']}"))
    uri = ((details or {}).get("properties") or {}).get("queryServiceUri")
    return (uri, database["displayName"]) if uri else None


def kql(ctx, text: str) -> list[dict]:
    uri, database = kql_database(ctx)
    return ctx.kusto.rows(uri, database, text, mgmt=text.lstrip().startswith("."))


RUNNABLE = (".execute database script", ".create", ".alter")
REMOVES = re.compile(r"^\s*\.(drop|clear|delete|purge|set|replace|rename|move)\b", re.M)
# The only KQL files the runner sends. The repair and reset files of the repository are a person's to run.
KQL_FILES = ("fabric/kql/01-tables.kql", "fabric/kql/02-update-policies.kql", "fabric/kql/03-onelake-availability.kql",
             "fabric/kql/04-prepared-views.kql", "fabric/kql/05-agent-readiness.kql",
             "fabric/kql/06-remediation-readiness.kql", "fabric/kql/07-command-log.kql")


def kql_blocks(text: str) -> list[str]:
    """The commands of a KQL file that set something up. The files keep each command free of empty lines, because a
    query window splits on them too. Checks, queries and anything that drops or clears are left out."""
    blocks = []
    for chunk in re.split(r"\n\s*\n", text):
        rows = [row for row in chunk.splitlines() if row.strip()]
        while rows and rows[0].lstrip().startswith("//"):
            rows.pop(0)             # a comment above a command; the comments inside a database script stay, as they ran
        if rows and rows[0].lstrip().startswith(RUNNABLE) and not REMOVES.search("\n".join(rows)):
            blocks.append("\n".join(rows))
    return blocks


def run_kql_file(ctx, relative: str) -> None:
    if relative not in KQL_FILES:
        raise CloudError(f"The runner does not run {relative}.")
    for block in kql_blocks((ctx.root / relative).read_text(encoding="utf-8")):
        for row in kql(ctx, block):
            if row.get("Result") not in (None, "Completed"):
                raise CloudError(ctx.redact(f"{relative}: the Eventhouse answered {row.get('Result')} to "
                                            f"{str(row.get('CommandText', ''))[:120]}: {str(row.get('Reason', ''))[:300]}"))


def confirmation(ctx, step_id: str, what: str) -> Probe:
    """For what the runner cannot read: the operator says it is so, and the checkpoint keeps who and when."""
    said = ctx.confirmed(step_id)
    if said:
        return unverified(f"{what}: confirmed by {said.get('by', 'the operator')} on {said.get('at')}; the runner cannot read it",
                          confirmed=True)
    return todo("waiting for your confirmation")


def script(ctx, *argv: str, env: dict | None = None) -> str:
    # The settings by name, and the subscription by name: a script started by the runner does not go by .deploy/current
    # or by the Azure CLI's active subscription, either of which another terminal can change while it runs.
    return ctx.shell.must(["bash", *argv], env={"ENV_FILE": str(ctx.env_file), "AZ_SUBSCRIPTION_PIN": ctx.cfg.get("SUBSCRIPTION_ID", ""),
                                                **(env or {})})


LARGE_ANSWER_SECONDS = 45


def act_iot_operations(ctx) -> None:
    """infra/04, after one look at the line to Azure.

    `az iot ops init` and `create` fetch answers of several megabytes and give them no time limit of their own. On
    26 November 2026, from a workstation that received 5 kB a second from Azure, init printed "Unable to stream
    download." every ten minutes and stood until the script's limit of ninety minutes, twice. The same script, started
    from Azure Cloud Shell with the deployment's settings, finished, and the next apply went on from there. So the
    runner asks for one such answer first, and hands the script to the operator when it does not arrive.
    """
    started = ctx.clock()
    try:
        ctx.az.json("rest", "--method", "get",
                    "--url", f"https://management.azure.com/subscriptions/{ctx.cfg['SUBSCRIPTION_ID']}/providers",
                    "--url-parameters", "api-version=2021-04-01", "--query", "length(value)", timeout=LARGE_ANSWER_SECONDS)
    except CloudError:
        raise Blocked(
            f"An answer of about 3.5 MB from Azure (the list of resource providers) did not arrive on this computer within "
            f"{LARGE_ANSWER_SECONDS} seconds. The Azure CLI commands of this step fetch answers of that size and wait for "
            "them without a limit: on a line like this they stood for ninety minutes and did not finish.",
            "Run this one script where Azure answers quickly, for example in Azure Cloud Shell (Bash), signed in as the same person:\n"
            f"  1. Upload two files there: the archive of this repository, and {ctx.env_label}\n"
            "  2. python3 -m zipfile -e fabric-windfarm-digital-twin-auto.zip . && cd fabric-windfarm-digital-twin-auto && "
            "ENV_FILE=\"$HOME/demo.env\" bash infra/04-deploy-iot-operations.sh\n"
            "     It skips what exists. Press Enter now and then: Cloud Shell ends a session after 20 minutes without a key.\n"
            "Or repair the line of this computer and apply again (compare a download here with one elsewhere).") from None
    ctx.say(f"      . a large answer from Azure arrived in {ctx.clock() - started:.0f} s")
    script(ctx, "infra/04-deploy-iot-operations.sh")


def on_vm(ctx, *argv: str) -> str:
    """A script on the edge VM, through the repository's own way in (SSH, or the VM agent when SSH is closed)."""
    script(ctx, "infra/vm.sh", "push")
    return script(ctx, "infra/vm.sh", "ssh", "bash", *argv)


def recorded(ctx, step_id: str, what: str) -> Probe:
    """For a step with nothing to look at from outside: the checkpoint is the only witness."""
    saved = ctx.state.step(step_id)
    if saved.get("status") == "complete":
        return done(saved.get("detail") or f"{what} (recorded on {saved.get('at')})")
    return todo()


def keep_done(ctx, step_id: str, live) -> Probe:
    """A gate that has passed stays passed: its result is a fact about the time it was measured."""
    saved = ctx.state.step(step_id)
    if saved.get("status") == "complete":
        return Probe("done", f"passed on {saved.get('at')}: {saved.get('detail', '')}", saved.get("evidence", {}))
    return live(ctx)


# ------------------------------------------------------------------------------------------- preflight
def pre_tools(ctx) -> Probe:
    missing = [tool for tool in ("az", "bash", "ssh") if not ctx.shell.which(tool)]
    if missing:
        return blocked("Not on this computer: " + ", ".join(missing) + ".", "Install them as in step 0 of "
                       "docs/01-deployment-guide-phase1.md (Workstation), then sign in: az login")
    return done("az, bash and ssh are here")


def pre_signin(ctx) -> Probe:
    try:
        me = account(ctx)
    except CloudError as error:
        return blocked(str(error), "az login")
    user = me.get("user") or {}
    if user.get("type") != "user":
        return blocked(f"The Azure CLI is signed in as a {user.get('type')}. Several steps accept a person only: the "
                       "Custom Locations lookup, the notebooks of Phase 2 and the agents of Phase 3.", "az login   (as yourself)")
    wanted = ctx.cfg.get("SUBSCRIPTION_ID")
    if wanted and wanted.lower() != str(me.get("id", "")).lower():
        return blocked(f"The Azure CLI is on subscription {me.get('name')} ({me.get('id')}); the settings name {wanted}.",
                       f"az account set --subscription {wanted}")
    recorded_tenant = ctx.target("tenant_id")
    if recorded_tenant and recorded_tenant != me.get("tenantId"):
        return blocked(f"This deployment belongs to tenant {recorded_tenant}; the Azure CLI is signed in to {me.get('tenantId')}.",
                       f"az login --tenant {recorded_tenant}")
    return done(f"{user.get('name')} in tenant {me.get('tenantId')}, subscription {me.get('name')}",
                tenant_id=me.get("tenantId"), subscription_id=me.get("id"))


EXTENSIONS = ("azure-iot-ops",)     # what the runner itself asks the Azure CLI on this computer; the scripts check their own


def pre_extensions(ctx) -> Probe:
    have = set(ctx.az.json("extension", "list", "--query", "[].name") or [])
    missing = [extension for extension in EXTENSIONS if extension not in have]
    if missing:
        return blocked("The Azure CLI on this computer lacks the extension " + ", ".join(missing) + ". The runner does not let "
                       "the CLI install it on the way, because the CLI asks before it does and nobody would see the question.",
                       "\n".join(f"az extension add --name {extension} --yes" for extension in missing))
    return done("Azure CLI extension azure-iot-ops is installed")


def pre_providers(ctx) -> Probe:
    # One small question for each. A single `az provider list` would be one call, and a download of every provider
    # with all its resource types: on a slow line that is the kind of call this runner has learned to avoid.
    wanted = PROVIDERS + (("Microsoft.Fabric",) if creating(ctx) else ())       # for a capacity of the deployment's own
    missing = [namespace for namespace in wanted
               if ctx.az.maybe("provider", "show", "--namespace", namespace, "--query", "registrationState") != "Registered"]
    if missing:
        return blocked("Not registered in the subscription: " + ", ".join(missing) + ". Registering is a change to the whole "
                       "subscription, so the runner leaves it to you.",
                       "\n".join(f"az provider register --namespace {namespace}" for namespace in missing)
                       + "\nRegistration takes a few minutes; plan shows when it is through.")
    return done(f"{len(wanted)} resource providers registered")


def pre_rights(ctx) -> Probe:
    me = account(ctx)
    needed = ("Needed: Contributor or Owner on the subscription to create the resource group, and for the role steps a role "
              "that assigns roles")
    try:
        myself = (ctx.az.graph("me?$select=id") or {}).get("id")
        if not myself:
            raise CloudError("Microsoft Graph did not say who is signed in")
        # at the subscription or above it, and through the groups you are in: assignedTo() follows groups
        held = role_assignments(ctx, f"/subscriptions/{me['id']}", f"atScope() and assignedTo('{myself}')")
    except CloudError as error:
        return unverified(f"your roles could not be read ({str(error)[:160]}). {needed}")
    roles = {role for role, _ in held}
    known = roles & set(ROLE_IDS)
    creates = roles & {"Owner", "Contributor"}
    assigns = roles & {"Owner", "User Access Administrator", "Role Based Access Control Administrator"}
    if not creates:
        if roles - known:
            return unverified(f"you hold {len(roles - known)} role(s) on the subscription that the runner does not know by "
                              f"their ID{', and ' + ', '.join(sorted(known)) if known else ''}. Whether they let you create a "
                              f"resource group shows at the first step. {needed}")
        return blocked(f"Your roles on the subscription are: {', '.join(sorted(known)) or 'none'}. Creating the resource group "
                       "needs Contributor or Owner.", "Ask the owner of the subscription for Contributor, or for a resource "
                       "group you own; the runner does not widen its own access.")
    if not assigns:
        return done(f"roles on the subscription: {', '.join(sorted(creates))}. You hold none of the roles that assign roles: the "
                    "role steps will stop and say what to ask for")
    return done("roles on the subscription: " + ", ".join(sorted(creates | assigns)))


def pre_region(ctx) -> Probe:
    location = ctx.cfg.get("LOCATION", "")
    if not location:
        return blocked("No Azure region has been chosen for the edge: the VM and Azure IoT Operations. The runner chooses no "
                       "geography by itself, and the settings, the profile of the subscription and the options of this run name none.",
                       f"python3 tools/deploy.py plan --edge-region REGION     one of: {', '.join(IOT_OPERATIONS_REGIONS)}\n"
                       "Add --save-profile to have the next deployments in this subscription take the same region without being asked.")
    if location not in IOT_OPERATIONS_REGIONS:
        return blocked(f"LOCATION is {location}. Azure IoT Operations supports Arc clusters in: {', '.join(IOT_OPERATIONS_REGIONS)}.",
                       f"Set LOCATION in {ctx.env_label} to one of these.")
    if ctx.state.step("p1.edge_vm").get("status") == "complete":
        return done(f"{location}; the VM exists, so its size is no longer a question")
    try:
        usable, refused = offered_sizes(ctx)
    except CloudError as error:
        # Not a reason to stop: p1.edge_vm tries the sizes of VM_SIZE in their order, and Azure refuses what is not offered.
        return unverified(f"{location} is supported. Which VM sizes you are offered could not be read ({str(error)[:140]}). "
                          "p1.edge_vm tries the sizes of VM_SIZE in their order; Azure refuses the ones you are not offered. "
                          "Put a size you know you are offered first", sizes_read=False)
    if not usable:
        return blocked(f"None of the sizes in VM_SIZE is offered to this subscription in {location}: "
                       + "; ".join(f"{size}: {why}" for size, why in refused.items()),
                       f"Put a size with 8 vCPUs and 32 GB that you are offered into VM_SIZE in {ctx.env_label}. The Azure "
                       "portal shows them under Virtual machines, Create, Size; sizes of the v6 and v7 families are the usual ones "
                       "in a managed subscription.")
    skipped = f" ({', '.join(refused)} not offered)" if refused else ""
    return done(f"{location}; VM size {usable[0]} is offered{skipped}", sizes=usable, sizes_read=True)


def offered_sizes(ctx) -> tuple[list, dict]:
    """The sizes of VM_SIZE this subscription may create in LOCATION, in their order, and why the others are out.

    One call to the Resource SKUs API with its location filter. `az vm list-skus` asks the same API for every region
    and filters on this computer: on 25 November 2026 that did not answer a workstation within five minutes. The
    filtered answer still holds every SKU of the region, and an hour later did not arrive within two minutes either:
    the caller treats no answer as "not read" and goes on.
    """
    location, sizes = ctx.cfg["LOCATION"], ctx.cfg.get("VM_SIZE", "").split()
    rows = ctx.az.json(
        "rest", "--method", "get", "--url", f"https://management.azure.com/subscriptions/{account(ctx)['id']}/providers/Microsoft.Compute/skus",
        "--url-parameters", "api-version=2021-07-01", f"$filter=location eq '{location}'",
        "--query", "value[?resourceType=='virtualMachines'].{name: name, refused: restrictions[?type=='Location'] | [0].reasonCode}",
        timeout=QUICK) or []
    known = {row.get("name"): row.get("refused") for row in rows}
    usable = [size for size in sizes if size in known and not known[size]]
    refused = {size: (known[size] if size in known else f"not known in {location}") for size in sizes if size not in usable}
    return usable, refused


def vm_family(size: str) -> tuple[str, int] | None:
    """('standarddasv7family', 8) for Standard_D8as_v7: the name Azure's usage list gives the size's family, as far as it
    can be told from the size's name, and the vCPUs the size takes."""
    match = re.fullmatch(r"Standard_([A-Z]+)(\d+)([a-z]*)_v(\d+)", size)
    if not match:
        return None
    letters, cores, features, version = match.groups()
    return f"standard{letters}{features}v{version}family".lower(), int(cores)


def pre_quota(ctx) -> Probe:
    """Room in the vCPU quota for the VM. Microsoft: a new VM must fit the quota of its size family and the region's
    total, and deallocated VMs count too. Only the size that is tried first is looked at."""
    location, sizes = ctx.cfg.get("LOCATION", ""), ctx.cfg.get("VM_SIZE", "").split()
    if ctx.state.step("p1.edge_vm").get("status") == "complete":
        return done("the VM exists")
    if not location:
        return blocked("The quota is a region's: no region has been chosen for the edge yet.", "See pre.region.")
    told = vm_family(sizes[0]) if sizes else None
    if not told:
        return unverified(f"the size family of {sizes[0] if sizes else 'nothing'} cannot be told from its name")
    family, cores = told
    try:
        rows = ctx.az.json("vm", "list-usage", "--location", location,
                           "--query", "[].{name: name.value, used: currentValue, limit: limit}", timeout=QUICK) or []
    except CloudError as error:
        return unverified(f"the vCPU quota in {location} could not be read ({str(error)[:140]})")
    by_name = {str(row.get("name") or "").lower(): row for row in rows}
    free = lambda row: int(row.get("limit") or 0) - int(row.get("used") or 0)      # noqa: E731
    total, own = by_name.get("cores"), by_name.get(family)
    short = [f"{what}: {row.get('used')} of {row.get('limit')} vCPUs in use" for what, row in
             (("the region's total", total), (f"the family of {sizes[0]}", own)) if row and free(row) < cores]
    if short:
        return blocked(f"{sizes[0]} takes {cores} vCPUs, and the quota in {location} has no room for them. " + "; ".join(short) + ".",
                       "Ask for more in the Azure portal: Quotas, Compute. A VM that is stopped still counts; only a deleted one "
                       "gives its vCPUs back. Or put a size of another family first in VM_SIZE.")
    if not own:
        return unverified(f"{cores} vCPUs for {sizes[0]}: the region's total has room"
                          + (f" ({free(total)} free of {total.get('limit')})" if total else " as far as it is listed")
                          + f"; the usage list has no row named like the family of {sizes[0]}")
    return done(f"{cores} vCPUs for {sizes[0]}: {free(own)} free of {own.get('limit')} in its family"
                + (f", {free(total)} of {total.get('limit')} in the region" if total else ""))


def pre_names(ctx) -> Probe:
    account_name = ctx.cfg.get("STORAGE_ACCOUNT_NAME", "")
    if ctx.target("resource_group_id"):
        return done("names in use by this deployment")
    answer = ctx.az.json("storage", "account", "check-name", "--name", account_name) or {}
    if not answer.get("nameAvailable", True):
        return blocked(f"The storage account name {account_name} is taken ({answer.get('reason')}). Storage names are unique "
                       "across Azure.", "python3 tools/deploy.py plan --new")
    return done(f"suffix {suffix(ctx)}; {account_name} is free")


def pre_custom_locations(ctx) -> Probe:
    value = ctx.cfg.get("CUSTOM_LOCATIONS_OID", "")
    if re.fullmatch(r"[0-9a-fA-F-]{36}", value) and value.lower() != CUSTOM_LOCATIONS_APP:
        return done("Custom Locations object ID is in the settings")
    found = (ctx.az.graph(f"servicePrincipals(appId='{CUSTOM_LOCATIONS_APP}')?$select=id") or {}).get("id")
    if not found:
        return blocked("The object ID of the Custom Locations service in your tenant is not in the settings, and the Azure CLI "
                       "could not read it. Reading it needs a person who may read service principals in Microsoft Entra ID.",
                       f"az ad sp show --id {CUSTOM_LOCATIONS_APP} --query id --output tsv\n"
                       f"Put the 36 characters it prints into CUSTOM_LOCATIONS_OID in {ctx.env_label}. It is not the ID above, "
                       "which is the same in every tenant.")
    names.write_env(ctx.env_file, {"CUSTOM_LOCATIONS_OID": found})
    ctx.cfg["CUSTOM_LOCATIONS_OID"] = found
    return done("Custom Locations object ID read from Microsoft Entra ID and written to the settings")


def pre_fabric(ctx) -> Probe:
    try:
        workspaces(ctx)
    except CloudError as error:
        if error.code == UNREACHED:
            # No answer at all: the network of this computer, not the sign-in (26 November 2026, a TLS handshake that hung).
            return blocked(f"The Fabric API could not be reached from this computer: {error}",
                           "This is the connection, not your sign-in. Run the same command again. If it says the same, time a "
                           "connection from here:\n"
                           "curl -sS -o /dev/null -w '%{time_connect} s to connect, %{time_appconnect} s for TLS\\n' https://api.fabric.microsoft.com/")
        return blocked(f"The Fabric API did not answer the signed-in user: {error}", "az login   (in a session that can get a "
                       "token for https://api.fabric.microsoft.com; Azure Cloud Shell often cannot)")
    return done("the Fabric API answers")


# What a capacity can hold, by its SKU (Microsoft Learn, "Microsoft Fabric concepts and licenses", read 25 November 2026):
# F SKUs and the trial hold Fabric items; P SKUs do once Fabric is enabled on them; Premium Per User "doesn't provision
# a Fabric capacity", and A and EM SKUs "only support Power BI items".
CAN_HOLD = {"fabric": "a Fabric capacity", "trial": "a Fabric trial capacity",
            "premium": "a Power BI Premium capacity (P SKU): Fabric has to be enabled on it"}
CANNOT_HOLD = {"per-user": "a Premium Per User capacity. It holds Power BI items only",
               "embedded": "an A or EM capacity. It holds Power BI items only"}


# ---- a capacity of the deployment's own, when the operator chose to have one made ------------------------------------
FABRIC_ARM = "api-version=2023-11-01"        # Microsoft.Fabric: Fabric Capacities - Create Or Update, Get, Check Name
#                                              Availability and List Skus, as read on 25 November 2026
NEW_CAPACITY_SKU = "F16"
NEW_CAPACITY_BASE = "fabwindfarm"            # a capacity's name: a lower-case letter, then letters and digits, 3 to 63
# Microsoft Learn, "Fabric region availability", page of 17 November 2026, read 25 November 2026: the regions with all
# Fabric workloads, and for each what the page lists as not available there, as far as this demo uses it.
REGIONS_READ = "17 November 2026"
FABRIC_REGIONS = {
    "brazilsouth": "Brazil South", "canadacentral": "Canada Central", "canadaeast": "Canada East", "mexicocentral": "Mexico Central",
    "centralus": "Central US", "eastus": "East US", "eastus2": "East US 2", "northcentralus": "North Central US",
    "southcentralus": "South Central US", "westus": "West US", "westus2": "West US 2", "westus3": "West US 3",
    "northeurope": "North Europe", "westeurope": "West Europe", "francecentral": "France Central",
    "germanywestcentral": "Germany West Central", "italynorth": "Italy North", "norwayeast": "Norway East",
    "polandcentral": "Poland Central", "spaincentral": "Spain Central", "swedencentral": "Sweden Central",
    "switzerlandnorth": "Switzerland North", "switzerlandwest": "Switzerland West", "uksouth": "UK South", "ukwest": "UK West",
    "uaenorth": "UAE North", "southafricanorth": "South Africa North", "eastasia": "East Asia", "southeastasia": "Southeast Asia",
    "australiaeast": "Australia East", "australiasoutheast": "Australia Southeast", "centralindia": "Central India",
    "southindia": "South India", "indonesiacentral": "Indonesia Central", "israelcentral": "Israel Central",
    "japaneast": "Japan East", "japanwest": "Japan West", "koreacentral": "Korea Central", "malaysiawest": "Malaysia West",
    "newzealandnorth": "New Zealand North", "taiwannorth": "Taiwan North", "taiwannorthwest": "Taiwan Northwest"}
FABRIC_REGION_GAPS = {"eastus": ("Operations agent",), "southcentralus": ("Operations agent",), "israelcentral": ("Fabric App",),
                      "malaysiawest": ("Fabric App",), "taiwannorth": ("Fabric App",), "taiwannorthwest": ("Fabric App",)}
DEMO_USES = {"Operations agent": "phase3", "Fabric App": "phase4"}       # what the demo needs of those, and from which phase
# Where the edge's own region lacks something the demo uses: the region next to it that lacks nothing.
NEIGHBOUR = {"southcentralus": "centralus", "eastus": "eastus2"}


def region_key(text) -> str:
    """'Central US', 'centralus' and 'US - Central US' are one region."""
    key = re.sub(r"[^a-z0-9]", "", str(text or "").lower())
    return key[2:] if key.startswith("us") and key[2:] in FABRIC_REGIONS else key


def region_name(region) -> str:
    return FABRIC_REGIONS.get(region_key(region), str(region))


def region_gaps(region, up_to: str = "phase4") -> list:
    """What Microsoft's table lists as missing in a region, of what the demo uses up to a phase."""
    return [feature for feature in FABRIC_REGION_GAPS.get(region_key(region), ())
            if PHASES.index(DEMO_USES[feature]) <= PHASES.index(up_to)]


def proper_fabric_region(edge_location: str) -> str | None:
    """The region for a new capacity: the edge's own when it lacks nothing the demo uses, else the one next to it."""
    edge = region_key(edge_location)
    if edge in FABRIC_REGIONS and not region_gaps(edge):
        return edge
    return NEIGHBOUR.get(edge)


def creating(ctx) -> bool:
    return bool(ctx.cfg.get("FABRIC_CAPACITY_CREATE_SKU"))


def new_capacity(ctx) -> dict:
    return {"name": ctx.cfg.get("FABRIC_CAPACITY_NAME", ""), "sku": ctx.cfg.get("FABRIC_CAPACITY_CREATE_SKU", ""),
            "region": region_key(ctx.cfg.get("FABRIC_CAPACITY_REGION", ""))}


def new_capacity_label(ctx) -> str:
    new = new_capacity(ctx)
    return f"{new['name']} ({new['sku']}, {region_name(new['region'])})"


def capacity_url(ctx) -> str:
    return (f"https://management.azure.com/subscriptions/{account(ctx)['id']}/resourceGroups/{ctx.cfg['RESOURCE_GROUP']}"
            f"/providers/Microsoft.Fabric/capacities/{new_capacity(ctx)['name']}")


def arm_capacity(ctx) -> dict | None:
    """The deployment's own capacity as Azure has it, or None while it does not exist."""
    return ctx.remember("arm_capacity", lambda: ctx.az.maybe("rest", "--method", "get", "--url", capacity_url(ctx),
                                                             "--url-parameters", FABRIC_ARM, timeout=QUICK))


def fabric_sku_regions(ctx, sku: str) -> set | None:
    """The regions Azure's list of SKUs names for a new capacity of this SKU (Fabric Capacities - List Skus).

    Every entry of the SKU is read and their regions are put together: the reference's sample has one region in each
    entry, so a SKU may stand in the list once for each region. (Up to the fifth issue only the first entry was read,
    and on 25 November the runner told a person that F16 is not offered in the region where he runs one.)
    None when the list does not name the SKU at all: Azure did not say, which is not the same as "nowhere"."""
    def ask():
        listed = ctx.az.json("rest", "--method", "get",
                             "--url", f"https://management.azure.com/subscriptions/{account(ctx)['id']}/providers/Microsoft.Fabric/skus",
                             "--url-parameters", FABRIC_ARM, "--query", "value[].{name: name, locations: locations}", timeout=QUICK) or []
        places = {region_key(place) for entry in listed if str(entry.get("name") or "").upper() == sku.upper()
                  for place in (entry.get("locations") or [])}
        return places or None
    return ctx.remember(f"fabric_skus:{sku}", ask)


def took_unlisted(ctx) -> str:
    """The region for a new capacity that a person took although Azure's list of SKUs does not name it, or ''."""
    return str(((ctx.state.data.get("choices") or {}).get("capacity_region_unlisted") or {}).get("answer") or "")


def capacity_name_free(ctx, capacity_name: str, region: str) -> tuple[bool, str]:
    answer = ctx.az.json("rest", "--method", "post", "--url",
                         f"https://management.azure.com/subscriptions/{account(ctx)['id']}/providers/Microsoft.Fabric/locations/"
                         f"{region}/checkNameAvailability", "--url-parameters", FABRIC_ARM,
                         "--body", json.dumps({"name": capacity_name, "type": "Microsoft.Fabric/capacities"}), timeout=QUICK) or {}
    return bool(answer.get("nameAvailable")), str(answer.get("reason") or answer.get("message") or "")


ASK = "python3 tools/deploy.py plan --ask   (in a terminal: it asks again)"


def pre_new_capacity(ctx) -> Probe:
    """Nothing stands in the way of making the capacity the operator chose to have made. Reads; creates nothing."""
    new, label = new_capacity(ctx), new_capacity_label(ctx)
    made = capacity(ctx)
    if made:                                  # the creation step found it in Fabric's list and wrote its ID down
        if made.get("state") != "Active":
            return blocked(f"Capacity {capacity_label(made)} is {made.get('state')}.", "Resume it in the Azure portal: Microsoft "
                           "Fabric, the capacity, Resume. The runner does not change a capacity once it exists.")
        return done(f"capacity {capacity_label(made)}, made by this deployment", capacity_id=made["id"])
    if not re.fullmatch(r"[a-z][a-z0-9]{2,62}", new["name"]) or not re.fullmatch(r"F\d+", new["sku"]):
        return blocked(f"The settings describe a new capacity that cannot be made: name '{new['name']}', SKU '{new['sku']}'. A name "
                       "is a lower-case letter followed by letters and digits; a SKU is F2, F4, F8, F16 and so on.", ASK)
    if new["region"] not in FABRIC_REGIONS:
        return blocked(f"'{new['region']}' is not a region with all Fabric workloads in Microsoft's table of {REGIONS_READ}.", ASK)
    user = str((account(ctx).get("user") or {}).get("name") or "")
    if "#EXT#" in user.upper():
        return blocked(f"You are signed in as a guest ({user}). Microsoft: a guest cannot be the administrator of a capacity, and "
                       "the runner makes you the administrator of the one it creates.", "Use an existing capacity, or sign in "
                       f"as a member of the tenant. {ASK}")
    missing = region_gaps(new["region"], ctx.options.up_to)
    if missing:
        return blocked(f"Microsoft's region table of {REGIONS_READ} lists no {' and no '.join(missing)} for a capacity in "
                       f"{region_name(new['region'])}, and the phases you chose use it.", f"Choose another region. {ASK}")
    later = [feature for feature in region_gaps(new["region"]) if feature not in missing]
    caution = f". For later phases: no {' and no '.join(later)} in that region, by Microsoft's table of {REGIONS_READ}" if later else ""
    unsure = ""
    try:
        offered = fabric_sku_regions(ctx, new["sku"])
        if offered is None:
            unsure = (f"Azure's list of SKUs does not name {new['sku']} for this subscription, so whether it can be made in "
                      f"{region_name(new['region'])} could not be told")
        elif new["region"] not in offered:
            named = some([region_name(place) for place in offered], most=12)
            if took_unlisted(ctx) != new["region"]:
                return blocked(f"Azure's list of SKUs does not name {region_name(new['region'])} for an {new['sku']} in this "
                               f"subscription. It names: {named}.", f"Choose another region, or take this one all the same and "
                               f"let Azure decide. {ASK}")
            unsure = (f"Azure's list of SKUs does not name {region_name(new['region'])} for an {new['sku']} (it names: {named}), "
                      "and you took the region all the same")
        if not (ctx.target("resource_group_id") and arm_capacity(ctx)):
            free, why = capacity_name_free(ctx, new["name"], new["region"])
            if not free:
                return blocked(f"The capacity name {new['name']} cannot be used ({why or 'no reason given'}).",
                               "python3 tools/deploy.py plan --new")
    except CloudError as error:
        return unverified(f"a new capacity will be made by p1.capacity: {label}. Whether {new['sku']} is offered there and the name "
                          f"is free could not be read ({str(error)[:140]}){caution}")
    if unsure:
        return unverified(f"a new capacity will be made by p1.capacity: {label}. {unsure}. The request for the capacity decides, "
                          f"straight after the resource group; if Azure refuses it, choose again: {ASK}{caution}")
    return done(f"a new capacity will be made by p1.capacity: {label}. Azure's list of SKUs names the region for {new['sku']}, and "
                f"the name is free{caution}")


def p1_capacity(ctx) -> Probe:
    if not creating(ctx):
        return done("the deployment uses a capacity that exists; none is made")
    new = new_capacity(ctx)
    if not ctx.target("resource_group_id"):
        return after("p1.resource_group")
    found = arm_capacity(ctx)
    if not found:
        return todo(f"{new['name']} does not exist yet")
    if (found.get("tags") or {}).get(TAG) != suffix(ctx):
        return blocked(f"A Fabric capacity named {new['name']} is in the resource group, and this deployment did not make it.",
                       "Start a deployment with other names: python3 tools/deploy.py plan --new")
    properties = found.get("properties") or {}
    state, provisioning = properties.get("state"), properties.get("provisioningState")
    if "Failed" in (state, provisioning):
        return blocked(f"Azure reports the capacity {new['name']} as failed.", "Look at it in the Azure portal (Microsoft Fabric, "
                       "the capacity, Activity log). If it is of no use, delete it there; the runner deletes nothing. Then run "
                       "apply again.")
    if state in ("Paused", "Pausing", "Suspended", "Suspending"):
        return blocked(f"The capacity {new['name']} is {state}.", "Resume it in the Azure portal: Microsoft Fabric, the capacity, "
                       "Resume. The runner does not resume a capacity.")
    if state != "Active":
        return todo(f"the capacity is {state or provisioning or 'being made'}")
    listed = next((entry for entry in capacities(ctx) if entry.get("displayName") == new["name"]), None)
    if not listed:
        return todo("the capacity is active in Azure; Fabric does not list it yet")
    if ctx.cfg.get("FABRIC_CAPACITY_ID") != listed["id"]:
        names.write_env(ctx.env_file, {"FABRIC_CAPACITY_ID": listed["id"]})       # what the workspace step asks for
        ctx.cfg["FABRIC_CAPACITY_ID"] = listed["id"]
    return done(f"capacity {capacity_label(listed)}, made by this deployment", capacity_id=listed["id"], resource_id=found.get("id"))


def act_capacity(ctx) -> None:
    new = new_capacity(ctx)
    ctx.cache.pop("arm_capacity", None)
    if not arm_capacity(ctx):                 # one that exists was started by an apply that did not live to see it finished
        body = {"location": new["region"], "sku": {"name": new["sku"], "tier": "Fabric"},
                "properties": {"administration": {"members": [(account(ctx).get("user") or {}).get("name")]}},
                "tags": {TAG: suffix(ctx), "created-by": "tools/deploy.py"}}
        try:
            ctx.az.run("rest", "--method", "put", "--url", capacity_url(ctx), "--url-parameters", FABRIC_ARM, "--body", json.dumps(body))
        except CloudError as error:
            if "quota" in str(error).lower():
                raise Blocked(f"Azure did not make the capacity: {error}",
                              f"The subscription's quota of Fabric capacity units does not cover an {new['sku']} in "
                              f"{region_name(new['region'])}. Ask for more in the Azure portal: Quotas, Microsoft Fabric, New Quota "
                              f"Request. Or use an existing capacity: {ASK}") from None
            raise
    # Azure answers the request at once and makes the capacity afterwards. Wait for it, within the limit of an operation.
    deadline = ctx.clock() + ctx.options.limits["operation"]
    while True:
        ctx.cache.pop("arm_capacity", None)
        state = ((arm_capacity(ctx) or {}).get("properties") or {}).get("state")
        if state in ("Active", "Failed", "Paused", "Pausing", "Suspended", "Suspending"):
            return                            # the step's own look says which, and what to do
        if ctx.clock() >= deadline:
            raise StillRunning(f"Azure is still making the capacity {new['name']} (state: {state or 'not reported'})")
        ctx.sleep(ctx.options.limits["poll"])


def capacity_kind(sku) -> str:
    sku = str(sku or "").strip().upper()
    if re.fullmatch(r"F\d+", sku):
        return "fabric"
    if re.fullmatch(r"FT\d+", sku) or sku == "TRIAL":
        return "trial"
    if re.fullmatch(r"P\d+", sku):
        return "premium"
    if sku.startswith("PP"):
        return "per-user"
    if re.fullmatch(r"(A|EM)\d+", sku):
        return "embedded"
    return "unknown"


def capacities(ctx) -> list:
    return ctx.remember("capacities", lambda: ctx.fabric.listing("capacities"))


def capacity_label(entry: dict) -> str:
    return f"{entry.get('displayName')} ({entry.get('sku')}, {entry.get('region')})"


def capacity(ctx) -> dict | None:
    """The capacity the settings name, as Fabric lists it for the signed-in person. None when it is not in their list."""
    wanted = ctx.cfg.get("FABRIC_CAPACITY_ID", "").lower()
    return next((entry for entry in capacities(ctx) if wanted and str(entry.get("id", "")).lower() == wanted), None)


def unlisted_capacities(ctx) -> dict:
    """Capacities that workspaces of the signed-in person run on and that Fabric does not list for them: ID -> workspace names."""
    listed = {str(entry.get("id", "")).lower() for entry in capacities(ctx)}
    found: dict = {}
    for workspace in workspaces(ctx):
        on = str(workspace.get("capacityId") or "").lower()
        if on and on not in listed:
            found.setdefault(on, []).append(str(workspace.get("displayName")))
    return found


def some(texts: list, most: int = 4) -> str:
    texts = sorted(texts)
    return ", ".join(texts[:most]) + (f" and {len(texts) - most} more" if len(texts) > most else "")


def capacity_choices(ctx) -> str:
    """What a person needs to choose a capacity: what Fabric lists for them, with what each can hold, and where their workspaces run."""
    rows = ["The runner takes a capacity by itself only when exactly one that can hold the demo is in sight. Name the one to use:",
            "  python3 tools/deploy.py plan --capacity ID",
            "or have one made for this deployment, which costs money for as long as it runs:",
            "  python3 tools/deploy.py plan --new-capacity --capacity-region REGION --approve-capacity-creation",
            "In a terminal, plan also asks. Add --save-profile to keep an existing capacity for the next deployments here.",
            "Capacities Fabric lists for you (those you administer or contribute to):"]
    for entry in capacities(ctx):
        kind = capacity_kind(entry.get("sku"))
        if kind in CANNOT_HOLD:
            verdict = "cannot hold the demo: " + CANNOT_HOLD[kind]
        elif entry.get("state") != "Active":
            verdict = f"is {entry.get('state')}"
        elif kind in CAN_HOLD:
            verdict = "can hold the demo: " + CAN_HOLD[kind]
        else:
            verdict = "a SKU the runner does not know"
        rows.append(f"  {entry.get('id')}  {capacity_label(entry)}  -> {verdict}")
    if not capacities(ctx):
        rows.append("  none")
    elsewhere = unlisted_capacities(ctx)
    if elsewhere:
        rows.append("Capacities that workspaces you can open run on, and that Fabric does not list for you (so their SKU "
                    "cannot be read):")
        rows += [f"  {capacity_id}  used by: {some(users)}" for capacity_id, users in sorted(elsewhere.items())]
    return "\n".join(rows)


def pre_capacity(ctx) -> Probe:
    if creating(ctx):
        return pre_new_capacity(ctx)
    wanted = ctx.cfg.get("FABRIC_CAPACITY_ID", "")
    if not wanted:
        usable = [entry for entry in capacities(ctx)
                  if entry.get("state") == "Active" and capacity_kind(entry.get("sku")) in CAN_HOLD]
        if len(usable) == 1 and not unlisted_capacities(ctx):
            # One candidate and no other in sight: not a choice. It is written down, and shown in the target before any approval.
            names.write_env(ctx.env_file, {"FABRIC_CAPACITY_ID": usable[0]["id"]})
            ctx.cfg["FABRIC_CAPACITY_ID"] = usable[0]["id"]
            return done(f"capacity {capacity_label(usable[0])}: the only one in sight that can hold Fabric items. Its ID is now "
                        f"in FABRIC_CAPACITY_ID", capacity_id=usable[0]["id"])
        return blocked(f"The settings name no capacity, and Fabric lists {len(usable)} for you that can hold the demo"
                       + (", with others in use by your workspaces." if unlisted_capacities(ctx) else "."), capacity_choices(ctx))
    chosen = capacity(ctx)
    if not chosen:
        users = unlisted_capacities(ctx).get(wanted.lower())
        if not users:
            return blocked(f"FABRIC_CAPACITY_ID is {wanted}. Fabric lists no capacity with that ID for you, and no workspace "
                           "you can open runs on it.", capacity_choices(ctx))
        return unverified(f"capacity {wanted} is not in the list Fabric gives you, so its SKU and state cannot be read. "
                          f"Workspaces you can open run on it ({some(users)}). Whether you may put a new workspace on it shows "
                          "when the runner creates the workspace: that takes the contributor role on the capacity (Fabric "
                          "admin portal, Capacity settings, the capacity, Details, Contributor permissions)",
                          capacity_id=wanted)
    kind = capacity_kind(chosen.get("sku"))
    if kind in CANNOT_HOLD:
        return blocked(f"FABRIC_CAPACITY_ID names {capacity_label(chosen)}: {CANNOT_HOLD[kind]}, so the Eventhouse, the Lakehouse "
                       "and the notebooks cannot be created on it.", capacity_choices(ctx))
    if chosen.get("state") != "Active":
        return blocked(f"Capacity {capacity_label(chosen)} is {chosen.get('state')}.", "Resume it in the Azure portal or the "
                       "Fabric admin portal. The runner does not change a capacity.")
    if kind == "unknown":
        return unverified(f"capacity {capacity_label(chosen)}: the runner does not know this SKU. Whether it holds Fabric items "
                          "shows when the workspace is created", capacity_id=chosen["id"])
    return done(f"capacity {capacity_label(chosen)}: {CAN_HOLD[kind]}", capacity_id=chosen["id"])


TENANT_SETTINGS = {
    "phase1": ["Service principals can use Fabric APIs (the two identities of the edge are added to the workspace and send to it)",
               "Users can create Fabric items, and you may create workspaces"],
    "phase3": ["Users can create and share Data agent item types, and the Copilot settings the data agent needs",
               "Enable Operations Agents (Preview)",
               "The ontology and graph settings, if your tenant shows them (Phase 3 found one tenant without them)"],
    "phase4": ["Fabric Apps"],
}


def tenant_settings(phase: str):
    def probe(ctx) -> Probe:
        return confirmation(ctx, f"{phase}.tenant_settings", "tenant settings")

    def manual(ctx) -> str:
        rows = "\n".join(f"  - {row}" for row in TENANT_SETTINGS[phase])
        return ("A Fabric administrator checks these tenant settings in the admin portal. The runner cannot read them and never "
                f"changes them:\n{rows}\nThen: the apply line the plan ends with, and --confirm {phase}.tenant_settings added to it")
    return probe, manual


# --------------------------------------------------------------------------------------------- Phase 1
def p1_resource_group(ctx) -> Probe:
    group_name = ctx.cfg["RESOURCE_GROUP"]
    group = ctx.az.maybe("group", "show", "--name", group_name)
    if group is None:
        return todo(f"{group_name} does not exist yet")
    ours = (group.get("tags") or {}).get(TAG) == suffix(ctx)
    known = ctx.target("resource_group_id")
    if not ours or (known and known.lower() != group["id"].lower()):
        return blocked(f"A resource group named {group_name} exists, and this deployment did not make it. The runner works in "
                       "a resource group of its own only.", "Start a deployment with other names: python3 tools/deploy.py plan --new")
    if not known:
        ctx.set_target(resource_group_id=group["id"])    # made by an apply that did not live to write it down; the tag says so
    strangers = []
    for resource in ctx.az.json("resource", "list", "--resource-group", group_name, "--query", "[].{id:id, type:type}") or []:
        provider = resource.get("type", "").split("/")[0].lower()
        if provider not in RG_PROVIDERS and not ctx.acknowledged(resource["id"]):
            strangers.append(f"{resource['type']}  {resource['id']}")
    if strangers:
        return blocked(f"{group_name} holds resources of a kind this demo does not create:\n  " + "\n  ".join(strangers),
                       "Move or remove them. If one belongs here after all, name it: apply ... --acknowledge <its resource ID>")
    return done(f"{group_name} in {group.get('location')}, made by this deployment", id=group["id"])


def act_resource_group(ctx) -> None:
    ctx.az.run("group", "create", "--name", ctx.cfg["RESOURCE_GROUP"], "--location", ctx.cfg["LOCATION"],
               "--tags", f"{TAG}={suffix(ctx)}", "created-by=tools/deploy.py")
    group = ctx.az.json("group", "show", "--name", ctx.cfg["RESOURCE_GROUP"])
    ctx.set_target(resource_group_id=group["id"])


def vm(ctx) -> dict | None:
    return ctx.remember("vm", lambda: ctx.az.maybe("vm", "show", "--show-details", "--resource-group", ctx.cfg["RESOURCE_GROUP"], "--name", ctx.cfg["VM_NAME"]))


def p1_edge_vm(ctx) -> Probe:
    if not ctx.target("resource_group_id"):
        return after("p1.resource_group")
    machine = vm(ctx)
    if not machine:
        return todo()
    if machine.get("provisioningState") != "Succeeded":
        return todo(f"the VM is {machine.get('provisioningState')}")
    return done(f"{machine['name']} ({(machine.get('hardwareProfile') or {}).get('vmSize')})", id=machine["id"])


def act_edge_vm(ctx) -> None:
    # What preflight or plan read about the sizes, from the checkpoint when that was within the last hours. Either way
    # the script does not ask `az vm list-skus`: it gets the sizes that were read, or the word to try each size and let
    # Azure refuse.
    sizes = PRE_REGION(ctx).evidence
    env = {"DEPLOY_RUNNER": "1"}
    if sizes.get("sizes_read") and sizes.get("sizes"):
        env["VM_SIZE_OFFERED"] = " ".join(sizes["sizes"])
    else:
        env["VM_SIZE_SKIP_CHECK"] = "1"
    script(ctx, "infra/01-create-edge-vm.sh", env=env)


VM_ROLES = ("Kubernetes Cluster - Azure Arc Onboarding", "Reader")


def vm_roles_missing(ctx) -> tuple[str, str, list]:
    """The VM identity's object ID, the demo's resource group, and which of the two roles it does not hold there yet."""
    principal = ((vm(ctx) or {}).get("identity") or {}).get("principalId", "")
    scope = ctx.target("resource_group_id", "")
    held = {role for role, at in role_assignments(ctx, scope, f"principalId eq '{principal}'") if covers(at, scope)}
    return principal, scope, [role for role in VM_ROLES if role not in held]


def p1_vm_roles(ctx) -> Probe:
    if not vm(ctx):
        return after("p1.edge_vm")
    missing = vm_roles_missing(ctx)[2]
    if not missing:
        return done("the VM's identity holds Arc onboarding and Reader on the resource group")
    return todo(f"{len(VM_ROLES) - len(missing)} of {len(VM_ROLES)} role assignments are there")


def act_vm_roles(ctx) -> None:
    principal, scope, missing = vm_roles_missing(ctx)
    for role in missing:
        # By ID and with the kind of principal: the CLI then neither looks the role up nor asks Microsoft Graph.
        ctx.az.run("role", "assignment", "create", "--assignee-object-id", principal, "--assignee-principal-type",
                   "ServicePrincipal", "--role", ROLE_IDS[role], "--scope", scope)


def cluster(ctx) -> dict | None:
    # Read as a plain resource: `az connectedk8s` is an extension the scripts use on the VM, and a workstation need not have it.
    return ctx.remember("cluster", lambda: ctx.az.maybe(
        "resource", "show", "--resource-group", ctx.cfg["RESOURCE_GROUP"], "--name", ctx.cfg["CLUSTER_NAME"],
        "--resource-type", "Microsoft.Kubernetes/connectedClusters"))


def p1_arc(ctx) -> Probe:
    if not vm(ctx):
        return after("p1.edge_vm")
    found = cluster(ctx)
    if not found:
        return todo()
    connected = (found.get("properties") or {}).get("connectivityStatus")
    if connected != "Connected":
        if (vm(ctx) or {}).get("powerState", "VM running") != "VM running":
            return blocked(f"The cluster is {connected}: the VM is stopped.", "bash infra/vm.sh start")
        return todo(f"the cluster is {connected}")
    return done(f"{found['name']} is connected to Azure Arc", id=found["id"])


def instance(ctx) -> dict | None:
    return ctx.remember("instance", lambda: ctx.az.maybe("iot", "ops", "show", "--resource-group", ctx.cfg["RESOURCE_GROUP"],
                                                         "--name", ctx.cfg["AIO_INSTANCE_NAME"]))


def p1_iot_operations(ctx) -> Probe:
    if not cluster(ctx):
        return after("p1.arc")
    found = instance(ctx)
    state = ((found or {}).get("properties") or {}).get("provisioningState")
    if state != "Succeeded":
        return todo(f"the instance is {state}" if found else "")
    return done(f"Azure IoT Operations instance {found['name']}", id=found["id"])


def edge_identities(ctx) -> dict:
    """The two identities of the edge that need the workspace: object ID by name."""
    def read():
        found = {}
        machine, arc = vm(ctx), cluster(ctx)
        if machine and (machine.get("identity") or {}).get("principalId"):
            found[machine["name"]] = machine["identity"]["principalId"]
        if arc:
            url = f"https://management.azure.com{arc['id']}/providers/Microsoft.KubernetesConfiguration/extensions?api-version=2023-05-01"
            for extension in (ctx.az.json("rest", "--method", "get", "--url", url) or {}).get("value", []):
                if (extension.get("properties") or {}).get("extensionType") == "microsoft.iotoperations":
                    principal = (extension.get("identity") or {}).get("principalId")
                    if principal:
                        found[extension["name"]] = principal
        return found
    return ctx.remember("edge_identities", read)


def chosen_workspace(ctx) -> Probe | None:
    """An existing workspace the operator chose, by its ID. None: it is fit to be taken, or it is this deployment's already."""
    chosen, known, workspace_name = ctx.cfg["FABRIC_WORKSPACE_ID"], workspace_id(ctx), ctx.cfg["FABRIC_WORKSPACE_NAME"]
    again = f"Choose again: {ASK}"
    found = next((w for w in workspaces(ctx) if str(w.get("id", "")).lower() == chosen.lower()), None)
    if known and known.lower() != chosen.lower():
        return blocked(f"This deployment works in workspace {known}; the settings now name {chosen}.",
                       "A deployment stays in its workspace. Put FABRIC_WORKSPACE_ID back, or start another deployment.")
    if not found:
        return blocked(f"The workspace you chose ({chosen}) is not among the workspaces you can open.", again)
    if found.get("displayName") != workspace_name:
        return blocked(f"The workspace you chose is now named {found.get('displayName')}; the settings say {workspace_name}. The "
                       "scripts and the app find it by name.", f"Rename it back, or choose again: {ASK}")
    if known:
        return None
    wanted = ctx.cfg.get("FABRIC_CAPACITY_ID", "")
    if creating(ctx) or (found.get("capacityId") or "").lower() != wanted.lower():
        return blocked(f"The workspace you chose, {workspace_name}, is on capacity {found.get('capacityId') or 'none'}; the "
                       f"settings name {new_capacity_label(ctx) + ', to be made' if creating(ctx) else wanted or 'none'}. A "
                       "workspace stays on its capacity: the runner moves none.", again)
    there = ctx.remember("chosen_items", lambda: ctx.fabric.listing(f"workspaces/{chosen}/items"))
    if there:
        return blocked(f"The workspace you chose, {workspace_name}, holds {len(there)} items "
                       f"({some([str(entry.get('displayName')) for entry in there])}). The runner starts only in a workspace "
                       "that is empty, so that everything in it is the demo's.", again)
    return todo(f"the workspace you chose, {workspace_name}, is empty; apply takes it into this deployment")


def p1_workspace(ctx) -> Probe:
    workspace_name, known = ctx.cfg["FABRIC_WORKSPACE_NAME"], workspace_id(ctx)
    marker = f"deployment {suffix(ctx)}"
    same_name = [w for w in workspaces(ctx) if w.get("displayName") == workspace_name]
    if ctx.cfg.get("FABRIC_WORKSPACE_ID"):
        verdict = chosen_workspace(ctx)
        if verdict:
            return verdict
    elif not known:
        if not same_name:
            return todo(f"{workspace_name} does not exist yet")
        if len(same_name) == 1 and marker in (same_name[0].get("description") or ""):
            ctx.set_target(workspace_id=same_name[0]["id"])     # made by an apply that did not live to write it down
            known = same_name[0]["id"]
        else:
            return blocked(f"A workspace named {workspace_name} exists, and this deployment did not make it. The runner works "
                           "in a workspace of its own only.", "Start a deployment with other names: python3 tools/deploy.py plan --new")
    mine = next((w for w in workspaces(ctx) if w.get("id") == known), None)
    if not mine:
        return todo(f"the workspace this deployment made ({known}) is gone")
    wanted = ctx.cfg.get("FABRIC_CAPACITY_ID", "")
    if mine.get("capacityId") and wanted and mine["capacityId"].lower() != wanted.lower():
        return blocked(f"The workspace is on capacity {mine.get('capacityId')}, not on the one in the settings ({wanted}).",
                       "Someone moved it. Move it back, or set FABRIC_CAPACITY_ID to where it is now and plan again.")
    strangers = [f"{entry.get('type')} {entry.get('displayName')}  ({entry.get('id')})" for entry in items(ctx)
                 if not expected_item(ctx, entry) and not ctx.acknowledged(entry.get("id"))]
    if strangers:
        return blocked(f"{workspace_name} holds items this demo does not create:\n  " + "\n  ".join(strangers),
                       "Move or delete them. If one belongs here after all, name it: apply ... --acknowledge <its item ID>")
    return done(f"{workspace_name} ({known})" + (", the workspace you chose" if ctx.cfg.get("FABRIC_WORKSPACE_ID") else ""), id=known)


def expected_item(ctx, entry: dict) -> bool:
    kind, display = entry.get("type", ""), entry.get("displayName", "")
    eventhouse, lakehouse = name(ctx, "EVENTHOUSE_NAME"), name(ctx, "FABRIC_LAKEHOUSE_NAME")
    if kind == "Notebook":
        return display in {n for group in NOTEBOOKS.values() for n in group} | set(STORY)
    exact = {"Eventhouse": {eventhouse}, "KQLDatabase": {eventhouse}, "Lakehouse": {lakehouse}, "SQLEndpoint": {lakehouse},
             "Eventstream": {name(ctx, "EVENTSTREAM_NAME"), name(ctx, "COMMAND_EVENTSTREAM_NAME")},
             "SemanticModel": {lakehouse, MODEL}, "Report": {REPORT}, "DataAgent": {DATA_AGENT}, "OperationsAgent": {OPERATIONS_AGENT}}
    # An ontology keeps a Lakehouse of its own, which Fabric makes with it and names after it: seen on 26 November 2026 as
    # WindFarmOntology_lh_ and 32 hexadecimal digits, with its SQL endpoint. The runner made neither and both are the demo's.
    if kind in ("Lakehouse", "SQLEndpoint", "SemanticModel") and re.fullmatch(rf"{re.escape(ONTOLOGY)}_lh_[0-9a-f]{{32}}", display):
        return True
    if kind in exact:
        return display in exact[kind]
    if kind == "KQLQueryset":
        return display.startswith(eventhouse)
    # The ontology brings items of its own kinds with it, and the app's item type is not written down anywhere.
    return display.startswith(ONTOLOGY) or display == name(ctx, "APP_NAME")


def act_workspace(ctx) -> None:
    chosen = ctx.cfg.get("FABRIC_WORKSPACE_ID")
    if chosen:
        # Nothing is made: the empty workspace the operator chose becomes this deployment's, by its ID in the checkpoint.
        ctx.set_target(workspace_id=chosen, workspace_chosen=True)
        return
    body = {"displayName": ctx.cfg["FABRIC_WORKSPACE_NAME"], "capacityId": ctx.cfg["FABRIC_CAPACITY_ID"],
            "description": f"Wind farm digital twin demo, deployment {suffix(ctx)}. Made by tools/deploy.py."}
    try:
        made = operation(ctx, "workspace", lambda: ctx.fabric.call("POST", "workspaces", body))
    except CloudError as error:
        if error.status in (401, 403) or "capacity" in f"{error} {error.code}".lower():
            raise Blocked(f"Fabric did not let you create the workspace on capacity {ctx.cfg['FABRIC_CAPACITY_ID']}: {error}",
                          "Creating a workspace needs two things the runner does not give itself: the tenant's permission to "
                          "create workspaces, and the contributor role on the capacity. An administrator of the capacity sets "
                          "that in the Fabric admin portal: Capacity settings, the kind of capacity, the capacity, Details, "
                          "Contributor permissions. Ask for it, or put another capacity into FABRIC_CAPACITY_ID and plan again "
                          "(python3 tools/deploy.py preflight lists them). Then run apply again.") from None
        raise
    if made and made.get("id"):
        ctx.set_target(workspace_id=made["id"])


def p1_eventhouse(ctx) -> Probe:
    if not workspace_id(ctx):
        return after("p1.workspace")
    house, target = item(ctx, "Eventhouse", name(ctx, "EVENTHOUSE_NAME")), kql_database(ctx)
    if house and target:
        return done(f"Eventhouse and KQL database {house['displayName']}", eventhouse_id=house["id"])
    return todo("the Eventhouse is there, its KQL database not yet" if house else "")


def act_eventhouse(ctx) -> None:
    ws, display = workspace_id(ctx), name(ctx, "EVENTHOUSE_NAME")
    house = item(ctx, "Eventhouse", display)
    if not house:
        house = operation(ctx, "eventhouse", lambda: ctx.fabric.call("POST", f"workspaces/{ws}/eventhouses", {"displayName": display}))
        ctx.cache.clear()
        house = house if (house or {}).get("id") else need_item(ctx, "Eventhouse", display)
    # Fabric gives a new Eventhouse a database of its name. Wait for that one before making another.
    for _ in range(12):
        if item(ctx, "KQLDatabase", display):
            return
        ctx.sleep(ctx.options.limits["poll"])
        ctx.cache.clear()
    operation(ctx, "kqldatabase", lambda: ctx.fabric.call("POST", f"workspaces/{ws}/kqlDatabases", {
        "displayName": display, "creationPayload": {"databaseType": "ReadWrite", "parentEventhouseItemId": house["id"]}}))


def p1_kql_schema(ctx) -> Probe:
    if not kql_database(ctx):
        return after("p1.eventhouse")
    tables = {row.get("TableName") for row in kql(ctx, ".show tables | project TableName")}
    missing = [table for table in ALL_TABLES if table not in tables]
    if missing:
        return todo("missing tables: " + ", ".join(missing))
    mappings = {row.get("Name") for row in kql(ctx, ".show table RawEvents ingestion json mappings | project Name")}
    if "RawEvents_mapping" not in mappings:
        return todo("the mapping RawEvents_mapping is missing")
    policy = kql(ctx, ".show table TurbineTelemetry policy update | project Policy")
    if not policy or str(policy[0].get("Policy") or "null") in ("null", "[]", ""):
        return todo("TurbineTelemetry has no update policy yet")
    return done("seven tables, the mapping RawEvents_mapping and the update policies")


def p1_lakehouse(ctx) -> Probe:
    if not workspace_id(ctx):
        return after("p1.workspace")
    found = item(ctx, "Lakehouse", name(ctx, "FABRIC_LAKEHOUSE_NAME"))
    return done(f"Lakehouse {found['displayName']}", lakehouse_id=found["id"]) if found else todo()


def act_lakehouse(ctx) -> None:
    operation(ctx, "lakehouse", lambda: ctx.fabric.call("POST", f"workspaces/{workspace_id(ctx)}/lakehouses",
                                                         {"displayName": name(ctx, "FABRIC_LAKEHOUSE_NAME")}))


def p1_onelake(ctx) -> Probe:
    if not kql_database(ctx):
        return after("p1.eventhouse")
    # The command takes one table (Learn, ".show table policy mirroring command"), and on 26 November 2026 the six of
    # them, asked one after the other, took 187 seconds in every plan and twice in every apply. They are asked together.
    uri, database = kql_database(ctx)
    with ThreadPoolExecutor(max_workers=len(LIVE_TABLES)) as together:
        answers = list(together.map(
            lambda table: ctx.kusto.rows(uri, database, f".show table {table} policy mirroring | project Policy", mgmt=True), LIVE_TABLES))
    off = []
    for table, rows in zip(LIVE_TABLES, answers):
        try:
            enabled = bool(rows) and json.loads(rows[0].get("Policy") or "null").get("IsEnabled") is True
        except (AttributeError, ValueError):
            enabled = False
        if not enabled:
            off.append(table)
    return todo("OneLake availability is off for: " + ", ".join(off)) if off else done("OneLake availability is on for the six typed tables")


def p1_shortcuts(ctx) -> Probe:
    lakehouse, database = item(ctx, "Lakehouse", name(ctx, "FABRIC_LAKEHOUSE_NAME")), item(ctx, "KQLDatabase", name(ctx, "EVENTHOUSE_NAME"))
    if not lakehouse or not database:
        return after("p1.lakehouse")
    there = ctx.remember("shortcuts", lambda: ctx.fabric.listing(f"workspaces/{workspace_id(ctx)}/items/{lakehouse['id']}/shortcuts"))
    wrong, missing = [], []
    for table in LIVE_TABLES:
        shortcut = next((s for s in there if s.get("name") == table and s.get("path", "").strip("/") == "Tables"), None)
        target = ((shortcut or {}).get("target") or {}).get("oneLake") or {}
        if not shortcut:
            missing.append(table)
        elif target.get("itemId") != database["id"] or target.get("path", "").strip("/") != f"Tables/{table}":
            wrong.append(table)
    if wrong:
        return blocked("These shortcuts exist and point somewhere else: " + ", ".join(wrong),
                       "Delete them in the Lakehouse (Tables, the menu of the shortcut, Delete). The runner replaces nothing.")
    return todo(f"{len(missing)} of 6 shortcuts are missing") if missing else done("six shortcuts to the typed tables of the Eventhouse")


def act_shortcuts(ctx) -> None:
    ws = workspace_id(ctx)
    lakehouse, database = need_item(ctx, "Lakehouse", name(ctx, "FABRIC_LAKEHOUSE_NAME")), need_item(ctx, "KQLDatabase", name(ctx, "EVENTHOUSE_NAME"))
    there = {s.get("name") for s in ctx.fabric.listing(f"workspaces/{ws}/items/{lakehouse['id']}/shortcuts")}
    for table in LIVE_TABLES:
        if table not in there:
            ctx.fabric.call("POST", f"workspaces/{ws}/items/{lakehouse['id']}/shortcuts", {
                "path": "Tables", "name": table,
                "target": {"oneLake": {"workspaceId": ws, "itemId": database["id"], "path": f"Tables/{table}"}}})


SOURCE, DESTINATION = "aio-edge", "eventhouse-raw"
WIZARD = """In the Fabric portal, as in step 6.7 of docs/01-deployment-guide-phase1.md:
1. Open the eventstream {eventstream}, select Edit, and remove the destination {destination} if it shows a warning or an error.
2. Add destination, Eventhouse, Direct ingestion; name {destination}; Eventhouse {eventhouse}. Save, then Publish.
3. In the live view select Configure on that destination. In the Get data wizard choose the existing table RawEvents.
4. On Inspect the data set the format to JSON, open the mapping list above the preview, turn on Use existing mapping
   and select RawEvents_mapping. The preview must show seven columns, none ending in _1. Finish."""


def eventstream_topology(ctx) -> dict | None:
    stream = item(ctx, "Eventstream", name(ctx, "EVENTSTREAM_NAME"))
    if not stream:
        return None
    return ctx.remember("topology", lambda: ctx.fabric.get(f"workspaces/{workspace_id(ctx)}/eventstreams/{stream['id']}/topology"))


def p1_eventstream(ctx) -> Probe:
    if not kql_database(ctx):
        return after("p1.eventhouse")
    topology = eventstream_topology(ctx)
    if topology is None:
        return todo()
    source = next((s for s in topology.get("sources", []) if s.get("name") == SOURCE and s.get("type") == "CustomEndpoint"), None)
    destination = next((d for d in topology.get("destinations", []) if d.get("type") == "Eventhouse"), None)
    words = dict(eventstream=name(ctx, "EVENTSTREAM_NAME"), destination=DESTINATION, eventhouse=name(ctx, "EVENTHOUSE_NAME"))
    if not source:
        return blocked(f"The eventstream {words['eventstream']} exists without the custom endpoint source {SOURCE}. The runner "
                       "did not make it this way and does not rebuild it.",
                       f"Delete the eventstream {words['eventstream']} in the workspace and run apply again, or add the source by "
                       "hand as in step 6.4 of docs/01-deployment-guide-phase1.md.")
    if not destination:
        return blocked("The eventstream has no Eventhouse destination.", WIZARD.format(**words))
    if destination.get("status") in ("Warning", "Failed"):
        database = item(ctx, "KQLDatabase", name(ctx, "EVENTHOUSE_NAME")) or {}
        if (destination.get("properties") or {}).get("itemId") != database.get("id"):
            # The eventstream the runner made on 26 November 2026, from Microsoft's article word for word: the destination
            # named the Eventhouse, and Fabric answered "is not a database artifact". The runner's own mistake is the
            # runner's to put right: the definition is written again with the KQL database in that place.
            return todo("the destination names the Eventhouse where Fabric wants the KQL database: the eventstream's "
                        "definition will be written again")
        # Microsoft's page: a property set that does not fit the mode is accepted, ingests nothing and reports no error.
        said = destination.get("error") or {}
        why = " ".join(str(said.get(key) or "") for key in ("errorCode", "errorMessage", "message")).strip() if isinstance(said, dict) else str(said)
        return blocked(f"The Eventhouse destination of the eventstream is in the state {destination['status']}: it ingests "
                       f"nothing.{' Fabric says: ' + why if why else ' Fabric gives no reason in the topology.'}",
                       WIZARD.format(**words))
    return done(f"eventstream {words['eventstream']}: custom endpoint {SOURCE}, direct ingestion into RawEvents "
                f"(destination {destination.get('status', 'state not reported')})", source_id=source.get("id"))


def act_eventstream(ctx) -> None:
    ws, display = workspace_id(ctx), name(ctx, "EVENTSTREAM_NAME")
    database = need_item(ctx, "KQLDatabase", name(ctx, "EVENTHOUSE_NAME"))
    stream = f"{display}-stream"
    # The destination is the one of Microsoft's article "Create an Eventstream with an Eventhouse DirectIngestion
    # destination by using APIs": a table, a connection name of at most 40 characters, a mapping that exists, and an item
    # ID. The article takes the Eventhouse's ID for that. Fabric refused it on 26 November 2026: "Artifact with id ... is
    # not a database artifact. It is of type 'KustoEventHouse'". So it is the ID of the KQL database. The source is a
    # custom endpoint, whose properties are empty.
    definition = {
        "sources": [{"name": SOURCE, "type": "CustomEndpoint", "properties": {}}],
        "destinations": [{"name": DESTINATION, "type": "Eventhouse",
                          "properties": {"dataIngestionMode": "DirectIngestion", "workspaceId": ws, "itemId": database["id"],
                                         "tableName": "RawEvents", "connectionName": f"es-windfarm-raw-{suffix(ctx)}",
                                         "mappingRuleName": "RawEvents_mapping"},
                          "inputNodes": [{"name": stream}]}],
        "streams": [{"name": stream, "type": "DefaultStream", "properties": {}, "inputNodes": [{"name": SOURCE}]}],
        "operators": [], "compatibilityLevel": "1.1"}
    payload = base64.b64encode(json.dumps(definition).encode("utf-8")).decode("ascii")
    parts = {"definition": {"parts": [{"path": "eventstream.json", "payload": payload, "payloadType": "InlineBase64"}]}}
    existing = item(ctx, "Eventstream", display)
    if existing:
        # Only the eventstream of this deployment's own workspace, and only when the probe found the destination naming
        # the wrong item. Update Eventstream Definition replaces the whole definition; nothing is deleted by the runner.
        ctx.say("      writing the eventstream's definition again, with the KQL database as the destination")
        operation(ctx, "eventstream-definition", lambda: ctx.fabric.call(
            "POST", f"workspaces/{ws}/eventstreams/{existing['id']}/updateDefinition", parts))
    else:
        operation(ctx, "eventstream", lambda: ctx.fabric.call("POST", f"workspaces/{ws}/eventstreams", {
            "displayName": display, "description": "Telemetry from the edge of the wind farm demo.", **parts}))
    # Fabric builds the destination's connection after it has taken the definition. Until it has, the topology shows the
    # state of before, which for a definition written again is the old failure.
    deadline = ctx.clock() + 120
    while ctx.clock() < deadline:
        ctx.cache.clear()
        topology = eventstream_topology(ctx) or {}
        states = [d.get("status") for d in topology.get("destinations", []) if d.get("type") == "Eventhouse"]
        if states and states[0] not in ("Failed", "Warning", "Creating", None):
            break
        ctx.sleep(ctx.options.limits["poll"])


def edge_connection(ctx) -> tuple[str, str] | None:
    """Where the edge sends to: the bootstrap server and the topic. The answer of Fabric also holds keys; only the
    two names are taken from it, and the answer itself is neither kept nor shown."""
    topology = eventstream_topology(ctx)
    source = next((s for s in (topology or {}).get("sources", []) if s.get("name") == SOURCE), None)
    if not source or not source.get("id"):
        return None
    stream = need_item(ctx, "Eventstream", name(ctx, "EVENTSTREAM_NAME"))
    answer = ctx.fabric.get(f"workspaces/{workspace_id(ctx)}/eventstreams/{stream['id']}/sources/{source['id']}/connection") or {}
    for secret in (answer.get("accessKeys") or {}).values():
        ctx.redact.learn(secret)
    namespace, topic = answer.get("fullyQualifiedNamespace"), answer.get("eventHubName")
    return (f"{namespace}:9093", topic) if namespace and topic else None


def p1_edge_connection(ctx) -> Probe:
    if eventstream_topology(ctx) is None:
        return after("p1.eventstream")
    live = ctx.remember("edge_connection", lambda: edge_connection(ctx))
    if not live:
        return todo("Fabric does not give the connection of the source yet")
    if (ctx.cfg.get("EVENTSTREAM_BOOTSTRAP_SERVER"), ctx.cfg.get("EVENTSTREAM_TOPIC")) == live:
        return done(f"the settings name the eventstream's endpoint ({live[1]})")
    if ctx.cfg.get("EVENTSTREAM_TOPIC"):
        return blocked(f"The settings name the topic {ctx.cfg['EVENTSTREAM_TOPIC']}; the eventstream's is {live[1]}.",
                       f"Empty EVENTSTREAM_BOOTSTRAP_SERVER and EVENTSTREAM_TOPIC in {ctx.env_label} if the eventstream was "
                       "made anew; the runner fills them in.")
    return todo()


def act_edge_connection(ctx) -> None:
    server, topic = edge_connection(ctx)
    names.write_env(ctx.env_file, {"EVENTSTREAM_BOOTSTRAP_SERVER": server, "EVENTSTREAM_TOPIC": topic})
    ctx.cfg.update(EVENTSTREAM_BOOTSTRAP_SERVER=server, EVENTSTREAM_TOPIC=topic)


def p1_workspace_access(ctx) -> Probe:
    if not workspace_id(ctx) or not instance(ctx):
        return after("p1.iot_operations and p1.workspace")
    wanted = edge_identities(ctx)
    if len(wanted) < 2:
        return todo("the identity of the Azure IoT Operations extension is not readable yet")
    have = {(entry.get("principal") or {}).get("id"): entry.get("role") for entry in
            ctx.remember("access", lambda: ctx.fabric.listing(f"workspaces/{workspace_id(ctx)}/roleAssignments"))}
    missing = [label for label, principal in wanted.items() if have.get(principal) not in ("Contributor", "Member", "Admin")]
    return todo("no access yet: " + ", ".join(missing)) if missing else done("both identities of the edge are Contributor in the workspace")


def act_workspace_access(ctx) -> None:
    ws = workspace_id(ctx)
    have = {(entry.get("principal") or {}).get("id") for entry in ctx.fabric.listing(f"workspaces/{ws}/roleAssignments")}
    for label, principal in edge_identities(ctx).items():
        if principal not in have:
            try:
                ctx.fabric.call("POST", f"workspaces/{ws}/roleAssignments",
                                {"principal": {"id": principal, "type": "ServicePrincipal"}, "role": "Contributor"})
            except CloudError as error:
                raise Blocked(f"Fabric did not add {label} to the workspace: {error}",
                              "If Fabric says the principal is not found, the identity is minutes old: run apply again shortly. "
                              "If it refuses service principals, the tenant setting 'Service principals can use Fabric APIs' is "
                              "off for them: that is a Fabric administrator's to change.") from None


def data_flow(ctx) -> dict | None:
    return ctx.remember("dataflow", lambda: ctx.az.maybe(
        "iot", "ops", "dataflow", "show", "--resource-group", ctx.cfg["RESOURCE_GROUP"], "--instance", ctx.cfg["AIO_INSTANCE_NAME"],
        "--profile", "default", "--name", "windfarm-to-fabric"))


def p1_data_flow(ctx) -> Probe:
    if not instance(ctx) or not ctx.cfg.get("EVENTSTREAM_TOPIC"):
        return after("p1.edge_connection")
    flow = data_flow(ctx)
    if not flow:
        return todo()
    operations = (flow.get("properties") or {}).get("operations") or []
    target = next((o.get("destinationSettings", {}).get("dataDestination") for o in operations if o.get("operationType") == "Destination"), None)
    if target != ctx.cfg["EVENTSTREAM_TOPIC"]:
        return blocked(f"The data flow at the edge sends to {target}; the eventstream of this deployment is {ctx.cfg['EVENTSTREAM_TOPIC']}.",
                       "bash infra/06-connect-edge-to-fabric.sh --new-eventstream   (after reading what it prints)")
    return done(f"data flow windfarm-to-fabric sends to {target}")


def freshness(ctx) -> dict:
    """What the Eventhouse holds of the last minutes. Read-only; used by the gate and by status."""
    raw = kql(ctx, "RawEvents | where ingestion_time() > ago(5m) | summarize Rows = count()")
    typed = kql(ctx, "TurbineTelemetry | where Timestamp > ago(5m) | summarize Rows = count(), Turbines = dcount(TurbineId), "
                     "AgeSeconds = toint((now() - max(Timestamp)) / 1s), WithSeq = countif(isnotnull(Seq))")
    first = typed[0] if typed else {}
    return {"raw_rows": (raw[0] if raw else {}).get("Rows", 0) or 0, "rows": first.get("Rows", 0) or 0,
            "turbines": first.get("Turbines", 0) or 0, "age_seconds": first.get("AgeSeconds"), "with_seq": first.get("WithSeq", 0) or 0}


def gate_telemetry(ctx) -> Probe:
    if not data_flow(ctx) or not kql_database(ctx):
        return after("p1.data_flow")
    seen = freshness(ctx)
    words = dict(eventstream=name(ctx, "EVENTSTREAM_NAME"), destination=DESTINATION, eventhouse=name(ctx, "EVENTHOUSE_NAME"))
    if not seen["raw_rows"]:
        return Probe("todo", "No event has reached RawEvents in the last 5 minutes.", action=(
            "Find where the events stop:\n"
            f"1. Open the eventstream {words['eventstream']}. No events in its data preview: the edge is not sending. Check the VM "
            "(bash infra/vm.sh status) and see 'No events in the eventstream' in docs/troubleshooting.md.\n"
            "2. Events in the preview and none in RawEvents: the direct ingestion did not take. Set it up by hand:\n" + WIZARD.format(**words)))
    if not seen["rows"] or not seen["with_seq"]:
        return Probe("todo", f"RawEvents receives events ({seen['raw_rows']} in 5 minutes) and TurbineTelemetry has "
                             f"{seen['rows']} rows, {seen['with_seq']} with a sequence number.", action=(
            "Events arrive and are not expanded as they should be. An empty Seq means a mapping other than RawEvents_mapping is in "
            "use (step 6.7 of the Phase 1 guide, 'Change the mapping before you finish'); see also fabric/kql/91-repair-wizard-columns.kql."))
    if (seen["age_seconds"] or 9999) > 180:
        return todo(f"the newest reading is {seen['age_seconds']} s old")
    return done(f"Eventhouse: {seen['rows']} readings from {seen['turbines']} turbines in the last 5 minutes, the newest "
                f"{seen['age_seconds']} s old", **seen)


def notebook_ids(ctx, group: str) -> dict:
    return {display: (item(ctx, "Notebook", display) or {}).get("id") for display in NOTEBOOKS[group]}


def notebooks_probe(group: str, prerequisite: str):
    def probe(ctx) -> Probe:
        if not item(ctx, "Lakehouse", name(ctx, "FABRIC_LAKEHOUSE_NAME")):
            return after(prerequisite)
        missing = [display for display, found in notebook_ids(ctx, group).items() if not found]
        return todo(f"{len(missing)} of {len(NOTEBOOKS[group])} to import") if missing else done(f"{len(NOTEBOOKS[group])} notebook{'s' if len(NOTEBOOKS[group]) != 1 else ''} imported")
    return probe


def import_notebooks(group: str):
    def act(ctx) -> None:
        ws, lakehouse = workspace_id(ctx), need_item(ctx, "Lakehouse", name(ctx, "FABRIC_LAKEHOUSE_NAME"))
        for display, found in notebook_ids(ctx, group).items():
            if found:
                continue        # a notebook that is there is left as it is, with whatever a person changed in it
            notebook = json.loads((ctx.root / "fabric" / "notebooks" / f"{display}.ipynb").read_text(encoding="utf-8"))
            # The default Lakehouse, as Microsoft's article on the notebook API writes it into the notebook's metadata.
            notebook.setdefault("metadata", {})["dependencies"] = {"lakehouse": {
                "default_lakehouse": lakehouse["id"], "default_lakehouse_name": lakehouse["displayName"],
                "default_lakehouse_workspace_id": ws}}
            payload = base64.b64encode(json.dumps(notebook).encode("utf-8")).decode("ascii")
            operation(ctx, f"import:{display}", lambda: ctx.fabric.call("POST", f"workspaces/{ws}/notebooks", {
                "displayName": display, "definition": {"format": "ipynb", "parts": [
                    {"path": "notebook-content.ipynb", "payload": payload, "payloadType": "InlineBase64"}]}}))
    return act


def ran(ctx, step_id: str, display: str) -> dict | None:
    return (ctx.state.step(step_id).get("evidence") or {}).get(f"job:{display}")


def notebook_probe(step_id: str, display: str, prerequisite: str, force=lambda ctx: False):
    def probe(ctx) -> Probe:
        if not item(ctx, "Notebook", display):
            return after(prerequisite)
        job = ran(ctx, step_id, display)
        if job and not force(ctx):
            return done(f"{display} ran to the end ({job.get('ended') or job.get('id')})")
        return todo()
    return probe


def run_step(display: str, parameters: dict | None = None):
    def act(ctx) -> None:
        run_notebook(ctx, workspace_id(ctx), need_item(ctx, "Notebook", display)["id"], display, parameters)
    return act


def schedules(ctx, display: str) -> list:
    notebook = item(ctx, "Notebook", display)
    if not notebook:
        return []
    return ctx.remember(f"schedules:{display}", lambda: ctx.fabric.listing(
        f"workspaces/{workspace_id(ctx)}/items/{notebook['id']}/jobs/RunNotebook/schedules"))


def scheduled_probe(step_id: str, display: str, prerequisite: str, run_first: bool):
    def probe(ctx) -> Probe:
        if not item(ctx, "Notebook", display):
            return after(prerequisite)
        if run_first and not ran(ctx, step_id, display):
            return todo("not run yet")
        on = [entry for entry in schedules(ctx, display) if entry.get("enabled")]
        if len(on) > 1:
            return blocked(f"{display} has {len(on)} schedules that are switched on.", f"Open {display}, Run, Schedule, and keep one.")
        return done(f"{display} has one schedule ({(on[0].get('configuration') or {}).get('type')})") if on else todo("no schedule yet")
    return probe


def schedule(ctx, kind: str) -> dict:
    """A schedule that starts ten minutes from now and runs for ten years. Microsoft's reference: a start in the past
    triggers a job at once, which would be a second run beside the one this step makes."""
    start = ctx.wall() + 600
    stamp = lambda seconds: time.strftime("%Y-%m-%dT%H:%M:00", time.gmtime(seconds))   # noqa: E731
    base = {"startDateTime": stamp(start), "endDateTime": stamp(start + 3650 * 86400), "localTimeZoneId": "UTC"}
    if kind == "daily":
        return {**base, "type": "Daily", "times": ["05:00"]}
    return {**base, "type": "Cron", "interval": 60}


def schedule_act(display: str, kind: str, run_first: bool):
    def act(ctx) -> None:
        notebook = need_item(ctx, "Notebook", display)
        if run_first and not ran(ctx, ctx.current, display):
            run_notebook(ctx, workspace_id(ctx), notebook["id"], display)
        ctx.cache.clear()
        if not [entry for entry in schedules(ctx, display) if entry.get("enabled")]:
            ctx.fabric.call("POST", f"workspaces/{workspace_id(ctx)}/items/{notebook['id']}/jobs/RunNotebook/schedules",
                            {"enabled": True, "configuration": schedule(ctx, kind)})
    return act


def gate_checks(phase: str) -> list:
    """What the gate notebook looks at: tables that must have rows, and tables whose newest row must be recent."""
    if phase == "phase1":
        return ([{"table": table, "min_rows": 1, "newest": "Timestamp", "within_minutes": 60} for table in ("TurbineTelemetry",)]
                + [{"table": table, "min_rows": 1} for table in LIVE_TABLES[1:] if table != "TurbineStateChanges"]
                + [{"table": table, "min_rows": 1} for table in (
                    "ref_turbines", "ref_components", "ref_alarm_codes", "ref_spare_parts", "ref_technicians", "ref_contracts",
                    "ops_scada_10min", "ops_met_10min", "ops_turbine_events", "ops_alarm_log", "ops_work_orders",
                    "ops_oil_analysis", "ops_curtailments", "ops_market_prices", "ops_power_forecast", "ops_monthly_budget")])
    return [{"table": table, "min_rows": 1} for table in (
        "dim_date", "dim_turbine", "dim_site", "kpi", "fact_scada_10min")]


def gate_lakehouse(phase: str, step_id: str, prerequisite: str):
    def live(ctx) -> Probe:
        if not item(ctx, "Notebook", GATE_NOTEBOOK):
            return after(prerequisite)
        return todo()

    def act(ctx) -> None:
        lakehouse = need_item(ctx, "Lakehouse", name(ctx, "FABRIC_LAKEHOUSE_NAME"))
        checks = json.dumps(gate_checks(phase))
        try:
            run_notebook(ctx, workspace_id(ctx), need_item(ctx, "Notebook", GATE_NOTEBOOK)["id"], GATE_NOTEBOOK,
                         {"checks": {"value": checks, "type": "string"}, "label": {"value": phase, "type": "string"}})
        except CloudError as error:
            raise Blocked(f"The gate notebook did not pass: {error}",
                          f"Open the notebook {GATE_NOTEBOOK} in the workspace; its last run names the table that is empty, "
                          "missing or stale. For a shortcut table, see step 7.3 of the Phase 1 guide: the first write of the "
                          "Eventhouse to OneLake can take 5 to 10 minutes. Then run apply again.") from None
        detail = "the gate notebook read every table"
        try:    # the figures are in a file the notebook writes; the verdict above does not depend on reading it
            raw = ctx.onelake.read(workspace_id(ctx), lakehouse["id"], f"Files/deployment/gate-{phase}.json")
            figures = json.loads(raw) if raw else None
        except Exception:   # noqa: BLE001
            figures = None
        if figures:
            newest = [f"{row['table']} newest {row['age_minutes']} min old" for row in figures.get("tables", []) if row.get("age_minutes") is not None]
            detail = f"{len(figures.get('tables', []))} tables with rows" + (f"; {', '.join(newest)}" if newest else "")
            ctx.state.note(step_id, figures=figures)
        ctx.state.note(step_id, passed=detail)

    def probe(ctx) -> Probe:
        saved = ctx.state.step(step_id)
        if (saved.get("evidence") or {}).get("passed"):
            return done(f"Lakehouse: {saved['evidence']['passed']}")
        return live(ctx)
    return probe, act


def act_kql_schema(ctx) -> None:
    for file in ("fabric/kql/01-tables.kql", "fabric/kql/02-update-policies.kql"):
        run_kql_file(ctx, file)


def history_wanted(ctx) -> bool:
    """History is generated once. Again only when asked, and once for each label the request carries."""
    label = ctx.options.regenerate_history
    return bool(label) and (ctx.state.step("p1.history").get("evidence") or {}).get("regenerated") != label


def act_history(ctx) -> None:
    run_step("02_generate_history")(ctx)
    if ctx.options.regenerate_history:
        ctx.state.note("p1.history", regenerated=ctx.options.regenerate_history)


def _who(ctx) -> str:
    me = account(ctx)
    return f"{me.get('id')}|{(me.get('user') or {}).get('name')}"


# Three checks ask Azure for answers that hold for a day and that can take a minute each to arrive, or not arrive.
PRE_RIGHTS = kept("pre.rights", pre_rights, _who)
PRE_PROVIDERS = kept("pre.providers", pre_providers, lambda ctx: f"{account(ctx).get('id')}|{creating(ctx)}")
# The sizes as a set: putting another size first is not a reason to ask Azure again which of them are offered.
PRE_REGION = kept("pre.region", pre_region, lambda ctx: "|".join((
    str(account(ctx).get("id")), ctx.cfg.get("LOCATION", ""), " ".join(sorted(ctx.cfg.get("VM_SIZE", "").split())),
    str(ctx.state.step("p1.edge_vm").get("status") == "complete"))))


PRE_QUOTA = kept("pre.quota", pre_quota, lambda ctx: "|".join((
    str(account(ctx).get("id")), ctx.cfg.get("LOCATION", ""), (ctx.cfg.get("VM_SIZE", "").split() or [""])[0],
    str(ctx.state.step("p1.edge_vm").get("status") == "complete"))))


def phase1() -> list[Step]:
    settings_probe, settings_manual = tenant_settings("phase1")
    gate_probe, gate_act = gate_lakehouse("phase1", "p1.gate_lakehouse", "p1.notebooks")
    kql_files = ("fabric/kql/01-tables.kql", "fabric/kql/02-update-policies.kql")
    return [
        Step("pre.tools", "preflight", "The tools the scripts need", pre_tools, basis="looks for az, bash and ssh on this computer"),
        Step("pre.signin", "preflight", "Signed in to Azure as a person, on the right subscription", pre_signin, proof="live",
             basis="az account show"),
        Step("pre.extensions", "preflight", "Azure CLI extension on this computer", pre_extensions, basis="az extension list"),
        Step("pre.rights", "preflight", "Your roles on the subscription", PRE_RIGHTS,
             basis="Role Assignments - List For Scope, filter atScope() and assignedTo(); Microsoft Graph, GET /me"),
        Step("pre.providers", "preflight", "Resource providers registered", PRE_PROVIDERS, basis="az provider show",
             manual="Register the providers the plan names."),
        Step("pre.region", "preflight", "Region and VM size", PRE_REGION,
             basis="Resource SKUs - List, with its location filter"),
        Step("pre.quota", "preflight", "vCPU quota for the VM", PRE_QUOTA, basis="az vm list-usage"),
        Step("pre.names", "preflight", "Generated names are free", pre_names, basis="az storage account check-name"),
        Step("pre.custom_locations", "preflight", "Custom Locations object ID", pre_custom_locations, basis="az ad sp show"),
        Step("pre.fabric", "preflight", "The Fabric API answers you", pre_fabric, basis="GET /v1/workspaces"),
        Step("pre.capacity", "preflight", "A capacity that can hold Fabric items, active", pre_capacity,
             basis="GET /v1/capacities and GET /v1/workspaces; SKUs as in the Fabric licenses article. For a capacity to be "
             "made: Fabric Capacities - List Skus and Check Name Availability"),
        Step("phase1.tenant_settings", "preflight", "Tenant settings for Phase 1", settings_probe, manual=settings_manual,
             observable=False, basis="Fabric admin portal; no API for a person who is not an administrator", proof="none"),

        Step("p1.resource_group", "phase1", "Resource group of the demo", p1_resource_group, act_resource_group,
             writes=f"creates the resource group with the tag {TAG}", basis="az group create", proof="offline"),
        Step("p1.capacity", "phase1", "Fabric capacity of the deployment's own, when you chose a new one", p1_capacity, act_capacity,
             needs=("capacity",), wait_seconds=120,
             writes="a Fabric capacity in the demo's resource group, with you as its administrator. It costs money for as long as "
             "it runs; the runner never pauses, resizes or deletes it",
             basis="Fabric Capacities - Create Or Update (Microsoft.Fabric, 2023-11-01) through az rest", proof="offline"),
        Step("p1.edge_vm", "phase1", "Edge VM", p1_edge_vm, act_edge_vm,
             inputs=("infra/01-create-edge-vm.sh",), writes="VM, network, SSH rule for your address, daily shutdown",
             basis="infra/01-create-edge-vm.sh, without its provider registration and role assignments", proof="live"),
        # Waited for: on 25 November 2026 the list of role assignments, read straight after two were made, held neither.
        Step("p1.vm_identity_roles", "phase1", "Roles for the VM's identity, on the resource group only", p1_vm_roles, act_vm_roles,
             needs=("roles",), wait_seconds=120, writes="'Kubernetes Cluster - Azure Arc Onboarding' and 'Reader' for the VM's managed identity, "
             "both on the demo's resource group. The manual guide gives Reader on the subscription; the runner does not",
             basis="az role assignment create, the role by its ID; read with Role Assignments - List For Scope", proof="offline"),
        Step("p1.edge_host", "phase1", "K3s and tools on the VM", lambda ctx: recorded(ctx, "p1.edge_host", "host prepared")
             if vm(ctx) else after("p1.edge_vm"), lambda ctx: on_vm(ctx, "./edge/scripts/02-prepare-host.sh"),
             inputs=("edge/scripts/02-prepare-host.sh", "infra/vm.sh"), observable=False, witness="p1.arc", writes="installs K3s and the Azure CLI on the VM",
             basis="edge/scripts/02-prepare-host.sh", proof="live"),
        Step("p1.arc", "phase1", "Cluster connected to Azure Arc", p1_arc, lambda ctx: on_vm(ctx, "./edge/scripts/03-arc-enable.sh"),
             inputs=("edge/scripts/03-arc-enable.sh",), wait_seconds=300, writes="Arc-enabled cluster with custom locations",
             basis="edge/scripts/03-arc-enable.sh (az connectedk8s connect, enable-features)", proof="live"),
        Step("p1.iot_operations", "phase1", "Azure IoT Operations", p1_iot_operations, act_iot_operations, needs=("roles",),
             inputs=("infra/04-deploy-iot-operations.sh",), wait_seconds=120,
             writes="storage account, schema registry, device registry namespace, the instance. The Azure CLI gives the schema "
             "registry's identity 'Storage Blob Data Contributor' on that storage account",
             basis="infra/04-deploy-iot-operations.sh (az iot ops init, create)", proof="live"),
        Step("p1.simulator", "phase1", "Turbine simulator on the edge", lambda ctx: recorded(ctx, "p1.simulator", "simulator deployed")
             if instance(ctx) else after("p1.iot_operations"), lambda ctx: on_vm(ctx, "./edge/scripts/05-deploy-simulator.sh"),
             inputs=("edge/scripts/05-deploy-simulator.sh", "simulator/Dockerfile"), observable=False, witness="p1.gate_telemetry",
             writes="builds the simulator image on the VM and starts it", basis="edge/scripts/05-deploy-simulator.sh", proof="live"),

        Step("p1.workspace", "phase1", "Fabric workspace of the demo", p1_workspace, act_workspace,
             writes="creates the workspace on the capacity shown; or, when you chose an existing empty workspace, takes that one "
             "into the deployment and creates none", basis="Workspaces - Create Workspace", proof="offline"),
        Step("p1.eventhouse", "phase1", "Eventhouse and KQL database", p1_eventhouse, act_eventhouse, wait_seconds=120,
             writes="Eventhouse WindFarmEH with its database", basis="Eventhouse - Create Eventhouse; KQL Database - Create KQL Database"),
        Step("p1.kql_schema", "phase1", "Tables, mapping and update policies", p1_kql_schema,
             act_kql_schema, inputs=kql_files,
             writes="runs the two database scripts of step 6.2", basis="Kusto REST API, /v1/rest/mgmt, .execute database script"),
        Step("p1.lakehouse", "phase1", "Lakehouse", p1_lakehouse, act_lakehouse, wait_seconds=120, writes="Lakehouse WindFarmLH",
             basis="Lakehouse - Create Lakehouse"),
        Step("p1.onelake_availability", "phase1", "OneLake availability of the typed tables", p1_onelake,
             lambda ctx: run_kql_file(ctx, "fabric/kql/03-onelake-availability.kql"), inputs=("fabric/kql/03-onelake-availability.kql",),
             writes="turns OneLake availability on for six tables", basis="Kusto REST API, .alter-merge table policy mirroring"),
        Step("p1.shortcuts", "phase1", "Shortcuts to the live tables", p1_shortcuts, act_shortcuts, wait_seconds=60,
             writes="six shortcuts under Tables of the Lakehouse", basis="OneLake Shortcuts - Create Shortcut (target: KQL database)"),
        Step("p1.eventstream", "phase1", "Eventstream with direct ingestion into RawEvents", p1_eventstream, act_eventstream,
             wait_seconds=180, writes="eventstream es-windfarm-edge: a custom endpoint, and the Eventhouse as destination with the "
             "mapping RawEvents_mapping", basis="Learn: Create an Eventstream with an Eventhouse DirectIngestion destination by using APIs; Update Eventstream Definition"),
        Step("p1.edge_connection", "phase1", "Where the edge sends to", p1_edge_connection, act_edge_connection,
             writes="writes the bootstrap server and the topic into the settings file. No key is read out of the answer",
             basis="Topology - Get Eventstream Source Connection", proof="live"),
        Step("p1.workspace_access", "phase1", "Workspace access for the two identities of the edge", p1_workspace_access,
             act_workspace_access, needs=("roles",), wait_seconds=60,
             writes="Contributor in the demo's workspace for the Azure IoT Operations extension and for the VM",
             basis="Workspaces - Add Workspace Role Assignment", proof="offline"),
        Step("p1.data_flow", "phase1", "Data flow from the edge to the eventstream", p1_data_flow,
             lambda ctx: script(ctx, "infra/06-connect-edge-to-fabric.sh"),
             inputs=("infra/06-connect-edge-to-fabric.sh", "edge/dataflows/windfarm-to-fabric.template.json"), wait_seconds=120,
             writes="endpoint fabric-eventstream and data flow windfarm-to-fabric", basis="infra/06-connect-edge-to-fabric.sh", proof="live"),
        Step("p1.gate_telemetry", "phase1", "GATE: fresh telemetry in the Eventhouse",
             lambda ctx: keep_done(ctx, "p1.gate_telemetry", gate_telemetry), wait_seconds=600, observable=False,
             manual="Nothing to do before the deployment: the runner measures this after the data flow exists, and says what to "
                    "look at when no telemetry arrives.", basis="Kusto REST API, /v1/rest/query"),

        Step("p1.reference_upload", "phase1", "Reference data uploaded from the edge",
             lambda ctx: recorded(ctx, "p1.reference_upload", "reference files uploaded") if item(ctx, "Lakehouse", name(ctx, "FABRIC_LAKEHOUSE_NAME"))
             else after("p1.lakehouse"), lambda ctx: on_vm(ctx, "./edge/scripts/07-sync-reference-data.sh"),
             inputs=("edge/scripts/07-sync-reference-data.sh",), observable=False, witness="p1.reference_tables", writes="Files/reference and Files/sop of the Lakehouse",
             basis="edge/scripts/07-sync-reference-data.sh", proof="live"),
        Step("p1.notebooks", "phase1", "Notebooks 01 to 04 and the gate notebook imported", notebooks_probe("phase1", "p1.lakehouse"),
             import_notebooks("phase1"), inputs=tuple(f"fabric/notebooks/{n}.ipynb" for n in NOTEBOOKS["phase1"]), wait_seconds=60,
             writes="five notebooks, each with the Lakehouse as its default", basis="Notebook - Create Notebook (definition, ipynb)"),
        Step("p1.reference_tables", "phase1", "Reference tables loaded (notebook 01)",
             notebook_probe("p1.reference_tables", "01_load_reference_data", "p1.notebooks"), run_step("01_load_reference_data"),
             observable=False, writes="13 ref_ tables", basis="Job Scheduler - Run On Demand Item Job (RunNotebook)"),
        Step("p1.history", "phase1", "Two years of operating history (notebook 02)",
             notebook_probe("p1.history", "02_generate_history", "p1.notebooks", force=history_wanted), act_history,
             observable=False, writes="12 ops_ tables. Run once; again only with --regenerate-history LABEL, once for a label",
             basis="Job Scheduler - Run On Demand Item Job (RunNotebook)"),
        Step("p1.forecast", "phase1", "Forecast refreshed and scheduled daily (notebook 03)",
             scheduled_probe("p1.forecast", "03_refresh_forecast", "p1.notebooks", True),
             schedule_act("03_refresh_forecast", "daily", True), observable=False,
             writes="one run of notebook 03 and one daily schedule for it", basis="Job Scheduler - Create Item Schedule"),
        Step("p1.gate_lakehouse", "phase1", "GATE: shortcuts readable, tables populated", gate_probe, gate_act, observable=False,
             inputs=(f"fabric/notebooks/{GATE_NOTEBOOK}.ipynb",), writes="one run of the gate notebook, which reads and writes one small result file",
             basis="Job Scheduler - Run On Demand Item Job; the job's state is the verdict"),
    ]
