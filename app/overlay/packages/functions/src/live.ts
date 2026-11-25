/**
 * The live values of the twin: the newest row of every turbine, the active alarms and the met mast.
 *
 * They can come two ways, and each way has functions of its own in `function_app.ts`:
 *
 *   eventhouse  KQL on the KQL database, as a service principal (`principal.ts`). Seconds old.
 *   lakehouse   T-SQL on the copies of the same tables in the Lakehouse (`sql.ts`), as the owner of
 *               the app. Minutes old, and there without any set-up.
 *
 * The queries are also in the repository, where they can be run by hand:
 * `fabric/kql/94-twin-app-queries.kql` and `fabric/sql/94-twin-app-queries.sql`.
 */
import { FUNCTIONS_BUILD } from './build.js';
import { COMMANDS_CACHE_MS, COMMANDS_WINDOW, COMMAND_LOG_RETRY_MS, LAKEHOUSE_WINDOW_MINUTES, LIVE_WINDOW } from './config.js';
import type { Alarm, CommandEntry, DiagnosticStep, LiveState, TrendPoint, TurbineLive, TurbineState, Weather } from './contract.js';
import { type Access, type LakehouseLookup, type Lookup, brief, clearLookup, lookup, lookupLakehouse } from './fabric.js';
import { KustoError, runQuery } from './kusto.js';
import { NoPrincipal, type Principal, clearPrincipalToken, principalToken } from './principal.js';
import type { Row, SqlBatch } from './sql.js';

/** The columns of TurbineTelemetry the twin shows, besides TurbineId and Timestamp. */
export const TELEMETRY_COLUMNS = [
  'State',
  'WindSpeed',
  'WindDirection',
  'AmbientTemp',
  'ActivePower',
  'PowerSetpoint',
  'RotorSpeed',
  'PitchAngle',
  'NacelleDirection',
  'YawError',
  'GearboxOilTemp',
  'GearboxBearingTemp',
  'GearboxOilPressure',
  'GearboxVibration',
  'GeneratorWindingTemp',
  'GeneratorBearingTemp',
  'MainBearingTemp',
  'TransformerTemp',
  'HydraulicPressure',
  'TowerVibration',
] as const;

export const TURBINES_QUERY = `TurbineTelemetry
| where Timestamp > ago(${LIVE_WINDOW})
| summarize arg_max(Timestamp, ${TELEMETRY_COLUMNS.join(', ')}) by TurbineId
| order by TurbineId asc`;

export const ALARMS_QUERY = `ActiveAlarms()
| order by RaisedAt desc
| take 100`;

export const WEATHER_QUERY = `WeatherObservations
| where Timestamp > ago(${LIVE_WINDOW})
| summarize arg_max(Timestamp, WindSpeed, WindDirection, WindGust, AmbientTemp, AirDensity)`;

/**
 * The edge's command log with what the telemetry showed afterwards (Phase 5c). `CommandLog` is a
 * function of the KQL database: `fabric/kql/07-command-log.kql` creates it together with the table
 * `EdgeCommands`. A database without them refuses this query; the twin then shows no commands.
 */
export const COMMANDS_QUERY = `CommandLog(${COMMANDS_WINDOW})
| order by Timestamp desc, TurbineId asc
| take 60`;

const TURBINE_ID = /^WT-\d{2}$/;

/**
 * The trend query of one turbine. Both values go into the text of the query, so both are checked:
 * the identifier against its pattern, the minutes as a whole number between 5 and 360.
 */
export function trendQuery(turbineId: string, minutes: number): string {
  if (!TURBINE_ID.test(turbineId)) throw new Error(`Not a turbine identifier: ${brief(turbineId)}`);
  const span = Math.min(360, Math.max(5, Math.round(Number(minutes) || 60)));
  return `TurbineTelemetry
| where Timestamp > ago(${span}m) and TurbineId == '${turbineId}'
| summarize ActivePower = avg(ActivePower), WindSpeed = avg(WindSpeed), RotorSpeed = avg(RotorSpeed), GearboxOilTemp = avg(GearboxOilTemp), GearboxBearingTemp = avg(GearboxBearingTemp), GearboxVibration = avg(GearboxVibration) by Timestamp = bin(Timestamp, 1m)
| order by Timestamp asc`;
}

