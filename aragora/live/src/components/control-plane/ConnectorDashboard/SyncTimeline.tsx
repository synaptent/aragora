'use client';

import { useMemo } from 'react';
import type { SyncHistoryItem } from './SyncStatusWidget';

export interface SyncTimelineProps {
  /** Sync history items */
  history: SyncHistoryItem[];
  /** Loading state */
  loading?: boolean;
  /** Number of hours to show (default: 24) */
  hoursToShow?: number;
  /** Callback when sync item is clicked */
  onSyncClick?: (syncId: string) => void;
}

interface TimelineSlot {
  hour: number;
  date: Date;
  syncs: SyncHistoryItem[];
  status: 'idle' | 'success' | 'running' | 'failed' | 'mixed';
}

/**
 * Visual timeline showing sync activity over time.
 */
export function SyncTimeline({
  history,
  loading = false,
  hoursToShow = 24,
  onSyncClick,
}: SyncTimelineProps) {
  // Build timeline slots
  const timelineSlots = useMemo(() => {
    const slots: TimelineSlot[] = [];
    const now = new Date();

    for (let i = hoursToShow - 1; i >= 0; i--) {
      const slotDate = new Date(now.getTime() - i * 60 * 60 * 1000);
      const slotHour = slotDate.getHours();

      // Find syncs that occurred in this hour
      const syncsInSlot = history.filter((sync) => {
        const syncDate = new Date(sync.started_at);
        return (
          syncDate.getHours() === slotHour &&
          syncDate.getDate() === slotDate.getDate() &&
          syncDate.getMonth() === slotDate.getMonth()
        );
      });

      // Determine slot status
      let status: TimelineSlot['status'] = 'idle';
      if (syncsInSlot.length > 0) {
        const hasFailure = syncsInSlot.some((s) => s.status === 'failed');
        const hasRunning = syncsInSlot.some((s) => s.status === 'running');
        const hasSuccess = syncsInSlot.some((s) => s.status === 'completed');

        if (hasFailure && hasSuccess) {
          status = 'mixed';
        } else if (hasRunning) {
          status = 'running';
        } else if (hasFailure) {
          status = 'failed';
        } else if (hasSuccess) {
          status = 'success';
        }
      }

      slots.push({ hour: slotHour, date: slotDate, syncs: syncsInSlot, status });
    }

    return slots;
  }, [history, hoursToShow]);

  // Summary stats
  const stats = useMemo(() => {
    const completed = history.filter((s) => s.status === 'completed').length;
    const failed = history.filter((s) => s.status === 'failed').length;
    const running = history.filter((s) => s.status === 'running').length;
    const totalItems = history.reduce((sum, s) => sum + (s.items_processed || 0), 0);

    return { completed, failed, running, totalItems };
  }, [history]);

  const statusColors = {
    idle: 'bg-surface-lighter',
    success: 'bg-green-500',
    running: 'bg-blue-500 animate-pulse',
    failed: 'bg-red-500',
    mixed: 'bg-yellow-500',
  };

  if (loading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="grid grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-12 bg-surface-lighter rounded" />
          ))}
        </div>
        <div className="h-16 bg-surface-lighter rounded" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-4 gap-3">
        <div className="p-3 bg-surface rounded-lg border border-border text-center">
          <div className="text-2xl font-theme-data font-bold text-green-400">{stats.completed}</div>
          <div className="text-xs text-text-muted">Completed</div>
        </div>
        <div className="p-3 bg-surface rounded-lg border border-border text-center">
          <div className="text-2xl font-theme-data font-bold text-blue-400">{stats.running}</div>
          <div className="text-xs text-text-muted">Running</div>
        </div>
        <div className="p-3 bg-surface rounded-lg border border-border text-center">
          <div className="text-2xl font-theme-data font-bold text-red-400">{stats.failed}</div>
          <div className="text-xs text-text-muted">Failed</div>
        </div>
        <div className="p-3 bg-surface rounded-lg border border-border text-center">
          <div className="text-2xl font-theme-data font-bold text-[var(--acid-cyan)]">
            {stats.totalItems.toLocaleString()}
          </div>
          <div className="text-xs text-text-muted">Items Synced</div>
        </div>
      </div>

      {/* Timeline */}
      <div className="p-4 bg-surface rounded-lg border border-border">
        <div className="flex items-center justify-between mb-3">
          <div className="text-sm font-medium">Sync Timeline (Last {hoursToShow}h)</div>
          <div className="flex items-center gap-3 text-xs text-text-muted">
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-green-500" /> Success
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-blue-500" /> Running
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-red-500" /> Failed
            </span>
          </div>
        </div>

        <div className="flex gap-0.5">
          {timelineSlots.map((slot, index) => (
            <div key={index} className="flex-1 min-w-0">
              <button
                onClick={() => {
                  if (slot.syncs.length > 0 && onSyncClick) {
                    onSyncClick(slot.syncs[0].id);
                  }
                }}
                disabled={slot.syncs.length === 0}
                className={`w-full h-8 rounded-sm ${statusColors[slot.status]}
                           hover:opacity-80 transition-opacity disabled:cursor-default`}
                title={`${formatHour(slot.hour)}: ${slot.syncs.length} sync${slot.syncs.length !== 1 ? 's' : ''}`}
              />
              {index % 4 === 0 && (
                <div className="text-xs text-text-muted text-center mt-1">
                  {formatHour(slot.hour)}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Recent Activity */}
      <div className="p-4 bg-surface rounded-lg border border-border">
        <div className="text-sm font-medium mb-3">Recent Activity</div>
        <div className="space-y-2 max-h-48 overflow-y-auto">
          {history.slice(0, 10).map((sync) => (
            <SyncActivityItem key={sync.id} sync={sync} onClick={() => onSyncClick?.(sync.id)} />
          ))}
          {history.length === 0 && (
            <div className="text-center text-text-muted text-sm py-4">No sync activity</div>
          )}
        </div>
      </div>
    </div>
  );
}

interface SyncActivityItemProps {
  sync: SyncHistoryItem;
  onClick?: () => void;
}

function SyncActivityItem({ sync, onClick }: SyncActivityItemProps) {
  const statusIcon: Record<SyncHistoryItem['status'], string> = {
    completed: '\u2713',
    running: '\u25B6',
    failed: '\u2717',
    cancelled: '\u2715',
  };

  const statusColor: Record<SyncHistoryItem['status'], string> = {
    completed: 'text-green-400',
    running: 'text-blue-400',
    failed: 'text-red-400',
    cancelled: 'text-yellow-400',
  };

  const timeFormatted = formatTimeAgo(new Date(sync.started_at));

  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-3 p-2 rounded hover:bg-surface-lighter
                 transition-colors text-left"
    >
      <span className={`text-lg ${statusColor[sync.status]}`}>{statusIcon[sync.status]}</span>
      <div className="flex-1 min-w-0">
        <div className="text-sm font-medium truncate">{sync.connector_name}</div>
        <div className="text-xs text-text-muted">
          {sync.items_processed?.toLocaleString() || 0} items
          {sync.duration_seconds && ` in ${formatDuration(sync.duration_seconds)}`}
        </div>
      </div>
      <div className="text-xs text-text-muted">{timeFormatted}</div>
    </button>
  );
}

function formatHour(hour: number): string {
  const ampm = hour >= 12 ? 'pm' : 'am';
  const h = hour % 12 || 12;
  return `${h}${ampm}`;
}

function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return date.toLocaleDateString();
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return secs > 0 ? `${mins}m ${secs}s` : `${mins}m`;
}

export default SyncTimeline;
