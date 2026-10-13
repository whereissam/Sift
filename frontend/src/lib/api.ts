/**
 * Thin wrapper over `fetch` for the Sift API.
 *
 * The app calls `fetch('/api/...')` directly in older components, which means
 * every caller re-implements the same three things: JSON headers, turning a
 * non-2xx into a useful message, and narrowing `unknown` to a response type.
 * New surfaces use this instead.
 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })

  if (!response.ok) {
    // FastAPI puts the useful part in `detail`; fall back to the status text
    // so the user never sees a bare "Failed to fetch".
    let message = response.statusText || `Request failed (${response.status})`
    try {
      const body = await response.json()
      if (typeof body?.detail === 'string') message = body.detail
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg) message = body.detail[0].msg
    } catch {
      /* body was not JSON — keep the status text */
    }
    throw new ApiError(message, response.status)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export function apiGet<T>(path: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, { method: 'GET', signal })
}

export function apiPost<T>(path: string, body?: unknown, signal?: AbortSignal): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })
}

/** Human-readable message for anything thrown by the helpers above. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message
  if (err instanceof Error) return err.message
  return 'Something went wrong'
}

/** `754.2` -> `12:34`. Subtitle-style, for timestamps in search hits. */
export function formatTimestamp(seconds?: number | null): string {
  if (seconds === undefined || seconds === null || Number.isNaN(seconds)) return ''
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const mm = h ? String(m).padStart(2, '0') : String(m)
  return h
    ? `${h}:${mm}:${String(s).padStart(2, '0')}`
    : `${mm}:${String(s).padStart(2, '0')}`
}

/** Deep-link into the source at a timestamp, when the platform supports it. */
export function sourceLinkAt(sourceUrl?: string | null, seconds?: number | null): string | null {
  if (!sourceUrl) return null
  if (seconds === undefined || seconds === null) return sourceUrl
  const at = Math.floor(seconds)
  if (/youtube\.com|youtu\.be/.test(sourceUrl)) {
    return `${sourceUrl}${sourceUrl.includes('?') ? '&' : '?'}t=${at}s`
  }
  return sourceUrl
}
