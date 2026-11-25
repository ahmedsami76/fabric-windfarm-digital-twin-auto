import { describe, expect, it } from 'vitest';

import { askedBy, commandWords, groupCommands, groupTarget, limitInForce, limitOf, limitText, statusLevel } from '../overlay/packages/frontend/src/twin/data/commands';
import type { Alarm, CommandEntry, TurbineLive } from '../overlay/packages/frontend/src/twin/data/contract';
import { readFileSync } from 'node:fs';

import { faultCount } from '../overlay/packages/frontend/src/twin/data/components';
import { SAMPLE_CONFIRM_S, SAMPLE_LIMIT_MINUTES, SAMPLE_LIMIT_NOTE, SAMPLE_LIMIT_PERCENT, SAMPLE_REQUESTER, createSampleProvider } from '../overlay/packages/frontend/src/twin/data/sampleProvider';
import { SITE } from '../overlay/packages/frontend/src/twin/data/site';

const RATED = SITE.turbineModel.ratedPowerKw;
const AGENT = 'operations agent WindFarmGearboxWatch, approved in Teams';
const T0 = Date.parse('2026-11-25T04:12:07Z');
const iso = (ms: number): string => new Date(ms).toISOString();
const clock = (text: string): string => text.slice(11, 16);

const entry = (over: Partial<CommandEntry> = {}): CommandEntry => ({
  requestId: 'a1b2c3d4e5f6', turbineId: 'WT-03', command: 'curtail', status: 'in force', at: iso(T0), requestedBy: AGENT, origin: 'cloud',
  limitKw: 1260, percent: 30, endsAt: iso(T0 + 3600_000), confirmedAt: iso(T0 + 4000), endedAt: '', error: '', ...over,
});
const turbine = (over: Partial<TurbineLive> = {}): TurbineLive => ({ id: 'WT-03', state: 'CURTAILED', powerSetpoint: 1260, activePower: 1255, ...over }) as TurbineLive;
const derateAlarm: Alarm = { id: 'x', turbineId: 'WT-03', code: 'GBX-VIB-CRIT', severity: 'critical', component: 'gearbox', description: 'Gearbox vibration critical, power derated to 30%', raisedAt: iso(T0), value: 8.2, threshold: 8, unit: 'mm/s', sopId: '' };

