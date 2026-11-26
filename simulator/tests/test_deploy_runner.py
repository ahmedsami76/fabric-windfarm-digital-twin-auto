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
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from deploy_fakes import CONNECTION, KEY, FakeAz, FakeFabric, FakeKusto, FakeOneLake, FakeShell, World  # noqa: E402
from deployer import cli, core, deployments, names, steps  # noqa: E402
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
                "clock": lambda: self.now[0], "sleep": sleep, "wall": lambda: self.wall[0],
                "ask": self.answer if self.answers is not None else None}

    answers: list | None = None     # None: nobody at the terminal. A list: what a person types, question after question

    def answer(self, prompt: str) -> str:
        """A person at the terminal: the question is shown, the next scripted answer is typed."""
        assert self.answers, f"the runner asked a question the test did not expect: {prompt}"
        typed = self.answers.pop(0)
        if typed in (EOFError, KeyboardInterrupt):
            raise typed
        self.out.write(f"{prompt}{typed}\n")
        return typed

    profile = True      # a profile for the pretend subscription: the region of the edge, as a person saved it once

    def run(self, *argv, answers=None, as_typed=False) -> tuple[int, str]:
        """One command. Unless as_typed, an apply is given the current deployment by name, as the line a plan prints has
        it; and a run with nobody at the terminal finds the profile a person saved for the subscription."""
        self.out, self.answers = io.StringIO(), (list(answers) if answers is not None else None)
        argv = list(argv)
        if not as_typed and argv[0] == "apply" and "--deployment" not in argv and self.suffix:
            argv += ["--deployment", self.suffix]
        saved = self.root / ".deploy" / "profiles" / "sub-1111.json"
        if self.profile and answers is None and argv[0] in ("plan", "preflight") and not saved.exists():
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_text(json.dumps({"tenant_id": "tenant-aaaa", "subscription_id": "sub-1111", "values": {"LOCATION": "southcentralus"}}))
        code = cli.main(argv, out=self.out, root=self.root, adapters=self.adapters)
        assert not self.answers, f"answers the runner never asked for: {self.answers}"
        self.last, self.answers = self.out.getvalue(), None
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
    def suffix(self) -> str:
        """The deployment commands work on now."""
        return deployments.current(self.root)

    @property
    def env(self) -> Path:
        return deployments.env_of(self.root, self.suffix)

    @property
    def cfg(self) -> dict:
        return names.read_env(self.env)

    @property
    def state(self) -> dict:
        return json.loads((self.root / ".deploy" / self.suffix / "state.json").read_text())

    def everything_written(self) -> str:
        """All the runner left behind on disk and said: where a secret would show."""
        texts = [self.last]
        for path in list((self.root / ".deploy").rglob("*")):
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
    assert "now: " in text and "now: after " not in text      # what was found is shown where it says why; "after p1.x" says nothing
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
    assert "provisioned   yes: " in text and "demo-ready    yes: Eventhouse, measured now" in text and "Lakehouse tables populated" in text
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
                                         "itemId": world.find(ws["id"], "KQLDatabase", "WindFarmEH")["id"], "tableName": "RawEvents",
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
def test_a_settings_file_of_a_deployment_made_by_hand_is_left_alone_and_not_used(bench):
    by_hand = Path(bench.root, "config", "demo.env")
    shutil.copy(bench.root / "config" / "demo.env.example", by_hand)
    before = by_hand.read_bytes()
    code, text = bench.run("plan")
    assert code == 0 and by_hand.read_bytes() == before and "Moved config/demo.env" not in text
    assert bench.cfg["RESOURCE_GROUP"] == f"rg-windfarm-edge-{bench.suffix}" and bench.world.writes == []


def test_a_resource_group_or_a_workspace_the_runner_did_not_make_is_never_used(bench):
    bench.plan(ROLES)
    cfg, world = bench.cfg, bench.world
    world.groups[cfg["RESOURCE_GROUP"]] = {"id": "/subscriptions/sub-1111/resourceGroups/x", "name": cfg["RESOURCE_GROUP"], "location": "eastus", "tags": {}}
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "this deployment did not make it" in text and "plan --new" in text and world.writes == []
    del world.groups[cfg["RESOURCE_GROUP"]]
    world.workspaces.append({"id": "ws-someone", "displayName": cfg["FABRIC_WORKSPACE_NAME"], "description": "Sales", "capacityId": "cap-0001"})
    code, text = bench.apply(ROLES)
    assert code == core.EXIT_BLOCKED and "A workspace named" in text
    assert not any(w.startswith("POST") for w in world.writes) and world.items == {}


def test_a_deployment_is_pinned_to_its_subscription_whatever_the_cli_is_on(deployed):
    """Pin every call to the approved tenant and subscription; do not depend on the CLI's active subscription."""
    world, mine = deployed.world, dict(deployed.world.account)
    writes = list(world.writes)
    # another terminal ran `az account set`: the deployment's subscription is still signed in, and every call names it
    world.account, world.others, world.named = dict(mine, id="sub-2222", name="Production"), {"sub-1111": mine}, set()
    code, text = deployed.run("plan", ROLES)
    assert code == 0 and "subscription    Demo subscription  (sub-1111)" in text and world.named == {"sub-1111"}
    assert re.search(r"p1\.resource_group\s+done", text) and world.writes == writes
    # an option that names another subscription for this deployment is refused, not followed
    code, text = deployed.run("plan", ROLES, "--subscription", "sub-2222")
    assert code == core.EXIT_REFUSED and f"Deployment {deployed.suffix} is in subscription sub-1111, and --subscription names sub-2222" in text
    assert "plan --new --subscription sub-2222" in text
    # the sign-in no longer reaches the deployment's subscription: refused, with what to do; nothing falls back to sub-2222
    world.others = {}
    for mode in (("plan", ROLES), ("apply", "--approve", "x", ROLES), ("status",)):
        code, text = deployed.run(*mode)
        assert code == core.EXIT_REFUSED and f"The Azure CLI cannot use subscription sub-1111, which deployment {deployed.suffix} is in" in text
        assert "az login --tenant tenant-aaaa" in text and "plan --new" in text
    # the same subscription ID answering from another tenant
    world.account = dict(mine, tenantId="tenant-bbbb")
    code, text = deployed.run("apply", "--approve", "x", ROLES)
    assert code == core.EXIT_REFUSED and "began in tenant tenant-aaaa" in text and world.writes == writes


def test_things_that_are_not_the_demos_stop_the_runner_until_they_are_named(deployed):
    world = deployed.world
    world.resources.append({"id": "/subscriptions/sub-1111/rg/providers/Microsoft.Sql/servers/payroll", "type": "Microsoft.Sql/servers"})
    stranger = world.add_item(world.workspaces[0]["id"], "Notebook", "Quarterly numbers")
    code, text = deployed.run("plan", ROLES)
    assert "Microsoft.Sql/servers" in text and "Notebook Quarterly numbers" in text and text.count("BLOCKED") == 2
    digest = re.search(r"^Plan (\w+)$", text, re.M)[1]
    code, text = deployed.run("apply", "--approve", digest, ROLES)
    assert code == core.EXIT_BLOCKED
    held = deployed.state["steps"]["p1.resource_group"]         # a finding about a complete step, unlike a question without an answer
    assert held["status"] == "blocked" and "unseen" not in held and "next: p1.resource_group" in text
    code, text = deployed.run("apply", "--approve", digest, ROLES, "--acknowledge", world.resources[-1]["id"], "--acknowledge", stranger["id"])
    assert code == 0, text


def test_a_new_deployment_goes_with_a_plan_and_names_one_that_exists_or_is_refused(deployed):
    assert "--new goes with preflight or plan" in deployed.run("apply", "--approve", "x", ROLES, "--new", as_typed=True)[1]
    assert "Give one of them" in deployed.run("plan", "--new", "--deployment", deployed.suffix)[1]
    code, text = deployed.run("status", "--deployment", "zzz")
    assert code == core.EXIT_REFUSED and "This folder has no deployment zzz" in text and f"{deployed.suffix}: subscription sub-1111" in text


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


def test_an_operation_whose_address_fabric_names_on_a_regional_host_is_asked_about_on_the_api(bench):
    # 26 November 2026, the first eventstream the runner made: "The Fabric API pointed to another address
    # (wabi-us-central-b-primary-redirect.analysis.windows.net). Stopped." The request had been accepted.
    bench.world.slow, bench.world.operations_elsewhere = {"eventstream"}, True
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_RUNNING and "pointed to another address" not in text, text[-600:]
    kept = bench.state["pending"]["p1.eventstream"]["eventstream"]["location"]
    assert kept.startswith("https://api.fabric.microsoft.com/v1/operations/")           # what is kept is where the token may go
    # the checkpoint of that day holds the regional address as Fabric wrote it: the next apply asks the API all the same
    state_file = bench.root / ".deploy" / bench.suffix / "state.json"
    state = json.loads(state_file.read_text())
    state["pending"]["p1.eventstream"]["eventstream"]["location"] = kept.replace("https://api.fabric.microsoft.com", "https://wabi-us-central-b-primary-redirect.analysis.windows.net")
    state_file.write_text(json.dumps(state))
    next(iter(bench.world.operations.values()))["finish"] = True
    code, text = bench.apply(ROLES)
    assert code == 0 and bench.world.writes.count("POST eventstreams es-windfarm-edge") == 1, text[-600:]
    # and a request the runner lost track of, whose result is there all the same, is not listed as under way for ever
    state = json.loads(state_file.read_text())
    state["pending"]["p1.eventstream"] = {"eventstream": {"location": "https://wabi-x.analysis.windows.net/v1/operations/gone"}}
    state["steps"]["p1.eventstream"]["status"] = "failed"
    state_file.write_text(json.dumps(state))
    code, text = bench.apply(ROLES)
    assert code == 0 and not bench.state["pending"] and bench.world.writes.count("POST eventstreams es-windfarm-edge") == 1
    # any other address on another host is still refused, and the token goes nowhere
    from operations_agent import FabricError, api_address
    api = "https://api.fabric.microsoft.com/v1"
    assert api_address(api, "https://x.analysis.windows.net/v1/operations/abc/result") == api + "/operations/abc/result"
    assert api_address(api, "https://x.analysis.windows.net/v1/workspaces/w/items/i/jobs/instances/j") == api + "/workspaces/w/items/i/jobs/instances/j"
    for elsewhere in ("https://example.invalid/v1/jobs/1", "https://example.invalid/operations/abc", "https://example.invalid/v1/workspaces/w/items"):
        with pytest.raises(FabricError, match="pointed to another address"):
            api_address(api, elsewhere)


def test_a_run_started_by_an_apply_that_died_is_waited_for_not_repeated(deployed):
    """The request went out, the computer went down before the checkpoint was written."""
    world, ws = deployed.world, deployed.world.workspaces[0]["id"]
    state_file = deployed.root / ".deploy" / deployed.cfg["DEPLOYMENT_SUFFIX"] / "state.json"
    state = json.loads(state_file.read_text())
    del state["steps"]["p1.history"]
    state_file.write_text(json.dumps(state))
    notebook = world.find(ws, "Notebook", "02_generate_history")["id"]
    world.jobs[notebook].append({"id": "job-orphan", "status": "InProgress", "polls": 0, "notebook": "02_generate_history"})
    # A run in progress that the checkpoint knows nothing of is not taken for this step's, and no second one is started
    code, text = deployed.apply(ROLES)
    assert code == core.EXIT_BLOCKED and "under way in Fabric that this deployment has no record of: job-orphan (InProgress" in text
    assert "--adopt-job p1.history=job-orphan" in text and world.writes.count("POST job 02_generate_history") == 1
    # the person says that it is this step's run: it is waited for, and its result taken
    code, text = deployed.apply(ROLES, "--adopt-job", "p1.history=job-orphan")
    assert code == 0 and "taking run job-orphan of 02_generate_history for this step, as you said" in text
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
    assert code == core.EXIT_REFUSED and "What differs: steps.p1.kql_schema.fabric/kql/01-tables.kql: was " in text
    assert "nothing of this command was kept" in text and bench.world.writes == []


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


