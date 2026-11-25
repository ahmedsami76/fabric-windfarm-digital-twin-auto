"""Physical and control model of one wind turbine.

The model is deliberately simple but internally consistent: power follows the
wind through a power curve, temperatures follow load through first-order lags,
and the controller raises alarms, derates and trips from the values its sensors
report. That consistency is what lets analytics (and later the agents) reason
about cause and effect.
"""
from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass

from .alarms import (ALARM_FILTER_S, ALARMS_BY_CODE, DERATE_LATCH_S, THRESHOLD_ALARMS,
                     TRIP_LOCKOUT_S, AlarmDef)
from .anomalies import Effects
from .site import TurbineModel, TurbineSpec
from .wind import Weather, wrap180, wrap360

AUX_POWER_KW = -12.0          # consumption of a turbine that is not generating
STANDARD_AIR_DENSITY = 1.225

RUNNING = "RUNNING"
DERATED = "DERATED"
CURTAILED = "CURTAILED"
IDLE = "IDLE"
PAUSED = "PAUSED"
STOPPED_HIGH_WIND = "STOPPED_HIGH_WIND"
STOPPED = "STOPPED"
MAINTENANCE = "MAINTENANCE"
FAULT = "FAULT"


def power_curve_kw(wind_speed: float, model: TurbineModel) -> float:
    """Reference power curve at standard air density."""
    ci, r, co = model.cut_in_wind_speed, model.rated_wind_speed, model.cut_out_wind_speed
    if wind_speed < ci or wind_speed > co:
        return 0.0
    if wind_speed >= r:
        return model.rated_power_kw
    return model.rated_power_kw * (wind_speed ** 3 - ci ** 3) / (r ** 3 - ci ** 3)


@dataclass
class _AlarmState:
    active: bool = False
    pending_since: float | None = None
    clearing_since: float | None = None
    alarm_id: str = ""
    raised_at: float = 0.0
    derate_release_at: float | None = None


