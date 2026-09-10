'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { ExecutiveSummary } from '@/components/dashboard/ExecutiveSummary';
import { SettlementPanel } from '@/components/dashboard/SettlementPanel';
import { useRightSidebar } from '@/context/RightSidebarContext';
import { fetchRecentDebates, type DebateArtifact } from '@/utils/supabase';
import { getAgentColors } from '@/utils/agentColors';
import { logger } from '@/utils/logger';
import { CostSummaryWidget } from '@/components/costs/CostSummaryWidget';
import { TrialStatusWidget } from '@/components/billing/TrialStatusWidget';
import { TemplateMarketplace } from '@/components/templates/TemplateMarketplace';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { useSWRFetch, useActiveDebates } from '@/hooks/useSWRFetch';
import type { ActiveDebate } from '@/hooks/useSWRFetch';
import { useDashboardEvents } from '@/hooks/useDashboardEvents';

// Backend API response shape for debates list
interface BackendDebatesResponse {
  debates?: Array<{
    id: string;
    debate_id?: string;
    task?: string;
    question?: string;
    agents: string[];
    consensus_reached: boolean;
    confidence: number;
    winning_proposal?: string | null;
    vote_tally?: Record<string, number> | null;
    created_at: string;
    loop_id?: string;
    cycle_number?: number;
    phase?: string;
  }>;
  results?: Array<{
    id: string;
    debate_id?: string;
    task?: string;
    question?: string;
    agents: string[];
    consensus_reached: boolean;
    confidence: number;
    winning_proposal?: string | null;
    vote_tally?: Record<string, number> | null;
    created_at: string;
    loop_id?: string;
    cycle_number?: number;
    phase?: string;
  }>;
}

// Normalize backend debate data to DebateArtifact shape
function normalizeDebate(
  d: NonNullable<BackendDebatesResponse['debates']>[number],
): DebateArtifact {
  return {
    id: d.debate_id || d.id,
    loop_id: d.loop_id || '',
    cycle_number: d.cycle_number || 0,
    phase: d.phase || 'completed',
    task: d.task || d.question || 'Untitled debate',
    agents: d.agents || [],
    transcript: [],
    consensus_reached: d.consensus_reached ?? false,
    confidence: d.confidence ?? 0,
    winning_proposal: d.winning_proposal ?? null,
    vote_tally: d.vote_tally ?? null,
    created_at: d.created_at || new Date().toISOString(),
  };
}

// Backend health response shape
interface HealthResponse {
  status?: string;
  components?: Record<string, { status?: string; healthy?: boolean }>;
  uptime_percent?: number;
  uptime?: number;
  services?: Record<string, string>;
}

const DEFAULT_STATUS_ITEMS = [
  { name: 'Debate Engine', key: 'debate_engine', icon: '' },
  { name: 'Agent Pool', key: 'agent_pool', icon: '' },
  { name: 'Knowledge Mound', key: 'knowledge_mound', icon: '' },
  { name: 'Channel Integrations', key: 'channels', icon: '' },
  { name: 'Audit System', key: 'audit', icon: '' },
];

