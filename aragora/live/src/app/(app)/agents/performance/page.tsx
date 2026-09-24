'use client';

import { useState, useMemo } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { TrustBadge } from '@/components/TrustBadge';
import { useAgentPerformance, type AgentPerformanceEntry } from '@/hooks/useSystemIntelligence';
import { useSWRFetch } from '@/hooks/useSWRFetch';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DebateSummaryResponse {
  data?: {
    total_debates?: number;
    avg_duration_ms?: number;
    consensus_rate?: number;
    avg_rounds?: number;
  };
}

// ---------------------------------------------------------------------------
// Sparkline SVG
// ---------------------------------------------------------------------------

function EloSparkline({
  points,
  width = 120,
  height = 32,
}: {
  points: { date: string; elo: number }[];
  width?: number;
  height?: number;
}) {
  if (points.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-[10px] text-[var(--text-muted)] font-theme-data"
        style={{ width, height }}
      >
        No history
      </div>
    );
  }

  const elos = points.map((p) => p.elo);
  const min = Math.min(...elos);
  const max = Math.max(...elos);
  const range = max - min || 1;
  const pad = 2;

  const pathPoints = points.map((p, i) => {
    const x = pad + (i / (points.length - 1)) * (width - 2 * pad);
    const y = height - pad - ((p.elo - min) / range) * (height - 2 * pad);
    return `${x},${y}`;
  });

  const trend = elos[elos.length - 1] - elos[0];
  const color = trend >= 0 ? 'var(--acid-green)' : '#f87171';

  return (
    <svg width={width} height={height} className="block">
      <polyline
        points={pathPoints.join(' ')}
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Endpoint dot */}
      {pathPoints.length > 0 && (
        <circle
          cx={pathPoints[pathPoints.length - 1].split(',')[0]}
          cy={pathPoints[pathPoints.length - 1].split(',')[1]}
          r={2}
          fill={color}
        />
      )}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Model Comparison
// ---------------------------------------------------------------------------

