"""The command line of the deployment runner: preflight, plan, apply, status."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import choices, deployments, ready, resolve
from .cloud import Az, CloudError, Kusto, OneLake, Shell, make_fabric
from .core import (EXIT_BLOCKED, EXIT_FAILED, EXIT_OK, EXIT_REFUSED, PHASES, Blocked, Context, Lock, Options, Redactor, Refused,
                   State, StepFailed, apply, make_plan, plan_differences, plan_digest, plan_record, print_plan, save_plan, select)
from .steps import capacity_label, creating, new_capacity, new_capacity_label
from .steps_later import catalogue

ROOT = Path(__file__).resolve().parents[2]
# What a person can state that the runner cannot read. The last one is no step: it is part of "demo-ready" (ready.py).
CONFIRMABLE = ("phase1.tenant_settings", "phase3.tenant_settings", "phase4.tenant_settings", "p2.acceptance", "p5a.isolation",
               "p3.agent_message")


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(prog="tools/deploy.py", description="Deploys the wind farm demo step by step. preflight, plan "
                                  "and status change nothing in Azure or Fabric. apply runs one approved plan and can be run again.")
    top.add_argument("mode", choices=("preflight", "plan", "apply", "status"))
    top.add_argument("--up-to", choices=PHASES[1:5], default="phase1", help="the last phase to include (default: phase1)")
    top.add_argument("--approve", metavar="PLAN", default="", help="apply: the identifier that plan printed")
    top.add_argument("--approve-role-changes", action="store_true",
                     help="allow the role assignments the plan lists, each on the demo's resource group or workspace")
    top.add_argument("--approve-capacity-creation", action="store_true",
                     help="allow the plan to make the Fabric capacity you chose to have made. It costs money for as long as it runs")
    choice = top.add_argument_group("choices of a deployment (preflight and plan). An option comes before the deployment's settings, "
                                    "those before the profile of the subscription, that before what the cloud shows")
    choice.add_argument("--subscription", metavar="ID", default="",
                        help="the subscription of a new deployment. Without it: the one the Azure CLI is on when the deployment is started")
    choice.add_argument("--edge-region", metavar="REGION", default="", help="Azure region of the VM and Azure IoT Operations")
    choice.add_argument("--capacity", metavar="ID", default="", help="the existing Fabric capacity to use, by ID (or by its name)")
    choice.add_argument("--new-capacity", action="store_true",
                        help="have a Fabric capacity made for this deployment (F16). It costs money for as long as it runs, "
                             "and needs --approve-capacity-creation")
    choice.add_argument("--capacity-region", metavar="REGION", default="", help="with --new-capacity: its region")
    choice.add_argument("--workspace-id", metavar="ID", default="",
                        help="use this existing, empty workspace on the chosen capacity. Without it a workspace is made")
    choice.add_argument("--vm-size", metavar="SIZES", default="", help="VM sizes in the order to try them, in quotes")
    choice.add_argument("--ssh-source", metavar="CIDR", default="",
                        help="the address range that may reach SSH on the VM. Without it: the public address of this computer")
    choice.add_argument("--save-profile", action="store_true",
                        help="keep region, existing capacity, VM sizes, shutdown hour and SSH range for the next deployments in "
                             "this tenant and subscription")
    choice.add_argument("--no-profile", action="store_true", help="leave the saved profile out of this run")
    top.add_argument("--no-input", action="store_true",
                     help="preflight and plan: ask nothing. A choice that is still open blocks the plan, with the options that settle it")
    top.add_argument("--ask", action="store_true",
                     help="preflight and plan, in a terminal: go through every question whose subject does not exist yet")
    top.add_argument("--adopt-job", metavar="STEP=JOB", action="append", default=[],
                     help="apply: this run of a notebook, which Fabric lists, is the run of that step. For a run the runner has no record of")
    top.add_argument("--resubmit", metavar="STEP", action="append", default=[],
                     help="apply: start the notebook of that step again, after an apply that ended before it knew whether Fabric took its request")
    top.add_argument("--app-check", metavar="BUILD,ROUTE,SECONDS", default="",
                     help="apply: what the twin's own connection check shows: its build, the route (lakehouse or eventhouse), "
                          "and the age of the newest reading in seconds")
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
    top.add_argument("--new", action="store_true",
                     help="preflight and plan: start a new deployment, with a new random suffix. The ones this folder already holds stay as they are")
    top.add_argument("--deployment", metavar="SUFFIX", default="",
                     help="work on this deployment of the folder. apply always names it; status lists them")
    top.add_argument("--recheck", action="store_true",
                     help="ask again what was asked within the last twelve hours and kept: your roles, the resource providers, the VM sizes")
    return top


def options_of(args) -> Options:
    granted = {f"preview:{name}" for name in args.allow_preview} | {f"optin:{name}" for name in args.opt_in}
    if args.approve_role_changes:
        granted.add("roles")
    if args.approve_capacity_creation:
        granted.add("capacity")
    return Options(up_to=args.up_to, granted=granted, phase5a=args.enable_phase5a_isolated_simulator,
                   regenerate_history=args.regenerate_history)


def target_of(ctx: Context, account: dict) -> dict:
    cfg = ctx.cfg
    return {"tenant_id": account.get("tenantId"), "subscription_id": account.get("id"), "subscription": account.get("name"),
            "resource_group": cfg["RESOURCE_GROUP"], "location": cfg.get("LOCATION"), "workspace_name": cfg["FABRIC_WORKSPACE_NAME"],
            # A capacity the deployment makes is named by what it will be, which is the same before and after it is made:
            # an approval given before the capacity exists still holds when an interrupted apply is run again.
            "capacity_id": (f"new:{cfg.get('FABRIC_CAPACITY_NAME')}:{cfg.get('FABRIC_CAPACITY_CREATE_SKU')}:{cfg.get('FABRIC_CAPACITY_REGION')}"
                            if cfg.get("FABRIC_CAPACITY_CREATE_SKU") else cfg.get("FABRIC_CAPACITY_ID", "")),
            "workspace_chosen": cfg.get("FABRIC_WORKSPACE_ID", ""),
            "suffix": cfg["DEPLOYMENT_SUFFIX"], "user": (account.get("user") or {}).get("name")}


def show_target(ctx: Context, target: dict) -> None:
    made = ctx.state.data["target"]
    ctx.say("Target")
    ctx.say(f"  deployment      {target['suffix']}")
    ctx.say(f"  tenant          {target['tenant_id']}")
    ctx.say(f"  subscription    {target['subscription']}  ({target['subscription_id']})")
    ctx.say(f"  resource group  {target['resource_group']} in {target['location'] or 'a region not chosen yet'}  "
            f"({'made by this deployment' if made.get('resource_group_id') else 'not created yet'})")
    chosen = ctx.cfg.get("FABRIC_WORKSPACE_ID")
    ctx.say(f"  workspace       {target['workspace_name']}  ("
            + (made.get("workspace_id") or (f"{chosen}, an existing empty one you chose" if chosen else "not created yet")) + ")")
    ctx.say(f"  capacity        {capacity_text(ctx, target['capacity_id'])}")
    if creating(ctx) and not ctx.cfg.get("FABRIC_CAPACITY_ID"):
        new = new_capacity(ctx)
        ctx.say(f"                  SKU {new['sku']}; region {new['region'] or 'not chosen'}; resource group {ctx.cfg['RESOURCE_GROUP']}; "
                f"administrator {target['user']}")
        ctx.say("                  Azure bills it for as long as it runs, whether or not anything uses it. The runner never pauses, "
                "resizes or deletes it: pausing is yours, and the clean-up deletes it with the resource group.")
    ctx.say(f"  signed in as    {target['user']}")
    chosen_by = resolve.sources(ctx)
    if chosen_by:
        ctx.say(f"  chosen by       {chosen_by}")


def capacity_text(ctx: Context, capacity_id: str) -> str:
    """The capacity by name and SKU when this run has read the list, so that a wrong one is seen before an approval."""
    if creating(ctx):
        made = ctx.cfg.get("FABRIC_CAPACITY_ID")
        return f"{new_capacity_label(ctx)}, " + (f"made by this deployment  {made}" if made else
                                                 f"to be made in {ctx.cfg['RESOURCE_GROUP']}: it costs money while it runs")
    if not capacity_id:
        return "not chosen yet: see pre.capacity"
    listed = ctx.cache.get("capacities")
    if listed is None:
        return capacity_id
    found = next((entry for entry in listed if str(entry.get("id", "")).lower() == capacity_id.lower()), None)
    return f"{capacity_label(found)}  {capacity_id}" if found else f"{capacity_id}  (not in the list of capacities Fabric gives you)"


def check_target(ctx: Context, target: dict) -> None:
    """A deployment stays in the tenant and the subscription it began in."""
    made = ctx.state.data["target"]
    if ctx.cfg.get("SUBSCRIPTION_ID") and target["subscription_id"] != ctx.cfg["SUBSCRIPTION_ID"]:
        raise Refused(f"The Azure CLI answered for subscription {target['subscription_id']} when asked for "
                      f"{ctx.cfg['SUBSCRIPTION_ID']}, the subscription of this deployment. Nothing was changed.")
    for key, label in (("tenant_id", "tenant"), ("subscription_id", "subscription")):
        if made.get(key) and made[key] != target[key]:
            raise Refused(f"This deployment began in {label} {made[key]}. The Azure CLI is now on {label} {target[key]}. "
                          "Nothing was changed. Sign in to the right one, or start a deployment here: python3 tools/deploy.py plan --new")


def build(args, root: Path, out, adapters=None) -> tuple[Context, list]:
    redact = Redactor()
    say = lambda text: print(redact(text), file=out, flush=True)   # noqa: E731
    made = adapters(redact) if callable(adapters) else (adapters or {})    # the tests hand in stand-ins
    az = made.get("az") or Az(redact)
    # Who answers questions: a script of answers in the tests, the keyboard in a real run. The output may go through a
    # pipe (to tee, to keep what was printed): the questions are still seen and answered. Only preflight and plan ask.
    read = made.get("ask") or (input if adapters is None and sys.stdin.isatty() else None)
    asker = choices.Asker(say, read) if read and not args.no_input and args.mode in ("preflight", "plan") else None
    if args.mode in ("apply", "status") and resolve.given(args):
        raise Refused(f"{', '.join(resolve.given(args))}: a choice is settled by a plan. apply carries out the plan that was "
                      "approved and status reads. Run plan with the option, read it, and apply that.")
    suffix = deployments.choose(args, root, az, say)
    cfg = deployments.check(root, suffix)
    if args.subscription and args.subscription != cfg.get("SUBSCRIPTION_ID"):
        raise Refused(f"Deployment {suffix} is in subscription {cfg.get('SUBSCRIPTION_ID')}, and --subscription names "
                      f"{args.subscription}. A deployment stays in its subscription. For a deployment there: python3 tools/deploy.py "
                      f"plan --new --subscription {args.subscription}")
    # From here on every call of the Azure CLI names the deployment's subscription: the CLI's active subscription,
    # which any terminal can change, decides nothing any more.
    az.pin(cfg.get("SUBSCRIPTION_ID", ""))
    options = options_of(args)
    state = State(deployments.home(root) / suffix, redact)
    ctx = Context(root=root, cfg=cfg, env_file=deployments.env_of(root, suffix), state=state, options=options, redact=redact, az=az,
                  shell=made.get("shell") or Shell(root, redact, out), out=out,
                  **{key: made[key] for key in ("clock", "sleep", "wall") if key in made})
    ctx.offered = {"confirmed": {}, "acknowledged": [], "adopt": {}, "resubmit": set()}
    ctx.me = signed_in_for(ctx)          # before anything else is asked of Azure or Fabric: is this sign-in the deployment's?
    ctx.fabric = made.get("fabric") or make_fabric(az)
    ctx.kusto = made.get("kusto") or Kusto(az, redact)
    ctx.onelake = made.get("onelake") or OneLake(az)
    ctx.asker = asker
    return ctx, select(catalogue(options), options)


def signed_in_for(ctx: Context) -> dict:
    """Who the Azure CLI is for the deployment's subscription. Not who it is for its active one."""
    suffix, wanted = ctx.cfg["DEPLOYMENT_SUFFIX"], ctx.cfg.get("SUBSCRIPTION_ID")
    try:
        return ctx.az.json("account", "show")
    except CloudError as error:
        if "not installed" in str(error):
            raise
        tenant = ctx.state.data["target"].get("tenant_id")
        raise Refused(f"The Azure CLI cannot use subscription {wanted}, which deployment {suffix} is in ({str(error)[:200]}). Sign in "
                      f"to its tenant: az login{' --tenant ' + tenant if tenant else ''}. The runner does not go by the CLI's "
                      f"active subscription; for a deployment elsewhere: python3 tools/deploy.py plan --new. Nothing was "
                      "changed.") from None


