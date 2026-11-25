/**
 * The service principal the app reads the Eventhouse as, for values that are seconds old.
 *
 * A Fabric app runs as its owner, and the platform gives it no token the Eventhouse accepts. A service
 * principal gets one from Microsoft Entra ID by itself. Its tenant, its application (client) ID and its
 * secret are three secrets of the app, set once with `npx rayfin secret set` (`app/create-principal.sh`
 * of the repository does it). Without them this route is simply not there, and the page reads the
 * Lakehouse instead.
 */
import {
  ENTRA_LOGIN,
  ENTRA_TIMEOUT_MS,
  KUSTO_SCOPE,
  SECRET_CLIENT_ID,
  SECRET_CLIENT_SECRET,
  SECRET_TENANT_ID,
} from './config.js';
import { brief } from './fabric.js';

export interface Principal {
  tenantId: string;
  clientId: string;
  clientSecret: string;
}

/** No service principal is set up. Not a fault: the Lakehouse route is used. */
export class NoPrincipal extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'NoPrincipal';
  }
}

/** The app has secrets, or should have, and the host could not hand them over. */
export class SecretsUnreadable extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SecretsUnreadable';
  }
}

/** Microsoft Entra ID did not give the service principal a token. */
export class PrincipalRefused extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'PrincipalRefused';
  }
}

const GUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * Reads the three secrets. `secret` returns the value of one. When the app has no secret of that name
 * it returns nothing or throws the host's "No value available for secret …": that is "not set up".
 * Anything else it throws means the host could not read the secrets at all, which is a failure and
 * is reported as one, with what the host said.
 */
export function readPrincipal(secret: (name: string) => string | undefined): Principal {
  const read = (name: string): string => {
    let value: string | undefined;
    try {
      value = secret(name);
    } catch (error) {
      const said = error instanceof Error ? error.message : String(error);
      if (!/no value available for secret/i.test(said)) {
        throw new SecretsUnreadable(`The secrets of the app could not be read (${name}): ${brief(said)}`);
      }
      value = undefined;
    }
    value = value?.trim();
    if (!value) {
      throw new NoPrincipal(
        `No service principal is set up for the Eventhouse: the app has no secret ${name}. The values come from the Lakehouse until app/create-principal.sh has been run.`
      );
    }
    return value;
  };
  const tenantId = read(SECRET_TENANT_ID);
  const clientId = read(SECRET_CLIENT_ID);
  const clientSecret = read(SECRET_CLIENT_SECRET);
  if (!GUID.test(tenantId)) throw new NoPrincipal(`The secret ${SECRET_TENANT_ID} is not a tenant ID (a GUID).`);
  if (!GUID.test(clientId)) throw new NoPrincipal(`The secret ${SECRET_CLIENT_ID} is not an application ID (a GUID).`);
  return { tenantId, clientId, clientSecret };
}

let held: { key: string; token: string; until: number } | undefined;

/** Forget the token of the service principal. Used by the connection check and by the tests. */
export function clearPrincipalToken(): void {
  held = undefined;
}

/**
 * A token for the Eventhouse, issued to the service principal (client credentials). It is kept in
 * memory until five minutes before it expires, so most calls ask Entra nothing.
 */
export async function principalToken(
  principal: Principal,
  fetchImpl: typeof fetch,
  now: number = Date.now()
): Promise<string> {
  const key = `${principal.tenantId}/${principal.clientId}`;
  if (held && held.key === key && now < held.until) return held.token;
  let response: Response;
  try {
    response = await fetchImpl(`${ENTRA_LOGIN}/${principal.tenantId}/oauth2/v2.0/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded', Accept: 'application/json' },
      body: new URLSearchParams({
        grant_type: 'client_credentials',
        client_id: principal.clientId,
        client_secret: principal.clientSecret,
        scope: KUSTO_SCOPE,
      }).toString(),
      signal: AbortSignal.timeout(ENTRA_TIMEOUT_MS),
    });
  } catch (error) {
    throw new PrincipalRefused(`Microsoft Entra ID could not be reached: ${brief(error)}`);
  }
  const text = await response.text().catch(() => '');
  let body: { access_token?: string; expires_in?: number; error?: string; error_description?: string } = {};
  try {
    body = JSON.parse(text) as typeof body;
  } catch {
    // Not JSON: the status and the text say what there is to say.
  }
  if (!response.ok || !body.access_token) {
    // The description of Entra names the application and the reason (AADSTS…); it never repeats the secret.
    const reason = body.error_description ?? body.error ?? text;
    throw new PrincipalRefused(
      `Microsoft Entra ID gave the service principal no token (${response.status}): ${brief(reason).replaceAll(principal.clientSecret, '…')}`
    );
  }
  const lifetimeS = Number.isFinite(body.expires_in) ? Number(body.expires_in) : 3600;
  held = { key, token: body.access_token, until: now + Math.max(60, lifetimeS - 300) * 1000 };
  return held.token;
}
