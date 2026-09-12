'use client';

import { useCallback } from 'react';
import { useAragoraClient } from '@/hooks/useAragoraClient';
import { useAsyncData } from '@/hooks/useAsyncData';
import type {
  AnalyticsSummary,
  FindingsTrend,
  RemediationMetrics,
  AgentMetrics,
  CostAnalysis,
  ComplianceScore,
  DisagreementStats,
} from '@/lib/aragora-client';

/**
 * Comprehensive Analytics Dashboard using SDK client methods.
 *
 * Displays all analytics metrics from the extended AnalyticsAPI:
 * - Summary metrics
 * - Findings trends
 * - Remediation metrics
 * - Agent performance
 * - Cost analysis
 * - Compliance scores
 * - Disagreement stats
 */

interface StatCardProps {
  label: string;
  value: string | number;
  sublabel?: string;
  color?: 'green' | 'cyan' | 'yellow' | 'red' | 'purple';
}

function StatCard({ label, value, sublabel, color = 'green' }: StatCardProps) {
  const colorClasses = {
    green: 'border-[var(--accent)]/30 bg-[var(--accent)]/5 text-[var(--accent)]',
    cyan: 'border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 text-[var(--acid-cyan)]',
    yellow: 'border-acid-yellow/30 bg-acid-yellow/5 text-[var(--acid-yellow)]',
    red: 'border-[var(--crimson)]/30 bg-[var(--crimson)]/5 text-[var(--crimson)]',
    purple: 'border-purple-500/30 bg-purple-500/5 text-purple-400',
  };

  return (
    <div className={`border ${colorClasses[color]} p-3 rounded`}>
      <div className="text-text-muted text-xs">{label}</div>
      <div className={`text-xl font-theme-data ${colorClasses[color].split(' ')[2]}`}>{value}</div>
      {sublabel && <div className="text-text-muted text-[10px] mt-1">{sublabel}</div>}
    </div>
  );
}

function ProgressBar({
  value,
  max = 100,
  color = 'green',
}: {
  value: number;
  max?: number;
  color?: string;
}) {
  const percentage = Math.min((value / max) * 100, 100);
  const colorClass =
    color === 'green'
      ? 'bg-[var(--accent)]'
      : color === 'red'
        ? 'bg-[var(--crimson)]'
        : 'bg-[var(--acid-cyan)]';

  return (
    <div className="h-2 bg-surface rounded-full overflow-hidden">
      <div
        className={`h-full ${colorClass} transition-all duration-300`}
        style={{ width: `${percentage}%` }}
      />
    </div>
  );
}

