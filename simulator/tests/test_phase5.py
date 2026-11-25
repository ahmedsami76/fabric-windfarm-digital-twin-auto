"""Phase 5: the command a notebook writes in Fabric is one the simulator's control topic accepts (5a), and
the curtailment the operations agent proposes relieves the gearbox it is proposed for (5b)."""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import run

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


edge = _load("edge_command", ROOT / "tools" / "edge_command.py")
remediation = _load("remediation_spec", ROOT / "tools" / "remediation_spec.py")
NOTEBOOK = ROOT / "fabric" / "notebooks" / "12_send_edge_command.ipynb"
NOW = datetime(2026, 11, 23, 16, 0, 0, tzinfo=timezone.utc)


def cells():
    return json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]


def source(cell) -> str:
    return "".join(cell["source"])


def test_notebook_is_current_and_its_cells_compile():
    assert subprocess.run([sys.executable, str(ROOT / "tools" / "build-phase5.py"), "--check"], capture_output=True).returncode == 0
    code = [c for c in cells() if c["cell_type"] == "code"]
    for cell in code:
        compile(source(cell), "cell", "exec")
        # No magic and no shell line: "%pip magic command is disabled" is what a notebook answers when it
        # runs as a job, and the action of the operations agent runs this notebook as a job.
        assert not [line for line in source(cell).split("\n") if line.startswith(("%", "!"))], source(cell)[:80]
    kinds = ["parameters" if "parameters" in c["metadata"].get("tags", []) else "other" for c in code]
    assert kinds[0] == "parameters" and kinds.count("parameters") == 1, kinds


def test_notebook_carries_the_tested_code_and_keeps_no_key():
    whole = "\n".join(source(c) for c in cells())
    module = (ROOT / "tools" / "edge_command.py").read_text(encoding="utf-8")
    for name in ("def build_command", "def find_custom_endpoint", "def send_settings", "def payload"):
        assert name in whole and name in module
    assert module.split("def build_command", 1)[1] in whole
    for forbidden in ("SharedAccessKey=", "Endpoint=sb://", "print(settings)", "print(connection"):
        assert forbidden not in whole
    assert "'connectionString']" not in whole.replace('settings["connectionString"]', "")


@pytest.mark.parametrize("args, state, check", [
    (dict(command="curtail", turbine="wt-01", percent=30, duration="10m"), "CURTAILED", lambda t: t.setpoint_kw == pytest.approx(0.30 * 4200)),
    (dict(command="stop", turbine="WT-01", duration="10m", reason="maintenance"), "MAINTENANCE", lambda t: t.manual_stop == "maintenance"),
])
def test_the_simulator_accepts_and_applies_what_the_notebook_builds(make_sim, args, state, check):
    sim = make_sim(wind=12.0)
    run(sim, 120)
    cmd = json.loads(edge.payload(edge.build_command(now=NOW, requested_by="ops@contoso.example", **args)))
    ack = sim.handle_command(cmd, channel="control")
    assert ack["ok"], ack
    assert ack["requestId"] == cmd["requestId"] and len(cmd["requestId"]) == 12
    run(sim, 180)
    assert sim.turbines["WT-01"].state == state
    assert check(sim.turbines["WT-01"])
    assert sim.turbines["WT-02"].state == "RUNNING"  # one turbine was named, one turbine changed
    undo = "release" if args["command"] == "curtail" else "start"
    assert sim.handle_command(edge.build_command(undo, "WT-01", now=NOW), channel="control")["ok"]
    run(sim, 120)
    assert sim.turbines["WT-01"].state == "RUNNING"


def test_a_curtailment_ends_by_itself(make_sim):
    sim = make_sim(wind=12.0)
    run(sim, 120)
    assert sim.handle_command(edge.build_command("curtail", "WT-01", percent=30, duration="2m", now=NOW), channel="control")["ok"]
    run(sim, 60)
    assert sim.turbines["WT-01"].state == "CURTAILED"
    run(sim, 180)
    assert sim.turbines["WT-01"].state == "RUNNING"


