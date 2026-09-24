/**
 * Tests for ConsensusMeter component
 *
 * Tests cover:
 * - Initial waiting state
 * - Vote display
 * - Consensus states (waiting, diverging, converging, consensus, deadlock)
 * - Agreement percentage calculation
 * - Consensus reached display
 */

import { render, screen } from '@testing-library/react';
import { ConsensusMeter } from '../ConsensusMeter';
import type { StreamEvent } from '@/types/events';

// Mock agentColors utility
jest.mock('@/utils/agentColors', () => ({
  getAgentColors: (_agent: string) => ({
    bg: 'bg-blue-500/20',
    text: 'text-blue-400',
    border: 'border-blue-500/30',
  }),
}));

const createVoteEvent = (
  agent: string,
  choice: string,
  confidence = 0.8,
  timestamp = Date.now() / 1000,
): StreamEvent => ({ type: 'vote', data: { agent, choice, confidence }, timestamp });

const createConsensusEvent = (
  reached: boolean,
  answer?: string,
  confidence?: number,
): StreamEvent => ({
  type: 'consensus',
  data: { reached, answer, confidence },
  timestamp: Date.now() / 1000,
});

describe('ConsensusMeter', () => {
  const defaultAgents = ['claude', 'gpt-4', 'gemini'];

  describe('initial state', () => {
    it('renders header', () => {
      render(<ConsensusMeter events={[]} agents={defaultAgents} />);

      expect(screen.getByText(/CONSENSUS METER/)).toBeInTheDocument();
    });

    it('shows AWAITING VOTES when no votes', () => {
      render(<ConsensusMeter events={[]} agents={defaultAgents} />);

      expect(screen.getByText('AWAITING VOTES')).toBeInTheDocument();
    });

    it('shows waiting message when no votes', () => {
      render(<ConsensusMeter events={[]} agents={defaultAgents} />);

      expect(screen.getByText(/Waiting for agents to cast votes/)).toBeInTheDocument();
    });

    it('shows 0% agreement with no votes', () => {
      render(<ConsensusMeter events={[]} agents={defaultAgents} />);

      expect(screen.getByText('0%')).toBeInTheDocument();
    });

    it('shows vote count', () => {
      render(<ConsensusMeter events={[]} agents={defaultAgents} />);

      expect(screen.getByText('Votes (0/3)')).toBeInTheDocument();
    });
  });

  describe('vote display', () => {
    it('displays votes when agents vote', () => {
      const events = [createVoteEvent('claude', 'Option A', 0.9)];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('Option A')).toBeInTheDocument();
      expect(screen.getByText('Votes (1/3)')).toBeInTheDocument();
    });

    it('shows agent name in vote', () => {
      const events = [createVoteEvent('claude', 'Option A', 0.9)];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      // Agent name is truncated at hyphen
      expect(screen.getByText('claude')).toBeInTheDocument();
    });

    it('shows confidence percentage', () => {
      const events = [createVoteEvent('claude', 'Option A', 0.85)];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('85%')).toBeInTheDocument();
    });

    it('groups votes by choice', () => {
      const events = [
        createVoteEvent('claude', 'Option A', 0.9),
        createVoteEvent('gpt-4', 'Option A', 0.85),
        createVoteEvent('gemini', 'Option B', 0.7),
      ];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('Option A')).toBeInTheDocument();
      expect(screen.getByText('(2)')).toBeInTheDocument(); // 2 votes for Option A
      expect(screen.getByText('Option B')).toBeInTheDocument();
      expect(screen.getByText('(1)')).toBeInTheDocument(); // 1 vote for Option B
    });

    it('uses latest vote when agent votes multiple times', () => {
      const events = [
        createVoteEvent('claude', 'Option A', 0.5, 1000),
        createVoteEvent('claude', 'Option B', 0.9, 2000), // Later vote
      ];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('Option B')).toBeInTheDocument();
      expect(screen.queryByText('Option A')).not.toBeInTheDocument();
    });
  });

  describe('consensus states', () => {
    it('shows DIVERGING when votes are split', () => {
      const events = [createVoteEvent('claude', 'Option A'), createVoteEvent('gpt-4', 'Option B')];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('DIVERGING')).toBeInTheDocument();
    });

    it('shows CONVERGING when majority agrees', () => {
      const events = [
        createVoteEvent('claude', 'Option A'),
        createVoteEvent('gpt-4', 'Option A'),
        createVoteEvent('gemini', 'Option B'),
      ];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('CONVERGING')).toBeInTheDocument();
    });

    it('shows CONSENSUS when consensus event received', () => {
      const events = [
        createVoteEvent('claude', 'Option A'),
        createVoteEvent('gpt-4', 'Option A'),
        createVoteEvent('gemini', 'Option A'),
        createConsensusEvent(true, 'Option A is the answer'),
      ];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('CONSENSUS')).toBeInTheDocument();
    });

    it('shows DEADLOCK when evenly split with no majority', () => {
      // Deadlock requires: all voted, multiple choices, equal split, no choice at majority
      // With 4 agents each voting for different options, maxVotes=1 < majorityThreshold=2
      const events = [
        createVoteEvent('agent-1', 'Option A'),
        createVoteEvent('agent-2', 'Option B'),
        createVoteEvent('agent-3', 'Option C'),
        createVoteEvent('agent-4', 'Option D'),
      ];

      render(
        <ConsensusMeter events={events} agents={['agent-1', 'agent-2', 'agent-3', 'agent-4']} />,
      );

      expect(screen.getByText('DEADLOCK')).toBeInTheDocument();
    });
  });

  describe('agreement percentage', () => {
    it('calculates 33% when 1 of 3 agree', () => {
      const events = [createVoteEvent('claude', 'Option A')];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('33%')).toBeInTheDocument();
    });

    it('calculates 67% when 2 of 3 agree', () => {
      const events = [createVoteEvent('claude', 'Option A'), createVoteEvent('gpt-4', 'Option A')];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('67%')).toBeInTheDocument();
    });

    it('calculates 100% when all agree', () => {
      const events = [
        createVoteEvent('claude', 'Option A'),
        createVoteEvent('gpt-4', 'Option A'),
        createVoteEvent('gemini', 'Option A'),
      ];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('100%')).toBeInTheDocument();
    });
  });

  describe('consensus reached display', () => {
    it('shows CONSENSUS REACHED text', () => {
      const events = [createConsensusEvent(true, 'The final answer')];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('CONSENSUS REACHED')).toBeInTheDocument();
    });

    it('shows consensus answer', () => {
      const events = [createConsensusEvent(true, 'AI will benefit humanity')];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('AI will benefit humanity')).toBeInTheDocument();
    });

    it('shows consensus confidence', () => {
      const events = [createConsensusEvent(true, 'Answer', 0.92)];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.getByText('Confidence: 92%')).toBeInTheDocument();
    });

    it('does not show consensus section when not reached', () => {
      const events = [createConsensusEvent(false)];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      expect(screen.queryByText('CONSENSUS REACHED')).not.toBeInTheDocument();
    });
  });

  describe('edge cases', () => {
    it('handles empty agents array', () => {
      render(<ConsensusMeter events={[]} agents={[]} />);

      expect(screen.getByText('Votes (0/0)')).toBeInTheDocument();
    });

    it('handles vote without confidence', () => {
      const events: StreamEvent[] = [
        {
          type: 'vote',
          data: { agent: 'claude', choice: 'Option A' }, // No confidence
          timestamp: Date.now() / 1000,
        },
      ];

      render(<ConsensusMeter events={events} agents={defaultAgents} />);

      // Should default to 50%
      expect(screen.getByText('50%')).toBeInTheDocument();
    });

    it('handles many events without performance issues', () => {
      const events: StreamEvent[] = [];
      for (let i = 0; i < 100; i++) {
        events.push(createVoteEvent(`agent-${i % 3}`, `Option ${i % 5}`));
      }

      const startTime = performance.now();
      render(<ConsensusMeter events={events} agents={['agent-0', 'agent-1', 'agent-2']} />);
      const endTime = performance.now();

      // Should render in reasonable time
      expect(endTime - startTime).toBeLessThan(500);
    });
  });
});
