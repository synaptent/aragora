/**
 * ResponsiveContainer - Utility components for mobile-responsive layouts.
 *
 * Provides:
 * - ResponsiveContainer: Main container with responsive padding/margins
 * - ResponsiveGrid: Adaptive grid that collapses on mobile
 * - ResponsiveStack: Horizontal on desktop, vertical on mobile
 * - MobileOnly/DesktopOnly: Conditional rendering by screen size
 * - ResponsiveDrawer: Bottom sheet on mobile, side panel on desktop
 */

'use client';

import React, { ReactNode, useState, useEffect } from 'react';
import { cn } from '@/lib/utils';
import { useIsMobile, useIsDesktop } from '@/hooks/useMediaQuery';

// =============================================================================
// ResponsiveContainer
// =============================================================================

interface ResponsiveContainerProps {
  children: ReactNode;
  className?: string;
  /** Maximum width on desktop */
  maxWidth?: 'sm' | 'md' | 'lg' | 'xl' | '2xl' | 'full' | 'none';
  /** Padding style */
  padding?: 'none' | 'sm' | 'md' | 'lg';
  /** Center content horizontally */
  center?: boolean;
}

const maxWidthClasses = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  '2xl': 'max-w-2xl',
  full: 'max-w-full',
  none: '',
};

const paddingClasses = {
  none: '',
  sm: 'px-3 py-2 md:px-4 md:py-3',
  md: 'px-4 py-3 md:px-6 md:py-4',
  lg: 'px-4 py-4 md:px-8 md:py-6',
};

export function ResponsiveContainer({
  children,
  className,
  maxWidth = 'full',
  padding = 'md',
  center = true,
}: ResponsiveContainerProps) {
  return (
    <div
      className={cn(
        'w-full',
        maxWidthClasses[maxWidth],
        paddingClasses[padding],
        center && 'mx-auto',
        className,
      )}
    >
      {children}
    </div>
  );
}

// =============================================================================
// ResponsiveGrid
// =============================================================================

interface ResponsiveGridProps {
  children: ReactNode;
  className?: string;
  /** Columns on different breakpoints */
  cols?: { mobile?: number; tablet?: number; desktop?: number };
  /** Gap between items */
  gap?: 'sm' | 'md' | 'lg';
}

const gapClasses = { sm: 'gap-2 md:gap-3', md: 'gap-3 md:gap-4', lg: 'gap-4 md:gap-6' };

export function ResponsiveGrid({
  children,
  className,
  cols = { mobile: 1, tablet: 2, desktop: 3 },
  gap = 'md',
}: ResponsiveGridProps) {
  return (
    <div
      className={cn(
        'grid',
        gapClasses[gap],
        // Using inline style for dynamic cols since Tailwind doesn't support dynamic classes
        className,
      )}
      style={{
        gridTemplateColumns: `repeat(var(--cols), minmax(0, 1fr))`,
        // @ts-expect-error - CSS custom properties are valid
        '--cols': cols.mobile || 1,
      }}
    >
      <style jsx>{`
        @media (min-width: 768px) {
          div {
            --cols: ${cols.tablet || 2};
          }
        }
        @media (min-width: 1024px) {
          div {
            --cols: ${cols.desktop || 3};
          }
        }
      `}</style>
      {children}
    </div>
  );
}

// =============================================================================
// ResponsiveStack
// =============================================================================

interface ResponsiveStackProps {
  children: ReactNode;
  className?: string;
  /** Reverse order on mobile */
  reverseOnMobile?: boolean;
  /** Gap between items */
  gap?: 'sm' | 'md' | 'lg';
  /** Alignment */
  align?: 'start' | 'center' | 'end' | 'stretch';
}

export function ResponsiveStack({
  children,
  className,
  reverseOnMobile = false,
  gap = 'md',
  align = 'stretch',
}: ResponsiveStackProps) {
  const alignClasses = {
    start: 'items-start',
    center: 'items-center',
    end: 'items-end',
    stretch: 'items-stretch',
  };

  return (
    <div
      className={cn(
        'flex flex-col md:flex-row',
        gapClasses[gap],
        alignClasses[align],
        reverseOnMobile && 'flex-col-reverse md:flex-row',
        className,
      )}
    >
      {children}
    </div>
  );
}

// =============================================================================
// MobileOnly / DesktopOnly
// =============================================================================