describe('what holds a turbine below its rated power', () => {
  it('is nothing while the setpoint is the rated power', () => {
    expect(limitOf(turbine({ state: 'RUNNING', powerSetpoint: RATED }), [], RATED)).toBeNull();
    expect(limitOf(undefined, [entry()], RATED)).toBeNull();
    // A limit of an hour ago that has ended explains nothing about now.
    expect(limitOf(turbine({ state: 'RUNNING', powerSetpoint: RATED }), [entry({ status: 'ended', endedAt: iso(T0 + 60_000) })], RATED)).toBeNull();
  });

  it('is the command the log has for it, with who asked, since when, until when and the confirmation', () => {
    const view = limitOf(turbine(), [entry()], RATED)!;
    expect(view).toMatchObject({ kind: 'command', limitKw: 1260 });
    expect(Math.round(view.percent)).toBe(30);
    expect(limitText(view, T0 + 23 * 60_000, clock, 'eventhouse')).toEqual({
      title: 'Limited: 1,260 kW · 30 % of rated',
      lines: [`Asked by ${AGENT}`, 'Since 04:12 · ends 05:12, in 37 min', 'Confirmed by the telemetry 4 s after the edge took the command'],
    });
    // In a weak wind the turbine gives less than the limit: said, because the power then tells nothing.
    expect(limitText(view, T0, clock, 'eventhouse', 1255).lines).toHaveLength(3);
    expect(limitText(view, T0, clock, 'eventhouse', 910).lines[3]).toBe('The wind gives less than the limit right now, so the power is not held down.');
    // Without an end, and after its time.
    expect(limitText(limitOf(turbine(), [entry({ endsAt: '' })], RATED)!, T0, clock, 'eventhouse').lines[1]).toBe('Since 04:12 · until it is released');
    expect(limitText(view, T0 + 3601_000, clock, 'eventhouse').lines[1]).toBe('Since 04:12 · its time ended 05:12');
    // The turbine may stand or have tripped: the limit is still the command's.
    expect(limitOf(turbine({ state: 'IDLE', activePower: 0 }), [entry()], RATED)!.kind).toBe('command');
    expect(limitOf(turbine({ state: 'FAULT', activePower: 0 }), [entry()], RATED)!.kind).toBe('command');
  });

  it('is on its way while the edge has the command and the telemetry does not show it', () => {
    const pending = entry({ status: 'taken by the edge, not yet seen in telemetry', confirmedAt: '' });
    const view = limitOf(turbine({ state: 'RUNNING', powerSetpoint: RATED }), [pending], RATED)!;
    expect(view).toMatchObject({ kind: 'pending', limitKw: 1260 });
    const said = limitText(view, T0 + 3000, clock, 'eventhouse');
    expect(said.title).toBe('Limit on its way: 1,260 kW · 30 % of rated');
    expect(said.lines).toEqual([`Asked by ${AGENT}`, 'The edge took the command at 04:12. The telemetry does not show it yet.']);
  });

  it("is the turbine controller's own doing when that holds the turbine lower, or when no command set a limit", () => {
    // A derate on an alarm, no command.
    const alone = limitOf(turbine({ state: 'DERATED', powerSetpoint: 1260 }), [], RATED)!;
    expect(alone).toMatchObject({ kind: 'controller', entry: null });
    expect(limitText(alone, T0, clock, 'eventhouse').lines).toEqual(['By the turbine controller itself: it lowers the power while one of its alarms is active.']);
    // The same on the Lakehouse route, where the log cannot be read: the state says enough.
    expect(limitOf(turbine({ state: 'DERATED', powerSetpoint: 1260 }), null, RATED)!.kind).toBe('controller');
    // A derated turbine that stands for lack of wind reads IDLE; its alarm still tells.
    expect(limitOf(turbine({ state: 'IDLE', powerSetpoint: 1260 }), [], RATED, [derateAlarm])!.kind).toBe('controller');
    // A command's limit of 50 % and a derate to 30 %: the lower one is the controller's, and the command's holds besides.
    const both = limitOf(turbine({ state: 'DERATED', powerSetpoint: 1260 }), [entry({ limitKw: 2100, percent: 50 })], RATED)!;
    expect(both.kind).toBe('controller');
    expect(limitText(both, T0 + 60_000, clock, 'eventhouse').lines[1]).toBe(`A limit of 2,100 kW asked by ${AGENT} also holds, ends 05:12, in 59 min.`);
  });

  it('says so when a limit is set and nothing tells who asked for it', () => {
    const noLine = limitOf(turbine(), [], RATED)!;
    expect(noLine.kind).toBe('unexplained');
    expect(limitText(noLine, T0, clock, 'eventhouse').lines[0]).toMatch(/the command log has no line for it/);
    const noLog = limitOf(turbine(), null, RATED)!;
    expect(noLog.kind).toBe('unknown');
    expect(limitText(noLog, T0, clock, 'lakehouse').lines[0]).toMatch(/read on the Eventhouse route only/);
    expect(limitText(noLog, T0, clock, 'eventhouse').lines[0]).toMatch(/this KQL database has no command log \(Phase 5c\)/);
    // Another turbine's limit explains nothing here.
    expect(limitOf(turbine(), [entry({ turbineId: 'WT-04' })], RATED)!.kind).toBe('unexplained');
  });

  it('takes the newest limit when the log has more than one in force', () => {
    const older = entry({ requestId: 'old', at: iso(T0 - 600_000), limitKw: 2100, percent: 50 });
    expect(limitInForce([older, entry()], 'WT-03')!.requestId).toBe('a1b2c3d4e5f6');
    expect(limitInForce([entry(), older], 'WT-03')!.requestId).toBe('a1b2c3d4e5f6');
    expect(limitInForce([entry({ command: 'stop' }), entry({ status: 'ended' }), entry({ status: 'refused' })], 'WT-03')).toBeNull();
    expect(limitInForce(null, 'WT-03')).toBeNull();
  });
});

