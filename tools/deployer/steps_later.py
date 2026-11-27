"""The steps of Phases 2 to 4 and of the opt-in Phase 5a, and the whole catalogue in order.

Three kinds of step appear here that Phase 1 does not have:
  - a notebook that installs a library with %pip. Microsoft documents that this is switched off in pipeline runs
    and how to switch it on there; for a run started through the API nothing is written. So these are the
    operator's by default, and the runner's only with --opt-in pip-jobs;
  - a preview feature, behind --allow-preview;
  - what has no API at all, or only one that asks a person: tenant settings, the operations agent, Teams, the
    sign-in of the app's tool.
"""
from __future__ import annotations

from pathlib import Path

import json
import re

from .cloud import SQL_RESOURCE, UNREACHED, CloudError, FabricError, operation, run_notebook

from operations_agent import decode_definition, encode_definition  # noqa: E402  (found through the path .cloud sets)
from .core import Blocked, Options, Probe, Step, blocked, done, todo, unverified
from .steps import (DATA_AGENT, MODEL, NOTEBOOKS, ONTOLOGY, OPERATIONS_AGENT, REPORT, after, confirmation,
                    data_flow, freshness, gate_lakehouse, import_notebooks, instance, item, items, kql, kql_database, name,
                    need_item, notebook_probe, notebooks_probe, phase1, ran, run_kql_file, run_step, schedule_act,
                    scheduled_probe, script, tenant_settings, workspace_id)

PIP = "optin:pip-jobs"
INLINE_INSTALL = {"_inlineInstallationEnabled": {"value": "True", "type": "bool"}}
BY_HAND = ("In the workspace open the notebook {notebook} and select Run all. {expect}\n"
           "Then run the same apply again: it looks for {artifact}.")


def functions(ctx) -> set:
    return {row.get("Name") for row in kql(ctx, ".show functions | project Name")}


def tables(ctx) -> set:
    return {row.get("TableName") for row in kql(ctx, ".show tables | project TableName")}


def p2_views(ctx) -> Probe:
    if not kql_database(ctx):
        return after("p1.eventhouse")
    missing = {"Scada10Min", "AlarmIntervals", "GearboxVsFleet"} - functions(ctx)
    return todo("missing functions: " + ", ".join(sorted(missing))) if missing else done("three prepared views in the Eventhouse")


def pip_notebook(step_id: str, phase: str, title: str, notebook: str, prerequisite: str, options: Options, *,
                 artifact: tuple | None = None, expect: str = "", preview: str = "", optional: bool = False) -> Step:
    """A notebook whose first cell is %pip install. Run by the runner as a job, with %pip switched on by the parameter
    Microsoft documents for pipelines: not written for a run started through the API, and seen to work on a tenant on
    26 November 2026 (notebooks 06 to 09, at the first try). The operator's with --no-pip-jobs, and, for a notebook that
    uses a preview, until that preview is allowed.

    With an artifact (an item the notebook creates), the step is complete when the item is there, whoever ran the
    notebook. Without one, a run by the runner is recorded, and a run by hand is confirmed by the operator.
    """
    what = f"the {artifact[0]} {artifact[1]}" if artifact else "your confirmation"

    def probe(ctx) -> Probe:
        if not item(ctx, "Notebook", notebook):
            return after(prerequisite)
        if artifact:
            found = item(ctx, artifact[0], artifact[1])
            return done(f"{artifact[0]} {artifact[1]} exists") if found else todo()
        if ran(ctx, step_id, notebook):
            return done(f"{notebook} ran to the end")
        return confirmation(ctx, step_id, f"{notebook} run by hand")

    def manual(ctx) -> str:
        text = BY_HAND.format(notebook=notebook, expect=expect, artifact=what)
        if not artifact:
            text += f"\nThen: the apply line the plan ends with, and --confirm {step_id} added to it"
        if PIP not in options.granted:
            return text + "\nThe runner leaves this notebook to you because the plan was made with --no-pip-jobs."
        if preview and preview not in options.granted:
            return text + (f"\nThe runner runs this notebook itself once the preview it uses is allowed: --allow-preview "
                           f"{preview.split(':', 1)[1]}.")
        return text

    def act(ctx) -> None:
        try:
            run_notebook(ctx, workspace_id(ctx), need_item(ctx, "Notebook", notebook)["id"], notebook, INLINE_INSTALL)
        except CloudError as error:
            raise Blocked(f"The run of {notebook} as a job did not work: {error}",
                          BY_HAND.format(notebook=notebook, expect=expect, artifact=what)
                          + "\nIf the failure names %pip: that is the part Microsoft has not written down for a run started "
                          "through the API. Make the plan with --no-pip-jobs from now on, and send me the line.") from None

    tried = PIP in options.granted and (not preview or preview in options.granted) and not optional
    return Step(step_id, phase, title, probe, act if tried else None, manual=manual, optional=optional,
                inputs=(f"fabric/notebooks/{notebook}.ipynb",), observable=bool(artifact),
                writes=f"runs {notebook} as a job, with %pip switched on by the parameter Microsoft documents for pipelines"
                if tried else "",
                basis="Job Scheduler - Run On Demand Item Job; _inlineInstallationEnabled is documented for pipeline runs only",
                proof="none" if tried else "live")


