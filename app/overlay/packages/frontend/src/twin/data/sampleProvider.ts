/**
 * A simulation of the wind farm that runs in the browser. It lets the twin be looked at without Fabric:
 * in the standalone preview, and in the deployed app with `?sample` in the address.
 *
 * It follows the edge simulator in what matters to the eye: one wind for the whole site, twelve
 * machines on one power curve, temperatures and pressures at the levels the simulator gives them, the
 * three standing conditions (WT-05 yawed, WT-07 warm gearbox, WT-09 eroded blades), and a gearbox
 * fault. The fault runs through the alarms of the turbine controller as the reference data lists them:
 * vibration high, vibration critical with a derate to 30%, oil temperature high and critical, the trip
 * on oil temperature, and a restart 65 seconds later. It also knows a limit on a turbine's power, set
 * the way the operations agent sets one after an approval, with the lines the edge's command log would
 * hold for it. Its numbers are invented and are not the numbers of the KQL database.
 */
import type { AgentAnswer, Alarm, CommandEntry, DiagnosticStep, LiveState, TrendPoint, TurbineLive, TurbineState } from './contract';
import type { TwinDataProvider } from './provider';
import { SITE, powerCurve } from './site';

interface Fault {
  turbineId: string;
  startMs: number;
}

/** A limit on a turbine's power, as a command sets it. */
interface Limit {
  turbineId: string;
  requestId: string;
  startMs: number;
  endMs: number;
  percent: number;
}

/** A simulated limit: to this share of rated power, for this long, shown by the "telemetry" after this delay. */
export const SAMPLE_LIMIT_PERCENT = 30;
export const SAMPLE_LIMIT_MINUTES = 5;
export const SAMPLE_CONFIRM_S = 6;
export const SAMPLE_REQUESTER = 'operations agent WindFarmGearboxWatch, approved in Teams (simulated)';

/**
 * What the turbine controller raises while a remote setpoint limits the power: a note of severity `info`,
 * not an alarm. Code, text and procedure are those of `data/reference/alarm_codes.csv`; a test compares.
 */
export const SAMPLE_LIMIT_NOTE = { code: 'POWER-CURTAILED', severity: 'info', component: 'controller', description: 'Power limited by remote setpoint', sopId: 'SOP-CUR-006' } as const;

/** The limit that holds on a turbine at a time: set, shown by the telemetry, and not yet over. */
const limitAt = (limits: Limit[], turbineId: string, nowMs: number): Limit | undefined =>
  limits.find((l) => l.turbineId === turbineId && nowMs >= l.startMs + SAMPLE_CONFIRM_S * 1000 && nowMs < l.endMs);

/** The lines the edge's command log would hold for the simulated limits, newest first. */
function commandLog(limits: Limit[], nowMs: number): CommandEntry[] {
  const iso = (ms: number): string => new Date(ms).toISOString();
  return limits
    .filter((l) => nowMs >= l.startMs && nowMs - l.startMs < 24 * 3600_000)
    .map((l): CommandEntry => {
      const shown = nowMs >= l.startMs + SAMPLE_CONFIRM_S * 1000;
      const over = nowMs >= l.endMs;
      return {
        requestId: l.requestId,
        turbineId: l.turbineId,
        command: 'curtail',
        status: over ? 'ended' : shown ? 'in force' : 'taken by the edge, not yet seen in telemetry',
        at: iso(l.startMs),
        requestedBy: SAMPLE_REQUESTER,
        origin: 'cloud',
        limitKw: (SITE.turbineModel.ratedPowerKw * l.percent) / 100,
        percent: l.percent,
        endsAt: iso(l.endMs),
        confirmedAt: shown ? iso(l.startMs + SAMPLE_CONFIRM_S * 1000) : '',
        endedAt: over ? iso(l.endMs) : '',
        error: '',
      };
    })
    .sort((a, b) => (a.at < b.at ? 1 : -1));
}