describe('a command in words', () => {
  it('names what was asked and who asked', () => {
    expect(commandWords(entry())).toBe('Limit to 30 % · 1,260 kW');
    expect(['release', 'stop', 'start', 'reset', 'other'].map((command) => commandWords(entry({ command })))).toEqual(['Limit lifted', 'Stop', 'Start', 'Reset', 'other']);
    expect(commandWords(entry({ limitKw: null, percent: null }))).toBe('Limit'); // a refused curtailment carries no numbers
    expect(askedBy(entry())).toBe(AGENT);
    expect(askedBy(entry({ requestedBy: '', origin: 'edge' }))).toBe('someone at the edge, with the simulator tool');
    expect(askedBy(entry({ requestedBy: '' }))).toBe('a sender that gave no name');
  });

  it('marks what is still open and what went wrong', () => {
    expect(['confirmed', 'ended', 'in force', 'taken by the edge, not yet seen in telemetry', 'taken by the edge, never seen in telemetry', 'refused'].map(statusLevel)).toEqual([0, 0, 1, 1, 2, 2]);
  });

  it('shows a command to all turbines as one line, newest first', () => {
    const all = SITE.turbines.map((t, i) => entry({ requestId: 'all-1', turbineId: t.id, at: iso(T0 + 60_000), status: i === 4 ? 'ended' : 'in force' }));
    const refused = entry({ requestId: 'bad', turbineId: 'EDGE-01', status: 'refused', at: iso(T0 + 120_000), limitKw: null, percent: null, error: "unknown turbine 'WT-99'" });
    const atEdge = [entry({ requestId: '', command: 'stop', turbineId: 'WT-08', origin: 'edge', requestedBy: '', at: iso(T0 - 5000), status: 'confirmed' }),
      entry({ requestId: '', command: 'stop', turbineId: 'WT-09', origin: 'edge', requestedBy: '', at: iso(T0 - 5000), status: 'confirmed' })];
    const groups = groupCommands([...all, entry(), refused, ...atEdge]);
    expect(groups.map((g) => groupTarget(g, 12))).toEqual(['No turbine', 'All 12 turbines', 'WT-03', 'WT-08', 'WT-09']);
    expect(groups[1].status).toBe('in force on 11, ended on 1');
    expect(groups.map((g) => g.level)).toEqual([2, 1, 1, 0, 0]);
    expect(groupTarget({ ...groups[1], turbines: ['WT-01', 'WT-02', 'WT-03', 'WT-04'] }, 12)).toBe('4 turbines');
    expect(groupCommands([])).toEqual([]);
  });
});

