/**
 * Looks up, by name, the Fabric items the twin reads: the workspace, the KQL database with its query
 * address, and the published data agent. One lookup per ten minutes; the result is kept in memory.
 */
import {
  DATA_AGENT_NAME,
  FABRIC_API,
  FABRIC_TIMEOUT_MS,
  KQL_DATABASE_NAME,
  LAKEHOUSE_NAME,
  LOOKUP_TTL_MS,
  WORKSPACE_NAME,
} from './config.js';

/** What a function needs from its context. Reading the token throws when the host supplied none. */
export interface Access {
  fabricToken: () => string;
  fetch: typeof fetch;
}

/** Where the Lakehouse answers SQL: the server of its SQL analytics endpoint, and its item identifier. */
export interface LakehouseLookup {
  workspaceId: string;
  lakehouseId: string;
  lakehouseName: string;
  /** The item identifier of the SQL analytics endpoint, which is an item of its own. Null when Fabric does not give it. */
  sqlEndpointId: string | null;
  sqlServer: string;
}

export interface Lookup {
  workspaceId: string;
  kqlDatabaseId: string;
  kqlDatabaseName: string;
  queryServiceUri: string;
  /** Null when no item with the agent's name exists in the workspace. */
  dataAgentId: string | null;
  dataAgentEndpoint: string | null;
}

export class FabricError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
    this.name = 'FabricError';
  }
}

interface FabricItem {
  id: string;
  displayName: string;
  type?: string;
  properties?: {
    queryServiceUri?: string;
    sqlEndpointProperties?: { connectionString?: string | null; id?: string | null; provisioningStatus?: string } | null;
  };
}

/** The text of an error without anything that could be a secret: one line, at most 300 characters. */
export function brief(error: unknown): string {
  const text = error instanceof Error ? error.message : String(error);
  return text
    .replace(/\s+/g, ' ')
    .replace(/Bearer\s+[A-Za-z0-9._~+/=-]+/g, 'Bearer …')
    .replace(/(client_secret|password)=[^&\s]+/gi, '$1=…')
    .slice(0, 300);
}

async function listAll(url: string, token: string, fetchImpl: typeof fetch): Promise<FabricItem[]> {
  const items: FabricItem[] = [];
  let next: string | undefined = url;
  for (let page = 0; next && page < 50; page++) {
    const response: Response = await fetchImpl(next, {
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
      signal: AbortSignal.timeout(FABRIC_TIMEOUT_MS),
    });
    if (!response.ok) {
      const body = await response.text().catch(() => '');
      const path = new URL(next).pathname;
      throw new FabricError(`Fabric API answered ${response.status} for ${path}: ${brief(body)}`, response.status);
    }
    const body = (await response.json()) as { value?: FabricItem[]; continuationUri?: string | null };
    items.push(...(body.value ?? []));
    next = body.continuationUri ?? undefined;
  }
  return items;
}

let cached: { at: number; value: Lookup } | undefined;
let cachedLakehouse: { at: number; value: LakehouseLookup } | undefined;

/** Forget the looked-up identifiers. Used by the connection check and by the tests. */
export function clearLookup(): void {
  cached = undefined;
  cachedLakehouse = undefined;
}

async function findWorkspace(token: string, fetchImpl: typeof fetch): Promise<FabricItem> {
  const workspaces = await listAll(`${FABRIC_API}/workspaces`, token, fetchImpl);
  const workspace = workspaces.find((w) => w.displayName === WORKSPACE_NAME);
  if (!workspace) {
    throw new FabricError(
      `The identity of the app sees ${workspaces.length} workspaces and none is named ${WORKSPACE_NAME}.`,
      404
    );
  }
  return workspace;
}

/** The Lakehouse and the server of its SQL analytics endpoint, by name. Kept for ten minutes. */
export async function lookupLakehouse(access: Access, now: number = Date.now()): Promise<LakehouseLookup> {
  if (cachedLakehouse && now - cachedLakehouse.at < LOOKUP_TTL_MS) return cachedLakehouse.value;
  const token = access.fabricToken();
  const workspace = await findWorkspace(token, access.fetch);
  const lakehouses = await listAll(`${FABRIC_API}/workspaces/${workspace.id}/lakehouses`, token, access.fetch);
  const lakehouse = lakehouses.find((l) => l.displayName === LAKEHOUSE_NAME);
  if (!lakehouse) {
    throw new FabricError(`Workspace ${WORKSPACE_NAME} has no Lakehouse named ${LAKEHOUSE_NAME}.`, 404);
  }
  const endpoint = lakehouse.properties?.sqlEndpointProperties;
  const sqlServer = endpoint?.connectionString;
  if (!sqlServer) {
    throw new FabricError(
      `Fabric did not return the SQL endpoint of Lakehouse ${LAKEHOUSE_NAME} (state: ${endpoint?.provisioningStatus ?? 'not given'}).`,
      502
    );
  }
  const value: LakehouseLookup = {
    workspaceId: workspace.id,
    lakehouseId: lakehouse.id,
    lakehouseName: lakehouse.displayName,
    sqlEndpointId: endpoint?.id ?? null,
    sqlServer,
  };
  cachedLakehouse = { at: now, value };
  return value;
}

export async function lookup(access: Access, now: number = Date.now()): Promise<Lookup> {
  if (cached && now - cached.at < LOOKUP_TTL_MS) return cached.value;
  const token = access.fabricToken();

  const workspace = await findWorkspace(token, access.fetch);

  const base = `${FABRIC_API}/workspaces/${workspace.id}`;
  const [databases, items] = await Promise.all([
    listAll(`${base}/kqlDatabases`, token, access.fetch),
    listAll(`${base}/items`, token, access.fetch),
  ]);
  const database = databases.find((d) => d.displayName === KQL_DATABASE_NAME);
  if (!database) {
    throw new FabricError(`Workspace ${WORKSPACE_NAME} has no KQL database named ${KQL_DATABASE_NAME}.`, 404);
  }
  const queryServiceUri = database.properties?.queryServiceUri;
  if (!queryServiceUri) {
    throw new FabricError(`Fabric did not return the query address of KQL database ${KQL_DATABASE_NAME}.`, 502);
  }
  // The item type of a data agent is DataAgent; items created in 2025 can still carry AISkill.
  const agent = items.find(
    (i) => i.displayName === DATA_AGENT_NAME && (i.type === 'DataAgent' || i.type === 'AISkill')
  );

  const value: Lookup = {
    workspaceId: workspace.id,
    kqlDatabaseId: database.id,
    kqlDatabaseName: database.displayName,
    queryServiceUri: queryServiceUri.replace(/\/+$/, ''),
    dataAgentId: agent?.id ?? null,
    dataAgentEndpoint: agent
      ? `${FABRIC_API}/mcp/workspaces/${workspace.id}/dataagents/${agent.id}/agent`
      : null,
  };
  cached = { at: now, value };
  return value;
}
