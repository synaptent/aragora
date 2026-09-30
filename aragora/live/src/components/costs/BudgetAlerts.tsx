'use client';

import { useState } from 'react';

interface Alert {
  id: string;
  type: string;
  message: string;
  severity: string;
  timestamp: string;
}

interface BudgetAlertsProps {
  alerts: Alert[];
  /** Callback when an alert is dismissed (sends to API) */
  onDismiss?: (alertId: string) => void | Promise<void>;
}

const SEVERITY_CONFIG: Record<string, { color: string; bgColor: string; icon: string }> = {
  critical: { color: 'text-red-400', bgColor: 'bg-red-500/10 border-red-500/30', icon: '🚨' },
  warning: {
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-500/10 border-yellow-500/30',
    icon: '⚠️',
  },
  info: { color: 'text-blue-400', bgColor: 'bg-blue-500/10 border-blue-500/30', icon: 'ℹ️' },
};

export function BudgetAlerts({ alerts, onDismiss }: BudgetAlertsProps) {
  const [dismissedAlerts, setDismissedAlerts] = useState<Set<string>>(new Set());
  const [expanded, setExpanded] = useState(true);
  const [dismissing, setDismissing] = useState<Set<string>>(new Set());

  const visibleAlerts = alerts.filter((a) => !dismissedAlerts.has(a.id));

  if (visibleAlerts.length === 0) return null;

  const dismissAlert = async (id: string) => {
    // Optimistic update - hide immediately
    setDismissedAlerts((prev) => new Set([...prev, id]));

    // Call API if provided
    if (onDismiss) {
      setDismissing((prev) => new Set([...prev, id]));
      try {
        await onDismiss(id);
      } catch {
        // Revert on error
        setDismissedAlerts((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      } finally {
        setDismissing((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      }
    }
  };

  const dismissAll = async () => {
    const ids = alerts.map((a) => a.id);
    setDismissedAlerts(new Set(ids));

    // Call API for each if provided
    if (onDismiss) {
      await Promise.all(
        ids.map(async (id) => {
          try {
            await onDismiss(id);
          } catch {
            // Ignore errors during bulk dismiss
          }
        }),
      );
    }
  };

  const formatTimeAgo = (timestamp: string): string => {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded overflow-hidden">
      {/* Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 flex items-center justify-between hover:bg-[var(--bg)] transition-colors"
      >
        <div className="flex items-center gap-3">
          <span className="text-xl">🔔</span>
          <div className="text-left">
            <h3 className="text-sm font-theme-data text-[var(--acid-green)]">BUDGET ALERTS</h3>
            <p className="text-xs text-[var(--text-muted)]">
              {visibleAlerts.length} active alert{visibleAlerts.length !== 1 ? 's' : ''}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={(e) => {
              e.stopPropagation();
              dismissAll();
            }}
            className="px-2 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          >
            Dismiss All
          </button>
          <span className="text-[var(--text-muted)]">{expanded ? '[-]' : '[+]'}</span>
        </div>
      </button>

      {/* Alerts List */}
      {expanded && (
        <div className="divide-y divide-[var(--border)]">
          {visibleAlerts.map((alert) => {
            const config = SEVERITY_CONFIG[alert.severity] || SEVERITY_CONFIG.info;

            return (
              <div key={alert.id} className={`p-4 ${config.bgColor} border-l-4`}>
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    <span className="text-lg">{config.icon}</span>
                    <div>
                      <p className={`text-sm ${config.color}`}>{alert.message}</p>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-xs text-[var(--text-muted)]">
                          {formatTimeAgo(alert.timestamp)}
                        </span>
                        <span className="text-xs text-[var(--text-muted)]">
                          • {alert.type.replace(/_/g, ' ')}
                        </span>
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={() => dismissAlert(alert.id)}
                    disabled={dismissing.has(alert.id)}
                    className="text-[var(--text-muted)] hover:text-[var(--text)] p-1 disabled:opacity-50"
                  >
                    {dismissing.has(alert.id) ? '...' : '✕'}
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default BudgetAlerts;