describe('the sample data', () => {
  it('limits a turbine as an approved command does: taken, shown by the telemetry, in force, ended', async () => {
    let now = Date.parse('2026-11-25T04:00:00Z');
    const provider = createSampleProvider(() => now);
    const one = async () => {
      const state = await provider.getLiveState();
      return { turbine: state.turbines.find((t) => t.id === 'WT-03')!, commands: state.commands!, state };
    };
    expect((await one()).commands).toEqual([]);
    const before = (await one()).turbine;
    expect(before.powerSetpoint).toBe(RATED);

    provider.limitTurbine!('WT-03');
    now += 2000; // the edge has it, the telemetry does not show it yet
    let { turbine: t, commands } = await one();
    expect(commands).toHaveLength(1);
    expect(commands[0]).toMatchObject({ turbineId: 'WT-03', command: 'curtail', status: 'taken by the edge, not yet seen in telemetry', requestedBy: SAMPLE_REQUESTER, origin: 'cloud', percent: SAMPLE_LIMIT_PERCENT, confirmedAt: '', endedAt: '' });
    expect(commands[0].limitKw).toBe((RATED * SAMPLE_LIMIT_PERCENT) / 100);
    expect(t.powerSetpoint).toBe(RATED);
    expect(limitOf(t, commands, RATED)!.kind).toBe('pending');

    now += SAMPLE_CONFIRM_S * 1000;
    ({ turbine: t, commands } = await one());
    expect(commands[0].status).toBe('in force');
    expect(t.state).toBe('CURTAILED');
    expect(t.powerSetpoint).toBe(1260);
    expect(t.activePower).toBeLessThanOrEqual(1260);
    expect(limitOf(t, commands, RATED)!.kind).toBe('command');
    expect(new Date(commands[0].endsAt).getTime() - new Date(commands[0].at).getTime()).toBe(SAMPLE_LIMIT_MINUTES * 60_000);
    // The controller says so too, as the edge simulator does: a note, listed for the turbine and not counted as an alarm.
    const notes = (await one()).state.alarms;
    expect(notes.map((a) => `${a.turbineId} ${a.code} ${a.severity}`)).toEqual(['WT-03 POWER-CURTAILED info']);
    expect(faultCount(notes)).toBe(0);
    const row = readFileSync(new URL('../../data/reference/alarm_codes.csv', import.meta.url), 'utf8').split(/\r?\n/).find((line) => line.startsWith('POWER-CURTAILED,'))!.split(',');
    expect(row.slice(0, 4)).toEqual([SAMPLE_LIMIT_NOTE.code, SAMPLE_LIMIT_NOTE.component, SAMPLE_LIMIT_NOTE.severity, SAMPLE_LIMIT_NOTE.description]);
    expect(row).toContain(SAMPLE_LIMIT_NOTE.sopId);
    // The other turbines are as they were, and a second press changes nothing while the limit holds.
    const others = (await one()).state.turbines.filter((x) => x.id !== 'WT-03');
    expect(others.every((x) => x.powerSetpoint === RATED && x.state !== 'CURTAILED')).toBe(true);
    provider.limitTurbine!('WT-03');
    provider.limitTurbine!('WT-99');
    expect((await one()).commands).toHaveLength(1);

    now += SAMPLE_LIMIT_MINUTES * 60_000;
    ({ turbine: t, commands } = await one());
    expect(commands[0]).toMatchObject({ status: 'ended', endedAt: commands[0].endsAt });
    expect(t.powerSetpoint).toBe(RATED);
    expect(t.state).not.toBe('CURTAILED');
    expect(limitOf(t, commands, RATED)).toBeNull();
    expect((await one()).state.alarms).toEqual([]); // the note goes with the limit
    // The trend of the last minutes shows the dip.
    const trend = await provider.getTrend('WT-03', 10);
    expect(Math.min(...trend.map((p) => p.activePower))).toBeLessThanOrEqual(1260);
    // A new limit after the first: two lines, newest first.
    provider.limitTurbine!('WT-03');
    now += 10_000;
    expect((await one()).commands.map((c) => c.status)).toEqual(['in force', 'ended']);
  });

  it('lets the controller hold a limited turbine lower when it derates on an alarm', async () => {
    let now = Date.parse('2026-11-25T04:00:00Z');
    const provider = createSampleProvider(() => now);
    provider.limitTurbine!('WT-07');
    provider.injectFault!('WT-07');
    now += 108_000; // the fault at its height: vibration critical, derated to 30 %
    const state = await provider.getLiveState();
    const t = state.turbines.find((x) => x.id === 'WT-07')!;
    expect(t.state).toBe('DERATED');
    expect(t.powerSetpoint).toBe(1260);
    // Both ask for 30 %: the limit is the command's as much as the controller's, and the log explains it.
    expect(limitOf(t, state.commands, RATED, state.alarms)!.kind).toBe('command');
  });
});
