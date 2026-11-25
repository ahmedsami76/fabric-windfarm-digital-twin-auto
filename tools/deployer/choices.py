"""The questions the runner asks, instead of sending a person to the settings file.

Asked by preflight and plan, in a terminal, before anything is looked at: the region of the edge, the Fabric capacity
(a new one, or one that exists), the workspace (a new one, or an empty one that exists), and which VM size to try first
when Azure did not say which are offered. Each answer is written to the deployment's settings and recorded in its checkpoint with
who gave it and when. Nothing here changes Azure or Fabric: an answer becomes a line of the plan, and the plan still
has to be approved.

A question is asked once. It is asked again when its answer no longer holds (a capacity that cannot hold the demo),
and with --ask. It is no longer asked once the thing it is about exists. Without a terminal, or with --no-input,
nothing is asked: the plan then blocks where an answer is missing and says which setting to fill in.
"""
from __future__ import annotations

import re
from typing import Callable

from . import names
from .cloud import CloudError
from .core import Blocked, Context, Refused
from .steps import (CAN_HOLD, CANNOT_HOLD, FABRIC_REGIONS, IOT_OPERATIONS_REGIONS, NEW_CAPACITY_BASE, NEW_CAPACITY_SKU, REGIONS_READ,
                    account, capacities, capacity, capacity_kind, capacity_label, creating, fabric_sku_regions, new_capacity_label,
                    proper_fabric_region, region_gaps, region_key, region_name, some, suffix, unlisted_capacities, workspaces)

# The app's configuration, and the shell that reads the settings file, take these characters in a workspace's name.
PLAIN_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")
TRIES = 3


class Asker:
    """Asks on the terminal. `read` is input() in a real run and a script of answers in the tests."""

    def __init__(self, say: Callable[[str], None], read: Callable[[str], str]):
        self.say, self._read, self._begun = say, read, False

    def topic(self, title: str) -> None:
        if not self._begun:
            self._begun = True
            self.say("A few questions first. Enter takes the answer in brackets. The answers go into the settings of this deployment; "
                     "nothing is changed in Azure or Fabric by them.")
        self.say(f"\n{title}")

    def line(self, prompt: str) -> str:
        try:
            return self._read(prompt).strip()
        except EOFError:
            raise Refused("A question got no answer. Nothing was changed in Azure or Fabric. Run the command again in a terminal, "
                          "or with --no-input: the plan then says which setting to fill in instead of asking.") from None

    def yes(self, question: str, default: bool) -> bool:
        for _ in range(TRIES):
            answer = self.line(f"  {question} [{'Y/n' if default else 'y/N'}] ").lower()
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            self.say("  Please answer y or n.")
        raise Refused("Three answers that were neither y nor n. Nothing was changed in Azure or Fabric.")

    def pick(self, question: str, count: int, default: int | None, words: dict | None = None, none: str = "none") -> int | None:
        """A number from 1 to count, or one of the words. Enter gives the default, which may be None for 'none of them'."""
        shown = default if default is not None else none
        for _ in range(TRIES):
            answer = self.line(f"  {question} [{shown}] ")
            if not answer:
                return default
            if answer.isdigit() and 1 <= int(answer) <= count:
                return int(answer)
            if words and answer.lower() in words:
                return words[answer.lower()]
            self.say(f"  Please give a number from 1 to {count}" + (", or a name from the list." if words else ", or Enter."))
        raise Refused("Three answers that were not in the list. Nothing was changed in Azure or Fabric.")


def _set(ctx: Context, **values) -> None:
    names.write_env(ctx.env_file, values)
    ctx.cfg.update(values)
    ctx.cache.clear()


def _record(ctx: Context, key: str, answer: str) -> None:
    ctx.state.data["choices"][key] = {"answer": answer, "at": ctx.state.stamp(),
                                      "by": (account(ctx).get("user") or {}).get("name")}
    ctx.state.save()


