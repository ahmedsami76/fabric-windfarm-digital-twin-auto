"""What the command center notebook (13_command_center) needs besides building a command: reading the
turbines' state from the KQL database, reading what the edge logged about a command (Phase 5c), and
telling from the telemetry whether the command took effect.

tools/build-phase5.py copies this file into the notebook, after tools/edge_command.py. It uses the
standard library only and nothing of edge_command, so that the tests can load it by itself.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timezone

TURBINES = [f"WT-{number:02d}" for number in range(1, 13)]
RATED_KW = 4200.0          # data/reference/turbines.csv; a test compares
WAIT_SECONDS = 150         # how long a command is waited for in the telemetry
POLL_SECONDS = 5
STOPPED = ("STOPPED", "MAINTENANCE")


def rows_of(body) -> list[dict]:
    """The rows of the first table of the KQL database's answer (REST, version 1), keyed by column name."""
    tables = (body or {}).get("Tables") if isinstance(body, dict) else None
    table = tables[0] if isinstance(tables, list) and tables else None
    if not isinstance(table, dict) or not isinstance(table.get("Columns"), list) or not isinstance(table.get("Rows"), list):
        raise RuntimeError("The KQL database answered in a form this notebook does not know (no Tables[0]).")
    names = [column.get("ColumnName") for column in table["Columns"]]
    rows = []
    for row in table["Rows"]:
        if not isinstance(row, list):       # a failure inside a result arrives as an object in place of a row
            raise RuntimeError(f"The KQL database reported a failure inside the result: {str(row)[:300]}")
        rows.append(dict(zip(names, row)))
    return rows


def targets_of(turbine: str) -> list[str]:
    """The turbines a command or a question is about. Refuses anything that is not a turbine or the word all."""
    name = str(turbine or "").strip()
    if name.lower() == "all":
        return list(TURBINES)
    if name.upper() not in TURBINES:
        raise ValueError(f"'{turbine}' is not a turbine. Use WT-01 to WT-12, or the word all.")
    return [name.upper()]


def _in_list(turbines: list[str]) -> str:
    return ", ".join(f"'{name}'" for name in turbines)


def status_query(turbine: str = "all") -> str:
    return f"""TurbineTelemetry
| where Timestamp > ago(10m) and TurbineId in ({_in_list(targets_of(turbine))})
| summarize arg_max(Timestamp, State, PowerSetpoint, ActivePower, WindSpeed, GearboxVibration, GearboxOilTemp) by TurbineId
| extend AgeSeconds = toint((now() - Timestamp) / 1s)
| order by TurbineId asc"""


def effect_query(turbine: str, since: str = "") -> str:
    """The newest reading of each turbine the command names: of the last five minutes, or, with `since`
    (the command's issuedAt), only readings taken after the command was written."""
    start = f"datetime({since})" if since else "ago(5m)"
    return f"""TurbineTelemetry
| where Timestamp >= {start} and TurbineId in ({_in_list(targets_of(turbine))})
| summarize arg_max(Timestamp, State, PowerSetpoint, ActivePower) by TurbineId
| extend AgeSeconds = toint((now() - Timestamp) / 1s)"""


def log_query(request_id: str) -> str:
    """What the edge logged about one command (table EdgeCommands, Phase 5c), and whether that table exists.

    One row with Kind 'log' says the table is there; rows with Kind 'command' are the edge's entries
    for this request, one for each turbine. The union is fuzzy so that the query also runs on a
    database that has no command log yet: the two parts that read the table are then left out.
    """
    wanted = "".join(c for c in str(request_id) if c.isalnum() or c in "-_")[:64]
    return f"""union isfuzzy=true
    (print Kind = 'asked', TurbineId = '', Ok = bool(null), Error = '', Timestamp = datetime(null), IssuedAt = datetime(null), RequestedBy = ''),
    (EdgeCommands | count | project Kind = 'log'),
    (EdgeCommands | where Timestamp > ago(1h) and RequestId == '{wanted}' | extend Kind = 'command')
| where Kind != 'asked'
| extend FabricToEdgeSeconds = datetime_diff('second', Timestamp, IssuedAt)
| project Kind, TurbineId, Ok, Error, Timestamp, FabricToEdgeSeconds, RequestedBy
| order by Kind desc, TurbineId asc"""


def log_of(rows: list[dict]) -> tuple[bool, list[dict]]:
    """From the rows of log_query: is there a command log in this database, and the edge's entries."""
    return any(row.get("Kind") == "log" for row in rows), [row for row in rows if row.get("Kind") == "command"]