const TREND_COLUMNS = ['ActivePower', 'WindSpeed', 'RotorSpeed', 'GearboxOilTemp', 'GearboxBearingTemp', 'GearboxVibration'] as const;

/*
 * The same four questions in T-SQL, for the copies of the tables in the Lakehouse. The newest row
 * there is minutes old, so the search goes back LAKEHOUSE_WINDOW_MINUTES. Names are written as the
 * Eventhouse spells them: the SQL endpoint tells capitals from small letters.
 */
export const SQL_TURBINES = `WITH newest AS (
  SELECT TurbineId, [Timestamp], ${TELEMETRY_COLUMNS.join(', ')},
         ROW_NUMBER() OVER (PARTITION BY TurbineId ORDER BY [Timestamp] DESC) AS rn
  FROM TurbineTelemetry
  WHERE [Timestamp] > DATEADD(minute, -${LAKEHOUSE_WINDOW_MINUTES}, SYSUTCDATETIME())
)
SELECT TurbineId, [Timestamp], ${TELEMETRY_COLUMNS.join(', ')}
FROM newest
WHERE rn = 1
ORDER BY TurbineId`;

/** What the function ActiveAlarms() of the KQL database does, on the copies of its two tables. */
export const SQL_ALARMS = `WITH started AS (
  SELECT TOP 1 DATEADD(second, -CAST(UptimeSeconds AS int), [Timestamp]) AS StartedAt
  FROM EdgeHeartbeats
  ORDER BY [Timestamp] DESC
), newest AS (
  SELECT [Timestamp], TurbineId, AlarmCode, Status, Severity, Component, Description, Value, Threshold, Unit, SopId, AlarmId,
         ROW_NUMBER() OVER (PARTITION BY AlarmId ORDER BY [Timestamp] DESC) AS rn
  FROM AlarmEvents
  WHERE AlarmCode <> 'COMMS-RESTORED'
)
SELECT TOP 100 [Timestamp] AS RaisedAt, TurbineId, AlarmCode, Severity, Component, Description, Value, Threshold, Unit, SopId, AlarmId
FROM newest
WHERE rn = 1 AND Status = 'raised'
  AND ((SELECT StartedAt FROM started) IS NULL OR [Timestamp] >= DATEADD(minute, -1, (SELECT StartedAt FROM started)))
ORDER BY [Timestamp] DESC`;

export const SQL_WEATHER = `SELECT TOP 1 [Timestamp], WindSpeed, WindDirection, WindGust, AmbientTemp, AirDensity
FROM WeatherObservations
WHERE [Timestamp] > DATEADD(minute, -${LAKEHOUSE_WINDOW_MINUTES}, SYSUTCDATETIME())
ORDER BY [Timestamp] DESC`;

export const SQL_PROBE = `SELECT COUNT(*) AS [Rows], COUNT(DISTINCT TurbineId) AS Turbines, MAX([Timestamp]) AS Newest
FROM TurbineTelemetry
WHERE [Timestamp] > DATEADD(minute, -${LAKEHOUSE_WINDOW_MINUTES}, SYSUTCDATETIME())`;

/** The trend of one turbine in T-SQL, one row a minute. The same checks as `trendQuery`. */
export function sqlTrendQuery(turbineId: string, minutes: number): string {
  if (!TURBINE_ID.test(turbineId)) throw new Error(`Not a turbine identifier: ${brief(turbineId)}`);
  const span = Math.min(360, Math.max(5, Math.round(Number(minutes) || 60)));
  const minute = `DATEADD(minute, DATEDIFF(minute, '2000-01-01', [Timestamp]), CAST('2000-01-01' AS datetime2(0)))`;
  return `SELECT ${minute} AS [Timestamp], ${TREND_COLUMNS.map((c) => `AVG(${c}) AS ${c}`).join(', ')}
FROM TurbineTelemetry
WHERE [Timestamp] > DATEADD(minute, -${span}, SYSUTCDATETIME()) AND TurbineId = '${turbineId}'
GROUP BY ${minute}
ORDER BY [Timestamp]`;
}