def main(argv=None, out=None, root: Path = ROOT, adapters=None) -> int:
    args = parser().parse_args(argv)
    out = out or sys.stdout
    try:
        ctx, steps = build(args, root, out, adapters)
        account = ctx.me
        target = target_of(ctx, account)
        check_target(ctx, target)
        if args.mode != "apply":
            busy = Lock(ctx.state.folder).holder()
            if busy:
                # This run's copy of the checkpoint is older than the one the apply keeps writing: read it, keep nothing.
                ctx.state.frozen = True
                ctx.say(f"An apply is running against this deployment (process {busy.get('pid')} on {busy.get('host')}, since "
                        f"{busy.get('started')}). This run reads, and writes nothing to the checkpoint.")
        if args.recheck:
            ctx.state.data["remembered"] = {}
            ctx.state.save()
        others = [entry for entry in deployments.listed(root) if entry != ctx.cfg["DEPLOYMENT_SUFFIX"]]
        ctx.say(f"Deployment {ctx.cfg['DEPLOYMENT_SUFFIX']}. Settings and checkpoint: .deploy/{ctx.cfg['DEPLOYMENT_SUFFIX']}/."
                + (f" Also in this folder: {', '.join(others)} (--deployment SUFFIX)." if others else "")
                + (" A new one beside it: add --new." if args.mode in ("preflight", "plan") else ""))
        if args.mode in ("preflight", "plan") and not ctx.state.frozen:
            # Every choice is settled here, before anything is looked at: from an option, the settings, the profile, or
            # what the cloud shows. What is left is asked together, when somebody can be asked; else the plan shows it.
            before = dict(ctx.state.data["choices"])
            ctx.options.granted |= resolve.settle(ctx, args, ctx.asker)   # a yes to "create a capacity" approves that step for this plan
            if ctx.state.data["choices"] != before:
                ctx.say("\n" + choices.summary(ctx) + "\n")
            if args.save_profile:
                ctx.say(resolve.save_profile(ctx))
            target = target_of(ctx, account)
        if args.mode == "status":
            return status(ctx, steps, target)
        # One line as each step is looked at. Looking is a dozen or more calls to the Azure CLI, each a few seconds and
        # one of them a minute or two; without the lines a person sees an empty screen and cannot tell waiting from stuck.
        ctx.say(f"Looking at {len([s for s in steps if s.prerequisite]) if args.mode == 'preflight' else len(steps)} steps. "
                "This reads and changes nothing. Each line is one or more calls to the Azure CLI or to Fabric; the whole can "
                "take a few minutes.")

        def progress(step, seconds):
            if seconds is None:
                ctx.say(f"  looking at {step.id}: {step.title}")
            elif seconds >= 5:
                ctx.say(f"    {seconds:.0f} s")
        ctx.progress = progress
        if args.mode == "preflight":
            steps = [step for step in steps if step.prerequisite]
        if args.mode == "apply":
            return run_apply(ctx, steps, args, account)
        lines = make_plan(ctx, steps)
        ctx.say("")
        target = target_of(ctx, account)          # the capacity may have been found by its probe just now
        show_target(ctx, target)
        if args.mode == "preflight":
            print_plan(ctx, lines)                 # the table without an identifier: there is nothing here to approve
            waiting = [line for line in lines if line.decision in ("blocked", "operator")]
            ctx.say("Preflight: " + (f"{len(waiting)} things need you before a deployment can run." if waiting else "nothing stands in the way."))
            ctx.say(f"Preflight is not a plan. The plan to read and approve: python3 tools/deploy.py plan --up-to {args.up_to}")
            return EXIT_BLOCKED if waiting else EXIT_OK
        record = plan_record(ctx, lines, target)
        digest = plan_digest(record)
        print_plan(ctx, lines, digest)
        save_plan(ctx, record, digest)             # what the approval covers, kept beside the checkpoint without secrets
        ctx.state.data["last_plan"] = digest       # so that an apply aimed at another deployment of the folder can say whose plan it is
        ctx.state.save()
        ctx.say("Nothing was changed in Azure or Fabric. To carry this plan out:")
        ctx.say("  " + apply_command(ctx, args, digest))
        waiting = [line.step.id for line in lines if line.decision == "operator" and line.step.id in CONFIRMABLE]
        if waiting:
            ctx.say("Add " + " ".join(f"--confirm {step}" for step in waiting) + " when that step of yours is done.")
        if not args.save_profile and not resolve.profile_path(ctx).exists() and ctx.cfg.get("LOCATION"):
            ctx.say("To have the next deployments in this subscription take the same region, capacity and VM sizes without "
                    "being asked: run this plan once more with --save-profile.")
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
    except KeyboardInterrupt:
        # At a question nothing has happened yet. In an apply, the command the runner was running has been stopped; what
        # it started in Azure or Fabric goes on there, and the next apply looks at it before it does anything.
        print("\nSTOPPED  by Ctrl+C. Run the same command again: it looks at what is there before it does anything.", file=out, flush=True)
        return 130