def history_query(lookback: str = "1h", turbine: str = "all") -> str:
    """The commands of the last hour or so with what became of them (function CommandLog, Phase 5c)."""
    span = str(lookback).strip().lower()
    if not re.fullmatch(r"[1-9]\d{0,2}[mhd]", span):
        raise ValueError(f"'{lookback}' is not a time span. Write it as 30m, 6h or 2d.")
    names = targets_of(turbine) + ["EDGE-01"]      # a refused command that named no turbine is logged under the edge
    return f"""CommandLog({span})
| where TurbineId in ({_in_list(names)})
| project Timestamp, TurbineId, Command, Status, LimitKw, EndsAt, RequestedBy, Source, FabricToEdgeSeconds, EdgeToTelemetrySeconds, Error
| order by Timestamp desc, TurbineId asc
| take 60"""


def by_turbine(rows: list[dict]) -> dict:
    return {row.get("TurbineId"): row for row in rows}


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number else None      # NaN is no number


def holds(cmd: dict, row) -> bool:
    """Does this reading show the command in force?"""
    if not row:
        return False
    state, setpoint = row.get("State"), _number(row.get("PowerSetpoint"))
    name = cmd["command"]
    if name == "curtail":
        return setpoint is not None and setpoint <= RATED_KW * float(cmd["percent"]) / 100.0 + 1.0
    if name == "release":
        return state != "CURTAILED"
    if name == "stop":
        return state in STOPPED
    if name == "start":
        return state not in STOPPED
    return state != "FAULT"                            # reset


def what(cmd: dict) -> str:
    name = cmd["command"]
    if name == "curtail":
        return f"limit of {RATED_KW * float(cmd['percent']) / 100.0:.0f} kW in force"
    return {"release": "limit lifted", "stop": "stopped", "start": "running again or free to run", "reset": "trip cleared"}[name]


def _reading(row) -> str:
    if not row:
        return "no reading"
    setpoint, power = _number(row.get("PowerSetpoint")), _number(row.get("ActivePower"))
    parts = [f"state {row.get('State')}"]
    if setpoint is not None:
        parts.append(f"setpoint {setpoint:.0f} kW")
    if power is not None:
        parts.append(f"power {power:.0f} kW")
    if row.get("Timestamp"):
        parts.append(f"reading of {str(row['Timestamp'])[11:19]}Z")
    return ", ".join(parts)


NO_LOG = "This database has no command log yet (Phase 5c: run block 1 of fabric/kql/07-command-log.kql)."


def _edge_says(row) -> str:
    seconds = _number(row.get("FabricToEdgeSeconds"))
    # Two clocks are in this number, the sender's and the edge's. Below zero it says only that they differ.
    took = "" if seconds is None or seconds < 0 else f" {seconds:.0f} s after it was written"
    at = f" (at {str(row['Timestamp'])[11:19]}Z)" if row.get("Timestamp") else ""
    return f"the edge took the command{took}{at}"


def follow(cmd: dict, before: dict, read, clock=time.monotonic, sleep=time.sleep, say=print,
           limit: float = WAIT_SECONDS, step: float = POLL_SECONDS, log=None) -> bool | None:
    """Wait until the edge's log and the telemetry show the command, and say how long each took.

    `before` holds the newest reading of each turbine from before the send, `read()` returns the newest
    readings taken after it. `log()`, when given, returns (is there a command log, the edge's entries
    for this command) as log_of does. With a log the edge's own word comes first: it took the command,
    or it refused it and why. Without one (a database from before Phase 5c) the telemetry is all there is.

    A turbine whose reading already looked like the command's effect before the send proves nothing
    by its telemetry afterwards. With the log, the edge's entry settles it; without, it is named as
    such and not counted as confirmed.
    Returns True when every turbine is settled, False when the edge refused the command or the time
    ran out, and None when there was nothing that could show it.
    """
    targets = targets_of(cmd["turbine"])
    already = [name for name in targets if holds(cmd, before.get(name))]
    effect = [name for name in targets if name not in already]       # the telemetry can show these
    has_log = None if log is not None else False
    taken: set[str] = set()                                          # the edge's log has these
    began, latest, told = clock(), {}, False
    while True:
        if has_log is not False:
            has_log, entries = log()
            if not has_log:
                say(NO_LOG + " Only the telemetry can show what became of this command.")
            refused = [row for row in entries if row.get("Ok") in (False, 0, "false", "False")]
            if refused:
                say(f"The edge refused the command: {refused[0].get('Error') or 'no reason given'}")
                return False
            for row in entries:
                name = row.get("TurbineId")
                if name in targets and name not in taken:
                    taken.add(name)
                    extra = " It was already so before, so the telemetry shows no change." if name in already else ""
                    say(f"{name}: {_edge_says(row)}, in the log {clock() - began:.0f} s after the send.{extra}")
        if not told:
            told = True
            if already and not has_log:
                say(f"{', '.join(already)}: already so before the command ({_reading(before.get(already[0]))}). "
                    "For that the telemetry cannot show whether this command arrived.")
                if not effect:
                    return None
            if effect:
                say(f"Waiting for the telemetry to show it: {what(cmd)} on {', '.join(effect)} (up to {limit:.0f} s) ...")
        if effect:
            latest = read() or {}
            for name in list(effect):
                if holds(cmd, latest.get(name)):
                    say(f"{name}: {what(cmd)}, seen {clock() - began:.0f} s after the send ({_reading(latest[name])}).")
                    effect.remove(name)
        open_log = [name for name in targets if name not in taken] if has_log else []
        if not effect and not open_log:
            return True
        if clock() - began >= limit:
            break
        sleep(step)
    for name in effect:
        heard = "the edge took it, but the telemetry does not show it" if name in taken else "not seen"
        say(f"{name}: {heard} after {limit:.0f} s ({_reading(latest.get(name) or before.get(name))}).")
    for name in open_log:
        if name not in effect:
            shown = "was already so before the command" if name in already else "the telemetry shows it"
            say(f"{name}: {shown}, but the edge's log has no entry for this command after {limit:.0f} s.")
    if has_log and not taken:
        say("The edge's log has no entry for this command. Either the command did not reach the edge, or the log "
            "does not reach the database: is the simulator 1.2.0, and does the data flow forward the topic "
            ".../command (docs/14-deployment-guide-phase5c.md, steps 1 and 2)?")
    say("Follow the command hop by hop with the table 'If something fails' of docs/12-deployment-guide-phase5a.md: "
        "the eventstream's data preview first, then the control topic on the edge.")
    return False


