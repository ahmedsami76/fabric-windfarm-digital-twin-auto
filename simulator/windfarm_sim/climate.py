"""Deterministic climate of the site: the slow part of the weather as a function of time.

Everything here is a pure function of the absolute time and a seed. That is what
keeps the three views of the wind consistent with each other:

* the history generator samples it for the past two years,
* the live simulator follows it as the mean around which its turbulence moves,
* the forecast is this same signal plus an error that grows with the horizon.

The shape is that of a West Texas ridge site: strongest winds in spring, weakest in
late summer, more wind at night than by day (low-level jet), southerly prevailing
wind with northerly spells behind cold fronts, and a few icing days in winter.

The module needs only numpy and has no imports from the rest of the package, so
the Fabric notebooks can carry a copy of it.
"""
from __future__ import annotations

import math

import numpy as np

DAY_S = 86400.0
# Mean hub-height wind speed (m/s) and mean air temperature (degC) by calendar month, January first.
MONTHLY_WIND = (8.7, 9.2, 10.0, 10.4, 9.9, 9.0, 7.9, 7.5, 8.1, 8.8, 8.9, 8.6)
MONTHLY_TEMP = (7.5, 9.5, 14.0, 18.5, 23.0, 27.0, 29.0, 28.5, 24.5, 18.5, 12.0, 8.0)
_MID_MONTH_DOY = (15.5, 45.0, 74.5, 105.0, 135.5, 166.0, 196.5, 227.5, 258.0, 288.5, 319.0, 349.5)
SYNOPTIC_SIGMA = 0.34          # spread of the multi-day wind factor (log scale)
DIURNAL_AMPLITUDE = 0.13       # night-time wind maximum, as a fraction of the mean
MESO_SIGMA = 0.13              # spread of the minutes-to-hours factor used for 10-minute history


def _as_array(t) -> np.ndarray:
    return np.atleast_1d(np.asarray(t, dtype=np.float64))


def day_of_year(t) -> np.ndarray:
    """Fractional day of the year (1.0 = start of 1 January, UTC)."""
    t = _as_array(t)
    days = np.floor(t / DAY_S).astype("int64").astype("datetime64[D]")
    year_start = days.astype("datetime64[Y]").astype("datetime64[D]")
    return (days - year_start).astype("int64") + 1.0 + (t % DAY_S) / DAY_S


def _seasonal(t, monthly) -> np.ndarray:
    xp = np.concatenate(([_MID_MONTH_DOY[-1] - 365.25], _MID_MONTH_DOY, [_MID_MONTH_DOY[0] + 365.25]))
    fp = np.concatenate(([monthly[-1]], monthly, [monthly[0]]))
    return np.interp(day_of_year(t), xp, fp)


def _soft_cap(v: np.ndarray, knee: float = 19.0, room: float = 13.0) -> np.ndarray:
    """Compress the far tail so that storms stay physical: nothing exceeds knee + room."""
    return np.where(v > knee, knee + room * (1.0 - np.exp(-(np.maximum(v, knee) - knee) / room)), v)


def turbine_character(seed: int, count: int) -> dict:
    """What makes each turbine of the site its own: how efficient it is, how warm it runs, how
    much it vibrates when healthy, how far its nacelle is off true north, and the phases of
    its slow performance drift. Fixed for the site, so the history and the live simulator
    describe the same machines. One value per turbine, in the order of the site file."""
    rng = np.random.default_rng([int(seed), 0xC4A2, 0])
    return {"efficiency": rng.uniform(0.984, 0.999, count),
            "thermal": rng.uniform(0.97, 1.03, count),
            "vibrationBase": rng.uniform(1.1, 1.6, count),
            "northError": rng.uniform(-2.4, 2.4, count),
            "driftPhase": rng.uniform(0.0, 2.0 * math.pi, (3, count))}


class _Spectrum:
    """Smooth pseudo-random signal with unit variance, as a sum of sinusoids with fixed random
    phases. It can be evaluated at any time without stepping through the time before it."""

    def __init__(self, rng: np.random.Generator, n: int, period_min_s: float, period_max_s: float,
                 slope: float = 0.5):
        periods = np.exp(rng.uniform(math.log(period_min_s), math.log(period_max_s), n))
        amps = periods ** slope * rng.uniform(0.7, 1.3, n)
        self.omega = 2.0 * math.pi / periods
        self.phase = rng.uniform(0.0, 2.0 * math.pi, n)
        self.amp = amps / math.sqrt(0.5 * float(np.sum(amps ** 2)))

    def __call__(self, t) -> np.ndarray:
        t = _as_array(t)
        out = np.zeros(t.shape)
        for w, p, a in zip(self.omega, self.phase, self.amp):
            out += a * np.sin(w * t + p)
        return out


