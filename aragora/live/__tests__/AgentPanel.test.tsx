/**
 * Tests for AgentPanel component
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { AgentPanel } from '../src/components/AgentPanel';
import type { StreamEvent } from '../src/types/events';

// Mock getAgentColors
jest.mock('../src/utils/agentColors', () => ({
  getAgentColors: (_agent: string) => ({
    bg: 'bg-surface',
    border: 'border-acid-green/30',
    text: 'text-acid-green',
    glow: '',
  }),
}));

describe('AgentPanel', () => {
  const createAgentEvent = (
    agent: string,
    content: string,
    role = 'proposer',
    round = 1,
  ): StreamEvent => ({
    type: 'agent_message',
    agent,
    round,
    timestamp: Date.now() / 1000,
    data: { content, role },
  });

  const createCritiqueEvent = (agent: string, target: string, issues: string[]): StreamEvent => ({
    type: 'critique',
    agent,
    timestamp: Date.now() / 1000,
    data: { target, issues, severity: 0.5 },
  });

  const createConsensusEvent = (reached: boolean, confidence: number): StreamEvent => ({
    type: 'consensus',
    agent: 'system',
    timestamp: Date.now() / 1000,
    data: { reached, confidence, answer: 'The consensus answer' },
  });

  describe('Empty State', () => {
    it('renders empty state message when no events', () => {
      render(<AgentPanel events={[]} />);
      expect(screen.getByText(/awaiting agent activity/i)).toBeInTheDocument();
    });

    it('shows event count as 0', () => {
      render(<AgentPanel events={[]} />);
      expect(screen.getByText('// 0 events')).toBeInTheDocument();
    });
  });

  describe('Agent Messages', () => {
    it('renders agent messages', () => {
      const events = [createAgentEvent('claude', 'Hello from Claude')];
      render(<AgentPanel events={events} />);
      expect(screen.getByText('CLAUDE')).toBeInTheDocument();
      expect(screen.getByText(/Hello from Claude/)).toBeInTheDocument();
    });

    it('shows multiple agent messages', () => {
      const events = [
        createAgentEvent('claude', 'First message'),
        createAgentEvent('gemini', 'Second message'),
      ];
      render(<AgentPanel events={events} />);
      expect(screen.getByText('CLAUDE')).toBeInTheDocument();
      expect(screen.getByText('GEMINI')).toBeInTheDocument();
    });

    it('displays round number', () => {
      const events = [createAgentEvent('claude', 'Test', 'proposer', 2)];
      render(<AgentPanel events={events} />);
      expect(screen.getByText('R2')).toBeInTheDocument();
    });

    it('shows correct event count', () => {
      const events = [
        createAgentEvent('claude', 'Message 1'),
        createAgentEvent('gemini', 'Message 2'),
        createAgentEvent('gpt4', 'Message 3'),
      ];
      render(<AgentPanel events={events} />);
      expect(screen.getByText('// 3 events')).toBeInTheDocument();
    });
  });

  describe('Critique Events', () => {
    it('renders critique events', () => {
      const events = [createCritiqueEvent('gemini', 'claude', ['Issue 1', 'Issue 2'])];
      render(<AgentPanel events={events} />);
      expect(screen.getByText('GEMINI')).toBeInTheDocument();
      expect(screen.getByText(/claude.*2 issues/i)).toBeInTheDocument();
    });
  });

  describe('Consensus Events', () => {
    it('renders consensus reached', () => {
      const events = [createConsensusEvent(true, 0.85)];
      render(<AgentPanel events={events} />);
      expect(screen.getByText(/consensus reached.*85%/i)).toBeInTheDocument();
    });

    it('renders consensus not reached', () => {
      const events = [createConsensusEvent(false, 0.3)];
      render(<AgentPanel events={events} />);
      expect(screen.getByText(/consensus not reached.*30%/i)).toBeInTheDocument();
    });
  });

  describe('Expand/Collapse', () => {
    it('expands message on click', () => {
      const events = [createAgentEvent('claude', 'Detailed content here')];
      render(<AgentPanel events={events} />);

      // Click to expand
      const expandButton = screen.getByText('[+]');
      fireEvent.click(expandButton);

      // Should now show collapse button
      expect(screen.getByText('[-]')).toBeInTheDocument();
    });

    it('expands all messages with +ALL button', () => {
      const events = [
        createAgentEvent('claude', 'Message 1'),
        createAgentEvent('gemini', 'Message 2'),
      ];
      render(<AgentPanel events={events} />);

      fireEvent.click(screen.getByText('[+ALL]'));

      // Both should be expanded
      const collapseButtons = screen.getAllByText('[-]');
      expect(collapseButtons.length).toBe(2);
    });

    it('collapses all messages with -ALL button', () => {
      const events = [
        createAgentEvent('claude', 'Message 1'),
        createAgentEvent('gemini', 'Message 2'),
      ];
      render(<AgentPanel events={events} />);

      // Expand all first
      fireEvent.click(screen.getByText('[+ALL]'));
      // Then collapse all
      fireEvent.click(screen.getByText('[-ALL]'));

      // Both should be collapsed
      const expandButtons = screen.getAllByText('[+]');
      expect(expandButtons.length).toBe(2);
    });
  });

  describe('Header', () => {
    it('displays AGENT_STREAM header', () => {
      render(<AgentPanel events={[]} />);
      expect(screen.getByText('AGENT_STREAM')).toBeInTheDocument();
    });
  });

  describe('Deduplication', () => {
    it('filters duplicate log messages that match agent messages', () => {
      const events: StreamEvent[] = [
        createAgentEvent('claude', 'Same content here'),
        {
          type: 'log_message',
          agent: 'system',
          timestamp: Date.now() / 1000,
          data: { message: 'Same content here' },
        },
      ];
      render(<AgentPanel events={events} />);
      // Should only show one event (agent_message), not the duplicate log
      expect(screen.getByText('// 1 events')).toBeInTheDocument();
    });
  });
});