export function AnalyticsDashboard() {
  const client = useAragoraClient();

  // Fetch all analytics data
  const summaryFetcher = useCallback(async () => {
    const res = await client.analytics.summary();
    return res.summary;
  }, [client]);

  const trendsFetcher = useCallback(async () => {
    const res = await client.analytics.findingsTrends(30);
    return res.trends;
  }, [client]);

  const remediationFetcher = useCallback(async () => {
    const res = await client.analytics.remediation();
    return res.metrics;
  }, [client]);

  const agentsFetcher = useCallback(async () => {
    const res = await client.analytics.agents();
    return res.agents;
  }, [client]);

  const costFetcher = useCallback(async () => {
    const res = await client.analytics.cost(30);
    return res.analysis;
  }, [client]);

  const complianceFetcher = useCallback(async () => {
    const res = await client.analytics.compliance();
    return res.compliance;
  }, [client]);

  const disagreementsFetcher = useCallback(async () => {
    const res = await client.analytics.disagreements();
    return res.stats;
  }, [client]);

  const {
    data: summary,
    loading: summaryLoading,
    error: summaryError,
  } = useAsyncData<AnalyticsSummary>(summaryFetcher, { immediate: true });

  const { data: trends, loading: trendsLoading } = useAsyncData<FindingsTrend[]>(trendsFetcher, {
    immediate: true,
  });

  const { data: remediation, loading: remediationLoading } = useAsyncData<RemediationMetrics>(
    remediationFetcher,
    { immediate: true },
  );

  const { data: agents, loading: agentsLoading } = useAsyncData<AgentMetrics[]>(agentsFetcher, {
    immediate: true,
  });

  const { data: cost, loading: costLoading } = useAsyncData<CostAnalysis>(costFetcher, {
    immediate: true,
  });

  const { data: compliance, loading: complianceLoading } = useAsyncData<ComplianceScore>(
    complianceFetcher,
    { immediate: true },
  );

  const { data: disagreements, loading: disagreementsLoading } = useAsyncData<DisagreementStats>(
    disagreementsFetcher,
    { immediate: true },
  );

  const isLoading =
    summaryLoading ||
    trendsLoading ||
    remediationLoading ||
    agentsLoading ||
    costLoading ||
    complianceLoading ||
    disagreementsLoading;

  if (summaryError) {
    return (
      <div className="p-6 text-center">
        <div className="text-[var(--crimson)] font-theme-data mb-2">Failed to load analytics</div>
        <div className="text-text-muted text-sm">{summaryError}</div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Summary Section */}
      <section>
        <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">{'>'} OVERVIEW</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="Total Debates" value={summary?.total_debates ?? '-'} color="green" />
          <StatCard label="Total Messages" value={summary?.total_messages ?? '-'} color="cyan" />
          <StatCard
            label="Consensus Rate"
            value={summary ? `${(summary.consensus_rate * 100).toFixed(1)}%` : '-'}
            color="purple"
          />
          <StatCard
            label="Active Users (24h)"
            value={summary?.active_users_24h ?? '-'}
            color="yellow"
          />
        </div>
      </section>

      {/* Remediation Section */}
      {remediation && (
        <section>
          <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">{'>'} REMEDIATION</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
            <StatCard label="Total Findings" value={remediation.total_findings} color="yellow" />
            <StatCard label="Remediated" value={remediation.remediated} color="green" />
            <StatCard label="Pending" value={remediation.pending} color="red" />
            <StatCard
              label="Avg Time (hrs)"
              value={remediation.avg_remediation_time_hours.toFixed(1)}
              color="cyan"
            />
          </div>
          <div className="border border-[var(--accent)]/30 bg-surface p-3 rounded">
            <div className="flex justify-between text-xs text-text-muted mb-2">
              <span>Remediation Progress</span>
              <span className="text-[var(--accent)]">
                {(remediation.remediation_rate * 100).toFixed(1)}%
              </span>
            </div>
            <ProgressBar value={remediation.remediation_rate * 100} />
          </div>
        </section>
      )}

      {/* Compliance Section */}
      {compliance && (
        <section>
          <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">{'>'} COMPLIANCE</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="border border-purple-500/30 bg-purple-500/5 p-4 rounded">
              <div className="text-text-muted text-xs mb-2">Overall Score</div>
              <div className="text-3xl font-theme-data text-purple-400 mb-2">
                {compliance.overall_score}%
              </div>
              <div className="text-text-muted text-[10px]">
                Last audit:{' '}
                {compliance.last_audit
                  ? new Date(compliance.last_audit).toLocaleDateString()
                  : 'N/A'}
              </div>
            </div>
            <div className="border border-[var(--accent)]/30 bg-surface p-3 rounded">
              <div className="text-text-muted text-xs mb-3">Categories</div>
              <div className="space-y-2">
                {compliance.categories.slice(0, 4).map((cat) => (
                  <div key={cat.category} className="flex items-center justify-between text-xs">
                    <span className="text-text truncate max-w-[120px]">{cat.category}</span>
                    <div className="flex items-center gap-2">
                      <ProgressBar value={cat.score} max={cat.max_score} />
                      <span className="text-[var(--accent)] font-theme-data w-12 text-right">
                        {cat.score}/{cat.max_score}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Cost Analysis Section */}
      {cost && (
        <section>
          <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">{'>'} COST ANALYSIS</h2>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-3">
            <StatCard
              label="Total Cost (30d)"
              value={`$${cost.total_cost_usd.toFixed(2)}`}
              color="yellow"
            />
            <StatCard
              label="Projected Monthly"
              value={`$${cost.projected_monthly_cost.toFixed(2)}`}
              color="cyan"
            />
            <div className="border border-[var(--accent)]/30 bg-surface p-3 rounded col-span-2 md:col-span-1">
              <div className="text-text-muted text-xs mb-2">Cost by Model</div>
              <div className="space-y-1">
                {Object.entries(cost.cost_by_model)
                  .slice(0, 3)
                  .map(([model, amount]) => (
                    <div key={model} className="flex justify-between text-xs">
                      <span className="text-text truncate max-w-[100px]">{model}</span>
                      <span className="text-[var(--accent)] font-theme-data">
                        ${(amount as number).toFixed(2)}
                      </span>
                    </div>
                  ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Agent Performance Section */}
      {agents && agents.length > 0 && (
        <section>
          <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">
            {'>'} AGENT PERFORMANCE
          </h2>
          <div className="border border-[var(--accent)]/30 bg-surface rounded overflow-hidden">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-[var(--accent)]/20 bg-[var(--accent)]/5">
                  <th className="text-left p-2 text-text-muted">Agent</th>
                  <th className="text-right p-2 text-text-muted">Debates</th>
                  <th className="text-right p-2 text-text-muted">Avg Length</th>
                  <th className="text-right p-2 text-text-muted">Consensus</th>
                  <th className="text-right p-2 text-text-muted">ELO</th>
                </tr>
              </thead>
              <tbody>
                {agents.slice(0, 5).map((agent) => (
                  <tr
                    key={agent.agent_id}
                    className="border-b border-[var(--accent)]/10 hover:bg-[var(--accent)]/5"
                  >
                    <td className="p-2 font-theme-data text-[var(--acid-cyan)]">
                      {agent.name || agent.agent_id}
                    </td>
                    <td className="p-2 text-right text-text">{agent.debates_participated}</td>
                    <td className="p-2 text-right text-text">{agent.avg_message_length}</td>
                    <td className="p-2 text-right text-[var(--accent)]">
                      {(agent.consensus_contribution * 100).toFixed(0)}%
                    </td>
                    <td className="p-2 text-right text-purple-400">{agent.elo_rating ?? '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Disagreements Section */}
      {disagreements && (
        <section>
          <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">{'>'} DISAGREEMENTS</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatCard
              label="Total Disagreements"
              value={disagreements.total_disagreements}
              color="yellow"
            />
            <StatCard
              label="Avg Intensity"
              value={`${(disagreements.avg_disagreement_intensity * 100).toFixed(0)}%`}
              color="red"
            />
            <StatCard
              label="Resolved Rate"
              value={`${(disagreements.resolved_rate * 100).toFixed(1)}%`}
              color="green"
            />
            <div className="border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 p-3 rounded">
              <div className="text-text-muted text-xs mb-2">Top Topics</div>
              <div className="space-y-1">
                {disagreements.top_disagreement_topics.slice(0, 3).map((t) => (
                  <div key={t.topic} className="flex justify-between text-xs">
                    <span className="text-text truncate max-w-[80px]">{t.topic}</span>
                    <span className="text-[var(--acid-cyan)] font-theme-data">{t.count}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Findings Trends Mini Chart */}
      {trends && trends.length > 0 && (
        <section>
          <h2 className="text-lg font-theme-data text-[var(--accent)] mb-3">
            {'>'} FINDINGS TREND (30D)
          </h2>
          <div className="border border-[var(--accent)]/30 bg-surface p-4 rounded">
            <div className="flex items-end gap-1 h-20">
              {trends.slice(-14).map((day) => {
                const maxFindings = Math.max(...trends.map((t) => t.findings_count), 1);
                const height = (day.findings_count / maxFindings) * 100;

                return (
                  <div
                    key={day.date}
                    className="flex-1 flex flex-col items-center group"
                    title={`${day.date}: ${day.findings_count} findings`}
                  >
                    <div
                      className="w-full bg-[var(--accent)]/60 hover:bg-[var(--accent)] transition-colors rounded-t"
                      style={{
                        height: `${height}%`,
                        minHeight: day.findings_count > 0 ? '4px' : '0',
                      }}
                    />
                  </div>
                );
              })}
            </div>
            <div className="flex justify-between text-[10px] text-text-muted mt-2">
              <span>{trends[Math.max(0, trends.length - 14)]?.date}</span>
              <span>{trends[trends.length - 1]?.date}</span>
            </div>
            <div className="flex gap-4 mt-3 text-xs">
              <span className="text-[var(--crimson)]">
                Critical: {trends.reduce((a, t) => a + t.critical, 0)}
              </span>
              <span className="text-warning">High: {trends.reduce((a, t) => a + t.high, 0)}</span>
              <span className="text-[var(--acid-yellow)]">
                Medium: {trends.reduce((a, t) => a + t.medium, 0)}
              </span>
              <span className="text-text-muted">Low: {trends.reduce((a, t) => a + t.low, 0)}</span>
            </div>
          </div>
        </section>
      )}

      {/* Loading overlay */}
      {isLoading && (
        <div className="fixed inset-0 bg-bg/50 flex items-center justify-center z-50 pointer-events-none">
          <div className="text-[var(--accent)] font-theme-data animate-pulse">
            Loading analytics...
          </div>
        </div>
      )}
    </div>
  );
}

export default AnalyticsDashboard;
