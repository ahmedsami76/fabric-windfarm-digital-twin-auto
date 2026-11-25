"""tools/deploy.py against a pretend Azure and Fabric (deploy_fakes.py).

What these tests can show: what the runner does with the answers it gets. Refusing a wrong target, resuming,
never making a thing twice, handing over what has no API, keeping secrets out of its output. What they cannot
show: that Azure and Fabric answer as the stand-ins do. docs/15-deployment-runner.md keeps the two apart.
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_fakes import CONNECTION, KEY, FakeAz, FakeFabric, FakeKusto, FakeOneLake, FakeShell, World  # noqa: E402
from deployer import cli, core, names, steps  # noqa: E402
from deployer.cloud import CloudError, run_notebook  # noqa: E402

ROLES, SETTINGS = "--approve-role-changes", "phase1.tenant_settings"


class Bench:
    """One copy of the repository's files, one pretend cloud, and the runner between them."""

    def __init__(self, folder: Path):
        self.root, self.world, self.now, self.kusto = folder, World(), [0.0], None
        self.wall = [1795600000.0]
        for part in ("fabric/kql", "fabric/notebooks", "app/overlay/packages/functions/src"):
            shutil.copytree(ROOT / part, folder / part)
        (folder / "config").mkdir()
        shutil.copy(ROOT / "config" / "demo.env.example", folder / "config" / "demo.env.example")

    def adapters(self, redact):
        self.kusto = FakeKusto(self.world)

        def sleep(seconds):
            self.now[0] += seconds
        az = FakeAz(self.world, redact)
        az.token("https://api.fabric.microsoft.com")            # as the real adapters do before their first call
        return {"az": az, "fabric": FakeFabric(self.world), "kusto": self.kusto,
                "shell": FakeShell(self.world, self.root, redact), "onelake": FakeOneLake(self.world),
                "clock": lambda: self.now[0], "sleep": sleep, "wall": lambda: self.wall[0]}

    def run(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        code = cli.main(list(argv), out=out, root=self.root, adapters=self.adapters)
        self.last = out.getvalue()
        return code, self.last

    def plan(self, *options) -> str:
        code, text = self.run("plan", *options)
        assert code == 0, text
        return re.search(r"^Plan (\w+)$", text, re.M)[1]

    def apply(self, *options, confirm=()) -> tuple[int, str]:
        digest = self.plan(*options)
        extra = [item for step in confirm for item in ("--confirm", step)]
        return self.run("apply", "--approve", digest, *options, *extra)

    @property
    def cfg(self) -> dict:
        return names.read_env(self.root / "config" / "demo.env")

    @property
    def state(self) -> dict:
        folder = self.root / ".deploy" / self.cfg["DEPLOYMENT_SUFFIX"]
        return json.loads((folder / "state.json").read_text())

    def everything_written(self) -> str:
        """All the runner left behind on disk and said: where a secret would show."""
        texts = [self.last]
        for path in list((self.root / ".deploy").rglob("*")) + [self.root / "config" / "demo.env"]:
            if path.is_file():
                texts.append(path.read_text())
        return "\n".join(texts)


@pytest.fixture
def bench(tmp_path):
    return Bench(tmp_path)


@pytest.fixture
def deployed(bench):
    """Phase 1, applied to the end."""
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == 0, text
    return bench


# ------------------------------------------------------------------------------------------ plan and names
def test_the_first_plan_chooses_names_and_changes_nothing(bench):
    code, text = bench.run("plan")
    assert code == 0 and "Nothing was changed in Azure or Fabric" in text
    cfg, suffix = bench.cfg, bench.cfg["DEPLOYMENT_SUFFIX"]
    assert re.fullmatch(r"[a-z0-9]{3}", suffix)
    assert cfg["RESOURCE_GROUP"] == f"rg-windfarm-edge-{suffix}" and cfg["STORAGE_ACCOUNT_NAME"] == f"sawindfarm{suffix}"
    assert cfg["FABRIC_WORKSPACE_NAME"] == f"WindFarmDigitalTwin-{suffix}" and cfg["VM_NAME"] == f"vm-windfarm-edge-{suffix}"
    assert cfg["SUBSCRIPTION_ID"] == "sub-1111" and cfg["SIM_IMAGE"] == "windfarm-simulator:1.2.0"
    assert bench.world.writes == [] and bench.world.shell_calls == []
    # the target is shown before anything else, and the second plan speaks of the same names
    for word in ("tenant-aaaa", "sub-1111", cfg["RESOURCE_GROUP"], cfg["FABRIC_WORKSPACE_NAME"], "cap-0001"):
        assert word in text
    assert bench.plan() == re.search(r"^Plan (\w+)$", text, re.M)[1]


def test_names_are_three_characters_from_a_small_alphabet_and_differ():
    seen = {names.new_suffix() for _ in range(200)}
    assert len(seen) > 150 and all(names.valid_suffix(suffix) for suffix in seen)
    assert len(names.generated("3x9")["STORAGE_ACCOUNT_NAME"]) <= 24
    with pytest.raises(ValueError):
        names.write_env(Path("/nonexistent"), {"VM_NAME": 'a"; rm -rf ~; "'})


def test_apply_needs_the_approval_of_the_plan_it_would_run(bench):
    digest = bench.plan(ROLES)
    code, text = bench.run("apply", ROLES)
    assert code == core.EXIT_REFUSED and f"--approve {digest}" in text
    code, text = bench.run("apply", "--approve", "0123456789ab", ROLES)
    assert code == core.EXIT_REFUSED and "You approved plan 0123456789ab" in text
    code, text = bench.run("apply", "--approve", digest)        # the same plan without the option it was made with
    assert code == core.EXIT_REFUSED
    assert bench.world.writes == []


# ------------------------------------------------------------------------------------------ the whole of Phase 1
def test_phase_1_runs_to_its_gates_and_says_what_was_measured(deployed):
    world, text = deployed.world, deployed.last
    assert "Everything up to phase1 is in place" in text
    assert "688 readings from 12 turbines in the last 5 minutes, the newest 38 s old" in text
    assert "Lakehouse: 2 tables with rows; TurbineTelemetry newest 6.5 min old" in text
    ws = world.workspaces[0]
    assert ws["capacityId"] == "cap-0001" and deployed.cfg["DEPLOYMENT_SUFFIX"] in ws["description"]
    kinds = sorted((entry["type"], entry["displayName"]) for entry in world.items[ws["id"]])
    assert ("Eventhouse", "WindFarmEH") in kinds and ("Lakehouse", "WindFarmLH") in kinds and ("Eventstream", "es-windfarm-edge") in kinds
    assert [name for kind, name in kinds if kind == "Notebook"] == sorted(steps.NOTEBOOKS["phase1"])
    # the destination of the eventstream is the one of Microsoft's article, with the mapping the guide insists on
    destination = world.definition["destinations"][0]
    assert destination["properties"] == {"dataIngestionMode": "DirectIngestion", "workspaceId": ws["id"],
                                         "itemId": world.find(ws["id"], "Eventhouse", "WindFarmEH")["id"], "tableName": "RawEvents",
                                         "connectionName": f"es-windfarm-raw-{deployed.cfg['DEPLOYMENT_SUFFIX']}",
                                         "mappingRuleName": "RawEvents_mapping"}
    assert len(destination["properties"]["connectionName"]) <= 40
    assert world.definition["sources"] == [{"name": "aio-edge", "type": "CustomEndpoint", "properties": {}}]
    # the settings got the endpoint's two names, and every notebook its Lakehouse
    assert deployed.cfg["EVENTSTREAM_BOOTSTRAP_SERVER"] == "esehabc123.servicebus.windows.net:9093" and deployed.cfg["EVENTSTREAM_TOPIC"] == "esehabc123_eh"
    lakehouse = world.find(ws["id"], "Lakehouse", "WindFarmLH")["id"]
    assert all(e["lakehouse"]["default_lakehouse"] == lakehouse for e in world.items[ws["id"]] if e["type"] == "Notebook")
    # six shortcuts to the KQL database, and none to RawEvents
    assert sorted(s["name"] for s in world.shortcuts[lakehouse]) == sorted(steps.LIVE_TABLES)
    # run: notebooks 01, 02, 03 and the gate, each once. 04 is imported and left for a person
    ran = [w.split()[-1] for w in world.writes if w.startswith("POST job")]
    assert ran == ["01_load_reference_data", "02_generate_history", "03_refresh_forecast", "90_deployment_gate"]


def test_a_second_apply_makes_nothing_twice(deployed):
    before, calls = list(deployed.world.writes), list(deployed.world.shell_calls)
    code, text = deployed.apply(ROLES)
    assert code == 0 and "running " not in text
    assert deployed.world.writes == before and deployed.world.shell_calls == calls
    world = deployed.world
    assert sum(len(jobs) for jobs in world.jobs.values()) == 4
    assert sum(len(entries) for entries in world.schedules.values()) == 1
    assert len(world.role_assignments) == 2 and len(world.access[world.workspaces[0]["id"]]) == 2
    assert len(world.workspaces) == 1 and len(world.groups) == 1


def test_role_changes_wait_for_their_own_approval_and_stay_inside_the_demo(bench):
    code, text = bench.apply(confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "p1.vm_identity_roles" in text and "--approve-role-changes" in text
    assert bench.world.role_assignments == [] and bench.world.vm
    code, text = bench.apply(ROLES)
    assert code == 0
    group = next(iter(bench.world.groups.values()))["id"]
    assert sorted(bench.world.role_assignments) == [                                      # by ID; nothing on the subscription
        ("principal-vm", steps.ROLE_IDS["Kubernetes Cluster - Azure Arc Onboarding"], group), ("principal-vm", steps.ROLE_IDS["Reader"], group)]
    assert bench.world.access[bench.world.workspaces[0]["id"]] == {"principal-vm": "Contributor", "principal-aio": "Contributor"}


def test_the_history_is_generated_once_and_again_only_for_a_new_label(deployed):
    jobs = lambda: [w for w in deployed.world.writes if w == "POST job 02_generate_history"]    # noqa: E731
    assert len(jobs()) == 1
    assert deployed.apply(ROLES, "--regenerate-history", "2026-12-01")[0] == 0 and len(jobs()) == 2
    assert deployed.apply(ROLES, "--regenerate-history", "2026-12-01")[0] == 0 and len(jobs()) == 2
    assert deployed.apply(ROLES)[0] == 0 and len(jobs()) == 2


def test_the_schedule_starts_in_the_future_so_that_fabric_does_not_run_the_job_at_once(deployed):
    schedule = next(iter(deployed.world.schedules.values()))[0]["configuration"]
    assert schedule["type"] == "Daily" and schedule["times"] == ["05:00"] and schedule["localTimeZoneId"] == "UTC"
    assert schedule["startDateTime"] > "2026-11-25T" and schedule["endDateTime"] > schedule["startDateTime"]
    assert schedule["startDateTime"] == "2026-11-25T09:56:00"        # ten minutes after the pretend clock (09:46:40 UTC)


# ------------------------------------------------------------------------------------------ the wrong target
def test_a_settings_file_of_a_deployment_made_by_hand_is_refused(bench):
    shutil.copy(bench.root / "config" / "demo.env.example", bench.root / "config" / "demo.env")
    code, text = bench.run("plan")
    assert code == core.EXIT_REFUSED and "made by hand" in text and bench.world.writes == []


def test_a_resource_group_or_a_workspace_the_runner_did_not_make_is_never_used(bench):
    bench.plan(ROLES)
    cfg, world = bench.cfg, bench.world
    world.groups[cfg["RESOURCE_GROUP"]] = {"id": "/subscriptions/sub-1111/resourceGroups/x", "name": cfg["RESOURCE_GROUP"], "location": "eastus", "tags": {}}
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "this deployment did not make it" in text and "--new-names" in text and world.writes == []
    del world.groups[cfg["RESOURCE_GROUP"]]
    world.workspaces.append({"id": "ws-someone", "displayName": cfg["FABRIC_WORKSPACE_NAME"], "description": "Sales", "capacityId": "cap-0001"})
    code, text = bench.apply(ROLES)
    assert code == core.EXIT_BLOCKED and "A workspace named" in text
    assert not any(w.startswith("POST") for w in world.writes) and world.items == {}


def test_another_subscription_or_tenant_after_the_start_is_refused(deployed):
    writes = list(deployed.world.writes)
    deployed.world.account = dict(deployed.world.account, id="sub-2222", name="Production")
    code, text = deployed.run("plan", ROLES)
    assert code == core.EXIT_REFUSED and "began in subscription sub-1111" in text
    deployed.world.account = dict(deployed.world.account, id="sub-1111", tenantId="tenant-bbbb")
    code, text = deployed.run("apply", "--approve", "x", ROLES)
    assert code == core.EXIT_REFUSED and "began in tenant tenant-aaaa" in text and deployed.world.writes == writes


def test_things_that_are_not_the_demos_stop_the_runner_until_they_are_named(deployed):
    world = deployed.world
    world.resources.append({"id": "/subscriptions/sub-1111/rg/providers/Microsoft.Sql/servers/payroll", "type": "Microsoft.Sql/servers"})
    stranger = world.add_item(world.workspaces[0]["id"], "Notebook", "Quarterly numbers")
    code, text = deployed.run("plan", ROLES)
    assert "Microsoft.Sql/servers" in text and "Notebook Quarterly numbers" in text and text.count("BLOCKED") == 2
    digest = re.search(r"^Plan (\w+)$", text, re.M)[1]
    code, text = deployed.run("apply", "--approve", digest, ROLES)
    assert code == core.EXIT_BLOCKED
    code, text = deployed.run("apply", "--approve", digest, ROLES, "--acknowledge", world.resources[-1]["id"], "--acknowledge", stranger["id"])
    assert code == 0, text


def test_new_names_are_refused_once_something_exists(deployed):
    code, text = deployed.run("plan", "--new-names")
    assert code == core.EXIT_REFUSED and "has created resources" in text


# ------------------------------------------------------------------------------------------ interruption and resume
def test_an_operation_fabric_has_not_finished_is_asked_about_again_and_not_started_twice(bench):
    bench.world.slow = {"eventhouse"}
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_RUNNING and "still running in Fabric" in text and "Nothing is lost" in text
    pending = bench.state["pending"]["p1.eventhouse"]["eventhouse"]["location"]
    assert pending.endswith("/operations/" + next(iter(bench.world.operations)))
    assert bench.state["steps"]["p1.eventhouse"]["status"] == "running"
    code, text = bench.apply(ROLES)                              # still running: the same wait, no second request
    assert code == core.EXIT_RUNNING and bench.world.writes.count("POST eventhouses WindFarmEH") == 1
    next(iter(bench.world.operations.values()))["finish"] = True
    code, text = bench.apply(ROLES)
    assert code == 0, text
    assert bench.world.writes.count("POST eventhouses WindFarmEH") == 1 and "pending" in bench.state and not bench.state["pending"]


def test_a_run_started_by_an_apply_that_died_is_waited_for_not_repeated(deployed):
    """The request went out, the computer went down before the checkpoint was written."""
    world, ws = deployed.world, deployed.world.workspaces[0]["id"]
    state_file = deployed.root / ".deploy" / deployed.cfg["DEPLOYMENT_SUFFIX"] / "state.json"
    state = json.loads(state_file.read_text())
    del state["steps"]["p1.history"]
    state_file.write_text(json.dumps(state))
    notebook = world.find(ws, "Notebook", "02_generate_history")["id"]
    world.jobs[notebook].append({"id": "job-orphan", "status": "InProgress", "polls": 0, "notebook": "02_generate_history"})
    code, text = deployed.apply(ROLES)
    assert code == 0 and "already under way (job-orphan)" in text
    assert world.writes.count("POST job 02_generate_history") == 1
    assert deployed.state["steps"]["p1.history"]["evidence"]["job:02_generate_history"]["id"] == "job-orphan"


def test_a_failed_script_stops_the_apply_and_the_next_one_goes_on_from_there(bench):
    bench.world.fail_script = "04-deploy-iot-operations.sh"
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_FAILED and "FAILED   p1.iot_operations" in text
    assert bench.state["steps"]["p1.iot_operations"]["status"] == "failed" and bench.state["steps"]["p1.arc"]["status"] == "complete"
    done_before = [call for call in bench.world.shell_calls if "01-create" in call or "03-arc" in call]
    code, text = bench.apply(ROLES)
    assert code == 0, text
    assert [call for call in bench.world.shell_calls if "01-create" in call or "03-arc" in call] == done_before


def test_a_command_that_returns_without_its_result_does_not_count(bench):
    class Quiet(FakeShell):
        def run(self, argv, env=None, cwd=None, timeout=0):
            if "03-arc-enable.sh" in " ".join(argv):
                return 0, "ok"                                 # exit code 0, and no cluster
            return super().run(argv, env, cwd, timeout)
    real = bench.adapters
    bench.adapters = lambda redact: dict(real(redact), shell=Quiet(bench.world, bench.root, redact))
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_FAILED and "ran without an error, and its result is not there" in text
    assert bench.state["steps"]["p1.arc"]["status"] == "failed"


def test_two_applies_at_once_are_refused_and_a_dead_ones_lock_is_taken_over(deployed):
    folder = deployed.root / ".deploy" / deployed.cfg["DEPLOYMENT_SUFFIX"]
    digest = deployed.plan(ROLES)
    (folder / "apply.lock").write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "started": "now"}))
    code, text = deployed.run("apply", "--approve", digest, ROLES)
    assert code == core.EXIT_REFUSED and "Another apply is running" in text
    (folder / "apply.lock").write_text(json.dumps({"pid": 2 ** 22 + 12345, "host": socket.gethostname(), "started": "long ago"}))
    assert deployed.run("apply", "--approve", digest, ROLES)[0] == 0 and not (folder / "apply.lock").exists()
    (folder / "apply.lock").write_text(json.dumps({"pid": 1, "host": "another-computer", "started": "now"}))
    assert deployed.run("apply", "--approve", digest, ROLES)[0] == core.EXIT_REFUSED


