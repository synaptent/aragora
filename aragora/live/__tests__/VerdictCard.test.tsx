/**
 * Tests for VerdictCard component
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { VerdictCard, VerdictBadge } from '../src/components/VerdictCard';
import type { StreamEvent } from '../src/types/events';

describe('VerdictCard', () => {
  const mockTimestamp = Date.now() / 1000;

  // Helper to create verdict event
  const createVerdictEvent = (
    data: Record<string, unknown>,
    type: 'grounded_verdict' | 'verdict' | 'consensus' = 'grounded_verdict',
  ): StreamEvent => ({ type, data, timestamp: mockTimestamp });

  describe('Rendering', () => {
    it('renders null when no verdict events exist', () => {
      const { container } = render(<VerdictCard events={[]} />);
      expect(container.firstChild).toBeNull();
    });

    it('renders null when events have no verdict type', () => {
      const events: StreamEvent[] = [{ type: 'agent_message', data: {}, timestamp: mockTimestamp }];
      const { container } = render(<VerdictCard events={events} />);
      expect(container.firstChild).toBeNull();
    });

    it('renders verdict card when grounded_verdict event exists', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'The test passed successfully.', confidence: 0.85 }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('Debate Verdict')).toBeInTheDocument();
      expect(screen.getByText('The test passed successfully.')).toBeInTheDocument();
    });

    it('renders verdict card when consensus event exists', () => {
      const events: StreamEvent[] = [
        createVerdictEvent(
          { content: 'Consensus reached on the topic.', confidence: 0.75 },
          'consensus',
        ),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('Debate Verdict')).toBeInTheDocument();
      expect(screen.getByText('Consensus reached on the topic.')).toBeInTheDocument();
    });

    it('uses latest verdict event when multiple exist', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'First verdict' }),
        createVerdictEvent({ recommendation: 'Latest verdict' }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('Latest verdict')).toBeInTheDocument();
      expect(screen.queryByText('First verdict')).not.toBeInTheDocument();
    });
  });

  describe('Confidence Display', () => {
    it('displays high confidence in green', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'High confidence verdict', confidence: 0.85 }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('85%')).toBeInTheDocument();
      expect(screen.getByText('85%')).toHaveClass('text-green-400');
    });

    it('displays medium confidence in yellow', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'Medium confidence verdict', confidence: 0.65 }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('65%')).toBeInTheDocument();
      expect(screen.getByText('65%')).toHaveClass('text-yellow-400');
    });

    it('displays low confidence in red', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'Low confidence verdict', confidence: 0.45 }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('45%')).toBeInTheDocument();
      expect(screen.getByText('45%')).toHaveClass('text-red-400');
    });
  });

  describe('Grounding Score', () => {
    it('displays grounding score when present', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({
          recommendation: 'Well grounded verdict',
          confidence: 0.8,
          grounding_score: 0.75,
        }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('Evidence:')).toBeInTheDocument();
      expect(screen.getByText('75%')).toBeInTheDocument();
    });

    it('does not display grounding section when score is 0', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'No grounding', confidence: 0.8, grounding_score: 0 }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.queryByText('Evidence:')).not.toBeInTheDocument();
    });

    it('uses evidence_grounding as fallback', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'Verdict', confidence: 0.8, evidence_grounding: 0.6 }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('60%')).toBeInTheDocument();
    });
  });

  describe('Citation Count', () => {
    it('displays citation count when present', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'Cited verdict', confidence: 0.8, citation_count: 5 }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('5')).toBeInTheDocument();
      expect(screen.getByText('📚')).toBeInTheDocument();
    });

    it('counts all_citations array when present', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({
          recommendation: 'Cited verdict',
          confidence: 0.8,
          all_citations: ['cite1', 'cite2', 'cite3'],
        }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('3')).toBeInTheDocument();
    });

    it('does not display citation count when 0', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'No citations', confidence: 0.8, citation_count: 0 }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.queryByText('📚')).not.toBeInTheDocument();
    });
  });

  describe('Unanimous Issues', () => {
    it('displays unanimous issues', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({
          recommendation: 'Verdict',
          confidence: 0.8,
          unanimous_issues: ['Security concern', 'Performance issue'],
        }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('2 Unanimous Issues')).toBeInTheDocument();
      expect(screen.getByText('• Security concern')).toBeInTheDocument();
      expect(screen.getByText('• Performance issue')).toBeInTheDocument();
    });

    it('shows +N more when more than 2 issues', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({
          recommendation: 'Verdict',
          confidence: 0.8,
          unanimous_issues: ['Issue 1', 'Issue 2', 'Issue 3', 'Issue 4'],
        }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('4 Unanimous Issues')).toBeInTheDocument();
      expect(screen.getByText('+2 more')).toBeInTheDocument();
    });
  });

  describe('Split Opinions', () => {
    it('displays split opinions', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({
          recommendation: 'Verdict',
          confidence: 0.8,
          split_opinions: ['Approach A vs B'],
        }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('1 Split Opinion')).toBeInTheDocument();
      expect(screen.getByText('• Approach A vs B')).toBeInTheDocument();
    });
  });

  describe('Risk Areas', () => {
    it('displays risk areas', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({
          recommendation: 'Verdict',
          confidence: 0.8,
          risk_areas: ['Data loss', 'API breaking change'],
        }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('2 Risk Areas')).toBeInTheDocument();
      expect(screen.getByText('• Data loss')).toBeInTheDocument();
      expect(screen.getByText('• API breaking change')).toBeInTheDocument();
    });
  });

  describe('Long Recommendation Expansion', () => {
    it('truncates long recommendations by default', () => {
      const longText = 'A'.repeat(400);
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: longText, confidence: 0.8 }),
      ];

      render(<VerdictCard events={events} />);

      // Should show truncated text with ellipsis
      expect(screen.getByText(/\.\.\.$/)).toBeInTheDocument();
      expect(screen.getByText('Show more')).toBeInTheDocument();
    });

    it('expands recommendation on button click', () => {
      const longText = 'A'.repeat(400);
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: longText, confidence: 0.8 }),
      ];

      render(<VerdictCard events={events} />);

      fireEvent.click(screen.getByText('Show more'));

      expect(screen.getByText('Show less')).toBeInTheDocument();
      expect(screen.getByText(longText)).toBeInTheDocument();
    });

    it('does not show expand button for short recommendations', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({ recommendation: 'Short text', confidence: 0.8 }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.queryByText('Show more')).not.toBeInTheDocument();
    });
  });

  describe('Cross-Examination Notes', () => {
    it('displays cross-examination section when present', () => {
      const events: StreamEvent[] = [
        createVerdictEvent({
          recommendation: 'Verdict',
          confidence: 0.8,
          cross_examination_notes: 'Detailed examination notes here.',
        }),
      ];

      render(<VerdictCard events={events} />);

      expect(screen.getByText('Cross-Examination Notes')).toBeInTheDocument();
    });
  });
});

describe('VerdictBadge', () => {
  it('renders high confidence badge in green', () => {
    render(<VerdictBadge confidence={0.85} />);

    expect(screen.getByText(/85%/)).toBeInTheDocument();
    expect(screen.getByText(/85%/).closest('span')).toHaveClass('text-green-400');
  });

  it('renders medium confidence badge in yellow', () => {
    render(<VerdictBadge confidence={0.65} />);

    expect(screen.getByText(/65%/)).toBeInTheDocument();
    expect(screen.getByText(/65%/).closest('span')).toHaveClass('text-yellow-400');
  });

  it('renders low confidence badge in red', () => {
    render(<VerdictBadge confidence={0.45} />);

    expect(screen.getByText(/45%/)).toBeInTheDocument();
    expect(screen.getByText(/45%/).closest('span')).toHaveClass('text-red-400');
  });
});
