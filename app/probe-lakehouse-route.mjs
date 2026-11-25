// Asks the SQL analytics endpoint of the Lakehouse the question the twin's Lakehouse route asks it, as the person who
// is signed in to the Azure CLI. Started by tools/deploy.py, which hands over the server, the database and a token in
// the environment. Prints one line of JSON: {"rows", "turbines", "newest_minutes"} or {"error"}. The token is not printed.
//
// The connection is the one of app/overlay/packages/functions/src/sql.ts, and the query is SQL_PROBE of live.ts with its
// window of 60 minutes; a test compares the two texts. The driver is the one bash app/create-app.sh installed for the app.
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

export const QUERY = `SELECT COUNT(*) AS [Rows], COUNT(DISTINCT TurbineId) AS Turbines, MAX([Timestamp]) AS Newest
FROM TurbineTelemetry
WHERE [Timestamp] > DATEADD(minute, -60, SYSUTCDATETIME())`;

const here = path.dirname(fileURLToPath(import.meta.url));
const answer = (value, code = 0) => {
  console.log(JSON.stringify(value));
  process.exit(code);
};
const { SQL_SERVER: server, SQL_DATABASE: database, SQL_TOKEN: token } = process.env;
if (!server || !database || !token) answer({ error: 'SQL_SERVER, SQL_DATABASE and SQL_TOKEN are not set. This is started by tools/deploy.py' }, 2);

let sql;
try {
  sql = createRequire(path.join(here, 'windfarm-twin', 'packages', 'functions', 'package.json'))('mssql');
} catch {
  answer({ error: 'the SQL driver is not there: bash app/create-app.sh installs it with the app' }, 2);
}

const pool = new sql.ConnectionPool({
  server, database, port: 1433, connectionTimeout: 30000, requestTimeout: 60000,
  options: { encrypt: true, trustServerCertificate: false, useUTC: true, appName: 'windfarm-deploy-gate' },
  authentication: { type: 'azure-active-directory-access-token', options: { token } },
});
try {
  await pool.connect();
  const row = (await pool.request().query(QUERY)).recordset[0] ?? {};
  const newest = row.Newest ? new Date(row.Newest) : null;
  answer({ rows: Number(row.Rows ?? 0), turbines: Number(row.Turbines ?? 0),
    newest_minutes: newest ? Math.round((Date.now() - newest.getTime()) / 6000) / 10 : null });
} catch (error) {
  // The driver's message can quote the server's name; it never holds the token.
  answer({ error: String(error?.message ?? error).split(token).join('[token]').slice(0, 300) }, 1);
} finally {
  await pool.close().catch(() => {});
}