def test_every_command_of_the_notebook_is_one_of_the_control_topic(make_sim):
    from windfarm_sim.engine import CONTROL_COMMANDS
    assert set(edge.COMMANDS) == set(CONTROL_COMMANDS)
    sim = make_sim()
    for name in edge.COMMANDS:
        cmd = edge.build_command(name, "WT-03", percent=50 if name == "curtail" else None, duration="5m" if name == "curtail" else "", now=NOW)
        assert sim.handle_command(cmd, channel="control")["ok"], name
    # The control topic refuses what the notebook must never send; so does the notebook itself.
    assert not sim.handle_command({"command": "inject", "turbine": "WT-03"}, channel="control")["ok"]
    with pytest.raises(edge.CommandError):
        edge.build_command("inject", "WT-03")


@pytest.mark.parametrize("args, says", [
    (dict(command="curtail", turbine="", percent=30, duration="10m"), "not a turbine"),          # the simulator would take "" as all twelve
    (dict(command="curtail", turbine=None, percent=30, duration="10m"), "not a turbine"),
    (dict(command="curtail", turbine="WT-13", percent=30, duration="10m"), "not a turbine"),
    (dict(command="curtail", turbine="WT-07'; drop", percent=30, duration="10m"), "not a turbine"),
    (dict(command="curtail", turbine="WT-07", percent=None, duration="10m"), "needs percent"),
    (dict(command="curtail", turbine="WT-07", percent=130, duration="10m"), "between 0 and 100"),
    (dict(command="curtail", turbine="WT-07", percent=-5, duration="10m"), "between 0 and 100"),
    (dict(command="curtail", turbine="WT-07", percent=30, duration=""), "needs a duration"),
    (dict(command="curtail", turbine="WT-07", percent=30, duration="soon"), "not a duration"),
    (dict(command="curtail", turbine="WT-07", percent=30, duration="0m"), "not a duration"),
    (dict(command="release", turbine="WT-07", percent=30), "takes no percent"),
    (dict(command="start", turbine="WT-07", duration="10m"), "takes no duration"),
    (dict(command="stop", turbine="WT-07", reason="because"), "reason of a stop"),
    (dict(command="wind", turbine="WT-07"), "not a command"),
])
def test_what_would_do_more_than_asked_is_refused_before_it_is_sent(args, says):
    with pytest.raises(edge.CommandError, match=says):
        edge.build_command(**args)


def test_all_turbines_only_when_the_word_is_written(make_sim):
    cmd = edge.build_command("curtail", "ALL", percent=50, duration="5m", now=NOW)
    assert cmd["turbine"] == "all"
    sim = make_sim()
    assert sorted(sim.handle_command(cmd, channel="control")["result"]["curtailed"]) == sorted(sim.turbines)


def test_the_lookup_reads_the_answers_of_the_fabric_api():
    assert edge.find_item([{"id": "1", "displayName": "es-windfarm-edge"}, {"id": "2", "displayName": "WindFarmCommands"}], "WindFarmCommands") == "2"
    assert edge.find_item([], "WindFarmCommands") is None
    topology = {"sources": [{"id": "s", "type": "CustomEndpoint"}], "destinations": [{"id": "k", "type": "Eventhouse"}, {"id": "d", "type": "CustomEndpoint"}]}
    assert edge.find_custom_endpoint(topology, "sources") == "s"
    assert edge.find_custom_endpoint(topology, "destinations") == "d"
    assert edge.find_custom_endpoint({}, "sources") is None
    good = {"fullyQualifiedNamespace": "ns.servicebus.windows.net", "eventHubName": "es_1", "accessKeys": {"primaryConnectionString": "Endpoint=sb://ns/;SharedAccessKey=k"}}
    assert edge.send_settings(good) == {"namespace": "ns.servicebus.windows.net", "eventHub": "es_1", "connectionString": "Endpoint=sb://ns/;SharedAccessKey=k"}
    with pytest.raises(edge.CommandError, match="accessKeys.primaryConnectionString") as failure:
        edge.send_settings({"fullyQualifiedNamespace": "ns", "eventHubName": "es_1", "accessKeys": {"primaryKey": "K3y~value"}})
    assert "K3y~value" not in str(failure.value)  # an error message names what is missing, never what is there


