/**
 * What the twin says about commands: who limited a turbine, since when and until when, and whether the
 * plant followed. The facts come from the edge's command log (`CommandEntry`, Phase 5c) and from the
 * power setpoint in the telemetry. This file only turns them into words; it sends nothing.
 */
import type { Alarm, CommandEntry, TurbineLive } from './contract';

const NOT_YET = 'taken by the edge, not yet seen in telemetry';

const kw = (value: number): string => Math.round(value).toLocaleString('en-US');

/**
 * The limit a command holds on a turbine now, if the log has one: the newest curtailment that is in
 * force, or that the edge has just taken and the telemetry does not show yet.
 */
export function limitInForce(commands: CommandEntry[] | null, turbineId: string): CommandEntry | null {
  const mine = (commands ?? []).filter((c) => c.turbineId === turbineId && c.command === 'curtail' && (c.status === 'in force' || c.status === NOT_YET));
  return mine.reduce<CommandEntry | null>((newest, c) => (newest === null || c.at > newest.at ? c : newest), null);
}

/** Who asked for a command, in words. */
export function askedBy(entry: CommandEntry): string {
  if (entry.requestedBy) return entry.requestedBy;
  return entry.origin === 'edge' ? 'someone at the edge, with the simulator tool' : 'a sender that gave no name';
}

/** A command in a few words: what it asked of the turbine. */
export function commandWords(entry: CommandEntry): string {
  switch (entry.command) {
    case 'curtail':
      return entry.percent !== null && entry.limitKw !== null ? `Limit to ${Math.round(entry.percent)} % · ${kw(entry.limitKw)} kW` : 'Limit';
    case 'release':
      return 'Limit lifted';
    case 'stop':
      return 'Stop';
    case 'start':
      return 'Start';
    case 'reset':
      return 'Reset';
    default:
      return entry.command;
  }
}

/** How serious a status is for the eye: 0 settled, 1 still open, 2 refused or lost. */
export function statusLevel(status: string): 0 | 1 | 2 {
  if (status === 'refused' || status.includes('never seen')) return 2;
  if (status === 'in force' || status === NOT_YET) return 1;
  return 0;
}

export interface LimitView {
  /** What the turbine may produce now, in kW and as a share of rated power. */
  limitKw: number;
  percent: number;
  /** The command behind it, when the log has one. */
  entry: CommandEntry | null;
  /**
   * `command`      a command set the limit and the telemetry shows it.
   * `pending`      the edge took a command; the telemetry does not show it yet.
   * `controller`   the turbine controller holds the turbine down by itself: a derate on an alarm.
   * `unexplained`  a limit is set and the log has no line for it.
   * `unknown`      a limit is set and the log cannot be read on this route.
   */
  kind: 'command' | 'pending' | 'controller' | 'unexplained' | 'unknown';
}

/**
 * What holds a turbine below its rated power, or null when nothing does. The setpoint in the telemetry is
 * the lower of two things: what the turbine controller allows by itself and what a command asked for.
 */
export function limitOf(turbine: TurbineLive | undefined, commands: CommandEntry[] | null, ratedKw: number, alarms: Alarm[] = []): LimitView | null {
  if (!turbine) return null;
  const entry = limitInForce(commands, turbine.id);
  const setpoint = turbine.powerSetpoint;
  const limited = setpoint < ratedKw - 1;
  if (!limited) {
    // Nothing shows in the telemetry. A command the edge has just taken is still worth a line.
    if (entry && entry.status === NOT_YET && entry.limitKw !== null) {
      return { limitKw: entry.limitKw, percent: (entry.limitKw / ratedKw) * 100, entry, kind: 'pending' };
    }
    return null;
  }
  const view = { limitKw: setpoint, percent: (setpoint / ratedKw) * 100 };
  if (entry && entry.limitKw !== null && setpoint >= entry.limitKw - 1) {
    return { ...view, entry, kind: entry.status === NOT_YET ? 'pending' : 'command' };
  }
  // Lower than any command asked for: the controller's own doing. A command's limit may hold besides.
  // The state alone does not always tell: a derated turbine that stands for lack of wind reads IDLE.
  const derated = turbine.state === 'DERATED' || alarms.some((a) => a.turbineId === turbine.id && /derated/i.test(a.description));
  if (derated || entry) return { ...view, entry, kind: 'controller' };
  return { ...view, entry: null, kind: commands === null ? 'unknown' : 'unexplained' };
}

const minutesText = (ms: number): string => {
  const minutes = Math.max(0, Math.round(ms / 60_000));
  return minutes >= 120 ? `${Math.round(minutes / 60)} h` : minutes === 1 ? '1 min' : `${minutes} min`;
};

