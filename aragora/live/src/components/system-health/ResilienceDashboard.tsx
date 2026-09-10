'use client';

import { useMemo } from 'react';
import {
  useSystemHealth,
  useCircuitBreakers,
  type CircuitBreakerInfo,
} from '@/hooks/useSystemHealth';

// ============================================================================
// State styling
// ============================================================================

const STATE_BADGE: Record<string, { text: string; border: string; bg: string; dot: string }> = {
  closed: {
    text: 'text-[var(--accent)]',
    border: 'border-[var(--accent)]/40',
    bg: 'bg-[var(--accent)]/10',
    dot: 'bg-[var(--accent)] shadow-[0_0_4px_var(--acid-green)]',
  },
  open: {
    text: 'text-red-400',
    border: 'border-red-400/40',
    bg: 'bg-red-400/10',
    dot: 'bg-red-400 shadow-[0_0_4px_#f87171]',
  },
  'half-open': {
    text: 'text-[var(--acid-yellow)]',
    border: 'border-acid-yellow/40',
    bg: 'bg-acid-yellow/10',
    dot: 'bg-acid-yellow shadow-[0_0_4px_var(--acid-yellow)]',
  },
};

function formatTimestamp(ts: string | null): string {
  if (!ts) return 'Never';
  try {
    const date = new Date(ts);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    const diffDays = Math.floor(diffHours / 24);
    return `${diffDays}d ago`;
  } catch {
    return 'Unknown';
  }
}

// ============================================================================
// Health Summary Sub-component
// ============================================================================

function HealthSummaryCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string | number;
  color?: string;
}) {
  return (
    <div className="card p-3 text-center">
      <div className="text-[10px] font-theme-data text-text-muted uppercase mb-1">{label}</div>
      <div className={`text-lg font-theme-data font-bold ${color || 'text-text'}`}>{value}</div>
    </div>
  );
}

// ============================================================================
// Circuit Breaker Card
// ============================================================================

