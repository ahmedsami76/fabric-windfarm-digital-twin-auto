"""Synthetic operating history of the wind farm.

``generate(site, as_of)`` returns pandas DataFrames that together look like what an
operator has after a few years of running a site: 10-minute SCADA statistics, the
availability log, alarms, work orders with cost and parts, oil analysis, blade
inspections, grid curtailments, market prices, day-ahead forecasts and the budget.

The tables are consistent with each other (an outage has its alarm, its work order,
its parts and its lost energy) and with the reference data, the live simulator and
the forecast, which all use the same site definition and the same climate.

The past is stable: the weather and the random faults of a given day do not depend
on when the history is generated. Only the "current situation" (open work orders,
the latest oil samples, the conditions that are developing now) moves with ``as_of``.

Needs numpy and pandas; scipy is used when present. No imports from the rest of the
package except ``catalog`` and ``climate``, so the Fabric notebooks can carry a copy.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .catalog import (BUDGET_CORRECTIVE_USD_PER_MONTH, BUDGET_FIXED_OPEX_USD_PER_MONTH, COMPONENT_LABELS,
                      FAULT_PRONE, FAULT_RATE_PER_YEAR, FAULT_TYPES, FIELD_TECHNICIANS,
                      GUARANTEED_AVAILABILITY_PCT, LABOR_RATE_USD_PER_HOUR, PART_BY_ID, PPA_PRICE_USD_PER_MWH,
                      STANDING_CONDITIONS)
from .climate import DAY_S, Climate, turbine_character

HISTORY_START = "2025-01-01T00:00:00+00:00"
STEP_S = 600
AUX_POWER_KW = -12.0
STANDARD_AIR_DENSITY = 1.225
ACCESS_WIND_LIMIT = 18.0       # technicians do not climb above this hub-height wind speed (m/s)

# Stop reasons, in the order of the code stored per turbine and interval.
NONE, FORCED, SCHEDULED, PLANNED, GRID_OUT, ICING, HIGH_WIND, STANDBY = range(8)
_PRIORITY = np.array([0, 9, 8, 8, 6, 5, 4, 2])
CATEGORY = {FORCED: "Forced outage", SCHEDULED: "Scheduled maintenance", PLANNED: "Planned corrective action",
            GRID_OUT: "Out of electrical specification", ICING: "Out of environmental specification",
            HIGH_WIND: "Out of environmental specification", STANDBY: "Technical standby"}
STATE = {FORCED: "FAULT", SCHEDULED: "MAINTENANCE", PLANNED: "MAINTENANCE", GRID_OUT: "STOPPED",
         ICING: "STOPPED", HIGH_WIND: "STOPPED_HIGH_WIND", STANDBY: "PAUSED"}
CAUSE = {GRID_OUT: "Grid outage", ICING: "Icing", HIGH_WIND: "High wind", STANDBY: "Cable untwist"}


# --------------------------------------------------------------------------- small helpers
def _epoch(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _ts(epoch) -> pd.Timestamp:
    return pd.Timestamp(float(epoch), unit="s").floor("s")


def _frame(rows: list[dict], columns: tuple) -> pd.DataFrame:
    """A table with exactly these columns, also when there are no rows (a short history)."""
    return pd.DataFrame(rows, columns=list(columns))


EVENT_COLUMNS = ("EventId", "TurbineId", "StartTime", "EndTime", "DurationHours", "AvailabilityCategory", "Cause",
                 "ComponentCode", "Component", "AlarmCode", "FaultClass", "FailureMode", "ResponsibleParty",
                 "Description", "LostEnergyMwh", "order")
ORDER_COLUMNS = ("WorkOrderId", "TurbineId", "ComponentId", "WorkType", "Priority", "Status", "OpenedDate",
                 "ScheduledDate", "ClosedDate", "Summary", "Findings", "FailureMode", "LaborHours", "CrewSize",
                 "LaborCostUsd", "PartsCostUsd", "OtherCostUsd", "TotalCostUsd", "DowntimeHours",
                 "WaitingForPartsHours", "LeadTechnicianId", "EventId", "SopId", "CoveredByWarranty", "CostBorneBy")
PART_COLUMNS = ("WorkOrderId", "PartId", "Quantity", "UnitCostUsd", "TotalCostUsd")
ALARM_COLUMNS = ("AlarmId", "TurbineId", "AlarmCode", "RaisedAt", "ClearedAt", "DurationMinutes", "EventId")
OIL_COLUMNS = ("SampleId", "TurbineId", "ComponentId", "SampleDate", "IronPpm", "CopperPpm", "SiliconPpm", "WaterPpm",
               "ViscosityAt40C", "ParticleCountIso4406", "Condition", "LabComment")
BLADE_COLUMNS = ("InspectionId", "TurbineId", "Blade", "InspectionDate", "Method", "FindingType", "SeverityCategory",
                 "SpanPositionM", "RecommendedAction", "Status", "RepairWorkOrderId", "order")
CURTAILMENT_COLUMNS = ("CurtailmentId", "StartTime", "EndTime", "DurationHours", "SetpointMw", "SetpointPctOfCapacity",
                       "Reason", "InstructedBy", "Compensated", "AvgRealTimePriceUsdPerMwh", "LostEnergyMwh")


def _day(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).date().isoformat()


def power_curve_kw(wind_speed, model: dict):
    """Reference power curve at standard air density. Same formula as the live turbine model."""
    v = np.asarray(wind_speed, dtype=np.float64)
    ci, r, co = float(model["cutInWindSpeed"]), float(model["ratedWindSpeed"]), float(model["cutOutWindSpeed"])
    rated = float(model["ratedPowerKw"])
    p = rated * (np.clip(v, ci, r) ** 3 - ci ** 3) / (r ** 3 - ci ** 3)
    return np.where((v < ci) | (v > co), 0.0, p)


def wake_table(site: dict) -> np.ndarray:
    """Wake factor per 5 degree wind direction bucket and turbine. Same model as the live wind field."""
    xs = np.array([float(t["x"]) for t in site["turbines"]])
    ys = np.array([float(t["y"]) for t in site["turbines"]])
    d_rotor = float(site["turbineModel"]["rotorDiameterM"])
    table = np.ones((72, len(xs)))
    for bucket in range(72):
        rad = math.radians(bucket * 5.0 + 2.5)
        ux, uy = -math.sin(rad), -math.cos(rad)
        dx, dy = xs[:, None] - xs[None, :], ys[:, None] - ys[None, :]
        down = dx * ux + dy * uy
        cross = np.abs(dx * uy - dy * ux)
        width = 0.5 * d_rotor + 0.06 * np.maximum(down, 0.0)
        centre = 0.30 / (1.0 + 0.09 * np.maximum(down, 0.0) / d_rotor) ** 2
        deficit = np.where((down > 0.0) & (down <= 14.0 * d_rotor), centre * np.exp(-(cross / width) ** 2), 0.0)
        np.fill_diagonal(deficit, 0.0)
        table[bucket] = 1.0 - np.minimum(0.35, np.sqrt(np.sum(deficit ** 2, axis=1)))
    return table


def speedup(site: dict) -> np.ndarray:
    elev = np.array([float(t["elevationM"]) for t in site["turbines"]])
    return 1.0 + 0.10 * (elev - elev.mean()) / max(1.0, elev.max() - elev.min())


def _lag(x: np.ndarray, tau_s: float) -> np.ndarray:
    """First-order lag along the time axis, the 10-minute counterpart of the live thermal model."""
    alpha = 1.0 - math.exp(-STEP_S / tau_s)
    try:
        from scipy.signal import lfilter
        return x[0] + lfilter([alpha], [1.0, alpha - 1.0], x - x[0], axis=0)
    except ImportError:                                   # pragma: no cover - scipy is normally there
        out = np.empty_like(x)
        out[0] = x[0]
        for i in range(1, len(x)):
            out[i] = out[i - 1] + alpha * (x[i] - out[i - 1])
        return out


def _band(wind: np.ndarray, sigma: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """10% and 90% bounds of a wind forecast. The spread covers the forecast error and the
    hour-to-hour variability that no forecast resolves."""
    spread = 1.2816 * np.sqrt(sigma ** 2 + 0.14 ** 2)
    return wind * np.exp(-spread), wind * np.exp(spread)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Start and end (exclusive) index of every run of True values."""
    if not mask.any():
        return []
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist()))


class _Calendar:
    """Working hours of the site crew, in local time: Monday to Saturday, 07:00 to 17:00."""

    def __init__(self, tz_name: str):
        self.tz = ZoneInfo(tz_name)

    def local(self, epoch: float) -> datetime:
        return datetime.fromtimestamp(epoch, self.tz)

    def at(self, day: datetime, hour: float) -> float:
        base = datetime(day.year, day.month, day.day, tzinfo=self.tz)
        return (base + timedelta(hours=hour)).timestamp()

    def work_start_after(self, epoch: float) -> float:
        d = self.local(epoch)
        for _ in range(10):
            start, end = self.at(d, 7.0), self.at(d, 17.0)
            if d.weekday() != 6:
                if epoch <= start:
                    return start
                if epoch < end - 3600.0:
                    return epoch
            d = d + timedelta(days=1)
            epoch = self.at(d, 0.0)
        return epoch

    def add_work_hours(self, epoch: float, hours: float) -> float:
        epoch = self.work_start_after(epoch)
        remaining = hours * 3600.0
        for _ in range(60):
            end = self.at(self.local(epoch), 17.0)
            if epoch + remaining <= end:
                return epoch + remaining
            remaining -= max(0.0, end - epoch)
            epoch = self.work_start_after(end + 1.0)
        return epoch + remaining


