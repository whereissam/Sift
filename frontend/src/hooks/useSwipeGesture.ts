import { useRef, useCallback } from 'react'
import { useDrag } from '@use-gesture/react'
import { useSpring, config } from '@react-spring/web'

interface SwipeGestureOptions {
  onSwipeLeft?: () => void
  onSwipeRight?: () => void
  threshold?: number
  maxDistance?: number
}

export function useSwipeGesture({
  onSwipeLeft,
  onSwipeRight,
  threshold = 80,
  maxDistance = 120,
}: SwipeGestureOptions) {
  const [{ x }, api] = useSpring(() => ({
    x: 0,
    config: config.stiff,
  }))

  const isDragging = useRef(false)

  const bind = useDrag(
    ({ movement: [mx], velocity: [vx], direction: [dx], active, cancel: _cancel }) => {
      isDragging.current = active

      if (active) {
        // Clamp the movement
        const clampedX = Math.max(-maxDistance, Math.min(maxDistance, mx))
        api.start({ x: clampedX, immediate: true })
      } else {
        // Check if swipe threshold was met
        const wasSwipe = Math.abs(mx) > threshold || Math.abs(vx) > 0.5

        if (wasSwipe) {
          if (mx < 0 && dx < 0 && onSwipeLeft) {
            // Swipe left
            api.start({
              x: -maxDistance,
              onRest: () => {
                onSwipeLeft()
                api.start({ x: 0 })
              },
            })
            return
          } else if (mx > 0 && dx > 0 && onSwipeRight) {
            // Swipe right
            api.start({
              x: maxDistance,
              onRest: () => {
                onSwipeRight()
                api.start({ x: 0 })
              },
            })
            return
          }
        }

        // Reset position
        api.start({ x: 0 })
      }
    },
    {
      axis: 'x',
      filterTaps: true,
      rubberband: true,
    }
  )

  const reset = useCallback(() => {
    api.start({ x: 0, immediate: true })
  }, [api])

  return {
    bind,
    x,
    isDragging: isDragging.current,
    reset,
  }
}

// Utility hook for detecting swipe direction
export function useSwipeDirection() {
  const startX = useRef(0)
  const startY = useRef(0)

  const onTouchStart = useCallback((e: React.TouchEvent) => {
    startX.current = e.touches[0].clientX
    startY.current = e.touches[0].clientY
  }, [])

  const getSwipeDirection = useCallback((e: React.TouchEvent): 'left' | 'right' | 'up' | 'down' | null => {
    const deltaX = e.changedTouches[0].clientX - startX.current
    const deltaY = e.changedTouches[0].clientY - startY.current

    const absX = Math.abs(deltaX)
    const absY = Math.abs(deltaY)

    // Minimum swipe distance
    if (absX < 30 && absY < 30) return null

    if (absX > absY) {
      return deltaX > 0 ? 'right' : 'left'
    } else {
      return deltaY > 0 ? 'down' : 'up'
    }
  }, [])

  return {
    onTouchStart,
    getSwipeDirection,
  }
}
