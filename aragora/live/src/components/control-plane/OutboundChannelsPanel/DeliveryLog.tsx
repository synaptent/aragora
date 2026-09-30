'use client';

import { useMemo } from 'react';
import type { OutboundChannelType } from './ChannelCard';

export type DeliveryStatus = 'pending' | 'sent' | 'delivered' | 'failed' | 'rate_limited';

export interface DeliveryLogEntry {
  id: string;
  message_id: string;
  channel_type: OutboundChannelType;
  channel_name: string;
  recipient?: string;
  content_preview: string;
  status: DeliveryStatus;
  sent_at?: string;
  delivered_at?: string;
  error_message?: string;
  deliberation_id?: string;
  retry_count?: number;
}

export interface DeliveryLogProps {
  entries: DeliveryLogEntry[];
  loading?: boolean;
  onRetry?: (entry: DeliveryLogEntry) => void;
  onViewDetails?: (entry: DeliveryLogEntry) => void;
  className?: string;
}

const CHANNEL_ICONS: Record<OutboundChannelType, string> = {
  slack: '📢',
  teams: '👥',
  discord: '🎮',
  telegram: '✈️',
  whatsapp: '💬',
  voice: '🎙️',
  email: '📧',
  webhook: '🔗',
};

function _getStatusColor(status: DeliveryStatus): string {
  switch (status) {
    case 'delivered':
      return 'text-[var(--accent)]';
    case 'sent':
      return 'text-cyan-400';
    case 'pending':
      return 'text-yellow-400';
    case 'failed':
      return 'text-red-400';
    case 'rate_limited':
      return 'text-orange-400';
    default:
      return 'text-text-muted';
  }
}

function getStatusBadgeClass(status: DeliveryStatus): string {
  switch (status) {
    case 'delivered':
      return 'bg-[var(--accent)]/20 text-[var(--accent)]';
    case 'sent':
      return 'bg-cyan-400/20 text-cyan-400';
    case 'pending':
      return 'bg-yellow-400/20 text-yellow-400';
    case 'failed':
      return 'bg-red-400/20 text-red-400';
    case 'rate_limited':
      return 'bg-orange-400/20 text-orange-400';
    default:
      return 'bg-surface text-text-muted';
  }
}

function formatTime(iso: string): string {
  const date = new Date(iso);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffMins < 1440) return `${Math.floor(diffMins / 60)}h ago`;
  return date.toLocaleDateString();
}

function formatFullTime(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString();
}

/**
 * Delivery log component showing outbound message delivery history.
 */
export function DeliveryLog({
  entries,
  loading = false,
  onRetry,
  onViewDetails,
  className = '',
}: DeliveryLogProps) {
  const stats = useMemo(() => {
    const total = entries.length;
    const delivered = entries.filter((e) => e.status === 'delivered').length;
    const failed = entries.filter((e) => e.status === 'failed').length;
    const pending = entries.filter((e) => e.status === 'pending' || e.status === 'sent').length;

    return {
      total,
      delivered,
      failed,
      pending,
      successRate: total > 0 ? ((delivered / total) * 100).toFixed(1) : '0.0',
    };
  }, [entries]);

  if (loading) {
    return (
      <div className={`space-y-3 ${className}`}>
        {[1, 2, 3].map((i) => (
          <div key={i} className="card p-4 animate-pulse">
            <div className="h-4 bg-surface rounded w-1/3 mb-2" />
            <div className="h-3 bg-surface rounded w-2/3" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className={className}>
      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-3 mb-4">
        <div className="bg-surface rounded p-3 text-center">
          <div className="text-xl font-theme-data font-bold text-text">{stats.total}</div>
          <div className="text-xs text-text-muted">Total</div>
        </div>
        <div className="bg-surface rounded p-3 text-center">
          <div className="text-xl font-theme-data font-bold text-[var(--accent)]">
            {stats.delivered}
          </div>
          <div className="text-xs text-text-muted">Delivered</div>
        </div>
        <div className="bg-surface rounded p-3 text-center">
          <div className="text-xl font-theme-data font-bold text-yellow-400">{stats.pending}</div>
          <div className="text-xs text-text-muted">Pending</div>
        </div>
        <div className="bg-surface rounded p-3 text-center">
          <div className="text-xl font-theme-data font-bold text-red-400">{stats.failed}</div>
          <div className="text-xs text-text-muted">Failed</div>
        </div>
      </div>

      {/* Log Entries */}
      <div className="space-y-2">
        {entries.length === 0 ? (
          <div className="card p-8 text-center">
            <div className="text-4xl mb-2">📭</div>
            <p className="text-text-muted">No delivery logs yet</p>
            <p className="text-xs text-text-muted mt-1">Outbound messages will appear here</p>
          </div>
        ) : (
          entries.map((entry) => (
            <div
              key={entry.id}
              onClick={() => onViewDetails?.(entry)}
              className="card p-3 cursor-pointer hover:border-[var(--accent)]/50 transition-colors"
            >
              <div className="flex items-start justify-between gap-3">
                {/* Left side - Channel & Content */}
                <div className="flex items-start gap-3 flex-1 min-w-0">
                  <span className="text-xl flex-shrink-0">
                    {CHANNEL_ICONS[entry.channel_type] || '📡'}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <span className="font-theme-data text-sm font-bold">
                        {entry.channel_name}
                      </span>
                      {entry.recipient && (
                        <span className="text-xs text-text-muted">→ {entry.recipient}</span>
                      )}
                    </div>
                    <p className="text-xs text-text-muted truncate">{entry.content_preview}</p>
                    {entry.deliberation_id && (
                      <div className="text-xs text-cyan-400 mt-1">
                        Debate: {entry.deliberation_id.slice(0, 8)}...
                      </div>
                    )}
                    {entry.error_message && entry.status === 'failed' && (
                      <div className="text-xs text-red-400 mt-1">⚠ {entry.error_message}</div>
                    )}
                  </div>
                </div>

                {/* Right side - Status & Time */}
                <div className="flex flex-col items-end gap-1 flex-shrink-0">
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-theme-data ${getStatusBadgeClass(
                      entry.status,
                    )}`}
                  >
                    {entry.status.toUpperCase()}
                  </span>
                  <span
                    className="text-xs text-text-muted"
                    title={entry.sent_at ? formatFullTime(entry.sent_at) : ''}
                  >
                    {entry.sent_at ? formatTime(entry.sent_at) : 'Queued'}
                  </span>
                  {entry.retry_count && entry.retry_count > 0 && (
                    <span className="text-xs text-yellow-400">Retry #{entry.retry_count}</span>
                  )}
                </div>
              </div>

              {/* Action buttons for failed */}
              {entry.status === 'failed' && onRetry && (
                <div className="mt-2 pt-2 border-t border-border flex justify-end">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onRetry(entry);
                    }}
                    className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] hover:bg-[var(--accent)]/30 rounded transition-colors"
                  >
                    Retry Delivery
                  </button>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default DeliveryLog;
