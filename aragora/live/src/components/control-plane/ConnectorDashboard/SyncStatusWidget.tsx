'use client';

import { useMemo } from 'react';
import type { ConnectorInfo } from './ConnectorCard';

export interface SyncHistoryItem {
  id: string;
  connector_id: string;
  connector_name: string;
  started_at: string;
  completed_at?: string;
  status: 'running' | 'completed' | 'failed' | 'cancelled';
  items_processed: number;
  items_total?: number;
  error_message?: string;
  duration_seconds?: number;
}

export interface SyncStatusWidgetProps {
  connectors: ConnectorInfo[];
  syncHistory: SyncHistoryItem[];
  onCancelSync?: (syncId: string) => void;
  onRetrySync?: (connectorId: string) => void;
}

/**
 * Widget showing real-time sync status and recent sync history.
 */
export function SyncStatusWidget({
  connectors,
  syncHistory,
  onCancelSync,
  onRetrySync,
}: SyncStatusWidgetProps) {
  // Calculate overall sync stats
  const stats = useMemo(() => {
    const connected = connectors.filter((c) => c.status === 'connected').length;
    const syncing = connectors.filter((c) => c.status === 'syncing').length;
    const errors = connectors.filter((c) => c.status === 'error').length;
    const totalItems = connectors.reduce((sum, c) => sum + (c.items_synced || 0), 0);

    // Calculate last 24h sync count
    const oneDayAgo = new Date(Date.now() - 24 * 60 * 60 * 1000);
    const recentSyncs = syncHistory.filter(
      (h) => new Date(h.started_at) >= oneDayAgo && h.status === 'completed',
    ).length;

    return { connected, syncing, errors, totalItems, recentSyncs };
  }, [connectors, syncHistory]);

  // Active syncs
  const activeSyncs = useMemo(() => {
    return syncHistory.filter((h) => h.status === 'running');
  }, [syncHistory]);

  // Recent completed/failed syncs
  const recentSyncs = useMemo(() => {
    return syncHistory
      .filter((h) => h.status !== 'running')
      .sort((a, b) => new Date(b.started_at).getTime() - new Date(a.started_at).getTime())
      .slice(0, 5);
  }, [syncHistory]);

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
    return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  };

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const formatItemCount = (count: number) => {
    if (count < 1000) return count.toString();
    if (count < 1000000) return `${(count / 1000).toFixed(1)}K`;
    return `${(count / 1000000).toFixed(1)}M`;
  };

  return (
    <div className="space-y-4">
      {/* Stats Overview */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="card p-3">
          <div className="text-xs font-theme-data text-text-muted">Connected</div>
          <div className="text-xl font-theme-data text-success">{stats.connected}</div>
        </div>
        <div className="card p-3">
          <div className="text-xs font-theme-data text-text-muted">Syncing</div>
          <div className="text-xl font-theme-data text-[var(--acid-cyan)]">{stats.syncing}</div>
        </div>
        <div className="card p-3">
          <div className="text-xs font-theme-data text-text-muted">Errors</div>
          <div className="text-xl font-theme-data text-[var(--crimson)]">{stats.errors}</div>
        </div>
        <div className="card p-3">
          <div className="text-xs font-theme-data text-text-muted">Total Items</div>
          <div className="text-xl font-theme-data">{formatItemCount(stats.totalItems)}</div>
        </div>
        <div className="card p-3">
          <div className="text-xs font-theme-data text-text-muted">Syncs (24h)</div>
          <div className="text-xl font-theme-data">{stats.recentSyncs}</div>
        </div>
      </div>

      {/* Active Syncs */}
      {activeSyncs.length > 0 && (
        <div className="card">
          <div className="p-3 border-b border-border flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[var(--acid-cyan)] animate-pulse" />
            <h3 className="font-theme-data text-sm text-[var(--accent)]">Active Syncs</h3>
          </div>
          <div className="p-3 space-y-3">
            {activeSyncs.map((sync) => (
              <div key={sync.id} className="bg-surface p-3 rounded">
                <div className="flex items-center justify-between mb-2">
                  <div>
                    <span className="font-theme-data text-sm">{sync.connector_name}</span>
                    <span className="text-xs text-text-muted ml-2">
                      Started {formatTime(sync.started_at)}
                    </span>
                  </div>
                  {onCancelSync && (
                    <button
                      onClick={() => onCancelSync(sync.id)}
                      className="text-xs text-[var(--crimson)] hover:text-[var(--crimson)]/80 transition-colors"
                    >
                      Cancel
                    </button>
                  )}
                </div>
                <div className="h-1.5 bg-bg rounded overflow-hidden mb-1">
                  <div
                    className="h-full bg-[var(--acid-cyan)] transition-all animate-pulse"
                    style={{
                      width: sync.items_total
                        ? `${(sync.items_processed / sync.items_total) * 100}%`
                        : '50%',
                    }}
                  />
                </div>
                <div className="text-xs text-text-muted font-theme-data">
                  {sync.items_total
                    ? `${formatItemCount(sync.items_processed)} / ${formatItemCount(sync.items_total)} items`
                    : `${formatItemCount(sync.items_processed)} items processed`}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Syncs */}
      <div className="card">
        <div className="p-3 border-b border-border">
          <h3 className="font-theme-data text-sm text-[var(--accent)]">Recent Syncs</h3>
        </div>
        {recentSyncs.length === 0 ? (
          <div className="p-6 text-center text-text-muted font-theme-data text-sm">
            No sync history yet
          </div>
        ) : (
          <div className="divide-y divide-border">
            {recentSyncs.map((sync) => (
              <div key={sync.id} className="p-3 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div
                    className={`w-2 h-2 rounded-full ${
                      sync.status === 'completed'
                        ? 'bg-success'
                        : sync.status === 'failed'
                          ? 'bg-[var(--crimson)]'
                          : 'bg-text-muted'
                    }`}
                  />
                  <div>
                    <div className="font-theme-data text-sm">{sync.connector_name}</div>
                    <div className="text-xs text-text-muted">
                      {formatTime(sync.started_at)}
                      {sync.duration_seconds && ` - ${formatDuration(sync.duration_seconds)}`}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <div className="text-right">
                    <div className="text-sm font-theme-data">
                      {formatItemCount(sync.items_processed)}
                    </div>
                    <div className="text-xs text-text-muted">items</div>
                  </div>
                  {sync.status === 'failed' && onRetrySync && (
                    <button
                      onClick={() => onRetrySync(sync.connector_id)}
                      className="text-xs text-[var(--acid-cyan)] hover:underline"
                    >
                      Retry
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default SyncStatusWidget;