def phase2(options: Options) -> list[Step]:
    gate_probe, gate_act = gate_lakehouse("phase2", "p2.gate", "p2.model_tables")
    return [
        Step("p2.prepared_views", "phase2", "Prepared views in the Eventhouse", p2_views,
             lambda ctx: run_kql_file(ctx, "fabric/kql/04-prepared-views.kql"), inputs=("fabric/kql/04-prepared-views.kql",),
             writes="three functions in the folder Prepared", basis="Kusto REST API, .create-or-alter function"),
        Step("p2.notebooks", "phase2", "Notebooks 05 to 08 imported", notebooks_probe("phase2", "p1.lakehouse"), import_notebooks("phase2"),
             inputs=tuple(f"fabric/notebooks/{n}.ipynb" for n in NOTEBOOKS["phase2"]), wait_seconds=60,
             writes="four notebooks, each with the Lakehouse as its default", basis="Notebook - Create Notebook (definition, ipynb)"),
        Step("p2.model_tables", "phase2", "Model tables built (notebook 05)",
             notebook_probe("p2.model_tables", "05_build_model_tables", "p2.notebooks"), run_step("05_build_model_tables"),
             observable=False, writes="the star schema in the Lakehouse", basis="Job Scheduler - Run On Demand Item Job (RunNotebook)"),
        pip_notebook("p2.semantic_model", "phase2", "Semantic model built (notebook 06)", "06_build_semantic_model", "p2.notebooks",
                     options, artifact=("SemanticModel", MODEL), expect="It builds the Direct Lake model WindFarm Operations."),
        pip_notebook("p2.acceptance", "phase2", "Model tested against the Lakehouse (notebook 07)", "07_model_acceptance",
                     "p2.notebooks", options, expect="Expect eleven lines that begin with PASS."),
        pip_notebook("p2.report", "phase2", "Report built (notebook 08)", "08_build_report", "p2.notebooks", options,
                     artifact=("Report", REPORT), expect="It builds the report WindFarm Operations Report."),
        Step("p2.schedule", "phase2", "Model tables refreshed every hour",
             scheduled_probe("p2.schedule", "05_build_model_tables", "p2.notebooks", False),
             schedule_act("05_build_model_tables", "hourly", False), writes="one hourly schedule for notebook 05",
             basis="Job Scheduler - Create Item Schedule (Cron, interval in minutes)"),
        Step("p2.gate", "phase2", "GATE: model tables populated", gate_probe, gate_act, observable=False,
             writes="one run of the gate notebook", basis="Job Scheduler - Run On Demand Item Job; the job's state is the verdict"),
    ]


def p3_capacity(ctx) -> Probe:
    from .steps import (CANNOT_HOLD, REGIONS_READ, capacity, capacity_kind, creating, new_capacity, region_gaps, region_name)
    needs = "The data agent and the operations agent need a paid capacity; on a trial they do not run"
    chosen = capacity(ctx)
    if not chosen and creating(ctx):
        chosen = {"sku": new_capacity(ctx)["sku"], "region": new_capacity(ctx)["region"]}      # not made yet; an F SKU is paid
    if not chosen:
        return unverified("the capacity is not in the list Fabric gives you, so the runner cannot read whether it is a paid "
                          f"one. {needs}")
    sku, kind = str(chosen.get("sku", "")), capacity_kind(chosen.get("sku"))
    move = ("Moving a workspace to another capacity is yours to decide and to do: workspace settings, License info. "
            "A workspace with items cannot move to a capacity in another region. Then set FABRIC_CAPACITY_ID and plan again.")
    if kind == "trial":
        return blocked(f"The capacity is a trial ({sku}). The data agent and the operations agent need a paid capacity.", move)
    if kind in CANNOT_HOLD:
        return blocked(f"The capacity ({sku}) is {CANNOT_HOLD[kind]}.",
                       "Put a capacity that can hold the demo into FABRIC_CAPACITY_ID: the step pre.capacity lists them.")
    if kind == "unknown":
        return unverified(f"the runner does not know the SKU {sku}. {needs}")
    missing = [feature for feature in region_gaps(chosen.get("region"), "phase3")]
    caution = (f". Microsoft's region table of {REGIONS_READ} lists no {' and no '.join(missing)} for a capacity in "
               f"{region_name(chosen.get('region'))}: the step that sets it up may not be possible there") if missing else ""
    return done(f"capacity SKU {sku}, a paid capacity{caution}")


OPERATIONS_AGENT_STEPS = f"""The operations agent is set up in the portal; Fabric has no documented way to create one with its playbook.
Follow step 9 of docs/09-deployment-guide-phase3.md:
1. In the workspace: New item, Operations agent, name {OPERATIONS_AGENT}.
2. Paste the text of fabric/operations-agent/agent-setup.txt into the one box; add the KQL database as its data source.
3. Generate the playbook, read its rules, and start the agent.
4. In Teams, install the app Fabric Operations Agent. The agent writes to the person who created it.
The runner looks for an item of type OperationsAgent with that name. It does not read or change the agent."""