const STATES: readonly TurbineState[] = [
  'RUNNING', 'DERATED', 'CURTAILED', 'IDLE', 'PAUSED', 'STOPPED', 'STOPPED_HIGH_WIND', 'MAINTENANCE', 'FAULT',
];

const num = (value: unknown): number => {
  const n = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(n) ? n : 0;
};
const numOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
};
const text = (value: unknown): string => (value === null || value === undefined ? '' : String(value));

export function toTurbine(row: Record<string, unknown>): TurbineLive {
  const state = text(row.State).toUpperCase() as TurbineState;
  return {
    id: text(row.TurbineId),
    timestamp: text(row.Timestamp),
    state: STATES.includes(state) ? state : 'UNKNOWN',
    windSpeed: num(row.WindSpeed),
    windDirection: num(row.WindDirection),
    ambientTemp: num(row.AmbientTemp),
    activePower: num(row.ActivePower),
    powerSetpoint: num(row.PowerSetpoint),
    rotorSpeed: num(row.RotorSpeed),
    pitchAngle: num(row.PitchAngle),
    nacelleDirection: num(row.NacelleDirection),
    yawError: num(row.YawError),
    gearboxOilTemp: num(row.GearboxOilTemp),
    gearboxBearingTemp: num(row.GearboxBearingTemp),
    gearboxOilPressure: num(row.GearboxOilPressure),
    gearboxVibration: num(row.GearboxVibration),
    generatorWindingTemp: num(row.GeneratorWindingTemp),
    generatorBearingTemp: num(row.GeneratorBearingTemp),
    mainBearingTemp: num(row.MainBearingTemp),
    transformerTemp: num(row.TransformerTemp),
    hydraulicPressure: num(row.HydraulicPressure),
    towerVibration: num(row.TowerVibration),
  };
}

export function toAlarm(row: Record<string, unknown>): Alarm {
  return {
    id: text(row.AlarmId),
    turbineId: text(row.TurbineId),
    code: text(row.AlarmCode),
    severity: text(row.Severity).toLowerCase(),
    component: text(row.Component),
    description: text(row.Description),
    raisedAt: text(row.RaisedAt),
    value: numOrNull(row.Value),
    threshold: numOrNull(row.Threshold),
    unit: text(row.Unit),
    sopId: text(row.SopId),
  };
}

export function toCommand(row: Record<string, unknown>): CommandEntry {
  return {
    requestId: text(row.RequestId),
    turbineId: text(row.TurbineId),
    command: text(row.Command).toLowerCase(),
    status: text(row.Status),
    at: text(row.Timestamp),
    requestedBy: text(row.RequestedBy),
    origin: text(row.Source).toLowerCase() === 'edge' ? 'edge' : 'cloud',
    limitKw: numOrNull(row.LimitKw),
    percent: numOrNull(row.Percent),
    endsAt: text(row.EndsAt),
    confirmedAt: text(row.ConfirmedAt),
    endedAt: text(row.EndedAt),
    error: text(row.Error),
  };
}

export function toWeather(row: Record<string, unknown> | undefined): Weather | null {
  if (!row || !text(row.Timestamp)) return null; // no observation in the window: one row of nulls
  return {
    timestamp: text(row.Timestamp),
    windSpeed: num(row.WindSpeed),
    windDirection: num(row.WindDirection),
    windGust: num(row.WindGust),
    ambientTemp: num(row.AmbientTemp),
    airDensity: num(row.AirDensity),
  };
}

export function toTrendPoint(row: Record<string, unknown>): TrendPoint {
  return {
    t: text(row.Timestamp),
    activePower: num(row.ActivePower),
    windSpeed: num(row.WindSpeed),
    rotorSpeed: num(row.RotorSpeed),
    gearboxOilTemp: num(row.GearboxOilTemp),
    gearboxBearingTemp: num(row.GearboxBearingTemp),
    gearboxVibration: num(row.GearboxVibration),
  };
}

/**
 * Under which name the Eventhouse knows the database: its display name or, when it does not know
 * that, its item identifier. Found out at the first query and remembered while the host lives.
 */
let acceptedDatabase: string | undefined;

/** The same for the SQL endpoint of the Lakehouse: the name of the database it answered to. */
let acceptedSqlDatabase: string | undefined;

