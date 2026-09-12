/**
 * BottomNavigation - Mobile-first bottom tab navigation.
 *
 * Features:
 * - Fixed bottom position on mobile
 * - Safe area inset support (iPhone notch)
 * - Active state indicators
 * - Badge support for notifications
 * - Haptic feedback on selection
 * - Keyboard accessible
 */

'use client';

import React, { useCallback } from 'react';
import { cn } from '@/lib/utils';
import { useRovingTabIndex } from '@/hooks/useAccessibility';
import { useIsMobile } from '@/hooks/useMediaQuery';

// =============================================================================
// Types
// =============================================================================

export interface NavItem {
  /** Unique identifier */
  id: string;
  /** Display label */
  label: string;
  /** Icon component */
  icon: React.ReactNode;
  /** Active icon (optional, uses icon if not provided) */
  activeIcon?: React.ReactNode;
  /** Badge count (shows notification dot if > 0) */
  badge?: number;
  /** Full badge count display (shows number instead of dot) */
  showBadgeCount?: boolean;
  /** Disabled state */
  disabled?: boolean;
}

interface BottomNavigationProps {
  /** Navigation items (3-5 recommended) */
  items: NavItem[];
  /** Currently active item ID */
  activeId: string;
  /** Callback when item is selected */
  onSelect: (id: string) => void;
  /** Custom class name */
  className?: string;
  /** Hide on desktop */
  hideOnDesktop?: boolean;
  /** Show labels */
  showLabels?: boolean;
}

// =============================================================================
// Haptic feedback
// =============================================================================

function triggerHaptic() {
  if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
    navigator.vibrate(10);
  }
}

// =============================================================================
// Component
// =============================================================================

export function BottomNavigation({
  items,
  activeId,
  onSelect,
  className,
  hideOnDesktop = true,
  showLabels = true,
}: BottomNavigationProps) {
  const isMobile = useIsMobile();
  const { setItemRef, handleKeyDown, getTabIndex } = useRovingTabIndex({
    itemCount: items.length,
    horizontal: true,
  });

  const handleSelect = useCallback(
    (id: string) => {
      triggerHaptic();
      onSelect(id);
    },
    [onSelect],
  );

  // Hide on desktop if configured
  if (hideOnDesktop && !isMobile) {
    return null;
  }

  return (
    <nav
      className={cn(
        // Fixed position at bottom
        'fixed bottom-0 left-0 right-0 z-50',
        // Background and border
        'bg-background/95 backdrop-blur-sm border-t',
        // Safe area padding for iPhone notch
        'pb-[env(safe-area-inset-bottom,0px)]',
        // Shadow
        'shadow-[0_-2px_10px_rgba(0,0,0,0.1)]',
        className,
      )}
      role="navigation"
      aria-label="Main navigation"
    >
      <div
        className="flex items-center justify-around px-2"
        role="tablist"
        onKeyDown={handleKeyDown}
      >
        {items.map((item, index) => {
          const isActive = item.id === activeId;
          const Icon = isActive && item.activeIcon ? item.activeIcon : item.icon;

          return (
            <button
              key={item.id}
              ref={(el) => setItemRef(index, el)}
              role="tab"
              aria-selected={isActive}
              aria-controls={`panel-${item.id}`}
              tabIndex={getTabIndex(index)}
              disabled={item.disabled}
              onClick={() => handleSelect(item.id)}
              className={cn(
                // Base styles
                'flex flex-col items-center justify-center',
                'min-w-[64px] min-h-[56px] py-2 px-3',
                'transition-colors duration-150',
                'touch-manipulation select-none',
                // Focus styles
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-inset',
                // Active state
                isActive ? 'text-primary' : 'text-muted-foreground hover:text-foreground',
                // Disabled state
                item.disabled && 'opacity-50 cursor-not-allowed',
              )}
            >
              {/* Icon container with badge */}
              <span className="relative">
                <span className={cn('block w-6 h-6', isActive && 'scale-110 transition-transform')}>
                  {Icon}
                </span>

                {/* Badge */}
                {item.badge !== undefined && item.badge > 0 && (
                  <span
                    className={cn(
                      'absolute -top-1 -right-1',
                      'flex items-center justify-center',
                      'bg-destructive text-destructive-foreground',
                      'rounded-full',
                      'font-medium',
                      item.showBadgeCount
                        ? 'min-w-[18px] h-[18px] px-1 text-[10px]'
                        : 'w-2.5 h-2.5',
                    )}
                    aria-label={`${item.badge} notifications`}
                  >
                    {item.showBadgeCount && (item.badge > 99 ? '99+' : item.badge)}
                  </span>
                )}
              </span>

              {/* Label */}
              {showLabels && (
                <span className={cn('text-[11px] mt-1 font-medium', 'max-w-[64px] truncate')}>
                  {item.label}
                </span>
              )}

              {/* Active indicator */}
              {isActive && (
                <span className="absolute -top-px left-1/2 -translate-x-1/2 w-8 h-0.5 bg-primary rounded-full" />
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}

// =============================================================================
// BottomNavigationSpacer - Prevents content from being hidden behind nav
// =============================================================================

interface BottomNavigationSpacerProps {
  className?: string;
  /** Height of the spacer (auto-calculated by default) */
  height?: number;
}

export function BottomNavigationSpacer({ className, height = 72 }: BottomNavigationSpacerProps) {
  const isMobile = useIsMobile();

  if (!isMobile) return null;

  return (
    <div
      className={cn('flex-shrink-0', className)}
      style={{ height: `calc(${height}px + env(safe-area-inset-bottom, 0px))` }}
      aria-hidden="true"
    />
  );
}

export default BottomNavigation;
