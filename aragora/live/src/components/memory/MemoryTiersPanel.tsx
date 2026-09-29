'use client';

import { useSWRFetch } from '@/hooks/useSWRFetch';

// ─── Types ───────────────────────────────────────────────────────────────────

interface TierInfo {
  id: string;
  name: string;
  description: string;
  ttl_seconds: number;
  ttl_human: string;
  count: number;
  limit: number;
  utilization: number;
  avg_importance: number;
  avg_surprise: number;
}

interface TiersResponse {
  tiers: TierInfo[];
  total_memories: number;
  transitions_24h: number;
}

interface PressureResponse {
  pressure: number;
  status: string;
  tier_utilization: Record<string, { count: number; limit: number; utilization: number }>;
  total_memories: number;
  cleanup_recommended: boolean;
}

// ─── Constants ───────────────────────────────────────────────────────────────

const TIER_COLORS: Record<string, { bar: string; text: string; border: string; glow: string }> = {
  fast: {
    bar: 'bg-red-500',
    text: 'text-red-400',
    border: 'border-red-500/30',
    glow: 'shadow-red-500/20',
  },
  medium: {
    bar: 'bg-yellow-500',
    text: 'text-yellow-400',
    border: 'border-yellow-500/30',
    glow: 'shadow-yellow-500/20',
  },
  slow: {
    bar: 'bg-blue-500',
    text: 'text-blue-400',
    border: 'border-blue-500/30',
    glow: 'shadow-blue-500/20',
  },
  glacial: {
    bar: 'bg-purple-500',
    text: 'text-purple-400',
    border: 'border-purple-500/30',
    glow: 'shadow-purple-500/20',
  },
};

const PRESSURE_STATUS_STYLES: Record<string, { text: string; bg: string }> = {
  normal: { text: 'text-green-400', bg: 'bg-green-900/20' },
  elevated: { text: 'text-yellow-400', bg: 'bg-yellow-900/20' },
  high: { text: 'text-orange-400', bg: 'bg-orange-900/20' },
  critical: { text: 'text-red-400', bg: 'bg-red-900/20' },
};

// ─── Sub-components ──────────────────────────────────────────────────────────

