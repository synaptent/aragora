'use client';

import React from 'react';

export type BreakerState = 'closed' | 'open' | 'half_open';

export interface CircuitBreaker {
  name: string;
  state: BreakerState;
  failure_count: number;
  success_count: number;
  last_failure?: string;
  reset_timeout_ms?: number;
}

export interface CircuitBreakerStatusProps {
  breakers: CircuitBreaker[];
  loading?: boolean;
}

const STATE_CONFIG: Record<
  BreakerState,
  { color: string; text: string; label: string; description: string }
> = {
  closed: {
    color: 'bg-success',
    text: 'text-success',
    label: 'CLOSED',
    description: 'Normal operation',
  },
  open: {
    color: 'bg-[var(--crimson)]',
    text: 'text-[var(--crimson)]',
    label: 'OPEN',
    description: 'Blocking requests',
  },
  half_open: {
    color: 'bg-acid-yellow',
    text: 'text-[var(--acid-yellow)]',
    label: 'HALF-OPEN',
    description: 'Testing recovery',
  },
};

export function CircuitBreakerStatus({ breakers, loading = false }: CircuitBreakerStatusProps) {
  if (loading) {
    return (
      <div className="bg-surface border border-[var(--accent)]/30 p-4 animate-pulse">
        <div className="w-32 h-4 bg-[var(--accent)]/20 rounded mb-4" />
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-12 bg-bg rounded" />
          ))}
        </div>
      </div>
    );
  }

  const openCount = breakers.filter((b) => b.state === 'open').length;
  const halfOpenCount = breakers.filter((b) => b.state === 'half_open').length;

  return (
    <div className="bg-surface border border-[var(--accent)]/30 p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase">
            {'>'} CIRCUIT BREAKERS
          </span>
        </div>
        <div className="flex items-center gap-2">
          {openCount > 0 && (
            <span className="px-2 py-0.5 text-xs font-theme-data bg-[var(--crimson)]/20 text-[var(--crimson)] rounded">
              {openCount} OPEN
            </span>
          )}
          {halfOpenCount > 0 && (
            <span className="px-2 py-0.5 text-xs font-theme-data bg-acid-yellow/20 text-[var(--acid-yellow)] rounded">
              {halfOpenCount} TESTING
            </span>
          )}
          {openCount === 0 && halfOpenCount === 0 && (
            <span className="px-2 py-0.5 text-xs font-theme-data bg-success/20 text-success rounded">
              ALL OK
            </span>
          )}
        </div>
      </div>

      {/* Breakers list */}
      {breakers.length === 0 ? (
        <div className="text-center text-text-muted font-theme-data text-sm py-4">
          No circuit breakers configured
        </div>
      ) : (
        <div className="space-y-2">
          {breakers.map((breaker) => {
            const config = STATE_CONFIG[breaker.state];
            return (
              <div key={breaker.name} className="bg-bg p-3 rounded">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className={`w-2 h-2 rounded-full ${config.color}`} />
                    <span className="text-sm font-theme-data text-text">{breaker.name}</span>
                  </div>
                  <span className={`text-xs font-theme-data ${config.text}`}>{config.label}</span>
                </div>
                <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
                  <span>
                    Failures: {breaker.failure_count} | Success: {breaker.success_count}
                  </span>
                  {breaker.state === 'open' && breaker.reset_timeout_ms && (
                    <span className="text-[var(--acid-yellow)]">
                      Reset in {Math.round(breaker.reset_timeout_ms / 1000)}s
                    </span>
                  )}
                </div>
                {breaker.last_failure && breaker.state !== 'closed' && (
                  <div className="mt-2 text-xs font-theme-data text-[var(--crimson)]/80 truncate">
                    Last: {breaker.last_failure}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
