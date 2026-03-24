import * as React from 'react'
import { useSpring, animated, config } from '@react-spring/web'

const AnimatedDiv = animated.div as React.FC<React.HTMLAttributes<HTMLDivElement> & { style?: Record<string, unknown>; ref?: React.Ref<HTMLDivElement> }>
import { useDrag } from '@use-gesture/react'
import { X } from 'lucide-react'
import { cn } from '@/lib/utils'

interface BottomSheetProps {
  open: boolean
  onClose: () => void
  children: React.ReactNode
  title?: string
  snapPoints?: number[]
  className?: string
}

export function BottomSheet({
  open,
  onClose,
  children,
  title,
  snapPoints = [0.5, 0.9],
  className,
}: BottomSheetProps) {
  const [currentSnap, setCurrentSnap] = React.useState(0)
  const containerRef = React.useRef<HTMLDivElement>(null)

  const maxHeight = typeof window !== 'undefined' ? window.innerHeight * 0.9 : 600

  const [{ y }, api] = useSpring(() => ({
    y: maxHeight,
    config: config.stiff,
  }))

  React.useEffect(() => {
    if (open) {
      const targetHeight = maxHeight * (1 - snapPoints[currentSnap])
      api.start({ y: targetHeight })
    } else {
      api.start({ y: maxHeight })
    }
  }, [open, currentSnap, api, maxHeight, snapPoints])

  const bind = useDrag(
    ({ movement: [, my], velocity: [, vy], direction: [, dy], cancel: _cancel, active }) => {
      const currentY = maxHeight * (1 - snapPoints[currentSnap])

      if (active) {
        api.start({ y: currentY + my, immediate: true })
      } else {
        // Determine if we should close or snap
        const newY = currentY + my

        if (vy > 0.5 && dy > 0) {
          // Fast swipe down - close
          onClose()
          return
        }

        if (newY > maxHeight * 0.7) {
          // Dragged past threshold - close
          onClose()
          return
        }

        // Find nearest snap point
        const relativePosition = 1 - newY / maxHeight
        let nearestSnap = 0
        let minDistance = Math.abs(snapPoints[0] - relativePosition)

        snapPoints.forEach((snap, index) => {
          const distance = Math.abs(snap - relativePosition)
          if (distance < minDistance) {
            minDistance = distance
            nearestSnap = index
          }
        })

        setCurrentSnap(nearestSnap)
        api.start({ y: maxHeight * (1 - snapPoints[nearestSnap]) })
      }
    },
    {
      from: () => [0, y.get()],
      filterTaps: true,
      bounds: { top: 0 },
      rubberband: true,
    }
  )

  if (!open) return null

  return (
    <>
      {/* Backdrop */}
      <AnimatedDiv
        className="fixed inset-0 bg-black/50 z-40"
        style={{
          opacity: y.to([0, maxHeight], [1, 0]) as unknown as number,
        }}
        onClick={onClose}
      />

      {/* Sheet */}
      <AnimatedDiv
        ref={containerRef}
        className={cn(
          'fixed left-0 right-0 bottom-0 z-50 bg-background rounded-t-2xl shadow-xl',
          'touch-none pb-safe',
          className
        )}
        style={{
          y,
          maxHeight: `${maxHeight}px`,
        }}
      >
        {/* Drag handle */}
        <div
          {...bind()}
          className="flex flex-col items-center pt-3 pb-2 cursor-grab active:cursor-grabbing"
        >
          <div className="w-12 h-1.5 bg-muted-foreground/30 rounded-full" />
        </div>

        {/* Header */}
        {title && (
          <div className="flex items-center justify-between px-4 pb-3 border-b">
            <h2 className="text-lg font-semibold">{title}</h2>
            <button
              onClick={onClose}
              className="p-2 -mr-2 rounded-full hover:bg-muted touch-target"
            >
              <X className="h-5 w-5" />
            </button>
          </div>
        )}

        {/* Content */}
        <div className="overflow-y-auto overscroll-contain" style={{ maxHeight: `${maxHeight - 80}px` }}>
          {children}
        </div>
      </AnimatedDiv>
    </>
  )
}
