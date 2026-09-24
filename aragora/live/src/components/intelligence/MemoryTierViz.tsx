'use client';

interface TierData {
  name: string;
  count: number;
  avg_importance: number;
  size_bytes: number;
}

interface MemoryTierVizProps {
  tiers: TierData[];
  loading?: boolean;
}

const TIER_COLORS: Record<string, string> = {
  fast: '#39ff14', // acid-green
  medium: '#00ffff', // acid-cyan
  slow: '#ffff00', // acid-yellow
  glacial: '#6b7280', // text-muted gray
};

const TIER_BG_CLASSES: Record<string, string> = {
  fast: 'bg-[var(--accent)]',
  medium: 'bg-[var(--acid-cyan)]',
  slow: 'bg-acid-yellow',
  glacial: 'bg-gray-500',
};

const TIER_TEXT_CLASSES: Record<string, string> = {
  fast: 'text-[var(--accent)]',
  medium: 'text-[var(--acid-cyan)]',
  slow: 'text-[var(--acid-yellow)]',
  glacial: 'text-text-muted',
};

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${(bytes / Math.pow(k, i)).toFixed(1)} ${sizes[i]}`;
}

export function MemoryTierViz({ tiers, loading = false }: MemoryTierVizProps) {
  if (loading) {
    return (
      <div className="card p-4">
        <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">{'>'} MEMORY TIERS</h3>
        <div className="animate-pulse space-y-4">
          <div className="h-8 bg-surface rounded w-full" />
          <div className="grid grid-cols-4 gap-2">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-16 bg-surface rounded" />
            ))}
          </div>
        </div>
      </div>
    );
  }

  const totalCount = tiers.reduce((sum, t) => sum + t.count, 0);

  return (
    <div className="card p-4">
      <h3 className="font-theme-data text-sm text-[var(--accent)] mb-4">{'>'} MEMORY TIERS</h3>

      {/* Stacked bar */}
      <div className="flex h-8 rounded overflow-hidden border border-[var(--accent)]/20 mb-4">
        {totalCount === 0 ? (
          <div className="flex-1 bg-surface flex items-center justify-center">
            <span className="text-text-muted text-xs font-theme-data">No data available</span>
          </div>
        ) : (
          tiers.map((tier) => {
            const pct = (tier.count / totalCount) * 100;
            if (pct === 0) return null;
            return (
              <div
                key={tier.name}
                className={`${TIER_BG_CLASSES[tier.name] ?? 'bg-gray-500'} opacity-70 flex items-center justify-center transition-all`}
                style={{ width: `${pct}%` }}
                title={`${tier.name}: ${tier.count} entries (${pct.toFixed(1)}%)`}
              >
                {pct > 10 && (
                  <span className="text-bg text-xs font-theme-data font-bold">
                    {tier.name.toUpperCase()}
                  </span>
                )}
              </div>
            );
          })
        )}
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {tiers.map((tier) => (
          <div
            key={tier.name}
            className="border border-[var(--accent)]/10 rounded p-3 bg-surface/30"
          >
            <div className="flex items-center gap-2 mb-2">
              <div
                className="w-2 h-2 rounded-full"
                style={{ backgroundColor: TIER_COLORS[tier.name] ?? '#6b7280' }}
              />
              <span
                className={`font-theme-data text-xs uppercase ${TIER_TEXT_CLASSES[tier.name] ?? 'text-text-muted'}`}
              >
                {tier.name}
              </span>
            </div>
            <div className="space-y-1">
              <div className="flex justify-between">
                <span className="text-text-muted text-xs font-theme-data">Count</span>
                <span className="text-text text-xs font-theme-data">
                  {tier.count.toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted text-xs font-theme-data">Importance</span>
                <span className="text-text text-xs font-theme-data">
                  {tier.avg_importance.toFixed(2)}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-text-muted text-xs font-theme-data">Size</span>
                <span className="text-text text-xs font-theme-data">
                  {formatBytes(tier.size_bytes)}
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default MemoryTierViz;
