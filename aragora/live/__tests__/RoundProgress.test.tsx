import { render, screen } from '@testing-library/react';
import { RoundProgress, RoundIndicator } from '../src/components/RoundProgress';
import type { StreamEvent } from '../src/types/events';

// Helper to create mock events
const createEvent = (overrides: Partial<StreamEvent> = {}): StreamEvent => ({
  type: 'agent_message',
  data: {},
  timestamp: Date.now() / 1000,
  round: 1,
  agent: 'claude',
  loop_id: 'test-loop',
  ...overrides,
});

describe('RoundProgress', () => {
  describe('initial rendering', () => {
    it('renders with default 4 rounds', () => {
      render(<RoundProgress events={[]} />);

      expect(screen.getByText('Debate Rounds')).toBeInTheDocument();
      expect(screen.getByText('0/4 complete')).toBeInTheDocument();
      expect(screen.getByText('R1')).toBeInTheDocument();
      expect(screen.getByText('R2')).toBeInTheDocument();
      expect(screen.getByText('R3')).toBeInTheDocument();
      expect(screen.getByText('R4')).toBeInTheDocument();
    });

    it('renders custom number of rounds', () => {
      render(<RoundProgress events={[]} totalRounds={6} />);

      expect(screen.getByText('0/6 complete')).toBeInTheDocument();
      expect(screen.getByText('R5')).toBeInTheDocument();
      expect(screen.getByText('R6')).toBeInTheDocument();
    });

    it('shows round stage names', () => {
      render(<RoundProgress events={[]} />);

      expect(screen.getByText('Initial Proposals')).toBeInTheDocument();
      expect(screen.getByText('Peer Review')).toBeInTheDocument();
      expect(screen.getByText('Revisions')).toBeInTheDocument();
      expect(screen.getByText('Final Synthesis')).toBeInTheDocument();
    });
  });

  describe('round status tracking', () => {
    it('marks rounds as complete when there are events in later rounds', () => {
      const events: StreamEvent[] = [
        createEvent({ round: 1, type: 'agent_message' }),
        createEvent({ round: 2, type: 'agent_message' }),
        createEvent({ round: 3, type: 'agent_message' }),
      ];

      render(<RoundProgress events={events} />);

      // Round 3 is active (highest with events)
      expect(screen.getByText('2/4 complete')).toBeInTheDocument();
    });

    it('shows active round detail panel', () => {
      const events: StreamEvent[] = [createEvent({ round: 2, type: 'agent_message' })];

      render(<RoundProgress events={events} />);

      // Active round panel should show
      expect(screen.getByText(/Round 2: Peer Review/)).toBeInTheDocument();
      expect(screen.getByText('Agents critique each other')).toBeInTheDocument();
    });

    it('counts agent messages per round', () => {
      const events: StreamEvent[] = [
        createEvent({ round: 1, type: 'agent_message', agent: 'claude' }),
        createEvent({ round: 1, type: 'agent_message', agent: 'gpt4' }),
        createEvent({ round: 1, type: 'agent_message', agent: 'gemini' }),
      ];

      render(<RoundProgress events={events} />);

      expect(screen.getByText('3 msgs')).toBeInTheDocument();
      expect(screen.getByText('3 responses')).toBeInTheDocument();
    });

    it('shows singular message count for single message', () => {
      const events: StreamEvent[] = [createEvent({ round: 1, type: 'agent_message' })];

      render(<RoundProgress events={events} />);

      expect(screen.getByText('1 msg')).toBeInTheDocument();
    });
  });

  describe('consensus tracking', () => {
    it('tracks consensus events', () => {
      const events: StreamEvent[] = [
        createEvent({ round: 1, type: 'agent_message' }),
        createEvent({ round: 1, type: 'consensus' }),
      ];

      render(<RoundProgress events={events} />);

      // Component should process consensus events without error
      expect(screen.getByText('Debate Rounds')).toBeInTheDocument();
    });
  });

  describe('timing display', () => {
    it('shows start time for active round', () => {
      const startTime = Math.floor(Date.now() / 1000);
      const events: StreamEvent[] = [
        createEvent({ round: 1, type: 'agent_message', timestamp: startTime }),
      ];

      render(<RoundProgress events={events} />);

      // Should show "Started" with time
      expect(screen.getByText(/Started/)).toBeInTheDocument();
    });
  });

  describe('edge cases', () => {
    it('handles events with round 0', () => {
      const events: StreamEvent[] = [
        createEvent({ round: 0, type: 'debate_start' }),
        createEvent({ round: 1, type: 'agent_message' }),
      ];

      render(<RoundProgress events={events} />);

      expect(screen.getByText('0/4 complete')).toBeInTheDocument();
    });

    it('handles events beyond totalRounds', () => {
      const events: StreamEvent[] = [createEvent({ round: 5, type: 'agent_message' })];

      render(<RoundProgress events={events} totalRounds={4} />);

      // Should not crash, round 5 should be ignored
      expect(screen.getByText('0/4 complete')).toBeInTheDocument();
    });

    it('handles empty events array', () => {
      render(<RoundProgress events={[]} />);

      expect(screen.getByText('0/4 complete')).toBeInTheDocument();
      // No active round detail panel should show
      expect(screen.queryByText(/Round \d+:/)).not.toBeInTheDocument();
    });
  });
});

describe('RoundIndicator', () => {
  it('renders compact round dots', () => {
    render(<RoundIndicator events={[]} />);

    // Should have 4 dots by default
    const dots = document.querySelectorAll('.rounded-full');
    expect(dots).toHaveLength(4);
  });

  it('highlights current round', () => {
    const events: StreamEvent[] = [createEvent({ round: 2, type: 'agent_message' })];

    render(<RoundIndicator events={events} />);

    // Current round dot should have animate-pulse class
    const dots = document.querySelectorAll('.rounded-full');
    expect(dots[1]).toHaveClass('animate-pulse');
  });

  it('marks completed rounds', () => {
    const events: StreamEvent[] = [createEvent({ round: 3, type: 'agent_message' })];

    render(<RoundIndicator events={events} />);

    // First two rounds should be complete (success color)
    const dots = document.querySelectorAll('.rounded-full');
    expect(dots[0]).toHaveClass('bg-success');
    expect(dots[1]).toHaveClass('bg-success');
    expect(dots[2]).toHaveClass('bg-accent'); // Current
    expect(dots[3]).toHaveClass('bg-border'); // Pending
  });

  it('respects custom totalRounds', () => {
    render(<RoundIndicator events={[]} totalRounds={6} />);

    const dots = document.querySelectorAll('.rounded-full');
    expect(dots).toHaveLength(6);
  });
});
