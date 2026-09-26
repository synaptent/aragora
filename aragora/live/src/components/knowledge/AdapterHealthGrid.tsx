'use client';

import { useAdapterHealth } from '@/hooks/useKnowledgeFlow';
import { useState } from 'react';

const STATUS_BADGE: Record<string, string> = {
  healthy: 'text-emerald-400 border-emerald-400/40 bg-emerald-400/5',
  degraded: 'text-amber-400 border-amber-400/40 bg-amber-400/5',
  unhealthy: 'text-red-400 border-red-400/40 bg-red-400/5',
  unknown: 'text-gray-400 border-gray-400/40 bg-gray-400/5',
};

type SortKey = 'name' | 'status' | 'entry_count';

export function AdapterHealthGrid() {
  const { adapters, total, active, stale, loading, error } = useAdapterHealth();
  const [sortBy, setSortBy] = useState<SortKey>('name');

  const sorted = [...adapters].sort((a, b) => {
    if (sortBy === 'name') return a.name.localeCompare(b.name);
    if (sortBy === 'status') return a.health.localeCompare(b.health);
    return b.entry_count - a.entry_count;
  });

  if (loading)
    return (
      <div className="animate-pulse p-4 text-[var(--text-muted)] font-theme-data">
        Loading adapter health...
      </div>
    );
  if (error)
    return <div className="p-4 text-red-400 font-theme-data">Failed to load adapter health</div>;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex gap-4 font-theme-data text-xs text-[var(--text-muted)]">
          <span>
            Total: <span className="text-[var(--acid-green)]">{total}</span>
          </span>
          <span>
            Active: <span className="text-emerald-400">{active}</span>
          </span>
          <span>
            Stale: <span className="text-amber-400">{stale}</span>
          </span>
        </div>
        <div className="flex gap-2">
          {(['name', 'status', 'entry_count'] as SortKey[]).map((k) => (
            <button
              key={k}
              onClick={() => setSortBy(k)}
              className={`text-[10px] font-theme-data px-2 py-0.5 border rounded ${sortBy === k ? 'border-[var(--acid-green)] text-[var(--acid-green)]' : 'border-[var(--text-muted)]/30 text-[var(--text-muted)]'}`}
            >
              {k.replace('_', ' ')}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
        {sorted.map((a) => (
          <div
            key={a.name}
            className={`card p-3 space-y-1 border-l-2 ${a.health === 'healthy' ? 'border-emerald-400' : a.health === 'degraded' ? 'border-amber-400' : a.health === 'unhealthy' ? 'border-red-400' : 'border-gray-400'}`}
          >
            <div className="flex items-center justify-between">
              <span className="font-theme-data text-xs text-[var(--text)] truncate">{a.name}</span>
              <span
                className={`text-[9px] font-theme-data px-1.5 py-0.5 border rounded ${STATUS_BADGE[a.health] || ''}`}
              >
                {a.status}
              </span>
            </div>
            <div className="text-[10px] font-theme-data text-[var(--text-muted)]">
              {a.entry_count} entries
            </div>
            {a.last_sync && (
              <div className="text-[9px] font-theme-data text-[var(--text-muted)]">
                Last sync: {a.last_sync}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
