/**
 * Tests for StreamingMessageCard component
 *
 * Tests cover:
 * - Basic rendering with agent name and content
 * - Reasoning phase label display
 * - Confidence badge display
 * - Collapsible reasoning panel
 * - Evidence sources display
 * - Confidence progress bar
 * - Streaming indicator
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { StreamingMessageCard } from '../StreamingMessageCard';
import type { StreamingMessage } from '../types';

// Mock agentColors utility
jest.mock('@/utils/agentColors', () => ({
  getAgentColors: (agent: string) => ({
    bg: `bg-${agent}-500/20`,
    text: `text-${agent}-400`,
    border: `border-${agent}-500/30`,
  }),
}));

const createStreamingMessage = (overrides: Partial<StreamingMessage> = {}): StreamingMessage => ({
  agent: 'claude',
  taskId: '',
  content: 'This is a streaming response...',
  startTime: Date.now() - 5000, // 5 seconds ago
  reasoning: [],
  evidence: [],
  confidence: null,
  ...overrides,
});

describe('StreamingMessageCard', () => {
  describe('basic rendering', () => {
    it('renders agent name uppercased', () => {
      render(<StreamingMessageCard message={createStreamingMessage()} />);
      expect(screen.getByText('CLAUDE')).toBeInTheDocument();
    });

    it('renders message content', () => {
      render(
        <StreamingMessageCard message={createStreamingMessage({ content: 'Test response' })} />,
      );
      expect(screen.getByText('Test response')).toBeInTheDocument();
    });

    it('shows STREAMING indicator', () => {
      render(<StreamingMessageCard message={createStreamingMessage()} />);
      expect(screen.getByText('STREAMING')).toBeInTheDocument();
    });

    it('shows cursor indicator', () => {
      const { container } = render(<StreamingMessageCard message={createStreamingMessage()} />);
      // The cursor is a span with | text
      const cursor = container.querySelector('.bg-\\[var\\(--acid-cyan\\)\\]');
      expect(cursor).toBeInTheDocument();
    });
  });

  describe('reasoning phase label', () => {
    it('shows explicit reasoning phase', () => {
      render(
        <StreamingMessageCard message={createStreamingMessage({ reasoningPhase: 'EVALUATING' })} />,
      );
      expect(screen.getByText('EVALUATING')).toBeInTheDocument();
    });

    it('shows CITING EVIDENCE when evidence present', () => {
      render(
        <StreamingMessageCard
          message={createStreamingMessage({ evidence: [{ title: 'Paper A' }] })}
        />,
      );
      expect(screen.getByText('CITING EVIDENCE')).toBeInTheDocument();
    });

    it('shows FORMING ARGUMENT when reasoning present', () => {
      render(
        <StreamingMessageCard
          message={createStreamingMessage({
            reasoning: [{ thinking: 'Step 1', timestamp: Date.now() }],
          })}
        />,
      );
      expect(screen.getByText('FORMING ARGUMENT')).toBeInTheDocument();
    });

    it('shows ANALYZING for short content', () => {
      render(<StreamingMessageCard message={createStreamingMessage({ content: 'Short' })} />);
      expect(screen.getByText('ANALYZING')).toBeInTheDocument();
    });
  });

  describe('confidence badge', () => {
    it('shows confidence percentage when available', () => {
      render(<StreamingMessageCard message={createStreamingMessage({ confidence: 0.85 })} />);
      expect(screen.getByText('85% conf')).toBeInTheDocument();
    });

    it('does not show confidence badge when null', () => {
      render(<StreamingMessageCard message={createStreamingMessage({ confidence: null })} />);
      expect(screen.queryByText(/conf$/)).not.toBeInTheDocument();
    });
  });

  describe('reasoning panel', () => {
    it('shows [SHOW REASONING] button when reasoning data available', () => {
      render(
        <StreamingMessageCard
          message={createStreamingMessage({
            reasoning: [{ thinking: 'Step 1', timestamp: Date.now() }],
          })}
        />,
      );
      expect(screen.getByText('[SHOW REASONING]')).toBeInTheDocument();
    });

    it('toggles reasoning panel on click', () => {
      render(
        <StreamingMessageCard
          message={createStreamingMessage({
            reasoning: [{ thinking: 'Evaluating trade-offs', timestamp: Date.now(), step: 1 }],
          })}
        />,
      );

      const button = screen.getByText('[SHOW REASONING]');
      fireEvent.click(button);

      // Panel should now be visible
      expect(screen.getByText('Reasoning Chain')).toBeInTheDocument();
      expect(screen.getByText('Evaluating trade-offs')).toBeInTheDocument();
      expect(screen.getByText('[HIDE REASONING]')).toBeInTheDocument();
    });

    it('shows reasoning step numbers', () => {
      render(
        <StreamingMessageCard
          message={createStreamingMessage({
            reasoning: [{ thinking: 'First step', timestamp: Date.now(), step: 1 }],
          })}
        />,
      );

      fireEvent.click(screen.getByText('[SHOW REASONING]'));
      expect(screen.getByText('#1')).toBeInTheDocument();
    });

    it('shows evidence sources in panel', () => {
      render(
        <StreamingMessageCard
          message={createStreamingMessage({
            evidence: [{ title: 'Research Paper A', relevance: 0.95 }, { title: 'Blog Post B' }],
          })}
        />,
      );

      fireEvent.click(screen.getByText('[SHOW REASONING]'));

      expect(screen.getByText('Evidence Sources')).toBeInTheDocument();
      expect(screen.getByText('Research Paper A')).toBeInTheDocument();
      expect(screen.getByText('(95%)')).toBeInTheDocument();
      expect(screen.getByText('Blog Post B')).toBeInTheDocument();
    });

    it('shows confidence bar in panel', () => {
      const { container } = render(
        <StreamingMessageCard message={createStreamingMessage({ confidence: 0.75 })} />,
      );

      fireEvent.click(screen.getByText('[SHOW REASONING]'));

      expect(screen.getByText('Confidence')).toBeInTheDocument();
      // Check the confidence bar width
      const bar = container.querySelector('.bg-\\[var\\(--accent\\)\\].transition-all');
      expect(bar).toBeInTheDocument();
      expect(bar).toHaveStyle({ width: '75%' });
    });

    it('does not show reasoning button when no reasoning data', () => {
      render(
        <StreamingMessageCard
          message={createStreamingMessage({ reasoning: [], evidence: [], confidence: null })}
        />,
      );

      expect(screen.queryByText('[SHOW REASONING]')).not.toBeInTheDocument();
    });
  });

  describe('edge cases', () => {
    it('handles empty content', () => {
      render(<StreamingMessageCard message={createStreamingMessage({ content: '' })} />);
      expect(screen.getByText('CLAUDE')).toBeInTheDocument();
    });

    it('handles undefined reasoning fields', () => {
      render(
        <StreamingMessageCard
          message={createStreamingMessage({
            reasoning: undefined,
            evidence: undefined,
            confidence: undefined,
          })}
        />,
      );
      expect(screen.getByText('CLAUDE')).toBeInTheDocument();
    });

    it('renders multiple reasoning steps', () => {
      render(
        <StreamingMessageCard
          message={createStreamingMessage({
            reasoning: [
              { thinking: 'Step A', timestamp: Date.now(), step: 1 },
              { thinking: 'Step B', timestamp: Date.now(), step: 2 },
              { thinking: 'Step C', timestamp: Date.now(), step: 3 },
            ],
          })}
        />,
      );

      fireEvent.click(screen.getByText('[SHOW REASONING]'));

      expect(screen.getByText('Step A')).toBeInTheDocument();
      expect(screen.getByText('Step B')).toBeInTheDocument();
      expect(screen.getByText('Step C')).toBeInTheDocument();
    });
  });
});