# --------------------------------------------------------------------------- the operations agent, as far as an API goes
# Asked for on 26 November 2026 ("so there is no way to automate the creation of the two agents?", then the choice of the
# documented part). Microsoft's reference has Create Operations Agent, in preview and for a person only, with a definition
# that holds the instructions, the data source and the actions. For the playbook, which holds the rules, it says to send an
# empty object until its schema is published: the rules are generated in the portal, and reading and starting stay a
# person's. The part is named Configurations.json, as the definition article has it and as this tenant returned it on
# 24 November 2026.
AGENT_TEXT = "fabric/operations-agent/agent-setup.txt"
AGENT_PART = "Configurations.json"
AGENT_FORMAT = "OperationsAgentV1"
AGENT_YOURS = f"""The runner created the operations agent {OPERATIONS_AGENT} with its instructions and the KQL database as its data source, and left it stopped. The rules are yours: Fabric publishes no way to write a playbook.
1. In the workspace open {OPERATIONS_AGENT}. On Agent setup the instructions are filled in, and Knowledge names the KQL database.
2. Select Generate playbook. Read its rules before you start the agent; step 9 of docs/09-deployment-guide-phase3.md has the table to compare with: gearbox vibration crosses above 4, crosses above 5.5, gearbox oil temperature crosses above 72.
3. In Teams, install the app Fabric Operations Agent. The agent writes to the person who created it.
4. Back in Fabric, select Start.
Then run the same apply again: it reads the agent's definition, and looks for a playbook and for an agent that is started."""


def agent_document(ctx) -> dict:
    """The definition the runner creates the agent with: the documented fields, an empty playbook, stopped."""
    database = need_item(ctx, "KQLDatabase", name(ctx, "EVENTHOUSE_NAME"))["id"]
    return {"configuration": {"instructions": (ctx.root / AGENT_TEXT).read_text(encoding="utf-8"),
                              "dataSources": {database: {"id": database, "type": "KustoDatabase", "workspaceId": workspace_id(ctx)}},
                              "actions": {}},
            "playbook": {}, "shouldRun": False}


def act_create_agent(ctx) -> None:
    body = {"displayName": OPERATIONS_AGENT,
            "description": f"Northwind Ridge wind farm demo, deployment {ctx.cfg['DEPLOYMENT_SUFFIX']}: watches the gearboxes.",
            **encode_definition(AGENT_PART, agent_document(ctx))}
    body["definition"]["format"] = AGENT_FORMAT          # as the sample request of Create Operations Agent has it
    try:
        operation(ctx, "operations-agent", lambda: ctx.fabric.call("POST", f"workspaces/{workspace_id(ctx)}/operationsAgents", body))
    except CloudError as error:
        if error.code == UNREACHED:
            raise
        raise Blocked(f"Fabric did not create the operations agent from its definition: {error}",
                      OPERATIONS_AGENT_STEPS + "\nThat line of Fabric's is what to send me. The runner does not try another form of the request.") from None


def agent_state(ctx) -> dict:
    """What the agent's definition says of it: whether it has a playbook, how many rules, whether it is to run."""
    def read():
        found = item(ctx, "OperationsAgent", OPERATIONS_AGENT)
        answer = ctx.fabric.long_running("POST", f"workspaces/{workspace_id(ctx)}/operationsAgents/{found['id']}/getDefinition")
        _path, document = decode_definition(answer)
        playbook = document.get("playbook") or {}
        # The reference calls the playbook reserved. What this tenant returned on 24 November 2026 held its rules under
        # RuleDefinitions; a playbook without that key is counted as a playbook, and its rules are not.
        rules = next((playbook[key] for key in ("RuleDefinitions", "ruleDefinitions") if isinstance(playbook.get(key), list)), None)
        return {"playbook": bool(playbook), "rules": None if rules is None else len(rules), "running": document.get("shouldRun") is True}
    return ctx.remember("operations agent", read)


def p3_agent_started(ctx) -> Probe:
    if not workspace_id(ctx) or not item(ctx, "OperationsAgent", OPERATIONS_AGENT):
        return after("p3.operations_agent_item")
    try:
        state = agent_state(ctx)
    except (CloudError, FabricError) as error:
        if getattr(error, "code", "") == UNREACHED:
            raise
        return unverified(f"an item {OPERATIONS_AGENT} exists, and its definition could not be read ({error}). That is not proof "
                          "that the agent has a playbook or is started")
    if not state["playbook"] or state["rules"] == 0:
        return todo("the agent has no playbook yet")
    rules = "a playbook" if state["rules"] is None else f"a playbook with {state['rules']} rule{'s' if state['rules'] != 1 else ''}"
    if not state["running"]:
        return todo(f"the agent has {rules} and is not started")
    return done(f"operations agent {OPERATIONS_AGENT}: {rules}, started. Whether its message reaches Teams, the runner cannot read")


def agent_steps_with_the_api() -> list[Step]:
    return [
        Step("p3.operations_agent_item", "phase3", "Operations agent created, with its instructions and its data source",
             lambda ctx: (done(f"operations agent {OPERATIONS_AGENT} exists") if item(ctx, "OperationsAgent", OPERATIONS_AGENT) else todo())
             if workspace_id(ctx) and item(ctx, "KQLDatabase", name(ctx, "EVENTHOUSE_NAME")) else after("p1.eventhouse"),
             act_create_agent, needs=("preview:operations-agent",), inputs=(AGENT_TEXT,), wait_seconds=60,
             writes=f"the operations agent {OPERATIONS_AGENT}: the instructions of {AGENT_TEXT}, the KQL database as its data source, "
                    "no action, no playbook, not started",
             basis="Operations Agent - Create Operations Agent (preview, a person only); Operations agent definition", proof="none"),
        Step("p3.operations_agent", "phase3", "Operations agent: playbook generated and read, agent started, Teams app installed",
             p3_agent_started, manual=AGENT_YOURS,
             basis="Operations Agent - Get Operations Agent Definition (preview), for the look; the playbook and the start: portal only",
             proof="none"),
    ]


