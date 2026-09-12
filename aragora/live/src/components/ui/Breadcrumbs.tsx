'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

interface BreadcrumbItem {
  label: string;
  href?: string;
}

interface BreadcrumbsProps {
  /** Custom items override auto-generation */
  items?: BreadcrumbItem[];
  /** Hide home link */
  hideHome?: boolean;
  /** Additional CSS classes */
  className?: string;
}

// Route to human-readable label mapping
const ROUTE_LABELS: Record<string, string> = {
  '': 'Home',
  debate: 'Debate',
  debates: 'Debates',
  agents: 'Agents',
  agent: 'Agent',
  analytics: 'Analytics',
  settings: 'Settings',
  admin: 'Admin',
  knowledge: 'Knowledge',
  memory: 'Memory',
  leaderboard: 'Leaderboard',
  tournaments: 'Tournaments',
  insights: 'Insights',
  social: 'Social',
  workflows: 'Workflows',
  builder: 'Builder',
  runtime: 'Runtime',
  ml: 'ML Intelligence',
  training: 'Training',
  explorer: 'Explorer',
  models: 'Models',
  moments: 'Moments',
  inbox: 'Inbox',
  connectors: 'Connectors',
  broadcast: 'Broadcast',
  calibration: 'Calibration',
  verification: 'Verification',
  evidence: 'Evidence',
  crux: 'Crux Analysis',
  'red-team': 'Red Team',
  network: 'Network',
  probe: 'Probe',
  modes: 'Modes',
  checkpoints: 'Checkpoints',
  breakpoints: 'Breakpoints',
  replays: 'Replays',
  gauntlet: 'Gauntlet',
  laboratory: 'Laboratory',
  evolution: 'Evolution',
  genesis: 'Genesis',
  hub: 'Hub',
  portal: 'Portal',
  billing: 'Billing',
  pricing: 'Pricing',
  documents: 'Documents',
  transcribe: 'Transcribe',
  speech: 'Speech',
  voice: 'Voice',
  queue: 'Queue',
  scheduler: 'Scheduler',
  selection: 'Selection',
  quality: 'Quality',
  impasse: 'Impasse',
  uncertainty: 'Uncertainty',
  forks: 'Forks',
  compare: 'Compare',
  gallery: 'Gallery',
  templates: 'Templates',
  plugins: 'Plugins',
  integrations: 'Integrations',
  chat: 'Chat',
  webhooks: 'Webhooks',
  observability: 'Observability',
  developer: 'Developer',
  'api-explorer': 'API Explorer',
  'control-plane': 'Dashboard',
  'nomic-control': 'Nomic Control',
  organization: 'Organization',
  members: 'Members',
  verticals: 'Verticals',
  reviews: 'Reviews',
  'ab-testing': 'A/B Testing',
  batch: 'Batch',
  repository: 'Repository',
  security: 'Security',
  privacy: 'Privacy',
  about: 'About',
  auth: 'Auth',
  login: 'Login',
  register: 'Register',
  audit: 'Audit',
  users: 'Users',
  tenants: 'Tenants',
  usage: 'Usage',
  revenue: 'Revenue',
  personas: 'Personas',
  forensic: 'Forensic',
  'ab-tests': 'A/B Tests',
  graph: 'Graph',
  matrix: 'Matrix',
  'memory-analytics': 'Memory Analytics',
};

/**
 * Get human-readable label for a route segment
 */
function getLabel(segment: string): string {
  // Check if it's a known route
  if (ROUTE_LABELS[segment]) {
    return ROUTE_LABELS[segment];
  }

  // Check if it's a dynamic segment (UUID-like or slug)
  if (segment.match(/^[a-f0-9-]{8,}$/i)) {
    return segment.slice(0, 8) + '...';
  }

  // Convert kebab-case to Title Case
  return segment
    .split('-')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

/**
 * Generate breadcrumb items from pathname
 */
function generateBreadcrumbs(pathname: string, hideHome: boolean): BreadcrumbItem[] {
  const segments = pathname.split('/').filter(Boolean);
  const items: BreadcrumbItem[] = [];

  // Add home if not hidden
  if (!hideHome) {
    items.push({ label: 'Home', href: '/' });
  }

  // Build path progressively
  let currentPath = '';
  for (let i = 0; i < segments.length; i++) {
    const segment = segments[i];
    currentPath += `/${segment}`;

    // Skip dynamic route markers like [[...id]]
    if (segment.startsWith('[[') || segment.startsWith('[')) {
      continue;
    }

    const isLast = i === segments.length - 1;
    items.push({ label: getLabel(segment), href: isLast ? undefined : currentPath });
  }

  return items;
}

/**
 * Breadcrumbs navigation component.
 * Auto-generates from pathname or accepts custom items.
 */
export function Breadcrumbs({ items, hideHome = false, className = '' }: BreadcrumbsProps) {
  const pathname = usePathname();

  // Use custom items or auto-generate
  const breadcrumbItems = items || generateBreadcrumbs(pathname, hideHome);

  // Don't render if only home or empty
  if (breadcrumbItems.length <= 1) {
    return null;
  }

  return (
    <nav
      aria-label="Breadcrumb"
      className={`flex items-center gap-1 text-xs font-theme-data text-text-muted ${className}`}
    >
      <ol className="flex items-center gap-1" role="list">
        {breadcrumbItems.map((item, index) => {
          const isLast = index === breadcrumbItems.length - 1;

          return (
            <li key={index} className="flex items-center gap-1">
              {index > 0 && (
                <span className="text-[var(--accent)]/30" aria-hidden="true">
                  /
                </span>
              )}

              {item.href && !isLast ? (
                <Link
                  href={item.href}
                  className="hover:text-[var(--accent)] transition-colors"
                  aria-current={undefined}
                >
                  {item.label}
                </Link>
              ) : (
                <span
                  className={isLast ? 'text-[var(--accent)]' : ''}
                  aria-current={isLast ? 'page' : undefined}
                >
                  {item.label}
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}

export default Breadcrumbs;
