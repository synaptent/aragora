'use client';

import { useState, useMemo } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import {
  MetricCard,
  TrendChart,
  CostBreakdown,
  type DataPoint,
  type CostCategory,
} from '@/components/analytics';
import { useSpendAnalytics, type SpendPeriod, type SpendAnomaly } from '@/hooks/useSpendAnalytics';

// ============================================================================
// Helpers
// ============================================================================

function formatUsd(value: number): string {
  if (value >= 1000) {
    return `$${(value / 1000).toFixed(1)}K`;
  }
  return `$${value.toFixed(2)}`;
}

function trendIcon(trend: string): string {
  if (trend === 'increasing') return '^';
  if (trend === 'decreasing') return 'v';
  return '~';
}

function trendColor(trend: string): 'green' | 'yellow' | 'red' {
  if (trend === 'increasing') return 'red';
  if (trend === 'decreasing') return 'green';
  return 'yellow';
}

// ============================================================================
// Sub-components
// ============================================================================

function PeriodSelector({
  value,
  onChange,
}: {
  value: SpendPeriod;
  onChange: (v: SpendPeriod) => void;
}) {
  const options: SpendPeriod[] = ['7d', '14d', '30d', '60d', '90d'];

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

/** Anomaly alert rows */
function AnomalyAlerts({ anomalies }: { anomalies: SpendAnomaly[] }) {
  if (anomalies.length === 0) return null;

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--acid-yellow)] mb-3">
        {'>'} SPEND ANOMALIES
      </h3>
      <div className="space-y-2">
        {anomalies.map((a) => (
          <div
            key={a.date}
            className={`flex items-center justify-between p-3 border rounded font-theme-data text-xs ${
              a.severity === 'critical'
                ? 'border-[var(--crimson)]/40 bg-[var(--crimson)]/5'
                : 'border-acid-yellow/40 bg-acid-yellow/5'
            }`}
          >
            <div className="flex items-center gap-3">
              <span
                className={
                  a.severity === 'critical' ? 'text-[var(--crimson)]' : 'text-[var(--acid-yellow)]'
                }
              >
                {a.severity === 'critical' ? '!!' : '!'}
              </span>
              <span className="text-text">{a.date}</span>
              <span className="text-text-muted">{a.description}</span>
            </div>
            <div className="flex items-center gap-4">
              <span className="text-text-muted">expected {formatUsd(a.expected_usd)}</span>
              <span
                className={
                  a.severity === 'critical' ? 'text-[var(--crimson)]' : 'text-[var(--acid-yellow)]'
                }
              >
                actual {formatUsd(a.actual_usd)}
              </span>
              <span className="text-text-muted">z={a.z_score.toFixed(1)}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Sortable cost table for agent or provider breakdowns */
function SpendTable({
  title,
  data,
  total,
}: {
  title: string;
  data: Record<string, number>;
  total: number;
}) {
  type SortKey = 'name' | 'cost' | 'pct';
  const [sortKey, setSortKey] = useState<SortKey>('cost');
  const [sortAsc, setSortAsc] = useState(false);

  const rows = useMemo(() => {
    const entries = Object.entries(data).map(([name, cost]) => ({
      name,
      cost,
      pct: total > 0 ? (cost / total) * 100 : 0,
    }));

    entries.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'string' && typeof bv === 'string')
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });

    return entries;
  }, [data, total, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const sortIndicator = (key: SortKey) => (sortKey === key ? (sortAsc ? ' ^' : ' v') : '');

  if (rows.length === 0) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
          {'>'} {title}
        </h3>
        <p className="text-text-muted font-theme-data text-sm text-center py-4">
          No spend data yet. Run debates to see cost breakdowns by provider and agent.
        </p>
      </div>
    );
  }

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
        {'>'} {title}
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full font-theme-data text-sm">
          <thead>
            <tr className="border-b border-[var(--accent)]/30">
              <th
                onClick={() => handleSort('name')}
                className="py-2 px-3 text-[var(--accent)] text-left cursor-pointer select-none hover:text-[var(--acid-cyan)] transition-colors"
              >
                Name{sortIndicator('name')}
              </th>
              <th
                onClick={() => handleSort('cost')}
                className="py-2 px-3 text-[var(--accent)] text-right cursor-pointer select-none hover:text-[var(--acid-cyan)] transition-colors"
              >
                Cost (USD){sortIndicator('cost')}
              </th>
              <th
                onClick={() => handleSort('pct')}
                className="py-2 px-3 text-[var(--accent)] text-right cursor-pointer select-none hover:text-[var(--acid-cyan)] transition-colors"
              >
                Share{sortIndicator('pct')}
              </th>
              <th className="py-2 px-3 text-[var(--accent)] text-right">Bar</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={row.name}
                className={`border-b border-[var(--accent)]/10 ${
                  i % 2 === 0 ? 'bg-[var(--accent)]/5' : ''
                }`}
              >
                <td className="py-2 px-3 text-[var(--acid-cyan)]">{row.name}</td>
                <td className="py-2 px-3 text-right text-text">{formatUsd(row.cost)}</td>
                <td className="py-2 px-3 text-right text-text-muted">{row.pct.toFixed(1)}%</td>
                <td className="py-2 px-3 text-right">
                  <div className="w-24 h-2 bg-surface rounded overflow-hidden ml-auto">
                    <div
                      className="h-full bg-[var(--accent)]/60 rounded"
                      style={{ width: `${Math.min(row.pct, 100)}%` }}
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

// ============================================================================
// Main Page
// ============================================================================

export default function SpendAnalyticsPage() {
  const [period, setPeriod] = useState<SpendPeriod>('30d');

  const { analytics, isLoading, error } = useSpendAnalytics(period);

  // Transform trend points into DataPoint[] for the TrendChart
  const timelineData: DataPoint[] = useMemo(() => {
    if (!analytics?.trend?.points) return [];
    return analytics.trend.points.map((p) => ({
      label: p.date.split('-').slice(1).join('/'), // MM/DD
      value: p.cost_usd,
      date: p.date,
    }));
  }, [analytics]);

  // Transform by_agent into CostCategory[] for the donut chart
  const agentCategories: CostCategory[] = useMemo(() => {
    if (!analytics?.by_agent) return [];
    const total = Object.values(analytics.by_agent).reduce((s, c) => s + c, 0);
    return Object.entries(analytics.by_agent)
      .sort(([, a], [, b]) => b - a)
      .map(([name, cost]) => ({ name, cost, percentage: total > 0 ? (cost / total) * 100 : 0 }));
  }, [analytics]);

  const agentTotal = useMemo(
    () => agentCategories.reduce((s, c) => s + c.cost, 0),
    [agentCategories],
  );

  // Derive MTD (month-to-date) total from trend
  const mtdTotal = analytics?.trend?.total_usd ?? 0;
  const dailyAvg = analytics?.trend?.avg_daily_usd ?? 0;
  const forecast = analytics?.forecast;
  const projectedMonthly = forecast?.projected_total_usd ?? 0;

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
                {'>'} SPEND ANALYTICS
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Actionable cost visibility across providers, agents, and time.
              </p>
            </div>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>

          {/* Error banner */}
          {error && (
            <div className="mb-6 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded p-4 text-[var(--crimson)] text-sm font-theme-data">
              Failed to load spend analytics. The server may be unavailable.
            </div>
          )}

          {/* ---- Overview Cards ---- */}
          <PanelErrorBoundary panelName="Spend Overview">
            <section className="mb-6">
              <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">{'>'} OVERVIEW</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  title="Total Spend (Period)"
                  value={formatUsd(mtdTotal)}
                  subtitle={`${period} period`}
                  color="green"
                  loading={isLoading}
                  icon="$"
                />
                <MetricCard
                  title="Daily Average"
                  value={formatUsd(dailyAvg)}
                  subtitle="avg per day"
                  color="cyan"
                  loading={isLoading}
                  icon="~"
                />
                <MetricCard
                  title="Projected Monthly"
                  value={formatUsd(projectedMonthly)}
                  subtitle={
                    forecast
                      ? `${forecast.trend} (${(forecast.confidence * 100).toFixed(0)}% conf)`
                      : 'forecast'
                  }
                  color={forecast ? trendColor(forecast.trend) : 'yellow'}
                  loading={isLoading}
                  icon={forecast ? trendIcon(forecast.trend) : '?'}
                />
                <MetricCard
                  title="Anomalies Detected"
                  value={analytics?.anomalies?.length ?? 0}
                  subtitle={
                    analytics?.anomalies?.length
                      ? `${analytics.anomalies.filter((a) => a.severity === 'critical').length} critical`
                      : 'none'
                  }
                  color={(analytics?.anomalies?.length ?? 0) > 0 ? 'red' : 'green'}
                  loading={isLoading}
                  icon="!"
                />
              </div>
            </section>
          </PanelErrorBoundary>

          {/* ---- Spend Timeline ---- */}
          <PanelErrorBoundary panelName="Spend Timeline">
            <section className="mb-6">
              <TrendChart
                title={`> DAILY SPEND (${period})`}
                data={timelineData}
                type="area"
                color="green"
                loading={isLoading}
                showTimeRangeSelector={false}
                height={280}
                formatValue={(v) => formatUsd(v)}
              />
            </section>
          </PanelErrorBoundary>

          {/* ---- Breakdowns row ---- */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            {/* Spend by Agent donut */}
            <PanelErrorBoundary panelName="Spend by Agent Chart">
              <CostBreakdown
                data={agentCategories}
                totalCost={agentTotal}
                title="SPEND BY AGENT"
                subtitle={`${period} period`}
                loading={isLoading}
                showTokens={false}
              />
            </PanelErrorBoundary>

            {/* Spend by Provider donut */}
            <PanelErrorBoundary panelName="Spend by Provider Chart">
              <CostBreakdown
                data={
                  analytics?.by_provider
                    ? Object.entries(analytics.by_provider)
                        .sort(([, a], [, b]) => b - a)
                        .map(([name, cost]) => ({
                          name,
                          cost,
                          percentage: mtdTotal > 0 ? (cost / mtdTotal) * 100 : 0,
                        }))
                    : []
                }
                totalCost={
                  analytics?.by_provider
                    ? Object.values(analytics.by_provider).reduce((s, c) => s + c, 0)
                    : 0
                }
                title="SPEND BY PROVIDER"
                subtitle={`${period} period`}
                loading={isLoading}
                showTokens={false}
              />
            </PanelErrorBoundary>
          </div>

          {/* ---- Sortable Tables ---- */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <PanelErrorBoundary panelName="Agent Cost Table">
              <SpendTable
                title="COST BY AGENT (TABLE)"
                data={analytics?.by_agent ?? {}}
                total={agentTotal}
              />
            </PanelErrorBoundary>

            <PanelErrorBoundary panelName="Provider Cost Table">
              <SpendTable
                title="COST BY PROVIDER (TABLE)"
                data={analytics?.by_provider ?? {}}
                total={
                  analytics?.by_provider
                    ? Object.values(analytics.by_provider).reduce((s, c) => s + c, 0)
                    : 0
                }
              />
            </PanelErrorBoundary>
          </div>

          {/* ---- Forecast Details ---- */}
          {forecast && !isLoading && (
            <PanelErrorBoundary panelName="Forecast">
              <section className="mb-6">
                <div className="card p-4">
                  <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
                    {'>'} COST FORECAST (next {forecast.forecast_days} days)
                  </h3>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="text-center">
                      <div className="text-text-muted text-[10px] font-theme-data">
                        PROJECTED TOTAL
                      </div>
                      <div className="text-[var(--accent)] font-theme-data text-lg">
                        {formatUsd(forecast.projected_total_usd)}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-text-muted text-[10px] font-theme-data">DAILY AVG</div>
                      <div className="text-[var(--acid-cyan)] font-theme-data text-lg">
                        {formatUsd(forecast.projected_daily_avg_usd)}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-text-muted text-[10px] font-theme-data">TREND</div>
                      <div
                        className={`font-theme-data text-lg ${
                          forecast.trend === 'increasing'
                            ? 'text-[var(--crimson)]'
                            : forecast.trend === 'decreasing'
                              ? 'text-[var(--accent)]'
                              : 'text-[var(--acid-yellow)]'
                        }`}
                      >
                        {forecast.trend}
                      </div>
                    </div>
                    <div className="text-center">
                      <div className="text-text-muted text-[10px] font-theme-data">CONFIDENCE</div>
                      <div className="text-purple-400 font-theme-data text-lg">
                        {(forecast.confidence * 100).toFixed(0)}%
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            </PanelErrorBoundary>
          )}

          {/* ---- Anomalies ---- */}
          {analytics?.anomalies && analytics.anomalies.length > 0 && (
            <PanelErrorBoundary panelName="Anomalies">
              <section className="mb-6">
                <AnomalyAlerts anomalies={analytics.anomalies} />
              </section>
            </PanelErrorBoundary>
          )}

          {/* Footer */}
          <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
            <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
            <p className="text-text-muted">{'>'} ARAGORA // SPEND ANALYTICS DASHBOARD</p>
          </footer>
        </div>
      </main>
    </>
  );
}