def test_the_script_and_the_data_flow_name_the_topic_the_simulator_listens_on(make_sim):
    sim = make_sim()
    assert sim.control_topic == "contoso/windfarm/northwind-ridge/_control/request"
    script = (ROOT / "infra" / "08-create-command-path.sh").read_text(encoding="utf-8")
    assert 'CONTROL_TOPIC="$TOPIC_ROOT/$SITE_ID/_control/request"' in script
    assert ': "${TOPIC_ROOT:=contoso/windfarm}"' in script and ': "${SITE_ID:=northwind-ridge}"' in script
    template = json.loads((ROOT / "edge" / "dataflows" / "fabric-to-windfarm-control.template.json").read_text(encoding="utf-8"))
    src, dst = template["operations"]
    assert src["operationType"] == "Source" and src["sourceSettings"]["endpointRef"] == "__ENDPOINT_NAME__"
    assert dst["destinationSettings"] == {"endpointRef": "default", "dataDestination": "__CONTROL_TOPIC__"}
    # The eventstream the script makes is the one the notebook looks for.
    builder = (ROOT / "tools" / "build-phase5.py").read_text(encoding="utf-8")
    assert 'EVENTSTREAM = "WindFarmCommands"' in builder and ': "${COMMAND_EVENTSTREAM_NAME:=WindFarmCommands}"' in script