# ------------------------------------------------------------------------------------------ plan changes and drift
def test_a_file_changed_after_the_plan_voids_the_approval(bench):
    digest = bench.plan(ROLES)
    path = bench.root / "fabric" / "kql" / "01-tables.kql"
    path.write_text(path.read_text() + "\n// one more line\n")
    code, text = bench.run("apply", "--approve", digest, ROLES)
    assert code == core.EXIT_REFUSED and "has changed since" in text and bench.world.writes == []


def test_something_removed_behind_the_runners_back_is_drift_and_needs_a_new_approval(deployed):
    world, ws = deployed.world, deployed.world.workspaces[0]["id"]
    old = deployed.plan(ROLES)
    lakehouse = world.find(ws, "Lakehouse", "WindFarmLH")
    world.items[ws] = [e for e in world.items[ws] if e["displayName"] != "WindFarmLH"]
    writes = list(world.writes)
    code, text = deployed.run("apply", "--approve", old, ROLES)
    assert code == core.EXIT_REFUSED and world.writes == writes
    code, text = deployed.run("plan", ROLES)
    assert "p1.lakehouse" in text and "DRIFT, will be redone" in text
    assert lakehouse and deployed.apply(ROLES)[0] in (0, core.EXIT_BLOCKED)       # approved again, the runner rebuilds what it can