def test_an_eventstream_the_runner_made_with_the_eventhouse_as_its_destination_is_written_again_with_the_database(bench):
    # 26 November 2026: made word for word from Microsoft's article, with the Eventhouse's ID in the destination. Fabric:
    # "Artifact with id '...' is not a database artifact. It is of type 'KustoEventHouse'", destination Failed.
    bench.world.slow = {"eventstream"}
    assert bench.apply(ROLES, confirm=[SETTINGS])[0] == core.EXIT_RUNNING       # up to the eventstream, which is not made yet
    world = bench.world; ws = world.workspaces[0]["id"]
    house, database = world.find(ws, "Eventhouse", "WindFarmEH"), world.find(ws, "KQLDatabase", "WindFarmEH")
    world.operations.clear(); world.slow = set()
    wrong = {"sources": [{"name": "aio-edge", "type": "CustomEndpoint", "properties": {}}],
             "destinations": [{"name": "eventhouse-raw", "type": "Eventhouse", "inputNodes": [{"name": "es-windfarm-edge-stream"}],
                               "properties": {"dataIngestionMode": "DirectIngestion", "workspaceId": ws, "itemId": house["id"],
                                              "tableName": "RawEvents", "connectionName": "es-windfarm-raw-x", "mappingRuleName": "RawEvents_mapping"}}],
             "streams": [{"name": "es-windfarm-edge-stream", "type": "DefaultStream", "properties": {}, "inputNodes": [{"name": "aio-edge"}]}],
             "operators": [], "compatibilityLevel": "1.1"}
    stream = world.add_item(ws, "Eventstream", "es-windfarm-edge")
    world.topology[stream["id"]] = FakeFabric(world)._topology(ws, wrong)
    source = world.topology[stream["id"]]["sources"][0]["id"]
    state_file = bench.root / ".deploy" / bench.suffix / "state.json"
    state = json.loads(state_file.read_text()); state["pending"] = {}; state_file.write_text(json.dumps(state))
    code, text = bench.run("plan", ROLES)
    assert re.search(r"p1\.eventstream\s+will run", text) and "definition will be written again" in text and "(destination Failed)" not in text
    code, text = bench.apply(ROLES)
    assert code == 0, text[-900:]
    assert "writing the eventstream's definition again, with the KQL database as the destination" in text
    assert world.definition["destinations"][0]["properties"]["itemId"] == database["id"]
    assert len([w for w in world.writes if w.startswith("POST eventstreams updateDefinition")]) == 1
    assert world.writes.count("POST eventstreams es-windfarm-edge") == 1                                   # no second eventstream
    assert len([i for i in world.items[ws] if i["type"] == "Eventstream"]) == 1
    assert world.topology[stream["id"]]["sources"][0]["id"] == source and world.topology[stream["id"]]["destinations"][0]["status"] == "Running"
    assert bench.apply(ROLES)[0] == 0 and len([w for w in world.writes if "updateDefinition" in w]) == 1     # and not again


def test_a_failed_destination_is_not_called_done_and_says_what_fabric_says(bench):
    # 26 November 2026, the plan after the first eventstream: "p1.eventstream  done  ... (destination Failed)".
    bench.world.destination_status = "Failed"
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "blocked  p1.eventstream" in text and "state Failed" in text
    assert "Fabric gives no reason in the topology" in text and all(word in text for word in WIZARD_WORDS)
    for topology in bench.world.topology.values():
        topology["destinations"][0]["error"] = {"errorCode": "DataConnectionFailed", "errorMessage": "the table was not found"}
    code, text = bench.run("plan", ROLES)
    assert re.search(r"p1\.eventstream\s+BLOCKED", text) and "Fabric says: DataConnectionFailed the table was not found" in text
    assert not [w for w in bench.world.writes if "updateDefinition" in w]        # the right item is named: nothing to write again
    assert "(destination Failed)" not in text


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
    assert "SQL probe with the operator's token: 7548 rows from 12 turbines in the last 60 minutes, the newest 2.0 min old" in text
    assert "as you and not as the app" in text
    assert "optional p4.eventhouse_principal" in text and "create-principal" not in " ".join(world.shell_calls)
    config = (deployed.root / ".deploy" / deployed.suffix / "app/windfarm-twin/packages/functions/src/config.ts").read_text()
    assert deployed.cfg["FABRIC_WORKSPACE_NAME"] in config
    assert world.find(ws, "FabricApp", "WindFarmTwin")
    # hourly schedule for notebook 05, made once
    assert [s[0]["configuration"]["type"] for s in world.schedules.values()] == ["Daily", "Cron"]
    # Provisioned is not demo-ready. An item of the operations agent and an app item prove neither Teams nor the twin
    assert "provisioned   yes" in text and "demo-ready    no" in text
    assert "an item exists, which is not proof that it is configured, running or delivering to Teams" in text
    assert "the deployed app's own connection check has not been given" in text and "SQL probe with the operator's token passed (not the app's identity)" in text
    build = re.search(r"--app-check ([0-9a-f]{12}),lakehouse,SECONDS", text)[1]
    # what the app's own check shows, read by a person: another build, or data that is too old, is no pass
    code, text = later(deployed, "--app-check", "000000000000,lakehouse,60", "--confirm", "p3.agent_message")
    assert "demo-ready    no" in text and f"named build 000000000000, and the repository is at {build}" in text
    code, text = later(deployed, "--app-check", f"{build},lakehouse,4000")
    assert "demo-ready    no" in text and "the newest reading was 4000 s old, more than 900 s" in text
    code, text = later(deployed, "--app-check", f"{build},lakehouse,120")
    assert code == 0 and "demo-ready    yes" in text and f"the twin's own check: build {build}, lakehouse route, newest reading 120 s old" in text
    assert "a Teams message seen, confirmed by sami@contoso.example" in text
    assert "--app-check takes BUILD,ROUTE,SECONDS" in later(deployed, "--app-check", "looks fine")[1]
    # status says the same from the checkpoint, and a stopped edge takes the word back
    world.vm["powerState"] = "VM deallocated"
    text = deployed.run("status", "--up-to", "phase4")[1]
    assert "provisioned   yes" in text and "demo-ready    no" in text and "no fresh telemetry now" in text
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
    assert "cap-0001" in text and "cap-0002" in text and "only when exactly one that can hold the demo is in sight" in text
    assert "python3 tools/deploy.py plan --capacity ID" in text and "--new-capacity --capacity-region REGION --approve-capacity-creation" in text
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

    def request(method, url, token, body=None, headers=None, timeout=0, read=False):
        calls.append((method, url, body, read))
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
    assert "Eventhouse, measured now: 688 readings from 12 turbines in the last 5 minutes, the newest 38 s old" in text
    assert "provisioned   yes" in text and "demo-ready    yes" in text
    # A stopped edge: everything is still provisioned and the gate stays passed, and the demo cannot be shown now
    deployed.world.vm["powerState"] = "VM deallocated"
    text = deployed.run("status")[1]
    assert "provisioned   yes" in text and "demo-ready    no" in text and "no fresh telemetry now: 0 readings from 0 turbines" in text
    assert "what holds: Lakehouse tables populated" in text and deployed.world.writes == writes
    # Fresh telemetry does not make a deployment ready for more than has been built: asked about Phase 2, of which nothing is there
    deployed.world.vm["powerState"] = "VM running"
    text = deployed.run("status", "--up-to", "phase2")[1]
    assert "provisioned   no: 25 of 33 steps complete; next: p2.prepared_views" in text
    assert re.search(r"demo-ready    no\n\s+- not everything is provisioned", text) and "demo-ready    yes" not in text
    assert "what holds: Eventhouse, measured now" in text and deployed.world.writes == writes


def test_a_deployment_that_has_its_resource_group_is_not_moved_by_an_option(deployed):
    region, writes = deployed.cfg["LOCATION"], list(deployed.world.writes)
    other = "westus3" if region != "westus3" else "eastus2"
    code, text = deployed.run("plan", ROLES, "--edge-region", other)
    assert code == core.EXIT_REFUSED and f"this deployment made its resource group in {region}" in text
    assert "For another one: python3 tools/deploy.py plan --new" in text
    assert deployed.cfg["LOCATION"] == region and deployed.world.writes == writes
    # the region it has is no change, and is taken
    assert deployed.run("plan", ROLES, "--edge-region", region)[0] == 0 and deployed.cfg["LOCATION"] == region


def test_on_a_line_that_large_answers_do_not_cross_the_iot_operations_script_is_handed_over_and_not_started(bench):
    # 26 November 2026: from a workstation that got 5 kB a second from Azure, `az iot ops init` stood for ninety minutes,
    # twice. The script finished from Azure Cloud Shell with the deployment's settings, and the apply went on from there.
    bench.world.slow_line = True
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "blocked  p1.iot_operations" in text, text[-900:]
    assert "did not arrive on this computer within 45 seconds" in text and "Azure Cloud Shell" in text
    assert 'ENV_FILE="$HOME/demo.env" bash infra/04-deploy-iot-operations.sh' in text and f".deploy/{bench.suffix}/demo.env" in text
    assert not [c for c in bench.world.shell_calls if "04-deploy-iot-operations" in c]        # the script was not started
    # the operator ran it elsewhere: the instance is there, the next apply asks for no large answer and goes on to the end
    bench.world.instance = {"id": "/subscriptions/sub-1111/x/instances/aio", "name": "aio", "properties": {"provisioningState": "Succeeded"}}
    asked = bench.world.large_answers
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == 0 and "done     p1.iot_operations" in text and bench.world.large_answers == asked
    # and where the line is good, the answer is asked for once, said, and the script runs
    other = Bench(bench.root.parent / "fast")
    code, text = other.apply(ROLES, confirm=[SETTINGS])
    assert code == 0 and "a large answer from Azure arrived in" in text and other.world.large_answers == 1


def test_a_confirmation_keeps_the_time_it_was_first_given(deployed):
    first = deployed.state["confirmed"][SETTINGS]
    code, _ = deployed.apply(ROLES, confirm=[SETTINGS])
    assert code == 0 and deployed.state["confirmed"][SETTINGS] == first


def test_role_assignments_that_azure_lists_a_little_later_are_waited_for_and_not_made_twice(bench):
    # The first apply on a tenant, 25 November 2026: "the step ran without an error, and its result is not there.
    # 0 of 2 role assignments are there", seconds after `az role assignment create` had returned twice.
    bench.world.role_lag = 3
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == 0 and "FAILED" not in text, text[-800:]
    assert "p1.vm_identity_roles: the VM's identity holds Arc onboarding and Reader" in text
    assert len([w for w in bench.world.writes if w.startswith("az role assignment create")]) == 2
    # a list that stays empty for longer than the step waits is still a failure, and the next apply makes nothing twice
    other = Bench(bench.root.parent / "slow"); other.world.role_lag = 10_000
    code, text = other.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_FAILED and "0 of 2 role assignments are there" in text
    other.world.role_reads_empty = 0
    code, text = other.apply(ROLES, confirm=[SETTINGS])
    assert code == 0 and len([w for w in other.world.writes if w.startswith("az role assignment create")]) == 2


def test_a_setting_changed_by_hand_in_a_deployment_comes_before_the_profile(bench):
    # Found on 25 November while a first deployment waited for its apply: the shutdown hour, changed in the deployment's
    # settings, was put back from the profile by the next plan, without a word, because the profile had been saved from
    # this very deployment and "from the profile" had never been recorded for it.
    code, text = bench.run("plan", ROLES, "--edge-region", "southcentralus", "--vm-size", "Standard_D8s_v7 Standard_D8s_v6", "--save-profile", answers=[])
    assert code == 0, text
    first = re.search(r"Plan (\w+)", text).group(1)
    env = bench.env
    env.write_text(env.read_text().replace('VM_AUTO_SHUTDOWN_UTC="0800"', 'VM_AUTO_SHUTDOWN_UTC="1200"'))
    code, text = bench.run("plan", ROLES, answers=[])
    assert code == 0 and bench.cfg["VM_AUTO_SHUTDOWN_UTC"] == "1200", text[-600:]
    assert re.search(r"Plan (\w+)", text).group(1) != first          # and the change is one the approval sees
    code, text = bench.run("apply", "--approve", first, ROLES)
    assert code == core.EXIT_REFUSED and 'settings.VM_AUTO_SHUTDOWN_UTC: was "0800", is now "1200"' in text, text[-500:]
    # the next deployment of the subscription still starts from the profile, where the hour is the one that was saved
    code, text = bench.run("plan", ROLES, "--new", answers=[])
    assert code == 0 and bench.cfg["VM_AUTO_SHUTDOWN_UTC"] == "0800" and bench.cfg["VM_SIZE"] == "Standard_D8s_v7 Standard_D8s_v6"


