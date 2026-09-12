'use client';

import type { ReviewQueueStats } from '@/hooks/useReviewQueue';
import { formatDecisionSeconds } from './format';

export interface StatsHeaderProps {
  visible: number;
  total: number;
  deferredCount: number;
  stats: ReviewQueueStats | null;
  degraded?: boolean;
  reason?: string;
}

export function StatsHeader({
  visible,
  total,
  deferredCount,
  stats,
  degraded,
  reason,
}: StatsHeaderProps) {
  const median = stats?.median_decision_seconds ?? null;
  const streak = stats?.streak ?? 0;
  const approved = stats?.approved ?? 0;

  // Styles are applied inline because Tailwind 4 in this project isn't
  // compiling some spacing utility classes (px-5, py-4, mt-*, mb-*, etc.).
  // Inline always wins.
  const tileStyle: React.CSSProperties = {
    backgroundColor: 'var(--surface)',
    borderColor: 'var(--border)',
    padding: '1rem 1.25rem',
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    minHeight: '5.5rem',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: '10px',
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: 'var(--text-muted)',
    marginBottom: '0.5rem',
  };

  const numberStyleBase: React.CSSProperties = {
    fontSize: '1.5rem',
    lineHeight: 1,
    fontFamily: 'var(--font-theme-data, var(--font-mono, monospace))',
  };

  const subTextStyle: React.CSSProperties = {
    fontSize: '11px',
    color: 'var(--text-muted)',
    marginTop: '0.5rem',
  };

  return (
    <header
      data-testid="review-queue-stats-header"
      className="flex flex-col"
      style={{ marginBottom: '2.5rem', gap: '0.75rem' }}
    >
      <div className="grid grid-cols-2 sm:grid-cols-5" style={{ gap: '0.75rem' }}>
        <div className="rounded-xl border" style={tileStyle}>
          <div style={labelStyle}>In queue</div>
          <div
            style={{ ...numberStyleBase, color: 'var(--accent)' }}
            data-testid="review-queue-visible"
            className="font-theme-data"
          >
            {visible}
          </div>
          {deferredCount > 0 ? (
            <div style={subTextStyle} data-testid="review-queue-deferred-count">
              {deferredCount} deferred
            </div>
          ) : (
            <div style={subTextStyle}>{total} total</div>
          )}
        </div>

        <div className="rounded-xl border" style={tileStyle}>
          <div style={labelStyle}>Median decision</div>
          <div
            style={{ ...numberStyleBase, color: 'var(--text)' }}
            data-testid="review-queue-median"
            className="font-theme-data"
          >
            {formatDecisionSeconds(median)}
          </div>
        </div>

        <div className="rounded-xl border" style={tileStyle}>
          <div style={labelStyle}>Streak</div>
          <div
            style={{
              ...numberStyleBase,
              color: streak > 0 ? 'var(--accent)' : 'var(--text-muted)',
            }}
            data-testid="review-queue-streak"
            className="font-theme-data"
          >
            {streak}
          </div>
        </div>

        <div className="rounded-xl border" style={tileStyle}>
          <div style={labelStyle}>Approved today</div>
          <div
            style={{ ...numberStyleBase, color: 'var(--text)' }}
            data-testid="review-queue-approved-today"
            className="font-theme-data"
          >
            {approved}
          </div>
        </div>

        <div
          className="col-span-2 rounded-xl border sm:col-span-1"
          style={{
            ...tileStyle,
            alignItems: 'center',
            justifyContent: 'center',
            flexDirection: 'row',
            gap: '0.5rem',
          }}
        >
          <kbd
            className="rounded-md border font-theme-data"
            style={{
              padding: '0.25rem 0.625rem',
              fontSize: '11px',
              borderColor: 'var(--border)',
              backgroundColor: 'var(--surface-elevated)',
              color: 'var(--text)',
            }}
          >
            ?
          </kbd>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>shortcuts</span>
        </div>
      </div>

      {degraded && (
        <div
          role="alert"
          data-testid="review-queue-degraded"
          className="rounded-xl border"
          style={{
            padding: '0.75rem 1rem',
            fontSize: '12px',
            borderColor: 'var(--warning)',
            backgroundColor: 'rgba(255, 255, 0, 0.06)',
            color: 'var(--warning)',
          }}
        >
          Queue running in degraded mode: {reason || 'gh CLI unavailable'}.
        </div>
      )}
    </header>
  );
}