# ------------------------------------------------------------------------------------------ handing over
WIZARD_WORDS = ("Use existing mapping", "RawEvents_mapping", "Direct ingestion")


def test_a_destination_that_fabric_took_and_that_ingests_nothing_is_handed_over_with_the_portal_steps(bench):
    bench.world.destination_status = "Warning"
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "blocked  p1.eventstream" in text and "state Warning" in text
    assert all(word in text for word in WIZARD_WORDS)
    assert bench.state["steps"]["p1.eventstream"]["status"] == "blocked" and "p1.data_flow" not in bench.state["steps"]
    # the operator repairs it in the portal; the same apply looks again and goes on
    for topology in bench.world.topology.values():
        topology["destinations"][0]["status"] = "Running"
    code, text = bench.apply(ROLES)
    assert code == 0, text
    assert bench.world.writes.count("POST eventstreams es-windfarm-edge") == 1


def test_no_rows_after_the_wait_is_a_block_with_where_to_look_not_a_success(bench):
    bench.world.ingestion_works = False
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "blocked  p1.gate_telemetry" in text and "No event has reached RawEvents" in text
    assert all(word in text for word in WIZARD_WORDS) and bench.now[0] >= 600          # it waited its ten minutes first
    assert "p1.reference_upload" not in bench.state["steps"]
    bench.world.ingestion_works = True
    assert bench.apply(ROLES)[0] == 0


def test_the_gate_notebook_decides_by_failing_and_its_reason_is_shown_without_the_token(deployed):
    state_file = deployed.root / ".deploy" / deployed.cfg["DEPLOYMENT_SUFFIX"] / "state.json"
    state = json.loads(state_file.read_text())
    del state["steps"]["p1.gate_lakehouse"]
    state_file.write_text(json.dumps(state))
    deployed.world.vm["powerState"] = "VM deallocated"        # the telemetry stops, the tables go stale
    code, text = deployed.apply(ROLES)
    assert code == core.EXIT_BLOCKED and "The gate notebook did not pass" in text and "TurbineTelemetry: 0 rows" in text
    assert not any(token in deployed.everything_written() for token in deployed.world.tokens)


def later(bench, *options, confirm=()):
    return bench.apply(ROLES, "--up-to", "phase4", *options, confirm=confirm)


def test_phases_2_to_4_stop_at_each_thing_only_a_person_can_do_and_go_on_when_it_is_there(deployed):
    world, ws = deployed.world, deployed.world.workspaces[0]["id"]
    code, text = later(deployed)
    assert code == core.EXIT_BLOCKED and "blocked  p2.semantic_model" in text and "06_build_semantic_model" in text and "Run all" in text
    assert "%pip" in text and "--opt-in pip-jobs" in text
    assert not any("06_build" in w for w in world.writes if w.startswith("POST job"))
    world.add_item(ws, "SemanticModel", "WindFarm Operations")
    code, text = later(deployed)
    assert "blocked  p2.acceptance" in text and "--confirm p2.acceptance" in text
    world.add_item(ws, "Report", "WindFarm Operations Report")
    code, text = later(deployed, confirm=["p2.acceptance"])
    assert code == core.EXIT_BLOCKED and "blocked  phase3.tenant_settings" in text and "Enable Operations Agents" in text
    code, text = later(deployed, confirm=["phase3.tenant_settings"])
    assert "blocked  p3.data_agent" in text
    world.add_item(ws, "DataAgent", "WindFarmDataAgent")
    code, text = later(deployed)
    assert "optional p3.ontology" in text and "blocked  p3.operations_agent" in text and "Fabric Operations Agent" in text
    assert "GearboxVsFleetLive" in world.kql["tables"]
    world.add_item(ws, "OperationsAgent", "WindFarmGearboxWatch")
    world.rayfin_signed_in = False
    code, text = later(deployed, confirm=["phase4.tenant_settings"])
    assert code == core.EXIT_BLOCKED and "not signed in" in text and "npx rayfin login" in text
    world.rayfin_signed_in = True
    code, text = later(deployed)
    assert code == 0, text
    assert "Lakehouse route PASS: 7548 rows from 12 turbines in the last 60 minutes, the newest 2.0 min old" in text
    assert "optional p4.eventhouse_principal" in text and "create-principal" not in " ".join(world.shell_calls)
    config = (deployed.root / "app/windfarm-twin/packages/functions/src/config.ts").read_text()
    assert deployed.cfg["FABRIC_WORKSPACE_NAME"] in config
    assert world.find(ws, "FabricApp", "WindFarmTwin")
    # hourly schedule for notebook 05, made once
    assert [s[0]["configuration"]["type"] for s in world.schedules.values()] == ["Daily", "Cron"]
    assert later(deployed)[0] == 0 and sum(len(s) for s in world.schedules.values()) == 2


def test_the_lakehouse_route_that_is_only_behind_blocks_with_what_was_seen_on_the_tenant(deployed):
    world, ws = deployed.world, deployed.world.workspaces[0]["id"]
    for kind, name in (("SemanticModel", "WindFarm Operations"), ("Report", "WindFarm Operations Report"),
                       ("DataAgent", "WindFarmDataAgent"), ("OperationsAgent", "WindFarmGearboxWatch")):
        world.add_item(ws, kind, name)
    world.sql_route = {"rows": 0, "turbines": 0, "newest_minutes": None}
    code, text = later(deployed, confirm=["p2.acceptance", "phase3.tenant_settings", "phase4.tenant_settings"])
    assert code == core.EXIT_BLOCKED and "blocked  p4.gate_data_route" in text and "only behind" in text
    world.sql_route = {"rows": 7548, "turbines": 12, "newest_minutes": 2.0}
    assert later(deployed)[0] == 0


