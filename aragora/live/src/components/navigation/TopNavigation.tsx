'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useAdaptiveMode } from '@/context/AdaptiveModeContext';
import { AdaptiveModeToggle, AdaptiveModeBadge } from '@/components/ui/AdaptiveModeToggle';
import { useSidebar } from '@/context/SidebarContext';

/**
 * Use-case driven navigation tabs
 *
 * Each tab represents a primary use case, with sub-navigation for specific features.
 */
export interface NavTab {
  id: string;
  label: string;
  icon: string;
  description: string;
  href: string;
  /** Features/pages within this tab */
  subItems: NavSubItem[];
  /** Requires advanced mode to show */
  advancedOnly?: boolean;
}

export interface NavSubItem {
  label: string;
  href: string;
  icon?: string;
  description?: string;
  advancedOnly?: boolean;
}

/**
 * Primary use-case tabs configuration
 *
 * Maps to backend endpoint groups for discoverability
 */
export const USE_CASE_TABS: NavTab[] = [
  {
    id: 'command',
    label: 'Command',
    icon: '\u25B8',
    description: 'Brain dump ideas, watch AI build execution plans',
    href: '/command',
    subItems: [
      {
        label: 'Command Center',
        href: '/command',
        icon: '\u25B8',
        description: 'AI-powered idea-to-execution',
      },
      {
        label: 'Pipeline',
        href: '/pipeline',
        icon: '|',
        description: 'Stage-by-stage pipeline view',
      },
      {
        label: 'Self-Improve',
        href: '/nomic-control',
        icon: '@',
        description: 'Monitor Nomic Loop',
      },
    ],
  },
  {
    id: 'security',
    label: 'Security',
    icon: '!',
    description: 'Code review, API scanning, red team exercises',
    href: '/security',
    subItems: [
      { label: 'Overview', href: '/security', icon: '#' },
      {
        label: 'Code Review',
        href: '/reviews',
        icon: '<',
        description: 'Automated security analysis',
      },
      {
        label: 'API Scan',
        href: '/gauntlet/api',
        icon: '>',
        description: 'API vulnerability testing',
      },
      {
        label: 'Red Team',
        href: '/gauntlet/redteam',
        icon: '!',
        description: 'Adversarial testing',
        advancedOnly: true,
      },
      { label: 'Reports', href: '/security/reports', icon: '|', advancedOnly: true },
    ],
  },
  {
    id: 'compliance',
    label: 'Compliance',
    icon: '%',
    description: 'GDPR, HIPAA, SOX regulatory audits',
    href: '/compliance',
    subItems: [
      { label: 'Overview', href: '/compliance', icon: '#' },
      {
        label: 'GDPR Check',
        href: '/gauntlet/gdpr',
        icon: 'G',
        description: 'Data protection compliance',
      },
      {
        label: 'HIPAA Audit',
        href: '/gauntlet/hipaa',
        icon: 'H',
        description: 'Healthcare compliance',
      },
      { label: 'SOX Review', href: '/gauntlet/sox', icon: 'S', description: 'Financial controls' },
      {
        label: 'Document Audit',
        href: '/audit',
        icon: '|',
        description: 'Policy document analysis',
      },
      { label: 'Reports', href: '/compliance/reports', icon: '>', advancedOnly: true },
    ],
  },
  {
    id: 'architecture',
    label: 'Architecture',
    icon: '@',
    description: 'Stress testing, incident analysis, system design',
    href: '/architecture',
    subItems: [
      { label: 'Overview', href: '/architecture', icon: '#' },
      {
        label: 'Stress Test',
        href: '/gauntlet',
        icon: '%',
        description: 'Decision stress testing',
      },
      {
        label: 'Incident Analysis',
        href: '/gauntlet/incident',
        icon: '!',
        description: 'Root cause analysis',
      },
      {
        label: 'Graph Debate',
        href: '/debates/graph',
        icon: '*',
        description: 'Multi-agent topology',
        advancedOnly: true,
      },
      { label: 'Design Review', href: '/architecture/review', icon: '?', advancedOnly: true },
      {
        label: 'Nomic Loop',
        href: '/nomic-control',
        icon: '@',
        description: 'Self-improvement observatory',
      },
    ],
  },
  {
    id: 'research',
    label: 'Research',
    icon: '?',
    description: 'Literature review, knowledge synthesis',
    href: '/research',
    subItems: [
      { label: 'Overview', href: '/research', icon: '#' },
      { label: 'New Research', href: '/arena', icon: '+', description: 'Start a research debate' },
      {
        label: 'Knowledge Base',
        href: '/knowledge',
        icon: '?',
        description: 'Search synthesized insights',
      },
      {
        label: 'Evidence',
        href: '/evidence',
        icon: '|',
        description: 'Source chain tracking',
        advancedOnly: true,
      },
      { label: 'Gallery', href: '/gallery', icon: '*', description: 'Public research debates' },
      { label: 'MCP Tools', href: '/tools', icon: '>', description: 'Explore 70+ AI tools' },
    ],
  },
  {
    id: 'intelligence',
    label: 'Intelligence',
    icon: '*',
    description: 'Memory, knowledge, and cross-debate learning',
    href: '/intelligence',
    subItems: [
      { label: 'Overview', href: '/intelligence', icon: '#' },
      { label: 'Memory', href: '/memory', icon: '~' },
      { label: 'Knowledge', href: '/knowledge', icon: '?' },
      { label: 'Facts', href: '/intelligence#facts', icon: '|' },
    ],
  },
  {
    id: 'decisions',
    label: 'Decisions',
    icon: '^',
    description: 'Vendor comparison, contract review, risk analysis',
    href: '/decisions',
    subItems: [
      { label: 'Overview', href: '/decisions', icon: '#' },
      { label: 'New Decision', href: '/arena', icon: '+', description: 'Start a decision debate' },
      {
        label: 'Matrix Debate',
        href: '/debates/matrix',
        icon: '[',
        description: 'Structured comparison',
        advancedOnly: true,
      },
      { label: 'Receipts', href: '/receipts', icon: '>', description: 'Decision audit trails' },
      { label: 'History', href: '/debates', icon: '#', description: 'Past decisions' },
    ],
  },
  {
    id: 'industry',
    label: 'Industry',
    icon: '/',
    description: 'Vertical-specific workflows',
    href: '/verticals',
    advancedOnly: true,
    subItems: [
      { label: 'Overview', href: '/verticals', icon: '#' },
      {
        label: 'Healthcare',
        href: '/verticals/healthcare',
        icon: 'H',
        description: 'Clinical decision support',
      },
      {
        label: 'Finance',
        href: '/verticals/finance',
        icon: '$',
        description: 'Risk and compliance',
      },
      {
        label: 'Legal',
        href: '/verticals/legal',
        icon: 'L',
        description: 'Contract and case analysis',
      },
      { label: 'Custom', href: '/verticals/custom', icon: '+', description: 'Configure vertical' },
    ],
  },
];

