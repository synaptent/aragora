import { render, screen } from '@testing-library/react';
import { CritiqueSeverityMeter } from '../CritiqueSeverityMeter';
import type { StreamEvent } from '@/types/events';

// Mock agent colors
jest.mock('@/utils/agentColors', () => ({
  getAgentColors: (_agent: string) => ({
    bg: 'bg-cyan-500/20',
    text: 'text-cyan-400',
    border: 'border-cyan-500/40',
  }),
}));

const createCritiqueEvent = (
  overrides: Partial<{
    agent: string;
    target: string;
    severity: number;
    issues: string[];
    round: number;
    timestamp: number;
  }> = {},
): StreamEvent => ({
  type: 'critique',
  round: overrides.round ?? 1,
  timestamp: overrides.timestamp ?? Date.now(),
  data: {
    agent: overrides.agent ?? 'claude',
    target: overrides.target ?? 'gpt4',
    severity: overrides.severity ?? 5,
    issues: overrides.issues ?? ['Test issue'],
  },
});

describe('CritiqueSeverityMeter', () => {
  const mockAgents = ['claude', 'gpt4', 'gemini'];

  describe('empty state', () => {
    it('shows empty message when no critiques', () => {
      render(<CritiqueSeverityMeter events={[]} agents={mockAgents} />);

      expect(screen.getByText('No critiques recorded yet...')).toBeInTheDocument();
    });

    it('renders header in empty state', () => {
      render(<CritiqueSeverityMeter events={[]} agents={mockAgents} />);

      expect(screen.getByText(/CRITIQUE INTENSITY/)).toBeInTheDocument();
    });
  });

  describe('with critiques', () => {
    it('displays critique count', () => {
      const events = [
        createCritiqueEvent({ agent: 'claude', target: 'gpt4', severity: 5 }),
        createCritiqueEvent({ agent: 'gpt4', target: 'claude', severity: 7 }),
      ];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('2 critiques recorded')).toBeInTheDocument();
    });

    it('displays singular critique count', () => {
      const events = [createCritiqueEvent({ agent: 'claude', target: 'gpt4', severity: 5 })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('1 critique recorded')).toBeInTheDocument();
    });

    it('calculates and displays average severity', () => {
      const events = [createCritiqueEvent({ severity: 4 }), createCritiqueEvent({ severity: 6 })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('5.0/10')).toBeInTheDocument();
    });

    it('shows per-agent breakdown', () => {
      const events = [
        createCritiqueEvent({ agent: 'claude', severity: 6 }),
        createCritiqueEvent({ agent: 'claude', severity: 8 }),
        createCritiqueEvent({ agent: 'gpt4', severity: 4 }),
      ];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      // Agent names are truncated at first hyphen
      expect(screen.getByText('claude')).toBeInTheDocument();
      expect(screen.getByText('gpt4')).toBeInTheDocument();
      // Critique counts shown as 2× and 1×
      expect(screen.getByText('2×')).toBeInTheDocument();
      expect(screen.getByText('1×')).toBeInTheDocument();
    });
  });

  describe('severity labels', () => {
    it('displays CRITICAL for severity >= 8', () => {
      const events = [createCritiqueEvent({ severity: 9 })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('CRITICAL')).toBeInTheDocument();
    });

    it('displays MAJOR for severity 6-7', () => {
      const events = [createCritiqueEvent({ severity: 7 })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('MAJOR')).toBeInTheDocument();
    });

    it('displays MODERATE for severity 4-5', () => {
      const events = [createCritiqueEvent({ severity: 5 })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('MODERATE')).toBeInTheDocument();
    });

    it('displays MINOR for severity 2-3', () => {
      const events = [createCritiqueEvent({ severity: 3 })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('MINOR')).toBeInTheDocument();
    });

    it('displays TRIVIAL for severity < 2', () => {
      const events = [createCritiqueEvent({ severity: 1 })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('TRIVIAL')).toBeInTheDocument();
    });
  });

  describe('recent issues', () => {
    it('displays recent issues section', () => {
      const events = [createCritiqueEvent({ issues: ['First issue'] })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('Recent Issues')).toBeInTheDocument();
    });

    it('shows first issue from critique', () => {
      const events = [createCritiqueEvent({ issues: ['Argument lacks evidence', 'Second issue'] })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('Argument lacks evidence')).toBeInTheDocument();
    });

    it('shows last 3 critiques in reverse order', () => {
      const events = [
        createCritiqueEvent({ issues: ['Issue 1'], timestamp: 1000 }),
        createCritiqueEvent({ issues: ['Issue 2'], timestamp: 2000 }),
        createCritiqueEvent({ issues: ['Issue 3'], timestamp: 3000 }),
        createCritiqueEvent({ issues: ['Issue 4'], timestamp: 4000 }),
      ];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      // Should show last 3 (Issue 2, 3, 4) in reverse order (4, 3, 2)
      expect(screen.getByText('Issue 4')).toBeInTheDocument();
      expect(screen.getByText('Issue 3')).toBeInTheDocument();
      expect(screen.getByText('Issue 2')).toBeInTheDocument();
      expect(screen.queryByText('Issue 1')).not.toBeInTheDocument();
    });

    it('displays agent arrow notation', () => {
      const events = [createCritiqueEvent({ agent: 'claude', target: 'gpt4' })];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('claude → gpt4')).toBeInTheDocument();
    });
  });

  describe('filtering non-critique events', () => {
    it('ignores non-critique events', () => {
      const events: StreamEvent[] = [
        { type: 'message', round: 1, timestamp: Date.now(), data: { content: 'hello' } },
        createCritiqueEvent({ severity: 5 }),
        { type: 'vote', round: 1, timestamp: Date.now(), data: { votes: {} } },
      ];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('1 critique recorded')).toBeInTheDocument();
    });
  });

  describe('default severity', () => {
    it('uses default severity of 5 when not provided', () => {
      const events: StreamEvent[] = [
        {
          type: 'critique',
          round: 1,
          timestamp: Date.now(),
          data: {
            agent: 'claude',
            target: 'gpt4',
            // severity not provided
            issues: [],
          },
        },
      ];

      render(<CritiqueSeverityMeter events={events} agents={mockAgents} />);

      expect(screen.getByText('5.0/10')).toBeInTheDocument();
      expect(screen.getByText('MODERATE')).toBeInTheDocument();
    });
  });
});
