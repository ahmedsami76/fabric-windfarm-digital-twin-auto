from conftest import run


def events(payloads, message_type, asset=None):
    return [p for p in payloads if p["messageType"] == message_type and (asset is None or p["assetId"] == asset)]


def telemetry(payloads, asset):
    return [p["data"] for p in events(payloads, "telemetry", asset)]


def test_quiet_site_raises_no_alarms(make_sim):
    payloads = run(make_sim(spontaneous=0.0), 1800)
    assert events(payloads, "alarm") == []


def test_gearbox_anomaly_is_detected_and_resolves_by_itself(make_sim):
    sim = make_sim()
    before = run(sim, 300)
    ack = sim.handle_command({"command": "inject", "turbine": "WT-07", "requestId": "r1"})
    assert ack["ok"] and ack["requestId"] == "r1"
    assert ack["result"]["kind"] == "gearbox_degradation"
    during = run(sim, 15 * 60)
    after = run(sim, 15 * 60)

    raised = {e["data"]["alarmCode"] for e in events(during, "alarm", "WT-07") if e["data"]["status"] == "raised"}
    assert {"GBX-VIB-HIGH", "GBX-VIB-CRIT"} <= raised
    assert any(e["data"]["state"] == "DERATED" for e in events(during, "state", "WT-07"))
    # No other turbine is affected.
    assert all(e["assetId"] == "WT-07" for e in events(during, "alarm"))

    base_vib = max(d["gearboxVibration"] for d in telemetry(before, "WT-07"))
    peak_vib = max(d["gearboxVibration"] for d in telemetry(during, "WT-07"))
    assert peak_vib > base_vib + 4
    peak_oil = max(d["gearboxOilTemp"] for d in telemetry(during, "WT-07"))
    assert peak_oil > max(d["gearboxOilTemp"] for d in telemetry(before, "WT-07")) + 12

    # It ends without any command: alarms clear, the derate releases, the turbine runs normally.
    assert sim.anomalies == []
    assert sim.turbines["WT-07"].active_alarm_codes() == []
    assert sim.turbines["WT-07"].state == "RUNNING"
    tail = telemetry(after, "WT-07")[-12:]
    assert max(d["gearboxVibration"] for d in tail) < base_vib + 1
    truth = [r["event"] for r in sim.ground_truth]
    assert truth == ["anomaly_started", "anomaly_ended"]


def test_derate_costs_production(make_sim):
    sim = make_sim(wind=11.5)
    run(sim, 300)
    sim.handle_command({"command": "inject", "turbine": "WT-07", "severity": 0.9})
    run(sim, 6 * 60)                       # ramp in, critical alarm, derate
    window = run(sim, 4 * 60)
    limit = 0.3 * 4200
    assert sim.turbines["WT-07"].state == "DERATED"
    assert max(d["activePower"] for d in telemetry(window, "WT-07")) <= limit * 1.05
    peers = [d["activePower"] for t in ("WT-06", "WT-08") for d in telemetry(window, t)]
    assert sum(peers) / len(peers) > limit * 1.3


def test_hold_anomaly_stays_until_resolved(make_sim):
    sim = make_sim()
    run(sim, 120)
    sim.handle_command({"command": "inject", "turbine": "WT-03", "kind": "generator_overheat", "hold": True})
    run(sim, 30 * 60)
    assert len(sim.anomalies) == 1 and sim.anomalies[0].describe(sim.t)["hold"]
    assert "GEN-WIND-TEMP-HIGH" in sim.turbines["WT-03"].active_alarm_codes()
    ack = sim.handle_command({"command": "resolve", "turbine": "WT-03"})
    assert len(ack["result"]["resolving"]) == 1
    run(sim, 15 * 60)
    assert sim.anomalies == []
    assert sim.turbines["WT-03"].active_alarm_codes() == []


def test_comms_loss_leaves_a_gap(make_sim):
    sim = make_sim()
    run(sim, 60)
    sim.handle_command({"command": "inject", "turbine": "WT-02", "kind": "comms_loss", "duration": "2m"})
    gap = run(sim, 110)
    assert telemetry(gap, "WT-02") == []
    assert len(telemetry(gap, "WT-01")) == 22
    back = run(sim, 60)
    assert len(telemetry(back, "WT-02")) >= 8
    assert any(e["data"]["alarmCode"] == "COMMS-RESTORED" for e in events(back, "alarm", "WT-02"))


