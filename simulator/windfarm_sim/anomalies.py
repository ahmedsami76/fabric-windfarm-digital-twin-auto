"""Injectable anomalies.

An anomaly ramps in, holds, then ramps out by itself (auto-resolve) unless it
was injected with ``hold=True``, in which case it stays until a ``resolve``
command arrives. Its ``intensity`` (0..1) scales the physical effects applied
to one turbine.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

ANOMALY_KINDS = {
    "gearbox_degradation": "Gearbox bearing wear: vibration and oil temperature rise, "
                           "efficiency drops, the controller derates or trips.",
    "generator_overheat": "Generator cooling failure: winding temperature rises with load.",
    "pitch_fault": "One blade pitch actuator sticks: pitch asymmetry, power loss, "
                   "tower vibration, low hydraulic pressure.",
    "yaw_misalignment": "Wind vane miscalibration: the nacelle points off the wind. "
                        "No alarm is raised; only the power deficit and the nacelle "
                        "direction give it away.",
    "sensor_freeze": "The gearbox oil temperature sensor flatlines at its last value.",
    "sensor_drift": "The gearbox oil temperature sensor drifts upwards; no physical fault.",
    "comms_loss": "The turbine stops reporting for the duration.",
}

DEFAULT_DURATION_S = 15 * 60.0
DEFAULT_SEVERITY = 0.8
HOLD_RAMP_OUT_S = 90.0


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


def _smooth(x: float) -> float:
    """Smoothstep: eases the start and end of a ramp."""
    x = _clamp01(x)
    return x * x * (3.0 - 2.0 * x)


@dataclass
class Effects:
    """Sum of the physical effects of all anomalies active on one turbine."""
    gbx_vib_add: float = 0.0
    gbx_oil_temp_add: float = 0.0
    gbx_bearing_temp_add: float = 0.0
    gbx_oil_pressure_add: float = 0.0
    gen_winding_temp_add: float = 0.0
    gen_bearing_temp_add: float = 0.0
    efficiency_mult: float = 1.0
    pitch_deviation: float = 0.0
    tower_vib_add: float = 0.0
    hyd_pressure_add: float = 0.0
    yaw_offset_deg: float = 0.0
    comms_down: bool = False
    freeze_oil_temp: bool = False
    oil_temp_sensor_bias: float = 0.0


@dataclass
class Anomaly:
    turbine_id: str
    kind: str
    severity: float
    started: float                    # simulation time, seconds
    duration: float | None            # None means hold until resolved
    ramp_in: float
    ramp_out: float
    source: str = "command"           # command | spontaneous
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    resolve_at: float | None = None   # simulation time when ramp-out begins

    def __post_init__(self) -> None:
        if self.kind not in ANOMALY_KINDS:
            raise ValueError(f"unknown anomaly kind '{self.kind}'")
        self.severity = max(0.05, min(1.0, float(self.severity)))
        if self.duration is not None and self.resolve_at is None:
            self.resolve_at = self.started + max(self.ramp_in, self.duration - self.ramp_out)

    # ------------------------------------------------------------------ #
    @classmethod
    def create(cls, turbine_id: str, kind: str, now: float, severity: float = DEFAULT_SEVERITY,
               duration: float | None = DEFAULT_DURATION_S, hold: bool = False,
               source: str = "command") -> "Anomaly":
        if hold:
            duration = None
        if duration is not None:
            duration = max(30.0, float(duration))
            ramp_in = min(0.30 * duration, 300.0)
            ramp_out = min(0.20 * duration, 180.0)
        else:
            ramp_in, ramp_out = 180.0, HOLD_RAMP_OUT_S
        if kind in ("comms_loss", "sensor_freeze"):
            # These switch on and off; a ramp makes no physical sense.
            ramp_in, ramp_out = 1.0, 1.0
        return cls(turbine_id=turbine_id, kind=kind, severity=severity, started=now,
                   duration=duration, ramp_in=ramp_in, ramp_out=ramp_out, source=source)

    def resolve(self, now: float) -> None:
        """Begin the ramp-out now (used for hold anomalies and early resolve)."""
        if self.resolve_at is None or self.resolve_at > now:
            self.resolve_at = now

    def intensity(self, now: float) -> float:
        up = _smooth((now - self.started) / self.ramp_in)
        if self.resolve_at is not None and now >= self.resolve_at:
            level = _smooth((self.resolve_at - self.started) / self.ramp_in)
            return level * (1.0 - _smooth((now - self.resolve_at) / self.ramp_out))
        return up

    def finished(self, now: float) -> bool:
        return self.resolve_at is not None and now >= self.resolve_at + self.ramp_out

    def ends_at(self) -> float | None:
        return None if self.resolve_at is None else self.resolve_at + self.ramp_out

    def describe(self, now: float) -> dict:
        ends = self.ends_at()
        return {
            "anomalyId": self.id,
            "turbineId": self.turbine_id,
            "kind": self.kind,
            "severity": round(self.severity, 2),
            "intensity": round(self.intensity(now), 3),
            "source": self.source,
            "elapsedSeconds": round(now - self.started),
            "remainingSeconds": None if ends is None else max(0, round(ends - now)),
            "hold": self.resolve_at is None,
        }

    # ------------------------------------------------------------------ #
    def apply(self, fx: Effects, now: float, activity: float) -> None:
        """Add this anomaly's effects to ``fx``.

        ``activity`` (0.15..1) reflects how hard the drivetrain is working:
        mechanical faults show less when the rotor is barely turning.
        """
        k = self.intensity(now)
        s = self.severity
        if k <= 0.0:
            return
        if self.kind == "gearbox_degradation":
            fx.gbx_vib_add += k * (2.0 + 6.5 * s) * activity
            fx.gbx_oil_temp_add += k * (12.0 + 22.0 * s) * (0.55 + 0.45 * activity)
            fx.gbx_bearing_temp_add += k * (6.0 + 10.0 * s) * (0.55 + 0.45 * activity)
            fx.gbx_oil_pressure_add -= k * (0.2 + 0.5 * s)
            fx.efficiency_mult *= 1.0 - k * (0.03 + 0.07 * s)
        elif self.kind == "generator_overheat":
            fx.gen_winding_temp_add += k * (20.0 + 30.0 * s) * (0.5 + 0.5 * activity)
            fx.gen_bearing_temp_add += k * (8.0 + 12.0 * s) * (0.5 + 0.5 * activity)
            fx.efficiency_mult *= 1.0 - k * 0.02 * s
        elif self.kind == "pitch_fault":
            fx.pitch_deviation += k * (4.0 + 10.0 * s)
            fx.efficiency_mult *= 1.0 - k * (0.12 + 0.25 * s)
            fx.tower_vib_add += k * (1.2 + 2.2 * s) * activity
            fx.hyd_pressure_add -= k * (12.0 + 28.0 * s)
        elif self.kind == "yaw_misalignment":
            fx.yaw_offset_deg += k * (10.0 + 20.0 * s)
        elif self.kind == "sensor_drift":
            fx.oil_temp_sensor_bias += k * (8.0 + 22.0 * s)
        elif self.kind == "sensor_freeze":
            fx.freeze_oil_temp = fx.freeze_oil_temp or k > 0.5
        elif self.kind == "comms_loss":
            fx.comms_down = fx.comms_down or k > 0.5
