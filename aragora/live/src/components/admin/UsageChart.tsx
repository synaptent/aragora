'use client';

import React, { useState, useMemo } from 'react';

export interface DataPoint {
  label: string;
  value: number;
  date?: string;
}

export type ChartType = 'line' | 'bar';
export type TimeRange = '7d' | '30d' | '90d';

interface UsageChartProps {
  title: string;
  data: DataPoint[];
  type?: ChartType;
  color?: string;
  showTimeRangeSelector?: boolean;
  defaultTimeRange?: TimeRange;
  onTimeRangeChange?: (range: TimeRange) => void;
  formatValue?: (value: number) => string;
  height?: number;
  loading?: boolean;
  className?: string;
}

export function UsageChart({
  title,
  data,
  type = 'line',
  color = 'acid-green',
  showTimeRangeSelector = true,
  defaultTimeRange = '30d',
  onTimeRangeChange,
  formatValue = (v) => v.toLocaleString(),
  height = 200,
  loading = false,
  className = '',
}: UsageChartProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>(defaultTimeRange);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const handleTimeRangeChange = (range: TimeRange) => {
    setTimeRange(range);
    onTimeRangeChange?.(range);
  };

  const { maxValue, minValue, chartData } = useMemo(() => {
    if (data.length === 0) {
      return { maxValue: 100, minValue: 0, chartData: [] };
    }
    const values = data.map((d) => d.value);
    const max = Math.max(...values);
    const min = Math.min(...values);
    return { maxValue: max || 100, minValue: min, chartData: data };
  }, [data]);

  const colorClasses = {
    'acid-green': {
      fill: 'fill-acid-green',
      stroke: 'stroke-acid-green',
      bg: 'bg-[var(--accent)]',
      text: 'text-[var(--accent)]',
    },
    'acid-cyan': {
      fill: 'fill-acid-cyan',
      stroke: 'stroke-acid-cyan',
      bg: 'bg-[var(--acid-cyan)]',
      text: 'text-[var(--acid-cyan)]',
    },
    'acid-yellow': {
      fill: 'fill-acid-yellow',
      stroke: 'stroke-acid-yellow',
      bg: 'bg-acid-yellow',
      text: 'text-[var(--acid-yellow)]',
    },
    'acid-magenta': {
      fill: 'fill-acid-magenta',
      stroke: 'stroke-acid-magenta',
      bg: 'bg-acid-magenta',
      text: 'text-[var(--acid-magenta)]',
    },
  };

  const colors = colorClasses[color as keyof typeof colorClasses] || colorClasses['acid-green'];

  const padding = { top: 20, right: 20, bottom: 30, left: 60 };
  const _chartWidth = 100; // percentage - reserved for future responsive sizing
  const chartHeight = height - padding.top - padding.bottom;

  const getY = (value: number) => {
    const range = maxValue - minValue || 1;
    return chartHeight - ((value - minValue) / range) * chartHeight;
  };

  const renderLineChart = () => {
    if (chartData.length === 0) return null;

    const points = chartData.map((d, i) => {
      const x = (i / Math.max(chartData.length - 1, 1)) * 100;
      const y = getY(d.value);
      return { x, y, ...d };
    });

    const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x}% ${p.y}`).join(' ');
    const areaPath = `${linePath} L 100% ${chartHeight} L 0% ${chartHeight} Z`;

    return (
      <g>
        {/* Area fill */}
        <path d={areaPath} className={`${colors.fill} opacity-10`} />
        {/* Line */}
        <path
          d={linePath}
          fill="none"
          className={`${colors.stroke}`}
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
        {/* Data points */}
        {points.map((p, i) => (
          <g key={i}>
            <circle
              cx={`${p.x}%`}
              cy={p.y}
              r={hoveredIndex === i ? 6 : 4}
              className={`${colors.fill} cursor-pointer transition-all`}
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
            />
          </g>
        ))}
      </g>
    );
  };

  const renderBarChart = () => {
    if (chartData.length === 0) return null;

    const barWidth = (100 / chartData.length) * 0.7;
    const gap = (100 / chartData.length) * 0.15;

    return (
      <g>
        {chartData.map((d, i) => {
          const x = (i / chartData.length) * 100 + gap;
          const barHeight = ((d.value - minValue) / (maxValue - minValue || 1)) * chartHeight;
          const y = chartHeight - barHeight;

          return (
            <rect
              key={i}
              x={`${x}%`}
              y={y}
              width={`${barWidth}%`}
              height={barHeight}
              className={`${colors.fill} ${hoveredIndex === i ? 'opacity-100' : 'opacity-70'} cursor-pointer transition-opacity`}
              rx="2"
              onMouseEnter={() => setHoveredIndex(i)}
              onMouseLeave={() => setHoveredIndex(null)}
            />
          );
        })}
      </g>
    );
  };

  const renderYAxis = () => {
    const steps = 5;
    const labels = [];
    for (let i = 0; i <= steps; i++) {
      const value = minValue + ((maxValue - minValue) / steps) * (steps - i);
      const y = (i / steps) * chartHeight;
      labels.push(
        <g key={i}>
          <line
            x1="0"
            y1={y}
            x2="100%"
            y2={y}
            stroke="currentColor"
            className="text-[var(--accent)]/10"
            strokeDasharray="4"
          />
          <text
            x="-8"
            y={y + 4}
            className="text-text-muted font-theme-data text-[10px]"
            textAnchor="end"
          >
            {formatValue(value)}
          </text>
        </g>,
      );
    }
    return labels;
  };

  const renderXAxis = () => {
    if (chartData.length === 0) return null;

    const step = Math.max(1, Math.floor(chartData.length / 6));
    return chartData
      .filter((_, i) => i % step === 0 || i === chartData.length - 1)
      .map((d, _i, _arr) => {
        const originalIndex = chartData.indexOf(d);
        const x = (originalIndex / Math.max(chartData.length - 1, 1)) * 100;
        return (
          <text
            key={originalIndex}
            x={`${x}%`}
            y={chartHeight + 20}
            className="text-text-muted font-theme-data text-[10px]"
            textAnchor="middle"
          >
            {d.label}
          </text>
        );
      });
  };

  return (
    <div className={`card p-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className={`font-theme-data text-sm ${colors.text}`}>{title}</h3>
        {showTimeRangeSelector && (
          <div className="flex gap-1">
            {(['7d', '30d', '90d'] as TimeRange[]).map((range) => (
              <button
                key={range}
                onClick={() => handleTimeRangeChange(range)}
                className={`px-2 py-1 font-theme-data text-xs rounded transition-colors ${
                  timeRange === range
                    ? `${colors.bg}/20 ${colors.text} border border-current`
                    : 'text-text-muted hover:text-text'
                }`}
              >
                {range}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Chart */}
      {loading ? (
        <div className="flex items-center justify-center" style={{ height }}>
          <div className="font-theme-data text-text-muted animate-pulse">Loading...</div>
        </div>
      ) : chartData.length === 0 ? (
        <div className="flex items-center justify-center" style={{ height }}>
          <div className="font-theme-data text-text-muted">No data available</div>
        </div>
      ) : (
        <div className="relative">
          <svg width="100%" height={height} className="overflow-visible" preserveAspectRatio="none">
            <g transform={`translate(${padding.left}, ${padding.top})`}>
              {renderYAxis()}
              {type === 'line' ? renderLineChart() : renderBarChart()}
              {renderXAxis()}
            </g>
          </svg>

          {/* Tooltip */}
          {hoveredIndex !== null && chartData[hoveredIndex] && (
            <div
              className="absolute z-10 px-2 py-1 bg-surface border border-[var(--accent)]/40 rounded shadow-lg font-theme-data text-xs"
              style={{
                left: `${(hoveredIndex / Math.max(chartData.length - 1, 1)) * 100}%`,
                top: 0,
                transform: 'translateX(-50%)',
              }}
            >
              <div className={colors.text}>{formatValue(chartData[hoveredIndex].value)}</div>
              <div className="text-text-muted">{chartData[hoveredIndex].label}</div>
            </div>
          )}
        </div>
      )}

      {/* Summary Stats */}
      <div className="flex justify-between mt-4 pt-4 border-t border-[var(--accent)]/20">
        <div>
          <div className="font-theme-data text-xs text-text-muted">Min</div>
          <div className="font-theme-data text-sm text-text">{formatValue(minValue)}</div>
        </div>
        <div>
          <div className="font-theme-data text-xs text-text-muted">Max</div>
          <div className="font-theme-data text-sm text-text">{formatValue(maxValue)}</div>
        </div>
        <div>
          <div className="font-theme-data text-xs text-text-muted">Avg</div>
          <div className="font-theme-data text-sm text-text">
            {formatValue(
              chartData.length > 0
                ? chartData.reduce((a, b) => a + b.value, 0) / chartData.length
                : 0,
            )}
          </div>
        </div>
        <div>
          <div className="font-theme-data text-xs text-text-muted">Total</div>
          <div className={`font-theme-data text-sm ${colors.text}`}>
            {formatValue(chartData.reduce((a, b) => a + b.value, 0))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default UsageChart;
