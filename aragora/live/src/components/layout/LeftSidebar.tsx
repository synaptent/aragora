'use client';

import React, { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useLayout } from '@/context/LayoutContext';
import { useAuth } from '@/context/AuthContext';
import { useProgressiveMode, ProgressiveMode } from '@/context/ProgressiveModeContext';
import { ModeSelector } from '@/components/ui/FeatureCard';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NavItem {
  label: string;
  href: string;
  icon: string;
  minMode?: ProgressiveMode;
  requiresAuth?: boolean;
  adminOnly?: boolean;
}

interface NavSection {
  title: string;
  key: string;
  items: NavItem[];
  /** Section-level mode gate: entire section hidden below this mode */
  minMode?: ProgressiveMode;
  /** Highlighted style (e.g. Enterprise) */
  highlight?: boolean;
  /** Admin-only section */
  adminOnly?: boolean;
  /** Collapsible (default true) */
  collapsible?: boolean;
}

// ---------------------------------------------------------------------------
// Quick Actions -- always visible at top, styled differently
// ---------------------------------------------------------------------------

const quickActions: NavItem[] = [
  { label: 'Try Now', href: '/demo/instant', icon: '\u26A1' },
  { label: 'Demo', href: '/demo', icon: '\u2605' },
  { label: 'New Debate', href: '/arena', icon: '+' },
  { label: 'Mission Control', href: '/mission-control', icon: '\u25C8', minMode: 'standard' },
  { label: 'Inbox', href: '/inbox', icon: '!', minMode: 'standard' },
];

// =============================================================================
// SIDEBAR NAVIGATION - Progressive Disclosure
// =============================================================================
// All ~197 frontend pages are organized into collapsible category groups below.
// Each section is clearly marked so that other agents and developers understand
// the structure.  DO NOT remove links from these sections -- they exist to make
// every page discoverable via the sidebar.  If a page is added to the app
// directory, add a corresponding NavItem here.
// =============================================================================

