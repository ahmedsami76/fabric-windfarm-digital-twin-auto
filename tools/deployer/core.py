"""The engine of the deployment runner: steps, probes, the plan and its approval, checkpoints, the lock.

Nothing in this file knows Azure or Fabric. cloud.py holds the adapters, steps.py the catalogue.

The rules the engine keeps, whatever the steps are:
  - A step is complete when its probe says so, never because a command returned.
  - Before a step runs, its probe is asked: what is already there is not made a second time.
  - Nothing is written to Azure or Fabric outside apply, and apply needs the approval of one plan.
  - What the checkpoint holds passes through the redactor first, and is written in one move.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

EXIT_OK, EXIT_FAILED, EXIT_REFUSED, EXIT_BLOCKED, EXIT_RUNNING = 0, 1, 2, 3, 4

PHASES = ("preflight", "phase1", "phase2", "phase3", "phase4", "phase5a")


class Refused(Exception):
    """The runner will not go on: wrong target, a changed plan, something that is not the demo's."""


class Blocked(Exception):
    """A person has to do something before the runner can go on."""

    def __init__(self, detail: str, action: str = ""):
        super().__init__(detail)
        self.detail, self.action = detail, action


class StillRunning(Exception):
    """Something asynchronous has not finished within the time the runner waits. Apply again later."""


class StepFailed(Exception):
    """The step was tried and did not work."""


# ------------------------------------------------------------------------------------------ redaction
class Redactor:
    """Takes tokens, keys and connection strings out of any text before it is shown or stored."""

    PATTERNS = (
        (re.compile(r"Endpoint=sb://[^\s\"']+"), "[connection string removed]"),
        (re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{6,}"), "[token removed]"),
        (re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._~+/=-]{16,}"), r"\1 [token removed]"),
        (re.compile(r"(?i)\b(SharedAccessKey|SharedAccessSignature|AccountKey|client_secret|clientSecret|password|pwd|sig)"
                    r"=[^;&\s\"']+"), r"\1=[removed]"),
        (re.compile(r'(?i)("(?:accessToken|access_token|refresh_token|id_token|primaryConnectionString|'
                    r'secondaryConnectionString|primaryKey|secondaryKey|clientSecret|client_secret|password|'
                    r'secretText|connectionString|sasToken)"\s*:\s*)"[^"]*"'), r'\1"[removed]"'),
    )

    def __init__(self):
        self._known: set[str] = set()

    def learn(self, value: str | None) -> None:
        """A value this run has handled as a secret: removed wherever it appears, whatever it looks like."""
        if value and len(value) >= 8:
            self._known.add(value)

    def __call__(self, text) -> str:
        text = text if isinstance(text, str) else str(text)
        for value in sorted(self._known, key=len, reverse=True):
            text = text.replace(value, "[secret removed]")
        for pattern, replacement in self.PATTERNS:
            text = pattern.sub(replacement, text)
        return text


# ----------------------------------------------------------------------------------------- checkpoint
class State:
    """The checkpoint of one deployment: what was done, what is under way, what a person confirmed."""

    def __init__(self, folder: Path, redact: Redactor, clock: Callable[[], float] = time.time):
        self.folder, self.path = Path(folder), Path(folder) / "state.json"
        self._redact, self._clock = redact, clock
        self.data = {"version": 1, "target": {}, "steps": {}, "pending": {}, "confirmed": {}, "acknowledged": []}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except ValueError as error:
                raise Refused(f"The checkpoint {self.path} cannot be read ({error}). It is written in one move, so this is "
                              "not a half-written file: someone changed it. Restore it or move it away.") from None

    def stamp(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._clock()))

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        text = self._redact(json.dumps(self.data, indent=2, sort_keys=True)) + "\n"
        handle, temporary = tempfile.mkstemp(dir=self.folder, prefix=".state-", suffix=".tmp")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                out.write(text)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, self.path)       # one move: a reader sees the old file or the new one
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def step(self, step_id: str) -> dict:
        return self.data["steps"].get(step_id, {})

    def mark(self, step_id: str, status: str, **more) -> None:
        entry = dict(self.data["steps"].get(step_id, {}))
        entry.update(status=status, at=self.stamp(), **more)
        self.data["steps"][step_id] = entry
        self.save()

    def note(self, step_id: str, **evidence) -> None:
        """Facts a step wants kept, such as the identifier of a job it started. No secrets."""
        entry = dict(self.data["steps"].get(step_id, {}))
        kept = dict(entry.get("evidence", {}))
        kept.update(evidence)
        entry["evidence"] = kept
        self.data["steps"][step_id] = entry
        self.save()

    def pending(self, step_id: str) -> dict:
        return self.data["pending"].get(step_id, {})

    def set_pending(self, step_id: str, key: str, value: dict) -> None:
        self.data["pending"].setdefault(step_id, {})[key] = dict(value, at=self.stamp())
        self.save()

    def clear_pending(self, step_id: str, key: str) -> None:
        if key in self.data["pending"].get(step_id, {}):
            del self.data["pending"][step_id][key]
            if not self.data["pending"][step_id]:
                del self.data["pending"][step_id]
            self.save()