def test_the_cells_run_in_order_against_a_pretend_fabric(monkeypatch, capsys):
    """Every code cell executed top to bottom in one namespace, with stand-ins for the three things only
    Fabric has: the notebook utilities, the Fabric REST client and the network to the event hub."""

    sent = []
    asked = []

    class Response:
        def __init__(self, body, status=200):
            self.status_code, self._body, self.text = status, body, json.dumps(body)

        def json(self):
            return self._body

    class Client:
        def get(self, path):
            asked.append(path)
            if path.endswith("/eventstreams"):
                return Response({"value": [{"id": "es-id", "displayName": "WindFarmCommands"}]})
            if path.endswith("/topology"):
                return Response({"sources": [{"id": "src-id", "type": "CustomEndpoint"}], "destinations": []})
            if path.endswith("/sources/src-id/connection"):
                return Response({"fullyQualifiedNamespace": "ns.servicebus.windows.net", "eventHubName": "es_1",
                                 "accessKeys": {"primaryConnectionString": "Endpoint=sb://ns.servicebus.windows.net/;SharedAccessKeyName=k;SharedAccessKey=S3cr3t=;EntityPath=es_1"}})
            return Response({"message": "not found"}, 404)

    class Batch(list):
        add = list.append

    class Producer:
        @classmethod
        def from_connection_string(cls, text, **kwargs):
            assert "EntityPath=es_1" in text and "eventhub_name" not in kwargs and kwargs["transport_type"] == "websocket"
            return cls()

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def create_batch(self):
            return Batch()

        def send_batch(self, batch):
            sent.extend(batch)

    class EventData:
        def __init__(self, body):
            self.body, self.content_type = body, None

    fabric = types.ModuleType("sempy.fabric")
    fabric.FabricRestClient, fabric.get_workspace_id = Client, lambda: "ws-id"
    sempy = types.ModuleType("sempy")
    sempy.fabric = fabric
    eventhub = types.ModuleType("azure.eventhub")
    eventhub.EventData, eventhub.EventHubProducerClient = EventData, Producer
    eventhub.TransportType = types.SimpleNamespace(AmqpOverWebsocket="websocket")
    azure = types.ModuleType("azure")
    azure.eventhub = eventhub
    for name, module in (("sempy", sempy), ("sempy.fabric", fabric), ("azure", azure), ("azure.eventhub", eventhub),
                         ("websocket", types.ModuleType("websocket"))):
        monkeypatch.setitem(sys.modules, name, module)
    utils = types.SimpleNamespace(runtime=types.SimpleNamespace(context={"userName": "sami@contoso.example"}))

    def run_all(overrides, by_hand=()):
        """Run all, the way Fabric does it for a caller: its values are set right after the parameter cell.
        `by_hand` is what a person changed in a cell before running: pairs of text to find and to put."""
        namespace = {"notebookutils": utils}
        for cell in cells():
            if cell["cell_type"] != "code":
                continue
            text = source(cell)
            for old, new in by_hand:
                text = text.replace(old, new)
            exec(text, namespace)
            if "parameters" in cell["metadata"].get("tags", []):
                namespace.update(overrides)
        return namespace

    run_all({"turbine": "WT-07"})
    out = capsys.readouterr().out
    assert asked == ["v1/workspaces/ws-id/eventstreams", "v1/workspaces/ws-id/eventstreams/es-id/topology",
                     "v1/workspaces/ws-id/eventstreams/es-id/sources/src-id/connection"]
    assert len(sent) == 1 and sent[0].content_type == "application/json"
    command = json.loads(sent[0].body)
    assert command["command"] == "curtail" and command["turbine"] == "WT-07" and command["percent"] == 30 and command["duration"] == "10m"
    assert command["requestedBy"] == "sami@contoso.example"
    assert f"request {command['requestId']}" in out and "Writes to ns.servicebus.windows.net, event hub es_1" in out
    assert "S3cr3t" not in out and "SharedAccessKey" not in out

    # dry_run sends nothing. A person sets it in the second code cell; it is not a value a caller can pass.
    sent.clear()
    run_all({"turbine": "WT-07"}, by_hand=[("dry_run = False", "dry_run = True")])
    assert sent == [] and "nothing was sent" in capsys.readouterr().out

    # As delivered, the notebook names no turbine and sends nothing: a caller that forgets the turbine
    # must not curtail one that happened to be the default.
    with pytest.raises(Exception, match="not a turbine") as refused:  # the notebook carries its own copy of the class
        run_all({})
    assert type(refused.value).__name__ == "CommandError" and sent == []

    # What the operations agent passes, as text: the action's four parameters.
    sent.clear()
    run_all({"turbine": "WT-03", "percent": "30", "duration": "60m",
             "requested_by": "operations agent WindFarmGearboxWatch, approved in Teams"})
    agent_command = json.loads(sent[0].body)
    assert (agent_command["turbine"], agent_command["percent"], agent_command["duration"]) == ("WT-03", 30.0, "60m")
    assert agent_command["requestedBy"].startswith("operations agent")

    # Fabric offers every name of the parameter cell to the agent's action (seen on 24 November 2026), so the
    # command is not in that cell. A caller that passes one anyway, with a dry run, a reason and another
    # eventstream, still gets a curtailment of the turbine it named, sent to the eventstream of this notebook.
    sent.clear()
    asked.clear()
    run_all({"turbine": "WT-03", "percent": "30", "duration": "60m", "command": "stop", "reason": "maintenance",
             "dry_run": "True", "EVENTSTREAM": "SomethingElse"})
    forced = json.loads(sent[0].body)
    assert forced["command"] == "curtail" and forced["turbine"] == "WT-03" and "reason" not in forced and "note" not in forced
    assert asked[0].endswith("/eventstreams") and len(sent) == 1
    parameter_cell = next(source(c) for c in cells() if "parameters" in c["metadata"].get("tags", []))
    assert re.findall(r"^([A-Za-z_]+) = ", parameter_cell, flags=re.M) == ["turbine", "percent", "duration", "requested_by"]

    # One turbine at a time: as the agent's action this notebook does not take the word all.
    sent.clear()
    with pytest.raises(Exception, match="one turbine at a time"):
        run_all({"turbine": "all", "percent": "30", "duration": "60m"})
    assert sent == []

    # By hand, a person may still send another command with this notebook, by changing the second code cell.
    run_all({"turbine": "WT-07"}, by_hand=[('command = "curtail"', 'command = "release"')])
    assert json.loads(sent[0].body)["command"] == "release"



@pytest.mark.parametrize("written", ["curtail", "Curtail", "CURTAIL", " curtail ", "cUrTaIl"])
def test_the_command_may_be_written_in_any_case(written):
    """Found in review on 23 November: the cell decided by the name as typed, so `Curtail` lost its percent."""
    cmd = edge.from_parameters(written, "WT-07", percent=30, duration="10m", now=NOW)
    assert (cmd["command"], cmd["percent"], cmd["duration"]) == ("curtail", 30.0, "10m")


