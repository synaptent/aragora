'use client';

import { useState, useCallback, useMemo, type ReactNode } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { ProtectedRoute } from '@/components/auth/ProtectedRoute';
import { useAragoraClient } from '@/hooks/useAragoraClient';
import { useAsyncData } from '@/hooks/useAsyncData';

import {
  MetricCard,
  TrendChart,
  AgentLeaderboard,
  CostBreakdown,
  type DataPoint,
  type TimeRange,
  type AgentRankingEntry,
  type CostCategory,
} from '@/components/analytics';

/**
 * Analytics Dashboard Page (Phase 4.4)
 *
 * Comprehensive analytics visualization including:
 * - Debate Metrics: success rate, avg duration, consensus rate
 * - Agent Performance: ELO rankings, response times, usage by agent
 * - Usage Trends: debates/day, tokens/day, active users
 * - Cost Analysis: spending by model, projected costs
 */

type TabType = 'overview' | 'agents' | 'usage' | 'cost' | 'consensus' | 'topics';

interface DebateOverviewData {
  time_range: string;
  total_debates: number;
  debates_this_period: number;
  debates_previous_period: number;
  growth_rate: number;
  consensus_reached: number;
  consensus_rate: number;
  avg_rounds: number;
  avg_agents_per_debate: number;
  avg_confidence: number;
}

interface DebateTrendData {
  period: string;
  total: number;
  consensus_reached: number;
  consensus_rate: number;
  avg_rounds: number;
}

interface LeaderboardResponse {
  leaderboard: AgentRankingEntry[];
  total_agents: number;
}

interface TokenUsageData {
  summary: {
    total_tokens_in: number;
    total_tokens_out: number;
    total_tokens: number;
    avg_tokens_per_day: number;
  };
  by_agent?: Record<string, string>;
  by_model?: Record<string, string>;
}

interface CostData {
  summary: {
    total_cost_usd: string;
    avg_cost_per_day: string;
    avg_cost_per_debate: string;
    total_api_calls: number;
  };
  by_provider: Record<string, { cost: string; percentage: number }>;
  by_model: Record<string, string>;
}

interface ConsensusOutcomeData {
  outcomes: { consensus: number; no_consensus: number; timeout: number; error: number };
  total_debates: number;
  consensus_rate: number;
}

interface TopicData {
  topic: string;
  debate_count: number;
  consensus_rate: number;
  avg_rounds: number;
}

/* ── Consensus Donut Chart ─────────────────────────────────────────── */

function ConsensusDonut({ outcomes }: { outcomes: ConsensusOutcomeData['outcomes'] }) {
  const total = outcomes.consensus + outcomes.no_consensus + outcomes.timeout + outcomes.error;
  if (total === 0) {
    return (
      <svg viewBox="0 0 200 200" className="w-48 h-48">
        <circle cx="100" cy="100" r="70" fill="none" stroke="#374151" strokeWidth="20" />
        <text
          x="100"
          y="105"
          textAnchor="middle"
          className="fill-text-muted"
          fontSize="14"
          fontFamily="monospace"
        >
          Run debates to see outcomes
        </text>
      </svg>
    );
  }

  const segments = [
    { value: outcomes.consensus, color: '#22c55e' },
    { value: outcomes.no_consensus, color: '#ef4444' },
    { value: outcomes.timeout, color: '#eab308' },
    { value: outcomes.error, color: '#6b7280' },
  ];

  const circumference = 2 * Math.PI * 70;
  let offset = 0;
  const arcs: ReactNode[] = [];

  for (const seg of segments) {
    if (seg.value === 0) continue;
    const pct = seg.value / total;
    const dashLen = pct * circumference;
    arcs.push(
      <circle
        key={seg.color}
        cx="100"
        cy="100"
        r="70"
        fill="none"
        stroke={seg.color}
        strokeWidth="20"
        strokeDasharray={`${dashLen} ${circumference - dashLen}`}
        strokeDashoffset={-offset}
        transform="rotate(-90 100 100)"
      />,
    );
    offset += dashLen;
  }

  return (
    <svg viewBox="0 0 200 200" className="w-48 h-48">
      {arcs}
      <text
        x="100"
        y="98"
        textAnchor="middle"
        className="fill-acid-green"
        fontSize="22"
        fontFamily="monospace"
        fontWeight="bold"
      >
        {((outcomes.consensus / total) * 100).toFixed(0)}%
      </text>
      <text
        x="100"
        y="116"
        textAnchor="middle"
        className="fill-text-muted"
        fontSize="10"
        fontFamily="monospace"
      >
        consensus
      </text>
    </svg>
  );
}

