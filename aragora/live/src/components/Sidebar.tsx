'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import Link from 'next/link';
import { useSidebar } from '@/context/SidebarContext';
import { useAuth } from '@/context/AuthContext';
import { useProgressiveMode, ProgressiveMode } from '@/context/ProgressiveModeContext';
import { ModeSelector } from '@/components/ui/FeatureCard';
import { useEdgeSwipe, useSwipeGesture } from '@/hooks/useSwipeGesture';
import { useOnboardingStore, selectIsOnboardingNeeded } from '@/store/onboardingStore';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface NavItem {
  label: string;
  href: string;
  icon?: string;
  requiresAuth?: boolean;
  adminOnly?: boolean;
  minMode?: ProgressiveMode;
}

// ---------------------------------------------------------------------------
// Account items
// ---------------------------------------------------------------------------

const accountItems: NavItem[] = [
  { label: 'Login', href: '/auth/login', icon: '>' },
  { label: 'Register', href: '/auth/register', icon: '+' },
];

const authenticatedAccountItems: NavItem[] = [
  { label: 'Settings', href: '/settings', icon: '*', requiresAuth: true },
  { label: 'Billing', href: '/billing', icon: '$', requiresAuth: true },
  { label: 'Organization', href: '/organization', icon: '@', requiresAuth: true },
];

/* === START SECTION === Progressive disclosure group */
const startItems: NavItem[] = [
  { label: 'Hub', href: '/hub', icon: '+' },
  { label: 'New Debate', href: '/arena', icon: '!' },
  { label: 'Demo', href: '/demo', icon: '\u2605' },
  { label: 'Try Now', href: '/demo/instant', icon: '\u26A1' },
  { label: 'Playbooks', href: '/playbooks', icon: 'P', minMode: 'standard' },
  { label: 'Stress-Test', href: '/gauntlet', icon: '%', minMode: 'standard' },
  { label: 'Code Review', href: '/code-review', icon: '<', minMode: 'standard' },
  { label: 'Document Audit', href: '/audit', icon: '|', minMode: 'standard' },
];

/* === PIPELINE SECTION === Progressive disclosure group */
const pipelineItems: NavItem[] = [
  { label: 'Mission Control', href: '/mission-control', icon: '\u25A3', minMode: 'standard' },
  { label: 'Pipeline', href: '/pipeline', icon: '|' },
  { label: 'Interrogate', href: '/interrogate', icon: '?' },
  { label: 'Spec Generator', href: '/prompt-engine', icon: '\u2261' },
  { label: 'Ideas', href: '/ideas', icon: '~', minMode: 'standard' },
  { label: 'Goals', href: '/goals', icon: 'G', minMode: 'standard' },
  { label: 'Actions', href: '/actions', icon: 'A', minMode: 'standard' },
  { label: 'Orchestration', href: '/orchestration', icon: '!', minMode: 'advanced' },
];

/* === DECISIONS SECTION === Progressive disclosure group */
const decisionsItems: NavItem[] = [
  { label: 'Active Debates', href: '/deliberations', icon: '\u2696', minMode: 'standard' },
  { label: 'Batch Debates', href: '/batch', icon: '\u229E', minMode: 'standard' },
  { label: 'Forks', href: '/forks', icon: '\u2442', minMode: 'advanced' },
  { label: 'Impasse', href: '/impasse', icon: '\u26A0', minMode: 'advanced' },
  { label: 'Compare', href: '/compare', icon: '\u2194', minMode: 'advanced' },
  { label: 'Crux', href: '/crux', icon: '\u2020', minMode: 'advanced' },
  { label: 'Spectate', href: '/spectate', icon: '\u25C9', minMode: 'advanced' },
  { label: 'Replays', href: '/replays', icon: '\u21BB', minMode: 'advanced' },
];

