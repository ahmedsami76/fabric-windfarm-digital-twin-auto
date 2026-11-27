"""Three words for where a deployment stands, kept apart.

  provisioned   every step up to the chosen phase is complete in the checkpoint: the things exist.
  blocked       a step waits for a person, failed, or is still running.
  demo-ready    the demo can be shown now: fresh telemetry measured at this moment, usable data in the Lakehouse,
                and, for the twin, the deployed app's own connection check, read by a person and given to the runner.

Provisioned is not demo-ready. An edge that was stopped last night is provisioned. An app item that exists may hold an
older build or read nothing. An operations agent item says nothing about whether the agent runs or reaches Teams.
What the runner measures itself it says so; what a person told it, it says who and when; what it asked with the
operator's own token it calls that, because the deployed app reads as another identity.
"""
from __future__ import annotations

import re

from .core import EXIT_OK, PHASES, Blocked, Context, Refused, StepFailed
from .steps import freshness, kql_database
from .steps_later import build_stamp

TELEMETRY_MAX_AGE = 180                                  # seconds: the limit of the telemetry gate of Phase 1
APP_MAX_AGE = {"lakehouse": 900, "eventhouse": 120}      # seconds, per route of the twin: what counts as fresh data there
APP_BUILD = "app/overlay/packages/functions/src/build.ts"


def read_app_check(ctx: Context, text: str, who: str) -> dict:
    """What a person read off the twin's own connection check: BUILD,ROUTE,SECONDS."""
    parts = [part.strip() for part in text.split(",")]
    if len(parts) != 3 or not re.fullmatch(r"[0-9a-f]{12}", parts[0]) or parts[1].lower() not in APP_MAX_AGE or not parts[2].isdigit():
        raise Refused("--app-check takes BUILD,ROUTE,SECONDS as the twin's connection check shows them: the build of twelve "
                      "characters, lakehouse or eventhouse, and the age of the newest reading in seconds. For example "
                      "--app-check 455aa9777780,lakehouse,120. Nothing was changed.")
    return {"build": parts[0], "route": parts[1].lower(), "age_seconds": int(parts[2]), "at": ctx.state.stamp(), "by": who}


def _complete(ctx: Context, step_id: str) -> bool:
    return ctx.state.step(step_id).get("status") == "complete"


def telemetry_now(ctx: Context) -> tuple[bool, str]:
    """Measured at this moment in the Eventhouse, not taken from the gate that passed earlier."""
    try:
        if not (ctx.target("workspace_id") and kql_database(ctx)):
            return False, "there is no Eventhouse yet"
        seen = freshness(ctx)
    except (StepFailed, Blocked) as error:
        return False, f"the Eventhouse could not be asked just now ({str(getattr(error, 'detail', error))[:160]})"
    text = (f"{seen['rows']} readings from {seen['turbines']} turbines in the last 5 minutes, the newest "
            f"{seen['age_seconds'] if seen['age_seconds'] is not None else '?'} s old")
    fresh = bool(seen["rows"]) and seen["turbines"] >= 12 and (seen["age_seconds"] if seen["age_seconds"] is not None else 9999) <= TELEMETRY_MAX_AGE
    return fresh, text


