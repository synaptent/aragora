/**
 * Tests for ReviewQueueList: keyboard shortcuts, empty state, selection.
 */
import { act, render, screen, fireEvent, waitFor } from '@testing-library/react';

jest.mock('../src/config', () => ({
  API_BASE_URL: 'http://localhost:8080',
  WS_URL: 'ws://localhost:8765/ws',
}));

const settlePRMock = jest.fn();

jest.mock('../src/hooks/useReviewQueue', () => ({
  __esModule: true,
  fetchBrief: jest.fn().mockResolvedValue(null),
  useSettlePR:
    (onSettled?: () => void) =>
    async (prNumber: number, action: string, options: Record<string, unknown> = {}) => {
      const result = await settlePRMock(prNumber, action, options);
      onSettled?.();
      return result;
    },
  settlePR: jest.fn(),
  generateBrief: jest.fn().mockResolvedValue({ state: 'queued' }),
  getBriefState: jest.fn().mockResolvedValue({ state: 'absent' }),
  cancelBriefGeneration: jest.fn().mockResolvedValue(undefined),
  getBriefGenerationFlag: jest.fn(() => null),
  __resetBriefGenerationFlagForTests: jest.fn(),
  useBriefState: jest.fn(() => ({
    snapshot: null,
    isLoading: false,
    error: null,
    featureDisabled: false,
    refresh: jest.fn().mockResolvedValue(null),
    setSnapshot: jest.fn(),
  })),
}));

import { ReviewQueueList } from '../src/components/review-queue/ReviewQueueList';
import type { ReviewQueuePR } from '../src/hooks/useReviewQueue';

function makePR(overrides: Partial<ReviewQueuePR> = {}): ReviewQueuePR {
  return {
    number: 1,
    title: 'Example',
    url: 'https://example.test/1',
    head_sha: 'a'.repeat(16),
    is_draft: false,
    author: 'armand',
    labels: [],
    additions: 10,
    deletions: 2,
    changed_files: 1,
    created_at: '',
    updated_at: '',
    age_seconds: 60,
    touched_subsystems: ['aragora/server'],
    ci: { success: 1, failure: 0, pending: 0, total: 1 },
    brief_present: true,
    verdict: 'approve_candidate',
    confidence: 5,
    deferred: false,
    ...overrides,
  };
}

describe('ReviewQueueList', () => {
  beforeEach(() => {
    settlePRMock.mockReset();
    settlePRMock.mockResolvedValue({ status: 'ok' });
  });

  it('renders empty state when no visible PRs', () => {
    render(<ReviewQueueList prs={[]} />);
    expect(screen.getByTestId('review-queue-empty')).toBeInTheDocument();
  });

  it('filters out deferred PRs', () => {
    render(
      <ReviewQueueList
        prs={[
          makePR({ number: 1, title: 'visible' }),
          makePR({ number: 2, title: 'hidden', deferred: true }),
        ]}
      />,
    );
    expect(screen.getByTestId('review-queue-card-1')).toBeInTheDocument();
    expect(screen.queryByTestId('review-queue-card-2')).toBeNull();
  });

  it('navigates with j/k', () => {
    render(
      <ReviewQueueList
        prs={[makePR({ number: 1 }), makePR({ number: 2 }), makePR({ number: 3 })]}
      />,
    );
    expect(screen.getByTestId('review-queue-card-1')).toHaveAttribute('data-selected', 'true');
    fireEvent.keyDown(window, { key: 'j' });
    expect(screen.getByTestId('review-queue-card-2')).toHaveAttribute('data-selected', 'true');
    fireEvent.keyDown(window, { key: 'j' });
    expect(screen.getByTestId('review-queue-card-3')).toHaveAttribute('data-selected', 'true');
    fireEvent.keyDown(window, { key: 'j' }); // clamp at last
    expect(screen.getByTestId('review-queue-card-3')).toHaveAttribute('data-selected', 'true');
    fireEvent.keyDown(window, { key: 'k' });
    expect(screen.getByTestId('review-queue-card-2')).toHaveAttribute('data-selected', 'true');
  });

  it('toggles help overlay on ? and closes on Escape', () => {
    render(<ReviewQueueList prs={[makePR()]} />);
    fireEvent.keyDown(window, { key: '?' });
    expect(screen.getByTestId('review-queue-keyboard-help')).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByTestId('review-queue-keyboard-help')).toBeNull();
  });

  it('approves selected PR with keyboard "a"', async () => {
    render(<ReviewQueueList prs={[makePR({ number: 11 })]} confirmFn={() => true} />);
    fireEvent.keyDown(window, { key: 'a' });
    await waitFor(() => expect(settlePRMock).toHaveBeenCalled());
    expect(settlePRMock.mock.calls[0][0]).toBe(11);
    expect(settlePRMock.mock.calls[0][1]).toBe('approve');
  });

  it('defers selected PR with keyboard "d"', async () => {
    render(<ReviewQueueList prs={[makePR({ number: 22 })]} />);
    fireEvent.keyDown(window, { key: 'd' });
    await waitFor(() => expect(settlePRMock).toHaveBeenCalled());
    expect(settlePRMock.mock.calls[0][1]).toBe('defer');
    expect(settlePRMock.mock.calls[0][2]).toEqual(
      expect.objectContaining({ reason: 'keyboard defer' }),
    );
  });

  it('requests changes via prompt callback', async () => {
    render(<ReviewQueueList prs={[makePR({ number: 33 })]} promptFn={() => 'needs tests'} />);
    fireEvent.keyDown(window, { key: 'r' });
    await waitFor(() => expect(settlePRMock).toHaveBeenCalled());
    expect(settlePRMock.mock.calls[0][1]).toBe('request-changes');
    expect(settlePRMock.mock.calls[0][2]).toEqual(
      expect.objectContaining({ reason: 'needs tests' }),
    );
  });

  it('opens diff with "o"', () => {
    const openMock = jest.fn();
    (global as unknown as { open: jest.Mock }).open = openMock;
    render(<ReviewQueueList prs={[makePR({ number: 44, url: 'https://pr/44' })]} />);
    fireEvent.keyDown(window, { key: 'o' });
    expect(openMock).toHaveBeenCalledWith('https://pr/44', '_blank', 'noopener,noreferrer');
  });

  it('ignores keyboard events when focus is in a textarea', async () => {
    render(<ReviewQueueList prs={[makePR({ number: 55 })]} />);
    // Expand the card to surface a textarea via request-changes
    fireEvent.click(screen.getByTestId('review-queue-request-changes-55'));
    const textarea = screen.getByTestId('review-queue-reason-input-55');
    act(() => {
      textarea.focus();
    });
    fireEvent.keyDown(textarea, { key: 'a' });
    // settle should not have been triggered
    expect(settlePRMock).not.toHaveBeenCalled();
  });

  it('toggles expansion on Enter', async () => {
    render(<ReviewQueueList prs={[makePR({ number: 66 })]} />);
    const card = screen.getByTestId('review-queue-card-66');
    expect(card.querySelector('[data-testid="brief-panel"]')).toBeNull();
    fireEvent.keyDown(window, { key: 'Enter' });
    // Brief loading indicator or empty state appears once expanded
    await waitFor(() => {
      const newCard = screen.getByTestId('review-queue-card-66');
      expect(newCard.querySelector('[data-testid^="brief-panel"]')).not.toBeNull();
    });
  });
});
