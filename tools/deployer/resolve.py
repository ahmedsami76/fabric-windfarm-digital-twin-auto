"""How the choices of a deployment are settled, without a question wherever that is possible.

For each choice, in this order:

  1. an option of this run (--edge-region, --capacity, --new-capacity, --workspace-id, --vm-size, --ssh-source);
  2. what the settings of the deployment already say;
  3. the profile saved for the tenant and subscription (plan --save-profile);
  4. a default that looking at the cloud establishes as the only one: a single capacity that can hold the demo.

A value that is not valid is refused where it is given. Nothing else is ever put in its place: not another region,
not another capacity. What is still open after the four is asked together, in a terminal, or shown by the plan with
the candidates and the options that settle it. No choice is made in apply or status.

Making a capacity is never taken from a profile or from another deployment: it is chosen for one deployment, with
--new-capacity or at the question, and approved for one plan.
"""
from __future__ import annotations

import ipaddress
import json
import re
from pathlib import Path

from .choices import (Asker, _record, _set, ask_capacity, ask_region, capacity_answer_fails, choose_new_capacity, run_choices,
                      usable, verdict)
from .cloud import CloudError
from .core import Blocked, Context, Refused
from .steps import (FABRIC_REGIONS, IOT_OPERATIONS_REGIONS, NEW_CAPACITY_BASE, NEW_CAPACITY_SKU, REGIONS_READ, account, capacities,
                    capacity_label, creating, fabric_sku_regions, proper_fabric_region, region_key, region_name, some, suffix,
                    unlisted_capacities, workspaces)

# The options that settle a choice. They go with preflight and plan; apply carries out what a plan settled.
CHOICE_OPTIONS = ("edge_region", "capacity", "new_capacity", "capacity_region", "workspace_id", "vm_size", "ssh_source",
                  "save_profile", "ask")
# What a profile may hold. Never a name, never a workspace, never the choice to make a capacity.
PROFILE_KEYS = ("LOCATION", "FABRIC_CAPACITY_ID", "VM_SIZE", "VM_AUTO_SHUTDOWN_UTC", "SSH_SOURCE_CIDR")


def given(args) -> list[str]:
    return ["--" + name.replace("_", "-") for name in CHOICE_OPTIONS if getattr(args, name, None)]


# ---------------------------------------------------------------------------------------------- the profile
def profile_path(ctx: Context) -> Path:
    return Path(ctx.root) / ".deploy" / "profiles" / f"{ctx.cfg['SUBSCRIPTION_ID']}.json"


def load_profile(ctx: Context) -> dict:
    """The values saved for this subscription, or {} when there are none. A profile of another tenant is not used."""
    path = profile_path(ctx)
    if not path.is_file():
        return {}
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        raise Refused(f"{path.relative_to(ctx.root)} is not readable as a profile. Delete it, or write it again with "
                      "plan --save-profile. Nothing was changed.") from None
    me = account(ctx)
    if saved.get("tenant_id") != me.get("tenantId") or saved.get("subscription_id") != me.get("id"):
        raise Refused(f"{path.relative_to(ctx.root)} was saved for tenant {saved.get('tenant_id')} and subscription "
                      f"{saved.get('subscription_id')}, and this deployment is in tenant {me.get('tenantId')}, subscription "
                      f"{me.get('id')}. Delete the file or run with --no-profile. Nothing was changed.")
    return {key: str(value) for key, value in (saved.get("values") or {}).items() if key in PROFILE_KEYS and value}


def save_profile(ctx: Context) -> str:
    """Keeps the choices of this deployment for the next ones in the same tenant and subscription. Says what it kept."""
    cfg, me = ctx.cfg, account(ctx)
    values = {key: cfg.get(key, "") for key in PROFILE_KEYS if cfg.get(key)}
    left_out = ""
    if creating(ctx):
        values.pop("FABRIC_CAPACITY_ID", None)
        left_out = (" This deployment makes a capacity of its own; that is chosen and approved for each deployment, so the "
                    "profile names no capacity.")
    if not values.get("LOCATION"):
        raise Refused("There is nothing to save yet: the region of the edge has not been chosen. Nothing was changed.")
    path = profile_path(ctx)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"tenant_id": me.get("tenantId"), "subscription_id": me.get("id"), "subscription": me.get("name"),
            "saved_at": ctx.state.stamp(), "saved_by": (me.get("user") or {}).get("name"),
            "from_deployment": cfg["DEPLOYMENT_SUFFIX"], "values": values}
    temporary = Path(str(path) + ".tmp")
    temporary.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return (f"Profile saved for subscription {me.get('name')}: {', '.join(f'{key}={value}' for key, value in values.items())}. "
            f"The next deployments here take these without being asked; an option of a run comes first, and "
            f"--no-profile leaves the profile out.{left_out} File: {path.relative_to(ctx.root)}")


