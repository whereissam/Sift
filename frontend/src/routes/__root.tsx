import { createRootRoute, Outlet, Link, useLocation } from '@tanstack/react-router'
import { ThemeToggle } from '@/components/theme-toggle'
import { FileAudio, FileVideo, FileText, Scissors, Rss, Settings, Mic } from 'lucide-react'

const NAV_ITEMS = [
  { to: '/audio', label: 'Audio', icon: FileAudio },
  { to: '/video', label: 'Video', icon: FileVideo },
  { to: '/transcribe', label: 'Transcribe', icon: FileText },
  { to: '/clips', label: 'Clips', icon: Scissors },
  { to: '/live', label: 'Live', icon: Mic },
] as const

const UTIL_ITEMS = [
  { to: '/subscriptions', label: 'Feeds', icon: Rss },
  { to: '/settings', label: 'Settings', icon: Settings },
] as const

export const Route = createRootRoute({
  component: () => {
    const location = useLocation()
    const isMainPage = ['/audio', '/video', '/transcribe', '/clips', '/live', '/'].includes(location.pathname)

    return (
      <div className="min-h-screen bg-background text-foreground flex flex-col">
        {/* ─── Top toolbar ─── */}
        <header className="border-b border-border">
          <div className="max-w-3xl mx-auto px-4 sm:px-6">
            <div className="flex items-center h-12 sm:h-14 gap-6">
              {/* Brand mark */}
              <Link to="/audio" className="flex items-center gap-2 shrink-0">
                <img src="/logo.svg" alt="AudioGrab" className="h-6 sm:h-7 w-auto" />
                <span className="text-sm sm:text-base font-bold tracking-tight text-foreground hidden sm:block">
                  AudioGrab
                </span>
              </Link>

              {/* Main nav */}
              <nav className="flex items-center gap-0.5 flex-1 overflow-x-auto">
                {NAV_ITEMS.map(({ to, label, icon: Icon }) => {
                  const active = location.pathname === to || (to === '/audio' && location.pathname === '/')
                  return (
                    <Link
                      key={to}
                      to={to}
                      className={`flex items-center gap-1.5 px-2.5 sm:px-3 py-1.5 text-xs sm:text-sm font-medium transition-colors whitespace-nowrap ${
                        active
                          ? 'text-primary'
                          : 'text-muted-foreground hover:text-foreground'
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5" />
                      {label}
                    </Link>
                  )
                })}
              </nav>

              {/* Utils */}
              <div className="flex items-center gap-1 shrink-0">
                {isMainPage && UTIL_ITEMS.map(({ to, label, icon: Icon }) => (
                  <Link
                    key={to}
                    to={to}
                    className="flex items-center gap-1.5 px-2 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
                    title={label}
                  >
                    <Icon className="w-3.5 h-3.5" />
                    <span className="hidden md:inline">{label}</span>
                  </Link>
                ))}
                <ThemeToggle />
              </div>
            </div>
          </div>
        </header>

        {/* ─── Content ─── */}
        {isMainPage ? (
          <main className="flex-1 flex flex-col">
            <div className="max-w-3xl w-full mx-auto px-4 sm:px-6 py-8 sm:py-12 flex-1">
              <Outlet />
            </div>
            <footer className="border-t border-border">
              <div className="max-w-3xl mx-auto px-4 sm:px-6 py-3">
                <p className="text-[11px] text-muted-foreground">
                  Public content with replay/download enabled only
                </p>
              </div>
            </footer>
          </main>
        ) : (
          <Outlet />
        )}
      </div>
    )
  },
})
