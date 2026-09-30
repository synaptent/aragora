'use client';

import { useState } from 'react';
import { KPICard, KPIGrid, KPIMiniCard } from './KPICards';
import { useUsageDashboard, type TimeRange } from '@/hooks/useUsageDashboard';
import { useSWRFetch } from '@/hooks/useSWRFetch';

interface ExecutiveSummaryProps {
  refreshInterval?: number; // ms (now handled by hook)
}

interface ExecutiveAgentPerformance {
  agent_id: string;
  agent_name: string;
  participations: number;
  consensus_contributions: number;
  consensus_rate: string;
  avg_agreement_score: number;
}

interface ExecutiveUsageSummary {
  period: { type: string; start: string; end: string; days: number };
  debates: { total: number; completed: number; consensus_rate: number };
  costs: { total_usd: string; avg_per_debate_usd: string; by_provider: Record<string, string> };
  quality?: { avg_confidence?: number };
  agents?: { top_agents?: ExecutiveAgentPerformance[] };
}

function getPeriodForRange(range: TimeRange): string {
  switch (range) {
    case '24h':
      return 'day';
    case '7d':
      return 'week';
    case '30d':
      return 'month';
    case '90d':
      return 'quarter';
    default:
      return 'month';
  }
}

export function ExecutiveSummary({ refreshInterval = 30000 }: ExecutiveSummaryProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');
  const {
    roi,
    budget,
    forecast,
    isLoading: usageLoading,
    error: usageError,
  } = useUsageDashboard(timeRange, { refreshInterval });
  const {
    data: summaryEnvelope,
    isLoading: summaryLoading,
    error: summaryError,
  } = useSWRFetch<{ data: ExecutiveUsageSummary }>(
    `/api/v1/usage/summary?period=${getPeriodForRange(timeRange)}`,
    { refreshInterval },
  );
  const summary = summaryEnvelope?.data ?? null;
  const topAgents = summary?.agents?.top_agents ?? [];
  const isLoading = usageLoading || summaryLoading;
  const error = usageError || summaryError;

  const formatNumber = (num: number): string => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  const formatCurrency = (value: number): string => {
    if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
    if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
    if (value >= 1) return `$${value.toFixed(2)}`;
    return `$${value.toFixed(3)}`;
  };

  const formatTime = (date: Date): string => {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 p-4 text-red-400 font-theme-data text-sm">
        Error loading dashboard: {error.message}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header with Time Range Selector */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-theme-data text-[var(--acid-green)]">
          {'>'} EXECUTIVE SUMMARY
        </h2>
        <div className="flex items-center gap-4">
          {/* Time Range Selector */}
          <div className="flex items-center gap-2">
            {(['24h', '7d', '30d', '90d'] as TimeRange[]).map((range) => (
              <button
                key={range}
                onClick={() => setTimeRange(range)}
                className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
                  timeRange === range
                    ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/50'
                    : 'bg-[var(--surface)] text-[var(--text-muted)] border-[var(--border)] hover:border-[var(--acid-green)]/30'
                }`}
              >
                {range.toUpperCase()}
              </button>
            ))}
          </div>
          {summary?.period?.end && (
            <span className="text-xs font-theme-data text-[var(--text-muted)]">
              Updated: {formatTime(new Date(summary.period.end))}
            </span>
          )}
        </div>
      </div>

      {/* Primary KPIs */}
      <KPIGrid columns={4}>
        <KPICard
          title="Total Debates"
          value={summary?.debates.total ?? '-'}
          subtitle={`${summary?.debates.completed ?? 0} completed`}
          color="green"
          loading={isLoading}
          icon=""
        />
        <KPICard
          title="Avg Confidence"
          value={
            summary?.quality?.avg_confidence != null
              ? `${(summary.quality.avg_confidence * 100).toFixed(0)}%`
              : '-'
          }
          subtitle={
            summary ? `${summary.debates.consensus_rate.toFixed(1)}% consensus rate` : undefined
          }
          color="cyan"
          loading={isLoading}
          icon=""
        />
        <KPICard
          title="Top Agents"
          value={topAgents.length > 0 ? `${topAgents.length} ranked` : '-'}
          subtitle={
            topAgents.length > 0
              ? topAgents.map((agent) => agent.agent_name).join(', ')
              : 'Run debates to rank agents'
          }
          color="yellow"
          loading={isLoading}
          icon=""
        />
        <KPICard
          title="Total Spend"
          value={summary ? formatCurrency(Number(summary.costs.total_usd)) : '-'}
          subtitle={
            summary
              ? `${formatCurrency(Number(summary.costs.avg_per_debate_usd))} per debate`
              : undefined
          }
          color="purple"
          loading={isLoading}
          icon=""
        />
      </KPIGrid>

      {/* Secondary Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Agent Health */}
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3 flex items-center gap-2">
            <span></span> AGENT HEALTH
          </h3>
          <div className="space-y-1">
            <KPIMiniCard label="#1 Agent" value={topAgents[0]?.agent_name ?? '-'} color="green" />
            <KPIMiniCard label="#2 Agent" value={topAgents[1]?.agent_name ?? '-'} color="cyan" />
            <KPIMiniCard label="#3 Agent" value={topAgents[2]?.agent_name ?? '-'} color="yellow" />
          </div>
        </div>

        {/* ROI Summary */}
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3 flex items-center gap-2">
            <span>$</span> ROI SUMMARY
          </h3>
          <div className="space-y-1">
            <KPIMiniCard
              label="ROI"
              value={roi ? `${roi.roi_percentage.toFixed(0)}%` : '-'}
              color="green"
            />
            <KPIMiniCard
              label="Time Saved"
              value={roi ? `${roi.time_saved_hours.toFixed(0)} hrs` : '-'}
              color="cyan"
            />
            <KPIMiniCard
              label="Cost Savings"
              value={roi ? `$${formatNumber(roi.cost_savings_usd)}` : '-'}
              color="yellow"
            />
          </div>
        </div>

        {/* Budget Status */}
        <div
          className={`bg-[var(--surface)] border p-4 ${
            budget?.alert_level === 'critical'
              ? 'border-red-500/50'
              : budget?.alert_level === 'warning'
                ? 'border-yellow-500/50'
                : 'border-[var(--border)]'
          }`}
        >
          <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3 flex items-center gap-2">
            <span></span> BUDGET STATUS
            {budget?.alert_level && budget.alert_level !== 'normal' && (
              <span
                className={`ml-auto px-2 py-0.5 text-xs uppercase ${
                  budget.alert_level === 'critical'
                    ? 'bg-red-500/20 text-red-400'
                    : 'bg-yellow-500/20 text-yellow-400'
                }`}
              >
                {budget.alert_level}
              </span>
            )}
          </h3>
          <div className="space-y-1">
            <KPIMiniCard
              label="Utilization"
              value={budget ? `${budget.utilization_percent.toFixed(0)}%` : '-'}
              color={
                budget?.alert_level === 'critical'
                  ? 'red'
                  : budget?.alert_level === 'warning'
                    ? 'yellow'
                    : 'green'
              }
            />
            <KPIMiniCard
              label="Remaining"
              value={budget ? `$${formatNumber(budget.remaining_usd)}` : '-'}
              color="cyan"
            />
            <KPIMiniCard label="Days Left" value={budget?.days_remaining ?? '-'} color="yellow" />
          </div>
        </div>
      </div>

      {/* Forecast Banner */}
      {forecast && (
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <h3 className="text-sm font-theme-data text-[var(--acid-cyan)]">MONTHLY FORECAST</h3>
              <span
                className={`text-xs font-theme-data px-2 py-0.5 ${
                  forecast.trend === 'increasing'
                    ? 'bg-yellow-500/20 text-yellow-400'
                    : forecast.trend === 'decreasing'
                      ? 'bg-green-500/20 text-green-400'
                      : 'bg-[var(--border)] text-[var(--text-muted)]'
                }`}
              >
                {forecast.trend.toUpperCase()}
              </span>
            </div>
            <div className="flex items-center gap-6 text-sm font-theme-data">
              <div>
                <span className="text-[var(--text-muted)]">Debates: </span>
                <span className="text-[var(--acid-green)]">
                  {formatNumber(forecast.projected_monthly_debates)}
                </span>
              </div>
              <div>
                <span className="text-[var(--text-muted)]">Tokens: </span>
                <span className="text-[var(--acid-cyan)]">
                  {formatNumber(forecast.projected_monthly_tokens)}
                </span>
              </div>
              <div>
                <span className="text-[var(--text-muted)]">Cost: </span>
                <span className="text-yellow-400">
                  ${formatNumber(forecast.projected_monthly_cost_usd)}
                </span>
              </div>
              <div>
                <span className="text-[var(--text-muted)]">Growth: </span>
                <span
                  className={
                    forecast.growth_rate_percent >= 0 ? 'text-yellow-400' : 'text-green-400'
                  }
                >
                  {forecast.growth_rate_percent >= 0 ? '+' : ''}
                  {forecast.growth_rate_percent.toFixed(1)}%
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Quick Actions */}
      <div className="flex items-center gap-2 pt-2">
        <span className="text-xs font-theme-data text-[var(--text-muted)]">Quick actions:</span>
        <a
          href="/arena"
          className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
        >
          NEW DEBATE
        </a>
        <a
          href="/debates/provenance"
          className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
        >
          AUDIT TRAIL
        </a>
        <a
          href="/control-plane"
          className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
        >
          DASHBOARD
        </a>
        <a
          href="/usage"
          className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
        >
          DETAILED USAGE
        </a>
      </div>
    </div>
  );
}

export default ExecutiveSummary;
