"""Run the simulator in real time: ``python -m windfarm_sim``."""
from __future__ import annotations

import json
import logging
import queue
import signal
import sys
import time
from pathlib import Path

from .config import SimConfig
from .engine import Simulator
from .site import load_site

log = logging.getLogger("windfarm")
ALIVE_FILE = Path("/tmp/windfarm-sim-alive")
OFFLINE_RESTART_S = 600


def main() -> int:
    cfg = SimConfig.from_env()
    logging.basicConfig(level=cfg.log_level, stream=sys.stdout,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    site = load_site(cfg.site_file)
    sim = Simulator(site, cfg)

    running = True

    def _stop(signum, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    link = None
    commands: queue.Queue[tuple[str, bytes]] = queue.Queue()
    request_topic = f"{sim.sim_topic_prefix}/request"
    if cfg.sink == "mqtt":
        from .k8s import current_ca_file
        from .mqtt_io import MqttLink
        if cfg.mqtt_tls:
            cfg.mqtt_ca_file = current_ca_file(cfg.mqtt_ca_file, cfg.mqtt_ca_configmap)
        link = MqttLink(cfg, on_message=lambda topic, payload: commands.put((topic, payload)))
        link.subscribe(request_topic)
        link.subscribe(sim.control_topic)
        link.start()
        if not link.wait_connected(30):
            log.warning("broker not reachable yet; simulating while the connection is retried")
    elif cfg.sink != "stdout":
        log.error("unknown SINK '%s' (use mqtt or stdout)", cfg.sink)
        return 2

    next_tick = time.monotonic()
    dropped = 0
    last_report = 0.0
    offline_since: float | None = None
    exit_code = 0
    while running:
        # A broker that stays unreachable usually means that its certificate or the token changed
        # under us. Stop, so that Kubernetes starts a fresh pod, which reads both again.
        if link is not None:
            if link.connected.is_set():
                offline_since = None
            elif offline_since is None:
                offline_since = time.monotonic()
            elif time.monotonic() - offline_since > OFFLINE_RESTART_S:
                log.error("no broker connection for %d minutes; exiting so that the pod restarts",
                          OFFLINE_RESTART_S // 60)
                exit_code = 3
                break
        while True:
            try:
                topic, payload = commands.get_nowait()
            except queue.Empty:
                break
            try:
                cmd = json.loads(payload)
                if not isinstance(cmd, dict):
                    raise ValueError("command must be a JSON object")
            except ValueError as exc:
                log.warning("ignored malformed command on %s: %s", topic, exc)
                continue
            if topic == request_topic:
                channel = "sim"
            elif topic == sim.control_topic:
                channel = "control"
            else:
                continue
            ack = sim.handle_command(cmd, channel)
            log.info("command %s -> ok=%s", ack["command"], ack["ok"])
            base = sim.sim_topic_prefix if channel == "sim" else sim.control_topic.rsplit("/", 1)[0]
            link.publish(f"{base}/response/{ack['requestId'] or 'none'}", ack)

        for msg in sim.step(1.0):
            if link is None:
                print(json.dumps({"topic": msg.topic, "payload": msg.payload}, separators=(",", ":")))
            elif not link.publish(msg.topic, msg.payload, retain=msg.retain):
                dropped += 1

        if link is not None:
            for record in sim.ground_truth:
                link.publish(f"{sim.sim_topic_prefix}/events", record)
            sim.ground_truth.clear()
            if sim.t - last_report >= 30:
                last_report = sim.t
                status = sim.status()
                link.publish(f"{sim.sim_topic_prefix}/status", status, retain=True)
                log.info("wind %.1f m/s, site power %d kW, published %d, dropped %d, anomalies %d",
                         status["wind"]["speed"], status["sitePowerKw"], sim.published, dropped,
                         len(status["activeAnomalies"]))
        else:
            sim.ground_truth.clear()

        try:
            ALIVE_FILE.touch()
        except OSError:
            pass

        next_tick += 1.0
        delay = next_tick - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        elif delay < -5.0:
            # Fell badly behind (host paused); resynchronise rather than race to catch up.
            next_tick = time.monotonic()

    if link is not None:
        cleared = sim.shutdown_messages()
        for msg in cleared:
            link.publish(msg.topic, msg.payload)
        if cleared:
            log.info("cleared %d alarms that were still raised", len(cleared))
            time.sleep(1.0)                 # give the network loop time to send them
        link.stop()
    log.info("simulator stopped")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
