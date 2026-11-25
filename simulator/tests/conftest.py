from pathlib import Path

import pytest

from windfarm_sim.config import SimConfig
from windfarm_sim.engine import Simulator
from windfarm_sim.site import load_site

SITE_FILE = Path(__file__).resolve().parents[2] / "data" / "reference" / "site.json"
START_EPOCH = 1_795_000_000.0


@pytest.fixture(scope="session")
def site():
    return load_site(SITE_FILE)


@pytest.fixture
def make_sim(site):
    def _make(seed=7, wind=10.5, spontaneous=0.0, wind_model="regime", standing=False, start_epoch=START_EPOCH):
        # The physics tests use a fixed wind band and healthy turbines. The climate wind and the
        # standing conditions have their own tests.
        cfg = SimConfig(site_file=str(SITE_FILE), seed=seed, wind_mean=wind,
                        wind_regime_min=wind - 0.5, wind_regime_max=wind + 0.5,
                        spontaneous_events_per_hour=spontaneous, wind_model=wind_model,
                        standing_conditions=standing)
        return Simulator(site, cfg, start_epoch=start_epoch)
    return _make


def run(sim, seconds):
    """Advance the simulator and return every payload it produced."""
    payloads = []
    for _ in range(int(seconds)):
        payloads.extend(m.payload for m in sim.step(1.0))
    return payloads
