"""Simulation engine: advances the wind farm and produces MQTT messages.

The engine has no I/O of its own. ``step`` advances simulated time and returns
the messages that became due, so the same engine drives the real-time
publisher, the offline sample generator and the unit tests.
"""
from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from . import SCHEMA_VERSION, __version__
from .alarms import ALARMS_BY_CODE
from .anomalies import ANOMALY_KINDS, DEFAULT_DURATION_S, DEFAULT_SEVERITY, Anomaly, Effects
from .config import SimConfig
from .site import Site
from .turbine import Turbine
from .wind import OU, WindField

log = logging.getLogger("windfarm.engine")

EDGE_ASSET_ID = "EDGE-01"
SIM_COMMANDS = {"inject", "resolve", "wind", "status", "kinds"}
CONTROL_COMMANDS = {"curtail", "release", "stop", "start", "reset"}


@dataclass
class Message:
    topic: str
    payload: dict
    retain: bool = False


def iso(epoch_s: float) -> str:
    return datetime.fromtimestamp(epoch_s, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{int((epoch_s % 1) * 1000):03d}Z"


def parse_duration(value, default: float | None = None) -> float | None:
    """Accept seconds as a number, or strings such as '90s', '12m', '1h'."""
    if value is None or value == "":
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower()
    mult = {"s": 1.0, "m": 60.0, "h": 3600.0}.get(text[-1])
    if mult is None:
        return float(text)
    return float(text[:-1]) * mult


class Simulator:
    def __init__(self, site: Site, cfg: SimConfig, start_epoch: float | None = None):
        self.site = site
        self.cfg = cfg
        self.seed = cfg.seed if cfg.seed is not None else random.SystemRandom().randrange(1, 2**31)
        self.rng = random.Random(self.seed)
        # Separate stream for identifiers, so that issuing one never shifts the physics.
        self._id_rng = random.Random(self.seed ^ 0x5DEECE66D)
        # Whole-second start so that message timestamps line up on second boundaries.
        self.started_epoch = float(int(time.time() if start_epoch is None else start_epoch))
        self.t = 0.0                        # simulated seconds since start
        self.wind = WindField(site, self.rng, cfg.wind_mean, cfg.wind_regime_min,
                              cfg.wind_regime_max, cfg.ambient_mean_c, climate=self._climate())
        self.turbines = {t.turbine_id: Turbine(t, site.model, random.Random(self.rng.getrandbits(64)))
                         for t in site.turbines}
        self.anomalies: list[Anomaly] = []
        # What is wrong with individual turbines "now", shared with the history: see catalog.py.
        self._standing: dict[str, list[dict]] = {}
        if cfg.standing_conditions:
            for cond in site.raw.get("standingConditions", []):
                if cond.get("turbineId") in self.turbines:
                    self._standing.setdefault(cond["turbineId"], []).append(cond)
            self._use_site_character()
        self._grid_v = OU(self.rng, tau_s=120.0, std=0.004, x0=0.0)
        self._grid_f = OU(self.rng, tau_s=20.0, std=0.012, x0=0.0)
        self._due = {"telemetry": 0.0, "weather": 0.0, "registry": 0.0, "heartbeat": 0.0}
        self._next_spontaneous = self._draw_spontaneous_gap()
        self._seq: dict[str, int] = {}
        self.published = 0
        # The command log: one entry per turbine an operating command acted on, sent with the next step.
        self._command_log: list[tuple[str, str, dict]] = []
        self.ground_truth: list[dict] = []   # anomaly lifecycle, never sent to the cloud
        log.info("simulator ready: site=%s turbines=%d seed=%d", site.site_id, len(self.turbines), self.seed)

    # ------------------------------------------------------------------ #
    def _climate(self):
        if self.cfg.wind_model != "climate":
            return None
        try:
            from .climate import Climate
        except ImportError as exc:          # numpy missing: fall back rather than fail to start
            log.warning("climate model unavailable (%s); using the regime wind model", exc)
            return None
        return Climate.for_site(self.site.raw)

    def _use_site_character(self) -> None:
        """Give every turbine the efficiency, thermal behaviour and vibration level it has in
        the site history, instead of values drawn for this run."""
        try:
            from .climate import turbine_character
        except ImportError:                 # numpy missing: keep the values drawn for this run
            return
        character = turbine_character(int(self.site.raw.get("climateSeed", 20211)), len(self.site.turbines))
        for i, spec in enumerate(self.site.turbines):
            turbine = self.turbines[spec.turbine_id]
            turbine.efficiency = float(character["efficiency"][i])
            turbine.thermal_k = float(character["thermal"][i])
            turbine.vib_base = float(character["vibrationBase"][i])

    def _apply_standing(self, tid: str, fx: Effects, activity: float) -> None:
        for cond in self._standing.get(tid, ()):
            kind = cond.get("kind")
            if kind == "gearbox_wear":
                fx.gbx_oil_temp_add += float(cond.get("oilTempAdd", 0.0)) * activity
                fx.gbx_bearing_temp_add += float(cond.get("bearingTempAdd", 0.0)) * activity
                fx.gbx_vib_add += float(cond.get("vibrationAdd", 0.0)) * activity
            elif kind == "yaw_offset":
                fx.yaw_offset_deg += float(cond.get("offsetDeg", 0.0))
            elif kind == "blade_erosion":
                fx.efficiency_mult *= float(cond.get("efficiency", 1.0))

    def shutdown_messages(self) -> list[Message]:
        """Clear every alarm that is still raised. Sent when the simulator stops, so that no
        alarm stays active in the cloud after the turbine controller behind it has gone."""
        ts = iso(self.epoch)
        out: list[Message] = []
        for tid, turbine in self.turbines.items():
            for code, state in turbine.alarms.items():
                if not state.active:
                    continue
                event = turbine._alarm_event(ALARMS_BY_CODE[code], state, "cleared", None, ts,
                                             self.t - state.raised_at)
                event["data"]["clearedBy"] = "simulator shutdown"
                state.active = False
                out.append(Message(self.topic(tid, "alarm"), self._envelope("alarm", tid, ts, event["data"])))
        self.published += len(out)
        return out

    @property
    def epoch(self) -> float:
        return self.started_epoch + self.t

    def topic(self, asset_id: str, message_type: str) -> str:
        return f"{self.cfg.topic_root}/{self.site.site_id}/{asset_id}/{message_type}"

    @property
    def sim_topic_prefix(self) -> str:
        return f"{self.cfg.topic_root}/{self.site.site_id}/_sim"

    @property
    def control_topic(self) -> str:
        return f"{self.cfg.topic_root}/{self.site.site_id}/_control/request"

    def _envelope(self, message_type: str, asset_id: str, ts: str, data: dict) -> dict:
        seq = self._seq.get(asset_id, 0) + 1
        self._seq[asset_id] = seq
        return {
            "messageType": message_type,
            "schemaVersion": SCHEMA_VERSION,
            "siteId": self.site.site_id,
            "assetId": asset_id,
            "timestamp": ts,
            "seq": seq,
            "data": data,
        }

    # ------------------------------------------------------------------ #
    def step(self, dt: float = 1.0) -> list[Message]:
        """Advance the farm by ``dt`` seconds and return the messages now due."""
        self.t += dt
        now = self.t
        ts = iso(self.epoch)
        out: list[Message] = []

        weather = self.wind.step(now, self.epoch, dt)
        grid_v = 1.0 + self._grid_v.step(dt)
        grid_f = 60.0 + self._grid_f.step(dt)

        self._spontaneous(now)
        finished = [a for a in self.anomalies if a.finished(now)]
        for a in finished:
            self.anomalies.remove(a)
            self._truth("anomaly_ended", a, now)

        for tid, turbine in self.turbines.items():
            fx = Effects()
            activity = turbine.activity()
            for a in self.anomalies:
                if a.turbine_id == tid:
                    a.apply(fx, now, activity)
            self._apply_standing(tid, fx, activity)
            turbine.step(now, ts, dt, self.wind.local_wind(tid), weather, fx, grid_v, grid_f)

        # Alarm and state events go out immediately, unless the turbine is offline:
        # then they wait in its buffer and are forwarded when communication returns.
        for tid, turbine in self.turbines.items():
            if turbine.comms_down or not turbine.events:
                continue
            for ev in turbine.events:
                out.append(Message(self.topic(tid, ev["messageType"]),
                                   self._envelope(ev["messageType"], tid, ev["timestamp"], ev["data"])))
            turbine.events.clear()

        # The command log goes out at once, also for a turbine that is offline: it is the controller's
        # record of what it was told, not a reading of the turbine.
        for asset, stamp, data in self._command_log:
            out.append(Message(self.topic(asset, "command"), self._envelope("command", asset, stamp, data)))
        self._command_log.clear()

        if now >= self._due["telemetry"]:
            self._due["telemetry"] = now + self.cfg.telemetry_interval_s
            for tid, turbine in self.turbines.items():
                if not turbine.comms_down:
                    out.append(Message(self.topic(tid, "telemetry"),
                                       self._envelope("telemetry", tid, ts, turbine.telemetry())))

        if now >= self._due["weather"]:
            self._due["weather"] = now + self.cfg.weather_interval_s
            w = weather
            data = {
                "windSpeed": round(w.wind_speed, 2), "windDirection": round(w.wind_direction, 1),
                "windGust": round(w.gust, 2), "ambientTemp": round(w.ambient_temp, 1),
                "pressure": round(w.pressure_hpa, 1), "humidity": round(w.humidity, 1),
                "airDensity": round(w.air_density, 4),
            }
            mast = self.site.met_mast_id
            out.append(Message(self.topic(mast, "weather"), self._envelope("weather", mast, ts, data)))

        if now >= self._due["registry"]:
            self._due["registry"] = now + self.cfg.registry_interval_s
            out.extend(self._registry_messages(ts))

        if now >= self._due["heartbeat"]:
            self._due["heartbeat"] = now + self.cfg.heartbeat_interval_s
            data = {
                "simulatorVersion": __version__,
                "uptimeSeconds": round(now),
                "turbinesReporting": sum(1 for t in self.turbines.values() if not t.comms_down),
                "turbinesTotal": len(self.turbines),
                "messagesPublished": self.published,
            }
            out.append(Message(self.topic(EDGE_ASSET_ID, "heartbeat"),
                               self._envelope("heartbeat", EDGE_ASSET_ID, ts, data)))

        self.published += len(out)
        return out

    def _registry_messages(self, ts: str) -> list[Message]:
        msgs = [Message(self.topic(tid, "asset"), self._envelope("asset", tid, ts, t.registry()), retain=True)
                for tid, t in self.turbines.items()]
        mast = self.site.raw["metMast"]
        msgs.append(Message(self.topic(mast["id"], "asset"), self._envelope("asset", mast["id"], ts, {
            "name": mast["name"], "assetType": "MetMast", "latitude": mast["latitude"],
            "longitude": mast["longitude"], "elevationM": mast["elevationM"],
            "localX": mast["x"], "localY": mast["y"],
        }), retain=True))
        return msgs

    # ------------------------------------------------------------------ #
    # randomness beyond the weather: small things that happen on a real site
    def _draw_spontaneous_gap(self) -> float:
        rate = self.cfg.spontaneous_events_per_hour
        if rate <= 0:
            return float("inf")
        return self.t + self.rng.expovariate(rate / 3600.0)

    def _spontaneous(self, now: float) -> None:
        if now < self._next_spontaneous:
            return
        self._next_spontaneous = self._draw_spontaneous_gap()
        tid = self.rng.choice(list(self.turbines))
        if any(a.turbine_id == tid for a in self.anomalies):
            return
        roll = self.rng.random()
        if roll < 0.40:
            a = Anomaly.create(tid, "comms_loss", now, duration=self.rng.uniform(30, 75), source="spontaneous")
        elif roll < 0.65:
            self.turbines[tid].pause(now + self.rng.uniform(60, 150))
            log.info("spontaneous: %s cable untwist", tid)
            return
        elif roll < 0.85:
            a = Anomaly.create(tid, "yaw_misalignment", now, severity=self.rng.uniform(0.05, 0.2),
                               duration=self.rng.uniform(300, 900), source="spontaneous")
        else:
            a = Anomaly.create(tid, "sensor_freeze", now, duration=self.rng.uniform(60, 180),
                               source="spontaneous")
        self._register(a)

    def _register(self, a: Anomaly) -> None:
        a.id = f"{self._id_rng.getrandbits(48):012x}"
        self.anomalies.append(a)
        self._truth("anomaly_started", a, self.t)

    def _truth(self, event: str, a: Anomaly, now: float) -> None:
        record = {"event": event, "timestamp": iso(self.epoch), **a.describe(now)}
        self.ground_truth.append(record)
        log.info("%s: %s %s severity=%.2f source=%s", event, a.turbine_id, a.kind, a.severity, a.source)

    # ------------------------------------------------------------------ #
    # commands
    def _targets(self, value) -> list[str]:
        if value in (None, "", "all", "*"):
            return list(self.turbines)
        tid = str(value).upper()
        if tid not in self.turbines:
            raise ValueError(f"unknown turbine '{value}'; valid: {', '.join(self.turbines)}")
        return [tid]

    def handle_command(self, cmd: dict, channel: str = "sim") -> dict:
        """Execute one command and return the acknowledgement payload."""
        name = str(cmd.get("command", "")).lower()
        request_id = cmd.get("requestId", "")
        try:
            allowed = SIM_COMMANDS | CONTROL_COMMANDS if channel == "sim" else CONTROL_COMMANDS
            if name not in allowed:
                raise ValueError(f"unknown command '{name}'; valid: {', '.join(sorted(allowed))}")
            result = getattr(self, f"_cmd_{name}")(cmd)
            if name in CONTROL_COMMANDS:
                self._log_command(name, cmd, channel, result=result)
            return {"requestId": request_id, "command": name, "ok": True,
                    "timestamp": iso(self.epoch), "result": result}
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("command rejected: %s (%s)", cmd, exc)
            if name in CONTROL_COMMANDS or channel == "control":
                self._log_command(name, cmd, channel, error=str(exc))
            return {"requestId": request_id, "command": name, "ok": False,
                    "timestamp": iso(self.epoch), "error": str(exc)}

    def _log_command(self, name: str, cmd: dict, channel: str, result: dict | None = None, error: str = "") -> None:
        """Note an operating command for the command log: what was asked, by whom, and what became of it.

        A turbine controller keeps such a log of every setpoint and stop it is given. Here it is one
        message of type ``command`` per turbine the command acted on, sent with the telemetry, so that
        the cloud can tell who limited a turbine and whether the plant took the command. A command that
        was refused is logged once, under the edge itself unless it named an existing turbine.
        Commands that only the simulator has (inject, wind, status) are not operating commands and
        are not logged; one of them arriving on the control topic is logged as refused.
        """
        ts = iso(self.epoch)
        targets = next((v for k, v in (result or {}).items()
                        if k in ("curtailed", "released", "stopped", "started", "reset")), None)
        if targets is None:
            named = str(cmd.get("turbine", "")).upper()
            targets = [named] if named in self.turbines else [EDGE_ASSET_ID]
        duration = (result or {}).get("durationSeconds")
        base = {
            "requestId": str(cmd.get("requestId") or ""),
            "command": name,
            "source": "cloud" if channel == "control" else "edge",
            "requestedBy": str(cmd.get("requestedBy") or "")[:120],
            "issuedAt": str(cmd.get("issuedAt") or "") or None,
            "ok": not error,
            "error": error[:300] or None,
            "percent": None, "limitKw": None,
            "durationSeconds": duration,
            "endsAt": None if duration is None else iso(self.epoch + duration),
            "reason": (str(cmd.get("reason") or cmd.get("note") or "")[:200] or None),
            "turbinesInCommand": len(targets) if not error else 0,
        }
        for asset in targets:
            data = dict(base)
            if name == "curtail" and not error and asset in self.turbines:
                percent = float(cmd["percent"])
                data["percent"] = percent
                data["limitKw"] = round(self.turbines[asset].model.rated_power_kw * percent / 100.0, 1)
            self._command_log.append((asset, ts, data))

    def _cmd_inject(self, cmd: dict) -> dict:
        kind = str(cmd.get("kind", "gearbox_degradation"))
        if kind not in ANOMALY_KINDS:
            raise ValueError(f"unknown kind '{kind}'; valid: {', '.join(ANOMALY_KINDS)}")
        tid = str(cmd.get("turbine", "")).upper()
        if tid not in self.turbines:
            raise ValueError(f"unknown turbine '{cmd.get('turbine')}'; valid: {', '.join(self.turbines)}")
        hold = bool(cmd.get("hold", False))
        duration = parse_duration(cmd.get("duration"), DEFAULT_DURATION_S)
        a = Anomaly.create(tid, kind, self.t, severity=float(cmd.get("severity", DEFAULT_SEVERITY)),
                           duration=duration, hold=hold)
        self._register(a)
        turbine = self.turbines[tid]
        result = a.describe(self.t)
        result["turbineState"] = turbine.state
        if not turbine.producing and kind not in ("comms_loss", "sensor_freeze", "sensor_drift"):
            result["warning"] = (f"{tid} is not generating (state {turbine.state}); the fault will "
                                 "barely show. Raise the wind first: wind --mean 10")
        return result

    def _cmd_resolve(self, cmd: dict) -> dict:
        targets = self._targets(cmd.get("turbine"))
        kind = cmd.get("kind")
        hit = [a for a in self.anomalies
               if a.turbine_id in targets and (kind in (None, "") or a.kind == kind)]
        for a in hit:
            a.resolve(self.t)
            self._truth("anomaly_resolving", a, self.t)
        return {"resolving": [a.describe(self.t) for a in hit]}

    def _cmd_wind(self, cmd: dict) -> dict:
        if cmd.get("clear"):
            self.wind.clear_wind_override()
            return {"override": None}
        mean = float(cmd["mean"])
        duration = parse_duration(cmd.get("duration"), 3600.0)
        self.wind.set_wind_override(mean, self.t + duration)
        return {"override": {"mean": self.wind.override_mean, "durationSeconds": round(duration)}}

    def _cmd_kinds(self, cmd: dict) -> dict:
        return {"kinds": ANOMALY_KINDS}

    def _cmd_status(self, cmd: dict) -> dict:
        return self.status()

    def _cmd_curtail(self, cmd: dict) -> dict:
        percent = float(cmd["percent"])
        duration = parse_duration(cmd.get("duration"))
        until = None if duration is None else self.t + duration
        targets = self._targets(cmd.get("turbine"))
        for tid in targets:
            self.turbines[tid].curtail(percent, until)
        return {"curtailed": targets, "percent": percent,
                "durationSeconds": None if duration is None else round(duration)}

    def _cmd_release(self, cmd: dict) -> dict:
        targets = self._targets(cmd.get("turbine"))
        for tid in targets:
            self.turbines[tid].release()
        return {"released": targets}

    def _cmd_stop(self, cmd: dict) -> dict:
        duration = parse_duration(cmd.get("duration"))
        until = None if duration is None else self.t + duration
        targets = self._targets(cmd.get("turbine"))
        for tid in targets:
            self.turbines[tid].stop(str(cmd.get("reason", "operator")), until)
        return {"stopped": targets, "durationSeconds": None if duration is None else round(duration)}

    def _cmd_start(self, cmd: dict) -> dict:
        targets = self._targets(cmd.get("turbine"))
        for tid in targets:
            self.turbines[tid].start()
        return {"started": targets}

    def _cmd_reset(self, cmd: dict) -> dict:
        targets = self._targets(cmd.get("turbine"))
        for tid in targets:
            self.turbines[tid].reset()
        return {"reset": targets}

    def status(self) -> dict:
        w = self.wind.weather
        return {
            "siteId": self.site.site_id,
            "simulatorVersion": __version__,
            "seed": self.seed,
            "uptimeSeconds": round(self.t),
            "wind": {"speed": round(w.wind_speed, 1), "direction": round(w.wind_direction),
                     "overrideMean": self.wind.override_mean,
                     "model": "climate" if self.wind.climate is not None else "regime"},
            "ambientTemp": round(w.ambient_temp, 1),
            "sitePowerKw": round(sum(max(0.0, t.power) for t in self.turbines.values())),
            "activeAnomalies": [a.describe(self.t) for a in self.anomalies],
            "standingConditions": [{"turbineId": tid, "kind": cond["kind"]}
                                   for tid, conds in sorted(self._standing.items()) for cond in conds],
            "turbines": {tid: {"state": t.state, "powerKw": round(t.power),
                               "alarms": t.active_alarm_codes()}
                         for tid, t in self.turbines.items()},
        }