def phase3(options: Options) -> list[Step]:
    settings_probe, settings_manual = tenant_settings("phase3")
    preview_agent = "preview:data-agent-sdk"
    ontology_allowed = "preview:ontology" in options.granted

    def ontology_probe(ctx) -> Probe:
        if not item(ctx, "Notebook", "11_build_ontology"):
            return after("p3.notebooks")
        found = [entry for entry in items(ctx) if entry.get("displayName") == ONTOLOGY and entry.get("type") == "Ontology"]
        return done(f"ontology {ONTOLOGY} exists") if found else todo()

    return [
        Step("p3.capacity", "phase3", "A paid capacity for the agents", p3_capacity, basis="GET /v1/capacities"),
        Step("phase3.tenant_settings", "phase3", "Tenant settings for Phase 3", settings_probe, manual=settings_manual,
             observable=False, basis="Fabric admin portal", proof="none"),
        Step("p3.notebooks", "phase3", "Notebooks 09 to 11 imported", notebooks_probe("phase3", "p1.lakehouse"), import_notebooks("phase3"),
             inputs=tuple(f"fabric/notebooks/{n}.ipynb" for n in NOTEBOOKS["phase3"]), wait_seconds=60,
             writes="three notebooks", basis="Notebook - Create Notebook (definition, ipynb)"),
        pip_notebook("p3.data_agent", "phase3", "Data agent built (notebook 09)", "09_build_data_agent", "p3.notebooks", options,
                     artifact=("DataAgent", DATA_AGENT), preview=preview_agent,
                     expect="It creates and publishes the data agent with a pre-release of Microsoft's SDK (0.1.36a0)."),
        pip_notebook("p3.data_agent_test", "phase3", "Data agent tested (notebook 10)", "10_test_data_agent", "p3.notebooks",
                     options, optional=True, expect="About 39 of 52 questions pass; one run is good to about two questions."),
        Step("p3.ontology", "phase3", "Ontology built (notebook 11, preview)", ontology_probe,
             run_step("11_build_ontology") if ontology_allowed else None, optional=not ontology_allowed,
             needs=("preview:ontology",), inputs=("fabric/notebooks/11_build_ontology.ipynb",),
             manual="The ontology is a preview feature, and the notebook writes the old ontology experience, which retires on 31 "
             "January 2027. The demo's data agent runs without it. To have the runner build it: --allow-preview ontology. "
             "By hand: open 11_build_ontology and select Run all.",
             writes="runs notebook 11, which creates the ontology item", basis="Job Scheduler - Run On Demand Item Job (RunNotebook)",
             proof="none"),
        Step("p3.agent_readiness", "phase3", "KQL database prepared for the operations agent",
             lambda ctx: (done("table GearboxVsFleetLive and its update policy") if "GearboxVsFleetLive" in tables(ctx) else todo())
             if kql_database(ctx) else after("p1.eventhouse"),
             lambda ctx: run_kql_file(ctx, "fabric/kql/05-agent-readiness.kql"), inputs=("fabric/kql/05-agent-readiness.kql",),
             writes="descriptions of the columns, and the table GearboxVsFleetLive with its update policy",
             basis="Kusto REST API, .execute database script"),
        *(agent_steps_with_the_api() if "preview:operations-agent" in options.granted else [
            Step("p3.operations_agent", "phase3", "Operations agent set up and started, Teams app installed",
                 lambda ctx: (done(f"an item {OPERATIONS_AGENT} exists. That is not proof that the agent is configured, running or "
                                   "delivering to Teams: the runner cannot read any of that")
                              if item(ctx, "OperationsAgent", OPERATIONS_AGENT) else todo()) if workspace_id(ctx) else after("p1.workspace"),
                 manual=OPERATIONS_AGENT_STEPS + "\nTo have the runner create the agent with its instructions and its data source, so that "
                 "only the playbook and the start are yours: --allow-preview operations-agent.",
                 basis="none: portal only (preview)", proof="live")]),
    ]


def build_stamp(ctx, relative: str) -> str:
    path = ctx.root / relative
    found = re.search(r"'([0-9a-f]{12})'", path.read_text(encoding="utf-8")) if path.exists() else None
    return found.group(1) if found else ""


def p4_node(ctx) -> Probe:
    code, text = ctx.shell.capture(["node", "--version"])
    major = int((re.search(r"v(\d+)", text) or [0, 0])[1]) if code == 0 else 0
    if major not in (20, 22, 24):
        return blocked(f"Node.js is {text.strip() or 'not installed'}. The app's tool lists 20, 22 and 24.",
                       "Install Node.js 22 as in step 2 of docs/11-deployment-guide-phase4.md.")
    return done(f"Node.js {text.strip()}")


def app_dir(ctx) -> Path:
    """Where this deployment's app is built: a folder of its own beside its checkpoint. Two deployments of one folder
    never share a build: the app's copy of config.ts names one workspace, and the app's tool keeps its own state there."""
    return ctx.state.folder / "app" / "windfarm-twin"


def app_label(ctx) -> str:
    return f".deploy/{ctx.cfg['DEPLOYMENT_SUFFIX']}/app/windfarm-twin"


