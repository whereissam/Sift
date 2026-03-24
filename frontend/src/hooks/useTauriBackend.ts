import { useState, useEffect } from 'react';

/**
 * Detects if we're running inside Tauri and manages backend readiness.
 * In browser mode, the backend is assumed to be running externally.
 */
export function useTauriBackend() {
  const isTauri = '__TAURI__' in window;
  const [backendReady, setBackendReady] = useState(!isTauri);
  const [backendError, setBackendError] = useState(false);

  useEffect(() => {
    if (!isTauri) return;

    let cancelled = false;

    async function listenForBackend() {
      try {
        const { listen } = await import('@tauri-apps/api/event');

        const unlisten = await listen<boolean>('backend-ready', (event) => {
          if (cancelled) return;
          if (event.payload) {
            setBackendReady(true);
          } else {
            setBackendError(true);
          }
        });

        // Also listen for unexpected termination
        const unlistenTerm = await listen('backend-terminated', () => {
          if (cancelled) return;
          setBackendReady(false);
          setBackendError(true);
        });

        return () => {
          cancelled = true;
          unlisten();
          unlistenTerm();
        };
      } catch {
        // Not in Tauri — fallback to browser mode
        if (!cancelled) setBackendReady(true);
      }
    }

    listenForBackend();
    return () => { cancelled = true; };
  }, [isTauri]);

  /**
   * Returns the base URL for API calls.
   * In Tauri, we hit localhost directly (no Vite proxy).
   * In browser, we use relative /api paths (proxied by Vite).
   */
  const apiBaseUrl = isTauri ? 'http://localhost:8000' : '';

  return { isTauri, backendReady, backendError, apiBaseUrl };
}
