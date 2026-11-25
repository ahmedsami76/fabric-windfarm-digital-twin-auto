"""Phase 5c, the command log: the edge reports every operating command it is given, and the cloud can
tell from that report and the telemetry who limited a turbine and whether the plant followed.

Three things are tested here.
1. The simulator: one message of type "command" for each turbine a command acted on, on a topic the
   data flow forwards, with the fields the KQL table reads.
2. The KQL file: its table and its update policy name exactly the fields of that message.
3. The rules of the function CommandLog, in their Python copy (command_log_reference.py), on the
   simulator's own messages: a command is called confirmed, in force and ended when it is.
That the KQL database computes what the Python copy computes is shown only by a run in Fabric.
"""
from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from windfarm_sim.engine import CONTROL_COMMANDS, EDGE_ASSET_ID, SIM_COMMANDS

ROOT = Path(__file__).resolve().parents[2]
KQL = (ROOT / "fabric" / "kql" / "07-command-log.kql").read_text(encoding="utf-8")
DATAFLOW = json.loads((ROOT / "edge" / "dataflows" / "windfarm-to-fabric.template.json").read_text(encoding="utf-8"))

_spec = importlib.util.spec_from_file_location("command_log_reference", Path(__file__).with_name("command_log_reference.py"))
reference = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reference)


def seconds(stamp: str) -> float:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc).timestamp()