/* === BROWSE SECTION === Progressive disclosure group */
const browseItems: NavItem[] = [
  { label: 'Dashboard', href: '/dashboard', icon: '\u25A6' },
  { label: 'Debates', href: '/debates', icon: '#' },
  { label: 'Knowledge', href: '/knowledge', icon: '?' },
  { label: 'Leaderboard', href: '/leaderboard', icon: '^', minMode: 'standard' },
  { label: 'Agents', href: '/agents', icon: '&', minMode: 'standard' },
  { label: 'Performance', href: '/agents/performance', icon: '\u2197', minMode: 'advanced' },
  { label: 'Marketplace', href: '/marketplace', icon: '$', minMode: 'standard' },
  { label: 'Usage & Costs', href: '/usage', icon: '%', minMode: 'standard' },
  { label: 'Gallery', href: '/gallery', icon: '*' },
  { label: 'Features', href: '/features', icon: '\u2756' },
  { label: 'About', href: '/about', icon: 'i' },
  { label: 'Portal', href: '/portal', icon: '\u2302', minMode: 'standard' },
  { label: 'Social', href: '/social', icon: '\u263A', minMode: 'standard' },
  { label: 'Moments', href: '/moments', icon: '\u25C6', minMode: 'standard' },
  { label: 'Reviews', href: '/reviews', icon: '\u2606', minMode: 'standard' },
];

/* === TOOLS SECTION === Progressive disclosure group */
const toolsItems: NavItem[] = [
  { label: 'Inbox', href: '/inbox', icon: '@', requiresAuth: true },
  { label: 'Shared Inbox', href: '/shared-inbox', icon: '\u2709', requiresAuth: true },
  { label: 'Tools', href: '/tools', icon: '\u2692', minMode: 'standard' },
  { label: 'Documents', href: '/documents', icon: ']', minMode: 'standard' },
  { label: 'Workflows', href: '/workflows', icon: '>', minMode: 'advanced' },
  { label: 'Connectors', href: '/connectors', icon: '<', minMode: 'advanced' },
  { label: 'Analytics', href: '/analytics', icon: '~', minMode: 'advanced' },
  { label: 'Templates', href: '/templates', icon: '[', minMode: 'standard' },
  { label: 'Autonomous', href: '/autonomous', icon: '!', minMode: 'expert' },
  { label: 'MCP Tools', href: '/mcp', icon: '~', minMode: 'advanced' },
  { label: 'Webhooks', href: '/webhooks', icon: '\u21C4', minMode: 'advanced' },
  { label: 'Plugins', href: '/plugins', icon: '\u2699', minMode: 'advanced' },
  { label: 'API Explorer', href: '/api-explorer', icon: '{', minMode: 'advanced' },
  { label: 'API Docs', href: '/api-docs', icon: '\u2261', minMode: 'advanced' },
  { label: 'Broadcast', href: '/broadcast', icon: '\u25CE', minMode: 'advanced' },
  { label: 'Command Center', href: '/command-center', icon: '\u2318', minMode: 'advanced' },
  { label: 'Command', href: '/command', icon: '\u276F', minMode: 'advanced' },
  { label: 'Integrations', href: '/integrations', icon: ':', minMode: 'advanced' },
  { label: 'Chat Integrations', href: '/integrations/chat', icon: '\u2709', minMode: 'advanced' },
];

/* === ANALYTICS & INSIGHTS SECTION === Progressive disclosure group */
const analyticsItems: NavItem[] = [
  { label: 'Insights', href: '/insights', icon: '\u272A', minMode: 'standard' },
  { label: 'Outcomes', href: '/analytics/outcomes', icon: '\u2713', minMode: 'standard' },
  { label: 'Intelligence', href: '/intelligence', icon: '\u269B', minMode: 'standard' },
  { label: 'System Intelligence', href: '/system-intelligence', icon: '\u2328', minMode: 'standard' },
  { label: 'Outcome Dashboard', href: '/outcome-dashboard', icon: '\u2611', minMode: 'standard' },
  { label: 'ELO Analytics', href: '/elo-analytics', icon: '\u2295', minMode: 'standard' },
  { label: 'Agent Evolution', href: '/agent-evolution', icon: '\u267E', minMode: 'advanced' },
  { label: 'Calibration', href: '/calibration', icon: '\u2316', minMode: 'advanced' },
  { label: 'Evaluation', href: '/evaluation', icon: '\u2606', minMode: 'advanced' },
  { label: 'Uncertainty', href: '/uncertainty', icon: '\u00B1', minMode: 'advanced' },
  { label: 'Quality', href: '/quality', icon: '\u2605', minMode: 'advanced' },
  { label: 'Costs', href: '/costs', icon: '\u00A2', minMode: 'standard' },
  { label: 'Budgets', href: '/budgets', icon: '\u00A3', minMode: 'standard' },
  { label: 'Tournaments', href: '/tournaments', icon: '\u2295', minMode: 'standard' },
  { label: 'Argument Analysis', href: '/argument-analysis', icon: '\u2726', minMode: 'standard' },
  { label: 'Consensus', href: '/consensus', icon: '\u2299', minMode: 'standard' },
  { label: 'Differentiation', href: '/differentiation', icon: '\u25C7', minMode: 'standard' },
  { label: 'Spend', href: '/analytics/spend', icon: '\u00A4', minMode: 'standard' },
  { label: 'Decisions', href: '/analytics/decisions', icon: '\u2713', minMode: 'standard' },
];

