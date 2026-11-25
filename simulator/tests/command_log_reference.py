"""The rules of the KQL function CommandLog (fabric/kql/07-command-log.kql), written a second time in Python.

The tests cannot run KQL, so the function itself is only read by the two checkers in tools/. What can
be tested here is whether its rules are right for the simulator: whether a reading taken after a command
shows that command, and whether a limit is called ended when it is. test_command_log.py runs these rules
on the simulator's own messages and compares the words and numbers of the two texts.
A change to the function is a change here, and the other way round.
"""
from __future__ import annotations

WAIT_S = 300.0          # let wait = 5m
TOLERANCE_KW = 1.0      # PowerSetpoint <= LimitKw + 1.0
STOPPED = ("STOPPED", "MAINTENANCE")
STATUSES = ("refused", "taken by the edge, not yet seen in telemetry", "taken by the edge, never seen in telemetry",
            "in force", "ended", "confirmed")


def shows(command: dict, reading: dict) -> bool:
    """Does this reading show the command? The case() of the function, branch for branch."""
    name = command["Command"]
    if name == "curtail":
        return reading["PowerSetpoint"] <= command["LimitKw"] + TOLERANCE_KW
    if name == "release":
        return reading["State"] != "CURTAILED"
    if name == "stop":
        return reading["State"] in STOPPED
    if name == "start":
        return reading["State"] not in STOPPED
    return reading["State"] != "FAULT"


def command_log(commands: list[dict], readings: list[dict], now: float) -> list[dict]:
    """One row for each command, with ConfirmedAt, EndedAt and Status. Times are seconds.

    A message that arrived twice (the path delivers at least once) is one command: the first line of the
    function keeps one row for each turbine, request, command and time.
    """
    once = {(c["TurbineId"], c["RequestId"], c["Command"], c["Timestamp"]): c for c in commands}
    commands = list(once.values())
    out = []
    for command in commands:
        mine = sorted((r for r in readings if r["TurbineId"] == command["TurbineId"]), key=lambda r: r["ReadingAt"])
        at, ok = command["Timestamp"], command["Ok"]
        confirmed = next((r["ReadingAt"] for r in mine if ok and at <= r["ReadingAt"] <= at + WAIT_S and shows(command, r)), None)
        ended = None
        if ok and command["Command"] == "curtail":
            lifted = None
            if confirmed is not None:
                lifted = next((r["ReadingAt"] for r in mine
                               if r["ReadingAt"] > confirmed and r["PowerSetpoint"] > command["LimitKw"] + TOLERANCE_KW), None)
            later = [c["Timestamp"] for c in commands
                     if c["Ok"] and c["TurbineId"] == command["TurbineId"] and c["Command"] in ("curtail", "release")
                     and (c["Timestamp"] > at or (c["Timestamp"] == at and c["RequestId"] != command["RequestId"]))]
            replaced = min(later) if later else None
            ends = command.get("EndsAt")
            over = ends if ends is not None and ends <= now else None
            times = [t for t in (lifted, replaced, over) if t is not None]
            ended = min(times) if times else None
        if not ok:
            status = "refused"
        elif command["Command"] == "curtail" and ended is not None:
            status = "ended"
        elif confirmed is None and at > now - WAIT_S:
            status = "taken by the edge, not yet seen in telemetry"
        elif confirmed is None:
            status = "taken by the edge, never seen in telemetry"
        elif command["Command"] == "curtail":
            status = "in force"
        else:
            status = "confirmed"
        out.append({**command, "ConfirmedAt": confirmed, "EndedAt": ended, "Status": status,
                    "EdgeToTelemetrySeconds": None if confirmed is None else round(confirmed - at)})
    return out