def test_sensor_drift_is_not_a_mechanical_fault(make_sim):
    sim = make_sim()
    before = run(sim, 300)
    sim.handle_command({"command": "inject", "turbine": "WT-04", "kind": "sensor_drift", "severity": 0.9})
    during = run(sim, 10 * 60)
    assert max(d["gearboxOilTemp"] for d in telemetry(during, "WT-04")) > \
        max(d["gearboxOilTemp"] for d in telemetry(before, "WT-04")) + 15
    assert max(d["gearboxVibration"] for d in telemetry(during, "WT-04")) < 3.5
    assert max(d["gearboxBearingTemp"] for d in telemetry(during, "WT-04")) < \
        max(d["gearboxBearingTemp"] for d in telemetry(before, "WT-04")) + 5


def test_yaw_misalignment_is_silent_but_costs_power(make_sim):
    sim = make_sim(wind=9.0)
    run(sim, 300)
    sim.handle_command({"command": "inject", "turbine": "WT-05", "kind": "yaw_misalignment",
                        "severity": 1.0, "hold": True})
    run(sim, 6 * 60)
    window = run(sim, 5 * 60)
    assert events(window, "alarm", "WT-05") == []
    reported = [abs(d["yawError"]) for d in telemetry(window, "WT-05")]
    assert sum(reported) / len(reported) < 5         # the faulty vane reports no error
    nacelle = telemetry(window, "WT-05")[-1]["nacelleDirection"]
    peers = [telemetry(window, x)[-1]["nacelleDirection"] for x in ("WT-03", "WT-08", "WT-09")]
    diff = min(abs((nacelle - p + 180) % 360 - 180) for p in peers)
    assert diff > 15


def test_curtail_release_stop_start(make_sim):
    sim = make_sim(wind=12.0)
    run(sim, 120)
    assert sim.handle_command({"command": "curtail", "turbine": "WT-01", "percent": 25})["ok"]
    window = run(sim, 180)
    assert sim.turbines["WT-01"].state == "CURTAILED"
    assert telemetry(window, "WT-01")[-1]["activePower"] <= 0.25 * 4200 * 1.05
    assert telemetry(window, "WT-01")[-1]["powerSetpoint"] == 1050
    sim.handle_command({"command": "release", "turbine": "WT-01"})
    run(sim, 120)
    assert sim.turbines["WT-01"].state == "RUNNING"

    sim.handle_command({"command": "stop", "turbine": "WT-01", "reason": "maintenance"})
    window = run(sim, 180)
    assert sim.turbines["WT-01"].state == "MAINTENANCE"
    assert telemetry(window, "WT-01")[-1]["activePower"] < 0
    sim.handle_command({"command": "start", "turbine": "WT-01"})
    run(sim, 120)
    assert sim.turbines["WT-01"].state == "RUNNING"


def test_commands_are_validated(make_sim):
    sim = make_sim()
    assert not sim.handle_command({"command": "inject", "turbine": "WT-99"})["ok"]
    assert not sim.handle_command({"command": "inject", "turbine": "WT-01", "kind": "nonsense"})["ok"]
    assert not sim.handle_command({"command": "explode"})["ok"]
    assert not sim.handle_command({"command": "curtail", "turbine": "WT-01"})["ok"]     # percent missing
    # The control channel (reserved for cloud-to-edge actions) cannot inject faults.
    assert not sim.handle_command({"command": "inject", "turbine": "WT-01"}, channel="control")["ok"]
    assert sim.handle_command({"command": "curtail", "turbine": "all", "percent": 80}, channel="control")["ok"]
    status = sim.handle_command({"command": "status"})["result"]
    assert set(status["turbines"]) == set(sim.turbines)


def test_wind_override(make_sim):
    sim = make_sim(wind=7.0)
    run(sim, 60)
    sim.handle_command({"command": "wind", "mean": 12.0, "duration": "30m"})
    run(sim, 20 * 60)
    assert sim.wind.weather.wind_speed > 9.5


def test_spontaneous_events_happen_and_end(make_sim):
    sim = make_sim(spontaneous=12.0)
    run(sim, 2 * 3600)
    kinds = {r["kind"] for r in sim.ground_truth}
    assert kinds                      # something happened
    assert kinds <= {"comms_loss", "yaw_misalignment", "sensor_freeze"}
    assert all(r["source"] == "spontaneous" for r in sim.ground_truth)
