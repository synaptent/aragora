'use client';

import React, { useMemo } from 'react';
import type { DeliberationEvent } from './types';

interface ConsensusFormationChartProps {
  events: DeliberationEvent[];
  height?: number;
}

interface DataPoint {
  round: number;
  consensus: number;
  timestamp: number;
}

export function ConsensusFormationChart({ events, height = 120 }: ConsensusFormationChartProps) {
  const dataPoints = useMemo(() => {
    const points: DataPoint[] = [];

    events
      .filter((e) => e.type === 'consensus_progress' || e.type === 'round_complete')
      .forEach((event) => {
        const data = event.data as { consensus_score?: number; round?: number };
        if (typeof data.consensus_score === 'number' && typeof data.round === 'number') {
          points.push({
            round: data.round,
            consensus: data.consensus_score,
            timestamp: event.timestamp,
          });
        }
      });

    return points.sort((a, b) => a.round - b.round);
  }, [events]);

  if (dataPoints.length === 0) {
    return (
      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="text-xs font-theme-data text-[var(--accent)] mb-2 uppercase">
          {'>'} CONSENSUS FORMATION
        </div>
        <div
          className="flex items-center justify-center text-text-muted font-theme-data text-xs"
          style={{ height }}
        >
          Waiting for consensus data...
        </div>
      </div>
    );
  }

  const maxConsensus = Math.max(...dataPoints.map((p) => p.consensus), 1);
  const width = 280;
  const padding = { top: 10, right: 10, bottom: 20, left: 30 };
  const chartWidth = width - padding.left - padding.right;
  const chartHeight = height - padding.top - padding.bottom;

  const xScale = (round: number) =>
    padding.left + (round / Math.max(dataPoints.length - 1, 1)) * chartWidth;
  const yScale = (consensus: number) =>
    padding.top + chartHeight - (consensus / maxConsensus) * chartHeight;

  const pathData = dataPoints
    .map((point, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(point.consensus)}`)
    .join(' ');

  const areaPathData = `${pathData} L ${xScale(dataPoints.length - 1)} ${padding.top + chartHeight} L ${xScale(0)} ${padding.top + chartHeight} Z`;

  const currentConsensus = dataPoints[dataPoints.length - 1]?.consensus ?? 0;

  return (
    <div className="bg-surface border border-[var(--accent)]/30 p-4">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase">
          {'>'} CONSENSUS FORMATION
        </span>
        <span
          className={`text-sm font-theme-data ${
            currentConsensus >= 0.8
              ? 'text-success'
              : currentConsensus >= 0.5
                ? 'text-[var(--acid-yellow)]'
                : 'text-text-muted'
          }`}
        >
          {Math.round(currentConsensus * 100)}%
        </span>
      </div>

      <svg width={width} height={height} className="w-full">
        {/* Grid lines */}
        {[0.25, 0.5, 0.75, 1].map((threshold) => (
          <g key={threshold}>
            <line
              x1={padding.left}
              y1={yScale(threshold)}
              x2={width - padding.right}
              y2={yScale(threshold)}
              stroke="var(--acid-green)"
              strokeOpacity={0.1}
              strokeDasharray="2,2"
            />
            <text
              x={padding.left - 5}
              y={yScale(threshold)}
              textAnchor="end"
              dominantBaseline="middle"
              className="text-[8px] font-theme-data fill-text-muted"
            >
              {Math.round(threshold * 100)}
            </text>
          </g>
        ))}

        {/* Consensus threshold line at 80% */}
        <line
          x1={padding.left}
          y1={yScale(0.8)}
          x2={width - padding.right}
          y2={yScale(0.8)}
          stroke="var(--acid-cyan)"
          strokeOpacity={0.5}
          strokeDasharray="4,2"
        />

        {/* Area under curve */}
        <path d={areaPathData} fill="var(--acid-green)" fillOpacity={0.1} />

        {/* Line */}
        <path d={pathData} fill="none" stroke="var(--acid-green)" strokeWidth={2} />

        {/* Data points */}
        {dataPoints.map((point, i) => (
          <g key={i}>
            <circle
              cx={xScale(i)}
              cy={yScale(point.consensus)}
              r={3}
              fill="var(--bg)"
              stroke="var(--acid-green)"
              strokeWidth={2}
            />
            <text
              x={xScale(i)}
              y={padding.top + chartHeight + 12}
              textAnchor="middle"
              className="text-[8px] font-theme-data fill-text-muted"
            >
              R{point.round}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}