const navSections: NavSection[] = [
  /* === CORE SECTION === Progressive disclosure group
   * Always-visible top-level pages. Not collapsible so users always see
   * the primary entry points (Dashboard, Debates, Pipeline, etc.).
   */
  {
    title: 'Core',
    key: 'core',
    collapsible: false,
    items: [
      { label: 'Home', href: '/', icon: '\u2261' },
      { label: 'Dashboard', href: '/dashboard', icon: '\u25A6' },
      { label: 'Debates', href: '/debates', icon: '\u2318' },
      { label: 'Oracle', href: '/oracle', icon: '\u25C9' },
      { label: 'Receipts', href: '/receipts', icon: '\u2611' },
      { label: 'Pipeline', href: '/pipeline', icon: '\u25B8', minMode: 'standard' },
      { label: 'Ideas', href: '/ideas', icon: '\u2726', minMode: 'standard' },
      { label: 'Goals', href: '/goals', icon: '\u25CE', minMode: 'standard' },
      { label: 'Actions', href: '/actions', icon: '\u25B6', minMode: 'standard' },
      { label: 'Knowledge', href: '/knowledge', icon: '?', minMode: 'standard' },
      { label: 'Agents', href: '/agents', icon: '&', minMode: 'standard' },
      { label: 'Analytics', href: '/analytics', icon: '~', minMode: 'standard' },
    ],
  },

  /* === DECISIONS SECTION === Progressive disclosure group
   * All debate-related workflows: deliberations, spectating, replays, etc.
   */
  {
    title: 'Decisions',
    key: 'decisions',
    minMode: 'standard',
    items: [
      { label: 'Deliberations', href: '/deliberations', icon: '\u2696' },
      { label: 'Playbooks', href: '/playbooks', icon: 'P' },
      { label: 'Batch Debates', href: '/batch', icon: '\u229E' },
      { label: 'Forks', href: '/forks', icon: '\u2442' },
      { label: 'Impasse', href: '/impasse', icon: '\u26A0' },
      { label: 'Compare', href: '/compare', icon: '\u2194' },
      { label: 'Crux', href: '/crux', icon: '\u2020' },
      { label: 'Debate Graph', href: '/debates/graph', icon: '\u25C8', minMode: 'advanced' },
      { label: 'Debate Matrix', href: '/debates/matrix', icon: '\u25A6', minMode: 'advanced' },
      { label: 'Provenance', href: '/debates/provenance', icon: '\u2192', minMode: 'advanced' },
      { label: 'Spectate', href: '/spectate', icon: '\u25C9', minMode: 'standard' },
      { label: 'Replays', href: '/replays', icon: '\u21BB', minMode: 'advanced' },
      { label: 'Settlements', href: '/settlements', icon: '\u2696', minMode: 'expert' },
    ],
  },

  /* === ENTERPRISE SECTION === Progressive disclosure group
   * Enterprise features: compliance, audit, policy, backup, moderation.
   * Highlighted with PRO badge.
   */
  {
    title: 'Enterprise',
    key: 'enterprise',
    minMode: 'standard',
    highlight: true,
    items: [
      { label: 'Decision Integrity', href: '/decision-integrity', icon: '\u2726' },
      { label: 'Gauntlet', href: '/gauntlet', icon: '\u26A1' },
      { label: 'Compliance', href: '/compliance', icon: '\u2713' },
      { label: 'Audit', href: '/audit', icon: '\u2611' },
      { label: 'New Audit', href: '/audit/new', icon: '\u271A', minMode: 'advanced' },
      { label: 'Audit Templates', href: '/audit/templates', icon: '\u2610', minMode: 'advanced' },
      { label: 'Audit View', href: '/audit/view', icon: '\u2630', minMode: 'advanced' },
      { label: 'Dashboard', href: '/control-plane', icon: '\u25CE' },
      { label: 'Receipts', href: '/receipts', icon: '$' },
      { label: 'Policy', href: '/policy', icon: '\u2696' },
      { label: 'Privacy', href: '/privacy', icon: '\u229E' },
      { label: 'Audit Trail', href: '/audit-trail', icon: '\u2610' },
      { label: 'Backup', href: '/backup', icon: '\u2B73', minMode: 'advanced' },
      { label: 'Moderation', href: '/moderation', icon: '\u2691' },
      { label: 'Blockchain', href: '/blockchain', icon: '\u26D3', minMode: 'advanced' },
    ],
  },

  /* === ANALYTICS & INSIGHTS SECTION === Progressive disclosure group
   * Dashboards, performance tracking, cost analysis, ELO analytics.
   */
  {
    title: 'Analytics & Insights',
    key: 'analytics',
    minMode: 'standard',
    items: [
      { label: 'Insights', href: '/insights', icon: '\u272A' },
      { label: 'Intelligence', href: '/intelligence', icon: '\u269B' },
      { label: 'System Intelligence', href: '/system-intelligence', icon: '\u2328' },
      { label: 'Outcome Dashboard', href: '/outcome-dashboard', icon: '\u2611' },
      {
        label: 'Analytics Outcomes',
        href: '/analytics/outcomes',
        icon: '\u2714',
        minMode: 'standard',
      },
      { label: 'Leaderboard', href: '/leaderboard', icon: '^' },
      { label: 'Performance', href: '/agent-performance', icon: '\u2261' },
      {
        label: 'Performance Detail',
        href: '/agents/performance',
        icon: '\u2197',
        minMode: 'advanced',
      },
      { label: 'ELO Analytics', href: '/elo-analytics', icon: '\u2295', minMode: 'standard' },
      { label: 'Agent Evolution', href: '/agent-evolution', icon: '\u267E', minMode: 'advanced' },
      { label: 'Tournaments', href: '/tournaments', icon: '\u2295' },
      { label: 'Calibration', href: '/calibration', icon: '\u2316', minMode: 'advanced' },
      { label: 'Evaluation', href: '/evaluation', icon: '\u2606', minMode: 'advanced' },
      { label: 'Uncertainty', href: '/uncertainty', icon: '\u00B1', minMode: 'advanced' },
      { label: 'Quality', href: '/quality', icon: '\u2605', minMode: 'advanced' },
      { label: 'Costs', href: '/costs', icon: '\u00A2', minMode: 'standard' },
      { label: 'Budgets', href: '/budgets', icon: '\u00A3', minMode: 'standard' },
      { label: 'Differentiation', href: '/differentiation', icon: '\u25C7', minMode: 'standard' },
      { label: 'Spend Breakdown', href: '/analytics/spend', icon: '\u00A4', minMode: 'standard' },
      { label: 'Spend', href: '/spend', icon: '$', minMode: 'standard' },
      { label: 'Decisions', href: '/analytics/decisions', icon: '\u2713', minMode: 'standard' },
      { label: 'Usage', href: '/usage', icon: '%', minMode: 'standard' },
      {
        label: 'Argument Analysis',
        href: '/argument-analysis',
        icon: '\u2726',
        minMode: 'standard',
      },
    ],
  },

  /* === TOOLS & INTEGRATIONS SECTION === Progressive disclosure group
   * External tools, connectors, plugins, API docs, marketplace.
   */
  {
    title: 'Tools',
    key: 'tools',
    minMode: 'standard',
    items: [
      { label: 'Tools', href: '/tools', icon: '\u2692' },
      { label: 'Documents', href: '/documents', icon: ']' },
      { label: 'Connectors', href: '/connectors', icon: '<' },
      { label: 'Templates', href: '/templates', icon: '[' },
      { label: 'Integrations', href: '/integrations', icon: '\u222B' },
      {
        label: 'Chat Integrations',
        href: '/integrations/chat',
        icon: '\u2709',
        minMode: 'advanced',
      },
      { label: 'Webhooks', href: '/webhooks', icon: '\u21C4', minMode: 'advanced' },
      { label: 'Marketplace', href: '/marketplace', icon: '\u229A' },
      { label: 'Plugins', href: '/plugins', icon: '\u2699', minMode: 'advanced' },
      { label: 'MCP Tools', href: '/mcp', icon: '\u2699', minMode: 'advanced' },
      { label: 'API Explorer', href: '/api-explorer', icon: '{', minMode: 'advanced' },
      { label: 'API Docs', href: '/api-docs', icon: '\u2261', minMode: 'advanced' },
    ],
  },

  /* === BROWSE & SOCIAL SECTION === Progressive disclosure group
   * Gallery, reviews, social features, shared inbox, broadcast.
   */
  {
    title: 'Browse',
    key: 'browse',
    minMode: 'standard',
    items: [
      { label: 'Gallery', href: '/gallery', icon: '\u2726' },
      { label: 'Reviews', href: '/reviews', icon: '\u2606' },
      { label: 'Hub', href: '/hub', icon: '\u2302' },
      { label: 'Portal', href: '/portal', icon: '\u2302', minMode: 'standard' },
      { label: 'Social', href: '/social', icon: '\u263A', minMode: 'standard' },
      {
        label: 'Shared Inbox',
        href: '/shared-inbox',
        icon: '\u2709',
        minMode: 'standard',
        requiresAuth: true,
      },
      { label: 'Broadcast', href: '/broadcast', icon: '\u25CE', minMode: 'advanced' },
      { label: 'Moments', href: '/moments', icon: '\u25C6', minMode: 'standard' },
    ],
  },

  /* === MEMORY & KNOWLEDGE SECTION === Progressive disclosure group
   * Memory systems, knowledge flow, supermemory, evidence, beliefs, RLM.
   */
  {
    title: 'Memory & Knowledge',
    key: 'memory',
    minMode: 'standard',
    items: [
      { label: 'Memory', href: '/memory', icon: '=' },
      { label: 'Memory Gateway', href: '/memory-gateway', icon: '\u2194' },
      { label: 'Supermemory', href: '/supermemory', icon: '\u221E', minMode: 'standard' },
      { label: 'Knowledge Flow', href: '/knowledge-flow', icon: '\u21C4' },
      {
        label: 'Knowledge Learning',
        href: '/knowledge/learning',
        icon: '\u2042',
        minMode: 'advanced',
      },
      { label: 'Cross-Debate', href: '/cross-debate', icon: '\u2728', minMode: 'standard' },
      { label: 'Pulse', href: '/pulse', icon: '\u2665', minMode: 'standard' },
      { label: 'Memory Analytics', href: '/memory-analytics', icon: '\u2261', minMode: 'advanced' },
      { label: 'Evidence', href: '/evidence', icon: '\u2690' },
      { label: 'Beliefs', href: '/beliefs', icon: '\u0394', minMode: 'standard' },
      { label: 'Consensus History', href: '/consensus', icon: '\u2263', minMode: 'standard' },
      { label: 'Explainability', href: '/explainability', icon: '?!', minMode: 'standard' },
      { label: 'Repository', href: '/repository', icon: '\u25A3', minMode: 'advanced' },
      { label: 'RLM', href: '/rlm', icon: '\u21BA', minMode: 'advanced' },
      { label: 'Reasoning', href: '/reasoning', icon: '\u22A2', minMode: 'standard' },
    ],
  },

  /* === DEVELOPMENT SECTION === Progressive disclosure group
   * Code review, codebase audit, security scanning, sandbox, feature flags.
   */
  {
    title: 'Development',
    key: 'development',
    minMode: 'standard',
    items: [
      { label: 'Code Review', href: '/code-review', icon: '</>' },
      { label: 'Codebase Audit', href: '/codebase-audit', icon: '\u2611' },
      { label: 'Security Scan', href: '/security-scan', icon: '\u26BF' },
      { label: 'Developer', href: '/developer', icon: '>_', minMode: 'advanced' },
      { label: 'Sandbox', href: '/sandbox', icon: '\u25A1', minMode: 'advanced' },
      { label: 'Feature Flags', href: '/feature-flags', icon: '\u2691', minMode: 'advanced' },
    ],
  },

  /* === ORCHESTRATION & AUTOMATION SECTION === Progressive disclosure group
   * Workflow engine, scheduling, queues, autonomous mode, command center.
   */
  {
    title: 'Orchestration',
    key: 'orchestration',
    minMode: 'advanced',
    items: [
      { label: 'Orchestration', href: '/orchestration', icon: '\u266B' },
      { label: 'Autonomous', href: '/autonomous', icon: '\u2699' },
      { label: 'Scheduler', href: '/scheduler', icon: '\u25F7' },
      { label: 'Pulse Scheduler', href: '/pulse-scheduler', icon: '\u23F1', minMode: 'advanced' },
      { label: 'Queue', href: '/queue', icon: '\u2630' },
      { label: 'Nomic Control', href: '/nomic-control', icon: '\u221E' },
      { label: 'Command Center', href: '/command-center', icon: '\u2318' },
      { label: 'Command', href: '/command', icon: '\u276F', minMode: 'advanced' },
      { label: 'Workflow Templates', href: '/workflows', icon: '\u2610' },
      { label: 'Workflow Builder', href: '/workflows/builder', icon: '\u2692' },
      { label: 'Workflow Runtime', href: '/workflows/runtime', icon: '\u25B6' },
      { label: 'Self-Improve', href: '/self-improve', icon: '\u21BB', minMode: 'standard' },
      { label: 'Coordination', href: '/coordination', icon: '\u2693', minMode: 'advanced' },
      { label: 'Feedback Hub', href: '/feedback-hub', icon: '\u21C4', minMode: 'advanced' },
    ],
  },

  /* === SECURITY SECTION === Progressive disclosure group
   * Security scanning, verification, data classification.
   */
  {
    title: 'Security',
    key: 'security',
    minMode: 'advanced',
    items: [
      { label: 'Security', href: '/security', icon: '\u26BF' },
      { label: 'Verification', href: '/verification', icon: '\u2713' },
      { label: 'Quick Verify', href: '/verify', icon: '\u2714' },
      {
        label: 'Data Classification',
        href: '/data-classification',
        icon: '\u2263',
        minMode: 'advanced',
      },
    ],
  },

  /* === AI & ML SECTION === Progressive disclosure group
   * Training, model management, ML experiments, A/B testing.
   */
  {
    title: 'AI & ML',
    key: 'ai-ml',
    minMode: 'advanced',
    items: [
      { label: 'Training', href: '/training', icon: '\u2699' },
      { label: 'Model Explorer', href: '/training/explorer', icon: '\u2316' },
      { label: 'Models', href: '/training/models', icon: '\u2206' },
      { label: 'ML', href: '/ml', icon: '\u2206' },
      { label: 'Selection', href: '/selection', icon: '\u21D2' },
      { label: 'Evolution', href: '/evolution', icon: '\u267E' },
      { label: 'AB Testing', href: '/ab-testing', icon: 'A|B' },
    ],
  },

  /* === VOICE & MEDIA SECTION === Progressive disclosure group
   * Voice synthesis, speech, transcription.
   */
  {
    title: 'Voice & Media',
    key: 'voice-media',
    minMode: 'advanced',
    items: [
      { label: 'Voice', href: '/voice', icon: '\u266A' },
      { label: 'Speech', href: '/speech', icon: '\u25B6' },
      { label: 'Transcribe', href: '/transcribe', icon: '\u270E' },
    ],
  },

  /* === ADVANCED SECTION === Progressive disclosure group
   * Power-user pages: genesis, introspection, red-team, laboratory.
   */
  {
    title: 'Advanced',
    key: 'advanced',
    minMode: 'advanced',
    items: [
      { label: 'Genesis', href: '/genesis', icon: '@', minMode: 'expert' },
      { label: 'Introspection', href: '/introspection', icon: '\u2299', minMode: 'expert' },
      { label: 'Network', href: '/network', icon: '\u2B21', minMode: 'expert' },
      { label: 'Probe', href: '/probe', icon: '\u25CE', minMode: 'expert' },
      { label: 'Red Team', href: '/red-team', icon: '\u2620', minMode: 'expert' },
      { label: 'Op Modes', href: '/modes', icon: '#', minMode: 'expert' },
      { label: 'Laboratory', href: '/laboratory', icon: '\u2697', minMode: 'expert' },
      { label: 'Breakpoints', href: '/breakpoints', icon: '\u25CF', minMode: 'expert' },
      { label: 'Checkpoints', href: '/checkpoints', icon: '\u2713', minMode: 'expert' },
    ],
  },

  /* === MONITORING SECTION === Progressive disclosure group
   * Observability, system status, pulse trending.
   */
  {
    title: 'Monitoring',
    key: 'monitoring',
    minMode: 'advanced',
    items: [
      { label: 'Observability', href: '/observability', icon: '\u25C9' },
      { label: 'System Status', href: '/system-status', icon: '\u2665', minMode: 'advanced' },
    ],
  },

  /* === BUSINESS SECTION === Progressive disclosure group
   * Billing, accounting, pricing, verticals, organization management.
   */
  {
    title: 'Business',
    key: 'business',
    minMode: 'standard',
    items: [
      { label: 'Billing', href: '/billing', icon: '$', requiresAuth: true },
      { label: 'Accounting', href: '/accounting', icon: '\u2211', requiresAuth: true },
      { label: 'Plaid Connect', href: '/accounting/plaid', icon: '\u2194', requiresAuth: true },
      { label: 'Pricing', href: '/pricing', icon: '\u00A4' },
      { label: 'Verticals', href: '/verticals', icon: '/' },
      { label: 'Organization', href: '/organization', icon: '\u2302', requiresAuth: true },
      { label: 'Members', href: '/organization/members', icon: '\uD83D\uDC65', requiresAuth: true },
    ],
  },

  /* === SETTINGS SECTION === Progressive disclosure group
   * Always-visible bottom section. Not collapsible.
   */
  {
    title: 'Settings',
    key: 'settings',
    collapsible: false,
    items: [
      { label: 'Get Started', href: '/get-started', icon: '\u25B8' },
      { label: 'Features', href: '/features', icon: '\u2726', minMode: 'standard' },
      { label: 'Settings', href: '/settings', icon: '*', requiresAuth: true },
      { label: 'About', href: '/about', icon: 'i', minMode: 'standard' },
    ],
  },

  /* === ADMIN SECTION === Progressive disclosure group
   * Admin-only pages.  Only visible to users with admin role.
   * Contains all /admin/* sub-pages including dedup, retention, velocity.
   */
  {
    title: 'Admin',
    key: 'admin',
    adminOnly: true,
    items: [
      { label: 'Admin Dashboard', href: '/admin', icon: '\u2699' },
      { label: 'Users', href: '/admin/users', icon: '\uD83D\uDC64' },
      { label: 'Organizations', href: '/admin/organizations', icon: '#' },
      { label: 'Tenants', href: '/admin/tenants', icon: '\u2302' },
      { label: 'Revenue', href: '/admin/revenue', icon: '$' },
      { label: 'ROI Dashboard', href: '/admin/roi-dashboard', icon: '\u2197' },
      { label: 'Billing', href: '/admin/billing', icon: '\u00A4' },
      { label: 'Usage', href: '/admin/usage', icon: '%' },
      { label: 'Audit', href: '/admin/audit', icon: '\u2611' },
      { label: 'Security', href: '/admin/security', icon: '\u26BF' },
      { label: 'Evidence', href: '/admin/evidence', icon: '\u2690' },
      { label: 'Forensic', href: '/admin/forensic', icon: '\u2623' },
      { label: 'Knowledge', href: '/admin/knowledge', icon: '?' },
      { label: 'Knowledge Velocity', href: '/admin/knowledge/velocity', icon: '\u21C8' },
      { label: 'Memory', href: '/admin/memory', icon: '=' },
      { label: 'Nomic', href: '/admin/nomic', icon: '\u221E' },
      { label: 'Personas', href: '/admin/personas', icon: '&' },
      { label: 'Queue', href: '/admin/queue', icon: '\u2630' },
      { label: 'Dedup', href: '/admin/dedup', icon: '\u2A01' },
      { label: 'Retention', href: '/admin/retention', icon: '\u23F3' },
      { label: 'Streaming', href: '/admin/streaming', icon: '\u25B6' },
      { label: 'Training', href: '/admin/training', icon: '\u2699' },
      { label: 'Verticals', href: '/admin/verticals', icon: '/' },
      { label: 'Workspace', href: '/admin/workspace', icon: '\u25A3' },
      { label: 'AB Tests', href: '/admin/ab-tests', icon: 'A|B' },
      { label: 'Federation', href: '/admin/federation', icon: '\u2318' },
      { label: 'Intelligence', href: '/admin/intelligence', icon: '\u269B' },
      { label: 'Observability', href: '/admin/observability', icon: '\u25C9' },
      { label: 'System Health', href: '/admin/system-health', icon: '\u2665' },
    ],
  },
];