export function TopNavigation() {
  const pathname = usePathname();
  const { isAdvanced } = useAdaptiveMode();
  const { toggle } = useSidebar();

  // Determine active tab from pathname
  const activeTab = getActiveTab(pathname);

  // Filter tabs based on adaptive mode
  const visibleTabs = USE_CASE_TABS.filter((tab) => !tab.advancedOnly || isAdvanced);

  return (
    <nav className="sticky top-0 z-30 bg-bg/95 backdrop-blur border-b border-[var(--accent)]/30">
      {/* Primary navigation row */}
      <div className="flex items-center justify-between px-4">
        {/* Left: Menu button + Logo */}
        <div className="flex items-center gap-4">
          <button
            onClick={toggle}
            className="p-2 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors rounded"
            aria-label="Open navigation menu"
          >
            <span className="font-theme-data text-lg">[=]</span>
          </button>

          <Link
            href="/"
            className="text-[var(--accent)] font-theme-data font-bold text-lg hover:text-[var(--acid-cyan)] transition-colors"
          >
            ARAGORA
          </Link>
        </div>

        {/* Center: Use-case tabs */}
        <div className="hidden md:flex items-center gap-1">
          {visibleTabs.map((tab) => (
            <NavTabButton key={tab.id} tab={tab} isActive={activeTab?.id === tab.id} />
          ))}
        </div>

        {/* Right: Mode toggle + actions */}
        <div className="flex items-center gap-3">
          <AdaptiveModeBadge className="hidden sm:block" />
          <AdaptiveModeToggle compact showLabels={false} className="hidden lg:flex" />

          {/* Quick action */}
          <Link
            href="/hub"
            className="px-3 py-1.5 bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/20 transition-colors rounded"
          >
            [+] New
          </Link>
        </div>
      </div>

      {/* Sub-navigation row (for active tab) */}
      {activeTab && <TabSubNavigation tab={activeTab} currentPath={pathname} />}
    </nav>
  );
}

/**
 * Individual tab button in primary nav
 */