# ---------------------------------------------------------------------------------------------- the four sources
def open_capacity(ctx: Context) -> bool:
    return not ctx.cfg.get("FABRIC_CAPACITY_ID") and not creating(ctx)


def _from_options(ctx: Context, args, ask: Asker | None) -> set:
    cfg, implied = ctx.cfg, set()
    group_made, workspace_made = bool(ctx.target("resource_group_id")), bool(ctx.target("workspace_id"))
    vm_made = ctx.state.step("p1.edge_vm").get("status") == "complete"
    stays = "A deployment stays where it is. For another one: python3 tools/deploy.py plan --new"
    if args.edge_region:
        region = re.sub(r"[^a-z0-9]", "", args.edge_region.lower())
        if region not in IOT_OPERATIONS_REGIONS:
            raise Refused(f"--edge-region {args.edge_region}: Azure IoT Operations is supported in {', '.join(IOT_OPERATIONS_REGIONS)}. "
                          "Nothing was changed.")
        if group_made and region != cfg.get("LOCATION"):
            raise Refused(f"--edge-region {region}: this deployment made its resource group in {cfg.get('LOCATION')}. {stays} "
                          f"--edge-region {region}")
        _set(ctx, LOCATION=region)
        _record(ctx, "region", region, "option --edge-region")
    if args.vm_size:
        sizes = args.vm_size.replace(",", " ").split()
        wrong = [size for size in sizes if not re.fullmatch(r"Standard_[A-Za-z0-9_]+", size)]
        if wrong or not sizes:
            raise Refused(f"--vm-size takes VM sizes in the order to try them, for example \"Standard_D8s_v7 Standard_D8s_v6\". "
                          f"Not a size: {', '.join(wrong) or 'nothing given'}. Nothing was changed.")
        if vm_made and " ".join(sizes) != " ".join(cfg.get("VM_SIZE", "").split()):
            raise Refused(f"--vm-size: the VM of this deployment exists. {stays}")
        _set(ctx, VM_SIZE=" ".join(sizes))
        _record(ctx, "vm_size", " ".join(sizes), "option --vm-size")
    if args.ssh_source:
        try:
            scope = str(ipaddress.ip_network(args.ssh_source, strict=False))
        except ValueError:
            raise Refused(f"--ssh-source {args.ssh_source} is not an address range such as 203.0.113.10/32. Nothing was "
                          "changed.") from None
        if scope.endswith("/0"):
            raise Refused("--ssh-source: the runner does not open SSH to every address. Give the range you work from.")
        _set(ctx, SSH_SOURCE_CIDR=scope)
        _record(ctx, "ssh", scope, "option --ssh-source")
    if args.capacity and args.new_capacity:
        raise Refused("--capacity names a capacity that exists and --new-capacity has one made. Give one of them.")
    if args.capacity_region and not args.new_capacity:
        raise Refused("--capacity-region is the region of a capacity to be made: it goes with --new-capacity. A capacity "
                      "that exists is where it is.")
    capacity_made = ctx.state.step("p1.capacity").get("status") == "complete" and creating(ctx)
    if args.capacity:
        listed = capacities(ctx)
        wanted = args.capacity.strip()
        found = [entry for entry in listed if wanted.lower() in (str(entry.get("id", "")).lower(), str(entry.get("displayName", "")).lower())]
        if len(found) > 1:
            raise Refused(f"--capacity {wanted} fits {len(found)} capacities: "
                          f"{'; '.join(capacity_label(entry) + ' ' + entry['id'] for entry in found)}. Name one by its ID.")
        if found and not usable(found[0]):
            raise Refused(f"--capacity {wanted}: {capacity_label(found[0])} {verdict(found[0])}. Nothing was changed.")
        if not found and wanted.lower() not in unlisted_capacities(ctx):
            raise Refused(f"--capacity {wanted} is not a capacity Fabric lists for you, and none of your workspaces runs on it. "
                          f"Fabric lists: {'; '.join(capacity_label(entry) + ' ' + entry['id'] for entry in listed) or 'none'}. "
                          "Nothing was changed.")
        chosen = found[0]["id"] if found else wanted
        if (workspace_made or capacity_made) and (creating(ctx) or chosen.lower() != cfg.get("FABRIC_CAPACITY_ID", "").lower()):
            raise Refused(f"--capacity {wanted}: the workspace or the capacity of this deployment exists. {stays}")
        _set(ctx, FABRIC_CAPACITY_ID=chosen, FABRIC_CAPACITY_CREATE_SKU="", FABRIC_CAPACITY_NAME="", FABRIC_CAPACITY_REGION="")
        _record(ctx, "capacity", f"existing {chosen}", "option --capacity")
    if args.new_capacity:
        if workspace_made and not creating(ctx):
            raise Refused(f"--new-capacity: the workspace of this deployment exists, on a capacity that exists. {stays}")
        if not args.capacity_region:
            if not ask:
                proposed = proper_fabric_region(cfg.get("LOCATION", ""))
                raise Refused("--new-capacity needs --capacity-region REGION when nobody can be asked. " +
                              (f"For an edge in {cfg.get('LOCATION')} the runner would propose {proposed}. " if proposed else "") +
                              "Nothing was changed.")
            ask.topic("Fabric capacity")
            if choose_new_capacity(ctx, ask):
                implied.add("capacity")
        else:
            region = region_key(args.capacity_region)
            if region not in FABRIC_REGIONS:
                raise Refused(f"--capacity-region {args.capacity_region} is not a region with all Fabric workloads in Microsoft's "
                              f"table of {REGIONS_READ}. Nothing was changed.")
            try:
                offered = fabric_sku_regions(ctx, NEW_CAPACITY_SKU)
            except CloudError:
                offered = None                      # preflight asks again, and says so
            if offered is not None and region not in offered:
                raise Refused(f"--capacity-region {region}: Azure's list of SKUs does not name {region_name(region)} for an "
                              f"{NEW_CAPACITY_SKU} in this subscription. It names: {some([region_name(place) for place in offered], most=12)}. "
                              "To take the region all the same, choose it at the question: plan --new-capacity, in a terminal.")
            if capacity_made and region != region_key(cfg.get("FABRIC_CAPACITY_REGION", "")):
                raise Refused(f"--capacity-region {region}: the capacity of this deployment exists. {stays}")
            _set(ctx, FABRIC_CAPACITY_CREATE_SKU=NEW_CAPACITY_SKU, FABRIC_CAPACITY_NAME=f"{NEW_CAPACITY_BASE}{suffix(ctx)}",
                 FABRIC_CAPACITY_REGION=region, FABRIC_CAPACITY_ID="")
            _record(ctx, "capacity", f"new {NEW_CAPACITY_BASE}{suffix(ctx)} {NEW_CAPACITY_SKU} {region}", "option --new-capacity")
            _record(ctx, "capacity_region_unlisted", "", "option --new-capacity")
    if args.workspace_id:
        wanted = args.workspace_id.strip()
        if workspace_made and wanted.lower() != str(ctx.target("workspace_id")).lower():
            raise Refused(f"--workspace-id {wanted}: this deployment has its workspace. {stays}")
        found = next((entry for entry in workspaces(ctx) if str(entry.get("id", "")).lower() == wanted.lower()), None)
        if not found:
            raise Refused(f"--workspace-id {wanted} is not a workspace you can see. It takes the ID, not the name. Nothing was changed.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", found.get("displayName", "")):
            raise Refused(f"--workspace-id {wanted}: the name '{found.get('displayName')}' has characters the scripts cannot take.")
        _set(ctx, FABRIC_WORKSPACE_ID=found["id"], FABRIC_WORKSPACE_NAME=found["displayName"])
        _record(ctx, "workspace", f"existing {found['id']}", "option --workspace-id")
    return implied


