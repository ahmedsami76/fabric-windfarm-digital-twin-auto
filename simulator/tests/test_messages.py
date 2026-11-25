import re

from conftest import run

ENVELOPE = {"messageType", "schemaVersion", "siteId", "assetId", "timestamp", "seq", "data"}
TELEMETRY_KEYS = {
    "state", "windSpeed", "windDirection", "ambientTemp", "activePower", "reactivePower",
    "powerSetpoint", "rotorSpeed", "generatorSpeed", "pitchAngle", "nacelleDirection", "yawError",
    "gearboxOilTemp", "gearboxBearingTemp", "gearboxOilPressure", "gearboxVibration",
    "generatorWindingTemp", "generatorBearingTemp", "mainBearingTemp", "nacelleTemp",
    "transformerTemp", "towerVibration", "hydraulicPressure", "gridVoltage", "gridFrequency",
    "energyTotal",
}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


def test_envelope_and_cadence(make_sim):
    sim = make_sim()
    payloads = run(sim, 60)
    for p in payloads:
        assert set(p) == ENVELOPE
        assert ISO.match(p["timestamp"])
        assert p["siteId"] == "northwind-ridge"
    by_type = {}
    for p in payloads:
        by_type.setdefault(p["messageType"], []).append(p)
    assert len(by_type["telemetry"]) == 12 * 12          # 12 turbines, every 5 s
    assert len(by_type["weather"]) == 6                   # every 10 s
    assert len(by_type["asset"]) == 13                    # 12 turbines and the met mast
    assert len(by_type["heartbeat"]) == 1
    for p in by_type["telemetry"]:
        assert set(p["data"]) == TELEMETRY_KEYS
        assert not any(k.startswith("_") for k in p["data"])


def test_sequence_numbers_increase_per_asset(make_sim):
    last = {}
    for p in run(make_sim(), 120):
        assert p["seq"] == last.get(p["assetId"], 0) + 1
        last[p["assetId"]] = p["seq"]


def test_topics(make_sim):
    sim = make_sim()
    topics = {m.topic for m in sim.step(1.0)}
    assert "contoso/windfarm/northwind-ridge/WT-07/telemetry" in topics
    assert "contoso/windfarm/northwind-ridge/MET-01/weather" in topics
    assert "contoso/windfarm/northwind-ridge/WT-07/asset" in topics
    assert "contoso/windfarm/northwind-ridge/EDGE-01/heartbeat" in topics


def test_same_seed_is_reproducible_and_seeds_differ(make_sim):
    a = run(make_sim(seed=3), 120)
    b = run(make_sim(seed=3), 120)
    c = run(make_sim(seed=4), 120)
    assert a == b
    assert a != c


def test_values_are_physically_plausible(make_sim):
    sim = make_sim(spontaneous=0.0)
    for p in run(sim, 900):
        if p["messageType"] != "telemetry":
            continue
        d = p["data"]
        assert -40 <= d["activePower"] <= 4200 * 1.02
        assert 0 <= d["rotorSpeed"] <= 13.5
        assert 20 <= d["gearboxOilTemp"] <= 76
        assert 0 <= d["gearboxVibration"] <= 4.0
        assert 59.9 <= d["gridFrequency"] <= 60.1
        assert 0 <= d["windDirection"] < 360