def report(ctx: Context, steps: list, code: int | None) -> list[str]:
    """The lines that end an apply and a status. `code` is the apply's exit code, None for status."""
    up_to = ctx.options.up_to
    counted = [step for step in steps if not step.optional and not step.prerequisite]
    left = [step for step in counted if not _complete(ctx, step.id)]
    stopped = [(step.id, ctx.state.step(step.id).get("status"), ctx.state.step(step.id).get("detail", ""))
               for step in steps if ctx.state.step(step.id).get("status") in ("blocked", "failed", "running")]
    # A complete step the runner could not ask about in this run: counted as complete, and named as what the run ended at.
    stopped += [(step.id, "complete and could not be looked at just now", ctx.state.step(step.id)["unseen"].get("detail", ""))
                for step in steps if ctx.state.step(step.id).get("unseen")]
    rows = [f"Where deployment {ctx.cfg['DEPLOYMENT_SUFFIX']} stands, up to {up_to}:"]
    provisioned = not left and (code in (None, EXIT_OK))
    rows.append(f"  provisioned   {'yes' if provisioned else 'no'}: {len(counted) - len(left)} of {len(counted)} steps complete"
                + (f"; next: {left[0].id}" if left else "" if provisioned else "; this run did not get to look at all of them"))
    if stopped:
        rows.append("  blocked       " + "; ".join(f"{step} is {word}" + (f" ({detail[:110]})" if detail else "") for step, word, detail in stopped[:3]))
    why = []
    if not provisioned:
        why.append("not everything is provisioned")
    fresh, telemetry = telemetry_now(ctx)
    if not fresh:
        why.append(f"no fresh telemetry now: {telemetry}")
    lake = ctx.state.step("p1.gate_lakehouse")
    if lake.get("status") != "complete":
        why.append("the Lakehouse's tables have not been measured as populated (p1.gate_lakehouse)")
    said = [f"Eventhouse, measured now: {telemetry}"] if fresh else []
    if lake.get("status") == "complete":
        said.append(f"Lakehouse tables populated, measured {lake.get('at', 'earlier')}")
    if PHASES.index(up_to) >= PHASES.index("phase3"):
        agent = ctx.confirmed("p3.agent_message")
        if agent:
            said.append(f"operations agent: a Teams message seen, confirmed by {agent.get('by')} at {agent.get('at')}")
        elif _complete(ctx, "p3.operations_agent"):
            why.append("the operations agent: an item exists, which is not proof that it is configured, running or delivering "
                       "to Teams. When you have seen its message in Teams: --confirm p3.agent_message")
    if PHASES.index(up_to) >= PHASES.index("phase4"):
        expected, check = build_stamp(ctx, APP_BUILD), ctx.state.data.get("app_check") or ctx.offered.get("app_check")
        probe = (ctx.state.step("p4.gate_data_route").get("evidence") or {}).get("passed")
        if probe:
            said.append("SQL probe with the operator's token passed (not the app's identity)")
        if not check:
            why.append(f"the twin: the deployed app's own connection check has not been given. Open the app, select the badge, and "
                       f"pass what it shows with the next apply: --app-check {expected or 'BUILD'},{'lakehouse' if ctx.options.lakehouse_only else 'eventhouse'},SECONDS")
        elif check["build"] != expected:
            why.append(f"the twin: its connection check named build {check['build']}, and the repository is at {expected}. Deploy "
                       "the app again (apply), then read the check again")
        elif check["route"] != "eventhouse" and not ctx.options.lakehouse_only:
            # This deployment has the service principal: a twin that passes on the Lakehouse route only has fallen back to it.
            why.append("the twin: its connection check passed on the Lakehouse route, and this deployment is to show the live "
                       "values of the Eventhouse. The lines 'Eventhouse route' of the check say what fails: a principal that is "
                       "minutes old, a tenant setting, or the right to read the database (bash app/create-principal.sh --show "
                       "names what exists). Read the check again when they pass: --app-check BUILD,eventhouse,SECONDS. To accept "
                       "the Lakehouse route for this deployment, plan again with --lakehouse-only")
        elif check["age_seconds"] > APP_MAX_AGE[check["route"]]:
            why.append(f"the twin: on its {check['route']} route the newest reading was {check['age_seconds']} s old, more than "
                       f"{APP_MAX_AGE[check['route']]} s. That is a failed connection for a demo: find where the data stops, then read "
                       "the check again")
        else:
            said.append(f"the twin's own check: build {check['build']}, {check['route']} route, newest reading {check['age_seconds']} s "
                        f"old, read by {check.get('by')} at {check.get('at')}")
    rows.append(f"  demo-ready    {'yes' if not why else 'no'}" + (": " + "; ".join(said) if not why else ""))
    for reason in why:
        rows.append(f"                - {reason}")
    if why and said:
        rows.append(f"                what holds: {'; '.join(said)}")
    return rows