def _from_profile(ctx: Context, args) -> None:
    if args.no_profile:
        return
    cfg, made = ctx.cfg, ctx.state.data["choices"]
    saved = load_profile(ctx)
    if not saved:
        return
    group_made, workspace_made = bool(ctx.target("resource_group_id")), bool(ctx.target("workspace_id"))
    vm_made = ctx.state.step("p1.edge_vm").get("status") == "complete"
    if not cfg.get("LOCATION") and not group_made and saved.get("LOCATION"):
        if saved["LOCATION"] not in IOT_OPERATIONS_REGIONS:
            raise Refused(f"The profile of this subscription names the edge region '{saved['LOCATION']}', which Azure IoT Operations "
                          "does not support. The runner puts no other region in its place. Give --edge-region REGION "
                          "--save-profile, or --no-profile.")
        _set(ctx, LOCATION=saved["LOCATION"])
        _record(ctx, "region", saved["LOCATION"], "profile")
    if open_capacity(ctx) and not workspace_made and saved.get("FABRIC_CAPACITY_ID"):
        # Written as it is. If it has been paused or deleted since, pre.capacity blocks on it: no other capacity is taken.
        _set(ctx, FABRIC_CAPACITY_ID=saved["FABRIC_CAPACITY_ID"])
        _record(ctx, "capacity", f"existing {saved['FABRIC_CAPACITY_ID']}", "profile")
    for key, record in (("VM_SIZE", "vm_size"), ("VM_AUTO_SHUTDOWN_UTC", "shutdown"), ("SSH_SOURCE_CIDR", "ssh")):
        if saved.get(key) and record not in made and not vm_made and cfg.get(key) != saved[key]:
            _set(ctx, **{key: saved[key]})
            _record(ctx, record, saved[key], "profile")
        elif saved.get(key) and record not in made and not vm_made:
            _record(ctx, record, saved[key], "profile")


