'use client';

/**
 * Agent Evolution Dashboard (GitHub issue #307)
 *
 * Shows persona changes over time, ELO score trends, pending Nomic Loop
 * changes with approve/reject controls, and prompt diff views.
 *
 * Backend endpoints:
 *   GET  /api/v1/agent-evolution/timeline   - Evolution events timeline
 *   GET  /api/v1/agent-evolution/elo-trends - ELO score history per agent
 *   GET  /api/v1/agent-evolution/pending    - Pending Nomic Loop changes
 *   POST /api/v1/agent-evolution/pending/{id}/approve
 *   POST /api/v1/agent-evolution/pending/{id}/reject
 */

import { useState } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useAuth } from '@/context/AuthContext';
import {
  useAgentEvolutionDashboard,
  type EvolutionEvent,
  type AgentEloTrend,
  type PendingChange,
} from '@/hooks/useAgentEvolution';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EVENT_TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  persona_change: { bg: 'bg-purple-500/20', text: 'text-purple-400', label: 'PERSONA' },
  prompt_modification: { bg: 'bg-cyan-500/20', text: 'text-cyan-400', label: 'PROMPT' },
  elo_adjustment: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', label: 'ELO' },
  nomic_proposal: { bg: 'bg-blue-500/20', text: 'text-blue-400', label: 'NOMIC' },
  rollback: { bg: 'bg-red-500/20', text: 'text-red-400', label: 'ROLLBACK' },
};

const CHANGE_TYPE_STYLES: Record<string, { bg: string; text: string; label: string }> = {
  persona_update: { bg: 'bg-purple-500/20', text: 'text-purple-400', label: 'PERSONA' },
  prompt_rewrite: { bg: 'bg-cyan-500/20', text: 'text-cyan-400', label: 'PROMPT' },
  parameter_tune: { bg: 'bg-yellow-500/20', text: 'text-yellow-400', label: 'PARAMS' },
  model_swap: { bg: 'bg-orange-500/20', text: 'text-orange-400', label: 'MODEL' },
};

const ELO_COLORS = [
  'text-[var(--acid-green)]',
  'text-cyan-400',
  'text-yellow-400',
  'text-purple-400',
  'text-orange-400',
  'text-pink-400',
];