/* === ENTERPRISE SECTION === Progressive disclosure group */
const enterpriseItems: NavItem[] = [
  { label: 'Decision Integrity', href: '/decision-integrity', icon: '\u2726', minMode: 'standard' },
  { label: 'Compliance', href: '/compliance', icon: '\u2713', minMode: 'standard' },
  { label: 'Dashboard', href: '/control-plane', icon: '\u25CE', minMode: 'standard' },
  { label: 'Receipts', href: '/receipts', icon: '$', minMode: 'standard' },
  { label: 'Policy', href: '/policy', icon: '\u2696', minMode: 'standard' },
  { label: 'Privacy', href: '/privacy', icon: '\u229E', minMode: 'standard' },
  { label: 'Audit Trail', href: '/audit-trail', icon: '\u2610', minMode: 'standard' },
  { label: 'Audit View', href: '/audit/view', icon: '\u2630', minMode: 'advanced' },
  { label: 'Audit Templates', href: '/audit/templates', icon: '\u2610', minMode: 'advanced' },
  { label: 'New Audit', href: '/audit/new', icon: '\u271A', minMode: 'advanced' },
  { label: 'Backup', href: '/backup', icon: '\u2B73', minMode: 'advanced' },
  { label: 'Moderation', href: '/moderation', icon: '\u2691', minMode: 'standard' },
  { label: 'Security', href: '/security', icon: '\u26BF', minMode: 'advanced' },
  { label: 'Blockchain', href: '/blockchain', icon: '\u26D3', minMode: 'advanced' },
  { label: 'Observability', href: '/observability', icon: '\u25C9', minMode: 'advanced' },
  { label: 'Pulse', href: '/pulse', icon: '\u2764', minMode: 'advanced' },
];

/* === MEMORY & KNOWLEDGE SECTION === Progressive disclosure group */
const memoryItems: NavItem[] = [
  { label: 'Memory', href: '/memory', icon: '=', minMode: 'advanced' },
  { label: 'Memory Gateway', href: '/memory-gateway', icon: '\u2194', minMode: 'advanced' },
  { label: 'Memory Analytics', href: '/memory-analytics', icon: '\u2261', minMode: 'advanced' },
  { label: 'Supermemory', href: '/supermemory', icon: '\u221E', minMode: 'advanced' },
  { label: 'Knowledge Flow', href: '/knowledge-flow', icon: '\u21C4', minMode: 'advanced' },
  { label: 'Knowledge Learning', href: '/knowledge/learning', icon: '\u2042', minMode: 'advanced' },
  { label: 'Cross-Debate', href: '/cross-debate', icon: '\u2728', minMode: 'advanced' },
  { label: 'Evidence', href: '/evidence', icon: '\u2690', minMode: 'advanced' },
  { label: 'Beliefs', href: '/beliefs', icon: '\u0394', minMode: 'advanced' },
  { label: 'Explainability', href: '/explainability', icon: '?!', minMode: 'advanced' },
  { label: 'Repository', href: '/repository', icon: '\u25A3', minMode: 'advanced' },
  { label: 'RLM', href: '/rlm', icon: '\u21BA', minMode: 'advanced' },
  { label: 'Reasoning', href: '/reasoning', icon: '\u2234', minMode: 'advanced' },
];

/* === DEVELOPMENT SECTION === Progressive disclosure group */
const developmentItems: NavItem[] = [
  { label: 'Codebase Audit', href: '/codebase-audit', icon: '\u2611', minMode: 'standard' },
  { label: 'Security Scan', href: '/security-scan', icon: '\u26BF', minMode: 'standard' },
  { label: 'Developer', href: '/developer', icon: '>_', minMode: 'advanced' },
  { label: 'Sandbox', href: '/sandbox', icon: '\u25A1', minMode: 'advanced' },
  { label: 'Feature Flags', href: '/feature-flags', icon: '\u2691', minMode: 'advanced' },
];

