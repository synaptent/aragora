/**
 * TouchButton - Accessible touch-optimized button with haptic feedback.
 *
 * Features:
 * - Minimum 44x44px touch target (WCAG 2.5.5)
 * - Visual and haptic feedback
 * - Loading state with spinner
 * - Long-press support
 * - Ripple effect on touch
 */

'use client';

import React, { useRef, useState, useCallback, useEffect, forwardRef } from 'react';
import { cn } from '@/lib/utils';
import { usePrefersReducedMotion } from '@/hooks/useMediaQuery';

// =============================================================================
// Types
// =============================================================================

interface TouchButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  /** Button variant */
  variant?: 'primary' | 'secondary' | 'ghost' | 'danger';
  /** Button size */
  size?: 'sm' | 'md' | 'lg';
  /** Show loading spinner */
  loading?: boolean;
  /** Icon to show before text */
  icon?: React.ReactNode;
  /** Icon to show after text */
  iconAfter?: React.ReactNode;
  /** Callback for long press (500ms) */
  onLongPress?: () => void;
  /** Long press delay in ms */
  longPressDelay?: number;
  /** Enable haptic feedback on supported devices */
  hapticFeedback?: boolean;
  /** Full width button */
  fullWidth?: boolean;
}

// =============================================================================
// Styles
// =============================================================================

const variantClasses = {
  primary: 'bg-primary text-primary-foreground hover:bg-primary/90 active:bg-primary/80',
  secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80 active:bg-secondary/70',
  ghost: 'hover:bg-muted active:bg-muted/80',
  danger:
    'bg-destructive text-destructive-foreground hover:bg-destructive/90 active:bg-destructive/80',
};

const sizeClasses = {
  sm: 'min-h-[44px] min-w-[44px] px-3 py-2 text-sm gap-1.5',
  md: 'min-h-[48px] min-w-[48px] px-4 py-2.5 text-base gap-2',
  lg: 'min-h-[56px] min-w-[56px] px-6 py-3 text-lg gap-2.5',
};

// =============================================================================
// Haptic Feedback
// =============================================================================

function triggerHaptic(type: 'light' | 'medium' | 'heavy' = 'light') {
  if (typeof navigator === 'undefined') return;

  // Use Vibration API if available
  if ('vibrate' in navigator) {
    const durations = { light: 10, medium: 20, heavy: 30 };
    navigator.vibrate(durations[type]);
  }
}

// =============================================================================
// Component
// =============================================================================