function ModelComparisonChart({ agents }: { agents: AgentPerformanceEntry[] }) {
  const grouped = useMemo(() => {
    const map: Record<
      string,
      { totalElo: number; totalWinRate: number; totalCal: number; count: number }
    > = {};
    agents.forEach((a) => {
      // Extract model provider from agent name (e.g., "claude-opus" -> "claude", "gpt-4" -> "gpt")
      const provider = a.name.split('-')[0] || a.name;
      if (!map[provider]) {
        map[provider] = { totalElo: 0, totalWinRate: 0, totalCal: 0, count: 0 };
      }
      map[provider].totalElo += a.elo;
      map[provider].totalWinRate += a.winRate;
      map[provider].totalCal += a.calibration;
      map[provider].count += 1;
    });
    return Object.entries(map)
      .map(([provider, stats]) => ({
        provider,
        avgElo: Math.round(stats.totalElo / stats.count),
        avgWinRate: stats.totalWinRate / stats.count,
        avgCalibration: stats.totalCal / stats.count,
        agentCount: stats.count,
      }))
      .sort((a, b) => b.avgElo - a.avgElo);
  }, [agents]);

  if (grouped.length === 0) return null;

  const maxElo = Math.max(...grouped.map((g) => g.avgElo));

  return (
    <div className="space-y-3">
      {grouped.map((g) => (
        <div key={g.provider} className="p-3 bg-[var(--bg)] border border-[var(--border)] rounded">
          <div className="flex items-center justify-between mb-2">
            <div>
              <span className="font-theme-data text-sm text-[var(--acid-cyan)] uppercase">
                {g.provider}
              </span>
              <span className="text-[10px] text-[var(--text-muted)] ml-2">
                ({g.agentCount} agents)
              </span>
            </div>
            <span className="font-theme-data text-sm text-purple-400">{g.avgElo}</span>
          </div>
          {/* ELO bar */}
          <div className="h-2 bg-[var(--surface)] rounded-full overflow-hidden mb-2">
            <div
              className="h-full bg-purple-500/60 rounded-full transition-all"
              style={{ width: `${(g.avgElo / maxElo) * 100}%` }}
            />
          </div>
          <div className="flex gap-4 text-[10px] font-theme-data text-[var(--text-muted)]">
            <span>
              Win Rate:{' '}
              <span className={g.avgWinRate >= 0.5 ? 'text-[var(--acid-green)]' : 'text-red-400'}>
                {(g.avgWinRate * 100).toFixed(1)}%
              </span>
            </span>
            <span>
              Calibration:{' '}
              <span className="text-[var(--acid-cyan)]">
                {(g.avgCalibration * 100).toFixed(0)}%
              </span>
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Domain Heatmap
// ---------------------------------------------------------------------------

function DomainHeatmap({ agents }: { agents: AgentPerformanceEntry[] }) {
  const domainData = useMemo(() => {
    const map: Record<string, number> = {};
    agents.forEach((a) => {
      a.domains.forEach((d) => {
        map[d] = (map[d] || 0) + 1;
      });
    });
    return Object.entries(map)
      .sort((a, b) => b[1] - a[1])
      .slice(0, 20);
  }, [agents]);

  if (domainData.length === 0) {
    return (
      <p className="text-sm text-[var(--text-muted)] font-theme-data">No domain data available.</p>
    );
  }

  const maxCount = domainData[0][1];

  return (
    <div className="flex flex-wrap gap-2">
      {domainData.map(([domain, count]) => {
        const intensity = Math.round((count / maxCount) * 100);
        return (
          <div
            key={domain}
            className="px-2.5 py-1.5 rounded font-theme-data text-xs border border-[var(--acid-green)]/20"
            style={{
              backgroundColor: `color-mix(in srgb, var(--acid-green) ${intensity}%, transparent)`,
              color: intensity > 50 ? 'var(--bg)' : 'var(--acid-green)',
            }}
          >
            {domain} <span className="opacity-70">({count})</span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type SortKey = 'elo' | 'winRate' | 'calibration' | 'name';

export default function AgentPerformancePage() {
  const { agents, isLoading, error } = useAgentPerformance();
  const [sortKey, setSortKey] = useState<SortKey>('elo');
  const [sortAsc, setSortAsc] = useState(false);
  const [filterDomain, setFilterDomain] = useState('');

  // Debate summary stats
  const { data: debateSummary } = useSWRFetch<DebateSummaryResponse>(
    '/api/v1/analytics/debates/summary',
    { refreshInterval: 60000 },
  );

  const allDomains = useMemo(() => {
    const set = new Set<string>();
    agents.forEach((a) => a.domains.forEach((d) => set.add(d)));
    return Array.from(set).sort();
  }, [agents]);

  const filtered = useMemo(() => {
    let list = [...agents];
    if (filterDomain) {
      list = list.filter((a) => a.domains.includes(filterDomain));
    }
    list.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case 'elo':
          cmp = a.elo - b.elo;
          break;
        case 'winRate':
          cmp = a.winRate - b.winRate;
          break;
        case 'calibration':
          cmp = a.calibration - b.calibration;
          break;
        case 'name':
          cmp = a.name.localeCompare(b.name);
          break;
      }
      return sortAsc ? cmp : -cmp;
    });
    return list;
  }, [agents, sortKey, sortAsc, filterDomain]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const sortIndicator = (key: SortKey) => {
    if (sortKey !== key) return '';
    return sortAsc ? ' \u2191' : ' \u2193';
  };

  // Summary stats
  const avgElo =
    agents.length > 0 ? Math.round(agents.reduce((s, a) => s + a.elo, 0) / agents.length) : 0;
  const avgWinRate =
    agents.length > 0 ? agents.reduce((s, a) => s + a.winRate, 0) / agents.length : 0;
  const avgCalibration =
    agents.length > 0 ? agents.reduce((s, a) => s + a.calibration, 0) / agents.length : 0;

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-2">
              <Link
                href="/agents"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                Agents
              </Link>
              <span className="text-[var(--text-muted)]">/</span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">Performance</span>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--acid-green)]">
              {'>'} AGENT PERFORMANCE ANALYTICS
            </h1>
            <p className="text-xs text-[var(--text-muted)] font-theme-data mt-1">
              Deep-dive into agent ELO trends, model comparisons, calibration accuracy, and domain
              strengths
            </p>
          </div>

          {/* Error State */}
          {error && (
            <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
              Failed to load agent performance data.
            </div>
          )}

          {/* Summary Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4 mb-6">
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-[var(--acid-green)]">
                {agents.length}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Agents
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-purple-400">{avgElo}</div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Avg ELO
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div
                className={`text-2xl font-theme-data ${avgWinRate >= 0.5 ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
              >
                {(avgWinRate * 100).toFixed(1)}%
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Avg Win Rate
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                {(avgCalibration * 100).toFixed(0)}%
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Avg Calibration
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-yellow-400">
                {debateSummary?.data?.total_debates ?? '-'}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Total Debates
              </div>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)] text-center">
              <div className="text-2xl font-theme-data text-[var(--text)]">
                {debateSummary?.data?.consensus_rate != null
                  ? `${(debateSummary.data.consensus_rate * 100).toFixed(0)}%`
                  : '-'}
              </div>
              <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                Consensus Rate
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-6">
            {/* Model Comparison */}
            <div className="lg:col-span-2">
              <PanelErrorBoundary panelName="Model Comparison">
                <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
                  <h2 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                    Model Provider Comparison
                  </h2>
                  {isLoading ? (
                    <div className="h-32 flex items-center justify-center text-[var(--text-muted)] font-theme-data animate-pulse">
                      Loading...
                    </div>
                  ) : (
                    <ModelComparisonChart agents={agents} />
                  )}
                </div>
              </PanelErrorBoundary>
            </div>

            {/* Domain Heatmap */}
            <div>
              <PanelErrorBoundary panelName="Domain Heatmap">
                <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
                  <h2 className="text-sm font-theme-data text-[var(--acid-green)] uppercase mb-4">
                    Domain Expertise
                  </h2>
                  {isLoading ? (
                    <div className="h-32 flex items-center justify-center text-[var(--text-muted)] font-theme-data animate-pulse">
                      Loading...
                    </div>
                  ) : (
                    <DomainHeatmap agents={agents} />
                  )}
                </div>
              </PanelErrorBoundary>
            </div>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-3 mb-4">
            <select
              value={filterDomain}
              onChange={(e) => setFilterDomain(e.target.value)}
              className="px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
            >
              <option value="">All Domains</option>
              {allDomains.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
              {filtered.length} of {agents.length} agents
            </span>
          </div>

          {/* Agent Performance Table */}
          <PanelErrorBoundary panelName="Agent Performance Table">
            <div className="bg-[var(--surface)] border border-[var(--border)] overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-[10px] font-theme-data text-[var(--text-muted)] uppercase border-b border-[var(--border)]">
                      <th
                        className="px-4 py-3 cursor-pointer hover:text-[var(--acid-green)] transition-colors"
                        onClick={() => handleSort('name')}
                      >
                        Agent{sortIndicator('name')}
                      </th>
                      <th
                        className="px-4 py-3 cursor-pointer hover:text-[var(--acid-green)] transition-colors"
                        onClick={() => handleSort('elo')}
                      >
                        ELO{sortIndicator('elo')}
                      </th>
                      <th className="px-4 py-3">Trend</th>
                      <th
                        className="px-4 py-3 cursor-pointer hover:text-[var(--acid-green)] transition-colors"
                        onClick={() => handleSort('winRate')}
                      >
                        Win Rate{sortIndicator('winRate')}
                      </th>
                      <th
                        className="px-4 py-3 cursor-pointer hover:text-[var(--acid-green)] transition-colors"
                        onClick={() => handleSort('calibration')}
                      >
                        Calibration{sortIndicator('calibration')}
                      </th>
                      <th className="px-4 py-3">Domains</th>
                    </tr>
                  </thead>
                  <tbody>
                    {isLoading ? (
                      <tr>
                        <td
                          colSpan={6}
                          className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data animate-pulse"
                        >
                          Loading agent data...
                        </td>
                      </tr>
                    ) : filtered.length === 0 ? (
                      <tr>
                        <td
                          colSpan={6}
                          className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data"
                        >
                          No agents match the current filters.
                        </td>
                      </tr>
                    ) : (
                      filtered.map((agent) => (
                        <tr
                          key={agent.id}
                          className="border-b border-[var(--border)]/50 hover:bg-[var(--acid-green)]/5 transition-colors"
                        >
                          <td className="px-4 py-3">
                            <div className="font-theme-data text-xs text-[var(--acid-cyan)] flex items-center gap-1.5">
                              {agent.name}
                              <TrustBadge calibration={agent.calibrationData ?? null} size="sm" />
                            </div>
                            <div className="text-[10px] text-[var(--text-muted)]">{agent.id}</div>
                          </td>
                          <td className="px-4 py-3 font-theme-data text-purple-400 font-bold">
                            {Math.round(agent.elo)}
                          </td>
                          <td className="px-4 py-3">
                            <EloSparkline points={agent.eloHistory} />
                          </td>
                          <td className="px-4 py-3">
                            <span
                              className={`font-theme-data ${agent.winRate >= 0.5 ? 'text-[var(--acid-green)]' : 'text-red-400'}`}
                            >
                              {(agent.winRate * 100).toFixed(1)}%
                            </span>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex items-center gap-2">
                              <div className="w-16 h-1.5 bg-[var(--bg)] rounded-full overflow-hidden">
                                <div
                                  className="h-full rounded-full bg-[var(--acid-cyan)]"
                                  style={{ width: `${agent.calibration * 100}%` }}
                                />
                              </div>
                              <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                                {(agent.calibration * 100).toFixed(0)}%
                              </span>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex gap-1 flex-wrap">
                              {agent.domains.slice(0, 3).map((d) => (
                                <span
                                  key={d}
                                  className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] rounded cursor-pointer hover:bg-[var(--acid-green)]/20"
                                  onClick={() => setFilterDomain(d)}
                                >
                                  {d}
                                </span>
                              ))}
                              {agent.domains.length > 3 && (
                                <span className="text-[10px] text-[var(--text-muted)]">
                                  +{agent.domains.length - 3}
                                </span>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </PanelErrorBoundary>

          {/* Quick Links */}
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/agents"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Agent Leaderboard
            </Link>
            <Link
              href="/calibration"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Calibration Details
            </Link>
            <Link
              href="/admin/intelligence"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              System Intelligence
            </Link>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
            {'='.repeat(40)}
          </div>
          <p className="text-[var(--text-muted)]">{'>'} ARAGORA // AGENT PERFORMANCE</p>
        </footer>
      </main>
    </>
  );
}
