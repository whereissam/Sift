// Server-communication helpers (pure where possible so they can be unit-tested).

export const DEFAULT_SERVER = 'http://localhost:8000';

export type CaptureAction = 'download' | 'transcribe';

/** Trim whitespace and any trailing slashes from a server URL. */
export function normalizeServerUrl(input: string): string {
  return input.trim().replace(/\/+$/, '');
}

/** Build the quick-add URL hitting the server's GET /api/add endpoint. */
export function buildAddUrl(serverUrl: string, pageUrl: string, action: CaptureAction): string {
  const params = new URLSearchParams({ url: pageUrl, action });
  return `${normalizeServerUrl(serverUrl)}/api/add?${params.toString()}`;
}

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]']);

/** True for loopback hostnames as reported by `URL.hostname`. */
export function isLoopbackHost(hostname: string): boolean {
  return LOOPBACK_HOSTS.has(hostname.toLowerCase());
}

/**
 * True when traffic to `serverUrl` would cross the network unencrypted: any
 * non-https URL whose host is not loopback. Unparseable URLs count as insecure
 * (fail closed).
 */
export function isInsecureRemoteServer(serverUrl: string): boolean {
  let parsed: URL;
  try {
    parsed = new URL(normalizeServerUrl(serverUrl));
  } catch {
    return true;
  }
  if (parsed.protocol === 'https:') return false;
  return !(parsed.protocol === 'http:' && isLoopbackHost(parsed.hostname));
}

/** The origin used to key per-server consent, or null if unparseable. */
export function serverOrigin(serverUrl: string): string | null {
  try {
    return new URL(normalizeServerUrl(serverUrl)).origin;
  } catch {
    return null;
  }
}

/**
 * Decide whether the API key may be attached to a request to `serverUrl`.
 *
 * - `none`: no key configured, send nothing.
 * - `send`: https or loopback http, or the user explicitly allowed cleartext
 *   for this exact origin.
 * - `needs-confirmation`: a key is set and the server is remote plain http; the
 *   key must not be sent until the user confirms for this origin.
 */
export type ApiKeyDecision = 'none' | 'send' | 'needs-confirmation';

export function apiKeyDecision(
  serverUrl: string,
  apiKey: string,
  allowedInsecureOrigins: readonly string[],
): ApiKeyDecision {
  if (!apiKey) return 'none';
  if (!isInsecureRemoteServer(serverUrl)) return 'send';
  const origin = serverOrigin(serverUrl);
  if (origin && origin !== 'null' && allowedInsecureOrigins.includes(origin)) return 'send';
  return 'needs-confirmation';
}

/** Derive the `<origin>/*` match pattern used to request host permission. */
export function originPattern(serverUrl: string): string {
  const { origin } = new URL(normalizeServerUrl(serverUrl));
  return `${origin}/*`;
}
