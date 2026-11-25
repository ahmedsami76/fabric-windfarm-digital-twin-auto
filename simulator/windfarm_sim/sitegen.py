"""Generate the fictional site and its reference data.

    python -m windfarm_sim.sitegen --out data/reference --seed 42

Everything is derived from the seed: procedural terrain, turbine layout on the
ridge crests, GIS layers, asset and component master data, spare parts, people,
contracts and the alarm and power-curve tables. Work orders and everything else
that has a date are part of the operating history (``history.py``). Commit the output so the
simulator, the Lakehouse and the 3D app all describe the same site. A different
seed gives a different site.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from datetime import date, timedelta
from pathlib import Path

from .alarms import ALARMS
from .catalog import CONTRACT_COLUMNS, CONTRACTS, EXTRA_ALARMS, SPARE_PARTS, STANDING_CONDITIONS, TECHNICIANS
from .site import TurbineModel
from .turbine import power_curve_kw

SITE_ID = "northwind-ridge"
SITE_NAME = "Northwind Ridge Wind Farm"
OPERATOR = "Contoso Energy"
ORIGIN_LAT, ORIGIN_LON = 32.2150, -100.4800   # fictional location on the West Texas plains
PREVAILING_WIND_DEG = 195.0
TERRAIN_SIZE_M = 6000.0
GRID = 129
TURBINE_COUNT = 12
CLIMATE_SEED = 20211
HISTORY_START = "2025-01-01T00:00:00+00:00"

MODEL = TurbineModel(
    model="CT-4.2-150", manufacturer="Contoso Turbines", rated_power_kw=4200.0,
    rotor_diameter_m=150.0, hub_height_m=105.0, cut_in_wind_speed=3.0,
    rated_wind_speed=12.0, cut_out_wind_speed=25.0, gear_ratio=97.0, rated_rotor_rpm=12.3,
)

COMPONENTS = (
    ("ROT", "Rotor hub", "Contoso Turbines", "CT-HUB-150", 25),
    ("BLD", "Blade set", "Tailspin Blades", "TB-73.5", 25),
    ("PIT", "Pitch system", "Woodgrove Hydraulics", "WH-PITCH-3A", 20),
    ("MBR", "Main bearing", "Northwind Bearings", "NB-SRB-2400", 20),
    ("GBX", "Gearbox", "Fabrikam Drivetrain", "FD-3P-97", 20),
    ("GEN", "Generator", "Adatum Electric", "AE-DFIG-4500", 20),
    ("CNV", "Converter", "Adatum Electric", "AE-CNV-1500", 15),
    ("TRF", "Transformer", "Adatum Electric", "AE-TRF-5000", 30),
    ("YAW", "Yaw system", "Contoso Turbines", "CT-YAW-6D", 20),
    ("HYD", "Hydraulic unit", "Woodgrove Hydraulics", "WH-HPU-200", 15),
    ("TWR", "Tower", "Contoso Turbines", "CT-TWR-105", 30),
)

SOPS = (
    ("SOP-OPS-000", "Alarm triage and escalation", "SOP-OPS-000-alarm-triage-and-escalation.md"),
    ("SOP-GBX-001", "Gearbox high temperature or vibration", "SOP-GBX-001-gearbox-temperature-vibration.md"),
    ("SOP-GEN-002", "Generator winding over-temperature", "SOP-GEN-002-generator-over-temperature.md"),
    ("SOP-PIT-003", "Pitch system fault", "SOP-PIT-003-pitch-system-fault.md"),
    ("SOP-YAW-004", "Yaw misalignment", "SOP-YAW-004-yaw-misalignment.md"),
    ("SOP-COM-005", "Loss of communication", "SOP-COM-005-loss-of-communication.md"),
    ("SOP-CUR-006", "Remote curtailment, stop and restart", "SOP-CUR-006-remote-curtailment-stop-restart.md"),
)


# --------------------------------------------------------------------------- #
# terrain
def _lattice(seed: int, ix: int, iy: int) -> float:
    h = (ix * 374761393 + iy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def _value_noise(seed: int, x: float, y: float) -> float:
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    sx, sy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _lattice(seed, ix, iy), _lattice(seed, ix + 1, iy)
    c, d = _lattice(seed, ix, iy + 1), _lattice(seed, ix + 1, iy + 1)
    return (a + (b - a) * sx) * (1 - sy) + (c + (d - c) * sx) * sy


def make_elevation(seed: int):
    """Return elevation(x, y) in metres for local coordinates in metres."""
    rng = random.Random(seed)
    phase1, phase2 = rng.uniform(0, 2 * math.pi), rng.uniform(0, 2 * math.pi)
    amp1, amp2 = rng.uniform(350, 550), rng.uniform(250, 400)
    spur_x = rng.uniform(-900, 900)

    def elevation(x: float, y: float) -> float:
        # Main ridge runs roughly west to east, across the prevailing wind.
        ridge_y = 500.0 + amp1 * math.sin(x / 1500.0 + phase1)
        main = 68.0 * math.exp(-((y - ridge_y) / 620.0) ** 2)
        # A spur runs south from the main ridge.
        spur_cx = spur_x + amp2 * math.sin(y / 1100.0 + phase2)
        spur = 44.0 * math.exp(-((x - spur_cx) / 480.0) ** 2) * (1.0 if y < ridge_y else
                                                                math.exp(-((y - ridge_y) / 500.0) ** 2))
        spur *= 1.0 / (1.0 + math.exp((-y - 1900.0) / 250.0))   # fades out toward the south edge
        noise = sum(_value_noise(seed + o, x / (1400.0 / 2 ** o), y / (1400.0 / 2 ** o)) * (18.0 / 2 ** o)
                    for o in range(4))
        return 696.0 + main + spur + noise + 0.0025 * (y + 3000.0)

    return elevation


# --------------------------------------------------------------------------- #
def _to_latlon(x: float, y: float) -> tuple[float, float]:
    lat = ORIGIN_LAT + y / 111_320.0
    lon = ORIGIN_LON + x / (111_320.0 * math.cos(math.radians(ORIGIN_LAT)))
    return round(lat, 6), round(lon, 6)


def _place_turbines(elevation) -> list[tuple[float, float]]:
    half = TERRAIN_SIZE_M / 2 - 600.0
    step = 75.0
    n = int(2 * half / step) + 1
    candidates = [(-half + i * step, -half + j * step) for i in range(n) for j in range(n)]
    candidates.sort(key=lambda p: elevation(*p), reverse=True)
    min_spacing = 4.2 * MODEL.rotor_diameter_m
    picked: list[tuple[float, float]] = []
    for p in candidates:
        if all(math.dist(p, q) >= min_spacing for q in picked):
            picked.append(p)
            if len(picked) == TURBINE_COUNT:
                break
    picked.sort(key=lambda p: (p[0], p[1]))
    return picked


def _mst(points: list[tuple[float, float]]) -> list[tuple[int, int]]:
    """Minimum spanning tree (Prim) used to lay out the access roads."""
    connected, edges = {0}, []
    while len(connected) < len(points):
        best = min(((math.dist(points[i], points[j]), i, j)
                    for i in connected for j in range(len(points)) if j not in connected))
        edges.append((best[1], best[2]))
        connected.add(best[2])
    return edges


def _feature(geometry_type: str, coordinates, properties: dict) -> dict:
    return {"type": "Feature", "geometry": {"type": geometry_type, "coordinates": coordinates},
            "properties": properties}


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


def _write_json(path: Path, obj, indent: int | None = 2) -> None:
    path.write_text(json.dumps(obj, indent=indent) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
DRIVETRAIN_WARRANTY_END = "2026-12-31"


def generate(out: Path, seed: int, drivetrain_warranty_end: str = DRIVETRAIN_WARRANTY_END) -> dict:
    rng = random.Random(seed)
    elevation = make_elevation(seed)
    (out / "gis").mkdir(parents=True, exist_ok=True)
    (out / "terrain").mkdir(parents=True, exist_ok=True)

    # ---- terrain heightmap -------------------------------------------------
    half = TERRAIN_SIZE_M / 2
    spacing = TERRAIN_SIZE_M / (GRID - 1)
    rows = [[round(elevation(-half + c * spacing, -half + r * spacing), 1) for c in range(GRID)]
            for r in range(GRID)]
    flat = [v for row in rows for v in row]
    _write_json(out / "terrain" / "heightmap.json", {
        "description": "Procedural terrain of the fictional site. Rows run south to north, "
                       "columns west to east, values are metres above sea level.",
        "seed": seed, "sizeM": TERRAIN_SIZE_M, "grid": GRID, "spacingM": spacing,
        "originLatitude": ORIGIN_LAT, "originLongitude": ORIGIN_LON,
        "minElevationM": min(flat), "maxElevationM": max(flat), "elevationsM": rows,
    }, indent=None)

    # ---- layout ------------------------------------------------------------
    positions = _place_turbines(elevation)
    turbines = []
    for i, (x, y) in enumerate(positions, start=1):
        lat, lon = _to_latlon(x, y)
        commissioned = date(2021, 3, 1) + timedelta(days=rng.randint(0, 150))
        turbines.append({
            "turbineId": f"WT-{i:02d}", "name": f"Turbine {i:02d}", "x": x, "y": y,
            "latitude": lat, "longitude": lon, "elevationM": round(elevation(x, y), 1),
            "string": "ABC"[(i - 1) * 3 // TURBINE_COUNT],
            "commissionedDate": commissioned.isoformat(),
            "serialNumber": f"CT42-{rng.randint(100000, 999999)}",
        })

    cx = sum(t["x"] for t in turbines) / len(turbines)
    cy = sum(t["y"] for t in turbines) / len(turbines)
    rad = math.radians(PREVAILING_WIND_DEG)
    mast_xy = (round(cx + 1300.0 * math.sin(rad)), round(cy + 1300.0 * math.cos(rad)))
    sub_xy = min(((x, y) for x in range(-1500, 1501, 150) for y in range(-2500, -1699, 100)),
                 key=lambda p: elevation(*p))
    om_xy = (sub_xy[0] + 120, sub_xy[1] - 60)
    gate_xy = (sub_xy[0], -half + 100)

    def point(pid: str, name: str, kind: str, xy) -> dict:
        lat, lon = _to_latlon(*xy)
        return {"id": pid, "name": name, "assetType": kind, "x": xy[0], "y": xy[1],
                "latitude": lat, "longitude": lon, "elevationM": round(elevation(*xy), 1)}

    mast = point("MET-01", "Met mast 01", "MetMast", mast_xy)
    substation = point("SUB-01", "Collector substation", "Substation", sub_xy)
    om = point("OM-01", "Operations and maintenance building", "Building", om_xy)

    site = {
        "siteId": SITE_ID, "siteName": SITE_NAME, "operator": OPERATOR,
        "fictional": True, "timezone": "America/Chicago",
        "origin": {"latitude": ORIGIN_LAT, "longitude": ORIGIN_LON},
        "prevailingWindDirectionDeg": PREVAILING_WIND_DEG,
        "ppaPriceUsdPerMwh": 38.5,
        # Assumed average emission intensity of the regional grid; used for "emissions avoided".
        "gridEmissionFactorKgCo2PerMwh": 370.0,
        "capacityMw": round(TURBINE_COUNT * MODEL.rated_power_kw / 1000.0, 1),
        "terrain": {"seed": seed, "sizeM": TERRAIN_SIZE_M, "grid": GRID,
                    "file": "terrain/heightmap.json"},
        "turbineModel": {
            "model": MODEL.model, "manufacturer": MODEL.manufacturer,
            "ratedPowerKw": MODEL.rated_power_kw, "rotorDiameterM": MODEL.rotor_diameter_m,
            "hubHeightM": MODEL.hub_height_m, "cutInWindSpeed": MODEL.cut_in_wind_speed,
            "ratedWindSpeed": MODEL.rated_wind_speed, "cutOutWindSpeed": MODEL.cut_out_wind_speed,
            "gearRatio": MODEL.gear_ratio, "ratedRotorRpm": MODEL.rated_rotor_rpm,
        },
        "metMast": mast, "substation": substation, "omBuilding": om,
        "turbines": turbines,
        # Shared by the history generator, the live simulator and the forecast.
        "climateSeed": CLIMATE_SEED,
        "historyStart": HISTORY_START,
        "standingConditions": [dict(c) for c in STANDING_CONDITIONS],
    }
    _write_json(out / "site.json", site)

    # ---- GIS layers --------------------------------------------------------
    def lonlat(xy) -> list[float]:
        lat, lon = _to_latlon(*xy)
        return [lon, lat]

    _write_json(out / "gis" / "turbines.geojson", {"type": "FeatureCollection", "features": [
        _feature("Point", [t["longitude"], t["latitude"], t["elevationM"]],
                 {"id": t["turbineId"], "name": t["name"], "assetType": "WindTurbine",
                  "string": t["string"], "elevationM": t["elevationM"]}) for t in turbines]})
    _write_json(out / "gis" / "infrastructure.geojson", {"type": "FeatureCollection", "features": [
        _feature("Point", [p["longitude"], p["latitude"], p["elevationM"]],
                 {"id": p["id"], "name": p["name"], "assetType": p["assetType"]})
        for p in (mast, substation, om)]})
    nodes = [sub_xy] + positions
    names = ["SUB-01"] + [t["turbineId"] for t in turbines]
    roads = [_feature("LineString", [lonlat(nodes[i]), lonlat(nodes[j])],
                      {"id": f"RD-{n:02d}", "from": names[i], "to": names[j], "roadType": "access",
                       "lengthM": round(math.dist(nodes[i], nodes[j]))})
             for n, (i, j) in enumerate(_mst(nodes), start=1)]
    roads.append(_feature("LineString", [lonlat(gate_xy), lonlat(sub_xy)],
                          {"id": "RD-00", "from": "GATE", "to": "SUB-01", "roadType": "entrance",
                           "lengthM": round(math.dist(gate_xy, sub_xy))}))
    _write_json(out / "gis" / "roads.geojson", {"type": "FeatureCollection", "features": roads})
    b = half - 200.0
    ring = [lonlat(p) for p in ((-b, -b), (b, -b), (b, b), (-b, b), (-b, -b))]
    _write_json(out / "gis" / "site_boundary.geojson", {"type": "FeatureCollection", "features": [
        _feature("Polygon", [ring], {"id": SITE_ID, "name": SITE_NAME, "areaKm2": round((2 * b / 1000) ** 2, 1)})]})

    # ---- master data -------------------------------------------------------
    _write_csv(out / "site.csv",
               ["siteId", "siteName", "operator", "latitude", "longitude", "timezone", "capacityMw",
                "turbineCount", "ppaPriceUsdPerMwh", "prevailingWindDirectionDeg", "gridEmissionFactorKgCo2PerMwh"],
               [[SITE_ID, SITE_NAME, OPERATOR, ORIGIN_LAT, ORIGIN_LON, "America/Chicago",
                 site["capacityMw"], TURBINE_COUNT, site["ppaPriceUsdPerMwh"], PREVAILING_WIND_DEG,
                 site["gridEmissionFactorKgCo2PerMwh"]]])
    _write_csv(out / "turbines.csv",
               ["turbineId", "siteId", "name", "model", "manufacturer", "serialNumber", "ratedPowerKw",
                "rotorDiameterM", "hubHeightM", "latitude", "longitude", "elevationM", "localX", "localY",
                "string", "commissionedDate"],
               [[t["turbineId"], SITE_ID, t["name"], MODEL.model, MODEL.manufacturer, t["serialNumber"],
                 MODEL.rated_power_kw, MODEL.rotor_diameter_m, MODEL.hub_height_m, t["latitude"],
                 t["longitude"], t["elevationM"], t["x"], t["y"], t["string"], t["commissionedDate"]]
                for t in turbines])

    component_rows = []
    for t in turbines:
        commissioned = date.fromisoformat(t["commissionedDate"])
        for code, ctype, maker, cmodel, life in COMPONENTS:
            installed = commissioned
            # A few components were replaced after commissioning.
            if code in ("CNV", "HYD", "PIT") and rng.random() < 0.18:
                installed = commissioned + timedelta(days=rng.randint(700, 1700))
            # Two years of supplier warranty; the drivetrain is covered by its own contract.
            if code in ("GBX", "MBR"):
                warranty_end, contract = drivetrain_warranty_end, "CT-WAR-001"
            else:
                warranty_end, contract = installed.replace(year=installed.year + 2).isoformat(), ""
            component_rows.append([f"{t['turbineId']}-{code}", t["turbineId"], code, ctype, maker, cmodel,
                                   f"{code}{rng.randint(10_000_000, 99_999_999)}", installed.isoformat(), life,
                                   warranty_end, contract])
    _write_csv(out / "components.csv",
               ["componentId", "turbineId", "componentCode", "componentType", "manufacturer", "model",
                "serialNumber", "installDate", "designLifeYears", "warrantyEndDate", "warrantyContractId"],
               component_rows)

    _write_csv(out / "alarm_codes.csv",
               ["alarmCode", "component", "severity", "description", "signal", "threshold", "direction",
                "unit", "controllerAction", "sopId", "liveSimulated"],
               [[a.code, a.component, a.severity, a.description,
                 "" if a.signal is None or a.signal.startswith("_") else a.signal,
                 "" if a.threshold is None else a.threshold, a.direction if a.signal else "", a.unit,
                 {"none": "", "derate": f"derate to {round(a.derate_to * 100)}%", "trip": "stop turbine"}[a.action],
                 a.sop, "true"] for a in ALARMS]
               + [[code, component, severity, description, "", "", "", "",
                   "stop turbine" if severity == "critical" else "", sop, "false"]
                  for code, component, severity, description, sop in EXTRA_ALARMS])

    _write_csv(out / "power_curve.csv", ["model", "windSpeed", "powerKw"],
               [[MODEL.model, ws / 2, round(power_curve_kw(ws / 2, MODEL), 1)] for ws in range(0, 61)])

    _write_csv(out / "sop_index.csv", ["sopId", "title", "file", "alarmCodes"],
               [[sid, title, f"sop/{fname}", ";".join([a.code for a in ALARMS if a.sop == sid]
                                                      + [e[0] for e in EXTRA_ALARMS if e[4] == sid])]
                for sid, title, fname in SOPS])

    _write_csv(out / "spare_parts.csv",
               ["partId", "description", "componentCode", "quantityOnHand", "reorderPoint", "leadTimeDays",
                "unitCostUsd", "location"], [list(part) for part in SPARE_PARTS])
    _write_csv(out / "technicians.csv",
               ["technicianId", "name", "role", "discipline", "certifications", "crew", "onCallRoleId"],
               [list(person) for person in TECHNICIANS])
    contract_rows = [list(contract) for contract in CONTRACTS]
    if drivetrain_warranty_end != DRIVETRAIN_WARRANTY_END:
        # Demonstrations after the original end date: move the warranty, in the date and in the text.
        end = date.fromisoformat(drivetrain_warranty_end)
        spoken = f"{end.day} {end.strftime('%B %Y')}"
        for row in contract_rows:
            if row[0] == "CT-WAR-001":
                row[4] = drivetrain_warranty_end
                row[-1] = row[-1].replace("31 December 2026", spoken)
    _write_csv(out / "contracts.csv", list(CONTRACT_COLUMNS), contract_rows)

    _write_csv(out / "oncall_roster.csv",
               ["roleId", "role", "discipline", "shift", "onCall", "escalationOrder", "contactChannel"],
               [["OPS-01", "Control room operator", "Operations", "Day", "true", 1, "Teams: Wind Ops Control Room"],
                ["OPS-02", "Control room operator", "Operations", "Night", "true", 1, "Teams: Wind Ops Control Room"],
                ["ENG-01", "Reliability engineer, drivetrain", "Engineering", "Day", "true", 2, "Teams: Reliability On-Call"],
                ["ENG-02", "Electrical engineer", "Engineering", "Day", "false", 2, "Teams: Reliability On-Call"],
                ["TECH-01", "Lead wind technician", "Maintenance", "Day", "true", 3, "Teams: Site Maintenance"],
                ["TECH-02", "Wind technician", "Maintenance", "Day", "false", 3, "Teams: Site Maintenance"],
                ["TECH-03", "Wind technician", "Maintenance", "Day", "false", 3, "Teams: Site Maintenance"],
                ["MGR-01", "Site manager", "Management", "Day", "true", 4, "Teams: Site Leadership"]])

    return site


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate the fictional wind farm site and reference data.")
    p.add_argument("--out", default="data/reference")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--drivetrain-warranty-end", default=DRIVETRAIN_WARRANTY_END, metavar="YYYY-MM-DD",
                   help="end of the gearbox and main bearing warranty (default: %(default)s)")
    args = p.parse_args(argv)
    date.fromisoformat(args.drivetrain_warranty_end)          # fail early on a bad date
    site = generate(Path(args.out), args.seed, args.drivetrain_warranty_end)
    elevs = [t["elevationM"] for t in site["turbines"]]
    print(f"site {site['siteId']}: {len(site['turbines'])} turbines, {site['capacityMw']} MW, "
          f"turbine elevations {min(elevs)} to {max(elevs)} m, written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
