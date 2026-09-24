'use client';

interface CostEntry {
  agent: string;
  tokens: number;
  cost: number;
}

interface CostBreakdownProps {
  costBreakdown: CostEntry[] | null | undefined;
  totalCost: number | null | undefined;
}

export function CostBreakdown({ costBreakdown, totalCost }: CostBreakdownProps) {
  if (!costBreakdown || costBreakdown.length === 0) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] p-6">
        <div className="text-xs font-theme-data text-[var(--acid-green)] mb-4">
          {'>'} COST BREAKDOWN
        </div>
        <div className="text-center py-6 text-[var(--text-muted)] font-theme-data text-sm">
          {'>'} No cost data available for this debate.
        </div>
      </div>
    );
  }

  const maxCost = Math.max(...costBreakdown.map((e) => e.cost));

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="text-xs font-theme-data text-[var(--acid-green)]">{'>'} COST BREAKDOWN</div>
        <div className="text-sm font-theme-data text-[var(--acid-green)]">
          TOTAL: ${typeof totalCost === 'number' ? totalCost.toFixed(4) : '--'}
        </div>
      </div>

      <div className="space-y-3">
        {costBreakdown.map((entry, i) => {
          const barWidth = maxCost > 0 ? (entry.cost / maxCost) * 100 : 0;
          return (
            <div key={i}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-theme-data text-[var(--text)]">{entry.agent}</span>
                <div className="flex items-center gap-3">
                  <span className="text-xs font-theme-data text-[var(--text-muted)]">
                    {entry.tokens.toLocaleString()} tokens
                  </span>
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)] w-16 text-right">
                    ${entry.cost.toFixed(4)}
                  </span>
                </div>
              </div>
              <div className="h-2 bg-[var(--bg)] border border-[var(--border)]">
                <div
                  className="h-full bg-[var(--acid-green)]/60 transition-all duration-300"
                  style={{ width: `${barWidth}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