def test_with_the_opt_ins_the_runner_tries_the_notebooks_itself_and_falls_back_to_the_person(deployed):
    world = deployed.world
    options = ("--opt-in", "pip-jobs", "--allow-preview", "data-agent-sdk", "--allow-preview", "ontology")
    world.failing_notebooks = {"08_build_report"}
    code, text = later(deployed, *options, confirm=["phase3.tenant_settings", "phase4.tenant_settings"])
    assert code == core.EXIT_BLOCKED and "blocked  p2.report" in text and "Run all" in text
    job = next(j for jobs in world.jobs.values() for j in jobs if j["notebook"] == "06_build_semantic_model")
    assert job["parameters"] == {"_inlineInstallationEnabled": {"value": "True", "type": "bool"}}
    world.failing_notebooks = set()
    world.add_item(world.workspaces[0]["id"], "Report", "WindFarm Operations Report")
    world.add_item(world.workspaces[0]["id"], "OperationsAgent", "WindFarmGearboxWatch")
    code, text = later(deployed, *options)
    assert code == 0, text
    assert world.find(world.workspaces[0]["id"], "Ontology", "WindFarmOntology") and world.find(world.workspaces[0]["id"], "DataAgent", "WindFarmDataAgent")
    # without the preview allowed, the pip opt-in alone does not start the pre-release SDK
    plan = deployed.run("plan", ROLES, "--up-to", "phase3", "--opt-in", "pip-jobs")[1]
    assert "p3.data_agent" in plan


def test_a_trial_capacity_stops_phase_3_and_the_runner_offers_no_way_around(deployed):
    world, ws = deployed.world, deployed.world.workspaces[0]["id"]
    world.capacities[0]["sku"] = "FT1"
    world.add_item(ws, "SemanticModel", "WindFarm Operations")
    world.add_item(ws, "Report", "WindFarm Operations Report")
    code, text = later(deployed, confirm=["p2.acceptance"])
    assert code == core.EXIT_BLOCKED and "blocked  p3.capacity" in text and "trial" in text and "yours to decide" in text


# ------------------------------------------------------------------------------------------ Phase 5a
PHASE5A = "--enable-phase5a-isolated-simulator"


def test_phase_5a_is_not_there_unless_asked_for(deployed):
    assert "p5a." not in deployed.run("plan", ROLES, "--up-to", "phase4")[1]
    assert "p5a.isolation" in deployed.run("plan", ROLES, PHASE5A)[1]


def test_phase_5a_provisions_the_path_switched_off_and_never_sends_anything(deployed):
    world, ws = deployed.world, deployed.world.workspaces[0]["id"]
    code, text = deployed.apply(ROLES, PHASE5A)
    assert code == core.EXIT_BLOCKED and "blocked  p5a.isolation" in text and "no real controller" in text
    assert "fabric-to-windfarm-control" not in world.dataflows
    code, text = deployed.apply(ROLES, PHASE5A, confirm=["p5a.isolation"])
    assert code == 0, text
    assert world.dataflows["fabric-to-windfarm-control"]["properties"]["mode"] == "Disabled"
    assert "switched off: no command reaches the simulator" in text and "optional p5a.enable" in text
    notebook = world.find(ws, "Notebook", "12_send_edge_command")
    assert notebook and notebook["id"] not in world.jobs
    assert not any(word in call for call in world.shell_calls for word in ("inject", "simctl", "mqtt"))
    # a person switches it on later: the runner reports it and changes nothing
    world.dataflows["fabric-to-windfarm-control"]["properties"]["mode"] = "Enabled"
    writes = list(world.writes)
    code, text = deployed.apply(ROLES, PHASE5A)
    assert code == 0 and "SWITCHED ON" in text and world.writes == writes


def test_the_runner_has_no_way_to_run_the_notebooks_that_send_commands(deployed):
    ctx, _ = cli.build(cli.parser().parse_args(["status"]), deployed.root, io.StringIO(), deployed.adapters)
    for name in ("12_send_edge_command", "13_command_center"):
        with pytest.raises(CloudError, match="does not run"):
            run_notebook(ctx, "ws", "nb", name)
    source = "".join((ROOT / "tools" / "deployer" / name).read_text() for name in ("steps.py", "steps_later.py", "cloud.py", "cli.py"))
    assert "inject-anomaly" not in source and "_control/request" not in source and "simctl.sh" not in source
    assert not re.search(r"run_step\(\"1[23]_", source)


# ------------------------------------------------------------------------------------------ secrets
def test_no_token_key_or_connection_string_reaches_the_output_the_checkpoint_or_the_settings(deployed):
    later(deployed, "--opt-in", "pip-jobs")
    deployed.run("status")
    written = deployed.everything_written() + json.dumps(deployed.state)
    assert deployed.world.tokens, "the run asked for no token: the test would prove nothing"
    # the middle of each key as well: a key that lost its last character on the way is still a key
    for secret in deployed.world.tokens + [KEY, KEY[::-1], KEY[4:28], KEY[::-1][4:28], CONNECTION, "SharedAccessKey="]:
        assert secret not in written
    assert "esehabc123_eh" in written                      # the topic is a name, and is kept


def test_a_script_that_prints_a_secret_is_shown_without_it(bench):
    bench.world.fail_script = "01-create-edge-vm.sh"
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_FAILED and KEY not in bench.everything_written()


def test_the_redactor_takes_out_what_looks_like_a_secret_and_what_it_was_told_is_one():
    redact = core.Redactor()
    redact.learn("an-opaque-value-1234")
    text = redact('Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345 {"accessToken": "xyz", "primaryKey":"k"} '
                  f'{CONNECTION} url?sig=abc%2Fdef&se=2026 AccountKey=QUJD== an-opaque-value-1234 '
                  'eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl esehabc123_eh')
    for secret in ("abcdefghijklmnopqrstuvwxyz012345", '"xyz"', '"k"', KEY, "abc%2Fdef", "QUJD==", "an-opaque-value-1234", "eyJhbGci"):
        assert secret not in text
    assert "esehabc123_eh" in text and "se=2026" in text


# ------------------------------------------------------------------------------------------ preflight
def test_preflight_names_what_is_missing_and_changes_nothing(bench):
    world = bench.world
    world.unregistered = {"Microsoft.IoTOperations", "Microsoft.DeviceRegistry"}
    world.capacities.append({"id": "cap-0002", "displayName": "other", "sku": "F2", "region": "West Europe", "state": "Active"})
    world.custom_locations = None
    world.my_roles = ["Reader"]
    code, text = bench.run("preflight", "--up-to", "phase4")
    assert code == core.EXIT_BLOCKED and world.writes == []
    assert "az provider register --namespace Microsoft.IoTOperations" in text and "a change to the whole subscription" in text
    assert "cap-0001" in text and "cap-0002" in text and "does not choose between capacities" in text
    assert "az ad sp show --id bc313c14" in text
    assert "Creating the resource group needs Contributor or Owner" in text and "does not widen its own access" in text
    assert "Fabric Apps" in text and "phase4.tenant_settings" in text
    assert "p1.edge_vm" not in text                       # preflight shows the prerequisites, not the deployment


def test_a_service_principal_sign_in_is_refused_for_what_only_a_person_may_do(bench):
    bench.plan()
    bench.world.account = dict(bench.world.account, user={"name": "app-id", "type": "servicePrincipal"})
    code, text = bench.run("preflight")
    assert code == core.EXIT_BLOCKED and "signed in as a servicePrincipal" in text


