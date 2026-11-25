/**
 * Names of the Fabric items the twin reads. They are the names the deployment guides of Phases 1 and 3
 * create. The functions look the items up by name at run time, so no identifier is written down here.
 */
export const WORKSPACE_NAME = 'WindFarmDigitalTwin';
export const KQL_DATABASE_NAME = 'WindFarmEH';
export const LAKEHOUSE_NAME = 'WindFarmLH';
export const DATA_AGENT_NAME = 'WindFarmDataAgent';

/** Fabric REST API. */
export const FABRIC_API = 'https://api.fabric.microsoft.com/v1';

/**
 * The resource a token must be issued for to query an Eventhouse. A Fabric app cannot get such a token
 * from the platform (first deployment, 23 November 2026: a custom audience needs an app with its own
 * identity, and the Eventhouse answers 401 to the token for the Fabric API). A service principal can:
 * `principal.ts` asks Microsoft Entra ID for one with these three secrets of the app.
 */
export const KUSTO_SCOPE = 'https://kusto.kusto.windows.net/.default';
export const ENTRA_LOGIN = 'https://login.microsoftonline.com';
export const SECRET_TENANT_ID = 'KUSTO_TENANT_ID';
export const SECRET_CLIENT_ID = 'KUSTO_CLIENT_ID';
export const SECRET_CLIENT_SECRET = 'KUSTO_CLIENT_SECRET';

/** How long the looked-up identifiers are kept in memory. */
export const LOOKUP_TTL_MS = 10 * 60 * 1000;

/** Telemetry older than this is not "live". */
export const LIVE_WINDOW = '10m';

/** How far back the command log is read. A limit that was set longer ago is shown without who asked for it. */
export const COMMANDS_WINDOW = '24h';

/**
 * The command log is read once in this time, however many pages are open and ask every five seconds:
 * its query joins every command of the day with the telemetry after it. A new command therefore shows
 * in the twin up to this much later than the turbine's own values do.
 */
export const COMMANDS_CACHE_MS = 15_000;

/** After the KQL database refused the query for the command log, it is not asked again for this long. */
export const COMMAND_LOG_RETRY_MS = 5 * 60 * 1000;

/**
 * The Lakehouse copies are written at most every 5 minutes (`TargetLatencyInMinutes=5` in
 * `fabric/kql/03-onelake-availability.kql`) and the SQL endpoint finds new files a little later, so the
 * newest row there is minutes old. This many minutes back are searched for it.
 */
export const LAKEHOUSE_WINDOW_MINUTES = 60;

/** Longest question and answer that pass through `askAgent`, in characters. */
export const MAX_QUESTION_CHARS = 1000;
export const MAX_ANSWER_CHARS = 20000;

/** The functions host stops an invocation after 240 seconds. Stay below it. */
export const AGENT_TIMEOUT_MS = 225_000;
export const KUSTO_TIMEOUT_MS = 20_000;
export const ENTRA_TIMEOUT_MS = 15_000;
export const SQL_CONNECT_TIMEOUT_MS = 30_000;
export const SQL_REQUEST_TIMEOUT_MS = 45_000;
export const FABRIC_TIMEOUT_MS = 20_000;
