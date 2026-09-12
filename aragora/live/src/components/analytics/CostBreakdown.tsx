'use client';

import React, { useState, useMemo } from 'react';

export interface CostCategory {
  name: string;
  cost: number;
  tokens?: number;
  percentage?: number;
}

interface CostBreakdownProps {
  /** Cost data by provider or model */
  data: CostCategory[];
  /** Total cost for the period */
  totalCost: number;
  /** Chart title */
  title?: string;
  /** Loading state */
  loading?: boolean;
  /** Subtitle or period label */
  subtitle?: string;
  /** Show token counts */
  showTokens?: boolean;
  /** Additional CSS classes */
  className?: string;
}

const COLORS = [
  { name: 'green', class: 'bg-[var(--accent)]', text: 'text-[var(--accent)]' },
  { name: 'cyan', class: 'bg-[var(--acid-cyan)]', text: 'text-[var(--acid-cyan)]' },
  { name: 'yellow', class: 'bg-acid-yellow', text: 'text-[var(--acid-yellow)]' },
  { name: 'magenta', class: 'bg-acid-magenta', text: 'text-[var(--acid-magenta)]' },
  { name: 'purple', class: 'bg-purple-500', text: 'text-purple-400' },
  { name: 'orange', class: 'bg-orange-500', text: 'text-orange-400' },
  { name: 'pink', class: 'bg-pink-500', text: 'text-pink-400' },
  { name: 'teal', class: 'bg-teal-500', text: 'text-teal-400' },
];