# ------------------------------------------------------------------------------------------ the pieces
def test_every_setup_command_of_the_kql_files_is_sent_and_nothing_that_removes():
    for name, expected in (("01-tables.kql", 1), ("02-update-policies.kql", 1), ("03-onelake-availability.kql", 1),
                           ("04-prepared-views.kql", 3), ("05-agent-readiness.kql", 2)):
        text = (ROOT / "fabric" / "kql" / name).read_text()
        blocks = steps.kql_blocks(text)
        assert len(blocks) == expected, name
        sent = "\n".join(blocks)
        assert all(block.startswith(".") for block in blocks), name     # no comment in front: a command begins with its dot
        for row in text.splitlines():           # no setup command is lost to the split; the check queries below them are not sent
            if row.startswith((".execute", ".create", ".alter")):
                assert row in sent, f"{name}: {row[:60]}"
        assert not re.search(r"^\.(drop|clear|delete|set)", sent, re.M), name
    assert steps.kql_blocks((ROOT / "fabric" / "kql" / "99-reset-demo-data.kql").read_text()) == []
    assert steps.kql_blocks(".drop table X\n\n.clear table Y data\n\nTurbineTelemetry | count\n") == []


def gate_logic():
    notebook = json.loads((ROOT / "fabric" / "notebooks" / "90_deployment_gate.ipynb").read_text())
    return ["".join(cell["source"]) for cell in notebook["cells"] if cell["cell_type"] == "code"]


def test_the_gate_notebook_fails_for_an_empty_a_stale_and_an_unreadable_table():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 11, 25, 9, 0, tzinfo=timezone.utc)

    class Frame:
        def __init__(self, rows, newest=None):
            self.rows, self.newest = rows, newest
        count = lambda self: self.rows                                   # noqa: E731
        agg = lambda self, _: self                                       # noqa: E731
        collect = lambda self: [[self.newest]]                           # noqa: E731

    class Spark:
        tables = {"good": Frame(10, now.replace(tzinfo=None) - timedelta(minutes=4)), "empty": Frame(0),
                  "stale": Frame(5, now - timedelta(hours=3))}

        @property
        def read(self):
            return self

        def table(self, name):
            if name not in self.tables:
                raise RuntimeError(f"[TABLE_OR_VIEW_NOT_FOUND] {name}")
            return self.tables[name]

    parameters, logic, verdict = gate_logic()
    scope = {"spark": Spark()}
    exec(parameters, scope)                         # the form the runner fills in
    assert scope["checks"] == "[]"
    exec(logic.split("\nresult = run_checks")[0], scope)
    live = {"newest": "Timestamp", "within_minutes": 60}
    result = scope["run_checks"](Spark(), [dict(table="good", **live), {"table": "empty"}, dict(table="stale", **live), {"table": "missing"}], now)
    assert [row["rows"] for row in result["tables"]] == [10, 0, 5, None] and result["tables"][0]["age_minutes"] == 4.0
    assert len(result["failures"]) == 3 and "stale: the newest row is 180.0 minutes old" in result["failures"][1]
    assert "raise RuntimeError" in verdict and "Files/deployment/gate-" in verdict
    assert scope["run_checks"](Spark(), [dict(table="good", **live)], now)["failures"] == []


def test_the_generated_and_copied_texts_are_what_they_are_copies_of():
    import subprocess
    assert subprocess.run([sys.executable, str(ROOT / "tools" / "build-deploy-gate.py"), "--check"], capture_output=True).returncode == 0
    probe = (ROOT / "app" / "probe-lakehouse-route.mjs").read_text()
    live = (ROOT / "app" / "overlay" / "packages" / "functions" / "src" / "live.ts").read_text()
    theirs = re.search(r"export const SQL_PROBE = `(.*?)`;", live, re.S)[1].replace("${LAKEHOUSE_WINDOW_MINUTES}", "60")
    ours = re.search(r"export const QUERY = `(.*?)`;", probe, re.S)[1]
    assert " ".join(ours.split()) == " ".join(theirs.split())
    # every step is named once, and every file a step names exists
    from deployer.steps_later import catalogue
    everything = catalogue(core.Options(up_to="phase4", phase5a=True))
    assert len({step.id for step in everything}) == len(everything)
    for step in everything:
        for name in step.inputs:
            assert (ROOT / name).exists(), f"{step.id} names {name}"
        assert step.basis, step.id


# ------------------------------------------------------------------------------------------ the real adapters
def test_the_azure_cli_adapter_tells_missing_from_failed_and_hides_the_token():
    import types
    from deployer.cloud import Az, Blocked
    answers = {
        ("group", "show"): (3, "", "ERROR: (ResourceGroupNotFound) Resource group 'rg-x' could not be found."),
        ("vm", "show"): (1, "", "ERROR: AADSTS700082: The refresh token has expired. Bearer abcdefghijklmnopqrstuvwxyz0123"),
        ("account", "show"): (0, '{"id": "sub-1"}', ""),
        ("account", "get-access-token"): (0, "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJl\n", ""),
    }
    seen = []

    def run(argv, **how):
        seen.append(argv)
        import subprocess
        assert how["stdin"] == subprocess.DEVNULL, "the Azure CLI could wait for a key that nobody is asked to press"
        code, out, err = answers[tuple(argv[1:3])]
        return types.SimpleNamespace(returncode=code, stdout=out, stderr=err)
    redact = core.Redactor()
    az = Az(redact, run=run)
    assert az.maybe("group", "show", "--name", "rg-x") is None
    assert az.json("account", "show") == {"id": "sub-1"} and seen[-1][-2:] == ["--output", "json"]
    with pytest.raises(CloudError) as failure:
        az.maybe("vm", "show")
    assert "AADSTS700082" in str(failure.value) and "abcdefghijklmnopqrstuvwxyz0123" not in str(failure.value)
    token = az.token("https://api.fabric.microsoft.com")
    assert redact(f"sent {token}") == "sent [secret removed]"
    answers[("account", "get-access-token")] = (1, "", "ERROR: Please run 'az login'")
    with pytest.raises(Blocked) as stop:
        az.token("https://storage.azure.com")
    assert "az login --scope https://storage.azure.com/.default" in stop.value.action


def test_the_shell_adapter_shows_a_scripts_output_without_its_secrets(tmp_path, capsys):
    from deployer.cloud import Shell
    shell = Shell(tmp_path, core.Redactor(), out=sys.stdout)
    code, text = shell.run(["bash", "-c", f"echo 'using {CONNECTION}'; echo second; exit 7"])
    shown = capsys.readouterr().out
    assert code == 7 and KEY not in text and KEY not in shown and "second" in shown and "[connection string removed]" in shown
    with pytest.raises(CloudError, match="exit code 7"):
        shell.must(["bash", "-c", "exit 7"])
    assert shell.capture(["no-such-program-here"])[0] == 127


def test_the_eventhouse_adapter_reads_rows_and_turns_a_refusal_into_a_block():
    from deployer.cloud import Blocked, Kusto, http
    calls = []

    def request(method, url, token, body=None, headers=None, timeout=0):
        calls.append((method, url, body))
        if "refused" in body["csl"]:
            return 403, b"Forbidden"
        return 200, json.dumps({"Tables": [{"Columns": [{"ColumnName": "TableName"}, {"ColumnName": "Rows"}],
                                            "Rows": [["RawEvents", 5], ["TurbineTelemetry", 7]]}]}).encode()

    class TokenOnly:
        token = staticmethod(lambda resource: "t")
    kusto = Kusto(TokenOnly(), core.Redactor(), request=request)
    kusto._audience["https://cluster.example"] = "https://cluster.example"         # as read from the cluster's metadata
    assert kusto.rows("https://cluster.example", "db", ".show tables", mgmt=True) == [
        {"TableName": "RawEvents", "Rows": 5}, {"TableName": "TurbineTelemetry", "Rows": 7}]
    assert calls[0][1] == "https://cluster.example/v1/rest/mgmt" and calls[0][2] == {"db": "db", "csl": ".show tables"}
    kusto.rows("https://cluster.example", "db", "RawEvents | count")
    assert calls[1][1].endswith("/v1/rest/query")
    with pytest.raises(Blocked):
        kusto.rows("https://cluster.example", "db", "refused")
    with pytest.raises(CloudError, match="not https"):
        http("GET", "http://plain.example/x", "token")