def test_no_hint_shows_an_apply_line_that_apply_would_refuse(bench):
    # Seen on a tenant on 25 November: the hint of a step of the operator's read "apply --approve <plan> --confirm ...",
    # without the deployment that apply insists on. The one line to copy is the one the plan ends with.
    text = bench.run("plan", ROLES, "--up-to", "phase4", PHASE5A)[1]
    lines = [row for row in text.splitlines() if "tools/deploy.py apply" in row]
    assert lines and all("--deployment " in row for row in lines), lines
    assert "the apply line the plan ends with, and --confirm phase1.tenant_settings added to it" in text


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


def test_a_new_deployment_gets_every_generated_name_anew_and_together(bench):
    bench.plan()
    first = bench.cfg
    code, text = bench.run("plan", "--new")
    second = bench.cfg
    assert code == 0 and second["DEPLOYMENT_SUFFIX"] != first["DEPLOYMENT_SUFFIX"]
    assert second["RESOURCE_GROUP"].endswith(second["DEPLOYMENT_SUFFIX"]) and second["STORAGE_ACCOUNT_NAME"] == "sawindfarm" + second["DEPLOYMENT_SUFFIX"]
    assert second["SUBSCRIPTION_ID"] == first["SUBSCRIPTION_ID"] and bench.world.writes == []
    # a name edited by hand is refused: the names of a deployment go together
    names.write_env(bench.env, {"VM_NAME": "my-own-vm"})
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
    fabric = RunnerFabric(OneAz(), clock=lambda: now[0], api="https://127.0.0.1:9/v1", sleep=lambda seconds: None)
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
    names.write_env(bench.env, {"FABRIC_CAPACITY_ID": value})


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
    assert bench.cfg["FABRIC_CAPACITY_ID"] == "cap-0001" and "capacity existing cap-0001 (the only capacity in sight that can hold the demo)" in text
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
    assert Unanswered.asked == ["roles", "sizes"] and text.count("--recheck asks again]") == 4      # and the providers and the quota
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
    names.write_env(bench.env, {"VM_SIZE": "Standard_D8s_v7 Standard_D8s_v6"})
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


# ------------------------------------------------------------------------------------------ after the run of 25 November, 15:40
def test_a_gate_the_runner_measures_is_not_shown_as_the_operators_step(bench):
    """A first plan showed `p1.gate_telemetry  YOUR STEP ... > See the plan line above.`: nothing for a person to do, and counted as theirs."""
    text = bench.run("plan", ROLES)[1]
    assert re.search(r"p1\.gate_telemetry\s+will be measured\s+GATE: fresh telemetry in the Eventhouse", text)
    assert "See the plan line above" not in text and not re.search(r"p1\.gate_telemetry\s+YOUR STEP", text)
    assert " 1 for you," in text                                        # the tenant settings, and nothing else
    # when it is measured and nothing arrives, the block still says where to look
    bench.world.ingestion_works = False
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_BLOCKED and "blocked  p1.gate_telemetry" in text and "Find where the events stop" in text


def test_phase_3_sends_an_unusable_capacity_back_to_the_choice_not_to_a_move(bench):
    """The run of 15:40 told a person with no workspace yet to move the workspace to another capacity."""
    as_on_the_tenant(bench.world)
    bench.plan()
    set_capacity(bench, PPU["id"])
    text = bench.run("preflight", "--up-to", "phase3")[1]
    after = text.split("p3.capacity")[2]
    assert "the step pre.capacity lists them" in after.split("phase3.tenant_settings")[0] and "Moving a workspace" not in after


# ------------------------------------------------------------------------------------------ the questions of plan
# 25 November 2026, 15:51: "instead of running sed command ... ask: would you like to create a new fabric capacity or use
# one of the existing ones ... enumerate all the existing capacities, and ask the user to pick one - next workspace - do
# the same - etc". Answers are what a person types; "" is Enter.
F32 = {"id": "d21d9da9-0000-0000-0000-0000000000f3", "displayName": "fabcentralussm01", "sku": "F32", "region": "Central US",
       "state": "Active"}
KEEP_REGION, NEW_WORKSPACE = "", ""
APPROVE_CAPACITY = "--approve-capacity-creation"


def his_tenant(world) -> None:
    """15:40: an F32 and a Premium Per User capacity listed; the workspace of the deployment by hand on the F32, with items."""
    world.capacities = [dict(F32), dict(PPU)]
    world.workspaces = [{"id": "ws-by-hand", "displayName": "WindFarmDigitalTwin", "description": "", "capacityId": F32["id"],
                         "type": "Workspace"}]
    world.items["ws-by-hand"] = [{"id": "item-1", "type": "Eventhouse", "displayName": "WindFarmEH"}]


def test_in_a_terminal_plan_asks_which_capacity_and_takes_the_one_picked(bench):
    his_tenant(bench.world)
    bench.run("preflight")                                   # nobody at the terminal: nothing is asked, as before
    set_capacity(bench, PPU["id"])                           # what the second issue left in his settings
    code, text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "n", "", NEW_WORKSPACE])
    assert code == 0 and bench.cfg["FABRIC_CAPACITY_ID"] == F32["id"] and bench.cfg["FABRIC_CAPACITY_CREATE_SKU"] == ""
    assert "The settings name a capacity that cannot be used: Premium Per User - Reserved (PP3, Central US) cannot hold the demo" in text
    assert "Create a new Fabric capacity for this demo (F16)? [y/N] n" in text
    assert f"    1. fabcentralussm01 (F32, Central US)   {F32['id']}" in text
    assert "    -  Premium Per User - Reserved (PP3, Central US): cannot hold the demo" in text
    assert "Chosen: edge in southcentralus; capacity fabcentralussm01 (F32, Central US); workspace " in text
    assert re.search(r"pre\.capacity\s+done", text) and f"capacity        fabcentralussm01 (F32, Central US)  {F32['id']}" in text
    made = bench.state["choices"]
    assert made["capacity"]["answer"] == f"existing {F32['id']}" and made["capacity"]["by"] == "sami@contoso.example"
    assert set(made) == {"region", "capacity", "workspace"}
    digest = re.search(r"^Plan (\w+)$", text, re.M)[1]
    assert f"  python3 tools/deploy.py apply --deployment {bench.suffix} --approve {digest} --approve-role-changes\n" in text
    assert "Add --confirm phase1.tenant_settings when that step of yours is done." in text
    # asked once: the next plan asks nothing and is the same plan
    assert f"Plan {digest}" in bench.run("plan", ROLES, answers=[])[1]
    # an answer that no longer holds is asked for again, and only that one
    set_capacity(bench, PPU["id"])
    asked = bench.run("plan", ROLES, answers=["n", "1"])[1].split("Looking at")[0]
    assert bench.cfg["FABRIC_CAPACITY_ID"] == F32["id"] and "Azure region of the edge" not in asked and "Fabric workspace" not in asked
    assert bench.world.writes == []


def test_a_new_capacity_is_made_only_when_chosen_and_approved_and_only_once(bench):
    world = bench.world
    his_tenant(world)
    code, text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "", NEW_WORKSPACE])
    suffix = bench.cfg["DEPLOYMENT_SUFFIX"]
    name = f"fabwindfarm{suffix}"
    assert (bench.cfg["FABRIC_CAPACITY_CREATE_SKU"], bench.cfg["FABRIC_CAPACITY_NAME"], bench.cfg["FABRIC_CAPACITY_REGION"],
            bench.cfg["FABRIC_CAPACITY_ID"]) == ("F16", name, "centralus", "")
    assert f"A new capacity: {name}, F16, in the demo's resource group rg-windfarm-edge-{suffix}, with you as its administrator." in text
    assert "It costs money for as long as it runs. The runner makes it and never pauses, resizes or deletes it" in text
    assert "lists no Operations agent for a capacity there, so the runner proposes Central US" in text
    assert f"capacity        {name} (F16, Central US), to be made in rg-windfarm-edge-{suffix}: it costs money while it runs" in text
    assert re.search(r"p1\.capacity\s+will run", text) and "9 resource providers registered" in text
    digest = re.search(r"^Plan (\w+)$", text, re.M)[1]
    assert f"apply --deployment {suffix} --approve {digest} --approve-role-changes {APPROVE_CAPACITY}\n" in text       # the yes approved it for this plan
    # Phase 3 reads the capacity that is to be made as what it will be: a paid one
    assert re.search(r"p3\.capacity\s+done\s+A paid capacity for the agents\n\s+capacity SKU F16, a paid capacity",
                     bench.run("plan", ROLES, "--up-to", "phase3", answers=[])[1])
    # a later plan without the option: the answer is kept, the approval is not
    code, later = bench.run("plan", ROLES, answers=[])
    assert re.search(r"p1\.capacity\s+needs approval", later) and "Add --approve-capacity-creation to plan and apply" in later
    unapproved = re.search(r"^Plan (\w+)$", later, re.M)[1]
    code, text = bench.run("apply", "--approve", unapproved, ROLES, "--confirm", SETTINGS)
    assert code == core.EXIT_BLOCKED and "blocked  p1.capacity" in text and world.arm_capacities == {} and world.vm is None
    # approved: one capacity, in the demo's resource group, marked as this deployment's, with the operator as administrator
    code, text = bench.run("apply", "--approve", digest, ROLES, APPROVE_CAPACITY)
    assert code == 0, text
    made = world.arm_capacities[name]
    assert made["location"] == "centralus" and made["sku"] == {"name": "F16", "tier": "Fabric"}
    assert made["tags"]["windfarm-demo-deployment"] == suffix and f"/resourceGroups/rg-windfarm-edge-{suffix}/" in made["id"]
    listed = next(entry for entry in world.capacities if entry["displayName"] == name)
    assert bench.cfg["FABRIC_CAPACITY_ID"] == listed["id"]
    workspace = next(entry for entry in world.workspaces if entry["displayName"] == bench.cfg["FABRIC_WORKSPACE_NAME"])
    assert workspace["capacityId"] == listed["id"]
    assert [row for row in world.writes if "Microsoft.Fabric/capacities" in row] == [f"az rest PUT Microsoft.Fabric/capacities/{name} F16 centralus"]
    assert world.writes.index(f"az rest PUT Microsoft.Fabric/capacities/{name} F16 centralus") == 1      # before the VM: a refusal costs nothing
    # the same approval still holds now that the capacity exists, and a second apply makes nothing
    writes = list(world.writes)
    code, text = bench.run("apply", "--approve", digest, ROLES, APPROVE_CAPACITY)
    assert code == 0 and world.writes == writes and f"capacity        {name} (F16, Central US), made by this deployment  {listed['id']}" in text
    # the capacity is paused later: said, and not resumed
    made["properties"]["state"] = listed["state"] = "Paused"
    text = bench.run("plan", ROLES, APPROVE_CAPACITY)[1]
    assert re.search(r"p1\.capacity\s+BLOCKED", text) and "The runner does not resume a capacity" in text and world.writes == writes


