import { useTauriBackend } from '@/hooks/useTauriBackend';

/**
 * Shows a loading screen while the backend sidecar is starting.
 * Only renders in Tauri (desktop) mode — in browser mode, children render immediately.
 */
export function DesktopSplash({ children }: { children: React.ReactNode }) {
  const { isTauri, backendReady, backendError } = useTauriBackend();

  // In browser mode, skip the splash entirely
  if (!isTauri || backendReady) {
    return <>{children}</>;
  }

  if (backendError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-zinc-950">
        <div className="text-center space-y-4 max-w-md px-6">
          <div className="text-5xl">&#x26A0;</div>
          <h1 className="text-xl font-semibold text-white">Backend Failed to Start</h1>
          <p className="text-zinc-400 text-sm">
            The Sift backend process could not be reached. Please restart the app.
            If the issue persists, check the logs in the app data directory.
          </p>
          <button
            onClick={() => window.location.reload()}
            className="mt-4 px-4 py-2 rounded bg-indigo-600 text-white text-sm hover:bg-indigo-500 transition"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Loading state
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950">
      <div className="text-center space-y-4">
        <div className="relative mx-auto h-16 w-16">
          <div className="absolute inset-0 rounded-full border-4 border-zinc-800" />
          <div className="absolute inset-0 rounded-full border-4 border-t-indigo-500 animate-spin" />
        </div>
        <h1 className="text-lg font-medium text-white">Starting Sift...</h1>
        <p className="text-sm text-zinc-500">Initializing backend services</p>
      </div>
    </div>
  );
}