def test_the_checkpoint_is_written_in_one_move_and_a_broken_one_is_not_guessed_at(tmp_path):
    state = core.State(tmp_path / "d", core.Redactor())
    state.mark("p1.x", "complete", detail=f"made with {CONNECTION}")
    assert KEY not in (tmp_path / "d" / "state.json").read_text()
    assert [path.name for path in (tmp_path / "d").iterdir()] == ["state.json"]            # no temporary file left behind
    (tmp_path / "d" / "state.json").write_text('{"steps": {"p1.x": ')
    with pytest.raises(core.Refused, match="cannot be read"):
        core.State(tmp_path / "d", core.Redactor())


# ------------------------------------------------------------------------------------------ a few more of the target
def test_status_shows_the_checkpoint_and_the_freshness_of_now_and_changes_nothing(deployed):
    writes = list(deployed.world.writes)
    code, text = deployed.run("status")
    assert code == 0 and deployed.world.writes == writes
    assert re.search(r"p1\.gate_telemetry\s+complete", text) and "p1.edge_host" in text and "(not looked at by the runner itself)" in text
    assert "Now, in the Eventhouse: 688 readings from 12 turbines in the last 5 minutes, the newest 38 s old." in text
    deployed.world.vm["powerState"] = "VM deallocated"
    assert "0 readings from 0 turbines" in deployed.run("status")[1]          # the gate stays passed; status tells the present


def test_what_an_apply_made_and_did_not_live_to_write_down_is_recognised_by_its_mark(deployed):
    state_file = deployed.root / ".deploy" / deployed.cfg["DEPLOYMENT_SUFFIX"] / "state.json"
    state = json.loads(state_file.read_text())
    group, workspace = state["target"].pop("resource_group_id"), state["target"].pop("workspace_id")
    state_file.write_text(json.dumps(state))
    writes = list(deployed.world.writes)
    code, text = deployed.apply(ROLES)
    assert code == 0, text
    assert deployed.world.writes == writes and deployed.state["target"]["resource_group_id"] == group
    assert deployed.state["target"]["workspace_id"] == workspace


def test_a_workspace_moved_to_another_capacity_stops_the_runner(deployed):
    deployed.world.workspaces[0]["capacityId"] = "cap-9999"
    code, text = deployed.run("plan", ROLES)
    assert "BLOCKED" in text and "Someone moved it" in text
    assert deployed.run("apply", "--approve", re.search(r"^Plan (\w+)$", text, re.M)[1], ROLES)[0] == core.EXIT_BLOCKED


def test_new_names_before_anything_exists_change_every_generated_name_together(bench):
    bench.plan()
    first = bench.cfg
    code, text = bench.run("plan", "--new-names")
    second = bench.cfg
    assert code == 0 and second["DEPLOYMENT_SUFFIX"] != first["DEPLOYMENT_SUFFIX"]
    assert second["RESOURCE_GROUP"].endswith(second["DEPLOYMENT_SUFFIX"]) and second["STORAGE_ACCOUNT_NAME"] == "sawindfarm" + second["DEPLOYMENT_SUFFIX"]
    assert second["SUBSCRIPTION_ID"] == first["SUBSCRIPTION_ID"] and bench.world.writes == []
    # a name edited by hand is refused: the names of a deployment go together
    names.write_env(bench.root / "config" / "demo.env", {"VM_NAME": "my-own-vm"})
    code, text = bench.run("plan")
    assert code == core.EXIT_REFUSED and "VM_NAME no longer carry the suffix" in text


def test_a_missing_tool_and_a_missing_right_are_named_and_nothing_is_widened(bench):
    bench.world.missing_tools = {"ssh"}
    code, text = bench.run("preflight")
    assert code == core.EXIT_BLOCKED and "Not on this computer: ssh" in text
    bench.world.missing_tools = set()
    bench.world.may_create_workspaces = False
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "blocked  p1.workspace" in text and "Contributor permissions" in text
    assert bench.world.workspaces == [] and len(bench.world.role_assignments) == 2       # the two on the resource group, no more
    bench.world.may_create_workspaces = True
    assert bench.apply(ROLES)[0] == 0


def test_a_long_apply_gets_a_new_token_before_the_old_one_ends():
    from deployer.cloud import RunnerFabric
    asked, now = [], [0.0]

    class OneAz:
        def token(self, resource):
            asked.append(resource)
            return f"token-{len(asked)}-padding-padding"
    fabric = RunnerFabric(OneAz(), clock=lambda: now[0], api="https://127.0.0.1:9/v1")
    assert fabric._token.startswith("token-1")
    now[0] = 1300.0
    with pytest.raises(CloudError):           # nothing listens there; the token is renewed before the attempt
        fabric.call("GET", "workspaces")
    assert len(asked) == 2 and fabric._token.startswith("token-2")


# ------------------------------------------------------------------------------------------ after the first run on a tenant
def test_every_check_is_announced_as_it_starts_so_that_waiting_does_not_look_like_a_hang(bench):
    """25 November 2026, 09:47: preflight printed one line and then nothing, and the user asked whether that was expected."""
    code, text = bench.run("preflight", "--up-to", "phase4")
    rows = text.splitlines()
    notice = next(i for i, row in enumerate(rows) if row.startswith("Looking at "))
    assert "changes nothing" in rows[notice] and "can take a few minutes" in rows[notice]
    announced = [row.split()[2].rstrip(":") for row in rows if row.startswith("  looking at ")]
    assert announced[:4] == ["pre.tools", "pre.signin", "pre.extensions", "pre.rights"] and "pre.region" in announced and "p4.node" in announced
    assert rows.index("Target") > max(i for i, row in enumerate(rows) if row.startswith("  looking at "))   # the table comes after
    assert "  looking at p1.workspace" in bench.run("plan")[1]
    # a check that took long says how long, which is where the first real numbers come from
    real = bench.adapters

    class Slow(FakeAz):
        def maybe(self, *args, timeout=0):
            if args[:1] == ("rest",) and "Microsoft.Compute/skus" in " ".join(args):
                bench.now[0] += 74
            return super().maybe(*args, timeout=timeout)
    bench.adapters = lambda redact: dict(real(redact), az=Slow(bench.world, redact))
    rows = bench.run("preflight", "--recheck")[1].splitlines()
    assert rows[next(i for i, row in enumerate(rows) if "looking at pre.region" in row) + 1] == "    74 s"
    assert sum(1 for row in rows if re.fullmatch(r"    \d+ s", row)) == 1


def test_one_check_that_cannot_be_made_is_one_line_and_the_others_are_still_made(bench):
    real = bench.adapters

    class Slow(FakeAz):
        def maybe(self, *args, timeout=0):
            if args[:2] == ("provider", "show"):
                raise CloudError("az provider show did not answer within 180 seconds.")
            return super().maybe(*args, timeout=timeout)
    bench.adapters = lambda redact: dict(real(redact), az=Slow(bench.world, redact))
    code, text = bench.run("preflight")
    assert code == core.EXIT_BLOCKED and "FAILED" not in text
    assert "could not be looked at: az provider show" in text and "Run the same command again" in text
    assert re.search(r"pre\.capacity\s+done", text) and re.search(r"pre\.region\s+done", text)


def test_the_vm_sizes_are_asked_with_one_filtered_call_that_cannot_stop_a_run(bench):
    """25 November 2026, 09:53: `az vm list-skus --location did not answer within 300 seconds`, and preflight ended there."""
    world = bench.world
    world.refused = {"Standard_D8s_v5": "NotAvailableForSubscription"}
    code, text = bench.run("preflight")
    assert "VM size Standard_D8s_v6 is offered (Standard_D8s_v5, Standard_D8as_v5, Standard_D8as_v6, Standard_D8as_v7 not offered)" in text
    # none of them: a block that names each size with its reason
    world.refused = {name: "NotAvailableForSubscription" for name in world.skus}
    text = bench.run("preflight", "--recheck")[1]
    assert "None of the sizes in VM_SIZE is offered" in text and "Standard_D8s_v7: NotAvailableForSubscription" in text
    assert "Standard_D8as_v5: not known in southcentralus" in text
    # the question cannot be asked: said in one line as NOT CHECKED, never as done, and no reason to stop
    world.refused = {"Standard_D8s_v5": "NotAvailableForSubscription"}
    real, unanswered = bench.adapters, []

    class Deaf(FakeAz):
        def maybe(self, *args, timeout=0):
            if args[:1] == ("rest",) and "Microsoft.Compute/skus" in " ".join(args):
                unanswered.append(timeout)
                raise CloudError("az rest --method get did not answer within 60 seconds.")
            return super().maybe(*args, timeout=timeout)
    bench.adapters = lambda redact: dict(real(redact), az=Deaf(world, redact))
    text = bench.run("preflight")[1]              # a block is not kept: the question is asked again without --recheck
    assert re.search(r"pre\.region\s+NOT CHECKED", text) and not re.search(r"pre\.region\s+done", text)
    assert "could not be read" in text and "p1.edge_vm tries the sizes of VM_SIZE in their order" in text
    assert unanswered == [60]
    # the apply does not ask a third and a fourth time, and the script is told to try the sizes instead of asking for itself
    assert bench.apply(ROLES, confirm=[SETTINGS])[0] == 0 and unanswered == [60]
    assert world.vm_env.get("VM_SIZE_SKIP_CHECK") == "1" and "VM_SIZE_OFFERED" not in world.vm_env


