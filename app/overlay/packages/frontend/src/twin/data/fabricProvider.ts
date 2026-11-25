/**
 * The values of the deployed twin: every call goes to a function of the Fabric app. No token and no
 * secret reaches the browser. The live values have two routes (`routes.ts`); the chat has one.
 */
import { getRayfinClient } from '@/lib/rayfin-client';

import type { AgentAnswer, DiagnosticStep, LiveState, TrendPoint } from './contract';
import { fromFunction as parse } from './functionResult';
import type { TwinDataProvider } from './provider';
import { chooseRoute } from './routes';

/** The functions host stops an invocation after 240 seconds; the data agent may need most of that. */
const AGENT_WAIT_MS = 240_000;
/** The first SQL connection after a pause can take half a minute. */
const LAKEHOUSE_WAIT_MS = 90_000;

export function createFabricProvider(): TwinDataProvider {
  const routes = chooseRoute({
    eventhouse: {
      live: async () => parse<LiveState>(await (await getRayfinClient()).functions.getLiveState.invoke(), 'getLiveState'),
      trend: async (turbineId, minutes) =>
        parse<TrendPoint[]>(await (await getRayfinClient()).functions.getTurbineTrend.invoke({ turbineId, minutes }), 'getTurbineTrend'),
      check: async () =>
        parse<DiagnosticStep[]>(await (await getRayfinClient()).functions.getDiagnostics.invoke(undefined, { timeoutMs: 90_000 }), 'getDiagnostics'),
    },
    lakehouse: {
      live: async () =>
        parse<LiveState>(
          await (await getRayfinClient()).functions.getLiveStateLakehouse.invoke(undefined, { timeoutMs: LAKEHOUSE_WAIT_MS }),
          'getLiveStateLakehouse'
        ),
      trend: async (turbineId, minutes) =>
        parse<TrendPoint[]>(
          await (await getRayfinClient()).functions.getTurbineTrendLakehouse.invoke({ turbineId, minutes }, { timeoutMs: LAKEHOUSE_WAIT_MS }),
          'getTurbineTrendLakehouse'
        ),
      check: async () =>
        parse<DiagnosticStep[]>(
          await (await getRayfinClient()).functions.getDiagnosticsLakehouse.invoke(undefined, { timeoutMs: 120_000 }),
          'getDiagnosticsLakehouse'
        ),
    },
  });

  return {
    kind: 'fabric',
    getLiveState: () => routes.live(),
    getTrend: (turbineId: string, minutes: number) => routes.trend(turbineId, minutes),
    ask: async (question: string): Promise<AgentAnswer> => {
      const client = await getRayfinClient();
      return parse<AgentAnswer>(await client.functions.askAgent.invoke({ question }, { timeoutMs: AGENT_WAIT_MS }), 'askAgent');
    },
    diagnostics: () => routes.check(),
    routeStatus: () => routes.status(),
  };
}
