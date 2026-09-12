/**
 * Accessibility hooks for WCAG 2.1 compliance.
 *
 * Provides utilities for:
 * - Focus management and trapping
 * - Keyboard navigation
 * - Screen reader announcements
 * - Reduced motion preferences
 * - High contrast detection
 */

'use client';

import { useRef, useEffect, useCallback, useState } from 'react';

// =============================================================================
// useAriaLive - Screen reader announcements
// =============================================================================

type AriaLivePolite = 'polite' | 'assertive' | 'off';

interface UseAriaLiveOptions {
  /** Politeness level for announcements */
  politeness?: AriaLivePolite;
  /** Clear announcement after delay (ms) */
  clearAfter?: number;
}

/**
 * Hook for making screen reader announcements.
 *
 * @example
 * ```tsx
 * const announce = useAriaLive();
 * announce('Form submitted successfully');
 * ```
 */
export function useAriaLive(options: UseAriaLiveOptions = {}) {
  const { politeness = 'polite', clearAfter = 5000 } = options;
  const [message, setMessage] = useState('');
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const announce = useCallback(
    (text: string, _overridePoliteness?: AriaLivePolite) => {
      // Clear any existing timeout
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }

      // Set message (screen readers will pick this up)
      setMessage(text);

      // Clear after delay
      if (clearAfter > 0) {
        timeoutRef.current = setTimeout(() => {
          setMessage('');
        }, clearAfter);
      }
    },
    [clearAfter],
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  // Return the announce function and a live region component
  return {
    announce,
    LiveRegion: () => (
      <div role="status" aria-live={politeness} aria-atomic="true" className="sr-only">
        {message}
      </div>
    ),
  };
}

// =============================================================================
// useKeyboardNavigation - Arrow key navigation
// =============================================================================

interface UseKeyboardNavigationOptions<T> {
  items: T[];
  /** Initial selected index */
  initialIndex?: number;
  /** Callback when selection changes */
  onSelect?: (item: T, index: number) => void;
  /** Callback when Enter/Space is pressed */
  onActivate?: (item: T, index: number) => void;
  /** Enable horizontal navigation */
  horizontal?: boolean;
  /** Enable wrap-around */
  wrap?: boolean;
  /** Enable type-ahead search */
  typeAhead?: boolean;
  /** Get label for type-ahead matching */
  getLabel?: (item: T) => string;
}

/**
 * Hook for keyboard navigation in lists/menus.
 *
 * @example
 * ```tsx
 * const { selectedIndex, getItemProps, containerProps } = useKeyboardNavigation({
 *   items: menuItems,
 *   onActivate: (item) => handleSelect(item),
 * });
 * ```
 */