/** Seconds from the start of a fault to: the end of the build-up, the trip, the restart, the end. */
const RAMP_S = 80;
const TRIP_S = 150;
const RESTART_S = 215;
const END_S = 300;

/**
 * What the turbine controller does on the two gearbox signals. Code, level, severity and text are
 * those of `data/reference/alarm_codes.csv`, and a test compares them. `clearBelow` is the level less
 * the hysteresis of the edge simulator; `derateTo` is the share of rated power the controller allows.
 */
export const SAMPLE_ALARMS = [
  { code: 'GBX-VIB-HIGH', signal: 'vibration', severity: 'warning', threshold: 5.5, clearBelow: 4.9, unit: 'mm/s', description: 'Gearbox vibration high', derateTo: 1 },
  { code: 'GBX-VIB-CRIT', signal: 'vibration', severity: 'critical', threshold: 8.0, clearBelow: 7.2, unit: 'mm/s', description: 'Gearbox vibration critical, power derated to 30%', derateTo: 0.3 },
  { code: 'GBX-OIL-TEMP-HIGH', signal: 'oil', severity: 'warning', threshold: 78.0, clearBelow: 75.0, unit: 'degC', description: 'Gearbox oil temperature high', derateTo: 1 },
  { code: 'GBX-OIL-TEMP-CRIT', signal: 'oil', severity: 'critical', threshold: 88.0, clearBelow: 85.0, unit: 'degC', description: 'Gearbox oil temperature critical, power derated to 50%', derateTo: 0.5 },
  { code: 'GBX-OIL-TEMP-TRIP', signal: 'oil', severity: 'critical', threshold: 96.0, clearBelow: 90.0, unit: 'degC', description: 'Gearbox oil temperature trip, turbine stopped', derateTo: 1 },
] as const;

const wave = (t: number, period: number, phase: number): number => Math.sin((t / period) * 2 * Math.PI + phase);
const clamp = (v: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, v));
const lerp = (a: number, b: number, u: number): number => a + (b - a) * u;

function siteWind(tSec: number): { speed: number; direction: number } {
  const speed = 9.2 + 2.3 * wave(tSec, 1700, 0.4) + 1.0 * wave(tSec, 420, 2.1) + 0.3 * wave(tSec, 95, 5.0);
  const direction = SITE.site.prevailingWindDirectionDeg + 11 * wave(tSec, 2300, 1.3) + 4 * wave(tSec, 190, 0.2);
  return { speed: clamp(speed, 2.5, 20), direction: (direction + 360) % 360 };
}

/** The simulated wind of the whole site at a time, in m/s. */
export const sampleWindSpeed = (nowMs: number): number => siteWind(nowMs / 1000).speed;

/**
 * What a fault drives the gearbox to, `s` seconds after it started: vibration and oil temperature
 * build up, the oil reaches the trip level, the stopped gearbox cools, and after the restart both
 * come back down.
 */
function faultAt(s: number): { vibration: number; oil: number; stopped: boolean } {
  if (s < RAMP_S) return { vibration: lerp(1.5, 9.2, s / RAMP_S), oil: lerp(58, 84, s / RAMP_S), stopped: false };
  if (s < TRIP_S) return { vibration: 9.2, oil: lerp(84, 96, (s - RAMP_S) / (TRIP_S - RAMP_S)), stopped: false };
  if (s < RESTART_S) return { vibration: 0.2, oil: lerp(96, 80, (s - TRIP_S) / (RESTART_S - TRIP_S)), stopped: true };
  const u = clamp((s - RESTART_S) / (END_S - RESTART_S), 0, 1);
  return { vibration: lerp(5.0, 1.5, u), oil: lerp(80, 58, u), stopped: false };
}

/** When each alarm is raised and cleared in the course of a fault, in seconds from its start. */
const WINDOWS = new Map<string, { from: number; to: number; value: number }>();
for (const def of SAMPLE_ALARMS) {
  let from = -1;
  let to = END_S;
  let value = 0;
  for (let s = 0; s <= END_S; s += 0.5) {
    const now = faultAt(s)[def.signal];
    if (from < 0 && now >= def.threshold) {
      from = s;
      value = now;
    } else if (from >= 0 && now < def.clearBelow) {
      to = s;
      break;
    }
  }
  if (from >= 0) WINDOWS.set(def.code, { from, to, value });
}

