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

from . import names
from .cloud import CloudError, operation, run_notebook
from .core import Blocked, Probe, Refused, Step, blocked, done, todo, unverified

TAG = "windfarm-demo-deployment"
PROVIDERS = ("Microsoft.ExtendedLocation", "Microsoft.Kubernetes", "Microsoft.KubernetesConfiguration", "Microsoft.IoTOperations",
             "Microsoft.DeviceRegistry", "Microsoft.SecretSyncController", "Microsoft.Storage", "Microsoft.Insights")
# Regions in which Azure IoT Operations supports Arc clusters (Microsoft Learn, read November 2026).
IOT_OPERATIONS_REGIONS = ("eastus", "eastus2", "westus", "westus2", "westus3", "southcentralus", "westeurope", "northeurope",
                          "germanywestcentral")
CUSTOM_LOCATIONS_APP = "bc313c14-388c-4e7d-a58e-70017303ee3b"
# Resource providers whose resources belong in the demo's resource group: what the scripts create, and what
# Azure and a managed subscription add to it by themselves (just-in-time access, monitoring).
RG_PROVIDERS = ("microsoft.compute", "microsoft.network", "microsoft.devtestlab", "microsoft.kubernetes",
                "microsoft.kubernetesconfiguration", "microsoft.extendedlocation", "microsoft.iotoperations",
                "microsoft.deviceregistry", "microsoft.storage", "microsoft.secretsynccontroller", "microsoft.managedidentity",
                "microsoft.security", "microsoft.insights", "microsoft.eventgrid", "microsoft.alertsmanagement")
LIVE_TABLES = ("TurbineTelemetry", "WeatherObservations", "AlarmEvents", "TurbineStateChanges", "AssetRegistry", "EdgeHeartbeats")
ALL_TABLES = ("RawEvents",) + LIVE_TABLES
GATE_NOTEBOOK = "90_deployment_gate"
NOTEBOOKS = {
    "phase1": ("01_load_reference_data", "02_generate_history", "03_refresh_forecast", "04_question_bank", GATE_NOTEBOOK),
    "phase2": ("05_build_model_tables", "06_build_semantic_model", "07_model_acceptance", "08_build_report"),
    "phase3": ("09_build_data_agent", "10_test_data_agent", "11_build_ontology"),
    "phase5a": ("12_send_edge_command",),
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
             "fabric/kql/04-prepared-views.kql", "fabric/kql/05-agent-readiness.kql")


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
        return unverified(f"{what}: confirmed by {said.get('by', 'the operator')} on {said.get('at')}; the runner cannot read it")
    return todo("waiting for your confirmation")


def script(ctx, *argv: str, env: dict | None = None) -> str:
    return ctx.shell.must(["bash", *argv], env={"ENV_FILE": str(ctx.env_file), **(env or {})})


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
    missing = [namespace for namespace in PROVIDERS
               if ctx.az.maybe("provider", "show", "--namespace", namespace, "--query", "registrationState") != "Registered"]
    if missing:
        return blocked("Not registered in the subscription: " + ", ".join(missing) + ". Registering is a change to the whole "
                       "subscription, so the runner leaves it to you.",
                       "\n".join(f"az provider register --namespace {namespace}" for namespace in missing)
                       + "\nRegistration takes a few minutes; plan shows when it is through.")
    return done(f"{len(PROVIDERS)} resource providers registered")


def pre_rights(ctx) -> Probe:
    me = account(ctx)
    scope = f"/subscriptions/{me['id']}"
    try:
        roles = ctx.az.json("role", "assignment", "list", "--assignee", me["user"]["name"], "--scope", scope,
                            "--include-inherited", "--include-groups", "--query", "[].roleDefinitionName")
    except CloudError as error:
        return unverified(f"could not read your roles ({str(error)[:160]}). Needed: Contributor on the subscription to create "
                          "the resource group, and the right to assign roles inside it")
    roles = set(roles or [])
    creates = roles & {"Owner", "Contributor"}
    assigns = roles & {"Owner", "User Access Administrator", "Role Based Access Control Administrator"}
    if not creates:
        return blocked(f"Your roles on the subscription are: {', '.join(sorted(roles)) or 'none'}. Creating the resource group "
                       "needs Contributor or Owner.", "Ask the owner of the subscription for Contributor, or for a resource "
                       "group you own; the runner does not widen its own access.")
    if not assigns:
        return unverified("you can create resources; you hold no role that assigns roles. The two role steps will stop and "
                          "say what to ask for")
    return done("roles on the subscription: " + ", ".join(sorted(creates | assigns)))