/* === AI & ML SECTION === Progressive disclosure group */
const aiMlItems: NavItem[] = [
  { label: 'Training', href: '/training', icon: '\u2699', minMode: 'advanced' },
  { label: 'ML', href: '/ml', icon: '\u2206', minMode: 'advanced' },
  { label: 'Selection', href: '/selection', icon: '\u21D2', minMode: 'advanced' },
  { label: 'Evolution', href: '/evolution', icon: '\u267E', minMode: 'advanced' },
  { label: 'AB Testing', href: '/ab-testing', icon: 'A|B', minMode: 'advanced' },
];

/* === VOICE & MEDIA SECTION === Progressive disclosure group */
const voiceMediaItems: NavItem[] = [
  { label: 'Voice', href: '/voice', icon: '\u266A', minMode: 'advanced' },
  { label: 'Speech', href: '/speech', icon: '\u25B6', minMode: 'advanced' },
  { label: 'Transcribe', href: '/transcribe', icon: '\u270E', minMode: 'advanced' },
];

/* === BUSINESS SECTION === Progressive disclosure group */
const businessItems: NavItem[] = [
  { label: 'Accounting', href: '/accounting', icon: '\u2211', requiresAuth: true },
  { label: 'Plaid Connect', href: '/accounting/plaid', icon: '\u2194', requiresAuth: true },
  { label: 'Pricing', href: '/pricing', icon: '\u00A4', minMode: 'standard' },
  { label: 'Verticals', href: '/verticals', icon: '/', minMode: 'advanced' },
  { label: 'Organization', href: '/organization', icon: '\u2302', requiresAuth: true },
  { label: 'Members', href: '/organization/members', icon: '\uD83D\uDC65', requiresAuth: true },
];

/* === ORCHESTRATION SECTION === Progressive disclosure group */
const orchestrationItems: NavItem[] = [
  { label: 'Scheduler', href: '/scheduler', icon: '\u25F7', minMode: 'advanced' },
  { label: 'Pulse Scheduler', href: '/pulse-scheduler', icon: '\u23F1', minMode: 'advanced' },
  { label: 'Queue', href: '/queue', icon: '\u2630', minMode: 'advanced' },
  { label: 'Automation', href: '/nomic-control', icon: '\u221E', minMode: 'advanced' },
  { label: 'Auto-Improve', href: '/self-improve', icon: '\u21BB', minMode: 'advanced' },
  { label: 'Verification', href: '/verification', icon: '\u2713', minMode: 'advanced' },
  { label: 'Coordination', href: '/coordination', icon: '\u2693', minMode: 'advanced' },
  { label: 'Feedback Hub', href: '/feedback-hub', icon: '\u21C4', minMode: 'advanced' },
];

/* === MONITORING SECTION === Progressive disclosure group */
const monitoringItems: NavItem[] = [
  { label: 'System Status', href: '/system-status', icon: '\u2665', minMode: 'advanced' },
  { label: 'Data Classification', href: '/data-classification', icon: '\u2263', minMode: 'advanced' },
];

/* === ADVANCED SECTION === Progressive disclosure group */
const advancedItems: NavItem[] = [
  { label: 'Genesis', href: '/genesis', icon: '@', minMode: 'expert' },
  { label: 'Introspection', href: '/introspection', icon: '?', minMode: 'expert' },
  { label: 'Agent Network', href: '/network', icon: '~', minMode: 'expert' },
  { label: 'Capability Probe', href: '/probe', icon: '^', minMode: 'expert' },
  { label: 'Red Team', href: '/red-team', icon: '!', minMode: 'expert' },
  { label: 'Op Modes', href: '/modes', icon: '#', minMode: 'expert' },
  { label: 'Laboratory', href: '/laboratory', icon: '\u2697', minMode: 'expert' },
  { label: 'Reasoning', href: '/reasoning', icon: '\u2234', minMode: 'expert' },
  { label: 'Breakpoints', href: '/breakpoints', icon: '\u25CF', minMode: 'expert' },
  { label: 'Checkpoints', href: '/checkpoints', icon: '\u2713', minMode: 'expert' },
  { label: 'Integrations', href: '/integrations', icon: ':', minMode: 'advanced' },
];

