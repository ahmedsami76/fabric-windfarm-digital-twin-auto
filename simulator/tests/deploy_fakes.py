"""A pretend Azure and Fabric for the tests of tools/deploy.py.

One World holds what exists. The five adapters of the runner (Azure CLI, Fabric API, Eventhouse, shell, OneLake)
are replaced by classes that read and change that World, and write every change into World.writes. The stand-ins
answer in the shapes Microsoft documents for the operations the runner uses; they prove what the runner does with
those answers, not that Fabric gives them.
"""
from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from deployer import names  # noqa: E402
from deployer.cloud import CloudError  # noqa: E402
from deployer.steps import ROLE_IDS  # noqa: E402

API = "https://api.fabric.microsoft.com/v1"
KEY = "s3cr3tKeyOfTheEventstream0123456789abcdefghij="
CONNECTION = f"Endpoint=sb://esehabc123.servicebus.windows.net/;SharedAccessKeyName=key_1;SharedAccessKey={KEY};EntityPath=esehabc123_eh"


class World:
    def __init__(self):
        self.account = {"id": "sub-1111", "name": "Demo subscription", "tenantId": "tenant-aaaa",
                        "user": {"name": "sami@contoso.example", "type": "user"}}
        self.my_roles = ["Owner"]            # at the subscription; a name the runner does not know stands for a custom role
        self.my_object_id = "11111111-2222-3333-4444-555555555555"
        self.role_calls = 0
        self.unregistered: set = set()
        self.skus = ["Standard_D8s_v5", "Standard_D8s_v6", "Standard_D8s_v7", "Standard_E4s_v5"]    # known in the region
        self.refused: dict = {}             # size -> reason code of a Location restriction
        self.sku_calls = 0
        # vCPUs in use and their limits, as `az vm list-usage` names them; Azure's own spelling of the families varies
        self.usage = {"cores": (8, 100), "standardDSv5Family": (0, 100), "StandardDsv7Family": (0, 100), "virtualMachines": (1, 25000)}
        self.usage_calls = 0
        self.storage_free = True
        self.custom_locations = "040ca937-7748-471b-a3ea-31d1ebd5da8a"
        self.groups: dict = {}
        self.resources: list = []
        self.vm = self.cluster = self.instance = None
        self.host = self.simulator = self.reference = False
        self.dataflows: dict = {}
        self.role_assignments: list = []
        self.capacities = [{"id": "cap-0001", "displayName": "demo-capacity", "sku": "F64", "region": "South Central US", "state": "Active"}]
        self.workspaces: list = []
        self.items: dict = {}
        self.shortcuts: dict = {}
        self.access: dict = {}
        self.jobs: dict = {}                # notebook id -> list of job instances
        self.schedules: dict = {}
        self.topology: dict = {}
        self.operations: dict = {}
        self.kql = {"tables": set(), "mappings": set(), "functions": set(), "update_policy": False, "mirroring": set()}
        self.writes: list = []              # every change, in order
        self.shell_calls: list = []
        self.env_files: list = []           # the settings file each script was handed
        self.tokens: list = []
        self.counter = 0
        # switches a test sets
        self.slow: set = set()              # kinds of item whose creation answers 202 and stays running
        self.polls_per_job = 1
        self.failing_notebooks: set = set()
        self.destination_status = "Running"
        self.ingestion_works = True
        self.fail_script = ""
        self.rayfin_signed_in = True
        self.sql_route = {"rows": 7548, "turbines": 12, "newest_minutes": 2.0}
        self.gate_file = True
        self.node = "v22.23.5"
        self.missing_tools: set = set()
        self.extensions = ["azure-iot-ops", "ssh"]
        self.may_create_workspaces = True
        self.closed_capacities: set = set()   # capacities a workspace cannot be put on by this person
        # Microsoft.Fabric in Azure: capacities by name as Azure has them, where a SKU is offered, names taken by others
        self.arm_capacities: dict = {}
        self.fabric_offers = {"F16": ["Central US", "East US 2", "West US 2", "West Europe", "South Central US"],
                              "F64": ["Central US"]}
        self.taken_capacity_names: set = set()
        self.fabric_quota = True
        self.capacity_state = "Active"        # the state a capacity is in right after it was made
        self.fabric_calls: list = []

    def new_id(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-{self.counter:04d}"

    def wrote(self, what: str) -> None:
        self.writes.append(what)

    def add_item(self, ws: str, kind: str, name: str) -> dict:
        entry = {"id": self.new_id(kind.lower()), "type": kind, "displayName": name}
        self.items.setdefault(ws, []).append(entry)
        return entry

    def find(self, ws: str, kind: str, name: str):
        return next((e for e in self.items.get(ws, []) if e["type"] == kind and e["displayName"] == name), None)

    def telemetry_flows(self) -> bool:
        return bool(self.simulator and "windfarm-to-fabric" in self.dataflows and self.ingestion_works
                    and "RawEvents_mapping" in self.kql["mappings"] and (self.vm or {}).get("powerState") == "VM running")


def opt(args, flag):
    return args[args.index(flag) + 1] if flag in args else None


class FakeAz:
    def __init__(self, world: World, redact=None):
        self.w, self._redact = world, redact

    def token(self, resource: str) -> str:
        token = "eyJ0eXAiOiJKV1Qi." + base64.b64encode(resource.encode()).decode().rstrip("=") + ".c2lnbmF0dXJlLW9mLXRoZS10b2tlbg"
        self.w.tokens.append(token)
        if self._redact:
            self._redact.learn(token)
        return token

    def json(self, *args, timeout=0):
        return self.maybe(*args, timeout=timeout)

    def run(self, *args, timeout=0):
        w = self.w
        if args[:2] == ("group", "create"):
            tags = dict(pair.split("=", 1) for pair in args[args.index("--tags") + 1:] if "=" in pair)
            name = opt(args, "--name")
            w.groups[name] = {"id": f"/subscriptions/{w.account['id']}/resourceGroups/{name}", "name": name,
                              "location": opt(args, "--location"), "tags": tags}
            w.wrote(f"az group create {name}")
        elif args[:1] == ("rest",) and "/providers/Microsoft.Fabric/capacities/" in opt(args, "--url"):
            assert opt(args, "--method") == "put" and "api-version=2023-11-01" in args
            name = opt(args, "--url").rsplit("/", 1)[-1]
            body = json.loads(opt(args, "--body"))
            assert re.fullmatch(r"[a-z][a-z0-9]{2,62}", name) and body["sku"] == {"name": body["sku"]["name"], "tier": "Fabric"}
            assert body["properties"]["administration"]["members"] == [w.account["user"]["name"]]
            group = opt(args, "--url").split("/resourceGroups/")[1].split("/")[0]
            assert group in w.groups, "a capacity can only be made in a resource group that exists"
            if not w.fabric_quota:
                raise CloudError("az rest --method put failed: (InsufficientQuota) The requested capacity exceeds the available quota")
            assert name not in w.arm_capacities, "the runner made a capacity a second time"
            w.arm_capacities[name] = {"id": opt(args, "--url").replace("https://management.azure.com", ""), "name": name,
                                      "location": body["location"], "sku": body["sku"], "tags": body.get("tags", {}),
                                      "properties": {"provisioningState": "Succeeded", "state": w.capacity_state}}
            display = {"centralus": "Central US", "eastus2": "East US 2", "westus2": "West US 2", "westeurope": "West Europe",
                       "southcentralus": "South Central US"}.get(body["location"], body["location"])
            w.capacities.append({"id": w.new_id("cap-new"), "displayName": name, "sku": body["sku"]["name"], "region": display,
                                 "state": "Active"})
            w.resources.append({"id": w.arm_capacities[name]["id"], "type": "Microsoft.Fabric/capacities"})
            w.wrote(f"az rest PUT Microsoft.Fabric/capacities/{name} {body['sku']['name']} {body['location']}")
        elif args[:3] == ("role", "assignment", "create"):
            # by ID and with the kind of principal: the real CLI then asks neither for role definitions nor Microsoft Graph
            assert re.fullmatch(r"[0-9a-f-]{36}", opt(args, "--role")) and opt(args, "--assignee-principal-type") == "ServicePrincipal"
            w.role_assignments.append((opt(args, "--assignee-object-id"), opt(args, "--role"), opt(args, "--scope")))
            w.wrote(f"az role assignment create {opt(args, '--role')} @ {opt(args, '--scope')}")
        else:
            raise AssertionError(f"the fake does not know az {' '.join(args)}")

    def maybe(self, *args, timeout=0):
        w = self.w
        if args[:2] == ("account", "show"):
            return w.account
        if args[:2] == ("provider", "show"):
            assert opt(args, "--query") == "registrationState"
            return "NotRegistered" if opt(args, "--namespace") in w.unregistered else "Registered"
        if args[:2] == ("extension", "list"):
            return list(w.extensions)
        if args[:2] == ("resource", "show"):
            assert opt(args, "--resource-type") == "Microsoft.Kubernetes/connectedClusters"
            return w.cluster
        if args[:3] == ("role", "assignment", "list"):
            raise AssertionError("the runner asked `az role assignment list`, which fetches every role definition to print names "
                                 "and stood for three minutes on a workstation")
        if args[:3] == ("ad", "signed-in-user", "show"):
            assert opt(args, "--query") == "id" and timeout and timeout <= 60
            return w.my_object_id
        if args[:1] == ("rest",) and "Microsoft.Authorization/roleAssignments" in opt(args, "--url"):
            assert "api-version=2022-04-01" in args and timeout and timeout <= 60
            w.role_calls += 1
            scope = opt(args, "--url").replace("https://management.azure.com", "").split("/providers/Microsoft.Authorization")[0]
            asked = next(arg for arg in args if arg.startswith("$filter="))[len("$filter="):]
            definition = "/subscriptions/sub-1111/providers/Microsoft.Authorization/roleDefinitions/"
            if asked == f"atScope() and assignedTo('{w.my_object_id}')":
                assert scope == f"/subscriptions/{w.account['id']}"
                return [{"role": definition + ROLE_IDS.get(role, "0c0c0c0c-aaaa-bbbb-cccc-" + f"{index:012d}"), "scope": scope}
                        for index, role in enumerate(w.my_roles)]
            principal = re.fullmatch(r"principalId eq '([^']+)'", asked)
            assert principal, f"a filter the documentation does not list: {asked}"
            return [{"role": definition + role, "scope": at} for who, role, at in w.role_assignments if who == principal[1]]
        if args[:2] == ("vm", "list-usage"):
            assert opt(args, "--location") and timeout and timeout <= 60
            w.usage_calls += 1
            return [{"name": name, "used": used, "limit": limit} for name, (used, limit) in w.usage.items()]
        if args[:2] == ("vm", "list-skus"):
            raise AssertionError("the runner asked `az vm list-skus`, which fetches every region and stood for five minutes on a workstation")
        if args[:3] == ("storage", "account", "check-name"):
            return {"nameAvailable": w.storage_free, "reason": None if w.storage_free else "AlreadyExists"}
        if args[:3] == ("ad", "sp", "show"):
            return w.custom_locations
        if args[:2] == ("group", "show"):
            return w.groups.get(opt(args, "--name"))
        if args[:2] == ("resource", "list"):
            return list(w.resources)
        if args[:2] == ("vm", "show"):
            return w.vm
        if args[:1] == ("connectedk8s",):
            raise AssertionError("the runner asked the Azure CLI for an extension command a workstation need not have")
        if args[:4] == ("iot", "ops", "dataflow", "show"):
            return w.dataflows.get(opt(args, "--name"))
        if args[:3] == ("iot", "ops", "show"):
            return w.instance
        if args[:1] == ("rest",) and "Microsoft.Fabric" in opt(args, "--url"):
            assert "api-version=2023-11-01" in args and timeout and timeout <= 60
            url = opt(args, "--url")
            w.fabric_calls.append(url.rsplit("/", 1)[-1])
            if url.endswith("/providers/Microsoft.Fabric/skus"):
                sku = re.search(r"name=='(\w+)'", opt(args, "--query"))[1]
                return w.fabric_offers.get(sku)
            if url.endswith("/checkNameAvailability"):
                asked = json.loads(opt(args, "--body"))
                assert asked["type"] == "Microsoft.Fabric/capacities"
                taken = asked["name"] in w.taken_capacity_names or asked["name"] in w.arm_capacities
                return {"nameAvailable": not taken, "reason": "AlreadyExists" if taken else None}
            assert opt(args, "--method") == "get" and "/providers/Microsoft.Fabric/capacities/" in url
            return w.arm_capacities.get(url.rsplit("/", 1)[-1])
        if args[:1] == ("rest",) and "Microsoft.Compute/skus" in opt(args, "--url"):
            assert any(re.fullmatch(r"\$filter=location eq '[a-z0-9]+'", arg) for arg in args)
            assert "api-version=2021-07-01" in args and timeout and timeout <= 120
            w.sku_calls += 1
            return [{"name": name, "refused": w.refused.get(name)} for name in w.skus]
        if args[:1] == ("rest",):
            return {"value": [{"name": "azure-iot-operations-ab1cd", "identity": {"principalId": "principal-aio"},
                               "properties": {"extensionType": "microsoft.iotoperations"}}] if w.instance else []}
        raise AssertionError(f"the fake does not know az {' '.join(args)}")


class FakeFabric:
    """Answers as the documented operations do: 201 with the item, or 202 with a Location to ask about."""

    def __init__(self, world: World):
        self.w = world

    def get(self, path):
        return self.call("GET", path)[2]

    def listing(self, path):
        return list((self.call("GET", path)[2] or {}).get("value", []))

    def _created(self, kind: str, slow_key: str, make):
        w = self.w
        if slow_key in w.slow:
            op = w.new_id("op")
            w.operations[op] = {"status": "Running", "make": make}
            return 202, {"Location": f"{API}/operations/{op}", "Retry-After": "5"}, None
        return 201, {}, make()

    def call(self, method, path, body=None):
        w = self.w
        path = path.replace(API + "/", "").lstrip("/")
        route = f"{method} {path}"
        if route == "GET workspaces":
            return 200, {}, {"value": list(w.workspaces)}
        if route == "GET capacities":
            return 200, {}, {"value": list(w.capacities)}
        if route == "POST workspaces":
            if not w.may_create_workspaces:
                raise CloudError("The Fabric API answered 403: InsufficientPrivileges", 403)
            if body.get("capacityId") in w.closed_capacities:
                # What Fabric answers here is not known; the stand-in names the capacity, as any honest answer would.
                raise CloudError("The Fabric API answered 400: the workspace cannot be assigned to this capacity", 400)
            if any(ws["displayName"] == body["displayName"] for ws in w.workspaces):
                raise CloudError("The Fabric API answered 409: WorkspaceNameAlreadyExists", 409)
            ws = {"id": w.new_id("ws"), "displayName": body["displayName"], "description": body.get("description", ""),
                  "capacityId": body.get("capacityId")}
            w.workspaces.append(ws)
            w.wrote(f"POST workspaces {body['displayName']} on {body.get('capacityId')}")
            return 201, {}, ws
        found = re.fullmatch(r"GET operations/(op-\d+)(/result)?", route)
        if found:
            operation = w.operations[found[1]]
            if found[2]:
                return 200, {}, operation.get("result")
            if operation["status"] == "Running" and operation.get("finish"):
                operation.update(status="Succeeded", result=operation["make"]())
            return 200, {}, {"status": operation["status"]}
        found = re.fullmatch(r"(GET|POST) workspaces/([^/]+)/(.+)", route)
        if not found:
            raise AssertionError(f"the fake does not know {route}")
        ws, rest = found[2], found[3]
        if rest == "items" and method == "GET":
            return 200, {}, {"value": list(w.items.get(ws, []))}
        if rest == "roleAssignments":
            if method == "GET":
                return 200, {}, {"value": [{"id": p, "principal": {"id": p, "type": "ServicePrincipal"}, "role": r} for p, r in w.access.get(ws, {}).items()]}
            w.access.setdefault(ws, {})[body["principal"]["id"]] = body["role"]
            w.wrote(f"POST roleAssignments {body['principal']['id']} {body['role']}")
            return 201, {}, {}
        if rest == "eventhouses" and method == "POST":
            def make():
                house = w.add_item(ws, "Eventhouse", body["displayName"])
                w.add_item(ws, "KQLDatabase", body["displayName"])      # Fabric gives a new Eventhouse a database of its name
                return house
            w.wrote(f"POST eventhouses {body['displayName']}")
            return self._created("Eventhouse", "eventhouse", make)
        if rest == "kqlDatabases" and method == "POST":
            w.wrote(f"POST kqlDatabases {body['displayName']}")
            return self._created("KQLDatabase", "kqldatabase", lambda: w.add_item(ws, "KQLDatabase", body["displayName"]))
        if re.fullmatch(r"kqlDatabases/[^/]+", rest):
            return 200, {}, {"properties": {"queryServiceUri": "https://trd-fake.z2.kusto.fabric.microsoft.com"}}
        if rest == "lakehouses" and method == "POST":
            def make():
                w.add_item(ws, "SQLEndpoint", body["displayName"])
                return w.add_item(ws, "Lakehouse", body["displayName"])
            w.wrote(f"POST lakehouses {body['displayName']}")
            return self._created("Lakehouse", "lakehouse", make)
        if re.fullmatch(r"lakehouses/[^/]+", rest):
            return 200, {}, {"properties": {"sqlEndpointProperties": {"connectionString": "fake.datawarehouse.fabric.microsoft.com"}}}
        found = re.fullmatch(r"items/([^/]+)/shortcuts", rest)
        if found:
            if method == "GET":
                return 200, {}, {"value": list(w.shortcuts.get(found[1], []))}
            w.shortcuts.setdefault(found[1], []).append({"name": body["name"], "path": body["path"], "target": dict(body["target"], type="OneLake")})
            w.wrote(f"POST shortcut {body['name']}")
            return 201, {}, {}
        if rest == "eventstreams" and method == "POST":
            definition = json.loads(base64.b64decode(body["definition"]["parts"][0]["payload"]))

            def make():
                stream = w.add_item(ws, "Eventstream", body["displayName"])
                w.topology[stream["id"]] = {
                    "sources": [dict(s, id=w.new_id("src"), status="Running") for s in definition["sources"]],
                    "destinations": [dict(d, id=w.new_id("dst"), status=w.destination_status) for d in definition["destinations"]],
                    "streams": definition["streams"]}
                w.definition = definition
                return stream
            w.wrote(f"POST eventstreams {body['displayName']}")
            return self._created("Eventstream", "eventstream", make)
        found = re.fullmatch(r"eventstreams/([^/]+)/topology", rest)
        if found:
            return 200, {}, w.topology[found[1]]
        if re.fullmatch(r"eventstreams/[^/]+/sources/[^/]+/connection", rest):
            return 200, {}, {"fullyQualifiedNamespace": "esehabc123.servicebus.windows.net", "eventHubName": "esehabc123_eh",
                             "accessKeys": {"primaryKey": KEY, "secondaryKey": KEY[::-1], "primaryConnectionString": CONNECTION,
                                            "secondaryConnectionString": CONNECTION.replace(KEY, KEY[::-1])}}
        if rest == "notebooks" and method == "POST":
            part = body["definition"]["parts"][0]
            assert body["definition"]["format"] == "ipynb" and part["path"].endswith(".ipynb")
            notebook = json.loads(base64.b64decode(part["payload"]))
            entry = w.add_item(ws, "Notebook", body["displayName"])
            entry["lakehouse"] = notebook["metadata"]["dependencies"]["lakehouse"]
            w.wrote(f"POST notebooks {body['displayName']}")
            return 201, {}, entry
        found = re.fullmatch(r"items/([^/]+)/jobs/instances(\?jobType=RunNotebook)?", rest)
        if found:
            if method == "GET":
                return 200, {}, {"value": list(w.jobs.get(found[1], []))}
            name = next(e["displayName"] for e in w.items[ws] if e["id"] == found[1])
            job = {"id": w.new_id("job"), "status": "NotStarted", "polls": 0, "notebook": name,
                   "parameters": ((body or {}).get("executionData") or {}).get("parameters")}
            w.jobs.setdefault(found[1], []).append(job)
            w.wrote(f"POST job {name}")
            return 202, {"Location": f"{API}/workspaces/{ws}/items/{found[1]}/jobs/instances/{job['id']}", "Retry-After": "30"}, None
        found = re.fullmatch(r"items/([^/]+)/jobs/instances/([^/]+)", rest)
        if found:
            job = next(j for j in w.jobs[found[1]] if j["id"] == found[2])
            if job["status"] in ("NotStarted", "InProgress"):
                job["polls"] += 1
                job["status"] = "InProgress"
                if job["polls"] >= w.polls_per_job:
                    self._finish(ws, job)
            return 200, {}, {key: job.get(key) for key in ("id", "status", "failureReason", "startTimeUtc", "endTimeUtc")}
        found = re.fullmatch(r"items/([^/]+)/jobs/RunNotebook/schedules", rest)
        if found:
            if method == "GET":
                return 200, {}, {"value": list(w.schedules.get(found[1], []))}
            w.schedules.setdefault(found[1], []).append({"id": w.new_id("sch"), "enabled": body["enabled"], "configuration": body["configuration"]})
            w.wrote("POST schedule")
            return 201, {}, {}
        raise AssertionError(f"the fake does not know {route}")

    def _finish(self, ws: str, job: dict) -> None:
        """What a notebook leaves behind when it has run."""
        w, name = self.w, job["notebook"]
        failed = name in w.failing_notebooks or (name == "90_deployment_gate" and not w.telemetry_flows())
        job.update(status="Failed" if failed else "Completed", startTimeUtc="2026-11-25T09:00:00", endTimeUtc="2026-11-25T09:03:00",
                   failureReason={"errorCode": "NotebookFailed", "message": f"Deployment gate failed: TurbineTelemetry: 0 rows; token {w.tokens[-1] if w.tokens else ''}"} if failed else None)
        if failed:
            return
        made = {"06_build_semantic_model": ("SemanticModel", "WindFarm Operations"), "08_build_report": ("Report", "WindFarm Operations Report"),
                "09_build_data_agent": ("DataAgent", "WindFarmDataAgent"), "11_build_ontology": ("Ontology", "WindFarmOntology")}
        if name in made and not w.find(ws, *made[name]):
            w.add_item(ws, *made[name])


class FakeKusto:
    def __init__(self, world: World):
        self.w, self.commands = world, []

    def rows(self, uri, database, csl, mgmt=False):
        k, text = self.w.kql, csl.strip()
        if text.startswith(".show tables"):
            return [{"TableName": name} for name in sorted(k["tables"])]
        if text.startswith(".show functions"):
            return [{"Name": name} for name in sorted(k["functions"])]
        if "ingestion json mappings" in text:
            return [{"Name": name} for name in sorted(k["mappings"])]
        if "policy update" in text and text.startswith(".show"):
            return [{"Policy": '[{"IsEnabled": true}]' if k["update_policy"] else "null"}]
        if "policy mirroring" in text and text.startswith(".show"):
            table = text.split()[2]
            return [{"Policy": json.dumps({"IsEnabled": table in k["mirroring"]})}]
        if text.startswith("."):
            assert mgmt, "a command was sent as a query"
            self.commands.append(text)
            self.w.wrote("KQL " + text.splitlines()[0][:40])
            assert not re.search(r"^\.(drop|clear|delete|set-or-replace)", text, re.M), "the runner sent a command that removes data"
            k["tables"] |= set(re.findall(r"^\.create-merge table (\w+)", text, re.M))
            k["mappings"] |= set(re.findall(r"ingestion json mapping '(\w+)'", text))
            k["functions"] |= set(re.findall(r"^\.create-or-alter function[^\n]*?\)\s*(\w+)\s*\(", text, re.M))
            k["update_policy"] = k["update_policy"] or "policy update" in text
            k["mirroring"] |= set(re.findall(r"^\.alter-merge table (\w+) policy mirroring", text, re.M))
            return [{"Result": "Completed", "CommandText": row} for row in text.splitlines() if row.startswith(".") and "execute database script" not in row]
        flowing = self.w.telemetry_flows()
        if text.startswith("RawEvents"):
            return [{"Rows": 720 if self.w.simulator and "windfarm-to-fabric" in self.w.dataflows and self.w.ingestion_works else 0}]
        if text.startswith("TurbineTelemetry"):
            return [{"Rows": 688 if flowing else 0, "Turbines": 12 if flowing else 0, "AgeSeconds": 38 if flowing else None,
                     "WithSeq": 688 if flowing else 0}]
        raise AssertionError(f"the fake Eventhouse does not know: {text[:80]}")


class FakeShell:
    def __init__(self, world: World, root: Path, redact):
        self.w, self.root, self._redact = world, Path(root), redact

    def must(self, argv, env=None, cwd=None, timeout=0):
        code, text = self.run(argv, env, cwd, timeout)
        if code != 0:
            raise CloudError(f"{' '.join(argv[:4])} ended with exit code {code}. Its last lines are above.")
        return text

    def which(self, tool):
        return tool not in self.w.missing_tools

    def capture(self, argv, env=None, cwd=None, timeout=0):
        w = self.w
        if argv[:2] == ["node", "--version"]:
            return (0, w.node + "\n") if w.node else (127, "")
        if argv[:2] == ["node", "app/probe-lakehouse-route.mjs"]:
            assert env["SQL_TOKEN"] in w.tokens and env["SQL_DATABASE"] == "WindFarmLH"
            w.shell_calls.append("node app/probe-lakehouse-route.mjs")
            return 0, self._redact(json.dumps(w.sql_route) + "\n")
        raise AssertionError(f"the fake shell does not capture {argv}")

    def run(self, argv, env=None, cwd=None, timeout=0):
        w, command, env = self.w, " ".join(argv), env or {}
        w.shell_calls.append(command)
        if w.fail_script and w.fail_script in command:
            w.fail_script = ""
            return 1, self._redact(f"ERROR: something went wrong; the connection was {CONNECTION}")
        w.wrote(command)
        # Every script is handed the settings of its deployment by name, and they are not config/demo.env.
        named = argv[argv.index("--workspace") + 1] if "--workspace" in argv else None       # the app's tool is told the name
        if argv[0] == "bash":
            settings = Path(env.get("ENV_FILE", ""))
            assert settings.is_file() and settings.parent.parent.name == ".deploy", f"a script was started without its deployment's settings: {env}"
            self.w.env_files.append(str(settings))
            named = names.read_env(settings).get("FABRIC_WORKSPACE_NAME")      # as the scripts find it
        ws = next((entry["id"] for entry in w.workspaces if entry.get("displayName") == named), None)
        if "01-create-edge-vm.sh" in command:
            assert env.get("DEPLOY_RUNNER") == "1", "the VM script was started without DEPLOY_RUNNER"
            w.vm_env = dict(env)
            name = next(n for n in w.groups)
            w.vm = {"id": f"{w.groups[name]['id']}/providers/Microsoft.Compute/virtualMachines/vm", "name": "vm-windfarm-edge-" + name[-3:],
                    "provisioningState": "Succeeded", "powerState": "VM running", "identity": {"principalId": "principal-vm"},
                    "hardwareProfile": {"vmSize": "Standard_D8s_v7"}}
            w.resources += [{"id": w.vm["id"], "type": "Microsoft.Compute/virtualMachines"}]
        elif "02-prepare-host.sh" in command:
            w.host = True
        elif "03-arc-enable.sh" in command:
            w.cluster = {"id": "/subscriptions/sub-1111/resourceGroups/rg/providers/Microsoft.Kubernetes/connectedClusters/arc",
                         "name": "arc", "properties": {"connectivityStatus": "Connected"}}
        elif "04-deploy-iot-operations.sh" in command:
            w.instance = {"id": "/subscriptions/sub-1111/x/instances/aio", "name": "aio", "properties": {"provisioningState": "Succeeded"}}
        elif "05-deploy-simulator.sh" in command:
            w.simulator = True
        elif "06-connect-edge-to-fabric.sh" in command:
            topic = re.search(r'^EVENTSTREAM_TOPIC="([^"]*)"', settings.read_text(), re.M)[1]
            w.dataflows["windfarm-to-fabric"] = {"properties": {"mode": "Enabled", "operations": [
                {"operationType": "Source"}, {"operationType": "Destination", "destinationSettings": {"dataDestination": topic}}]}}
        elif "07-sync-reference-data.sh" in command:
            w.reference = True
        elif "08-create-command-path.sh" in command:
            w.dataflows["fabric-to-windfarm-control"] = {"properties": {"mode": env.get("COMMAND_DATAFLOW_MODE", "Enabled")}}
            if not w.find(ws, "Eventstream", "WindFarmCommands"):
                w.add_item(ws, "Eventstream", "WindFarmCommands")
        elif "create-app.sh" in command:
            source = self.root / "app" / "overlay" / "packages" / "functions" / "src"
            target = self.root / "app" / "windfarm-twin" / "packages" / "functions" / "src"
            target.mkdir(parents=True, exist_ok=True)
            (target / "build.ts").write_text((source / "build.ts").read_text())
            (target / "config.ts").write_text(f"export const WORKSPACE_NAME = '{env['FABRIC_WORKSPACE_NAME']}';\n")
        elif command.startswith("npx rayfin up"):
            if not w.rayfin_signed_in:
                w.writes.pop()
                return 1, "Error: You are not signed in. Run `rayfin login`."
            w.add_item(ws, "FabricApp", "WindFarmTwin")
        elif "vm.sh push" in command:
            w.writes.pop()          # copies files to the VM: not a change worth counting in the tests
        else:
            raise AssertionError(f"the fake shell does not know: {command}")
        return 0, "ok"


class FakeOneLake:
    def __init__(self, world: World):
        self.w = world

    def read(self, workspace_id, item_id, path):
        if not self.w.gate_file:
            return None
        return json.dumps({"tables": [{"table": "TurbineTelemetry", "rows": 8352, "age_minutes": 6.5},
                                      {"table": "ref_turbines", "rows": 12, "age_minutes": None}], "failures": []}).encode()