class Climate:
    def __init__(self, seed: int, longitude: float, elevation_m: float, prevailing_direction_deg: float):
        self.seed = int(seed)
        self.longitude = float(longitude)
        self.elevation_m = float(elevation_m)
        self.prevailing = float(prevailing_direction_deg)
        rng = np.random.default_rng([self.seed, 0xC11A7E])
        self._synoptic = _Spectrum(rng, 22, 1.6 * DAY_S, 15.0 * DAY_S)
        self._meso = _Spectrum(rng, 40, 25 * 60.0, 10 * 3600.0, slope=0.35)
        self._veer = _Spectrum(rng, 14, 1.5 * DAY_S, 9.0 * DAY_S)
        self._front = _Spectrum(rng, 14, 2.5 * DAY_S, 11.0 * DAY_S)
        self._temp = _Spectrum(rng, 16, 1.5 * DAY_S, 12.0 * DAY_S)
        self._moist = _Spectrum(rng, 14, 1.0 * DAY_S, 8.0 * DAY_S)
        self._press = _Spectrum(rng, 12, 2.0 * DAY_S, 10.0 * DAY_S)
        self._gust_cache: dict[int, tuple[float, float, float]] = {}

    @classmethod
    def for_site(cls, site: dict, seed: int | None = None) -> "Climate":
        """Build the climate from the site definition (data/reference/site.json)."""
        elevations = [float(t["elevationM"]) for t in site["turbines"]]
        return cls(seed=site.get("climateSeed", 20211) if seed is None else seed,
                   longitude=float(site["origin"]["longitude"]),
                   elevation_m=sum(elevations) / len(elevations),
                   prevailing_direction_deg=float(site["prevailingWindDirectionDeg"]))

    # ------------------------------------------------------------------ time helpers
    def solar_hour(self, t) -> np.ndarray:
        return (_as_array(t) / 3600.0 + self.longitude / 15.0) % 24.0

    # ------------------------------------------------------------------ wind
    def _gust_fronts(self, t: np.ndarray) -> np.ndarray:
        """Short, strong wind events (thunderstorm outflow), mostly in spring. A few per year
        push the wind above the cut-out speed of the turbines."""
        add = np.zeros(t.shape)
        if t.size == 0:
            return add
        first, last = int(math.floor(t.min() / DAY_S)) - 1, int(math.floor(t.max() / DAY_S))
        for day in range(first, last + 1):
            event = self._gust_cache.get(day)
            if event is None:
                rng = np.random.default_rng([self.seed, 0x6057, day])
                doy = float(day_of_year(day * DAY_S)[0])
                season = 1.0 + 1.6 * math.exp(-((doy - 125.0) / 45.0) ** 2)   # peaks in early May
                if rng.random() < 0.010 * season:
                    centre = day * DAY_S + rng.uniform(15.0, 26.0) * 3600.0 - self.longitude * 240.0
                    event = (centre, rng.uniform(1500.0, 3600.0), rng.uniform(8.0, 14.0))
                else:
                    event = (0.0, 1.0, 0.0)
                self._gust_cache[day] = event
            centre, width, peak = event
            if peak > 0.0:
                add += peak * np.exp(-0.5 * ((t - centre) / width) ** 2)
        return add

    def wind_mean(self, t) -> np.ndarray:
        """Site wind speed at hub height without the minutes-to-hours variability (m/s)."""
        t = _as_array(t)
        hour = self.solar_hour(t)
        diurnal = 1.0 + DIURNAL_AMPLITUDE * np.cos(2.0 * math.pi * (hour - 23.0) / 24.0)
        synoptic = np.exp(SYNOPTIC_SIGMA * self._synoptic(t) - 0.5 * SYNOPTIC_SIGMA ** 2)
        return _soft_cap(np.maximum(0.3, _seasonal(t, MONTHLY_WIND) * diurnal * synoptic)
                         + self._gust_fronts(t))

    def wind_10min(self, t) -> np.ndarray:
        """Site wind speed as a 10-minute mean, with the variability that the live simulator
        produces with its own random process."""
        t = _as_array(t)
        return _soft_cap(self.wind_mean(t) * np.exp(MESO_SIGMA * self._meso(t) - 0.5 * MESO_SIGMA ** 2))

    def front_weight(self, t) -> np.ndarray:
        """0 = ordinary southerly flow, 1 = behind a cold front (northerly, colder)."""
        t = _as_array(t)
        winter = 0.5 + 0.5 * np.cos(2.0 * math.pi * (day_of_year(t) - 15.0) / 365.25)
        threshold = 1.75 - 0.95 * winter
        return 1.0 / (1.0 + np.exp(-5.0 * (self._front(t) - threshold)))

    def wind_direction(self, t) -> np.ndarray:
        """Direction the wind comes from, degrees."""
        t = _as_array(t)
        w = self.front_weight(t)
        veer = self._veer(t)
        south = np.radians(self.prevailing + 32.0 * veer)
        north = np.radians(350.0 + 22.0 * veer)
        x = (1.0 - w) * np.sin(south) + w * np.sin(north)
        y = (1.0 - w) * np.cos(south) + w * np.cos(north)
        return np.degrees(np.arctan2(x, y)) % 360.0

    # ------------------------------------------------------------------ air
    def temperature(self, t) -> np.ndarray:
        t = _as_array(t)
        hour = self.solar_hour(t)
        winter = 0.5 + 0.5 * np.cos(2.0 * math.pi * (day_of_year(t) - 15.0) / 365.25)
        return (_seasonal(t, MONTHLY_TEMP) + 6.5 * np.sin(2.0 * math.pi * (hour - 9.0) / 24.0)
                + 3.2 * self._temp(t) - (4.0 + 7.0 * winter) * self.front_weight(t))

    def humidity(self, t) -> np.ndarray:
        t = _as_array(t)
        anomaly = self.temperature(t) - _seasonal(t, MONTHLY_TEMP)
        return np.clip(54.0 - 1.9 * anomaly + 17.0 * self._moist(t), 12.0, 100.0)

    def pressure_hpa(self, t) -> np.ndarray:
        return 1013.0 + 6.0 * self._press(_as_array(t))

    def air_density(self, t) -> np.ndarray:
        station_hpa = self.pressure_hpa(t) * math.exp(-self.elevation_m / 8434.0)
        return station_hpa * 100.0 / (287.05 * (self.temperature(t) + 273.15))

    def icing(self, t) -> np.ndarray:
        """True while freezing temperatures and very moist air coincide (blade icing)."""
        return (self.temperature(t) < -3.0) & (self.humidity(t) > 93.0)

    # ------------------------------------------------------------------ forecast
    @staticmethod
    def forecast_error_sigma(horizon_h) -> np.ndarray:
        """Relative error of a wind speed forecast as a function of its horizon in hours."""
        h = np.maximum(0.0, _as_array(horizon_h))
        return 0.05 + 0.036 * np.sqrt(h / 6.0)

    def forecast_wind(self, issued_at: float, target_t) -> tuple[np.ndarray, np.ndarray]:
        """Wind speed forecast issued at one time for later times. Returns the forecast and the
        relative one-sigma error that the forecaster would quote for it."""
        target = _as_array(target_t)
        sigma = self.forecast_error_sigma((target - issued_at) / 3600.0)
        rng = np.random.default_rng([self.seed, 0xF0CA57, int(math.floor(issued_at / 3600.0))])
        miss = _Spectrum(rng, 10, 5 * 3600.0, 3.0 * DAY_S)
        return self.wind_mean(target) * np.exp(sigma * miss(target) - 0.5 * sigma ** 2), sigma

    # ------------------------------------------------------------------ scalar access (live simulator)
    def at(self, epoch_s: float) -> dict:
        """All values at one instant, as plain floats."""
        t = np.array([float(epoch_s)])
        return {
            "windSpeed": float(self.wind_mean(t)[0]),
            "windDirection": float(self.wind_direction(t)[0]),
            "ambientTemp": float(self.temperature(t)[0]),
            "humidity": float(self.humidity(t)[0]),
            "pressureHpa": float(self.pressure_hpa(t)[0]),
        }
