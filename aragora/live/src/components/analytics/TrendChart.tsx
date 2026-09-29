'use client';

import React, { useState, useMemo } from 'react';

export interface DataPoint {
  label: string;
  value: number;
  date?: string;
}

export type ChartType = 'line' | 'bar' | 'area';
export type TimeRange = '7d' | '30d' | '90d';

interface TrendChartProps {
  /** Chart title */
  title: string;
  /** Data points to display */
  data: DataPoint[];
  /** Chart type */
  type?: ChartType;
  /** Primary color theme */
  color?: 'green' | 'cyan' | 'yellow' | 'magenta' | 'purple';
  /** Show time range selector */
  showTimeRangeSelector?: boolean;
  /** Default time range */
  defaultTimeRange?: TimeRange;
  /** Callback when time range changes */
  onTimeRangeChange?: (range: TimeRange) => void;
  /** Value formatter function */
  formatValue?: (value: number) => string;
  /** Chart height in pixels */
  height?: number;
  /** Loading state */
  loading?: boolean;
  /** Additional CSS classes */
  className?: string;
  /** Show grid lines */
  showGrid?: boolean;
}

const colorConfig = {
  green: {
    fill: 'fill-acid-green',
    stroke: 'stroke-acid-green',
    bg: 'bg-[var(--accent)]',
    text: 'text-[var(--accent)]',
    fillRgba: 'rgba(57, 255, 20, 0.15)',
  },
  cyan: {
    fill: 'fill-acid-cyan',
    stroke: 'stroke-acid-cyan',
    bg: 'bg-[var(--acid-cyan)]',
    text: 'text-[var(--acid-cyan)]',
    fillRgba: 'rgba(0, 255, 255, 0.15)',
  },
  yellow: {
    fill: 'fill-acid-yellow',
    stroke: 'stroke-acid-yellow',
    bg: 'bg-acid-yellow',
    text: 'text-[var(--acid-yellow)]',
    fillRgba: 'rgba(255, 255, 0, 0.15)',
  },
  magenta: {
    fill: 'fill-acid-magenta',
    stroke: 'stroke-acid-magenta',
    bg: 'bg-acid-magenta',
    text: 'text-[var(--acid-magenta)]',
    fillRgba: 'rgba(255, 0, 255, 0.15)',
  },
  purple: {
    fill: 'fill-purple-500',
    stroke: 'stroke-purple-500',
    bg: 'bg-purple-500',
    text: 'text-purple-400',
    fillRgba: 'rgba(168, 85, 247, 0.15)',
  },
};