def pre_region(ctx) -> Probe:
    location = ctx.cfg.get("LOCATION", "")
    if location not in IOT_OPERATIONS_REGIONS:
        return blocked(f"LOCATION is {location}. Azure IoT Operations supports Arc clusters in: {', '.join(IOT_OPERATIONS_REGIONS)}.",
                       f"Set LOCATION in {ctx.env_file.name} to one of these.")
    if ctx.state.step("p1.edge_vm").get("status") == "complete":
        return done(f"{location}; the VM exists, so its size is no longer a question")
    try:
        usable, refused = offered_sizes(ctx)
    except CloudError as error:
        # Not a reason to stop: step 1 tries the sizes of VM_SIZE in turn and says so when Azure refuses them all.
        return unverified(f"{location} is supported. Which VM sizes you are offered could not be read ({str(error)[:140]}); "
                          "step 1 tries the sizes of VM_SIZE in turn")
    if not usable:
        return blocked(f"None of the sizes in VM_SIZE is offered to this subscription in {location}: "
                       + "; ".join(f"{size}: {why}" for size, why in refused.items()),
                       f"Put a size with 8 vCPUs and 32 GB that you are offered into VM_SIZE in {ctx.env_file.name}. The Azure "
                       "portal shows them under Virtual machines, Create, Size; sizes of the v6 and v7 families are the usual ones "
                       "in a managed subscription.")
    skipped = f" ({', '.join(refused)} not offered)" if refused else ""
    return done(f"{location}; VM size {usable[0]} is offered{skipped}")


def offered_sizes(ctx) -> tuple[list, dict]:
    """The sizes of VM_SIZE this subscription may create in LOCATION, in their order, and why the others are out.

    One call to the Resource SKUs API with its location filter. `az vm list-skus` asks the same API for every region
    and filters on this computer: on 25 November 2026 that did not answer a workstation within five minutes.
    """
    location, sizes = ctx.cfg["LOCATION"], ctx.cfg.get("VM_SIZE", "").split()
    rows = ctx.az.json(
        "rest", "--method", "get", "--url", f"https://management.azure.com/subscriptions/{account(ctx)['id']}/providers/Microsoft.Compute/skus",
        "--url-parameters", "api-version=2021-07-01", f"$filter=location eq '{location}'",
        "--query", "value[?resourceType=='virtualMachines'].{name: name, refused: restrictions[?type=='Location'] | [0].reasonCode}",
        timeout=120) or []
    known = {row.get("name"): row.get("refused") for row in rows}
    usable = [size for size in sizes if size in known and not known[size]]
    refused = {size: (known[size] if size in known else f"not known in {location}") for size in sizes if size not in usable}
    return usable, refused


def pre_names(ctx) -> Probe:
    account_name = ctx.cfg.get("STORAGE_ACCOUNT_NAME", "")
    if ctx.target("resource_group_id"):
        return done("names in use by this deployment")
    answer = ctx.az.json("storage", "account", "check-name", "--name", account_name) or {}
    if not answer.get("nameAvailable", True):
        return blocked(f"The storage account name {account_name} is taken ({answer.get('reason')}). Storage names are unique "
                       "across Azure.", "python3 tools/deploy.py plan --new-names")
    return done(f"suffix {suffix(ctx)}; {account_name} is free")


def pre_custom_locations(ctx) -> Probe:
    value = ctx.cfg.get("CUSTOM_LOCATIONS_OID", "")
    if re.fullmatch(r"[0-9a-fA-F-]{36}", value) and value.lower() != CUSTOM_LOCATIONS_APP:
        return done("Custom Locations object ID is in the settings")
    found = ctx.az.maybe("ad", "sp", "show", "--id", CUSTOM_LOCATIONS_APP, "--query", "id")
    if not found:
        return blocked("The object ID of the Custom Locations service in your tenant is not in the settings, and the Azure CLI "
                       "could not read it. Reading it needs a person who may read service principals in Microsoft Entra ID.",
                       f"az ad sp show --id {CUSTOM_LOCATIONS_APP} --query id --output tsv\n"
                       f"Put the 36 characters it prints into CUSTOM_LOCATIONS_OID in {ctx.env_file.name}. It is not the ID above, "
                       "which is the same in every tenant.")
    names.write_env(ctx.env_file, {"CUSTOM_LOCATIONS_OID": found})
    ctx.cfg["CUSTOM_LOCATIONS_OID"] = found
    return done("Custom Locations object ID read from Microsoft Entra ID and written to the settings")


