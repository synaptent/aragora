'use client';

import { useSLOStatus } from '@/hooks/useSystemHealth';

export function SLOStatusCards() {
  const { slos, isLoading, available, overallHealthy } = useSLOStatus();

  if (isLoading) {
    return (
      <div className="card p-6 animate-pulse">
        <div className="h-4 bg-surface rounded w-36 mb-4" />
        <div className="grid grid-cols-3 gap-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-24 bg-surface rounded" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="card p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="font-theme-data text-[var(--accent)]">SLO Compliance</h3>
        {available && (
          <span
            className={`text-[10px] font-theme-data px-2 py-0.5 rounded border ${
              overallHealthy
                ? 'text-[var(--accent)] border-[var(--accent)]/40 bg-[var(--accent)]/10'
                : 'text-acid-red border-acid-red/40 bg-acid-red/10'
            }`}
          >
            {overallHealthy ? 'ALL COMPLIANT' : 'BREACH DETECTED'}
          </span>
        )}
      </div>
      {!available ? (
        <p className="text-text-muted font-theme-data text-xs">SLO tracking unavailable</p>
      ) : slos.length === 0 ? (
        <p className="text-text-muted font-theme-data text-xs">No SLOs configured</p>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          {slos.map((s) => {
            const compliantColor = s.compliant ? 'acid-green' : 'acid-red';
            const burnColor =
              s.burn_rate > 5
                ? 'text-acid-red'
                : s.burn_rate > 1
                  ? 'text-[var(--acid-yellow)]'
                  : 'text-text-muted';
            // For latency SLO (lte comparison), gauge shows target/current
            const isLatency = s.key === 'latency_p99';
            const gaugePct = isLatency
              ? Math.min(100, s.target > 0 ? (s.target / Math.max(s.current, 0.001)) * 100 : 100)
              : Math.min(100, s.target > 0 ? (s.current / s.target) * 100 : 100);

            return (
              <div
                key={s.key}
                className={`card p-3 space-y-2 border-l-2 ${s.compliant ? 'border-[var(--accent)]' : 'border-acid-red'}`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-theme-data text-xs text-text">{s.name}</span>
                  <span
                    className={`text-[10px] font-theme-data px-1.5 py-0.5 rounded border ${
                      s.compliant
                        ? 'text-[var(--accent)] border-[var(--accent)]/40'
                        : 'text-acid-red border-acid-red/40'
                    }`}
                  >
                    {s.compliant ? 'OK' : 'BREACH'}
                  </span>
                </div>
                {/* Target vs current */}
                <div className="flex justify-between text-[10px] font-theme-data">
                  <span className="text-text-muted">
                    Target:{' '}
                    {isLatency
                      ? `${(s.target * 1000).toFixed(0)}ms`
                      : `${(s.target * 100).toFixed(2)}%`}
                  </span>
                  <span className={`text-${compliantColor}`}>
                    {isLatency
                      ? `${(s.current * 1000).toFixed(0)}ms`
                      : `${(s.current * 100).toFixed(2)}%`}
                  </span>
                </div>
                {/* Compliance gauge */}
                <div className="h-1.5 bg-surface rounded overflow-hidden border border-border">
                  <div
                    className={`h-full bg-${compliantColor} transition-all duration-500`}
                    style={{ width: `${gaugePct}%` }}
                  />
                </div>
                {/* Error budget and burn rate */}
                <div className="flex justify-between text-[10px] font-theme-data">
                  <span className="text-text-muted">
                    Budget: {s.error_budget_remaining.toFixed(1)}%
                  </span>
                  <span className={burnColor}>Burn: {s.burn_rate.toFixed(2)}x</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
