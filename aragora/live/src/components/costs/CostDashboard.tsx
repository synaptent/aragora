'use client';

import { useState } from 'react';
import { CostBreakdownChart } from './CostBreakdownChart';
import { BudgetAlerts } from './BudgetAlerts';
import { UsageTimeline } from './UsageTimeline';
import { OptimizationRecommendations } from './OptimizationRecommendations';
import { EfficiencyMetrics } from './EfficiencyMetrics';
import { BudgetForecast } from './BudgetForecast';
import {
  useCosts,
  useSpendTrend,
  useAgentCostBreakdown,
  useModelCostBreakdown,
  useDebateCostBreakdown,
  useBudgetUtilization,
  type TimeRange,
} from '@/hooks/useCosts';

type TabView = 'overview' | 'analytics' | 'recommendations' | 'efficiency' | 'forecast';

export function CostDashboard() {
  const [timeRange, setTimeRange] = useState<TimeRange>('7d');
  const [activeTab, setActiveTab] = useState<TabView>('overview');

  const { costData, isLoading, error, dismissAlert, refresh } = useCosts(timeRange);

  // Spend analytics hooks
  const { trend: spendTrend, isLoading: trendLoading } = useSpendTrend(timeRange);
  const { agentBreakdown, isLoading: agentLoading } = useAgentCostBreakdown();
  const { modelBreakdown, isLoading: modelLoading } = useModelCostBreakdown();
  const { debateBreakdown, isLoading: debateLoading } = useDebateCostBreakdown();
  const { utilization, isLoading: utilizationLoading } = useBudgetUtilization();

  if (isLoading || !costData) {
    return (
      <div className="animate-pulse space-y-6">
        <div className="h-8 bg-[var(--surface)] rounded w-1/3" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 bg-[var(--surface)] rounded" />
          ))}
        </div>
        <div className="h-64 bg-[var(--surface)] rounded" />
      </div>
    );
  }

  const budgetUsagePercent = (costData.totalCost / costData.budget) * 100;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-theme-data text-[var(--acid-green)]">
            {'>'} SPEND ANALYTICS
          </h1>
          <p className="text-sm text-[var(--text-muted)] mt-1">
            Monitor and optimize your AI spend across debates, agents, and models
          </p>
        </div>
        <div className="flex items-center gap-2">
          <TimeRangeSelector value={timeRange} onChange={setTimeRange} />
          <button
            onClick={refresh}
            disabled={isLoading}
            className="px-3 py-2 text-sm font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] border border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 transition-colors disabled:opacity-50"
          >
            {isLoading ? 'Loading...' : 'Refresh'}
          </button>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="flex border-b border-[var(--border)]">
        {(['overview', 'analytics', 'recommendations', 'efficiency', 'forecast'] as const).map(
          (tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-theme-data transition-colors ${
                activeTab === tab
                  ? 'text-[var(--acid-green)] border-b-2 border-[var(--acid-green)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ),
        )}
      </div>

      {/* Tab Content */}
      {activeTab === 'overview' && (
        <>
          {/* Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <SummaryCard
              label="Total Cost"
              value={`$${costData.totalCost.toFixed(2)}`}
              subtext={`of $${costData.budget.toFixed(2)} budget`}
              color="text-[var(--acid-green)]"
              progress={budgetUsagePercent}
            />
            <SummaryCard
              label="Tokens Used"
              value={formatNumber(costData.tokensUsed)}
              subtext="input + output"
              color="text-[var(--acid-cyan)]"
            />
            <SummaryCard
              label="API Calls"
              value={formatNumber(costData.apiCalls)}
              subtext="total requests"
              color="text-purple-400"
            />
            <SummaryCard
              label="Avg Cost/Call"
              value={`$${((costData.totalCost / costData.apiCalls) * 1000).toFixed(4)}`}
              subtext="per 1K calls"
              color="text-yellow-400"
            />
          </div>

          {/* Budget Progress */}
          <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
                {'>'} BUDGET PROGRESS
              </h3>
              <span
                className={`text-sm font-theme-data ${
                  budgetUsagePercent >= 90
                    ? 'text-red-400'
                    : budgetUsagePercent >= 75
                      ? 'text-yellow-400'
                      : 'text-green-400'
                }`}
              >
                {budgetUsagePercent.toFixed(1)}% used
              </span>
            </div>
            <div className="h-4 bg-[var(--bg)] rounded-full overflow-hidden">
              <div
                className={`h-full transition-all duration-500 ${
                  budgetUsagePercent >= 90
                    ? 'bg-red-500'
                    : budgetUsagePercent >= 75
                      ? 'bg-yellow-500'
                      : 'bg-[var(--acid-green)]'
                }`}
                style={{ width: `${Math.min(budgetUsagePercent, 100)}%` }}
              />
            </div>
            <div className="flex justify-between mt-2 text-xs text-[var(--text-muted)]">
              <span>$0</span>
              <span>${(costData.budget * 0.5).toFixed(0)}</span>
              <span>${costData.budget.toFixed(0)}</span>
            </div>
          </div>

          {/* Error Display */}
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded p-4 text-red-400 text-sm font-theme-data">
              Error loading cost data: {error.message}
            </div>
          )}

          {/* Alerts */}
          {costData.alerts.length > 0 && (
            <BudgetAlerts alerts={costData.alerts} onDismiss={dismissAlert} />
          )}

          {/* Charts Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            {/* Cost by Provider */}
            <CostBreakdownChart
              title="Cost by Provider"
              data={costData.costByProvider}
              colors={['#00ff9d', '#00d4ff', '#ff6b6b', '#ffd93d']}
            />

            {/* Cost by Feature */}
            <CostBreakdownChart
              title="Cost by Feature"
              data={costData.costByFeature}
              colors={['#a855f7', '#3b82f6', '#22c55e', '#f59e0b']}
            />
          </div>

          {/* Usage Timeline */}
          <UsageTimeline data={costData.dailyCosts} />

          {/* Last Updated */}
          <div className="text-xs text-[var(--text-muted)] text-center">
            Last updated: {new Date(costData.lastUpdated).toLocaleString()}
          </div>
        </>
      )}

      {activeTab === 'analytics' && (
        <>
          {/* Budget Utilization Gauge */}
          <BudgetUtilizationGauge utilization={utilization} loading={utilizationLoading} />

          {/* Spend Trend Chart */}
          <SpendTrendChart trend={spendTrend} loading={trendLoading} />

          {/* Agent and Model Breakdown */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <AgentBreakdownPanel data={agentBreakdown} loading={agentLoading} />
            <ModelBreakdownPanel data={modelBreakdown} loading={modelLoading} />
          </div>

          {/* Recent Debates with Cost */}
          <RecentDebatesPanel data={debateBreakdown} loading={debateLoading} />
        </>
      )}

      {activeTab === 'recommendations' && <OptimizationRecommendations />}

      {activeTab === 'efficiency' && <EfficiencyMetrics timeRange={timeRange} />}

      {activeTab === 'forecast' && <BudgetForecast />}
    </div>
  );
}