# ---------------------------------------------------------------------------------------------- the region of the edge
def ask_region(ctx: Context, ask: Asker) -> None:
    current = ctx.cfg.get("LOCATION", "")
    ask.topic("Azure region of the edge: the VM and Azure IoT Operations")
    for index, region in enumerate(IOT_OPERATIONS_REGIONS, 1):
        ask.say(f"    {index}. {region}{'   (now)' if region == current else ''}")
    default = IOT_OPERATIONS_REGIONS.index(current) + 1 if current in IOT_OPERATIONS_REGIONS else None
    picked = ask.pick("Region", len(IOT_OPERATIONS_REGIONS), default,
                      {region: index for index, region in enumerate(IOT_OPERATIONS_REGIONS, 1)})
    if picked is None:
        raise Refused(f"LOCATION is '{current}', which Azure IoT Operations does not support, and no other region was chosen.")
    chosen = IOT_OPERATIONS_REGIONS[picked - 1]
    if chosen != current:
        _set(ctx, LOCATION=chosen)
    _record(ctx, "region", chosen)


# ---------------------------------------------------------------------------------------------- the capacity
def usable(entry: dict) -> bool:
    return entry.get("state") == "Active" and capacity_kind(entry.get("sku")) in CAN_HOLD


def verdict(entry: dict) -> str:
    kind = capacity_kind(entry.get("sku"))
    if kind in CANNOT_HOLD:
        return "cannot hold the demo: " + CANNOT_HOLD[kind]
    if entry.get("state") != "Active":
        return f"is {entry.get('state')}: the runner resumes none"
    return "can hold the demo" if kind in CAN_HOLD else "a SKU the runner does not know"


def capacity_answer_fails(ctx: Context) -> str:
    """Why the capacity in the settings cannot be used, or '' when it can or none is named."""
    wanted = ctx.cfg.get("FABRIC_CAPACITY_ID", "")
    if creating(ctx) or not wanted:
        return ""
    chosen = capacity(ctx)
    if chosen:
        return "" if usable(chosen) else f"{capacity_label(chosen)} {verdict(chosen)}"
    return "" if wanted.lower() in unlisted_capacities(ctx) else f"{wanted} is not a capacity you can see"


def ask_capacity(ctx: Context, ask: Asker) -> bool:
    """True when the answer was: make a new one."""
    listed = capacities(ctx)
    good = [entry for entry in listed if usable(entry)]
    elsewhere = unlisted_capacities(ctx)
    ask.topic("Fabric capacity")
    wrong = capacity_answer_fails(ctx)
    if wrong:
        ask.say(f"  The settings name a capacity that cannot be used: {wrong}.")
    ask.say(f"  Fabric lists {len(listed)} for you, {len(good)} of which can hold the demo.")
    if ask.yes(f"Create a new Fabric capacity for this demo ({NEW_CAPACITY_SKU})?", default=not good and not elsewhere):
        return choose_new_capacity(ctx, ask)
    ask.say("  Capacities you can use:")
    choices = []
    for entry in listed:
        if usable(entry):
            choices.append(entry["id"])
            ask.say(f"    {len(choices)}. {capacity_label(entry)}   {entry['id']}")
        else:
            ask.say(f"    -  {capacity_label(entry)}: {verdict(entry)}")
    for capacity_id, users in sorted(elsewhere.items()):
        choices.append(capacity_id)
        ask.say(f"    {len(choices)}. {capacity_id}   not in Fabric's list for you, so its SKU cannot be read; used by: {some(users)}")
    if not choices:
        ask.say("  None of them can hold the demo.")
        if ask.yes(f"Create a new one ({NEW_CAPACITY_SKU}) after all?", default=False):
            return choose_new_capacity(ctx, ask)
        ask.say("  No capacity chosen. The plan will stop at pre.capacity.")
        return False
    picked = ask.pick("Capacity", len(choices), 1)
    _set(ctx, FABRIC_CAPACITY_ID=choices[picked - 1], FABRIC_CAPACITY_CREATE_SKU="", FABRIC_CAPACITY_NAME="", FABRIC_CAPACITY_REGION="")
    _record(ctx, "capacity", f"existing {choices[picked - 1]}")
    return False