def _alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


class Lock:
    """One apply at a time for one deployment. The checkpoint lives on this computer, and so does the lock."""

    def __init__(self, folder: Path, clock: Callable[[], float] = time.time):
        self.path, self._clock = Path(folder) / "apply.lock", clock

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        me = {"pid": os.getpid(), "host": socket.gethostname(),
              "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self._clock()))}
        for attempt in (1, 2):
            try:
                handle = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                try:
                    other = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    other = {}
                if attempt == 1 and other.get("host") == me["host"] and not _alive(other.get("pid")):
                    os.unlink(self.path)           # the apply that held it has ended without letting go
                    continue
                raise Refused(f"Another apply is running against this deployment: process {other.get('pid', '?')} on "
                              f"{other.get('host', '?')}, started {other.get('started', '?')}. Wait for it. If you are "
                              f"certain that it is gone, delete {self.path}.") from None
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(me, out)
            return self
        raise Refused(f"Could not take the lock {self.path}.")

    def __exit__(self, *_):
        try:
            os.unlink(self.path)
        except OSError:
            pass


# ----------------------------------------------------------------------------------------- steps
@dataclass
class Probe:
    """What a step found when it looked, without changing anything."""
    state: str                      # done | todo | blocked | unverified
    detail: str = ""
    evidence: dict = field(default_factory=dict)
    action: str = ""                # for blocked: what the operator has to do, exactly


def done(detail: str = "", **evidence) -> Probe:
    return Probe("done", detail, evidence)


def todo(detail: str = "") -> Probe:
    return Probe("todo", detail)


def blocked(detail: str, action: str = "") -> Probe:
    return Probe("blocked", detail, action=action)


def unverified(detail: str) -> Probe:
    """Passes, and says that the runner could not check it."""
    return Probe("unverified", detail)


@dataclass
class Step:
    id: str
    phase: str
    title: str
    probe: Callable[["Context"], Probe]
    act: Callable[["Context"], None] | None = None      # the write. None: a check, a gate, or an operator's step
    manual: str | Callable[["Context"], str] = ""        # what the operator does when there is nothing the runner may do
    needs: tuple = ()               # approvals and opt-ins: "roles", "preview:<name>", "optin:<name>"
    inputs: tuple = ()              # files of the repository whose content is part of the plan
    wait_seconds: int = 0           # how long apply keeps asking the probe before it gives up
    optional: bool = False          # an operator's step that does not hold the deployment up
    observable: bool = True         # False: the probe can only read the checkpoint, so it cannot see drift
    witness: str = ""               # for a step nothing can look at from outside: the later step that proves it
    prerequisite: bool = False      # a check that preflight shows: a right, a setting, a tool
    writes: str = ""                # what it changes, in words, for the plan
    basis: str = ""                 # the documented operation it rests on
    proof: str = "offline"          # live | offline | none: how far this step has been proven


@dataclass
class Options:
    up_to: str = "phase1"
    granted: set = field(default_factory=set)      # "roles", "preview:ontology", "optin:pip-jobs", ...
    phase5a: bool = False
    regenerate_history: str = ""     # a label; the history is generated again once for each new label
    limits: dict = field(default_factory=lambda: {"operation": 900, "job": 2700, "poll": 10})


class Context:
    """What a step is handed: the settings, the adapters, the checkpoint, and a way to speak."""

    def __init__(self, *, root: Path, cfg: dict, env_file: Path, state: State, options: Options, redact: Redactor,
                 az=None, fabric=None, kusto=None, shell=None, onelake=None, out=None,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep,
                 wall: Callable[[], float] = time.time):
        self.root, self.cfg, self.env_file = Path(root), cfg, Path(env_file)
        self.state, self.options, self.redact = state, options, redact
        self.az, self.fabric, self.kusto, self.shell, self.onelake = az, fabric, kusto, shell, onelake
        self._out, self.clock, self.sleep, self.wall = out, clock, sleep, wall
        self.cache: dict = {}
        self.current: str = ""          # the step that is running, for the helpers that keep pending work
        # Called before a step is looked at, and after it with the seconds it took: a person sees life, and the first
        # real numbers of how long looking takes come out of every run.
        self.progress: Callable[[Step, float | None], None] | None = None

    def say(self, text: str = "") -> None:
        print(self.redact(text), file=self._out, flush=True)

    def remember(self, key: str, make: Callable[[], object]):
        """Asks the cloud once per run for the same thing. Cleared after every write."""
        if key not in self.cache:
            self.cache[key] = make()
        return self.cache[key]

    def confirmed(self, step_id: str) -> dict | None:
        return self.state.data["confirmed"].get(step_id)

    def target(self, key: str, default=None):
        return self.state.data["target"].get(key, default)

    def set_target(self, **values) -> None:
        self.state.data["target"].update(values)
        self.state.save()


# ----------------------------------------------------------------------------------------- plan
@dataclass
class Line:
    step: Step
    probe: Probe
    decision: str                   # done | run | operator | needs | blocked | drift | optional
    missing: tuple = ()


def decide(ctx: Context, step: Step, probe: Probe) -> Line:
    saved = ctx.state.step(step.id).get("status")
    if probe.state in ("done", "unverified"):
        return Line(step, probe, "done")
    missing = tuple(need for need in step.needs if need not in ctx.options.granted)
    if step.optional:
        return Line(step, probe, "optional")
    if probe.state == "blocked":
        return Line(step, probe, "blocked")
    if saved == "complete" and step.observable:
        # The checkpoint says done and the cloud says otherwise: something changed behind the runner's back.
        return Line(step, probe, "drift", missing)
    if missing:
        return Line(step, probe, "needs", missing)
    if step.act is None:
        return Line(step, probe, "operator")
    return Line(step, probe, "run")


def select(steps: list[Step], options: Options) -> list[Step]:
    """The steps up to the chosen phase. Phase 5a only when it was asked for by its own option."""
    last = PHASES.index(options.up_to)
    wanted = set(PHASES[:last + 1]) - {"phase5a"}
    if options.phase5a:
        wanted.add("phase5a")
    return [step for step in steps if step.phase in wanted]


def look(ctx: Context, step: Step, quiet: bool = False) -> Probe:
    """Asks a step's probe. A question that could not be asked becomes that step's line, and the others are still asked:
    one slow or failing call does not cost the whole plan."""
    if ctx.progress and not quiet:
        ctx.progress(step, None)
    began = ctx.clock()
    try:
        return step.probe(ctx)
    except Blocked as stop:
        return Probe("blocked", stop.detail, action=stop.action)
    except StepFailed as failure:
        return Probe("blocked", f"could not be looked at: {failure}",
                     action="Run the same command again. If it says the same, that line is what to send.")
    finally:
        if ctx.progress and not quiet:
            ctx.progress(step, ctx.clock() - began)


def make_plan(ctx: Context, steps: list[Step]) -> list[Line]:
    return [decide(ctx, step, look(ctx, step)) for step in steps]


def file_digest(root: Path, relative: str) -> str:
    path = Path(root) / relative
    if not path.exists():
        return "missing"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


TARGET_KEYS = ("tenant_id", "subscription_id", "resource_group", "location", "workspace_name", "capacity_id", "suffix")


def plan_hash(ctx: Context, lines: list[Line], target: dict) -> str:
    """What an approval covers: the target, the options, every step with the files it uses, and any drift.

    Whether a step is done already is not part of it, so the same approval resumes an interrupted apply.
    Drift is part of it: when the cloud no longer matches the checkpoint, the old approval is void.
    """
    body = {
        "target": {key: target.get(key) for key in TARGET_KEYS},
        "up_to": ctx.options.up_to, "phase5a": ctx.options.phase5a,
        "granted": sorted(ctx.options.granted), "regenerate_history": ctx.options.regenerate_history,
        "steps": [[line.step.id, [file_digest(ctx.root, name) for name in line.step.inputs]] for line in lines],
        "drift": sorted(line.step.id for line in lines if line.decision == "drift"),
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode("utf-8")).hexdigest()[:12]


WORDS = {"done": "done", "run": "will run", "operator": "YOUR STEP", "needs": "needs approval", "blocked": "BLOCKED",
         "drift": "DRIFT, will be redone", "optional": "optional, yours"}


def manual_text(ctx: Context, step: Step, probe: Probe) -> str:
    text = step.manual(ctx) if callable(step.manual) else step.manual
    return probe.action or text


NEED_HELP = {
    "roles": "role assignments, each limited to the demo's resource group or workspace. Add --approve-role-changes to "
             "plan and apply after reading which ones.",
}


def explain_need(need: str) -> str:
    if need in NEED_HELP:
        return NEED_HELP[need]
    kind, _, name = need.partition(":")
    if kind == "preview":
        return f"a preview feature ({name}). Add --allow-preview {name} to plan and apply, or do the step by hand."
    return f"an opt-in ({name}). Add --opt-in {name} to plan and apply, or do the step by hand."


def print_plan(ctx: Context, lines: list[Line], digest: str) -> None:
    phase = None
    for line in lines:
        if line.step.phase != phase:
            phase = line.step.phase
            ctx.say(f"\n{phase}")
        word = WORDS[line.decision]
        ctx.say(f"  {line.step.id:<28} {word:<22} {line.step.title}")
        if line.probe.detail and line.decision in ("done", "blocked", "drift", "optional"):
            ctx.say(f"  {'':<28} {'':<22}   {line.probe.detail}")
        if line.decision == "run" and line.step.writes:
            ctx.say(f"  {'':<28} {'':<22}   changes: {line.step.writes}")
        if line.decision in ("needs", "drift") and line.missing:
            for need in line.missing:
                ctx.say(f"  {'':<28} {'':<22}   needs {explain_need(need)}")
        if line.decision in ("operator", "blocked", "optional"):
            for row in manual_text(ctx, line.step, line.probe).splitlines():
                ctx.say(f"  {'':<28} {'':<22}   > {row}")
    counts = {word: sum(1 for line in lines if line.decision == word) for word in WORDS}
    ctx.say(f"\n{counts['done']} done, {counts['run'] + counts['drift']} for the runner, {counts['operator']} for you, "
            f"{counts['needs']} waiting for an approval, {counts['blocked']} blocked, {counts['optional']} optional.")
    ctx.say(f"Plan {digest}")


# ----------------------------------------------------------------------------------------- apply
def _wait_for(ctx: Context, step: Step, first: Probe | None = None) -> Probe:
    """Asks the probe until it says done, or the step's time is over. Always asks at least once."""
    probe = first or look(ctx, step, quiet=True)
    deadline = ctx.clock() + step.wait_seconds
    while probe.state not in ("done", "unverified", "blocked") and ctx.clock() < deadline:
        ctx.sleep(ctx.options.limits["poll"])
        ctx.cache.clear()
        probe = look(ctx, step, quiet=True)
    return probe


def _report_block(ctx: Context, step: Step, probe: Probe, why: str) -> int:
    ctx.state.mark(step.id, "blocked", detail=probe.detail or why)
    ctx.say(f"\nblocked  {step.id}: {step.title}")
    ctx.say(f"  {probe.detail or why}")
    action = manual_text(ctx, step, probe)
    if action:
        ctx.say("  What to do:")
        for row in action.splitlines():
            ctx.say(f"    {row}")
    ctx.say("  Then run the same apply again. It looks at the result before it goes on.")
    return EXIT_BLOCKED


def apply(ctx: Context, steps: list[Step], approved: set[str]) -> int:
    """Runs the steps in order and stops at the first that needs a person, fails, or is still running."""
    for step in steps:
        ctx.current = step.id
        probe = look(ctx, step, quiet=True)
        saved = ctx.state.step(step.id)
        if probe.state in ("done", "unverified"):
            if saved.get("status") != "complete":
                ctx.state.mark(step.id, "complete", detail=probe.detail, evidence={**saved.get("evidence", {}), **probe.evidence},
                               verified=probe.state == "done")
            ctx.say(f"done     {step.id}: {probe.detail or step.title}")
            continue
        if step.optional:
            ctx.say(f"optional {step.id}: {step.title} (yours, when you want it)")
            continue
        if probe.state == "blocked":
            return _report_block(ctx, step, probe, "")
        if saved.get("status") == "complete" and step.observable and step.id not in approved:
            raise Refused(f"{step.id} was complete, and now: {probe.detail or 'it is not there'}. Something changed outside "
                          "the runner. Run plan again and read what it says about drift before you approve.")
        missing = [need for need in step.needs if need not in ctx.options.granted]
        if missing:
            return _report_block(ctx, step, Probe("blocked", "This step needs " + "; ".join(explain_need(n) for n in missing)), "")
        if step.act is None:
            probe = _wait_for(ctx, step, probe)
            if probe.state in ("done", "unverified"):
                ctx.state.mark(step.id, "complete", detail=probe.detail, evidence=probe.evidence, verified=probe.state == "done")
                ctx.say(f"done     {step.id}: {probe.detail or step.title}")
                continue
            return _report_block(ctx, step, probe, "Not there yet.")
        ctx.say(f"\nrunning  {step.id}: {step.title}")
        ctx.state.mark(step.id, "running", attempts=saved.get("attempts", 0) + 1)
        try:
            step.act(ctx)
        except Blocked as stop:
            return _report_block(ctx, step, Probe("blocked", stop.detail, action=stop.action), "")
        except StillRunning as wait:
            ctx.say(f"waiting  {step.id}: {wait}")
            ctx.say("  Nothing is lost. Run the same apply again later: it asks about what is under way before anything else.")
            return EXIT_RUNNING
        except StepFailed as failure:
            ctx.state.mark(step.id, "failed", detail=str(failure))
            ctx.say(f"FAILED   {step.id}: {failure}")
            return EXIT_FAILED
        ctx.cache.clear()
        probe = _wait_for(ctx, step)
        if probe.state == "blocked":
            return _report_block(ctx, step, probe, "")
        if probe.state == "todo" and step.witness:
            # Nothing outside can be asked about this step. It ended without an error; the step named proves it later.
            ctx.state.mark(step.id, "complete", detail=f"ran to the end; proven by {step.witness}", verified=False)
            ctx.say(f"done     {step.id}: ran to the end. Nothing to look at from outside; {step.witness} proves it")
            continue
        if probe.state not in ("done", "unverified"):
            # The command returned without an error, and what it should have made is not there.
            ctx.state.mark(step.id, "failed", detail=f"ran without an error, and the result is not there: {probe.detail}")
            ctx.say(f"FAILED   {step.id}: the step ran without an error, and its result is not there. {probe.detail}")
            return EXIT_FAILED
        ctx.state.mark(step.id, "complete", detail=probe.detail,
                       evidence={**ctx.state.step(step.id).get("evidence", {}), **probe.evidence}, verified=probe.state == "done")
        ctx.say(f"done     {step.id}: {probe.detail or step.title}")
    ctx.current = ""
    return EXIT_OK