def from_fabric(sim, command, turbine, request_id, **more):
    """A command as notebook 12 writes it, handed to the simulator the way the control topic does."""
    cmd = {"command": command, "turbine": turbine, "requestId": request_id,
           "requestedBy": "operations agent WindFarmGearboxWatch, approved in Teams",
           "issuedAt": datetime.fromtimestamp(sim.epoch - 3, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **more}
    return sim.handle_command(cmd, channel="control")


def logged(messages):
    return [m for m in messages if m.payload["messageType"] == "command"]


class Plant:
    """A simulator whose messages are kept the way the KQL database keeps them: commands and readings."""

    def __init__(self, sim):
        self.sim, self.commands, self.readings = sim, [], []

    def run(self, seconds_):
        for _ in range(int(seconds_)):
            for m in self.sim.step(1.0):
                p = m.payload
                if p["messageType"] == "command":
                    d = p["data"]
                    self.commands.append({
                        "Timestamp": seconds(p["timestamp"]), "TurbineId": p["assetId"], "RequestId": d["requestId"], "Command": d["command"],
                        "Ok": d["ok"], "LimitKw": d["limitKw"], "EndsAt": seconds(d["endsAt"]) if d["endsAt"] else None})
                elif p["messageType"] == "telemetry":
                    self.readings.append({"TurbineId": p["assetId"], "ReadingAt": seconds(p["timestamp"]),
                                          "State": p["data"]["state"], "PowerSetpoint": p["data"]["powerSetpoint"]})
        return self

    def log(self):
        rows = reference.command_log(self.commands, self.readings, self.sim.epoch)
        return {(row["RequestId"], row["TurbineId"]): row for row in rows}


@pytest.fixture
def plant(make_sim):
    sim = make_sim(wind=13.0)
    return Plant(sim).run(120)


# ------------------------------------------------------------------------------------------- the message
def test_a_command_from_fabric_is_logged_once_for_the_turbine_it_acted_on(make_sim):
    sim = make_sim(wind=13.0)
    for _ in range(60):
        sim.step(1.0)
    answer = from_fabric(sim, "curtail", "WT-03", "req-1", percent=30, duration="60m")
    assert answer["ok"]
    out = sim.step(1.0)
    [message] = logged(out)
    assert message.topic == f"contoso/windfarm/{sim.site.site_id}/WT-03/command" and not message.retain
    p = message.payload
    assert (p["messageType"], p["assetId"], p["siteId"]) == ("command", "WT-03", sim.site.site_id)
    assert p["data"] == {
        "requestId": "req-1", "command": "curtail", "source": "cloud",
        "requestedBy": "operations agent WindFarmGearboxWatch, approved in Teams",
        "issuedAt": p["data"]["issuedAt"], "ok": True, "error": None, "percent": 30.0, "limitKw": 1260.0,
        "durationSeconds": 3600, "endsAt": p["data"]["endsAt"], "reason": None, "turbinesInCommand": 1}
    # The edge's time of the command, and the end it worked out from the duration.
    assert seconds(p["data"]["endsAt"]) - seconds(p["timestamp"]) == pytest.approx(3600, abs=0.01)
    assert 0 < seconds(p["timestamp"]) - datetime.strptime(p["data"]["issuedAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp() < 5
    # Said once, and in the turbine's own numbering, so that no reading of a gap check is disturbed.
    later = [m for _ in range(30) for m in sim.step(1.0)]
    assert logged(later) == []
    numbers = [m.payload["seq"] for m in out + later if m.payload["assetId"] == "WT-03"]
    assert numbers == list(range(numbers[0], numbers[0] + len(numbers)))


def test_a_command_to_all_is_logged_for_each_of_the_twelve_under_one_request(make_sim):
    sim = make_sim(wind=13.0)
    sim.step(1.0)
    from_fabric(sim, "curtail", "all", "req-all", percent=50, duration="2m")
    entries = logged(sim.step(1.0))
    assert [m.payload["assetId"] for m in entries] == list(sim.turbines)
    assert {m.payload["data"]["requestId"] for m in entries} == {"req-all"}
    assert {m.payload["data"]["turbinesInCommand"] for m in entries} == {12}
    assert {m.payload["data"]["limitKw"] for m in entries} == {2100.0}


@pytest.mark.parametrize("command, more, want", [
    ("release", {}, {"durationSeconds": None, "endsAt": None, "percent": None, "limitKw": None, "reason": None}),
    ("stop", {"duration": "15m", "reason": "maintenance"}, {"durationSeconds": 900, "percent": None, "limitKw": None, "reason": "maintenance"}),
    ("stop", {}, {"durationSeconds": None, "endsAt": None, "reason": None}),
    ("start", {}, {"durationSeconds": None, "endsAt": None}),
    ("reset", {}, {"durationSeconds": None, "endsAt": None}),
])
def test_every_operating_command_is_logged_with_what_it_carried(make_sim, command, more, want):
    sim = make_sim(wind=13.0)
    sim.step(1.0)
    assert from_fabric(sim, command, "WT-05", "req-2", **more)["ok"]
    [message] = logged(sim.step(1.0))
    data = message.payload["data"]
    assert (data["command"], data["ok"], data["source"], message.payload["assetId"]) == (command, True, "cloud", "WT-05")
    for key, value in want.items():
        assert data[key] == value, key
    assert set(CONTROL_COMMANDS) == {"curtail", "release", "stop", "start", "reset"}


def test_a_refused_command_is_logged_once_with_the_reason(make_sim):
    sim = make_sim(wind=13.0)
    sim.step(1.0)
    # A turbine that does not exist: logged under the edge itself.
    assert not from_fabric(sim, "curtail", "WT-99", "req-a", percent=30, duration="10m")["ok"]
    # A turbine that exists, and a command that is incomplete: logged under that turbine.
    assert not from_fabric(sim, "curtail", "WT-04", "req-b")["ok"]
    # A command only the simulator has does not belong on the control topic: refused, and logged as refused.
    assert not from_fabric(sim, "inject", "WT-06", "req-c", kind="gearbox_degradation")["ok"]
    entries = {m.payload["data"]["requestId"]: m.payload for m in logged(sim.step(1.0))}
    assert [entries[r]["assetId"] for r in ("req-a", "req-b", "req-c")] == [EDGE_ASSET_ID, "WT-04", "WT-06"]
    for payload in entries.values():
        data = payload["data"]
        assert data["ok"] is False and data["error"] and data["turbinesInCommand"] == 0 and data["limitKw"] is None
    assert "WT-99" in entries["req-a"]["data"]["error"] and "inject" in entries["req-c"]["data"]["error"]
    # Nothing was limited.
    assert all(t.setpoint_kw is None for t in sim.turbines.values())


def test_commands_given_at_the_edge_are_logged_as_such_and_simulator_commands_are_not(make_sim):
    sim = make_sim(wind=13.0)
    sim.step(1.0)
    # simctl: the same five commands, on the simulator's own topic. No sender's time, no name.
    assert sim.handle_command({"command": "curtail", "turbine": "WT-08", "percent": 40, "duration": "5m", "requestId": "ctl-1"}, channel="sim")["ok"]
    # What only the simulator has is not an operating command: a fault, the wind, a look.
    assert sim.handle_command({"command": "inject", "turbine": "WT-07", "kind": "gearbox_degradation", "duration": "5m"}, channel="sim")["ok"]
    assert sim.handle_command({"command": "wind", "mean": 12}, channel="sim")["ok"]
    assert sim.handle_command({"command": "status"}, channel="sim")["ok"]
    assert not sim.handle_command({"command": "nonsense"}, channel="sim")["ok"]
    [message] = logged(sim.step(1.0))
    data = message.payload["data"]
    assert (message.payload["assetId"], data["command"], data["source"], data["issuedAt"], data["requestedBy"]) == ("WT-08", "curtail", "edge", None, "")
    assert SIM_COMMANDS.isdisjoint(CONTROL_COMMANDS)


def test_a_command_for_a_turbine_that_is_offline_is_logged_at_once(make_sim):
    sim = make_sim(wind=13.0)
    for _ in range(30):
        sim.step(1.0)
    assert sim.handle_command({"command": "inject", "turbine": "WT-02", "kind": "comms_loss", "duration": "3m"}, channel="sim")["ok"]
    for _ in range(10):
        sim.step(1.0)
    assert sim.turbines["WT-02"].comms_down
    from_fabric(sim, "curtail", "WT-02", "req-off", percent=30, duration="30m")
    out = sim.step(1.0)
    assert [m.payload["assetId"] for m in logged(out)] == ["WT-02"]
    # The turbine's own messages wait until it is back; the controller's log does not.
    assert not [m for m in out if m.payload["assetId"] == "WT-02" and m.payload["messageType"] == "telemetry"]


# ------------------------------------------------------------------------- the way to the KQL database
def test_the_data_flow_forwards_every_kind_of_message_the_simulator_sends(make_sim):
    sim = make_sim(wind=13.0)
    kinds = set()
    for second in range(700):
        if second == 100:
            sim.handle_command({"command": "inject", "turbine": "WT-07", "kind": "gearbox_degradation", "severity": 1.0, "duration": "8m"}, channel="sim")
            from_fabric(sim, "stop", "WT-01", "req-s", duration="1m")
        kinds |= {m.topic.rsplit("/", 1)[1] for m in sim.step(1.0)}
    [source] = [op for op in DATAFLOW["operations"] if op["operationType"] == "Source"]
    topics = source["sourceSettings"]["dataSources"]
    assert all(t.startswith("contoso/windfarm/+/+/") for t in topics) and len(set(topics)) == len(topics)
    forwarded = {t.rsplit("/", 1)[1] for t in topics}
    assert kinds == forwarded == {"telemetry", "weather", "alarm", "state", "asset", "heartbeat", "command"}
    # Neither the commands on their way in nor their acknowledgements are sent on to Fabric: no loop.
    assert not [t for t in topics if "_control" in t or "_sim" in t]
    assert not sim.control_topic.endswith("/command")


def test_the_table_and_its_update_policy_read_the_fields_of_the_message(make_sim):
    sim = make_sim(wind=13.0)
    sim.step(1.0)
    from_fabric(sim, "curtail", "WT-03", "req-1", percent=30, duration="60m")
    [message] = logged(sim.step(1.0))
    fields = set(message.payload["data"])
    policy = KQL.split("Expand_EdgeCommands() {")[1].split("\n}")[0]
    assert "messageType == 'command'" in policy
    read = set(re.findall(r"data\['(\w+)'\]", policy))
    assert read == fields
    # Every column the policy fills is a column of the table, in the table's order, with the table's type.
    table = re.search(r"^\.create-merge table EdgeCommands \((.*)\)$", KQL, re.M).group(1)
    columns = [c.split(":")[0].strip() for c in table.split(",")]
    projected = re.findall(r"^\s+(\w+) = ", policy, re.M)
    assert projected == columns
    types = dict(c.strip().split(": ") for c in table.split(","))
    casts = {"tostring": "string", "todatetime": "datetime", "tobool": "bool", "toreal": "real", "tolong": "long", "toint": "int"}
    for column, cast in re.findall(r"^\s+(\w+) = (to\w+)\(data\[", policy, re.M):
        assert casts[cast] == types[column], column
    # The descriptions name every column.
    described = re.findall(r'^\s+(\w+): "', KQL.split("column-docstrings (")[1].split("\n)")[0], re.M)
    assert described == columns
    assert '"Source": "RawEvents", "Query": "Expand_EdgeCommands()"' in KQL
    # Block 1 is one database script: an empty line would end it early in the query window.
    script = KQL.split(".execute database script <|")[1].split("\n// Block 2.")[0].rstrip("\n")
    assert "\n\n" not in script


def test_the_python_copy_of_the_rules_says_what_the_function_says():
    function = KQL.split("CommandLog(lookback: timespan = 24h) {")[1].split("\n}")[0]
    assert f"let wait = {int(reference.WAIT_S // 60)}m;" in function
    assert f"PowerSetpoint <= LimitKw + {reference.TOLERANCE_KW}" in function and f"PowerSetpoint > LimitKw + {reference.TOLERANCE_KW}" in function
    for line in ("Command == 'release', State != 'CURTAILED'", "Command == 'stop', State in ('STOPPED', 'MAINTENANCE')",
                 "Command == 'start', State !in ('STOPPED', 'MAINTENANCE')", "State != 'FAULT')"):
        assert line in function, line
    assert set(re.findall(r"'((?:refused|taken by the edge|in force|ended|confirmed)[^']*)'", function)) == set(reference.STATUSES)
    # The order of the cases is the order of the Python copy: refused, ended, not yet, never, in force, confirmed.
    order = [function.index(f"'{word}'") for word in ("refused", "ended", "taken by the edge, not yet seen in telemetry",
                                                      "taken by the edge, never seen in telemetry", "in force", "confirmed")]
    assert order == sorted(order)


def test_the_guide_names_what_the_repository_holds():
    guide = (ROOT / "docs" / "14-deployment-guide-phase5c.md").read_text(encoding="utf-8")
    # The build of the app the guide tells the reader to look for is the one in the repository.
    stamp = re.search(r"FUNCTIONS_BUILD = '([0-9a-f]{12})'", (ROOT / "app" / "overlay" / "packages" / "functions" / "src" / "build.ts").read_text()).group(1)
    assert f"The three `build` lines read `{stamp}`" in guide
    # The version, the topic and the names of the table and the function.
    version = re.search(r'__version__ = "([^"]+)"', (ROOT / "simulator" / "windfarm_sim" / "__init__.py").read_text()).group(1)
    assert f"simulator {version}" in guide and f'SIM_IMAGE="windfarm-simulator:{version}"' in guide
    for name in ("EdgeCommands", "CommandLog", "contoso/windfarm/+/+/command", "fabric/kql/07-command-log.kql"):
        assert name in guide, name
    # Block 1 has as many commands as the guide says it answers with rows.
    script = KQL.split(".execute database script <|")[1].split("\n// Block 2.")[0]
    assert len(re.findall(r"^\.", script, re.M)) == 7 and "seven rows" in guide
    # Every status the function can give is explained to the reader somewhere in the guide or the troubleshooting page.
    pages = guide + (ROOT / "docs" / "troubleshooting.md").read_text(encoding="utf-8")
    for status in reference.STATUSES:
        assert status in pages, status


# ------------------------------------------------------------------- the rules, on the simulator's messages
def test_a_curtailment_is_in_force_once_the_telemetry_shows_it_and_ended_when_its_time_is_over(plant):
    sim = plant.sim
    while True:             # go on to the second in which a round of telemetry went out
        before = len(plant.readings)
        if len(plant.run(1).readings) > before:
            break
    from_fabric(sim, "curtail", "WT-03", "req-1", percent=30, duration="10m")
    plant.run(2)            # the log is out, the next round of telemetry is not
    row = plant.log()[("req-1", "WT-03")]
    assert row["Status"] == "taken by the edge, not yet seen in telemetry" and row["ConfirmedAt"] is None
    plant.run(30)
    row = plant.log()[("req-1", "WT-03")]
    assert row["Status"] == "in force" and row["EndedAt"] is None
    assert 0 <= row["EdgeToTelemetrySeconds"] <= sim.cfg.telemetry_interval_s
    assert sim.turbines["WT-03"].state == "CURTAILED"
    plant.run(600)
    row = plant.log()[("req-1", "WT-03")]
    assert row["Status"] == "ended"
    assert row["EndedAt"] == pytest.approx(row["EndsAt"], abs=sim.cfg.telemetry_interval_s + 1)
    assert sim.turbines["WT-03"].setpoint_kw is None


def test_a_message_that_arrives_twice_is_one_command(plant):
    sim = plant.sim
    from_fabric(sim, "curtail", "WT-03", "req-1", percent=30, duration="10m")
    plant.run(30)
    plant.commands.append(dict(plant.commands[0]))            # the broker and the eventstream deliver at least once
    rows = reference.command_log(plant.commands, plant.readings, sim.epoch)
    assert len(rows) == 1 and rows[0]["Status"] == "in force"
    function = KQL.split("CommandLog(lookback: timespan = 24h) {")[1].split("\n}")[0]
    assert "summarize arg_max(IngestedAt, *) by TurbineId, RequestId, Command, Timestamp;" in function


def test_a_release_ends_the_limit_and_is_itself_confirmed(plant):
    sim = plant.sim
    from_fabric(sim, "curtail", "WT-03", "req-1", percent=30, duration="60m")
    plant.run(60)
    from_fabric(sim, "release", "WT-03", "req-2")
    plant.run(30)
    log = plant.log()
    limit, release = log[("req-1", "WT-03")], log[("req-2", "WT-03")]
    assert limit["Status"] == "ended" and limit["EndedAt"] == pytest.approx(release["Timestamp"], abs=sim.cfg.telemetry_interval_s + 1)
    assert release["Status"] == "confirmed" and release["EndedAt"] is None


def test_a_second_limit_replaces_the_first_whichever_is_tighter(plant):
    sim = plant.sim
    from_fabric(sim, "curtail", "WT-03", "req-1", percent=50, duration="60m")
    plant.run(40)
    from_fabric(sim, "curtail", "WT-03", "req-2", percent=30, duration="60m")     # tighter: the telemetry alone would not end the first
    plant.run(40)
    from_fabric(sim, "curtail", "WT-03", "req-3", percent=60, duration="60m")     # looser
    plant.run(40)
    log = plant.log()
    assert [log[(r, "WT-03")]["Status"] for r in ("req-1", "req-2", "req-3")] == ["ended", "ended", "in force"]
    assert log[("req-1", "WT-03")]["EndedAt"] == log[("req-2", "WT-03")]["Timestamp"]
    assert log[("req-2", "WT-03")]["EndedAt"] <= log[("req-3", "WT-03")]["Timestamp"] + sim.cfg.telemetry_interval_s
    # Only one limit per turbine is ever in force.
    assert sum(1 for row in log.values() if row["Status"] == "in force") == 1


def test_stop_start_and_reset_are_confirmed_by_the_state(plant):
    sim = plant.sim
    from_fabric(sim, "stop", "WT-05", "req-1", reason="maintenance")
    plant.run(20)
    assert plant.log()[("req-1", "WT-05")]["Status"] == "confirmed" and sim.turbines["WT-05"].state == "MAINTENANCE"
    from_fabric(sim, "start", "WT-05", "req-2")
    plant.run(20)
    assert plant.log()[("req-2", "WT-05")]["Status"] == "confirmed"
    from_fabric(sim, "reset", "WT-05", "req-3")
    plant.run(20)
    assert plant.log()[("req-3", "WT-05")]["Status"] == "confirmed"


def test_a_refused_command_and_a_weak_wind(make_sim):
    sim = make_sim(wind=7.0)
    plant = Plant(sim).run(120)
    from_fabric(sim, "curtail", "WT-99", "req-x", percent=30, duration="10m")
    from_fabric(sim, "curtail", "WT-03", "req-1", percent=30, duration="10m")
    plant.run(30)
    log = plant.log()
    assert log[("req-x", EDGE_ASSET_ID)]["Status"] == "refused"
    # In a weak wind the turbine gives less than the limit anyway. The setpoint still shows the limit, so the
    # command is confirmed, though the power did not change.
    assert sim.turbines["WT-03"].power < 1260 and log[("req-1", "WT-03")]["Status"] == "in force"


def test_a_command_to_a_turbine_that_does_not_report_waits_and_is_then_called_never_seen(plant):
    sim = plant.sim
    sim.handle_command({"command": "inject", "turbine": "WT-02", "kind": "comms_loss", "duration": "20m"}, channel="sim")
    plant.run(10)
    from_fabric(sim, "curtail", "WT-02", "req-1", percent=30, duration="60m")
    plant.run(60)
    assert plant.log()[("req-1", "WT-02")]["Status"] == "taken by the edge, not yet seen in telemetry"
    plant.run(300)
    assert plant.log()[("req-1", "WT-02")]["Status"] == "taken by the edge, never seen in telemetry"
    # A short loss: the readings that were held back arrive, and the command is confirmed after all.
    sim.handle_command({"command": "inject", "turbine": "WT-09", "kind": "comms_loss", "duration": "1m"}, channel="sim")
    plant.run(10)
    from_fabric(sim, "curtail", "WT-09", "req-2", percent=30, duration="60m")
    plant.run(120)
    assert plant.log()[("req-2", "WT-09")]["Status"] == "in force"