def p4_scaffold(ctx) -> Probe:
    ours = build_stamp(ctx, "app/overlay/packages/functions/src/build.ts")
    stamp, config = app_dir(ctx) / "packages/functions/src/build.ts", app_dir(ctx) / "packages/functions/src/config.ts"
    found = re.search(r"'([0-9a-f]{12})'", stamp.read_text(encoding="utf-8")) if stamp.exists() else None
    theirs = found.group(1) if found else ""
    if not theirs:
        return todo()
    if theirs != ours:
        return todo(f"the app holds build {theirs}; the repository is at {ours}")
    if f"WORKSPACE_NAME = '{ctx.cfg['FABRIC_WORKSPACE_NAME']}'" not in config.read_text(encoding="utf-8"):
        return todo("the app names another workspace")
    return done(f"app scaffolded in {app_label(ctx)}, build {ours}, looking for workspace {ctx.cfg['FABRIC_WORKSPACE_NAME']}")


def app_item(ctx) -> dict | None:
    data_kinds = {"Notebook", "Lakehouse", "Eventhouse", "KQLDatabase", "Eventstream", "SemanticModel", "Report", "SQLEndpoint"}
    found = [entry for entry in items(ctx) if entry.get("displayName") == name(ctx, "APP_NAME") and entry.get("type") not in data_kinds]
    return found[0] if len(found) == 1 else None


SIGN_IN = ("cd {app} && export RAYFIN_ENCRYPTION_FALLBACK_ENABLED=true && npx rayfin login\n"
           "(The export is for WSL, which has no keychain; it lets the tool keep your sign-in unencrypted under ~/.rayfin. "
           "The runner does not set it for you. On WSL no browser opens by itself: step 4 of docs/11-deployment-guide-phase4.md.)")


def act_deploy_app(ctx) -> None:
    workspace_name = ctx.cfg["FABRIC_WORKSPACE_NAME"]
    same = [w for w in ctx.fabric.listing("workspaces") if w.get("displayName") == workspace_name]
    if len(same) != 1 or same[0].get("id") != workspace_id(ctx):
        raise Blocked(f"The app's tool takes the workspace by name, and the name {workspace_name} stands for {len(same)} "
                      "workspaces you can see, or for another one than this deployment's.", "Rename or remove the other workspace.")
    code, text = ctx.shell.run(["npx", "rayfin", "up", "--workspace", workspace_name, "--item-name", name(ctx, "APP_NAME")],
                               cwd=app_dir(ctx))
    if code != 0:
        if re.search(r"(?i)sign[ -]?in|log ?in|keychain|unauthor|401", text):
            raise Blocked("The app's tool is not signed in. Signing in opens a browser and is yours to do.", SIGN_IN.format(app=app_label(ctx)))
        raise CloudError(f"npx rayfin up ended with exit code {code}. Its last lines are above; it names a diagnostic log.")
    ctx.state.note("p4.deploy", up_at=ctx.state.now())


# ------------------------------------------------------------------------------- the live route: a service principal
# A Fabric app runs as its owner and gets no token the Eventhouse accepts (Phase 4, 23 November 2026). With a service
# principal the twin reads the Eventhouse, seconds behind the turbines; without one it reads the Lakehouse's copy, minutes
# behind. Asked for as a step of the runner on 26 November 2026: "I need the demo to run as in the previous run (live from
# KQL and delayed with lakehouse)". The runner starts app/create-principal.sh, which ran on a tenant on 23 November.
PRINCIPAL = "windfarm-twin-eventhouse-reader"
REDEPLOY_GAP = 150       # seconds between two deployments of an app's functions (Rayfin's guide says two minutes)
WITHOUT = ("To go on without the live route, with the twin on the Lakehouse's copy: make the plan again with --lakehouse-only.")


def principal_name(ctx) -> str:
    """A registration of the deployment's own. Making a secret replaces the one before it, so a registration shared with
    another deployment would take that deployment's twin off its live route."""
    return f"{PRINCIPAL}-{ctx.cfg['DEPLOYMENT_SUFFIX']}"


def principal(ctx) -> dict:
    """What Microsoft Entra ID holds under that name: read through Microsoft Graph, in the deployment's tenant."""
    def read():
        listed = ctx.az.graph(f"applications?$filter=displayName%20eq%20'{principal_name(ctx)}'&$select=appId,passwordCredentials")
        found = (listed or {}).get("value") or []
        if len(found) != 1:
            return {"count": len(found)}
        holder = ctx.az.graph(f"servicePrincipals(appId='{found[0]['appId']}')?$select=id") or {}
        return {"count": 1, "app_id": found[0]["appId"], "object_id": holder.get("id", ""),
                "secrets": sorted((key.get("startDateTime") or "", key.get("endDateTime") or "")
                                  for key in found[0].get("passwordCredentials") or [])}
    return ctx.remember("principal", read)


def p4_principal(ctx) -> Probe:
    if not workspace_id(ctx) or not app_item(ctx):
        return after("p4.deploy")
    label = principal_name(ctx)
    try:
        known = principal(ctx)
    except CloudError as error:
        if error.code == UNREACHED:
            raise
        return blocked(f"Microsoft Entra ID did not say whether the app registration {label} exists: {error}", WITHOUT)
    if known["count"] > 1:
        return blocked(f"{known['count']} app registrations are named {label}. The runner takes none of them for its own.",
                       "Microsoft Entra admin center, App registrations: rename or delete the ones that are not this deployment's.")
    if not known["count"]:
        return todo(f"no app registration named {label} yet")
    if not known["object_id"]:
        return todo(f"the app registration {label} has no service principal yet")
    roles = {(entry.get("principal") or {}).get("id"): entry.get("role") for entry in
             ctx.remember("access", lambda: ctx.fabric.listing(f"workspaces/{workspace_id(ctx)}/roleAssignments"))}
    if not roles.get(known["object_id"]):
        return todo(f"the service principal {label} has no role in the workspace yet")
    now = ctx.state.stamp()[:19]
    if not [end for _start, end in known["secrets"] if end[:19] > now]:
        return todo(f"the app registration {label} has no client secret that is still valid")
    saved = ctx.state.step("p4.eventhouse_principal").get("evidence") or {}
    if saved.get("secret_start") != known["secrets"][-1][0]:
        # The runner never sees the secret. What it can compare is when the registration's newest secret was made.
        return todo("the app has not been handed the registration's present secret by this deployment")
    return done(f"service principal {label} ({known['app_id']}): {roles[known['object_id']]} in the workspace, its secret "
                f"handed to the app on {saved.get('handed_at', 'an earlier run')}", app_id=known["app_id"])


