#!/usr/bin/env python3
"""Phase 5b: the instructions and the action of the operations agent, through the Fabric API.

Started by infra/09-remediation-agent.sh, which gets a token for the signed-in user from the Azure
CLI and hands it over in the environment variable FABRIC_TOKEN. The token is never printed and is
sent to the Fabric API only.

    show                 how the agent is set up now, and what differs from Phase 5b. Changes nothing
    save                 the same, and the agent's definition written to a file. Changes nothing in Fabric
    apply                save the agent's definition to a file, then give it the Phase 5b instructions
                         and the action 'Curtail turbine'. Leaves the agent stopped
    restore FILE         put a saved definition back. Fabric checks what it is given, and on 24 November 2026
                         it refused a playbook that its own portal had generated; see the guide
    rehearse TURBINE     run notebook 12_send_edge_command as a job with the parameters the action
                         passes, as text, and wait for the result

What this rests on (Microsoft Learn, read on 24 November 2026):
  Items - Get Operations Agent Definition: POST workspaces/{id}/operationsAgents/{id}/getDefinition,
      long running, user identities only.
  Operations agent definition: one part with {"configuration": {"instructions", "dataSources",
      "actions", "messageDestination"}, "playbook", "shouldRun"}; an action of kind FabricJobAction
      has a connection {"jobArtifactId", "jobWorkspaceId", "itemType", "jobType"} and parameters
      [{"name", "description"}]. The article names the part Configurations.json and the sample of the
      API names it OperationsAgentV1.json, so the part is found by its content and written back under
      the name it came with. The article calls the playbook "reserved for future expansion"; what Fabric
      returns for an agent made in the portal holds its rules and the objects they watch
      (playbook.ontologyDefinitions), seen in an error message of 24 November 2026.
  Job Scheduler - Run On Demand Item Job: POST workspaces/{id}/items/{id}/jobs/instances?jobType=RunNotebook
      with {"executionData": {"parameters": {name: {"value", "type"}}}}; 202 with a Location to poll.
"""
from __future__ import annotations

import base64
import copy
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import remediation_spec as spec  # noqa: E402

DEFAULT_API = "https://api.fabric.microsoft.com/v1"
# As the portal writes them for an action that runs a notebook (read back on 24 November 2026). Microsoft's
# article gives "Notebook" as its example of an item type; the update that carried that word was refused.
ITEM_TYPE, JOB_TYPE = "SynapseNotebook", "RunNotebook"
REHEARSAL_DURATION = "2m"
JOB_DONE = {"Completed", "Failed", "Cancelled", "Deduped"}


class FabricError(Exception):
    """The Fabric API refused, or answered something this tool cannot use. The text is for the person."""

    def __init__(self, text: str, status: int | None = None, code: str = ""):
        super().__init__(text)
        self.status, self.code = status, code


# ----------------------------------------------------------------------------------------------- HTTP
def api_address(api: str, url: str) -> str:
    """The address to ask, on the Fabric API itself. The token is sent nowhere else.

    An accepted request (202) names where to ask for its result in a Location header. Microsoft's reference shows that
    address on the API (`.../v1/operations/{id}`). On 26 November 2026 Fabric named one on a regional host instead,
    `wabi-us-central-b-primary-redirect.analysis.windows.net/v1/operations/{id}`. The operation is the same, and the
    reference documents it on the API (Long Running Operations - Get Operation State, Get Operation Result), as it does
    a job (Job Scheduler - Get Item Job Instance): an address of one of those two forms is asked on the API. Any other
    address on another host is refused, as before.
    """
    base, asked = urllib.parse.urlsplit(api.rstrip("/")), urllib.parse.urlsplit(url)
    if asked[:2] == base[:2]:
        return url
    known = re.fullmatch(re.escape(base.path) + r"(/operations/[^/]+(?:/result)?|/workspaces/[^/]+/items/[^/]+/jobs/instances/[^/]+)/?",
                         asked.path)
    if not known:
        raise FabricError(f"The Fabric API pointed to another address ({asked.netloc}). Stopped.")
    return f"{api.rstrip('/')}{known[1]}"