@pytest.mark.parametrize("written", ["stop", "Stop", "STOP"])
def test_a_stop_keeps_its_end_however_it_is_written(make_sim, written):
    """The same fault, with a worse result: `Stop` lost its duration silently and became a stop without an end."""
    cmd = edge.from_parameters(written, "WT-01", percent=30, duration="2m", now=NOW)
    assert cmd["command"] == "stop" and cmd["duration"] == "2m" and "percent" not in cmd
    sim = make_sim(wind=12.0)
    run(sim, 120)
    assert sim.handle_command(cmd, channel="control")["ok"]
    run(sim, 60)
    assert sim.turbines["WT-01"].state != "RUNNING"
    run(sim, 180)
    assert sim.turbines["WT-01"].state == "RUNNING"


def test_values_of_the_other_commands_are_left_out_not_refused():
    """Step 6 of the guide: only the command is changed to release; percent and duration stay in the cell."""
    for name in ("release", "Release", "start", "reset"):
        cmd = edge.from_parameters(name, "WT-07", percent=30, duration="10m", now=NOW)
        assert "percent" not in cmd and "duration" not in cmd, name


@pytest.mark.parametrize("percent, duration, want", [
    ("30", "10m", (30.0, "10m")), ("30%", "10 m", (30.0, "10m")), (" 30 % ", "10 min", (30.0, "10m")),
    (30, "10 minutes", (30.0, "10m")), (30, "90 seconds", (30.0, "90s")), (30, "1 hour", (30.0, "1h")), (30, "2 HRS", (30.0, "2h")),
])
def test_a_percentage_and_a_duration_are_read_as_people_write_them(percent, duration, want):
    cmd = edge.from_parameters("curtail", "WT-07", percent=percent, duration=duration, now=NOW)
    assert (cmd["percent"], cmd["duration"]) == want


@pytest.mark.parametrize("percent, duration, says", [
    ("thirty", "10m", "needs percent"), ("30", "600", "not a duration"), ("30", "ten minutes", "not a duration"),
    ("30", "10 fortnights", "not a duration"), ("130%", "10m", "between 0 and 100"), ("30", "", "needs a duration"),
])
def test_what_cannot_be_read_is_still_refused(percent, duration, says):
    with pytest.raises(edge.CommandError, match=says):
        edge.from_parameters("curtail", "WT-07", percent=percent, duration=duration)


def test_dry_run_written_as_text_is_read_as_what_it_says():
    """A parameter that arrives as the text "False" is a true value to Python; the notebook would have sent nothing."""
    assert [edge.as_flag(v) for v in (True, "True", "true", " TRUE ", "1", "yes")] == [True] * 6
    assert [edge.as_flag(v) for v in (False, "False", "false", "0", "no", "")] == [False] * 6
    with pytest.raises(edge.CommandError, match="write True or False"):
        edge.as_flag("maybe")
    code = "\n".join(source(c) for c in cells() if c["cell_type"] == "code")
    assert "dry_run = as_flag(dry_run)" in code and "from_parameters(command, turbine" in code
    assert 'if command == "curtail"' not in code and "command in (" not in code.split("def from_parameters")[0].split("# The command, checked")[-1]