/* === ADMIN SECTION === Progressive disclosure group
 * Admin-only pages including dedup, retention, knowledge velocity.
 */
const adminNavItems: NavItem[] = [
  { label: 'Admin Dashboard', href: '/admin', icon: '!', adminOnly: true },
  { label: 'User Management', href: '/admin/users', icon: '@', adminOnly: true },
  { label: 'Organizations', href: '/admin/organizations', icon: '#', adminOnly: true },
  { label: 'Tenants', href: '/admin/tenants', icon: '\u2302', adminOnly: true },
  { label: 'Revenue', href: '/admin/revenue', icon: '$', adminOnly: true },
  { label: 'ROI Dashboard', href: '/admin/roi-dashboard', icon: '\u2197', adminOnly: true },
  { label: 'Admin Billing', href: '/admin/billing', icon: '\u00A4', adminOnly: true },
  { label: 'Admin Usage', href: '/admin/usage', icon: '%', adminOnly: true },
  { label: 'Admin Audit', href: '/admin/audit', icon: '\u2611', adminOnly: true },
  { label: 'Admin Security', href: '/admin/security', icon: '\u26BF', adminOnly: true },
  { label: 'Admin Evidence', href: '/admin/evidence', icon: '\u2690', adminOnly: true },
  { label: 'Forensic', href: '/admin/forensic', icon: '\u2623', adminOnly: true },
  { label: 'Admin Knowledge', href: '/admin/knowledge', icon: '?', adminOnly: true },
  { label: 'Knowledge Velocity', href: '/admin/knowledge/velocity', icon: '\u21C8', adminOnly: true },
  { label: 'Admin Memory', href: '/admin/memory', icon: '=', adminOnly: true },
  { label: 'Nomic', href: '/admin/nomic', icon: '\u221E', adminOnly: true },
  { label: 'Personas', href: '/admin/personas', icon: '&', adminOnly: true },
  { label: 'Admin Queue', href: '/admin/queue', icon: '\u2630', adminOnly: true },
  { label: 'Dedup', href: '/admin/dedup', icon: '\u2A01', adminOnly: true },
  { label: 'Retention', href: '/admin/retention', icon: '\u23F3', adminOnly: true },
  { label: 'Streaming', href: '/admin/streaming', icon: '\u25B6', adminOnly: true },
  { label: 'Admin Training', href: '/admin/training', icon: '\u2699', adminOnly: true },
  { label: 'Admin Verticals', href: '/admin/verticals', icon: '/', adminOnly: true },
  { label: 'Workspace', href: '/admin/workspace', icon: '\u25A3', adminOnly: true },
  { label: 'AB Tests', href: '/admin/ab-tests', icon: 'A|B', adminOnly: true },
  { label: 'Federation', href: '/admin/federation', icon: '\u2318', adminOnly: true },
  { label: 'Intelligence', href: '/admin/intelligence', icon: '\u269B', adminOnly: true },
  { label: 'Observability', href: '/admin/observability', icon: '\u25C9', adminOnly: true },
  { label: 'System Health', href: '/admin/system-health', icon: '\u2764', adminOnly: true },
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function Sidebar() {
  const { isOpen, close, open } = useSidebar();
  const { isAuthenticated, user, logout } = useAuth();
  const { isFeatureVisible, modeLabel } = useProgressiveMode();
  const onboardingState = useOnboardingStore();
  const showOnboarding = selectIsOnboardingNeeded(onboardingState);
  const sidebarRef = useRef<HTMLDivElement>(null);
  const firstFocusableRef = useRef<HTMLButtonElement>(null);

  const isAdmin = user?.role === 'admin';

  // Collapsible section state -- persisted in localStorage
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());

  useEffect(() => {
    try {
      const saved = localStorage.getItem('aragora-mobile-sidebar-collapsed');
      if (saved) setCollapsedSections(new Set(JSON.parse(saved)));
    } catch { /* ignore */ }
  }, []);

  const toggleSection = useCallback((key: string) => {
    setCollapsedSections(prev => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      try { localStorage.setItem('aragora-mobile-sidebar-collapsed', JSON.stringify([...next])); } catch { /* ignore */ }
      return next;
    });
  }, []);

  // Edge swipe to open sidebar (from left edge of screen)
  useEdgeSwipe({
    edge: 'left',
    onSwipe: open,
    edgeWidth: 20,
    threshold: 50,
    enabled: !isOpen, // Only enable when sidebar is closed
  });

  // Swipe gesture on sidebar to close (swipe left)
  const swipeRef = useSwipeGesture<HTMLDivElement>({
    onSwipeLeft: close,
    threshold: 50,
    enabled: isOpen,
  });

  // Combine refs
  const combinedRef = (el: HTMLDivElement | null) => {
    (sidebarRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
    (swipeRef as React.MutableRefObject<HTMLDivElement | null>).current = el;
  };

  // Focus trap
  useEffect(() => {
    if (isOpen && firstFocusableRef.current) {
      firstFocusableRef.current.focus();
    }
  }, [isOpen]);

  // Close on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (sidebarRef.current && !sidebarRef.current.contains(e.target as Node)) {
        close();
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen, close]);

  const handleLogout = async () => {
    await logout();
    close();
  };

  const renderNavSection = (title: string, items: NavItem[], sectionMinMode?: ProgressiveMode, sectionKey?: string) => {
    // Don't show section at all if user's mode is below section minimum
    if (sectionMinMode && !isFeatureVisible(sectionMinMode)) {
      return null;
    }

    const filteredItems = items.filter(item => {
      if (item.requiresAuth && !isAuthenticated) return false;
      if (item.adminOnly && !isAdmin) return false;
      if (item.minMode && !isFeatureVisible(item.minMode)) return false;
      return true;
    });

    if (filteredItems.length === 0) return null;

    // Collapsible support: use sectionKey if provided
    const canCollapse = !!sectionKey;
    const isCollapsed = canCollapse && collapsedSections.has(sectionKey!);

    return (
      <div className="mb-6">
        {/* Section header with collapse toggle and count badge */}
        <button
          onClick={canCollapse ? () => toggleSection(sectionKey!) : undefined}
          className={`
            w-full flex items-center justify-between px-2 mb-2
            text-acid-cyan text-xs uppercase tracking-wider
            ${canCollapse ? 'cursor-pointer hover:text-acid-green transition-colors' : 'cursor-default'}
          `}
        >
          <span className="flex items-center gap-1.5">
            {title}
            {/* Count badge -- shows number of visible items in this group */}
            {canCollapse && (
              <span className="px-1 py-0.5 text-[9px] font-medium bg-acid-green/10 text-acid-green/70 rounded leading-none">
                {filteredItems.length}
              </span>
            )}
          </span>
          {canCollapse && (
            <span className="font-mono text-[10px] text-acid-green/50">
              {isCollapsed ? '\u25B8' : '\u25BE'}
            </span>
          )}
        </button>

        {/* Collapsible nav items */}
        {!isCollapsed && (
          <nav>
            {filteredItems.map(item => (
              <Link
                key={item.href}
                href={item.href}
                onClick={close}
                className="flex items-center gap-2 px-2 py-2 text-acid-green hover:bg-acid-green/10 hover:text-acid-cyan transition-colors font-mono text-sm"
              >
                {item.icon && (
                  <span className="w-4 text-center text-acid-green/70">{item.icon}</span>
                )}
                {item.label}
              </Link>
            ))}
          </nav>
        )}
      </div>
    );
  };

  return (
    <>
      {/* Backdrop overlay - solid in light mode, translucent with blur in dark mode */}
      <div
        className={`fixed inset-0 z-40 transition-opacity duration-300 bg-black/70 backdrop-blur-sm ${
          isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'
        }`}
        data-theme-backdrop
        aria-hidden="true"
      />

      {/* Sidebar panel - fully opaque background */}
      <div
        ref={combinedRef}
        role="dialog"
        aria-modal="true"
        aria-label="Navigation menu"
        className={`fixed top-0 left-0 h-full w-72 sm:w-72 bg-bg border-r border-acid-green/30 z-50 transform transition-transform duration-300 ease-in-out ${
          isOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-acid-green/30">
          <span className="text-acid-green font-mono font-bold text-lg">[MENU]</span>
          <button
            ref={firstFocusableRef}
            onClick={close}
            className="text-acid-green hover:text-acid-cyan transition-colors p-1 focus:outline-none focus:ring-2 focus:ring-acid-green/50 rounded"
            aria-label="Close menu"
          >
            <span className="text-xl">&times;</span>
          </button>
        </div>

        {/* Navigation content */}
        <div className="overflow-y-auto h-[calc(100%-8rem)] p-4">
          {/* Account section */}
          {!isAuthenticated ? (
            renderNavSection('Account', accountItems)
          ) : (
            <>
              {/* User info */}
              <div className="mb-6 p-3 bg-acid-green/5 border border-acid-green/20 rounded">
                <div className="text-acid-green font-mono text-sm truncate">
                  {user?.email || 'User'}
                </div>
                <div className="text-acid-green/60 text-xs mt-1">
                  {user?.role || 'member'}
                </div>
              </div>
              {renderNavSection('Account', authenticatedAccountItems)}
            </>
          )}

          {/* Mode selector */}
          <div className="mb-6 p-2">
            <h3 className="text-acid-cyan text-xs uppercase tracking-wider mb-2 px-2">
              Mode: {modeLabel}
            </h3>
            <ModeSelector compact />
          </div>

          {/* === START === Use cases (not collapsible) */}
          {renderNavSection('Start', showOnboarding
            ? [{ label: 'Get Started', href: '/onboarding', icon: '>', minMode: 'simple' as ProgressiveMode }, ...startItems]
            : startItems
          )}

          {/* === PIPELINE === Idea-to-Execution stages (not collapsible) */}
          {renderNavSection('Pipeline', pipelineItems)}

          {/* === DECISIONS === Progressive disclosure group */}
          {renderNavSection('Decisions', decisionsItems, 'standard', 'decisions')}

          {/* === BROWSE === Progressive disclosure group */}
          {renderNavSection('Browse', browseItems, undefined, 'browse')}

          {/* === ANALYTICS & INSIGHTS === Progressive disclosure group */}
          {renderNavSection('Analytics & Insights', analyticsItems, 'standard', 'analytics')}

          {/* === ENTERPRISE === Progressive disclosure group */}
          {renderNavSection('Enterprise', enterpriseItems, 'standard', 'enterprise')}

          {/* === TOOLS === Progressive disclosure group */}
          {renderNavSection('Tools', toolsItems, 'standard', 'tools')}

          {/* === MEMORY & KNOWLEDGE === Progressive disclosure group */}
          {renderNavSection('Memory & Knowledge', memoryItems, 'advanced', 'memory')}

          {/* === DEVELOPMENT === Progressive disclosure group */}
          {renderNavSection('Development', developmentItems, 'standard', 'development')}

          {/* === AI & ML === Progressive disclosure group */}
          {renderNavSection('AI & ML', aiMlItems, 'advanced', 'ai-ml')}

          {/* === VOICE & MEDIA === Progressive disclosure group */}
          {renderNavSection('Voice & Media', voiceMediaItems, 'advanced', 'voice-media')}

          {/* === ORCHESTRATION === Progressive disclosure group */}
          {renderNavSection('Orchestration', orchestrationItems, 'advanced', 'orchestration')}

          {/* === MONITORING === Progressive disclosure group */}
          {renderNavSection('Monitoring', monitoringItems, 'advanced', 'monitoring')}

          {/* === BUSINESS === Progressive disclosure group */}
          {renderNavSection('Business', businessItems, 'standard', 'business')}

          {/* === ADVANCED === Progressive disclosure group */}
          {renderNavSection('Advanced', advancedItems, 'advanced', 'advanced')}

          {/* === ADMIN === Progressive disclosure group (admin-only) */}
          {isAdmin && renderNavSection('Admin', adminNavItems, 'expert', 'admin')}
        </div>

        {/* Footer */}
        <div className="absolute bottom-0 left-0 right-0 p-4 border-t border-acid-green/30 bg-bg">
          <div className="mb-3 text-center">
            <Link
              href="/about"
              onClick={close}
              className="text-acid-green/70 hover:text-acid-cyan transition-colors font-mono text-xs"
            >
              About
            </Link>
          </div>
          {isAuthenticated ? (
            <button
              onClick={handleLogout}
              className="w-full px-4 py-2 text-crimson hover:bg-crimson/10 transition-colors font-mono text-sm border border-crimson/30 rounded"
            >
              Logout
            </button>
          ) : (
            <div className="text-center text-acid-green/50 text-xs font-mono">
              ARAGORA // LIVE
            </div>
          )}
        </div>
      </div>
    </>
  );
}
