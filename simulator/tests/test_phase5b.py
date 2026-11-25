"""Phase 5b: tools/operations_agent.py against a stand-in for the Fabric API.

The stand-in speaks HTTP on a local port and answers the way Microsoft Learn describes the calls the tool
makes: lists, the definition of an operations agent as a long-running operation, the update of that
definition, and a notebook job with a Location to poll. It is not Fabric: what Fabric really answers shows
only in a run against a tenant, and the guide says which outputs to send back.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WS, AGENT, NOTEBOOK, DATABASE = ("11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222",
                                 "33333333-3333-4333-8333-333333333333", "44444444-4444-4444-8444-444444444444")
TOKEN = "t0ken-of-the-test"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load("operations_agent", ROOT / "tools" / "operations_agent.py")
spec = tool.spec
edge = _load("edge_command_5b", ROOT / "tools" / "edge_command.py")
PHASE3_TEXT = (ROOT / "fabric" / "operations-agent" / "agent-setup.txt").read_text(encoding="utf-8")


def phase3_document() -> dict:
    return {
        "configuration": {
            "instructions": PHASE3_TEXT,
            "dataSources": {"kusto1": {"id": DATABASE, "type": "KustoDatabase", "workspaceId": WS}},
            "actions": {},
            "messageDestination": {"kind": "Recipient", "recipient": "admin@contoso.example"},
            "identity": {"sponsor": "admin"},
        },
        # What is known of a playbook the portal generated, from Fabric's error message of 24 November 2026:
        # it has "ontologyDefinitions" with classes, and rules that name a class. The fields inside are a guess.
        "playbook": {"ontologyDefinitions": [{"name": "TurbineRunSample"}, {"name": "TurbineRunSample"}, {"name": "TurbineRunSample"}],
                     "rules": [{"name": "Rule Gearbox Vibration Early Warning", "class": "TurbineRunSample"},
                               {"name": "Rule Gearbox Vibration Alarm Level", "class": "TurbineRunSample"},
                               {"name": "Rule Gearbox Oil Temperature Early Warning", "class": "TurbineRunSample"}]},
        "shouldRun": True,
    }


def the_action(document) -> dict:
    """The action 'Curtail turbine' of a definition, whatever its key."""
    return tool.find_action(document)[1]


def b64(document) -> str:
    return base64.b64encode(json.dumps(document).encode()).decode()


class Stand:
    """State of the pretend Fabric. Tests change the attributes before they call the tool."""

    def __init__(self):
        self.document = phase3_document()
        self.part = "OperationsAgentV1.json"
        self.agents = [{"id": AGENT, "displayName": "WindFarmGearboxWatch", "type": "OperationsAgent"},
                       {"id": "99999999-9999-4999-8999-999999999999", "displayName": "AnotherAgent", "type": "OperationsAgent"}]
        self.notebooks = [{"id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "displayName": "04_curated_tables"},
                          {"id": NOTEBOOK, "displayName": "12_send_edge_command"}]
        self.long_running = True          # getDefinition and updateDefinition answer 202 first
        self.specific_paths = True        # False: only the generic /items/{id}/... paths exist
        self.refuse_update = None         # (status, errorCode, message)
        self.refuse_playbook = False      # as Fabric did on 24 November 2026: a class defined more than once is refused
        self.throttle = 0                 # this many requests are answered 429 first
        self.job_states = ["NotStarted", "InProgress", "InProgress", "Completed"]
        self.job_failure = None
        self.location_elsewhere = False
        self.requests: list[tuple[str, str, object]] = []
        self.operations: dict[str, object] = {}
        self.polls = 0

    def definition(self) -> dict:
        return {"definition": {"parts": [
            {"path": self.part, "payload": b64(self.document), "payloadType": "InlineBase64"},
            {"path": ".platform", "payload": b64({"metadata": {"type": "OperationsAgent", "displayName": "WindFarmGearboxWatch"}}), "payloadType": "InlineBase64"}]}}


@pytest.fixture
def fabric(tmp_path):
    stand = Stand()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _send(self, status, body=None, headers=None):
            raw = b"" if body is None else json.dumps(body).encode()
            self.send_response(status)
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _handle(self, method):
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            path = self.path[len("/v1"):]
            stand.requests.append((method, path, body))
            base = f"http://127.0.0.1:{self.server.server_port}/v1"
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._send(401, {"errorCode": "TokenExpired", "message": "Access token has expired, resubmit with a new access token", "requestId": "r-401"})
            if stand.throttle:
                stand.throttle -= 1
                return self._send(429, {"errorCode": "RequestBlocked", "message": "slow down"}, {"Retry-After": "0"})
            ws = f"/workspaces/{WS}"
            if (method, path) == ("GET", "/workspaces"):
                return self._send(200, {"value": [{"id": "0", "displayName": "My workspace"}], "continuationUri": f"{base}/workspaces?continuationToken=2"})
            if (method, path) == ("GET", "/workspaces?continuationToken=2"):
                return self._send(200, {"value": [{"id": WS, "displayName": "WindFarmDigitalTwin"}]})
            if (method, path) == ("GET", f"{ws}/operationsAgents"):
                return self._send(200, {"value": stand.agents}) if stand.specific_paths else self._send(404, {"errorCode": "EndpointNotFound", "message": "no such path"})
            if (method, path) == ("GET", f"{ws}/items"):
                return self._send(200, {"value": stand.agents + [dict(n, type="Notebook") for n in stand.notebooks]})
            if (method, path) == ("GET", f"{ws}/notebooks"):
                return self._send(200, {"value": stand.notebooks})
            if (method, path) == ("GET", f"{ws}/kqlDatabases"):
                return self._send(200, {"value": [{"id": DATABASE, "displayName": "WindFarmEH"}]})
            kinds = ["operationsAgents", "items"] if stand.specific_paths else ["items"]
            for kind in kinds:
                if (method, path) == ("POST", f"{ws}/{kind}/{AGENT}/getDefinition"):
                    return self._operation(base, stand.definition())
                if (method, path) == ("POST", f"{ws}/{kind}/{AGENT}/updateDefinition"):
                    if stand.refuse_update:
                        status, code, message = stand.refuse_update
                        return self._send(status, {"errorCode": code, "message": message, "requestId": "r-77"})
                    parts = body["definition"]["parts"]
                    assert [p["path"] for p in parts] == [stand.part] and parts[0]["payloadType"] == "InlineBase64"
                    written = json.loads(base64.b64decode(parts[0]["payload"]))
                    classes = [c.get("name") for c in (written.get("playbook") or {}).get("ontologyDefinitions", [])]
                    if stand.refuse_playbook and len(classes) != len(set(classes)):
                        return self._send(400, {"errorCode": "InvalidInput", "requestId": "r-9a", "message": (
                            "The definition is invalid: rule 'Rule Gearbox Vibration Early Warning' monitors class 'TurbineRunSample', but "
                            "'playbook.ontologyDefinitions' defines class 'TurbineRunSample' 3 times. Keep a single entry for class "
                            "'TurbineRunSample' and for each of its properties, then try again.")})
                    stand.document = written
                    return self._operation(base, None)
            if (method, path) == ("POST", f"{ws}/items/{NOTEBOOK}/jobs/instances?jobType=RunNotebook"):
                stand.polls = 0
                where = "http://example.invalid/v1/jobs/1" if stand.location_elsewhere else f"{base}{ws}/items/{NOTEBOOK}/jobs/instances/job-1"
                return self._send(202, None, {"Location": where, "Retry-After": "60"})
            if (method, path) == ("GET", f"{ws}/items/{NOTEBOOK}/jobs/instances/job-1"):
                state = stand.job_states[min(stand.polls, len(stand.job_states) - 1)]
                stand.polls += 1
                return self._send(200, {"id": "job-1", "itemId": NOTEBOOK, "jobType": "RunNotebook", "invokeType": "Manual", "status": state,
                                        "failureReason": stand.job_failure if state == "Failed" else None})
            if method == "GET" and path.startswith("/operations/"):
                name = path.split("/")[2]
                if path.endswith("/result"):
                    result = stand.operations[name]
                    return self._send(200, result) if result is not None else self._send(400, {"errorCode": "OperationHasNoResult", "message": "The operation has no result"})
                seen = stand.operations.setdefault(name + ":polls", 0)
                stand.operations[name + ":polls"] = seen + 1
                return self._send(200, {"status": "Running" if seen == 0 else "Succeeded", "percentComplete": 50 if seen == 0 else 100})
            return self._send(404, {"errorCode": "EndpointNotFound", "message": f"no such path {path}"})

        def _operation(self, base, result):
            if not stand.long_running:
                return self._send(200, result)
            name = f"op{len(stand.operations)}"
            stand.operations[name] = result
            return self._send(202, None, {"Location": f"{base}/operations/{name}", "x-ms-operation-id": name, "Retry-After": "30"})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    stand.env = {"FABRIC_TOKEN": TOKEN, "FABRIC_API": f"http://127.0.0.1:{server.server_port}/v1", "FABRIC_POLL_SECONDS": "0",
                 "AGENT_SAVE_DIR": str(tmp_path / "saved")}
    stand.saved = tmp_path / "saved"
    yield stand
    server.shutdown()
    server.server_close()


def run_tool(stand, *argv, capsys):
    out = io.StringIO()
    code = tool.main(list(argv), env=stand.env, out=out)
    text = out.getvalue() + capsys.readouterr().err
    assert TOKEN not in text
    return code, text


def writes(stand):
    return [r for r in stand.requests if r[0] == "POST" and r[1].endswith("/updateDefinition")]


# ------------------------------------------------------------------------------------------------ show
def test_show_says_what_the_agent_is_and_changes_nothing(fabric, capsys):
    code, text = run_tool(fabric, "show", capsys=capsys)
    assert code == 0, text
    assert "Operations agent WindFarmGearboxWatch" in text and "Running: yes" in text
    assert "Data source kusto1: KustoDatabase WindFarmEH" in text
    assert "Messages go to: admin@contoso.example" in text and "Actions: none" in text
    assert "playbook.ontologyDefinitions: 3 entries (TurbineRunSample, TurbineRunSample, TurbineRunSample)" in text
    assert "playbook.rules: 3 entries (Rule Gearbox Vibration Early Warning, " in text
    assert "The instructions are those of Phase 3" in text
    assert "There is no action named 'Curtail turbine'" in text
    assert not writes(fabric) and not fabric.saved.exists()
    assert all(method == "GET" or path.endswith("/getDefinition") for method, path, _ in fabric.requests)


def test_save_writes_the_definition_to_a_file_and_changes_nothing(fabric, capsys):
    code, text = run_tool(fabric, "save", capsys=capsys)
    assert code == 0, text
    saved = list(fabric.saved.glob("WindFarmGearboxWatch-*.json"))
    assert len(saved) == 1 and f"Saved the agent's definition: {saved[0]}" in text and "No key and no token." in text
    kept = json.loads(saved[0].read_text(encoding="utf-8"))
    assert kept["part"] == "OperationsAgentV1.json" and kept["document"] == phase3_document()      # readable, without decoding
    assert tool.decode_definition(kept["response"]) == ("OperationsAgentV1.json", phase3_document())
    assert "The instructions are those of Phase 3" in text and not writes(fabric) and TOKEN not in saved[0].read_text()
    # A second save in the same second does not write over the first: the earlier file is the backup.
    fixed = datetime(2026, 11, 25, 4, 8, 34, tzinfo=timezone.utc)
    session = tool.Session(tool.Fabric(TOKEN, fabric.env["FABRIC_API"], poll_seconds=0), fabric.env)
    first = tool.keep(session, AGENT, {"n": 1}, "p.json", {"n": 1}, now=fixed)
    second = tool.keep(session, AGENT, {"n": 2}, "p.json", {"n": 2}, now=fixed)
    assert first.name == "WindFarmGearboxWatch-20261125T040834Z.json" and second.name == "WindFarmGearboxWatch-20261125T040834Z-2.json"
    assert json.loads(first.read_text())["document"] == {"n": 1} and json.loads(second.read_text())["document"] == {"n": 2}


# ----------------------------------------------------------------------------------------------- apply
def test_apply_saves_first_then_writes_the_instructions_and_the_action(fabric, capsys):
    before = phase3_document()
    code, text = run_tool(fabric, "apply", capsys=capsys)
    assert code == 0, text
    # 1. The definition as it was is on disk before anything is written.
    saved = list(fabric.saved.glob("WindFarmGearboxWatch-*.json"))
    assert len(saved) == 1
    kept = json.loads(saved[0].read_text())
    assert tool.decode_definition(kept["response"]) == ("OperationsAgentV1.json", before) and kept["agentId"] == AGENT
    order = [path.rsplit("/", 1)[-1] for method, path, _ in fabric.requests if method == "POST"]
    assert order == ["getDefinition", "updateDefinition", "getDefinition"]
    # 2. What was written.
    now = fabric.document
    configuration = now["configuration"]
    assert configuration["instructions"] == spec.setup_text()
    action_key, action = tool.find_action(now)
    assert action_key == action["id"]                                     # as the portal does: the action's id is its key
    assert action["kind"] == "FabricJobAction" and action["displayName"] == "Curtail turbine"
    # "SynapseNotebook" is what the portal writes for a notebook (read back on 24 November 2026), not "Notebook".
    assert action["connection"] == {"jobArtifactId": NOTEBOOK, "jobWorkspaceId": WS, "itemType": "SynapseNotebook", "jobType": "RunNotebook"}
    assert [p["name"] for p in action["parameters"]] == ["turbine", "percent", "duration", "requested_by"]
    assert all(set(p) == {"name", "description"} and p["description"] for p in action["parameters"])
    assert len(action["id"]) == 36 and action["description"] == spec.action_description()
    # 3. What was kept, and how the agent is left.
    for key in ("dataSources", "messageDestination", "identity"):
        assert configuration[key] == before["configuration"][key], key
    assert now["playbook"] == {} and now["shouldRun"] is False
    assert set(now) == set(before) and set(configuration) == set(before["configuration"])
    # 4. What the person is told.
    assert "Instructions and action are those of Phase 5b." in text and "Differs from Phase 5b" not in text
    assert "The agent was running and is now stopped." in text and "generate the playbook" in text
    assert "bash infra/09-remediation-agent.sh --restore " in text
    assert f"Action {action_key}: 'Curtail turbine' (FabricJobAction), runs SynapseNotebook 12_send_edge_command as RunNotebook. Parameters: turbine, percent, duration, requested_by" in text


def test_apply_twice_changes_nothing_more_and_other_actions_stay(fabric, capsys):
    fabric.document["configuration"]["actions"]["notifyFlow"] = {"id": "f", "kind": "PowerAutomateAction", "displayName": "Tell the control room",
                                                               "description": "d", "parameters": [{"name": "Severity"}]}
    assert run_tool(fabric, "apply", capsys=capsys)[0] == 0
    first = json.loads(json.dumps(fabric.document))
    assert run_tool(fabric, "apply", capsys=capsys)[0] == 0
    assert fabric.document == first                                   # the action kept its id
    made_key = tool.find_action(fabric.document)[0]
    assert set(fabric.document["configuration"]["actions"]) == {"notifyFlow", made_key}
    # An action made by hand under another key, with the same name, is updated in place and not doubled.
    actions = fabric.document["configuration"]["actions"]
    actions["a1"] = dict(actions.pop(made_key), parameters=[{"name": "Turbine", "description": "typed by hand"}])
    code, text = run_tool(fabric, "show", capsys=capsys)
    assert "The action's parameters are Turbine; they should be turbine, percent, duration, requested_by." in text
    assert run_tool(fabric, "apply", capsys=capsys)[0] == 0
    assert set(fabric.document["configuration"]["actions"]) == {"notifyFlow", "a1"}
    assert [p["name"] for p in fabric.document["configuration"]["actions"]["a1"]["parameters"]] == ["turbine", "percent", "duration", "requested_by"]


@pytest.mark.parametrize("long_running, specific, part", [(False, True, "Configurations.json"), (True, False, "OperationsAgentV1.json")])
def test_the_part_keeps_its_name_and_both_kinds_of_answer_and_path_work(fabric, capsys, long_running, specific, part):
    """Microsoft's article names the part Configurations.json and the API's sample names it OperationsAgentV1.json."""
    fabric.long_running, fabric.specific_paths, fabric.part = long_running, specific, part
    code, text = run_tool(fabric, "apply", capsys=capsys)
    assert code == 0, text
    assert f"Definition part: {part}" in text and fabric.document["configuration"]["instructions"] == spec.setup_text()


def test_a_refusal_is_reported_in_fabrics_words_and_nothing_is_lost(fabric, capsys):
    fabric.refuse_update = (403, "InsufficientPrivileges", "The caller does not have sufficient permissions to update the item")
    code, text = run_tool(fabric, "apply", capsys=capsys)
    assert code == 3
    assert "ERROR: The Fabric API answered 403: InsufficientPrivileges. It said: The caller does not have sufficient permissions" in text
    assert "(request r-77)" in text
    assert fabric.document == phase3_document() and len(list(fabric.saved.glob("*.json"))) == 1


def test_a_busy_api_is_waited_for_and_a_wrong_token_is_said(fabric, capsys):
    fabric.throttle = 2
    assert run_tool(fabric, "show", capsys=capsys)[0] == 0
    fabric.env["FABRIC_TOKEN"] = "another"
    code, text = run_tool(fabric, "show", capsys=capsys)
    assert code == 3 and "answered 401: TokenExpired" in text and "another" not in text
    fabric.env["FABRIC_TOKEN"] = ""
    code, text = run_tool(fabric, "show", capsys=capsys)
    assert code == 3 and "No token" in text


def test_an_agent_or_a_notebook_that_is_missing_or_double_is_named(fabric, capsys):
    fabric.env["OPERATIONS_AGENT_NAME"] = "WindFarmGearboxWatcher"
    code, text = run_tool(fabric, "apply", capsys=capsys)
    assert code == 3 and "No operations agent named WindFarmGearboxWatcher. Found: AnotherAgent, WindFarmGearboxWatch." in text
    del fabric.env["OPERATIONS_AGENT_NAME"]
    fabric.notebooks.append({"id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "displayName": "12_send_edge_command"})
    code, text = run_tool(fabric, "apply", capsys=capsys)
    assert code == 3 and "2 notebooks are named 12_send_edge_command" in text
    assert not writes(fabric)
    fabric.notebooks[:] = fabric.notebooks[:1]
    code, text = run_tool(fabric, "show", capsys=capsys)        # show still describes the agent
    assert code == 0 and "No notebook named 12_send_edge_command" in text and "Running: yes" in text
    fabric.env["FABRIC_WORKSPACE_NAME"] = "Elsewhere"
    code, text = run_tool(fabric, "show", capsys=capsys)
    assert code == 3 and "No workspace named Elsewhere. Found: My workspace, WindFarmDigitalTwin." in text


def test_a_notebook_imported_again_shows_as_a_difference(fabric, capsys):
    assert run_tool(fabric, "apply", capsys=capsys)[0] == 0
    fabric.notebooks[1]["id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    code, text = run_tool(fabric, "show", capsys=capsys)
    assert "The action does not run the notebook 12_send_edge_command of this workspace" in text and "apply once more" in text


def test_a_definition_this_tool_cannot_read_is_not_written_over(fabric, capsys):
    fabric.document = {"settings": {"something": "else"}}
    code, text = run_tool(fabric, "apply", capsys=capsys)
    assert code == 3 and "no part with a configuration. Its parts: OperationsAgentV1.json, .platform." in text
    assert not writes(fabric)


# --------------------------------------------------------------------------------------------- restore
def test_restore_puts_the_saved_definition_back(fabric, capsys, tmp_path):
    assert run_tool(fabric, "apply", capsys=capsys)[0] == 0
    saved = next(fabric.saved.glob("*.json"))
    code, text = run_tool(fabric, "restore", str(saved), capsys=capsys)
    assert code == 0, text
    assert fabric.document == phase3_document()                      # with its playbook and running again
    assert "The instructions are those of Phase 3" in text and "check its playbook" in text
    other = tmp_path / "other.json"
    other.write_text(json.dumps(dict(json.loads(saved.read_text()), agentId="someone-else")))
    code, text = run_tool(fabric, "restore", str(other), capsys=capsys)
    assert code == 3 and "was saved from another agent" in text
    other.write_text("{}")
    code, text = run_tool(fabric, "restore", str(other), capsys=capsys)
    assert code == 3 and "is not a definition saved by this tool" in text
    assert len(writes(fabric)) == 2


# -------------------------------------------------------------------------------------------- rehearse
def notebook_cells():
    return json.loads((ROOT / "fabric" / "notebooks" / "12_send_edge_command.ipynb").read_text(encoding="utf-8"))["cells"]


def test_the_rehearsal_runs_the_notebook_as_the_action_does(fabric, capsys):
    code, text = run_tool(fabric, "rehearse", "wt-07", capsys=capsys)
    assert code == 0, text
    method, path, body = next(r for r in fabric.requests if "jobs/instances?" in r[1])
    parameters = body["executionData"]["parameters"]
    assert set(parameters) == {name for name, _ in spec.PARAMETERS}
    assert all(set(p) == {"value", "type"} and p["type"] == "string" and isinstance(p["value"], str) for p in parameters.values())
    assert (parameters["turbine"]["value"], parameters["percent"]["value"], parameters["duration"]["value"]) == ("WT-07", "30", "2m")
    assert "NotStarted" in text and "InProgress" in text and "Completed" in text and "The job completed" in text
    # What Fabric does with these values: they replace the ones of the parameter cell. The cells that
    # follow then build a command the control topic accepts.
    cells = [c for c in notebook_cells() if c["cell_type"] == "code"]
    namespace = {}
    exec("".join(cells[0]["source"]), namespace)
    assert "parameters" in cells[0]["metadata"]["tags"] and set(parameters) <= set(namespace)
    namespace.update({name: p["value"] for name, p in parameters.items()})
    for cell in cells[1:4]:                 # what a caller cannot set, the tested code, the command
        exec("".join(cell["source"]), namespace)
    command = namespace["cmd"]
    assert (command["command"], command["turbine"], command["percent"], command["duration"]) == ("curtail", "WT-07", 30.0, "2m")
    assert command["requestedBy"].startswith("rehearsal of the agent's action")


def test_a_failed_rehearsal_says_why_and_a_wrong_turbine_starts_nothing(fabric, capsys):
    fabric.job_states = ["InProgress", "Failed"]
    fabric.job_failure = {"errorCode": "NotebookExecutionFailed", "message": "CommandError: '' is not a turbine. Use WT-01 to WT-12, or the word all."}
    code, text = run_tool(fabric, "rehearse", "WT-07", capsys=capsys)
    assert code == 1 and "The job ended as Failed. NotebookExecutionFailed CommandError: '' is not a turbine" in text
    fabric.requests.clear()
    for wrong in ("WT-13", "all", ""):
        code, text = run_tool(fabric, "rehearse", wrong, capsys=capsys)
        assert code == 3 and not [r for r in fabric.requests if "jobs/instances" in r[1]], (wrong, text)


def test_the_token_is_not_sent_to_another_address(fabric, capsys):
    fabric.location_elsewhere = True
    code, text = run_tool(fabric, "rehearse", "WT-07", capsys=capsys)
    assert code == 3 and "pointed to another address (example.invalid)" in text


def test_the_token_goes_over_https_only(fabric, capsys):
    fabric.env["FABRIC_API"] = "http://api.fabric.example/v1"
    code, text = run_tool(fabric, "show", capsys=capsys)
    assert code == 3 and "The token is sent over https only" in text and fabric.requests == []


def test_the_script_hands_the_token_over_and_never_shows_it(fabric, tmp_path):
    """infra/09-remediation-agent.sh from end to end: a stand-in for the Azure CLI gives the token, the
    script passes it to the tool in the environment, and the tool talks to the stand-in for Fabric."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    az = bin_dir / "az"
    az.write_text(f"""#!/usr/bin/env bash
echo "az $*" >> "{tmp_path}/az.log"
case "$*" in
  "account show"*) echo user ;;
  "account get-access-token --resource https://api.fabric.microsoft.com --query accessToken --output tsv") echo "{TOKEN}" ;;
  *) echo "unexpected az $*" >&2; exit 9 ;;
esac
""", encoding="utf-8")
    az.chmod(0o755)
    env_file = tmp_path / "demo.env"
    env_file.write_text((ROOT / "config" / "demo.env.example").read_text(encoding="utf-8"), encoding="utf-8")
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", ENV_FILE=str(env_file), **{k: v for k, v in fabric.env.items() if k != "FABRIC_TOKEN"})
    env.pop("FABRIC_TOKEN", None)

    def script(*args):
        done = subprocess.run(["bash", str(ROOT / "infra" / "09-remediation-agent.sh"), *args], env=env, capture_output=True, text=True)
        assert TOKEN not in done.stdout + done.stderr
        return done.returncode, done.stdout + done.stderr

    code, text = script("--show")
    assert code == 0 and "The instructions are those of Phase 3" in text, text
    code, text = script()
    assert code == 0 and "Instructions and action are those of Phase 5b." in text, text
    assert the_action(fabric.document)["connection"]["jobArtifactId"] == NOTEBOOK
    code, text = script("--rehearse", "WT-07")
    assert code == 0 and "The job completed" in text, text
    saved = next(fabric.saved.glob("*.json"))
    code, text = script("--restore", str(saved))
    assert code == 0 and fabric.document == phase3_document(), text
    code, text = script("--save")
    assert code == 0 and "Saved the agent's definition: " in text and len(list(fabric.saved.glob("*.json"))) == 2, text
    # Obstacle C, 24 November: Fabric refuses to take back a playbook its own portal generated. The script says so,
    # and says how to go back by hand.
    fabric.refuse_playbook = True
    code, text = script("--restore", str(saved))
    assert code == 3 and "defines class 'TurbineRunSample' 3 times" in text, text
    assert "The saved definition was not put back. The agent is as it was." in text and "fabric/operations-agent/agent-setup.txt" in text
    fabric.refuse_playbook = False
    # Fabric refuses the change: the script says how to do it by hand.
    fabric.refuse_update = (403, "InsufficientPrivileges", "The caller does not have sufficient permissions")
    code, text = script()
    assert code == 3 and "InsufficientPrivileges" in text and "Do it by hand instead: step 4 of docs/13-deployment-guide-phase5b.md" in text
    assert TOKEN not in (tmp_path / "az.log").read_text()


