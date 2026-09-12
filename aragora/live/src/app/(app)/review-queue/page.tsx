'use client';

import { useEffect, useState } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useReviewQueue, useReviewQueueStats } from '@/hooks/useReviewQueue';
import { ReviewQueueList, StatsHeader } from '@/components/review-queue';
import { Mode3LiveBanner } from '@/components/review-queue/Mode3LiveBanner';

/**
 * PDB UI v0 — browser-based PR review queue.
 *
 * This is the minimum viable surface described in
 * ``docs/plans/2026-04-19-pr-intelligence-brief-addendum.md §8``. It lets the
 * founder clear a morning's worth of PRs faster than GitHub's native UI while
 * preserving the human settlement gate (approve / request-changes still flow
 * through `gh`, which runs as the founder's own GitHub identity). Defer is
 * local-only state. No auto-merge, no bot approvals.
 */
export default function ReviewQueuePage() {
  const { prs, total, visible, deferredCount, degraded, reason, isLoading, error, mutate } =
    useReviewQueue();
  const { stats, mutate: refetchStats } = useReviewQueueStats();
  const [celebrated, setCelebrated] = useState(false);
  const [showCelebration, setShowCelebration] = useState(false);

  useEffect(() => {
    if (isLoading) return;
    if (!error && visible === 0 && total > 0 && !celebrated) {
      setShowCelebration(true);
      setCelebrated(true);
      const timer = setTimeout(() => setShowCelebration(false), 4000);
      return () => clearTimeout(timer);
    }
    if (visible > 0) {
      setCelebrated(false);
    }
  }, [celebrated, error, isLoading, total, visible]);

  const refetch = () => {
    void mutate();
    void refetchStats();
  };

  return (
    <div className="min-h-screen bg-bg text-text relative overflow-hidden">
      <Scanlines />
      <CRTVignette />
      <div className="max-w-6xl mx-auto px-4 py-8 relative z-10">
        <div className="mb-8">
          <div className="flex items-baseline gap-3 mb-2">
            <h1 className="text-xl font-theme-data font-bold text-[var(--accent)]">Review queue</h1>
            <span
              className="text-xs font-theme-data"
              style={{
                letterSpacing: '0.08em',
                textTransform: 'uppercase',
                color: 'var(--text-muted)',
              }}
            >
              PDB UI v0
            </span>
          </div>
          <p className="text-text-muted font-theme-data text-sm">
            Presidential-brief-style PR settlement. Scan, decide, move on.
          </p>
        </div>

        <Mode3LiveBanner />

        <StatsHeader
          visible={visible}
          total={total}
          deferredCount={deferredCount}
          stats={stats}
          degraded={degraded}
          reason={reason}
        />

        {error && (
          <div
            role="alert"
            data-testid="review-queue-page-error"
            className="mb-4 rounded-xl border px-4 py-3 text-sm"
            style={{
              borderColor: 'var(--crimson)',
              backgroundColor: 'rgba(255, 0, 64, 0.08)',
              color: 'var(--crimson)',
            }}
          >
            Failed to load queue: {(error as Error).message || 'unknown error'}
          </div>
        )}

        {isLoading ? (
          <div
            data-testid="review-queue-page-loading"
            className="py-12 text-center text-sm"
            style={{ color: 'var(--text-muted)' }}
          >
            loading queue…
          </div>
        ) : (
          <ReviewQueueList prs={prs} onSettled={refetch} />
        )}

        {showCelebration && (
          <div
            role="status"
            data-testid="review-queue-inbox-zero"
            className="fixed bottom-6 right-6 z-30 rounded-xl border px-5 py-4 shadow-xl"
            style={{
              borderColor: 'var(--accent)',
              backgroundColor: 'var(--surface-elevated)',
              boxShadow: 'var(--shadow-floating)',
              color: 'var(--text)',
            }}
          >
            <div className="font-theme-data text-base" style={{ color: 'var(--accent)' }}>
              inbox zero 🎉
            </div>
            <div className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
              Queue is clear. Streak: {stats?.streak ?? 0}.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