def pre_fabric(ctx) -> Probe:
    try:
        ctx.remember("workspaces", lambda: ctx.fabric.listing("workspaces"))
    except CloudError as error:
        return blocked(f"The Fabric API did not answer the signed-in user: {error}", "az login   (in a session that can get a "
                       "token for https://api.fabric.microsoft.com; Azure Cloud Shell often cannot)")
    return done("the Fabric API answers")


def capacity(ctx) -> dict | None:
    wanted = ctx.cfg.get("FABRIC_CAPACITY_ID", "")
    capacities = ctx.remember("capacities", lambda: ctx.fabric.listing("capacities"))
    if wanted:
        return next((entry for entry in capacities if entry.get("id", "").lower() == wanted.lower()), None)
    active = [entry for entry in capacities if entry.get("state") == "Active"]
    return active[0] if len(active) == 1 else None


def pre_capacity(ctx) -> Probe:
    capacities = ctx.remember("capacities", lambda: ctx.fabric.listing("capacities"))
    listing = "\n".join(f"  {c.get('id')}  {c.get('displayName')}  {c.get('sku')}  {c.get('region')}  {c.get('state')}" for c in capacities)
    chosen = capacity(ctx)
    if not chosen:
        if ctx.cfg.get("FABRIC_CAPACITY_ID"):
            return blocked(f"FABRIC_CAPACITY_ID is {ctx.cfg['FABRIC_CAPACITY_ID']}, and you see no capacity with that ID.",
                           "Capacities you can see:\n" + (listing or "  none"))
        return blocked(f"You can see {len(capacities)} capacities, and the settings name none. The runner does not choose a "
                       "capacity and does not create one.",
                       f"Put the ID of the capacity for this demo into FABRIC_CAPACITY_ID in {ctx.env_file.name}:\n" + (listing or "  none"))
    if chosen.get("state") != "Active":
        return blocked(f"Capacity {chosen.get('displayName')} is {chosen.get('state')}.", "Resume it in the Azure portal or the "
                       "Fabric admin portal. The runner does not change a capacity.")
    if not ctx.cfg.get("FABRIC_CAPACITY_ID"):
        names.write_env(ctx.env_file, {"FABRIC_CAPACITY_ID": chosen["id"]})
        ctx.cfg["FABRIC_CAPACITY_ID"] = chosen["id"]
    return done(f"capacity {chosen.get('displayName')} ({chosen.get('sku')}, {chosen.get('region')}), the only active one you see"
                if len([c for c in capacities if c.get("state") == "Active"]) == 1 else
                f"capacity {chosen.get('displayName')} ({chosen.get('sku')}, {chosen.get('region')})", capacity_id=chosen["id"])


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
                f"changes them:\n{rows}\nThen: python3 tools/deploy.py apply --approve <plan> --confirm {phase}.tenant_settings")
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
                       "a resource group of its own only.", "Choose other names: python3 tools/deploy.py plan --new-names")
    if not known:
        ctx.set_target(resource_group_id=group["id"])    # made by an apply that did not live to write it down; the tag says so
    strangers = []
    for resource in ctx.az.json("resource", "list", "--resource-group", group_name, "--query", "[].{id:id, type:type}") or []:
        provider = resource.get("type", "").split("/")[0].lower()
        if provider not in RG_PROVIDERS and resource["id"] not in ctx.state.data["acknowledged"]:
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
    env = {"DEPLOY_RUNNER": "1"}
    try:
        usable, _ = offered_sizes(ctx)
        if usable:
            env["VM_SIZE_OFFERED"] = " ".join(usable)       # the script then skips its own, slow, question to Azure
    except CloudError:
        pass                                                # the script asks for itself, and says that it can take minutes
    script(ctx, "infra/01-create-edge-vm.sh", env=env)


def vm_roles(ctx) -> list[tuple[str, str, str]]:
    """(principal, role, scope) for the VM's identity: both on the demo's resource group, neither on the subscription."""
    principal = ((vm(ctx) or {}).get("identity") or {}).get("principalId", "")
    scope = ctx.target("resource_group_id", "")
    return [(principal, "Kubernetes Cluster - Azure Arc Onboarding", scope), (principal, "Reader", scope)]