def test_the_hints_name_the_step_of_the_guide_that_holds_the_way_by_hand():
    """Obstacle B, 24 November: the script sent the user to step 3, which is the rehearsal. The steps were
    renumbered after the hint was written, and nothing compared the two."""
    guide = (ROOT / "docs" / "13-deployment-guide-phase5b.md").read_text(encoding="utf-8")
    before = guide[:guide.index("\n### By hand\n")]
    step = re.findall(r"^## Step (\d+): ", before, flags=re.M)[-1]
    script = (ROOT / "infra" / "09-remediation-agent.sh").read_text(encoding="utf-8")
    action = (ROOT / "fabric" / "operations-agent" / "phase5b-action.txt").read_text(encoding="utf-8")
    assert re.findall(r"step (\d+) of (?:docs/13-deployment-guide-phase5b\.md|the guide)", script) == [step, step]
    replace = re.search(r"^## Step (\d+): Replace the notebook$", guide, flags=re.M).group(1)
    assert re.findall(r"guide, step (\d+)", action) == [step, replace]      # by hand; and where the notebook is replaced
    # And every "step N" of the guide that says what a step does points at a step with that subject.
    for number, subject in re.findall(r"\[Step (\d+): ([^\]]+)\]\(#", guide):
        assert f"## Step {number}: {subject}" in guide