interface ConditionalRenderProps {
  children: ReactNode;
  /** Fallback content for the opposite screen size */
  fallback?: ReactNode;
}

export function MobileOnly({ children, fallback }: ConditionalRenderProps) {
  const isMobile = useIsMobile();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  // SSR: render nothing until hydrated
  if (!mounted) return null;

  return <>{isMobile ? children : fallback}</>;
}

export function DesktopOnly({ children, fallback }: ConditionalRenderProps) {
  const isDesktop = useIsDesktop();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return <>{isDesktop ? children : fallback}</>;
}

// =============================================================================
// ResponsiveDrawer
// =============================================================================

interface ResponsiveDrawerProps {
  children: ReactNode;
  isOpen: boolean;
  onClose: () => void;
  title?: string;
  className?: string;
  /** Position on desktop */
  desktopPosition?: 'left' | 'right';
  /** Width on desktop */
  desktopWidth?: 'sm' | 'md' | 'lg';
}

const desktopWidthClasses = { sm: 'md:w-80', md: 'md:w-96', lg: 'md:w-[480px]' };

export function ResponsiveDrawer({
  children,
  isOpen,
  onClose,
  title,
  className,
  desktopPosition = 'right',
  desktopWidth = 'md',
}: ResponsiveDrawerProps) {
  const isMobile = useIsMobile();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted || !isOpen) return null;

  // Mobile: Bottom sheet
  if (isMobile) {
    return (
      <>
        {/* Backdrop */}
        <div className="fixed inset-0 bg-black/50 z-40 animate-in fade-in" onClick={onClose} />
        {/* Bottom Sheet */}
        <div
          className={cn(
            'fixed inset-x-0 bottom-0 z-50 bg-background rounded-t-xl shadow-xl',
            'max-h-[85vh] overflow-y-auto',
            'animate-in slide-in-from-bottom duration-300',
            className,
          )}
        >
          {/* Handle */}
          <div className="sticky top-0 bg-background pt-2 pb-1 flex justify-center">
            <div className="w-12 h-1.5 bg-muted-foreground/30 rounded-full" />
          </div>
          {/* Header */}
          {title && (
            <div className="px-4 py-2 border-b flex items-center justify-between">
              <h3 className="font-semibold">{title}</h3>
              <button onClick={onClose} className="p-2 hover:bg-muted rounded-lg">
                <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M6 18L18 6M6 6l12 12"
                  />
                </svg>
              </button>
            </div>
          )}
          {/* Content */}
          <div className="p-4">{children}</div>
        </div>
      </>
    );
  }

  // Desktop: Side panel
  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/30 z-40 animate-in fade-in" onClick={onClose} />
      {/* Side Panel */}
      <div
        className={cn(
          'fixed top-0 bottom-0 z-50 bg-background shadow-xl',
          desktopWidthClasses[desktopWidth],
          desktopPosition === 'right'
            ? 'right-0 animate-in slide-in-from-right'
            : 'left-0 animate-in slide-in-from-left',
          'duration-300',
          className,
        )}
      >
        {/* Header */}
        {title && (
          <div className="px-6 py-4 border-b flex items-center justify-between">
            <h3 className="font-semibold text-lg">{title}</h3>
            <button onClick={onClose} className="p-2 hover:bg-muted rounded-lg">
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
        )}
        {/* Content */}
        <div className="p-6 overflow-y-auto h-[calc(100%-73px)]">{children}</div>
      </div>
    </>
  );
}

// =============================================================================
// ResponsiveText
// =============================================================================

interface ResponsiveTextProps {
  children: ReactNode;
  className?: string;
  as?: 'h1' | 'h2' | 'h3' | 'h4' | 'p' | 'span';
}

const textSizeClasses = {
  h1: 'text-2xl md:text-3xl lg:text-4xl font-bold',
  h2: 'text-xl md:text-2xl lg:text-3xl font-semibold',
  h3: 'text-lg md:text-xl lg:text-2xl font-semibold',
  h4: 'text-base md:text-lg lg:text-xl font-medium',
  p: 'text-sm md:text-base',
  span: 'text-sm md:text-base',
};

export function ResponsiveText({ children, className, as = 'p' }: ResponsiveTextProps) {
  const Component = as;
  return <Component className={cn(textSizeClasses[as], className)}>{children}</Component>;
}

// =============================================================================
// Export utilities
// =============================================================================

export { useIsMobile, useIsDesktop } from '@/hooks/useMediaQuery';