def test_what_stands_in_the_way_of_a_new_capacity_is_said_before_anything_is_made(bench):
    world = bench.world
    his_tenant(world)
    world.unregistered = {"Microsoft.Fabric"}
    text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "", NEW_WORKSPACE])[1]
    assert re.search(r"pre\.providers\s+BLOCKED", text) and "az provider register --namespace Microsoft.Fabric" in text
    world.unregistered = set()
    world.taken_capacity_names = {bench.cfg["FABRIC_CAPACITY_NAME"]}
    text = bench.run("plan", ROLES)[1]
    assert re.search(r"pre\.capacity\s+BLOCKED", text) and "cannot be used (AlreadyExists)" in text and "plan --new" in text
    world.taken_capacity_names = set()
    world.fabric_offers["F16"] = ["West Europe", "East US 2"]
    text = bench.run("plan", ROLES)[1]
    assert re.search(r"pre\.capacity\s+BLOCKED", text) and "plan --ask" in text
    assert "Azure's list of SKUs does not name Central US for an F16 in this subscription. It names: East US 2, West Europe." in text
    world.fabric_offers["F16"] = ["Central US", "South Central US"]
    world.account["user"]["name"] = "sami_contoso.com#EXT#@other.onmicrosoft.com"
    assert "a guest cannot be the administrator of a capacity" in bench.run("plan", ROLES)[1]
    world.account["user"]["name"] = "sami@contoso.example"
    # a region that lacks what a later phase uses: a caution for Phase 1, a block once that phase is asked for
    names.write_env(bench.env, {"FABRIC_CAPACITY_REGION": "southcentralus"})
    text = bench.run("plan", ROLES)[1]
    assert re.search(r"pre\.capacity\s+done", text) and "For later phases: no Operations agent in that region" in text
    text = bench.run("plan", ROLES, "--up-to", "phase3")[1]
    assert re.search(r"pre\.capacity\s+BLOCKED", text) and "lists no Operations agent for a capacity in South Central US" in text
    # the question cannot be asked: not checked, never done
    names.write_env(bench.env, {"FABRIC_CAPACITY_REGION": "centralus"})
    real = bench.adapters

    class NoFabricProvider(FakeAz):
        def maybe(self, *args, timeout=0):
            if args[:1] == ("rest",) and "Microsoft.Fabric/skus" in " ".join(args):
                raise CloudError("az rest --method get did not answer within 60 seconds.")
            return super().maybe(*args, timeout=timeout)
    bench.adapters = lambda redact: dict(real(redact), az=NoFabricProvider(world, redact))
    text = bench.run("plan", ROLES)[1]
    assert re.search(r"pre\.capacity\s+NOT CHECKED", text) and "could not be read" in text
    assert world.writes == [] and world.arm_capacities == {}


def new_capacity_plan(bench) -> str:
    his_tenant(bench.world)
    text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "", NEW_WORKSPACE])[1]
    return re.search(r"^Plan (\w+)$", text, re.M)[1]


def test_no_quota_and_a_capacity_that_is_not_ours_stop_the_step_before_the_vm(bench):
    world = bench.world
    digest = new_capacity_plan(bench)
    world.fabric_quota = False
    code, text = bench.run("apply", "--approve", digest, ROLES, APPROVE_CAPACITY, "--confirm", SETTINGS)
    assert code == core.EXIT_BLOCKED and "blocked  p1.capacity" in text and "Quotas, Microsoft Fabric, New Quota Request" in text
    assert world.vm is None and world.arm_capacities == {}
    # somebody made a capacity of that name in the group meanwhile: not taken over
    name, group = bench.cfg["FABRIC_CAPACITY_NAME"], bench.cfg["RESOURCE_GROUP"]
    world.fabric_quota = True
    world.arm_capacities[name] = {"id": f"{world.groups[group]['id']}/providers/Microsoft.Fabric/capacities/{name}", "name": name,
                                  "tags": {}, "properties": {"provisioningState": "Succeeded", "state": "Active"}}
    code, text = bench.run("apply", "--approve", digest, ROLES, APPROVE_CAPACITY)
    assert code == core.EXIT_BLOCKED and "this deployment did not make it" in text and world.vm is None


def test_a_capacity_azure_is_still_making_is_waited_for_and_not_made_twice(bench):
    world = bench.world
    digest = new_capacity_plan(bench)
    world.capacity_state = "Provisioning"
    code, text = bench.run("apply", "--approve", digest, ROLES, APPROVE_CAPACITY, "--confirm", SETTINGS)
    assert code == core.EXIT_RUNNING and "Azure is still making the capacity" in text and "Run the same apply again later" in text
    assert bench.now[0] >= 900 and world.vm is None
    made = world.arm_capacities[bench.cfg["FABRIC_CAPACITY_NAME"]]
    # still not ready: the second apply waits for the same capacity; the stand-in fails the test on a second request
    assert bench.run("apply", "--approve", digest, ROLES, APPROVE_CAPACITY)[0] == core.EXIT_RUNNING
    made["properties"]["state"] = "Active"
    code, text = bench.run("apply", "--approve", digest, ROLES, APPROVE_CAPACITY)
    assert code == 0, text
    assert len([row for row in world.writes if "Microsoft.Fabric/capacities" in row]) == 1


def some_workspaces(world) -> None:
    world.workspaces = [
        {"id": "ws-busy", "displayName": "Busy", "description": "", "capacityId": "cap-0001", "type": "Workspace"},
        {"id": "ws-free", "displayName": "Sandbox-1", "description": "", "capacityId": "cap-0001", "type": "Workspace"},
        {"id": "ws-space", "displayName": "Has Space", "description": "", "capacityId": "cap-0001", "type": "Workspace"},
        {"id": "ws-other", "displayName": "Elsewhere", "description": "", "capacityId": "cap-0009", "type": "Workspace"},
        {"id": "ws-mine", "displayName": "My workspace", "description": "", "type": "Personal"}]
    world.items["ws-busy"] = [{"id": "r1", "type": "Report", "displayName": "Sales"}, {"id": "r2", "type": "Lakehouse", "displayName": "Bronze"}]
    world.capacities.append({"id": "cap-0009", "displayName": "other", "sku": "F8", "region": "West US 2", "state": "Active"})


def test_an_existing_workspace_is_taken_only_when_it_is_empty_and_on_the_chosen_capacity(bench):
    world = bench.world
    some_workspaces(world)
    code, text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "n", "1", "n", "1", "2"])
    assert "    1. Busy\n" in text and "    2. Sandbox-1\n" in text and "(1 more are on other capacities.)" in text
    assert "    -  Has Space: its name has characters the app's configuration does not take" in text and "My workspace" not in text
    assert "Busy holds 2 items (Bronze, Sales). The runner starts only in a workspace that is empty" in text
    assert (bench.cfg["FABRIC_WORKSPACE_NAME"], bench.cfg["FABRIC_WORKSPACE_ID"]) == ("Sandbox-1", "ws-free")
    assert "workspace       Sandbox-1  (ws-free, an existing empty one you chose)" in text
    assert re.search(r"p1\.workspace\s+will run", text) and "is empty; apply takes it into this deployment" not in text.split("p1.workspace")[0]
    digest = re.search(r"^Plan (\w+)$", text, re.M)[1]
    # somebody puts an item into it before the apply: not taken
    world.items["ws-free"] = [{"id": "x1", "type": "Notebook", "displayName": "scratch"}]
    code, text = bench.run("apply", "--approve", digest, ROLES, "--confirm", SETTINGS)
    assert code == core.EXIT_BLOCKED and "blocked  p1.workspace" in text and "holds 1 items (scratch)" in text
    world.items["ws-free"] = []
    code, text = bench.run("apply", "--approve", digest, ROLES)
    assert code == 0, text
    assert len(world.workspaces) == 5 and not [row for row in world.writes if row.startswith("POST workspaces ")]     # none was made
    assert world.find("ws-free", "Eventhouse", "WindFarmEH") and world.find("ws-free", "Lakehouse", "WindFarmLH")
    assert bench.state["target"]["workspace_id"] == "ws-free" and bench.state["target"]["workspace_chosen"] is True
    assert "the workspace you chose" in bench.run("plan", ROLES)[1]
    # a deployment stays in its workspace
    names.write_env(bench.env, {"FABRIC_WORKSPACE_ID": "ws-busy", "FABRIC_WORKSPACE_NAME": "Busy"})
    assert "A deployment stays in its workspace" in bench.run("plan", ROLES)[1]


def test_a_workspace_named_by_hand_is_held_to_the_same_rules(bench):
    world = bench.world
    some_workspaces(world)
    bench.plan()
    env = bench.env
    names.write_env(env, {"FABRIC_CAPACITY_ID": "cap-0001"})
    names.write_env(env, {"FABRIC_WORKSPACE_ID": "ws-other", "FABRIC_WORKSPACE_NAME": "Elsewhere"})
    text = bench.run("plan", ROLES)[1]
    assert re.search(r"p1\.workspace\s+BLOCKED", text) and "A workspace stays on its capacity: the runner moves none" in text
    names.write_env(env, {"FABRIC_WORKSPACE_ID": "ws-free", "FABRIC_WORKSPACE_NAME": "Sandbox-9"})
    assert "is now named Sandbox-1; the settings say Sandbox-9" in bench.run("plan", ROLES)[1]
    names.write_env(env, {"FABRIC_WORKSPACE_ID": "ws-gone", "FABRIC_WORKSPACE_NAME": "Gone"})
    assert "is not among the workspaces you can open" in bench.run("plan", ROLES)[1]
    names.write_env(env, {"FABRIC_WORKSPACE_ID": "ws-busy", "FABRIC_WORKSPACE_NAME": "Busy"})
    assert "holds 2 items (Bronze, Sales)" in bench.run("plan", ROLES)[1]
    # without an ID a name that is not the generated one is refused, as before
    names.write_env(env, {"FABRIC_WORKSPACE_ID": "", "FABRIC_WORKSPACE_NAME": "Busy"})
    code, text = bench.run("plan", ROLES)
    assert code == core.EXIT_REFUSED and "no longer carry the suffix" in text and world.writes == []


def test_with_a_new_capacity_the_workspace_is_new_too(bench):
    some_workspaces(bench.world)
    text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "", "n"])[1]
    assert "With a new capacity the workspace is new too" in text
    assert bench.cfg["FABRIC_WORKSPACE_NAME"] == f"WindFarmDigitalTwin-{bench.cfg['DEPLOYMENT_SUFFIX']}" and bench.cfg["FABRIC_WORKSPACE_ID"] == ""


def test_the_region_of_the_edge_and_of_a_new_capacity_are_asked_and_checked(bench):
    world = bench.world
    # the edge by number, the capacity's region typed; a region without the SKU and one that is none are said and asked again
    text = bench.run("plan", ROLES, "--ask", answers=["4", "y", "westus", "n", "narnia", "West Europe", NEW_WORKSPACE])[1]
    assert bench.cfg["LOCATION"] == "westus2" and bench.cfg["FABRIC_CAPACITY_REGION"] == "westeurope"
    assert ("Azure's list of SKUs does not name West US for an F16 in your subscription. It names: Australia East, Brazil South, "
            "Central US, East US 2, South Central US, West Europe, West US 2.") in text      # each region once, though Azure lists some twice
    assert "Take West US all the same, and let Azure decide when the capacity is requested? [y/N] n" in text
    assert "'narnia' is not a region with all Fabric workloads" in text and bench.state["choices"]["capacity_region_unlisted"]["answer"] == ""
    assert "so the runner proposes" not in text                       # West US 2 lacks nothing: proposed as it is
    assert "[westus2] westus" in text
    # asked again on request, by name; a region that lacks something of the demo needs a yes
    text = bench.run("plan", ROLES, "--ask", answers=["southcentralus", "y", "southcentralus", "n", "", NEW_WORKSPACE])[1]
    assert bench.cfg["LOCATION"] == "southcentralus" and bench.cfg["FABRIC_CAPACITY_REGION"] == "centralus"
    assert "Microsoft's table lists no Operations agent in South Central US, which later phases of the demo use. Take it anyway? [y/N] n" in text
    # three answers that are not in the list end the run, with nothing changed
    code, text = bench.run("plan", ROLES, "--ask", answers=["12", "mars", "0"])
    assert code == core.EXIT_REFUSED and "Three answers that were not in the list" in text and world.writes == []


