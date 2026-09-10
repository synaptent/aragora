'use client';

import { useCircuitBreakers } from '@/hooks/useSystemHealth';

const STATE_BADGE: Record<string, { text: string; border: string; bg: string }> = {
  closed: {
    text: 'text-[var(--accent)]',
    border: 'border-[var(--accent)]/40',
    bg: 'bg-[var(--accent)]/10',
  },
  open: { text: 'text-acid-red', border: 'border-acid-red/40', bg: 'bg-acid-red/10' },
  'half-open': {
    text: 'text-[var(--acid-yellow)]',
    border: 'border-acid-yellow/40',
    bg: 'bg-acid-yellow/10',
  },
};

export function CircuitBreakerGrid() {
  const { breakers, isLoading, available } = useCircuitBreakers();

  if (isLoading) {
    return (
      <div className="card p-6 animate-pulse">
        <div className="h-4 bg-surface rounded w-40 mb-4" />
        <div className="grid grid-cols-2 gap-3">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-20 bg-surface rounded" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="card p-6">
      <h3 className="font-theme-data text-[var(--accent)] mb-4">Circuit Breakers</h3>
      {!available ? (
        <p className="text-text-muted font-theme-data text-xs">Resilience registry unavailable</p>
      ) : breakers.length === 0 ? (
        <p className="text-text-muted font-theme-data text-xs">No circuit breakers registered</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {breakers.map((b) => {
            const badge = STATE_BADGE[b.state] || STATE_BADGE.closed;
            const barColor =
              b.success_rate > 0.95
                ? 'bg-[var(--accent)]'
                : b.success_rate > 0.7
                  ? 'bg-acid-yellow'
                  : 'bg-acid-red';
            return (
              <div key={b.name} className="card p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <span className="font-theme-data text-xs text-text truncate max-w-[60%]">
                    {b.name}
                  </span>
                  <span
                    className={`text-[10px] font-theme-data px-2 py-0.5 border rounded ${badge.text} ${badge.border} ${badge.bg}`}
                  >
                    {b.state.toUpperCase().replace('-', '_')}
                  </span>
                </div>
                {/* Success rate bar */}
                <div className="h-1.5 bg-surface rounded overflow-hidden border border-border">
                  <div
                    className={`h-full transition-all duration-500 ${barColor}`}
                    style={{ width: `${b.success_rate * 100}%` }}
                  />
                </div>
                <div className="flex justify-between text-[10px] font-theme-data text-text-muted">
                  <span>
                    Failures: {b.failure_count}/{b.failure_threshold}
                  </span>
                  <span>{(b.success_rate * 100).toFixed(1)}%</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