function SystemStatusPanel({ refreshInterval = 30000 }: { refreshInterval?: number }) {
  const { data: health, error: healthError } = useSWRFetch<HealthResponse>('/api/health', {
    refreshInterval,
  });

  const getComponentStatus = (key: string): string => {
    if (healthError || !health) return 'unknown';
    // Check components map if available
    if (health.components?.[key]) {
      const comp = health.components[key];
      if (comp.status) return comp.status;
      if (comp.healthy === true) return 'operational';
      if (comp.healthy === false) return 'degraded';
    }
    // Check services map if available
    if (health.services?.[key]) {
      return health.services[key];
    }
    // If overall health is ok, assume operational
    if (health.status === 'ok' || health.status === 'healthy') return 'operational';
    return 'unknown';
  };

  const overallUp =
    !healthError && health && (health.status === 'ok' || health.status === 'healthy');
  const uptimePercent = health?.uptime_percent ?? (overallUp ? 99.9 : null);

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} SYSTEM STATUS</h3>
        <div className="flex items-center gap-2">
          {overallUp ? (
            <span className="px-2 py-0.5 text-[10px] font-theme-data bg-green-500/20 text-green-400 border border-green-500/30">
              LIVE
            </span>
          ) : healthError ? (
            <span className="px-2 py-0.5 text-[10px] font-theme-data bg-red-500/20 text-red-400 border border-red-500/30">
              OFFLINE
            </span>
          ) : (
            <span className="px-2 py-0.5 text-[10px] font-theme-data bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 animate-pulse">
              CHECKING
            </span>
          )}
          <Link
            href="/admin"
            className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
          >
            ADMIN
          </Link>
        </div>
      </div>

      <div className="p-4 space-y-4">
        {DEFAULT_STATUS_ITEMS.map((item) => {
          const status = getComponentStatus(item.key);
          return (
            <div key={item.name} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-sm">{item.icon}</span>
                <span className="text-xs font-theme-data text-[var(--text)]">{item.name}</span>
              </div>
              <span
                className={`px-2 py-0.5 text-[10px] font-theme-data uppercase ${
                  status === 'operational'
                    ? 'bg-green-500/20 text-green-400 border border-green-500/30'
                    : status === 'degraded'
                      ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                      : status === 'unknown'
                        ? 'bg-gray-500/20 text-gray-400 border border-gray-500/30 animate-pulse'
                        : 'bg-red-500/20 text-red-400 border border-red-500/30'
                }`}
              >
                {status === 'unknown' ? 'checking' : status}
              </span>
            </div>
          );
        })}

        <div className="pt-3 mt-3 border-t border-[var(--border)]">
          <div className="flex items-center justify-between text-xs font-theme-data">
            <span className="text-[var(--text-muted)]">30-day uptime</span>
            <span
              className={uptimePercent !== null ? 'text-green-400' : 'text-[var(--text-muted)]'}
            >
              {uptimePercent !== null ? `${uptimePercent.toFixed(2)}%` : '--'}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function formatElapsed(seconds: number): string {
  const mins = Math.floor(seconds / 60);
  const hrs = Math.floor(mins / 60);
  if (hrs > 0) return `${hrs}h ${mins % 60}m`;
  if (mins > 0) return `${mins}m`;
  return `${Math.floor(seconds)}s`;
}