class Fabric:
    def __init__(self, token: str, api: str = DEFAULT_API, poll_seconds: float = 3.0, sleep=time.sleep):
        if not token:
            raise FabricError("No token. Start this through: bash infra/09-remediation-agent.sh")
        self.api = api.rstrip("/")
        self._token, self._poll, self._sleep = token, poll_seconds, sleep
        self.job_poll = max(poll_seconds, 5.0) if poll_seconds else 0.0   # a job is asked about less often
        self._origin = urllib.parse.urlsplit(self.api)[:2]
        address = urllib.parse.urlsplit(self.api)
        if address.scheme != "https" and address.hostname not in ("127.0.0.1", "localhost"):   # a local stand-in, in the tests
            raise FabricError(f"FABRIC_API is {self.api}. The token is sent over https only.")

    def _url(self, path: str) -> str:
        url = path if path.startswith("http") else f"{self.api}/{path.lstrip('/')}"
        return api_address(self.api, url)   # a Location header must not send the token elsewhere

    def call(self, method: str, path: str, body=None):
        """One request. Returns (status, headers, parsed body or None). Waits and repeats on 429."""
        data = None if body is None else json.dumps(body).encode("utf-8")
        for attempt in range(4):
            request = urllib.request.Request(self._url(path), data=data, method=method)
            request.add_header("Authorization", f"Bearer {self._token}")
            if data is not None:
                request.add_header("Content-Type", "application/json")
            elif method == "POST":
                request.add_header("Content-Length", "0")
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    return response.status, dict(response.headers.items()), _parse(response.read())
            except urllib.error.HTTPError as error:
                payload = _parse(error.read())
                if error.code == 429 and attempt < 3:
                    self._sleep(min(float(error.headers.get("Retry-After") or 5), 60.0))
                    continue
                raise FabricError(_said(error.code, payload), status=error.code,
                                  code=(payload or {}).get("errorCode", "") if isinstance(payload, dict) else "") from None
            except urllib.error.URLError as error:
                raise FabricError(f"Could not reach the Fabric API at {self.api}: {error.reason}") from None
        raise FabricError("The Fabric API kept answering 429 (too many requests). Try again in a few minutes.")

    def get(self, path: str):
        return self.call("GET", path)[2]

    def listing(self, path: str) -> list:
        """All entries of a list, following continuation."""
        out, url = [], path
        while url:
            page = self.get(url) or {}
            out.extend(page.get("value", []))
            url = page.get("continuationUri")
        return out

    def long_running(self, method: str, path: str, body=None):
        """A call that may answer 202: waits for the operation and returns its result, or None."""
        status, headers, payload = self.call(method, path, body)
        if status != 202:
            return payload
        location = _header(headers, "Location")
        if not location:
            raise FabricError("The Fabric API accepted the request and did not say where to ask for the result.")
        for _ in range(120):
            self._sleep(self._poll)
            state = self.get(location) or {}
            if state.get("status") == "Succeeded":
                try:
                    return self.get(location.rstrip("/") + "/result")
                except FabricError as error:
                    if error.status in (400, 404):   # an operation without a result, such as an update
                        return None
                    raise
            if state.get("status") in ("Failed", "Undefined"):
                error = state.get("error") or {}
                raise FabricError(f"The operation failed: {error.get('errorCode', '')} {error.get('message', '')}".strip())
        raise FabricError("The operation did not finish in time.")


def _parse(raw: bytes):
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {"message": raw[:300].decode("utf-8", "replace")}


def _said(status: int, payload) -> str:
    payload = payload if isinstance(payload, dict) else {}
    parts = [f"The Fabric API answered {status}"]
    if payload.get("errorCode"):
        parts.append(str(payload["errorCode"]))
    text = ": ".join(parts)
    if payload.get("message"):
        text += f". It said: {str(payload['message'])[:400]}"
    if payload.get("requestId"):
        text += f" (request {payload['requestId']})"
    return text


