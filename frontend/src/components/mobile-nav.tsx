import { useState, useEffect } from 'react'
import { Link, useLocation } from '@tanstack/react-router'
import { Menu, X, Home, Info, Sparkles, ListOrdered, Settings } from 'lucide-react'
import { Button } from '@/components/ui/button'

import { useSwipeDirection } from '@/hooks/useSwipeGesture'

const NAV_ITEMS = [
  { to: '/', label: 'Home', icon: Home },
  { to: '/about', label: 'About', icon: Info },
  { to: '/features', label: 'Features', icon: Sparkles },
  { to: '/subscriptions', label: 'Subscriptions', icon: ListOrdered },
  { to: '/settings', label: 'Settings', icon: Settings },
] as const

export function MobileNav() {
  const [isOpen, setIsOpen] = useState(false)
  const location = useLocation()
  const { onTouchStart, getSwipeDirection } = useSwipeDirection()

  // Close menu on route change
  useEffect(() => {
    setIsOpen(false)
  }, [location.pathname])

  // Close menu on escape key
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setIsOpen(false)
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [])

  const handleTouchEnd = (e: React.TouchEvent) => {
    const direction = getSwipeDirection(e)
    if (direction === 'left' && isOpen) {
      setIsOpen(false)
    } else if (direction === 'right' && !isOpen) {
      setIsOpen(true)
    }
  }

  return (
    <div
      className="sm:hidden"
      onTouchStart={onTouchStart}
      onTouchEnd={handleTouchEnd}
    >
      <Button
        variant="ghost"
        size="icon"
        onClick={() => setIsOpen(!isOpen)}
        className="h-12 w-12 touch-target"
        aria-expanded={isOpen}
        aria-controls="mobile-menu"
        aria-label={isOpen ? 'Close menu' : 'Open menu'}
      >
        {isOpen ? (
          <X className="h-6 w-6" />
        ) : (
          <Menu className="h-6 w-6" />
        )}
      </Button>

      {/* Backdrop */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/20 z-40"
          onClick={() => setIsOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Menu */}
      <div
        id="mobile-menu"
        className={`
          fixed top-16 left-0 right-0 z-50
          bg-background border-b shadow-xl
          transform transition-transform duration-200 ease-out
          ${isOpen ? 'translate-y-0' : '-translate-y-full pointer-events-none'}
        `}
        role="navigation"
        aria-label="Mobile navigation"
      >
        <div className="container mx-auto px-4 py-3 pb-safe">
          <nav className="flex flex-col gap-1">
            {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
              <Link
                key={to}
                to={to}
                className={`
                  flex items-center gap-3 px-4 py-3 rounded-lg
                  text-foreground hover:bg-muted active:bg-muted/80
                  [&.active]:bg-primary/10 [&.active]:text-primary [&.active]:font-medium
                  transition-colors touch-target min-h-[48px]
                `}
                onClick={() => setIsOpen(false)}
              >
                <Icon className="h-5 w-5 flex-shrink-0" />
                <span className="text-base">{label}</span>
              </Link>
            ))}
          </nav>
        </div>
      </div>
    </div>
  )
}