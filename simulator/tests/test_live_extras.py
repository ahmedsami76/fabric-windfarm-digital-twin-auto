"""What the live simulator gained after the first deployment: the shared climate, the standing
conditions of individual turbines, clean alarm state on shutdown and a self-renewing broker CA."""
import json
import statistics

import pytest

from windfarm_sim import k8s
from windfarm_sim.climate import Climate
from windfarm_sim.wind import wrap180

from conftest import SITE_FILE, START_EPOCH, run


def test_wind_follows_the_shared_climate(make_sim):
    climate = Climate.for_site(json.loads(SITE_FILE.read_text()))
    for offset_days in (0, 40, 200):
        start = START_EPOCH + offset_days * 86400.0
        sim = make_sim(wind_model="climate", start_epoch=start)
        speeds = [p["data"]["windSpeed"] for p in run(sim, 3600) if p["messageType"] == "weather"]
        expected = float(climate.wind_mean([start + 1800.0])[0])
        assert sim.status()["wind"]["model"] == "climate"
        assert statistics.mean(speeds) == pytest.approx(expected, abs=max(2.2, 0.3 * expected))


def test_wind_override_still_works_with_the_climate(make_sim):
    sim = make_sim(wind_model="climate")
    run(sim, 60)
    assert sim.handle_command({"command": "wind", "mean": 11.0, "duration": "60m"})["ok"]
    speeds = [p["data"]["windSpeed"] for p in run(sim, 1800) if p["messageType"] == "weather"]
    assert statistics.mean(speeds[-60:]) == pytest.approx(11.0, abs=1.6)


def test_regime_model_is_still_available(make_sim):
    sim = make_sim(wind_model="regime")
    assert sim.status()["wind"]["model"] == "regime" and sim.wind.climate is None


def test_standing_conditions_show_in_the_telemetry(make_sim):
    # Same turbines, same run; the only difference is the conditions themselves.
    healthy = make_sim(seed=11, standing=True)
    healthy._standing.clear()
    worn = make_sim(seed=11, standing=True)

    def averages(sim):
        out = {}
        for p in run(sim, 1500):
            if p["messageType"] == "telemetry":
                d = out.setdefault(p["assetId"], {"vib": [], "oil": [], "nacelle": [], "wind": [], "power": []})
                d["vib"].append(p["data"]["gearboxVibration"])
                d["oil"].append(p["data"]["gearboxOilTemp"])
                d["nacelle"].append(wrap180(p["data"]["nacelleDirection"] - p["data"]["windDirection"]))
                d["power"].append(p["data"]["activePower"])
        return {tid: {k: statistics.mean(v[-120:]) for k, v in d.items() if v} for tid, d in out.items()}

    a, b = averages(healthy), averages(worn)
    assert b["WT-07"]["vib"] - a["WT-07"]["vib"] > 0.8          # worn gearbox: more vibration ...
    assert b["WT-07"]["oil"] - a["WT-07"]["oil"] > 2.0          # ... and warmer oil
    assert abs(b["WT-06"]["vib"] - a["WT-06"]["vib"]) < 0.2     # the neighbour is untouched
    assert abs(b["WT-05"]["nacelle"] - a["WT-05"]["nacelle"]) > 6.0   # miscalibrated vane: nacelle off the wind
    assert b["WT-05"]["power"] < a["WT-05"]["power"] * 0.985
    assert b["WT-09"]["power"] < a["WT-09"]["power"] * 0.985    # eroded blades
    # None of this is enough to raise an alarm by itself.
    assert all(not t.active_alarm_codes() for t in worn.turbines.values())


def test_live_turbines_have_the_character_of_the_site_history(make_sim, site):
    from windfarm_sim.climate import turbine_character
    character = turbine_character(site.raw["climateSeed"], len(site.turbines))
    for seed in (3, 4):                                  # whatever the seed of the run
        sim = make_sim(seed=seed, standing=True)
        for i, spec in enumerate(site.turbines):
            turbine = sim.turbines[spec.turbine_id]
            assert turbine.efficiency == pytest.approx(character["efficiency"][i])
            assert turbine.thermal_k == pytest.approx(character["thermal"][i])
            assert turbine.vib_base == pytest.approx(character["vibrationBase"][i])
    # Without the site's conditions every run draws its own turbines, as in version 1.0.
    a, b = make_sim(seed=3, standing=False), make_sim(seed=4, standing=False)
    assert a.turbines["WT-01"].efficiency != b.turbines["WT-01"].efficiency


def test_rated_power_is_reached_in_thin_air(make_sim):
    """At 800 m the air is thin: the turbine needs more wind for rated power, and gets there."""
    sim = make_sim(seed=5, wind=16.0, standing=True)
    powers = {}
    for p in run(sim, 900):
        if p["messageType"] == "telemetry":
            powers.setdefault(p["assetId"], []).append(p["data"]["activePower"])
    rated = sim.site.model.rated_power_kw
    at_rated = [tid for tid, v in powers.items() if statistics.mean(v[-60:]) > 0.985 * rated]
    assert len(at_rated) >= 9, {tid: round(statistics.mean(v[-60:])) for tid, v in powers.items()}