/**
 * The command log is an addition of Phase 5c, and the twin has to work on a database that does not have
 * it. When the database refuses the query, it is not asked again for a while, and what it said is kept
 * for the connection check.
 */
let commandLogAskAgainAt = 0;
let commandLogSaid: string | null = null;
/** The last answer, kept for COMMANDS_CACHE_MS while the host lives. */
let commandLogKept: { at: number; lines: CommandEntry[] } | null = null;

/** Forget all of it. Used by the connection check and by the tests. */
export function resetRoute(): void {
  acceptedDatabase = undefined;
  acceptedSqlDatabase = undefined;
  commandLogAskAgainAt = 0;
  commandLogSaid = null;
  commandLogKept = null;
}

/** What the KQL database last said to the query for the command log; null when it answered. */
export function commandLogProblem(): string | null {
  return commandLogSaid;
}

export function currentSqlDatabase(): string | undefined {
  return acceptedSqlDatabase;
}

export function currentDatabase(): string | undefined {
  return acceptedDatabase;
}

const unknownDatabase = (error: unknown): boolean =>
  error instanceof KustoError && error.status >= 400 && error.status < 500 && /database/i.test(error.message);

/** Runs KQL on the Eventhouse with the token of the service principal. */
export async function queryEventhouse(access: Access, found: Lookup, token: string, csl: string): Promise<Row[]> {
  const databases = acceptedDatabase ? [acceptedDatabase] : [found.kqlDatabaseName, found.kqlDatabaseId];
  let failure: unknown;
  for (const database of databases) {
    try {
      const rows = await runQuery({ queryServiceUri: found.queryServiceUri, database, query: csl, token, fetch: access.fetch });
      acceptedDatabase = database;
      return rows;
    } catch (error) {
      failure = error;
      if (unknownDatabase(error)) continue; // try the identifier
      if (acceptedDatabase) resetRoute(); // what worked before no longer does: start over next time
      throw error;
    }
  }
  throw failure ?? new Error('The Eventhouse was not asked.');
}

function liveState(route: 'eventhouse' | 'lakehouse', turbineRows: Row[], alarmRows: Row[], weatherRows: Row[], commands: CommandEntry[] | null): LiveState {
  const turbines = turbineRows.map(toTurbine);
  const asOf = turbines.reduce((latest, t) => (t.timestamp > latest ? t.timestamp : latest), '');
  return { source: 'fabric', route, asOf, turbines, alarms: alarmRows.map(toAlarm), weather: toWeather(weatherRows[0]), commands };
}

/**
 * The command log, or null when the database cannot give it. It never throws: the turbines are shown
 * with or without it. Call it after a query has settled the name of the database.
 */
export async function commandsFromEventhouse(access: Access, found: Lookup, token: string, now: number = Date.now()): Promise<CommandEntry[] | null> {
  if (commandLogKept && now >= commandLogKept.at && now - commandLogKept.at < COMMANDS_CACHE_MS) return commandLogKept.lines;
  if (now < commandLogAskAgainAt) return null;
  try {
    const database = acceptedDatabase ?? found.kqlDatabaseName;
    const rows = await runQuery({ queryServiceUri: found.queryServiceUri, database, query: COMMANDS_QUERY, token, fetch: access.fetch });
    commandLogSaid = null;
    commandLogKept = { at: now, lines: rows.map(toCommand) };
    return commandLogKept.lines;
  } catch (error) {
    commandLogKept = null;
    commandLogSaid = brief(error);
    // A query the database cannot run will not run five seconds later either. Anything else may pass.
    if (error instanceof KustoError && error.status >= 400 && error.status < 500) commandLogAskAgainAt = now + COMMAND_LOG_RETRY_MS;
    return null;
  }
}

/** The live values from the KQL database, as the service principal. Throws NoPrincipal when there is none. */
export async function liveFromEventhouse(access: Access, principal: () => Principal): Promise<LiveState> {
  const who = principal();
  const [found, token] = await Promise.all([lookup(access), principalToken(who, access.fetch)]);
  // The first query settles the name of the database; the other two then run side by side.
  const turbineRows = await queryEventhouse(access, found, token, TURBINES_QUERY);
  const [alarmRows, weatherRows, commands] = await Promise.all([
    queryEventhouse(access, found, token, ALARMS_QUERY),
    queryEventhouse(access, found, token, WEATHER_QUERY),
    commandsFromEventhouse(access, found, token),
  ]);
  return liveState('eventhouse', turbineRows, alarmRows, weatherRows, commands);
}

