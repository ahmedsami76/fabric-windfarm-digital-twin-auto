import { describe, expect, it } from 'vitest';

import type { DiagnosticStep, LiveState, TrendPoint } from '../overlay/packages/frontend/src/twin/data/contract';
import { fromFunction } from '../overlay/packages/frontend/src/twin/data/functionResult';
import { LAKEHOUSE_POLL_MS, POLL_MS, STALE_AFTER_S, STOPPED_HINT, ageText, freshnessOf, pollDelay } from '../overlay/packages/frontend/src/twin/data/provider';
import { RETRY_EVENTHOUSE_MS, type RouteCalls, chooseRoute } from '../overlay/packages/frontend/src/twin/data/routes';

const state = (route: 'eventhouse' | 'lakehouse'): LiveState => ({ source: 'fabric', route, asOf: '2026-11-23T07:00:00Z', turbines: [], alarms: [], weather: null, commands: null });
const point: TrendPoint = { t: '2026-11-23T07:00:00Z', activePower: 1, windSpeed: 1, rotorSpeed: 1, gearboxOilTemp: 1, gearboxBearingTemp: 1, gearboxVibration: 1 };

/** Two pretend routes. `eventhouse.fail` makes the Eventhouse functions answer with that reason. */
function routes(): { calls: Record<'eventhouse' | 'lakehouse', RouteCalls>; log: string[]; eventhouse: { fail: string | null }; lakehouse: { fail: string | null }; now: { ms: number } } {
  const log: string[] = [];
  const eventhouse = { fail: null as string | null };
  const lakehouse = { fail: null as string | null };
  const make = (name: 'eventhouse' | 'lakehouse', switchOf: { fail: string | null }): RouteCalls => {
    const gate = <T>(what: string, value: T): Promise<T> => {
      log.push(`${name}.${what}`);
      return switchOf.fail ? Promise.reject(new Error(switchOf.fail)) : Promise.resolve(value);
    };
    return {
      live: () => gate('live', state(name)),
      trend: () => gate('trend', [point]),
      check: () => gate('check', [{ step: `${name} route: query`, ok: true, detail: 'fine' }] as DiagnosticStep[]),
    };
  };
  return { calls: { eventhouse: make('eventhouse', eventhouse), lakehouse: make('lakehouse', lakehouse) }, log, eventhouse, lakehouse, now: { ms: 1_000_000 } };
}

describe('which route the live values take', () => {
  it('uses the Eventhouse when it answers, and never asks the Lakehouse', async () => {
    const r = routes();
    const chooser = chooseRoute(r.calls, () => r.now.ms);
    expect((await chooser.live()).route).toBe('eventhouse');
    await chooser.trend('WT-07', 60);
    expect(r.log).toEqual(['eventhouse.live', 'eventhouse.trend']);
    expect(chooser.status()).toEqual({ route: 'eventhouse', eventhouseSaid: null });
  });

  it('falls back to the Lakehouse when the Eventhouse does not answer, and remembers why', async () => {
    const r = routes();
    r.eventhouse.fail = 'No service principal is set up for the Eventhouse: the app has no secret KUSTO_TENANT_ID.';
    const chooser = chooseRoute(r.calls, () => r.now.ms);
    expect((await chooser.live()).route).toBe('lakehouse');
    expect(chooser.status()).toEqual({ route: 'lakehouse', eventhouseSaid: r.eventhouse.fail });
  });

  it('then stays on the Lakehouse for two minutes without asking the Eventhouse again', async () => {
    const r = routes();
    r.eventhouse.fail = 'refused';
    const chooser = chooseRoute(r.calls, () => r.now.ms);
    await chooser.live();
    r.log.length = 0;
    r.now.ms += RETRY_EVENTHOUSE_MS - 1;
    await chooser.live();
    await chooser.trend('WT-07', 60);
    expect(r.log).toEqual(['lakehouse.live', 'lakehouse.trend']);
  });

  it('tries the Eventhouse again after two minutes, and moves back to it when it answers', async () => {
    const r = routes();
    r.eventhouse.fail = 'refused';
    const chooser = chooseRoute(r.calls, () => r.now.ms);
    await chooser.live();
    r.eventhouse.fail = null; // the principal was set up in the meantime
    r.now.ms += RETRY_EVENTHOUSE_MS;
    r.log.length = 0;
    expect((await chooser.live()).route).toBe('eventhouse');
    await chooser.live();
    expect(r.log).toEqual(['eventhouse.live', 'eventhouse.live']);
    expect(chooser.status().route).toBe('eventhouse');
  });

  it('leaves the Eventhouse as soon as it stops answering', async () => {
    const r = routes();
    const chooser = chooseRoute(r.calls, () => r.now.ms);
    await chooser.live();
    r.eventhouse.fail = 'The Eventhouse answered 403';
    expect((await chooser.live()).route).toBe('lakehouse');
  });

  it('says what both routes said when neither answers', async () => {
    const r = routes();
    r.eventhouse.fail = 'no principal.';
    r.lakehouse.fail = 'Login failed.';
    const chooser = chooseRoute(r.calls, () => r.now.ms);
    await expect(chooser.live()).rejects.toThrow('Eventhouse route: no principal. Lakehouse route: Login failed.');
    expect(chooser.status().route).toBeNull();
  });

  it('checks both routes whichever is in use, and turns a check that does not answer into a line', async () => {
    const r = routes();
    r.lakehouse.fail = 'WorkloadException/SomethingRefused: the platform refused the function';
    const steps = await chooseRoute(r.calls, () => r.now.ms).check();
    expect(steps).toEqual([
      { step: 'eventhouse route: query', ok: true, detail: 'fine' },
      { step: 'Lakehouse route: the check itself', ok: false, detail: r.lakehouse.fail },
    ]);
    expect(r.log.sort()).toEqual(['eventhouse.check', 'lakehouse.check']);
  });
});