def _header(headers: dict, name: str):
    return next((value for key, value in headers.items() if key.lower() == name.lower()), None)


# ------------------------------------------------------------------------------------ pure functions
def find_by_name(entries: list, name: str, what: str) -> str:
    """The id of the one entry with that display name. Stops when there is none, or more than one."""
    hits = [e.get("id") for e in entries if e.get("displayName") == name]
    if not hits:
        known = ", ".join(sorted(str(e.get("displayName")) for e in entries)) or "none"
        raise FabricError(f"No {what} named {name}. Found: {known}.")
    if len(hits) > 1:
        raise FabricError(f"{len(hits)} {what}s are named {name}. Rename or delete the ones that are not in use.")
    return hits[0]


def decode_definition(response: dict) -> tuple[str, dict]:
    """(path, document) of the part that holds the agent's configuration."""
    parts = ((response or {}).get("definition") or {}).get("parts") or []
    for part in parts:
        if part.get("path") == ".platform" or part.get("payloadType", "InlineBase64") != "InlineBase64":
            continue
        try:
            document = json.loads(base64.b64decode(part.get("payload", "")).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            continue
        if isinstance(document, dict) and isinstance(document.get("configuration"), dict):
            return part["path"], document
    names = ", ".join(str(p.get("path")) for p in parts) or "none"
    raise FabricError(f"The definition of the agent has no part with a configuration. Its parts: {names}.")


def encode_definition(path: str, document: dict) -> dict:
    payload = base64.b64encode(json.dumps(document, indent=2, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return {"definition": {"parts": [{"path": path, "payload": payload, "payloadType": "InlineBase64"}]}}


def find_action(document: dict, display_name: str = spec.ACTION_NAME):
    """(key, action) of the action with that name, or (None, None)."""
    actions = (document.get("configuration") or {}).get("actions") or {}
    for key, action in actions.items():
        if isinstance(action, dict) and action.get("displayName") == display_name:
            return key, action
    return None, None


def action_object(notebook_id: str, workspace_id: str, action_id: str) -> dict:
    return {
        "id": action_id,
        "kind": "FabricJobAction",
        "displayName": spec.ACTION_NAME,
        "description": spec.action_description(),
        "connection": {"jobArtifactId": notebook_id, "jobWorkspaceId": workspace_id, "itemType": ITEM_TYPE, "jobType": JOB_TYPE},
        "parameters": [{"name": name, "description": text} for name, text in spec.PARAMETERS],
    }


def with_remediation(document: dict, notebook_id: str, workspace_id: str, new_id=lambda: str(uuid.uuid4())) -> dict:
    """The agent's definition with the Phase 5b instructions and the action. Everything else is kept:
    the data source, where messages go, the identity, other actions. The agent is left stopped, and
    the playbook empty, so that nothing runs on rules made from the earlier instructions."""
    out = copy.deepcopy(document)
    configuration = out.setdefault("configuration", {})
    configuration["instructions"] = spec.setup_text()
    key, existing = find_action(out)
    actions = configuration.get("actions")
    if not isinstance(actions, dict):
        actions = configuration["actions"] = {}
    action_id = (existing or {}).get("id") or new_id()
    actions[key or action_id] = action_object(notebook_id, workspace_id, action_id)     # the portal keys an action by its id
    out["playbook"] = {}
    out["shouldRun"] = False
    return out


def _same_text(a, b) -> bool:
    clean = lambda text: "\n".join(line.rstrip() for line in str(text or "").replace("\r\n", "\n").strip().split("\n"))
    return clean(a) == clean(b)


def differences(document: dict, notebook_id: str, workspace_id: str, database_id: str | None = None) -> list[str]:
    """What differs from the Phase 5b setup, in sentences. Empty when nothing does. Running or stopped is not judged."""
    out = []
    configuration = document.get("configuration") or {}
    instructions = configuration.get("instructions", "")
    if not _same_text(instructions, spec.setup_text()):
        phase3 = ROOT / "fabric" / "operations-agent" / "agent-setup.txt"
        if phase3.is_file() and _same_text(instructions, phase3.read_text(encoding="utf-8")):
            out.append("The instructions are those of Phase 3 (fabric/operations-agent/agent-setup.txt).")
        elif f"'{spec.TABLE}'" in str(instructions) and f"'{spec.ACTION_NAME}'" in str(instructions):
            out.append("The instructions speak of the table and the action of Phase 5b and are not word for word those of fabric/operations-agent/phase5b-agent-setup.txt.")
        else:
            out.append("The instructions are not those of fabric/operations-agent/phase5b-agent-setup.txt.")
    if configuration.get("goals"):
        out.append("The definition still has a separate 'goals' text. It was left as it is.")
    key, action = find_action(document)
    if action is None:
        names = ", ".join(str(a.get("displayName")) for a in (configuration.get("actions") or {}).values() if isinstance(a, dict)) or "none"
        out.append(f"There is no action named '{spec.ACTION_NAME}'. Actions: {names}.")
    else:
        connection = action.get("connection") or {}
        if action.get("kind") != "FabricJobAction":
            out.append(f"The action '{spec.ACTION_NAME}' is of kind {action.get('kind')}, not a Fabric item action.")
        if connection.get("jobArtifactId") != notebook_id or connection.get("jobWorkspaceId") != workspace_id:
            out.append(f"The action does not run the notebook {spec.NOTEBOOK} of this workspace (it names item {connection.get('jobArtifactId')}). "
                       "A notebook that is imported again gets a new id: apply once more.")
        elif (connection.get("itemType"), connection.get("jobType")) != (ITEM_TYPE, JOB_TYPE):
            out.append(f"The action's item type and job type are {connection.get('itemType')} and {connection.get('jobType')}; this tool writes {ITEM_TYPE} and {JOB_TYPE}.")
        have = [p.get("name") for p in action.get("parameters") or [] if isinstance(p, dict)]
        want = [name for name, _ in spec.PARAMETERS]
        if sorted(map(str, have)) != sorted(want):
            out.append(f"The action's parameters are {', '.join(map(str, have)) or 'none'}; they should be {', '.join(want)}.")
    if database_id:
        sources = [s for s in (configuration.get("dataSources") or {}).values() if isinstance(s, dict)]
        if not any(s.get("id") == database_id for s in sources):
            out.append("The KQL database of the demo is not among the agent's data sources.")
    return out


def describe(document: dict, path: str, names: dict) -> list[str]:
    """The agent's setup in lines a person can check. `names` maps item ids to names."""
    configuration = document.get("configuration") or {}
    instructions = str(configuration.get("instructions") or "")
    first_rule = next((line.strip() for line in instructions.split("\n") if line.strip().startswith("1.")), "")
    lines = [f"Definition part: {path}",
             f"Running: {'yes' if document.get('shouldRun') else 'no'}",
             f"Instructions: {len(instructions)} characters. First rule: {(first_rule.split('. ', 2)[1] + '.') if first_rule.count('. ') >= 2 else first_rule[:120] or 'not found'}"]
    for key, source in (configuration.get("dataSources") or {}).items():
        if isinstance(source, dict):
            lines.append(f"Data source {key}: {source.get('type')} {names.get(source.get('id'), source.get('id'))}")
        else:
            lines.append(f"Data source {key}: {source}")
    destination = configuration.get("messageDestination") or {}
    if destination.get("kind") == "Recipient":
        lines.append(f"Messages go to: {destination.get('recipient')}")
    elif destination:
        lines.append(f"Messages go to: {destination.get('kind')} (team {destination.get('teamId')}, channel {destination.get('channelId')})")
    elif configuration.get("recipient"):
        lines.append(f"Messages go to: {configuration.get('recipient')}")
    else:
        lines.append("Messages go to: not in the definition (the creator of the agent, unless changed under Agent behavior)")
    actions = configuration.get("actions") or {}
    if not actions:
        lines.append("Actions: none")
    for key, action in actions.items():
        if not isinstance(action, dict):
            continue
        connection = action.get("connection") or {}
        target = ""
        if connection:
            target = f", runs {connection.get('itemType')} {names.get(connection.get('jobArtifactId'), connection.get('jobArtifactId'))} as {connection.get('jobType')}"
        parameters = ", ".join(str(p.get("name")) for p in action.get("parameters") or [] if isinstance(p, dict)) or "none"
        lines.append(f"Action {key}: '{action.get('displayName')}' ({action.get('kind')}){target}. Parameters: {parameters}")
    playbook = document.get("playbook")
    if not playbook:
        lines.append("Playbook in the definition: empty")
    else:
        lines.append(f"Playbook in the definition: {len(json.dumps(playbook))} characters")
        if isinstance(playbook, dict):
            for key, value in playbook.items():     # its form is not published: say what is there, assume nothing
                size = f"{len(value)} entries" if isinstance(value, (list, dict)) else str(value)[:60]
                names = [str(v.get("name") or v.get("displayName")) for v in (value if isinstance(value, list) else [])
                         if isinstance(v, dict) and (v.get("name") or v.get("displayName"))]
                lines.append(f"  playbook.{key}: {size}" + (f" ({', '.join(names[:8])})" if names else ""))
    return lines


def job_request(turbine: str, percent: int = spec.CURTAIL_PERCENT, duration: str = REHEARSAL_DURATION) -> dict:
    """The body of the job run: the action's four parameters, each as text, the way a caller that
    knows no types passes them."""
    values = {"turbine": turbine, "percent": str(percent), "duration": duration,
              "requested_by": "rehearsal of the agent's action (infra/09-remediation-agent.sh --rehearse)"}
    assert set(values) == {name for name, _ in spec.PARAMETERS}
    return {"executionData": {"parameters": {name: {"value": value, "type": "string"} for name, value in values.items()}}}


# --------------------------------------------------------------------------------------------- modes
class Session:
    def __init__(self, fabric: Fabric, env: dict):
        self.fabric = fabric
        self.workspace_name = env.get("FABRIC_WORKSPACE_NAME") or "WindFarmDigitalTwin"
        self.agent_name = env.get("OPERATIONS_AGENT_NAME") or spec.AGENT
        self.database_name = env.get("EVENTHOUSE_NAME") or "WindFarmEH"   # the KQL database carries the Eventhouse's name
        self.save_dir = Path(env.get("AGENT_SAVE_DIR") or ROOT / "fabric" / "operations-agent" / "saved")
        self.workspace_id = find_by_name(fabric.listing("workspaces"), self.workspace_name, "workspace")
        self._ws = f"workspaces/{self.workspace_id}"

    def agent_id(self) -> str:
        try:
            agents = self.fabric.listing(f"{self._ws}/operationsAgents")
        except FabricError as error:
            if error.status != 404:
                raise
            agents = [i for i in self.fabric.listing(f"{self._ws}/items") if i.get("type") == "OperationsAgent"]
        return find_by_name(agents, self.agent_name, "operations agent")

    def notebook_id(self) -> str:
        return find_by_name(self.fabric.listing(f"{self._ws}/notebooks"), spec.NOTEBOOK, "notebook")

    def database_id(self):
        try:
            return find_by_name(self.fabric.listing(f"{self._ws}/kqlDatabases"), self.database_name, "KQL database")
        except FabricError:
            return None

    def read(self, agent_id: str) -> dict:
        try:
            return self.fabric.long_running("POST", f"{self._ws}/operationsAgents/{agent_id}/getDefinition")
        except FabricError as error:
            if error.status != 404:
                raise
            return self.fabric.long_running("POST", f"{self._ws}/items/{agent_id}/getDefinition")

    def write(self, agent_id: str, path: str, document: dict) -> None:
        body = encode_definition(path, document)
        try:
            self.fabric.long_running("POST", f"{self._ws}/operationsAgents/{agent_id}/updateDefinition", body)
        except FabricError as error:
            if error.status != 404:
                raise
            self.fabric.long_running("POST", f"{self._ws}/items/{agent_id}/updateDefinition", body)


def report(session: Session, agent_id: str, path: str, document: dict, out) -> list[str]:
    database_id = session.database_id()
    try:
        notebook_id = session.notebook_id()
    except FabricError as error:
        notebook_id = None
        print(f"  ({error})", file=out)
    names = {notebook_id: spec.NOTEBOOK} if notebook_id else {}
    if database_id:
        names[database_id] = session.database_name
    print(f"Operations agent {session.agent_name} ({agent_id}) in workspace {session.workspace_name}", file=out)
    for line in describe(document, path, names):
        print(f"  {line}", file=out)
    found = differences(document, notebook_id or "", session.workspace_id, database_id)
    if found:
        print("Differs from Phase 5b:", file=out)
        for line in found:
            print(f"  - {line}", file=out)
    else:
        print("Instructions and action are those of Phase 5b.", file=out)
    return found


def show(session: Session, out) -> int:
    agent_id = session.agent_id()
    path, document = decode_definition(session.read(agent_id))
    report(session, agent_id, path, document, out)
    return 0


def keep(session: Session, agent_id: str, response: dict, path: str, document: dict, now=None) -> Path:
    """Write the definition to a file. "response" is what Fabric returned and what restore writes back;
    "part" and "document" are the same definition decoded, for reading."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    session.save_dir.mkdir(parents=True, exist_ok=True)
    saved, number = session.save_dir / f"{session.agent_name}-{stamp}.json", 1
    while saved.exists():           # two saves within a second: the earlier one is the one worth keeping
        number += 1
        saved = session.save_dir / f"{session.agent_name}-{stamp}-{number}.json"
    saved.write_text(json.dumps({"agent": session.agent_name, "agentId": agent_id, "workspaceId": session.workspace_id,
                                 "savedAt": stamp, "part": path, "document": document, "response": response},
                                indent=1, ensure_ascii=False), encoding="utf-8")
    return saved


def save(session: Session, out, now=None) -> int:
    agent_id = session.agent_id()
    response = session.read(agent_id)
    path, document = decode_definition(response)
    saved = keep(session, agent_id, response, path, document, now)
    report(session, agent_id, path, document, out)
    print(f"Saved the agent's definition: {_shown(saved)}", file=out)
    print("It holds the instructions, the actions, the playbook, item ids and the recipient's sign-in address. No key and no token.", file=out)
    return 0


def apply(session: Session, out, now=None) -> int:
    agent_id, notebook_id = session.agent_id(), session.notebook_id()
    response = session.read(agent_id)
    path, document = decode_definition(response)
    saved = keep(session, agent_id, response, path, document, now)
    print(f"Saved the agent's definition as it was: {_shown(saved)}", file=out)
    was_running = bool(document.get("shouldRun"))
    session.write(agent_id, path, with_remediation(document, notebook_id, session.workspace_id))
    print("Wrote the Phase 5b instructions and the action. Reading the definition back:", file=out)
    path, document = decode_definition(session.read(agent_id))
    found = report(session, agent_id, path, document, out)
    if document.get("shouldRun"):
        print("The agent is still running. Stop it in the portal before you look at the playbook.", file=out)
    elif was_running:
        print("The agent was running and is now stopped.", file=out)
    print("Next, in the portal: open the agent, look at the instructions and the action, generate the playbook, "
          "compare its rule with the guide, and select Start.", file=out)
    print(f"To go back: bash infra/09-remediation-agent.sh --restore {_shown(saved)} (Fabric may refuse a playbook "
          "the portal generated; then go back by hand, as the guide says).", file=out)
    return 1 if found else 0


def restore(session: Session, file: str, out) -> int:
    try:
        saved = json.loads(Path(file).read_text(encoding="utf-8"))
        path, document = decode_definition(saved["response"])
    except (OSError, ValueError, KeyError) as error:
        raise FabricError(f"{file} is not a definition saved by this tool: {error}") from None
    agent_id = session.agent_id()
    if saved.get("agentId") not in (None, agent_id):
        raise FabricError(f"{file} was saved from another agent ({saved.get('agentId')}); {session.agent_name} is {agent_id}.")
    session.write(agent_id, path, document)
    print(f"Put back the definition saved at {saved.get('savedAt')}. Reading it back:", file=out)
    path, document = decode_definition(session.read(agent_id))
    report(session, agent_id, path, document, out)
    print("Open the agent in the portal and check its playbook before you rely on it.", file=out)
    return 0


def rehearse(session: Session, turbine: str, out, clock=time.monotonic, limit_seconds: float = 1200.0) -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    import edge_command
    try:
        command = edge_command.from_parameters("curtail", turbine, percent=str(spec.CURTAIL_PERCENT), duration=REHEARSAL_DURATION)
    except edge_command.CommandError as error:
        raise FabricError(str(error)) from None
    if command["turbine"] == "all":
        raise FabricError("The rehearsal limits one turbine. Name it, for example WT-07.")
    notebook_id = session.notebook_id()
    began = clock()
    status, headers, _ = session.fabric.call("POST", f"workspaces/{session.workspace_id}/items/{notebook_id}/jobs/instances?jobType={JOB_TYPE}",
                                             job_request(command["turbine"]))
    location = _header(headers, "Location")
    if status != 202 or not location:
        raise FabricError(f"The Fabric API answered {status} to the job request and gave no job to follow.")
    print(f"Started {spec.NOTEBOOK} as a job: curtail {command['turbine']} to {spec.CURTAIL_PERCENT} percent for {REHEARSAL_DURATION}. "
          "The limit ends by itself.", file=out)
    last = None
    while clock() - began < limit_seconds:
        session.fabric._sleep(session.fabric.job_poll)
        job = session.fabric.get(location) or {}
        state = job.get("status")
        if state != last:
            print(f"  {clock() - began:5.0f} s  {state}", file=out)
            last = state
        if state in JOB_DONE:
            if state == "Completed":
                print(f"The job completed {clock() - began:.0f} seconds after the request. The turbine should be CURTAILED within a minute; "
                      "check with the query at the end of the notebook, or in the twin.", file=out)
                return 0
            reason = job.get("failureReason") or {}
            said = f"{reason.get('errorCode', '')} {reason.get('message', '')}".strip() if isinstance(reason, dict) else str(reason)
            print(f"The job ended as {state}. {said}".strip(), file=out)
            print("Open the notebook's run in the workspace (Monitor, or Recent runs of the notebook) to see the cell that failed.", file=out)
            return 1
    print("The job did not finish in 20 minutes. Look at it under Monitor in the workspace.", file=out)
    return 1


def _shown(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def main(argv, env=None, out=sys.stdout) -> int:
    env = os.environ if env is None else env
    usage = "Use: show, save, apply, restore FILE, or rehearse TURBINE."
    if not argv or argv[0] not in ("show", "save", "apply", "restore", "rehearse") or len(argv) != (2 if argv[0] in ("restore", "rehearse") else 1):
        print(usage, file=sys.stderr)
        return 2
    try:
        fabric = Fabric(env.get("FABRIC_TOKEN", ""), env.get("FABRIC_API") or DEFAULT_API,
                        poll_seconds=float(env.get("FABRIC_POLL_SECONDS") or 3))
        session = Session(fabric, env)
        if argv[0] == "show":
            return show(session, out)
        if argv[0] == "save":
            return save(session, out)
        if argv[0] == "apply":
            return apply(session, out)
        if argv[0] == "restore":
            return restore(session, argv[1], out)
        return rehearse(session, argv[1], out)
    except FabricError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
