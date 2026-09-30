/**
 * Tests for the StatsHeader component in the review-queue surface.
 */
import { render, screen } from '@testing-library/react';

import { StatsHeader } from '../src/components/review-queue/StatsHeader';
import type { ReviewQueueStats } from '../src/hooks/useReviewQueue';

function stats(partial: Partial<ReviewQueueStats> = {}): ReviewQueueStats {
  return {
    date: '2026-04-19',
    approved: 0,
    request_changes: 0,
    deferred: 0,
    streak: 0,
    decision_count: 0,
    median_decision_seconds: null,
    ...partial,
  };
}

describe('StatsHeader', () => {
  it('renders visible/deferred counts and median decision time', () => {
    render(
      <StatsHeader
        visible={3}
        total={5}
        deferredCount={2}
        stats={stats({ streak: 4, median_decision_seconds: 18, approved: 7 })}
      />,
    );

    expect(screen.getByTestId('review-queue-visible')).toHaveTextContent('3');
    expect(screen.getByTestId('review-queue-deferred-count')).toHaveTextContent('2 deferred');
    expect(screen.getByTestId('review-queue-median')).toHaveTextContent('18.0s');
    expect(screen.getByTestId('review-queue-streak')).toHaveTextContent('4');
    expect(screen.getByTestId('review-queue-approved-today')).toHaveTextContent('7');
    expect(screen.getByText('Approved today')).toBeInTheDocument();
    expect(screen.queryByText(/5 total/)).not.toBeInTheDocument();
  });

  it('shows degraded banner when degraded is true', () => {
    render(
      <StatsHeader
        visible={0}
        total={0}
        deferredCount={0}
        stats={null}
        degraded
        reason="gh CLI missing"
      />,
    );

    expect(screen.getByTestId('review-queue-degraded')).toHaveTextContent(/gh CLI missing/);
  });

  it('hides deferred count when zero', () => {
    render(<StatsHeader visible={1} total={1} deferredCount={0} stats={stats()} />);
    expect(screen.queryByTestId('review-queue-deferred-count')).toBeNull();
  });

  it('renders dash when median is unknown', () => {
    render(<StatsHeader visible={0} total={0} deferredCount={0} stats={stats()} />);
    expect(screen.getByTestId('review-queue-median')).toHaveTextContent('—');
  });
});