function faultProgress(fault: Fault | undefined, nowMs: number): number {
  if (!fault) return -1;
  const s = (nowMs - fault.startMs) / 1000;
  return s >= 0 && s < END_S ? s : -1;
}

function simulate(index: number, nowMs: number, faults: Fault[], limits: Limit[] = []): { live: TurbineLive; alarms: Alarm[] } {
  const spec = SITE.turbines[index];
  const model = SITE.turbineModel;
  const t = nowMs / 1000;
  const wind = siteWind(t);
  const local = wind.speed * (1 + 0.05 * Math.sin(index * 2.4)) + 0.35 * wave(t, 140 + index * 11, index * 1.7);
  const windSpeed = clamp(local, 0, 30);
  const windDirection = (wind.direction + 3 * wave(t, 61, index) + 360) % 360;
  const ambientTemp = 19 + 5 * wave(t, 86400, -1.9);

  const yawOffset = spec.id === 'WT-05' ? 9 : 0;
  const performance = spec.id === 'WT-05' ? 0.95 : spec.id === 'WT-09' ? 0.95 : 1;
  const fault = faults.find((f) => f.turbineId === spec.id);
  const s = faultProgress(fault, nowMs);
  const fx = s >= 0 ? faultAt(s) : undefined;
  const active = s >= 0 ? SAMPLE_ALARMS.filter((def) => { const w = WINDOWS.get(def.code); return w !== undefined && s >= w.from && s < w.to; }) : [];
  const derate = Math.min(1, ...active.map((def) => def.derateTo));

  // A command's limit: the setpoint is the lower of it and what the controller allows by itself.
  const commanded = limitAt(limits, spec.id, nowMs);
  const setpoint = commanded ? (model.ratedPowerKw * commanded.percent) / 100 : model.ratedPowerKw;
  const state: TurbineState = fx?.stopped ? 'FAULT' : windSpeed < model.cutInWindSpeed ? 'IDLE' : derate < 1 ? 'DERATED' : commanded ? 'CURTAILED' : 'RUNNING';
  const producing = state === 'RUNNING' || state === 'DERATED' || state === 'CURTAILED';
  const possible = powerCurve(windSpeed) * performance;
  const limit = Math.min(model.ratedPowerKw * derate, setpoint);
  const wouldBe = Math.min(possible, limit); // what it gives, or would give if it were not stopped
  const activePower = producing ? Math.min(limit, Math.max(0, wouldBe * (1 + 0.015 * wave(t, 9, index)))) : 0;
  const load = activePower / model.ratedPowerKw;
  const turning = model.ratedRotorRpm * clamp(0.42 + 0.58 * (windSpeed / model.ratedWindSpeed), 0.42, 1) * (derate < 1 ? 0.8 : 1);
  const rotorSpeed = producing ? turning : 0;
  const speedShare = rotorSpeed / model.ratedRotorRpm;
  let pitchAngle = 88;
  if (producing) {
    const over = (windSpeed - model.ratedWindSpeed) / (model.cutOutWindSpeed - model.ratedWindSpeed);
    pitchAngle = windSpeed > model.ratedWindSpeed ? 1.5 + 21 * Math.min(1, over) ** 0.85 : 0.6;
    if (possible > limit + 1) pitchAngle += 14 * (1 - limit / possible) ** 0.7; // blades turned out of the wind to hold the limit
  }

  // Temperatures: warm with the load when the machine turns, a little over the air when it stands.
  // A machine that has just stopped keeps its heat for a while, and takes a while to warm up again.
  const heat = !fx ? (producing ? 1 : 0) : s < TRIP_S ? 1 : s < RESTART_S ? Math.exp(-(s - TRIP_S) / 400) : 1 - (1 - Math.exp(-(RESTART_S - TRIP_S) / 400)) * Math.exp(-(s - RESTART_S) / 150);
  const warmLoad = producing ? load : wouldBe / model.ratedPowerKw;
  const warmSpeed = turning / model.ratedRotorRpm;
  const overAir = ambientTemp - 15;
  const warm = (turningValue: number, standingValue: number): number => standingValue + (turningValue - standingValue) * heat;
  const oilNormal = warm(52 + 14 * warmLoad + 0.25 * overAir, ambientTemp + 10) + (spec.id === 'WT-07' ? 2.4 : 0);
  const gearboxOilTemp = Math.max(oilNormal, fx?.oil ?? 0) + 0.4 * wave(t, 70, index);
  const vibrationNormal = producing ? 1.6 * (0.35 + 0.65 * speedShare ** 2) + 0.5 * load + (spec.id === 'WT-07' ? 0.9 : 0) : 0.2;
  const gearboxVibration = (producing ? Math.max(vibrationNormal, fx?.vibration ?? 0) : 0.2) + 0.08 * wave(t, 13, index * 3);

  const live: TurbineLive = {
    id: spec.id,
    timestamp: new Date(nowMs).toISOString(),
    state,
    windSpeed,
    windDirection,
    ambientTemp,
    activePower,
    powerSetpoint: limit,
    rotorSpeed,
    pitchAngle,
    nacelleDirection: (windDirection - yawOffset + 360) % 360,
    yawError: yawOffset + 1.2 * wave(t, 40, index * 0.9),
    gearboxOilTemp,
    gearboxBearingTemp: gearboxOilTemp + 3 + 7 * load + 0.4 * wave(t, 83, index + 1),
    gearboxOilPressure: producing ? 3.2 - 0.012 * (gearboxOilTemp - 55) + 0.02 * wave(t, 29, index) : 0.8,
    gearboxVibration,
    generatorWindingTemp: warm(60 + 50 * warmLoad ** 1.3 + 0.3 * overAir, ambientTemp + 8),
    generatorBearingTemp: warm(42 + 22 * warmLoad + 0.3 * overAir, ambientTemp + 6),
    mainBearingTemp: warm(30 + 14 * warmSpeed + 0.4 * overAir, ambientTemp + 4),
    transformerTemp: warm(45 + 38 * warmLoad ** 1.2 + 0.4 * overAir, ambientTemp + 10),
    hydraulicPressure: 186 + 3 * wave(t, 47, index * 1.3),
    towerVibration: 0.25 + (0.45 * windSpeed) / 25 + 0.15 * speedShare + 0.04 * wave(t, 17, index),
  };

  const alarms: Alarm[] = fault
    ? active.map((def) => {
        const w = WINDOWS.get(def.code)!;
        return {
          id: `${spec.id}-${def.code}-${fault.startMs}`,
          turbineId: spec.id,
          code: def.code,
          severity: def.severity,
          component: 'gearbox',
          description: def.description,
          raisedAt: new Date(fault.startMs + w.from * 1000).toISOString(),
          value: w.value,
          threshold: def.threshold,
          unit: def.unit,
          sopId: 'SOP-GBX-001',
        };
      })
    : [];
  if (commanded) {
    alarms.push({
      id: `${spec.id}-${SAMPLE_LIMIT_NOTE.code}-${commanded.startMs}`,
      turbineId: spec.id,
      code: SAMPLE_LIMIT_NOTE.code,
      severity: SAMPLE_LIMIT_NOTE.severity,
      component: SAMPLE_LIMIT_NOTE.component,
      description: SAMPLE_LIMIT_NOTE.description,
      raisedAt: new Date(commanded.startMs + SAMPLE_CONFIRM_S * 1000).toISOString(),
      value: null,
      threshold: null,
      unit: '',
      sopId: SAMPLE_LIMIT_NOTE.sopId,
    });
  }
  return { live, alarms };
}