def test_the_vm_script_is_handed_the_sizes_that_were_checked_and_the_question_ends_with_the_vm(bench):
    bench.world.refused = {"Standard_D8s_v5": "NotAvailableForSubscription"}
    assert bench.apply(ROLES, confirm=[SETTINGS])[0] == 0
    assert bench.world.vm_env["VM_SIZE_OFFERED"] == "Standard_D8s_v6 Standard_D8s_v7"
    asked = bench.world.sku_calls
    code, text = bench.run("plan", ROLES)
    assert bench.world.sku_calls == asked and "the VM exists, so its size is no longer a question" in text


def test_a_missing_cli_extension_is_the_operators_to_install_and_is_never_asked_for_on_the_way(bench):
    bench.world.extensions = ["ssh"]
    code, text = bench.run("preflight")
    assert code == core.EXIT_BLOCKED and "az extension add --name azure-iot-ops --yes" in text and "nobody would see the question" in text
    # and the cluster is read as a plain resource: the fake fails the test on any `az connectedk8s`, which a workstation may lack
    bench.world.extensions = ["azure-iot-ops"]
    assert bench.apply(ROLES, confirm=[SETTINGS])[0] == 0


# ------------------------------------------------------------------------------------------ after the second run on a tenant
PPU = {"id": "0aa47150-0000-0000-0000-00000000pp30", "displayName": "Premium Per User - Reserved", "sku": "PP3",
       "region": "Central US", "state": "Active"}
ELSEWHERE = "7c1e2d3f-0000-0000-0000-0000000trial"


def as_on_the_tenant(world) -> None:
    """25 November 2026, 10:09: the only capacity Fabric listed was Premium Per User; the existing workspace ran on another."""
    world.capacities = [dict(PPU)]
    world.workspaces = [{"id": "ws-by-hand", "displayName": "WindFarmDigitalTwin", "description": "", "capacityId": ELSEWHERE},
                        {"id": "ws-mine", "displayName": "My workspace", "description": "", "type": "Personal"}]


def set_capacity(bench, value: str) -> None:
    names.write_env(bench.root / "config" / "demo.env", {"FABRIC_CAPACITY_ID": value})


def test_a_capacity_that_cannot_hold_fabric_items_is_never_chosen_and_never_accepted(bench):
    """The second issue took "the only capacity you see" for "the capacity to use", wrote a Premium Per User capacity
    into the settings, showed `done`, and called it a paid capacity for Phase 3."""
    as_on_the_tenant(bench.world)
    code, text = bench.run("preflight", "--up-to", "phase3")
    assert code == core.EXIT_BLOCKED and bench.cfg["FABRIC_CAPACITY_ID"] == ""             # nothing chosen, nothing written
    assert re.search(r"pre\.capacity\s+BLOCKED", text) and "Fabric lists 0 for you that can hold the demo" in text
    assert f"{PPU['id']}  Premium Per User - Reserved (PP3, Central US)  -> cannot hold the demo: a Premium Per User capacity" in text
    assert f"{ELSEWHERE}  used by: WindFarmDigitalTwin" in text and "My workspace" not in text
    assert "capacity        not chosen yet" in text
    # the ID the second issue wrote: refused by what it is, with the same list to choose from
    set_capacity(bench, PPU["id"])
    code, text = bench.run("preflight", "--up-to", "phase3")
    assert code == core.EXIT_BLOCKED and "FABRIC_CAPACITY_ID names Premium Per User - Reserved (PP3, Central US): a Premium Per User capacity" in text
    assert "cannot be created on it" in text and f"{ELSEWHERE}  used by: WindFarmDigitalTwin" in text
    assert f"capacity        Premium Per User - Reserved (PP3, Central US)  {PPU['id']}" in text     # the target names it
    assert re.search(r"p3\.capacity\s+BLOCKED", text) and "a paid capacity" not in text.split("p3.capacity")[2].split("\n")[1]
    # an ID nobody has
    set_capacity(bench, "cap-nowhere")
    text = bench.run("preflight")[1]
    assert "Fabric lists no capacity with that ID for you, and no workspace you can open runs on it" in text
    assert bench.world.writes == []


def test_a_capacity_fabric_does_not_list_is_accepted_as_not_checked_and_the_workspace_decides(bench):
    as_on_the_tenant(bench.world)
    bench.plan()
    set_capacity(bench, ELSEWHERE)
    code, text = bench.run("plan", ROLES, "--up-to", "phase3")
    assert re.search(r"pre\.capacity\s+NOT CHECKED", text) and "is not in the list Fabric gives you" in text
    assert "Workspaces you can open run on it (WindFarmDigitalTwin)" in text and "Contributor permissions" in text
    assert f"capacity        {ELSEWHERE}  (not in the list of capacities Fabric gives you)" in text
    assert re.search(r"p3\.capacity\s+NOT CHECKED", text) and "cannot read whether it is a paid one" in text
    # Fabric refuses the workspace on that capacity: a block that names the capacity, and nothing half-made
    bench.world.closed_capacities = {ELSEWHERE}
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "blocked  p1.workspace" in text and f"on capacity {ELSEWHERE}" in text
    assert "put another capacity into FABRIC_CAPACITY_ID" in text and len(bench.world.workspaces) == 2
    # it lets him: the workspace is made there, and the deployment goes on to the end of Phase 1
    bench.world.closed_capacities = set()
    code, text = bench.apply(ROLES)
    assert code == 0, text
    made = next(entry for entry in bench.world.workspaces if entry["displayName"] == bench.cfg["FABRIC_WORKSPACE_NAME"])
    assert made["capacityId"] == ELSEWHERE and "unchecked pre.capacity" in text


@pytest.mark.parametrize("sku, kind", [("F2", "fabric"), ("F64", "fabric"), ("FT1", "trial"), ("Trial", "trial"), ("P1", "premium"),
                                       ("PP3", "per-user"), ("A4", "embedded"), ("EM3", "embedded"), ("DCT1", "unknown"),
                                       ("", "unknown"), (None, "unknown")])
def test_what_a_capacity_can_hold_is_read_from_its_sku(sku, kind):
    assert steps.capacity_kind(sku) == kind
    assert (kind in steps.CAN_HOLD) + (kind in steps.CANNOT_HOLD) + (kind == "unknown") == 1


def test_one_usable_capacity_and_no_other_in_sight_is_taken_and_two_candidates_are_a_choice(bench):
    bench.world.capacities.append(dict(PPU))                       # a second one that cannot hold the demo is no rival
    text = bench.run("preflight")[1]
    assert bench.cfg["FABRIC_CAPACITY_ID"] == "cap-0001" and "the only one in sight that can hold Fabric items" in text
    assert "capacity        demo-capacity (F64, South Central US)  cap-0001" in text
    # with a workspace on a capacity that is not listed there are two candidates, and the runner does not pick
    set_capacity(bench, "")
    bench.world.workspaces = [{"id": "ws-other", "displayName": "Sales", "description": "", "capacityId": ELSEWHERE}]
    code, text = bench.run("preflight")
    assert code == core.EXIT_BLOCKED and bench.cfg["FABRIC_CAPACITY_ID"] == "" and "with others in use by your workspaces" in text
    assert "cap-0001  demo-capacity (F64, South Central US)  -> can hold the demo: a Fabric capacity" in text
    # a paused capacity is said to be paused, and is not resumed
    bench.world.workspaces, bench.world.capacities[0]["state"] = [], "Inactive"
    set_capacity(bench, "cap-0001")
    text = bench.run("preflight")[1]
    assert "Capacity demo-capacity (F64, South Central US) is Inactive" in text and "does not change a capacity" in text


