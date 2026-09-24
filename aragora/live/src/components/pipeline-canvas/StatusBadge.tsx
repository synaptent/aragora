'use client';

/**
 * StatusBadge - Color-coded execution status indicator for pipeline nodes.
 *
 * Displays execution state (pending, in_progress, succeeded, failed, partial)
 * with a tooltip showing execution details like receipt hash, timestamp, and agent.
 */

import { memo, useState, useCallback } from 'react';
import { EXECUTION_STATUS_COLORS, type ExecutionStatus } from './types';

interface StatusBadgeProps {
  /** Current execution status. */
  status: ExecutionStatus;
  /** Optional receipt hash from execution. */
  receiptHash?: string;
  /** Optional agent that performed execution. */
  agent?: string;
  /** Optional timestamp of last status change. */
  timestamp?: number;
  /** Small variant for compact displays. */
  size?: 'sm' | 'md';
}

const STATUS_LABELS: Record<ExecutionStatus, string> = {
  pending: 'Pending',
  in_progress: 'Running',
  succeeded: 'Succeeded',
  failed: 'Failed',
  partial: 'Partial',
};

const STATUS_ICONS: Record<ExecutionStatus, string> = {
  pending: '\u25CB', // ○
  in_progress: '\u25D4', // ◔
  succeeded: '\u2713', // ✓
  failed: '\u2717', // ✗
  partial: '\u25D1', // ◑
};

export const StatusBadge = memo(function StatusBadge({
  status,
  receiptHash,
  agent,
  timestamp,
  size = 'sm',
}: StatusBadgeProps) {
  const [showTooltip, setShowTooltip] = useState(false);
  const colors = EXECUTION_STATUS_COLORS[status] || EXECUTION_STATUS_COLORS.pending;

  const handleMouseEnter = useCallback(() => setShowTooltip(true), []);
  const handleMouseLeave = useCallback(() => setShowTooltip(false), []);

  const hasDetails = receiptHash || agent || timestamp;
  const sizeClasses = size === 'sm' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-1 text-xs';

  return (
    <div
      className="relative inline-block"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <span
        className={`
          inline-flex items-center gap-1 rounded font-theme-data ring-1
          ${colors.bg} ${colors.text} ${colors.ring}
          ${sizeClasses}
          ${status === 'in_progress' ? 'animate-pulse' : ''}
        `}
      >
        <span>{STATUS_ICONS[status]}</span>
        {STATUS_LABELS[status]}
      </span>

      {showTooltip && hasDetails && (
        <div className="absolute z-50 bottom-full left-1/2 -translate-x-1/2 mb-1.5 w-48 p-2 rounded bg-surface border border-border shadow-lg text-xs">
          <div className="font-theme-data text-text-muted mb-1">{STATUS_LABELS[status]}</div>
          {agent && (
            <div className="flex justify-between">
              <span className="text-text-muted">Agent:</span>
              <span className="text-text truncate ml-2">{agent}</span>
            </div>
          )}
          {receiptHash && (
            <div className="flex justify-between">
              <span className="text-text-muted">Receipt:</span>
              <span className="text-text font-theme-data">{receiptHash.slice(0, 12)}</span>
            </div>
          )}
          {timestamp && (
            <div className="flex justify-between">
              <span className="text-text-muted">Time:</span>
              <span className="text-text">{new Date(timestamp * 1000).toLocaleTimeString()}</span>
            </div>
          )}
          <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-1/2 rotate-45 w-2 h-2 bg-surface border-r border-b border-border" />
        </div>
      )}
    </div>
  );
});

export default StatusBadge;