export function useKeyboardNavigation<T>(options: UseKeyboardNavigationOptions<T>) {
  const {
    items,
    initialIndex = 0,
    onSelect,
    onActivate,
    horizontal = false,
    wrap = true,
    typeAhead = false,
    getLabel = (item) => String(item),
  } = options;

  const [selectedIndex, setSelectedIndex] = useState(initialIndex);
  const [typeBuffer, setTypeBuffer] = useState('');
  const typeTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const containerRef = useRef<HTMLElement>(null);

  // Navigate to next/previous item
  const navigate = useCallback(
    (direction: 1 | -1) => {
      setSelectedIndex((current) => {
        let next = current + direction;

        if (wrap) {
          if (next < 0) next = items.length - 1;
          if (next >= items.length) next = 0;
        } else {
          next = Math.max(0, Math.min(items.length - 1, next));
        }

        onSelect?.(items[next], next);
        return next;
      });
    },
    [items, wrap, onSelect],
  );

  // Type-ahead search
  const handleTypeAhead = useCallback(
    (char: string) => {
      if (!typeAhead) return;

      // Clear existing timeout
      if (typeTimeoutRef.current) {
        clearTimeout(typeTimeoutRef.current);
      }

      const newBuffer = typeBuffer + char.toLowerCase();
      setTypeBuffer(newBuffer);

      // Find matching item
      const matchIndex = items.findIndex((item) =>
        getLabel(item).toLowerCase().startsWith(newBuffer),
      );

      if (matchIndex !== -1) {
        setSelectedIndex(matchIndex);
        onSelect?.(items[matchIndex], matchIndex);
      }

      // Clear buffer after delay
      typeTimeoutRef.current = setTimeout(() => {
        setTypeBuffer('');
      }, 500);
    },
    [items, typeAhead, typeBuffer, getLabel, onSelect],
  );

  // Handle keyboard events
  const handleKeyDown = useCallback(
    (event: KeyboardEvent) => {
      const { key } = event;

      // Arrow navigation
      if (horizontal) {
        if (key === 'ArrowLeft') {
          event.preventDefault();
          navigate(-1);
        } else if (key === 'ArrowRight') {
          event.preventDefault();
          navigate(1);
        }
      } else {
        if (key === 'ArrowUp') {
          event.preventDefault();
          navigate(-1);
        } else if (key === 'ArrowDown') {
          event.preventDefault();
          navigate(1);
        }
      }

      // Home/End
      if (key === 'Home') {
        event.preventDefault();
        setSelectedIndex(0);
        onSelect?.(items[0], 0);
      } else if (key === 'End') {
        event.preventDefault();
        const lastIndex = items.length - 1;
        setSelectedIndex(lastIndex);
        onSelect?.(items[lastIndex], lastIndex);
      }

      // Activation
      if (key === 'Enter' || key === ' ') {
        event.preventDefault();
        onActivate?.(items[selectedIndex], selectedIndex);
      }

      // Type-ahead (single printable character)
      if (key.length === 1 && key.match(/\S/)) {
        handleTypeAhead(key);
      }
    },
    [horizontal, navigate, items, selectedIndex, onSelect, onActivate, handleTypeAhead],
  );

  // Attach keyboard listener to container
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    container.addEventListener('keydown', handleKeyDown as EventListener);
    return () => {
      container.removeEventListener('keydown', handleKeyDown as EventListener);
    };
  }, [handleKeyDown]);

  // Cleanup type-ahead timeout
  useEffect(() => {
    return () => {
      if (typeTimeoutRef.current) {
        clearTimeout(typeTimeoutRef.current);
      }
    };
  }, []);

  return {
    selectedIndex,
    setSelectedIndex,
    containerRef,
    containerProps: {
      ref: containerRef,
      role: 'listbox',
      tabIndex: 0,
      'aria-activedescendant': `item-${selectedIndex}`,
    },
    getItemProps: (index: number) => ({
      id: `item-${index}`,
      role: 'option',
      'aria-selected': index === selectedIndex,
      tabIndex: index === selectedIndex ? 0 : -1,
      onClick: () => {
        setSelectedIndex(index);
        onSelect?.(items[index], index);
        onActivate?.(items[index], index);
      },
    }),
  };
}

// =============================================================================
// useRovingTabIndex - Focus management for component groups
// =============================================================================

interface UseRovingTabIndexOptions {
  /** Number of items in the group */
  itemCount: number;
  /** Callback when focus changes */
  onFocusChange?: (index: number) => void;
  /** Enable horizontal navigation */
  horizontal?: boolean;
  /** Enable wrap-around */
  wrap?: boolean;
}

/**
 * Hook for roving tabindex pattern (tab into group, arrow keys within).
 *
 * @example
 * ```tsx
 * const { focusedIndex, getTabIndex, handleKeyDown } = useRovingTabIndex({
 *   itemCount: buttons.length,
 * });
 * ```
 */
export function useRovingTabIndex(options: UseRovingTabIndexOptions) {
  const { itemCount, onFocusChange, horizontal = false, wrap = true } = options;

  const [focusedIndex, setFocusedIndex] = useState(0);
  const itemRefs = useRef<(HTMLElement | null)[]>([]);

  const setItemRef = useCallback((index: number, el: HTMLElement | null) => {
    itemRefs.current[index] = el;
  }, []);

  const focusItem = useCallback(
    (index: number) => {
      const clampedIndex = wrap
        ? ((index % itemCount) + itemCount) % itemCount
        : Math.max(0, Math.min(itemCount - 1, index));

      setFocusedIndex(clampedIndex);
      itemRefs.current[clampedIndex]?.focus();
      onFocusChange?.(clampedIndex);
    },
    [itemCount, wrap, onFocusChange],
  );

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      const { key } = event;

      if (horizontal) {
        if (key === 'ArrowLeft') {
          event.preventDefault();
          focusItem(focusedIndex - 1);
        } else if (key === 'ArrowRight') {
          event.preventDefault();
          focusItem(focusedIndex + 1);
        }
      } else {
        if (key === 'ArrowUp') {
          event.preventDefault();
          focusItem(focusedIndex - 1);
        } else if (key === 'ArrowDown') {
          event.preventDefault();
          focusItem(focusedIndex + 1);
        }
      }

      if (key === 'Home') {
        event.preventDefault();
        focusItem(0);
      } else if (key === 'End') {
        event.preventDefault();
        focusItem(itemCount - 1);
      }
    },
    [horizontal, focusedIndex, focusItem, itemCount],
  );

  return {
    focusedIndex,
    setFocusedIndex,
    setItemRef,
    handleKeyDown,
    getTabIndex: (index: number) => (index === focusedIndex ? 0 : -1),
  };
}

