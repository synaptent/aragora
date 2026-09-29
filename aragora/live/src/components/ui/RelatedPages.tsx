'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

interface RelatedPage {
  label: string;
  href: string;
  description?: string;
}

interface RelatedPagesProps {
  /** Override the auto-detected related pages */
  pages?: RelatedPage[];
  /** Additional CSS classes */
  className?: string;
  /** Maximum number of pages to show */
  maxPages?: number;
  /** Title for the section */
  title?: string;
}

// Define related page mappings by route pattern
// Each key is a route prefix, value is an array of related pages
const RELATED_PAGES: Record<string, RelatedPage[]> = {
  // Debate-related pages
  '/debates': [
    { label: 'New Debate', href: '/arena', description: 'Start a new debate' },
    { label: 'Leaderboard', href: '/leaderboard', description: 'Agent rankings' },
    { label: 'Templates', href: '/templates', description: 'Debate templates' },
    { label: 'Analytics', href: '/analytics', description: 'Debate analytics' },
  ],
  '/arena': [
    { label: 'Debates', href: '/debates', description: 'View past debates' },
    { label: 'Templates', href: '/templates', description: 'Use a template' },
    { label: 'Agents', href: '/agents', description: 'Configure agents' },
  ],
  '/debate': [
    { label: 'All Debates', href: '/debates', description: 'Back to debates' },
    { label: 'Checkpoints', href: '/checkpoints', description: 'Resume debates' },
    { label: 'Share', href: '/social', description: 'Share debate' },
  ],

  // Agent-related pages
  '/agents': [
    { label: 'Leaderboard', href: '/leaderboard', description: 'Rankings' },
    { label: 'Calibration', href: '/calibration', description: 'Agent tuning' },
    { label: 'Debates', href: '/debates', description: 'See agents in action' },
  ],
  '/leaderboard': [
    { label: 'Agents', href: '/agents', description: 'Agent details' },
    { label: 'Tournaments', href: '/tournaments', description: 'Competitions' },
    { label: 'Analytics', href: '/analytics', description: 'Performance data' },
  ],

  // Knowledge-related pages
  '/knowledge': [
    { label: 'Memory', href: '/memory', description: 'System memory' },
    { label: 'Evidence', href: '/evidence', description: 'Evidence store' },
    { label: 'Documents', href: '/documents', description: 'Document library' },
  ],
  '/memory': [
    { label: 'Knowledge', href: '/knowledge', description: 'Knowledge base' },
    { label: 'Analytics', href: '/memory-analytics', description: 'Memory stats' },
    { label: 'Settings', href: '/settings', description: 'Configure memory' },
  ],
  '/documents': [
    { label: 'Knowledge', href: '/knowledge', description: 'Knowledge base' },
    { label: 'Connectors', href: '/connectors', description: 'Data sources' },
    { label: 'Evidence', href: '/evidence', description: 'Evidence store' },
  ],

  // Workflow-related pages
  '/workflows': [
    { label: 'Templates', href: '/templates', description: 'Workflow templates' },
    { label: 'Scheduler', href: '/scheduler', description: 'Schedule runs' },
    { label: 'Analytics', href: '/analytics', description: 'Run analytics' },
  ],
  '/connectors': [
    { label: 'Integrations', href: '/integrations', description: 'App integrations' },
    { label: 'Workflows', href: '/workflows', description: 'Use in workflows' },
    { label: 'Documents', href: '/documents', description: 'Connected docs' },
  ],

  // Analytics-related pages
  '/analytics': [
    { label: 'Debates', href: '/debates', description: 'Source debates' },
    { label: 'Leaderboard', href: '/leaderboard', description: 'Rankings' },
    { label: 'ML Intelligence', href: '/ml', description: 'ML insights' },
  ],
  '/ml': [
    { label: 'Training', href: '/training', description: 'Model training' },
    { label: 'Analytics', href: '/analytics', description: 'Performance' },
    { label: 'Calibration', href: '/calibration', description: 'Tuning' },
  ],

  // Admin pages
  '/admin': [
    { label: 'Users', href: '/admin/users', description: 'User management' },
    { label: 'Organizations', href: '/admin/organizations', description: 'Org management' },
    { label: 'Billing', href: '/admin/billing', description: 'Billing admin' },
    { label: 'Forensic', href: '/admin/forensic', description: 'System forensics' },
  ],

  // Testing-related pages
  '/gauntlet': [
    { label: 'Debates', href: '/debates', description: 'View results' },
    { label: 'Templates', href: '/templates', description: 'Test templates' },
    { label: 'Analytics', href: '/analytics', description: 'Test analytics' },
  ],
  '/reviews': [
    { label: 'Debates', href: '/debates', description: 'Full debates' },
    { label: 'Gallery', href: '/gallery', description: 'Review gallery' },
    { label: 'Templates', href: '/templates', description: 'Review templates' },
  ],

  // Settings pages
  '/settings': [
    { label: 'Billing', href: '/billing', description: 'Billing settings' },
    { label: 'Organization', href: '/organization', description: 'Org settings' },
    { label: 'Integrations', href: '/integrations', description: 'Connect apps' },
  ],
  '/billing': [
    { label: 'Settings', href: '/settings', description: 'Account settings' },
    { label: 'Usage', href: '/usage', description: 'Usage details' },
    { label: 'Pricing', href: '/pricing', description: 'Plan options' },
  ],

  // Verification and testing
  '/verification': [
    { label: 'Evidence', href: '/evidence', description: 'Evidence store' },
    { label: 'Crux Analysis', href: '/crux', description: 'Crux detection' },
    { label: 'Red Team', href: '/red-team', description: 'Red team tools' },
  ],

  // Hub and entry points
  '/hub': [
    { label: 'New Debate', href: '/arena', description: 'Start debating' },
    { label: 'Debates', href: '/debates', description: 'View debates' },
    { label: 'Gallery', href: '/gallery', description: 'Browse gallery' },
  ],

  // Social features
  '/social': [
    { label: 'Gallery', href: '/gallery', description: 'Public gallery' },
    { label: 'Debates', href: '/debates', description: 'Shareable debates' },
    { label: 'Leaderboard', href: '/leaderboard', description: 'Rankings' },
  ],

  // Advanced features
  '/genesis': [
    { label: 'Evolution', href: '/evolution', description: 'Evolution history' },
    { label: 'Agents', href: '/agents', description: 'Agent catalog' },
    { label: 'Analytics', href: '/analytics', description: 'Evolution stats' },
  ],
  '/introspection': [
    { label: 'Agents', href: '/agents', description: 'Agent details' },
    { label: 'Memory', href: '/memory', description: 'Agent memory' },
    { label: 'Analytics', href: '/analytics', description: 'Performance' },
  ],
};

