/**
 * SkipLinks - Accessibility skip links for keyboard navigation.
 *
 * Features:
 * - Skip to main content
 * - Skip to navigation
 * - Skip to search (if present)
 * - Only visible on keyboard focus
 * - Smooth scroll with focus
 */

'use client';

import React, { useCallback } from 'react';
import { cn } from '@/lib/utils';

// =============================================================================
// Types
// =============================================================================

export interface SkipLinkItem {
  /** Target element ID */
  targetId: string;
  /** Link label */
  label: string;
}

interface SkipLinksProps {
  /** Skip link items */
  links?: SkipLinkItem[];
  /** Custom class name */
  className?: string;
}

// =============================================================================
// Default links
// =============================================================================

const defaultLinks: SkipLinkItem[] = [
  { targetId: 'main-content', label: 'Skip to main content' },
  { targetId: 'main-navigation', label: 'Skip to navigation' },
];

// =============================================================================
// Component
// =============================================================================

export function SkipLinks({ links = defaultLinks, className }: SkipLinksProps) {
  const handleClick = useCallback((e: React.MouseEvent<HTMLAnchorElement>, targetId: string) => {
    e.preventDefault();
    const target = document.getElementById(targetId);
    if (target) {
      // Focus the target element
      target.setAttribute('tabindex', '-1');
      target.focus();
      target.scrollIntoView({ behavior: 'smooth', block: 'start' });

      // Remove tabindex after blur
      target.addEventListener(
        'blur',
        () => {
          target.removeAttribute('tabindex');
        },
        { once: true },
      );
    }
  }, []);

  return (
    <nav
      aria-label="Skip links"
      className={cn('fixed top-0 left-0 z-[100]', 'flex flex-col gap-1 p-2', className)}
    >
      {links.map((link) => (
        <a
          key={link.targetId}
          href={`#${link.targetId}`}
          onClick={(e) => handleClick(e, link.targetId)}
          className={cn(
            // Hidden by default
            'sr-only',
            // Visible on focus
            'focus:not-sr-only',
            'focus:fixed focus:top-2 focus:left-2',
            'focus:z-[100]',
            // Styling
            'focus:px-4 focus:py-2',
            'focus:bg-background focus:text-foreground',
            'focus:border focus:rounded-md',
            'focus:shadow-lg',
            'focus:outline-none focus:ring-2 focus:ring-primary',
            // Font
            'focus:font-medium focus:text-sm',
          )}
        >
          {link.label}
        </a>
      ))}
    </nav>
  );
}

// =============================================================================
// Landmark IDs - Constants for consistent ID usage
// =============================================================================

export const LANDMARK_IDS = {
  mainContent: 'main-content',
  mainNavigation: 'main-navigation',
  search: 'search',
  footer: 'main-footer',
} as const;

// =============================================================================
// MainContent wrapper - Ensures proper landmark with ID
// =============================================================================

interface MainContentProps {
  children: React.ReactNode;
  className?: string;
}

export function MainContent({ children, className }: MainContentProps) {
  return (
    <main
      id={LANDMARK_IDS.mainContent}
      role="main"
      tabIndex={-1}
      className={cn('focus:outline-none', className)}
    >
      {children}
    </main>
  );
}

export default SkipLinks;
