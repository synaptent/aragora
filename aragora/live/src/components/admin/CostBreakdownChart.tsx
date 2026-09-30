'use client';

import React, { useState, useMemo } from 'react';

export interface CostItem {
  id: string;
  label: string;
  cost: number;
  category: string;
  subcategory?: string;
  metadata?: Record<string, unknown>;
}

export type BreakdownType = 'feature' | 'agent' | 'domain' | 'user' | 'workspace';
export type TimeRange = '24h' | '7d' | '30d' | '90d';

interface CostBreakdownChartProps {
  data: CostItem[];
  title?: string;
  breakdownType?: BreakdownType;
  showTimeRangeSelector?: boolean;
  defaultTimeRange?: TimeRange;
  onTimeRangeChange?: (range: TimeRange) => void;
  onBreakdownTypeChange?: (type: BreakdownType) => void;
  onItemClick?: (item: CostItem) => void;
  currencySymbol?: string;
  loading?: boolean;
  className?: string;
}

const CATEGORY_COLORS: Record<string, string> = {
  debate: 'acid-green',
  agent: 'acid-cyan',
  workflow: 'acid-yellow',
  storage: 'acid-magenta',
  api: 'acid-red',
  knowledge: 'acid-green',
  analytics: 'acid-cyan',
  default: 'text-muted',
};

function formatCurrency(value: number, symbol: string = '$'): string {
  if (value >= 1000000) {
    return `${symbol}${(value / 1000000).toFixed(2)}M`;
  }
  if (value >= 1000) {
    return `${symbol}${(value / 1000).toFixed(2)}K`;
  }
  return `${symbol}${value.toFixed(2)}`;
}

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

