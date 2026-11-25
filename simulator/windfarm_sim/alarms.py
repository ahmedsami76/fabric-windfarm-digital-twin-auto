"""Alarm catalogue of the simulated turbine controller.

The same catalogue drives the simulator and the ``alarm_codes.csv`` reference
file, so thresholds in the data always match what the reference data says.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlarmDef:
    code: str
    component: str
    severity: str            # info | warning | critical
    description: str
    signal: str | None       # telemetry signal watched; None for event alarms
    threshold: float | None
    direction: str = "high"  # high: raise at >= threshold; low: raise at <=
    unit: str = ""
    on_delay_s: float = 10.0
    off_delay_s: float = 20.0
    hysteresis: float = 0.0
    action: str = "none"     # none | derate | trip
    derate_to: float = 1.0   # fraction of rated power while the action holds
    sop: str = ""


# Threshold alarms are evaluated every simulation step against a short moving
# average of what the sensors report, as a real controller does, so that single
# noisy samples neither raise nor clear an alarm. Event alarms (signal=None)
# are raised by state changes.
ALARMS: tuple[AlarmDef, ...] = (
    AlarmDef("GBX-OIL-TEMP-HIGH", "gearbox", "warning",
             "Gearbox oil temperature high", "gearboxOilTemp", 78.0, unit="degC",
             hysteresis=3.0, sop="SOP-GBX-001"),
    AlarmDef("GBX-OIL-TEMP-CRIT", "gearbox", "critical",
             "Gearbox oil temperature critical, power derated to 50%",
             "gearboxOilTemp", 88.0, unit="degC", hysteresis=3.0,
             action="derate", derate_to=0.5, sop="SOP-GBX-001"),
    AlarmDef("GBX-OIL-TEMP-TRIP", "gearbox", "critical",
             "Gearbox oil temperature trip, turbine stopped",
             "gearboxOilTemp", 96.0, unit="degC", hysteresis=6.0,
             on_delay_s=5.0, action="trip", sop="SOP-GBX-001"),
    AlarmDef("GBX-VIB-HIGH", "gearbox", "warning",
             "Gearbox vibration high", "gearboxVibration", 5.5, unit="mm/s",
             on_delay_s=15.0, hysteresis=0.6, sop="SOP-GBX-001"),
    AlarmDef("GBX-VIB-CRIT", "gearbox", "critical",
             "Gearbox vibration critical, power derated to 30%",
             "gearboxVibration", 8.0, unit="mm/s", on_delay_s=15.0,
             hysteresis=0.8, action="derate", derate_to=0.3, sop="SOP-GBX-001"),
    AlarmDef("GEN-WIND-TEMP-HIGH", "generator", "warning",
             "Generator winding temperature high", "generatorWindingTemp", 125.0,
             unit="degC", hysteresis=4.0, sop="SOP-GEN-002"),
    AlarmDef("GEN-WIND-TEMP-CRIT", "generator", "critical",
             "Generator winding temperature critical, power derated to 50%",
             "generatorWindingTemp", 140.0, unit="degC", hysteresis=4.0,
             action="derate", derate_to=0.5, sop="SOP-GEN-002"),
    AlarmDef("GEN-WIND-TEMP-TRIP", "generator", "critical",
             "Generator winding temperature trip, turbine stopped",
             "generatorWindingTemp", 155.0, unit="degC", hysteresis=8.0,
             on_delay_s=5.0, action="trip", sop="SOP-GEN-002"),
    AlarmDef("HYD-PRESS-LOW", "hydraulic system", "warning",
             "Hydraulic pressure low", "hydraulicPressure", 160.0,
             direction="low", unit="bar", hysteresis=5.0, sop="SOP-PIT-003"),
    AlarmDef("PITCH-ASYM", "pitch system", "warning",
             "Blade pitch asymmetry detected", "_pitchDeviation", 5.0, unit="deg",
             hysteresis=1.0, sop="SOP-PIT-003"),
    AlarmDef("PITCH-ASYM-CRIT", "pitch system", "critical",
             "Blade pitch asymmetry critical, power derated to 40%",
             "_pitchDeviation", 11.0, unit="deg", hysteresis=1.5,
             action="derate", derate_to=0.4, sop="SOP-PIT-003"),
    AlarmDef("TWR-VIB-HIGH", "tower", "warning",
             "Tower vibration high", "towerVibration", 2.5, unit="mm/s",
             on_delay_s=15.0, hysteresis=0.4, sop="SOP-PIT-003"),
    # --- event alarms -------------------------------------------------------
    AlarmDef("YAW-UNTWIST", "yaw system", "info",
             "Cable untwist in progress, turbine paused", None, None,
             sop="SOP-OPS-000"),
    AlarmDef("HIGH-WIND-STOP", "controller", "info",
             "Turbine stopped, wind above cut-out", None, None, sop="SOP-OPS-000"),
    AlarmDef("MANUAL-STOP", "controller", "info",
             "Turbine stopped by operator command", None, None, sop="SOP-CUR-006"),
    AlarmDef("POWER-CURTAILED", "controller", "info",
             "Power limited by remote setpoint", None, None, sop="SOP-CUR-006"),
    AlarmDef("COMMS-RESTORED", "scada", "info",
             "Communication with turbine controller restored", None, None,
             sop="SOP-COM-005"),
)

ALARMS_BY_CODE = {a.code: a for a in ALARMS}
THRESHOLD_ALARMS = tuple(a for a in ALARMS if a.signal is not None)

# How long a derate stays latched after its alarm clears (seconds). Real
# controllers hold a protective derate until conditions are stable.
DERATE_LATCH_S = 300.0
# Lockout after a trip: the turbine restarts by itself only after every warning
# and critical alarm has been clear for this long. An operator reset skips it.
TRIP_LOCKOUT_S = 600.0
# Time constant of the moving average used for alarm evaluation.
ALARM_FILTER_S = 8.0