def apply_command(ctx: Context, args, digest: str) -> str:
    """The apply that carries out the plan just shown, written out to be copied: its deployment by name, and the
    approvals and opt-ins that are part of what was approved."""
    words = ["python3 tools/deploy.py apply", f"--deployment {ctx.cfg['DEPLOYMENT_SUFFIX']}", f"--approve {digest}"]
    if args.up_to != "phase1":
        words.append(f"--up-to {args.up_to}")
    granted = ctx.options.granted
    words += [flag for need, flag in (("roles", "--approve-role-changes"), ("capacity", "--approve-capacity-creation")) if need in granted]
    words += [f"--allow-preview {need.split(':', 1)[1]}" for need in sorted(granted) if need.startswith("preview:")]
    words += [f"--opt-in {need.split(':', 1)[1]}" for need in sorted(granted) if need.startswith("optin:")]
    if ctx.options.phase5a:
        words.append("--enable-phase5a-isolated-simulator")
    if ctx.options.regenerate_history:
        words.append(f"--regenerate-history {ctx.options.regenerate_history}")
    return " ".join(words)


def offered_with(ctx: Context, args, who: str) -> dict:
    """What this apply brings along: confirmations, acknowledgements, and what to do about a notebook run whose fate
    an earlier apply did not learn. Checked here; kept in the checkpoint only once the plan has been accepted."""
    if any(step not in CONFIRMABLE for step in args.confirm):
        raise Refused(f"--confirm takes: {', '.join(CONFIRMABLE)}. Everything else the runner looks at itself.")
    adopt = {}
    for pair in args.adopt_job:
        step, _, job = pair.partition("=")
        if not step or not job:
            raise Refused(f"--adopt-job takes STEP=JOB, for example p1.history=0f1e2d3c-…; got '{pair}'.")
        adopt[step] = job
    if set(adopt) & set(args.resubmit):
        raise Refused(f"--adopt-job and --resubmit both name {', '.join(sorted(set(adopt) & set(args.resubmit)))}. A run is taken, or a new one is started.")
    check = None
    if args.app_check:
        check = ready.read_app_check(ctx, args.app_check, who)
    return {"confirmed": {step: {"at": ctx.state.stamp(), "by": who} for step in args.confirm},
            "acknowledged": list(args.acknowledge), "adopt": adopt, "resubmit": set(args.resubmit), "app_check": check}