def test_the_send_cell_brings_what_the_transport_needs_without_a_magic(monkeypatch, tmp_path, capsys):
    """Obstacle A, 24 November: the send over port 443 needs websocket-client, which azure-eventhub does not
    install. And a job may not use %pip, so the cell installs with pip as a command, when a library is missing."""
    send = next(source(c) for c in cells() if c["cell_type"] == "code" and source(c).startswith("# Send."))
    assert "TransportType.AmqpOverWebsocket" in send
    assert re.search(r'bring\("websocket", "websocket-client==\d+\.\d+\.\d+"\)', send)
    assert re.search(r'bring\("azure\.eventhub", "azure-eventhub==\d+\.\d+\.\d+"\)', send)
    assert send.index('bring("websocket"') < send.index('bring("azure.eventhub"') < send.index("from azure.eventhub import")

    namespace = {"dry_run": True}
    exec(send, namespace)                      # defines bring(); with dry_run nothing else happens
    bring = namespace["bring"]
    assert bring("json", "never-installed==0") is json          # a library that is there is not installed again

    import site
    user_site = tmp_path / "user-site"
    ran = []

    def pip(command, **kwargs):
        ran.append(command)
        if command[-1] == "broken==1":
            return types.SimpleNamespace(returncode=1, stdout="", stderr="ERROR: No matching distribution found for broken==1")
        user_site.mkdir(exist_ok=True)
        (user_site / "library_of_phase5b.py").write_text("ANSWER = 42\n", encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", pip)
    monkeypatch.setattr(site, "getusersitepackages", lambda: str(user_site))
    monkeypatch.setattr(sys, "path", list(sys.path))
    # The folder did not exist when the interpreter started, so it is not on the path: the case of a
    # runtime whose own folder is read-only, where pip installs for the user.
    assert bring("library_of_phase5b", "library-of-phase5b==1.0").ANSWER == 42
    assert ran == [[sys.executable, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "library-of-phase5b==1.0"]]
    assert "Installed library-of-phase5b==1.0" in capsys.readouterr().out
    sys.modules.pop("library_of_phase5b", None)
    with pytest.raises(SystemExit, match="pip could not install broken==1: ERROR: No matching distribution"):
        bring("library_that_is_not_there", "broken==1")


def test_the_send_gets_as_far_as_the_network_with_the_pinned_libraries():
    """The check that was missing: open the connection, not only build the client. The transport loads its
    library when it connects, so a client that is only constructed proves nothing about it. Skipped where
    the two libraries of the install cell are not installed."""
    eventhub = pytest.importorskip("azure.eventhub")
    pytest.importorskip("websocket")
    producer = eventhub.EventHubProducerClient.from_connection_string(
        "Endpoint=sb://127.0.0.1:9/;SharedAccessKeyName=k;SharedAccessKey=YWJj;EntityPath=es_1",
        transport_type=eventhub.TransportType.AmqpOverWebsocket, retry_total=0)
    with pytest.raises(Exception) as failure:
        with producer:
            producer.create_batch()
    assert not isinstance(failure.value, ImportError), failure.value
    assert "Please install" not in str(failure.value)


# ------------------------------------------------------------------------------------------- Phase 5b
def _gearbox(sim, tid, seconds):
    """Mean vibration, oil temperature and power of one turbine over the next `seconds` of simulation."""
    vib, oil, power = [], [], []
    for _ in range(seconds):
        sim.step(1.0)
        signals = sim.turbines[tid]._signals
        vib.append(signals["gearboxVibration"]), oil.append(signals["gearboxOilTemp"]), power.append(signals["activePower"])
    mean = lambda values: sum(values) / len(values)
    return mean(vib), mean(oil), mean(power), sim.turbines[tid].state


@pytest.mark.parametrize("wind", [8.5, 10.0, 11.0, 12.0, 13.0])
def test_a_curtailment_relieves_a_gearbox_that_runs_rough(make_sim, wind, capsys):
    """The story of Phase 5b in the simulator: a small fault held on WT-03, then the command the agent proposes.
    The curtailment has to show in the symptom, or approving it would change nothing a person can see."""
    bites = wind >= 10.0  # below that the turbine delivers less than the limit of 1260 kW anyway
    sim = make_sim(wind=wind)
    run(sim, 300)
    assert sim.handle_command({"command": "inject", "turbine": "WT-03", "kind": "gearbox_degradation", "severity": 0.2, "hold": True}, channel="sim")["ok"]
    run(sim, 900)
    before = _gearbox(sim, "WT-03", 300)
    assert before[3] == "RUNNING" and before[0] > 4.0, before
    warning = sim.turbines["WT-03"].alarms["GBX-OIL-TEMP-HIGH"]
    warned = warning.active
    assert sim.handle_command(edge.from_parameters("curtail", "WT-03", percent=30, duration="60m", now=NOW), channel="control")["ok"]
    run(sim, 900)
    after = _gearbox(sim, "WT-03", 300)
    with capsys.disabled():
        print(f"\n   wind {wind}: before {before[0]:.2f} mm/s, {before[1]:.1f} degC, {before[2]:.0f} kW; curtailed {after[0]:.2f} mm/s, {after[1]:.1f} degC, {after[2]:.0f} kW, {after[3]}")
    assert after[3] == "CURTAILED" and after[2] <= 0.30 * 4200 + 30
    if not bites:
        assert before[2] < 0.30 * 4200 and remediation.cost_per_hour(before[2]) == 0  # nothing to lose, little to gain
        return
    assert remediation.cost_per_hour(before[2]) > 15
    assert after[0] < before[0] - 0.1, (before, after)       # less vibration
    assert after[1] < before[1] - 3.0, (before, after)       # a cooler gearbox
    assert after[1] < remediation.ALARM_OIL_TEMP              # back under the controller's alarm level
    assert after[0] > remediation.EARLY_VIBRATION             # and still past the early warning: relieved, not cured
    # What a person sees in the twin: at 13 m/s the controller has raised its oil-temperature warning by
    # now, and it clears by itself once the turbine is limited.
    if wind >= 13.0:
        assert warned
    assert not warning.active
    assert any(a.kind == "gearbox_degradation" for a in sim.anomalies if a.turbine_id == "WT-03")  # relieved, not cured


def test_the_figures_of_the_decision_are_those_of_the_reference_data():
    f = remediation.facts()
    assert f == {"ratedPowerKw": 4200.0, "limitKw": 1260.0, "priceUsdPerMwh": 38.5, "exchangeUsd": 385000, "leadTimeDays": 140, "warrantyEnd": "2026-12-31"}
    kql = (ROOT / "fabric" / "kql" / "06-remediation-readiness.kql").read_text(encoding="utf-8")
    for line in ("let RatedPowerKw = 4200.0;", "let CurtailPercent = 30;", "let PriceUsdPerMwh = 38.5;", "let ExchangeUsd = long(385000);",
                 "let LeadTimeDays = 140;", "let WarrantyEnd = datetime(2026-12-31);"):
        assert line in kql, line
    # The arithmetic of the table, in Python: 3,090 kW at 12 m/s loses 1,830 kW, which is 70 USD an hour.
    assert remediation.cost_per_hour(3090) == 70 and remediation.cost_per_hour(1260) == 0 and remediation.cost_per_hour(900) == 0
    assert remediation.cost_per_hour(4200) == 113
    # The thresholds are the ones the Phase 3 agent and the twin use.
    spec = _load("agent_spec", ROOT / "tools" / "agent_spec.py")
    assert (remediation.EARLY_VIBRATION, remediation.ALARM_VIBRATION, remediation.EARLY_OIL_TEMP) == (spec.EARLY_VIBRATION, spec.ALARM_VIBRATION, spec.EARLY_OIL_TEMP)


def test_the_agent_is_told_only_of_columns_that_exist_and_of_parameters_the_notebook_has():
    """Phase 3, obstacle 6: the playbook is not generated when the instructions name something that is no column."""
    columns = {name for name, _, _ in remediation.COLUMNS}
    setup = (ROOT / "fabric" / "operations-agent" / "phase5b-agent-setup.txt").read_text(encoding="utf-8")
    quoted = set(re.findall(r"'([A-Za-z][A-Za-z0-9]+)'", setup))
    names = {q for q in quoted if q[0].isupper() and q not in (remediation.TABLE,)}
    assert names and names <= columns, names - columns
    assert f"'{remediation.TABLE}'" in setup and "crosses above 4 mm/s" in setup and "is above" not in setup.lower()
    kql = (ROOT / "fabric" / "kql" / "06-remediation-readiness.kql").read_text(encoding="utf-8")
    for name in columns:
        assert f"{name}:" in kql and name in kql.split("| project ")[1].split("\n")[0], name
    # The parameters of the action are variables of the notebook's parameter cell, and the instructions use them.
    parameter_cell = next(source(c) for c in cells() if "parameters" in c["metadata"].get("tags", []))
    assigned = set(re.findall(r"^([a-zA-Z_]+) = ", parameter_cell, flags=re.M))
    # The same names, no more and no fewer: Fabric makes every name of that cell a parameter of the action.
    assert assigned == {name for name, _ in remediation.PARAMETERS}
    for name in ("turbine", "percent", "duration"):
        assert f"as '{name}'" in setup, name
    action = (ROOT / "fabric" / "operations-agent" / "phase5b-action.txt").read_text(encoding="utf-8")
    assert remediation.ACTION_NAME in action and f"'{remediation.ACTION_NAME}'" in setup and remediation.NOTEBOOK in action
    # What the agent is told to pass is a command the notebook accepts and the simulator applies.
    cmd = edge.from_parameters("curtail", "WT-03", percent=str(remediation.CURTAIL_PERCENT), duration=remediation.CURTAIL_DURATION, now=NOW)
    assert cmd["percent"] == 30.0 and cmd["duration"] == "60m"