export function CostBreakdownChart({
  data,
  title = 'COST BREAKDOWN',
  breakdownType = 'feature',
  showTimeRangeSelector = true,
  defaultTimeRange = '30d',
  onTimeRangeChange,
  onBreakdownTypeChange,
  onItemClick,
  currencySymbol = '$',
  loading = false,
  className = '',
}: CostBreakdownChartProps) {
  const [timeRange, setTimeRange] = useState<TimeRange>(defaultTimeRange);
  const [hoveredItem, setHoveredItem] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const handleTimeRangeChange = (range: TimeRange) => {
    setTimeRange(range);
    onTimeRangeChange?.(range);
  };

  const { sortedData, totalCost, topItems } = useMemo(() => {
    const sorted = [...data].sort((a, b) => b.cost - a.cost);
    const total = sorted.reduce((sum, item) => sum + item.cost, 0);
    const top = showAll ? sorted : sorted.slice(0, 8);
    return { sortedData: sorted, totalCost: total, topItems: top };
  }, [data, showAll]);

  const getCategoryColor = (category: string): string => {
    return CATEGORY_COLORS[category.toLowerCase()] || CATEGORY_COLORS.default;
  };

  const breakdownTypes: { value: BreakdownType; label: string }[] = [
    { value: 'feature', label: 'FEATURE' },
    { value: 'agent', label: 'AGENT' },
    { value: 'domain', label: 'DOMAIN' },
    { value: 'user', label: 'USER' },
    { value: 'workspace', label: 'WORKSPACE' },
  ];

  if (loading) {
    return (
      <div className={`card p-8 ${className}`}>
        <div className="flex items-center justify-center">
          <div className="font-theme-data text-text-muted animate-pulse">Loading cost data...</div>
        </div>
      </div>
    );
  }

  return (
    <div className={`card ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-[var(--accent)]/20">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-theme-data text-lg text-[var(--accent)]">{title}</h3>
            <div className="font-theme-data text-2xl text-text mt-1">
              {formatCurrency(totalCost, currencySymbol)}
              <span className="text-sm text-text-muted ml-2">total</span>
            </div>
          </div>
          {showTimeRangeSelector && (
            <div className="flex gap-1">
              {(['24h', '7d', '30d', '90d'] as TimeRange[]).map((range) => (
                <button
                  key={range}
                  onClick={() => handleTimeRangeChange(range)}
                  className={`px-2 py-1 font-theme-data text-xs rounded transition-colors ${
                    timeRange === range
                      ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40'
                      : 'text-text-muted hover:text-text'
                  }`}
                >
                  {range}
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Breakdown Type Selector */}
        {onBreakdownTypeChange && (
          <div className="flex items-center gap-2">
            <span className="font-theme-data text-xs text-text-muted">BY:</span>
            {breakdownTypes.map((type) => (
              <button
                key={type.value}
                onClick={() => onBreakdownTypeChange(type.value)}
                className={`px-2 py-1 font-theme-data text-xs rounded transition-colors ${
                  breakdownType === type.value
                    ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/40'
                    : 'text-text-muted hover:text-text'
                }`}
              >
                {type.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Bar Chart */}
      <div className="p-4">
        {topItems.length === 0 ? (
          <div className="py-8 text-center font-theme-data text-text-muted">
            No cost data available
          </div>
        ) : (
          <div className="space-y-3">
            {topItems.map((item) => {
              const percentage = totalCost > 0 ? (item.cost / totalCost) * 100 : 0;
              const color = getCategoryColor(item.category);
              const isHovered = hoveredItem === item.id;

              return (
                <div
                  key={item.id}
                  className={`relative cursor-pointer transition-all ${
                    isHovered ? 'transform scale-[1.01]' : ''
                  }`}
                  onMouseEnter={() => setHoveredItem(item.id)}
                  onMouseLeave={() => setHoveredItem(null)}
                  onClick={() => onItemClick?.(item)}
                >
                  {/* Label and Value */}
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full bg-${color}`} />
                      <span className="font-theme-data text-sm text-text">{item.label}</span>
                      {item.subcategory && (
                        <span className="font-theme-data text-xs text-text-muted">
                          ({item.subcategory})
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <span className="font-theme-data text-sm text-text-muted">
                        {formatPercent(percentage)}
                      </span>
                      <span className={`font-theme-data text-sm text-${color}`}>
                        {formatCurrency(item.cost, currencySymbol)}
                      </span>
                    </div>
                  </div>

                  {/* Progress Bar */}
                  <div className="h-6 bg-surface-elevated rounded overflow-hidden">
                    <div
                      className={`h-full bg-${color}/30 border-r-2 border-${color} transition-all duration-300 ${
                        isHovered ? `bg-${color}/50` : ''
                      }`}
                      style={{ width: `${Math.max(percentage, 0.5)}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Show More/Less */}
        {sortedData.length > 8 && (
          <button
            onClick={() => setShowAll(!showAll)}
            className="mt-4 w-full py-2 font-theme-data text-xs text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
          >
            {showAll
              ? `SHOW LESS`
              : `SHOW ALL ${sortedData.length} ITEMS (+${sortedData.length - 8} more)`}
          </button>
        )}
      </div>

      {/* Summary Footer */}
      <div className="p-4 border-t border-[var(--accent)]/20 bg-surface">
        <div className="grid grid-cols-4 gap-4">
          <div>
            <div className="font-theme-data text-xs text-text-muted">ITEMS</div>
            <div className="font-theme-data text-lg text-text">{sortedData.length}</div>
          </div>
          <div>
            <div className="font-theme-data text-xs text-text-muted">AVG COST</div>
            <div className="font-theme-data text-lg text-text">
              {formatCurrency(
                sortedData.length > 0 ? totalCost / sortedData.length : 0,
                currencySymbol,
              )}
            </div>
          </div>
          <div>
            <div className="font-theme-data text-xs text-text-muted">TOP ITEM</div>
            <div className="font-theme-data text-lg text-[var(--accent)]">
              {sortedData[0] ? formatPercent((sortedData[0].cost / totalCost) * 100) : '-'}
            </div>
          </div>
          <div>
            <div className="font-theme-data text-xs text-text-muted">CATEGORIES</div>
            <div className="font-theme-data text-lg text-text">
              {new Set(sortedData.map((d) => d.category)).size}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default CostBreakdownChart;
