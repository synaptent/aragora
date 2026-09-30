'use client';

import { memo, useMemo } from 'react';
import { useEloTrends } from '@/hooks/useEloAnalytics';

// Agent color palette for the chart lines
const AGENT_COLORS = [
  'var(--acid-green)',
  'var(--acid-cyan)',
  'var(--acid-magenta)',
  'var(--acid-yellow)',
  'var(--gold)',
];

interface EloTrendChartProps {
  /** Maximum number of data points to display */
  maxPoints?: number;
  /** Chart height in pixels */
  height?: number;
}

function EloTrendChartComponent({ maxPoints = 30, height = 240 }: EloTrendChartProps) {
  const { trends, agents, isLoading, error } = useEloTrends(undefined, 'daily');

  const chartData = useMemo(() => {
    if (!trends || agents.length === 0) return null;

    // Collect all unique periods across all agents, sorted chronologically
    const periodSet = new Set<string>();
    for (const agentName of agents.slice(0, 5)) {
      const agentTrend = trends[agentName];
      if (agentTrend) {
        for (const point of agentTrend) {
          periodSet.add(point.period);
        }
      }
    }

    const periods = Array.from(periodSet).sort().slice(-maxPoints);
    if (periods.length < 2) return null;

    // Build series for each agent
    const series: Array<{
      agent: string;
      color: string;
      points: Array<{ period: string; elo: number }>;
    }> = [];

    let globalMin = Infinity;
    let globalMax = -Infinity;

    for (let i = 0; i < Math.min(agents.length, 5); i++) {
      const agentName = agents[i];
      const agentTrend = trends[agentName];
      if (!agentTrend || agentTrend.length === 0) continue;

      // Create a lookup by period
      const lookup = new Map<string, number>();
      for (const pt of agentTrend) {
        lookup.set(pt.period, pt.elo);
      }

      // Map to our period axis, interpolating gaps with last known value
      const points: Array<{ period: string; elo: number }> = [];
      let lastElo: number | null = null;

      for (const period of periods) {
        const elo: number | null = lookup.get(period) ?? lastElo;
        if (elo !== null && elo !== undefined) {
          points.push({ period, elo });
          lastElo = elo;
          if (elo < globalMin) globalMin = elo;
          if (elo > globalMax) globalMax = elo;
        }
      }

      if (points.length >= 2) {
        series.push({ agent: agentName, color: AGENT_COLORS[i % AGENT_COLORS.length], points });
      }
    }

    if (series.length === 0) return null;

    // Add some padding to the range
    const range = globalMax - globalMin;
    const padding = Math.max(range * 0.1, 10);
    globalMin = Math.floor(globalMin - padding);
    globalMax = Math.ceil(globalMax + padding);

    return { series, periods, globalMin, globalMax };
  }, [trends, agents, maxPoints]);

  if (isLoading) {
    return (
      <div className="card p-4 animate-pulse">
        <div className="h-4 bg-surface rounded w-40 mb-3" />
        <div className="bg-surface rounded" style={{ height }} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-4">
        <h4 className="font-theme-data text-xs text-[var(--accent)] mb-2">ELO Rating Trends</h4>
        <p className="text-text-muted font-theme-data text-xs">
          Unable to load trend data. The analytics endpoint may be unavailable.
        </p>
      </div>
    );
  }

  if (!chartData) {
    return (
      <div className="card p-4">
        <h4 className="font-theme-data text-xs text-[var(--accent)] mb-2">ELO Rating Trends</h4>
        <p className="text-text-muted font-theme-data text-xs">
          Not enough data points to render trends. Run more debate cycles to generate history.
        </p>
      </div>
    );
  }

  const { series, periods, globalMin, globalMax } = chartData;
  const chartWidth = 600;
  const chartPadding = { top: 10, right: 16, bottom: 28, left: 48 };
  const plotWidth = chartWidth - chartPadding.left - chartPadding.right;
  const plotHeight = height - chartPadding.top - chartPadding.bottom;
  const eloRange = globalMax - globalMin || 1;

  // Convert data point to SVG coordinates
  function toX(idx: number): number {
    return chartPadding.left + (idx / Math.max(periods.length - 1, 1)) * plotWidth;
  }

  function toY(elo: number): number {
    return chartPadding.top + plotHeight - ((elo - globalMin) / eloRange) * plotHeight;
  }

  // Build Y-axis ticks
  const yTickCount = 5;
  const yTicks: number[] = [];
  for (let i = 0; i <= yTickCount; i++) {
    yTicks.push(Math.round(globalMin + (eloRange * i) / yTickCount));
  }

  // Build X-axis labels (show every Nth period)
  const xLabelInterval = Math.max(1, Math.floor(periods.length / 5));

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <h4 className="font-theme-data text-xs text-[var(--accent)]">ELO Rating Trends</h4>
        <span className="font-theme-data text-[10px] text-text-muted">
          Top {series.length} agents | Last {periods.length} data points
        </span>
      </div>

      <svg
        viewBox={`0 0 ${chartWidth} ${height}`}
        className="w-full"
        style={{ maxHeight: height }}
        role="img"
        aria-label="ELO rating trend chart showing top agent performance over time"
      >
        {/* Grid lines */}
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              x1={chartPadding.left}
              y1={toY(tick)}
              x2={chartWidth - chartPadding.right}
              y2={toY(tick)}
              stroke="var(--border)"
              strokeDasharray="3,3"
              strokeWidth={0.5}
            />
            <text
              x={chartPadding.left - 6}
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
          // Format period: "2026-02-15" -> "02/15"
          const parts = period.split('-');
          const label = parts.length >= 3 ? `${parts[1]}/${parts[2]}` : period.slice(-5);
          return (
            <text
              key={period}
              x={toX(idx)}
              y={height - 4}
              textAnchor="middle"
              fill="var(--text-muted)"
              fontSize={8}
              fontFamily="monospace"
            >
              {label}
            </text>
          );
        })}

        {/* Data lines */}
        {series.map(({ agent, color, points }) => {
          // Map points to the period index
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
                strokeWidth={1.5}
                strokeLinejoin="round"
                strokeLinecap="round"
                opacity={0.9}
              />
              {/* End-point dot */}
              {lastIdx !== undefined && (
                <circle
                  cx={toX(lastIdx)}
                  cy={toY(lastPoint.elo)}
                  r={3}
                  fill={color}
                  stroke="var(--bg)"
                  strokeWidth={1}
                />
              )}
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mt-2">
        {series.map(({ agent, color }) => (
          <div key={agent} className="flex items-center gap-1.5">
            <span
              className="w-2.5 h-2.5 rounded-full inline-block"
              style={{ backgroundColor: color }}
            />
            <span className="font-theme-data text-[10px] text-text">{agent}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export const EloTrendChart = memo(EloTrendChartComponent);
