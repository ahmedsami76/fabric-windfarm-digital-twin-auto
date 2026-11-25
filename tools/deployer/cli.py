"""The command line of the deployment runner: preflight, plan, apply, status."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import names
from .cloud import Az, Kusto, OneLake, Shell, make_fabric
from .core import (EXIT_BLOCKED, EXIT_FAILED, EXIT_OK, EXIT_REFUSED, PHASES, Blocked, Context, Lock, Options, Redactor, Refused,
                   State, StepFailed, apply, make_plan, plan_hash, print_plan, select)
from .steps import freshness, kql_database
from .steps_later import catalogue

ROOT = Path(__file__).resolve().parents[2]
CONFIRMABLE = ("phase1.tenant_settings", "phase3.tenant_settings", "phase4.tenant_settings", "p2.acceptance", "p5a.isolation")


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="tools/deploy.py", description="Deploys the wind farm demo step by step. preflight, plan "
                                  "and status change nothing in Azure or Fabric. apply runs one approved plan and can be run again.")
    top.add_argument("mode", choices=("preflight", "plan", "apply", "status"))
    top.add_argument("--up-to", choices=PHASES[1:5], default="phase1", help="the last phase to include (default: phase1)")
    top.add_argument("--approve", metavar="PLAN", default="", help="apply: the identifier that plan printed")
    top.add_argument("--approve-role-changes", action="store_true",
                     help="allow the role assignments the plan lists, each on the demo's resource group or workspace")
    top.add_argument("--allow-preview", metavar="NAME", action="append", default=[], choices=("data-agent-sdk", "ontology"),
                     help="let the runner use a preview feature: data-agent-sdk, ontology")
    top.add_argument("--opt-in", metavar="NAME", action="append", default=[], choices=("pip-jobs",),
                     help="pip-jobs: try the notebooks that use %%pip as jobs (not documented for jobs started through the API)")
    top.add_argument("--enable-phase5a-isolated-simulator", action="store_true",
                     help="also provision the command path of Phase 5a, switched off. For an edge that is this demo's simulator only")
    top.add_argument("--regenerate-history", metavar="LABEL", default="",
                     help="run notebook 02 again, once for this label (for example a date)")
    top.add_argument("--confirm", metavar="STEP", action="append", default=[], help="apply: you confirm a step the runner cannot read")
    top.add_argument("--acknowledge", metavar="ID", action="append", default=[],
                     help="apply: this resource or item in the demo's group or workspace belongs there")
    top.add_argument("--new-names", action="store_true", help="plan: choose a new suffix, while nothing has been created")
    return top


def options_of(args) -> Options:
    granted = {f"preview:{name}" for name in args.allow_preview} | {f"optin:{name}" for name in args.opt_in}
    if args.approve_role_changes:
        granted.add("roles")
    return Options(up_to=args.up_to, granted=granted, phase5a=args.enable_phase5a_isolated_simulator,
                   regenerate_history=args.regenerate_history)


def settings(args, root: Path, az, say) -> dict:
    """The settings file of this deployment. Made on the first plan, with generated names; never guessed afterwards."""
    env_file, example = root / "config" / "demo.env", root / "config" / "demo.env.example"
    if not env_file.exists():
        if args.mode in ("apply", "status"):
            raise Refused(f"{env_file} does not exist. Run plan first: it chooses the names and writes them there.")
        suffix = names.new_suffix()
        account = az.json("account", "show")
        names.write_env(env_file, {**names.generated(suffix), "SUBSCRIPTION_ID": account["id"], "FABRIC_CAPACITY_ID": ""}, template=example)
        say(f"Wrote {env_file.relative_to(root)} with names ending in -{suffix}, for subscription {account.get('name')}. "
            "Nothing was changed in Azure or Fabric. Read the file; LOCATION and VM_SIZE are yours to change before the first apply.")
    cfg = names.read_env(env_file)
    suffix = cfg.get("DEPLOYMENT_SUFFIX", "")
    if not names.valid_suffix(suffix):
        raise Refused(f"{env_file} has no DEPLOYMENT_SUFFIX: it describes a deployment that was made by hand, from the guides. "
                      "The runner works only in a resource group and a workspace that it made itself. To start one, move this "
                      "file away (keep it: it is the record of your deployment) and run plan.")
    expected = names.generated(suffix)
    changed = [key for key, value in expected.items() if cfg.get(key) != value]
    if changed:
        raise Refused(f"{env_file}: {', '.join(changed)} no longer carry the suffix -{suffix}. The names of a deployment are not "
                      "edited by hand. Put them back, or start a new deployment with plan --new-names.")
    if args.new_names:
        if args.mode != "plan":
            raise Refused("--new-names goes with plan.")
        made = State(root / ".deploy" / suffix, Redactor()).data["target"]
        if made.get("resource_group_id") or made.get("workspace_id"):
            raise Refused(f"Deployment -{suffix} has created resources. New names would leave them behind without a record. "
                          "Remove that deployment first (bash infra/99-cleanup.sh), or go on with it.")
        fresh = names.new_suffix()
        names.write_env(env_file, {**names.generated(fresh), "EVENTSTREAM_BOOTSTRAP_SERVER": "", "EVENTSTREAM_TOPIC": ""})
        say(f"New names, ending in -{fresh}.")
        cfg = names.read_env(env_file)
    return cfg


def target_of(ctx: Context, account: dict) -> dict:
    cfg = ctx.cfg
    return {"tenant_id": account.get("tenantId"), "subscription_id": account.get("id"), "subscription": account.get("name"),
            "resource_group": cfg["RESOURCE_GROUP"], "location": cfg.get("LOCATION"), "workspace_name": cfg["FABRIC_WORKSPACE_NAME"],
            "capacity_id": cfg.get("FABRIC_CAPACITY_ID", ""), "suffix": cfg["DEPLOYMENT_SUFFIX"], "user": (account.get("user") or {}).get("name")}


def show_target(ctx: Context, target: dict) -> None:
    made = ctx.state.data["target"]
    ctx.say("Target")
    ctx.say(f"  tenant          {target['tenant_id']}")
    ctx.say(f"  subscription    {target['subscription']}  ({target['subscription_id']})")
    ctx.say(f"  resource group  {target['resource_group']} in {target['location']}  "
            f"({'made by this deployment' if made.get('resource_group_id') else 'not created yet'})")
    ctx.say(f"  workspace       {target['workspace_name']}  ({made.get('workspace_id') or 'not created yet'})")
    ctx.say(f"  capacity        {target['capacity_id'] or 'not chosen yet: see pre.capacity'}")
    ctx.say(f"  signed in as    {target['user']}")


def check_target(ctx: Context, target: dict) -> None:
    """A deployment stays in the tenant and the subscription it began in."""
    made = ctx.state.data["target"]
    for key, label in (("tenant_id", "tenant"), ("subscription_id", "subscription")):
        if made.get(key) and made[key] != target[key]:
            raise Refused(f"This deployment began in {label} {made[key]}. The Azure CLI is now on {label} {target[key]}. "
                          "Nothing was changed. Sign in to the right one, or start a new deployment in a new copy of the settings.")


def build(args, root: Path, out, adapters=None) -> tuple[Context, list]:
    redact = Redactor()
    say = lambda text: print(redact(text), file=out, flush=True)   # noqa: E731
    made = adapters(redact) if callable(adapters) else (adapters or {})    # the tests hand in stand-ins
    az = made.get("az") or Az(redact)
    cfg = settings(args, root, az, say)
    options = options_of(args)
    state = State(root / ".deploy" / cfg["DEPLOYMENT_SUFFIX"], redact)
    ctx = Context(root=root, cfg=cfg, env_file=root / "config" / "demo.env", state=state, options=options, redact=redact, az=az,
                  shell=made.get("shell") or Shell(root, redact, out), out=out,
                  **{key: made[key] for key in ("clock", "sleep", "wall") if key in made})
    ctx.fabric = made.get("fabric") or make_fabric(az)
    ctx.kusto = made.get("kusto") or Kusto(az, redact)
    ctx.onelake = made.get("onelake") or OneLake(az)
    return ctx, select(catalogue(options), options)


def main(argv=None, out=None, root: Path = ROOT, adapters=None) -> int:
    args = parser().parse_args(argv)
    out = out or sys.stdout
    try:
        ctx, steps = build(args, root, out, adapters)
        account = ctx.az.json("account", "show")
        target = target_of(ctx, account)
        check_target(ctx, target)
        if args.mode == "status":
            return status(ctx, steps, target)
        if args.mode == "preflight":
            steps = [step for step in steps if step.prerequisite]
        if args.mode == "apply":
            return run_apply(ctx, steps, args, account)
        lines = make_plan(ctx, steps)
        target = target_of(ctx, account)          # the capacity may have been found by its probe just now
        show_target(ctx, target)
        digest = plan_hash(ctx, lines, target)
        print_plan(ctx, lines, digest)
        if args.mode == "preflight":
            waiting = [line for line in lines if line.decision in ("blocked", "operator")]
            ctx.say("Preflight: " + (f"{len(waiting)} things need you before a deployment can run." if waiting else "nothing stands in the way."))
            return EXIT_BLOCKED if waiting else EXIT_OK
        ctx.say("Nothing was changed in Azure or Fabric. To carry this plan out, repeat the command with apply and "
                f"--approve {digest}, and the same options.")
        return EXIT_OK
    except Refused as stop:
        print(f"REFUSED  {stop}", file=out, flush=True)
        return EXIT_REFUSED
    except Blocked as stop:
        print(f"BLOCKED  {stop.detail}\n  What to do:\n    {stop.action}", file=out, flush=True)
        return EXIT_BLOCKED
    except StepFailed as failure:
        print(f"FAILED   {failure}", file=out, flush=True)
        return EXIT_FAILED


def run_apply(ctx: Context, steps: list, args, account: dict) -> int:
    with Lock(ctx.state.folder):
        if any(step not in CONFIRMABLE for step in args.confirm):
            raise Refused(f"--confirm takes: {', '.join(CONFIRMABLE)}. Everything else the runner looks at itself.")
        for step in args.confirm:
            ctx.state.data["confirmed"][step] = {"at": ctx.state.stamp(), "by": (account.get("user") or {}).get("name")}
        for resource in args.acknowledge:
            if resource not in ctx.state.data["acknowledged"]:
                ctx.state.data["acknowledged"].append(resource)
        if args.confirm or args.acknowledge:
            ctx.state.save()
        lines = make_plan(ctx, steps)
        target = target_of(ctx, account)
        show_target(ctx, target)
        digest = plan_hash(ctx, lines, target)
        if not args.approve:
            raise Refused(f"apply needs the approval of a plan: --approve {digest} if this is the plan you have read. "
                          "Run plan with the same options to read it.")
        if args.approve != digest:
            raise Refused(f"You approved plan {args.approve}; the plan is now {digest}. The target, the options, a file a step "
                          "uses, or the state of the cloud has changed since. Nothing was changed. Run plan again and read it.")
        if not ctx.state.data["target"].get("tenant_id"):
            ctx.set_target(tenant_id=target["tenant_id"], subscription_id=target["subscription_id"])
        ctx.cache.clear()
        code = apply(ctx, steps, {line.step.id for line in lines if line.decision == "drift"})
        if code == EXIT_OK:
            ctx.say(f"\nEverything up to {ctx.options.up_to} is in place. python3 tools/deploy.py status shows it with what was measured.")
        return code


def status(ctx: Context, steps: list, target: dict) -> int:
    show_target(ctx, target)
    ctx.say("")
    for step in steps:
        saved = ctx.state.step(step.id)
        word = saved.get("status", "not started")
        ctx.say(f"  {step.id:<28} {word:<12} {saved.get('at', ''):<21} {saved.get('detail', '')}")
        if saved.get("status") == "complete" and saved.get("verified") is False:
            ctx.say(f"  {'':<28} {'':<12} {'':<21} (not looked at by the runner itself)")
    for step_id, work in ctx.state.data["pending"].items():
        ctx.say(f"  under way for {step_id}: {', '.join(work)}")
    try:
        if ctx.target("workspace_id") and kql_database(ctx):
            seen = freshness(ctx)
            ctx.say(f"\nNow, in the Eventhouse: {seen['rows']} readings from {seen['turbines']} turbines in the last 5 minutes, "
                    f"the newest {seen['age_seconds']} s old.")
    except (StepFailed, Blocked) as error:
        ctx.say(f"\nThe Eventhouse could not be asked just now: {error}")
    return EXIT_OK