def choose_new_capacity(ctx: Context, ask: Asker) -> bool:
    edge = ctx.cfg.get("LOCATION", "")
    proposed = proper_fabric_region(edge)
    capacity_name = f"{NEW_CAPACITY_BASE}{suffix(ctx)}"
    ask.say(f"  A new capacity: {capacity_name}, {NEW_CAPACITY_SKU}, in the demo's resource group {ctx.cfg['RESOURCE_GROUP']}, with you as its "
            "administrator.")
    ask.say("  It costs money for as long as it runs. The runner makes it and never pauses, resizes or deletes it; pausing is "
            "yours, in the Azure portal (Microsoft Fabric, the capacity, Pause).")
    try:
        offered = fabric_sku_regions(ctx, NEW_CAPACITY_SKU)
    except CloudError as error:
        offered = None
        ask.say(f"  Where your subscription is offered an {NEW_CAPACITY_SKU} could not be read ({str(error)[:120]}); preflight asks again.")
    if proposed and region_key(edge) != proposed:
        ask.say(f"  The edge is in {edge}. Microsoft's region table of {REGIONS_READ} lists no {' and no '.join(region_gaps(edge))} for "
                f"a capacity there, so the runner proposes {region_name(proposed)}.")
    if proposed and offered is not None and proposed not in offered:
        ask.say(f"  {NEW_CAPACITY_SKU} is not offered to your subscription in {region_name(proposed)}.")
        proposed = None
    for _ in range(TRIES):
        answer = ask.line(f"  Region for the capacity, as Azure writes it (westus2, westeurope, ...) [{proposed or 'none'}] ")
        region = region_key(answer) if answer else proposed
        if not region:
            ask.say("  Please name a region.")
        elif region not in FABRIC_REGIONS:
            ask.say(f"  '{answer}' is not a region with all Fabric workloads in Microsoft's table of {REGIONS_READ}.")
        elif offered is not None and region not in offered:
            ask.say(f"  {NEW_CAPACITY_SKU} is not offered to your subscription in {region_name(region)}. It is offered in: "
                    f"{some([region_name(place) for place in offered], most=12) or 'no region'}.")
        elif region_gaps(region) and not ask.yes(f"Microsoft's table lists no {' and no '.join(region_gaps(region))} in "
                                                 f"{region_name(region)}, which later phases of the demo use. Take it anyway?", False):
            continue
        else:
            _set(ctx, FABRIC_CAPACITY_CREATE_SKU=NEW_CAPACITY_SKU, FABRIC_CAPACITY_NAME=capacity_name, FABRIC_CAPACITY_REGION=region,
                 FABRIC_CAPACITY_ID="")
            _record(ctx, "capacity", f"new {capacity_name} {NEW_CAPACITY_SKU} {region}")
            return True
    raise Refused("No region for the new capacity after three answers. Nothing was changed in Azure or Fabric.")


# ---------------------------------------------------------------------------------------------- the workspace
def ask_workspace(ctx: Context, ask: Asker) -> None:
    own = names.generated(suffix(ctx))["FABRIC_WORKSPACE_NAME"]
    ask.topic("Fabric workspace")

    def new() -> None:
        _set(ctx, FABRIC_WORKSPACE_NAME=own, FABRIC_WORKSPACE_ID="")
        _record(ctx, "workspace", f"new {own}")

    if ask.yes(f"Create a new workspace for this demo, {own}?", default=True):
        return new()
    if creating(ctx):
        ask.say("  A workspace stays on the capacity it is on, and the runner moves none. With a new capacity the workspace is "
                f"new too: {own}.")
        return new()
    on = ctx.cfg.get("FABRIC_CAPACITY_ID", "").lower()
    candidates, elsewhere = [], 0
    ask.say("  Workspaces on the capacity you chose. The runner takes only one that is empty:")
    for workspace in sorted(workspaces(ctx), key=lambda entry: str(entry.get("displayName"))):
        if str(workspace.get("type", "Workspace")) != "Workspace" or not workspace.get("capacityId"):
            continue
        if not on or workspace["capacityId"].lower() != on:
            elsewhere += 1
        elif not PLAIN_NAME.match(str(workspace.get("displayName"))):
            ask.say(f"    -  {workspace.get('displayName')}: its name has characters the app's configuration does not take")
        else:
            candidates.append(workspace)
            ask.say(f"    {len(candidates)}. {workspace.get('displayName')}")
    if elsewhere:
        ask.say(f"    ({elsewhere} more are on other capacities.)")
    while candidates:
        picked = ask.pick("Workspace, or Enter for a new one", len(candidates), None, none="new")
        if picked is None:
            break
        chosen = candidates[picked - 1]
        inside = ctx.fabric.listing(f"workspaces/{chosen['id']}/items")
        if inside:
            ask.say(f"  {chosen.get('displayName')} holds {len(inside)} item{'s' if len(inside) != 1 else ''} "
                    f"({some([str(entry.get('displayName')) for entry in inside])}). "
                    "The runner starts only in a workspace that is empty, so that everything in it is the demo's.")
            continue
        _set(ctx, FABRIC_WORKSPACE_NAME=str(chosen["displayName"]), FABRIC_WORKSPACE_ID=str(chosen["id"]))
        _record(ctx, "workspace", f"existing {chosen['id']}")
        return None
    if not candidates:
        ask.say("    none that can be taken.")
    ask.say(f"  A new workspace, then: {own}.")
    return new()


