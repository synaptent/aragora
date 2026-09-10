'use client';

import { KPICard, KPIGrid, KPIMiniCard } from './KPICards';
import type { UsageSummary, UsageForecast, TimeRange } from '@/hooks/useUsageDashboard';

interface UsageBreakdownProps {
  summary: UsageSummary | null;
  forecast: UsageForecast | null;
  timeRange: TimeRange;
  loading?: boolean;
}

/**
 * Usage Breakdown component for the usage dashboard.
 * Displays token usage, costs, and debate metrics with forecasting.
 */
export function UsageBreakdown({
  summary,
  forecast,
  timeRange,
  loading = false,
}: UsageBreakdownProps) {
  const formatNumber = (num: number): string => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  const formatCurrency = (value: number): string => {
    if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
    return `$${value.toFixed(2)}`;
  };

  const getTimeRangeLabel = (range: TimeRange): string => {
    switch (range) {
      case '24h':
        return 'Today';
      case '7d':
        return 'This Week';
      case '30d':
        return 'This Month';
      case '90d':
        return 'This Quarter';
      default:
        return range;
    }
  };

  const getTrendIcon = (trend: string): string => {
    if (trend === 'increasing') return '^';
    if (trend === 'decreasing') return 'v';
    return '~';
  };

  const getTrendColor = (trend: string): 'green' | 'red' | 'yellow' => {
    // For costs, increasing is bad (red), decreasing is good (green)
    if (trend === 'increasing') return 'red';
    if (trend === 'decreasing') return 'green';
    return 'yellow';
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] flex items-center gap-2">
          <span>@</span> USAGE BREAKDOWN
        </h3>
        <span className="text-xs font-theme-data text-[var(--text-muted)]">
          {getTimeRangeLabel(timeRange)}
        </span>
      </div>

      {/* Primary Usage KPIs */}
      <KPIGrid columns={4}>
        <KPICard
          title="Total Debates"
          value={summary?.debates.total ?? '-'}
          subtitle={`${summary?.debates.completed ?? 0} completed`}
          color="green"
          loading={loading}
        />
        <KPICard
          title="Tokens (In)"
          value={summary ? formatNumber(summary.tokens.total_in) : '-'}
          subtitle={summary ? `${formatNumber(summary.tokens.today)} today` : undefined}
          color="cyan"
          loading={loading}
        />
        <KPICard
          title="Tokens (Out)"
          value={summary ? formatNumber(summary.tokens.total_out) : '-'}
          subtitle={summary ? `${formatNumber(summary.tokens.this_week)} this week` : undefined}
          color="yellow"
          loading={loading}
        />
        <KPICard
          title="Total Cost"
          value={summary ? formatCurrency(summary.costs.total_usd) : '-'}
          subtitle={summary ? `${formatCurrency(summary.costs.today_usd)} today` : undefined}
          color="purple"
          loading={loading}
        />
      </KPIGrid>

      {/* Detailed Breakdown */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Debate Activity */}
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <h4 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3 flex items-center gap-2">
            <span>!</span> DEBATE ACTIVITY
          </h4>
          <div className="space-y-1">
            <KPIMiniCard label="Today" value={summary?.debates.today ?? 0} color="green" />
            <KPIMiniCard label="This Week" value={summary?.debates.this_week ?? 0} color="cyan" />
            <KPIMiniCard
              label="This Month"
              value={summary?.debates.this_month ?? 0}
              color="yellow"
            />
          </div>
        </div>

        {/* Cost Breakdown */}
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <h4 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3 flex items-center gap-2">
            <span>$</span> COST BREAKDOWN
          </h4>
          <div className="space-y-1">
            <KPIMiniCard
              label="Today"
              value={summary ? formatCurrency(summary.costs.today_usd) : '-'}
              color="green"
            />
            <KPIMiniCard
              label="This Week"
              value={summary ? formatCurrency(summary.costs.this_week_usd) : '-'}
              color="cyan"
            />
            <KPIMiniCard
              label="This Month"
              value={summary ? formatCurrency(summary.costs.this_month_usd) : '-'}
              color="yellow"
            />
          </div>
        </div>

        {/* Consensus Metrics */}
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <h4 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3 flex items-center gap-2">
            <span>%</span> CONSENSUS
          </h4>
          <div className="space-y-1">
            <KPIMiniCard
              label="Consensus Rate"
              value={summary ? `${(summary.consensus.rate * 100).toFixed(0)}%` : '-'}
              color={
                summary && summary.consensus.rate >= 0.8
                  ? 'green'
                  : summary && summary.consensus.rate >= 0.6
                    ? 'yellow'
                    : 'red'
              }
            />
            <KPIMiniCard
              label="Avg Confidence"
              value={summary ? `${(summary.consensus.avg_confidence * 100).toFixed(0)}%` : '-'}
              color="cyan"
            />
            <KPIMiniCard
              label="Avg Time"
              value={summary ? `${summary.consensus.avg_time_seconds.toFixed(0)}s` : '-'}
              color="yellow"
            />
          </div>
        </div>
      </div>

      {/* Forecast Section */}
      {forecast && (
        <div className="bg-[var(--surface)] border border-[var(--border)] p-4">
          <h4 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3 flex items-center gap-2">
            <span>{getTrendIcon(forecast.trend)}</span> MONTHLY FORECAST
            <span className="text-[var(--text-muted)]">
              ({(forecast.confidence * 100).toFixed(0)}% confidence)
            </span>
          </h4>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="text-center">
              <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">
                Projected Debates
              </div>
              <div className="text-lg font-theme-data font-bold text-[var(--acid-green)]">
                {formatNumber(forecast.projected_monthly_debates)}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">
                Projected Tokens
              </div>
              <div className="text-lg font-theme-data font-bold text-[var(--acid-cyan)]">
                {formatNumber(forecast.projected_monthly_tokens)}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">
                Projected Cost
              </div>
              <div className="text-lg font-theme-data font-bold text-yellow-400">
                {formatCurrency(forecast.projected_monthly_cost_usd)}
              </div>
            </div>
            <div className="text-center">
              <div className="text-xs font-theme-data text-[var(--text-muted)] mb-1">
                Growth Rate
              </div>
              <div
                className={`text-lg font-theme-data font-bold ${getTrendColor(forecast.trend) === 'green' ? 'text-green-400' : getTrendColor(forecast.trend) === 'red' ? 'text-red-400' : 'text-yellow-400'}`}
              >
                {forecast.growth_rate_percent >= 0 ? '+' : ''}
                {forecast.growth_rate_percent.toFixed(1)}%
              </div>
            </div>
          </div>
          {forecast.recommendations.length > 0 && (
            <div className="mt-4 pt-4 border-t border-[var(--border)]">
              <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
                RECOMMENDATIONS:
              </div>
              <ul className="space-y-1">
                {forecast.recommendations.slice(0, 3).map((rec, idx) => (
                  <li key={idx} className="text-xs font-theme-data text-[var(--acid-green)]">
                    {'>'} {rec}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default UsageBreakdown;