// =============================================================================
// useHighContrast - High contrast mode detection
// =============================================================================

/**
 * Hook to detect high contrast mode preference.
 */
export function useHighContrast(): boolean {
  const [isHighContrast, setIsHighContrast] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    // Check for Windows high contrast mode
    const mediaQuery = window.matchMedia('(forced-colors: active)');
    setIsHighContrast(mediaQuery.matches);

    const handler = (event: MediaQueryListEvent) => {
      setIsHighContrast(event.matches);
    };

    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handler);
      return () => mediaQuery.removeEventListener('change', handler);
    }
    // Legacy browsers
    mediaQuery.addListener(handler);
    return () => mediaQuery.removeListener(handler);
  }, []);

  return isHighContrast;
}

// =============================================================================
// useColorScheme - System color scheme preference
// =============================================================================

type ColorScheme = 'light' | 'dark' | 'no-preference';

/**
 * Hook to detect system color scheme preference.
 */
export function useColorScheme(): ColorScheme {
  const prefersDark = useMediaQueryMatch('(prefers-color-scheme: dark)');
  const prefersLight = useMediaQueryMatch('(prefers-color-scheme: light)');

  if (prefersDark) return 'dark';
  if (prefersLight) return 'light';
  return 'no-preference';
}

// Helper for useColorScheme
function useMediaQueryMatch(query: string): boolean {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined') return;

    const mediaQuery = window.matchMedia(query);
    setMatches(mediaQuery.matches);

    const handler = (event: MediaQueryListEvent) => {
      setMatches(event.matches);
    };

    if (mediaQuery.addEventListener) {
      mediaQuery.addEventListener('change', handler);
      return () => mediaQuery.removeEventListener('change', handler);
    }
    mediaQuery.addListener(handler);
    return () => mediaQuery.removeListener(handler);
  }, [query]);

  return matches;
}

// =============================================================================
// useInertWhenHidden - Inert attribute management
// =============================================================================

/**
 * Hook to manage inert attribute for hidden content.
 * Makes content inaccessible to assistive technology when hidden.
 *
 * @example
 * ```tsx
 * const inertRef = useInertWhenHidden(isModalOpen);
 * <main ref={inertRef}>...</main>
 * ```
 */
export function useInertWhenHidden<T extends HTMLElement>(isHidden: boolean) {
  const ref = useRef<T>(null);

  useEffect(() => {
    const element = ref.current;
    if (!element) return;

    if (isHidden) {
      element.setAttribute('inert', '');
    } else {
      element.removeAttribute('inert');
    }

    return () => {
      element.removeAttribute('inert');
    };
  }, [isHidden]);

  return ref;
}

// =============================================================================
// useSkipLink - Skip to main content
// =============================================================================

interface UseSkipLinkOptions {
  /** Target element ID to skip to */
  targetId: string;
  /** Label for screen readers */
  label?: string;
}

/**
 * Hook for skip link functionality.
 * Returns props to spread on a skip link element.
 */
export function useSkipLink(options: UseSkipLinkOptions) {
  const { targetId, label = 'Skip to main content' } = options;

  const handleClick = useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault();
      const target = document.getElementById(targetId);
      if (target) {
        target.focus();
        target.scrollIntoView();
      }
    },
    [targetId],
  );

  return {
    href: `#${targetId}`,
    onClick: handleClick,
    className:
      'sr-only focus:not-sr-only focus:absolute focus:top-4 focus:left-4 focus:z-50 focus:px-4 focus:py-2 focus:bg-background focus:border focus:rounded-md',
    children: label,
  };
}

// =============================================================================
// Export types
// =============================================================================

export type { AriaLivePolite, UseAriaLiveOptions, UseKeyboardNavigationOptions };
