"""The shared climate: deterministic, plausible for the region, and usable three ways."""
import json

import numpy as np
import pytest

from windfarm_sim.climate import Climate

from conftest import SITE_FILE

T0 = np.datetime64("2025-01-01T00:00").astype("datetime64[s]").astype(float)


@pytest.fixture(scope="module")
def climate():
    return Climate.for_site(json.loads(SITE_FILE.read_text()))


@pytest.fixture(scope="module")
def year(climate):
    t = T0 + 600.0 * np.arange(365 * 144)
    return t, climate.wind_10min(t), climate.wind_direction(t), climate.temperature(t)


def test_same_seed_same_weather_any_order(climate):
    other = Climate.for_site(json.loads(SITE_FILE.read_text()))
    t = T0 + 3600.0 * np.arange(500)
    assert np.array_equal(climate.wind_mean(t), other.wind_mean(t))
    # A value does not depend on which other times are asked for with it.
    assert climate.wind_mean(t[123:124])[0] == pytest.approx(climate.wind_mean(t)[123])
    assert climate.at(t[77])["windSpeed"] == pytest.approx(climate.wind_mean(t)[77])


def test_wind_resource_is_west_texas_like(year):
    t, ws, wd, _ = year
    assert 8.3 < ws.mean() < 9.8
    assert ws.min() >= 0.0 and ws.max() < 34.0
    month = t.astype("datetime64[s]").astype("datetime64[M]").astype(int) % 12
    assert ws[np.isin(month, (2, 3, 4))].mean() > ws[np.isin(month, (6, 7, 8))].mean() + 1.0   # spring beats summer
    assert 0.0005 < (ws > 25.0).mean() < 0.01                                                 # storms are rare
    southerly = ((wd > 120) & (wd < 260)).mean()
    assert 0.65 < southerly < 0.95


def test_nights_are_windier_than_days(climate, year):
    t, ws, _, _ = year
    hour = climate.solar_hour(t)
    assert ws[(hour >= 21) | (hour < 3)].mean() > ws[(hour >= 9) & (hour < 15)].mean() + 0.8


def test_temperature_and_icing(climate, year):
    t, _, _, temp = year
    month = t.astype("datetime64[s]").astype("datetime64[M]").astype(int) % 12
    assert temp[month == 6].mean() > temp[month == 0].mean() + 15.0
    icing_hours = climate.icing(t).sum() / 6.0
    assert 5.0 < icing_hours < 150.0


def test_forecast_error_grows_with_the_horizon(climate):
    short, long = [], []
    for k in range(0, 300, 4):
        issued = T0 + k * 86400.0 + 16 * 3600.0
        target = issued + 3600.0 * np.arange(1, 169)
        forecast, sigma = climate.forecast_wind(issued, target)
        actual = climate.wind_mean(target)
        short.append(np.abs(forecast[:12] - actual[:12]).mean())
        long.append(np.abs(forecast[120:] - actual[120:]).mean())
        assert np.all(np.diff(sigma) >= 0)
    assert np.mean(long) > 1.5 * np.mean(short)
    assert np.mean(short) < 1.2