def p1_vm_roles(ctx) -> Probe:
    if not vm(ctx):
        return after("p1.edge_vm")
    held = []
    for principal, role, scope in vm_roles(ctx):
        found = ctx.az.json("role", "assignment", "list", "--assignee", principal, "--scope", scope, "--role", role, "--query", "[].id")
        if found:
            held.append(role)
    if len(held) == 2:
        return done("the VM's identity holds Arc onboarding and Reader on the resource group")
    return todo(f"{len(held)} of 2 role assignments are there")


def act_vm_roles(ctx) -> None:
    for principal, role, scope in vm_roles(ctx):
        if not ctx.az.json("role", "assignment", "list", "--assignee", principal, "--scope", scope, "--role", role, "--query", "[].id"):
            ctx.az.run("role", "assignment", "create", "--assignee-object-id", principal, "--assignee-principal-type",
                       "ServicePrincipal", "--role", role, "--scope", scope)


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


def p1_workspace(ctx) -> Probe:
    workspace_name, known = ctx.cfg["FABRIC_WORKSPACE_NAME"], workspace_id(ctx)
    marker = f"deployment {suffix(ctx)}"
    workspaces = ctx.remember("workspaces", lambda: ctx.fabric.listing("workspaces"))
    same_name = [w for w in workspaces if w.get("displayName") == workspace_name]
    if not known:
        if not same_name:
            return todo(f"{workspace_name} does not exist yet")
        if len(same_name) == 1 and marker in (same_name[0].get("description") or ""):
            ctx.set_target(workspace_id=same_name[0]["id"])     # made by an apply that did not live to write it down
            known = same_name[0]["id"]
        else:
            return blocked(f"A workspace named {workspace_name} exists, and this deployment did not make it. The runner works "
                           "in a workspace of its own only.", "Choose other names: python3 tools/deploy.py plan --new-names")
    mine = next((w for w in workspaces if w.get("id") == known), None)
    if not mine:
        return todo(f"the workspace this deployment made ({known}) is gone")
    wanted = ctx.cfg.get("FABRIC_CAPACITY_ID", "")
    if mine.get("capacityId") and wanted and mine["capacityId"].lower() != wanted.lower():
        return blocked(f"The workspace is on capacity {mine.get('capacityId')}, not on the one in the settings ({wanted}).",
                       "Someone moved it. Move it back, or set FABRIC_CAPACITY_ID to where it is now and plan again.")
    strangers = [f"{entry.get('type')} {entry.get('displayName')}  ({entry.get('id')})" for entry in items(ctx)
                 if not expected_item(ctx, entry) and entry.get("id") not in ctx.state.data["acknowledged"]]
    if strangers:
        return blocked(f"{workspace_name} holds items this demo does not create:\n  " + "\n  ".join(strangers),
                       "Move or delete them. If one belongs here after all, name it: apply ... --acknowledge <its item ID>")
    return done(f"{workspace_name} ({known})", id=known)


def expected_item(ctx, entry: dict) -> bool:
    kind, display = entry.get("type", ""), entry.get("displayName", "")
    eventhouse, lakehouse = name(ctx, "EVENTHOUSE_NAME"), name(ctx, "FABRIC_LAKEHOUSE_NAME")
    if kind == "Notebook":
        return display in {n for group in NOTEBOOKS.values() for n in group} | set(STORY)
    exact = {"Eventhouse": {eventhouse}, "KQLDatabase": {eventhouse}, "Lakehouse": {lakehouse}, "SQLEndpoint": {lakehouse},
             "Eventstream": {name(ctx, "EVENTSTREAM_NAME"), name(ctx, "COMMAND_EVENTSTREAM_NAME")},
             "SemanticModel": {lakehouse, MODEL}, "Report": {REPORT}, "DataAgent": {DATA_AGENT}, "OperationsAgent": {OPERATIONS_AGENT}}
    if kind in exact:
        return display in exact[kind]
    if kind == "KQLQueryset":
        return display.startswith(eventhouse)
    # The ontology brings items of its own kinds with it, and the app's item type is not written down anywhere.
    return display.startswith(ONTOLOGY) or display == name(ctx, "APP_NAME")


