import json

from conftest import SITE_FILE

from windfarm_sim import generate


def test_generate_writes_json_lines(tmp_path):
    out = tmp_path / "sample.jsonl"
    truth = tmp_path / "truth.jsonl"
    rc = generate.main(["--site", str(SITE_FILE), "--minutes", "12", "--seed", "1",
                        "--start", "2026-11-19T15:00:00Z", "--no-spontaneous",
                        "--inject", "WT-07:gearbox_degradation:0.9:6m@2m",
                        "--out", str(out), "--truth", str(truth)])
    assert rc == 0
    lines = [json.loads(line) for line in out.read_text().splitlines()]
    assert lines[0]["timestamp"].startswith("2026-11-19T15:00:01")
    assert sum(1 for p in lines if p["messageType"] == "telemetry") == 12 * 12 * 12
    assert any(p["messageType"] == "alarm" and p["assetId"] == "WT-07" for p in lines)
    assert [json.loads(l)["event"] for l in truth.read_text().splitlines()] == \
        ["anomaly_started", "anomaly_ended"]
