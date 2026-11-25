/**
 * Runs a KQL query on the Eventhouse through its REST address and returns the rows of the result.
 */
import { KUSTO_TIMEOUT_MS } from './config.js';
import { brief } from './fabric.js';

export class KustoError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = 'KustoError';
  }
}

interface KustoV1Table {
  TableName?: string;
  Columns?: { ColumnName: string }[];
  Rows?: unknown[][];
}

/**
 * The rows of the first table of a version 1 answer, each as an object keyed by column name.
 * The first table is the result of the query; the tables after it describe the run.
 */
export function rowsOf(body: unknown): Record<string, unknown>[] {
  const tables = (body as { Tables?: KustoV1Table[] } | null)?.Tables;
  const table = Array.isArray(tables) ? tables[0] : undefined;
  if (!table || !Array.isArray(table.Columns) || !Array.isArray(table.Rows)) {
    throw new KustoError('The Eventhouse answered in a form this app does not know (no Tables[0]).', 502);
  }
  const names = table.Columns.map((c) => c.ColumnName);
  const rows: Record<string, unknown>[] = [];
  for (const row of table.Rows) {
    if (!Array.isArray(row)) {
      // A failure in the middle of a result arrives as an object in place of a row.
      throw new KustoError(`The Eventhouse reported a failure inside the result: ${brief(JSON.stringify(row))}`, 502);
    }
    const record: Record<string, unknown> = {};
    names.forEach((name, i) => (record[name] = row[i]));
    rows.push(record);
  }
  return rows;
}

export interface QueryOptions {
  queryServiceUri: string;
  database: string;
  query: string;
  token: string;
  fetch: typeof fetch;
}

export async function runQuery(options: QueryOptions): Promise<Record<string, unknown>[]> {
  const response = await options.fetch(`${options.queryServiceUri}/v1/rest/query`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${options.token}`,
      Accept: 'application/json',
      'Content-Type': 'application/json; charset=utf-8',
      'x-ms-app': 'windfarm-twin',
    },
    body: JSON.stringify({
      db: options.database,
      csl: options.query,
      properties: { Options: { servertimeout: '00:00:15' } },
    }),
    signal: AbortSignal.timeout(KUSTO_TIMEOUT_MS),
  });
  if (!response.ok) {
    const body = await response.text().catch(() => '');
    throw new KustoError(`The Eventhouse answered ${response.status}: ${brief(body)}`, response.status);
  }
  return rowsOf(await response.json());
}
