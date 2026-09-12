'use client';

import Link from 'next/link';
import { useSettlements, type SettlementRecord } from '@/hooks/useSettlements';

/**
 * Status badge configuration for settlement lifecycle states.
 */
const STATUS_CONFIG: Record<
  SettlementRecord['status'],
  { label: string; bg: string; text: string; border: string }
> = {
  settled: {
    label: 'SETTLED',
    bg: 'bg-green-500/20',
    text: 'text-green-400',
    border: 'border-green-500/30',
  },
  due_review: {
    label: 'DUE REVIEW',
    bg: 'bg-yellow-500/20',
    text: 'text-yellow-400',
    border: 'border-yellow-500/30',
  },
  invalidated: {
    label: 'INVALIDATED',
    bg: 'bg-red-500/20',
    text: 'text-red-400',
    border: 'border-red-500/30',
  },
  confirmed: {
    label: 'CONFIRMED',
    bg: 'bg-blue-500/20',
    text: 'text-blue-400',
    border: 'border-blue-500/30',
  },
};

function StatusBadge({ status }: { status: SettlementRecord['status'] }) {
  const config = STATUS_CONFIG[status] ?? STATUS_CONFIG.settled;
  return (
    <span
      className={`px-2 py-0.5 text-[10px] font-theme-data ${config.bg} ${config.text} border ${config.border}`}
      data-testid={`status-badge-${status}`}
    >
      {config.label}
    </span>
  );
}

function formatHorizon(isoDate: string): string {
  if (!isoDate) return '--';
  try {
    const date = new Date(isoDate);
    const now = new Date();
    const diffMs = date.getTime() - now.getTime();
    const diffDays = Math.ceil(diffMs / 86400000);

    if (diffDays < 0) return `${Math.abs(diffDays)}d overdue`;
    if (diffDays === 0) return 'today';
    if (diffDays === 1) return 'tomorrow';
    return `${diffDays}d`;
  } catch {
    return '--';
  }
}

function truncateId(debateId: string): string {
  if (debateId.length <= 12) return debateId;
  return `${debateId.slice(0, 10)}...`;
}

interface SettlementPanelProps {
  refreshInterval?: number;
}

/**
 * Settlement lifecycle panel for the executive dashboard.
 *
 * Shows an overview of debate settlements -- which decisions are settled,
 * due for review, confirmed, or invalidated -- with status badges and
 * a count of due reviews as a prominent indicator.
 */
export function SettlementPanel({ refreshInterval }: SettlementPanelProps) {
  const { summary, dueCount, isLoading, error } = useSettlements(
    refreshInterval ? { refreshInterval } : undefined,
  );

  if (isLoading) {
    return (
      <div
        className="bg-[var(--surface)] border border-[var(--border)]"
        data-testid="settlement-panel-loading"
      >
        <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
          <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
            {'>'} SETTLEMENT STATUS
          </h3>
        </div>
        <div className="p-4 text-center text-[var(--text-muted)] font-theme-data text-sm animate-pulse">
          Loading...
        </div>
      </div>
    );
  }

  if (error || !summary) {
    return (
      <div
        className="bg-[var(--surface)] border border-[var(--border)]"
        data-testid="settlement-panel"
      >
        <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
          <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
            {'>'} SETTLEMENT STATUS
          </h3>
        </div>
        <div className="p-4 text-center text-[var(--text-muted)] font-theme-data text-sm">
          No settlement data available
        </div>
      </div>
    );
  }

  const byStatus = summary.by_status ?? {};
  const recent = summary.recent ?? [];

  return (
    <div
      className="bg-[var(--surface)] border border-[var(--border)]"
      data-testid="settlement-panel"
    >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
          {'>'} SETTLEMENT STATUS
        </h3>
        <div className="flex items-center gap-2">
          {dueCount > 0 && (
            <span
              className="px-2 py-0.5 text-[10px] font-theme-data bg-yellow-500/20 text-yellow-400 border border-yellow-500/30"
              data-testid="due-review-badge"
            >
              {dueCount} DUE
            </span>
          )}
          <Link
            href="/settlements"
            className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
          >
            VIEW ALL
          </Link>
        </div>
      </div>

      {/* Status overview */}
      <div className="p-4 space-y-4">
        <div className="grid grid-cols-4 gap-3">
          {(['settled', 'due_review', 'confirmed', 'invalidated'] as const).map((status) => {
            const config = STATUS_CONFIG[status];
            const count = byStatus[status] ?? 0;
            return (
              <div key={status} className="text-center">
                <div className={`text-lg font-theme-data font-bold ${config.text}`}>{count}</div>
                <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                  {config.label}
                </div>
              </div>
            );
          })}
        </div>

        {/* Average confidence */}
        <div className="flex items-center justify-between pt-3 border-t border-[var(--border)]">
          <span className="text-xs font-theme-data text-[var(--text-muted)]">Avg Confidence</span>
          <span className="text-xs font-theme-data text-[var(--acid-green)]">
            {(summary.average_confidence * 100).toFixed(0)}%
          </span>
        </div>

        {/* Recent settlements */}
        {recent.length > 0 && (
          <div className="pt-3 border-t border-[var(--border)]">
            <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
              Recent Settlements
            </div>
            <div className="space-y-2">
              {recent.slice(0, 5).map((record) => (
                <div key={record.debate_id} className="flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <StatusBadge status={record.status} />
                    <span className="text-xs font-theme-data text-[var(--text)] truncate">
                      {truncateId(record.debate_id)}
                    </span>
                  </div>
                  <div className="flex items-center gap-3 flex-shrink-0">
                    {record.anchor_hash && (
                      <span
                        className={`text-[9px] font-theme-data px-1 py-0 border ${
                          record.anchor_local_only
                            ? 'text-gray-400 border-gray-600'
                            : 'text-purple-400 border-purple-500/30'
                        }`}
                        title={`Anchor: ${record.anchor_hash}${record.anchor_chain_id ? ` (chain ${record.anchor_chain_id})` : ' (local)'}`}
                        data-testid="anchor-badge"
                      >
                        {record.anchor_local_only ? 'LOCAL' : `CH:${record.anchor_chain_id}`}
                      </span>
                    )}
                    <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                      {(record.confidence * 100).toFixed(0)}%
                    </span>
                    <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                      {formatHorizon(record.review_horizon)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Empty recent */}
        {recent.length === 0 && summary.total === 0 && (
          <div className="pt-3 border-t border-[var(--border)] text-center">
            <p className="text-xs font-theme-data text-[var(--text-muted)]">
              No settlements yet. Settlements are created when debates reach consensus.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
