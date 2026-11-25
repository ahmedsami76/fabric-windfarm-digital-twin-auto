/**
 * Runs T-SQL on the SQL analytics endpoint of the Lakehouse, with the token the platform issues to the
 * app for SQL. This is Rayfin's own recipe for a Lakehouse ("Add a Fabric resource" in its guide):
 * the driver `mssql`, `encrypt: true`, the token as `azure-active-directory-access-token`, the server
 * from the Lakehouse's `sqlEndpointProperties`, and the item identifier of the Lakehouse as database.
 */
import sql from 'mssql';

import { SQL_CONNECT_TIMEOUT_MS, SQL_REQUEST_TIMEOUT_MS } from './config.js';

export type Row = Record<string, unknown>;

/** Runs several statements on one connection and returns the rows of each, in the same order. */
export type SqlBatch = (statements: string[]) => Promise<Row[][]>;

export class SqlError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SqlError';
  }
}

/**
 * Date and time values arrive as JavaScript dates. The contract carries text, so they become ISO 8601
 * in UTC here, the form the Eventhouse returns them in.
 */
export function plainRows(rows: readonly Row[]): Row[] {
  return rows.map((row) => {
    const plain: Row = {};
    for (const [name, value] of Object.entries(row)) {
      plain[name] = value instanceof Date ? (Number.isNaN(value.getTime()) ? null : value.toISOString()) : value;
    }
    return plain;
  });
}

/** One connection per call: opened, used for every statement, closed. */
export function lakehouseBatch(server: string, database: string, token: string): SqlBatch {
  return async (statements: string[]): Promise<Row[][]> => {
    const pool = new sql.ConnectionPool({
      server,
      database,
      connectionTimeout: SQL_CONNECT_TIMEOUT_MS,
      requestTimeout: SQL_REQUEST_TIMEOUT_MS,
      options: { encrypt: true, trustServerCertificate: false, useUTC: true, appName: 'windfarm-twin' },
      authentication: { type: 'azure-active-directory-access-token', options: { token } },
      pool: { max: 4, min: 0 },
    });
    try {
      await pool.connect();
      const results = await Promise.all(statements.map((statement) => pool.request().query(statement)));
      return results.map((result) => plainRows(result.recordset as Row[]));
    } catch (error) {
      const e = error as { code?: string; message?: string };
      throw new SqlError(`The SQL endpoint of the Lakehouse answered ${e.code ?? 'an error'}: ${e.message ?? String(error)}`);
    } finally {
      await pool.close().catch(() => undefined);
    }
  };
}