// ---------------------------------------------------------------------------
// Persistence key for collapsed section state
// ---------------------------------------------------------------------------
const COLLAPSED_SECTIONS_KEY = 'aragora-sidebar-collapsed-sections';

function loadCollapsedSections(): Set<string> {
  try {
    const saved = localStorage.getItem(COLLAPSED_SECTIONS_KEY);
    if (saved) return new Set(JSON.parse(saved));
  } catch {
    // ignore
  }
  return new Set<string>();
}

function saveCollapsedSections(collapsed: Set<string>) {
  try {
    localStorage.setItem(COLLAPSED_SECTIONS_KEY, JSON.stringify([...collapsed]));
  } catch {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function LeftSidebar() {
  const pathname = usePathname();
  const {
    leftSidebarOpen,
    leftSidebarCollapsed,
    closeLeftSidebar,
    setLeftSidebarCollapsed,
    isMobile,
    leftSidebarWidth,
  } = useLayout();
  const { isAuthenticated, user } = useAuth();
  const { isFeatureVisible } = useProgressiveMode();

  const isAdmin = user?.role === 'admin';

  // Collapsible section state
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());

  // Load collapsed state from localStorage on mount
  useEffect(() => {
    setCollapsedSections(loadCollapsedSections());
  }, []);

  const toggleSection = useCallback((key: string) => {
    setCollapsedSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      saveCollapsedSections(next);
      return next;
    });
  }, []);

  // Don't render on desktop if closed, but always render for mobile (as overlay)
  if (!isMobile && !leftSidebarOpen) {
    return null;
  }

  const filterItems = (items: NavItem[]) =>
    items.filter((item) => {
      if (item.requiresAuth && !isAuthenticated) return false;
      if (item.adminOnly && !isAdmin) return false;
      if (item.minMode && !isFeatureVisible(item.minMode)) return false;
      return true;
    });

  const isItemActive = (href: string) => {
    if (href === '/') return pathname === '/';
    return pathname === href || pathname?.startsWith(href + '/');
  };

  const renderNavItem = (item: NavItem) => {
    const isActive = isItemActive(item.href);

    return (
      <Link
        key={item.href}
        href={item.href}
        onClick={() => isMobile && closeLeftSidebar()}
        className={`
          flex items-center gap-3 px-3 py-2 sm:py-1.5 rounded-md transition-colors text-xs
          ${
            isActive
              ? 'bg-[var(--acid-green)]/10 text-[var(--acid-green)]'
              : 'text-[var(--text-muted)] hover:bg-[var(--surface-elevated)] hover:text-[var(--text)]'
          }
        `}
        title={leftSidebarCollapsed ? item.label : undefined}
      >
        <span className="font-theme-data text-sm w-5 text-center flex-shrink-0">{item.icon}</span>
        {!leftSidebarCollapsed && (
          <span className="text-sm font-medium truncate">{item.label}</span>
        )}
      </Link>
    );
  };

  const renderSection = (section: NavSection) => {
    // Section-level gates
    if (section.minMode && !isFeatureVisible(section.minMode)) return null;
    if (section.adminOnly && !isAdmin) return null;

    const filtered = filterItems(section.items);
    if (filtered.length === 0) return null;

    const isCollapsed = section.collapsible !== false && collapsedSections.has(section.key);
    const canCollapse = section.collapsible !== false;

    // Check if any child is active (show section even if collapsed)
    const hasActiveChild = filtered.some((item) => isItemActive(item.href));

    return (
      <div key={section.key} className="mb-2">
        {!leftSidebarCollapsed && section.title && (
          <button
            onClick={canCollapse ? () => toggleSection(section.key) : undefined}
            className={`
              w-full px-3 mb-1 flex items-center justify-between
              text-xs font-medium uppercase tracking-wider
              ${section.highlight ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'}
              ${canCollapse ? 'cursor-pointer hover:text-[var(--text)] transition-colors' : 'cursor-default'}
            `}
          >
            <span className="flex items-center gap-1.5">
              {section.title}
              {/* Count badge -- shows how many items are in this section */}
              {canCollapse && (
                <span className="px-1 py-0.5 text-[10px] font-medium bg-[var(--surface-elevated)] text-[var(--text-muted)] rounded leading-none">
                  {filtered.length}
                </span>
              )}
              {section.highlight && (
                <span className="px-1 py-0.5 text-[10px] font-medium bg-[var(--acid-green)]/10 text-[var(--acid-green)] rounded leading-none">
                  PRO
                </span>
              )}
              {hasActiveChild && isCollapsed && (
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--acid-green)]" />
              )}
            </span>
            {canCollapse && (
              <span className="font-theme-data text-[10px] opacity-50">
                {isCollapsed ? '\u25B8' : '\u25BE'}
              </span>
            )}
          </button>
        )}
        {!isCollapsed && (
          <nav className={`space-y-0.5 ${section.highlight ? 'relative' : ''}`}>
            {section.highlight && (
              <div
                className="absolute -left-1 top-0 bottom-0 w-0.5 bg-[var(--acid-green)]/30 rounded-full"
                aria-hidden="true"
              />
            )}
            {filtered.map(renderNavItem)}
          </nav>
        )}
      </div>
    );
  };

  const sidebarContent = (
    <div className="flex flex-col h-full">
      {/* Quick Actions */}
      <div className="p-3 border-b border-[var(--border)]">
        {filterItems(quickActions).map((item) => (
          <Link
            key={item.href}
            href={item.href}
            onClick={() => isMobile && closeLeftSidebar()}
            className="flex items-center gap-2 px-3 py-2 mb-1 rounded-md bg-[var(--acid-green)]/10 text-[var(--acid-green)] hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            <span className="font-theme-data text-lg">{item.icon}</span>
            {!leftSidebarCollapsed && <span className="text-sm font-medium">{item.label}</span>}
          </Link>
        ))}
      </div>

      {/* Scrollable Navigation */}
      <div className="flex-1 overflow-y-auto p-3">{navSections.map(renderSection)}</div>

      {/* Bottom: Login/User + Mode Selector + Collapse Toggle */}
      <div className="border-t border-[var(--border)] p-3">
        {/* Login link when not authenticated */}
        {!isAuthenticated && (
          <Link
            href="/auth/login"
            onClick={() => isMobile && closeLeftSidebar()}
            className="flex items-center gap-2 px-3 py-2 mb-3 rounded-md bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors"
            title={leftSidebarCollapsed ? 'Login' : undefined}
          >
            <span className="font-theme-data text-lg">{'\u2192'}</span>
            {!leftSidebarCollapsed && <span className="text-sm font-medium">Login</span>}
          </Link>
        )}

        {/* Show user info when authenticated */}
        {isAuthenticated && user && !leftSidebarCollapsed && (
          <div className="px-3 py-2 mb-3 text-xs text-[var(--text-muted)]">
            <span className="text-[var(--acid-green)]">{'\u25CF'}</span>{' '}
            {user.email || user.name || 'Logged in'}
          </div>
        )}

        {!leftSidebarCollapsed && (
          <div className="mb-3">
            <ModeSelector compact />
          </div>
        )}

        {/* Collapse toggle (desktop only) */}
        {!isMobile && (
          <button
            onClick={() => setLeftSidebarCollapsed(!leftSidebarCollapsed)}
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-md text-[var(--text-muted)] hover:bg-[var(--surface-elevated)] hover:text-[var(--text)] transition-colors"
            aria-label={leftSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            title={leftSidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            <span className="font-theme-data" aria-hidden="true">
              {leftSidebarCollapsed ? '\u00BB' : '\u00AB'}
            </span>
            {!leftSidebarCollapsed && <span className="text-sm">Collapse</span>}
          </button>
        )}
      </div>
    </div>
  );

  // Mobile: Full-screen overlay drawer
  if (isMobile) {
    return (
      <>
        {/* Backdrop */}
        {leftSidebarOpen && (
          <div className="fixed inset-0 bg-black/50 z-40" onClick={closeLeftSidebar} />
        )}

        {/* Drawer */}
        <aside
          aria-label="Main navigation"
          className={`
            fixed top-0 left-0 h-full w-72 bg-[var(--surface)] border-r border-[var(--border)] z-50
            transform transition-transform duration-200 ease-out
            ${leftSidebarOpen ? 'translate-x-0' : '-translate-x-full'}
          `}
          style={{ paddingTop: '48px' }} // Below TopBar
        >
          {sidebarContent}
        </aside>
      </>
    );
  }

  // Desktop: Persistent sidebar
  return (
    <aside
      aria-label="Main navigation"
      className="fixed top-12 left-0 h-[calc(100vh-48px)] bg-[var(--surface)] border-r border-[var(--border)] z-30 transition-all duration-200"
      style={{ width: leftSidebarWidth }}
    >
      {sidebarContent}
    </aside>
  );
}