def history_table(rows: list[dict]) -> str:
    """The command log as text, newest first."""
    if not rows:
        return "No command in that time."
    head = f"{'At (UTC)':<9} {'Turbine':<8} {'Command':<8} {'Status':<45} {'Limit kW':>8} {'Ends':<9} {'To edge s':>9} {'To reading s':>12}  Asked by"
    lines = [head, "-" * len(head)]

    def clock_of(value):
        return str(value)[11:19] if value else "-"

    def whole(value, width):
        number = _number(value)
        return f"{'-':>{width}}" if number is None else f"{number:>{width}.0f}"

    for row in rows:
        status = str(row.get("Status") or "")
        if status == "refused" and row.get("Error"):
            status = f"refused: {row['Error']}"
        asked = str(row.get("RequestedBy") or "") or ("at the edge" if row.get("Source") == "edge" else "not said")
        lines.append(f"{clock_of(row.get('Timestamp')):<9} {str(row.get('TurbineId')):<8} {str(row.get('Command')):<8} "
                     f"{status[:45]:<45} {whole(row.get('LimitKw'), 8)} {clock_of(row.get('EndsAt')):<9} "
                     f"{whole(row.get('FabricToEdgeSeconds'), 9)} {whole(row.get('EdgeToTelemetrySeconds'), 12)}  {asked}")
    return "\n".join(lines)


def status_table(rows: list[dict]) -> str:
    """The state of the turbines as text, one line each."""
    if not rows:
        return ("No telemetry in the last 10 minutes. Is the edge VM running? It stops every day at 08:00 UTC: "
                "bash infra/vm.sh status")
    head = f"{'Turbine':<8} {'State':<17} {'Limit kW':>8} {'Power kW':>8} {'Wind m/s':>8} {'Vib mm/s':>8} {'Oil degC':>8} {'Age s':>6}"
    lines = [head, "-" * len(head)]

    def cell(value, digits, width):
        number = _number(value)
        return f"{'-':>{width}}" if number is None else f"{number:>{width}.{digits}f}"

    for row in rows:
        setpoint = _number(row.get("PowerSetpoint"))
        limit = f"{'-':>8}" if setpoint is None or setpoint >= RATED_KW - 1.0 else f"{setpoint:>8.0f}"
        lines.append(f"{str(row.get('TurbineId')):<8} {str(row.get('State')):<17} {limit} {cell(row.get('ActivePower'), 0, 8)} "
                     f"{cell(row.get('WindSpeed'), 1, 8)} {cell(row.get('GearboxVibration'), 2, 8)} {cell(row.get('GearboxOilTemp'), 1, 8)} "
                     f"{cell(row.get('AgeSeconds'), 0, 6)}")
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    lines.append(f"{len(rows)} turbines, read at {stamp}Z. 'Limit' is the power setpoint when it is below the rated {RATED_KW:.0f} kW.")
    return "\n".join(lines)
