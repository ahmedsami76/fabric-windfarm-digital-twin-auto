/**
 * The site as the twin draws it: turbines, buildings, roads and terrain, in metres in the site's own
 * frame (x to the east, y to the north). The data is `assets/site-data.ts`, which
 * `tools/build-twin-assets.py` of the repository makes from `data/reference`.
 */
import { SITE_DATA_JSON } from '../assets/site-data';

export interface SiteTurbine {
  id: string;
  name: string;
  x: number;
  y: number;
  elevationM: number;
  string: string;
}

export interface SitePlace {
  id: string;
  name: string;
  type: string;
  x: number;
  y: number;
  elevationM: number;
}

export interface SiteRoad {
  id: string;
  type: string;
  points: number[][];
}

export interface TurbineModel {
  model: string;
  ratedPowerKw: number;
  rotorDiameterM: number;
  hubHeightM: number;
  cutInWindSpeed: number;
  ratedWindSpeed: number;
  cutOutWindSpeed: number;
  ratedRotorRpm: number;
}

export interface Site {
  site: { id: string; name: string; operator: string; capacityMw: number; timezone: string; prevailingWindDirectionDeg: number };
  turbineModel: TurbineModel;
  turbines: SiteTurbine[];
  infrastructure: SitePlace[];
  roads: SiteRoad[];
  terrain: { grid: number; sizeM: number; minElevationM: number; maxElevationM: number; elevationsDm: number[][] };
}

export const SITE = JSON.parse(SITE_DATA_JSON) as Site;

/**
 * Thresholds on the gearbox signals. The early warning at 4.0 mm/s and 72 °C is the one the operations
 * agent of Phase 3 watches (`tools/agent_spec.py`). The alarm levels, 5.5 mm/s and 78 °C, are those at
 * which the turbine controller raises its first alarm on each signal (`data/reference/alarm_codes.csv`).
 */
export const EARLY_VIBRATION = 4.0;
export const ALARM_VIBRATION = 5.5;
export const EARLY_OIL_TEMP = 72.0;
export const ALARM_OIL_TEMP = 78.0;

/**
 * Yaw error, in degrees either way, from which the twin marks the yaw system. This one is the twin's
 * own: the turbine controller has no alarm on the yaw error, and a nacelle that stands this far off
 * the wind for long is what a miscalibrated wind vane looks like.
 */
export const WATCH_YAW_ERROR = 6.0;

/** Elevation in metres above sea level at a position, by bilinear interpolation of the grid. */
export function groundAt(x: number, y: number): number {
  const { grid, sizeM, elevationsDm } = SITE.terrain;
  const step = sizeM / (grid - 1);
  const col = Math.min(Math.max((x + sizeM / 2) / step, 0), grid - 1 - 1e-9);
  const row = Math.min(Math.max((y + sizeM / 2) / step, 0), grid - 1 - 1e-9);
  const c = Math.floor(col);
  const r = Math.floor(row);
  const fc = col - c;
  const fr = row - r;
  const south = elevationsDm[r][c] * (1 - fc) + elevationsDm[r][c + 1] * fc;
  const north = elevationsDm[r + 1][c] * (1 - fc) + elevationsDm[r + 1][c + 1] * fc;
  return (south * (1 - fr) + north * fr) / 10;
}

/** Power in kW the turbine model gives at a wind speed: a cubic rise from cut-in to rated power. */
export function powerCurve(windSpeed: number): number {
  const m = SITE.turbineModel;
  if (windSpeed < m.cutInWindSpeed || windSpeed >= m.cutOutWindSpeed) return 0;
  if (windSpeed >= m.ratedWindSpeed) return m.ratedPowerKw;
  const share = (windSpeed ** 3 - m.cutInWindSpeed ** 3) / (m.ratedWindSpeed ** 3 - m.cutInWindSpeed ** 3);
  return m.ratedPowerKw * share;
}

/**
 * Whether the gearbox readings of a turbine are worth watching: 1 from the early warning on, 0 below it.
 *
 * The readings alone never say "alarm". The turbine controller compares a short average with its limit
 * and, for vibration, waits 15 seconds before it raises one, so a single reading of 5.6 mm/s is no alarm.
 * A small fault at a fresh wind produces such readings every minute or so; a twin that turned red on
 * each of them would flicker and would contradict its own alarm list. Red comes from the alarms of the
 * controller: `gearboxCondition` in `components.ts`.
 */
export function gearboxWatch(vibration: number, oilTemp: number): 0 | 1 {
  return vibration >= EARLY_VIBRATION || oilTemp >= EARLY_OIL_TEMP ? 1 : 0;
}
