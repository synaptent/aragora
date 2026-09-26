'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { ThemeToggle } from '@/components/ThemeToggle';
import { BackendSelector } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import {
  useEloTrends,
  useAgentEloDetail,
  useRankingStats,
  useDomainLeaderboard,
} from '@/hooks/useEloAnalytics';

// ============================================================================
// Constants
// ============================================================================

type TabKey = 'rankings' | 'domains' | 'trends' | 'stats';

const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'rankings', label: 'Rankings' },
  { key: 'domains', label: 'Domains' },
  { key: 'trends', label: 'Trends' },
  { key: 'stats', label: 'Stats' },
];

const DOMAINS = [
  { key: null as string | null, label: 'Overall' },
  { key: 'technical', label: 'Technical' },
  { key: 'business', label: 'Business' },
  { key: 'creative', label: 'Creative' },
  { key: 'security', label: 'Security' },
];

const TREND_COLORS = [
  'var(--acid-green)',
  '#22d3ee', // cyan
  '#c084fc', // purple
  '#facc15', // yellow
  '#f97316', // orange
];

// ============================================================================
// Helper functions
// ============================================================================

function getEloColor(elo: number): string {
  if (elo >= 1600) return 'text-green-400';
  if (elo >= 1500) return 'text-yellow-400';
  if (elo >= 1400) return 'text-orange-400';
  return 'text-red-400';
}

function getRankBadge(rank: number): string {
  if (rank === 1) return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30';
  if (rank === 2) return 'bg-zinc-400/20 text-zinc-300 border-zinc-400/30';
  if (rank === 3) return 'bg-amber-600/20 text-amber-500 border-amber-600/30';
  return 'bg-surface text-text-muted border-border';
}

function getEloTier(elo: number): string {
  if (elo >= 1800) return 'GRANDMASTER';
  if (elo >= 1600) return 'MASTER';
  if (elo >= 1500) return 'EXPERT';
  if (elo >= 1400) return 'ADVANCED';
  if (elo >= 1200) return 'INTERMEDIATE';
  return 'NOVICE';
}

// ============================================================================
// Sub-components
// ============================================================================