def test_wrong_arguments_are_refused_without_a_call(fabric, capsys):
    for argv in ([], ["delete"], ["restore"], ["rehearse"], ["show", "extra"]):
        assert tool.main(argv, env=fabric.env, out=io.StringIO()) == 2
    assert "Use: show, save, apply, restore FILE, or rehearse TURBINE." in capsys.readouterr().err
    assert fabric.requests == []


# ------------------------------------------------------------------------------- the definition itself
def test_the_definition_follows_the_published_schema():
    """The shape of Microsoft's article 'Operations agent definition' (read on 24 November 2026)."""
    made = tool.with_remediation(phase3_document(), NOTEBOOK, WS, new_id=lambda: "55555555-5555-4555-8555-555555555555")
    assert set(made) == {"configuration", "playbook", "shouldRun"}
    action = made["configuration"]["actions"]["55555555-5555-4555-8555-555555555555"]
    assert set(action) == {"id", "kind", "displayName", "description", "connection", "parameters"}
    assert set(action["connection"]) == {"jobArtifactId", "jobWorkspaceId", "itemType", "jobType"}
    # The instructions travel as one JSON string: the page's own example breaks a string over two lines,
    # which no JSON reader accepts, so the round trip is checked here.
    body = tool.encode_definition("Configurations.json", made)
    again = json.loads(base64.b64decode(body["definition"]["parts"][0]["payload"]))
    assert again == made and "\n" in again["configuration"]["instructions"]
    assert tool.differences(made, NOTEBOOK, WS, DATABASE) == []
    # Instructions pasted by hand in the portal come back with other line ends and spaces at the end of lines.
    by_hand = json.loads(json.dumps(made))
    by_hand["configuration"]["instructions"] = made["configuration"]["instructions"].replace("\n", " \r\n") + "\r\n\r\n"
    assert tool.differences(by_hand, NOTEBOOK, WS, DATABASE) == []
    by_hand["configuration"]["instructions"] = by_hand["configuration"]["instructions"].replace("crosses above 4 mm/s", "is above 4 mm/s")
    assert tool.differences(by_hand, NOTEBOOK, WS, DATABASE) == [
        "The instructions speak of the table and the action of Phase 5b and are not word for word those of fabric/operations-agent/phase5b-agent-setup.txt."]