export function createSampleProvider(clock: () => number = Date.now): TwinDataProvider {
  const faults: Fault[] = [];
  const limits: Limit[] = [];

  const stateAt = (nowMs: number): LiveState => {
    const all = SITE.turbines.map((_, i) => simulate(i, nowMs, faults, limits));
    const turbines = all.map((one) => one.live);
    const wind = siteWind(nowMs / 1000);
    return {
      source: 'sample',
      route: 'sample',
      asOf: new Date(nowMs).toISOString(),
      turbines,
      alarms: all.flatMap((one) => one.alarms).sort((x, y) => (x.raisedAt < y.raisedAt ? 1 : -1)),
      weather: {
        timestamp: new Date(nowMs).toISOString(),
        windSpeed: wind.speed,
        windDirection: wind.direction,
        windGust: wind.speed * 1.25,
        ambientTemp: turbines[0]?.ambientTemp ?? 20,
        airDensity: 1.11,
      },
      commands: commandLog(limits, nowMs),
    };
  };

  return {
    kind: 'sample',
    getLiveState: async () => stateAt(clock()),
    getTrend: async (turbineId: string, minutes: number): Promise<TrendPoint[]> => {
      const index = SITE.turbines.findIndex((t) => t.id === turbineId);
      if (index < 0) return [];
      const end = Math.floor(clock() / 60000) * 60000;
      const points: TrendPoint[] = [];
      for (let m = Math.max(5, Math.min(360, minutes)); m >= 0; m--) {
        const at = end - m * 60000;
        const { live } = simulate(index, at, faults, limits);
        points.push({
          t: new Date(at).toISOString(), activePower: live.activePower, windSpeed: live.windSpeed, rotorSpeed: live.rotorSpeed,
          gearboxOilTemp: live.gearboxOilTemp, gearboxBearingTemp: live.gearboxBearingTemp, gearboxVibration: live.gearboxVibration,
        });
      }
      return points;
    },
    ask: async (question: string): Promise<AgentAnswer> => {
      await new Promise((resolve) => setTimeout(resolve, 900));
      const now = stateAt(clock());
      const worst = [...now.turbines].sort((a, b) => b.gearboxVibration - a.gearboxVibration)[0];
      const power = now.turbines.reduce((sum, t) => sum + t.activePower, 0) / 1000;
      const text =
        'This is the sample mode of the twin: no data agent is connected, so I can only describe the simulated values on screen.\n\n' +
        `Right now the simulated site produces ${power.toFixed(1)} MW from ${now.turbines.filter((t) => t.activePower > 0).length} turbines. ` +
        `The highest gearbox vibration is on ${worst.id} with ${worst.gearboxVibration.toFixed(1)} mm/s.\n\n` +
        `Deployed in Fabric, this panel sends your question ("${question.slice(0, 120)}") to the data agent WindFarmDataAgent, which answers from the Lakehouse and the KQL database.`;
      return { text, seconds: 0.9 };
    },
    diagnostics: async (): Promise<DiagnosticStep[]> => [
      { step: 'Sample data', ok: true, detail: 'The values are simulated in the browser. Nothing is read from Fabric.' },
    ],
    injectFault: (turbineId: string) => {
      const now = clock();
      const running = faults.find((f) => f.turbineId === turbineId);
      if (running && faultProgress(running, now) >= 0) return;
      for (let i = faults.length - 1; i >= 0; i--) if (faults[i].turbineId === turbineId) faults.splice(i, 1);
      faults.push({ turbineId, startMs: now });
    },
    limitTurbine: (turbineId: string) => {
      const now = clock();
      if (!SITE.turbines.some((t) => t.id === turbineId)) return;
      if (limits.some((l) => l.turbineId === turbineId && now < l.endMs)) return; // one limit at a time
      const requestId = `sample-${now.toString(36)}`;
      limits.push({ turbineId, requestId, startMs: now, endMs: now + SAMPLE_LIMIT_MINUTES * 60_000, percent: SAMPLE_LIMIT_PERCENT });
    },
  };
}
