"""Generate sample data offline, faster than real time.

    python -m windfarm_sim.generate --minutes 45 --seed 7 \
        --inject "WT-07:gearbox_degradation:0.8:15m@10m" --out data/samples/sample_events.json

Each output line is one message payload, exactly as it would arrive in the
Fabric eventstream, so the file can be used to test the Fabric side without
the edge.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import SimConfig
from .engine import Simulator, parse_duration
from .site import load_site


def _parse_inject(text: str) -> tuple[float, dict]:
    """'WT-07:gearbox_degradation:0.8:15m@10m' -> (600.0, command dict)."""
    spec, _, at = text.partition("@")
    parts = spec.split(":")
    if len(parts) < 2:
        raise argparse.ArgumentTypeError("use TURBINE:KIND[:SEVERITY[:DURATION]]@OFFSET")
    cmd = {"command": "inject", "turbine": parts[0], "kind": parts[1]}
    if len(parts) > 2 and parts[2]:
        cmd["severity"] = float(parts[2])
    if len(parts) > 3 and parts[3]:
        cmd["duration"] = parts[3]
    return parse_duration(at or "0", 0.0), cmd


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate wind farm sample data as JSON lines.")
    p.add_argument("--site", default="data/reference/site.json")
    p.add_argument("--minutes", type=float, default=45.0)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--start", default="", help="UTC start time, ISO 8601 (default: now)")
    p.add_argument("--wind-mean", type=float, default=10.0)
    p.add_argument("--inject", action="append", default=[], type=_parse_inject,
                   help="TURBINE:KIND[:SEVERITY[:DURATION]]@OFFSET, repeatable")
    p.add_argument("--no-spontaneous", action="store_true", help="disable random minor events")
    p.add_argument("--out", required=True)
    p.add_argument("--truth", default="", help="optional file for the anomaly ground truth")
    args = p.parse_args(argv)

    cfg = SimConfig(site_file=args.site, seed=args.seed, wind_mean=args.wind_mean,
                    wind_regime_min=args.wind_mean - 1.0, wind_regime_max=args.wind_mean + 1.0,
                    spontaneous_events_per_hour=0.0 if args.no_spontaneous else 1.0,
                    # A fixed wind band, so that the sample shows the fault and not the weather of the day.
                    wind_model="regime")
    start = (datetime.fromisoformat(args.start.replace("Z", "+00:00")).timestamp()
             if args.start else datetime.now(timezone.utc).timestamp())
    sim = Simulator(load_site(args.site), cfg, start_epoch=start)
    pending = sorted(args.inject, key=lambda item: item[0])

    counts: dict[str, int] = {}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as out:
        for _ in range(int(args.minutes * 60)):
            while pending and sim.t >= pending[0][0]:
                ack = sim.handle_command(pending.pop(0)[1])
                if not ack["ok"]:
                    print(f"inject failed: {ack['error']}", file=sys.stderr)
                    return 1
            for msg in sim.step(1.0):
                out.write(json.dumps(msg.payload, separators=(",", ":")) + "\n")
                kind = msg.payload["messageType"]
                counts[kind] = counts.get(kind, 0) + 1

    if args.truth:
        Path(args.truth).write_text(
            "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in sim.ground_truth), encoding="utf-8")
    print(f"wrote {sum(counts.values())} messages to {out_path}: "
          + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
