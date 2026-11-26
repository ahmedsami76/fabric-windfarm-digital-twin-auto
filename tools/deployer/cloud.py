"""The adapters of the deployment runner: the Azure CLI, the Fabric API, the Eventhouse, OneLake, the shell.

Every call to the outside goes through one of these five, which is where the tests put their stand-ins.
Tokens come from the Azure CLI's sign-in, are handed to the redactor at once, and are sent only to the
service they were asked for.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .core import Blocked, Redactor, StepFailed, StillRunning

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from operations_agent import DEFAULT_API, UNREACHED, Fabric, FabricError, api_address  # noqa: E402  (the client of Phase 5b: 429, long-running calls, one origin)

FABRIC_RESOURCE = "https://api.fabric.microsoft.com"
STORAGE_RESOURCE = "https://storage.azure.com"
SQL_RESOURCE = "https://database.windows.net"
ONELAKE = "https://onelake.dfs.fabric.microsoft.com"
JOB_DONE = {"Completed", "Failed", "Cancelled", "Deduped"}
# Words with which the Azure CLI says that the thing asked for does not exist.
NOT_FOUND = ("ResourceNotFound", "ResourceGroupNotFound", "was not found", "could not be found", "not found",
             "does not exist", "NotFound", "No registered resource provider")


class CloudError(FabricError, StepFailed):
    """Azure or Fabric refused, or could not be reached. The text is for the person and holds no secret."""

    def __init__(self, text: str, status: int | None = None, code: str = ""):
        super().__init__(text, status, code)


class RunnerFabric(Fabric):
    """The Fabric client of Phase 5b, with its refusals turned into failures of the step that made the call.

    An apply can last longer than a token. The client asks the Azure CLI for a new one when its own is twenty
    minutes old; the CLI answers from its cache until the token is close to its end.
    """
    FRESH_SECONDS = 1200

    def __init__(self, az: "Az", clock=None, **more):
        import time
        self._az, self._clock = az, clock or time.monotonic
        self._issued = self._clock()
        super().__init__(az.token(FABRIC_RESOURCE), **more)

    def call(self, method: str, path: str, body=None):
        if self._clock() - self._issued > self.FRESH_SECONDS:
            self._token, self._issued = self._az.token(FABRIC_RESOURCE), self._clock()
        try:
            return super().call(method, path, body)
        except CloudError:
            raise
        except FabricError as error:
            raise CloudError(str(error), error.status, error.code) from None


# Command groups that take no --subscription: seen with Azure CLI 2.93.0, where `az extension list --subscription X` and
# `az config get --subscription X` end with "unrecognized arguments", and the help of `az ad ...` does not list the option.
NO_SUBSCRIPTION = ("ad", "extension", "config", "version", "login", "logout")
TRIES = 3            # how often a read that gets no answer, or a connection that cannot be made, is tried
SHARES = (1 / 6, 1 / 3, 1 / 2)      # of an `az` read's time, per try
FIRST_READ_SECONDS = 60
SPLIT_FROM = 120     # seconds: a read with less time than this is asked once (its first try would have under 20 s)
READ_WORDS = ("show", "list", "list-usage", "list-skus", "check-name", "exists", "get-access-token")


class Az:
    """The Azure CLI, with the sign-in the operator made. Read with show and list, write only inside apply.

    Once a deployment is known, every call names the deployment's subscription itself (pin). The CLI's active
    subscription, which another terminal can change at any moment, then no longer decides where a call goes or which
    tenant a token is for."""

    def __init__(self, redact: Redactor, run=subprocess.run, request=None):
        self._redact, self._run, self._request = redact, run, request
        self.subscription = ""

    def pin(self, subscription_id: str) -> None:
        self.subscription = subscription_id or ""

    def pinned(self, args) -> list:
        args = list(args)
        if self.subscription and args and args[0] not in NO_SUBSCRIPTION and "--subscription" not in args:
            args += ["--subscription", self.subscription]
        return args

    @staticmethod
    def reads(args) -> bool:
        """A call that changes nothing, and so can be made again when it gets no answer."""
        args = [str(arg) for arg in args]
        if args[:1] == ["rest"]:
            return "--method" in args and args[args.index("--method") + 1].lower() == "get"
        words = args[:next((n for n, arg in enumerate(args) if arg.startswith("-")), len(args))]       # the command, no values
        return any(word in READ_WORDS for word in words)

    def _call(self, args, timeout):
        # A read is asked up to TRIES times within its time, each try with more of it (a sixth, a third, a half): on
        # 26 November 2026 `az resource list` for one resource group stood for 180 seconds on a workstation where the
        # same question, asked again, took two. A read that is slow and not stuck still has half of the time in one
        # piece. A call that changes something is made once, with all of its time.
        shares = SHARES if self.reads(args) and timeout >= SPLIT_FROM else (1.0,)
        for attempt, share in enumerate(shares, start=1):
            try:
                # No keyboard for the CLI: with its output captured, a question it asked (to install an extension, say)
                # would be seen by nobody, and it would wait for an answer until the time limit.
                return self._run(["az", *self.pinned(args)], capture_output=True, text=True, timeout=max(1, round(timeout * share)),
                                 stdin=subprocess.DEVNULL)
            except FileNotFoundError:
                raise CloudError("The Azure CLI (az) is not installed on this computer.") from None
            except subprocess.TimeoutExpired:
                if attempt == len(shares):
                    tries = f", asked {attempt} times" if attempt > 1 else ""
                    raise CloudError(f"az {' '.join(args[:3])} did not answer within {timeout} seconds{tries}.") from None

    def json(self, *args, timeout: int = 180):
        """The parsed answer. Raises when the CLI fails."""
        result = self._call([*args, "--output", "json"], timeout)
        if result.returncode != 0:
            raise CloudError(self._redact(f"az {' '.join(args[:4])} failed: {_tail(result.stderr)}"))
        text = result.stdout.strip()
        return json.loads(text) if text else None

    def maybe(self, *args, timeout: int = 180):
        """The parsed answer, or None when the thing does not exist. Any other failure raises."""
        result = self._call([*args, "--output", "json"], timeout)
        if result.returncode != 0:
            if any(word in result.stderr for word in NOT_FOUND):
                return None
            raise CloudError(self._redact(f"az {' '.join(args[:4])} failed: {_tail(result.stderr)}"))
        text = result.stdout.strip()
        return json.loads(text) if text else None

    def run(self, *args, timeout: int = 1800) -> None:
        result = self._call([*args, "--output", "none"], timeout)
        if result.returncode != 0:
            raise CloudError(self._redact(f"az {' '.join(args[:4])} failed: {_tail(result.stderr)}"))

    def token(self, resource: str) -> str:
        result = self._call(["account", "get-access-token", "--resource", resource, "--query", "accessToken", "--output", "tsv"], 120)
        token = result.stdout.strip()
        if result.returncode != 0 or not token:
            raise Blocked(self._redact(f"The Azure CLI gave no token for {resource}: {_tail(result.stderr)}"),
                          f"az login --scope {resource}/.default")
        self._redact.learn(token)
        return token

    def graph(self, path: str):
        """One read of Microsoft Graph, with a token for the tenant of the pinned subscription. None when Graph has no
        such object. (`az ad` follows the CLI's active subscription and takes no --subscription, so it is not used.)"""
        result = self._call(["account", "get-access-token", "--resource-type", "ms-graph", "--query", "accessToken", "--output", "tsv"], 120)
        token = result.stdout.strip()
        if result.returncode != 0 or not token:
            raise CloudError(self._redact(f"The Azure CLI gave no token for Microsoft Graph: {_tail(result.stderr)}"))
        self._redact.learn(token)
        status, body = (self._request or http)("GET", "https://graph.microsoft.com/v1.0/" + path.lstrip("/"), token, timeout=60)
        if status == 404:
            return None
        if status != 200:
            raise CloudError(self._redact(f"Microsoft Graph answered {status} to {path.split('?')[0]}: {bytes(body)[:300]!r}"))
        return json.loads(body)


def _tail(text: str, lines: int = 6) -> str:
    rows = [row for row in (text or "").strip().splitlines() if row.strip()]
    return " | ".join(rows[-lines:])[:900]


class Shell:
    """The repository's own scripts, started through bash, their output shown through the redactor."""

    QUIET_NOTE = 60          # seconds without a line of output after which the runner says that it is still waiting

    def __init__(self, root: Path, redact: Redactor, out=None, popen=subprocess.Popen):
        self.root, self._redact, self._out, self._popen = Path(root), redact, out, popen

    @staticmethod
    def _stop(process) -> None:
        """Ends a command and everything it started: they run in a session of their own, which is ended as a whole."""
        import os
        import signal
        for sign, grace in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
            try:
                os.killpg(process.pid, sign)
            except (ProcessLookupError, PermissionError, AttributeError, TypeError, OSError):
                try:
                    process.terminate() if sign == signal.SIGTERM else process.kill()
                except Exception:      # noqa: BLE001  it has ended by itself
                    return
            try:
                process.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                continue

    def run(self, argv: list[str], env: dict | None = None, cwd: Path | None = None, timeout: int = 5400) -> tuple[int, str]:
        """Runs a command, shows its output as it comes, and holds it to a time limit by the clock.

        The limit also ends a command that prints nothing: its output is read by a thread of its own, so that waiting
        for a line never keeps the runner from looking at the clock. On the limit, and on Ctrl+C, the command and
        whatever it started on this computer are stopped. What it began in Azure or Fabric goes on there; the step
        looks at that before anything is tried again."""
        import os
        import queue
        import threading
        import time
        full = dict(os.environ)
        full.update(env or {})
        try:
            process = self._popen(argv, cwd=str(cwd or self.root), env=full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, text=True, start_new_session=True)
        except FileNotFoundError as error:
            raise CloudError(f"{argv[0]} is not installed on this computer ({error}).") from None
        rows: queue.Queue = queue.Queue()

        def read() -> None:
            try:
                for row in process.stdout:
                    rows.put(row)
            finally:
                rows.put(None)
        threading.Thread(target=read, daemon=True).start()
        kept: list[str] = []
        started = last = time.monotonic()
        late = CloudError(f"{' '.join(argv[:3])} did not finish within {timeout} seconds. The runner stopped it and what it had "
                          "started on this computer. Run the same apply again: it looks at what is there before it does anything.")
        try:
            while True:
                left = started + timeout - time.monotonic()
                if left <= 0:
                    self._stop(process)
                    raise late
                try:
                    row = rows.get(timeout=min(left, self.QUIET_NOTE))
                except queue.Empty:
                    now = time.monotonic()
                    if now - started < timeout:
                        print(f"      . still running after {now - started:.0f} s; no line for {now - last:.0f} s (limit {timeout} s)",
                              file=self._out, flush=True)
                    continue
                if row is None:
                    break
                last = time.monotonic()
                row = self._redact(row.rstrip("\n"))
                kept.append(row)
                del kept[:-60]
                print(f"      | {row}", file=self._out, flush=True)
            try:
                code = process.wait(timeout=max(1.0, started + timeout - time.monotonic()))
            except subprocess.TimeoutExpired:
                self._stop(process)
                raise late from None
        except KeyboardInterrupt:
            self._stop(process)
            raise
        return code, "\n".join(kept)

    def which(self, tool: str) -> bool:
        import shutil
        return shutil.which(tool) is not None

    def capture(self, argv: list[str], env: dict | None = None, cwd: Path | None = None, timeout: int = 180) -> tuple[int, str]:
        """A short command whose answer is read, not shown. What it prints still passes the redactor before it is used."""
        import os
        full = dict(os.environ)
        full.update(env or {})
        try:
            result = subprocess.run(argv, cwd=str(cwd or self.root), env=full, capture_output=True, text=True, timeout=timeout,
                                    stdin=subprocess.DEVNULL)
        except FileNotFoundError:
            return 127, ""
        except subprocess.TimeoutExpired:
            return 124, ""
        return result.returncode, self._redact(result.stdout + result.stderr)

    def must(self, argv: list[str], env: dict | None = None, cwd: Path | None = None, timeout: int = 5400) -> str:
        code, text = self.run(argv, env, cwd, timeout)
        if code != 0:
            raise CloudError(f"{' '.join(argv[:4])} ended with exit code {code}. Its last lines are above.")
        return text


def http(method: str, url: str, token: str, body=None, headers: dict | None = None, timeout: int = 60, read: bool = False,
         sleep=time.sleep):
    """One request outside the Fabric API. Returns (status, parsed body or text). The token goes over https only."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise CloudError(f"Refused to send a token to {url}: not https.")
    data = None if body is None else json.dumps(body).encode("utf-8")
    host, read = urllib.parse.urlsplit(url).netloc, read or method == "GET"
    for attempt in range(1, TRIES + 1):
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", f"Bearer {token}")
        if data is not None:
            request.add_header("Content-Type", "application/json; charset=utf-8")
        for name, value in (headers or {}).items():
            request.add_header(name, value)
        try:
            # The first try of a read has a minute at most: a connection that hangs is given up sooner and made anew.
            with urllib.request.urlopen(request, timeout=min(timeout, FIRST_READ_SECONDS) if read and attempt == 1 else timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()
        except urllib.error.URLError as error:
            # While the connection was made or the request sent: nothing has been acted on, so any request is made again.
            if attempt == TRIES:
                raise CloudError(f"Could not reach {host}, in {TRIES} tries: {error.reason}", code=UNREACHED) from None
        except OSError as error:
            # While waiting for the answer: the request went out. Only a read is asked again.
            if not read or attempt == TRIES:
                raise CloudError(f"{host} did not answer a request it was sent ({method}): {error}", code=UNREACHED) from None
        sleep(2.0 * attempt)


class Kusto:
    """Queries and management commands against the KQL database, over the REST interface of the Eventhouse.

    The audience of the token is what the cluster itself names (GET /v1/rest/auth/metadata), as the Kusto
    client libraries do. From a workstation with the Azure CLI's token this has not run on a tenant yet.
    """

    def __init__(self, az: Az, redact: Redactor, request=http):
        self._az, self._redact, self._request, self._audience = az, redact, request, {}

    def _token(self, uri: str) -> str:
        if uri not in self._audience:
            audience = uri
            try:
                with urllib.request.urlopen(f"{uri}/v1/rest/auth/metadata", timeout=30) as response:
                    audience = json.loads(response.read())["AzureAD"]["KustoServiceResourceId"]
            except Exception:   # noqa: BLE001  (no metadata: the cluster's own address is the documented audience)
                pass
            self._audience[uri] = audience
        return self._az.token(self._audience[uri])

    def rows(self, uri: str, database: str, csl: str, mgmt: bool = False) -> list[dict]:
        # A query changes nothing and is asked again when no answer comes, and so is a command that only shows. Any other
        # management command is sent once.
        read = not mgmt or csl.lstrip().lower().startswith(".show ")
        status, raw = self._request("POST", f"{uri.rstrip('/')}/v1/rest/{'mgmt' if mgmt else 'query'}", self._token(uri),
                                    {"db": database, "csl": csl}, timeout=180, **({"read": True} if read else {}))
        if status in (401, 403):
            raise Blocked(f"The Eventhouse answered {status} to the signed-in user.",
                          "Check that you are the owner of the KQL database or have a role in the workspace, then run apply again.")
        if status != 200:
            raise CloudError(self._redact(f"The Eventhouse answered {status}: {raw[:600].decode('utf-8', 'replace')}"))
        tables = json.loads(raw).get("Tables", [])
        if not tables:
            return []
        names = [column["ColumnName"] for column in tables[0]["Columns"]]
        return [dict(zip(names, row)) for row in tables[0]["Rows"]]


class OneLake:
    """Reads one small file from a Lakehouse over the OneLake API. Used for the result of the gate notebook."""

    def __init__(self, az: Az, request=http):
        self._az, self._request = az, request

    def read(self, workspace_id: str, item_id: str, path: str) -> bytes | None:
        status, raw = self._request("GET", f"{ONELAKE}/{workspace_id}/{item_id}/{path.lstrip('/')}",
                                    self._az.token(STORAGE_RESOURCE), timeout=60)
        return raw if status == 200 else None


def make_fabric(az: Az) -> RunnerFabric:
    return RunnerFabric(az, poll_seconds=5.0)


# ------------------------------------------------------------------------- work that outlives one apply
def _on_the_api(fabric, location: str) -> str:
    try:
        return api_address(getattr(fabric, "api", DEFAULT_API), location)
    except FabricError as error:
        raise CloudError(str(error)) from None


def operation(ctx, key: str, start):
    """A Fabric call that may answer 202. Its address is kept in the checkpoint before the first wait, so that
    an apply that is interrupted, or gives up waiting, asks about the same operation next time and starts no second one.

    start() makes the request and returns what Fabric.call returns: (status, headers, body).
    """
    step, fabric = ctx.current, ctx.fabric
    location = (ctx.state.pending(step).get(key) or {}).get("location")
    if location:
        # A checkpoint of 26 November 2026 holds the address of an operation on a regional host, as Fabric named it.
        location = _on_the_api(fabric, location)
    if not location:
        status, headers, payload = start()
        if status != 202:
            return payload
        location = next((value for name, value in headers.items() if name.lower() == "location"), None)
        if not location:
            raise CloudError("Fabric accepted the request and did not say where to ask for the result.")
        location = _on_the_api(fabric, location)
        ctx.state.set_pending(step, key, {"location": location})
    deadline = ctx.clock() + ctx.options.limits["operation"]
    while True:
        try:
            state = fabric.get(location) or {}
        except FabricError as error:
            if error.status == 404:        # Fabric has forgotten the operation: the step looks for the result itself
                ctx.state.clear_pending(step, key)
                return None
            raise CloudError(str(error)) from None
        if state.get("status") == "Succeeded":
            ctx.state.clear_pending(step, key)
            try:
                return fabric.get(location.rstrip("/") + "/result")
            except FabricError as error:
                if error.status in (400, 404):
                    return None
                raise CloudError(str(error)) from None
        if state.get("status") in ("Failed", "Undefined"):
            ctx.state.clear_pending(step, key)
            error = state.get("error") or {}
            raise CloudError(f"Fabric says the operation failed: {error.get('errorCode', '')} {error.get('message', '')}".strip())
        if ctx.clock() >= deadline:
            raise StillRunning(f"'{key}' is still running in Fabric after {ctx.options.limits['operation']} seconds.")
        ctx.sleep(ctx.options.limits["poll"])


NEVER_RUN = ("12_", "13_")     # the notebooks that send commands to the edge. The runner has no way to start them.


def _runs(instances: list) -> str:
    return "; ".join(f"{one.get('id')} ({one.get('status')}, started {one.get('startTimeUtc') or 'not yet'})" for one in instances) or "none"


def run_notebook(ctx, workspace_id: str, notebook_id: str, name: str, parameters: dict | None = None) -> dict:
    """Runs a notebook as a job and waits for it, within a limit. Returns the finished job.

    One run for one step, and only a run the runner knows to be its own:

    - Before the request leaves, the intent is written to the checkpoint. When Fabric answers, the run's ID replaces it.
    - A run whose ID is in the checkpoint is asked about, also after it has finished: its result is taken, and no
      second run is started.
    - An intent without an ID means an earlier apply ended between the request and the answer. Whether Fabric took the
      request is then not known, and Fabric offers no key by which a run could be matched to a request (Run On Demand
      Item Job documents none). The notebooks write data, so the runner neither starts another run nor takes one it
      finds: it lists the runs since, and a person says which it was (--adopt-job) or that there was none (--resubmit).
    - A run in progress that the checkpoint knows nothing of is somebody's, not the runner's. It is not waited for as
      if it were this step's.
    """
    if name.startswith(NEVER_RUN):
        raise CloudError(f"The runner does not run {name}: it sends a command to the edge. That stays with a person.")
    step, fabric = ctx.current, ctx.fabric
    base = f"workspaces/{workspace_id}/items/{notebook_id}/jobs/instances"
    pending = ctx.state.pending(step).get("job") or {}
    job, adopt, again = pending.get("id"), ctx.offered.get("adopt", {}).get(step), step in ctx.offered.get("resubmit", ())
    apply_again = "Then run the same apply again, with that option added."
    try:
        if not job and adopt:
            try:
                known = fabric.get(f"{base}/{adopt}")
            except FabricError as error:
                if error.status != 404:
                    raise
                known = None
            if not known:
                raise Blocked(f"--adopt-job {step}={adopt}: Fabric has no run of {name} with that ID.",
                              f"Runs it lists: {_runs(list(fabric.listing(base)))}")
            job = adopt
            ctx.say(f"      taking run {job} of {name} for this step, as you said")
        elif not job and pending.get("intent") and not again:
            since = [one for one in fabric.listing(base) if (one.get("startTimeUtc") or "9") >= pending.get("at", "")[:19]]
            raise Blocked(f"An earlier apply set out to run {name} at {pending.get('at')} and ended before it learned whether Fabric "
                          f"took the request. Runs of the notebook that Fabric lists since then: {_runs(since)}.",
                          f"If one of them is that run:   --adopt-job {step}=ID   (the runner waits for it, or takes its result)\n"
                          f"If the request never arrived:  --resubmit {step}\n{apply_again}\n"
                          f"The runner does neither by itself: {name} writes data, and Fabric gives a request no key by which its "
                          "run could be recognised.")
        elif not job and not again:
            active = [one for one in fabric.listing(base) if one.get("status") in ("NotStarted", "InProgress")]
            if active:
                raise Blocked(f"A run of {name} is under way in Fabric that this deployment has no record of: {_runs(active)}.",
                              "Wait for it to end, or cancel it in Fabric (the notebook, Run history), and run the same apply again.\n"
                              f"If it is a run an apply of yours started:   --adopt-job {step}={active[0].get('id')}\n"
                              "The runner does not take a run it did not start for this step's.")
        if not job:
            # The intent first: if this process ends before Fabric's answer is written down, the next apply knows.
            ctx.state.set_pending(step, "job", {"intent": "run", "notebook": name, "at": ctx.state.stamp()})
            body = {"executionData": {"parameters": parameters}} if parameters else None
            status, headers, _ = fabric.call("POST", f"{base}?jobType=RunNotebook", body)
            location = next((value for key, value in headers.items() if key.lower() == "location"), "")
            job = location.rstrip("/").rsplit("/", 1)[-1]
            if status != 202 or not job:
                raise CloudError(f"Fabric answered {status} to the request to run {name}, without a job to ask about.")
        ctx.state.set_pending(step, "job", {"id": job, "notebook": name, "at": pending.get("at") or ctx.state.stamp()})
        deadline = ctx.clock() + ctx.options.limits["job"]
        while True:
            instance = fabric.get(f"{base}/{job}") or {}
            if instance.get("status") in JOB_DONE:
                break
            if ctx.clock() >= deadline:
                raise StillRunning(f"The run of {name} ({job}) is {instance.get('status', 'not answering')} after "
                                   f"{ctx.options.limits['job']} seconds.")
            ctx.sleep(ctx.options.limits["poll"])
    except FabricError as error:
        raise CloudError(str(error)) from None
    ctx.state.clear_pending(step, "job")
    if instance.get("status") != "Completed":
        reason = instance.get("failureReason") or {}
        raise CloudError(ctx.redact(f"The run of {name} ended as {instance.get('status')}: "
                                    f"{reason.get('errorCode', '')} {str(reason.get('message', ''))[:500]}".strip()))
    ctx.state.note(step, **{f"job:{name}": {"id": job, "status": "Completed", "started": instance.get("startTimeUtc"),
                                            "ended": instance.get("endTimeUtc")}})
    return instance
