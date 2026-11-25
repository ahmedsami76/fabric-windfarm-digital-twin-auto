"""simctl: send commands to the running simulator over MQTT.

Run it inside the simulator pod, where the broker settings are already in the
environment:

    kubectl exec -n windfarm deploy/windfarm-simulator -- simctl status
    kubectl exec -n windfarm deploy/windfarm-simulator -- \
        simctl inject WT-07 gearbox_degradation --severity 0.8 --duration 15m
"""
from __future__ import annotations

import argparse
import json
import queue
import sys
import uuid

from .anomalies import ANOMALY_KINDS
from .config import SimConfig
from .mqtt_io import MqttLink
from .site import load_site


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="simctl", description="Control the wind farm simulator.")
    p.add_argument("--json", action="store_true", help="print the raw JSON acknowledgement")
    p.add_argument("--timeout", type=float, default=10.0, help="seconds to wait for a reply")
    sub = p.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show wind, power, turbine states and active anomalies")
    sub.add_parser("kinds", help="list the anomaly kinds that can be injected")

    inj = sub.add_parser("inject", help="inject an anomaly on one turbine")
    inj.add_argument("turbine", help="turbine id, for example WT-07")
    inj.add_argument("kind", nargs="?", default="gearbox_degradation", choices=sorted(ANOMALY_KINDS))
    inj.add_argument("--severity", type=float, default=0.8, help="0.05 to 1.0 (default 0.8)")
    inj.add_argument("--duration", default="15m", help="for example 90s, 15m, 1h (default 15m)")
    inj.add_argument("--hold", action="store_true",
                     help="keep the fault active until 'simctl resolve' is sent")

    res = sub.add_parser("resolve", help="end anomalies early (they ramp out)")
    res.add_argument("turbine", nargs="?", default="all")
    res.add_argument("--kind", default="")

    wind = sub.add_parser("wind", help="temporarily steer the site wind for a demo")
    wind.add_argument("--mean", type=float, help="target mean wind speed in m/s")
    wind.add_argument("--duration", default="60m")
    wind.add_argument("--clear", action="store_true", help="remove the override")

    cur = sub.add_parser("curtail", help="limit power by remote setpoint")
    cur.add_argument("turbine", help="turbine id or 'all'")
    cur.add_argument("--percent", type=float, required=True, help="percent of rated power")
    cur.add_argument("--duration", default="", help="optional, for example 30m")

    for name, text in (("release", "remove a curtailment"), ("start", "restart a stopped turbine"),
                       ("reset", "reset a latched trip or derate")):
        sp = sub.add_parser(name, help=text)
        sp.add_argument("turbine", nargs="?", default="all")

    stop = sub.add_parser("stop", help="stop a turbine")
    stop.add_argument("turbine")
    stop.add_argument("--reason", default="operator", help="use 'maintenance' for a maintenance stop")
    stop.add_argument("--duration", default="")
    return p


def _print_status(result: dict) -> None:
    wind = result["wind"]
    override = "" if wind["overrideMean"] is None else f" (override mean {wind['overrideMean']} m/s)"
    print(f"Site {result['siteId']}  simulator {result.get('simulatorVersion', '?')}  seed {result['seed']}  "
          f"uptime {result['uptimeSeconds']} s")
    print(f"Wind {wind['speed']} m/s from {wind['direction']} deg{override}  "
          f"ambient {result['ambientTemp']} C  site power {result['sitePowerKw']} kW  "
          f"wind model {wind.get('model', 'regime')}")
    print()
    print(f"{'Turbine':<8} {'State':<18} {'Power kW':>9}  Alarms")
    for tid, t in result["turbines"].items():
        print(f"{tid:<8} {t['state']:<18} {t['powerKw']:>9}  {', '.join(t['alarms']) or '-'}")
    print()
    if result["activeAnomalies"]:
        print("Active anomalies:")
        for a in result["activeAnomalies"]:
            remaining = "until resolved" if a["hold"] else f"{a['remainingSeconds']} s left"
            print(f"  {a['turbineId']} {a['kind']} severity {a['severity']} "
                  f"intensity {a['intensity']} ({a['source']}, {remaining})")
    else:
        print("Active anomalies: none")
    standing = result.get("standingConditions") or []
    if standing:
        print("Standing conditions (from the site history, no alarm): "
              + ", ".join(f"{c['turbineId']} {c['kind']}" for c in standing))


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cfg = SimConfig.from_env()
    site = load_site(cfg.site_file)
    prefix = f"{cfg.topic_root}/{site.site_id}/_sim"

    request = {k: v for k, v in vars(args).items() if k not in ("json", "timeout") and v not in ("", None)}
    request["requestId"] = uuid.uuid4().hex[:12]
    if args.command == "wind" and not args.clear and args.mean is None:
        print("wind: give --mean <m/s> or --clear", file=sys.stderr)
        return 2

    replies: queue.Queue[bytes] = queue.Queue()
    response_topic = f"{prefix}/response/{request['requestId']}"

    def on_message(topic: str, payload: bytes) -> None:
        if topic == response_topic:
            replies.put(payload)

    if cfg.mqtt_tls:
        from .k8s import current_ca_file
        cfg.mqtt_ca_file = current_ca_file(cfg.mqtt_ca_file, cfg.mqtt_ca_configmap)
    link = MqttLink(cfg, client_id=f"simctl-{request['requestId']}", on_message=on_message)
    link.subscribe(response_topic)
    link.start()
    try:
        if not link.wait_connected(args.timeout):
            print("could not connect to the MQTT broker", file=sys.stderr)
            return 1
        link.publish(f"{prefix}/request", request)
        try:
            ack = json.loads(replies.get(timeout=args.timeout))
        except queue.Empty:
            print("no reply from the simulator (is it running?)", file=sys.stderr)
            return 1
    finally:
        link.stop()

    if args.json:
        print(json.dumps(ack, indent=2))
    elif not ack.get("ok"):
        print(f"rejected: {ack.get('error')}", file=sys.stderr)
    elif args.command == "status":
        _print_status(ack["result"])
    else:
        print(json.dumps(ack["result"], indent=2))
    return 0 if ack.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