export function CostBreakdown({
  data,
  totalCost,
  title = 'COST BREAKDOWN',
  loading = false,
  subtitle,
  showTokens = true,
  className = '',
}: CostBreakdownProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const processedData = useMemo(() => {
    return data.map((item, index) => ({
      ...item,
      percentage: item.percentage ?? (totalCost > 0 ? (item.cost / totalCost) * 100 : 0),
      color: COLORS[index % COLORS.length],
    }));
  }, [data, totalCost]);

  const formatCurrency = (value: number): string => {
    return `$${value.toFixed(2)}`;
  };

  const formatTokens = (value: number): string => {
    if (value >= 1000000) {
      return `${(value / 1000000).toFixed(1)}M`;
    }
    if (value >= 1000) {
      return `${(value / 1000).toFixed(1)}K`;
    }
    return value.toString();
  };

  if (loading) {
    return (
      <div className={`card p-4 ${className}`}>
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
          {'>'} {title}
        </h3>
        <div className="animate-pulse space-y-4">
          <div className="h-24 bg-surface rounded" />
          <div className="space-y-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-8 bg-surface rounded" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (data.length === 0) {
    return (
      <div className={`card p-4 ${className}`}>
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">
          {'>'} {title}
        </h3>
        <div className="text-center text-text-muted font-theme-data text-sm py-8">
          No cost data available
        </div>
      </div>
    );
  }

  // Calculate angles for pie chart
  let cumulativeAngle = 0;
  const segments = processedData.map((item) => {
    const startAngle = cumulativeAngle;
    const angle = (item.percentage / 100) * 360;
    cumulativeAngle += angle;
    return { ...item, startAngle, angle };
  });

  const createArc = (startAngle: number, angle: number, radius: number = 45): string => {
    const start = (startAngle - 90) * (Math.PI / 180);
    const end = (startAngle + angle - 90) * (Math.PI / 180);
    const x1 = 50 + radius * Math.cos(start);
    const y1 = 50 + radius * Math.sin(start);
    const x2 = 50 + radius * Math.cos(end);
    const y2 = 50 + radius * Math.sin(end);
    const largeArc = angle > 180 ? 1 : 0;
    return `M 50 50 L ${x1} ${y1} A ${radius} ${radius} 0 ${largeArc} 1 ${x2} ${y2} Z`;
  };

  return (
    <div className={`card p-4 ${className}`}>
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-theme-data text-sm text-[var(--accent)]">
            {'>'} {title}
          </h3>
          {subtitle && <p className="text-text-muted text-xs font-theme-data">{subtitle}</p>}
        </div>
        <div className="text-right">
          <div className="text-text-muted text-xs font-theme-data">Total</div>
          <div className="text-[var(--accent)] font-theme-data text-xl">
            {formatCurrency(totalCost)}
          </div>
        </div>
      </div>

      {/* Pie Chart and Legend */}
      <div className="flex gap-6">
        {/* Pie Chart */}
        <div className="relative w-32 h-32 flex-shrink-0">
          <svg viewBox="0 0 100 100" className="transform -rotate-90">
            {segments.map((segment, index) => (
              <path
                key={segment.name}
                d={createArc(segment.startAngle, Math.max(segment.angle, 0.1))}
                className={`${segment.color.class} ${
                  hoveredIndex === index ? 'opacity-100' : 'opacity-80'
                } cursor-pointer transition-opacity`}
                onMouseEnter={() => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
              />
            ))}
            {/* Center hole for donut effect */}
            <circle cx="50" cy="50" r="25" className="fill-bg" />
          </svg>
          {/* Center label */}
          {hoveredIndex !== null && processedData[hoveredIndex] && (
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <div className={`font-theme-data text-xs ${processedData[hoveredIndex].color.text}`}>
                {processedData[hoveredIndex].percentage.toFixed(1)}%
              </div>
              <div className="font-theme-data text-[10px] text-text-muted truncate max-w-[60px]">
                {processedData[hoveredIndex].name}
              </div>
            </div>
          )}
        </div>

        {/* Legend */}
        <div className="flex-1 space-y-2 overflow-y-auto max-h-32">
          {processedData.map((item, index) => (
            <div
              key={item.name}
              className={`flex items-center justify-between p-2 rounded transition-colors cursor-pointer ${
                hoveredIndex === index ? 'bg-surface' : ''
              }`}
              onMouseEnter={() => setHoveredIndex(index)}
              onMouseLeave={() => setHoveredIndex(null)}
            >
              <div className="flex items-center gap-2">
                <div className={`w-3 h-3 rounded ${item.color.class}`} />
                <span className="font-theme-data text-xs text-text truncate max-w-[100px]">
                  {item.name}
                </span>
              </div>
              <span className={`font-theme-data text-xs ${item.color.text}`}>
                {formatCurrency(item.cost)}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Detailed breakdown table */}
      <div className="mt-4 pt-4 border-t border-[var(--accent)]/20">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-text-muted font-theme-data">
              <th className="text-left pb-2">Provider/Model</th>
              <th className="text-right pb-2">Cost</th>
              <th className="text-right pb-2">%</th>
              {showTokens && <th className="text-right pb-2">Tokens</th>}
            </tr>
          </thead>
          <tbody>
            {processedData.map((item) => (
              <tr key={item.name} className="border-t border-[var(--accent)]/10">
                <td className="py-2">
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded ${item.color.class}`} />
                    <span className="font-theme-data text-text">{item.name}</span>
                  </div>
                </td>
                <td className={`py-2 text-right font-theme-data ${item.color.text}`}>
                  {formatCurrency(item.cost)}
                </td>
                <td className="py-2 text-right font-theme-data text-text-muted">
                  {item.percentage.toFixed(1)}%
                </td>
                {showTokens && (
                  <td className="py-2 text-right font-theme-data text-text-muted">
                    {item.tokens ? formatTokens(item.tokens) : '-'}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Projected costs */}
      {totalCost > 0 && (
        <div className="mt-4 pt-4 border-t border-[var(--accent)]/20">
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <div className="text-text-muted text-[10px] font-theme-data">DAILY AVG</div>
              <div className="text-[var(--accent)] font-theme-data text-sm">
                {formatCurrency(totalCost / 30)}
              </div>
            </div>
            <div>
              <div className="text-text-muted text-[10px] font-theme-data">MONTHLY PROJ</div>
              <div className="text-[var(--acid-cyan)] font-theme-data text-sm">
                {formatCurrency(totalCost)}
              </div>
            </div>
            <div>
              <div className="text-text-muted text-[10px] font-theme-data">YEARLY PROJ</div>
              <div className="text-purple-400 font-theme-data text-sm">
                {formatCurrency(totalCost * 12)}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default CostBreakdown;