/**
 * Find related pages for the current route
 */
function findRelatedPages(pathname: string, maxPages: number): RelatedPage[] {
  // Try exact match first
  if (RELATED_PAGES[pathname]) {
    return RELATED_PAGES[pathname].slice(0, maxPages);
  }

  // Try prefix match (for dynamic routes like /debate/[id])
  const segments = pathname.split('/').filter(Boolean);
  for (let i = segments.length; i > 0; i--) {
    const prefix = '/' + segments.slice(0, i).join('/');
    if (RELATED_PAGES[prefix]) {
      return RELATED_PAGES[prefix].slice(0, maxPages);
    }
  }

  // Default fallback - return some general navigation
  return [
    { label: 'Hub', href: '/hub', description: 'Main dashboard' },
    { label: 'Debates', href: '/debates', description: 'View debates' },
    { label: 'Knowledge', href: '/knowledge', description: 'Knowledge base' },
  ].slice(0, maxPages);
}

/**
 * Related Pages navigation component.
 * Shows contextually relevant pages based on current location.
 */
export function RelatedPages({
  pages,
  className = '',
  maxPages = 4,
  title = 'Related',
}: RelatedPagesProps) {
  const pathname = usePathname();

  // Use custom pages or auto-detect
  const relatedPages = pages || findRelatedPages(pathname, maxPages);

  // Don't render if no related pages
  if (relatedPages.length === 0) {
    return null;
  }

  return (
    <nav aria-label="Related pages" className={`flex flex-col gap-2 ${className}`}>
      <span className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
        {title}
      </span>
      <ul className="flex flex-wrap gap-2" role="list">
        {relatedPages.map((page, index) => (
          <li key={index}>
            <Link
              href={page.href}
              className="inline-flex items-center gap-1 px-2 py-1 text-xs font-theme-data
                         border border-[var(--accent)]/20 rounded bg-surface/50
                         hover:border-[var(--accent)]/50 hover:bg-surface
                         transition-colors group"
              title={page.description}
            >
              <span className="text-[var(--accent)]/60 group-hover:text-[var(--accent)]">&gt;</span>
              <span className="text-text-secondary group-hover:text-text-primary">
                {page.label}
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export default RelatedPages;