def test_the_agent_as_the_portal_made_it_counts_as_phase_5b():
    """What --show printed for the user's agent after the way by hand, 24 November 2026, 22:38: the action under
    its id as key, item type SynapseNotebook, no message destination, the data source under its id, no playbook yet."""
    by_hand = {"configuration": {
        "instructions": spec.setup_text(),
        "dataSources": {DATABASE: {"id": DATABASE, "type": "KustoDatabase", "workspaceId": WS}},
        "actions": {"29c47124-3741-4b55-b807-c43d142a3eb1": {
            "id": "29c47124-3741-4b55-b807-c43d142a3eb1", "kind": "FabricJobAction", "displayName": "Curtail turbine", "description": "typed in the dialog",
            "connection": {"jobArtifactId": NOTEBOOK, "jobWorkspaceId": WS, "itemType": "SynapseNotebook", "jobType": "RunNotebook"},
            "parameters": [{"name": name, "type": "string", "description": "pasted"} for name, _ in spec.PARAMETERS]}}},
        "playbook": {}, "shouldRun": False}
    assert tool.differences(by_hand, NOTEBOOK, WS, DATABASE) == []
    lines = tool.describe(by_hand, "Configurations.json", {NOTEBOOK: "12_send_edge_command", DATABASE: "WindFarmEH"})
    assert "Definition part: Configurations.json" in lines and "Running: no" in lines and "Playbook in the definition: empty" in lines
    assert ("Action 29c47124-3741-4b55-b807-c43d142a3eb1: 'Curtail turbine' (FabricJobAction), runs SynapseNotebook 12_send_edge_command "
            "as RunNotebook. Parameters: turbine, percent, duration, requested_by") in lines
    # Running the script on it afterwards keeps the action's key and id, and whatever else the portal wrote into a parameter.
    again = tool.with_remediation(by_hand, NOTEBOOK, WS)
    assert list(again["configuration"]["actions"]) == ["29c47124-3741-4b55-b807-c43d142a3eb1"]
    assert again["configuration"]["actions"]["29c47124-3741-4b55-b807-c43d142a3eb1"]["id"] == "29c47124-3741-4b55-b807-c43d142a3eb1"


def test_the_action_cannot_stop_a_turbine():
    """The action has no parameter for the command, so the notebook's own value applies, and that is curtail."""
    names = [name for name, _ in spec.PARAMETERS]
    assert "command" not in names and "reason" not in names and "dry_run" not in names
    code = ["".join(c["source"]) for c in notebook_cells() if c["cell_type"] == "code"]
    assert 'turbine = ""' in code[0] and "command" not in code[0].replace("a command names its turbine", "")
    assert 'command = "curtail"' in code[1] and 'dry_run = False' in code[1]      # set after a caller's values
    # Whatever is typed into the four parameters, the command that is built is a curtailment of one turbine, or nothing.
    for turbine, percent, duration in (("WT-03", "30", "60m"), ("WT-03", "0", "1h"), ("stop WT-03", "30", "60m"), ("all", "30", "60m"),
                                       ("WT-03", "stop", "60m"), ("WT-03", "30", "forever")):
        try:
            command = edge.from_parameters("curtail", turbine, percent=percent, duration=duration)
        except edge.CommandError:
            continue
        assert command["command"] == "curtail" and command["duration"] and 0 <= command["percent"] <= 100
        assert command["turbine"] in ("WT-03", "all")
