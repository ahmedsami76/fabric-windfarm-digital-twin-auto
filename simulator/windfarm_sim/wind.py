"""Stochastic weather and wind field for the site.

Wind speed is a slow mean-reverting process around a baseline, plus faster
gusts. The baseline is the site climate (``climate.py``): season, time of day
and passing weather systems, the same signal that the history and the forecast
use. Without a climate the baseline is a random regime inside a band. Each
turbine sees the site wind modified by terrain speed-up, wakes from upstream
turbines and its own local turbulence.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .site import Site


class OU:
    """Ornstein-Uhlenbeck process: mean-reverting noise with a time constant."""

    def __init__(self, rng: random.Random, tau_s: float, std: float, x0: float | None = None):
        self.rng = rng
        self.tau = tau_s
        self.std = std
        self.x = rng.gauss(0.0, std) if x0 is None else x0

    def step(self, dt: float, mean: float = 0.0) -> float:
        a = math.exp(-dt / self.tau)
        self.x = mean + (self.x - mean) * a + self.std * math.sqrt(1.0 - a * a) * self.rng.gauss(0.0, 1.0)
        return self.x


def wrap180(deg: float) -> float:
    """Wrap an angle difference into (-180, 180]."""
    d = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def wrap360(deg: float) -> float:
    return deg % 360.0


@dataclass
class Weather:
    wind_speed: float
    wind_direction: float
    gust: float
    ambient_temp: float
    pressure_hpa: float
    humidity: float
    air_density: float


class WindField:
    def __init__(self, site: Site, rng: random.Random, wind_mean: float,
                 regime_min: float, regime_max: float, ambient_mean_c: float, climate=None):
        self.site = site
        self.rng = rng
        self.climate = climate
        self._climate_now: dict | None = None
        self._climate_at = float("-inf")
        self.regime_min = regime_min
        self.regime_max = regime_max
        self.regime_mean = min(regime_max, max(regime_min, rng.gauss(wind_mean, 1.2)))
        self.override_mean: float | None = None
        self.override_until: float | None = None
        self._next_regime_shift = rng.expovariate(1.0 / (3 * 3600.0))
        self.ambient_mean = ambient_mean_c + rng.gauss(0.0, 2.0)

        self._slow = OU(rng, tau_s=2400.0, std=1.6)
        self._slow.x = self.regime_mean + self._slow.x
        self._gust = OU(rng, tau_s=15.0, std=1.0)
        self._dir_slow = OU(rng, tau_s=3600.0, std=18.0)
        self._dir_fast = OU(rng, tau_s=30.0, std=3.0)
        self._temp = OU(rng, tau_s=1800.0, std=0.8)
        self._press = OU(rng, tau_s=6 * 3600.0, std=4.0)
        self._hum = OU(rng, tau_s=3600.0, std=6.0)
        self._turb = {t.turbine_id: OU(rng, tau_s=8.0, std=1.0) for t in site.turbines}

        elevs = [t.elevation_m for t in site.turbines]
        span = max(1.0, max(elevs) - min(elevs))
        mean_e = site.mean_elevation_m
        # Higher turbines on the ridge see a little more wind.
        self._speedup = {t.turbine_id: 1.0 + 0.10 * (t.elevation_m - mean_e) / span
                         for t in site.turbines}
        self._wake: dict[str, float] = {t.turbine_id: 1.0 for t in site.turbines}
        self._wake_dir_bucket: int | None = None
        self.weather = Weather(self._slow.x, site.prevailing_wind_direction_deg, self._slow.x,
                               self.ambient_mean, 1013.0, 50.0, 1.2)
        self._local: dict[str, float] = {}

    # ------------------------------------------------------------------ #
    def set_wind_override(self, mean: float, until: float | None) -> None:
        self.override_mean = max(0.0, min(30.0, mean))
        self.override_until = until

    def clear_wind_override(self) -> None:
        self.override_mean = None
        self.override_until = None

    def _solar_hour(self, epoch_s: float) -> float:
        return ((epoch_s / 3600.0) + self.site.longitude / 15.0) % 24.0

    def step(self, sim_t: float, epoch_s: float, dt: float) -> Weather:
        hour = self._solar_hour(epoch_s)
        climate = None
        if self.climate is not None:
            if epoch_s - self._climate_at >= 20.0 or epoch_s < self._climate_at:
                first = self._climate_now is None
                self._climate_now = self.climate.at(epoch_s)
                self._climate_at = epoch_s
                if first:
                    # Start on the climate, not on the random regime drawn above.
                    self._slow.x = self._climate_now["windSpeed"] + self._slow.std * self.rng.gauss(0.0, 0.5)
            climate = self._climate_now

        if self.override_until is not None and sim_t >= self.override_until:
            self.clear_wind_override()
        if climate is None and sim_t >= self._next_regime_shift:
            self.regime_mean = self.rng.uniform(self.regime_min, self.regime_max)
            self._next_regime_shift = sim_t + self.rng.expovariate(1.0 / (3 * 3600.0))

        if self.override_mean is not None:
            # A demo override pulls the wind to the requested mean quickly.
            target = self.override_mean
            self._slow.tau = 240.0
        elif climate is not None:
            target = climate["windSpeed"]
            self._slow.tau = 2400.0
        else:
            # Wind picks up in the late afternoon and evening.
            target = self.regime_mean + 1.3 * math.sin(2.0 * math.pi * (hour - 13.0) / 24.0)
            self._slow.tau = 2400.0
        # The random part scales with the wind, so a calm stays calm and a gale stays rough.
        spread = 1.0 if climate is None or self.override_mean is not None else min(1.0, max(0.35, target / 9.0))
        slow = max(0.0, target + (self._slow.step(dt, target) - target) * spread)
        gust = self._gust.step(dt) * 0.08 * max(slow, 2.0)
        ws = max(0.0, slow + gust)

        if climate is not None:
            wd = wrap360(climate["windDirection"] + 0.3 * self._dir_slow.step(dt) + self._dir_fast.step(dt))
            temp = climate["ambientTemp"] + self._temp.step(dt)
            press = climate["pressureHpa"] + 0.2 * self._press.step(dt)
            hum = max(12.0, min(100.0, climate["humidity"] + 0.4 * self._hum.step(dt)))
        else:
            wd = wrap360(self.site.prevailing_wind_direction_deg
                         + self._dir_slow.step(dt) + self._dir_fast.step(dt))
            temp = (self.ambient_mean + 7.0 * math.sin(2.0 * math.pi * (hour - 9.0) / 24.0)
                    + self._temp.step(dt))
            press = 1013.0 + self._press.step(dt)
            hum = max(15.0, min(98.0, 55.0 - 2.2 * (temp - self.ambient_mean) + self._hum.step(dt)))
        # Station pressure at site elevation, then dry-air density.
        station_hpa = press * math.exp(-self.site.mean_elevation_m / 8434.0)
        density = station_hpa * 100.0 / (287.05 * (temp + 273.15))

        self._update_wakes(wd)
        for t in self.site.turbines:
            tid = t.turbine_id
            turb = 1.0 + 0.06 * self._turb[tid].step(dt)
            self._local[tid] = max(0.0, ws * self._speedup[tid] * self._wake[tid] * turb)

        self.weather = Weather(ws, wd, max(ws, slow + abs(gust) * 1.8), temp, press, hum, density)
        return self.weather

    def local_wind(self, turbine_id: str) -> float:
        return self._local.get(turbine_id, self.weather.wind_speed)

    # ------------------------------------------------------------------ #
    def _update_wakes(self, wind_dir: float) -> None:
        """Recompute wake factors when the wind direction moves to a new 5 degree bucket."""
        bucket = int(wind_dir // 5)
        if bucket == self._wake_dir_bucket:
            return
        self._wake_dir_bucket = bucket
        d_rotor = self.site.model.rotor_diameter_m
        rad = math.radians(wind_dir)
        # Wind direction is where the wind comes FROM; it travels the other way.
        ux, uy = -math.sin(rad), -math.cos(rad)
        for ti in self.site.turbines:
            deficit_sq = 0.0
            for tj in self.site.turbines:
                if tj is ti:
                    continue
                dx, dy = ti.x - tj.x, ti.y - tj.y
                down = dx * ux + dy * uy
                if down <= 0.0 or down > 14.0 * d_rotor:
                    continue
                cross = abs(dx * uy - dy * ux)
                width = 0.5 * d_rotor + 0.06 * down
                centre = 0.30 / (1.0 + 0.09 * down / d_rotor) ** 2
                deficit_sq += (centre * math.exp(-(cross / width) ** 2)) ** 2
            self._wake[ti.turbine_id] = 1.0 - min(0.35, math.sqrt(deficit_sq))
