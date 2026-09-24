'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';

interface Alert {
  id: string;
  severity: string;
  title: string;
  description: string;
  source: string;
  timestamp: string;
  acknowledged: boolean;
  acknowledged_by: string | null;
  debate_triggered: boolean;
  debate_id: string | null;
  metadata: Record<string, unknown>;
}

interface AlertsPanelProps {
  apiBase: string;
}

const SEVERITY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  info: { bg: 'bg-blue-500/10', text: 'text-blue-400', border: 'border-blue-500/30' },
  low: {
    bg: 'bg-[var(--accent)]/10',
    text: 'text-[var(--accent)]',
    border: 'border-[var(--accent)]/30',
  },
  medium: { bg: 'bg-yellow-500/10', text: 'text-yellow-500', border: 'border-yellow-500/30' },
  high: { bg: 'bg-orange-500/10', text: 'text-orange-400', border: 'border-orange-500/30' },
  critical: { bg: 'bg-red-500/10', text: 'text-red-400', border: 'border-red-500/30' },
};

export function AlertsPanel({ apiBase }: AlertsPanelProps) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState<string | null>(null);

  const fetchAlerts = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await apiFetch<{ alerts: Alert[] }>(`${apiBase}/autonomous/alerts/active`);
      if (result.error) {
        throw new Error(result.error);
      }
      setAlerts(result.data?.alerts ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch alerts');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  const handleAcknowledge = async (alertId: string) => {
    try {
      setActionLoading(alertId);
      await apiFetch(`${apiBase}/autonomous/alerts/${alertId}/acknowledge`, {
        method: 'POST',
        body: JSON.stringify({ acknowledged_by: 'dashboard_user' }),
      });
      await fetchAlerts();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to acknowledge');
    } finally {
      setActionLoading(null);
    }
  };

  const handleResolve = async (alertId: string) => {
    try {
      setActionLoading(alertId);
      await apiFetch(`${apiBase}/autonomous/alerts/${alertId}/resolve`, { method: 'POST' });
      await fetchAlerts();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to resolve');
    } finally {
      setActionLoading(null);
    }
  };

  if (loading && alerts.length === 0) {
    return <div className="text-white/50 animate-pulse">Loading alerts...</div>;
  }

  if (error) {
    return (
      <div className="p-4 bg-red-500/10 border border-red-500/30 rounded text-red-400">
        {error}
        <button onClick={fetchAlerts} className="ml-4 text-sm underline">
          Retry
        </button>
      </div>
    );
  }

  if (alerts.length === 0) {
    return (
      <div className="text-center py-12 text-white/50">
        <div className="text-4xl mb-2">🔔</div>
        <div>No active alerts</div>
      </div>
    );
  }

  // Sort by severity
  const sortedAlerts = [...alerts].sort((a, b) => {
    const severityOrder = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
    return (
      (severityOrder[a.severity as keyof typeof severityOrder] ?? 5) -
      (severityOrder[b.severity as keyof typeof severityOrder] ?? 5)
    );
  });

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <span className="text-sm text-white/70">
          {alerts.length} active alert{alerts.length !== 1 ? 's' : ''}
        </span>
        <button
          onClick={fetchAlerts}
          disabled={loading}
          aria-label="Refresh alerts"
          className="text-xs text-white/50 hover:text-white"
        >
          Refresh
        </button>
      </div>

      <div className="space-y-2">
        {sortedAlerts.map((alert) => {
          const style = SEVERITY_STYLES[alert.severity] ?? SEVERITY_STYLES.medium;

          return (
            <div key={alert.id} className={`border rounded-lg p-4 ${style.border} ${style.bg}`}>
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className={`font-medium ${style.text}`}>{alert.title}</span>
                    <span
                      className={`px-1.5 py-0.5 rounded text-xs uppercase ${style.bg} ${style.text}`}
                    >
                      {alert.severity}
                    </span>
                    {alert.acknowledged && (
                      <span className="px-1.5 py-0.5 rounded text-xs bg-white/10 text-white/50">
                        Ack
                      </span>
                    )}
                  </div>
                  <div className="text-sm text-white/50 mt-1">{alert.description}</div>
                  <div className="flex items-center gap-4 mt-2 text-xs text-white/40">
                    <span>Source: {alert.source}</span>
                    <span>{new Date(alert.timestamp).toLocaleString()}</span>
                    {alert.debate_triggered && (
                      <span className="text-[var(--acid-cyan)]">Debate triggered</span>
                    )}
                  </div>
                </div>

                <div className="flex gap-2">
                  {!alert.acknowledged && (
                    <button
                      onClick={() => handleAcknowledge(alert.id)}
                      disabled={actionLoading === alert.id}
                      aria-label={`Acknowledge alert: ${alert.title}`}
                      className="px-3 py-1.5 text-xs bg-white/10 hover:bg-white/20 text-white rounded transition-colors disabled:opacity-50"
                    >
                      {actionLoading === alert.id ? '...' : 'Ack'}
                    </button>
                  )}
                  <button
                    onClick={() => handleResolve(alert.id)}
                    disabled={actionLoading === alert.id}
                    aria-label={`Resolve alert: ${alert.title}`}
                    className="px-3 py-1.5 text-xs bg-[var(--accent)]/20 hover:bg-[var(--accent)]/30 text-[var(--accent)] rounded transition-colors disabled:opacity-50"
                  >
                    {actionLoading === alert.id ? '...' : 'Resolve'}
                  </button>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default AlertsPanel;