def act_workspace(ctx) -> None:
    body = {"displayName": ctx.cfg["FABRIC_WORKSPACE_NAME"], "capacityId": ctx.cfg["FABRIC_CAPACITY_ID"],
            "description": f"Wind farm digital twin demo, deployment {suffix(ctx)}. Made by tools/deploy.py."}
    try:
        made = operation(ctx, "workspace", lambda: ctx.fabric.call("POST", "workspaces", body))
    except CloudError as error:
        if error.status in (401, 403):
            raise Blocked(f"Fabric did not let you create the workspace: {error}",
                          "Creating a workspace needs two things the runner does not give itself: the tenant's permission to "
                          "create workspaces, and Contributor or Admin on the capacity. Ask a Fabric administrator, then run apply again.") from None
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
    off = []
    for table in LIVE_TABLES:
        rows = kql(ctx, f".show table {table} policy mirroring | project Policy")
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
1. Open the eventstream {eventstream}, select Edit, and remove the destination {destination} if it shows a warning.
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
    if destination.get("status") == "Warning":
        # Microsoft's page: a property set that does not fit the mode is accepted, ingests nothing and reports no error.
        return blocked("The Eventhouse destination of the eventstream is in the state Warning: it ingests nothing.",
                       WIZARD.format(**words))
    return done(f"eventstream {words['eventstream']}: custom endpoint {SOURCE}, direct ingestion into RawEvents "
                f"(destination {destination.get('status', 'state not reported')})", source_id=source.get("id"))


def act_eventstream(ctx) -> None:
    ws, display = workspace_id(ctx), name(ctx, "EVENTSTREAM_NAME")
    house = need_item(ctx, "Eventhouse", name(ctx, "EVENTHOUSE_NAME"))
    stream = f"{display}-stream"
    # The destination is word for word the one of Microsoft's article "Create an Eventstream with an Eventhouse
    # DirectIngestion destination by using APIs": the Eventhouse's item ID, a table, a connection name of at most 40
    # characters, and a mapping that exists. The source is a custom endpoint, whose properties are empty.
    definition = {
        "sources": [{"name": SOURCE, "type": "CustomEndpoint", "properties": {}}],
        "destinations": [{"name": DESTINATION, "type": "Eventhouse",
                          "properties": {"dataIngestionMode": "DirectIngestion", "workspaceId": ws, "itemId": house["id"],
                                         "tableName": "RawEvents", "connectionName": f"es-windfarm-raw-{suffix(ctx)}",
                                         "mappingRuleName": "RawEvents_mapping"},
                          "inputNodes": [{"name": stream}]}],
        "streams": [{"name": stream, "type": "DefaultStream", "properties": {}, "inputNodes": [{"name": SOURCE}]}],
        "operators": [], "compatibilityLevel": "1.1"}
    payload = base64.b64encode(json.dumps(definition).encode("utf-8")).decode("ascii")
    operation(ctx, "eventstream", lambda: ctx.fabric.call("POST", f"workspaces/{ws}/eventstreams", {
        "displayName": display, "description": "Telemetry from the edge of the wind farm demo.",
        "definition": {"parts": [{"path": "eventstream.json", "payload": payload, "payloadType": "InlineBase64"}]}}))


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
                       f"Empty EVENTSTREAM_BOOTSTRAP_SERVER and EVENTSTREAM_TOPIC in {ctx.env_file.name} if the eventstream was "
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
        return todo(f"{len(missing)} of {len(NOTEBOOKS[group])} to import") if missing else done(f"{len(NOTEBOOKS[group])} notebooks imported")
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


