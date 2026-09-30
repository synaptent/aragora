/**
 * Tests for the ReviewQueueCard component: rendering, actions, confirm prompts.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

jest.mock('../src/config', () => ({
  API_BASE_URL: 'http://localhost:8080',
  WS_URL: 'ws://localhost:8765/ws',
}));

jest.mock('../src/hooks/useReviewQueue', () => ({
  fetchBrief: jest.fn(),
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

import { ReviewQueueCard } from '../src/components/review-queue/ReviewQueueCard';
import type { ReviewQueuePR } from '../src/hooks/useReviewQueue';
import { fetchBrief } from '../src/hooks/useReviewQueue';

function makePR(overrides: Partial<ReviewQueuePR> = {}): ReviewQueuePR {
  return {
    number: 42,
    title: 'Improve queue triage',
    url: 'https://github.com/example/repo/pull/42',
    head_sha: 'abcdef1234567890',
    is_draft: false,
    author: 'armand',
    labels: [],
    additions: 40,
    deletions: 10,
    changed_files: 3,
    created_at: '2026-04-19T06:00:00Z',
    updated_at: '2026-04-19T07:00:00Z',
    age_seconds: 3600,
    touched_subsystems: ['aragora/server', 'aragora/live/src'],
    ci: { success: 2, failure: 0, pending: 0, total: 2 },
    brief_present: false,
    verdict: null,
    confidence: null,
    deferred: false,
    ...overrides,
  };
}

describe('ReviewQueueCard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (fetchBrief as jest.Mock).mockReset();
    // Default: do not open real windows
    (global as unknown as { open: jest.Mock }).open = jest.fn();
  });

  it('renders key metadata', () => {
    render(
      <ReviewQueueCard
        pr={makePR()}
        selected
        expanded={false}
        onSelect={jest.fn()}
        onToggleExpand={jest.fn()}
        onSettle={jest.fn()}
      />,
    );
    expect(screen.getByTestId('review-queue-card-42')).toHaveAttribute('data-selected', 'true');
    expect(screen.getByText('PR')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText(/Improve queue triage/)).toBeInTheDocument();
    expect(screen.getByText('aragora/server')).toBeInTheDocument();
    expect(screen.getByText(/by armand/)).toBeInTheDocument();
  });

  it('approves silently when no brief exists yet', async () => {
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
    const onSettle = jest.fn().mockResolvedValue(undefined);
    render(
      <ReviewQueueCard
        pr={makePR()}
        selected={false}
        expanded={false}
        onSelect={jest.fn()}
        onToggleExpand={jest.fn()}
        onSettle={onSettle}
      />,
    );
    fireEvent.click(screen.getByTestId('review-queue-approve-42'));
    await waitFor(() => expect(onSettle).toHaveBeenCalledWith('approve', undefined));
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('prompts before approving when a present brief disagrees', () => {
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(false);
    const onSettle = jest.fn();
    render(
      <ReviewQueueCard
        pr={makePR({ brief_present: true, verdict: 'repair_first' })}
        selected={false}
        expanded={false}
        onSelect={jest.fn()}
        onToggleExpand={jest.fn()}
        onSettle={onSettle}
      />,
    );
    fireEvent.click(screen.getByTestId('review-queue-approve-42'));
    expect(confirmSpy).toHaveBeenCalled();
    expect(onSettle).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('approves silently when brief verdict is approve_candidate', async () => {
    const onSettle = jest.fn().mockResolvedValue(undefined);
    const confirmSpy = jest.spyOn(window, 'confirm').mockReturnValue(true);
    render(
      <ReviewQueueCard
        pr={makePR({ brief_present: true, verdict: 'approve_candidate' })}
        selected={false}
        expanded={false}
        onSelect={jest.fn()}
        onToggleExpand={jest.fn()}
        onSettle={onSettle}
      />,
    );
    fireEvent.click(screen.getByTestId('review-queue-approve-42'));
    await waitFor(() => expect(onSettle).toHaveBeenCalledWith('approve', undefined));
    expect(confirmSpy).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it('requires reason for request-changes and submits it', async () => {
    const onSettle = jest.fn().mockResolvedValue(undefined);
    render(
      <ReviewQueueCard
        pr={makePR()}
        selected={false}
        expanded={false}
        onSelect={jest.fn()}
        onToggleExpand={jest.fn()}
        onSettle={onSettle}
      />,
    );

    fireEvent.click(screen.getByTestId('review-queue-request-changes-42'));
    const input = screen.getByTestId('review-queue-reason-input-42');
    // Submitting empty reason surfaces error without calling onSettle
    fireEvent.click(screen.getByTestId('review-queue-reason-submit-42'));
    expect(onSettle).not.toHaveBeenCalled();

    // Provide reason and submit
    fireEvent.change(input, { target: { value: 'tests missing' } });
    fireEvent.click(screen.getByTestId('review-queue-reason-submit-42'));
    await waitFor(() =>
      expect(onSettle).toHaveBeenCalledWith('request-changes', { reason: 'tests missing' }),
    );
  });

  it('defers without prompting', async () => {
    const onSettle = jest.fn().mockResolvedValue(undefined);
    render(
      <ReviewQueueCard
        pr={makePR()}
        selected={false}
        expanded={false}
        onSelect={jest.fn()}
        onToggleExpand={jest.fn()}
        onSettle={onSettle}
      />,
    );
    fireEvent.click(screen.getByTestId('review-queue-defer-42'));
    await waitFor(() =>
      expect(onSettle).toHaveBeenCalledWith('defer', { reason: 'deferred from web UI' }),
    );
  });

  it('opens the diff in a new tab', () => {
    const openMock = jest.fn();
    (global as unknown as { open: jest.Mock }).open = openMock;
    render(
      <ReviewQueueCard
        pr={makePR()}
        selected={false}
        expanded={false}
        onSelect={jest.fn()}
        onToggleExpand={jest.fn()}
        onSettle={jest.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId('review-queue-open-diff-42'));
    expect(openMock).toHaveBeenCalledWith(
      'https://github.com/example/repo/pull/42',
      '_blank',
      'noopener,noreferrer',
    );
  });

  it('fetches the brief when expanded', async () => {
    (fetchBrief as jest.Mock).mockResolvedValue({
      pr_number: 42,
      head_sha: 'abcdef123',
      verdict: 'approve_candidate',
      confidence: 5,
      logic: 'fine',
      security: 'fine',
      maintainability: 'fine',
      skeptic: 'ok',
    });
    render(
      <ReviewQueueCard
        pr={makePR()}
        selected={false}
        expanded
        onSelect={jest.fn()}
        onToggleExpand={jest.fn()}
        onSettle={jest.fn()}
      />,
    );
    await waitFor(() => expect(fetchBrief).toHaveBeenCalledWith(42));
    await waitFor(() =>
      expect(screen.getByTestId('brief-verdict')).toHaveTextContent('approve_candidate'),
    );
  });
});
