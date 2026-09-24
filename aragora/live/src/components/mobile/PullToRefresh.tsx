/**
 * PullToRefresh - Native-feel pull-to-refresh component.
 *
 * Features:
 * - Smooth rubber-band effect
 * - Progress indicator
 * - Haptic feedback at trigger point
 * - Works with scroll containers
 * - Respects reduced motion preference
 */

'use client';

import React, { useRef, useState, useCallback, useEffect, ReactNode } from 'react';
import { cn } from '@/lib/utils';
import { usePrefersReducedMotion, useIsTouchDevice } from '@/hooks/useMediaQuery';

// =============================================================================
// Types
// =============================================================================

interface PullToRefreshProps {
  children: ReactNode;
  /** Async callback when refresh is triggered */
  onRefresh: () => Promise<void>;
  /** Distance in pixels to trigger refresh */
  threshold?: number;
  /** Maximum pull distance */
  maxPull?: number;
  /** Resistance factor (higher = harder to pull) */
  resistance?: number;
  /** Custom refresh indicator */
  refreshIndicator?: ReactNode;
  /** Custom loading indicator */
  loadingIndicator?: ReactNode;
  /** Custom class name for container */
  className?: string;
  /** Disabled state */
  disabled?: boolean;
}

type RefreshState = 'idle' | 'pulling' | 'triggered' | 'refreshing';

// =============================================================================
// Haptic feedback
// =============================================================================

function triggerHaptic() {
  if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
    navigator.vibrate(15);
  }
}

// =============================================================================
// Default indicators
// =============================================================================

function DefaultRefreshIndicator({ progress }: { progress: number }) {
  return (
    <div
      className="flex items-center justify-center"
      style={{
        opacity: Math.min(1, progress),
        transform: `scale(${Math.min(1, 0.5 + progress * 0.5)}) rotate(${progress * 180}deg)`,
      }}
    >
      <svg
        className="w-6 h-6 text-muted-foreground"
        fill="none"
        stroke="currentColor"
        viewBox="0 0 24 24"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          strokeWidth={2}
          d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
        />
      </svg>
    </div>
  );
}

function DefaultLoadingIndicator() {
  return (
    <svg className="animate-spin w-6 h-6 text-primary" fill="none" viewBox="0 0 24 24">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
      />
    </svg>
  );
}

// =============================================================================
// Component
// =============================================================================

export function PullToRefresh({
  children,
  onRefresh,
  threshold = 80,
  maxPull = 150,
  resistance = 2.5,
  refreshIndicator,
  loadingIndicator,
  className,
  disabled = false,
}: PullToRefreshProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const startYRef = useRef<number>(0);
  const currentYRef = useRef<number>(0);

  const [pullDistance, setPullDistance] = useState(0);
  const [state, setState] = useState<RefreshState>('idle');
  const [hasTriggeredHaptic, setHasTriggeredHaptic] = useState(false);

  const prefersReducedMotion = usePrefersReducedMotion();
  const isTouch = useIsTouchDevice();

  // Calculate the visual distance with rubber-band effect
  const visualDistance = Math.min(maxPull, pullDistance > 0 ? pullDistance / resistance : 0);

  // Progress towards threshold (0-1)
  const progress = Math.min(1, visualDistance / threshold);

  // Handle touch start
  const handleTouchStart = useCallback(
    (e: TouchEvent) => {
      if (disabled || state === 'refreshing') return;

      const container = containerRef.current;
      if (!container) return;

      // Only start if at the top of the scroll
      if (container.scrollTop > 0) return;

      startYRef.current = e.touches[0].clientY;
      currentYRef.current = e.touches[0].clientY;
      setHasTriggeredHaptic(false);
    },
    [disabled, state],
  );

  // Handle touch move
  const handleTouchMove = useCallback(
    (e: TouchEvent) => {
      if (disabled || state === 'refreshing') return;
      if (startYRef.current === 0) return;

      const container = containerRef.current;
      if (!container) return;

      // Only allow pull when at top
      if (container.scrollTop > 0) {
        startYRef.current = 0;
        setPullDistance(0);
        setState('idle');
        return;
      }

      currentYRef.current = e.touches[0].clientY;
      const diff = currentYRef.current - startYRef.current;

      if (diff > 0) {
        // Prevent default scroll when pulling down
        e.preventDefault();
        setPullDistance(diff);
        setState('pulling');

        // Trigger haptic at threshold
        if (diff / resistance >= threshold && !hasTriggeredHaptic) {
          triggerHaptic();
          setHasTriggeredHaptic(true);
          setState('triggered');
        } else if (diff / resistance < threshold) {
          setState('pulling');
        }
      }
    },
    [disabled, state, threshold, resistance, hasTriggeredHaptic],
  );

  // Handle touch end
  const handleTouchEnd = useCallback(async () => {
    if (disabled) return;

    const wasTriggered = state === 'triggered';
    startYRef.current = 0;

    if (wasTriggered) {
      setState('refreshing');
      setPullDistance(threshold * resistance); // Hold at threshold while refreshing

      try {
        await onRefresh();
      } finally {
        // Animate back to top
        setPullDistance(0);
        setState('idle');
      }
    } else {
      setPullDistance(0);
      setState('idle');
    }
  }, [disabled, state, threshold, resistance, onRefresh]);

  // Attach touch handlers
  useEffect(() => {
    const container = containerRef.current;
    if (!container || !isTouch) return;

    container.addEventListener('touchstart', handleTouchStart, { passive: true });
    container.addEventListener('touchmove', handleTouchMove, { passive: false });
    container.addEventListener('touchend', handleTouchEnd);

    return () => {
      container.removeEventListener('touchstart', handleTouchStart);
      container.removeEventListener('touchmove', handleTouchMove);
      container.removeEventListener('touchend', handleTouchEnd);
    };
  }, [isTouch, handleTouchStart, handleTouchMove, handleTouchEnd]);

  return (
    <div ref={containerRef} className={cn('relative overflow-auto h-full', className)}>
      {/* Refresh indicator */}
      <div
        className={cn(
          'absolute left-0 right-0 flex items-center justify-center',
          'pointer-events-none z-10',
          prefersReducedMotion ? '' : 'transition-transform duration-200',
        )}
        style={{
          height: `${threshold}px`,
          top: `-${threshold}px`,
          transform: `translateY(${visualDistance}px)`,
        }}
      >
        {state === 'refreshing'
          ? loadingIndicator || <DefaultLoadingIndicator />
          : refreshIndicator || <DefaultRefreshIndicator progress={progress} />}
      </div>

      {/* Content */}
      <div
        ref={contentRef}
        className={cn(prefersReducedMotion ? '' : 'transition-transform duration-200')}
        style={{ transform: state !== 'idle' ? `translateY(${visualDistance}px)` : undefined }}
      >
        {children}
      </div>
    </div>
  );
}

export default PullToRefresh;