const secondsBetween = (from: string, to: string): number | null => {
  const ms = new Date(to).getTime() - new Date(from).getTime();
  return Number.isFinite(ms) ? Math.max(0, Math.round(ms / 1000)) : null;
};

/**
 * The limit of a turbine in words: a heading and the lines under it. `clock` turns a time into the
 * text the page shows; `route` is where the live values come from, for the case that the log is missing.
 * With the turbine's power, a limit the wind does not reach is said to be one.
 */
export function limitText(view: LimitView, now: number, clock: (iso: string) => string, route: string, activePowerKw?: number): { title: string; lines: string[] } {
  const title = `${view.kind === 'pending' ? 'Limit on its way' : 'Limited'}: ${kw(view.limitKw)} kW · ${Math.round(view.percent)} % of rated`;
  const entry = view.entry;
  const until = (e: CommandEntry): string => {
    if (!e.endsAt) return 'until it is released';
    const left = new Date(e.endsAt).getTime() - now;
    return Number.isFinite(left) && left > 0 ? `ends ${clock(e.endsAt)}, in ${minutesText(left)}` : `its time ended ${clock(e.endsAt)}`;
  };
  if (view.kind === 'command' && entry) {
    const seconds = secondsBetween(entry.at, entry.confirmedAt);
    return {
      title,
      lines: [
        `Asked by ${askedBy(entry)}`,
        `Since ${clock(entry.at)} · ${until(entry)}`,
        seconds === null ? 'Confirmed by the telemetry' : `Confirmed by the telemetry ${seconds} s after the edge took the command`,
        // In a weak wind the turbine gives less than the limit anyway: the limit holds and changes nothing.
        ...(activePowerKw !== undefined && activePowerKw < view.limitKw * 0.93 ? ['The wind gives less than the limit right now, so the power is not held down.'] : []),
      ],
    };
  }
  if (view.kind === 'pending' && entry) {
    return { title, lines: [`Asked by ${askedBy(entry)}`, `The edge took the command at ${clock(entry.at)}. The telemetry does not show it yet.`] };
  }
  if (view.kind === 'controller') {
    const lines = ['By the turbine controller itself: it lowers the power while one of its alarms is active.'];
    if (entry && entry.limitKw !== null) lines.push(`A limit of ${kw(entry.limitKw)} kW asked by ${askedBy(entry)} also holds, ${until(entry)}.`);
    return { title, lines };
  }
  if (view.kind === 'unexplained') {
    return { title, lines: ['A limit is set, and the command log has no line for it: it was set before the log existed, or more than 24 hours ago.'] };
  }
  return {
    title,
    lines: [
      route === 'lakehouse'
        ? 'A limit is set. Who asked for it is in the command log, which is read on the Eventhouse route only.'
        : 'A limit is set. Who asked for it is not known here: this KQL database has no command log (Phase 5c).',
    ],
  };
}

/** One command as it was sent: a command to all turbines is one group with twelve lines. */
export interface CommandGroup {
  key: string;
  first: CommandEntry;
  turbines: string[];
  /** The status all lines share, or a count of each. */
  status: string;
  level: 0 | 1 | 2;
}

/** The commands as they were sent, newest first. */
export function groupCommands(commands: CommandEntry[]): CommandGroup[] {
  const groups = new Map<string, CommandEntry[]>();
  for (const c of commands) {
    // Commands given at the edge may carry no identifier: then each line stands for itself.
    const key = c.requestId ? `${c.requestId}|${c.command}` : `${c.at}|${c.turbineId}|${c.command}`;
    groups.set(key, [...(groups.get(key) ?? []), c]);
  }
  return [...groups.entries()]
    .map(([key, lines]) => {
      const counts = new Map<string, number>();
      for (const line of lines) counts.set(line.status, (counts.get(line.status) ?? 0) + 1);
      const status = counts.size === 1 ? lines[0].status : [...counts.entries()].map(([s, n]) => `${s} on ${n}`).join(', ');
      const level = Math.max(...lines.map((line) => statusLevel(line.status))) as 0 | 1 | 2;
      return { key, first: lines[0], turbines: lines.map((line) => line.turbineId).sort(), status, level };
    })
    .sort((a, b) => (a.first.at < b.first.at ? 1 : a.first.at > b.first.at ? -1 : 0));
}

/** The turbines of a group in words. */
export function groupTarget(group: CommandGroup, turbinesOnSite: number): string {
  if (group.turbines.length >= turbinesOnSite) return `All ${turbinesOnSite} turbines`;
  if (group.turbines.length > 3) return `${group.turbines.length} turbines`;
  return group.turbines.map((id) => (id.startsWith('WT-') ? id : 'No turbine')).join(', ');
}