class Unanswered(FakeAz):
    """The two calls with large answers stand until the time limit, as on the workstation of 25 November."""
    asked: list = []

    def maybe(self, *args, timeout=0):
        text = " ".join(args)
        if args[:1] == ("rest",) and ("Microsoft.Compute/skus" in text or "roleAssignments" in text and "assignedTo" in text):
            Unanswered.asked.append("sizes" if "skus" in text else "roles")
            raise CloudError(f"az rest --method get did not answer within {timeout} seconds.")
        return super().maybe(*args, timeout=timeout)


@pytest.fixture
def slow_line(bench):
    Unanswered.asked = []
    real = bench.adapters
    bench.adapters = lambda redact: dict(real(redact), az=Unanswered(bench.world, redact))
    return bench


def test_what_could_not_be_checked_is_never_called_done(slow_line):
    """The second issue printed `pre.rights  done  ... could not read your roles`."""
    code, text = slow_line.run("preflight")
    for step in ("pre.rights", "pre.region"):
        assert re.search(rf"{re.escape(step)}\s+NOT CHECKED", text) and not re.search(rf"{re.escape(step)}\s+done", text)
    assert "your roles could not be read (az rest --method get did not answer within 60 seconds.)" in text
    assert " 2 not checked," in text and "NOT CHECKED: the runner could not read it. It does not stop the deployment" in text
    assert code == core.EXIT_BLOCKED and "Preflight: 1 things need you" in text          # the tenant settings; not the two checks
    code, text = slow_line.apply(ROLES, confirm=[SETTINGS])
    assert code == 0, text
    assert "unchecked pre.rights:" in text and "unchecked pre.region:" in text and "done     pre.rights" not in text
    assert "confirmed phase1.tenant_settings:" in text
    plan = slow_line.run("plan", ROLES)[1]
    # the VM exists now, so its size is no longer a question; the roles stay what they were: not read
    assert re.search(r"phase1\.tenant_settings\s+confirmed by you", plan) and " 1 confirmed by you, 1 not checked," in plan
    assert re.search(r"pre\.rights\s+NOT CHECKED", plan) and re.search(r"pre\.region\s+done", plan)
    status = slow_line.run("status")[1]
    assert status.count("(not looked at by the runner itself)") >= 3


def test_preflight_shows_no_plan_to_approve(bench):
    """The second issue ended preflight with `Plan a45d1f787e4f`, which no apply would have taken."""
    text = bench.run("preflight", "--up-to", "phase4")[1]
    assert not re.search(r"^Plan ", text, re.M) and not re.search(r"--approve [0-9a-f]{12}", text)
    assert "Preflight is not a plan. The plan to read and approve: python3 tools/deploy.py plan --up-to phase4" in text
    assert re.search(r"^Plan \w{12}$", bench.run("plan", "--up-to", "phase4")[1], re.M)


def test_your_roles_are_read_with_one_small_question_and_never_with_the_slow_one(bench):
    """`az role assignment list` fetches every role definition to print names; the fake fails the test if it is asked."""
    world = bench.world
    text = bench.run("preflight")[1]
    assert re.search(r"pre\.rights\s+done", text) and "roles on the subscription: Owner" in text and world.role_calls == 1
    world.my_roles = ["Contributor"]
    text = bench.run("preflight", "--recheck")[1]
    assert re.search(r"pre\.rights\s+done", text) and "You hold none of the roles that assign roles" in text
    world.my_roles = ["Reader", "Corp Custom Operator"]                 # a role the runner has no ID for
    text = bench.run("preflight", "--recheck")[1]
    assert re.search(r"pre\.rights\s+NOT CHECKED", text) and "1 role(s) on the subscription that the runner does not know by their ID, and Reader" in text
    world.my_roles = []
    code, text = bench.run("preflight", "--recheck")
    assert re.search(r"pre\.rights\s+BLOCKED", text) and "Your roles on the subscription are: none" in text
    # a role held above the resource group counts for the VM's identity, one below it does not
    assert steps.covers("/subscriptions/s", "/subscriptions/s/resourceGroups/rg") and steps.covers("/", "/subscriptions/s/resourceGroups/rg")
    assert steps.covers("/subscriptions/S/resourceGroups/RG", "/subscriptions/s/resourceGroups/rg")
    assert not steps.covers("/subscriptions/s/resourceGroups/rg/providers/x/y/z", "/subscriptions/s/resourceGroups/rg")
    assert not steps.covers("/subscriptions/s/resourceGroups/rg-other", "/subscriptions/s/resourceGroups/rg")


def test_a_question_that_stood_without_an_answer_is_not_asked_again_by_every_run(slow_line):
    """25 November 2026, 10:09: 180 s and 120 s of waiting in preflight, due again in every plan and twice in every apply."""
    slow_line.run("preflight")
    assert Unanswered.asked == ["roles", "sizes"]
    text = slow_line.run("plan", ROLES)[1]
    assert Unanswered.asked == ["roles", "sizes"] and text.count("--recheck asks again]") == 3      # and the providers
    assert re.search(r"pre\.region\s+NOT CHECKED", text)                # kept as what it was, not promoted
    assert slow_line.apply(ROLES, confirm=[SETTINGS])[0] == 0 and Unanswered.asked == ["roles", "sizes"]
    # asked again: on request, after twelve hours, and when what the answer depends on has changed
    slow_line.run("plan", ROLES, "--recheck")
    assert Unanswered.asked == ["roles", "sizes", "roles"]              # the VM exists: its size is no longer a question
    slow_line.wall[0] += 11 * 3600
    assert "[asked 11 h ago; --recheck asks again]" in slow_line.run("plan", ROLES)[1] and len(Unanswered.asked) == 3
    slow_line.wall[0] += 2 * 3600
    slow_line.run("plan", ROLES)
    assert Unanswered.asked == ["roles", "sizes", "roles", "roles"]


def test_a_kept_answer_is_for_the_settings_it_was_read_with_and_a_block_is_never_kept(bench):
    world = bench.world
    world.unregistered = {"Microsoft.IoTOperations"}
    assert "az provider register --namespace Microsoft.IoTOperations" in bench.run("preflight")[1]
    world.unregistered = set()
    assert re.search(r"pre\.providers\s+done\s+Resource providers registered\n\s+8 resource providers registered\n", bench.run("preflight")[1])
    asked = world.sku_calls
    bench.run("preflight")
    assert world.sku_calls == asked
    names.write_env(bench.root / "config" / "demo.env", {"VM_SIZE": "Standard_D8s_v7 Standard_D8s_v6"})
    text = bench.run("preflight")[1]
    assert world.sku_calls == asked + 1 and "VM size Standard_D8s_v7 is offered" in text
    # the sizes that were read reach the script from the checkpoint, without another question
    assert bench.apply(ROLES, confirm=[SETTINGS])[0] == 0 and world.sku_calls == asked + 1
    assert world.vm_env["VM_SIZE_OFFERED"] == "Standard_D8s_v7 Standard_D8s_v6" and "VM_SIZE_SKIP_CHECK" not in world.vm_env


def test_a_plan_made_while_an_apply_runs_reads_the_checkpoint_and_writes_nothing_to_it(deployed):
    folder = deployed.root / ".deploy" / deployed.cfg["DEPLOYMENT_SUFFIX"]
    (folder / "apply.lock").write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "started": "2026-11-25T16:00:00Z"}))
    before = (folder / "state.json").read_bytes()
    deployed.wall[0] += 60
    code, text = deployed.run("plan", ROLES, "--recheck")              # would clear and rewrite what was kept
    assert code == 0 and "An apply is running against this deployment" in text and "writes nothing to the checkpoint" in text
    assert (folder / "state.json").read_bytes() == before
    # a lock left by a process that has ended is nobody's
    (folder / "apply.lock").write_text(json.dumps({"pid": 2 ** 22 + 12345, "host": socket.gethostname(), "started": "x"}))
    text = deployed.run("plan", ROLES, "--recheck")[1]
    assert "An apply is running" not in text and (folder / "state.json").read_bytes() != before
