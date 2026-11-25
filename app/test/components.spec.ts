import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

import { PARTS, componentQuestion, componentStatus, gearboxCondition, partOfAlarm, faultCount, faultsFirst, isFault } from '../overlay/packages/frontend/src/twin/data/components';
import type { Alarm, TurbineLive } from '../overlay/packages/frontend/src/twin/data/contract';
import { createSampleProvider } from '../overlay/packages/frontend/src/twin/data/sampleProvider';
import { WATCH_YAW_ERROR } from '../overlay/packages/frontend/src/twin/data/site';

const here = new URL('.', import.meta.url).pathname;
const start = Date.UTC(2026, 10, 21, 18, 0, 0);

/** One column of a file of the reference data. Cells in double quotes may hold commas. */
function column(file: string, name: string): string[] {
  const cells = (line: string): string[] => [...line.matchAll(/("([^"]*)"|[^,]*)(,|$)/g)].slice(0, -1).map((m) => m[2] ?? m[1]);
  const lines = readFileSync(`${here}../../data/reference/${file}`, 'utf8').trim().split(/\r?\n/);
  const index = cells(lines[0]).indexOf(name);
  expect(index, `${file} has a column ${name}`).toBeGreaterThanOrEqual(0);
  return lines.slice(1).map((line) => cells(line)[index]);
}

const alarm = (over: Partial<Alarm>): Alarm => ({
  id: 'a', turbineId: 'WT-01', code: 'X', severity: 'warning', component: 'gearbox', description: '', raisedAt: new Date(start).toISOString(),
  value: null, threshold: null, unit: '', sopId: '', ...over,
});

async function turbine(id: string): Promise<TurbineLive> {
  const state = await createSampleProvider(() => start).getLiveState();
  return state.turbines.find((t) => t.id === id)!;
}

describe('the components of a turbine', () => {
  it('are the components of the reference data, by code and by name', () => {
    const codes = column('components.csv', 'componentCode');
    const names = column('components.csv', 'componentType');
    const known = new Map(codes.map((code, i) => [code, names[i]]));
    expect([...known.keys()].sort()).toEqual(PARTS.map((p) => p.key).sort());
    for (const part of PARTS) expect(known.get(part.key)).toBe(part.name);
  });

  it('find their alarms by the component name of the alarm catalogue', () => {
    const expected: Record<string, string | null> = {
      gearbox: 'GBX', generator: 'GEN', 'hydraulic system': 'HYD', 'pitch system': 'PIT', tower: 'TWR', 'yaw system': 'YAW', converter: 'CNV', blades: 'BLD',
      controller: null, scada: null, grid: null, environment: null,
    };
    const inCatalogue = [...new Set(column('alarm_codes.csv', 'component'))];
    expect(inCatalogue.sort()).toEqual(Object.keys(expected).sort());
    for (const name of inCatalogue) expect(partOfAlarm({ component: name }), name).toBe(expected[name]);
    expect(partOfAlarm({ component: 'Gearbox' })).toBe('GBX'); // the events table writes it with a capital
    expect(partOfAlarm({ component: '' })).toBeNull();
  });

  it('are all without a mark on a turbine that runs as it should', async () => {
    const status = componentStatus(await turbine('WT-02'), []);
    expect(status.map((s) => s.key)).toEqual(PARTS.map((p) => p.key));
    expect(status.every((s) => s.level === 0 && s.alarms.length === 0)).toBe(true);
    const gearbox = status.find((s) => s.key === 'GBX')!;
    expect(gearbox.values).toHaveLength(4);
    expect(gearbox.values[0]).toMatch(/^\d\.\d mm\/s$/);
    expect(status.find((s) => s.key === 'BLD')!.values).toEqual([]);
    for (const s of status) for (const value of s.values) expect(value).not.toMatch(/NaN|undefined/);
  });

  it('mark the yaw system of the turbine that stands off the wind', async () => {
    const t = await turbine('WT-05');
    expect(Math.abs(t.yawError)).toBeGreaterThan(WATCH_YAW_ERROR);
    const status = componentStatus(t, []);
    expect(status.filter((s) => s.level > 0).map((s) => [s.key, s.level])).toEqual([['YAW', 1]]);
  });

  it('follow the gearbox from the early warning to the alarm', async () => {
    let now = start;
    const provider = createSampleProvider(() => now);
    provider.injectFault?.('WT-03');
    const at = async (seconds: number) => {
      now = start + seconds * 1000;
      const state = await provider.getLiveState();
      return componentStatus(state.turbines.find((t) => t.id === 'WT-03')!, state.alarms).find((s) => s.key === 'GBX')!;
    };
    expect(await at(5)).toMatchObject({ level: 0, alarms: [] });
    expect(await at(30)).toMatchObject({ level: 1, alarms: [] });
    expect(await at(50)).toMatchObject({ level: 2, alarms: ['GBX-VIB-HIGH'] });
    const tripped = await at(170);
    expect(tripped.level).toBe(2);
    expect(tripped.alarms).toContain('GBX-OIL-TEMP-TRIP');

    // Only the gearbox of that turbine is marked, and no part of its neighbour.
    now = start + 120 * 1000;
    const state = await provider.getLiveState();
    const other = componentStatus(state.turbines.find((t) => t.id === 'WT-02')!, state.alarms);
    expect(other.every((s) => s.level === 0)).toBe(true);
    const own = componentStatus(state.turbines.find((t) => t.id === 'WT-03')!, state.alarms);
    expect(own.filter((s) => s.level > 0).map((s) => s.key)).toEqual(['GBX']);
  });

  it('take a warning or a critical alarm as a mark, and an information as none', async () => {
    const t = await turbine('WT-02');
    const level = (a: Alarm, key: string) => componentStatus(t, [a]).find((s) => s.key === key)!.level;
    expect(level(alarm({ turbineId: 'WT-02', component: 'tower', code: 'TWR-VIB-HIGH' }), 'TWR')).toBe(2);
    expect(level(alarm({ turbineId: 'WT-02', component: 'pitch system', severity: 'critical' }), 'PIT')).toBe(2);
    expect(level(alarm({ turbineId: 'WT-02', component: 'yaw system', severity: 'info', code: 'YAW-UNTWIST' }), 'YAW')).toBe(0);
    expect(level(alarm({ turbineId: 'WT-09', component: 'tower' }), 'TWR')).toBe(0);
    expect(componentStatus(t, [alarm({ turbineId: 'WT-02', component: 'controller' })]).every((s) => s.level === 0)).toBe(true);
  });

  it('call the gearbox red only when the controller has an alarm on it, however high one reading is', async () => {
    const healthy = await turbine('WT-02');
    const noisy: TurbineLive = { ...healthy, gearboxVibration: 5.54, gearboxOilTemp: 74.3 }; // the reading of the first deployment
    expect(gearboxCondition(healthy, [])).toBe(0);
    expect(gearboxCondition(noisy, [])).toBe(1);
    expect(componentStatus(noisy, []).find((s) => s.key === 'GBX')!.level).toBe(1);
    const gearboxAlarm = alarm({ turbineId: 'WT-02', component: 'gearbox', code: 'GBX-VIB-HIGH' });
    expect(gearboxCondition(noisy, [gearboxAlarm])).toBe(2);
    expect(gearboxCondition(healthy, [gearboxAlarm])).toBe(2); // the alarm stands until the controller clears it
    // Alarms of another turbine, of another component, or of severity info do not colour this gearbox.
    expect(gearboxCondition(noisy, [alarm({ turbineId: 'WT-09', component: 'gearbox' })])).toBe(1);
    expect(gearboxCondition(noisy, [alarm({ turbineId: 'WT-02', component: 'generator' })])).toBe(1);
    expect(gearboxCondition(noisy, [alarm({ turbineId: 'WT-02', component: 'gearbox', severity: 'info' })])).toBe(1);
  });

  it('count and put first what is wrong, and only list what somebody did', () => {
    // Seen on 25 November 2026: a limit sent by hand raised POWER-CURTAILED, and the top bar showed a red "1".
    const note = alarm({ turbineId: 'WT-07', component: 'controller', severity: 'info', code: 'POWER-CURTAILED' });
    const stop = alarm({ turbineId: 'WT-05', component: 'controller', severity: 'info', code: 'MANUAL-STOP' });
    const warning = alarm({ turbineId: 'WT-03', component: 'gearbox', code: 'GBX-OIL-TEMP-HIGH' });
    const critical = alarm({ turbineId: 'WT-03', component: 'gearbox', severity: 'critical', code: 'GBX-VIB-CRIT' });
    expect([note, stop, warning, critical].map(isFault)).toEqual([false, false, true, true]);
    expect(faultCount([note])).toBe(0);
    expect(faultCount([note, warning, stop, critical])).toBe(2);
    expect(faultCount([])).toBe(0);
    // In a list the notes come after the alarms, so six lines of notes never hide an alarm; each kind keeps its order.
    expect(faultsFirst([note, warning, stop, critical]).map((a) => a.code)).toEqual(['GBX-OIL-TEMP-HIGH', 'GBX-VIB-CRIT', 'POWER-CURTAILED', 'MANUAL-STOP']);
    // A severity the page does not know is not called an alarm either.
    expect(isFault(alarm({ severity: 'notice' }))).toBe(false);
  });

  it('show a dash for a signal the functions do not send yet, and no mark for it', async () => {
    // What a page of this version gets from functions of the first delivery: four signals fewer.
    const { gearboxOilPressure, generatorBearingTemp, transformerTemp, hydraulicPressure, ...older } = await turbine('WT-02');
    expect([gearboxOilPressure, generatorBearingTemp, transformerTemp, hydraulicPressure].every((v) => typeof v === 'number')).toBe(true);
    const status = componentStatus(older as TurbineLive, []);
    const values = (key: string) => status.find((s) => s.key === key)!.values;
    expect(values('TRF')).toEqual(['– °C']);
    expect(values('HYD')).toEqual(['– bar']);
    expect(values('GEN')[1]).toBe('bearing – °C');
    expect(values('GBX')[3]).toBe('– bar');
    expect(values('GBX')[0]).toMatch(/^\d\.\d mm\/s$/);
    expect(status.every((s) => s.level === 0)).toBe(true);
  });

  it('ask the data agent about a component by the name the data uses', () => {
    expect(componentQuestion('WT-07', PARTS.find((p) => p.key === 'HYD')!)).toBe('What stops and work orders has the hydraulic unit of WT-07 had?');
  });
});