# ---------------------------------------------------------------------------------------------- the VM size
def sizes_unread(ctx: Context) -> bool:
    kept = ctx.state.data["remembered"].get("pre.region") or {}
    return kept.get("state") == "unverified" and (kept.get("evidence") or {}).get("sizes_read") is False


def ask_vm_size(ctx: Context, ask: Asker) -> None:
    sizes = ctx.cfg.get("VM_SIZE", "").split()
    ask.topic("VM size")
    ask.say("  Azure did not say which sizes your subscription is offered. They are tried in this order, and Azure refuses the "
            "ones you are not offered:")
    for index, size in enumerate(sizes, 1):
        ask.say(f"    {index}. {size}")
    picked = ask.pick("If you know one you are offered, its number: it is tried first. Enter keeps the order", len(sizes), None,
                      none="keep")
    if picked and picked != 1:
        sizes.insert(0, sizes.pop(picked - 1))
        _set(ctx, VM_SIZE=" ".join(sizes))
    _record(ctx, "vm_size", sizes[0] if sizes else "")


# ---------------------------------------------------------------------------------------------- all of them, in order
def run_choices(ctx: Context, ask: Asker, again: bool = False) -> set:
    """Asks what is open. Returns the approvals an answer of this run implies: {'capacity'} when a new capacity was chosen."""
    made, implied = ctx.state.data["choices"], set()
    no_group, no_workspace = not ctx.target("resource_group_id"), not ctx.target("workspace_id")
    no_capacity = ctx.state.step("p1.capacity").get("status") != "complete"
    no_vm = ctx.state.step("p1.edge_vm").get("status") != "complete"

    def due(key: str) -> bool:
        return again or key not in made

    if no_group and (due("region") or ctx.cfg.get("LOCATION") not in IOT_OPERATIONS_REGIONS):
        ask_region(ctx, ask)
    try:
        if no_workspace and no_capacity and (due("capacity") or capacity_answer_fails(ctx)):
            if ask_capacity(ctx, ask):
                implied.add("capacity")
        if no_workspace and due("workspace"):
            ask_workspace(ctx, ask)
    except (CloudError, Blocked) as error:
        # Fabric did not answer: the plan below says so at pre.fabric, with what to do. The questions wait for the next run.
        ask.say(f"\n  Fabric could not be asked just now ({str(getattr(error, 'detail', error))[:160]}). The questions about the "
                "capacity and the workspace come with the next run.")
    if no_vm and sizes_unread(ctx) and due("vm_size"):
        ask_vm_size(ctx, ask)
    return implied


def summary(ctx: Context) -> str:
    """One line of what was chosen, for the end of the questions."""
    listed = None if creating(ctx) else capacity(ctx)
    capacity_text = (new_capacity_label(ctx) + ", to be made" if creating(ctx) else
                     capacity_label(listed) if listed else ctx.cfg.get("FABRIC_CAPACITY_ID") or "none yet")
    workspace_text = ctx.cfg["FABRIC_WORKSPACE_NAME"] + (", which exists" if ctx.cfg.get("FABRIC_WORKSPACE_ID") else ", to be made")
    return (f"Chosen: edge in {ctx.cfg.get('LOCATION')}; capacity {capacity_text}; workspace {workspace_text}. Written to "
            f"{ctx.env_label}. Nothing was changed in Azure or Fabric.")