def test_demo_fault_on_the_worn_gearbox_still_plays_out(make_sim):
    sim = make_sim(standing=True)
    run(sim, 300)
    assert sim.handle_command({"command": "inject", "turbine": "WT-07", "kind": "gearbox_degradation",
                               "severity": 0.8, "duration": "15m"})["ok"]
    payloads = run(sim, 25 * 60)
    raised = [p["data"]["alarmCode"] for p in payloads
              if p["messageType"] == "alarm" and p["data"]["status"] == "raised" and p["assetId"] == "WT-07"]
    cleared = [p["data"]["alarmCode"] for p in payloads
               if p["messageType"] == "alarm" and p["data"]["status"] == "cleared" and p["assetId"] == "WT-07"]
    assert "GBX-VIB-HIGH" in raised and "GBX-VIB-CRIT" in raised
    assert set(raised) == set(cleared)                          # it resolves by itself
    assert not sim.turbines["WT-07"].active_alarm_codes()


def test_shutdown_clears_raised_alarms(make_sim):
    sim = make_sim()
    run(sim, 120)
    sim.handle_command({"command": "inject", "turbine": "WT-07", "kind": "gearbox_degradation", "hold": True})
    run(sim, 8 * 60)
    active = set(sim.turbines["WT-07"].active_alarm_codes())
    assert active
    messages = sim.shutdown_messages()
    assert {m.payload["data"]["alarmCode"] for m in messages} == active
    for m in messages:
        assert m.topic.endswith("/WT-07/alarm")
        assert m.payload["messageType"] == "alarm" and m.payload["data"]["status"] == "cleared"
        assert m.payload["data"]["clearedBy"] == "simulator shutdown"
        assert m.payload["data"]["durationSeconds"] > 0 and m.payload["data"]["alarmId"]
    assert not sim.turbines["WT-07"].active_alarm_codes()
    assert sim.shutdown_messages() == []


PEM_OLD = "-----BEGIN CERTIFICATE-----\nOLD\n-----END CERTIFICATE-----\n"
PEM_NEW = "-----BEGIN CERTIFICATE-----\nNEW\n-----END CERTIFICATE-----\n"


def test_ca_copy_is_replaced_only_when_the_cluster_has_another(tmp_path, monkeypatch):
    mounted = tmp_path / "ca.crt"
    mounted.write_text(PEM_OLD)
    monkeypatch.setattr(k8s.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(k8s, "read_configmap_key", lambda spec: None)          # not in a cluster / no access
    assert k8s.current_ca_file(str(mounted), "ns/name/ca.crt") == str(mounted)
    monkeypatch.setattr(k8s, "read_configmap_key", lambda spec: PEM_OLD)       # unchanged
    assert k8s.current_ca_file(str(mounted), "ns/name/ca.crt") == str(mounted)
    monkeypatch.setattr(k8s, "read_configmap_key", lambda spec: PEM_NEW)       # rotated
    fresh = k8s.current_ca_file(str(mounted), "ns/name/ca.crt")
    assert fresh != str(mounted) and open(fresh).read() == PEM_NEW
    assert k8s.current_ca_file(str(mounted), "") == str(mounted)                # switched off


def test_configmap_is_read_through_the_kubernetes_api(tmp_path, monkeypatch):
    (tmp_path / "token").write_text("abc123\n")
    (tmp_path / "ca.crt").write_text("unused")
    monkeypatch.setattr(k8s, "SERVICE_ACCOUNT_DIR", tmp_path)
    monkeypatch.setattr(k8s.ssl, "create_default_context", lambda cafile=None: None)
    assert k8s.read_configmap_key("ns/name/ca.crt") is None                     # no cluster environment
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.43.0.1")
    monkeypatch.setenv("KUBERNETES_SERVICE_PORT", "443")
    seen = {}

    class Response:
        def __init__(self, body): self.body = body
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self, *a): return json.dumps(self.body).encode()

    def fake_urlopen(request, context=None, timeout=None):
        seen["url"], seen["auth"] = request.full_url, request.get_header("Authorization")
        return Response({"data": {"ca.crt": PEM_NEW, "other": "x"}})

    monkeypatch.setattr(k8s.urllib.request, "urlopen", fake_urlopen)
    assert k8s.read_configmap_key("azure-iot-operations/azure-iot-operations-aio-ca-trust-bundle/ca.crt") == PEM_NEW
    assert seen["url"] == ("https://10.43.0.1:443/api/v1/namespaces/azure-iot-operations/configmaps/"
                           "azure-iot-operations-aio-ca-trust-bundle")
    assert seen["auth"] == "Bearer abc123"
    assert k8s.read_configmap_key("ns/name/missing-key") is None
    assert k8s.read_configmap_key("malformed") is None

    def failing(request, context=None, timeout=None):
        raise OSError("403 Forbidden")
    monkeypatch.setattr(k8s.urllib.request, "urlopen", failing)
    assert k8s.read_configmap_key("ns/name/ca.crt") is None                     # access denied: keep the copy