function NavTabButton({ tab, isActive }: { tab: NavTab; isActive: boolean }) {
  return (
    <Link
      href={tab.href}
      className={`
        flex items-center gap-1.5 px-3 py-2
        font-theme-data text-sm
        transition-colors
        border-b-2
        ${
          isActive
            ? 'border-[var(--accent)] text-[var(--accent)]'
            : 'border-transparent text-text-muted hover:text-text hover:border-[var(--accent)]/30'
        }
      `}
      title={tab.description}
    >
      <span className="text-[var(--accent)]/70">{tab.icon}</span>
      <span>{tab.label}</span>
    </Link>
  );
}

/**
 * Sub-navigation within a tab
 */
function TabSubNavigation({ tab, currentPath }: { tab: NavTab; currentPath: string }) {
  const { isAdvanced } = useAdaptiveMode();

  const visibleItems = tab.subItems.filter((item) => !item.advancedOnly || isAdvanced);

  return (
    <div className="flex items-center gap-1 px-4 py-1 border-t border-[var(--accent)]/10 bg-surface/50 overflow-x-auto">
      {visibleItems.map((item) => {
        const isActive =
          currentPath === item.href ||
          (item.href !== tab.href && currentPath.startsWith(item.href));

        return (
          <Link
            key={item.href}
            href={item.href}
            className={`
              flex items-center gap-1 px-2 py-1
              font-theme-data text-xs
              rounded
              transition-colors
              whitespace-nowrap
              ${
                isActive
                  ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                  : 'text-text-muted hover:text-text hover:bg-[var(--accent)]/5'
              }
            `}
            title={item.description}
          >
            {item.icon && <span className="opacity-70">{item.icon}</span>}
            <span>{item.label}</span>
          </Link>
        );
      })}
    </div>
  );
}

/**
 * Determine which tab is active based on current pathname
 */
function getActiveTab(pathname: string): NavTab | null {
  // Direct match first
  for (const tab of USE_CASE_TABS) {
    if (pathname === tab.href) return tab;
    for (const sub of tab.subItems) {
      if (pathname === sub.href) return tab;
    }
  }

  // Prefix match
  for (const tab of USE_CASE_TABS) {
    if (pathname.startsWith(tab.href + '/')) return tab;
    for (const sub of tab.subItems) {
      if (pathname.startsWith(sub.href + '/')) return tab;
    }
  }

  // Map known routes to tabs
  const routeTabMap: Record<string, string> = {
    '/command': 'command',
    '/pipeline': 'command',
    '/nomic-control': 'command',
    '/reviews': 'security',
    '/gauntlet': 'architecture',
    '/audit': 'compliance',
    '/knowledge': 'research',
    '/arena': 'research',
    '/debates': 'decisions',
    '/receipts': 'decisions',
    '/gallery': 'research',
    '/verticals': 'industry',
    '/evidence': 'research',
    '/intelligence': 'intelligence',
    '/tools': 'research',
  };

  for (const [prefix, tabId] of Object.entries(routeTabMap)) {
    if (pathname.startsWith(prefix)) {
      return USE_CASE_TABS.find((t) => t.id === tabId) || null;
    }
  }

  return null;
}

/**
 * Mobile navigation drawer content
 *
 * Used when viewport is too narrow for tab display
 */
export function MobileNavTabs() {
  const pathname = usePathname();
  const { isAdvanced } = useAdaptiveMode();

  const visibleTabs = USE_CASE_TABS.filter((tab) => !tab.advancedOnly || isAdvanced);

  return (
    <div className="space-y-4">
      {visibleTabs.map((tab) => {
        const isActive = pathname.startsWith(tab.href);
        const visibleItems = tab.subItems.filter((item) => !item.advancedOnly || isAdvanced);

        return (
          <div key={tab.id} className="border border-[var(--accent)]/20 rounded">
            <Link
              href={tab.href}
              className={`
                flex items-center gap-2 px-3 py-2
                font-theme-data
                ${isActive ? 'bg-[var(--accent)]/10 text-[var(--accent)]' : 'text-text'}
              `}
            >
              <span className="text-[var(--accent)]/70">{tab.icon}</span>
              <span className="font-bold">{tab.label}</span>
            </Link>

            {isActive && visibleItems.length > 0 && (
              <div className="border-t border-[var(--accent)]/10 px-2 py-1">
                {visibleItems.map((item) => (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`
                      block px-3 py-1.5 text-sm
                      ${
                        pathname === item.href
                          ? 'text-[var(--accent)]'
                          : 'text-text-muted hover:text-text'
                      }
                    `}
                  >
                    {item.label}
                  </Link>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
