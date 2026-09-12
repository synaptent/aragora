/**
 * Tests for the BriefPanel component — covers both the legacy
 * brief/loading/error props AND the Mode 3 state-driven rendering for
 * all six lifecycle states (absent / queued / running / ready / failed
 * / stale).
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { BriefPanel } from '../src/components/review-queue/BriefPanel';
import type { BriefStateSnapshot, ReviewQueueBrief } from '../src/hooks/useReviewQueue';

function makeReadyBrief(overrides: Partial<ReviewQueueBrief> = {}): ReviewQueueBrief {
  return {
    pr_number: 42,
    head_sha: 'abcdef1234567890',
    verdict: 'approve_candidate',
    confidence: 4,
    logic: 'flow looks fine',
    security: 'no surface changes',
    maintainability: 'small diff',
    skeptic: 'watch for flaky CI',
    ...overrides,
  };
}

function makeSnapshot(
  state: BriefStateSnapshot['state'],
  extra: Partial<BriefStateSnapshot> = {},
): BriefStateSnapshot {
  return { state, ...extra };
}

describe('BriefPanel — legacy prop surface', () => {
  it('renders loading state', () => {
    render(<BriefPanel brief={null} loading />);
    expect(screen.getByTestId('brief-panel-loading')).toBeInTheDocument();
  });

  it('renders error state', () => {
    render(<BriefPanel brief={null} error="boom" />);
    expect(screen.getByTestId('brief-panel-error')).toHaveTextContent('boom');
  });

  it('renders legacy empty state when brief is null and generation not enabled', () => {
    render(<BriefPanel brief={null} />);
    expect(screen.getByTestId('brief-panel-empty')).toBeInTheDocument();
    // Legacy empty state does not show a generate button.
    expect(screen.queryByTestId('brief-panel-generate')).toBeNull();
  });

  it('renders all role sections when populated', () => {
    render(<BriefPanel brief={makeReadyBrief()} />);
    expect(screen.getByTestId('brief-verdict')).toHaveTextContent('approve_candidate');
    expect(screen.getByTestId('brief-confidence')).toHaveTextContent('confidence 4/5');
    expect(screen.getByTestId('brief-section-logic')).toHaveTextContent('flow looks fine');
    expect(screen.getByTestId('brief-section-security')).toHaveTextContent('no surface changes');
    expect(screen.getByTestId('brief-section-maintainability')).toHaveTextContent('small diff');
    expect(screen.getByTestId('brief-section-skeptic')).toHaveTextContent('watch for flaky CI');
  });

  it('shows em-dash for missing sections and hides confidence when null', () => {
    render(
      <BriefPanel
        brief={makeReadyBrief({
          verdict: 'needs_human_attention',
          confidence: null,
          logic: '',
          security: null,
          maintainability: '   ',
          skeptic: undefined as unknown as string,
        })}
      />,
    );
    expect(screen.getByTestId('brief-section-logic')).toHaveTextContent('—');
    expect(screen.getByTestId('brief-section-security')).toHaveTextContent('—');
    expect(screen.getByTestId('brief-section-maintainability')).toHaveTextContent('—');
    expect(screen.getByTestId('brief-section-skeptic')).toHaveTextContent('—');
    expect(screen.queryByTestId('brief-confidence')).toBeNull();
  });
});

describe('BriefPanel — Mode 3 lifecycle states', () => {
  it('absent: shows generation CTA when generationEnabled', () => {
    const onGenerate = jest.fn();
    render(
      <BriefPanel
        brief={null}
        state={makeSnapshot('absent')}
        generationEnabled
        onGenerate={onGenerate}
      />,
    );
    expect(screen.getByTestId('brief-panel-absent')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('brief-panel-generate'));
    expect(onGenerate).toHaveBeenCalledTimes(1);
  });

  it('absent: falls back to legacy empty-slate when generation disabled', () => {
    render(<BriefPanel brief={null} state={makeSnapshot('absent')} generationEnabled={false} />);
    expect(screen.getByTestId('brief-panel-empty')).toBeInTheDocument();
    expect(screen.queryByTestId('brief-panel-absent')).toBeNull();
    expect(screen.queryByTestId('brief-panel-generate')).toBeNull();
  });

  it('queued: renders queued skeleton with starting-soon copy', () => {
    render(<BriefPanel brief={null} state={makeSnapshot('queued')} generationEnabled />);
    expect(screen.getByTestId('brief-panel-queued')).toBeInTheDocument();
    expect(screen.getByTestId('brief-panel-spinner')).toBeInTheDocument();
    expect(screen.getByTestId('brief-panel-progress-detail')).toHaveTextContent(/Queued/i);
  });

  it('running: surfaces phase + roles + elapsed + cost in the progress row', () => {
    render(
      <BriefPanel
        brief={null}
        state={makeSnapshot('running', {
          phase: 'findings',
          rolesComplete: 3,
          rolesTotal: 8,
          elapsedSeconds: 45,
          costUsdSoFar: 0.12,
        })}
        generationEnabled
      />,
    );
    expect(screen.getByTestId('brief-panel-running')).toBeInTheDocument();
    const detail = screen.getByTestId('brief-panel-progress-detail');
    expect(detail).toHaveTextContent(/findings/i);
    expect(detail).toHaveTextContent(/3\/8 roles done/);
    expect(detail).toHaveTextContent(/~45s elapsed/);
    expect(detail).toHaveTextContent(/\$0\.12/);
  });

  it('ready: renders role sections when brief body is loaded', () => {
    render(<BriefPanel brief={makeReadyBrief()} state={makeSnapshot('ready')} generationEnabled />);
    expect(screen.getByTestId('brief-panel')).toBeInTheDocument();
    expect(screen.getByTestId('brief-verdict')).toHaveTextContent('approve_candidate');
  });

  it('ready: falls back to loading placeholder when body not yet fetched', () => {
    render(<BriefPanel brief={null} state={makeSnapshot('ready')} generationEnabled />);
    expect(screen.getByTestId('brief-panel-loading')).toBeInTheDocument();
  });

  it('failed: renders error + retry button; retry calls onRetry', () => {
    const onRetry = jest.fn();
    render(
      <BriefPanel
        brief={null}
        state={makeSnapshot('failed', {
          phase: 'findings',
          reason: 'model rate limited',
          costUsdSoFar: 0.07,
        })}
        generationEnabled
        onRetry={onRetry}
      />,
    );
    const panel = screen.getByTestId('brief-panel-failed');
    expect(panel).toHaveTextContent(/failed at findings/i);
    expect(screen.getByTestId('brief-panel-failed-reason')).toHaveTextContent('model rate limited');
    expect(screen.getByTestId('brief-panel-failed-cost')).toHaveTextContent('$0.07');
    fireEvent.click(screen.getByTestId('brief-panel-retry'));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('stale: renders warning + regenerate CTA; regenerate calls onGenerate', () => {
    const onGenerate = jest.fn();
    render(
      <BriefPanel
        brief={makeReadyBrief({ head_sha: 'oldshaaaaaaaaaaaaaaaa' })}
        state={makeSnapshot('stale', { headSha: 'newshaaaaaaaaaaaaaaa' })}
        generationEnabled
        onGenerate={onGenerate}
      />,
    );
    const panel = screen.getByTestId('brief-panel-stale');
    expect(panel).toHaveTextContent('oldshaaaaaaa');
    expect(panel).toHaveTextContent('newshaaaaaaa');
    fireEvent.click(screen.getByTestId('brief-panel-regenerate'));
    expect(onGenerate).toHaveBeenCalledTimes(1);
  });
});