export async function trendFromEventhouse(access: Access, principal: () => Principal, turbineId: string, minutes: number): Promise<TrendPoint[]> {
  const csl = trendQuery(turbineId, minutes);
  const who = principal();
  const [found, token] = await Promise.all([lookup(access), principalToken(who, access.fetch)]);
  return (await queryEventhouse(access, found, token, csl)).map(toTrendPoint);
}

/** Opens the SQL endpoint of a Lakehouse: server, database (the item identifier), token. */
export type SqlConnect = (server: string, database: string, token: string) => SqlBatch;

/**
 * The names the SQL endpoint may know the Lakehouse by, in the order they are tried. Rayfin's guide
 * says the item identifier of the Lakehouse; on the first deployment (23 November 2026) the endpoint
 * answered "the database was not found or you have insufficient permissions" to it and opened the
 * database under the display name. So the name comes first; the two identifiers stay as fallbacks,
 * and the one that answers is remembered while the host lives.
 */
export function sqlDatabaseNames(found: LakehouseLookup): { name: string; kind: string }[] {
  const names = [
    { name: found.lakehouseName, kind: 'the name of the Lakehouse' },
    { name: found.lakehouseId, kind: 'the item identifier of the Lakehouse' },
    ...(found.sqlEndpointId ? [{ name: found.sqlEndpointId, kind: 'the item identifier of the SQL endpoint' }] : []),
  ];
  return names.filter((n, i) => names.findIndex((m) => m.name === n.name) === i);
}

/** True when the endpoint let the token in and did not open the database: another name may work. */
const databaseNotOpened = (error: unknown): boolean =>
  /database was not found|insufficient permissions to connect|cannot open database|ELOGIN/i.test(error instanceof Error ? error.message : String(error));

/** Runs the statements on the Lakehouse, under the first database name the endpoint accepts. */
export async function queryLakehouse(found: LakehouseLookup, token: string, connect: SqlConnect, statements: string[]): Promise<Row[][]> {
  const candidates = sqlDatabaseNames(found);
  const order = acceptedSqlDatabase ? candidates.filter((c) => c.name === acceptedSqlDatabase) : candidates;
  const said: string[] = [];
  for (const candidate of order.length ? order : candidates) {
    try {
      const rows = await connect(found.sqlServer, candidate.name, token)(statements);
      acceptedSqlDatabase = candidate.name;
      return rows;
    } catch (error) {
      if (!databaseNotOpened(error)) throw error;
      said.push(`as ${candidate.kind}: ${brief(error).slice(0, 150)}`);
    }
  }
  acceptedSqlDatabase = undefined; // what worked before no longer does: try every name next time
  throw new Error(`The SQL endpoint opened the database under none of ${said.length} names. ${said.join(' | ')}`);
}

/** The live values from the copies of the tables in the Lakehouse, as the owner of the app. */
export async function liveFromLakehouse(access: Access, sqlToken: () => string, connect: SqlConnect): Promise<LiveState> {
  const found = await lookupLakehouse(access);
  const [turbineRows, alarmRows, weatherRows] = await queryLakehouse(found, sqlToken(), connect, [SQL_TURBINES, SQL_ALARMS, SQL_WEATHER]);
  // The command log is not copied to the Lakehouse: on this route the twin shows a limit without who asked for it.
  return liveState('lakehouse', turbineRows ?? [], alarmRows ?? [], weatherRows ?? [], null);
}

export async function trendFromLakehouse(access: Access, sqlToken: () => string, connect: SqlConnect, turbineId: string, minutes: number): Promise<TrendPoint[]> {
  const statement = sqlTrendQuery(turbineId, minutes);
  const found = await lookupLakehouse(access);
  const [rows] = await queryLakehouse(found, sqlToken(), connect, [statement]);
  return (rows ?? []).map(toTrendPoint);
}