export function TrendChart({
  title,
  data,
  type = 'line',
  color = 'green',
  showTimeRangeSelector = true,
  defaultTimeRange = '30d',
  onTimeRangeChange,
  formatValue = (v) => v.toLocaleString(),
  height = 200,
  loading = false,
  className = '',
  showGrid = true,
}: TrendChartProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>(defaultTimeRange);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const colors = colorConfig[color];

  const handleTimeRangeChange = (range: TimeRange) => {
    setTimeRange(range);
    onTimeRangeChange?.(range);
  };

  const { maxValue, minValue, chartData, range } = useMemo(() => {
    if (data.length === 0) {
      return { maxValue: 100, minValue: 0, chartData: [], range: 100 };
    }
    const values = data.map((d) => d.value);
    const max = Math.max(...values);
    const min = Math.min(...values, 0); // Include 0 in min
    return { maxValue: max || 100, minValue: min, chartData: data, range: max - min || 1 };
  }, [data]);

  const padding = { top: 20, right: 20, bottom: 35, left: 55 };
  const chartHeight = height - padding.top - padding.bottom;

  const getY = (value: number): number => {
    return chartHeight - ((value - minValue) / range) * chartHeight;
  };

  const renderLineChart = () => {
    if (chartData.length === 0) return null;

    const points = chartData.map((d, i) => {
      const x = chartData.length === 1 ? 50 : (i / (chartData.length - 1)) * 100;
      const y = getY(d.value);
      return { x, y, ...d };
    });

    const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x}% ${p.y}`).join(' ');

    return (
      <g>
        {/* Line */}
        <path
          d={linePath}
          fill="none"
          className={colors.stroke}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
        {/* Data points */}
        {points.map((p, i) => (
          <circle
            key={i}
            cx={`${p.x}%`}
            cy={p.y}
            r={hoveredIndex === i ? 6 : 4}
            className={`${colors.fill} cursor-pointer transition-all`}
            onMouseEnter={() => setHoveredIndex(i)}
            onMouseLeave={() => setHoveredIndex(null)}
          />
        ))}
      </g>
    );
  };

  const renderAreaChart = () => {
    if (chartData.length === 0) return null;

    const points = chartData.map((d, i) => {
      const x = chartData.length === 1 ? 50 : (i / (chartData.length - 1)) * 100;
      const y = getY(d.value);
      return { x, y, ...d };
    });

    const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x}% ${p.y}`).join(' ');
    const areaPath = `${linePath} L 100% ${chartHeight} L 0% ${chartHeight} Z`;

    return (
      <g>
        {/* Area fill with gradient */}
        <defs>
          <linearGradient id={`gradient-${color}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" style={{ stopColor: colors.fillRgba.replace('0.15', '0.4') }} />
            <stop offset="100%" style={{ stopColor: colors.fillRgba.replace('0.15', '0.05') }} />
          </linearGradient>
        </defs>
        <path d={areaPath} fill={`url(#gradient-${color})`} />
        {/* Line on top */}
        <path
          d={linePath}
          fill="none"
          className={colors.stroke}
          strokeWidth="2"
          vectorEffect="non-scaling-stroke"
        />
        {/* Data points */}
        {points.map((p, i) => (
          <circle
            key={i}
            cx={`${p.x}%`}
            cy={p.y}
            r={hoveredIndex === i ? 6 : 3}
            className={`${colors.fill} cursor-pointer transition-all`}
            onMouseEnter={() => setHoveredIndex(i)}
            onMouseLeave={() => setHoveredIndex(null)}
          />
        ))}
      </g>
    );
  };

  const renderBarChart = () => {
    if (chartData.length === 0) return null;

    const barWidth = (100 / chartData.length) * 0.6;
    const gap = (100 / chartData.length) * 0.2;

    return (
      <g>
        {chartData.map((d, i) => {
          const x = (i / chartData.length) * 100 + gap;
          const barHeight = ((d.value - minValue) / range) * chartHeight;
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

  const renderGrid = () => {
    if (!showGrid) return null;

    const steps = 4;
    const lines = [];
    for (let i = 0; i <= steps; i++) {
      const y = (i / steps) * chartHeight;
      const value = maxValue - ((maxValue - minValue) / steps) * i;
      lines.push(
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
    return lines;
  };

  const renderXAxis = () => {
    if (chartData.length === 0) return null;

    const step = Math.max(1, Math.floor(chartData.length / 6));
    const labels = chartData.filter((_, i) => i % step === 0 || i === chartData.length - 1);

    return labels.map((d) => {
      const originalIndex = chartData.indexOf(d);
      const x = chartData.length === 1 ? 50 : (originalIndex / (chartData.length - 1)) * 100;
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

  const chartRenderer = { line: renderLineChart, area: renderAreaChart, bar: renderBarChart };

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
              {renderGrid()}
              {chartRenderer[type]()}
              {renderXAxis()}
            </g>
          </svg>

          {/* Tooltip */}
          {hoveredIndex !== null && chartData[hoveredIndex] && (
            <div
              className="absolute z-10 px-3 py-2 bg-surface border border-[var(--accent)]/40 rounded shadow-lg font-theme-data text-xs"
              style={{
                left: `calc(${padding.left}px + ${(hoveredIndex / Math.max(chartData.length - 1, 1)) * 100}% * (100% - ${padding.left + padding.right}px) / 100%)`,
                top: padding.top - 10,
                transform: 'translateX(-50%) translateY(-100%)',
              }}
            >
              <div className={colors.text}>{formatValue(chartData[hoveredIndex].value)}</div>
              <div className="text-text-muted">{chartData[hoveredIndex].label}</div>
            </div>
          )}
        </div>
      )}

      {/* Summary Stats */}
      {!loading && chartData.length > 0 && (
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
              {formatValue(chartData.reduce((a, b) => a + b.value, 0) / chartData.length)}
            </div>
          </div>
          <div>
            <div className="font-theme-data text-xs text-text-muted">Total</div>
            <div className={`font-theme-data text-sm ${colors.text}`}>
              {formatValue(chartData.reduce((a, b) => a + b.value, 0))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default TrendChart;
