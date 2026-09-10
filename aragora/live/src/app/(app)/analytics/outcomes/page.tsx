'use client';

import { useState, useMemo } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { MetricCard, TrendChart, type DataPoint } from '@/components/analytics';
import {
  useOutcomeAnalytics,
  type OutcomePeriod,
  type AgentLeaderboardEntry,
  type DecisionHistoryEntry,
  type CalibrationPoint,
} from '@/hooks/useOutcomeAnalytics';

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

function qualityColor(score: number): string {
  if (score >= 75) return 'text-[var(--accent)]';
  if (score >= 50) return 'text-[var(--acid-yellow)]';
  return 'text-[var(--crimson)]';
}

function qualityBg(score: number): string {
  if (score >= 75) return 'bg-[var(--accent)]/60';
  if (score >= 50) return 'bg-acid-yellow/60';
  return 'bg-[var(--crimson)]/60';
}

// ============================================================================
// Sub-components
// ============================================================================

function PeriodSelector({
  value,
  onChange,
}: {
  value: OutcomePeriod;
  onChange: (v: OutcomePeriod) => void;
}) {
  const options: OutcomePeriod[] = ['7d', '30d', '90d', '365d'];

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

/** Quality Score gauge */
function QualityGauge({ score, change }: { score: number; change: number | null }) {
  const circumference = 2 * Math.PI * 60;
  const pct = Math.min(score / 100, 1.0);
  const dashLen = pct * circumference;

  const strokeColor = score >= 75 ? '#39FF14' : score >= 50 ? '#FFD700' : '#DC143C';

  return (
    <div className="flex flex-col items-center">
      <svg viewBox="0 0 160 160" className="w-40 h-40">
        {/* Track */}
        <circle cx="80" cy="80" r="60" fill="none" stroke="#374151" strokeWidth="12" />
        {/* Value arc */}
        <circle
          cx="80"
          cy="80"
          r="60"
          fill="none"
          stroke={strokeColor}
          strokeWidth="12"
          strokeDasharray={`${dashLen} ${circumference - dashLen}`}
          strokeDashoffset={circumference * 0.25}
          strokeLinecap="round"
          transform="rotate(-90 80 80)"
          className="transition-all duration-700"
        />
        {/* Center label */}
        <text
          x="80"
          y="75"
          textAnchor="middle"
          fill={strokeColor}
          fontSize="28"
          fontFamily="monospace"
          fontWeight="bold"
        >
          {score.toFixed(0)}
        </text>
        <text
          x="80"
          y="95"
          textAnchor="middle"
          className="fill-text-muted"
          fontSize="10"
          fontFamily="monospace"
        >
          QUALITY SCORE
        </text>
      </svg>
      {change !== null && (
        <div
          className={`font-theme-data text-xs mt-1 ${change >= 0 ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'}`}
        >
          {change >= 0 ? '+' : ''}
          {change.toFixed(1)}% vs prev
        </div>
      )}
    </div>
  );
}

/** Agent performance leaderboard with ELO + Brier */
function AgentPerformanceTable({
  agents,
  loading,
}: {
  agents: AgentLeaderboardEntry[];
  loading: boolean;
}) {
  type SortKey = 'rank' | 'elo' | 'brier_score' | 'win_rate' | 'debates';
  const [sortKey, setSortKey] = useState<SortKey>('rank');
  const [sortAsc, setSortAsc] = useState(true);

  const sorted = useMemo(() => {
    const copy = [...agents];
    copy.sort((a, b) => {
      let av: number;
      let bv: number;
      switch (sortKey) {
        case 'rank':
          av = a.rank;
          bv = b.rank;
          break;
        case 'elo':
          av = a.elo;
          bv = b.elo;
          break;
        case 'brier_score':
          av = a.brier_score ?? 999;
          bv = b.brier_score ?? 999;
          break;
        case 'win_rate':
          av = a.win_rate;
          bv = b.win_rate;
          break;
        case 'debates':
          av = a.debates;
          bv = b.debates;
          break;
        default:
          return 0;
      }
      return sortAsc ? av - bv : bv - av;
    });
    return copy;
  }, [agents, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(key === 'rank' || key === 'brier_score');
    }
  };

  const sortIndicator = (key: SortKey) => (sortKey === key ? (sortAsc ? ' ^' : ' v') : '');

  if (loading) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
          {'>'} AGENT PERFORMANCE LEADERBOARD
        </h3>
        <div className="animate-pulse space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-10 bg-surface rounded" />
          ))}
        </div>
      </div>
    );
  }

  if (agents.length === 0) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
          {'>'} AGENT PERFORMANCE LEADERBOARD
        </h3>
        <p className="text-text-muted font-theme-data text-sm text-center py-8">
          No agent performance data yet. Run debates to see ELO ratings, Brier scores, and
          calibration accuracy.
        </p>
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="p-4 border-b border-[var(--accent)]/20">
        <h3 className="font-theme-data text-sm text-[var(--accent)]">
          {'>'} AGENT PERFORMANCE LEADERBOARD
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-theme-data text-xs">
          <thead>
            <tr className="border-b border-[var(--accent)]/20 bg-[var(--accent)]/5">
              {(
                [
                  ['rank', 'Rank', 'text-left'],
                  [null, 'Agent', 'text-left'],
                  ['elo', 'ELO', 'text-right'],
                  ['win_rate', 'Win Rate', 'text-right'],
                  ['debates', 'Debates', 'text-right'],
                  ['brier_score', 'Brier Score', 'text-right'],
                  [null, 'Calibration', 'text-right'],
                ] as [SortKey | null, string, string][]
              ).map(([key, label, align]) => (
                <th
                  key={label}
                  onClick={key ? () => handleSort(key) : undefined}
                  className={`p-3 text-text-muted ${align} ${
                    key ? 'cursor-pointer hover:text-[var(--accent)] transition-colors' : ''
                  }`}
                >
                  {label}
                  {key ? sortIndicator(key) : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((agent, i) => (
              <tr
                key={agent.agent_id}
                className={`border-b border-[var(--accent)]/10 hover:bg-[var(--accent)]/5 transition-colors ${
                  i % 2 === 0 ? 'bg-[var(--accent)]/[0.02]' : ''
                }`}
              >
                <td className="p-3">
                  <span
                    className={`font-bold ${
                      agent.rank === 1
                        ? 'text-[var(--acid-yellow)]'
                        : agent.rank === 2
                          ? 'text-gray-300'
                          : agent.rank === 3
                            ? 'text-orange-400'
                            : 'text-text-muted'
                    }`}
                  >
                    [{agent.rank}]
                  </span>
                </td>
                <td className="p-3">
                  <div className="flex flex-col">
                    <span className="text-[var(--acid-cyan)]">{agent.agent_name}</span>
                    {agent.model && (
                      <span className="text-[10px] text-text-muted">{agent.model}</span>
                    )}
                  </div>
                </td>
                <td className="p-3 text-right">
                  <span className="text-purple-400">{agent.elo.toFixed(0)}</span>
                  {agent.elo_change !== 0 && (
                    <span
                      className={`ml-1 text-[10px] ${
                        agent.elo_change > 0 ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'
                      }`}
                    >
                      {agent.elo_change > 0 ? '+' : ''}
                      {agent.elo_change.toFixed(0)}
                    </span>
                  )}
                </td>
                <td className="p-3 text-right">
                  <span
                    className={
                      agent.win_rate >= 50 ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'
                    }
                  >
                    {agent.win_rate.toFixed(1)}%
                  </span>
                </td>
                <td className="p-3 text-right text-text">{agent.debates}</td>
                <td className="p-3 text-right">
                  {agent.brier_score !== null ? (
                    <span
                      className={
                        agent.brier_score <= 0.25
                          ? 'text-[var(--accent)]'
                          : agent.brier_score <= 0.5
                            ? 'text-[var(--acid-yellow)]'
                            : 'text-[var(--crimson)]'
                      }
                    >
                      {agent.brier_score.toFixed(3)}
                    </span>
                  ) : (
                    <span className="text-text-muted">--</span>
                  )}
                </td>
                <td className="p-3 text-right">
                  {agent.calibration_accuracy !== null ? (
                    <span className="text-[var(--acid-cyan)]">
                      {(agent.calibration_accuracy * 100).toFixed(0)}%
                    </span>
                  ) : (
                    <span className="text-text-muted">--</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {/* Summary bar */}
      <div className="p-4 border-t border-[var(--accent)]/20 bg-surface/50">
        <div className="flex justify-between text-xs font-theme-data text-text-muted">
          <span>
            Agents: <span className="text-[var(--accent)]">{agents.length}</span>
          </span>
          <span>
            Avg ELO:{' '}
            <span className="text-purple-400">
              {agents.length > 0
                ? Math.round(agents.reduce((s, a) => s + a.elo, 0) / agents.length)
                : 0}
            </span>
          </span>
          <span>
            Total debates:{' '}
            <span className="text-[var(--acid-cyan)]">
              {agents.reduce((s, a) => s + a.debates, 0)}
            </span>
          </span>
        </div>
      </div>
    </div>
  );
}

/** Decision History Table */
function DecisionHistoryTable({
  decisions,
  total,
  loading,
}: {
  decisions: DecisionHistoryEntry[];
  total: number;
  loading: boolean;
}) {
  type SortKey = 'created_at' | 'quality_score' | 'rounds' | 'agent_count';
  const [sortKey, setSortKey] = useState<SortKey>('created_at');
  const [sortAsc, setSortAsc] = useState(false);

  const sorted = useMemo(() => {
    const copy = [...decisions];
    copy.sort((a, b) => {
      let av: number | string;
      let bv: number | string;
      switch (sortKey) {
        case 'created_at':
          av = a.created_at;
          bv = b.created_at;
          break;
        case 'quality_score':
          av = a.quality_score;
          bv = b.quality_score;
          break;
        case 'rounds':
          av = a.rounds;
          bv = b.rounds;
          break;
        case 'agent_count':
          av = a.agent_count;
          bv = b.agent_count;
          break;
        default:
          return 0;
      }
      if (typeof av === 'string' && typeof bv === 'string') {
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      }
      return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
    });
    return copy;
  }, [decisions, sortKey, sortAsc]);

  const handleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  const sortIndicator = (key: SortKey) => (sortKey === key ? (sortAsc ? ' ^' : ' v') : '');

  if (loading) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
          {'>'} DECISION HISTORY ({total})
        </h3>
        <div className="animate-pulse space-y-3">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-8 bg-surface rounded" />
          ))}
        </div>
      </div>
    );
  }

  if (decisions.length === 0) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-3">
          {'>'} DECISION HISTORY
        </h3>
        <p className="text-text-muted font-theme-data text-sm text-center py-8">
          No decisions yet. Quality scores, rounds, and agent participation will appear here after
          debates.
        </p>
      </div>
    );
  }

  return (
    <div className="card overflow-hidden">
      <div className="p-4 border-b border-[var(--accent)]/20">
        <h3 className="font-theme-data text-sm text-[var(--accent)]">
          {'>'} DECISION HISTORY ({total} total)
        </h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full font-theme-data text-xs">
          <thead>
            <tr className="border-b border-[var(--accent)]/20 bg-[var(--accent)]/5">
              <th className="p-3 text-text-muted text-left">Status</th>
              <th className="p-3 text-text-muted text-left">Task / ID</th>
              <th
                onClick={() => handleSort('quality_score')}
                className="p-3 text-text-muted text-right cursor-pointer hover:text-[var(--accent)] transition-colors"
              >
                Quality{sortIndicator('quality_score')}
              </th>
              <th
                onClick={() => handleSort('rounds')}
                className="p-3 text-text-muted text-right cursor-pointer hover:text-[var(--accent)] transition-colors"
              >
                Rounds{sortIndicator('rounds')}
              </th>
              <th
                onClick={() => handleSort('agent_count')}
                className="p-3 text-text-muted text-right cursor-pointer hover:text-[var(--accent)] transition-colors"
              >
                Agents{sortIndicator('agent_count')}
              </th>
              <th className="p-3 text-text-muted text-right">Duration</th>
              <th
                onClick={() => handleSort('created_at')}
                className="p-3 text-text-muted text-right cursor-pointer hover:text-[var(--accent)] transition-colors"
              >
                Date{sortIndicator('created_at')}
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((d, i) => (
              <tr
                key={d.debate_id}
                className={`border-b border-[var(--accent)]/10 hover:bg-[var(--accent)]/5 transition-colors ${
                  i % 2 === 0 ? 'bg-[var(--accent)]/[0.02]' : ''
                }`}
              >
                <td className="p-3">
                  <span
                    className={
                      d.consensus_reached ? 'text-[var(--accent)]' : 'text-[var(--acid-yellow)]'
                    }
                  >
                    {d.consensus_reached ? '[OK]' : '[--]'}
                  </span>
                </td>
                <td className="p-3 text-text truncate max-w-[200px]">{d.task || d.debate_id}</td>
                <td className="p-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <span className={qualityColor(d.quality_score)}>
                      {d.quality_score.toFixed(0)}
                    </span>
                    <div className="w-12 h-1.5 bg-surface rounded overflow-hidden">
                      <div
                        className={`h-full rounded ${qualityBg(d.quality_score)}`}
                        style={{ width: `${Math.min(d.quality_score, 100)}%` }}
                      />
                    </div>
                  </div>
                </td>
                <td className="p-3 text-right text-text-muted">{d.rounds}</td>
                <td className="p-3 text-right text-text-muted">{d.agent_count}</td>
                <td className="p-3 text-right text-text-muted">
                  {formatDuration(d.duration_seconds)}
                </td>
                <td className="p-3 text-right text-text-muted text-[10px]">
                  {d.created_at ? new Date(d.created_at).toLocaleDateString() : ''}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** Calibration Curve Chart (scatter plot: predicted vs actual) */
function CalibrationCurve({
  points,
  totalObs,
  loading,
}: {
  points: CalibrationPoint[];
  totalObs: number;
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
          {'>'} CALIBRATION CURVE
        </h3>
        <div className="flex items-center justify-center h-64">
          <div className="font-theme-data text-text-muted animate-pulse">Loading...</div>
        </div>
      </div>
    );
  }

  const hasData = points.some((p) => p.count > 0);

  if (!hasData) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
          {'>'} CALIBRATION CURVE
        </h3>
        <div className="flex items-center justify-center h-64">
          <div className="font-theme-data text-text-muted text-sm text-center space-y-2">
            <p>No calibration data yet</p>
            <p className="text-xs text-text-muted/60">
              Complete debates with confidence predictions to see predicted vs actual accuracy.
            </p>
          </div>
        </div>
      </div>
    );
  }

  const chartW = 300;
  const chartH = 250;
  const pad = { top: 20, right: 20, bottom: 40, left: 50 };
  const innerW = chartW - pad.left - pad.right;
  const innerH = chartH - pad.top - pad.bottom;

  const toX = (v: number) => pad.left + v * innerW;
  const toY = (v: number) => pad.top + (1 - v) * innerH;

  // Perfect calibration line
  const perfectLine = `M ${toX(0)} ${toY(0)} L ${toX(1)} ${toY(1)}`;

  // Actual data points
  const dataPoints = points.filter((p) => p.count > 0);

  // Build area path for the actual line
  const actualLine = dataPoints
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${toX(p.predicted)} ${toY(p.actual)}`)
    .join(' ');

  // Max count for circle sizing
  const maxCount = Math.max(...dataPoints.map((p) => p.count), 1);

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-2">{'>'} CALIBRATION CURVE</h3>
      <p className="text-text-muted text-[10px] font-theme-data mb-4">
        Predicted confidence vs actual outcome accuracy ({totalObs} observations)
      </p>

      <div className="flex justify-center">
        <svg
          viewBox={`0 0 ${chartW} ${chartH}`}
          className="w-full max-w-md"
          preserveAspectRatio="xMidYMid meet"
        >
          {/* Grid */}
          {[0, 0.25, 0.5, 0.75, 1.0].map((v) => (
            <g key={`grid-${v}`}>
              <line
                x1={toX(0)}
                y1={toY(v)}
                x2={toX(1)}
                y2={toY(v)}
                stroke="currentColor"
                className="text-[var(--accent)]/10"
                strokeDasharray="3"
              />
              <text
                x={toX(0) - 8}
                y={toY(v) + 3}
                textAnchor="end"
                className="fill-text-muted"
                fontSize="9"
                fontFamily="monospace"
              >
                {(v * 100).toFixed(0)}%
              </text>
              <line
                x1={toX(v)}
                y1={toY(0)}
                x2={toX(v)}
                y2={toY(1)}
                stroke="currentColor"
                className="text-[var(--accent)]/10"
                strokeDasharray="3"
              />
              <text
                x={toX(v)}
                y={toY(0) + 16}
                textAnchor="middle"
                className="fill-text-muted"
                fontSize="9"
                fontFamily="monospace"
              >
                {(v * 100).toFixed(0)}%
              </text>
            </g>
          ))}

          {/* Perfect calibration diagonal */}
          <path
            d={perfectLine}
            fill="none"
            stroke="#6b7280"
            strokeWidth="1"
            strokeDasharray="6 4"
          />

          {/* Actual calibration line */}
          {dataPoints.length > 1 && (
            <path
              d={actualLine}
              fill="none"
              stroke="#39FF14"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Data points (sized by count) */}
          {dataPoints.map((p) => {
            const r = 3 + (p.count / maxCount) * 6;
            return (
              <circle
                key={p.bucket}
                cx={toX(p.predicted)}
                cy={toY(p.actual)}
                r={r}
                fill="#39FF14"
                fillOpacity={0.6}
                stroke="#39FF14"
                strokeWidth={1}
              />
            );
          })}

          {/* Axis labels */}
          <text
            x={toX(0.5)}
            y={chartH - 4}
            textAnchor="middle"
            className="fill-text-muted"
            fontSize="10"
            fontFamily="monospace"
          >
            Predicted Confidence
          </text>
          <text
            x={12}
            y={toY(0.5)}
            textAnchor="middle"
            className="fill-text-muted"
            fontSize="10"
            fontFamily="monospace"
            transform={`rotate(-90, 12, ${toY(0.5)})`}
          >
            Actual Rate
          </text>
        </svg>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-6 mt-4 font-theme-data text-[10px]">
        <div className="flex items-center gap-2">
          <div className="w-4 h-0.5 bg-gray-500" style={{ borderTop: '1px dashed #6b7280' }} />
          <span className="text-text-muted">Perfect calibration</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-4 h-0.5 bg-[var(--accent)]" />
          <span className="text-text-muted">Actual calibration</span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-2 h-2 rounded-full bg-[var(--accent)]/60" />
          <span className="text-text-muted">Size = sample count</span>
        </div>
      </div>
    </div>
  );
}

// ============================================================================
// Main Page
// ============================================================================

export default function OutcomeAnalyticsPage() {
  const [period, setPeriod] = useState<OutcomePeriod>('30d');

  const { quality, agents, history, calibration, isLoading, error } = useOutcomeAnalytics(period);

  // Transform quality trend into DataPoint[] for the TrendChart
  const qualityTrendData: DataPoint[] = useMemo(() => {
    if (!quality?.trend) return [];
    return quality.trend.map((p) => ({
      label: p.timestamp.split('T')[0]?.split('-').slice(1).join('/') ?? '',
      value: p.consensus_rate * 100,
      date: p.timestamp.split('T')[0] ?? '',
    }));
  }, [quality]);

  const convergenceTrendData: DataPoint[] = useMemo(() => {
    if (!quality?.trend) return [];
    return quality.trend.map((p) => ({
      label: p.timestamp.split('T')[0]?.split('-').slice(1).join('/') ?? '',
      value: p.avg_rounds,
      date: p.timestamp.split('T')[0] ?? '',
    }));
  }, [quality]);

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
                {'>'} OUTCOME ANALYTICS
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                Decision quality scores, agent calibration, and convergence trends.
              </p>
            </div>
            <PeriodSelector value={period} onChange={setPeriod} />
          </div>

          {/* Error banner */}
          {error && (
            <div className="mb-6 bg-[var(--crimson)]/10 border border-[var(--crimson)]/30 rounded p-4 text-[var(--crimson)] text-sm font-theme-data">
              Failed to load outcome analytics. The server may be unavailable.
            </div>
          )}

          {/* ---- Quality Score + Overview Cards ---- */}
          <PanelErrorBoundary panelName="Quality Overview">
            <section className="mb-6">
              <h2 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                {'>'} DECISION QUALITY
              </h2>
              <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
                {/* Quality gauge */}
                <div className="md:col-span-1 card p-4 flex items-center justify-center">
                  {isLoading ? (
                    <div className="animate-pulse w-40 h-40 bg-surface rounded-full" />
                  ) : (
                    <QualityGauge
                      score={quality?.quality_score ?? 0}
                      change={quality?.quality_change ?? null}
                    />
                  )}
                </div>

                {/* Metric cards */}
                <div className="md:col-span-4 grid grid-cols-2 md:grid-cols-4 gap-4">
                  <MetricCard
                    title="Total Decisions"
                    value={quality?.total_decisions ?? 0}
                    subtitle={`${period} period`}
                    color="green"
                    loading={isLoading}
                    icon="#"
                  />
                  <MetricCard
                    title="Consensus Rate"
                    value={quality ? `${(quality.consensus_rate * 100).toFixed(1)}%` : '--'}
                    subtitle={`${quality?.completed_decisions ?? 0} completed`}
                    color="cyan"
                    loading={isLoading}
                    icon="%"
                  />
                  <MetricCard
                    title="Avg Rounds"
                    value={quality?.avg_rounds?.toFixed(1) ?? '--'}
                    subtitle="to conclusion"
                    color="yellow"
                    loading={isLoading}
                    icon="~"
                  />
                  <MetricCard
                    title="Completion Rate"
                    value={quality ? formatPct(quality.completion_rate) : '--'}
                    subtitle="debates finished"
                    color="purple"
                    loading={isLoading}
                    icon="*"
                  />
                </div>
              </div>
            </section>
          </PanelErrorBoundary>

          {/* ---- Consensus Quality Chart ---- */}
          <PanelErrorBoundary panelName="Consensus Quality">
            <section className="mb-6">
              <TrendChart
                title={`> CONSENSUS RATE TREND (${period})`}
                data={qualityTrendData}
                type="area"
                color="cyan"
                loading={isLoading}
                showTimeRangeSelector={false}
                height={280}
                formatValue={(v) => `${v.toFixed(1)}%`}
              />
            </section>
          </PanelErrorBoundary>

          {/* ---- Convergence Speed + Calibration ---- */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
            <PanelErrorBoundary panelName="Convergence Speed">
              <TrendChart
                title={`> CONVERGENCE SPEED - AVG ROUNDS (${period})`}
                data={convergenceTrendData}
                type="line"
                color="green"
                loading={isLoading}
                showTimeRangeSelector={false}
                height={240}
                formatValue={(v) => v.toFixed(1)}
              />
            </PanelErrorBoundary>

            <PanelErrorBoundary panelName="Calibration Curve">
              <CalibrationCurve
                points={calibration?.points ?? []}
                totalObs={calibration?.total_observations ?? 0}
                loading={isLoading}
              />
            </PanelErrorBoundary>
          </div>

          {/* ---- Agent Performance Leaderboard ---- */}
          <PanelErrorBoundary panelName="Agent Leaderboard">
            <section className="mb-6">
              <AgentPerformanceTable agents={agents?.agents ?? []} loading={isLoading} />
            </section>
          </PanelErrorBoundary>

          {/* ---- Decision History Table ---- */}
          <PanelErrorBoundary panelName="Decision History">
            <section className="mb-6">
              <DecisionHistoryTable
                decisions={history?.decisions ?? []}
                total={history?.total ?? 0}
                loading={isLoading}
              />
            </section>
          </PanelErrorBoundary>

          {/* Footer */}
          <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
            <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
            <p className="text-text-muted">{'>'} ARAGORA // OUTCOME ANALYTICS DASHBOARD</p>
          </footer>
        </div>
      </main>
    </>
  );
}