def run_apply(ctx: Context, steps: list, args, account: dict) -> int:
    with Lock(ctx.state.folder):
        # Under the lock nothing that was read before it is trusted: the checkpoint and the settings are read again.
        ctx.state.reload()
        settings = deployments.check(ctx.root, ctx.cfg["DEPLOYMENT_SUFFIX"])
        ctx.cfg.clear()
        ctx.cfg.update(settings)
        ctx.cache.clear()
        ctx.offered = offered_with(ctx, args, (account.get("user") or {}).get("name"))
        lines = make_plan(ctx, steps)
        target = target_of(ctx, account)
        show_target(ctx, target)
        record = plan_record(ctx, lines, target)
        digest = plan_digest(record)
        if not args.approve:
            raise Refused(f"apply needs the approval of a plan: --approve {digest} if this is the plan you have read. "
                          "Run plan with the same options to read it.")
        if args.approve != digest:
            whose = deployments.owner_of_plan(ctx.root, args.approve, besides=ctx.cfg["DEPLOYMENT_SUFFIX"])
            if whose:
                raise Refused(f"Plan {args.approve} is the plan of deployment {whose}; this apply works on deployment "
                              f"{ctx.cfg['DEPLOYMENT_SUFFIX']}. Nothing was changed. Use --deployment {whose} to apply that plan.")
            differs = plan_differences(ctx, args.approve, record)
            raise Refused(f"You approved plan {args.approve}; what an apply would do now is plan {digest}. "
                          + ("What differs: " + "; ".join(differs) + ". " if differs else
                             "The target, the sign-in, a setting, an option, a file a step uses, or the state of the cloud has changed since. ")
                          + "Nothing was changed, and nothing of this command was kept. Run plan again and read it.")
        # The plan and its target are the ones that were approved. Only now is anything of this command kept.
        for step_id, said in ctx.offered["confirmed"].items():      # the first confirmation stands: who said so, and when
            ctx.state.data["confirmed"].setdefault(step_id, said)
        for thing in ctx.offered["acknowledged"]:
            if thing not in ctx.state.data["acknowledged"]:
                ctx.state.data["acknowledged"].append(thing)
        if ctx.offered.get("app_check"):
            ctx.state.data["app_check"] = ctx.offered["app_check"]
        if not ctx.state.data["target"].get("tenant_id"):
            ctx.state.data["target"].update(tenant_id=target["tenant_id"], subscription_id=target["subscription_id"])
        ctx.state.save()
        ctx.cache.clear()
        code = apply(ctx, steps, {line.step.id for line in lines if line.decision == "drift"})
        ctx.say("")
        for row in ready.report(ctx, steps, code):
            ctx.say(row)
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
    everything = deployments.listed(ctx.root)
    if len(everything) > 1:
        ctx.say("\nThe deployments of this folder:")
        for entry in everything:
            ctx.say(f"  {deployments.describe(ctx.root, entry)}{'   <- this one' if entry == ctx.cfg['DEPLOYMENT_SUFFIX'] else ''}")
    ctx.say("")
    for row in ready.report(ctx, steps, None):
        ctx.say(row)
    return EXIT_OK