const step = (steps: DiagnosticStep[], name: string, ok: boolean, detail: string): void => {
  steps.push({ step: name, ok, detail: brief(detail) });
};

/**
 * How long a reading takes from the turbine to the KQL database, measured in the data itself: the time
 * the row arrived (`IngestedAt`, which the update policy takes from `ingestion_time()`) minus the time
 * the turbine put on it. No clock of a workstation or of the function host is in it. The connection
 * check prints the result, because the limit after which the page calls its values stale
 * (`STALE_AFTER_S`) has to sit well above the highest delay.
 */
export const DELAY_QUERY = `TurbineTelemetry
| where Timestamp > ago(15m)
| extend DelayS = datetime_diff('second', IngestedAt, Timestamp)
| summarize Rows = count(), Median = percentile(DelayS, 50), P95 = percentile(DelayS, 95), Highest = max(DelayS)`;

/** The words of the connection check for the answer to `DELAY_QUERY`. */
export function delayText(row: Record<string, unknown>): string {
  const n = (value: unknown): string => (typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value)) : '?');
  return `median ${n(row.Median)} s, 95 % of the rows within ${n(row.P95)} s, highest ${n(row.Highest)} s, over the ${n(row.Rows)} rows of the last 15 minutes`;
}

const minutesOld = (iso: string, now: number): string => {
  const ms = now - new Date(iso).getTime();
  if (!iso || !Number.isFinite(ms)) return 'age unknown';
  return ms < 90_000 ? `${Math.max(0, Math.round(ms / 1000))} s old` : `${Math.round(ms / 60_000)} min old`;
};

/**
 * Tries what the real-time route and the chat need, one thing after the other, and says what happened
 * at each. The steps do not stop at the first failure, so one run shows everything that is wrong.
 */
export async function checkEventhouse(access: Access, principal: () => Principal, now: number = Date.now()): Promise<DiagnosticStep[]> {
  const steps: DiagnosticStep[] = [];
  step(steps, 'Functions of the Eventhouse route', true, `build ${FUNCTIONS_BUILD}`);

  let fabricOk = false;
  try {
    access.fabricToken();
    fabricOk = true;
    step(steps, 'Token for the Fabric API', true, 'supplied by the host');
  } catch (error) {
    step(steps, 'Token for the Fabric API', false, brief(error));
  }

  let found: Lookup | undefined;
  if (fabricOk) {
    try {
      clearLookup();
      found = await lookup(access);
      step(steps, 'Workspace and KQL database', true, `${found.kqlDatabaseName} at ${found.queryServiceUri}`);
      step(steps, 'Data agent, for the chat', found.dataAgentId !== null, found.dataAgentId ?? 'no item with the name of the agent in the workspace');
    } catch (error) {
      step(steps, 'Workspace and KQL database', false, brief(error));
    }
  }

  let who: Principal | undefined;
  try {
    who = principal();
    step(steps, 'Eventhouse route: service principal', true, `application ${who.clientId} in tenant ${who.tenantId}`);
  } catch (error) {
    if (error instanceof NoPrincipal) {
      steps.push({ step: 'Eventhouse route: service principal', ok: false, skipped: true, detail: brief(error) });
    } else {
      step(steps, 'Eventhouse route: service principal', false, brief(error));
    }
  }

  let token: string | undefined;
  if (who) {
    try {
      clearPrincipalToken();
      token = await principalToken(who, access.fetch);
      step(steps, 'Eventhouse route: token from Microsoft Entra ID', true, 'issued to the service principal');
    } catch (error) {
      step(steps, 'Eventhouse route: token from Microsoft Entra ID', false, brief(error));
    }
  }

  if (found && token) {
    try {
      resetRoute();
      const rows = await queryEventhouse(access, found, token, 'TurbineTelemetry | where Timestamp > ago(2m) | summarize Rows = count(), Turbines = dcount(TurbineId), Newest = max(Timestamp)');
      const r = rows[0] ?? {};
      const newest = text(r.Newest);
      step(steps, 'Eventhouse route: query', num(r.Rows) > 0, num(r.Rows) > 0
        ? `${num(r.Rows)} rows from ${num(r.Turbines)} turbines in the last 2 minutes; newest ${minutesOld(newest, now)}`
        : 'the query ran and found no telemetry in the last 2 minutes: the simulator or the edge VM is stopped (the VM has a daily shutdown)');
      if (num(r.Rows) > 0) {
        // A measurement, not a condition: when it cannot be taken, the route still works.
        try {
          const delay = await queryEventhouse(access, found, token, DELAY_QUERY);
          step(steps, 'Eventhouse route: delay from turbine to database', true, delayText(delay[0] ?? {}));
        } catch (error) {
          steps.push({ step: 'Eventhouse route: delay from turbine to database', ok: false, skipped: true, detail: `not measured: ${brief(error)}` });
        }
      }
      // An addition of Phase 5c, not a condition of the route: without it the twin shows no commands.
      // `resetRoute` above has cleared what was kept, so this asks the database itself.
      const commands = await commandsFromEventhouse(access, found, token, now);
      if (commands) {
        const limits = commands.filter((c) => c.command === 'curtail' && c.status === 'in force').length;
        step(steps, 'Eventhouse route: command log', true, `${commands.length} line${commands.length === 1 ? '' : 's'} in the last ${COMMANDS_WINDOW}, ${limits} limit${limits === 1 ? '' : 's'} in force`);
      } else {
        steps.push({
          step: 'Eventhouse route: command log', ok: false, skipped: true,
          detail: brief(`not there, so the twin shows no commands. Phase 5c creates it: block 1 of fabric/kql/07-command-log.kql. The database said: ${commandLogSaid ?? 'nothing'}`),
        });
      }
    } catch (error) {
      step(steps, 'Eventhouse route: query', false, brief(error));
    }
  }
  return steps;
}

