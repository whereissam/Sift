/**
 * Desktop (Tauri) vs browser: where the API lives.
 *
 * In the browser the SPA is served next to the API (nginx, or Vite's dev
 * proxy), so components call relative `/api/...` URLs. The Tauri webview is
 * served from `tauri://localhost` (`http://tauri.localhost` on Windows) and
 * the embedded backend listens on http://localhost:8000, so relative URLs
 * never reached it. Everything here leaves browser behaviour unchanged.
 */
import { isTauri } from '@tauri-apps/api/core'

/** True inside the Tauri webview. Tauri 2 sets this before page scripts run. */
export const IS_TAURI = isTauri()

/** The embedded backend in the desktop app; '' in the browser. */
export const API_BASE = IS_TAURI ? 'http://localhost:8000' : ''

/** An `/api/...` path as a URL that reaches the backend. */
export function apiUrl(path: string): string {
  return IS_TAURI && path.startsWith('/api') ? `${API_BASE}${path}` : path
}

/** A WebSocket URL for an `/api/...` path. */
export function wsUrl(path: string): string {
  if (IS_TAURI) return `ws://localhost:8000${path}`
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}

/** Rewrite a fetch target that points at this page's own `/api`. */
export function rewriteFetchTarget(input: RequestInfo | URL): RequestInfo | URL {
  if (typeof input === 'string') return apiUrl(input)
  const url = new URL(input instanceof Request ? input.url : input.href)
  if (url.origin !== window.location.origin || !url.pathname.startsWith('/api')) return input
  const target = `${API_BASE}${url.pathname}${url.search}`
  return input instanceof Request ? new Request(target, input) : target
}

/**
 * In the desktop app, send every relative `/api` fetch to the backend.
 *
 * Components call `fetch('/api/...')` in ~60 places; patching fetch once at
 * startup covers all of them, and anything added later.
 */
export function installDesktopFetch(): void {
  if (!IS_TAURI) return
  const original = window.fetch.bind(window)
  window.fetch = (input, init) => original(rewriteFetchTarget(input), init)
}