function PressureIndicator({
  pressure,
  status,
  cleanupRecommended,
}: {
  pressure: number;
  status: string;
  cleanupRecommended: boolean;
}) {
  const pct = Math.round(pressure * 100);
  const statusStyle = PRESSURE_STATUS_STYLES[status] ?? PRESSURE_STATUS_STYLES.normal;
  const barColor =
    pct > 90
      ? 'bg-red-500'
      : pct > 70
        ? 'bg-orange-500'
        : pct > 50
          ? 'bg-yellow-500'
          : 'bg-green-500';

  return (
    <div className="p-4 bg-surface border border-border rounded-lg">
      <div className="flex items-center justify-between mb-2">
        <h4 className="text-xs font-theme-data text-text-muted uppercase">Overall Pressure</h4>
        <span
          className={`px-2 py-0.5 text-[10px] font-theme-data rounded ${statusStyle.bg} ${statusStyle.text}`}
        >
          {status.toUpperCase()}
        </span>
      </div>

      {/* Pressure bar */}
      <div className="mb-2">
        <div className="flex justify-between text-xs font-theme-data mb-1">
          <span className="text-text">{pct}%</span>
          <span className="text-text-muted">memory utilization</span>
        </div>
        <div className="h-3 bg-bg rounded-full overflow-hidden">
          <div
            className={`h-full ${barColor} transition-all duration-500 rounded-full`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      {cleanupRecommended && (
        <div className="text-[10px] font-theme-data text-orange-400 mt-2 flex items-center gap-1">
          <span>!</span> Cleanup recommended - memory pressure exceeds 90%
        </div>
      )}
    </div>
  );
}

function TierCard({ tier }: { tier: TierInfo }) {
  const colors = TIER_COLORS[tier.id] ?? TIER_COLORS.slow;
  const pct = Math.round(tier.utilization * 100);
  const barWidth = Math.min(100, pct);

  // Determine utilization urgency
  const urgencyColor =
    pct > 90
      ? 'text-red-400'
      : pct > 70
        ? 'text-orange-400'
        : pct > 50
          ? 'text-yellow-400'
          : 'text-green-400';

  return (
    <div
      className={`p-4 bg-surface border ${colors.border} rounded-lg hover:shadow-lg ${colors.glow} transition-all`}
    >
      {/* Tier header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <h4 className={`text-sm font-theme-data font-bold ${colors.text}`}>{tier.name}</h4>
          <p className="text-[10px] text-text-muted">{tier.description}</p>
        </div>
        <div className="text-right">
          <div className="text-xs font-theme-data text-text-muted">TTL</div>
          <div className={`text-sm font-theme-data font-bold ${colors.text}`}>{tier.ttl_human}</div>
        </div>
      </div>

      {/* Utilization bar */}
      <div className="mb-3">
        <div className="flex justify-between text-xs font-theme-data mb-1">
          <span className={urgencyColor}>{pct}% utilized</span>
          <span className="text-text-muted">
            {tier.count} / {tier.limit}
          </span>
        </div>
        <div className="h-2.5 bg-bg rounded-full overflow-hidden">
          <div
            className={`h-full ${colors.bar} transition-all duration-500 rounded-full`}
            style={{ width: `${barWidth}%` }}
          />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 gap-2">
        <div className="p-2 bg-bg rounded">
          <div className="text-[10px] text-text-muted">Count</div>
          <div className="text-sm font-theme-data text-text">{tier.count}</div>
        </div>
        <div className="p-2 bg-bg rounded">
          <div className="text-[10px] text-text-muted">Limit</div>
          <div className="text-sm font-theme-data text-text">{tier.limit}</div>
        </div>
        <div className="p-2 bg-bg rounded">
          <div className="text-[10px] text-text-muted">Avg Importance</div>
          <div className="text-sm font-theme-data text-text">
            {(tier.avg_importance * 100).toFixed(0)}%
          </div>
        </div>
        <div className="p-2 bg-bg rounded">
          <div className="text-[10px] text-text-muted">Avg Surprise</div>
          <div className="text-sm font-theme-data text-text">
            {(tier.avg_surprise * 100).toFixed(0)}%
          </div>
        </div>
      </div>
    </div>
  );
}

function TiersSummary({
  totalMemories,
  transitions,
}: {
  totalMemories: number;
  transitions: number;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 mb-4">
      <div className="p-3 bg-surface border border-border rounded-lg text-center">
        <div className="text-xl font-theme-data text-[var(--accent)]">{totalMemories}</div>
        <div className="text-[10px] text-text-muted">Total Memories</div>
      </div>
      <div className="p-3 bg-surface border border-border rounded-lg text-center">
        <div className="text-xl font-theme-data text-[var(--acid-cyan)]">{transitions}</div>
        <div className="text-[10px] text-text-muted">Transitions (24h)</div>
      </div>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export function MemoryTiersPanel() {
  // Fetch tier details
  const {
    data: tiersData,
    error: tiersError,
    isLoading: tiersLoading,
    mutate: refreshTiers,
  } = useSWRFetch<TiersResponse>('/api/v1/memory/tiers', { refreshInterval: 30000 });

  // Fetch memory pressure
  const {
    data: pressureData,
    error: pressureError,
    isLoading: pressureLoading,
  } = useSWRFetch<PressureResponse>('/api/v1/memory/pressure', { refreshInterval: 30000 });

  const tiers = tiersData?.tiers ?? [];
  const isLoading = tiersLoading || pressureLoading;
  const hasError = (tiersError || pressureError) && !isLoading;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider">
            Memory Tier Visualization
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Multi-tier continuum memory: fast, medium, slow, and glacial storage
          </p>
        </div>
        <button
          onClick={() => refreshTiers()}
          disabled={isLoading}
          className="px-3 py-1.5 text-xs font-theme-data bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)] rounded hover:bg-[var(--acid-cyan)]/30 transition-colors disabled:opacity-50"
        >
          {isLoading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {/* Loading State */}
      {isLoading && (
        <div className="text-center py-8 text-text-muted font-theme-data animate-pulse">
          Loading memory tier data...
        </div>
      )}

      {/* Error State */}
      {hasError && (
        <div className="p-4 bg-surface border border-border rounded-lg text-center">
          <p className="text-text-muted font-theme-data text-sm">
            Unable to load memory tier data. The backend may not be running.
          </p>
          <button
            onClick={() => refreshTiers()}
            className="mt-2 px-3 py-1 text-xs font-theme-data text-[var(--accent)] border border-[var(--accent)]/30 rounded hover:bg-[var(--accent)]/10"
          >
            Retry
          </button>
        </div>
      )}

      {/* Content */}
      {!isLoading && !hasError && (
        <>
          {/* Pressure indicator */}
          {pressureData && (
            <PressureIndicator
              pressure={pressureData.pressure}
              status={pressureData.status}
              cleanupRecommended={pressureData.cleanup_recommended}
            />
          )}

          {/* Summary stats */}
          {tiersData && (
            <TiersSummary
              totalMemories={tiersData.total_memories}
              transitions={tiersData.transitions_24h}
            />
          )}

          {/* Tier Cards */}
          {tiers.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {tiers.map((tier) => (
                <TierCard key={tier.id} tier={tier} />
              ))}
            </div>
          ) : (
            <div className="p-8 bg-surface border border-border rounded-lg text-center">
              <div className="text-3xl mb-2">--</div>
              <p className="text-text-muted font-theme-data text-sm">
                No memory tier data available
              </p>
              <p className="text-text-muted/60 font-theme-data text-xs mt-1">
                The continuum memory system may not be initialized
              </p>
            </div>
          )}

          {/* Tier utilization comparison (horizontal stacked view) */}
          {tiers.length > 0 && (
            <div className="p-4 bg-surface border border-border rounded-lg">
              <h4 className="text-xs font-theme-data text-text-muted uppercase mb-3">
                Utilization Comparison
              </h4>
              <div className="space-y-2">
                {tiers.map((tier) => {
                  const colors = TIER_COLORS[tier.id] ?? TIER_COLORS.slow;
                  const pct = Math.round(tier.utilization * 100);
                  return (
                    <div key={tier.id} className="flex items-center gap-3">
                      <span className={`w-16 text-xs font-theme-data ${colors.text} text-right`}>
                        {tier.name}
                      </span>
                      <div className="flex-1 h-4 bg-bg rounded-full overflow-hidden">
                        <div
                          className={`h-full ${colors.bar} transition-all duration-500 rounded-full`}
                          style={{ width: `${Math.min(100, pct)}%` }}
                        />
                      </div>
                      <span className="w-12 text-xs font-theme-data text-text text-right">
                        {pct}%
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
