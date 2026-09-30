/**
 * Tests for PacketDecisionCard — per-PR card used by the
 * `/review-queue/packets/[receiptId]` settlement-packet sign-off
 * surface. Confirms decision selection, comment capture, tier-badge
 * rendering, and recommended-action display all behave as the page
 * layer expects.
 */
import { render, screen, fireEvent } from '@testing-library/react';

import {
  PACKET_DECISION_OPTIONS,
  PacketDecisionCard,
  type PacketDecisionId,
} from '../src/components/review-queue/PacketDecisionCard';
import type { ReviewQueuePR } from '../src/hooks/useReviewQueue';

function makePR(overrides: Partial<ReviewQueuePR> = {}): ReviewQueuePR {
  return {
    number: 7240,
    title: 'codex desktop inspector',
    url: 'https://github.com/synaptent/aragora/pull/7240',
    head_sha: 'aaaaaaaaaaaaaaaa',
    is_draft: false,
    author: '(unknown)',
    labels: [],
    additions: 0,
    deletions: 0,
    changed_files: 0,
    created_at: '2026-05-17T00:00:00Z',
    updated_at: '2026-05-17T00:00:00Z',
    age_seconds: 3600,
    touched_subsystems: [],
    ci: { success: 57, failure: 0, pending: 0, total: 57 },
    brief_present: false,
    verdict: null,
    confidence: null,
    deferred: false,
    tier: '2',
    ...overrides,
  };
}

describe('PacketDecisionCard', () => {
  it('renders PR identity, tier badge, CI summary and title link', () => {
    render(
      <PacketDecisionCard
        pr={makePR()}
        decision={null}
        comment=""
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    expect(screen.getByTestId('packet-decision-card-7240')).toBeInTheDocument();
    expect(screen.getByTestId('packet-decision-tier-7240')).toHaveTextContent('T2');
    expect(screen.getByTestId('packet-decision-ci-7240')).toHaveTextContent(/57\/57/);
    const titleLink = screen.getByTestId('packet-decision-title-7240');
    expect(titleLink).toHaveTextContent('codex desktop inspector');
    expect(titleLink).toHaveAttribute('href', 'https://github.com/synaptent/aragora/pull/7240');
  });

  it('hides the tier badge when no tier is supplied', () => {
    render(
      <PacketDecisionCard
        pr={makePR({ tier: null })}
        decision={null}
        comment=""
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    expect(screen.queryByTestId('packet-decision-tier-7240')).toBeNull();
  });

  it('renders draft state when PR is draft', () => {
    render(
      <PacketDecisionCard
        pr={makePR({ is_draft: true })}
        decision={null}
        comment=""
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    expect(screen.getByTestId('packet-decision-draft-7240')).toHaveTextContent('draft');
  });

  it('shows the recommended action when supplied', () => {
    render(
      <PacketDecisionCard
        pr={makePR()}
        decision={null}
        comment=""
        recommendedAction="APPROVE Tier 2"
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    expect(screen.getByTestId('packet-decision-recommendation-7240')).toHaveTextContent(
      'Recommended: APPROVE Tier 2',
    );
  });

  it('renders all five decision options', () => {
    render(
      <PacketDecisionCard
        pr={makePR()}
        decision={null}
        comment=""
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    PACKET_DECISION_OPTIONS.forEach((opt) => {
      expect(screen.getByTestId(`packet-decision-option-7240-${opt.id}`)).toBeInTheDocument();
    });
    expect(PACKET_DECISION_OPTIONS).toHaveLength(5);
  });

  it('reports the chosen decision via onDecisionChange', () => {
    const onDecisionChange = jest.fn();
    render(
      <PacketDecisionCard
        pr={makePR()}
        decision={null}
        comment=""
        onDecisionChange={onDecisionChange}
        onCommentChange={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('packet-decision-option-7240-approve_tier'));
    expect(onDecisionChange).toHaveBeenCalledTimes(1);
    expect(onDecisionChange).toHaveBeenCalledWith<PacketDecisionId[]>('approve_tier');
  });

  it('marks the currently-selected decision as checked', () => {
    render(
      <PacketDecisionCard
        pr={makePR()}
        decision="reject"
        comment=""
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    const rejectInput = screen.getByTestId(
      'packet-decision-option-7240-reject',
    ) as HTMLInputElement;
    const approveInput = screen.getByTestId(
      'packet-decision-option-7240-approve_tier',
    ) as HTMLInputElement;
    expect(rejectInput.checked).toBe(true);
    expect(approveInput.checked).toBe(false);
  });

  it('reports comment changes via onCommentChange', () => {
    const onCommentChange = jest.fn();
    render(
      <PacketDecisionCard
        pr={makePR()}
        decision={null}
        comment=""
        onDecisionChange={jest.fn()}
        onCommentChange={onCommentChange}
      />,
    );

    const textarea = screen.getByTestId('packet-decision-comment-7240');
    fireEvent.change(textarea, { target: { value: 'looks ok' } });
    expect(onCommentChange).toHaveBeenCalledWith('looks ok');
  });

  it('renders the selected visual treatment when `selected` is true', () => {
    const { rerender } = render(
      <PacketDecisionCard
        pr={makePR()}
        decision={null}
        comment=""
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    const cardUnselected = screen.getByTestId('packet-decision-card-7240');
    expect(cardUnselected).toHaveAttribute('data-selected', 'false');
    expect(cardUnselected).toHaveAttribute('aria-selected', 'false');

    rerender(
      <PacketDecisionCard
        pr={makePR()}
        decision={null}
        comment=""
        selected
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    const cardSelected = screen.getByTestId('packet-decision-card-7240');
    expect(cardSelected).toHaveAttribute('data-selected', 'true');
    expect(cardSelected).toHaveAttribute('aria-selected', 'true');
  });

  it('calls onSelect when the card chrome is clicked', () => {
    const onSelect = jest.fn();
    render(
      <PacketDecisionCard
        pr={makePR()}
        decision={null}
        comment=""
        onSelect={onSelect}
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    fireEvent.click(screen.getByTestId('packet-decision-card-7240'));
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('renders 1..5 digit shortcut hints next to each option', () => {
    render(
      <PacketDecisionCard
        pr={makePR()}
        decision={null}
        comment=""
        onDecisionChange={jest.fn()}
        onCommentChange={jest.fn()}
      />,
    );

    const list = screen.getByTestId('packet-decision-options-7240');
    expect(list).toHaveTextContent('1.');
    expect(list).toHaveTextContent('5.');
  });
});