function CircuitBreakerCard({ breaker }: { breaker: CircuitBreakerInfo }) {
  const badge = STATE_BADGE[breaker.state] || STATE_BADGE.closed;

  const barColor =
    breaker.success_rate > 0.95
      ? 'bg-[var(--accent)]'
      : breaker.success_rate > 0.7
        ? 'bg-acid-yellow'
        : 'bg-red-400';

  return (
    <div className="card p-3 space-y-2 hover:border-border transition-colors">
      {/* Header: name + state badge */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className={`w-2 h-2 rounded-full flex-shrink-0 ${badge.dot}`} />
          <span className="font-theme-data text-xs text-text truncate" title={breaker.name}>
            {breaker.name}
          </span>
        </div>
        <span
          className={`text-[10px] font-theme-data px-2 py-0.5 border rounded flex-shrink-0 ${badge.text} ${badge.border} ${badge.bg}`}
        >
          {breaker.state.toUpperCase().replace('-', '_')}
        </span>
      </div>

      {/* Success rate bar */}
      <div className="h-1.5 bg-surface rounded overflow-hidden border border-border">
        <div
          className={`h-full transition-all duration-500 ${barColor}`}
          style={{ width: `${breaker.success_rate * 100}%` }}
        />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-1 text-[10px] font-theme-data text-text-muted">
        <div>
          <span className="block text-text-muted">Failures</span>
          <span className={breaker.failure_count > 0 ? 'text-red-400' : 'text-text'}>
            {breaker.failure_count}/{breaker.failure_threshold}
          </span>
        </div>
        <div>
          <span className="block text-text-muted">Success</span>
          <span className={breaker.success_rate > 0.95 ? 'text-[var(--accent)]' : 'text-text'}>
            {(breaker.success_rate * 100).toFixed(1)}%
          </span>
        </div>
        <div>
          <span className="block text-text-muted">Last Fail</span>
          <span>{formatTimestamp(breaker.last_failure)}</span>
        </div>
      </div>

      {/* Cooldown info for open/half-open */}
      {breaker.state !== 'closed' && breaker.cooldown_seconds > 0 && (
        <div className="text-[10px] font-theme-data text-[var(--acid-yellow)]">
          Cooldown: {breaker.cooldown_seconds}s
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Main Resilience Dashboard
// ============================================================================

export function ResilienceDashboard() {
  const { health, isLoading: healthLoading } = useSystemHealth();
  const { breakers, isLoading: breakersLoading, available } = useCircuitBreakers();

  const isLoading = healthLoading || breakersLoading;

  // Compute summary metrics
  const summary = useMemo(() => {
    const total = breakers.length;
    const closed = breakers.filter((b) => b.state === 'closed').length;
    const open = breakers.filter((b) => b.state === 'open').length;
    const halfOpen = breakers.filter((b) => b.state === 'half-open').length;

    // Average success rate across all breakers
    const avgSuccessRate =
      total > 0 ? breakers.reduce((sum, b) => sum + b.success_rate, 0) / total : 1;

    // Overall status
    let overallStatus: 'healthy' | 'degraded' | 'critical' = 'healthy';
    if (open > 0) overallStatus = 'critical';
    else if (halfOpen > 0) overallStatus = 'degraded';

    return { total, closed, open, halfOpen, avgSuccessRate, overallStatus };
  }, [breakers]);

  // Sort breakers: open first, then half-open, then closed
  const sortedBreakers = useMemo(() => {
    const stateOrder: Record<string, number> = { open: 0, 'half-open': 1, closed: 2 };
    return [...breakers].sort((a, b) => {
      const aOrder = stateOrder[a.state] ?? 3;
      const bOrder = stateOrder[b.state] ?? 3;
      if (aOrder !== bOrder) return aOrder - bOrder;
      // Secondary sort: by failure count descending
      return b.failure_count - a.failure_count;
    });
  }, [breakers]);

  if (isLoading) {
    return (
      <div className="space-y-4 animate-pulse">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card p-3 h-16 bg-surface rounded" />
          ))}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card p-3 h-24 bg-surface rounded" />
          ))}
        </div>
      </div>
    );
  }

  const statusColor =
    summary.overallStatus === 'healthy'
      ? 'text-[var(--accent)]'
      : summary.overallStatus === 'degraded'
        ? 'text-[var(--acid-yellow)]'
        : 'text-red-400';

  const statusGlow =
    summary.overallStatus === 'healthy'
      ? 'shadow-[0_0_12px_var(--acid-green)]'
      : summary.overallStatus === 'degraded'
        ? 'shadow-[0_0_12px_var(--acid-yellow)]'
        : 'shadow-[0_0_12px_#f87171]';

  const statusBg =
    summary.overallStatus === 'healthy'
      ? 'bg-[var(--accent)]'
      : summary.overallStatus === 'degraded'
        ? 'bg-acid-yellow'
        : 'bg-red-400';

  return (
    <div className="space-y-4">
      {/* Overall Status Banner */}
      <div className="card p-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className={`w-3 h-3 rounded-full ${statusBg} ${statusGlow} animate-pulse`} />
          <div>
            <h3 className={`font-theme-data text-sm font-bold ${statusColor}`}>
              {summary.overallStatus === 'healthy'
                ? 'RESILIENCE: ALL CIRCUITS HEALTHY'
                : summary.overallStatus === 'degraded'
                  ? 'RESILIENCE: DEGRADED - CIRCUITS RECOVERING'
                  : 'RESILIENCE: CRITICAL - OPEN CIRCUITS DETECTED'}
            </h3>
            {health && (
              <p className="font-theme-data text-[10px] text-text-muted">
                Last check:{' '}
                {health.last_check ? new Date(health.last_check).toLocaleTimeString() : 'N/A'}
              </p>
            )}
          </div>
        </div>
        <span className="font-theme-data text-xs text-text-muted">
          {summary.total} breaker{summary.total !== 1 ? 's' : ''} registered
        </span>
      </div>

      {/* Health Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <HealthSummaryCard label="Active Breakers" value={summary.total} />
        <HealthSummaryCard
          label="Avg Success Rate"
          value={`${(summary.avgSuccessRate * 100).toFixed(1)}%`}
          color={
            summary.avgSuccessRate > 0.95
              ? 'text-[var(--accent)]'
              : summary.avgSuccessRate > 0.7
                ? 'text-[var(--acid-yellow)]'
                : 'text-red-400'
          }
        />
        <HealthSummaryCard
          label="Open Circuits"
          value={summary.open}
          color={summary.open > 0 ? 'text-red-400' : 'text-[var(--accent)]'}
        />
        <HealthSummaryCard
          label="Half-Open"
          value={summary.halfOpen}
          color={summary.halfOpen > 0 ? 'text-[var(--acid-yellow)]' : 'text-[var(--accent)]'}
        />
      </div>

      {/* Uptime bar (visual representation of closed vs non-closed) */}
      {summary.total > 0 && (
        <div className="card p-3">
          <div className="flex items-center justify-between mb-2">
            <span className="font-theme-data text-xs text-text-muted">
              Circuit Health Distribution
            </span>
            <span className="font-theme-data text-[10px] text-[var(--accent)]">
              {summary.closed}/{summary.total} closed
            </span>
          </div>
          <div className="h-3 bg-surface rounded overflow-hidden border border-border flex">
            {summary.closed > 0 && (
              <div
                className="h-full bg-[var(--accent)] transition-all duration-500"
                style={{ width: `${(summary.closed / summary.total) * 100}%` }}
                title={`${summary.closed} closed`}
              />
            )}
            {summary.halfOpen > 0 && (
              <div
                className="h-full bg-acid-yellow transition-all duration-500"
                style={{ width: `${(summary.halfOpen / summary.total) * 100}%` }}
                title={`${summary.halfOpen} half-open`}
              />
            )}
            {summary.open > 0 && (
              <div
                className="h-full bg-red-400 transition-all duration-500"
                style={{ width: `${(summary.open / summary.total) * 100}%` }}
                title={`${summary.open} open`}
              />
            )}
          </div>
          <div className="flex gap-4 mt-1.5 text-[10px] font-theme-data">
            <span className="text-[var(--accent)]">{summary.closed} Closed</span>
            {summary.halfOpen > 0 && (
              <span className="text-[var(--acid-yellow)]">{summary.halfOpen} Half-Open</span>
            )}
            {summary.open > 0 && <span className="text-red-400">{summary.open} Open</span>}
          </div>
        </div>
      )}

      {/* Circuit Breaker Grid */}
      {!available ? (
        <div className="card p-6">
          <p className="text-text-muted font-theme-data text-xs text-center">
            Resilience registry unavailable. The circuit breaker subsystem may not be initialized.
          </p>
        </div>
      ) : sortedBreakers.length === 0 ? (
        <div className="card p-6">
          <p className="text-text-muted font-theme-data text-xs text-center">
            No circuit breakers registered. Breakers are created automatically when services are
            called.
          </p>
        </div>
      ) : (
        <div>
          <h4 className="font-theme-data text-xs text-[var(--accent)] mb-3">
            Circuit Breaker Status Grid
          </h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {sortedBreakers.map((breaker) => (
              <CircuitBreakerCard key={breaker.name} breaker={breaker} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