def test_the_vm_size_is_asked_once_azure_could_not_say_and_moving_one_forward_asks_azure_nothing(slow_line):
    """What the sed line of 15:50 did by hand: put the size of his existing VM first."""
    answers = [KEEP_REGION, "n", "", NEW_WORKSPACE]
    text = slow_line.run("plan", ROLES, "--ask", answers=answers)[1]
    assert "VM size" not in text.split("Looking at")[0] and Unanswered.asked == ["roles", "sizes"]      # not known yet that Azure will not say
    text = slow_line.run("plan", ROLES, "--ask", answers=answers + ["3"])[1]
    assert "Azure did not say which sizes your subscription is offered" in text and "    3. Standard_D8s_v7" in text
    assert slow_line.cfg["VM_SIZE"].split()[:2] == ["Standard_D8s_v7", "Standard_D8s_v5"]
    assert Unanswered.asked == ["roles", "sizes"]                       # the same sizes in another order: no new question to Azure
    assert slow_line.run("plan", ROLES, answers=[])[0] == 0             # and the person is not asked twice
    assert slow_line.state["choices"]["vm_size"]["answer"] == "Standard_D8s_v7"


def test_nobody_to_ask_means_no_questions_and_no_answer_means_nothing_changed(bench):
    his_tenant(bench.world)
    code, text = bench.run("plan", ROLES, "--no-input", "--edge-region", "southcentralus", answers=[])
    assert "A few questions first" not in text and "could not be settled" not in text and re.search(r"pre\.capacity\s+done", text)
    assert {key: one["source"] for key, one in bench.state["choices"].items()} == {
        "region": "option --edge-region", "capacity": "the only capacity in sight that can hold the demo"}
    # the terminal closes in the middle of a question
    code, text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, EOFError])
    assert code == core.EXIT_REFUSED and "A question got no answer" in text and bench.world.writes == []
    assert bench.cfg["FABRIC_CAPACITY_CREATE_SKU"] == ""
    # Ctrl+C at a question: said in a line, not as a traceback
    code, text = bench.run("plan", ROLES, "--ask", answers=[KeyboardInterrupt])
    assert code == 130 and "STOPPED  by Ctrl+C" in text and bench.world.writes == []
    # apply never asks, also when questions are open and somebody is at the terminal
    digest = bench.plan(ROLES, "--no-input")
    assert "workspace" not in bench.state["choices"]
    assert bench.run("apply", "--approve", digest, ROLES, "--confirm", SETTINGS, answers=[])[0] == 0


def test_no_questions_while_an_apply_runs_and_none_about_what_exists(bench):
    bench.plan(ROLES, "--no-input")
    folder = bench.root / ".deploy" / bench.cfg["DEPLOYMENT_SUFFIX"]
    (folder / "apply.lock").write_text(json.dumps({"pid": os.getpid(), "host": socket.gethostname(), "started": "x"}))
    text = bench.run("plan", ROLES, answers=[])[1]                           # questions are open, and are not asked now
    assert "An apply is running" in text and "A few questions first" not in text
    (folder / "apply.lock").unlink()
    assert bench.apply(ROLES, "--no-input", confirm=[SETTINGS])[0] == 0
    assert bench.run("plan", ROLES, "--ask", answers=[])[0] == 0             # everything the questions are about exists


def test_a_capacity_to_be_made_is_named_after_its_own_deployment(bench):
    his_tenant(bench.world)
    bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "", NEW_WORKSPACE])
    old = bench.cfg["FABRIC_CAPACITY_NAME"]
    # the next deployment of the folder is asked for itself, and its capacity carries its own suffix
    assert bench.run("plan", ROLES, "--new", "--ask", answers=[KEEP_REGION, "y", "", NEW_WORKSPACE])[0] == 0
    assert bench.cfg["FABRIC_CAPACITY_NAME"] == f"fabwindfarm{bench.cfg['DEPLOYMENT_SUFFIX']}" != old
    names.write_env(bench.env, {"FABRIC_CAPACITY_NAME": "mycapacity"})
    code, text = bench.run("plan", ROLES)
    assert code == core.EXIT_REFUSED and "FABRIC_CAPACITY_NAME" in text


def test_the_vcpu_quota_is_looked_at_before_a_vm_is_asked_for(bench):
    """25 November 2026: the new VM stands beside the VM of the deployment by hand, and a deallocated VM counts too."""
    world = bench.world
    text = bench.run("preflight")[1]
    assert re.search(r"pre\.quota\s+done", text) and "8 vCPUs for Standard_D8s_v5: 100 free of 100 in its family, 92 of 100 in the region" in text
    assert steps.vm_family("Standard_D8as_v7") == ("standarddasv7family", 8) and steps.vm_family("Standard_E4ds_v5") == ("standardedsv5family", 4)
    assert steps.vm_family("Basic_A1") is None
    # the size of his existing VM first: its family has 2 vCPUs left of 10
    world.usage["StandardDsv7Family"] = (8, 10)
    names.write_env(bench.env, {"VM_SIZE": "Standard_D8s_v7 Standard_D8s_v6"})
    code, text = bench.run("preflight")
    assert re.search(r"pre\.quota\s+BLOCKED", text) and "the family of Standard_D8s_v7: 8 of 10 vCPUs in use" in text
    assert "A VM that is stopped still counts" in text and code == core.EXIT_BLOCKED
    world.usage["StandardDsv7Family"] = (8, 32)
    world.usage["cores"] = (96, 100)
    text = bench.run("preflight")[1]                                   # a block is not kept: asked again, and now the total
    assert "the region's total: 96 of 100 vCPUs in use" in text and "the family of" not in text.split("pre.quota")[2].split("pre.names")[0]
    world.usage["cores"] = (8, 100)
    del world.usage["StandardDsv7Family"]
    text = bench.run("preflight")[1]
    assert re.search(r"pre\.quota\s+NOT CHECKED", text) and "no row named like the family of Standard_D8s_v7" in text
    asked = world.usage_calls
    bench.run("preflight")
    assert world.usage_calls == asked                                  # kept, like the other answers that hold for a day
    assert bench.apply(ROLES, confirm=[SETTINGS])[0] == 0
    assert re.search(r"pre\.quota\s+done\s+vCPU quota for the VM\n\s+the VM exists\n", bench.run("plan", ROLES, "--recheck")[1])
    assert world.writes.count("az group create rg-windfarm-edge-" + bench.cfg["DEPLOYMENT_SUFFIX"]) == 1


# ------------------------------------------------------------------------------------------ one folder, many deployments
# 25 November 2026, 16:35: "I don't want a pre-populated .env file. I want you to generate the random 3 alphanum suffix in
# the runtime. I might be building this demo over and over in the same tenant or new tenants".
def test_nothing_is_prepared_the_first_plan_starts_a_deployment_and_keeps_its_settings_with_its_checkpoint(bench):
    assert not (bench.root / ".deploy").exists() and not Path(bench.root, "config", "demo.env").exists()
    code, text = bench.run("plan", ROLES)
    suffix = bench.suffix
    assert code == 0 and names.valid_suffix(suffix) and (bench.root / ".deploy" / "current").read_text().strip() == suffix
    assert f"New deployment {suffix}: every name ends in -{suffix}, for subscription Demo subscription (sub-1111). Its settings are in .deploy/{suffix}/demo.env." in text
    assert f"Deployment {suffix}. Settings and checkpoint: .deploy/{suffix}/. A new one beside it: add --new." in text
    assert bench.env == bench.root / ".deploy" / suffix / "demo.env" and bench.cfg["RESOURCE_GROUP"] == f"rg-windfarm-edge-{suffix}"
    opening = bench.env.read_text().split("\n\n")[0]                        # the file says what it is, not how to copy a template
    assert opening.startswith(f"# The settings of deployment {suffix}, kept by tools/deploy.py") and "Copy this file" not in bench.env.read_text()
    assert "\n# ---- Azure ---" in bench.env.read_text() and "# ---- Only for tools/deploy.py" in bench.env.read_text()   # the rest of the template is there
    assert not Path(bench.root, "config", "demo.env").exists() and bench.world.writes == []
    # every script of the deployment is handed that file, and nothing is ever written into config/
    assert bench.apply(ROLES, confirm=[SETTINGS])[0] == 0
    assert bench.world.env_files and set(bench.world.env_files) == {str(bench.env)}
    assert sorted(entry.name for entry in (bench.root / "config").iterdir()) == ["demo.env.example"]
    # the next plan goes on with it: no new names. One deployment in the folder: the apply line needs no name
    assert bench.run("plan", ROLES)[0] == 0 and bench.suffix == suffix and "New deployment" not in bench.last
    assert f"  python3 tools/deploy.py apply --deployment {suffix} --approve " in bench.last     # the apply line always names its deployment


def test_the_same_folder_holds_one_deployment_after_another_and_each_keeps_its_own(deployed):
    first, world = deployed.suffix, deployed.world
    writes = list(world.writes)
    names.write_env(deployed.env, {"VM_SIZE": "Standard_D8s_v7 Standard_D8s_v6"})
    # the choices of the first are kept for the subscription once, on request ...
    code, text = deployed.run("plan", ROLES, "--save-profile")
    assert code == 0 and "Profile saved for subscription Demo subscription: LOCATION=southcentralus, FABRIC_CAPACITY_ID=cap-0001, VM_SIZE=" in text
    kept = {path.name: path.read_bytes() for path in (deployed.root / ".deploy" / first).iterdir() if path.is_file()}
    # ... and the next deployment takes them with no question and no option: a repeat deployment
    code, text = deployed.run("plan", ROLES, "--new", answers=[])
    second = deployed.suffix
    assert code == 0 and second != first and deployments.listed(deployed.root) == [first, second]
    assert ("chosen by       edge region southcentralus (profile); capacity existing cap-0001 (profile); "
            "VM sizes Standard_D8s_v7 Standard_D8s_v6 (profile)") in text
    assert deployed.cfg["VM_SIZE"] == "Standard_D8s_v7 Standard_D8s_v6" and deployed.cfg["EVENTSTREAM_TOPIC"] == ""      # choices, not what was made
    assert deployed.cfg["CUSTOM_LOCATIONS_OID"] == world.custom_locations and " 0 blocked," in text
    assert f"Also in this folder: {first} (--deployment SUFFIX)." in text
    assert re.search(r"p1\.resource_group\s+will run", text) and f"rg-windfarm-edge-{second} in southcentralus  (not created yet)" in text
    assert world.writes == writes                                           # the plan of the second changed nothing
    assert {path.name: path.read_bytes() for path in (deployed.root / ".deploy" / first).iterdir() if path.is_file()} == kept      # and the first is as it was
    plan_of_second = re.search(r"^Plan (\w+)$", text, re.M)[1]
    # with more than one deployment in the folder, the apply line that is printed names its own
    assert f"python3 tools/deploy.py apply --deployment {second} --approve {plan_of_second} {ROLES}\n" in text
    # status names both; --deployment goes back to the first, which is still complete
    status = deployed.run("status")[1]
    assert f"  {first}: subscription sub-1111; resource group rg-windfarm-edge-{first} made" in status
    assert f"  {second}: subscription sub-1111; nothing made yet   <- this one" in status
    code, text = deployed.run("plan", ROLES, "--deployment", first)
    assert deployed.suffix == first and re.search(r"p1\.resource_group\s+done", text) and " 0 for the runner," in text
    # an apply with the other deployment's plan says whose plan it is, and changes nothing
    code, text = deployed.run("apply", "--approve", plan_of_second, ROLES)
    assert code == core.EXIT_REFUSED and f"Plan {plan_of_second} is the plan of deployment {second}" in text
    assert f"Use --deployment {second} to apply that plan" in text and world.writes == writes


