import filecmp
import math

from conftest import SITE_FILE

from windfarm_sim import sitegen
from windfarm_sim.alarms import ALARMS, ALARMS_BY_CODE
from windfarm_sim.engine import parse_duration
from windfarm_sim.turbine import power_curve_kw


def test_site_layout(site):
    assert len(site.turbines) == 12
    ids = [t.turbine_id for t in site.turbines]
    assert ids == [f"WT-{i:02d}" for i in range(1, 13)]
    spacing = min(math.dist((a.x, a.y), (b.x, b.y))
                  for i, a in enumerate(site.turbines) for b in site.turbines[i + 1:])
    assert spacing >= 4 * site.model.rotor_diameter_m


def test_power_curve(site):
    m = site.model
    assert power_curve_kw(m.cut_in_wind_speed - 0.1, m) == 0.0
    assert power_curve_kw(m.cut_out_wind_speed + 0.1, m) == 0.0
    assert power_curve_kw(m.rated_wind_speed, m) == m.rated_power_kw
    assert power_curve_kw(20.0, m) == m.rated_power_kw
    values = [power_curve_kw(ws / 10, m) for ws in range(30, 121)]
    assert values == sorted(values)


def test_alarm_catalogue_is_consistent():
    assert len(ALARMS_BY_CODE) == len(ALARMS)
    for a in ALARMS:
        assert a.severity in ("info", "warning", "critical")
        assert a.sop.startswith("SOP-")
        if a.action == "derate":
            assert 0 < a.derate_to < 1


def test_parse_duration():
    assert parse_duration("90s") == 90
    assert parse_duration("12m") == 720
    assert parse_duration("1h") == 3600
    assert parse_duration(45) == 45
    assert parse_duration("", 7) == 7


def test_committed_reference_data_matches_the_generator(tmp_path):
    """data/reference must be regenerated whenever the generator or the alarm catalogue changes."""
    sitegen.generate(tmp_path, seed=42)
    committed = SITE_FILE.parent
    generated = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert generated == sorted(p.relative_to(committed) for p in committed.rglob("*") if p.is_file())
    stale = [str(rel) for rel in generated if not filecmp.cmp(tmp_path / rel, committed / rel, shallow=False)]
    assert stale == [], f"run: python -m windfarm_sim.sitegen --out data/reference --seed 42 ({stale})"
