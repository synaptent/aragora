'use client';

interface SkipLinkProps {
  /** The ID of the element to skip to */
  targetId: string;
  /** Text to display in the skip link */
  children?: React.ReactNode;
}

/**
 * Skip link for keyboard navigation accessibility
 *
 * Allows keyboard users to skip directly to main content,
 * bypassing navigation and other repeated elements.
 *
 * The link is visually hidden until focused.
 *
 * @example
 * // In your layout:
 * <SkipLink targetId="main-content">Skip to main content</SkipLink>
 * <Navigation />
 * <main id="main-content">...</main>
 */
export function SkipLink({ targetId, children = 'Skip to main content' }: SkipLinkProps) {
  return (
    <a
      href={`#${targetId}`}
      className="
        sr-only focus:not-sr-only
        focus:fixed focus:top-2 focus:left-2 focus:z-[9999]
        focus:px-4 focus:py-2
        focus:bg-[var(--accent)] focus:text-bg
        focus:font-theme-data focus:text-sm
        focus:rounded focus:outline-none
        focus:ring-2 focus:ring-acid-green focus:ring-offset-2 focus:ring-offset-bg
      "
    >
      {children}
    </a>
  );
}

/**
 * Skip link target - marks where skip links should navigate to
 *
 * @example
 * <SkipLinkTarget id="main-content" />
 */
export function SkipLinkTarget({ id }: { id: string }) {
  return <span id={id} tabIndex={-1} className="sr-only" aria-hidden="true" />;
}