// ============================================================================
// Spend Analytics Sub-components
// ============================================================================

import type {
  SpendTrend,
  AgentCostBreakdownData,
  ModelCostBreakdownData,
  DebateCostBreakdownData,
  BudgetUtilization,
} from '@/hooks/useCosts';

function BudgetUtilizationGauge({
  utilization,
  loading,
}: {
  utilization: BudgetUtilization | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6 animate-pulse">
        <div className="h-6 bg-[var(--bg)] rounded w-1/3 mb-4" />
        <div className="h-32 bg-[var(--bg)] rounded" />
      </div>
    );
  }

  if (!utilization || utilization.budget_usd === 0) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
          {'>'} BUDGET UTILIZATION
        </h3>
        <p className="text-sm text-[var(--text-muted)]">No budget configured for this workspace.</p>
      </div>
    );
  }

  const pct = utilization.utilization_pct;
  const gaugeColor = pct >= 90 ? '#ef4444' : pct >= 75 ? '#eab308' : '#00ff9d';
  const circumference = 2 * Math.PI * 60;
  const strokeDashoffset = circumference - (Math.min(pct, 100) / 100) * circumference;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6">
      <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">
        {'>'} BUDGET UTILIZATION
      </h3>
      <div className="flex items-center gap-8">
        {/* Gauge */}
        <div className="relative w-36 h-36 flex-shrink-0">
          <svg className="w-full h-full transform -rotate-90" viewBox="0 0 140 140">
            <circle cx="70" cy="70" r="60" fill="none" stroke="var(--bg)" strokeWidth="12" />
            <circle
              cx="70"
              cy="70"
              r="60"
              fill="none"
              stroke={gaugeColor}
              strokeWidth="12"
              strokeLinecap="round"
              strokeDasharray={circumference}
              strokeDashoffset={strokeDashoffset}
              className="transition-all duration-700"
            />
          </svg>
          <div className="absolute inset-0 flex items-center justify-center flex-col">
            <span className="text-2xl font-theme-data font-bold" style={{ color: gaugeColor }}>
              {pct.toFixed(0)}%
            </span>
            <span className="text-xs text-[var(--text-muted)]">used</span>
          </div>
        </div>

        {/* Details */}
        <div className="flex-1 grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs text-[var(--text-muted)]">Monthly Budget</div>
            <div className="text-lg font-theme-data text-[var(--text)]">
              ${utilization.budget_usd.toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-xs text-[var(--text-muted)]">Spent</div>
            <div className="text-lg font-theme-data text-[var(--acid-green)]">
              ${utilization.spent_usd.toFixed(2)}
            </div>
          </div>
          <div>
            <div className="text-xs text-[var(--text-muted)]">Remaining</div>
            <div className="text-lg font-theme-data text-[var(--text)]">
              ${utilization.remaining_usd.toFixed(2)}
            </div>
          </div>
          {utilization.daily_budget_usd !== null && (
            <div>
              <div className="text-xs text-[var(--text-muted)]">Daily Budget</div>
              <div className="text-lg font-theme-data text-[var(--text)]">
                ${utilization.daily_budget_usd.toFixed(2)}
                <span className="text-xs text-[var(--text-muted)] ml-1">
                  ({utilization.daily_utilization_pct.toFixed(0)}% used)
                </span>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function SpendTrendChart({ trend, loading }: { trend: SpendTrend | null; loading: boolean }) {
  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6 animate-pulse">
        <div className="h-6 bg-[var(--bg)] rounded w-1/4 mb-4" />
        <div className="h-48 bg-[var(--bg)] rounded" />
      </div>
    );
  }

  if (!trend || trend.points.length === 0) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-4">{'>'} COST TREND</h3>
        <p className="text-sm text-[var(--text-muted)]">No spend data available for this period.</p>
      </div>
    );
  }

  const maxCost = Math.max(...trend.points.map((p) => p.cost_usd), 0.01);
  const chartHeight = 160;

  // Build SVG polyline points
  const stepX = trend.points.length > 1 ? 100 / (trend.points.length - 1) : 50;
  const linePoints = trend.points
    .map((p, i) => {
      const x = i * stepX;
      const y = 100 - (p.cost_usd / maxCost) * 100;
      return `${x},${y}`;
    })
    .join(' ');

  // Build fill polygon (close to bottom)
  const fillPoints = `0,100 ${linePoints} ${(trend.points.length - 1) * stepX},100`;

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} COST TREND</h3>
        <div className="flex items-center gap-4 text-xs font-theme-data text-[var(--text-muted)]">
          <span>
            Total: <span className="text-[var(--acid-green)]">${trend.total_usd.toFixed(2)}</span>
          </span>
          <span>
            Avg/day:{' '}
            <span className="text-[var(--acid-cyan)]">${trend.avg_daily_usd.toFixed(2)}</span>
          </span>
        </div>
      </div>

      {/* SVG Line Chart */}
      <div style={{ height: chartHeight }} className="relative">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="w-full h-full">
          {/* Grid lines */}
          {[0, 25, 50, 75].map((y) => (
            <line
              key={y}
              x1="0"
              y1={y}
              x2="100"
              y2={y}
              stroke="var(--border)"
              strokeWidth="0.3"
              strokeDasharray="2,2"
            />
          ))}

          {/* Average line */}
          <line
            x1="0"
            y1={100 - (trend.avg_daily_usd / maxCost) * 100}
            x2="100"
            y2={100 - (trend.avg_daily_usd / maxCost) * 100}
            stroke="#eab308"
            strokeWidth="0.4"
            strokeDasharray="3,3"
          />

          {/* Fill area */}
          <polygon points={fillPoints} fill="url(#trendGradient)" opacity="0.3" />

          {/* Line */}
          <polyline
            points={linePoints}
            fill="none"
            stroke="#00ff9d"
            strokeWidth="0.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />

          {/* Data points */}
          {trend.points.map((p, i) => {
            const x = i * stepX;
            const y = 100 - (p.cost_usd / maxCost) * 100;
            return <circle key={p.date} cx={x} cy={y} r="1" fill="#00ff9d" />;
          })}

          <defs>
            <linearGradient id="trendGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#00ff9d" stopOpacity="0.4" />
              <stop offset="100%" stopColor="#00ff9d" stopOpacity="0" />
            </linearGradient>
          </defs>
        </svg>
      </div>

      {/* X-axis labels */}
      <div className="flex justify-between mt-2 text-xs text-[var(--text-muted)]">
        {trend.points.length > 0 && (
          <>
            <span>{formatDateLabel(trend.points[0].date)}</span>
            {trend.points.length > 2 && (
              <span>{formatDateLabel(trend.points[Math.floor(trend.points.length / 2)].date)}</span>
            )}
            <span>{formatDateLabel(trend.points[trend.points.length - 1].date)}</span>
          </>
        )}
      </div>

      {/* Y-axis labels */}
      <div className="absolute top-6 right-6 text-xs font-theme-data text-[var(--text-muted)]">
        max ${maxCost.toFixed(2)}
      </div>
    </div>
  );
}

