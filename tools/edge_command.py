"""One operating command for the edge of the wind farm, and where to send it (Phase 5).

Notebook 12_send_edge_command carries a copy of this file; tools/build-phase5.py puts it there. The
code here needs nothing but the Python standard library, so the tests run it as it is: they hand the
command it builds to the simulator's own handler of the control topic.

The control topic of the simulator takes five commands and nothing else: curtail, release, stop,
start and reset. It cannot inject a fault or change the wind.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone

COMMANDS = ("curtail", "release", "stop", "start", "reset")
TURBINE = re.compile(r"^WT-(0[1-9]|1[0-2])$")
DURATION = re.compile(r"^[1-9][0-9]{0,3}[smh]$")
# How a person or an agent may write a duration: 10m, 10 m, 10 min, 10 minutes, 90 seconds, 1 hour.
SPELLED_DURATION = re.compile(r"^([1-9][0-9]{0,3})\s*(s|sec|secs|second|seconds|m|min|mins|minute|minutes|h|hr|hrs|hour|hours)$")
STOP_REASONS = ("operator", "maintenance")


class CommandError(ValueError):
    """The command would not be accepted, or would do more than was asked for."""


def build_command(command, turbine, percent=None, duration="", reason="", requested_by="", request_id=None, now=None):
    """The JSON object for the control topic, after checking every field.

    The simulator treats a missing turbine as "all twelve". Here a turbine is always required, and
    all of them only when the word `all` is written out.
    """
    name = str(command or "").strip().lower()
    if name not in COMMANDS:
        raise CommandError(f"'{command}' is not a command of the control topic. Use one of: {', '.join(COMMANDS)}.")
    target = str(turbine or "").strip()
    if target.lower() == "all":
        target = "all"
    else:
        target = target.upper()
        if not TURBINE.match(target):
            raise CommandError(f"'{turbine}' is not a turbine. Use WT-01 to WT-12, or the word all.")
    out = {"command": name, "requestId": request_id or uuid.uuid4().hex[:12], "turbine": target}

    text = str(duration or "").strip().lower()
    if text and name not in ("curtail", "stop"):
        raise CommandError(f"'{name}' takes no duration.")
    if text and not DURATION.match(text):
        raise CommandError(f"'{duration}' is not a duration. Write a number and s, m or h, for example 30m.")
    if name == "curtail":
        try:
            value = float(percent)
        except (TypeError, ValueError):
            raise CommandError("curtail needs percent: the share of rated power the turbine may still produce, 0 to 100.") from None
        if not 0 <= value <= 100:
            raise CommandError(f"percent is {value:g}; it must be between 0 and 100.")
        if not text:
            raise CommandError("curtail needs a duration here, for example 30m, so that a forgotten command ends by itself. To end it sooner, send release.")
        out["percent"] = value
    elif percent not in (None, ""):
        raise CommandError(f"'{name}' takes no percent.")
    if text:
        out["duration"] = text
    if name == "stop":
        why = str(reason or "operator").strip().lower()
        if why not in STOP_REASONS:
            raise CommandError(f"The reason of a stop is one of: {', '.join(STOP_REASONS)}.")
        out["reason"] = why
    elif reason:
        out["note"] = str(reason)[:200]
    if requested_by:
        out["requestedBy"] = str(requested_by)[:120]
    out["issuedAt"] = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def as_flag(value, name="dry_run"):
    """True or False from a parameter that may arrive as text. The text "False" is not a true value."""
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no", ""):
        return False
    raise CommandError(f"{name} is '{value}'; write True or False.")


def from_parameters(command, turbine, percent=None, duration="", reason="", requested_by="", request_id=None, now=None):
    """The command for the values of the notebook's parameter cell, however they were written.

    Whoever fills that cell, a person, a pipeline or the operations agent, changes the values the
    command needs and leaves the others as they stand, and may write `Curtail`, `30%` or `10 minutes`.
    So the name is brought to lower case before anything is decided by it, a value the command does
    not take is left out, and a percentage or a duration is read in the forms people write them.
    Deciding by the name as it was typed dropped the duration of a `Stop`, which then had no end.
    """
    name = str(command or "").strip().lower()
    if name == "curtail" and isinstance(percent, str):
        percent = percent.strip().rstrip("%").strip()
    text = str(duration or "").strip().lower()
    spelled = SPELLED_DURATION.match(text)
    if spelled:
        text = spelled.group(1) + spelled.group(2)[0]
    return build_command(name, turbine, percent=percent if name == "curtail" else None,
                         duration=text if name in ("curtail", "stop") else "", reason=reason,
                         requested_by=requested_by, request_id=request_id, now=now)


def find_item(items, name):
    """The id of the item of that display name in the answer of a Fabric list call, or None."""
    return next((item.get("id") for item in items if item.get("displayName") == name), None)


def find_custom_endpoint(topology, kind):
    """The id of the custom endpoint among the `sources` or the `destinations` of an eventstream, or None."""
    return next((node.get("id") for node in topology.get(kind, []) if node.get("type") == "CustomEndpoint"), None)


def send_settings(connection):
    """What a sender needs from the connection of a custom endpoint source, checked for completeness."""
    namespace = connection.get("fullyQualifiedNamespace") or ""
    event_hub = connection.get("eventHubName") or ""
    secret = (connection.get("accessKeys") or {}).get("primaryConnectionString") or ""
    missing = [label for label, value in (("fullyQualifiedNamespace", namespace), ("eventHubName", event_hub), ("accessKeys.primaryConnectionString", secret)) if not value]
    if missing:
        raise CommandError("The connection of the eventstream's source lacks: " + ", ".join(missing) + ".")
    return {"namespace": namespace, "eventHub": event_hub, "connectionString": secret}


def payload(command):
    """The bytes that go on the wire: compact JSON, as the simulator's own tool writes it."""
    return json.dumps(command, separators=(",", ":")).encode("utf-8")