def act_principal(ctx) -> None:
    label, leftover = principal_name(ctx), app_dir(ctx) / "rayfin" / ".env.secrets"
    try:
        before = (principal(ctx).get("secrets") or [("", "")])[-1][0]
    except CloudError as error:
        raise Blocked(f"Microsoft Entra ID did not answer about the app registration {label}: {error}", WITHOUT) from None
    try:
        code, text = ctx.shell.run(["bash", "app/create-principal.sh"], env={
            "ENV_FILE": str(ctx.env_file), "AZ_SUBSCRIPTION_PIN": ctx.cfg.get("SUBSCRIPTION_ID", ""), "PRINCIPAL_NAME": label,
            "FABRIC_WORKSPACE_NAME": ctx.cfg["FABRIC_WORKSPACE_NAME"], "APP_DIR": str(app_dir(ctx))})
    finally:
        if leftover.exists():       # the script removes the file it hands to the app's tool; a run that was stopped may not have
            leftover.unlink()
    if code != 0:
        said = next((row.strip() for row in reversed(text.splitlines()) if row.strip().startswith("STOP:")), "")[6:300]
        if "Rayfin did not take the secrets" in text:
            raise Blocked("The app's tool did not take the secrets. Most likely it is not signed in.", SIGN_IN.format(app=app_label(ctx)))
        if "active subscription is in tenant" in text:
            raise Blocked(said, f"az account set --subscription {ctx.cfg.get('SUBSCRIPTION_ID', '')}")
        if re.search(r"was not created|No secret was made|may not read app registrations", text):
            raise Blocked(f"Microsoft Entra ID did not let you make the app registration or its secret. {said}",
                          "Ask an administrator of the directory for the right to register applications (the role Application "
                          "Developer), or for the registration itself.\n" + WITHOUT)
        if "The role was not given" in text:
            raise Blocked(said, "You need the Admin or Member role in the workspace. Then run apply again.")
        raise CloudError(f"bash app/create-principal.sh ended with exit code {code}. Its last lines are above.")
    # The script made a new secret and handed it to the app. Which one, the runner knows only by its time in the directory.
    deadline = ctx.clock() + 120
    while True:
        ctx.cache.clear()
        newest = (principal(ctx).get("secrets") or [("", "")])[-1][0]
        if newest and newest != before:
            break
        if ctx.clock() >= deadline:
            raise CloudError(f"The secret was made and handed to the app, and Microsoft Entra ID does not list it yet under {label}. "
                             "Run apply again: it makes a new one and looks again.")
        ctx.sleep(ctx.options.limits["poll"])
    ctx.state.note("p4.eventhouse_principal", secret_start=newest, handed_at=ctx.state.stamp())


def p4_redeploy(ctx) -> Probe:
    handed = (ctx.state.step("p4.eventhouse_principal").get("evidence") or {}).get("secret_start")
    if ctx.state.step("p4.eventhouse_principal").get("status") != "complete" or not handed:
        return after("p4.eventhouse_principal")
    mine = (ctx.state.step("p4.deploy_secrets").get("evidence") or {}).get("deployed_for")
    if mine != handed:
        return todo("the app has not been deployed since its secrets were set")
    return done("the app was deployed again after its secrets were set")


def act_redeploy(ctx) -> None:
    handed = (ctx.state.step("p4.eventhouse_principal").get("evidence") or {}).get("secret_start")
    last = (ctx.state.step("p4.deploy").get("evidence") or {}).get("up_at")
    gap = REDEPLOY_GAP - (ctx.state.now() - last) if last else 0
    if 0 < gap <= REDEPLOY_GAP:
        ctx.say(f"      waiting {gap:.0f} s: an app's functions are not deployed twice within two minutes")
        ctx.sleep(gap)
    act_deploy_app(ctx)
    ctx.state.note("p4.deploy_secrets", deployed_for=handed)


