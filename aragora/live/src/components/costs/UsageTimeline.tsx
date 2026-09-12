'use client';

import { useState } from 'react';

interface DailyCost {
  date: string;
  cost: number;
  tokens: number;
}

interface UsageTimelineProps {
  data: DailyCost[];
}

type ViewMode = 'cost' | 'tokens';

export function UsageTimeline({ data }: UsageTimelineProps) {
  const [viewMode, setViewMode] = useState<ViewMode>('cost');
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  if (data.length === 0) return null;

  const maxValue = Math.max(...data.map((d) => (viewMode === 'cost' ? d.cost : d.tokens)));
  const totalCost = data.reduce((sum, d) => sum + d.cost, 0);
  const totalTokens = data.reduce((sum, d) => sum + d.tokens, 0);
  const avgCost = totalCost / data.length;

  const formatDate = (dateStr: string): string => {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  };

  const formatValue = (value: number): string => {
    if (viewMode === 'cost') {
      return `$${value.toFixed(2)}`;
    }
    if (value >= 1000000) {
      return `${(value / 1000000).toFixed(1)}M`;
    }
    if (value >= 1000) {
      return `${(value / 1000).toFixed(0)}K`;
    }
    return value.toString();
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} USAGE TIMELINE</h3>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setViewMode('cost')}
            className={`px-3 py-1 text-xs font-theme-data rounded transition-colors ${
              viewMode === 'cost'
                ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            Cost
          </button>
          <button
            onClick={() => setViewMode('tokens')}
            className={`px-3 py-1 text-xs font-theme-data rounded transition-colors ${
              viewMode === 'tokens'
                ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)]'
            }`}
          >
            Tokens
          </button>
        </div>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-3 gap-4 mb-4 p-3 bg-[var(--bg)] rounded">
        <div>
          <div className="text-xs text-[var(--text-muted)]">
            Total {viewMode === 'cost' ? 'Cost' : 'Tokens'}
          </div>
          <div
            className={`text-lg font-theme-data ${viewMode === 'cost' ? 'text-[var(--acid-green)]' : 'text-[var(--acid-cyan)]'}`}
          >
            {viewMode === 'cost' ? `$${totalCost.toFixed(2)}` : formatValue(totalTokens)}
          </div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-muted)]">Daily Average</div>
          <div className="text-lg font-theme-data text-[var(--text)]">
            {viewMode === 'cost'
              ? `$${avgCost.toFixed(2)}`
              : formatValue(totalTokens / data.length)}
          </div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-muted)]">Days</div>
          <div className="text-lg font-theme-data text-[var(--text)]">{data.length}</div>
        </div>
      </div>

      {/* Chart */}
      <div className="relative h-40">
        {/* Average line */}
        <div
          className="absolute left-0 right-0 border-t border-dashed border-yellow-500/50"
          style={{
            bottom: `${((viewMode === 'cost' ? avgCost : totalTokens / data.length) / maxValue) * 100}%`,
          }}
        >
          <span className="absolute right-0 -top-3 text-xs text-yellow-500">avg</span>
        </div>

        {/* Bars */}
        <div className="flex items-end justify-between h-full gap-1">
          {data.map((item, index) => {
            const value = viewMode === 'cost' ? item.cost : item.tokens;
            const heightPercent = (value / maxValue) * 100;
            const isHovered = hoveredIndex === index;

            return (
              <div
                key={item.date}
                className="relative flex-1 flex flex-col items-center"
                onMouseEnter={() => setHoveredIndex(index)}
                onMouseLeave={() => setHoveredIndex(null)}
              >
                {/* Tooltip */}
                {isHovered && (
                  <div className="absolute bottom-full mb-2 p-2 bg-[var(--bg)] border border-[var(--border)] rounded shadow-lg z-10 whitespace-nowrap">
                    <div className="text-xs font-theme-data text-[var(--text)]">
                      {formatDate(item.date)}
                    </div>
                    <div
                      className={`text-sm font-theme-data ${viewMode === 'cost' ? 'text-[var(--acid-green)]' : 'text-[var(--acid-cyan)]'}`}
                    >
                      {formatValue(value)}
                    </div>
                    {viewMode === 'cost' && (
                      <div className="text-xs text-[var(--text-muted)]">
                        {formatValue(item.tokens)} tokens
                      </div>
                    )}
                  </div>
                )}

                {/* Bar */}
                <div
                  className={`w-full rounded-t transition-all duration-200 cursor-pointer ${
                    viewMode === 'cost'
                      ? isHovered
                        ? 'bg-[var(--acid-green)]'
                        : 'bg-[var(--acid-green)]/60'
                      : isHovered
                        ? 'bg-[var(--acid-cyan)]'
                        : 'bg-[var(--acid-cyan)]/60'
                  }`}
                  style={{ height: `${heightPercent}%`, minHeight: '4px' }}
                />

                {/* Date label */}
                <div className="text-xs text-[var(--text-muted)] mt-1 transform -rotate-45 origin-left w-12">
                  {formatDate(item.date).split(' ')[1]}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Y-axis labels */}
      <div className="flex justify-between mt-4 text-xs text-[var(--text-muted)]">
        <span>$0</span>
        <span>{formatValue(maxValue / 2)}</span>
        <span>{formatValue(maxValue)}</span>
      </div>
    </div>
  );
}

export default UsageTimeline;