class Turbine:
    def __init__(self, spec: TurbineSpec, model: TurbineModel, rng: random.Random):
        self.spec = spec
        self.model = model
        self.rng = rng
        self.id = spec.turbine_id

        # Individual character: no two turbines behave exactly alike.
        self.efficiency = rng.uniform(0.955, 1.0)
        self.thermal_k = rng.uniform(0.97, 1.03)
        self.vib_base = rng.uniform(1.1, 1.6)
        self.hyd_phase = rng.uniform(0.0, 2.0 * math.pi)
        self.sensor_bias = {
            "gearboxOilTemp": rng.gauss(0.0, 0.4),
            "generatorWindingTemp": rng.gauss(0.0, 0.6),
            "windSpeed": rng.gauss(0.0, 0.08),
        }

        self._warm = False
        self.ws_avg = 0.0
        self.producing = False
        self.high_wind = False
        self.tripped = False
        self._trip_clear_since: float | None = None
        self.manual_stop: str | None = None
        self.manual_stop_until: float | None = None
        self.setpoint_kw: float | None = None
        self.setpoint_until: float | None = None
        self.paused_until: float | None = None
        self.comms_down = False
        self._was_comms_down = False
        self._yawing = False

        self.power = 0.0
        self.available_power = 0.0
        self.rotor_rpm = 0.0
        self.pitch = 88.0
        self.nacelle_dir = 0.0
        self.t_gbx_oil = 40.0
        self.t_gbx_bearing = 42.0
        self.t_gen_winding = 45.0
        self.t_gen_bearing = 40.0
        self.t_main_bearing = 30.0
        self.t_nacelle = 25.0
        self.t_transformer = 45.0
        self.add_gbx_oil = 0.0
        self.add_gbx_bearing = 0.0
        self.add_gen_winding = 0.0
        self.add_gen_bearing = 0.0
        self.energy_total_kwh = rng.uniform(28e6, 41e6)
        self._frozen_oil: float | None = None

        self.state = IDLE
        self.alarms: dict[str, _AlarmState] = {a.code: _AlarmState() for a in ALARMS_BY_CODE.values()}
        self.events: list[dict] = []     # alarm and state events waiting to be published
        self._signals: dict[str, float] = {}
        self._filtered: dict[str, float] = {}
        self._seq = 0

    # ------------------------------------------------------------------ #
    # commands
    def curtail(self, percent: float, until: float | None) -> None:
        percent = max(0.0, min(100.0, percent))
        self.setpoint_kw = self.model.rated_power_kw * percent / 100.0
        self.setpoint_until = until

    def release(self) -> None:
        self.setpoint_kw = None
        self.setpoint_until = None

    def stop(self, reason: str, until: float | None) -> None:
        self.manual_stop = reason or "operator"
        self.manual_stop_until = until

    def start(self) -> None:
        self.manual_stop = None
        self.manual_stop_until = None

    def reset(self) -> None:
        """Operator reset of a latched trip and of latched derates."""
        self.tripped = False
        self._trip_clear_since = None
        for st in self.alarms.values():
            st.derate_release_at = None

    def pause(self, until: float) -> None:
        self.paused_until = until

    def activity(self) -> float:
        frac = self.rotor_rpm / self.model.rated_rotor_rpm
        return max(0.15, min(1.0, frac / 0.5))

    def next_seq(self) -> int:
        self._seq += 1
        return self._seq

    # ------------------------------------------------------------------ #
    def step(self, sim_t: float, iso_ts: str, dt: float, wind_speed: float, weather: Weather,
             fx: Effects, grid_v_pu: float, grid_freq: float) -> None:
        m = self.model
        rng = self.rng
        amb = weather.ambient_temp
        wd = weather.wind_direction

        if not self._warm:
            self.ws_avg = wind_speed
            self.nacelle_dir = wd
        self.ws_avg += (wind_speed - self.ws_avg) * (1.0 - math.exp(-dt / 30.0))

        # ---- timers on commands -------------------------------------------
        if self.setpoint_until is not None and sim_t >= self.setpoint_until:
            self.release()
        if self.manual_stop_until is not None and sim_t >= self.manual_stop_until:
            self.start()
        if self.paused_until is not None and sim_t >= self.paused_until:
            self.paused_until = None

        # ---- run permission ------------------------------------------------
        if self.high_wind:
            if self.ws_avg < m.cut_out_wind_speed - 3.0:
                self.high_wind = False
        elif self.ws_avg > m.cut_out_wind_speed:
            self.high_wind = True

        allowed = not (self.tripped or self.manual_stop or self.paused_until is not None
                       or self.high_wind)
        if self.producing:
            if not allowed or self.ws_avg < m.cut_in_wind_speed - 0.2:
                self.producing = False
        elif allowed and self.ws_avg > m.cut_in_wind_speed + 0.5:
            self.producing = True
        if not self._warm:
            self.producing = allowed and self.ws_avg > m.cut_in_wind_speed

        # ---- yaw -----------------------------------------------------------
        # A miscalibrated vane makes the controller hold an offset to the wind.
        yaw_target = wd + fx.yaw_offset_deg
        vane_error = wrap180(yaw_target - self.nacelle_dir)
        if abs(vane_error) > 4.0:
            self._yawing = True
        if self._yawing:
            move = math.copysign(min(abs(vane_error), 0.5 * dt), vane_error)
            self.nacelle_dir = wrap360(self.nacelle_dir + move)
            vane_error = wrap180(yaw_target - self.nacelle_dir)
            if abs(vane_error) < 1.0:
                self._yawing = False
        true_misalignment = wrap180(wd - self.nacelle_dir)

        # ---- power ---------------------------------------------------------
        # Thin air moves the power curve to higher wind speeds; it does not lower rated power.
        # Losses (efficiency, misalignment) cost power below rated wind and are made up by the
        # pitch control above it. Same formula as the history generator.
        density_ratio = weather.air_density / STANDARD_AIR_DENSITY
        equivalent_wind = wind_speed * density_ratio ** (1.0 / 3.0)
        if wind_speed > m.cut_out_wind_speed:
            equivalent_wind = wind_speed
        avail = power_curve_kw(equivalent_wind, m) * self.efficiency * fx.efficiency_mult
        avail *= max(0.0, math.cos(math.radians(true_misalignment))) ** 3
        avail = min(m.rated_power_kw, avail)
        self.available_power = avail

        derate = self._derate_factor(sim_t)
        limit = m.rated_power_kw * derate
        if self.setpoint_kw is not None:
            limit = min(limit, self.setpoint_kw)
        target = min(avail, limit) if self.producing else AUX_POWER_KW
        if not self._warm:
            self.power = target
        self.power += (target - self.power) * (1.0 - math.exp(-dt / 8.0))
        noise = rng.gauss(0.0, 0.004 * m.rated_power_kw) if self.producing else rng.gauss(0.0, 0.6)
        power_out = self.power + noise
        if self.producing:
            power_out = min(power_out, m.rated_power_kw * 1.01)
        load = max(0.0, self.power) / m.rated_power_kw

        # ---- rotor and pitch ----------------------------------------------
        if self.producing:
            frac = 0.45 + 0.55 * (wind_speed - m.cut_in_wind_speed) / (9.5 - m.cut_in_wind_speed)
            rpm_target = m.rated_rotor_rpm * max(0.45, min(1.0, frac))
            rpm_tau = 10.0
        else:
            braked = self.tripped or self.manual_stop
            rpm_target = 0.0 if braked else min(0.6, 0.06 * wind_speed)
            rpm_tau = 25.0
        if not self._warm:
            self.rotor_rpm = rpm_target
        self.rotor_rpm += (rpm_target - self.rotor_rpm) * (1.0 - math.exp(-dt / rpm_tau))
        rotor_out = max(0.0, self.rotor_rpm + rng.gauss(0.0, 0.03))
        speed_frac = self.rotor_rpm / m.rated_rotor_rpm
        rotating = speed_frac > 0.2

        if self.producing:
            if wind_speed > m.rated_wind_speed:
                over = (wind_speed - m.rated_wind_speed) / (m.cut_out_wind_speed - m.rated_wind_speed)
                pitch_target = 1.5 + 21.0 * min(1.0, over) ** 0.85
            else:
                pitch_target = 0.6
            if avail > limit + 1.0:
                pitch_target += 14.0 * (1.0 - limit / avail) ** 0.7
        else:
            pitch_target = 88.0
        if not self._warm:
            self.pitch = pitch_target
        step_max = 6.0 * dt
        self.pitch += max(-step_max, min(step_max, pitch_target - self.pitch))
        pitch_out = self.pitch + fx.pitch_deviation / 3.0 + rng.gauss(0.0, 0.05)
        pitch_deviation = max(0.0, fx.pitch_deviation + rng.gauss(0.0, 0.15))

        # ---- temperatures --------------------------------------------------
        k = self.thermal_k
        d_amb = amb - 15.0
        if rotating:
            tg_oil = (52.0 + 14.0 * load) * k + 0.25 * d_amb
            tg_gen = (60.0 + 50.0 * load ** 1.3) * k + 0.30 * d_amb
            tg_genb = (42.0 + 22.0 * load) * k + 0.30 * d_amb
            tg_main = (30.0 + 14.0 * speed_frac) * k + 0.40 * d_amb
            tg_trafo = (45.0 + 38.0 * load ** 1.2) * k + 0.40 * d_amb
        else:
            tg_oil, tg_gen, tg_genb = amb + 10.0, amb + 8.0, amb + 6.0
            tg_main, tg_trafo = amb + 4.0, amb + 10.0
        tg_gbxb = tg_oil + 3.0 + 7.0 * load
        tg_nac = amb + 6.0 + 9.0 * load
        if not self._warm:
            self.t_gbx_oil, self.t_gbx_bearing = tg_oil, tg_gbxb
            self.t_gen_winding, self.t_gen_bearing = tg_gen, tg_genb
            self.t_main_bearing, self.t_nacelle, self.t_transformer = tg_main, tg_nac, tg_trafo
        self.t_gbx_oil += (tg_oil - self.t_gbx_oil) * (1.0 - math.exp(-dt / 420.0))
        self.t_gbx_bearing += (tg_gbxb - self.t_gbx_bearing) * (1.0 - math.exp(-dt / 300.0))
        self.t_gen_winding += (tg_gen - self.t_gen_winding) * (1.0 - math.exp(-dt / 360.0))
        self.t_gen_bearing += (tg_genb - self.t_gen_bearing) * (1.0 - math.exp(-dt / 400.0))
        self.t_main_bearing += (tg_main - self.t_main_bearing) * (1.0 - math.exp(-dt / 900.0))
        self.t_nacelle += (tg_nac - self.t_nacelle) * (1.0 - math.exp(-dt / 900.0))
        self.t_transformer += (tg_trafo - self.t_transformer) * (1.0 - math.exp(-dt / 1200.0))
        # Fault heat appears faster than the bulk thermal mass responds.
        a_fast = 1.0 - math.exp(-dt / 40.0)
        self.add_gbx_oil += (fx.gbx_oil_temp_add - self.add_gbx_oil) * a_fast
        self.add_gbx_bearing += (fx.gbx_bearing_temp_add - self.add_gbx_bearing) * a_fast
        self.add_gen_winding += (fx.gen_winding_temp_add - self.add_gen_winding) * a_fast
        self.add_gen_bearing += (fx.gen_bearing_temp_add - self.add_gen_bearing) * a_fast

        oil_true = self.t_gbx_oil + self.add_gbx_oil
        oil_measured = (oil_true + self.sensor_bias["gearboxOilTemp"]
                        + fx.oil_temp_sensor_bias + rng.gauss(0.0, 0.15))
        if fx.freeze_oil_temp:
            if self._frozen_oil is None:
                self._frozen_oil = self._signals.get("gearboxOilTemp", oil_measured)
            oil_measured = self._frozen_oil
        else:
            self._frozen_oil = None

        # ---- vibration, pressures, grid -----------------------------------
        gbx_vib = (self.vib_base * (0.35 + 0.65 * speed_frac ** 2) + 0.5 * load
                   + rng.gauss(0.0, 0.10)
                   + fx.gbx_vib_add * (1.0 + 0.10 * rng.gauss(0.0, 1.0)))
        tower_vib = (0.25 + 0.45 * wind_speed / 25.0 + 0.15 * speed_frac
                     + rng.gauss(0.0, 0.04) + fx.tower_vib_add)
        if rotating:
            oil_press = 3.2 - 0.012 * (oil_true - 55.0) + fx.gbx_oil_pressure_add + rng.gauss(0.0, 0.03)
        else:
            oil_press = 0.8 + rng.gauss(0.0, 0.02)
        hyd = (186.0 + 3.0 * math.sin(2.0 * math.pi * sim_t / 47.0 + self.hyd_phase)
               + rng.gauss(0.0, 0.8) + fx.hyd_pressure_add)
        reactive = 0.2 * power_out + rng.gauss(0.0, 8.0) if self.producing else rng.gauss(0.0, 1.0)

        if self.power > 0.0:
            self.energy_total_kwh += self.power * dt / 3600.0

        self._signals = {
            "windSpeed": max(0.0, wind_speed + self.sensor_bias["windSpeed"] + rng.gauss(0.0, 0.05)),
            "windDirection": wrap360(wd + rng.gauss(0.0, 0.8)),
            "ambientTemp": amb + rng.gauss(0.0, 0.1),
            "activePower": power_out,
            "reactivePower": reactive,
            "powerSetpoint": min(limit, m.rated_power_kw),
            "rotorSpeed": rotor_out,
            "generatorSpeed": rotor_out * m.gear_ratio,
            "pitchAngle": pitch_out,
            "nacelleDirection": self.nacelle_dir,
            "yawError": vane_error + rng.gauss(0.0, 0.3),
            "gearboxOilTemp": oil_measured,
            "gearboxBearingTemp": self.t_gbx_bearing + self.add_gbx_bearing + rng.gauss(0.0, 0.15),
            "gearboxOilPressure": max(0.0, oil_press),
            "gearboxVibration": max(0.05, gbx_vib),
            "generatorWindingTemp": (self.t_gen_winding + self.add_gen_winding
                                     + self.sensor_bias["generatorWindingTemp"] + rng.gauss(0.0, 0.2)),
            "generatorBearingTemp": self.t_gen_bearing + self.add_gen_bearing + rng.gauss(0.0, 0.15),
            "mainBearingTemp": self.t_main_bearing + rng.gauss(0.0, 0.1),
            "nacelleTemp": self.t_nacelle + rng.gauss(0.0, 0.1),
            "transformerTemp": self.t_transformer + rng.gauss(0.0, 0.15),
            "towerVibration": max(0.02, tower_vib),
            "hydraulicPressure": hyd,
            "gridVoltage": 690.0 * (grid_v_pu + rng.gauss(0.0, 0.0015)),
            "gridFrequency": grid_freq + rng.gauss(0.0, 0.004),
            "energyTotal": self.energy_total_kwh,
            "_pitchDeviation": pitch_deviation,
        }

        # ---- protection and state -----------------------------------------
        self._evaluate_alarms(sim_t, iso_ts, dt)
        self.comms_down = fx.comms_down
        if self._was_comms_down and not self.comms_down:
            self._emit_event_alarm("COMMS-RESTORED", "raised", iso_ts, sim_t)
        self._was_comms_down = self.comms_down
        self._update_state(sim_t, iso_ts)
        self._warm = True

    # ------------------------------------------------------------------ #
    def _derate_factor(self, sim_t: float) -> float:
        factor = 1.0
        for code, st in self.alarms.items():
            a = ALARMS_BY_CODE[code]
            if a.action != "derate":
                continue
            if st.active or (st.derate_release_at is not None and sim_t < st.derate_release_at):
                factor = min(factor, a.derate_to)
        return factor

    def _evaluate_alarms(self, sim_t: float, iso_ts: str, dt: float) -> None:
        alpha = 1.0 - math.exp(-dt / ALARM_FILTER_S)
        for a in THRESHOLD_ALARMS:
            raw = self._signals[a.signal]
            prev = self._filtered.get(a.signal, raw)
            self._filtered[a.signal] = prev + (raw - prev) * alpha

        any_active = False
        for a in THRESHOLD_ALARMS:
            st = self.alarms[a.code]
            value = self._filtered[a.signal]
            if a.direction == "high":
                over = value >= a.threshold
                clear = value < a.threshold - a.hysteresis
            else:
                over = value <= a.threshold
                clear = value > a.threshold + a.hysteresis
            if not st.active:
                if over:
                    if st.pending_since is None:
                        st.pending_since = sim_t
                    if sim_t - st.pending_since >= a.on_delay_s:
                        self._raise(a, st, value, iso_ts, sim_t)
                else:
                    st.pending_since = None
            else:
                if clear:
                    if st.clearing_since is None:
                        st.clearing_since = sim_t
                    if sim_t - st.clearing_since >= a.off_delay_s:
                        self._clear(a, st, value, iso_ts, sim_t)
                else:
                    st.clearing_since = None
            if st.active and a.severity != "info":
                any_active = True

        if self.tripped:
            if any_active:
                self._trip_clear_since = None
            else:
                if self._trip_clear_since is None:
                    self._trip_clear_since = sim_t
                if sim_t - self._trip_clear_since >= TRIP_LOCKOUT_S:
                    self.tripped = False
                    self._trip_clear_since = None

    def _raise(self, a: AlarmDef, st: _AlarmState, value: float, iso_ts: str, sim_t: float) -> None:
        st.active = True
        st.pending_since = None
        st.clearing_since = None
        st.alarm_id = uuid.UUID(int=self.rng.getrandbits(128)).hex
        st.raised_at = sim_t
        st.derate_release_at = None
        if a.action == "trip":
            self.tripped = True
            self._trip_clear_since = None
        self.events.append(self._alarm_event(a, st, "raised", value, iso_ts, None))

    def _clear(self, a: AlarmDef, st: _AlarmState, value: float, iso_ts: str, sim_t: float) -> None:
        st.active = False
        st.clearing_since = None
        if a.action == "derate":
            st.derate_release_at = sim_t + DERATE_LATCH_S
        self.events.append(self._alarm_event(a, st, "cleared", value, iso_ts, sim_t - st.raised_at))

    def _alarm_event(self, a: AlarmDef, st: _AlarmState, status: str, value: float | None,
                     iso_ts: str, duration: float | None) -> dict:
        return {
            "messageType": "alarm",
            "timestamp": iso_ts,
            "data": {
                "alarmId": st.alarm_id,
                "alarmCode": a.code,
                "status": status,
                "severity": a.severity,
                "component": a.component,
                "description": a.description,
                "value": None if value is None else round(value, 2),
                "threshold": a.threshold,
                "unit": a.unit,
                "durationSeconds": None if duration is None else round(duration),
                "sop": a.sop,
            },
        }

    def _emit_event_alarm(self, code: str, status: str, iso_ts: str, sim_t: float) -> None:
        a = ALARMS_BY_CODE[code]
        st = self.alarms[code]
        if status == "raised":
            st.alarm_id = uuid.UUID(int=self.rng.getrandbits(128)).hex
            st.raised_at = sim_t
            st.active = code != "COMMS-RESTORED"
            self.events.append(self._alarm_event(a, st, "raised", None, iso_ts, None))
        elif st.active:
            st.active = False
            self.events.append(self._alarm_event(a, st, "cleared", None, iso_ts, sim_t - st.raised_at))

    def _update_state(self, sim_t: float, iso_ts: str) -> None:
        derated = self._derate_factor(sim_t) < 1.0
        curtailed = self.setpoint_kw is not None and self.setpoint_kw < self.model.rated_power_kw
        if self.manual_stop:
            new, reason = (MAINTENANCE if "maint" in self.manual_stop.lower() else STOPPED), self.manual_stop
        elif self.tripped:
            new, reason = FAULT, "protection trip"
        elif self.paused_until is not None:
            new, reason = PAUSED, "cable untwist"
        elif self.high_wind:
            new, reason = STOPPED_HIGH_WIND, "wind above cut-out"
        elif not self.producing:
            new, reason = IDLE, "wind below cut-in"
        elif derated:
            new, reason = DERATED, "protective derate"
        elif curtailed:
            new, reason = CURTAILED, "remote setpoint"
        else:
            new, reason = RUNNING, "normal operation"

        for code, active in (("MANUAL-STOP", bool(self.manual_stop)),
                             ("YAW-UNTWIST", self.paused_until is not None),
                             ("HIGH-WIND-STOP", self.high_wind),
                             ("POWER-CURTAILED", curtailed)):
            if active != self.alarms[code].active:
                self._emit_event_alarm(code, "raised" if active else "cleared", iso_ts, sim_t)

        if new != self.state and self._warm:
            self.events.append({
                "messageType": "state",
                "timestamp": iso_ts,
                "data": {"previousState": self.state, "state": new, "reason": reason},
            })
        self.state = new

    # ------------------------------------------------------------------ #
    def telemetry(self) -> dict:
        s = self._signals
        out = {"state": self.state}
        for key, digits in _ROUNDING.items():
            out[key] = round(s[key], digits)
        return out

    def active_alarm_codes(self) -> list[str]:
        return sorted(code for code, st in self.alarms.items() if st.active)

    def registry(self) -> dict:
        sp, m = self.spec, self.model
        return {
            "name": sp.name,
            "assetType": "WindTurbine",
            "model": m.model,
            "manufacturer": m.manufacturer,
            "serialNumber": sp.serial_number,
            "ratedPowerKw": m.rated_power_kw,
            "rotorDiameterM": m.rotor_diameter_m,
            "hubHeightM": m.hub_height_m,
            "latitude": sp.latitude,
            "longitude": sp.longitude,
            "elevationM": sp.elevation_m,
            "localX": sp.x,
            "localY": sp.y,
            "string": sp.string,
            "commissionedDate": sp.commissioned_date,
        }


_ROUNDING = {
    "windSpeed": 2, "windDirection": 1, "ambientTemp": 1,
    "activePower": 1, "reactivePower": 1, "powerSetpoint": 0,
    "rotorSpeed": 2, "generatorSpeed": 0, "pitchAngle": 2,
    "nacelleDirection": 1, "yawError": 1,
    "gearboxOilTemp": 1, "gearboxBearingTemp": 1, "gearboxOilPressure": 2,
    "gearboxVibration": 2, "generatorWindingTemp": 1, "generatorBearingTemp": 1,
    "mainBearingTemp": 1, "nacelleTemp": 1, "transformerTemp": 1,
    "towerVibration": 2, "hydraulicPressure": 1, "gridVoltage": 1,
    "gridFrequency": 3, "energyTotal": 1,
}
