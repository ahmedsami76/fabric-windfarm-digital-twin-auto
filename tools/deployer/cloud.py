"""The adapters of the deployment runner: the Azure CLI, the Fabric API, the Eventhouse, OneLake, the shell.

Every call to the outside goes through one of these five, which is where the tests put their stand-ins.
Tokens come from the Azure CLI's sign-in, are handed to the redactor at once, and are sent only to the
service they were asked for.
"""
from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .core import Blocked, Redactor, StepFailed, StillRunning

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from operations_agent import Fabric, FabricError  # noqa: E402  (the client of Phase 5b: 429, long-running calls, one origin)

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


class Az:
    """The Azure CLI, with the sign-in the operator made. Read with show and list, write only inside apply."""

    def __init__(self, redact: Redactor, run=subprocess.run):
        self._redact, self._run = redact, run

    def _call(self, args, timeout):
        try:
            return self._run(["az", *args], capture_output=True, text=True, timeout=timeout)
        except FileNotFoundError:
            raise CloudError("The Azure CLI (az) is not installed on this computer.") from None
        except subprocess.TimeoutExpired:
            raise CloudError(f"az {' '.join(args[:3])} did not answer within {timeout} seconds.") from None

    def json(self, *args, timeout: int = 300):
        """The parsed answer. Raises when the CLI fails."""
        result = self._call([*args, "--output", "json"], timeout)
        if result.returncode != 0:
            raise CloudError(self._redact(f"az {' '.join(args[:4])} failed: {_tail(result.stderr)}"))
        text = result.stdout.strip()
        return json.loads(text) if text else None

    def maybe(self, *args, timeout: int = 300):
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


def _tail(text: str, lines: int = 6) -> str:
    rows = [row for row in (text or "").strip().splitlines() if row.strip()]
    return " | ".join(rows[-lines:])[:900]


class Shell:
    """The repository's own scripts, started through bash, their output shown through the redactor."""

    def __init__(self, root: Path, redact: Redactor, out=None, popen=subprocess.Popen):
        self.root, self._redact, self._out, self._popen = Path(root), redact, out, popen

    def run(self, argv: list[str], env: dict | None = None, cwd: Path | None = None, timeout: int = 5400) -> tuple[int, str]:
        import os
        full = dict(os.environ)
        full.update(env or {})
        try:
            process = self._popen(argv, cwd=str(cwd or self.root), env=full, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  stdin=subprocess.DEVNULL, text=True)
        except FileNotFoundError as error:
            raise CloudError(f"{argv[0]} is not installed on this computer ({error}).") from None
        kept: list[str] = []
        for row in process.stdout:
            row = self._redact(row.rstrip("\n"))
            kept.append(row)
            del kept[:-60]
            print(f"      | {row}", file=self._out, flush=True)
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            raise CloudError(f"{' '.join(argv[:3])} did not finish within {timeout} seconds.") from None
        return code, "\n".join(kept)

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


def http(method: str, url: str, token: str, body=None, headers: dict | None = None, timeout: int = 60):
    """One request outside the Fabric API. Returns (status, parsed body or text). The token goes over https only."""
    if urllib.parse.urlsplit(url).scheme != "https":
        raise CloudError(f"Refused to send a token to {url}: not https.")
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        request.add_header("Content-Type", "application/json; charset=utf-8")
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except urllib.error.URLError as error:
        raise CloudError(f"Could not reach {urllib.parse.urlsplit(url).netloc}: {error.reason}") from None


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
        status, raw = self._request("POST", f"{uri.rstrip('/')}/v1/rest/{'mgmt' if mgmt else 'query'}", self._token(uri),
                                    {"db": database, "csl": csl}, timeout=180)
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
def operation(ctx, key: str, start):
    """A Fabric call that may answer 202. Its address is kept in the checkpoint before the first wait, so that
    an apply that is interrupted, or gives up waiting, asks about the same operation next time and starts no second one.

    start() makes the request and returns what Fabric.call returns: (status, headers, body).
    """
    step, fabric = ctx.current, ctx.fabric
    location = (ctx.state.pending(step).get(key) or {}).get("location")
    if not location:
        status, headers, payload = start()
        if status != 202:
            return payload
        location = next((value for name, value in headers.items() if name.lower() == "location"), None)
        if not location:
            raise CloudError("Fabric accepted the request and did not say where to ask for the result.")
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


def run_notebook(ctx, workspace_id: str, notebook_id: str, name: str, parameters: dict | None = None) -> dict:
    """Runs a notebook as a job and waits for it, within a limit. Returns the finished job.

    One run for one step: a job that is recorded as started, or that Fabric shows as queued or running for this
    notebook, is waited for. A second one is never started beside it.
    """
    if name.startswith(NEVER_RUN):
        raise CloudError(f"The runner does not run {name}: it sends a command to the edge. That stays with a person.")
    step, fabric = ctx.current, ctx.fabric
    base = f"workspaces/{workspace_id}/items/{notebook_id}/jobs/instances"
    job = (ctx.state.pending(step).get("job") or {}).get("id")
    try:
        if not job:
            for instance in fabric.listing(base):
                if instance.get("status") in ("NotStarted", "InProgress"):
                    job = instance["id"]           # started by an apply that did not live to write it down
                    ctx.say(f"      a run of {name} is already under way ({job}); waiting for that one")
                    break
        if not job:
            body = {"executionData": {"parameters": parameters}} if parameters else None
            status, headers, _ = fabric.call("POST", f"{base}?jobType=RunNotebook", body)
            location = next((value for key, value in headers.items() if key.lower() == "location"), "")
            job = location.rstrip("/").rsplit("/", 1)[-1]
            if status != 202 or not job:
                raise CloudError(f"Fabric answered {status} to the request to run {name}, without a job to ask about.")
        ctx.state.set_pending(step, "job", {"id": job, "notebook": name})
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
