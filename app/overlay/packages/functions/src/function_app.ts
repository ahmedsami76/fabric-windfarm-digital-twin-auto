/**
 * The server side of the wind farm twin: seven functions that the browser calls through the Rayfin
 * client. They run as the identity of the app, which today is the owner of the Fabric app item.
 *
 *   getLiveState               newest row per turbine, alarms, met mast   KQL database, as a service principal
 *   getTurbineTrend            one turbine, minute by minute              KQL database, as a service principal
 *   getDiagnostics             tries that route and the data agent        Fabric API, Entra ID, KQL database
 *   getLiveStateLakehouse      the same values, minutes old               Lakehouse SQL endpoint
 *   getTurbineTrendLakehouse   the same trend, minutes old                Lakehouse SQL endpoint
 *   getDiagnosticsLakehouse    tries that route                           Fabric API, Lakehouse SQL endpoint
 *   askAgent                   one question to the published data agent   Fabric API (MCP)
 *
 * Why two routes, each with functions of its own. The first deployment (23 November 2026) showed that a
 * Fabric app gets no token the Eventhouse accepts: a token made for it is a "custom audience", issued
 * only to an app with its own identity, and the token for the Fabric API is answered with 401. It also
 * showed that the platform refuses every call of a function whose declared audience it cannot serve,
 * before the function's code runs. So nothing one route declares may stand in the way of the other:
 * the page calls the Eventhouse functions first and the Lakehouse functions when those do not answer.
 *
 * The audiences in the context annotations are the declaration Rayfin deploys from, written literally
 * on purpose. Every function returns JSON text in a shape of `contract.ts`; when it cannot do its
 * work it returns `{ "error": … }` with the reason, because the host reports a function that throws
 * as "InternalError" and nothing more.
 */
import { AudienceType, UserDataFunctions, type RayfinContext } from '@microsoft/fabric-user-data-functions';

import { askDataAgent } from './agent.js';
import type { Failure } from './contract.js';
import { type Access, brief, lookup } from './fabric.js';
import {
  checkEventhouse,
  checkLakehouse,
  liveFromEventhouse,
  liveFromLakehouse,
  trendFromEventhouse,
  trendFromLakehouse,
} from './live.js';
import { type Principal, readPrincipal } from './principal.js';
import { lakehouseBatch } from './sql.js';

const udf = new UserDataFunctions();

// The app has no tables of its own, so the data schema of the context is left open.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type NoTables = Record<string, any>;

/** The result as JSON text, or the reason it could not be had. A function of this app never throws. */
async function answer(work: () => Promise<unknown>): Promise<string> {
  try {
    return JSON.stringify(await work());
  } catch (error) {
    const failure: Failure = { error: brief(error) };
    return JSON.stringify(failure);
  }
}

/**
 * The secrets of the app, read by name. The names are not known to the compiler: they exist only
 * after `npx rayfin secret set`, and the app has to build without them. Reading one that is not set
 * throws, which `readPrincipal` takes as "no service principal".
 */
function principalOf(ctx: { Secrets: unknown }): () => Principal {
  const secrets = ctx.Secrets as Record<string, string | undefined>;
  return () => readPrincipal((name) => secrets[name]);
}

udf.func(
  'getLiveState',
  async (ctx: RayfinContext<NoTables, AudienceType.Fabric>): Promise<string> => {
    const access: Access = { fabricToken: () => ctx.Tokens.Fabric, fetch };
    return answer(() => liveFromEventhouse(access, principalOf(ctx)));
  },
  []
);

udf.func(
  'getTurbineTrend',
  async (turbineId: string, minutes: number, ctx: RayfinContext<NoTables, AudienceType.Fabric>): Promise<string> => {
    const access: Access = { fabricToken: () => ctx.Tokens.Fabric, fetch };
    return answer(() => trendFromEventhouse(access, principalOf(ctx), turbineId, minutes));
  },
  []
);

udf.func(
  'getDiagnostics',
  async (ctx: RayfinContext<NoTables, AudienceType.Fabric>): Promise<string> => {
    const access: Access = { fabricToken: () => ctx.Tokens.Fabric, fetch };
    return answer(() => checkEventhouse(access, principalOf(ctx)));
  },
  []
);

udf.func(
  'getLiveStateLakehouse',
  async (ctx: RayfinContext<NoTables, AudienceType.Fabric | AudienceType.Sql>): Promise<string> => {
    const access: Access = { fabricToken: () => ctx.Tokens.Fabric, fetch };
    return answer(() => liveFromLakehouse(access, () => ctx.Tokens.Sql, lakehouseBatch));
  },
  []
);

udf.func(
  'getTurbineTrendLakehouse',
  async (
    turbineId: string,
    minutes: number,
    ctx: RayfinContext<NoTables, AudienceType.Fabric | AudienceType.Sql>
  ): Promise<string> => {
    const access: Access = { fabricToken: () => ctx.Tokens.Fabric, fetch };
    return answer(() => trendFromLakehouse(access, () => ctx.Tokens.Sql, lakehouseBatch, turbineId, minutes));
  },
  []
);

udf.func(
  'getDiagnosticsLakehouse',
  async (ctx: RayfinContext<NoTables, AudienceType.Fabric | AudienceType.Sql>): Promise<string> => {
    const access: Access = { fabricToken: () => ctx.Tokens.Fabric, fetch };
    return answer(() => checkLakehouse(access, () => ctx.Tokens.Sql, lakehouseBatch));
  },
  []
);

udf.func(
  'askAgent',
  async (question: string, ctx: RayfinContext<NoTables, AudienceType.Fabric>): Promise<string> => {
    const token = ctx.Tokens.Fabric;
    const access: Access = { fabricToken: () => token, fetch };
    return answer(async () => {
      const found = await lookup(access);
      if (!found.dataAgentEndpoint) {
        throw new Error('No data agent named WindFarmDataAgent in the workspace. Build it with notebook 09 of Phase 3.');
      }
      return askDataAgent(found.dataAgentEndpoint, token, question, fetch);
    });
  },
  []
);
