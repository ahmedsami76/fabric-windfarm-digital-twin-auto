"""Site definition: the static description of the wind farm.

The site file (data/reference/site.json) is produced by ``sitegen`` and is the
single source of truth shared by the simulator, the Lakehouse reference tables
and, later, the 3D app.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TurbineModel:
    model: str
    manufacturer: str
    rated_power_kw: float
    rotor_diameter_m: float
    hub_height_m: float
    cut_in_wind_speed: float
    rated_wind_speed: float
    cut_out_wind_speed: float
    gear_ratio: float
    rated_rotor_rpm: float


@dataclass(frozen=True)
class TurbineSpec:
    turbine_id: str
    name: str
    x: float              # metres east of the site origin
    y: float              # metres north of the site origin
    latitude: float
    longitude: float
    elevation_m: float
    string: str
    commissioned_date: str
    serial_number: str


@dataclass(frozen=True)
class Site:
    site_id: str
    site_name: str
    operator: str
    timezone: str
    latitude: float
    longitude: float
    prevailing_wind_direction_deg: float
    ppa_price_usd_per_mwh: float
    model: TurbineModel
    turbines: tuple[TurbineSpec, ...]
    met_mast_id: str
    raw: dict

    @property
    def mean_elevation_m(self) -> float:
        return sum(t.elevation_m for t in self.turbines) / len(self.turbines)

    def turbine(self, turbine_id: str) -> TurbineSpec:
        for t in self.turbines:
            if t.turbine_id == turbine_id:
                return t
        raise KeyError(turbine_id)


def load_site(path: str | Path) -> Site:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    m = raw["turbineModel"]
    model = TurbineModel(
        model=m["model"],
        manufacturer=m["manufacturer"],
        rated_power_kw=float(m["ratedPowerKw"]),
        rotor_diameter_m=float(m["rotorDiameterM"]),
        hub_height_m=float(m["hubHeightM"]),
        cut_in_wind_speed=float(m["cutInWindSpeed"]),
        rated_wind_speed=float(m["ratedWindSpeed"]),
        cut_out_wind_speed=float(m["cutOutWindSpeed"]),
        gear_ratio=float(m["gearRatio"]),
        rated_rotor_rpm=float(m["ratedRotorRpm"]),
    )
    turbines = tuple(
        TurbineSpec(
            turbine_id=t["turbineId"],
            name=t["name"],
            x=float(t["x"]),
            y=float(t["y"]),
            latitude=float(t["latitude"]),
            longitude=float(t["longitude"]),
            elevation_m=float(t["elevationM"]),
            string=t["string"],
            commissioned_date=t["commissionedDate"],
            serial_number=t["serialNumber"],
        )
        for t in raw["turbines"]
    )
    return Site(
        site_id=raw["siteId"],
        site_name=raw["siteName"],
        operator=raw["operator"],
        timezone=raw["timezone"],
        latitude=float(raw["origin"]["latitude"]),
        longitude=float(raw["origin"]["longitude"]),
        prevailing_wind_direction_deg=float(raw["prevailingWindDirectionDeg"]),
        ppa_price_usd_per_mwh=float(raw["ppaPriceUsdPerMwh"]),
        model=model,
        turbines=turbines,
        met_mast_id=raw["metMast"]["id"],
        raw=raw,
    )
