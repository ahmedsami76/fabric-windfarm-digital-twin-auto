import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import type { LiveState } from '../overlay/packages/frontend/src/twin/data/contract';
import { sampleRequested } from '../overlay/packages/frontend/src/twin/data/provider';
import { SAMPLE_ALARMS, createSampleProvider } from '../overlay/packages/frontend/src/twin/data/sampleProvider';
import { ALARM_OIL_TEMP, ALARM_VIBRATION, EARLY_OIL_TEMP, SITE, gearboxWatch, groundAt, powerCurve } from '../overlay/packages/frontend/src/twin/data/site';
import { gearboxCondition } from '../overlay/packages/frontend/src/twin/data/components';
import { VERTICAL_SCALE, elevationAt, heightAt } from '../overlay/packages/frontend/src/twin/scene/terrain';
import { downwind, yawFor } from '../overlay/packages/frontend/src/twin/scene/turbine';

const here = new URL('.', import.meta.url).pathname;

/** A CSV file as objects. Cells in double quotes may hold commas. */
function readCsv(file: string): Record<string, string>[] {
  const cells = (line: string): string[] => [...line.matchAll(/("([^"]*)"|[^,]*)(,|$)/g)].slice(0, -1).map((m) => m[2] ?? m[1]);
  const lines = readFileSync(file, 'utf8').trim().split(/\r?\n/);
  const columns = cells(lines[0]);
  return lines.slice(1).map((line) => Object.fromEntries(cells(line).map((cell, i) => [columns[i], cell])));
}

describe('the contract', () => {
  it('is the same file in the frontend and in the functions', () => {
    const frontend = readFileSync(`${here}../overlay/packages/frontend/src/twin/data/contract.ts`, 'utf8');
    const functions = readFileSync(`${here}../overlay/packages/functions/src/contract.ts`, 'utf8');
    expect(frontend).toBe(functions);
    expect(frontend).not.toMatch(/^import /m);
  });
});

describe('the site data', () => {
  it('holds twelve turbines of the model, three places and the roads', () => {
    expect(SITE.turbines.map((t) => t.id)).toEqual(Array.from({ length: 12 }, (_, i) => `WT-${String(i + 1).padStart(2, '0')}`));
    expect(SITE.infrastructure.map((p) => p.type).sort()).toEqual(['Building', 'MetMast', 'Substation']);
    expect(SITE.roads.length).toBeGreaterThan(10);
    expect(SITE.turbineModel.ratedPowerKw * SITE.turbines.length).toBeCloseTo(SITE.site.capacityMw * 1000, 0);
  });

  it('puts every turbine on the ground of the heightmap', () => {
    for (const t of SITE.turbines) expect(Math.abs(groundAt(t.x, t.y) - t.elevationM)).toBeLessThan(1);
  });

  it('has a power curve from cut-in to rated power', () => {
    const m = SITE.turbineModel;
    expect(powerCurve(m.cutInWindSpeed - 0.1)).toBe(0);
    expect(powerCurve(m.ratedWindSpeed)).toBe(m.ratedPowerKw);
    expect(powerCurve(m.cutOutWindSpeed)).toBe(0);
    expect(powerCurve(8)).toBeGreaterThan(powerCurve(7));
  });

  it('marks the gearbox from the early warning of the operations agent on, and never calls a reading an alarm', () => {
    expect(gearboxWatch(2.0, 60)).toBe(0);
    expect(gearboxWatch(4.0, 60)).toBe(1);
    expect(gearboxWatch(2.0, 72)).toBe(1);
    // At and above the controller's limits the readings still say "watch": the controller decides on the alarm.
    expect(gearboxWatch(ALARM_VIBRATION, 60)).toBe(1);
    expect(gearboxWatch(5.94, 60)).toBe(1); // the highest single reading of a fault of severity 0.2 in the simulator
    expect(gearboxWatch(2.0, ALARM_OIL_TEMP)).toBe(1);
  });
});

describe('the ground', () => {
  it('is level around a turbine and at the height of its base', () => {
    for (const t of SITE.turbines) {
      const base = heightAt(t.x, t.y);
      expect(base).toBeCloseTo((groundAt(t.x, t.y) - SITE.terrain.minElevationM) * VERTICAL_SCALE, 5);
      for (const [dx, dy] of [[25, 0], [0, -25], [-18, 18]]) expect(Math.abs(heightAt(t.x + dx, t.y + dy) - base)).toBeLessThan(0.01);
    }
  });

  it('joins the site to the country around it without a step', () => {
    const half = SITE.terrain.sizeM / 2;
    for (const y of [-2000, 0, 1500]) expect(Math.abs(elevationAt(half + 1, y) - elevationAt(half - 1, y))).toBeLessThan(1.5);
  });
});

describe('directions', () => {
  it('turns a nacelle to face the wind', () => {
    // A nacelle looks along +z of its group. Turned for wind from the north it must look north, which is -z.
    const facing = (deg: number) => ({ x: Math.sin(yawFor(deg)), z: Math.cos(yawFor(deg)) });
    expect(facing(0).z).toBeCloseTo(-1);
    expect(facing(90).x).toBeCloseTo(1);
    expect(facing(180).z).toBeCloseTo(1);
  });

  it('blows the streaks away from where the wind comes from', () => {
    expect(downwind(0).z).toBeCloseTo(1); // from the north, to the south
    expect(downwind(270).x).toBeCloseTo(1); // from the west, to the east
  });
});

describe('the sample data', () => {
  const start = Date.UTC(2026, 10, 21, 18, 0, 0);

  it('gives twelve running turbines with plausible values, the same for the same time', async () => {
    const a = await createSampleProvider(() => start).getLiveState();
    const b = await createSampleProvider(() => start).getLiveState();
    expect(a).toEqual(b);
    expect(a.source).toBe('sample');
    expect(a.turbines).toHaveLength(12);
    for (const t of a.turbines) {
      expect(t.activePower).toBeGreaterThanOrEqual(0);
      expect(t.activePower).toBeLessThanOrEqual(SITE.turbineModel.ratedPowerKw * 1.03);
      expect(t.rotorSpeed).toBeLessThanOrEqual(SITE.turbineModel.ratedRotorRpm);
      expect(t.gearboxVibration).toBeLessThan(ALARM_VIBRATION);
    }
    expect(a.alarms).toEqual([]);
  });

  it('shows the three standing conditions', async () => {
    const state = await createSampleProvider(() => start).getLiveState();
    const by = (id: string) => state.turbines.find((t) => t.id === id)!;
    expect(by('WT-05').yawError).toBeGreaterThan(6);
    expect(by('WT-07').gearboxVibration - by('WT-06').gearboxVibration).toBeGreaterThan(0.5);
    expect(Math.abs(by('WT-05').windDirection - by('WT-05').nacelleDirection)).toBeGreaterThan(6);
  });

  it('gives every signal the twin shows a value in the range of the edge simulator', async () => {
    const state = await createSampleProvider(() => start).getLiveState();
    for (const t of state.turbines) {
      expect(t.gearboxOilPressure).toBeGreaterThan(2.8);
      expect(t.gearboxOilPressure).toBeLessThan(3.4);
      expect(t.hydraulicPressure).toBeGreaterThan(182);
      expect(t.hydraulicPressure).toBeLessThan(190);
      expect(t.gearboxOilTemp).toBeLessThan(EARLY_OIL_TEMP);
      expect(t.gearboxBearingTemp).toBeGreaterThan(t.gearboxOilTemp);
      expect(t.generatorWindingTemp).toBeGreaterThan(t.generatorBearingTemp);
      for (const warm of [t.generatorBearingTemp, t.mainBearingTemp, t.transformerTemp]) expect(warm).toBeGreaterThan(t.ambientTemp + 5);
      expect(t.generatorWindingTemp).toBeLessThan(125); // the level of the first generator alarm
      expect(t.towerVibration).toBeLessThan(2.5); // the level of the tower alarm
    }
  });

  it('raises the gearbox alarms as the alarm catalogue of the reference data defines them', () => {
    const rows = readCsv(`${here}../../data/reference/alarm_codes.csv`);
    const catalogue = new Map(rows.map((row) => [row.alarmCode, row]));
    expect(SAMPLE_ALARMS.length).toBe(5);
    expect(Number(catalogue.get('GBX-VIB-HIGH')!.threshold)).toBe(ALARM_VIBRATION);
    expect(Number(catalogue.get('GBX-OIL-TEMP-HIGH')!.threshold)).toBe(ALARM_OIL_TEMP);
    for (const alarm of SAMPLE_ALARMS) {
      const row = catalogue.get(alarm.code);
      expect(row, alarm.code).toBeDefined();
      expect(row!.component).toBe('gearbox');
      expect(row!.severity).toBe(alarm.severity);
      expect(Number(row!.threshold)).toBe(alarm.threshold);
      expect(row!.unit).toBe(alarm.unit);
      expect(row!.signal).toBe(alarm.signal === 'oil' ? 'gearboxOilTemp' : 'gearboxVibration');
      expect(row!.sopId).toBe('SOP-GBX-001');
      expect(row!.description).toBe(alarm.description);
      expect(row!.controllerAction).toBe(alarm.derateTo < 1 ? `derate to ${alarm.derateTo * 100}%` : alarm.code.endsWith('-TRIP') ? 'stop turbine' : '');
      expect(alarm.clearBelow).toBeLessThan(alarm.threshold);
    }
  });

  it('runs a gearbox fault through the alarms, the derate, the trip and the restart', async () => {
    const rated = SITE.turbineModel.ratedPowerKw;
    const turbine = (s: LiveState) => s.turbines.find((t) => t.id === 'WT-03')!;
    const codes = (s: LiveState) => s.alarms.map((a) => a.code).sort();
    // A time of day with wind enough for the limit of the derate to hold the turbine back.
    let windy = start;
    for (;;) {
      const moments = await Promise.all([0, 120, 225].map((after) => createSampleProvider(() => windy + after * 1000).getLiveState()));
      if (moments.every((m) => turbine(m).activePower > rated * 0.6)) break;
      windy += 600_000;
      expect(windy - start).toBeLessThan(86_400_000);
    }
    let now = windy;
    const provider = createSampleProvider(() => now);
    provider.injectFault?.('WT-03');
    const at = async (seconds: number): Promise<LiveState> => {
      now = windy + seconds * 1000;
      return provider.getLiveState();
    };

    const early = await at(30);
    expect(turbine(early).state).toBe('RUNNING');
    expect(gearboxCondition(turbine(early), early.alarms)).toBe(1);
    expect(early.alarms).toEqual([]);

    const warned = await at(50);
    expect(turbine(warned).state).toBe('RUNNING');
    expect(turbine(warned).gearboxVibration).toBeGreaterThan(ALARM_VIBRATION);
    expect(codes(warned)).toEqual(['GBX-VIB-HIGH']);
    expect(warned.alarms[0].severity).toBe('warning');
    expect(gearboxCondition(turbine(warned), warned.alarms)).toBe(2); // red while it runs: the controller has an alarm
    expect(gearboxCondition(turbine(warned), [])).toBe(1); // the same readings without the alarm are amber

    const derated = await at(120);
    expect(turbine(derated).state).toBe('DERATED');
    expect(turbine(derated).gearboxVibration).toBeGreaterThan(8);
    expect(turbine(derated).powerSetpoint).toBeCloseTo(rated * 0.3, 6);
    expect(turbine(derated).activePower).toBeLessThanOrEqual(rated * 0.3 * 1.02);
    expect(turbine(derated).activePower).toBeGreaterThan(rated * 0.3 * 0.98);
    expect(turbine(derated).pitchAngle).toBeGreaterThan(5);
    expect(codes(derated)).toEqual(['GBX-OIL-TEMP-CRIT', 'GBX-OIL-TEMP-HIGH', 'GBX-VIB-CRIT', 'GBX-VIB-HIGH']);
    expect(derated.alarms.every((a) => a.turbineId === 'WT-03' && a.component === 'gearbox')).toBe(true);
    // Newest first, and each alarm carries the value that raised it.
    expect(derated.alarms.map((a) => a.raisedAt)).toEqual([...derated.alarms.map((a) => a.raisedAt)].sort().reverse());
    for (const a of derated.alarms) expect(a.value!).toBeGreaterThanOrEqual(a.threshold!);

    const tripped = await at(170);
    expect(turbine(tripped).state).toBe('FAULT');
    expect(turbine(tripped).activePower).toBe(0);
    expect(turbine(tripped).rotorSpeed).toBe(0);
    expect(turbine(tripped).gearboxVibration).toBeLessThan(1); // a gearbox that stands does not vibrate
    expect(turbine(tripped).gearboxOilTemp).toBeGreaterThan(88);
    expect(turbine(tripped).generatorWindingTemp).toBeGreaterThan(turbine(tripped).ambientTemp + 20); // still warm
    expect(codes(tripped)).toEqual(['GBX-OIL-TEMP-CRIT', 'GBX-OIL-TEMP-HIGH', 'GBX-OIL-TEMP-TRIP']);
    expect(gearboxCondition(turbine(tripped), tripped.alarms)).toBe(2); // red by the oil alarms alone

    const restarted = await at(225);
    expect(turbine(restarted).state).toBe('RUNNING');
    expect(turbine(restarted).activePower).toBeGreaterThan(rated * 0.6);
    expect(codes(restarted)).toEqual(['GBX-OIL-TEMP-HIGH']);

    const over = await at(320);
    expect(turbine(over).state).toBe('RUNNING');
    expect(over.alarms).toEqual([]);
    expect(over.turbines.filter((t) => t.state !== 'RUNNING')).toEqual([]);
  });

  it('changes no value by more than a step when the turbine trips or restarts, except what the stop itself changes', async () => {
    let now = start;
    const provider = createSampleProvider(() => now);
    provider.injectFault?.('WT-03');
    const at = async (seconds: number) => {
      now = start + seconds * 1000;
      return (await provider.getLiveState()).turbines.find((t) => t.id === 'WT-03')!;
    };
    for (const moment of [150, 215]) {
      const before = await at(moment - 0.5);
      const after = await at(moment + 0.5);
      for (const key of ['gearboxOilTemp', 'generatorWindingTemp', 'generatorBearingTemp', 'mainBearingTemp', 'transformerTemp'] as const) {
        expect(Math.abs(after[key] - before[key]), `${key} at ${moment} s`).toBeLessThan(2.5);
      }
    }
  });

  it('gives a trend of one point a minute', async () => {
    const trend = await createSampleProvider(() => start).getTrend('WT-07', 60);
    expect(trend).toHaveLength(61);
    expect(new Date(trend[1].t).getTime() - new Date(trend[0].t).getTime()).toBe(60000);
    expect(await createSampleProvider(() => start).getTrend('WT-99', 60)).toEqual([]);
  });
});

describe('the sample switch', () => {
  it('reads ?sample from the address', () => {
    expect(sampleRequested('?sample')).toBe(true);
    expect(sampleRequested('?sample=1')).toBe(true);
    expect(sampleRequested('?sample=0')).toBe(false);
    expect(sampleRequested('')).toBe(false);
  });
});

describe('what a function returned', () => {
  it('takes the object the Rayfin client has already parsed', async () => {
    const { fromFunction } = await import('../overlay/packages/frontend/src/twin/data/functionResult');
    const steps = [{ step: 'Token for the Fabric API', ok: true, detail: 'supplied by the host' }];
    expect(fromFunction(steps, 'getDiagnostics')).toBe(steps);
    expect(fromFunction({ source: 'fabric' }, 'getLiveState')).toEqual({ source: 'fabric' });
  });
  it('parses JSON text, for a client that hands the text over', async () => {
    const { fromFunction } = await import('../overlay/packages/frontend/src/twin/data/functionResult');
    expect(fromFunction('[{"step":"a","ok":false,"detail":"b"}]', 'getDiagnostics')).toEqual([{ step: 'a', ok: false, detail: 'b' }]);
  });
  it('says what it got when that is neither', async () => {
    const { fromFunction } = await import('../overlay/packages/frontend/src/twin/data/functionResult');
    expect(() => fromFunction('Service Unavailable', 'askAgent')).toThrow(/did not return JSON. It returned: Service Unavailable/);
    expect(() => fromFunction(undefined, 'getLiveState')).toThrow(/returned nothing/);
    expect(() => fromFunction(42, 'getLiveState')).toThrow(/returned 42/);
  });
});
