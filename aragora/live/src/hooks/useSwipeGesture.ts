'use client';

import { useRef, useEffect, useCallback } from 'react';

export type SwipeDirection = 'left' | 'right' | 'up' | 'down';

export interface SwipeGestureOptions {
  /** Minimum distance in pixels to trigger a swipe */
  threshold?: number;
  /** Maximum time in milliseconds for the swipe gesture */
  maxTime?: number;
  /** Callback when swipe is detected */
  onSwipe?: (direction: SwipeDirection) => void;
  /** Callback for specific directions */
  onSwipeLeft?: () => void;
  onSwipeRight?: () => void;
  onSwipeUp?: () => void;
  onSwipeDown?: () => void;
  /** Whether the gesture is enabled */
  enabled?: boolean;
}

interface TouchState {
  startX: number;
  startY: number;
  startTime: number;
}

/**
 * Hook for detecting swipe gestures on touch devices.
 *
 * @example
 * ```tsx
 * const ref = useSwipeGesture({
 *   onSwipeRight: () => openSidebar(),
 *   onSwipeLeft: () => closeSidebar(),
 *   threshold: 50,
 * });
 *
 * return <div ref={ref}>...</div>;
 * ```
 */
export function useSwipeGesture<T extends HTMLElement = HTMLElement>(
  options: SwipeGestureOptions = {},
) {
  const {
    threshold = 50,
    maxTime = 300,
    onSwipe,
    onSwipeLeft,
    onSwipeRight,
    onSwipeUp,
    onSwipeDown,
    enabled = true,
  } = options;

  const ref = useRef<T>(null);
  const touchState = useRef<TouchState | null>(null);

  const handleTouchStart = useCallback(
    (e: TouchEvent) => {
      if (!enabled) return;
      const touch = e.touches[0];
      touchState.current = { startX: touch.clientX, startY: touch.clientY, startTime: Date.now() };
    },
    [enabled],
  );

  const handleTouchEnd = useCallback(
    (e: TouchEvent) => {
      if (!enabled || !touchState.current) return;

      const touch = e.changedTouches[0];
      const { startX, startY, startTime } = touchState.current;
      const endX = touch.clientX;
      const endY = touch.clientY;
      const endTime = Date.now();

      // Check if gesture was quick enough
      const timeDiff = endTime - startTime;
      if (timeDiff > maxTime) {
        touchState.current = null;
        return;
      }

      const diffX = endX - startX;
      const diffY = endY - startY;
      const absX = Math.abs(diffX);
      const absY = Math.abs(diffY);

      // Determine if horizontal or vertical swipe
      let direction: SwipeDirection | null = null;

      if (absX > absY && absX > threshold) {
        // Horizontal swipe
        direction = diffX > 0 ? 'right' : 'left';
      } else if (absY > absX && absY > threshold) {
        // Vertical swipe
        direction = diffY > 0 ? 'down' : 'up';
      }

      if (direction) {
        onSwipe?.(direction);
        switch (direction) {
          case 'left':
            onSwipeLeft?.();
            break;
          case 'right':
            onSwipeRight?.();
            break;
          case 'up':
            onSwipeUp?.();
            break;
          case 'down':
            onSwipeDown?.();
            break;
        }
      }

      touchState.current = null;
    },
    [enabled, threshold, maxTime, onSwipe, onSwipeLeft, onSwipeRight, onSwipeUp, onSwipeDown],
  );

  useEffect(() => {
    const element = ref.current;
    if (!element || !enabled) return;

    element.addEventListener('touchstart', handleTouchStart, { passive: true });
    element.addEventListener('touchend', handleTouchEnd, { passive: true });

    return () => {
      element.removeEventListener('touchstart', handleTouchStart);
      element.removeEventListener('touchend', handleTouchEnd);
    };
  }, [enabled, handleTouchStart, handleTouchEnd]);

  return ref;
}

/**
 * Hook for detecting edge swipes (from screen edges).
 * Useful for opening sidebars/drawers.
 *
 * @example
 * ```tsx
 * useEdgeSwipe({
 *   edge: 'left',
 *   onSwipe: () => openSidebar(),
 * });
 * ```
 */
export function useEdgeSwipe(options: {
  edge: 'left' | 'right';
  onSwipe: () => void;
  /** Distance from edge in pixels to start detecting */
  edgeWidth?: number;
  /** Minimum swipe distance */
  threshold?: number;
  enabled?: boolean;
}) {
  const { edge, onSwipe, edgeWidth = 20, threshold = 50, enabled = true } = options;

  const touchState = useRef<{ startX: number; startY: number } | null>(null);

  useEffect(() => {
    if (!enabled) return;

    const handleTouchStart = (e: TouchEvent) => {
      const touch = e.touches[0];
      const x = touch.clientX;
      const windowWidth = window.innerWidth;

      // Check if touch started at the edge
      const isLeftEdge = edge === 'left' && x < edgeWidth;
      const isRightEdge = edge === 'right' && x > windowWidth - edgeWidth;

      if (isLeftEdge || isRightEdge) {
        touchState.current = { startX: x, startY: touch.clientY };
      }
    };

    const handleTouchEnd = (e: TouchEvent) => {
      if (!touchState.current) return;

      const touch = e.changedTouches[0];
      const diffX = touch.clientX - touchState.current.startX;
      const diffY = Math.abs(touch.clientY - touchState.current.startY);

      // Check if swipe was primarily horizontal
      if (diffY < Math.abs(diffX) && Math.abs(diffX) > threshold) {
        // Left edge: swipe right opens
        // Right edge: swipe left opens
        const isValidSwipe = (edge === 'left' && diffX > 0) || (edge === 'right' && diffX < 0);

        if (isValidSwipe) {
          onSwipe();
        }
      }

      touchState.current = null;
    };

    document.addEventListener('touchstart', handleTouchStart, { passive: true });
    document.addEventListener('touchend', handleTouchEnd, { passive: true });

    return () => {
      document.removeEventListener('touchstart', handleTouchStart);
      document.removeEventListener('touchend', handleTouchEnd);
    };
  }, [edge, onSwipe, edgeWidth, threshold, enabled]);
}

export default useSwipeGesture;