describe('a function that could not do its work', () => {
  it('arrives as an error with the reason the function gave, as an object or as text', () => {
    expect(() => fromFunction({ error: 'The Eventhouse answered 403: not authorized' }, 'getLiveState')).toThrow('The Eventhouse answered 403: not authorized');
    expect(() => fromFunction('{"error":"No service principal is set up"}', 'getLiveState')).toThrow('No service principal is set up');
  });
  it('is not confused with a result that has a field of that name among others', () => {
    const result = { error: 'none', text: 'answer' };
    expect(fromFunction(result, 'askAgent')).toBe(result);
  });
});

describe('what the page says about the age of its values', () => {
  const seen = (route: 'eventhouse' | 'lakehouse' | 'sample', turbines = 1) => ({ source: route === 'sample' ? 'sample' : 'fabric', route, turbines: new Array<unknown>(turbines).fill(0) });

  it('calls Eventhouse values live for two minutes, then stale', () => {
    expect(freshnessOf(seen('eventhouse'), 5, false)).toBe('live');
    // The one reading from a deployed app was 56 seconds: a working pipeline must not sit at the limit.
    expect(freshnessOf(seen('eventhouse'), 56, false)).toBe('live');
    expect(freshnessOf(seen('eventhouse'), 90, false)).toBe('live');
    expect(STALE_AFTER_S).toBeGreaterThanOrEqual(2 * 56);
    expect(freshnessOf(seen('eventhouse'), STALE_AFTER_S, false)).toBe('live');
    expect(freshnessOf(seen('eventhouse'), STALE_AFTER_S + 1, false)).toBe('stale');
  });
  it('names the stopped edge VM and the commands in the hint of a stale badge', () => {
    for (const part of ['edge VM', 'VM_AUTO_SHUTDOWN_UTC', 'bash infra/vm.sh status', 'bash infra/vm.sh start']) expect(STOPPED_HINT).toContain(part);
    expect(STOPPED_HINT).not.toContain('./infra');
  });
  it('calls Lakehouse values delayed, never live, and stale only after twenty minutes', () => {
    expect(freshnessOf(seen('lakehouse'), 5, false)).toBe('delayed');
    expect(freshnessOf(seen('lakehouse'), 9 * 60, false)).toBe('delayed');
    expect(freshnessOf(seen('lakehouse'), 21 * 60, false)).toBe('stale');
  });
  it('keeps the other states: connecting, sample, no telemetry, not connected', () => {
    expect(freshnessOf(null, null, false)).toBe('loading');
    expect(freshnessOf(null, null, true)).toBe('error');
    expect(freshnessOf(seen('sample'), 0, false)).toBe('sample');
    expect(freshnessOf(seen('lakehouse', 0), null, false)).toBe('silent');
    expect(freshnessOf(seen('eventhouse'), 5, true)).toBe('error');
  });
  it('asks every 5 seconds on the Eventhouse, twice a minute on the Lakehouse, and slower after a failure', () => {
    expect(pollDelay('eventhouse', false)).toBe(POLL_MS);
    expect(pollDelay('sample', false)).toBe(POLL_MS);
    expect(pollDelay('lakehouse', false)).toBe(LAKEHOUSE_POLL_MS);
    expect(pollDelay(undefined, true)).toBe(POLL_MS * 3);
  });
  it('gives an age in seconds up to two minutes, then in minutes', () => {
    expect([ageText(45), ageText(120), ageText(121), ageText(7 * 60 + 20), ageText(null)]).toEqual(['45 s', '120 s', '2 min', '7 min', 'age unknown']);
  });
});