function RankingsPanel() {
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const { agents, isLoading, error } = useDomainLeaderboard(null, 25);
  const { agent: agentDetail, isLoading: detailLoading } = useAgentEloDetail(selectedAgent);

  if (isLoading) {
    return (
      <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
        Loading rankings...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 bg-surface border border-red-500/30 rounded-lg text-center">
        <p className="text-red-400 font-theme-data text-sm">Failed to load rankings data.</p>
      </div>
    );
  }

  if (!agents || agents.length === 0) {
    return (
      <div className="p-8 bg-surface border border-border rounded-lg text-center">
        <p className="text-text-muted font-theme-data">
          No ranking data available. Run debate cycles to generate ELO ratings.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Rankings Table */}
      <div className="bg-surface border border-border rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm font-theme-data">
            <thead>
              <tr className="text-text-muted border-b border-border bg-bg/50">
                <th className="text-left py-3 px-4 w-12">#</th>
                <th className="text-left py-3 px-4">Agent</th>
                <th className="text-right py-3 px-4">ELO</th>
                <th className="text-right py-3 px-4 hidden sm:table-cell">Tier</th>
                <th className="text-right py-3 px-4 hidden md:table-cell">Win Rate</th>
                <th className="text-right py-3 px-4 hidden md:table-cell">Games</th>
                <th className="text-right py-3 px-4">W/L/D</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent, idx) => {
                const rank = idx + 1;
                const totalGames = (agent.wins || 0) + (agent.losses || 0) + (agent.draws || 0);
                const winRate =
                  totalGames > 0
                    ? Math.round(((agent.wins || 0) / totalGames) * 100)
                    : Math.round(agent.win_rate ?? 0);
                const elo = Math.round(agent.elo);
                const isSelected = selectedAgent === agent.agent_name;

                return (
                  <tr
                    key={agent.agent_name}
                    onClick={() => setSelectedAgent(isSelected ? null : agent.agent_name)}
                    className={`border-b border-border/50 cursor-pointer transition-colors ${
                      isSelected
                        ? 'bg-[var(--accent)]/10 border-[var(--accent)]/30'
                        : 'hover:bg-surface/80'
                    }`}
                  >
                    <td className="py-3 px-4">
                      <div
                        className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold border ${getRankBadge(rank)}`}
                      >
                        {rank}
                      </div>
                    </td>
                    <td className="py-3 px-4">
                      <Link
                        href={`/agent/${encodeURIComponent(agent.agent_name)}/`}
                        className="text-text hover:text-[var(--accent)] transition-colors"
                        onClick={(e) => e.stopPropagation()}
                      >
                        {agent.agent_name}
                      </Link>
                    </td>
                    <td className={`py-3 px-4 text-right font-bold ${getEloColor(elo)}`}>{elo}</td>
                    <td className="py-3 px-4 text-right text-text-muted text-xs hidden sm:table-cell">
                      {getEloTier(elo)}
                    </td>
                    <td className="py-3 px-4 text-right text-text-muted hidden md:table-cell">
                      {winRate}%
                    </td>
                    <td className="py-3 px-4 text-right text-text-muted hidden md:table-cell">
                      {agent.games || totalGames}
                    </td>
                    <td className="py-3 px-4 text-right">
                      <span className="text-green-400">{agent.wins || 0}</span>
                      {'/'}
                      <span className="text-red-400">{agent.losses || 0}</span>
                      {'/'}
                      <span className="text-yellow-400">{agent.draws || 0}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Agent Detail Panel (expanded when selected) */}
      {selectedAgent && (
        <div className="p-4 bg-surface border border-[var(--accent)]/30 rounded-lg">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-theme-data font-bold text-[var(--accent)]">
              {'>'} AGENT DETAIL: {selectedAgent}
            </h3>
            <button
              onClick={() => setSelectedAgent(null)}
              className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
            >
              [CLOSE]
            </button>
          </div>

          {detailLoading ? (
            <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-4">
              Loading agent detail...
            </div>
          ) : agentDetail ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-3 bg-bg rounded">
                <div
                  className={`text-xl font-theme-data font-bold ${getEloColor(agentDetail.elo)}`}
                >
                  {Math.round(agentDetail.elo)}
                </div>
                <div className="text-xs text-text-muted">Current ELO</div>
              </div>
              <div className="p-3 bg-bg rounded">
                <div
                  className={`text-xl font-theme-data font-bold ${
                    agentDetail.elo_change >= 0 ? 'text-[var(--accent)]' : 'text-red-400'
                  }`}
                >
                  {agentDetail.elo_change >= 0 ? '+' : ''}
                  {agentDetail.elo_change}
                </div>
                <div className="text-xs text-text-muted">ELO Change</div>
              </div>
              <div className="p-3 bg-bg rounded">
                <div className="text-xl font-theme-data font-bold text-text">
                  {agentDetail.debates_count}
                </div>
                <div className="text-xs text-text-muted">Total Debates</div>
              </div>
              <div className="p-3 bg-bg rounded">
                <div className="text-xl font-theme-data font-bold text-text">
                  {Math.round(agentDetail.win_rate)}%
                </div>
                <div className="text-xs text-text-muted">Win Rate</div>
              </div>

              {/* Domain Performance */}
              {agentDetail.domain_performance &&
                Object.keys(agentDetail.domain_performance).length > 0 && (
                  <div className="col-span-2 md:col-span-4 p-3 bg-bg rounded">
                    <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
                      Domain Performance
                    </div>
                    <div className="flex flex-wrap gap-3">
                      {Object.entries(agentDetail.domain_performance).map(([domain, perf]) => (
                        <div key={domain} className="text-xs font-theme-data">
                          <span className="text-text-muted">{domain}: </span>
                          <span className={getEloColor(perf.elo)}>{Math.round(perf.elo)}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

              {/* Calibration */}
              {agentDetail.calibration_score != null && (
                <div className="col-span-2 p-3 bg-bg rounded">
                  <div className="text-xs font-theme-data text-text-muted uppercase mb-1">
                    Calibration
                  </div>
                  <div className="text-sm font-theme-data text-text">
                    Score: {(agentDetail.calibration_score * 100).toFixed(1)}%
                    {agentDetail.calibration_accuracy != null && (
                      <span className="ml-3">
                        Accuracy: {(agentDetail.calibration_accuracy * 100).toFixed(1)}%
                      </span>
                    )}
                  </div>
                </div>
              )}

              {/* Mini ELO history chart */}
              {agentDetail.elo_history && agentDetail.elo_history.length >= 2 && (
                <div className="col-span-2 md:col-span-4 p-3 bg-bg rounded">
                  <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
                    ELO History
                  </div>
                  <MiniEloChart history={agentDetail.elo_history} color="var(--acid-green)" />
                </div>
              )}
            </div>
          ) : (
            <p className="text-text-muted font-theme-data text-xs py-2">
              No detailed data available for this agent.
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function MiniEloChart({
  history,
  color,
}: {
  history: Array<{ timestamp: string; elo: number }>;
  color: string;
}) {
  const chartData = useMemo(() => {
    if (history.length < 2) return null;
    const elos = history.map((h) => h.elo);
    const min = Math.min(...elos);
    const max = Math.max(...elos);
    const range = max - min || 1;
    const padding = range * 0.1;

    return { min: min - padding, max: max + padding, range: range + padding * 2, points: history };
  }, [history]);

  if (!chartData) return null;

  const width = 400;
  const height = 60;
  const padX = 4;
  const padY = 4;
  const plotW = width - padX * 2;
  const plotH = height - padY * 2;

  const pathParts = chartData.points.map((pt, i) => {
    const x = padX + (i / (chartData.points.length - 1)) * plotW;
    const y = padY + plotH - ((pt.elo - chartData.min) / chartData.range) * plotH;
    return `${x},${y}`;
  });

  const d = `M${pathParts.join('L')}`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ maxHeight: height }}>
      <path
        d={d}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* End dot */}
      {(() => {
        const lastPt = chartData.points[chartData.points.length - 1];
        const x = padX + ((chartData.points.length - 1) / (chartData.points.length - 1)) * plotW;
        const y = padY + plotH - ((lastPt.elo - chartData.min) / chartData.range) * plotH;
        return <circle cx={x} cy={y} r={3} fill={color} />;
      })()}
    </svg>
  );
}

function DomainsPanel() {
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);
  const { agents, isLoading, error } = useDomainLeaderboard(selectedDomain, 15);

  return (
    <div className="space-y-4">
      {/* Domain tabs */}
      <div className="flex gap-1 flex-wrap" role="tablist" aria-label="Domain filter">
        {DOMAINS.map(({ key, label }) => (
          <button
            key={label}
            onClick={() => setSelectedDomain(key)}
            role="tab"
            aria-selected={selectedDomain === key}
            className={`px-3 py-1.5 rounded text-xs font-theme-data transition-colors ${
              selectedDomain === key
                ? 'bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)]'
                : 'border border-border text-text-muted hover:border-[var(--accent)]/50'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
          Loading domain leaderboard...
        </div>
      ) : error ? (
        <div className="p-8 bg-surface border border-red-500/30 rounded-lg text-center">
          <p className="text-red-400 font-theme-data text-sm">Failed to load domain leaderboard.</p>
        </div>
      ) : !agents || agents.length === 0 ? (
        <div className="p-8 bg-surface border border-border rounded-lg text-center">
          <p className="text-text-muted font-theme-data">
            No rankings available for this domain. Run debate cycles to generate data.
          </p>
        </div>
      ) : (
        <div className="bg-surface border border-border rounded-lg overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm font-theme-data">
              <thead>
                <tr className="text-text-muted border-b border-border bg-bg/50">
                  <th className="text-left py-3 px-4 w-12">#</th>
                  <th className="text-left py-3 px-4">Agent</th>
                  <th className="text-right py-3 px-4">ELO</th>
                  {selectedDomain && (
                    <th className="text-right py-3 px-4 hidden sm:table-cell">Domain ELO</th>
                  )}
                  <th className="text-right py-3 px-4 hidden sm:table-cell">Win Rate</th>
                  <th className="text-right py-3 px-4">W/L/D</th>
                </tr>
              </thead>
              <tbody>
                {agents.map((agent, idx) => {
                  const rank = idx + 1;
                  const totalGames = (agent.wins || 0) + (agent.losses || 0) + (agent.draws || 0);
                  const winRate =
                    totalGames > 0
                      ? Math.round(((agent.wins || 0) / totalGames) * 100)
                      : Math.round(agent.win_rate ?? 0);

                  return (
                    <tr
                      key={agent.agent_name}
                      className="border-b border-border/50 hover:bg-surface/80 transition-colors"
                    >
                      <td className="py-2.5 px-4">
                        <div
                          className={`w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold border ${getRankBadge(rank)}`}
                        >
                          {rank}
                        </div>
                      </td>
                      <td className="py-2.5 px-4">
                        <Link
                          href={`/agent/${encodeURIComponent(agent.agent_name)}/`}
                          className="text-text hover:text-[var(--accent)] transition-colors"
                        >
                          {agent.agent_name}
                        </Link>
                      </td>
                      <td
                        className={`py-2.5 px-4 text-right font-bold ${getEloColor(Math.round(agent.elo))}`}
                      >
                        {Math.round(agent.elo)}
                      </td>
                      {selectedDomain && (
                        <td
                          className={`py-2.5 px-4 text-right hidden sm:table-cell ${getEloColor(Math.round(agent.domain_elo))}`}
                        >
                          {Math.round(agent.domain_elo)}
                        </td>
                      )}
                      <td className="py-2.5 px-4 text-right text-text-muted hidden sm:table-cell">
                        {winRate}%
                      </td>
                      <td className="py-2.5 px-4 text-right">
                        <span className="text-green-400">{agent.wins || 0}</span>
                        {'/'}
                        <span className="text-red-400">{agent.losses || 0}</span>
                        {'/'}
                        <span className="text-yellow-400">{agent.draws || 0}</span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

function TrendsPanel() {
  const { trends, agents, isLoading, error } = useEloTrends(undefined, 'daily');

  const chartData = useMemo(() => {
    if (!trends || agents.length === 0) return null;

    // Collect all unique periods
    const periodSet = new Set<string>();
    const topAgents = agents.slice(0, 5);
    for (const agentName of topAgents) {
      const agentTrend = trends[agentName];
      if (agentTrend) {
        for (const point of agentTrend) {
          periodSet.add(point.period);
        }
      }
    }

    const periods = Array.from(periodSet).sort().slice(-30);
    if (periods.length < 2) return null;

    // Build series
    const series: Array<{
      agent: string;
      color: string;
      points: Array<{ period: string; elo: number }>;
      latestElo: number;
      earliestElo: number;
    }> = [];

    let globalMin = Infinity;
    let globalMax = -Infinity;

    for (let i = 0; i < topAgents.length; i++) {
      const agentName = topAgents[i];
      const agentTrend = trends[agentName];
      if (!agentTrend || agentTrend.length === 0) continue;

      const lookup = new Map<string, number>();
      for (const pt of agentTrend) {
        lookup.set(pt.period, pt.elo);
      }

      const points: Array<{ period: string; elo: number }> = [];
      let lastElo: number | null = null;

      for (const period of periods) {
        const elo: number | null | undefined = lookup.get(period) ?? lastElo;
        if (elo !== null && elo !== undefined) {
          points.push({ period, elo });
          lastElo = elo;
          if (elo < globalMin) globalMin = elo;
          if (elo > globalMax) globalMax = elo;
        }
      }

      if (points.length >= 2) {
        series.push({
          agent: agentName,
          color: TREND_COLORS[i % TREND_COLORS.length],
          points,
          latestElo: points[points.length - 1].elo,
          earliestElo: points[0].elo,
        });
      }
    }

    if (series.length === 0) return null;

    const range = globalMax - globalMin;
    const padding = Math.max(range * 0.1, 10);
    globalMin = Math.floor(globalMin - padding);
    globalMax = Math.ceil(globalMax + padding);

    return { series, periods, globalMin, globalMax };
  }, [trends, agents]);

  if (isLoading) {
    return (
      <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
        Loading trend data...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 bg-surface border border-red-500/30 rounded-lg text-center">
        <p className="text-red-400 font-theme-data text-sm">
          Failed to load ELO trends. The analytics endpoint may be unavailable.
        </p>
      </div>
    );
  }

  if (!chartData) {
    return (
      <div className="p-8 bg-surface border border-border rounded-lg text-center">
        <p className="text-text-muted font-theme-data">
          Not enough data points to render trends. Run more debate cycles to generate history.
        </p>
      </div>
    );
  }

  const { series, periods, globalMin, globalMax } = chartData;
  const chartWidth = 700;
  const chartHeight = 320;
  const pad = { top: 16, right: 20, bottom: 32, left: 52 };
  const plotW = chartWidth - pad.left - pad.right;
  const plotH = chartHeight - pad.top - pad.bottom;
  const eloRange = globalMax - globalMin || 1;

  function toX(idx: number): number {
    return pad.left + (idx / Math.max(periods.length - 1, 1)) * plotW;
  }

  function toY(elo: number): number {
    return pad.top + plotH - ((elo - globalMin) / eloRange) * plotH;
  }

  // Y-axis ticks
  const yTickCount = 6;
  const yTicks: number[] = [];
  for (let i = 0; i <= yTickCount; i++) {
    yTicks.push(Math.round(globalMin + (eloRange * i) / yTickCount));
  }

  // X-axis labels
  const xLabelInterval = Math.max(1, Math.floor(periods.length / 6));

  return (
    <div className="space-y-4">
      <div className="p-4 bg-surface border border-border rounded-lg">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-theme-data font-bold text-[var(--accent)]">
            ELO RATING TRENDS
          </h3>
          <span className="font-theme-data text-xs text-text-muted">
            Top {series.length} agents | {periods.length} data points
          </span>
        </div>

        <svg
          viewBox={`0 0 ${chartWidth} ${chartHeight}`}
          className="w-full"
          style={{ maxHeight: chartHeight }}
          role="img"
          aria-label="ELO rating trend chart"
        >
          {/* Grid lines */}
          {yTicks.map((tick) => (
            <g key={tick}>
              <line
                x1={pad.left}
                y1={toY(tick)}
                x2={chartWidth - pad.right}
                y2={toY(tick)}
                stroke="var(--border)"
                strokeDasharray="3,3"
                strokeWidth={0.5}
              />
              <text
                x={pad.left - 8}
                y={toY(tick) + 3}
                textAnchor="end"
                fill="var(--text-muted)"
                fontSize={9}
                fontFamily="monospace"
              >
                {tick}
              </text>
            </g>
          ))}

          {/* X-axis labels */}
          {periods.map((period, idx) => {
            if (idx % xLabelInterval !== 0 && idx !== periods.length - 1) return null;
            const parts = period.split('-');
            const label = parts.length >= 3 ? `${parts[1]}/${parts[2]}` : period.slice(-5);
            return (
              <text
                key={period}
                x={toX(idx)}
                y={chartHeight - 6}
                textAnchor="middle"
                fill="var(--text-muted)"
                fontSize={9}
                fontFamily="monospace"
              >
                {label}
              </text>
            );
          })}

          {/* Data lines */}
          {series.map(({ agent, color, points }) => {
            const periodLookup = new Map(periods.map((p, i) => [p, i]));

            const pathParts = points
              .map((pt) => {
                const idx = periodLookup.get(pt.period);
                if (idx === undefined) return null;
                return `${toX(idx)},${toY(pt.elo)}`;
              })
              .filter(Boolean);

            if (pathParts.length < 2) return null;

            const d = `M${pathParts.join('L')}`;
            const lastPoint = points[points.length - 1];
            const lastIdx = periodLookup.get(lastPoint.period);

            return (
              <g key={agent}>
                <path
                  d={d}
                  fill="none"
                  stroke={color}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                  opacity={0.9}
                />
                {lastIdx !== undefined && (
                  <circle
                    cx={toX(lastIdx)}
                    cy={toY(lastPoint.elo)}
                    r={4}
                    fill={color}
                    stroke="var(--bg)"
                    strokeWidth={1.5}
                  />
                )}
              </g>
            );
          })}
        </svg>

        {/* Legend with change indicators */}
        <div className="flex flex-wrap gap-4 mt-3 pt-3 border-t border-border/50">
          {series.map(({ agent, color, latestElo, earliestElo }) => {
            const change = Math.round(latestElo - earliestElo);
            return (
              <div key={agent} className="flex items-center gap-2">
                <span
                  className="w-3 h-3 rounded-full inline-block"
                  style={{ backgroundColor: color }}
                />
                <span className="font-theme-data text-xs text-text">{agent}</span>
                <span
                  className={`font-theme-data text-xs ${change >= 0 ? 'text-[var(--accent)]' : 'text-red-400'}`}
                >
                  ({change >= 0 ? '+' : ''}
                  {change})
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function StatsPanel() {
  const { stats, isLoading, error } = useRankingStats();
  const { agents } = useDomainLeaderboard(null, 50);

  // Derive stats summary from ranking data
  const summary = useMemo(() => {
    if (!agents || agents.length === 0) return null;

    const sorted = [...agents].sort((a, b) => b.elo - a.elo);
    const highest = sorted[0];

    // Find most active (most games)
    const byGames = [...agents].sort((a, b) => {
      const gamesA = a.games || (a.wins || 0) + (a.losses || 0) + (a.draws || 0);
      const gamesB = b.games || (b.wins || 0) + (b.losses || 0) + (b.draws || 0);
      return gamesB - gamesA;
    });
    const mostActive = byGames[0];

    // Find best win rate (minimum 3 games)
    const withGames = agents.filter((a) => {
      const g = a.games || (a.wins || 0) + (a.losses || 0) + (a.draws || 0);
      return g >= 3;
    });
    const byWinRate = [...withGames].sort((a, b) => {
      const wrA = a.win_rate ?? 0;
      const wrB = b.win_rate ?? 0;
      return wrB - wrA;
    });
    const bestWinRate = byWinRate[0] ?? null;

    return { highest, mostActive, bestWinRate };
  }, [agents]);

  if (isLoading) {
    return (
      <div className="text-[var(--accent)] font-theme-data animate-pulse text-center py-12">
        Loading stats...
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8 bg-surface border border-red-500/30 rounded-lg text-center">
        <p className="text-red-400 font-theme-data text-sm">Failed to load ranking stats.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Key Metrics */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="p-4 bg-surface border border-border rounded-lg text-center">
            <div className="text-3xl font-theme-data font-bold text-[var(--accent)]">
              {Math.round(stats.mean_elo)}
            </div>
            <div className="text-xs text-text-muted uppercase font-theme-data">Mean ELO</div>
          </div>
          <div className="p-4 bg-surface border border-border rounded-lg text-center">
            <div className="text-3xl font-theme-data font-bold text-blue-400">
              {Math.round(stats.median_elo)}
            </div>
            <div className="text-xs text-text-muted uppercase font-theme-data">Median ELO</div>
          </div>
          <div className="p-4 bg-surface border border-border rounded-lg text-center">
            <div className="text-3xl font-theme-data font-bold text-purple-400">
              {stats.total_agents}
            </div>
            <div className="text-xs text-text-muted uppercase font-theme-data">Total Agents</div>
          </div>
          <div className="p-4 bg-surface border border-border rounded-lg text-center">
            <div className="text-3xl font-theme-data font-bold text-yellow-400">
              {stats.total_matches}
            </div>
            <div className="text-xs text-text-muted uppercase font-theme-data">Total Matches</div>
          </div>
        </div>
      )}

      {/* Highlights */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Highest Rated */}
          <div className="p-4 bg-surface border border-[var(--accent)]/30 rounded-lg">
            <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
              Highest Rated
            </div>
            <div className="text-lg font-theme-data font-bold text-[var(--accent)]">
              {summary.highest.agent_name}
            </div>
            <div
              className={`text-sm font-theme-data ${getEloColor(Math.round(summary.highest.elo))}`}
            >
              {Math.round(summary.highest.elo)} ELO
            </div>
            <div className="text-xs font-theme-data text-text-muted mt-1">
              {getEloTier(summary.highest.elo)}
            </div>
          </div>

          {/* Most Active */}
          <div className="p-4 bg-surface border border-blue-400/30 rounded-lg">
            <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
              Most Active
            </div>
            <div className="text-lg font-theme-data font-bold text-blue-400">
              {summary.mostActive.agent_name}
            </div>
            <div className="text-sm font-theme-data text-text">
              {summary.mostActive.games ||
                (summary.mostActive.wins || 0) +
                  (summary.mostActive.losses || 0) +
                  (summary.mostActive.draws || 0)}{' '}
              games
            </div>
          </div>

          {/* Best Win Rate */}
          {summary.bestWinRate && (
            <div className="p-4 bg-surface border border-yellow-400/30 rounded-lg">
              <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
                Best Win Rate
              </div>
              <div className="text-lg font-theme-data font-bold text-yellow-400">
                {summary.bestWinRate.agent_name}
              </div>
              <div className="text-sm font-theme-data text-text">
                {Math.round(summary.bestWinRate.win_rate ?? 0)}% win rate
              </div>
            </div>
          )}
        </div>
      )}

      {/* Trending Agents */}
      {stats && (stats.trending_up.length > 0 || stats.trending_down.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Trending Up */}
          {stats.trending_up.length > 0 && (
            <div className="p-4 bg-surface border border-border rounded-lg">
              <h3 className="text-sm font-theme-data font-bold text-[var(--accent)] mb-3">
                TRENDING UP
              </h3>
              <div className="space-y-1">
                {stats.trending_up.map((agent) => (
                  <div key={agent} className="flex items-center gap-2 text-sm font-theme-data">
                    <span className="text-[var(--accent)]">^</span>
                    <Link
                      href={`/agent/${encodeURIComponent(agent)}/`}
                      className="text-text hover:text-[var(--accent)] transition-colors"
                    >
                      {agent}
                    </Link>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Trending Down */}
          {stats.trending_down.length > 0 && (
            <div className="p-4 bg-surface border border-border rounded-lg">
              <h3 className="text-sm font-theme-data font-bold text-red-400 mb-3">TRENDING DOWN</h3>
              <div className="space-y-1">
                {stats.trending_down.map((agent) => (
                  <div key={agent} className="flex items-center gap-2 text-sm font-theme-data">
                    <span className="text-red-400">v</span>
                    <Link
                      href={`/agent/${encodeURIComponent(agent)}/`}
                      className="text-text hover:text-red-400 transition-colors"
                    >
                      {agent}
                    </Link>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Rating Distribution */}
      {stats && stats.rating_distribution && Object.keys(stats.rating_distribution).length > 0 && (
        <div className="p-4 bg-surface border border-border rounded-lg">
          <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-4">
            Rating Distribution
          </h3>
          <div className="space-y-2">
            {Object.entries(stats.rating_distribution)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([bracket, count]) => {
                const maxCount = Math.max(...Object.values(stats.rating_distribution));
                const pct = maxCount > 0 ? (count / maxCount) * 100 : 0;
                return (
                  <div key={bracket} className="flex items-center gap-3">
                    <span className="text-xs font-theme-data text-text-muted w-24 shrink-0 text-right">
                      {bracket}
                    </span>
                    <div className="flex-1 bg-bg rounded-full h-4 overflow-hidden">
                      <div
                        className="h-full bg-[var(--accent)]/60 rounded-full transition-all"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                    <span className="text-xs font-theme-data text-text w-8 text-right">
                      {count}
                    </span>
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Main Page
// ============================================================================

export default function EloAnalyticsPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('rankings');

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
            <div className="flex items-center gap-3">
              <Link
                href="/leaderboard"
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [LEADERBOARD]
              </Link>
              <BackendSelector compact />
              <ThemeToggle />
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} ELO ANALYTICS
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Deep analytics for agent ELO ratings. Track rankings, domain-specific performance,
              historical trends, and statistical summaries across the debate ecosystem.
            </p>
          </div>

          {/* Tabs */}
          <div className="flex gap-2 mb-6">
            {TABS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setActiveTab(key)}
                className={`px-4 py-2 text-sm font-theme-data rounded border transition-colors ${
                  activeTab === key
                    ? 'bg-[var(--accent)]/20 border-[var(--accent)] text-[var(--accent)]'
                    : 'border-border text-text-muted hover:border-[var(--accent)]/50'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {activeTab === 'rankings' && (
            <PanelErrorBoundary panelName="ELO Rankings">
              <RankingsPanel />
            </PanelErrorBoundary>
          )}

          {activeTab === 'domains' && (
            <PanelErrorBoundary panelName="Domain Leaderboards">
              <DomainsPanel />
            </PanelErrorBoundary>
          )}

          {activeTab === 'trends' && (
            <PanelErrorBoundary panelName="ELO Trends">
              <TrendsPanel />
            </PanelErrorBoundary>
          )}

          {activeTab === 'stats' && (
            <PanelErrorBoundary panelName="Ranking Stats">
              <StatsPanel />
            </PanelErrorBoundary>
          )}
        </div>

        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // ELO ANALYTICS</p>
        </footer>
      </main>
    </>
  );
}
