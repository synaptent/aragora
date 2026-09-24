'use client';

import { useAdapterHealth } from '@/hooks/useKnowledgeFlow';

const statusColors: Record<string, string> = {
  active: 'text-green-400',
  stale: 'text-yellow-400',
  offline: 'text-red-400',
};

const healthDots: Record<string, string> = {
  healthy: 'bg-green-400',
  degraded: 'bg-yellow-400',
  unhealthy: 'bg-red-400',
};

export function AdaptersTab() {
  const { adapters, total, active, stale, loading, refresh } = useAdapterHealth();

  if (loading && adapters.length === 0) {
    return (
      <div className="flex items-center justify-center h-48 text-text-muted text-sm">
        Loading adapter status...
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary bar */}
      <div className="flex items-center justify-between">
        <div className="flex gap-6 text-sm">
          <span className="text-text-muted">
            Total: <span className="text-text font-theme-data">{total}</span>
          </span>
          <span className="text-green-400">
            Active: <span className="font-theme-data">{active}</span>
          </span>
          <span className="text-yellow-400">
            Stale: <span className="font-theme-data">{stale}</span>
          </span>
          <span className="text-red-400">
            Offline: <span className="font-theme-data">{total - active - stale}</span>
          </span>
        </div>
        <button onClick={() => refresh()} className="text-xs text-[var(--accent)] hover:underline">
          Refresh
        </button>
      </div>

      {/* Adapter grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {adapters.map((adapter) => (
          <div
            key={adapter.name}
            className="p-3 bg-surface rounded-lg border border-border hover:border-[var(--accent)]/30 transition-colors"
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-theme-data text-sm text-text truncate">{adapter.name}</span>
              <span
                className={`flex items-center gap-1.5 text-xs ${statusColors[adapter.status] || 'text-text-muted'}`}
              >
                <span
                  className={`w-2 h-2 rounded-full ${healthDots[adapter.health] || 'bg-gray-500'}`}
                />
                {adapter.status}
              </span>
            </div>
            <div className="flex items-center justify-between text-xs text-text-muted">
              <span>{adapter.entry_count.toLocaleString()} entries</span>
              <span>
                {adapter.last_sync
                  ? `synced ${new Date(adapter.last_sync).toLocaleDateString()}`
                  : 'never synced'}
              </span>
            </div>
          </div>
        ))}
      </div>

      {adapters.length === 0 && !loading && (
        <div className="text-center text-text-muted text-sm py-8">No adapters registered yet.</div>
      )}
    </div>
  );
}
