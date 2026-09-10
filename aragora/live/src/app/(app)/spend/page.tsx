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
import {
  useSpendDashboardSummary,
  useSpendDashboardTrends,
  useSpendDashboardByAgent,
  useSpendDashboardByDecision,
  useSpendDashboardBudget,
} from '@/hooks/useSpendAnalytics';

// ============================================================================
// Helpers
// ============================================================================

function formatUsd(value: number | string): string {
  const num = typeof value === 'string' ? parseFloat(value) : value;
  if (isNaN(num)) return '$0.00';
  if (num >= 1000) {
    return `$${(num / 1000).toFixed(1)}K`;
  }
  return `$${num.toFixed(2)}`;
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
  value: 'daily' | 'weekly' | 'monthly';
  onChange: (v: 'daily' | 'weekly' | 'monthly') => void;
}) {
  const options: Array<'daily' | 'weekly' | 'monthly'> = ['daily', 'weekly', 'monthly'];

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

/** Budget utilization gauge */
function BudgetGauge({
  utilization,
  remaining,
  total,
  forecastDays,
}: {
  utilization: number;
  remaining: number;
  total: number;
  forecastDays: number | null;
}) {
  const barColor =
    utilization >= 90
      ? 'bg-[var(--crimson)]'
      : utilization >= 70
        ? 'bg-acid-yellow'
        : 'bg-[var(--accent)]';

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
        {'>'} BUDGET UTILIZATION
      </h3>

      {/* Gauge bar */}
      <div className="mb-4">
        <div className="flex justify-between text-xs font-theme-data text-text-muted mb-1">
          <span>0%</span>
          <span>{utilization.toFixed(1)}%</span>
          <span>100%</span>
        </div>
        <div className="w-full h-4 bg-surface rounded overflow-hidden border border-[var(--accent)]/20">
          <div
            className={`h-full ${barColor} transition-all duration-500`}
            style={{ width: `${Math.min(utilization, 100)}%` }}
          />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-3 gap-4">
        <div className="text-center">
          <div className="text-text-muted text-[10px] font-theme-data">BUDGET</div>
          <div className="text-[var(--accent)] font-theme-data text-sm">{formatUsd(total)}</div>
        </div>
        <div className="text-center">
          <div className="text-text-muted text-[10px] font-theme-data">REMAINING</div>
          <div className="text-[var(--acid-cyan)] font-theme-data text-sm">
            {formatUsd(remaining)}
          </div>
        </div>
        <div className="text-center">
          <div className="text-text-muted text-[10px] font-theme-data">DAYS LEFT</div>
          <div className="text-purple-400 font-theme-data text-sm">
            {forecastDays !== null ? `~${forecastDays}d` : '--'}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Decision cost table */
function DecisionCostTable({
  decisions,
}: {
  decisions: Array<{ debate_id: string; cost_usd: string }>;
}) {
  if (decisions.length === 0) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
          {'>'} COST PER DECISION
        </h3>
        <p className="text-text-muted font-theme-data text-sm text-center py-4">
          No decision costs recorded yet.
        </p>
      </div>
    );
  }

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">{'>'} COST PER DECISION</h3>
      <div className="overflow-x-auto">
        <table className="w-full font-theme-data text-sm">
          <thead>
            <tr className="border-b border-[var(--accent)]/30">
              <th className="py-2 px-3 text-[var(--accent)] text-left">Debate ID</th>
              <th className="py-2 px-3 text-[var(--accent)] text-right">Cost (USD)</th>
            </tr>
          </thead>
          <tbody>
            {decisions.map((d, i) => (
              <tr
                key={d.debate_id}
                className={`border-b border-[var(--accent)]/10 ${
                  i % 2 === 0 ? 'bg-[var(--accent)]/5' : ''
                }`}
              >
                <td className="py-2 px-3 text-[var(--acid-cyan)] truncate max-w-[200px]">
                  {d.debate_id}
                </td>
                <td className="py-2 px-3 text-right text-text">{formatUsd(d.cost_usd)}</td>
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

export default function SpendDashboardPage() {
  const [period, setPeriod] = useState<'daily' | 'weekly' | 'monthly'>('daily');
  const [days, _setDays] = useState(30);

  // Fetch data from all 5 endpoints
  const { summary, isLoading: summaryLoading, error: summaryError } = useSpendDashboardSummary();
  const { trends, isLoading: trendsLoading } = useSpendDashboardTrends('default', period, days);
  const { agentBreakdown, isLoading: agentLoading } = useSpendDashboardByAgent();
  const { decisionBreakdown, isLoading: decisionLoading } = useSpendDashboardByDecision();
  const { budget, isLoading: budgetLoading } = useSpendDashboardBudget();

  const _isLoading =
    summaryLoading || trendsLoading || agentLoading || decisionLoading || budgetLoading;

  // Transform trend data_points into DataPoint[] for TrendChart
  const timelineData: DataPoint[] = useMemo(() => {
    if (!trends?.data_points) return [];
    return trends.data_points.map((p) => ({
      label: p.date ? p.date.split('-').slice(1).join('/') : '',
      value: p.amount_usd ?? 0,
      date: p.date,
    }));
  }, [trends]);

  // Transform agent breakdown into CostCategory[] for donut chart
  const agentCategories: CostCategory[] = useMemo(() => {
    if (!agentBreakdown?.agents) return [];
    return agentBreakdown.agents.map((a) => ({
      name: a.agent_name,
      cost: parseFloat(a.cost_usd) || 0,
      percentage: a.percentage,
    }));
  }, [agentBreakdown]);

  const agentTotal = useMemo(
    () => agentCategories.reduce((s, c) => s + c.cost, 0),
    [agentCategories],
  );

  // Summary values
  const totalSpend = summary?.total_spend_usd ?? '0.00';
  const totalCalls = summary?.total_api_calls ?? 0;
  const totalTokens = summary?.total_tokens ?? 0;
  const utilizationPct = summary?.utilization_pct ?? 0;
  const trendDir = summary?.trend_direction ?? 'stable';
  const avgCostPerDecision = summary?.avg_cost_per_decision ?? 0;

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
                {'>'} SPEND DASHBOARD
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Budget tracking, agent costs, and decision spend visibility.
              </p>
            </div>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>

          {/* Error banner */}
          {summaryError && (
            <div className="mb-6 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded p-4 text-[var(--crimson)] text-sm font-theme-data">
              Failed to load spend dashboard. The server may be unavailable.
            </div>
          )}

          {/* ---- Overview Cards ---- */}
          <PanelErrorBoundary panelName="Spend Summary">
            <section className="mb-6">
              <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">{'>'} SUMMARY</h2>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  title="Total Spend"
                  value={formatUsd(totalSpend)}
                  subtitle={`${totalCalls} API calls`}
                  color="green"
                  loading={summaryLoading}
                  icon="$"
                />
                <MetricCard
                  title="Total Tokens"
                  value={
                    totalTokens >= 1000000
                      ? `${(totalTokens / 1000000).toFixed(1)}M`
                      : totalTokens >= 1000
                        ? `${(totalTokens / 1000).toFixed(0)}K`
                        : String(totalTokens)
                  }
                  subtitle="input + output"
                  color="cyan"
                  loading={summaryLoading}
                  icon="T"
                />
                <MetricCard
                  title="Trend"
                  value={trendDir}
                  subtitle={`${utilizationPct}% budget used`}
                  color={trendColor(trendDir)}
                  loading={summaryLoading}
                  icon={trendIcon(trendDir)}
                />
                <MetricCard
                  title="Avg Cost / Decision"
                  value={formatUsd(avgCostPerDecision)}
                  subtitle="per API call"
                  color="yellow"
                  loading={summaryLoading}
                  icon="="
                />
              </div>
            </section>
          </PanelErrorBoundary>

          {/* ---- Spend Timeline ---- */}
          <PanelErrorBoundary panelName="Spend Trends">
            <section className="mb-6">
              <TrendChart
                title={`> SPEND OVER TIME (${period})`}
                data={timelineData}
                type="area"
                color="green"
                loading={trendsLoading}
                showTimeRangeSelector={false}
                height={280}
                formatValue={(v) => formatUsd(v)}
              />
            </section>
          </PanelErrorBoundary>

          {/* ---- Agent Breakdown + Budget Gauge ---- */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <PanelErrorBoundary panelName="Agent Cost Breakdown">
              <CostBreakdown
                data={agentCategories}
                totalCost={agentTotal}
                title="SPEND BY AGENT"
                subtitle={`total: ${formatUsd(agentBreakdown?.total_usd ?? '0')}`}
                loading={agentLoading}
                showTokens={false}
              />
            </PanelErrorBoundary>

            <PanelErrorBoundary panelName="Budget Utilization">
              <BudgetGauge
                utilization={budget?.utilization_pct ?? 0}
                remaining={budget?.total_remaining_usd ?? 0}
                total={budget?.total_budget_usd ?? 0}
                forecastDays={budget?.forecast_exhaustion_days ?? null}
              />
            </PanelErrorBoundary>
          </div>

          {/* ---- Decision Cost Table ---- */}
          <PanelErrorBoundary panelName="Decision Costs">
            <section className="mb-6">
              <DecisionCostTable decisions={decisionBreakdown?.decisions ?? []} />
            </section>
          </PanelErrorBoundary>

          {/* Footer */}
          <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
            <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
            <p className="text-text-muted">{'>'} ARAGORA // SPEND DASHBOARD</p>
          </footer>
        </div>
      </main>
    </>
  );
}