def phase1() -> list[Step]:
    settings_probe, settings_manual = tenant_settings("phase1")
    gate_probe, gate_act = gate_lakehouse("phase1", "p1.gate_lakehouse", "p1.notebooks")
    kql_files = ("fabric/kql/01-tables.kql", "fabric/kql/02-update-policies.kql")
    return [
        Step("pre.tools", "preflight", "The tools the scripts need", pre_tools, basis="looks for az, bash and ssh on this computer"),
        Step("pre.signin", "preflight", "Signed in to Azure as a person, on the right subscription", pre_signin, proof="live",
             basis="az account show"),
        Step("pre.extensions", "preflight", "Azure CLI extension on this computer", pre_extensions, basis="az extension list"),
        Step("pre.rights", "preflight", "Your roles on the subscription", pre_rights, basis="az role assignment list"),
        Step("pre.providers", "preflight", "Resource providers registered", pre_providers, basis="az provider show",
             manual="Register the providers the plan names."),
        Step("pre.region", "preflight", "Region and VM size", pre_region,
             basis="Resource SKUs - List, with its location filter"),
        Step("pre.names", "preflight", "Generated names are free", pre_names, basis="az storage account check-name"),
        Step("pre.custom_locations", "preflight", "Custom Locations object ID", pre_custom_locations, basis="az ad sp show"),
        Step("pre.fabric", "preflight", "The Fabric API answers you", pre_fabric, basis="GET /v1/workspaces"),
        Step("pre.capacity", "preflight", "One Fabric capacity, active", pre_capacity, basis="GET /v1/capacities"),
        Step("phase1.tenant_settings", "preflight", "Tenant settings for Phase 1", settings_probe, manual=settings_manual,
             observable=False, basis="Fabric admin portal; no API for a person who is not an administrator", proof="none"),

        Step("p1.resource_group", "phase1", "Resource group of the demo", p1_resource_group, act_resource_group,
             writes=f"creates the resource group with the tag {TAG}", basis="az group create", proof="offline"),
        Step("p1.edge_vm", "phase1", "Edge VM", p1_edge_vm, act_edge_vm,
             inputs=("infra/01-create-edge-vm.sh",), writes="VM, network, SSH rule for your address, daily shutdown",
             basis="infra/01-create-edge-vm.sh, without its provider registration and role assignments", proof="live"),
        Step("p1.vm_identity_roles", "phase1", "Roles for the VM's identity, on the resource group only", p1_vm_roles, act_vm_roles,
             needs=("roles",), writes="'Kubernetes Cluster - Azure Arc Onboarding' and 'Reader' for the VM's managed identity, "
             "both on the demo's resource group. The manual guide gives Reader on the subscription; the runner does not",
             basis="az role assignment create", proof="offline"),
        Step("p1.edge_host", "phase1", "K3s and tools on the VM", lambda ctx: recorded(ctx, "p1.edge_host", "host prepared")
             if vm(ctx) else after("p1.edge_vm"), lambda ctx: on_vm(ctx, "./edge/scripts/02-prepare-host.sh"),
             inputs=("edge/scripts/02-prepare-host.sh", "infra/vm.sh"), observable=False, witness="p1.arc", writes="installs K3s and the Azure CLI on the VM",
             basis="edge/scripts/02-prepare-host.sh", proof="live"),
        Step("p1.arc", "phase1", "Cluster connected to Azure Arc", p1_arc, lambda ctx: on_vm(ctx, "./edge/scripts/03-arc-enable.sh"),
             inputs=("edge/scripts/03-arc-enable.sh",), wait_seconds=300, writes="Arc-enabled cluster with custom locations",
             basis="edge/scripts/03-arc-enable.sh (az connectedk8s connect, enable-features)", proof="live"),
        Step("p1.iot_operations", "phase1", "Azure IoT Operations", p1_iot_operations,
             lambda ctx: script(ctx, "infra/04-deploy-iot-operations.sh"), needs=("roles",),
             inputs=("infra/04-deploy-iot-operations.sh",), wait_seconds=120,
             writes="storage account, schema registry, device registry namespace, the instance. The Azure CLI gives the schema "
             "registry's identity 'Storage Blob Data Contributor' on that storage account",
             basis="infra/04-deploy-iot-operations.sh (az iot ops init, create)", proof="live"),
        Step("p1.simulator", "phase1", "Turbine simulator on the edge", lambda ctx: recorded(ctx, "p1.simulator", "simulator deployed")
             if instance(ctx) else after("p1.iot_operations"), lambda ctx: on_vm(ctx, "./edge/scripts/05-deploy-simulator.sh"),
             inputs=("edge/scripts/05-deploy-simulator.sh", "simulator/Dockerfile"), observable=False, witness="p1.gate_telemetry",
             writes="builds the simulator image on the VM and starts it", basis="edge/scripts/05-deploy-simulator.sh", proof="live"),

        Step("p1.workspace", "phase1", "Fabric workspace of the demo", p1_workspace, act_workspace,
             writes="creates the workspace on the capacity shown", basis="Workspaces - Create Workspace", proof="offline"),
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
             "mapping RawEvents_mapping", basis="Learn: Create an Eventstream with an Eventhouse DirectIngestion destination by using APIs"),
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
             manual="See the plan line above.", basis="Kusto REST API, /v1/rest/query"),

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
