'use client';

import { useState, useMemo } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { MetricCard, TrendChart, type DataPoint } from '@/components/analytics';
import { useDecisionAnalytics, type AnalyticsPeriod } from '@/hooks/useDecisionAnalytics';

// ============================================================================
// Helpers
// ============================================================================

function formatPct(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

// ============================================================================
// Sub-components
// ============================================================================

function PeriodSelector({
  value,
  onChange,
}: {
  value: AnalyticsPeriod;
  onChange: (v: AnalyticsPeriod) => void;
}) {
  const options: AnalyticsPeriod[] = ['7d', '30d', '90d', '365d'];

  return (
    <div className="flex gap-1">
      {options.map((p) => (
        <button
          key={p}
          onClick={() => onChange(p)}
          className={`px-3 py-2 text-xs font-theme-data transition-colors ${
            value === p
              ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/40'
              : 'text-text-muted hover:text-text'
          }`}
        >
          {p}
        </button>
      ))}
    </div>
  );
}

/** Agent quality table */
function AgentTable({
  agents,
}: {
  agents: {
    agent_name: string;
    debates_participated: number;
    consensus_contributions: number;
    avg_confidence: number;
    contribution_score: number;
  }[];
}) {
  if (agents.length === 0) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">{'>'} AGENT QUALITY</h3>
        <p className="text-text-muted font-theme-data text-sm text-center py-4">
          No agent quality data yet. Debates will show contribution scores and consensus accuracy
          here.
        </p>
      </div>
    );
  }

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">{'>'} AGENT QUALITY</h3>
      <div className="overflow-x-auto">
        <table className="w-full font-theme-data text-sm">
          <thead>
            <tr className="border-b border-[var(--accent)]/30">
              <th className="py-2 px-3 text-[var(--accent)] text-left">Agent</th>
              <th className="py-2 px-3 text-[var(--accent)] text-right">Debates</th>
              <th className="py-2 px-3 text-[var(--accent)] text-right">Consensus</th>
              <th className="py-2 px-3 text-[var(--accent)] text-right">Confidence</th>
              <th className="py-2 px-3 text-[var(--accent)] text-right">Score</th>
            </tr>
          </thead>
          <tbody>
            {agents.map((a, i) => (
              <tr
                key={a.agent_name}
                className={`border-b border-[var(--accent)]/10 ${
                  i % 2 === 0 ? 'bg-[var(--accent)]/5' : ''
                }`}
              >
                <td className="py-2 px-3 text-[var(--acid-cyan)]">{a.agent_name}</td>
                <td className="py-2 px-3 text-right text-text">{a.debates_participated}</td>
                <td className="py-2 px-3 text-right text-text">{a.consensus_contributions}</td>
                <td className="py-2 px-3 text-right text-text-muted">
                  {formatPct(a.avg_confidence)}
                </td>
                <td className="py-2 px-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <span className="text-[var(--accent)]">
                      {(a.contribution_score * 100).toFixed(0)}
                    </span>
                    <div className="w-16 h-2 bg-surface rounded overflow-hidden">
                      <div
                        className="h-full bg-[var(--accent)]/60 rounded"
                        style={{ width: `${Math.min(a.contribution_score * 100, 100)}%` }}
                      />
                    </div>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Domain breakdown table */
function DomainTable({
  domains,
  total,
}: {
  domains: { domain: string; decision_count: number; percentage: number }[];
  total: number;
}) {
  if (domains.length === 0) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">{'>'} DOMAINS</h3>
        <p className="text-text-muted font-theme-data text-sm text-center py-4">
          No domain data yet. Run debates across different topics to see decision distribution by
          domain.
        </p>
      </div>
    );
  }

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
        {'>'} DOMAINS ({total} decisions)
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full font-theme-data text-sm">
          <thead>
            <tr className="border-b border-[var(--accent)]/30">
              <th className="py-2 px-3 text-[var(--accent)] text-left">Domain</th>
              <th className="py-2 px-3 text-[var(--accent)] text-right">Count</th>
              <th className="py-2 px-3 text-[var(--accent)] text-right">Share</th>
              <th className="py-2 px-3 text-[var(--accent)] text-right">Bar</th>
            </tr>
          </thead>
          <tbody>
            {domains.map((d, i) => (
              <tr
                key={d.domain}
                className={`border-b border-[var(--accent)]/10 ${
                  i % 2 === 0 ? 'bg-[var(--accent)]/5' : ''
                }`}
              >
                <td className="py-2 px-3 text-[var(--acid-cyan)]">{d.domain}</td>
                <td className="py-2 px-3 text-right text-text">{d.decision_count}</td>
                <td className="py-2 px-3 text-right text-text-muted">{d.percentage.toFixed(1)}%</td>
                <td className="py-2 px-3 text-right">
                  <div className="w-24 h-2 bg-surface rounded overflow-hidden ml-auto">
                    <div
                      className="h-full bg-[var(--acid-cyan)]/60 rounded"
                      style={{ width: `${Math.min(d.percentage, 100)}%` }}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Recent outcomes list */
function OutcomesList({
  outcomes,
  total,
}: {
  outcomes: {
    debate_id: string;
    task: string;
    consensus_reached: boolean;
    confidence: number;
    rounds: number;
    agents: string[];
    duration_seconds: number;
    created_at: string;
  }[];
  total: number;
}) {
  if (outcomes.length === 0) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
          {'>'} RECENT DECISIONS ({total})
        </h3>
        <p className="text-text-muted font-theme-data text-sm text-center py-4">
          No decisions recorded yet. Start a debate to see verdicts, quality scores, and agent
          participation here.
        </p>
      </div>
    );
  }

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
        {'>'} RECENT DECISIONS ({total} total)
      </h3>
      <div className="space-y-2">
        {outcomes.map((o) => (
          <div
            key={o.debate_id}
            className={`flex items-center justify-between p-3 border rounded font-theme-data text-xs ${
              o.consensus_reached
                ? 'border-[var(--accent)]/30 bg-[var(--accent)]/5'
                : 'border-acid-yellow/30 bg-acid-yellow/5'
            }`}
          >
            <div className="flex items-center gap-3 min-w-0 flex-1">
              <span
                className={
                  o.consensus_reached ? 'text-[var(--accent)]' : 'text-[var(--acid-yellow)]'
                }
              >
                {o.consensus_reached ? '[OK]' : '[--]'}
              </span>
              <span className="text-text truncate">{o.task || o.debate_id}</span>
            </div>
            <div className="flex items-center gap-4 flex-shrink-0 ml-4">
              <span className="text-text-muted">{o.rounds}r</span>
              <span className="text-text-muted">{o.agents.length}a</span>
              <span className="text-text-muted">{formatDuration(o.duration_seconds)}</span>
              <span className="text-text-muted text-[10px]">
                {o.created_at ? new Date(o.created_at).toLocaleDateString() : ''}
              </span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ============================================================================
// Main Page
// ============================================================================

export default function DecisionAnalyticsPage() {
  const [period, setPeriod] = useState<AnalyticsPeriod>('30d');

  const { overview, trends, outcomes, agentMetrics, domainMetrics, isLoading, error } =
    useDecisionAnalytics(period);

  // Transform trend points into DataPoint[] for the TrendChart
  const consensusTrendData: DataPoint[] = useMemo(() => {
    if (!trends?.points) return [];
    return trends.points.map((p) => ({
      label: p.timestamp.split('T')[0]?.split('-').slice(1).join('/') ?? '',
      value: p.consensus_rate * 100,
      date: p.timestamp.split('T')[0] ?? '',
    }));
  }, [trends]);

  const roundsTrendData: DataPoint[] = useMemo(() => {
    if (!trends?.points) return [];
    return trends.points.map((p) => ({
      label: p.timestamp.split('T')[0]?.split('-').slice(1).join('/') ?? '',
      value: p.avg_rounds,
      date: p.timestamp.split('T')[0] ?? '',
    }));
  }, [trends]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6 max-w-7xl">
          {/* Header */}
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-4 mb-6">
            <div>
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-1">
                {'>'} DECISION ANALYTICS
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Track AI-assisted decision quality, consensus rates, and agent performance over
                time.
              </p>
            </div>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>

          {/* Error banner */}
          {error && (
            <div className="mb-6 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded p-4 text-[var(--crimson)] text-sm font-theme-data">
              Failed to load decision analytics. The server may be unavailable.
            </div>
          )}

          {/* ---- Overview Cards ---- */}
          <PanelErrorBoundary panelName="Decision Overview">
            <section className="mb-6">
              <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">{'>'} OVERVIEW</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  title="Total Decisions"
                  value={overview?.total_decisions ?? 0}
                  subtitle={`${period} period`}
                  color="green"
                  loading={isLoading}
                  icon="#"
                />
                <MetricCard
                  title="Consensus Rate"
                  value={overview ? `${(overview.consensus_rate * 100).toFixed(1)}%` : '--'}
                  subtitle={`${overview?.consensus_reached ?? 0} reached`}
                  color="cyan"
                  loading={isLoading}
                  icon="%"
                />
                <MetricCard
                  title="Avg Confidence"
                  value={overview ? `${(overview.avg_confidence * 100).toFixed(1)}%` : '--'}
                  subtitle="mean confidence"
                  color="yellow"
                  loading={isLoading}
                  icon="~"
                />
                <MetricCard
                  title="Avg Rounds"
                  value={overview?.avg_rounds?.toFixed(1) ?? '--'}
                  subtitle="rounds to conclusion"
                  color="green"
                  loading={isLoading}
                  icon="@"
                />
              </div>
            </section>
          </PanelErrorBoundary>

          {/* ---- Quality Trend ---- */}
          <PanelErrorBoundary panelName="Quality Trend">
            <section className="mb-6">
              <TrendChart
                title={`> CONSENSUS RATE TREND (${period})`}
                data={consensusTrendData}
                type="area"
                color="cyan"
                loading={isLoading}
                showTimeRangeSelector={false}
                height={280}
                formatValue={(v) => `${v.toFixed(1)}%`}
              />
            </section>
          </PanelErrorBoundary>

          {/* ---- Rounds Trend ---- */}
          <PanelErrorBoundary panelName="Rounds Trend">
            <section className="mb-6">
              <TrendChart
                title={`> AVG ROUNDS TO CONCLUSION (${period})`}
                data={roundsTrendData}
                type="line"
                color="green"
                loading={isLoading}
                showTimeRangeSelector={false}
                height={200}
                formatValue={(v) => v.toFixed(1)}
              />
            </section>
          </PanelErrorBoundary>

          {/* ---- Agent + Domain Tables ---- */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <PanelErrorBoundary panelName="Agent Quality">
              <AgentTable agents={agentMetrics?.agents ?? []} />
            </PanelErrorBoundary>

            <PanelErrorBoundary panelName="Domains">
              <DomainTable
                domains={domainMetrics?.domains ?? []}
                total={domainMetrics?.total_decisions ?? 0}
              />
            </PanelErrorBoundary>
          </div>

          {/* ---- Recent Decisions ---- */}
          <PanelErrorBoundary panelName="Recent Decisions">
            <section className="mb-6">
              <OutcomesList outcomes={outcomes?.outcomes ?? []} total={outcomes?.total ?? 0} />
            </section>
          </PanelErrorBoundary>

          {/* Footer */}
          <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
            <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
            <p className="text-text-muted">{'>'} ARAGORA // DECISION OUTCOME ANALYTICS</p>
          </footer>
        </div>
      </main>
    </>
  );
}