def test_a_new_deployment_elsewhere_is_started_on_request_and_takes_nothing_from_here(deployed):
    first, world, mine = deployed.suffix, deployed.world, dict(deployed.world.account)
    writes = list(world.writes)
    there = dict(mine, id="sub-2222", name="Another tenant's subscription", tenantId="tenant-bbbb")
    world.account, world.others = there, {"sub-1111": mine}
    world.groups, world.workspaces, world.vm, world.custom_locations = {}, [], None, "99999999-aaaa-bbbb-cccc-000000000000"
    # nobody is asked anything, and nothing is started by itself: the current deployment stays the one commands work on
    code, text = deployed.run("plan", ROLES, answers=[])
    assert deployed.suffix == first and "New deployment" not in text
    # --new starts one in the subscription the CLI is on; the profile of the other subscription is not used there
    code, text = deployed.run("plan", ROLES, "--new", "--no-input")
    second = deployed.suffix
    assert second != first and deployed.cfg["SUBSCRIPTION_ID"] == "sub-2222" and deployed.cfg["LOCATION"] == ""
    assert re.search(r"pre\.region\s+BLOCKED", text) and "python3 tools/deploy.py plan --edge-region REGION" in text
    assert "chooses no geography by itself" in text and world.writes == writes
    code, text = deployed.run("plan", ROLES, "--edge-region", "westus3")
    assert deployed.cfg["LOCATION"] == "westus3" and deployed.cfg["CUSTOM_LOCATIONS_OID"] == "99999999-aaaa-bbbb-cccc-000000000000"
    # or in a subscription named for it, whatever the CLI is on
    code, text = deployed.run("plan", ROLES, "--new", "--subscription", "sub-1111")
    assert deployed.cfg["SUBSCRIPTION_ID"] == "sub-1111" and deployed.suffix not in (first, second)
    assert world.writes == writes and names.read_env(deployments.env_of(deployed.root, first))["SUBSCRIPTION_ID"] == "sub-1111"


def test_a_deployment_whose_resource_group_is_gone_shows_drift_and_is_never_swapped_for_another(deployed):
    first, world = deployed.suffix, deployed.world
    del world.groups[deployed.cfg["RESOURCE_GROUP"]]                        # bash infra/99-cleanup.sh --all, say
    for answers in (None, []):                                              # nobody there, or somebody: no question either way
        code, text = deployed.run("plan", ROLES, answers=answers)
        assert deployed.suffix == first and "DRIFT" in text and "New deployment" not in text
    world.workspaces, world.items, world.vm, world.instance, world.cluster = [], {}, None, None, None
    code, text = deployed.run("plan", ROLES, "--new")
    assert code == 0 and deployed.suffix != first and re.search(r"p1\.resource_group\s+will run", text) and "DRIFT" not in text


def test_settings_the_earlier_issues_kept_in_config_are_moved_to_their_deployment_once(bench):
    """His folder on 25 November: config/demo.env with the suffix 064, written by the first issue, and .deploy/064/."""
    his_tenant(bench.world)
    old = Path(bench.root, "config", "demo.env")
    names.write_env(old, {**names.generated("064"), "SUBSCRIPTION_ID": "sub-1111", "FABRIC_CAPACITY_ID": F32["id"], "LOCATION": "westus2"},
                    template=bench.root / "config" / "demo.env.example")
    (bench.root / ".deploy" / "064").mkdir(parents=True)
    (bench.root / ".deploy" / "064" / "state.json").write_text(json.dumps({"version": 1, "choices": {"region": {"answer": "westus2"}}}))
    (bench.root / ".deploy" / "9zz").mkdir()                                # a checkpoint whose settings are gone is no deployment
    (bench.root / ".deploy" / "9zz" / "state.json").write_text("{}")
    code, text = bench.run("plan", ROLES)
    assert code == 0 and "Moved config/demo.env to .deploy/064/demo.env" in text and not old.exists()
    assert deployments.listed(bench.root) == ["064"] and "9zz" not in text
    assert bench.env.read_text().startswith("# The settings of deployment 064, kept by tools/deploy.py") and "Copy this file" not in bench.env.read_text()
    assert bench.suffix == "064" and bench.cfg["LOCATION"] == "westus2" and bench.state["choices"]["region"]["answer"] == "westus2"
    assert "Moved" not in bench.run("plan", ROLES)[1] and "New deployment" not in bench.last


def test_a_folder_with_several_deployments_and_no_current_one_asks_which(bench):
    bench.plan()
    first = bench.suffix
    bench.run("plan", "--new")
    (bench.root / ".deploy" / "current").unlink()
    code, text = bench.run("status")
    assert code == core.EXIT_REFUSED and "Name one with --deployment" in text and first in text
    assert bench.run("status", "--deployment", first)[0] == 0 and bench.suffix == first
    # the suffix inside the settings is the deployment's own
    names.write_env(bench.env, {"DEPLOYMENT_SUFFIX": "abc"})
    code, text = bench.run("plan")
    assert code == core.EXIT_REFUSED and "DEPLOYMENT_SUFFIX is 'abc'" in text
    # and a folder with nothing in it has nothing to apply or to show
    shutil.rmtree(bench.root / ".deploy")
    assert "This folder has no deployment yet" in bench.run("status")[1] and not (bench.root / ".deploy").exists()


def test_a_new_deployment_takes_no_suffix_twice(deployed, monkeypatch):
    first = deployed.suffix
    drawn = iter([first, first, "q7k"])
    monkeypatch.setattr(names, "new_suffix", lambda: next(drawn))            # the draw comes up with the suffix in use, twice
    code, text = deployed.run("plan", ROLES, "--new")
    assert code == 0 and deployed.suffix == "q7k" and deployments.listed(deployed.root) == [first, "q7k"]


def test_settings_in_config_never_replace_those_of_a_deployment_and_a_deleted_deployment_is_not_the_current_one(bench):
    bench.plan()
    first, mine = bench.suffix, bench.env.read_bytes()
    stray = Path(bench.root, "config", "demo.env")                          # a copy someone put back, with the same suffix
    names.write_env(stray, {**names.generated(first), "SUBSCRIPTION_ID": "sub-9999"}, template=bench.root / "config" / "demo.env.example")
    code, text = bench.run("plan")
    assert code == 0 and "Moved" not in text and stray.exists() and bench.env.read_bytes() == mine
    bench.run("plan", "--new")
    second = bench.suffix
    shutil.rmtree(bench.root / ".deploy" / second)                          # the folder of the current one is thrown away
    code, text = bench.run("status")
    assert code == 0 and bench.suffix == first and f"Deployment {first}." in text


# ------------------------------------------------------------------------------------------ where a new capacity can be made
# 25 November 2026, 17:17, the first run of the questions on a tenant: "F16 is not offered to your subscription in Central US",
# with a picture of his own F16, active, in Central US. The runner had read the first entry of Azure's list for the SKU.
def test_every_entry_of_a_sku_is_read_whichever_way_azure_lists_them(bench):
    world = bench.world
    his_tenant(world)
    assert world.skus_by_region and world.fabric_offers["F16"][0] == "Australia East"   # as his list of 17:55: 63 entries for F16
    text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "", NEW_WORKSPACE])[1]
    assert bench.cfg["FABRIC_CAPACITY_REGION"] == "centralus" and "does not name" not in text and "[centralus] " in text
    assert re.search(r"pre\.capacity\s+done", text) and "Azure's list of SKUs names the region for F16, and the name is free" in text
    world.skus_by_region = False                                            # or one entry for a SKU, with all its regions
    text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "", NEW_WORKSPACE])[1]
    assert bench.cfg["FABRIC_CAPACITY_REGION"] == "centralus" and "does not name" not in text and re.search(r"pre\.capacity\s+done", text)


def test_a_list_that_does_not_name_the_sku_is_not_a_refusal_and_azure_decides(bench):
    world = bench.world
    his_tenant(world)
    del world.fabric_offers["F16"]
    text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "", NEW_WORKSPACE])[1]
    assert "Azure's list of SKUs does not name F16 for your subscription, so where one can be made could not be told." in text
    assert bench.cfg["FABRIC_CAPACITY_REGION"] == "centralus" and re.search(r"pre\.capacity\s+NOT CHECKED", text)
    assert "The request for the capacity decides, straight after the resource group" in text
    digest = re.search(r"^Plan (\w+)$", text, re.M)[1]
    bench.run("apply", "--approve", digest, ROLES, APPROVE_CAPACITY, "--confirm", SETTINGS)
    assert list(world.arm_capacities) == [bench.cfg["FABRIC_CAPACITY_NAME"]]


def test_a_region_the_list_does_not_name_is_said_with_the_list_and_left_to_the_person(bench):
    world = bench.world
    his_tenant(world)
    world.fabric_offers["F16"] = ["West Europe", "East US 2"]
    # Enter at a question that has no proposal left asks again; the region typed is taken only on a yes
    text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "", "centralus", "n", "centralus", "y", NEW_WORKSPACE])[1]
    assert "Azure's list of SKUs does not name Central US for an F16 in your subscription. It names: East US 2, West Europe." in text
    assert "[none] \n  Please name a region." in text
    assert text.count("Take Central US all the same, and let Azure decide when the capacity is requested? [y/N]") == 2
    assert bench.cfg["FABRIC_CAPACITY_REGION"] == "centralus" and bench.state["choices"]["capacity_region_unlisted"]["answer"] == "centralus"
    assert re.search(r"pre\.capacity\s+NOT CHECKED", text) and "and you took the region all the same" in text
    assert "if Azure refuses it, choose again: python3 tools/deploy.py plan --ask" in text
    # the yes was for that region: another one written into the settings by hand is held to the list
    names.write_env(bench.env, {"FABRIC_CAPACITY_REGION": "westus2"})
    text = bench.run("plan", ROLES)[1]
    assert re.search(r"pre\.capacity\s+BLOCKED", text) and "does not name West US 2 for an F16 in this subscription" in text
    # and it ends with the next choice: a region the list names, then the first one by hand again
    text = bench.run("plan", ROLES, "--ask", answers=[KEEP_REGION, "y", "westeurope", NEW_WORKSPACE])[1]
    assert bench.cfg["FABRIC_CAPACITY_REGION"] == "westeurope" and re.search(r"pre\.capacity\s+done", text)
    names.write_env(bench.env, {"FABRIC_CAPACITY_REGION": "centralus"})
    assert re.search(r"pre\.capacity\s+BLOCKED", bench.run("plan", ROLES)[1])


# ------------------------------------------------------------------------------------------ the hardening of the seventh issue
# 25 November 2026, 18:08: "Harden the existing ... deployment runner and make repeat deployments require fewer interactions."
def test_an_ambiguous_capacity_or_region_stops_with_the_candidates_and_nothing_is_written_to_the_cloud(bench):
    world = bench.world
    world.capacities.append({"id": "cap-0002", "displayName": "second-capacity", "sku": "F8", "region": "West US 2", "state": "Active"})
    world.capacities.append(dict(PPU))
    bench.profile = False                                                    # no profile, no option, nobody to ask
    code, text = bench.run("plan", ROLES)
    assert code == 0 and re.search(r"pre\.region\s+BLOCKED", text) and re.search(r"pre\.capacity\s+BLOCKED", text)
    assert "plan --edge-region REGION     one of: eastus, eastus2" in text
    assert "cap-0001" in text and "cap-0002" in text and "python3 tools/deploy.py plan --capacity ID" in text
    assert bench.cfg["LOCATION"] == "" and bench.cfg["FABRIC_CAPACITY_ID"] == ""          # nothing was put in their place
    digest = re.search(r"^Plan (\w+)$", text, re.M)[1]
    code, text = bench.run("apply", "--approve", digest, ROLES, "--confirm", SETTINGS)
    assert code == core.EXIT_BLOCKED and world.writes == []
    # an option that is not valid is refused where it is given, and nothing else is taken instead
    for option, value, words in (("--edge-region", "moonbase", "Azure IoT Operations is supported in"),
                                 ("--capacity", "cap-9999", "is not a capacity Fabric lists for you"),
                                 ("--capacity", PPU["id"], "cannot hold the demo: a Premium Per User capacity"),
                                 ("--vm-size", "huge", "Not a size: huge"), ("--ssh-source", "0.0.0.0/0", "does not open SSH to every address"),
                                 ("--workspace-id", "ws-nowhere", "is not a workspace you can see")):
        code, text = bench.run("plan", ROLES, option, value)
        assert code == core.EXIT_REFUSED and words in text and bench.cfg["LOCATION"] == "" and bench.cfg["FABRIC_CAPACITY_ID"] == ""
    assert "Give one of them" in bench.run("plan", "--capacity", "cap-0001", "--new-capacity")[1]
    assert "goes with --new-capacity" in bench.run("plan", "--capacity-region", "centralus")[1]
    # the options settle both, together; the plan says where each choice came from
    code, text = bench.run("plan", ROLES, "--edge-region", "westus3", "--capacity", "second-capacity", "--ssh-source", "203.0.113.10")
    assert code == 0 and " 0 blocked," in text and bench.cfg["FABRIC_CAPACITY_ID"] == "cap-0002" and bench.cfg["SSH_SOURCE_CIDR"] == "203.0.113.10/32"
    assert "chosen by       edge region westus3 (option --edge-region); capacity existing cap-0002 (option --capacity)" in text
    # an apply names its deployment: it does not go by .deploy/current, which a plan in another terminal may have moved
    code, text = bench.run("apply", "--approve", "x", ROLES, as_typed=True)
    assert code == core.EXIT_REFUSED and "apply names its deployment: add --deployment SUFFIX" in text and bench.suffix in text
    # a choice is settled by a plan: apply and status take none
    for mode in (("apply", "--approve", "x"), ("status",)):
        code, text = bench.run(*mode, "--edge-region", "eastus")
        assert code == core.EXIT_REFUSED and "--edge-region: a choice is settled by a plan" in text