function DonutLegendItem({ color, label, value }: { color: string; label: string; value: number }) {
  return (
    <div className="flex items-center gap-3">
      <span className="inline-block w-3 h-3 rounded-sm" style={{ backgroundColor: color }} />
      <span className="text-text">{label}</span>
      <span className="text-text-muted ml-auto">{value}</span>
    </div>
  );
}

/* ── Topic Table ──────────────────────────────────────────────────── */

type TopicSortKey = 'topic' | 'debate_count' | 'consensus_rate' | 'avg_rounds';

function TopicTable({ topics }: { topics: TopicData[] }) {
  const [sortKey, setSortKey] = useState<TopicSortKey>('debate_count');
  const [sortAsc, setSortAsc] = useState(false);

  const sorted = useMemo(() => {
    const copy = [...topics];
    copy.sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (typeof av === 'string' && typeof bv === 'string')
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return copy;
  }, [topics, sortKey, sortAsc]);

  const handleSort = (key: TopicSortKey) => {
    if (key === sortKey) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const sortIndicator = (key: TopicSortKey) => (sortKey === key ? (sortAsc ? ' ^' : ' v') : '');

  const rateColor = (rate: number) => {
    if (rate > 70) return 'text-green-400';
    if (rate > 50) return 'text-yellow-400';
    return 'text-red-400';
  };

  return (
    <table className="w-full font-theme-data text-sm">
      <thead>
        <tr className="border-b border-[var(--accent)]/30">
          {(
            [
              ['topic', 'Topic'],
              ['debate_count', 'Debates'],
              ['consensus_rate', 'Consensus Rate'],
              ['avg_rounds', 'Avg Rounds'],
            ] as [TopicSortKey, string][]
          ).map(([key, label]) => (
            <th
              key={key}
              onClick={() => handleSort(key)}
              className={`py-2 px-3 text-[var(--accent)] cursor-pointer select-none hover:text-[var(--acid-cyan)] transition-colors ${
                key === 'topic' ? 'text-left' : 'text-right'
              }`}
            >
              {label}
              {sortIndicator(key)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sorted.map((t, i) => (
          <tr
            key={t.topic}
            className={`border-b border-[var(--accent)]/10 ${
              i % 2 === 0 ? 'bg-[var(--accent)]/5' : ''
            }`}
          >
            <td className="py-2 px-3 text-[var(--acid-cyan)]">{t.topic}</td>
            <td className="py-2 px-3 text-right text-text">{t.debate_count}</td>
            <td className={`py-2 px-3 text-right ${rateColor(t.consensus_rate)}`}>
              {t.consensus_rate.toFixed(1)}%
            </td>
            <td className="py-2 px-3 text-right text-text-muted">{t.avg_rounds.toFixed(1)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function AnalyticsPage() {
  const { config: backendConfig } = useBackend();
  // Client available for future SDK-based fetching
  const _client = useAragoraClient();
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [timeRange, setTimeRange] = useState<TimeRange>('30d');

  // Fetch debate overview
  const overviewFetcher = useCallback(async (): Promise<DebateOverviewData | null> => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/analytics/debates/overview?time_range=${timeRange}`,
      );
      if (!response.ok) return null;
      return response.json();
    } catch {
      return null;
    }
  }, [backendConfig.api, timeRange]);

  // Fetch debate trends
  const trendsFetcher = useCallback(async (): Promise<DebateTrendData[]> => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/analytics/debates/trends?time_range=${timeRange}&granularity=daily`,
      );
      if (!response.ok) return [];
      const data = await response.json();
      return data.data_points || [];
    } catch {
      return [];
    }
  }, [backendConfig.api, timeRange]);

  // Fetch agent leaderboard
  const leaderboardFetcher = useCallback(async (): Promise<LeaderboardResponse | null> => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/analytics/agents/leaderboard?limit=20`,
      );
      if (!response.ok) return null;
      return response.json();
    } catch {
      return null;
    }
  }, [backendConfig.api]);

  // Fetch token usage
  const tokenFetcher = useCallback(async (): Promise<TokenUsageData | null> => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/analytics/usage/tokens?time_range=${timeRange}&org_id=default`,
      );
      if (!response.ok) return null;
      return response.json();
    } catch {
      return null;
    }
  }, [backendConfig.api, timeRange]);

  // Fetch cost data
  const costFetcher = useCallback(async (): Promise<CostData | null> => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/analytics/usage/costs?time_range=${timeRange}&org_id=default`,
      );
      if (!response.ok) return null;
      return response.json();
    } catch {
      return null;
    }
  }, [backendConfig.api, timeRange]);

  // Fetch consensus outcomes
  const consensusFetcher = useCallback(async (): Promise<ConsensusOutcomeData | null> => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/analytics/debates/outcomes?time_range=${timeRange}`,
      );
      if (!response.ok) return null;
      return response.json();
    } catch {
      return null;
    }
  }, [backendConfig.api, timeRange]);

  // Fetch topic analysis
  const topicsFetcher = useCallback(async (): Promise<TopicData[]> => {
    try {
      const response = await fetch(
        `${backendConfig.api}/api/v1/analytics/debates/topics?time_range=${timeRange}`,
      );
      if (!response.ok) return [];
      const data = await response.json();
      return data.topics || [];
    } catch {
      return [];
    }
  }, [backendConfig.api, timeRange]);

  const { data: overview, loading: overviewLoading } = useAsyncData(overviewFetcher, {
    immediate: true,
  });

  const { data: trends, loading: trendsLoading } = useAsyncData(trendsFetcher, { immediate: true });

  const { data: leaderboard, loading: leaderboardLoading } = useAsyncData(leaderboardFetcher, {
    immediate: true,
  });

  const { data: tokenUsage, loading: tokenLoading } = useAsyncData(tokenFetcher, {
    immediate: true,
  });

  const { data: costData, loading: costLoading } = useAsyncData(costFetcher, { immediate: true });

  const { data: consensusData, loading: consensusLoading } = useAsyncData(consensusFetcher, {
    immediate: true,
  });

  const { data: topicsData, loading: topicsLoading } = useAsyncData(topicsFetcher, {
    immediate: true,
  });

  // Transform trends for chart
  const debateTrendData: DataPoint[] = useMemo(() => {
    if (!trends) return [];
    return trends.map((t) => ({
      label: t.period.split('-').slice(1).join('/'), // Format: MM/DD
      value: t.total,
      date: t.period,
    }));
  }, [trends]);

  const consensusTrendData: DataPoint[] = useMemo(() => {
    if (!trends) return [];
    return trends.map((t) => ({
      label: t.period.split('-').slice(1).join('/'),
      value: t.consensus_rate,
      date: t.period,
    }));
  }, [trends]);

  // Transform cost data for breakdown
  const costCategories: CostCategory[] = useMemo(() => {
    if (!costData?.by_provider) return [];
    return Object.entries(costData.by_provider).map(([name, data]) => ({
      name,
      cost: parseFloat(data.cost),
      percentage: data.percentage,
    }));
  }, [costData]);

  const handleTimeRangeChange = (range: TimeRange) => {
    setTimeRange(range);
  };

  const tabs: { id: TabType; label: string }[] = [
    { id: 'overview', label: 'OVERVIEW' },
    { id: 'agents', label: 'AGENTS' },
    { id: 'usage', label: 'USAGE' },
    { id: 'cost', label: 'COST' },
    { id: 'consensus', label: 'CONSENSUS' },
    { id: 'topics', label: 'TOPICS' },
  ];

  return (
    <ProtectedRoute>
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />

        <main className="min-h-screen bg-bg text-text relative z-10">
          <div className="container mx-auto px-4 py-6">
            {/* Header */}
            <div className="mb-6">
              <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
                {'>'} ANALYTICS DASHBOARD
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Debate metrics, agent performance, usage trends, and cost analysis.
              </p>
            </div>

            {/* Tab Navigation */}
            <div className="flex flex-wrap gap-1 border-b border-[var(--accent)]/20 pb-2 mb-6">
              {tabs.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-4 py-2 text-xs font-theme-data transition-colors ${
                    activeTab === tab.id
                      ? 'bg-[var(--accent)] text-bg'
                      : 'text-text-muted hover:text-[var(--accent)]'
                  }`}
                >
                  [{tab.label}]
                </button>
              ))}

              {/* Time Range Selector */}
              <div className="ml-auto flex gap-1">
                {(['7d', '30d', '90d'] as TimeRange[]).map((range) => (
                  <button
                    key={range}
                    onClick={() => handleTimeRangeChange(range)}
                    className={`px-3 py-2 text-xs font-theme-data transition-colors ${
                      timeRange === range
                        ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/40'
                        : 'text-text-muted hover:text-text'
                    }`}
                  >
                    {range}
                  </button>
                ))}
              </div>
            </div>

            {/* Tab Content */}
            <div className="space-y-6">
              {/* Overview Tab */}
              {activeTab === 'overview' && (
                <PanelErrorBoundary panelName="Overview">
                  <div className="space-y-6">
                    {/* Key Metrics */}
                    <section>
                      <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                        {'>'} KEY METRICS
                      </h2>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <MetricCard
                          title="Total Debates"
                          value={overview?.total_debates ?? '-'}
                          subtitle={`${overview?.debates_this_period ?? 0} this period`}
                          change={overview?.growth_rate}
                          changePeriod="vs prev"
                          color="green"
                          loading={overviewLoading}
                          icon="#"
                        />
                        <MetricCard
                          title="Consensus Rate"
                          value={overview ? `${overview.consensus_rate.toFixed(1)}%` : '-'}
                          subtitle={`${overview?.consensus_reached ?? 0} reached`}
                          color="cyan"
                          loading={overviewLoading}
                          icon="%"
                        />
                        <MetricCard
                          title="Avg Rounds"
                          value={overview?.avg_rounds.toFixed(1) ?? '-'}
                          subtitle="per debate"
                          color="yellow"
                          loading={overviewLoading}
                          icon="~"
                        />
                        <MetricCard
                          title="Avg Confidence"
                          value={overview ? `${(overview.avg_confidence * 100).toFixed(0)}%` : '-'}
                          subtitle="consensus confidence"
                          color="purple"
                          loading={overviewLoading}
                          icon="*"
                        />
                      </div>
                    </section>

                    {/* Debates Trend */}
                    <section>
                      <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                        {'>'} DEBATE ACTIVITY
                      </h2>
                      <TrendChart
                        title="Debates Over Time"
                        data={debateTrendData}
                        type="area"
                        color="green"
                        loading={trendsLoading}
                        showTimeRangeSelector={false}
                        height={250}
                      />
                    </section>

                    {/* Consensus Rate Trend */}
                    <section>
                      <TrendChart
                        title="Consensus Rate Trend"
                        data={consensusTrendData}
                        type="line"
                        color="cyan"
                        loading={trendsLoading}
                        showTimeRangeSelector={false}
                        height={200}
                        formatValue={(v) => `${v.toFixed(1)}%`}
                      />
                    </section>
                  </div>
                </PanelErrorBoundary>
              )}

              {/* Agents Tab */}
              {activeTab === 'agents' && (
                <PanelErrorBoundary panelName="Agent Performance">
                  <div className="space-y-6">
                    {/* Agent Stats Summary */}
                    <section>
                      <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                        {'>'} AGENT STATISTICS
                      </h2>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <MetricCard
                          title="Total Agents"
                          value={leaderboard?.total_agents ?? '-'}
                          color="green"
                          loading={leaderboardLoading}
                          icon="#"
                        />
                        <MetricCard
                          title="Top ELO"
                          value={leaderboard?.leaderboard?.[0]?.elo.toFixed(0) ?? '-'}
                          subtitle={leaderboard?.leaderboard?.[0]?.agent_name ?? ''}
                          color="purple"
                          loading={leaderboardLoading}
                          icon="^"
                        />
                        <MetricCard
                          title="Avg Win Rate"
                          value={
                            leaderboard?.leaderboard
                              ? `${(
                                  leaderboard.leaderboard.reduce((a, b) => a + b.win_rate, 0) /
                                  leaderboard.leaderboard.length
                                ).toFixed(1)}%`
                              : '-'
                          }
                          color="cyan"
                          loading={leaderboardLoading}
                          icon="%"
                        />
                        <MetricCard
                          title="Total Games"
                          value={
                            leaderboard?.leaderboard
                              ? leaderboard.leaderboard.reduce((a, b) => a + b.games_played, 0)
                              : '-'
                          }
                          color="yellow"
                          loading={leaderboardLoading}
                          icon=">"
                        />
                      </div>
                    </section>

                    {/* Leaderboard */}
                    <section>
                      <AgentLeaderboard
                        agents={leaderboard?.leaderboard ?? []}
                        loading={leaderboardLoading}
                        title="AGENT RANKINGS"
                        limit={15}
                      />
                    </section>

                    {/* Agent Comparison Grid */}
                    {leaderboard?.leaderboard && leaderboard.leaderboard.length > 0 && (
                      <section>
                        <div className="card p-4">
                          <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
                            {'>'} TOP AGENT COMPARISON
                          </h3>
                          <div className="overflow-x-auto">
                            <table className="w-full font-theme-data text-sm">
                              <thead>
                                <tr className="border-b border-[var(--accent)]/30">
                                  <th className="text-left py-2 px-3 text-[var(--accent)]">
                                    Agent
                                  </th>
                                  <th className="text-right py-2 px-3 text-[var(--accent)]">ELO</th>
                                  <th className="text-right py-2 px-3 text-[var(--accent)]">
                                    Win Rate
                                  </th>
                                  <th className="text-right py-2 px-3 text-[var(--accent)]">
                                    Games
                                  </th>
                                </tr>
                              </thead>
                              <tbody>
                                {leaderboard.leaderboard.slice(0, 5).map((agent, i) => (
                                  <tr
                                    key={agent.agent_name}
                                    className={`border-b border-[var(--accent)]/10 ${
                                      i % 2 === 0 ? 'bg-[var(--accent)]/5' : ''
                                    }`}
                                  >
                                    <td className="py-2 px-3 text-[var(--acid-cyan)]">
                                      {agent.agent_name}
                                    </td>
                                    <td className="py-2 px-3 text-right text-text">
                                      {agent.elo.toFixed(0)}
                                    </td>
                                    <td className="py-2 px-3 text-right text-text">
                                      {agent.win_rate.toFixed(1)}%
                                    </td>
                                    <td className="py-2 px-3 text-right text-text-muted">
                                      {agent.games_played}
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        </div>
                      </section>
                    )}
                  </div>
                </PanelErrorBoundary>
              )}

              {/* Usage Tab */}
              {activeTab === 'usage' && (
                <PanelErrorBoundary panelName="Usage Analytics">
                  <div className="space-y-6">
                    {/* Token Usage Summary */}
                    <section>
                      <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                        {'>'} TOKEN USAGE
                      </h2>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <MetricCard
                          title="Total Tokens"
                          value={
                            tokenUsage
                              ? (tokenUsage.summary.total_tokens / 1000000).toFixed(2) + 'M'
                              : '-'
                          }
                          color="green"
                          loading={tokenLoading}
                          icon="#"
                        />
                        <MetricCard
                          title="Input Tokens"
                          value={
                            tokenUsage
                              ? (tokenUsage.summary.total_tokens_in / 1000000).toFixed(2) + 'M'
                              : '-'
                          }
                          color="cyan"
                          loading={tokenLoading}
                          icon=">"
                        />
                        <MetricCard
                          title="Output Tokens"
                          value={
                            tokenUsage
                              ? (tokenUsage.summary.total_tokens_out / 1000000).toFixed(2) + 'M'
                              : '-'
                          }
                          color="yellow"
                          loading={tokenLoading}
                          icon="<"
                        />
                        <MetricCard
                          title="Avg/Day"
                          value={
                            tokenUsage
                              ? (tokenUsage.summary.avg_tokens_per_day / 1000).toFixed(1) + 'K'
                              : '-'
                          }
                          color="purple"
                          loading={tokenLoading}
                          icon="~"
                        />
                      </div>
                    </section>

                    {/* Usage by Model */}
                    {tokenUsage?.by_model && Object.keys(tokenUsage.by_model).length > 0 && (
                      <section>
                        <div className="card p-4">
                          <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
                            {'>'} USAGE BY MODEL
                          </h3>
                          <div className="space-y-2">
                            {Object.entries(tokenUsage.by_model).map(([model, usage]) => (
                              <div
                                key={model}
                                className="flex items-center justify-between p-2 border border-[var(--accent)]/20 rounded"
                              >
                                <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                                  {model}
                                </span>
                                <span className="font-theme-data text-sm text-text">{usage}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      </section>
                    )}
                  </div>
                </PanelErrorBoundary>
              )}

              {/* Cost Tab */}
              {activeTab === 'cost' && (
                <PanelErrorBoundary panelName="Cost Analysis">
                  <div className="space-y-6">
                    {/* Cost Summary */}
                    <section>
                      <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                        {'>'} COST SUMMARY
                      </h2>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <MetricCard
                          title="Total Cost"
                          value={costData ? `$${costData.summary.total_cost_usd}` : '-'}
                          subtitle={`${timeRange} period`}
                          color="green"
                          loading={costLoading}
                          icon="$"
                        />
                        <MetricCard
                          title="Avg/Day"
                          value={costData ? `$${costData.summary.avg_cost_per_day}` : '-'}
                          color="cyan"
                          loading={costLoading}
                          icon="~"
                        />
                        <MetricCard
                          title="Avg/Debate"
                          value={costData ? `$${costData.summary.avg_cost_per_debate}` : '-'}
                          color="yellow"
                          loading={costLoading}
                          icon="#"
                        />
                        <MetricCard
                          title="API Calls"
                          value={costData?.summary.total_api_calls ?? '-'}
                          color="purple"
                          loading={costLoading}
                          icon=">"
                        />
                      </div>
                    </section>

                    {/* Cost Breakdown */}
                    <section>
                      <CostBreakdown
                        data={costCategories}
                        totalCost={parseFloat(costData?.summary.total_cost_usd ?? '0')}
                        title="COST BY PROVIDER"
                        subtitle={`${timeRange} period`}
                        loading={costLoading}
                        showTokens={false}
                      />
                    </section>

                    {/* Cost by Model */}
                    {costData?.by_model && Object.keys(costData.by_model).length > 0 && (
                      <section>
                        <div className="card p-4">
                          <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
                            {'>'} COST BY MODEL
                          </h3>
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                            {Object.entries(costData.by_model)
                              .sort(([, a], [, b]) => parseFloat(b) - parseFloat(a))
                              .map(([model, cost]) => (
                                <div
                                  key={model}
                                  className="flex items-center justify-between p-3 border border-[var(--accent)]/20 rounded hover:bg-[var(--accent)]/5 transition-colors"
                                >
                                  <span className="font-theme-data text-sm text-[var(--acid-cyan)]">
                                    {model}
                                  </span>
                                  <span className="font-theme-data text-sm text-[var(--accent)]">
                                    ${cost}
                                  </span>
                                </div>
                              ))}
                          </div>
                        </div>
                      </section>
                    )}
                  </div>
                </PanelErrorBoundary>
              )}

              {/* Consensus Tab */}
              {activeTab === 'consensus' && (
                <PanelErrorBoundary panelName="Consensus Analysis">
                  <div className="space-y-6">
                    {consensusLoading ? (
                      <div className="card p-8 text-center font-theme-data text-text-muted animate-pulse">
                        Loading consensus data...
                      </div>
                    ) : consensusData ? (
                      <>
                        {/* Donut Chart */}
                        <section>
                          <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                            {'>'} OUTCOME DISTRIBUTION
                          </h2>
                          <div className="card p-6">
                            <div className="flex flex-col md:flex-row items-center gap-8">
                              <ConsensusDonut outcomes={consensusData.outcomes} />
                              <div className="space-y-3 font-theme-data text-sm">
                                <DonutLegendItem
                                  color="#22c55e"
                                  label="Consensus"
                                  value={consensusData.outcomes.consensus}
                                />
                                <DonutLegendItem
                                  color="#ef4444"
                                  label="No Consensus"
                                  value={consensusData.outcomes.no_consensus}
                                />
                                <DonutLegendItem
                                  color="#eab308"
                                  label="Timeout"
                                  value={consensusData.outcomes.timeout}
                                />
                                <DonutLegendItem
                                  color="#6b7280"
                                  label="Error"
                                  value={consensusData.outcomes.error}
                                />
                              </div>
                            </div>
                          </div>
                        </section>

                        {/* Consensus Metrics */}
                        <section>
                          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                            <MetricCard
                              title="Total Debates"
                              value={consensusData.total_debates}
                              color="green"
                              loading={false}
                              icon="#"
                            />
                            <MetricCard
                              title="Consensus Rate"
                              value={`${consensusData.consensus_rate.toFixed(1)}%`}
                              color="cyan"
                              loading={false}
                              icon="%"
                            />
                            <MetricCard
                              title="Successful"
                              value={consensusData.outcomes.consensus}
                              subtitle={`of ${consensusData.total_debates} debates`}
                              color="purple"
                              loading={false}
                              icon="+"
                            />
                          </div>
                        </section>
                      </>
                    ) : (
                      <div className="card p-8 text-center font-theme-data text-text-muted space-y-2">
                        <p>No consensus data in this time range.</p>
                        <p className="text-xs text-text-muted/60">
                          Try a wider date range or run debates to generate consensus metrics.
                        </p>
                      </div>
                    )}
                  </div>
                </PanelErrorBoundary>
              )}

              {/* Topics Tab */}
              {activeTab === 'topics' && (
                <PanelErrorBoundary panelName="Topic Analysis">
                  <div className="space-y-6">
                    <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                      {'>'} TOPIC ANALYSIS
                    </h2>
                    {topicsLoading ? (
                      <div className="card p-8 text-center font-theme-data text-text-muted animate-pulse">
                        Loading topic data...
                      </div>
                    ) : topicsData && topicsData.length > 0 ? (
                      <section>
                        <div className="card p-4">
                          <div className="overflow-x-auto">
                            <TopicTable topics={topicsData} />
                          </div>
                        </div>
                      </section>
                    ) : (
                      <div className="card p-8 text-center font-theme-data text-text-muted space-y-2">
                        <p>No topic data in this time range.</p>
                        <p className="text-xs text-text-muted/60">
                          Expand your date range or start a debate to see trending topics.
                        </p>
                      </div>
                    )}
                  </div>
                </PanelErrorBoundary>
              )}
            </div>
          </div>

          {/* Footer */}
          <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
            <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
            <p className="text-text-muted">{'>'} ARAGORA // ANALYTICS DASHBOARD</p>
          </footer>
        </main>
      </>
    </ProtectedRoute>
  );
}