# --------------------------------------------------------------------------- the generator
class _History:
    def __init__(self, site: dict, as_of, start, seed: int | None):
        self.site = site
        self.model = site["turbineModel"]
        self.rated = float(self.model["ratedPowerKw"])
        self.ids = [t["turbineId"] for t in site["turbines"]]
        self.n = len(self.ids)
        self.index = {tid: i for i, tid in enumerate(self.ids)}
        self.seed = int(site.get("climateSeed", 20211) if seed is None else seed)
        self.climate = Climate.for_site(site, self.seed)
        self.cal = _Calendar(site["timezone"])

        self.t0 = _epoch(start)
        self.as_of = _epoch(datetime.now(timezone.utc) if as_of is None else as_of)
        steps = int((self.as_of - self.t0) // STEP_S)
        if steps < 30 * 144:
            raise ValueError("the history needs at least 30 days between its start and as_of")
        self.N = steps
        self.t = self.t0 + STEP_S * np.arange(steps, dtype=np.float64)
        self.end = self.t0 + STEP_S * steps
        self.day0 = int(self.t0 // DAY_S)
        self.days = int(math.ceil(steps / 144))

        self.stop = np.zeros((self.N, self.n), dtype=np.int8)
        self.derate = np.ones((self.N, self.n), dtype=np.float32)
        self.nodata = np.zeros((self.N, self.n), dtype=bool)
        self.curtail = np.ones(self.N, dtype=np.float32)
        self.events: list[dict] = []
        self.alarms: list[dict] = []
        self.orders: list[dict] = []
        self.order_parts: list[dict] = []
        self.oil: list[dict] = []
        self.blades: list[dict] = []
        self.curtailments: list[dict] = []
        self.service_days: dict[str, list[float]] = {tid: [] for tid in self.ids}

    # ---- indexing ----------------------------------------------------------------
    def i(self, epoch: float) -> int:
        return int(min(self.N, max(0, math.floor((epoch - self.t0) / STEP_S))))

    def ago(self, days: float) -> float:
        return self.as_of - days * DAY_S

    def workday(self, days_from_now: float) -> float:
        """07:30 local time on the working day that many days from now (negative = in the past)."""
        d = self.cal.local(self.as_of + days_from_now * DAY_S)
        if d.weekday() == 6:
            d = d + timedelta(days=1)
        return self.cal.at(d, 7.5)

    def rng(self, stream: int, key: int = 0) -> np.random.Generator:
        return np.random.default_rng([self.seed, stream, key])

    def _mark(self, turbine: int | None, start: float, end: float, code: int) -> None:
        a, b = self.i(start), self.i(end)
        if b <= a:
            b = min(self.N, a + 1)
        cols = slice(None) if turbine is None else turbine
        current = self.stop[a:b, cols]
        self.stop[a:b, cols] = np.where(_PRIORITY[code] > _PRIORITY[current], code, current)

    def _event(self, turbine: str, start: float, end: float, code: int, cause: str, component: str = "",
               alarm: str = "", fault_class: str = "", failure_mode: str = "", responsible: str = "",
               description: str = "") -> dict:
        end = min(end, self.end)
        ev = {"EventId": f"EV-{turbine}-{datetime.fromtimestamp(start, timezone.utc):%Y%m%d%H%M}",
              "TurbineId": turbine, "start": start, "end": end, "code": code,
              "AvailabilityCategory": CATEGORY[code], "Cause": cause, "ComponentCode": component,
              "Component": COMPONENT_LABELS.get(component, ""), "AlarmCode": alarm, "FaultClass": fault_class,
              "FailureMode": failure_mode, "ResponsibleParty": responsible, "Description": description,
              "WorkOrderId": "", "ongoing": end >= self.end}
        self.events.append(ev)
        if turbine != "SITE":
            self._mark(self.index[turbine], start, end, code)
        return ev

    def _alarm(self, turbine: str, code: str, raised: float, cleared: float | None, event: dict | None = None) -> None:
        if raised >= self.end:
            return
        if cleared is not None and cleared >= self.end:
            cleared = None
        self.alarms.append({"TurbineId": turbine, "AlarmCode": code, "raised": raised, "cleared": cleared,
                            "EventId": event["EventId"] if event else ""})

    def _order(self, turbine: str, component: str, work_type: str, status: str, opened: float, summary: str,
               findings: str = "", scheduled: float | None = None, closed: float | None = None,
               labor_hours: float = 0.0, crew: int = 2, parts: tuple = (), other_cost: float = 0.0,
               downtime_hours: float = 0.0, lead: str = "", event: dict | None = None, sop: str = "",
               failure_mode: str = "", priority: str = "Normal", warranty: bool = False,
               waiting_hours: float = 0.0) -> dict:
        parts_cost = 0.0
        key = len(self.orders)
        for part_id, quantity in parts:
            unit = float(PART_BY_ID[part_id][6])
            parts_cost += unit * quantity
            self.order_parts.append({"order": key, "PartId": part_id, "Quantity": quantity, "UnitCostUsd": unit})
        labor_cost = round(labor_hours * crew * LABOR_RATE_USD_PER_HOUR, 2)
        order = {"key": key, "TurbineId": turbine, "ComponentId": f"{turbine}-{component}" if component else "",
                 "WorkType": work_type, "Priority": priority, "Status": status, "opened": opened,
                 "scheduled": scheduled, "closed": closed, "Summary": summary, "Findings": findings,
                 "FailureMode": failure_mode, "LaborHours": round(labor_hours * crew, 1), "CrewSize": crew,
                 "LaborCostUsd": labor_cost, "PartsCostUsd": round(parts_cost, 2),
                 "OtherCostUsd": round(other_cost, 2),
                 "TotalCostUsd": round(labor_cost + parts_cost + other_cost, 2),
                 "DowntimeHours": round(downtime_hours, 1), "WaitingForPartsHours": round(waiting_hours, 1),
                 "LeadTechnicianId": lead, "EventId": event["EventId"] if event else "", "SopId": sop,
                 "CoveredByWarranty": warranty,
                 # Who pays, under the contracts in the reference data.
                 "CostBorneBy": ("Warranty" if warranty else "Owner" if work_type == "Corrective"
                                 else "Service agreement")}
        self.orders.append(order)
        if event is not None:
            event["order"] = key
        return order

    # ---- weather -----------------------------------------------------------------
    def weather(self) -> None:
        c, t = self.climate, self.t
        self.ws_site = c.wind_10min(t)
        self.wd = c.wind_direction(t)
        self.temp = c.temperature(t)
        self.hum = c.humidity(t)
        self.press = c.pressure_hpa(t)
        self.rho = c.air_density(t)
        self.ice = c.icing(t)
        wake = wake_table(self.site)[(self.wd // 5).astype(int) % 72]
        noise = np.empty((self.N, self.n, 4), dtype=np.float32)
        for d in range(self.days):
            a, b = d * 144, min(self.N, (d + 1) * 144)
            noise[a:b] = self.rng(0x7015E, self.day0 + d).standard_normal((b - a, self.n, 4), dtype=np.float32)
        self.noise = noise
        self.ws = np.maximum(0.0, self.ws_site[:, None] * speedup(self.site)[None, :] * wake
                             * (1.0 + 0.035 * noise[:, :, 0]))
        local = pd.to_datetime(t, unit="s", utc=True).tz_convert(self.site["timezone"])
        self.local_hour = np.asarray(local.hour + local.minute / 60.0)
        self.month = np.asarray(local.month)

    # ---- environment and grid ------------------------------------------------------
    def environment(self) -> None:
        thaw = 9                                             # intervals a turbine needs after the ice is gone
        for k, (a, b) in enumerate(_runs(self.ice)):
            if b - a < 3:
                continue
            rng = self.rng(0x1CE, self.day0 + a // 144)
            for i, tid in enumerate(self.ids):
                if rng.random() < 0.88:
                    start = self.t[a] + rng.uniform(0, 3) * STEP_S
                    end = self.t0 + (b + thaw + rng.integers(0, 12)) * STEP_S
                    ev = self._event(tid, start, end, ICING, "Icing", responsible="Environment",
                                     description="Ice detected on blades; turbine stopped until the ice had gone.")
                    self._alarm(tid, "ENV-ICE-DETECTED", start, ev["end"], ev)
        co = float(self.model["cutOutWindSpeed"])
        for i, tid in enumerate(self.ids):
            last_end = -1
            for a, b in _runs(self.ws[:, i] > co):
                if a < last_end:
                    continue
                end = b
                while end < self.N and self.ws[end, i] > co - 3.0:
                    end += 1
                last_end = end
                ev = self._event(tid, self.t[a], self.t0 + end * STEP_S, HIGH_WIND, "High wind",
                                 responsible="Environment", description="Wind above cut-out speed.")
                self._alarm(tid, "HIGH-WIND-STOP", self.t[a], ev["end"], ev)

    def grid_outages(self) -> None:
        for d in range(self.days):
            rng = self.rng(0x621D, self.day0 + d)
            if rng.random() < 0.0045:
                start = self.t0 + d * DAY_S + rng.uniform(0, DAY_S)
                hours = float(np.clip(rng.lognormal(math.log(2.4), 0.7), 0.4, 14.0))
                reason = rng.choice(["Transmission line trip", "Substation breaker maintenance by the grid operator",
                                     "Substation protection trip"])
                for tid in self.ids:
                    ev = self._event(tid, start, start + hours * 3600 + 600, GRID_OUT, "Grid outage", "GRID",
                                     "GRID-LOSS", responsible="Grid operator", description=str(reason))
                    self._alarm(tid, "GRID-LOSS", start, ev["end"], ev)

    def market(self) -> None:
        """Hourly market prices and the curtailment that follows from them."""
        hours = self.N // 6
        th = self.t0 + 3600.0 * np.arange(hours)
        ws_h = self.ws_site[:hours * 6].reshape(hours, 6).mean(axis=1)
        wind_cf = power_curve_kw(ws_h * 0.93, self.model) / self.rated          # regional wind output
        hour = self.local_hour[:hours * 6:6]
        month = self.month[:hours * 6:6]
        summer = np.isin(month, (6, 7, 8, 9))
        load = np.where(summer, 0.62 + 0.38 * np.exp(-((hour - 16.5) / 4.0) ** 2),
                        0.60 + 0.22 * np.exp(-((hour - 7.5) / 2.0) ** 2) + 0.26 * np.exp(-((hour - 19.0) / 2.5) ** 2))
        noise = np.concatenate([self.rng(0x9A1CE, self.day0 + d).standard_normal(24) for d in range(self.days)])[:hours]
        extra = np.concatenate([self.rng(0x9A1CF, self.day0 + d).random(24) for d in range(self.days)])[:hours]
        rt = (20.0 + 46.0 * load ** 3) * (1.0 - 0.74 * wind_cf ** 1.3) + 5.0 * noise
        glut = np.clip((wind_cf - 0.70) / 0.30, 0.0, 1.0) * np.clip((0.76 - load) / 0.16, 0.0, 1.0)
        rt -= glut * (14.0 + 34.0 * extra ** 2)
        scarce = summer & (hour >= 15) & (hour <= 19) & (wind_cf < 0.22) & (extra < 0.07)
        rt = np.where(scarce, rt * (3.0 + 40.0 * extra / 0.07 * np.abs(noise)), rt)
        iced = self.ice[:hours * 6].reshape(hours, 6).any(axis=1)
        rt = np.where(iced, 180.0 + 1400.0 * extra + 300.0 * np.abs(noise), rt)
        rt = np.clip(rt, -35.0, 5000.0)
        kernel = np.array([0.2, 0.6, 0.2])
        da = np.convolve(np.minimum(rt, 600.0), kernel, mode="same") * (1.0 + 0.2 * (extra - 0.5)) + 1.5
        self.prices = pd.DataFrame({"Timestamp": pd.to_datetime(th, unit="s"), "SettlementPoint": "HB_WEST",
                                    "DayAheadPriceUsdPerMwh": np.round(da, 2),
                                    "RealTimePriceUsdPerMwh": np.round(rt, 2)})
        self.price_rt = rt

        capacity_mw = self.rated * self.n / 1000.0
        frac_h = np.ones(hours, dtype=np.float32)
        reason_h = np.zeros(hours, dtype=np.int8)                # 1 economic, 2 congestion, 3 test
        frac_h = np.where(rt < -33.0, 0.0, np.where(rt < -29.0, 0.25, np.where(rt < -24.0, 0.5, frac_h)))
        reason_h = np.where(frac_h < 1.0, 1, reason_h)
        for d in range(self.days):
            rng = self.rng(0xC0196, self.day0 + d)
            spring = 2.0 if int(month[min(hours - 1, d * 24)]) in (3, 4, 5) else 1.0
            for h in range(d * 24, min(hours, (d + 1) * 24)):
                if reason_h[h] == 0 and wind_cf[h] > 0.72 and rng.random() < 0.06 * spring:
                    length = int(rng.integers(1, 6))
                    limit = float(rng.choice([0.55, 0.65, 0.75, 0.8]))
                    for hh in range(h, min(hours, h + length)):
                        if reason_h[hh] == 0:
                            frac_h[hh], reason_h[hh] = limit, 2
            if rng.random() < 2.0 / 365.0:
                h = d * 24 + int(rng.integers(15, 22))
                if h < hours and reason_h[h] == 0:
                    frac_h[h], reason_h[h] = 0.5, 3
        self.curtail[:hours * 6] = np.repeat(frac_h, 6)
        reasons = {1: ("Economic curtailment (negative real-time price)", "Offtaker", True),
                   2: ("Congestion (West Texas export constraint)", "Grid operator", False),
                   3: ("Grid operator curtailment test", "Grid operator", False)}
        h = 0
        while h < hours:
            if reason_h[h] == 0:
                h += 1
                continue
            e = h
            while e < hours and reason_h[e] == reason_h[h]:
                e += 1
            reason, by, paid = reasons[int(reason_h[h])]
            start = th[h]
            self.curtailments.append({
                "CurtailmentId": f"CU-{datetime.fromtimestamp(start, timezone.utc):%Y%m%d%H%M}",
                "start": start, "end": th[h] + (e - h) * 3600.0, "a": h * 6, "b": e * 6,
                "SetpointMw": round(float(frac_h[h:e].mean()) * capacity_mw, 1),
                "SetpointPctOfCapacity": round(float(frac_h[h:e].mean()) * 100.0, 0),
                "Reason": reason, "InstructedBy": by, "Compensated": paid,
                "AvgRealTimePriceUsdPerMwh": round(float(rt[h:e].mean()), 2)})
            h = e

    # ---- planned work ----------------------------------------------------------------
    def _low_wind_day(self, first_day: float, taken: dict, per_day: int, span: int = 8) -> float:
        """Local midnight of the working day with the least wind among the next few, as a planner
        would pick it from the forecast."""
        best, best_wind = None, 1e9
        d = self.cal.local(first_day)
        for _ in range(span):
            midnight = self.cal.at(d, 0.0)
            if d.weekday() < 5 and taken.get(midnight, 0) < per_day:
                hours = midnight + 3600.0 * np.arange(8, 17)
                wind = float(self.climate.wind_mean(hours).mean())
                if wind < best_wind:
                    best, best_wind = midnight, wind
            d = d + timedelta(days=1)
        if best is None:
            best = self.cal.at(d, 0.0)
        taken[best] = taken.get(best, 0) + 1
        return best

    def scheduled_maintenance(self) -> None:
        first_year = datetime.fromtimestamp(self.t0, timezone.utc).year
        last_year = datetime.fromtimestamp(self.end, timezone.utc).year
        tz = self.cal.tz
        for year in range(first_year, last_year + 1):
            campaigns = (
                ("Semi-annual service (spring)", datetime(year, 3, 3, tzinfo=tz), 8.5, 2, "service"),
                ("Annual blade inspection by drone", datetime(year, 6, 2, tzinfo=tz), 1.5, 4, "blades"),
                ("Semi-annual service (autumn)", datetime(year, 9, 8, tzinfo=tz), 9.5, 2, "service"),
                ("Annual safety and lift inspection", datetime(year, 1, 20, tzinfo=tz), 4.0, 3, "safety"),
                ("Annual transformer and switchgear service", datetime(year, 12, 1, tzinfo=tz), 5.0, 3, "electrical"),
            )
            for number, (name, first, hours, per_day, kind) in enumerate(campaigns):
                taken: dict = {}
                for k, tid in enumerate(self.ids):
                    rng = self.rng(0x5E21, year * 10000 + number * 100 + k)
                    earliest = (first + timedelta(days=(k // per_day) * (2 if kind == "service" else 1))).timestamp()
                    if earliest > self.end + 45 * DAY_S or earliest < self.t0:
                        continue
                    midnight = self._low_wind_day(earliest, taken, per_day)
                    day = self.cal.local(midnight + 12 * 3600)
                    start = self.cal.at(day, 7.5 + (0.0 if kind != "blades" else rng.uniform(0, 7)))
                    end = start + hours * 3600.0 * rng.uniform(0.9, 1.15)
                    crew = 3 if kind == "service" else 2
                    lead = str(rng.choice(FIELD_TECHNICIANS[:5]))
                    component = {"service": "GBX", "blades": "BLD", "safety": "TWR", "electrical": "TRF"}[kind]
                    if start >= self.end:                         # still to come
                        self._order(tid, component, "Preventive" if kind != "blades" else "Inspection", "Scheduled",
                                    start - 21 * DAY_S, name, scheduled=start, crew=crew, lead=lead)
                        continue
                    ev = self._event(tid, start, end, SCHEDULED, "Scheduled maintenance", component,
                                     responsible="Operator", description=name)
                    parts = ()
                    findings = "Completed to checklist. No abnormal findings."
                    if kind == "service":
                        parts = (("SP-GBX-FLT-10", 1),) + ((("SP-HYD-OIL-46", 1),) if rng.random() < 0.3 else ())
                        self.service_days[tid].append(start)
                        self._oil_sample(tid, start + 2 * 3600, rng)
                    elif kind == "blades":
                        findings = self._blade_campaign(tid, start, rng)
                    self._order(tid, component, "Preventive" if kind != "blades" else "Inspection", "Closed",
                                start - 21 * DAY_S, name, findings, scheduled=start, closed=ev["end"],
                                labor_hours=(ev["end"] - start) / 3600.0, crew=crew, parts=parts,
                                downtime_hours=(ev["end"] - start) / 3600.0, lead=lead, event=ev)

    # ---- condition data ------------------------------------------------------------------
    def _wear_iron(self, tid: str, when: float) -> float | None:
        """Iron in the gearbox oil of a turbine whose bearing is wearing, or None when it is healthy.
        The points are the lab results of the planted stories; samples in between follow the same curve."""
        if tid == "WT-07":
            ago = (self.as_of - when) / DAY_S
            if 0.0 <= ago < 160.0:
                return float(np.interp(ago, [0.0, 36.0, 99.0, 160.0], [140.0, 118.0, 71.0, 24.0]))
        if tid == "WT-02" and getattr(self, "wt02_failure", 0.0) > when:
            before = (self.wt02_failure - when) / DAY_S
            if before < 200.0:
                return float(np.interp(before, [0.0, 38.0, 92.0, 150.0, 200.0], [270.0, 226.0, 148.0, 82.0, 25.0]))
        return None

    def _oil_sample(self, tid: str, when: float, rng, iron: float | None = None, comment: str = "") -> None:
        if when >= self.end:
            return
        if iron is None:
            worn = self._wear_iron(tid, when)
            iron = float(rng.uniform(14, 34)) if worn is None else worn + float(rng.uniform(-3, 3))
        level = int(np.clip(round(16.5 + 3.2 * math.log10(max(iron, 5.0) / 20.0)), 15, 24))
        condition = "Normal" if iron < 45 else ("Monitor" if iron < 90 else "Action")
        self.oil.append({"SampleId": f"OA-{tid}-{_day(when).replace('-', '')}", "TurbineId": tid,
                         "ComponentId": f"{tid}-GBX", "SampleDate": _day(when), "IronPpm": round(iron, 0),
                         "CopperPpm": round(float(rng.uniform(2, 9)) + iron * 0.03, 0),
                         "SiliconPpm": round(float(rng.uniform(3, 12)), 0),
                         "WaterPpm": round(float(rng.uniform(70, 260)), 0),
                         "ViscosityAt40C": round(float(rng.uniform(302, 331)), 1),
                         "ParticleCountIso4406": f"{level + 3}/{level + 1}/{level - 2}",
                         "Condition": condition,
                         "LabComment": comment or {"Normal": "Oil and wear metals within normal limits.",
                                                   "Monitor": "Wear metals elevated. Shorten the sampling interval.",
                                                   "Action": "Wear metals high. Inspect the gearbox."}[condition]})

    def _blade_campaign(self, tid: str, when: float, rng) -> str:
        year = datetime.fromtimestamp(when, timezone.utc).year
        first_campaign = year == datetime.fromtimestamp(self.t0, timezone.utc).year
        worst = 1
        for blade in "ABC":
            findings = []
            if tid == "WT-09" and blade in "AC":
                findings.append(("Leading-edge erosion", 3 if first_campaign else 4, rng.uniform(52, 71)))
            elif rng.random() < 0.55:
                kind = str(rng.choice(["Leading-edge erosion", "Surface coating damage", "Trailing-edge crack",
                                       "Lightning receptor wear", "Contamination"], p=[0.4, 0.25, 0.1, 0.1, 0.15]))
                findings.append((kind, int(rng.choice([1, 2, 3], p=[0.5, 0.38, 0.12])), rng.uniform(20, 72)))
            for kind, severity, position in findings:
                worst = max(worst, severity)
                open_item = severity >= 4 or (severity == 3 and not first_campaign)
                self.blades.append({
                    "InspectionId": f"BI-{tid}-{blade}-{_day(when).replace('-', '')}-{len(self.blades):04d}",
                    "TurbineId": tid, "Blade": blade, "InspectionDate": _day(when), "Method": "Drone",
                    "FindingType": kind, "SeverityCategory": severity, "SpanPositionM": round(float(position), 1),
                    "RecommendedAction": {1: "None", 2: "Monitor at next inspection", 3: "Repair within 12 months",
                                          4: "Repair within 3 months", 5: "Stop turbine and repair"}[severity],
                    "Status": "Open" if open_item else ("Monitor" if severity >= 2 else "Closed"),
                    "RepairWorkOrderId": ""})
        return {1: "No significant findings.", 2: "Minor findings, monitor.", 3: "Category 3 findings, repair planned.",
                4: "Category 4 leading-edge erosion, repair within 3 months."}.get(worst, "See findings.")

    # ---- repairs ----------------------------------------------------------------------------
    def _wait_for_access(self, epoch: float) -> float:
        for _ in range(40):
            epoch = self.cal.work_start_after(epoch)
            i = self.i(epoch)
            if i >= self.N or (self.ws_site[i] < ACCESS_WIND_LIMIT and not self.ice[i]):
                return epoch
            epoch += 3600.0
        return epoch

    def _repair(self, tid: str, when: float, fault: tuple, rng, fixed_hours: float | None = None,
                wait_days: float | None = None, crew: int = 2, other_cost: float = 0.0, findings: str = "",
                extra_parts: tuple = (), lead: str = "", warranty: bool = False, summary: str = "",
                responsible: str = "Service provider") -> dict:
        code, component, klass, _, mode, text, parts = fault
        if klass == "A":
            end = when + rng.uniform(6, 45) * 60.0
            ev = self._event(tid, when, end, FORCED, "Auto-reset fault", component, code, "A", mode,
                             "Grid operator" if component == "GRID" else "Service provider",
                             "Tripped and restarted by the controller.")
            self._alarm(tid, code, when, ev["end"], ev)
            return ev
        arrive = self._wait_for_access(when + 20 * 60.0) + rng.uniform(0.6, 1.6) * 3600.0
        if wait_days is None:
            wait_days = 0.0
            if klass == "C" and parts:
                part = PART_BY_ID[parts[0]]
                if part[3] < 1 or rng.random() < 0.2:
                    wait_days = part[5] * rng.uniform(0.35, 0.9)
        first_visit = arrive
        if wait_days:
            arrive = self._wait_for_access(arrive + wait_days * DAY_S)
        hours = fixed_hours if fixed_hours is not None else (
            float(np.clip(rng.lognormal(math.log(2.0), 0.5), 0.7, 7.0)) if klass == "B" else float(rng.uniform(5, 13)))
        done = self.cal.add_work_hours(arrive, hours) + 0.4 * 3600.0
        ev = self._event(tid, when, done, FORCED, "Component fault", component, code, klass, mode,
                         responsible, text or summary)
        self._alarm(tid, code, when, ev["end"], ev)
        closed = None if ev["ongoing"] else done
        self._order(tid, component if component in COMPONENT_LABELS and component not in ("CTL", "GRID") else "",
                    "Corrective", "Closed" if closed else "In progress", when + 15 * 60.0, summary or text,
                    findings or f"{mode}. {text}. Function test passed, turbine returned to service.",
                    scheduled=arrive, closed=closed, labor_hours=hours, crew=crew,
                    parts=tuple((p, 1) for p in parts) + tuple(extra_parts), other_cost=other_cost,
                    downtime_hours=(ev["end"] - when) / 3600.0,
                    waiting_hours=(min(arrive, ev["end"]) - min(first_visit, ev["end"])) / 3600.0,
                    lead=lead or str(rng.choice(FIELD_TECHNICIANS[:5])), event=ev,
                    sop={"GBX": "SOP-GBX-001", "GEN": "SOP-GEN-002", "PIT": "SOP-PIT-003", "HYD": "SOP-PIT-003",
                         "YAW": "SOP-YAW-004"}.get(component, "SOP-OPS-000"),
                    failure_mode=mode, priority="High" if klass == "C" else "Normal", warranty=warranty)
        return ev

    def stories(self) -> None:
        """The events an analyst should be able to find: precedents, repeat offenders and what is
        developing now."""
        fault = {f[0]: f for f in FAULT_TYPES}
        rng = self.rng(0x5702)
        # WT-02: high-speed shaft bearing failure, the precedent for WT-07.
        self.wt02_failure = self.ago(418) + 15.3 * 3600
        if self.wt02_failure > self.t0 + 120 * DAY_S:
            for days_before, iron, text in ((150, 82, "Iron elevated. Re-sample in 60 days."),
                                            (92, 148, "Iron rising. Borescope inspection recommended."),
                                            (38, 226, "Iron high, bearing material in the oil. Plan a bearing replacement.")):
                self._oil_sample("WT-02", self.wt02_failure - days_before * DAY_S, rng, iron, text)
            ev = self._repair("WT-02", self.wt02_failure,
                              ("GBX-VIB-CRIT", "GBX", "C", 0, "High-speed shaft bearing failure", "", ("SP-GBX-HSS-BRG",)),
                              rng, fixed_hours=46.0, wait_days=3.6, crew=3, other_cost=82000.0, lead="TECH-01",
                              warranty=True, extra_parts=(("SP-GBX-OIL-320", 1), ("SP-GBX-FLT-10", 2)),
                              summary="Gearbox high-speed shaft bearing replaced",
                              findings="Vibration critical alarm followed by an oil temperature trip. Borescope "
                                       "showed spalling on the high-speed shaft bearing outer race. Bearing kit "
                                       "replaced up-tower with a crane-assisted lift, oil flushed and renewed. "
                                       "Crane mobilisation took four days. Claimed under the drivetrain warranty.")
            self._alarm("WT-02", "GBX-OIL-TEMP-TRIP", self.wt02_failure + 900, ev["end"], ev)
            self._oil_sample("WT-02", ev["end"] + 30 * DAY_S, rng, 11, "After bearing replacement and oil change: clean.")
        # WT-11: generator bearing.
        when = self.ago(214) + 9.1 * 3600
        if when > self.t0:
            self._repair("WT-11", when, ("GEN-BRG-TEMP-HIGH", "GEN", "C", 0, "Drive-end bearing failure", "",
                                         ("SP-GEN-BRG-DE",)), rng, fixed_hours=22.0, wait_days=1.2, crew=3,
                         lead="TECH-04", summary="Generator drive-end bearing replaced",
                         findings="Bearing temperature alarm and noise. Grease discoloured, cage worn. Bearing "
                                  "replaced, shaft alignment checked.")
        # WT-04: lightning strike on a blade.
        when = self.ago(189) + 23.2 * 3600
        if when > self.t0:
            ev = self._repair("WT-04", when, ("ENV-LIGHTNING-STRIKE", "BLD", "C", 0, "Lightning damage", "",
                                              ("SP-BLD-RCP", "SP-BLD-LAM")), rng, fixed_hours=30.0, wait_days=2.4,
                              crew=2, other_cost=14500.0, lead="TECH-03", summary="Blade B lightning damage repaired",
                              responsible="Environment",
                              findings="Lightning strike registered. Receptor burnt and laminate delaminated over "
                                       "0.4 m near the tip of blade B. Repaired by rope access.")
            self.blades.append({"InspectionId": f"BI-WT-04-B-{_day(when + DAY_S).replace('-', '')}-L001",
                                "TurbineId": "WT-04", "Blade": "B", "InspectionDate": _day(when + DAY_S),
                                "Method": "Rope access", "FindingType": "Lightning damage", "SeverityCategory": 5,
                                "SpanPositionM": 70.5, "RecommendedAction": "Stop turbine and repair",
                                "Status": "Closed", "RepairWorkOrderId": "", "order": ev.get("order")})
        # WT-03: generator cooling fan, weeks of hot running and derating before it failed.
        self.wt03_fix = self.ago(77) + 14.6 * 3600
        if self.wt03_fix > self.t0 + 90 * DAY_S:
            self._repair("WT-03", self.wt03_fix, fault["GEN-FAN-FAULT"], rng, fixed_hours=5.0, wait_days=0.0, lead="TECH-02",
                         findings="Fan motor bearing failed; winding temperature alarms and derating over the "
                                  "preceding weeks. Fan assembly replaced. Winding temperature back to normal.")
        # WT-10: pitch valve.
        when = self.ago(154) + 16.4 * 3600
        if when > self.t0:
            self._repair("WT-10", when, fault["PITCH-ASYM-CRIT"], rng, fixed_hours=4.5, wait_days=0.0, lead="TECH-03",
                         summary="Pitch proportional valve replaced, blade B",
                         findings="Valve sticking caused the pitch asymmetry alarm. Valve replaced, function test passed.")
        # WT-05: wind vane replaced, and not calibrated afterwards.
        self.wt05_vane = self.ago(96) + 13.0 * 3600
        if self.wt05_vane > self.t0:
            self._repair("WT-05", self.wt05_vane, fault["YAW-VANE-FAULT"], rng, fixed_hours=2.0, lead="TECH-06")
            self._order("WT-05", "YAW", "Corrective", "Open", self.workday(-20), "Wind vane calibration check",
                        "Nacelle direction differs from the neighbouring turbines by about 9 degrees since the "
                        "wind vane was replaced. Calibration pending.", scheduled=self.workday(6),
                        lead="TECH-02", sop="SOP-YAW-004", failure_mode="Yaw misalignment")
        # WT-07: what is developing now.
        self._oil_sample("WT-07", self.ago(99), rng, 71, "Iron elevated. Re-sample in 60 days.")
        self._oil_sample("WT-07", self.ago(36), rng, 118, "Iron still rising. Borescope inspection of the "
                                                         "high-speed shaft bearing recommended.")
        self._order("WT-07", "GBX", "OilAnalysis", "Closed", self.ago(99), "Gearbox oil sample and analysis",
                    "Iron particle count elevated. Re-sample in 60 days.", closed=self.ago(93), labor_hours=1.5,
                    crew=1, lead="TECH-01", sop="SOP-GBX-001")
        self._order("WT-07", "GBX", "OilAnalysis", "Closed", self.ago(36), "Gearbox oil re-sample",
                    "Iron particle count still rising. Borescope inspection of the high-speed shaft bearing "
                    "recommended.", closed=self.ago(31), labor_hours=1.5, crew=1, lead="ENG-01", sop="SOP-GBX-001")
        self._order("WT-07", "GBX", "Inspection", "Scheduled", self.workday(-28),
                    "Borescope inspection of gearbox high-speed shaft bearing",
                    "Bearing kit SP-GBX-HSS-BRG reserved. Six hours of downtime planned in a low-wind window.",
                    scheduled=self.workday(14), crew=2, lead="TECH-01", sop="SOP-GBX-001", priority="High",
                    failure_mode="Bearing wear (suspected)")
        # WT-09: blade repair waiting for calm, warm weather.
        self._order("WT-09", "BLD", "Corrective", "Scheduled", self.workday(-120), "Leading-edge repair, blades A and C",
                    "Category 4 erosion found by the drone inspection. Leading-edge protection kits in stock. "
                    "Needs two calm days above 10 degC.", scheduled=self.workday(24), crew=2, lead="TECH-03",
                    parts=(("SP-BLD-LEP", 2),), failure_mode="Leading-edge erosion")
        # Two preventive tasks that have slipped.
        for tid, days in (("WT-01", 31), ("WT-08", 12)):
            self._order(tid, "TWR", "Preventive", "Open", self.workday(-days - 30), "Tower bolt torque check",
                        "Postponed twice for high wind.", scheduled=self.workday(-days), crew=2, lead="TECH-04")

    def random_faults(self) -> None:
        types = {k: [f for f in FAULT_TYPES if f[2] == k] for k in "ABC"}
        cut_in = float(self.model["cutInWindSpeed"])
        for d in range(self.days):
            month = int(self.month[min(self.N - 1, d * 144 + 72)])
            for klass in "ABC":
                base = sum(f[3] for f in types[klass])
                for i, tid in enumerate(self.ids):
                    # One random stream per turbine, class and day: what happens to one turbine
                    # never changes the history of another.
                    rng = self.rng(0xFA17 + ord(klass), (self.day0 + d) * 100 + i)
                    # Converters fail more in the heat, hydraulics in the cold; some turbines are prone.
                    weights = np.array([f[3] * FAULT_PRONE.get((tid, f[1]), 1.0)
                                        * (1.5 if f[1] == "CNV" and month in (6, 7, 8) else 1.0)
                                        * (1.4 if f[1] in ("PIT", "HYD") and month in (12, 1, 2) else 1.0)
                                        for f in types[klass]])
                    count = rng.poisson(FAULT_RATE_PER_YEAR[klass] / 365.25 * weights.sum() / base)
                    for _ in range(int(count)):
                        fault = types[klass][int(rng.choice(len(weights), p=weights / weights.sum()))]
                        when = self.t0 + d * DAY_S + rng.uniform(0, DAY_S)
                        k = self.i(when)
                        if k >= self.N or self.stop[k, i] != NONE or self.ws[k, i] < cut_in + 0.5:
                            continue
                        self._repair(tid, when, fault, rng)

    def standby_and_comms(self) -> None:
        for i, tid in enumerate(self.ids):
            rng = self.rng(0x7157, i)
            when = self.t0 + rng.uniform(0, 30) * DAY_S
            while when < self.end:
                k = self.i(when)
                if k < self.N and self.stop[k, i] == NONE:
                    end = when + rng.uniform(8, 16) * 60.0
                    ev = self._event(tid, when, end, STANDBY, "Cable untwist", "YAW", "YAW-UNTWIST",
                                     responsible="Operator", description="Automatic cable untwist.")
                    self._alarm(tid, "YAW-UNTWIST", when, ev["end"], ev)
                when += rng.uniform(16, 44) * DAY_S
            when = self.t0 + rng.uniform(0, 60) * DAY_S
            while when < self.end:
                a, b = self.i(when), self.i(when + rng.uniform(10, 240) * 60.0)
                self.nodata[a:max(b, a + 1), i] = True
                self._alarm(tid, "COMMS-LOST", when, self.t0 + max(b, a + 1) * STEP_S)
                when += rng.exponential(52.0) * DAY_S

    # ---- power and signals ------------------------------------------------------------------
    def signals(self) -> dict:
        m, rated = self.model, self.rated
        ci, v_rated, co = float(m["cutInWindSpeed"]), float(m["ratedWindSpeed"]), float(m["cutOutWindSpeed"])
        ws, noise = self.ws, self.noise
        rho = self.rho[:, None]
        character = turbine_character(self.seed, self.n)
        efficiency, thermal, vib_base = character["efficiency"], character["thermal"], character["vibrationBase"]
        # No nacelle is aligned to true north exactly: a small fixed calibration error per turbine.
        north_error = character["northError"]
        # Performance wanders by about one percent over weeks and months (blade soiling, sensor
        # drift, controller settings). Tied to absolute time, so the past stays the same.
        phase = character["driftPhase"]
        wander = sum(amplitude * np.sin(2.0 * math.pi * self.t[:, None] / (period * DAY_S) + phase[k][None, :])
                     for k, (period, amplitude) in enumerate(((23.0, 0.003), (61.0, 0.004), (173.0, 0.004))))
        age = (self.t - self.t0)[:, None] / DAY_S
        ago = (self.as_of - self.t)[:, None] / DAY_S

        performance = np.ones((self.N, self.n))
        yaw_offset = np.zeros((self.N, self.n))
        add_oil = np.zeros((self.N, self.n))
        add_bearing = np.zeros((self.N, self.n))
        add_vib = np.zeros((self.N, self.n))
        add_winding = np.zeros((self.N, self.n))
        for cond in STANDING_CONDITIONS:
            i = self.index[cond["turbineId"]]
            ramp = np.clip(1.0 - ago[:, 0] / cond["sinceDays"], 0.0, 1.0)
            if cond["kind"] == "gearbox_wear":
                add_oil[:, i] += cond["oilTempAdd"] * ramp ** 1.5
                add_bearing[:, i] += cond["bearingTempAdd"] * ramp ** 1.5
                add_vib[:, i] += cond["vibrationAdd"] * ramp ** 2
            elif cond["kind"] == "yaw_offset":
                yaw_offset[:, i] = np.where(self.t >= getattr(self, "wt05_vane", self.as_of), cond["offsetDeg"], 0.0)
            elif cond["kind"] == "blade_erosion":
                performance[:, i] = 1.0 - (1.0 - cond["efficiency"]) * np.clip(ramp + 0.25, 0.0, 1.0)
        if hasattr(self, "wt02_failure") and self.wt02_failure > self.t0:
            before = (self.wt02_failure - self.t) / DAY_S
            ramp = np.where((before > 0) & (before < 110), (1.0 - before / 110.0) ** 2, 0.0)
            i = self.index["WT-02"]
            add_oil[:, i] += 9.0 * ramp
            add_bearing[:, i] += 14.0 * ramp
            add_vib[:, i] += 3.6 * ramp
        if hasattr(self, "wt03_fix") and self.wt03_fix > self.t0:
            before = (self.wt03_fix - self.t) / DAY_S
            i = self.index["WT-03"]
            fan = np.where((before > 0) & (before < 85), np.clip(1.25 - before / 85.0, 0.3, 1.0), 0.0)
            add_winding[:, i] += 21.0 * fan
            hot = (fan > 0) & (self.temp > 30.0) & (ws[:, i] > 10.0)
            self.derate[hot, i] = 0.5

        v_eq = ws * (rho / STANDARD_AIR_DENSITY) ** (1.0 / 3.0)
        possible = power_curve_kw(v_eq, m)
        available = np.minimum(rated, possible * efficiency[None, :] * performance * (1.0 + wander)
                               * np.cos(np.radians(yaw_offset)) ** 3)
        limit_frac = np.minimum(self.curtail[:, None], self.derate)
        limit = rated * limit_frac
        operating = self.stop == NONE
        producing = operating & (ws >= ci) & (ws <= co) & ~((self.curtail[:, None] <= 0.0) & operating)
        power = np.where(producing, np.minimum(available, limit), AUX_POWER_KW)
        power = power + np.where(producing, 0.006 * rated * noise[:, :, 1], 0.4 * noise[:, :, 1])
        power = np.where(producing, np.clip(power, 0.0, rated * 1.01), power)
        curtailed = producing & (self.curtail[:, None] < 1.0) & (available > rated * self.curtail[:, None] + 1.0)
        derated = producing & ~curtailed & (self.derate < 1.0) & (available > rated * self.derate + 1.0)
        stopped_by_curtailment = operating & (self.curtail[:, None] <= 0.0) & (ws >= ci) & (ws <= co)

        load = np.maximum(power, 0.0) / rated
        rated_rpm = float(m["ratedRotorRpm"])
        rpm = np.where(producing, rated_rpm * np.clip(0.45 + 0.55 * (ws - ci) / (9.5 - ci), 0.45, 1.0),
                       np.where((self.stop == FORCED) | (self.stop == SCHEDULED) | (self.stop == PLANNED), 0.0,
                                np.minimum(0.6, 0.06 * ws)))
        rpm = np.maximum(0.0, rpm + 0.03 * noise[:, :, 2])
        sf = rpm / rated_rpm
        rotating = sf > 0.2
        over = np.clip((ws - v_rated) / (co - v_rated), 0.0, 1.0)
        pitch = np.where(ws > v_rated, 1.5 + 21.0 * over ** 0.85, 0.6)
        limited = producing & (available > limit + 1.0)
        pitch = pitch + np.where(limited, 14.0 * (1.0 - np.minimum(1.0, limit / np.maximum(available, 1.0))) ** 0.7, 0.0)
        pitch = np.where(producing, pitch, 88.0) + 0.05 * noise[:, :, 3]

        amb = self.temp[:, None] + 0.0 * ws
        d_amb = amb - 15.0
        k = thermal[None, :]
        t_oil = _lag(np.where(rotating, (52.0 + 14.0 * load) * k + 0.25 * d_amb, amb + 10.0), 420.0)
        t_gbx_b = _lag(np.where(rotating, (55.0 + 21.0 * load) * k + 0.25 * d_amb, amb + 13.0), 300.0)
        t_gen = _lag(np.where(rotating, (60.0 + 50.0 * load ** 1.3) * k + 0.30 * d_amb, amb + 8.0), 360.0)
        t_gen_b = _lag(np.where(rotating, (42.0 + 22.0 * load) * k + 0.30 * d_amb, amb + 6.0), 400.0)
        t_main = _lag(np.where(rotating, (30.0 + 14.0 * sf) * k + 0.40 * d_amb, amb + 4.0), 900.0)
        t_nac = _lag(amb + 6.0 + 9.0 * load, 900.0)
        t_oil = t_oil + add_oil * (0.4 + 0.6 * load) * rotating
        t_gbx_b = t_gbx_b + add_bearing * (0.4 + 0.6 * load) * rotating
        t_gen = t_gen + add_winding * load ** 0.8
        vib = vib_base[None, :] * (0.35 + 0.65 * sf ** 2) + 0.5 * load + add_vib * (0.3 + 0.7 * sf) \
            + 0.07 * noise[:, :, 0]
        self.t_oil, self.t_gen, self.vib, self.producing = t_oil, t_gen, vib, producing

        sigma = 0.11 * (0.75 * ws + 5.6) * (1.0 + 0.12 * noise[:, :, 2])
        p_low = np.where(producing, np.minimum(np.minimum(rated, power_curve_kw(np.maximum(v_eq - 1.3 * sigma, 0), m)), limit), power)
        p_high = np.where(producing, np.minimum(np.minimum(rated * 1.01, power_curve_kw(v_eq + 1.3 * sigma, m)), limit * 1.01), power)
        nacelle = (self.wd[:, None] + yaw_offset + north_error[None, :] + 1.5 * noise[:, :, 3]) % 360.0

        state = np.full((self.N, self.n), "IDLE", dtype=object)
        state[producing] = "RUNNING"
        state[derated] = "DERATED"
        state[curtailed] = "CURTAILED"
        state[stopped_by_curtailment] = "CURTAILED"
        category = np.full((self.N, self.n), "Out of environmental specification", dtype=object)   # calm
        cause = np.full((self.N, self.n), "Low wind", dtype=object)
        category[producing], cause[producing] = "Full performance", ""
        category[derated], cause[derated] = "Partial performance", "Technical derate"
        category[curtailed | stopped_by_curtailment] = "Partial performance"
        cause[curtailed | stopped_by_curtailment] = "Grid curtailment"
        category[stopped_by_curtailment] = "Requested shutdown"
        for code in range(1, 8):
            mask = self.stop == code
            state[mask], category[mask] = STATE[code], CATEGORY[code]
            cause[mask] = CAUSE.get(code, {FORCED: "Component fault", SCHEDULED: "Scheduled maintenance",
                                           PLANNED: "Corrective maintenance"}.get(code, ""))
        loss_row = ~producing | derated | curtailed
        energy = np.maximum(power, 0.0) / 6.0
        possible_energy = possible / 6.0
        lost = np.where(loss_row & (cause != "Low wind"), np.maximum(possible_energy - energy, 0.0), 0.0)
        self.energy, self.possible_energy, self.lost = energy, possible_energy, lost
        self.category, self.cause, self.state = category, cause, state

        def col(x, digits=2):
            out = np.round(np.asarray(x, dtype=np.float64), digits).astype(np.float32)
            return np.where(self.nodata, np.nan, out).ravel()

        def text(x, missing):
            return np.where(self.nodata, missing, x).ravel()

        return {
            "Timestamp": np.repeat(pd.to_datetime(self.t, unit="s").values, self.n),
            "TurbineId": np.tile(np.array(self.ids, dtype=object), self.N),
            "State": text(state, "UNKNOWN"),
            "AvailabilityCategory": text(category, "Information unavailable"),
            "LossCause": text(cause, ""),
            "WindSpeed": col(ws), "WindSpeedStd": col(sigma), "WindSpeedMax": col(ws + 2.4 * sigma),
            "WindDirection": col((self.wd[:, None] + 2.0 * noise[:, :, 3]) % 360.0, 1),
            "AmbientTemp": col(amb + 0.1 * noise[:, :, 1], 1), "AirDensity": col(rho + 0.0 * ws, 3),
            "ActivePower": col(power, 1), "ActivePowerMin": col(p_low, 1), "ActivePowerMax": col(p_high, 1),
            "ReactivePower": col(np.where(producing, 0.2 * power, 0.0), 1),
            "PowerSetpoint": col(np.minimum(limit, rated), 0), "PossiblePower": col(possible, 1),
            "RotorSpeed": col(rpm), "GeneratorSpeed": col(rpm * float(m["gearRatio"]), 0),
            "PitchAngle": col(pitch), "NacelleDirection": col(nacelle, 1),
            "GearboxOilTemp": col(t_oil + 0.15 * noise[:, :, 0], 1),
            "GearboxBearingTemp": col(t_gbx_b + 0.15 * noise[:, :, 1], 1),
            "GearboxVibration": col(vib),
            "GeneratorWindingTemp": col(t_gen + 0.3 * noise[:, :, 2], 1),
            "GeneratorBearingTemp": col(t_gen_b + 0.2 * noise[:, :, 3], 1),
            "MainBearingTemp": col(t_main + 0.2 * noise[:, :, 0], 1), "NacelleTemp": col(t_nac, 1),
            "EnergyKwh": col(energy), "PossibleEnergyKwh": col(possible_energy), "LostEnergyKwh": col(lost),
        }

    def threshold_alarms(self) -> None:
        for name, values, limit, hysteresis in (("GBX-OIL-TEMP-HIGH", self.t_oil, 78.0, 3.0),
                                                ("GBX-VIB-HIGH", self.vib, 5.5, 0.6),
                                                ("GEN-WIND-TEMP-HIGH", self.t_gen, 125.0, 4.0)):
            for i, tid in enumerate(self.ids):
                for a, b in _runs((values[:, i] >= limit) & self.producing[:, i]):
                    end = b
                    while end < self.N and values[end, i] > limit - hysteresis and self.producing[end, i]:
                        end += 1
                    self._alarm(tid, name, self.t[a] + 120.0, self.t0 + end * STEP_S)
        for i, tid in enumerate(self.ids):
            for a, b in _runs((self.derate[:, i] < 1.0) & self.producing[:, i]):
                self._alarm(tid, "GEN-WIND-TEMP-CRIT", self.t[a], self.t0 + b * STEP_S)
        held_back = self.cause == "Grid curtailment"
        for cu in self.curtailments:
            for i in np.flatnonzero(held_back[cu["a"]:cu["b"]].any(axis=0)):
                self._alarm(self.ids[i], "POWER-CURTAILED", cu["start"], cu["end"])

    # ---- tables that do not depend on the turbines' state -----------------------------------
    def site_power_mw(self, wind, direction, density) -> np.ndarray:
        wake = wake_table(self.site)[(np.asarray(direction) // 5).astype(int) % 72]
        v = np.asarray(wind)[:, None] * speedup(self.site)[None, :] * wake
        v = v * (np.asarray(density)[:, None] / STANDARD_AIR_DENSITY) ** (1.0 / 3.0)
        return power_curve_kw(v, self.model).sum(axis=1) * 0.955 / 1000.0

    def forecasts(self) -> pd.DataFrame:
        return forecast_table(self.site, self.t0, self.as_of, self.seed)

    def budget(self) -> pd.DataFrame:
        """Monthly budget from the long-term climate (ten earlier years), as an energy yield
        assessment would give it."""
        c = self.climate
        by_month, wind_sum, hours = np.zeros(12), np.zeros(12), np.zeros(12)
        years = range(2012, 2022)
        for year in years:
            start = datetime(year, 1, 1, tzinfo=timezone.utc).timestamp()
            t = start + 3600.0 * np.arange(8760)
            wind = c.wind_10min(t)
            mw = self.site_power_mw(wind, c.wind_direction(t), c.air_density(t))
            month = pd.to_datetime(t, unit="s").month.values
            for mth in range(12):
                in_month = month == mth + 1
                by_month[mth] += mw[in_month].sum()
                wind_sum[mth] += wind[in_month].sum()
                hours[mth] += in_month.sum()
        gross = by_month / len(years)
        rows = []
        first = pd.Timestamp(self.t0, unit="s").to_period("M")
        last = pd.Period(year=pd.Timestamp(self.as_of, unit="s").year, month=12, freq="M")
        for period in pd.period_range(first, last, freq="M"):
            p50 = gross[period.month - 1] * period.days_in_month / (
                31 if period.month in (1, 3, 5, 7, 8, 10, 12) else 30 if period.month != 2 else 28.25) * 0.925
            fixed = BUDGET_FIXED_OPEX_USD_PER_MONTH
            corrective = BUDGET_CORRECTIVE_USD_PER_MONTH
            rows.append({"YearMonth": str(period), "Year": period.year, "Month": period.month,
                         "P50EnergyMwh": round(p50, 0), "P90EnergyMwh": round(p50 * 0.87, 0),
                         "LongTermWindSpeed": round(wind_sum[period.month - 1] / hours[period.month - 1], 2),
                         "BudgetAvailabilityPct": GUARANTEED_AVAILABILITY_PCT,
                         "BudgetRevenueUsd": round(p50 * PPA_PRICE_USD_PER_MWH, 0),
                         "BudgetFixedOpexUsd": fixed, "BudgetCorrectiveMaintenanceUsd": corrective,
                         "BudgetOpexUsd": fixed + corrective})
        return pd.DataFrame(rows)

    # ---- assembling ---------------------------------------------------------------------------
    def tables(self) -> dict[str, pd.DataFrame]:
        self.weather()
        self.environment()
        self.grid_outages()
        self.market()
        self.stories()
        self.scheduled_maintenance()
        self.random_faults()
        self.standby_and_comms()
        scada = pd.DataFrame(self.signals())
        self.threshold_alarms()

        lost_cum = np.vstack([np.zeros((1, self.n)), np.cumsum(self.lost, axis=0)])
        event_rows = []
        for ev in sorted(self.events, key=lambda e: (e["start"], e["TurbineId"])):
            a, b = self.i(ev["start"]), max(self.i(ev["end"]), self.i(ev["start"]) + 1)
            if ev["TurbineId"] == "SITE":
                lost = float((lost_cum[b] - lost_cum[a]).sum())
            else:
                lost = float(lost_cum[b, self.index[ev["TurbineId"]]] - lost_cum[a, self.index[ev["TurbineId"]]])
            event_rows.append({
                "EventId": ev["EventId"], "TurbineId": ev["TurbineId"], "StartTime": _ts(ev["start"]),
                "EndTime": pd.NaT if ev["ongoing"] else _ts(ev["end"]),
                "DurationHours": round((ev["end"] - ev["start"]) / 3600.0, 2),
                "AvailabilityCategory": ev["AvailabilityCategory"], "Cause": ev["Cause"],
                "ComponentCode": ev["ComponentCode"], "Component": ev["Component"], "AlarmCode": ev["AlarmCode"],
                "FaultClass": ev["FaultClass"], "FailureMode": ev["FailureMode"],
                "ResponsibleParty": ev["ResponsibleParty"], "Description": ev["Description"],
                "LostEnergyMwh": round(lost / 1000.0, 3), "order": ev.get("order")})
        events = _frame(event_rows, EVENT_COLUMNS)

        orders = sorted(self.orders, key=lambda o: o["opened"])
        number, ids = {}, {}
        for o in orders:
            year = datetime.fromtimestamp(o["opened"], timezone.utc).year
            number[year] = number.get(year, 0) + 1
            ids[o["key"]] = f"WO-{year}-{number[year]:04d}"
        work_orders = _frame([{
            "WorkOrderId": ids[o["key"]], "TurbineId": o["TurbineId"], "ComponentId": o["ComponentId"],
            "WorkType": o["WorkType"], "Priority": o["Priority"], "Status": o["Status"],
            "OpenedDate": _ts(o["opened"]), "ScheduledDate": pd.NaT if o["scheduled"] is None else _ts(o["scheduled"]),
            "ClosedDate": pd.NaT if o["closed"] is None else _ts(o["closed"]), "Summary": o["Summary"],
            "Findings": o["Findings"], "FailureMode": o["FailureMode"], "LaborHours": o["LaborHours"],
            "CrewSize": o["CrewSize"], "LaborCostUsd": o["LaborCostUsd"], "PartsCostUsd": o["PartsCostUsd"],
            "OtherCostUsd": o["OtherCostUsd"], "TotalCostUsd": o["TotalCostUsd"], "DowntimeHours": o["DowntimeHours"],
            "WaitingForPartsHours": o["WaitingForPartsHours"],
            "LeadTechnicianId": o["LeadTechnicianId"], "EventId": o["EventId"], "SopId": o["SopId"],
            "CoveredByWarranty": o["CoveredByWarranty"], "CostBorneBy": o["CostBorneBy"]} for o in orders],
            ORDER_COLUMNS)
        events["WorkOrderId"] = events.pop("order").map(lambda k: ids.get(k, "") if pd.notna(k) else "")
        parts = _frame([{"WorkOrderId": ids[p["order"]], "PartId": p["PartId"], "Quantity": p["Quantity"],
                         "UnitCostUsd": p["UnitCostUsd"],
                         "TotalCostUsd": round(p["Quantity"] * p["UnitCostUsd"], 2)} for p in self.order_parts],
                       PART_COLUMNS)
        blades = _frame(self.blades, BLADE_COLUMNS)
        blades["RepairWorkOrderId"] = blades.pop("order").map(lambda k: ids.get(k, "") if pd.notna(k) else "")
        repair = work_orders.loc[work_orders["Summary"].str.startswith("Leading-edge repair"), "WorkOrderId"]
        if len(repair):
            pending = (blades["TurbineId"] == "WT-09") & (blades["SeverityCategory"] >= 4)
            blades.loc[pending, "RepairWorkOrderId"] = repair.iloc[0]

        alarm_rows = sorted(self.alarms, key=lambda a: (a["raised"], a["TurbineId"], a["AlarmCode"]))
        alarms = _frame([{
            "AlarmId": f"AL-{k + 1:07d}", "TurbineId": a["TurbineId"], "AlarmCode": a["AlarmCode"],
            "RaisedAt": _ts(a["raised"]), "ClearedAt": pd.NaT if a["cleared"] is None else _ts(a["cleared"]),
            "DurationMinutes": None if a["cleared"] is None else round((a["cleared"] - a["raised"]) / 60.0, 1),
            "EventId": a["EventId"]} for k, a in enumerate(alarm_rows)], ALARM_COLUMNS)

        site_lost = self.lost.sum(axis=1)
        cum = np.concatenate(([0.0], np.cumsum(site_lost)))
        curtailments = _frame([{
            "CurtailmentId": cu["CurtailmentId"], "StartTime": _ts(cu["start"]), "EndTime": _ts(cu["end"]),
            "DurationHours": round((cu["end"] - cu["start"]) / 3600.0, 1), "SetpointMw": cu["SetpointMw"],
            "SetpointPctOfCapacity": cu["SetpointPctOfCapacity"], "Reason": cu["Reason"],
            "InstructedBy": cu["InstructedBy"], "Compensated": cu["Compensated"],
            "AvgRealTimePriceUsdPerMwh": cu["AvgRealTimePriceUsdPerMwh"],
            "LostEnergyMwh": round(float(
                (self.lost[cu["a"]:cu["b"]] * (self.cause[cu["a"]:cu["b"]] == "Grid curtailment")).sum()) / 1000.0, 3)}
            for cu in self.curtailments], CURTAILMENT_COLUMNS)
        del cum

        sigma = 0.11 * (0.75 * self.ws_site + 5.6)
        met = pd.DataFrame({
            "Timestamp": pd.to_datetime(self.t, unit="s"), "StationId": self.site["metMast"]["id"],
            "WindSpeed": np.round(self.ws_site, 2).astype(np.float32),
            "WindGust": np.round(self.ws_site + 2.4 * sigma, 2).astype(np.float32),
            "WindDirection": np.round(self.wd, 1).astype(np.float32),
            "AmbientTemp": np.round(self.temp, 1).astype(np.float32),
            "Pressure": np.round(self.press * math.exp(-self.climate.elevation_m / 8434.0), 1).astype(np.float32),
            "Humidity": np.round(self.hum, 0).astype(np.float32),
            "AirDensity": np.round(self.rho, 3).astype(np.float32), "IcingConditions": self.ice})

        return {"scada_10min": scada, "met_10min": met, "turbine_events": events, "alarm_log": alarms,
                "work_orders": work_orders, "work_order_parts": parts, "oil_analysis": _frame(self.oil, OIL_COLUMNS),
                "blade_inspections": blades, "curtailments": curtailments, "market_prices": self.prices,
                "power_forecast": self.forecasts(), "monthly_budget": self.budget()}


def generate(site: dict, as_of=None, start=None, seed: int | None = None) -> dict[str, pd.DataFrame]:
    """Build every history table. ``as_of`` is the moment the history ends (default: now);
    ``start`` defaults to the site's ``historyStart``."""
    return _History(site, as_of, start or site.get("historyStart", HISTORY_START), seed).tables()


def _forecast_rows(h: "_History", issued: float, target: np.ndarray, kind: str) -> pd.DataFrame:
    c = h.climate
    wind, sigma = c.forecast_wind(issued, target)
    direction, density = c.wind_direction(target), c.air_density(target)
    low, high = _band(wind, sigma)
    return pd.DataFrame({
        "IssuedAt": _ts(issued), "TargetTime": pd.to_datetime(target, unit="s"), "ForecastType": kind,
        "HorizonHours": np.round((target - issued) / 3600.0, 0).astype("int64"),
        "WindSpeed": np.round(wind, 2), "WindSpeedP10": np.round(low, 2), "WindSpeedP90": np.round(high, 2),
        "PowerMw": np.round(h.site_power_mw(wind, direction, density), 2),
        "PowerMwP10": np.round(h.site_power_mw(low, direction, density), 2),
        "PowerMwP90": np.round(h.site_power_mw(high, direction, density), 2),
        "AmbientTemp": np.round(c.temperature(target), 1), "IcingRisk": c.icing(target)})


def forecast_table(site: dict, start, as_of=None, seed: int | None = None, latest_hours: int = 168) -> pd.DataFrame:
    """Wind and power forecasts: one day-ahead forecast per day issued at 10:00 local time for the
    next local day, from ``start`` to ``as_of``, plus the latest forecast for the coming week.
    Cheap enough to run every hour, so a scheduled notebook can keep the forecast current."""
    h = _History.__new__(_History)
    h.site, h.model = site, site["turbineModel"]
    h.seed = int(site.get("climateSeed", 20211) if seed is None else seed)
    h.climate = Climate.for_site(site, h.seed)
    cal = _Calendar(site["timezone"])
    t0 = _epoch(start)
    now = _epoch(datetime.now(timezone.utc) if as_of is None else as_of)
    frames = []
    day = cal.local(t0)
    while True:
        issued = cal.at(day, 10.0)
        if issued >= now:
            break
        if issued >= t0:
            frames.append(_forecast_rows(h, issued, cal.at(day + timedelta(days=1), 0.0) + 3600.0 * np.arange(24),
                                         "Day-ahead"))
        day = day + timedelta(days=1)
    latest = math.floor(now / 3600.0) * 3600.0
    frames.append(_forecast_rows(h, latest, latest + 3600.0 * np.arange(1, latest_hours + 1), "Latest"))
    return pd.concat(frames, ignore_index=True)


def latest_forecast(site: dict, as_of=None, hours: int = 168, seed: int | None = None) -> pd.DataFrame:
    """Only the forecast issued at ``as_of`` for the coming hours."""
    table = forecast_table(site, _epoch(datetime.now(timezone.utc) if as_of is None else as_of), as_of, seed, hours)
    return table[table["ForecastType"] == "Latest"].reset_index(drop=True)


# --------------------------------------------------------------------------- headline numbers
def summarise(tables: dict[str, pd.DataFrame], site: dict, period: tuple | None = None) -> dict:
    """Headline KPIs of a period (default: everything), computed the way docs/kpi-definitions.md
    defines them. Used by the tests and for the answer key of the question bank."""
    s = tables["scada_10min"]
    if period is not None:
        s = s[(s["Timestamp"] >= period[0]) & (s["Timestamp"] < period[1])]
    known = s[s["AvailabilityCategory"] != "Information unavailable"]
    hours = len(known) / 6.0
    cat = known.groupby("AvailabilityCategory").size() / 6.0
    down = sum(float(cat.get(c, 0.0)) for c in ("Forced outage", "Scheduled maintenance", "Planned corrective action"))
    rated_mw = float(site["turbineModel"]["ratedPowerKw"]) / 1000.0
    energy = float(known["EnergyKwh"].sum()) / 1000.0
    lost = known.groupby("LossCause")["LostEnergyKwh"].sum() / 1000.0
    lost = lost[lost > 0.0]
    technical = sum(float(lost.get(c, 0.0)) for c in ("Component fault", "Scheduled maintenance",
                                                      "Corrective maintenance", "Technical derate"))
    full = known[known["AvailabilityCategory"] == "Full performance"]
    pi = (full.groupby("TurbineId")["EnergyKwh"].sum() / full.groupby("TurbineId")["PossibleEnergyKwh"].sum())
    return {
        "turbineHours": round(hours, 0),
        "energyMwh": round(energy, 0),
        "capacityFactorPct": round(100.0 * energy / (hours * rated_mw), 2),
        "timeAvailabilityPct": round(100.0 * (1.0 - down / hours), 2),
        "energyAvailabilityPct": round(100.0 * energy / (energy + technical), 2),
        "lostEnergyMwhByCause": {k: round(float(v), 0) for k, v in lost.sort_values(ascending=False).items()},
        "curtailmentPctOfPossible": round(100.0 * float(lost.get("Grid curtailment", 0.0))
                                          / (energy + float(lost.sum())), 2),
        "hoursByCategory": {k: round(float(v), 0) for k, v in cat.sort_values(ascending=False).items()},
        "performanceIndexByTurbine": {k: round(float(v), 4) for k, v in pi.items()},
    }


# --- command line (everything below this line is left out of the notebook copy) ---
def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Generate the synthetic operating history as files.")
    parser.add_argument("--site", default="data/reference/site.json")
    parser.add_argument("--out", default="data/history")
    parser.add_argument("--as-of", default=None, help="end of the history, ISO 8601 (default: now)")
    parser.add_argument("--start", default=None, help="start of the history (default: the site's historyStart)")
    parser.add_argument("--format", choices=("csv", "parquet"), default="csv")
    args = parser.parse_args(argv)
    site = json.loads(Path(args.site).read_text(encoding="utf-8"))
    tables = generate(site, as_of=args.as_of, start=args.start)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        if args.format == "parquet":
            frame.to_parquet(out / f"{name}.parquet", index=False)
        else:
            frame.to_csv(out / f"{name}.csv.gz" if len(frame) > 200_000 else out / f"{name}.csv", index=False)
        print(f"{name:20s} {len(frame):>9,} rows")
    (out / "summary.json").write_text(json.dumps(summarise(tables, site), indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
