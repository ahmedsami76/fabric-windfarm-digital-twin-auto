/**
 * Where the twin gets its values. Two implementations: the functions of the Fabric app
 * (`fabricProvider.ts`) and a simulation that runs in the browser (`sampleProvider.ts`).
 */
import type { AgentAnswer, DiagnosticStep, LiveState, TrendPoint } from './contract';

export interface TwinDataProvider {
  /** `fabric` reads Fabric and asks the data agent; `sample` invents its values. */
  readonly kind: 'fabric' | 'sample';
  getLiveState(): Promise<LiveState>;
  getTrend(turbineId: string, minutes: number): Promise<TrendPoint[]>;
  ask(question: string): Promise<AgentAnswer>;
  diagnostics(): Promise<DiagnosticStep[]>;
  /** Only the simulation has it: start a gearbox fault on a turbine, as the edge script does. */
  injectFault?(turbineId: string): void;
  /**
   * Only the simulation has it: limit a turbine's power for a few minutes, as the operations agent does
   * after an approval. The deployed twin shows commands and sends none.
   */
  limitTurbine?(turbineId: string): void;
  /** Only the Fabric provider has it: the route of the last answer, and what the Eventhouse route said. */
  routeStatus?(): { route: 'eventhouse' | 'lakehouse' | null; eventhouseSaid: string | null };
}

/** How often the twin asks for new values, in milliseconds. The simulator reports every 5 seconds. */
export const POLL_MS = 5000;

/** The copies in the Lakehouse change every few minutes: asking twice a minute is enough. */
export const LAKEHOUSE_POLL_MS = 30_000;

/**
 * Telemetry older than this many seconds is shown as stale.
 *
 * The age the page shows is the browser's clock minus the time the turbine put on the newest row. A
 * healthy pipeline already puts a delay in it: the simulator reports every 5 seconds, the Eventhouse
 * collects up to 20 seconds of events before it stores them (`fabric/kql/01-tables.kql`), the page asks
 * every 5 seconds, and broker, data flow and eventstream add their own. The one reading from a deployed
 * app, on 23 November 2026, was 56 seconds. With the first limit of 60 seconds the badge would have
 * changed between "Live" and "Stale" on a pipeline that works, so the limit is two minutes. The
 * connection check prints the delay of the last 15 minutes; move this limit if yours is higher.
 */
export const STALE_AFTER_S = 120;

/**
 * The same for the Lakehouse route. The copies are written about every 5 minutes
 * (`TargetLatencyInMinutes=5` in `fabric/kql/03-onelake-availability.kql`); the one reading from a
 * deployed app was 2 minutes.
 */
export const LAKEHOUSE_STALE_AFTER_S = 20 * 60;

/** What the badge says under the pointer when values stopped arriving: the usual cause and its cure. */
export const STOPPED_HINT =
  'No new values are arriving. The usual cause is the edge VM: it is stopped every day at the time set in VM_AUTO_SHUTDOWN_UTC (08:00 UTC unless changed). On the workstation: bash infra/vm.sh status, then bash infra/vm.sh start. Values return about 5 minutes after the start.';

/** The wait before the next question, by the route of the last answer. */
export function pollDelay(route: 'eventhouse' | 'lakehouse' | 'sample' | undefined, failed: boolean): number {
  if (failed) return POLL_MS * 3;
  return route === 'lakehouse' ? LAKEHOUSE_POLL_MS : POLL_MS;
}

export type Freshness = 'loading' | 'live' | 'delayed' | 'stale' | 'silent' | 'sample' | 'error';

/** What the badge says about the values on the page. */
export function freshnessOf(
  live: { source: string; route?: string; turbines: unknown[] } | null,
  ageS: number | null,
  failed: boolean
): Freshness {
  if (failed && !live) return 'error';
  if (!live) return 'loading';
  if (live.source === 'sample') return 'sample';
  if (live.turbines.length === 0) return 'silent';
  if (failed) return 'error';
  const lakehouse = live.route === 'lakehouse';
  if (ageS !== null && ageS > (lakehouse ? LAKEHOUSE_STALE_AFTER_S : STALE_AFTER_S)) return 'stale';
  return lakehouse ? 'delayed' : 'live';
}

/** An age in words: seconds up to two minutes, then minutes. */
export function ageText(ageS: number | null): string {
  if (ageS === null) return 'age unknown';
  return ageS > 120 ? `${Math.round(ageS / 60)} min` : `${ageS} s`;
}

/** True when the address of the page asks for the simulation: `?sample` or `?sample=1`. */
export function sampleRequested(search: string = window.location.search): boolean {
  const value = new URLSearchParams(search).get('sample');
  return value !== null && value !== '0' && value !== 'false';
}