export const TouchButton = forwardRef<HTMLButtonElement, TouchButtonProps>(
  (
    {
      children,
      className,
      variant = 'primary',
      size = 'md',
      loading = false,
      disabled = false,
      icon,
      iconAfter,
      onLongPress,
      longPressDelay = 500,
      hapticFeedback = true,
      fullWidth = false,
      onClick,
      ...props
    },
    ref,
  ) => {
    const prefersReducedMotion = usePrefersReducedMotion();
    const [ripples, setRipples] = useState<Array<{ x: number; y: number; id: number }>>([]);
    const [isLongPressing, setIsLongPressing] = useState(false);
    const longPressTimerRef = useRef<NodeJS.Timeout | null>(null);
    const buttonRef = useRef<HTMLButtonElement | null>(null);
    const rippleIdRef = useRef(0);

    // Merge refs
    const mergedRef = useCallback(
      (el: HTMLButtonElement | null) => {
        buttonRef.current = el;
        if (typeof ref === 'function') {
          ref(el);
        } else if (ref) {
          ref.current = el;
        }
      },
      [ref],
    );

    // Handle ripple effect
    const addRipple = useCallback(
      (event: React.MouseEvent | React.TouchEvent) => {
        if (prefersReducedMotion || disabled || loading) return;

        const button = buttonRef.current;
        if (!button) return;

        const rect = button.getBoundingClientRect();
        let x: number, y: number;

        if ('touches' in event) {
          const touch = event.touches[0];
          x = touch.clientX - rect.left;
          y = touch.clientY - rect.top;
        } else {
          x = event.clientX - rect.left;
          y = event.clientY - rect.top;
        }

        const id = rippleIdRef.current++;
        setRipples((prev) => [...prev, { x, y, id }]);

        // Remove ripple after animation
        setTimeout(() => {
          setRipples((prev) => prev.filter((r) => r.id !== id));
        }, 600);
      },
      [prefersReducedMotion, disabled, loading],
    );

    // Handle long press start
    const handlePressStart = useCallback(
      (event: React.MouseEvent | React.TouchEvent) => {
        if (disabled || loading || !onLongPress) return;

        addRipple(event);

        longPressTimerRef.current = setTimeout(() => {
          setIsLongPressing(true);
          if (hapticFeedback) triggerHaptic('medium');
          onLongPress();
        }, longPressDelay);
      },
      [disabled, loading, onLongPress, longPressDelay, addRipple, hapticFeedback],
    );

    // Handle press end
    const handlePressEnd = useCallback(() => {
      if (longPressTimerRef.current) {
        clearTimeout(longPressTimerRef.current);
        longPressTimerRef.current = null;
      }
      setIsLongPressing(false);
    }, []);

    // Handle click
    const handleClick = useCallback(
      (event: React.MouseEvent<HTMLButtonElement>) => {
        if (disabled || loading || isLongPressing) return;

        if (hapticFeedback) triggerHaptic('light');
        addRipple(event);
        onClick?.(event);
      },
      [disabled, loading, isLongPressing, hapticFeedback, addRipple, onClick],
    );

    // Cleanup on unmount
    useEffect(() => {
      return () => {
        if (longPressTimerRef.current) {
          clearTimeout(longPressTimerRef.current);
        }
      };
    }, []);

    return (
      <button
        ref={mergedRef}
        className={cn(
          // Base styles
          'relative inline-flex items-center justify-center',
          'rounded-lg font-medium',
          'transition-colors duration-150',
          'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2',
          'overflow-hidden',
          // Touch feedback
          'touch-manipulation select-none',
          // Active state
          'active:scale-[0.98]',
          // Variant and size
          variantClasses[variant],
          sizeClasses[size],
          // States
          (disabled || loading) && 'opacity-50 cursor-not-allowed',
          fullWidth && 'w-full',
          className,
        )}
        disabled={disabled || loading}
        onClick={handleClick}
        onMouseDown={onLongPress ? handlePressStart : addRipple}
        onMouseUp={handlePressEnd}
        onMouseLeave={handlePressEnd}
        onTouchStart={onLongPress ? handlePressStart : addRipple}
        onTouchEnd={handlePressEnd}
        {...props}
      >
        {/* Ripple effects */}
        {ripples.map((ripple) => (
          <span
            key={ripple.id}
            className="absolute bg-white/30 rounded-full pointer-events-none animate-ripple"
            style={{ left: ripple.x, top: ripple.y, transform: 'translate(-50%, -50%)' }}
          />
        ))}

        {/* Loading spinner */}
        {loading && (
          <span className="absolute inset-0 flex items-center justify-center bg-inherit">
            <svg className="animate-spin h-5 w-5" fill="none" viewBox="0 0 24 24">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
              />
            </svg>
          </span>
        )}

        {/* Content */}
        <span className={cn('flex items-center gap-2', loading && 'invisible')}>
          {icon}
          {children}
          {iconAfter}
        </span>
      </button>
    );
  },
);

TouchButton.displayName = 'TouchButton';

// =============================================================================
// TouchIconButton - Icon-only variant
// =============================================================================

interface TouchIconButtonProps extends Omit<TouchButtonProps, 'children' | 'icon' | 'iconAfter'> {
  /** Icon element */
  icon: React.ReactNode;
  /** Accessible label (required for screen readers) */
  'aria-label': string;
}

export const TouchIconButton = forwardRef<HTMLButtonElement, TouchIconButtonProps>(
  ({ icon, className, size = 'md', ...props }, ref) => {
    const iconSizeClasses = {
      sm: 'min-h-[44px] min-w-[44px] p-2',
      md: 'min-h-[48px] min-w-[48px] p-2.5',
      lg: 'min-h-[56px] min-w-[56px] p-3',
    };

    return (
      <TouchButton
        ref={ref}
        className={cn(iconSizeClasses[size], 'aspect-square', className)}
        size={size}
        {...props}
      >
        {icon}
      </TouchButton>
    );
  },
);

TouchIconButton.displayName = 'TouchIconButton';

export default TouchButton;