type TabType = 'timeline' | 'elo' | 'pending';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatRelativeTime(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function formatEloChange(before: number | null, after: number | null): string {
  if (before === null || after === null) return '--';
  const diff = after - before;
  if (diff > 0) return `+${diff}`;
  if (diff < 0) return `${diff}`;
  return '0';
}

function eloChangeColor(before: number | null, after: number | null): string {
  if (before === null || after === null) return 'text-[var(--text-muted)]';
  const diff = after - before;
  if (diff > 0) return 'text-green-400';
  if (diff < 0) return 'text-red-400';
  return 'text-[var(--text-muted)]';
}

// ---------------------------------------------------------------------------
// Panel: Timeline
// ---------------------------------------------------------------------------

function TimelinePanel({ events, loading }: { events: EvolutionEvent[]; loading: boolean }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="p-6 text-xs font-theme-data text-[var(--text-muted)] animate-pulse">
        Loading timeline...
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="p-6 text-center text-xs font-theme-data text-[var(--text-muted)]">
        No evolution events recorded yet.
      </div>
    );
  }

  return (
    <div className="divide-y divide-[var(--border)]">
      {events.map((event) => {
        const style = EVENT_TYPE_STYLES[event.event_type] || EVENT_TYPE_STYLES.prompt_modification;
        const isExpanded = expandedId === event.id;
        const hasDiff = event.old_value && event.new_value;

        return (
          <div key={event.id} className="p-4">
            {/* Header row */}
            <div className="flex items-start gap-3">
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] w-14 shrink-0 pt-0.5">
                {formatRelativeTime(event.timestamp)}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span
                    className={`px-1.5 py-0 text-[10px] font-theme-data rounded ${style.bg} ${style.text}`}
                  >
                    {style.label}
                  </span>
                  <span className="text-xs font-theme-data text-[var(--acid-green)]">
                    {event.agent_name}
                  </span>
                  {event.nomic_cycle_id && (
                    <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                      [{event.nomic_cycle_id}]
                    </span>
                  )}
                </div>
                <div className="text-xs font-theme-data text-[var(--text)] mb-1">
                  {event.description}
                </div>

                {/* ELO change indicator */}
                {(event.elo_before !== null || event.elo_after !== null) && (
                  <div className="flex items-center gap-2 text-[10px] font-theme-data">
                    <span className="text-[var(--text-muted)]">ELO:</span>
                    <span className="text-[var(--text)]">{event.elo_before ?? '?'}</span>
                    <span className="text-[var(--text-muted)]">&rarr;</span>
                    <span className="text-[var(--text)]">{event.elo_after ?? '?'}</span>
                    <span className={eloChangeColor(event.elo_before, event.elo_after)}>
                      ({formatEloChange(event.elo_before, event.elo_after)})
                    </span>
                  </div>
                )}

                {/* Approval status */}
                {event.approved !== null && (
                  <div className="flex items-center gap-2 mt-1 text-[10px] font-theme-data">
                    <span className={event.approved ? 'text-green-400' : 'text-red-400'}>
                      {event.approved ? '[APPROVED]' : '[REJECTED]'}
                    </span>
                    {event.approved_by && (
                      <span className="text-[var(--text-muted)]">by {event.approved_by}</span>
                    )}
                  </div>
                )}

                {/* Diff toggle */}
                {hasDiff && (
                  <button
                    onClick={() => setExpandedId(isExpanded ? null : event.id)}
                    className="mt-2 text-[10px] font-theme-data text-[var(--acid-green)] hover:text-cyan-400 transition-colors"
                  >
                    {isExpanded ? '[-] HIDE DIFF' : '[+] SHOW DIFF'}
                  </button>
                )}

                {/* Diff view */}
                {isExpanded && hasDiff && (
                  <div className="mt-2 border border-[var(--border)] rounded overflow-hidden">
                    <div className="grid grid-cols-2 divide-x divide-[var(--border)]">
                      <div className="p-3">
                        <div className="text-[10px] font-theme-data text-red-400 mb-1">
                          --- BEFORE
                        </div>
                        <pre className="text-[10px] font-theme-data text-[var(--text-muted)] whitespace-pre-wrap break-words">
                          {event.old_value}
                        </pre>
                      </div>
                      <div className="p-3">
                        <div className="text-[10px] font-theme-data text-green-400 mb-1">
                          +++ AFTER
                        </div>
                        <pre className="text-[10px] font-theme-data text-[var(--text)] whitespace-pre-wrap break-words">
                          {event.new_value}
                        </pre>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel: ELO Trends Table
// ---------------------------------------------------------------------------

function EloTrendsPanel({
  agents,
  loading,
  period,
}: {
  agents: AgentEloTrend[];
  loading: boolean;
  period: string;
}) {
  if (loading) {
    return (
      <div className="p-6 text-xs font-theme-data text-[var(--text-muted)] animate-pulse">
        Loading ELO trends...
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div className="p-6 text-center text-xs font-theme-data text-[var(--text-muted)]">
        No ELO data available.
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4">
      {/* Summary table */}
      <div className="overflow-x-auto">
        <table className="w-full font-theme-data text-sm">
          <thead>
            <tr className="border-b border-[var(--acid-green)]/30">
              <th className="text-left py-2 px-3 text-[var(--acid-green)]">Agent</th>
              <th className="text-right py-2 px-3 text-[var(--acid-green)]">Current</th>
              <th className="text-right py-2 px-3 text-[var(--acid-green)]">Peak</th>
              <th className="text-right py-2 px-3 text-[var(--acid-green)]">Low</th>
              <th className="text-right py-2 px-3 text-[var(--acid-green)]">Delta</th>
              <th className="text-right py-2 px-3 text-[var(--acid-green)]">Debates</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((agent, i) => {
              const delta = agent.current_elo - (agent.trend[0]?.elo ?? agent.current_elo);
              const deltaColor =
                delta > 0
                  ? 'text-green-400'
                  : delta < 0
                    ? 'text-red-400'
                    : 'text-[var(--text-muted)]';
              return (
                <tr
                  key={agent.agent_name}
                  className={`border-b border-[var(--acid-green)]/10 ${
                    i % 2 === 0 ? 'bg-[var(--acid-green)]/5' : ''
                  }`}
                >
                  <td className={`py-2 px-3 ${ELO_COLORS[i % ELO_COLORS.length]}`}>
                    {agent.agent_name}
                    <span className="text-[10px] text-[var(--text-muted)] ml-2">
                      ({agent.provider})
                    </span>
                  </td>
                  <td className="py-2 px-3 text-right text-[var(--text)] font-bold">
                    {agent.current_elo}
                  </td>
                  <td className="py-2 px-3 text-right text-green-400/70">{agent.peak_elo}</td>
                  <td className="py-2 px-3 text-right text-red-400/70">{agent.lowest_elo}</td>
                  <td className={`py-2 px-3 text-right ${deltaColor}`}>
                    {delta > 0 ? '+' : ''}
                    {delta}
                  </td>
                  <td className="py-2 px-3 text-right text-[var(--text-muted)]">
                    {agent.total_debates}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* ASCII sparkline trend per agent */}
      <div className="space-y-3">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
          {'>'} TREND SPARKLINES ({period})
        </h3>
        {agents.map((agent, agentIdx) => {
          const trend = agent.trend;
          if (trend.length === 0) return null;

          const min = Math.min(...trend.map((t) => t.elo));
          const max = Math.max(...trend.map((t) => t.elo));
          const range = max - min || 1;

          // ASCII sparkline using block characters
          const barChars = [
            ' ',
            '\u2581',
            '\u2582',
            '\u2583',
            '\u2584',
            '\u2585',
            '\u2586',
            '\u2587',
            '\u2588',
          ];
          const sparkline = trend
            .map((t) => {
              const idx = Math.round(((t.elo - min) / range) * (barChars.length - 1));
              return barChars[idx];
            })
            .join('');

          return (
            <div key={agent.agent_name} className="flex items-center gap-3">
              <span
                className={`text-xs font-theme-data w-28 truncate ${ELO_COLORS[agentIdx % ELO_COLORS.length]}`}
              >
                {agent.agent_name}
              </span>
              <span className="text-sm font-theme-data text-[var(--acid-green)] tracking-wider">
                {sparkline}
              </span>
              <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                {min}-{max}
              </span>
            </div>
          );
        })}
      </div>

      {/* Detailed trend table */}
      <details className="border border-[var(--border)] rounded">
        <summary className="p-3 cursor-pointer hover:bg-[var(--surface)] transition-colors text-xs font-theme-data text-[var(--text-muted)]">
          [+] DETAILED ELO HISTORY
        </summary>
        <div className="p-3 border-t border-[var(--border)] max-h-64 overflow-y-auto">
          <table className="w-full font-theme-data text-[10px]">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="text-left py-1 px-2 text-[var(--text-muted)]">Agent</th>
                <th className="text-left py-1 px-2 text-[var(--text-muted)]">Date</th>
                <th className="text-right py-1 px-2 text-[var(--text-muted)]">ELO</th>
                <th className="text-right py-1 px-2 text-[var(--text-muted)]">Change</th>
              </tr>
            </thead>
            <tbody>
              {agents.flatMap((agent) =>
                agent.trend.map((point, idx) => (
                  <tr
                    key={`${agent.agent_name}-${idx}`}
                    className="border-b border-[var(--border)]/30"
                  >
                    <td className="py-1 px-2 text-[var(--text)]">{agent.agent_name}</td>
                    <td className="py-1 px-2 text-[var(--text-muted)]">
                      {new Date(point.timestamp).toLocaleDateString()}
                    </td>
                    <td className="py-1 px-2 text-right text-[var(--text)]">{point.elo}</td>
                    <td
                      className={`py-1 px-2 text-right ${
                        point.change > 0
                          ? 'text-green-400'
                          : point.change < 0
                            ? 'text-red-400'
                            : 'text-[var(--text-muted)]'
                      }`}
                    >
                      {point.change > 0 ? '+' : ''}
                      {point.change}
                    </td>
                  </tr>
                )),
              )}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Panel: Pending Changes
// ---------------------------------------------------------------------------

function PendingChangesPanel({
  changes,
  loading,
  isAdmin,
  onApprove,
  onReject,
}: {
  changes: PendingChange[];
  loading: boolean;
  isAdmin: boolean;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
}) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [actionInFlight, setActionInFlight] = useState<string | null>(null);

  if (loading) {
    return (
      <div className="p-6 text-xs font-theme-data text-[var(--text-muted)] animate-pulse">
        Loading pending changes...
      </div>
    );
  }

  const pendingOnly = changes.filter((c) => c.status === 'pending');

  if (pendingOnly.length === 0) {
    return (
      <div className="p-6 text-center text-xs font-theme-data text-[var(--text-muted)]">
        No pending changes. The Nomic Loop has nothing awaiting review.
      </div>
    );
  }

  const handleApprove = async (id: string) => {
    setActionInFlight(id);
    try {
      onApprove(id);
    } finally {
      setActionInFlight(null);
    }
  };

  const handleReject = async (id: string) => {
    setActionInFlight(id);
    try {
      onReject(id);
    } finally {
      setActionInFlight(null);
    }
  };

  return (
    <div className="divide-y divide-[var(--border)]">
      {pendingOnly.map((change) => {
        const style = CHANGE_TYPE_STYLES[change.change_type] || CHANGE_TYPE_STYLES.prompt_rewrite;
        const isExpanded = expandedId === change.id;

        return (
          <div key={change.id} className="p-4">
            {/* Header */}
            <div className="flex items-start justify-between gap-3 mb-2">
              <div className="flex-1">
                <div className="flex items-center gap-2 flex-wrap mb-1">
                  <span
                    className={`px-1.5 py-0 text-[10px] font-theme-data rounded ${style.bg} ${style.text}`}
                  >
                    {style.label}
                  </span>
                  <span className="text-xs font-theme-data text-[var(--acid-green)]">
                    {change.agent_name}
                  </span>
                  <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    [{change.nomic_cycle_id}]
                  </span>
                </div>
                <div className="text-xs font-theme-data text-[var(--text)] mb-1">
                  {change.description}
                </div>
                <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  {change.diff_summary}
                </div>
                <div className="text-[10px] font-theme-data text-cyan-400/70 mt-1">
                  Impact: {change.impact_estimate}
                </div>
                <div className="text-[10px] font-theme-data text-[var(--text-muted)] mt-0.5">
                  Proposed {formatRelativeTime(change.proposed_at)} by {change.proposed_by}
                </div>
              </div>

              {/* Admin controls */}
              {isAdmin && (
                <div className="flex gap-2 shrink-0">
                  <button
                    onClick={() => handleApprove(change.id)}
                    disabled={actionInFlight === change.id}
                    className="px-3 py-1.5 text-[10px] font-theme-data text-green-400 bg-green-500/10 border border-green-500/30 rounded hover:bg-green-500/20 disabled:opacity-50 transition-colors"
                  >
                    {actionInFlight === change.id ? '...' : 'APPROVE'}
                  </button>
                  <button
                    onClick={() => handleReject(change.id)}
                    disabled={actionInFlight === change.id}
                    className="px-3 py-1.5 text-[10px] font-theme-data text-red-400 bg-red-500/10 border border-red-500/30 rounded hover:bg-red-500/20 disabled:opacity-50 transition-colors"
                  >
                    {actionInFlight === change.id ? '...' : 'REJECT'}
                  </button>
                </div>
              )}
            </div>

            {/* Diff toggle */}
            <button
              onClick={() => setExpandedId(isExpanded ? null : change.id)}
              className="text-[10px] font-theme-data text-[var(--acid-green)] hover:text-cyan-400 transition-colors"
            >
              {isExpanded ? '[-] HIDE DIFF' : '[+] VIEW DIFF'}
            </button>

            {/* Diff view */}
            {isExpanded && (
              <div className="mt-2 border border-[var(--border)] rounded overflow-hidden">
                <div className="grid grid-cols-2 divide-x divide-[var(--border)]">
                  <div className="p-3 bg-red-500/5">
                    <div className="text-[10px] font-theme-data text-red-400 mb-2">--- CURRENT</div>
                    <pre className="text-[10px] font-theme-data text-[var(--text-muted)] whitespace-pre-wrap break-words leading-relaxed">
                      {change.old_content}
                    </pre>
                  </div>
                  <div className="p-3 bg-green-500/5">
                    <div className="text-[10px] font-theme-data text-green-400 mb-2">
                      +++ PROPOSED
                    </div>
                    <pre className="text-[10px] font-theme-data text-[var(--text)] whitespace-pre-wrap break-words leading-relaxed">
                      {change.new_content}
                    </pre>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AgentEvolutionPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';
  const [activeTab, setActiveTab] = useState<TabType>('timeline');
  const [eloPeriod, setEloPeriod] = useState('7d');

  const { timeline, trends, pending, isLoading, approveChange, rejectChange } =
    useAgentEvolutionDashboard(eloPeriod);

  const tabs: { id: TabType; label: string; count?: number }[] = [
    { id: 'timeline', label: 'TIMELINE' },
    { id: 'elo', label: 'ELO TRENDS' },
    { id: 'pending', label: 'PENDING', count: pending.total_pending },
  ];

  return (
    <div className="min-h-screen bg-[var(--bg)]">
      <Scanlines />
      <CRTVignette />

      <header className="border-b border-[var(--border)] bg-[var(--surface)]/50 backdrop-blur-sm sticky top-0 z-40">
        <div className="container mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Link href="/" className="hover:text-[var(--acid-green)]">
              <AsciiBannerCompact />
            </Link>
            <span className="text-[var(--text-muted)] font-theme-data text-sm">
              {'//'} AGENT EVOLUTION
            </span>
          </div>
          <div className="flex items-center gap-3">
            <BackendSelector />
            <ThemeToggle />
          </div>
        </div>
      </header>

      <main className="container mx-auto px-4 py-6 max-w-5xl relative z-10">
        {/* Breadcrumb + Title */}
        <div className="mb-6">
          <div className="flex items-center gap-3 mb-2">
            <Link
              href="/dashboard"
              className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
            >
              DASHBOARD
            </Link>
            <span className="text-xs font-theme-data text-[var(--text-muted)]">/</span>
            <span className="text-xs font-theme-data text-[var(--acid-green)]">
              AGENT EVOLUTION
            </span>
          </div>
          <h1 className="text-xl font-theme-data text-[var(--acid-green)] mb-1">
            {'>'} AGENT EVOLUTION DASHBOARD
          </h1>
          <p className="text-xs text-[var(--text-muted)] font-theme-data">
            Persona changes, ELO score trends, and pending Nomic Loop proposals
          </p>
        </div>

        {/* Tab Navigation */}
        <div className="flex flex-wrap items-center gap-1 border-b border-[var(--acid-green)]/20 pb-2 mb-6">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`px-4 py-2 text-xs font-theme-data transition-colors ${
                activeTab === tab.id
                  ? 'bg-[var(--acid-green)] text-[var(--bg)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--acid-green)]'
              }`}
            >
              [{tab.label}]
              {tab.count !== undefined && tab.count > 0 && (
                <span
                  className={`ml-1 px-1.5 py-0 text-[10px] rounded-full ${
                    activeTab === tab.id
                      ? 'bg-[var(--bg)] text-[var(--acid-green)]'
                      : 'bg-orange-500/20 text-orange-400'
                  }`}
                >
                  {tab.count}
                </span>
              )}
            </button>
          ))}

          {/* ELO period selector (visible on ELO tab) */}
          {activeTab === 'elo' && (
            <div className="ml-auto flex gap-1">
              {['7d', '30d', '90d'].map((p) => (
                <button
                  key={p}
                  onClick={() => setEloPeriod(p)}
                  className={`px-3 py-2 text-xs font-theme-data transition-colors ${
                    eloPeriod === p
                      ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/40'
                      : 'text-[var(--text-muted)] hover:text-[var(--text)]'
                  }`}
                >
                  {p}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Tab Content */}
        <div className="bg-[var(--surface)] border border-[var(--border)]">
          {/* Timeline Tab */}
          {activeTab === 'timeline' && (
            <PanelErrorBoundary panelName="Evolution Timeline">
              <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
                <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
                  {'>'} EVOLUTION TIMELINE
                </h3>
                <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  {timeline.total} events
                </span>
              </div>
              <TimelinePanel events={timeline.events} loading={isLoading} />
            </PanelErrorBoundary>
          )}

          {/* ELO Trends Tab */}
          {activeTab === 'elo' && (
            <PanelErrorBoundary panelName="ELO Trends">
              <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
                <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
                  {'>'} ELO SCORE TRENDS
                </h3>
                <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  {trends.agents.length} agents tracked
                </span>
              </div>
              <EloTrendsPanel agents={trends.agents} loading={isLoading} period={eloPeriod} />
            </PanelErrorBoundary>
          )}

          {/* Pending Changes Tab */}
          {activeTab === 'pending' && (
            <PanelErrorBoundary panelName="Pending Changes">
              <div className="p-4 border-b border-[var(--border)] flex items-center justify-between">
                <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
                  {'>'} PENDING NOMIC LOOP CHANGES
                </h3>
                <span
                  className={`text-[10px] font-theme-data ${
                    pending.total_pending > 0 ? 'text-orange-400' : 'text-[var(--text-muted)]'
                  }`}
                >
                  {pending.total_pending} pending
                </span>
              </div>
              {!isAdmin && pending.total_pending > 0 && (
                <div className="px-4 py-2 bg-yellow-500/10 border-b border-yellow-500/20 text-[10px] font-theme-data text-yellow-400">
                  Admin access required to approve or reject changes
                </div>
              )}
              <PendingChangesPanel
                changes={pending.changes}
                loading={isLoading}
                isAdmin={isAdmin}
                onApprove={approveChange}
                onReject={rejectChange}
              />
            </PanelErrorBoundary>
          )}
        </div>

        {/* Quick Links */}
        <div className="flex items-center gap-2 pt-4 mt-6 border-t border-[var(--border)]">
          <span className="text-xs font-theme-data text-[var(--text-muted)]">Related:</span>
          <Link
            href="/evolution"
            className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            EVOLUTION
          </Link>
          <Link
            href="/leaderboard"
            className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            LEADERBOARD
          </Link>
          <Link
            href="/analytics"
            className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            ANALYTICS
          </Link>
          <Link
            href="/self-improve"
            className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            NOMIC LOOP
          </Link>
        </div>
      </main>

      <footer className="border-t border-[var(--border)] bg-[var(--surface)]/50 py-4 mt-8">
        <div className="container mx-auto px-4 flex items-center justify-between text-xs text-[var(--text-muted)] font-theme-data">
          <span>Agent personas evolve through Nomic Loop debate cycles</span>
          <div className="flex items-center gap-4">
            <Link href="/evolution" className="hover:text-[var(--acid-green)]">
              EVOLUTION
            </Link>
            <Link href="/leaderboard" className="hover:text-[var(--acid-green)]">
              LEADERBOARD
            </Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