function LiveDebatesPanel() {
  const { data, isLoading } = useActiveDebates();
  const debates: ActiveDebate[] = data?.debates ?? [];

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)]">
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] flex items-center gap-2">
          {'>'} LIVE DEBATES
          {debates.length > 0 && (
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500" />
            </span>
          )}
        </h3>
        {debates.length > 0 && (
          <span className="px-2 py-0.5 text-[10px] font-theme-data bg-green-500/20 text-green-400 border border-green-500/30">
            {debates.length} ACTIVE
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="p-4 text-center text-[var(--text-muted)] font-theme-data text-sm animate-pulse">
          Checking...
        </div>
      ) : debates.length === 0 ? (
        <div className="p-4 text-center text-[var(--text-muted)] font-theme-data text-sm">
          No debates running.{' '}
          <Link href="/arena" className="text-[var(--acid-green)] hover:underline">
            Start one
          </Link>
        </div>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {debates.map((debate) => (
            <Link
              key={debate.id}
              href={`/debate/${debate.id}`}
              className="block p-4 hover:bg-[var(--bg)] transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-theme-data text-[var(--text)] truncate">
                    {debate.topic || 'Untitled debate'}
                  </p>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                      {debate.agents.length} agents
                    </span>
                    <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                      Round {debate.round}/{debate.total_rounds}
                    </span>
                  </div>
                </div>
                <div className="text-right flex-shrink-0">
                  <div className="flex items-center gap-1">
                    <span className="relative flex h-1.5 w-1.5">
                      <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                      <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-green-500" />
                    </span>
                    <span className="text-[10px] font-theme-data text-green-400 uppercase">
                      {debate.status}
                    </span>
                  </div>
                  <div className="text-[10px] text-[var(--text-muted)] font-theme-data mt-1">
                    {formatElapsed(debate.elapsed_seconds)}
                  </div>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function DashboardContent() {
  const [recentDebates, setRecentDebates] = useState<DebateArtifact[]>([]);
  const [loadingDebates, setLoadingDebates] = useState(true);
  const [_dataSource, setDataSource] = useState<'backend' | 'supabase' | 'none'>('none');

  const { setContext, clearContext } = useRightSidebar();

  // WebSocket-driven live refresh — invalidates SWR cache on debate lifecycle events.
  // When connected, we rely on push-based invalidation and only poll as a safety net.
  const { isConnected: wsConnected } = useDashboardEvents();
  const pollInterval = wsConnected ? 120_000 : 30_000; // 120 s safety-net vs 30 s fallback

  // Fetch debates from backend API
  const {
    data: backendDebates,
    error: backendError,
    isLoading: backendLoading,
  } = useSWRFetch<BackendDebatesResponse>('/api/v1/debates?limit=5&sort=created_at:desc', {
    refreshInterval: pollInterval,
  });

  // When backend data arrives, use it; otherwise fall back to Supabase
  useEffect(() => {
    if (backendLoading) {
      setLoadingDebates(true);
      return;
    }

    const debateList = backendDebates?.debates || backendDebates?.results;
    if (debateList && debateList.length > 0) {
      setRecentDebates(debateList.map(normalizeDebate));
      setDataSource('backend');
      setLoadingDebates(false);
      return;
    }

    // Backend returned empty or errored -- fall back to Supabase
    if (backendError || !debateList) {
      if (backendError) {
        logger.warn('Backend debates fetch failed, falling back to Supabase:', backendError);
      }
      (async () => {
        try {
          const data = await fetchRecentDebates(5);
          setRecentDebates(data);
          setDataSource(data.length > 0 ? 'supabase' : 'none');
        } catch (e) {
          logger.error('Failed to load recent debates from Supabase:', e);
          setRecentDebates([]);
          setDataSource('none');
        } finally {
          setLoadingDebates(false);
        }
      })();
      return;
    }

    // Backend returned empty array (legitimate: no debates yet)
    setRecentDebates([]);
    setDataSource('backend');
    setLoadingDebates(false);
  }, [backendDebates, backendError, backendLoading]);

  // Set up right sidebar
  useEffect(() => {
    setContext({
      title: 'Executive Dashboard',
      subtitle: 'Real-time KPIs',
      statsContent: (
        <div className="space-y-3">
          <div className="text-xs text-[var(--text-muted)] font-theme-data">
            Overview of AI-debated decisions across your organization.
          </div>
          <div className="border-t border-[var(--border)] pt-3">
            <div className="text-xs text-[var(--acid-green)] font-theme-data mb-1">
              WHAT IS ARAGORA?
            </div>
            <div className="text-xs text-[var(--text)] font-theme-data leading-relaxed">
              Multiple AI models debate your decisions and deliver verdicts with confidence scores
              and audit trails.
            </div>
          </div>
        </div>
      ),
      actionsContent: (
        <div className="space-y-2">
          <Link
            href="/arena"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            + NEW DEBATE
          </Link>
          <Link
            href="/control-plane"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            OPERATIONS
          </Link>
          <Link
            href="/admin"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            ADMIN
          </Link>
        </div>
      ),
    });

    return () => clearContext();
  }, [setContext, clearContext]);

  const formatTimeAgo = (timestamp: string) => {
    const diff = Date.now() - new Date(timestamp).getTime();
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(diff / 86400000);

    if (days > 0) return `${days}d ago`;
    if (hours > 0) return `${hours}h ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return 'just now';
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-2">
                  {'>'} EXECUTIVE DASHBOARD
                </h1>
                <p className="text-xs text-[var(--text-muted)] font-theme-data">
                  AI models that debate your decisions — with confidence scores and full audit
                  trails
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`px-2 py-1 text-xs font-theme-data border ${
                    wsConnected
                      ? 'bg-green-500/20 text-green-400 border-green-500/30'
                      : 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
                  }`}
                >
                  {wsConnected ? ' LIVE' : ' POLLING'}
                </span>
              </div>
            </div>
          </div>

          {/* Executive Summary KPIs */}
          <PanelErrorBoundary panelName="Executive Summary">
            <ExecutiveSummary refreshInterval={pollInterval} />
          </PanelErrorBoundary>

          {/* Trial / Subscription Status */}
          <div className="mt-6">
            <PanelErrorBoundary panelName="Trial Status">
              <TrialStatusWidget />
            </PanelErrorBoundary>
          </div>

          {/* Settlement Status */}
          <div className="mt-6">
            <PanelErrorBoundary panelName="Settlement Panel">
              <SettlementPanel refreshInterval={pollInterval} />
            </PanelErrorBoundary>
          </div>

          {/* Live Debates */}
          <div className="mt-6">
            <PanelErrorBoundary panelName="Live Debates">
              <LiveDebatesPanel />
            </PanelErrorBoundary>
          </div>

          {/* Recent Activity Section */}
          <div className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Recent Debates */}
            <PanelErrorBoundary panelName="Recent Debates">
              <div className="bg-[var(--surface)] border border-[var(--border)]">
                <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
                  <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
                    {'>'} RECENT DEBATES
                  </h3>
                  <Link
                    href="/debates"
                    className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
                  >
                    VIEW ALL
                  </Link>
                </div>

                {loadingDebates ? (
                  <div className="p-4 text-center text-[var(--text-muted)] font-theme-data text-sm animate-pulse">
                    Loading...
                  </div>
                ) : recentDebates.length === 0 ? (
                  <div className="p-4 text-center text-[var(--text-muted)] font-theme-data text-sm">
                    No recent debates.{' '}
                    <Link href="/arena" className="text-[var(--acid-green)] hover:underline">
                      Start one
                    </Link>
                  </div>
                ) : (
                  <div className="divide-y divide-[var(--border)]">
                    {recentDebates.map((debate) => (
                      <Link
                        key={debate.id}
                        href={`/debate/${debate.id}`}
                        className="block p-4 hover:bg-[var(--bg)] transition-colors"
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-theme-data text-[var(--text)] truncate">
                              {debate.task}
                            </p>
                            <div className="flex items-center gap-2 mt-1">
                              <div className="flex items-center gap-1">
                                {debate.agents.slice(0, 3).map((agent, i) => {
                                  const colors = getAgentColors(agent);
                                  return (
                                    <span
                                      key={i}
                                      className={`px-1 py-0.5 text-[10px] ${colors.bg} ${colors.text} font-theme-data`}
                                    >
                                      {agent.split('-')[0][0].toUpperCase()}
                                    </span>
                                  );
                                })}
                                {debate.agents.length > 3 && (
                                  <span className="text-[10px] text-[var(--text-muted)] font-theme-data">
                                    +{debate.agents.length - 3}
                                  </span>
                                )}
                              </div>
                            </div>
                          </div>
                          <div className="text-right flex-shrink-0">
                            <div
                              className={`text-xs font-theme-data ${
                                debate.consensus_reached ? 'text-green-400' : 'text-yellow-400'
                              }`}
                            >
                              {debate.consensus_reached ? '' : ''}{' '}
                              {Math.round(debate.confidence * 100)}%
                            </div>
                            <div className="text-[10px] text-[var(--text-muted)] font-theme-data mt-1">
                              {formatTimeAgo(debate.created_at)}
                            </div>
                          </div>
                        </div>
                      </Link>
                    ))}
                  </div>
                )}
              </div>
            </PanelErrorBoundary>

            {/* System Status */}
            <PanelErrorBoundary panelName="System Status">
              <SystemStatusPanel refreshInterval={pollInterval} />
            </PanelErrorBoundary>
          </div>

          {/* Cost Overview */}
          <div className="mt-8 grid grid-cols-1 lg:grid-cols-2 gap-6">
            <PanelErrorBoundary panelName="Cost Summary">
              <CostSummaryWidget />
            </PanelErrorBoundary>
          </div>

          {/* Debate Templates */}
          <PanelErrorBoundary panelName="Template Marketplace">
            <TemplateMarketplace />
          </PanelErrorBoundary>

          {/* Feature Grid */}
          <div className="mt-8">
            <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
              {'>'} QUICK ACCESS
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
              {[
                { href: '/arena', label: 'New Debate', icon: '+', desc: 'Start a decision' },
                { href: '/debates', label: 'Debates', icon: '', desc: 'Past decisions' },
                { href: '/oracle', label: 'Oracle', icon: '', desc: 'Live streaming' },
                { href: '/receipts', label: 'Receipts', icon: '', desc: 'Audit trails' },
                { href: '/leaderboard', label: 'Rankings', icon: '', desc: 'Agent performance' },
                { href: '/settings', label: 'Settings', icon: '', desc: 'Configure' },
              ].map((item) => (
                <Link
                  key={item.href}
                  href={item.href}
                  className="bg-[var(--surface)] border border-[var(--border)] p-3 hover:border-[var(--acid-green)]/50 transition-colors group"
                >
                  <div className="text-xl mb-1">{item.icon}</div>
                  <div className="text-xs font-theme-data text-[var(--text)] group-hover:text-[var(--acid-green)] transition-colors">
                    {item.label}
                  </div>
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    {item.desc}
                  </div>
                </Link>
              ))}
            </div>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-6 border-t border-[var(--border)] mt-8">
          <p className="text-[var(--text-muted)]">42 AI agents debating your decisions</p>
        </footer>
      </main>
    </>
  );
}

export default function DashboardPage() {
  return (
    <ProtectedRoute redirectTo="/dashboard">
      <DashboardContent />
    </ProtectedRoute>
  );
}
