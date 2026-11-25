"""The command center notebook (13_command_center): commands sent by hand reach the simulator, and the
notebook tells from the edge's command log and from the telemetry what became of each.

The cells are executed in one namespace against stand-ins for what only Fabric has. Two of the stand-ins
are joined to a simulator: the pretend event hub hands every event to the simulator's handler of the
control topic, and the pretend KQL database answers from the simulator's turbines. So a command the
notebook sends changes what the notebook reads next, as on the tenant. That the eventstream, the data
flow and the Eventhouse behave like these stand-ins is shown only by a run in Fabric.
"""
from __future__ import annotations

import csv
import importlib.util
import io
import json
import subprocess
import sys
import time
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOTEBOOK = ROOT / "fabric" / "notebooks" / "13_command_center.ipynb"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


center = _load("command_center", ROOT / "tools" / "command_center.py")
edge = _load("edge_command_center", ROOT / "tools" / "edge_command.py")
reference = _load("command_log_reference", Path(__file__).with_name("command_log_reference.py"))


def cells(kind="code"):
    return [c for c in json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"] if c["cell_type"] == kind]


def source(cell) -> str:
    return "".join(cell["source"])


# ------------------------------------------------------------------------------------- the notebook file
def test_the_notebook_is_current_and_is_not_one_a_job_can_fill_in():
    assert subprocess.run([sys.executable, str(ROOT / "tools" / "build-phase5.py"), "--check"], capture_output=True).returncode == 0
    code = cells()
    for cell in code:
        compile(source(cell), "cell", "exec")
        assert not [line for line in source(cell).split("\n") if line.startswith(("%", "!"))]
        # No parameter cell: this notebook is for a person. Notebook 12 is the one with values a job sets.
        assert "parameters" not in cell["metadata"].get("tags", [])
    whole = "\n".join(source(c) for c in cells("code") + cells("markdown"))
    assert "SharedAccessKey" not in whole.replace('"SharedAccessKey="', "")
    # It carries the tested code of both modules, word for word.
    for name in ("edge_command.py", "command_center.py"):
        module = (ROOT / "tools" / name).read_text(encoding="utf-8")
        body = module.split('"""', 2)[2].replace("from __future__ import annotations\n\n", "").strip("\n")
        assert body in source(code[0]), name
    # Every command of the control topic has a cell, and the examples are commands the notebook's own check accepts.
    examples = [source(c) for c in code if source(c).startswith("send(")]
    assert {text.split('"')[1] for text in examples} == set(edge.COMMANDS)


def test_the_figures_and_names_are_those_of_the_site_and_the_tables(tmp_path):
    with open(ROOT / "data" / "reference" / "turbines.csv", newline="", encoding="utf-8") as handle:
        turbines = list(csv.DictReader(handle))
    assert [row["turbineId"] for row in turbines] == center.TURBINES
    assert {float(row["ratedPowerKw"]) for row in turbines} == {center.RATED_KW}
    tables = (ROOT / "fabric" / "kql" / "01-tables.kql").read_text(encoding="utf-8")
    telemetry = next(line for line in tables.split("\n") if line.startswith(".create-merge table TurbineTelemetry"))
    for column in ("Timestamp", "TurbineId", "State", "PowerSetpoint", "ActivePower", "WindSpeed", "GearboxVibration", "GearboxOilTemp"):
        assert f"{column}:" in telemetry, column
        assert column in center.status_query() or column in center.effect_query("WT-01")
    # The queries through the Kusto language library, where it is installed (tools/kql-syntax-check.js says how):
    # their grammar, and with the tables and functions of the database, their columns and types.
    queries = "\n\n".join([center.status_query("WT-07"), center.effect_query("all", since="2026-11-25T03:10:00Z"),
                           center.log_query("a1b2c3d4e5f6"), center.history_query("6h", "WT-03")]) + "\n"
    scratch = tmp_path / "99-command-center.kql"
    scratch.write_text(queries, encoding="utf-8")
    database = sorted(str(f) for f in (ROOT / "fabric" / "kql").glob("0*.kql"))
    for tool, args, good in (("kql-syntax-check.js", [str(scratch)], "no syntax diagnostics"),
                             ("kql-semantic-check.js", database + [str(scratch)], "no diagnostics")):
        try:
            check = subprocess.run(["node", str(ROOT / "tools" / tool)] + args, capture_output=True, text=True)
        except FileNotFoundError:
            break
        if "Cannot find module" in check.stderr:
            break
        assert check.returncode == 0 and good in check.stdout, check.stdout + check.stderr
    # The log is asked for in a way that also runs on a database without it, and only by a request's identifier.
    log = center.log_query("a1b2-c3'; drop table x")
    assert log.startswith("union isfuzzy=true") and "RequestId == 'a1b2-c3droptablex'" in log and log.count("EdgeCommands") == 2
    assert center.history_query().startswith("CommandLog(1h)\n")
    assert center.history_query("90M", "wt-03").startswith("CommandLog(90m)\n| where TurbineId in ('WT-03', 'EDGE-01')")
    for lookback, turbine in (("1h", "WT-13"), ("1h; .drop table x", "all"), ("", "all"), ("0h", "all"), ("1 hour", "all"), ("ago(1h)", "all")):
        with pytest.raises(ValueError):
            center.history_query(lookback, turbine)
    # Only a turbine, or the word all, ever reaches a query.
    for wrong in ("WT-13", "WT-07' or 1==1 //", "", None, "wt-7"):
        with pytest.raises(ValueError):
            center.effect_query(wrong)
    assert center.targets_of("wt-07") == ["WT-07"] and len(center.targets_of("ALL")) == 12


# ------------------------------------------------------------------------- reading the telemetry's answer
def test_the_answer_of_the_kql_database_is_read_or_refused():
    body = {"Tables": [{"TableName": "Table_0", "Columns": [{"ColumnName": "TurbineId"}, {"ColumnName": "State"}],
                        "Rows": [["WT-01", "RUNNING"], ["WT-02", "IDLE"]]}, {"TableName": "Table_1", "Columns": [], "Rows": []}]}
    assert center.rows_of(body) == [{"TurbineId": "WT-01", "State": "RUNNING"}, {"TurbineId": "WT-02", "State": "IDLE"}]
    for wrong in (None, {}, {"Tables": []}, {"Tables": [{"Columns": []}]}, {"error": {"message": "x"}}):
        with pytest.raises(RuntimeError, match="does not know"):
            center.rows_of(wrong)
    body["Tables"][0]["Rows"].append({"OneApiErrors": [{"error": {"message": "Query execution lacks memory"}}]})
    with pytest.raises(RuntimeError, match="failure inside the result"):
        center.rows_of(body)


@pytest.mark.parametrize("cmd, row, want", [
    ({"command": "curtail", "percent": 30.0}, {"State": "CURTAILED", "PowerSetpoint": 1260.0}, True),
    ({"command": "curtail", "percent": 30.0}, {"State": "IDLE", "PowerSetpoint": 1260}, True),          # no wind: the limit still shows
    ({"command": "curtail", "percent": 30.0}, {"State": "RUNNING", "PowerSetpoint": 4200.0}, False),
    ({"command": "curtail", "percent": 30.0}, {"State": "CURTAILED", "PowerSetpoint": 2100.0}, False),   # an older, weaker limit
    ({"command": "curtail", "percent": 30.0}, {"State": "RUNNING", "PowerSetpoint": None}, False),
    ({"command": "curtail", "percent": 30.0}, {"State": "RUNNING", "PowerSetpoint": "NaN"}, False),
    ({"command": "release"}, {"State": "RUNNING", "PowerSetpoint": 4200.0}, True),
    ({"command": "release"}, {"State": "CURTAILED", "PowerSetpoint": 1260.0}, False),
    ({"command": "stop"}, {"State": "MAINTENANCE"}, True), ({"command": "stop"}, {"State": "STOPPED"}, True),
    ({"command": "stop"}, {"State": "RUNNING"}, False),
    ({"command": "start"}, {"State": "IDLE"}, True), ({"command": "start"}, {"State": "STOPPED"}, False),
    ({"command": "reset"}, {"State": "FAULT"}, False), ({"command": "reset"}, {"State": "RUNNING"}, True),
    ({"command": "stop"}, None, False), ({"command": "release"}, {}, False),
])
def test_what_counts_as_a_command_in_force(cmd, row, want):
    assert center.holds(cmd, row) is want


def _clock():
    state = {"t": 0.0}
    return state, (lambda: state["t"]), (lambda seconds: state.__setitem__("t", state["t"] + seconds))


def test_following_a_command_says_when_it_showed_and_when_it_cannot_tell():
    cmd = {"command": "curtail", "turbine": "WT-07", "percent": 30.0}
    running = {"TurbineId": "WT-07", "State": "RUNNING", "PowerSetpoint": 4200.0, "ActivePower": 3000.0, "Timestamp": "2026-11-25T03:10:00.000Z"}
    limited = dict(running, State="CURTAILED", PowerSetpoint=1260.0, Timestamp="2026-11-25T03:10:40.000Z")
    # 1. It shows on the fourth look, 15 seconds after the send.
    state, clock, sleep = _clock()
    looks, said = [], []
    def read():
        looks.append(state["t"])
        return {"WT-07": limited} if state["t"] >= 15 else {"WT-07": running}
    assert center.follow(cmd, {"WT-07": running}, read, clock=clock, sleep=sleep, say=said.append) is True
    assert looks == [0, 5, 10, 15]
    assert said[-1] == "WT-07: limit of 1260 kW in force, seen 15 s after the send (state CURTAILED, setpoint 1260 kW, power 3000 kW, reading of 03:10:40Z)."
    # 2. It never shows: the time runs out, and the person is told where to look.
    state, clock, sleep = _clock()
    said.clear()
    assert center.follow(cmd, {"WT-07": running}, lambda: {}, clock=clock, sleep=sleep, say=said.append, limit=20) is False
    assert state["t"] == 20 and "WT-07: not seen after 20 s (state RUNNING, setpoint 4200 kW" in said[-2] and "If something fails" in said[-1]
    # 3. The turbine was already limited that far: a reading that looks right proves nothing, and nothing is waited for.
    said.clear()
    assert center.follow(cmd, {"WT-07": limited}, lambda: pytest.fail("must not read"), say=said.append) is None
    assert "already so before the command" in said[0] and "cannot show whether this command arrived" in said[0] and len(said) == 1
    # 4. All twelve: eleven are waited for, the one that was curtailed before is named and left out.
    state, clock, sleep = _clock()
    said.clear()
    everyone = {name: dict(running, TurbineId=name) for name in center.TURBINES}
    before = dict(everyone, **{"WT-02": dict(limited, TurbineId="WT-02")})
    after = {name: dict(limited, TurbineId=name) for name in center.TURBINES}
    assert center.follow(dict(cmd, turbine="all"), before, lambda: after, clock=clock, sleep=sleep, say=said.append) is True
    assert said[0].startswith("WT-02: already so") and sum(1 for line in said if "seen 0 s after the send" in line) == 11
    # 5. No reading at all before the send (the VM was asleep): everything is waited for.
    state, clock, sleep = _clock()
    assert center.follow(cmd, {}, lambda: {}, clock=clock, sleep=sleep, say=lambda line: None, limit=10) is False


def test_following_a_command_with_the_edges_log():
    cmd = {"command": "curtail", "turbine": "WT-07", "percent": 30.0}
    running = {"TurbineId": "WT-07", "State": "RUNNING", "PowerSetpoint": 4200.0, "ActivePower": 3000.0, "Timestamp": "2026-11-25T03:10:00.000Z"}
    limited = dict(running, State="CURTAILED", PowerSetpoint=1260.0, Timestamp="2026-11-25T03:10:40.000Z")
    entry = {"Kind": "command", "TurbineId": "WT-07", "Ok": True, "Error": "", "Timestamp": "2026-11-25T03:10:08.412Z", "FabricToEdgeSeconds": 4}
    # 1. The log has it after 10 s, the telemetry after 20: both are said, in that order, and then it is done.
    state, clock, sleep = _clock()
    said = []
    assert center.follow(cmd, {"WT-07": running}, lambda: {"WT-07": limited if state["t"] >= 20 else running}, clock=clock, sleep=sleep,
                         say=said.append, log=lambda: (True, [entry] if state["t"] >= 10 else [])) is True
    assert said == ["Waiting for the telemetry to show it: limit of 1260 kW in force on WT-07 (up to 150 s) ...",
                    "WT-07: the edge took the command 4 s after it was written (at 03:10:08Z), in the log 10 s after the send.",
                    "WT-07: limit of 1260 kW in force, seen 20 s after the send (state CURTAILED, setpoint 1260 kW, power 3000 kW, reading of 03:10:40Z)."]
    assert state["t"] == 20
    # 2. The telemetry is first (the log's row waits in a batch): the wait goes on until the log has it too.
    state, clock, sleep = _clock()
    said.clear()
    assert center.follow(cmd, {"WT-07": running}, lambda: {"WT-07": limited}, clock=clock, sleep=sleep, say=said.append,
                         log=lambda: (True, [entry] if state["t"] >= 15 else [])) is True
    assert state["t"] == 15 and "seen 0 s after the send" in said[1] and "in the log 15 s after the send" in said[2]
    # 3. Refused: the edge's reason, at once, and False.
    state, clock, sleep = _clock()
    said.clear()
    refused = dict(entry, TurbineId="EDGE-01", Ok=False, Error="unknown turbine 'WT-99'; valid: WT-01, WT-02")
    assert center.follow(cmd, {"WT-07": running}, lambda: {"WT-07": running}, clock=clock, sleep=sleep, say=said.append, log=lambda: (True, [refused])) is False
    assert said == ["The edge refused the command: unknown turbine 'WT-99'; valid: WT-01, WT-02"] and state["t"] == 0
    for spelled in (0, "false", "False"):                      # however the database writes a bool
        said.clear()
        assert center.follow(cmd, {}, lambda: {}, clock=clock, sleep=sleep, say=said.append, log=lambda: (True, [dict(refused, Ok=spelled)])) is False
        assert said[0].startswith("The edge refused the command") and state["t"] == 0, spelled
    # 4. The edge took it, the telemetry never shows it: that is said as such.
    state, clock, sleep = _clock()
    said.clear()
    assert center.follow(cmd, {"WT-07": running}, lambda: {"WT-07": running}, clock=clock, sleep=sleep, say=said.append, limit=20, log=lambda: (True, [entry])) is False
    assert "WT-07: the edge took it, but the telemetry does not show it after 20 s" in said[-2] and "no entry" not in " ".join(said)
    # 5. The telemetry shows it, the log never has it: the log's own path is the suspect.
    state, clock, sleep = _clock()
    said.clear()
    assert center.follow(cmd, {"WT-07": running}, lambda: {"WT-07": limited}, clock=clock, sleep=sleep, say=said.append, limit=20, log=lambda: (True, [])) is False
    text = " ".join(said)
    assert "WT-07: the telemetry shows it, but the edge's log has no entry for this command after 20 s." in text
    assert "is the simulator 1.2.0, and does the data flow forward the topic .../command" in text
    # 6. Already so before, and the log has the entry: settled by the log, without a wait for telemetry.
    state, clock, sleep = _clock()
    said.clear()
    assert center.follow(cmd, {"WT-07": limited}, lambda: pytest.fail("must not read"), clock=clock, sleep=sleep, say=said.append, log=lambda: (True, [entry])) is True
    assert said == ["WT-07: the edge took the command 4 s after it was written (at 03:10:08Z), in the log 0 s after the send. "
                    "It was already so before, so the telemetry shows no change."]
    # 7. All twelve: twelve entries, each said once however often the log is read.
    state, clock, sleep = _clock()
    said.clear()
    everyone = {name: dict(running, TurbineId=name) for name in center.TURBINES}
    after = {name: dict(limited, TurbineId=name) for name in center.TURBINES}
    entries = [dict(entry, TurbineId=name) for name in center.TURBINES]
    assert center.follow(dict(cmd, turbine="all"), everyone, lambda: after if state["t"] >= 10 else everyone, clock=clock, sleep=sleep, say=said.append,
                         log=lambda: (True, entries)) is True
    assert sum(1 for line in said if "the edge took the command" in line) == 12 and sum(1 for line in said if ", seen 10 s after" in line) == 12
    # 8. The clocks of sender and edge differ: no number is made of that.
    said.clear()
    center.follow(cmd, {"WT-07": limited}, lambda: {}, say=said.append, log=lambda: (True, [dict(entry, FabricToEdgeSeconds=-2)]))
    assert said[0].startswith("WT-07: the edge took the command (at 03:10:08Z), in the log")


def test_the_command_log_reads_as_a_table():
    rows = [{"Timestamp": "2026-11-25T04:12:07.000Z", "TurbineId": "WT-03", "Command": "curtail", "Status": "in force", "LimitKw": 1260.0,
             "EndsAt": "2026-11-25T05:12:07.000Z", "RequestedBy": "operations agent WindFarmGearboxWatch, approved in Teams", "Source": "cloud",
             "FabricToEdgeSeconds": 3, "EdgeToTelemetrySeconds": 4, "Error": ""},
            {"Timestamp": "2026-11-25T04:02:00.000Z", "TurbineId": "EDGE-01", "Command": "curtail", "Status": "refused", "LimitKw": None, "EndsAt": None,
             "RequestedBy": "MOD Administrator", "Source": "cloud", "FabricToEdgeSeconds": 2, "EdgeToTelemetrySeconds": None, "Error": "unknown turbine 'WT-99'"},
            {"Timestamp": "2026-11-25T03:50:00.000Z", "TurbineId": "WT-08", "Command": "stop", "Status": "confirmed", "LimitKw": None, "EndsAt": None,
             "RequestedBy": "", "Source": "edge", "FabricToEdgeSeconds": None, "EdgeToTelemetrySeconds": 5, "Error": ""}]
    text = center.history_table(rows).split("\n")
    assert text[2].split()[:8] == ["04:12:07", "WT-03", "curtail", "in", "force", "1260", "05:12:07", "3"]
    assert text[2].endswith("  operations agent WindFarmGearboxWatch, approved in Teams")
    assert "refused: unknown turbine 'WT-99'" in text[3] and text[3].endswith("MOD Administrator")
    assert text[4].endswith("  at the edge") and text[4].split()[:4] == ["03:50:00", "WT-08", "stop", "confirmed"]
    assert len({line.index("  ", 100) for line in text[2:]}) == 1          # the columns line up to the last
    assert center.history_table([]) == "No command in that time."


def test_the_state_of_the_turbines_reads_as_a_table():
    rows = [{"TurbineId": "WT-03", "State": "RUNNING", "PowerSetpoint": 4200.0, "ActivePower": 3629.7, "WindSpeed": 12.96, "GearboxVibration": 5.049,
             "GearboxOilTemp": 81.84, "AgeSeconds": 12, "Timestamp": "2026-11-25T03:10:40Z"},
            {"TurbineId": "WT-07", "State": "CURTAILED", "PowerSetpoint": 1260.0, "ActivePower": 1259.6, "WindSpeed": 12.4, "GearboxVibration": None,
             "GearboxOilTemp": "NaN", "AgeSeconds": 7, "Timestamp": "2026-11-25T03:10:45Z"},
            {"TurbineId": "WT-11", "State": "STOPPED_HIGH_WIND", "PowerSetpoint": 4200, "ActivePower": 0, "WindSpeed": 26.0, "GearboxVibration": 0.05,
             "GearboxOilTemp": 31.0, "AgeSeconds": 3}]
    text = center.status_table(rows).split("\n")
    assert text[0].split() == ["Turbine", "State", "Limit", "kW", "Power", "kW", "Wind", "m/s", "Vib", "mm/s", "Oil", "degC", "Age", "s"]
    assert text[2].split() == ["WT-03", "RUNNING", "-", "3630", "13.0", "5.05", "81.8", "12"]
    assert text[3].split() == ["WT-07", "CURTAILED", "1260", "1260", "12.4", "-", "-", "7"]
    assert text[4].split()[:3] == ["WT-11", "STOPPED_HIGH_WIND", "-"]
    assert len({len(line) for line in text[:5]}) == 1                          # the columns line up
    assert "bash infra/vm.sh status" in center.status_table([])


def _seconds(stamp: str) -> float:
    form = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in stamp else "%Y-%m-%dT%H:%M:%SZ"
    return datetime.strptime(stamp, form).replace(tzinfo=timezone.utc).timestamp()


# --------------------------------------------------------------------- the cells, joined to a simulator
class Tenant:
    """Stand-ins for Fabric, with a simulator behind the event hub and behind the KQL database."""

    def __init__(self, sim, monkeypatch):
        self.sim, self.sent, self.queries, self.kql_error = sim, [], [], None
        self.arrives = True                 # False: the command is lost between the eventstream and the edge
        self.changed = None                 # a function: what the command looks like when it reaches the edge
        self.has_log = True                 # False: a KQL database from before Phase 5c, without the table EdgeCommands
        self.commands, self.readings = [], []
        tenant = self
        step = sim.step

        def stepped(dt=1.0):                # what the simulator sends is what the KQL database gets
            out = step(dt)
            for message in out:
                kind, payload = message.payload["messageType"], message.payload
                if kind == "command":
                    tenant.commands.append(payload)
                elif kind == "telemetry":
                    tenant.readings.append({"TurbineId": payload["assetId"], "ReadingAt": _seconds(payload["timestamp"]),
                                            "State": payload["data"]["state"], "PowerSetpoint": payload["data"]["powerSetpoint"]})
            return out

        sim.step = stepped

        class Response:
            def __init__(self, body, status=200):
                self.status_code, self._body, self.text = status, body, json.dumps(body)

            def json(self):
                return self._body

        class Client:
            def get(self, path):
                if path.endswith("/eventstreams"):
                    return Response({"value": [{"id": "es-id", "displayName": "WindFarmCommands"}]})
                if path.endswith("/topology"):
                    return Response({"sources": [{"id": "src-id", "type": "CustomEndpoint"}], "destinations": []})
                if path.endswith("/sources/src-id/connection"):
                    return Response({"fullyQualifiedNamespace": "ns.servicebus.windows.net", "eventHubName": "es_1", "accessKeys": {
                        "primaryConnectionString": "Endpoint=sb://ns.servicebus.windows.net/;SharedAccessKeyName=k;SharedAccessKey=S3cr3t=;EntityPath=es_1"}})
                if path.endswith("/kqlDatabases"):
                    return Response({"value": [{"id": "db-id", "displayName": "WindFarmEH", "properties": {"queryServiceUri": "https://eh.z9.kusto.fabric.microsoft.com"}}]})
                return Response({"message": "not found"}, 404)

        class Batch(list):
            add = list.append

        class Producer:
            @classmethod
            def from_connection_string(cls, text, **kwargs):
                assert "EntityPath=es_1" in text and kwargs["transport_type"] == "websocket"
                return cls()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def create_batch(self):
                return Batch()

            def send_batch(self, batch):
                for event in batch:
                    tenant.sent.append(json.loads(event.body))
                    if tenant.arrives:
                        arrived = json.loads(event.body)
                        answer = tenant.sim.handle_command(tenant.changed(arrived) if tenant.changed else arrived, channel="control")
                        assert answer["ok"] or tenant.changed, answer

        fabric = types.ModuleType("sempy.fabric")
        fabric.FabricRestClient, fabric.get_workspace_id = Client, lambda: "ws-id"
        sempy = types.ModuleType("sempy")
        sempy.fabric = fabric
        eventhub = types.ModuleType("azure.eventhub")
        eventhub.EventData = lambda body: types.SimpleNamespace(body=body, content_type=None)
        eventhub.EventHubProducerClient, eventhub.TransportType = Producer, types.SimpleNamespace(AmqpOverWebsocket="websocket")
        azure = types.ModuleType("azure")
        azure.eventhub = eventhub
        for name, module in (("sempy", sempy), ("sempy.fabric", fabric), ("azure", azure), ("azure.eventhub", eventhub),
                             ("websocket", types.ModuleType("websocket"))):
            monkeypatch.setitem(sys.modules, name, module)
        self.utils = types.SimpleNamespace(
            runtime=types.SimpleNamespace(context={"userName": "MOD Administrator"}),
            credentials=types.SimpleNamespace(getToken=lambda audience: f"token-for:{audience}"))

        import urllib.error
        import urllib.request

        def urlopen(request, timeout=None):
            assert request.full_url == "https://eh.z9.kusto.fabric.microsoft.com/v1/rest/query" and request.get_method() == "POST"
            assert request.get_header("Authorization") == "Bearer token-for:https://eh.z9.kusto.fabric.microsoft.com"
            body = json.loads(request.data)
            assert body["db"] == "WindFarmEH"
            tenant.queries.append(body["csl"])
            if tenant.kql_error:
                raise urllib.error.HTTPError(request.full_url, tenant.kql_error, "Forbidden", {}, io.BytesIO(b'{"error": {"message": "Principal is not authorized"}}'))
            return io.BytesIO(json.dumps(tenant.answer(body["csl"])).encode())

        monkeypatch.setattr(urllib.request, "urlopen", urlopen)
        # Time: the notebook's waiting moves the simulator, so nothing in the test sleeps.
        monkeypatch.setattr(time, "sleep", lambda seconds: [sim.step(1.0) for _ in range(int(seconds))])
        monkeypatch.setattr(time, "monotonic", lambda: sim.t)

    def log_rows(self):
        """The rows of EdgeCommands, and the same with what became of each command (CommandLog)."""
        rows = [{"Timestamp": _seconds(p["timestamp"]), "TurbineId": p["assetId"], "RequestId": d["requestId"], "Command": d["command"],
                 "Ok": d["ok"], "Error": d["error"], "LimitKw": d["limitKw"], "EndsAt": _seconds(d["endsAt"]) if d["endsAt"] else None,
                 "IssuedAt": _seconds(d["issuedAt"]) if d["issuedAt"] else None, "RequestedBy": d["requestedBy"], "Source": d["source"]}
                for p in self.commands for d in [p["data"]]]
        return reference.command_log(rows, self.readings, self.sim.epoch)

    def answer(self, query):
        """What the KQL database would hold: the newest reading of each turbine the query names, or the command log."""
        def table(names, rows):
            return {"Tables": [{"TableName": "Table_0", "Columns": [{"ColumnName": n} for n in names], "Rows": rows}]}

        def stamp_of(value):
            return None if value is None else datetime.fromtimestamp(value, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        if query.startswith("union isfuzzy=true"):
            wanted = query.split("RequestId == '")[1].split("'")[0]
            names = ["Kind", "TurbineId", "Ok", "Error", "Timestamp", "FabricToEdgeSeconds", "RequestedBy"]
            if not self.has_log:                  # the fuzzy union leaves out what reads the missing table
                return table(names, [])
            rows = [["log", "", None, "", None, None, ""]]
            rows += [["command", r["TurbineId"], r["Ok"], r["Error"] or "", stamp_of(r["Timestamp"]),
                      None if r["IssuedAt"] is None else round(r["Timestamp"] - r["IssuedAt"]), r["RequestedBy"]]
                     for r in self.log_rows() if r["RequestId"] == wanted]
            return table(names, rows)
        if query.startswith("CommandLog("):
            assert self.has_log, "the notebook asked for the command log of a database that has none"
            names = ["Timestamp", "TurbineId", "Command", "Status", "LimitKw", "EndsAt", "RequestedBy", "Source",
                     "FabricToEdgeSeconds", "EdgeToTelemetrySeconds", "Error"]
            rows = [[stamp_of(r["Timestamp"]), r["TurbineId"], r["Command"], r["Status"], r["LimitKw"], stamp_of(r["EndsAt"]), r["RequestedBy"],
                     r["Source"], None if r["IssuedAt"] is None else round(r["Timestamp"] - r["IssuedAt"]), r["EdgeToTelemetrySeconds"], r["Error"] or ""]
                    for r in sorted(self.log_rows(), key=lambda r: (-r["Timestamp"], r["TurbineId"])) if f"'{r['TurbineId']}'" in query]
            return table(names, rows)
        stamp = datetime.fromtimestamp(self.sim.epoch, tz=timezone.utc)
        since = None
        if "datetime(" in query:
            since = datetime.strptime(query.split("datetime(")[1].split(")")[0], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        wide = "GearboxVibration" in query
        names = ["TurbineId", "Timestamp", "State", "PowerSetpoint", "ActivePower"] + (["WindSpeed", "GearboxVibration", "GearboxOilTemp"] if wide else []) + ["AgeSeconds"]
        rows = []
        for name, turbine in sorted(self.sim.turbines.items()):
            if f"'{name}'" not in query or (since and stamp < since):
                continue
            signals = turbine._signals
            row = [name, stamp.strftime("%Y-%m-%dT%H:%M:%S.000Z"), turbine.state, signals["powerSetpoint"], signals["activePower"]]
            rows.append(row + ([signals["windSpeed"], signals["gearboxVibration"], signals["gearboxOilTemp"]] if wide else []) + [0])
        return {"Tables": [{"TableName": "Table_0", "Columns": [{"ColumnName": n} for n in names], "Rows": rows}]}

    def start(self):
        """Run the notebook's first two code cells: the modules and the connection."""
        namespace = {"notebookutils": self.utils, "display": lambda widget: namespace.__setitem__("shown", widget)}
        for cell in cells()[:2]:
            exec(source(cell), namespace)
        return namespace


@pytest.fixture
def tenant(make_sim, monkeypatch):
    # After the 300 steps below, the simulator's clock is a few seconds ahead of this computer's. It was set to show the
    # present exactly, and on a busy machine the 300 steps themselves took more than a second: the edge then seemed to
    # take a command before it was written, the notebook rightly printed no number, and a test that expects one failed.
    sim = make_sim(wind=12.0, start_epoch=time.time() - 300 + 5)
    for _ in range(300):
        sim.step(1.0)
    return Tenant(sim, monkeypatch)


def test_connecting_shows_where_commands_go_and_how_the_turbines_stand(tenant, capsys):
    tenant.start()
    out = capsys.readouterr().out
    assert "Commands go to the eventstream WindFarmCommands (ns.servicebus.windows.net)." in out
    assert "Commands are sent as MOD Administrator." in out and "12 turbines, read at" in out
    assert "S3cr3t" not in out and "token-for" not in out and tenant.sent == []


def test_every_cell_of_the_notebook_does_what_its_heading_says(tenant, capsys):
    """Run all, top to bottom, as a person does the first time."""
    sim = tenant.sim
    namespace = {"notebookutils": tenant.utils, "display": lambda widget: None}
    seen = {}
    for cell in cells():
        text = source(cell)
        exec(text, namespace)
        if text.startswith("send("):
            seen[text] = (capsys.readouterr().out, {name: sim.turbines[name].state for name in ("WT-03", "WT-05", "WT-07")}, sim.turbines["WT-07"].setpoint_kw)
    out, states, setpoint = seen['send("curtail", "WT-07", percent=30, duration="10m")']
    assert states["WT-07"] == "CURTAILED" and setpoint == 1260.0 and "WT-07: limit of 1260 kW in force, seen" in out and "Sent: curtail for WT-07" in out
    out, states, setpoint = seen['send("release", "WT-07")']
    assert states["WT-07"] == "RUNNING" and setpoint is None and "WT-07: limit lifted, seen" in out
    out, states, _ = seen['send("stop", "WT-05", duration="5m", reason="maintenance")']
    assert states["WT-05"] == "MAINTENANCE" and "WT-05: stopped, seen" in out
    out, states, _ = seen['send("start", "WT-05")']
    assert states["WT-05"] != "MAINTENANCE" and "WT-05: running again or free to run, seen" in out
    # A reset of a turbine that has not tripped changes nothing the telemetry could show. The edge's log settles it.
    out, states, _ = seen['send("reset", "WT-03")']
    assert "WT-03: the edge took the command" in out and "It was already so before, so the telemetry shows no change." in out
    assert "Waiting" not in out and "cannot show" not in out
    # Every command that was sent is first confirmed by the edge, then by the telemetry.
    for text, (out, _, _) in seen.items():
        if "dry_run" not in text and "reset" not in text:
            lines = out.split("\n")
            took = next(i for i, line in enumerate(lines) if "the edge took the command" in line)
            assert took < next(i for i, line in enumerate(lines) if ", seen " in line), text
            assert " s after it was written (at " in lines[took] and "in the log" in lines[took]
    out, _, _ = seen['send("curtail", "all", percent=50, duration="2m", dry_run=True)']
    assert "dry_run: nothing was sent." in out and '"turbine": "all"' in out
    assert [c["command"] for c in tenant.sent] == ["curtail", "release", "stop", "start", "reset"]
    assert all(c["requestedBy"] == "MOD Administrator" for c in tenant.sent)
    assert all(sim.turbines[name].setpoint_kw is None for name in center.TURBINES)       # the dry run for all twelve changed nothing
    # The command log, as the cell under "The command log" shows it once commands have been sent.
    namespace["history"]()
    table = capsys.readouterr().out.split("\n")
    assert table[0].split()[:6] == ["At", "(UTC)", "Turbine", "Command", "Status", "Limit"] and len({len(line) for line in table[:2]}) == 1
    rows = [line.split() for line in table[2:] if line]
    assert [(row[1], row[2]) for row in rows] == [("WT-03", "reset"), ("WT-05", "start"), ("WT-05", "stop"), ("WT-07", "release"), ("WT-07", "curtail")]
    assert [row[3] for row in rows] == ["confirmed", "confirmed", "confirmed", "confirmed", "ended"] and rows[-1][4] == "1260"
    assert all(line.endswith("MOD Administrator") for line in table[2:] if line)
    namespace["history"]("1h", "WT-05")
    assert [line.split()[2] for line in capsys.readouterr().out.split("\n")[2:] if line] == ["start", "stop"]
    namespace["history"]("yesterday")
    assert "Not shown: 'yesterday' is not a time span" in capsys.readouterr().out


def test_a_command_that_is_lost_on_the_way_is_noticed(tenant, capsys):
    namespace = tenant.start()
    capsys.readouterr()
    tenant.arrives = False
    namespace["send"]("curtail", "WT-07", percent=30, duration="10m")
    out = capsys.readouterr().out
    assert "Sent: curtail for WT-07" in out and "WT-07: not seen after 150 s (state RUNNING, setpoint 4200 kW" in out
    assert "The edge's log has no entry for this command." in out and "the edge took" not in out
    assert "docs/14-deployment-guide-phase5c.md" in out and "docs/12-deployment-guide-phase5a.md" in out
    assert tenant.sim.turbines["WT-07"].setpoint_kw is None
    # After the send only readings taken since the command was written are asked for, and only this command's log.
    readings = [q for q in tenant.queries if q.startswith("TurbineTelemetry") and "GearboxVibration" not in q]
    assert "ago(5m)" in readings[0] and all(q.count(f"Timestamp >= datetime({namespace['last_command']['issuedAt']})") == 1 for q in readings[1:])
    asked = [q for q in tenant.queries if q.startswith("union isfuzzy=true")]
    assert len(asked) == len(readings) - 1 and all(f"RequestId == '{namespace['last_command']['requestId']}'" in q for q in asked)


def test_a_command_the_edge_refuses_is_said_with_the_edges_reason(tenant, capsys):
    namespace = tenant.start()
    capsys.readouterr()
    # The notebook's own check lets only good commands out, so the test changes one on the way.
    tenant.changed = lambda cmd: {**cmd, "turbine": "WT-99"}
    namespace["send"]("curtail", "WT-07", percent=30, duration="10m")
    out = capsys.readouterr().out
    assert "The edge refused the command: unknown turbine 'WT-99'" in out
    assert "not seen after" not in out and "If something fails" not in out          # the answer is in: nothing is waited out
    assert tenant.sim.turbines["WT-07"].setpoint_kw is None and tenant.sim.t < 330
    namespace["history"]()
    line = next(line for line in capsys.readouterr().out.split("\n") if "EDGE-01" in line)
    assert "refused: unknown turbine 'WT-99'" in line


def test_on_a_database_without_the_command_log_the_notebook_follows_the_telemetry_only(tenant, capsys):
    tenant.has_log = False
    namespace = tenant.start()
    capsys.readouterr()
    namespace["send"]("curtail", "WT-07", percent=30, duration="10m")
    out = capsys.readouterr().out
    assert out.count("This database has no command log yet (Phase 5c: run block 1 of fabric/kql/07-command-log.kql).") == 1
    assert "Only the telemetry can show what became of this command." in out
    assert "WT-07: limit of 1260 kW in force, seen" in out and "the edge" not in out.split("Only the telemetry")[1]
    assert len([q for q in tenant.queries if q.startswith("union isfuzzy=true")]) == 1   # asked once, then left alone
    # What the telemetry cannot show stays unknown, and is said to be.
    namespace["send"]("reset", "WT-03")
    out = capsys.readouterr().out
    assert "WT-03: already so before the command (state RUNNING" in out and "cannot show whether this command arrived" in out
    namespace["history"]()
    assert capsys.readouterr().out.strip() == "This database has no command log yet (Phase 5c: run block 1 of fabric/kql/07-command-log.kql)."
    assert not [q for q in tenant.queries if q.startswith("CommandLog(")]


def test_what_the_notebook_refuses_is_said_and_not_sent(tenant, capsys):
    namespace = tenant.start()
    capsys.readouterr()
    send = namespace["send"]
    for args, kwargs, says in ((("curtail", "WT-07"), {"percent": 30}, "curtail needs a duration"), (("curtail", ""), {"percent": 30, "duration": "10m"}, "is not a turbine"),
                               (("inject", "WT-07"), {}, "is not a command of the control topic"), (("curtail", "WT-07"), {"percent": 130, "duration": "10m"}, "between 0 and 100"),
                               (("stop", "WT-13"), {}, "is not a turbine")):
        send(*args, **kwargs)
        assert f"Not sent: " in (out := capsys.readouterr().out) and says in out, (args, out)
    assert tenant.sent == [] and namespace["last_command"] is None
    # As people write it.
    send("Curtail", "wt-07", percent="30%", duration="10 minutes", wait=False)
    assert tenant.sent[0]["percent"] == 30.0 and tenant.sent[0]["duration"] == "10m" and "Waiting" not in capsys.readouterr().out
    # The KQL database refuses the reader: said in its words, and no command goes out blind.
    tenant.kql_error = 403
    with pytest.raises(RuntimeError, match="The KQL database answered 403: .*not authorized"):
        send("release", "WT-07")
    assert len(tenant.sent) == 1


def test_the_panel_sends_what_its_cells_send(tenant, capsys):
    pytest.importorskip("ipywidgets")
    namespace = tenant.start()
    exec(source(cells()[-1]), namespace)
    assert namespace["shown"] is namespace["panel"]
    capsys.readouterr()
    assert list(namespace["w_command"].options) == list(edge.COMMANDS) and list(namespace["w_turbine"].options) == center.TURBINES + ["all"]
    namespace["w_status"].click()
    assert "12 turbines, read at" in namespace["w_log"].value
    namespace["w_send"].click()                                    # as shown: curtail WT-07 to 30 percent for 10m
    log = namespace["w_log"].value
    assert tenant.sent[-1]["command"] == "curtail" and tenant.sent[-1]["turbine"] == "WT-07" and tenant.sim.turbines["WT-07"].setpoint_kw == 1260.0
    assert "Sent: curtail for WT-07" in log and "limit of 1260 kW in force, seen" in log and "12 turbines" not in log
    namespace["w_command"].value, namespace["w_turbine"].value = "stop", "WT-05"
    namespace["w_reason"].value, namespace["w_duration"].value, namespace["w_wait"].value = "maintenance", "5m", False
    namespace["w_send"].click()
    assert tenant.sent[-1] == {**tenant.sent[-1], "command": "stop", "turbine": "WT-05", "reason": "maintenance", "duration": "5m"}
    assert "percent" not in tenant.sent[-1] and tenant.sim.turbines["WT-05"].manual_stop
    namespace["w_command"].value = "release"                       # the values a release does not take are left out
    namespace["w_send"].click()
    assert tenant.sent[-1]["command"] == "release" and not {"duration", "percent", "note", "reason"} & set(tenant.sent[-1])
    # A failure inside a button shows in the log; a button has nowhere else to put it.
    tenant.kql_error = 403
    namespace["w_status"].click()
    assert "Failed: The KQL database answered 403" in namespace["w_log"].value
    assert capsys.readouterr().out == ""                           # everything the panel says is in its log