def test_a_pinned_capacity_that_is_gone_blocks_and_no_other_is_taken(bench):
    world = bench.world
    saved = bench.root / ".deploy" / "profiles" / "sub-1111.json"
    saved.parent.mkdir(parents=True)
    saved.write_text(json.dumps({"tenant_id": "tenant-aaaa", "subscription_id": "sub-1111",
                                 "values": {"LOCATION": "southcentralus", "FABRIC_CAPACITY_ID": "cap-gone"}}))
    code, text = bench.run("plan", ROLES)
    assert bench.cfg["FABRIC_CAPACITY_ID"] == "cap-gone" and re.search(r"pre\.capacity\s+BLOCKED", text)        # cap-0001 is there, and is not taken
    assert "capacity existing cap-gone (profile)" in text
    assert bench.run("plan", ROLES, "--no-profile", "--new", "--edge-region", "eastus2")[0] == 0 and bench.cfg["FABRIC_CAPACITY_ID"] == "cap-0001"
    saved.write_text(json.dumps({"tenant_id": "tenant-zzzz", "subscription_id": "sub-1111", "values": {"LOCATION": "eastus"}}))
    code, text = bench.run("plan", ROLES, "--new")
    assert code == core.EXIT_REFUSED and "was saved for tenant tenant-zzzz" in text and world.writes == []


def test_the_choice_to_make_a_capacity_is_never_inherited_and_needs_its_own_approval(bench):
    his_tenant(bench.world)
    code, text = bench.run("plan", ROLES, "--new-capacity", "--capacity-region", "centralus")
    first = bench.suffix
    assert code == 0 and re.search(r"p1\.capacity\s+needs approval", text) and "--approve-capacity-creation" in text
    # what is to be paid for is shown in the plan itself, not only in a question: SKU, region, resource group, administrator, the bill
    assert f"SKU F16; region centralus; resource group rg-windfarm-edge-{first}; administrator sami@contoso.example" in text
    assert "Azure bills it for as long as it runs, whether or not anything uses it." in text
    assert APPROVE_CAPACITY not in text.split("To carry this plan out:")[1].splitlines()[1]            # the apply line carries no approval nobody gave
    assert "--new-capacity needs --capacity-region REGION when nobody can be asked" in bench.run("plan", "--new", "--new-capacity")[1]
    # the profile keeps the region and no capacity; the next deployment makes none and is not allowed to
    code, text = bench.run("plan", ROLES, "--deployment", first, "--save-profile")
    assert "makes a capacity of its own" in text and "the profile names no capacity" in text and "FABRIC_CAPACITY_ID" not in text.split("Profile saved")[1].split("\n")[0]
    code, text = bench.run("plan", ROLES, "--new", APPROVE_CAPACITY)
    assert bench.suffix != first and bench.cfg["FABRIC_CAPACITY_CREATE_SKU"] == "" and bench.cfg["FABRIC_CAPACITY_ID"] == F32["id"]
    assert re.search(r"p1\.capacity\s+done", text) and "none is made" in text


def test_a_changed_vm_size_ssh_scope_setting_or_shipped_file_voids_the_approval_and_says_what_differs(bench):
    (bench.root / "config" / "load-env.sh").write_text("# the helpers every script reads\n")
    (bench.root / "simulator" / "windfarm_sim").mkdir(parents=True)
    (bench.root / "simulator" / "windfarm_sim" / "engine.py").write_text("VERSION = 1\n")
    digest = bench.plan(ROLES)
    saved = json.loads((bench.root / ".deploy" / bench.suffix / "plans" / f"{digest}.json").read_text())["covers"]
    assert saved["operator"] == "sami@contoso.example" and saved["deployment"] == bench.suffix and saved["subscription_id"] == "sub-1111"
    assert saved["vm_sizes"][0] == "Standard_D8s_v5" and saved["ssh_scope"].startswith("the public address of the computer")
    assert [step for step, _ in saved["role_grants"]] == ["p1.vm_identity_roles", "p1.iot_operations", "p1.workspace_access"]
    assert "simulator/windfarm_sim" in dict(saved["steps"])["p1.simulator"] and "config/load-env.sh" in dict(saved["steps"])["p1.edge_vm"]
    apply = ("apply", "--approve", digest, ROLES, "--confirm", SETTINGS)

    def refused(words: str) -> None:
        code, text = bench.run(*apply)
        assert code == core.EXIT_REFUSED and "What differs: " in text and words in text, text
        assert bench.world.writes == [] and bench.state["confirmed"] == {}        # and the confirmation given with it was not kept
    before = bench.env.read_text()
    names.write_env(bench.env, {"VM_SIZE": "Standard_D8s_v7 Standard_D8s_v5"})
    refused('vm_sizes: was ["Standard_D8s_v5", ')
    bench.env.write_text(before)
    names.write_env(bench.env, {"SSH_SOURCE_CIDR": "198.51.100.0/24"})
    refused('ssh_scope: was "the public address of the computer that runs the apply, as a /32", is now "198.51.100.0/24"')
    bench.env.write_text(before)
    names.write_env(bench.env, {"VM_AUTO_SHUTDOWN_UTC": "1200"})
    refused("settings.VM_AUTO_SHUTDOWN_UTC: was ")
    bench.env.write_text(before)
    (bench.root / "simulator" / "windfarm_sim" / "engine.py").write_text("VERSION = 2\n")        # shipped to the VM by the simulator's step
    refused("steps.p1.simulator.simulator/windfarm_sim: was ")
    (bench.root / "simulator" / "windfarm_sim" / "engine.py").write_text("VERSION = 1\n")
    (bench.root / "config" / "load-env.sh").write_text("# changed\n")                              # read by every script
    refused("config/load-env.sh: was ")
    (bench.root / "config" / "load-env.sh").write_text("# the helpers every script reads\n")
    bench.world.account["user"]["name"] = "someone.else@contoso.example"                          # another person at the same CLI
    refused('operator: was "sami@contoso.example", is now "someone.else@contoso.example"')
    bench.world.account["user"]["name"] = "sami@contoso.example"
    # as it was planned, the same approval is accepted, and what the apply itself writes on the way does not void it
    code, text = bench.run(*apply)
    assert code == 0 and bench.cfg["EVENTSTREAM_TOPIC"] and bench.state["confirmed"][SETTINGS]["by"] == "sami@contoso.example"
    assert bench.run(*apply)[0] == 0


def test_two_deployments_never_build_the_app_in_one_folder(deployed):
    def context(*argv):
        ctx, steps = cli.build(cli.parser().parse_args(list(argv)), deployed.root, io.StringIO(), deployed.adapters)
        return ctx, {step.id: step for step in steps}
    first = deployed.suffix
    one, steps = context("plan", "--up-to", "phase4")
    steps["p4.scaffold"].act(one)
    deployed.run("plan", "--new", "--up-to", "phase4")
    two, steps_two = context("plan", "--up-to", "phase4")
    steps_two["p4.scaffold"].act(two)                                       # the second build, while the first has not been deployed
    builds = deployed.world.app_builds
    assert builds == [str(deployed.root / ".deploy" / suffix / "app" / "windfarm-twin") for suffix in (first, deployed.suffix)]
    for ctx in (one, two):
        config = (Path(builds[(one, two).index(ctx)]) / "packages/functions/src/config.ts").read_text()
        assert ctx.cfg["FABRIC_WORKSPACE_NAME"] in config
    one.current = "p4.deploy"
    steps["p4.deploy"].act(one)             # the stand-in fails a deployment from a folder that was built for another workspace
    assert deployed.world.find(deployed.world.workspaces[0]["id"], "FabricApp", "WindFarmTwin")
    assert not (deployed.root / "app" / "windfarm-twin").exists()


def test_an_apply_that_ended_before_fabric_answered_does_not_start_or_take_a_run_by_itself(bench):
    world = bench.world
    world.die_after_post = "02_generate_history"
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == 130 and world.writes.count("POST job 02_generate_history") == 1
    assert bench.state["pending"]["p1.history"]["job"]["intent"] == "run" and "id" not in bench.state["pending"]["p1.history"]["job"]
    job = next(iter(world.jobs.values()), None) and [j for runs in world.jobs.values() for j in runs if j["notebook"] == "02_generate_history"][0]["id"]
    code, text = bench.apply(ROLES)
    assert code == core.EXIT_BLOCKED and "set out to run 02_generate_history" in text and "ended before it learned whether Fabric took the request" in text
    assert f"{job} (" in text and "--adopt-job p1.history=ID" in text and "--resubmit p1.history" in text
    assert world.writes.count("POST job 02_generate_history") == 1          # no second run, and the first not taken unasked
    code, text = bench.apply(ROLES, "--adopt-job", "p1.history=no-such-run")
    assert code != 0 and world.writes.count("POST job 02_generate_history") == 1
    code, text = bench.apply(ROLES, "--adopt-job", f"p1.history={job}")
    assert code == 0 and world.writes.count("POST job 02_generate_history") == 1
    assert bench.state["steps"]["p1.history"]["evidence"]["job:02_generate_history"]["id"] == job and bench.state["pending"] == {}


def test_a_request_that_never_arrived_is_sent_again_only_when_a_person_says_so(bench):
    world = bench.world
    world.die_after_post = "02_generate_history"
    assert bench.apply(ROLES, confirm=[SETTINGS])[0] == 130
    for runs in world.jobs.values():                                        # as if Fabric had never taken the request
        runs[:] = [job for job in runs if job["notebook"] != "02_generate_history"]
    code, text = bench.apply(ROLES)
    assert code == core.EXIT_BLOCKED and "Fabric lists since then: none" in text
    assert "--adopt-job and --resubmit both name p1.history" in bench.apply(ROLES, "--resubmit", "p1.history", "--adopt-job", "p1.history=x")[1]
    code, text = bench.apply(ROLES, "--resubmit", "p1.history")
    assert code == 0 and world.writes.count("POST job 02_generate_history") == 2 and bench.state["pending"] == {}


def test_a_run_that_finished_while_nobody_waited_is_taken_and_not_run_again(bench):
    world = bench.world
    world.polls_per_job = 10 ** 6                                           # the notebooks run longer than an apply waits
    code, text = bench.apply(ROLES, confirm=[SETTINGS])
    assert code == core.EXIT_RUNNING and "01_load_reference_data" in text
    saved = bench.state["pending"]["p1.reference_tables"]["job"]["id"]
    for runs in world.jobs.values():
        for job in runs:
            job["polls"] = 10 ** 6 - 1                                      # ... and it finishes before the next apply asks
    world.polls_per_job = 3
    code, text = bench.apply(ROLES)
    assert code == 0 and world.writes.count("POST job 01_load_reference_data") == 1
    assert bench.state["steps"]["p1.reference_tables"]["evidence"]["job:01_load_reference_data"]["id"] == saved
    writes = list(world.writes)
    assert bench.apply(ROLES)[0] == 0 and world.writes == writes            # a finished plan applied again adds nothing


