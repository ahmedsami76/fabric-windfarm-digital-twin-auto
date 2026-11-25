"""End-to-end check over a real MQTT broker (amqtt, MQTT 3.1.1, no TLS).

This covers publishing, retained asset messages and the simctl request/response
path. The K8S-SAT authentication used inside Azure IoT Operations needs MQTT v5
and the cluster's broker, so it can only be verified on the edge cluster.
"""
import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("amqtt")
import paho.mqtt.client as mqtt  # noqa: E402
from amqtt.broker import Broker  # noqa: E402

SIM_DIR = Path(__file__).resolve().parents[1]
SITE_FILE = SIM_DIR.parent / "data" / "reference" / "site.json"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def broker_port():
    port = _free_port()
    loop = asyncio.new_event_loop()
    ready = threading.Event()
    holder = {}

    async def _run():
        holder["broker"] = Broker({
            "listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{port}"}},
            "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}},
        })
        await holder["broker"].start()
        ready.set()

    def _thread():
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_run())
        loop.run_forever()

    threading.Thread(target=_thread, daemon=True).start()
    assert ready.wait(10), "broker did not start"
    yield port
    asyncio.run_coroutine_threadsafe(holder["broker"].shutdown(), loop).result(10)
    loop.call_soon_threadsafe(loop.stop)


def test_publish_and_simctl_over_mqtt(broker_port):
    env = dict(os.environ, SITE_FILE=str(SITE_FILE), MQTT_HOST="127.0.0.1", MQTT_PORT=str(broker_port),
               MQTT_AUTH="none", MQTT_TLS="false", MQTT_PROTOCOL="v311", SEED="5", WIND_MEAN="10",
               SPONTANEOUS_EVENTS_PER_HOUR="0", PYTHONPATH=str(SIM_DIR))
    received = []
    probe = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="probe", protocol=mqtt.MQTTv311)
    probe.on_connect = lambda c, u, f, rc, p=None: c.subscribe("contoso/windfarm/#")
    probe.on_message = lambda c, u, m: received.append((m.topic, m.retain, json.loads(m.payload)))
    probe.connect("127.0.0.1", broker_port)
    probe.loop_start()

    sim = subprocess.Popen([sys.executable, "-m", "windfarm_sim"], env=env, cwd=SIM_DIR,
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.time() + 20
        while time.time() < deadline and sum(1 for t, _, _ in received if t.endswith("/telemetry")) < 24:
            time.sleep(0.5)
        topics = {t for t, _, _ in received}
        assert "contoso/windfarm/northwind-ridge/WT-07/telemetry" in topics
        assert "contoso/windfarm/northwind-ridge/MET-01/weather" in topics
        assert "contoso/windfarm/northwind-ridge/WT-01/asset" in topics

        def simctl(*args):
            return subprocess.run([sys.executable, "-m", "windfarm_sim.ctl", "--json", *args],
                                  env=env, cwd=SIM_DIR, capture_output=True, text=True, timeout=30)

        status = simctl("status")
        assert status.returncode == 0, status.stderr
        assert len(json.loads(status.stdout)["result"]["turbines"]) == 12

        inject = simctl("inject", "WT-07", "gearbox_degradation", "--duration", "2m")
        assert inject.returncode == 0, inject.stderr
        assert json.loads(inject.stdout)["result"]["turbineId"] == "WT-07"

        bad = simctl("inject", "WT-99")
        assert bad.returncode == 1 and json.loads(bad.stdout)["ok"] is False

        time.sleep(2)
        after = json.loads(simctl("status").stdout)["result"]
        assert [a["turbineId"] for a in after["activeAnomalies"]] == ["WT-07"]
    finally:
        sim.terminate()
        sim.wait(10)
        probe.loop_stop()