def _from_discovery(ctx: Context) -> None:
    """One capacity that can hold the demo, and no other in sight: that one. Two candidates are a choice, not a default."""
    if not open_capacity(ctx) or ctx.target("workspace_id"):
        return
    try:
        good = [entry for entry in capacities(ctx) if usable(entry)]
        if len(good) == 1 and not unlisted_capacities(ctx):
            _set(ctx, FABRIC_CAPACITY_ID=good[0]["id"])
            _record(ctx, "capacity", f"existing {good[0]['id']}", "the only capacity in sight that can hold the demo")
    except (CloudError, Blocked):
        return                                      # pre.fabric says what is wrong with the Fabric API


def settle(ctx: Context, args, ask: Asker | None) -> set:
    """Settles what can be settled and asks, together, what cannot. Returns the approvals an answer implies."""
    implied = _from_options(ctx, args, ask)
    _from_profile(ctx, args)
    _from_discovery(ctx)
    if not ask:
        return implied
    if args.ask:
        return implied | run_choices(ctx, ask, again=True)
    no_region = not ctx.cfg.get("LOCATION") and not ctx.target("resource_group_id")
    try:
        no_capacity = not ctx.target("workspace_id") and (open_capacity(ctx) or bool(capacity_answer_fails(ctx)))
    except (CloudError, Blocked):
        no_capacity = False
    waiting = [text for due, text in ((no_region, "the Azure region of the edge (--edge-region)"),
                                      (no_capacity, "the Fabric capacity (--capacity ID, or --new-capacity --capacity-region REGION)")) if due]
    if not waiting:
        return implied
    ask.say(f"{len(waiting)} choice{'s' if len(waiting) > 1 else ''} of this deployment could not be settled from options, "
            f"settings, a profile or what the cloud shows: {'; '.join(waiting)}. Asked now, together; Enter takes the answer in "
            "brackets. Nothing is changed in Azure or Fabric by an answer.")
    if no_region:
        ask_region(ctx, ask)
    if no_capacity:
        try:
            if ask_capacity(ctx, ask):
                implied.add("capacity")
        except (CloudError, Blocked) as error:
            ask.say(f"\n  Fabric could not be asked just now ({str(getattr(error, 'detail', error))[:160]}). The plan says so at pre.fabric.")
    return implied


def sources(ctx: Context) -> str:
    """Where each choice of the deployment came from, for the plan."""
    made = ctx.state.data["choices"]
    shown = [f"{label} {made[key].get('answer')} ({made[key].get('source') or 'asked'})"
             for key, label in (("region", "edge region"), ("capacity", "capacity"), ("workspace", "workspace"), ("vm_size", "VM sizes"),
                                ("ssh", "SSH from"))
             if made.get(key, {}).get("answer")]
    return "; ".join(shown)