def test_a_script_that_prints_nothing_is_stopped_at_its_limit_with_what_it_started(tmp_path, capsys):
    from deployer.cloud import Shell
    shell = Shell(tmp_path, core.Redactor(), out=sys.stdout)
    shell.QUIET_NOTE = 1
    begun = time.monotonic()
    with pytest.raises(CloudError, match="did not finish within 3 seconds"):
        shell.run(["bash", "-c", "sleep 300 & echo $! > child.pid; echo started; wait"], timeout=3)
    assert time.monotonic() - begun < 20
    shown = capsys.readouterr().out
    assert "| started" in shown and "still running after" in shown and "no line for" in shown
    child = int((tmp_path / "child.pid").read_text())
    for _ in range(50):                                                     # the command and what it started are gone
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        raise AssertionError("the process the script had started is still running")
    assert shell.run(["bash", "-c", "echo quick"], timeout=5) == (0, "quick")


def test_under_the_lock_the_checkpoint_is_read_again_before_anything_is_decided(bench, monkeypatch):
    """Another apply finished between this one's start and its turn at the lock: what it wrote is not written over."""
    digest = bench.plan(ROLES)
    state_file = bench.root / ".deploy" / bench.suffix / "state.json"
    enter = core.Lock.__enter__

    def another_apply_wrote_first(lock):
        held = enter(lock)
        data = json.loads(state_file.read_text())
        data["steps"]["p1.note"] = {"status": "complete", "detail": "written by the apply that held the lock before this one"}
        state_file.write_text(json.dumps(data))
        return held
    monkeypatch.setattr(core.Lock, "__enter__", another_apply_wrote_first)
    code, text = bench.run("apply", "--approve", digest, ROLES)
    assert code == core.EXIT_BLOCKED and bench.state["steps"]["p1.note"]["detail"].startswith("written by the apply")


# ------------------------------------------------------------------------------------------ a line that drops single connections
# 26 November 2026, 14:45 to 15:02: three applies in a row ended on one call that got no answer (a TLS handshake to the
# Fabric API, `az resource list`, a TLS handshake again), on a workstation whose connections to the same hosts, timed
# seconds before, took a fifth of a second. Each time nothing had been changed, and a step that was complete was no
# longer counted.
def test_a_read_through_the_azure_cli_that_gets_no_answer_is_asked_again_and_a_change_is_made_once():
    import subprocess
    import types
    from deployer.cloud import Az
    given, hang = [], [0]

    def run(argv, **how):
        given.append(how["timeout"])
        if hang[0] > 0:
            hang[0] -= 1
            raise subprocess.TimeoutExpired(argv, how["timeout"])
        return types.SimpleNamespace(returncode=0, stdout="[]", stderr="")
    az = Az(core.Redactor(), run=run)
    hang[0] = 2
    assert az.json("resource", "list", "--resource-group", "rg-x") == [] and given == [30, 60, 90]      # of 180 seconds
    given.clear()
    hang[0] = 3
    with pytest.raises(CloudError, match="az resource list --resource-group did not answer within 180 seconds, asked 3 times"):
        az.json("resource", "list", "--resource-group", "rg-x")
    assert given == [30, 60, 90]
    given.clear()
    hang[0] = 1                                               # a call that changes something: once, with all of its time
    with pytest.raises(CloudError, match=r"did not answer within 1800 seconds\.$"):
        az.run("group", "create", "--name", "list", "--location", "southcentralus")
    assert given == [1800] and hang[0] == 0
    given.clear()
    hang[0] = 1                                               # a read with a short limit of its own is not cut into pieces
    with pytest.raises(CloudError, match=r"within 45 seconds\.$"):
        az.json("rest", "--method", "get", "--url", "https://management.azure.com/x", timeout=45)
    assert given == [45]
    assert Az.reads(["rest", "--method", "GET", "--url", "u"]) and not Az.reads(["rest", "--method", "put", "--url", "u/list"])
    assert Az.reads(["account", "get-access-token", "--resource", "r"]) and Az.reads(["iot", "ops", "show", "--name", "n"])
    assert not Az.reads(["vm", "run-command", "invoke", "--name", "show"]) and not Az.reads(["role", "assignment", "create"])


class _Answer:
    status, headers = 200, {}

    def read(self):
        return b'{"value": []}'

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def line(monkeypatch):
    """urllib's door, with a list of what goes wrong on the next requests. Yields (sent, faults)."""
    import urllib.request
    sent, faults = [], []

    def urlopen(request, timeout=0):
        sent.append((request.get_method(), timeout))
        if faults:
            fault = faults.pop(0)
            if fault is not None:
                raise fault
        return _Answer()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    return sent, faults


def _handshake():
    import urllib.error
    return urllib.error.URLError(TimeoutError("_ssl.c:1063: The handshake operation timed out"))


def test_a_connection_to_fabric_that_hangs_is_made_again_and_a_request_that_went_out_is_not_sent_twice(line):
    from operations_agent import UNREACHED, Fabric, FabricError
    sent, faults = line
    naps = []
    fabric = Fabric("token-token-token-token", sleep=naps.append)
    faults[:] = [_handshake(), _handshake()]
    assert fabric.get("workspaces") == {"value": []}
    assert sent == [("GET", 20), ("GET", 20), ("GET", 60)] and naps == [2.0, 4.0]      # given up sooner, then given time
    sent.clear()
    faults[:] = [_handshake()]                                 # nothing was sent: a request that changes something goes again
    assert fabric.call("POST", "workspaces/w/items", {"displayName": "x"})[0] == 200 and len(sent) == 2
    sent.clear()
    faults[:] = [TimeoutError("The read operation timed out")]  # it was sent, and no answer came: not sent a second time
    with pytest.raises(FabricError, match=r"did not answer a request it was sent \(POST\)") as stop:
        fabric.call("POST", "workspaces/w/items", {"displayName": "x"})
    assert len(sent) == 1 and stop.value.code == UNREACHED and stop.value.status is None
    sent.clear()
    faults[:] = [TimeoutError("The read operation timed out"), TimeoutError("The read operation timed out")]
    assert fabric.get("workspaces") == {"value": []} and len(sent) == 3            # a read is asked again
    sent.clear()
    faults[:] = [_handshake(), _handshake(), _handshake()]
    with pytest.raises(FabricError, match="in 3 tries: .*handshake operation timed out") as stop:
        fabric.get("workspaces")
    assert len(sent) == 3 and stop.value.code == UNREACHED


def test_the_other_addresses_are_asked_again_the_same_way_and_a_management_command_is_sent_once(line):
    from deployer.cloud import UNREACHED, Kusto, http
    sent, faults = line
    naps = []
    faults[:] = [_handshake(), TimeoutError("The read operation timed out")]
    assert http("GET", "https://onelake.example/ws/item/Files", "token", timeout=180, sleep=naps.append)[0] == 200 and len(naps) == 2
    assert sent == [("GET", 60), ("GET", 180), ("GET", 180)]          # a hung read is given up after a minute, then given its time
    sent.clear()
    faults[:] = [TimeoutError("The read operation timed out")]
    with pytest.raises(CloudError, match=r"onelake.example did not answer a request it was sent \(PUT\)") as stop:
        http("PUT", "https://onelake.example/ws/item/Files/x", "token", body={}, sleep=naps.append)
    assert len(sent) == 1 and stop.value.code == UNREACHED
    sent.clear()
    faults[:] = [_handshake(), _handshake(), _handshake()]
    with pytest.raises(CloudError, match="Could not reach onelake.example, in 3 tries"):
        http("PUT", "https://onelake.example/ws/item/Files/x", "token", body={}, sleep=naps.append)
    # the Eventhouse: a query is a read although it is a POST, a management command is not
    asked = []

    def request(method, url, token, body=None, headers=None, timeout=0, read=False):
        asked.append((url.rsplit("/", 1)[-1], read))
        return 200, json.dumps({"Tables": [{"Columns": [], "Rows": []}]}).encode()

    class TokenOnly:
        token = staticmethod(lambda resource: "t")
    kusto = Kusto(TokenOnly(), core.Redactor(), request=request)
    kusto._audience["https://cluster.example"] = "https://cluster.example"
    kusto.rows("https://cluster.example", "db", "RawEvents | count")
    kusto.rows("https://cluster.example", "db", ".create table T (a: int)", mgmt=True)
    kusto.rows("https://cluster.example", "db", ".show table T policy mirroring | project Policy", mgmt=True)   # shows, changes nothing
    kusto.rows("https://cluster.example", "db", ".alter-merge table T policy mirroring kind=delta", mgmt=True)
    assert asked == [("query", True), ("mgmt", False), ("mgmt", True), ("mgmt", False)]


def test_a_complete_step_that_cannot_be_asked_about_for_a_moment_is_still_counted_as_complete(deployed):
    complete = sum(1 for entry in deployed.state["steps"].values() if entry.get("status") == "complete")
    before, calls = list(deployed.world.writes), list(deployed.world.shell_calls)
    digest = deployed.plan(ROLES)
    deployed.world.no_answer[("resource", "list")] = 2               # once as the apply reads the plan again, once at the step
    code, text = deployed.run("apply", "--approve", digest, ROLES)
    assert code == core.EXIT_BLOCKED and "blocked  p1.resource_group" in text and "could not be looked at" in text, text[-900:]
    entry = deployed.state["steps"]["p1.resource_group"]
    assert entry["status"] == "complete" and "did not answer within" in entry["unseen"]["detail"]
    assert sum(1 for e in deployed.state["steps"].values() if e.get("status") == "complete") == complete
    assert "provisioned   no: " in text and "steps complete; this run did not get to look at all of them" in text
    assert "p1.resource_group is complete and could not be looked at just now" in text
    assert "demo-ready    no" in text                                  # a run that ended early vouches for nothing
    code, text = deployed.run("apply", "--approve", digest, ROLES)   # the line is back: nothing is done again
    assert code == 0 and "provisioned   yes" in text and "unseen" not in deployed.state["steps"]["p1.resource_group"]
    assert deployed.world.writes == before and deployed.world.shell_calls == calls


def test_a_step_that_is_not_complete_and_cannot_be_looked_at_is_blocked_as_before(bench):
    digest = bench.plan(ROLES)
    bench.world.no_answer[("resource", "list")] = 1
    code, text = bench.run("apply", "--approve", digest, ROLES, "--confirm", SETTINGS)
    assert code == core.EXIT_BLOCKED and bench.state["steps"]["p1.resource_group"]["status"] == "blocked"
    assert "unseen" not in bench.state["steps"]["p1.resource_group"]


def test_fabric_not_reached_is_called_the_connection_and_not_the_sign_in(bench):
    bench.run("plan", ROLES)
    bench.world.no_answer["fabric"] = 1
    code, text = bench.run("preflight")
    row = next(r for r in text.splitlines() if "pre.fabric" in r and "BLOCKED" in r)
    assert "could not be reached from this computer" in text and "handshake operation timed out" in text, row
    assert "This is the connection, not your sign-in" in text and "time_appconnect" in text
    assert "az login   (in a session" not in text
    bench.world.no_answer["fabric refuses"] = 1                        # an answer, and it is a refusal: that is the sign-in
    code, text = bench.run("preflight")
    assert "did not answer the signed-in user" in text and "TokenExpired" in text and "az login   (in a session" in text
    assert "not your sign-in" not in text


def test_the_six_mirroring_policies_are_asked_together_and_not_one_after_the_other(deployed):
    # 26 November 2026: `looking at p1.onelake_availability ... 187 s`, in every plan and twice in every apply. The command
    # takes one table, and each answer took about half a minute.
    import threading
    together = threading.Barrier(6, timeout=10)
    asked = []

    class Slow(FakeKusto):
        def rows(self, uri, database, csl, mgmt=False):
            if "policy mirroring" in csl and csl.lstrip().startswith(".show"):
                asked.append(csl.split()[2])
                together.wait()               # goes on only when all six are in flight at once
            return super().rows(uri, database, csl, mgmt)
    real = deployed.adapters
    deployed.adapters = lambda redact: dict(real(redact), kusto=Slow(deployed.world))
    code, text = deployed.run("plan", ROLES)
    assert code == 0 and "OneLake availability is on for the six typed tables" in text, text[-600:]
    assert len(asked) == 6 and len(set(asked)) == 6
    deployed.world.kql["mirroring"].discard("AlarmEvents")       # and each answer still belongs to its table
    together.reset()
    code, text = deployed.run("plan", ROLES)
    assert "OneLake availability is off for: AlarmEvents" in text
