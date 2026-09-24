/**
 * useMediaQuery hook for responsive design.
 *
 * Provides utilities for detecting screen size and adjusting UI accordingly.
 */

import { useState, useEffect, useCallback } from 'react';

// Breakpoint values (matches Tailwind defaults)
export const BREAKPOINTS = { sm: 640, md: 768, lg: 1024, xl: 1280, '2xl': 1536 } as const;

type BreakpointKey = keyof typeof BREAKPOINTS;

/**
 * Hook to detect if a media query matches.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    // Check if we're in a browser environment
    if (typeof window === 'undefined') return;

    const mediaQuery = window.matchMedia(query);
    setMatches(mediaQuery.matches);

    const handler = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    // Modern browsers
    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handler);
      return () => mediaQuery.removeEventListener('change', handler);
    }
    // Legacy browsers
    mediaQuery.addListener(handler);
    return () => mediaQuery.removeListener(handler);
  }, [query]);

  return matches;
}

/**
 * Hook to check if viewport is below a breakpoint (mobile-first).
 */
export function useIsMobile(breakpoint: BreakpointKey = 'md'): boolean {
  return useMediaQuery(`(max-width: ${BREAKPOINTS[breakpoint] - 1}px)`);
}

/**
 * Hook to check if viewport is above a breakpoint.
 */
export function useIsDesktop(breakpoint: BreakpointKey = 'lg'): boolean {
  return useMediaQuery(`(min-width: ${BREAKPOINTS[breakpoint]}px)`);
}

/**
 * Hook to check if viewport is in tablet range.
 */
export function useIsTablet(): boolean {
  return useMediaQuery(`(min-width: ${BREAKPOINTS.md}px) and (max-width: ${BREAKPOINTS.lg - 1}px)`);
}

/**
 * Hook to get the current breakpoint.
 */
export function useBreakpoint(): BreakpointKey | 'xs' {
  const isSm = useMediaQuery(`(min-width: ${BREAKPOINTS.sm}px)`);
  const isMd = useMediaQuery(`(min-width: ${BREAKPOINTS.md}px)`);
  const isLg = useMediaQuery(`(min-width: ${BREAKPOINTS.lg}px)`);
  const isXl = useMediaQuery(`(min-width: ${BREAKPOINTS.xl}px)`);
  const is2xl = useMediaQuery(`(min-width: ${BREAKPOINTS['2xl']}px)`);

  if (is2xl) return '2xl';
  if (isXl) return 'xl';
  if (isLg) return 'lg';
  if (isMd) return 'md';
  if (isSm) return 'sm';
  return 'xs';
}

/**
 * Hook to detect touch device.
 */
export function useIsTouchDevice(): boolean {
  const [isTouch, setIsTouch] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const checkTouch = () => {
      setIsTouch(
        'ontouchstart' in window ||
          navigator.maxTouchPoints > 0 ||
          // Check for older IE touch support
          ((navigator as { msMaxTouchPoints?: number }).msMaxTouchPoints ?? 0) > 0,
      );
    };

    checkTouch();
  }, []);

  return isTouch;
}

/**
 * Hook to detect orientation.
 */
export function useOrientation(): 'portrait' | 'landscape' {
  const isPortrait = useMediaQuery('(orientation: portrait)');
  return isPortrait ? 'portrait' : 'landscape';
}

/**
 * Hook to detect reduced motion preference.
 */
export function usePrefersReducedMotion(): boolean {
  return useMediaQuery('(prefers-reduced-motion: reduce)');
}

/**
 * Hook that provides comprehensive responsive utilities.
 */
export function useResponsive() {
  const isMobile = useIsMobile();
  const isTablet = useIsTablet();
  const isDesktop = useIsDesktop();
  const breakpoint = useBreakpoint();
  const isTouch = useIsTouchDevice();
  const orientation = useOrientation();
  const prefersReducedMotion = usePrefersReducedMotion();

  // Utility for responsive values
  const responsive = useCallback(
    <T>(values: { mobile?: T; tablet?: T; desktop?: T; default: T }): T => {
      if (isMobile && values.mobile !== undefined) return values.mobile;
      if (isTablet && values.tablet !== undefined) return values.tablet;
      if (isDesktop && values.desktop !== undefined) return values.desktop;
      return values.default;
    },
    [isMobile, isTablet, isDesktop],
  );

  return {
    isMobile,
    isTablet,
    isDesktop,
    breakpoint,
    isTouch,
    orientation,
    prefersReducedMotion,
    responsive,
  };
}

export default useMediaQuery;