function AgentBreakdownPanel({
  data,
  loading,
}: {
  data: AgentCostBreakdownData | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 animate-pulse">
        <div className="h-5 bg-[var(--bg)] rounded w-1/3 mb-4" />
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-6 bg-[var(--bg)] rounded" />
          ))}
        </div>
      </div>
    );
  }

  const agents = data?.agents ?? [];
  const colors = [
    '#00ff9d',
    '#00d4ff',
    '#a855f7',
    '#f59e0b',
    '#ef4444',
    '#ec4899',
    '#14b8a6',
    '#8b5cf6',
  ];

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} COST BY AGENT</h3>
        <span className="text-xs font-theme-data text-[var(--text-muted)]">
          {agents.length} agents
        </span>
      </div>

      {agents.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">No agent cost data available.</p>
      ) : (
        <div className="space-y-3">
          {agents.map((agent, index) => {
            const barColor = colors[index % colors.length];
            return (
              <div key={agent.name}>
                <div className="flex items-center justify-between text-xs mb-1">
                  <span className="text-[var(--text)]">{agent.name}</span>
                  <div className="flex items-center gap-2">
                    <span className="font-theme-data" style={{ color: barColor }}>
                      {agent.percentage.toFixed(1)}%
                    </span>
                    <span className="font-theme-data text-[var(--text-muted)]">
                      ${agent.cost_usd.toFixed(2)}
                    </span>
                  </div>
                </div>
                <div className="h-2 bg-[var(--bg)] rounded-full overflow-hidden">
                  <div
                    className="h-full transition-all duration-500 rounded-full"
                    style={{ width: `${agent.percentage}%`, backgroundColor: barColor }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ModelBreakdownPanel({
  data,
  loading,
}: {
  data: ModelCostBreakdownData | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 animate-pulse">
        <div className="h-5 bg-[var(--bg)] rounded w-1/3 mb-4" />
        <div className="h-32 bg-[var(--bg)] rounded" />
      </div>
    );
  }

  const models = data?.models ?? [];
  const total = data?.total_usd ?? 0;
  const colors = [
    '#00ff9d',
    '#00d4ff',
    '#a855f7',
    '#f59e0b',
    '#ef4444',
    '#ec4899',
    '#14b8a6',
    '#8b5cf6',
  ];

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} COST BY MODEL</h3>
        <span className="text-xs font-theme-data text-[var(--text-muted)]">
          {models.length} models
        </span>
      </div>

      {models.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">No model cost data available.</p>
      ) : (
        <>
          {/* Donut visualization */}
          <div className="flex items-center gap-4 mb-4">
            <div className="relative w-24 h-24 flex-shrink-0">
              {total > 0 && <MiniDonut data={models} colors={colors} />}
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="text-center">
                  <div className="text-sm font-theme-data text-[var(--text)]">
                    ${total.toFixed(0)}
                  </div>
                </div>
              </div>
            </div>

            <div className="flex-1 space-y-1">
              {models.slice(0, 5).map((model, index) => (
                <div key={model.name} className="flex items-center gap-2 text-xs">
                  <div
                    className="w-2 h-2 rounded-full flex-shrink-0"
                    style={{ backgroundColor: colors[index % colors.length] }}
                  />
                  <span className="text-[var(--text)] truncate flex-1">{model.name}</span>
                  <span className="font-theme-data text-[var(--text-muted)]">
                    ${model.cost_usd.toFixed(2)}
                  </span>
                </div>
              ))}
              {models.length > 5 && (
                <div className="text-xs text-[var(--text-muted)]">+{models.length - 5} more</div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function MiniDonut({
  data,
  colors,
}: {
  data: Array<{ name: string; cost_usd: number; percentage: number }>;
  colors: string[];
}) {
  const total = data.reduce((sum, d) => sum + d.cost_usd, 0);
  if (total === 0) return null;

  let cumulativePercent = 0;
  const stops: string[] = [];

  data.forEach((item, index) => {
    const percent = (item.cost_usd / total) * 100;
    const color = colors[index % colors.length];
    stops.push(`${color} ${cumulativePercent * 3.6}deg ${(cumulativePercent + percent) * 3.6}deg`);
    cumulativePercent += percent;
  });

  return (
    <div
      className="w-full h-full rounded-full"
      style={{
        background: `conic-gradient(${stops.join(', ')})`,
        mask: 'radial-gradient(farthest-side, transparent calc(100% - 10px), black calc(100% - 9px))',
        WebkitMask:
          'radial-gradient(farthest-side, transparent calc(100% - 10px), black calc(100% - 9px))',
      }}
    />
  );
}

function RecentDebatesPanel({
  data,
  loading,
}: {
  data: DebateCostBreakdownData | null;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 animate-pulse">
        <div className="h-5 bg-[var(--bg)] rounded w-1/3 mb-4" />
        <div className="space-y-2">
          {[1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-10 bg-[var(--bg)] rounded" />
          ))}
        </div>
      </div>
    );
  }

  const debates = data?.debates ?? [];

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
          {'>'} RECENT DEBATES WITH COST
        </h3>
        <span className="text-xs font-theme-data text-[var(--text-muted)]">
          {debates.length} debates | Total: ${(data?.total_usd ?? 0).toFixed(2)}
        </span>
      </div>

      {debates.length === 0 ? (
        <p className="text-sm text-[var(--text-muted)]">No debate cost data available.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs font-theme-data">
            <thead>
              <tr className="text-left text-[var(--text-muted)] border-b border-[var(--border)]">
                <th className="pb-2 pr-4">Debate ID</th>
                <th className="pb-2 pr-4 text-right">Cost</th>
                <th className="pb-2 pr-4 text-right">Agents</th>
                <th className="pb-2 pr-4 text-right">Calls</th>
                <th className="pb-2 text-right">Last Activity</th>
              </tr>
            </thead>
            <tbody>
              {debates.slice(0, 10).map((debate) => (
                <tr
                  key={debate.debate_id}
                  className="border-b border-[var(--border)]/50 hover:bg-[var(--bg)]/50 transition-colors"
                >
                  <td className="py-2 pr-4 text-[var(--acid-cyan)]">
                    {debate.debate_id.length > 20
                      ? debate.debate_id.slice(0, 20) + '...'
                      : debate.debate_id}
                  </td>
                  <td className="py-2 pr-4 text-right text-[var(--acid-green)]">
                    ${debate.cost_usd.toFixed(4)}
                  </td>
                  <td className="py-2 pr-4 text-right text-[var(--text)]">{debate.agent_count}</td>
                  <td className="py-2 pr-4 text-right text-[var(--text)]">{debate.call_count}</td>
                  <td className="py-2 text-right text-[var(--text-muted)]">
                    {formatDateLabel(debate.last_activity.split('T')[0])}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {debates.length > 10 && (
            <div className="text-xs text-[var(--text-muted)] text-center mt-3">
              Showing top 10 of {debates.length} debates
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Shared Components
// ============================================================================

interface TimeRangeSelectorProps {
  value: TimeRange;
  onChange: (value: TimeRange) => void;
}

function TimeRangeSelector({ value, onChange }: TimeRangeSelectorProps) {
  const ranges: Array<{ id: TimeRange; label: string }> = [
    { id: '24h', label: '24h' },
    { id: '7d', label: '7d' },
    { id: '30d', label: '30d' },
    { id: '90d', label: '90d' },
  ];

  return (
    <div className="flex border border-[var(--border)] rounded overflow-hidden">
      {ranges.map((range) => (
        <button
          key={range.id}
          onClick={() => onChange(range.id)}
          className={`px-3 py-1.5 text-xs font-theme-data transition-colors ${
            value === range.id
              ? 'bg-[var(--acid-green)] text-[var(--bg)]'
              : 'text-[var(--text-muted)] hover:text-[var(--text)] hover:bg-[var(--bg)]'
          }`}
        >
          {range.label}
        </button>
      ))}
    </div>
  );
}

interface SummaryCardProps {
  label: string;
  value: string;
  subtext: string;
  color: string;
  progress?: number;
}

function SummaryCard({ label, value, subtext, color, progress }: SummaryCardProps) {
  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
      <div className={`text-2xl font-theme-data font-bold ${color}`}>{value}</div>
      <div className="text-xs text-[var(--text-muted)] mt-1">{label}</div>
      <div className="text-xs text-[var(--text-muted)] opacity-70">{subtext}</div>
      {progress !== undefined && (
        <div className="mt-2 h-1 bg-[var(--bg)] rounded overflow-hidden">
          <div
            className={`h-full ${color.replace('text-', 'bg-').replace('[var(--acid-green)]', '[var(--acid-green)]')}`}
            style={{ width: `${Math.min(progress, 100)}%`, backgroundColor: 'var(--acid-green)' }}
          />
        </div>
      )}
    </div>
  );
}

function formatNumber(num: number): string {
  if (num >= 1000000) {
    return `${(num / 1000000).toFixed(1)}M`;
  }
  if (num >= 1000) {
    return `${(num / 1000).toFixed(1)}K`;
  }
  return num.toString();
}

function formatDateLabel(dateStr: string): string {
  const date = new Date(dateStr);
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export default CostDashboard;
