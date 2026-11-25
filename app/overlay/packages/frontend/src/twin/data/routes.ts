/**
 * Which of the two ways the live values take, decided in the page.
 *
 *   eventhouse  the KQL database, read as a service principal: seconds old. Needs the principal.
 *   lakehouse   the copies of the same tables in the Lakehouse: minutes old. Needs nothing.
 *
 * Each way has functions of its own, so that what one of them asks of the platform cannot stop the
 * other (see `function_app.ts`). The page asks the Eventhouse functions first. When they do not answer,
 * it uses the Lakehouse functions and tries the Eventhouse again every two minutes, so a principal that
 * is set up later is picked up without a reload.
 *
 * This file knows nothing of Rayfin: the calls are handed in, so the choice can be tested.
 */
import type { DiagnosticStep, LiveState, TrendPoint } from './contract';

export type Route = 'eventhouse' | 'lakehouse';

/** The functions of one route, already unpacked: each returns the shape or throws with the reason. */
export interface RouteCalls {
  live(): Promise<LiveState>;
  trend(turbineId: string, minutes: number): Promise<TrendPoint[]>;
  check(): Promise<DiagnosticStep[]>;
}

/** How long the Lakehouse route is used before the Eventhouse is tried again, in milliseconds. */
export const RETRY_EVENTHOUSE_MS = 120_000;

export interface RouteChooser {
  live(): Promise<LiveState>;
  trend(turbineId: string, minutes: number): Promise<TrendPoint[]>;
  check(): Promise<DiagnosticStep[]>;
  /** The route of the last answer, and why the Eventhouse was not used when it was not. */
  status(): { route: Route | null; eventhouseSaid: string | null };
}

const reason = (error: unknown): string => (error instanceof Error ? error.message : String(error));

export function chooseRoute(calls: Record<Route, RouteCalls>, clock: () => number = Date.now): RouteChooser {
  let route: Route | null = null;
  let eventhouseSaid: string | null = null;
  let retryAt = 0;

  /** Runs `work` on the Eventhouse when it is its turn, otherwise or on failure on the Lakehouse. */
  async function run<T>(work: (c: RouteCalls) => Promise<T>): Promise<T> {
    if (route !== 'lakehouse' || clock() >= retryAt) {
      try {
        const result = await work(calls.eventhouse);
        route = 'eventhouse';
        eventhouseSaid = null;
        return result;
      } catch (error) {
        eventhouseSaid = reason(error);
        retryAt = clock() + RETRY_EVENTHOUSE_MS;
      }
    }
    try {
      const result = await work(calls.lakehouse);
      route = 'lakehouse';
      return result;
    } catch (error) {
      route = null;
      throw new Error(`Eventhouse route: ${eventhouseSaid ?? 'not tried'} Lakehouse route: ${reason(error)}`);
    }
  }

  return {
    live: () => run((c) => c.live()),
    trend: (turbineId, minutes) => run((c) => c.trend(turbineId, minutes)),
    /** Both routes are checked, whichever is in use; a check that does not answer becomes a line. */
    check: async () => {
      const [eventhouse, lakehouse] = await Promise.allSettled([calls.eventhouse.check(), calls.lakehouse.check()]);
      const lines = (settled: PromiseSettledResult<DiagnosticStep[]>, name: string): DiagnosticStep[] =>
        settled.status === 'fulfilled'
          ? settled.value
          : [{ step: `${name}: the check itself`, ok: false, detail: reason(settled.reason) }];
      return [...lines(eventhouse, 'Eventhouse route'), ...lines(lakehouse, 'Lakehouse route')];
    },
    status: () => ({ route, eventhouseSaid }),
  };
}