def lakehouse_route(ctx) -> dict:
    """Asks the SQL endpoint of the Lakehouse what the twin's fallback route asks it, as the signed-in person."""
    ws = workspace_id(ctx)
    lakehouse = need_item(ctx, "Lakehouse", name(ctx, "FABRIC_LAKEHOUSE_NAME"))
    details = ctx.fabric.get(f"workspaces/{ws}/lakehouses/{lakehouse['id']}") or {}
    server = (((details.get("properties") or {}).get("sqlEndpointProperties")) or {}).get("connectionString")
    if not server:
        raise Blocked("The Lakehouse has no SQL endpoint yet.", "It is made a few minutes after the Lakehouse. Run apply again.")
    code, text = ctx.shell.capture(["node", "app/probe-lakehouse-route.mjs"], env={
        "SQL_SERVER": server, "SQL_DATABASE": lakehouse["displayName"], "SQL_TOKEN": ctx.az.token(SQL_RESOURCE)})
    try:
        return json.loads(text.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": ctx.redact(text.strip()[-400:]) or f"the probe ended with exit code {code}"}


def gate_route_act(ctx) -> None:
    seen = lakehouse_route(ctx)
    if seen.get("error") or not seen.get("rows"):
        raise Blocked(f"Lakehouse route: {seen.get('error') or 'the query ran and found no telemetry in the last 60 minutes'}.",
                      "If the Eventhouse has fresh telemetry (python3 tools/deploy.py status), the SQL endpoint is only behind, which "
                      "it is after a time without use: run apply again in a few minutes. Seen on 25 November 2026: no rows, and "
                      "7,548 rows three and a half minutes later.")
    live = freshness(ctx) if data_flow(ctx) else {}
    ctx.state.note("p4.gate_data_route", passed=(
        f"SQL probe with the operator's token: {seen['rows']} rows from {seen.get('turbines')} turbines in the last 60 minutes, the "
        f"newest {seen.get('newest_minutes')} min old. It asks what the twin's Lakehouse route asks, as you and not as the app: "
        f"it shows the data is there, not that the deployed app reads it. Eventhouse: newest reading {live.get('age_seconds', '?')} s old"),
        route="lakehouse", figures=seen)


def gate_route_probe(ctx) -> Probe:
    saved = (ctx.state.step("p4.gate_data_route").get("evidence") or {})
    if saved.get("passed"):
        return done(saved["passed"])
    return todo() if app_item(ctx) else after("p4.deploy")


def phase4(options: Options) -> list[Step]:
    settings_probe, settings_manual = tenant_settings("phase4")
    check_lakehouse = Step("p4.connection_check", "phase4", "The app's own connection check: what makes the twin demo-ready",
             lambda ctx: todo("yours to read, once: the runner has no documented way to ask the deployed app"), optional=True,
             observable=False,
             manual="Open the app in the workspace and select the badge at the top right. Read three things off the check: the "
             "build it names, the route that says PASS (Lakehouse, or Eventhouse with the service principal), and how old the "
             "newest reading is.\nThen tell the runner, with the next apply: --app-check BUILD,ROUTE,SECONDS   for example "
             "--app-check 455aa9777780,lakehouse,120\nstatus calls the twin demo-ready only with that, for the build that is deployed.",
             basis="the app", proof="live")
    check_live = Step("p4.connection_check", "phase4", "The app's own connection check: what makes the twin demo-ready",
             lambda ctx: todo("yours to read, once: the runner has no documented way to ask the deployed app"), optional=True,
             observable=False,
             manual="Open the app in the workspace and select the badge at the top right. Read three things off the check: the "
             "build it names, the route that says PASS, and how old the newest reading is. With the service principal that is the "
             "Eventhouse route; the Lakehouse route is what the twin falls back to.\nThen tell the runner, with the next apply: "
             "--app-check BUILD,ROUTE,SECONDS   for example --app-check 455aa9777780,eventhouse,40\nstatus calls the twin demo-ready only with that, for the build that is deployed.",
             basis="the app", proof="live")
    live = [
        Step("p4.eventhouse_principal", "phase4", "Real-time values: a service principal that reads the Eventhouse", p4_principal, act_principal,
             needs=("roles",), wait_seconds=120, inputs=("app/create-principal.sh",),
             writes="in Microsoft Entra ID: one app registration named windfarm-twin-eventhouse-reader-<suffix>, its service principal, and "
                    "one client secret valid for a year, which replaces any earlier secret of that registration. In Fabric: the Viewer "
                    "role for that principal in the demo's workspace, and three secrets of the app. The secret is never shown or stored",
             basis="app/create-principal.sh (az ad app create, az ad sp create, az ad app credential reset; Workspaces - Add Workspace "
                   "Role Assignment; npx rayfin secret set); read with Microsoft Graph, GET /applications", proof="live"),
        Step("p4.deploy_secrets", "phase4", "App deployed again, so that its functions read the secrets", p4_redeploy, act_redeploy,
             observable=False, writes="the app's page and functions, deployed a second time",
             basis="npx rayfin up --workspace NAME --item-name NAME (Rayfin 2.0.1)", proof="live"),
    ]
    lakehouse_only = [
        Step("p4.eventhouse_principal", "phase4", "Real-time values: the service principal (left out with --lakehouse-only)",
             lambda ctx: todo("not looked at: optional, and the runner neither creates an app registration nor grants it a role"),
             optional=True, observable=False, manual="When you want the twin 40 seconds behind the turbines instead of minutes:\n"
             "bash app/create-principal.sh\nIt finds the workspace and the app folder of the current deployment by itself, creates an app registration with a secret and gives "
             "it Viewer in the workspace; step 7 of docs/11-deployment-guide-phase4.md. Without it the twin runs on the Lakehouse route.",
             basis="app/create-principal.sh", proof="live"),
    ]
    return [
        Step("phase4.tenant_settings", "phase4", "Tenant setting Fabric Apps", settings_probe, manual=settings_manual,
             observable=False, basis="Fabric admin portal", proof="none"),
        Step("p4.node", "phase4", "Node.js on this computer", p4_node, basis="node --version"),
        Step("p4.scaffold", "phase4", "App created from Microsoft's template, with the twin laid over it", p4_scaffold,
             lambda ctx: script(ctx, "app/create-app.sh", env={"FABRIC_WORKSPACE_NAME": ctx.cfg["FABRIC_WORKSPACE_NAME"],
                                                              "APP_DIR": str(app_dir(ctx))}),
             inputs=("app/create-app.sh", "app/overlay/packages/functions/src/build.ts"),
             writes="the app's folder of this deployment on this computer, .deploy/<suffix>/app/windfarm-twin; nothing in Fabric",
             basis="app/create-app.sh", proof="live"),
        Step("p4.deploy", "phase4", "App deployed to the workspace",
             lambda ctx: (done(f"app item {name(ctx, 'APP_NAME')} is in the workspace") if app_item(ctx) else todo())
             if workspace_id(ctx) else after("p1.workspace"), act_deploy_app, wait_seconds=120, inputs=("app/overlay",),
             writes="the Fabric app item WindFarmTwin, its page and its seven functions",
             basis="npx rayfin up --workspace NAME --item-name NAME (Rayfin 2.0.1)", proof="live"),
        *([] if options.lakehouse_only else live),
        Step("p4.gate_data_route", "phase4", "GATE: the Lakehouse answers the twin's query (asked with the operator's token)", gate_route_probe, gate_route_act,
             observable=False, writes="nothing; one query against the SQL endpoint of the Lakehouse",
             basis="SQL analytics endpoint, with a token for https://database.windows.net", proof="offline"),
        *(lakehouse_only if options.lakehouse_only else []),
        check_lakehouse if options.lakehouse_only else check_live,
    ]


def command_flow(ctx) -> dict | None:
    return ctx.remember("commandflow", lambda: ctx.az.maybe(
        "iot", "ops", "dataflow", "show", "--resource-group", ctx.cfg["RESOURCE_GROUP"], "--instance", ctx.cfg["AIO_INSTANCE_NAME"],
        "--profile", "default", "--name", "fabric-to-windfarm-control"))


def p5a_command_path(ctx) -> Probe:
    if not instance(ctx) or not workspace_id(ctx):
        return after("p1.iot_operations and p1.workspace")
    flow = command_flow(ctx)
    if not flow:
        return todo()
    mode = (flow.get("properties") or {}).get("mode", "Enabled")
    if mode == "Disabled":
        return done("command path in place and switched off: no command reaches the simulator")
    return done("command path in place and SWITCHED ON. The runner created it switched off; a person enabled it")


ENABLE = """The command path exists and is switched off. Switching it on, and every command, is yours:
  bash infra/08-create-command-path.sh        switches the data flow on
  then docs/12-deployment-guide-phase5a.md from step 3 (watch the control topic, send one command with notebook 12)
The runner never runs notebook 12 or 13, never publishes to the control topic and never injects a fault."""


def phase5a(options: Options) -> list[Step]:
    return [
        Step("p5a.isolation", "phase5a", "This edge is an isolated simulator",
             lambda ctx: confirmation(ctx, "p5a.isolation", "isolated simulator") if instance(ctx) else after("p1.iot_operations"),
             manual=lambda ctx: (
                 f"Phase 5a builds a path on which a message from Fabric becomes a command on the MQTT broker of {ctx.cfg['AIO_INSTANCE_NAME']}.\n"
                 "Confirm that nothing but this demo's simulator listens on that broker: no real controller, no other bridge.\n"
                 "The runner can see that it made this instance itself; it cannot see what else was connected to it since.\n"
                 "Then: the apply line the plan ends with, and --confirm p5a.isolation added to it"),
             observable=False, basis="none: a statement only a person can make", proof="none"),
        Step("p5a.command_path", "phase5a", "Command path provisioned, switched off", p5a_command_path,
             lambda ctx: script(ctx, "infra/08-create-command-path.sh", env={"COMMAND_DATAFLOW_MODE": "Disabled"}),
             inputs=("infra/08-create-command-path.sh", "edge/dataflows/fabric-to-windfarm-control.template.json"), wait_seconds=120,
             writes="eventstream WindFarmCommands, endpoint fabric-commands, and the data flow fabric-to-windfarm-control with mode Disabled",
             basis="infra/08-create-command-path.sh; az iot ops dataflow apply with \"mode\": \"Disabled\"", proof="offline"),
        Step("p5a.notebook", "phase5a", "Notebook 12 imported, not run", notebooks_probe("phase5a", "p1.lakehouse"), import_notebooks("phase5a"),
             inputs=("fabric/notebooks/12_send_edge_command.ipynb",), wait_seconds=60,
             writes="imports the notebook. It is never run by the runner", basis="Notebook - Create Notebook (definition, ipynb)"),
        Step("p5a.enable", "phase5a", "Switch the command path on and send a command (yours)", lambda ctx: todo("yours"),
             optional=True, observable=False, manual=ENABLE, basis="docs/12-deployment-guide-phase5a.md", proof="live"),
    ]


PREREQUISITES = {"p3.capacity", "phase3.tenant_settings", "phase4.tenant_settings", "p4.node", "p5a.isolation"}


def catalogue(options: Options) -> list[Step]:
    steps = phase1() + phase2(options) + phase3(options) + phase4(options) + phase5a(options)
    seen = set()
    for step in steps:
        assert step.id not in seen, f"two steps are named {step.id}"
        seen.add(step.id)
        step.prerequisite = step.phase == "preflight" or step.id in PREREQUISITES
    return steps