/** Tries what the Lakehouse route needs, in the same manner. */
export async function checkLakehouse(access: Access, sqlToken: () => string, connect: SqlConnect, now: number = Date.now()): Promise<DiagnosticStep[]> {
  const steps: DiagnosticStep[] = [];
  step(steps, 'Functions of the Lakehouse route', true, `build ${FUNCTIONS_BUILD}`);
  let token: string | undefined;
  try {
    token = sqlToken();
    step(steps, 'Lakehouse route: token for SQL', true, 'supplied by the host');
  } catch (error) {
    step(steps, 'Lakehouse route: token for SQL', false, brief(error));
  }
  let found: LakehouseLookup | undefined;
  try {
    clearLookup();
    found = await lookupLakehouse(access);
    step(steps, 'Lakehouse route: Lakehouse and SQL endpoint', true, `${found.lakehouseName} at ${found.sqlServer}`);
  } catch (error) {
    step(steps, 'Lakehouse route: Lakehouse and SQL endpoint', false, brief(error));
  }
  if (found && token) {
    try {
      acceptedSqlDatabase = undefined; // the check tries every name afresh
      const [rows] = await queryLakehouse(found, token, connect, [SQL_PROBE]);
      const r = rows?.[0] ?? {};
      const newest = text(r.Newest);
      const opened = sqlDatabaseNames(found).find((n) => n.name === acceptedSqlDatabase)?.kind ?? 'an unknown name';
      step(steps, 'Lakehouse route: query', num(r.Rows) > 0, num(r.Rows) > 0
        ? `${num(r.Rows)} rows from ${num(r.Turbines)} turbines in the last ${LAKEHOUSE_WINDOW_MINUTES} minutes; newest ${minutesOld(newest, now)}; database opened as ${opened}`
        // Seen on 25 November 2026: this line failed and passed 3.5 minutes later with nothing changed. The SQL endpoint
        // follows new data only while it is in use, and this check is often the first to ask it in a long time.
        : `the query ran and found no telemetry in the last ${LAKEHOUSE_WINDOW_MINUTES} minutes; database opened as ${opened}. `
          + 'If the Eventhouse route has telemetry, the SQL endpoint of the Lakehouse is only behind, which it is after a time without use: check again in a few minutes');
    } catch (error) {
      // Longer than other lines on purpose: it carries what the endpoint said to each name.
      steps.push({ step: 'Lakehouse route: query', ok: false, detail: (error instanceof Error ? error.message : String(error)).replace(/\s+/g, ' ').slice(0, 900) });
    }
  }
  return steps;
}
