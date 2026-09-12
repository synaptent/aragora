/**
 * Tests for DebateTimeline component
 *
 * Tests cover:
 * - Renders timeline header with event count
 * - Displays messages as timeline entries
 * - Displays stream events as timeline entries
 * - Agent filtering via select dropdown
 * - Event type filter toggle buttons
 * - Chronological ordering
 * - Entry expansion for detail content
 */

import { render, screen, fireEvent } from '@testing-library/react';
import { DebateTimeline } from '../DebateTimeline';
import type { TranscriptMessage } from '@/hooks/useDebateWebSocket';
import type { StreamEvent } from '@/types/events';

// Mock agentColors utility
jest.mock('@/utils/agentColors', () => ({
  getAgentColors: (agent: string) => ({
    bg: `bg-${agent}-500/20`,
    text: `text-${agent}-400`,
    border: `border-${agent}-500/30`,
    dot: 'bg-acid-green',
  }),
}));

const createMessage = (overrides: Partial<TranscriptMessage> = {}): TranscriptMessage => ({
  agent: 'claude',
  content: 'This is a test message.',
  timestamp: 1705420800,
  role: 'participant',
  round: 1,
  ...overrides,
});

const createStreamEvent = (overrides: Partial<StreamEvent> = {}): StreamEvent => ({
  type: 'agent_message' as const,
  data: { content: 'Event data' },
  timestamp: 1705420800,
  agent: 'claude',
  ...overrides,
});

describe('DebateTimeline', () => {
  describe('basic rendering', () => {
    it('renders timeline header with event count', () => {
      render(<DebateTimeline messages={[createMessage()]} streamEvents={[]} agents={['claude']} />);

      expect(screen.getByText(/DEBATE TIMELINE/)).toBeInTheDocument();
      expect(screen.getByText(/1 events/)).toBeInTheDocument();
    });

    it('renders with empty data showing 0 events', () => {
      render(<DebateTimeline messages={[]} streamEvents={[]} agents={[]} />);

      expect(screen.getByText(/DEBATE TIMELINE/)).toBeInTheDocument();
      expect(screen.getByText(/0 events/)).toBeInTheDocument();
    });

    it('shows no events message when no data', () => {
      render(<DebateTimeline messages={[]} streamEvents={[]} agents={[]} />);

      expect(screen.getByText('No timeline events to display')).toBeInTheDocument();
    });
  });

  describe('message entries', () => {
    it('renders messages as timeline entries with agent name', () => {
      const messages = [
        createMessage({ agent: 'claude', content: 'First message', timestamp: 1705420800 }),
        createMessage({ agent: 'gpt-4', content: 'Second message', timestamp: 1705420810 }),
      ];

      render(<DebateTimeline messages={messages} streamEvents={[]} agents={['claude', 'gpt-4']} />);

      // Agent names in timeline entries are displayed lowercase
      expect(screen.getAllByText('claude').length).toBeGreaterThan(0);
      expect(screen.getAllByText('gpt-4').length).toBeGreaterThan(0);
    });

    it('renders message content in entries', () => {
      render(
        <DebateTimeline
          messages={[createMessage({ content: 'Short message' })]}
          streamEvents={[]}
          agents={['claude']}
        />,
      );

      expect(screen.getByText('Short message')).toBeInTheDocument();
    });

    it('truncates long messages to 200 chars', () => {
      const longContent = 'A'.repeat(300);
      render(
        <DebateTimeline
          messages={[createMessage({ content: longContent })]}
          streamEvents={[]}
          agents={['claude']}
        />,
      );

      // Should see truncated content with ellipsis
      const truncated = screen.getByText(/^A{200}\.\.\./);
      expect(truncated).toBeInTheDocument();
    });

    it('shows [MESSAGE] type label for message entries', () => {
      render(<DebateTimeline messages={[createMessage()]} streamEvents={[]} agents={['claude']} />);

      expect(screen.getByText('[MESSAGE]')).toBeInTheDocument();
    });
  });

  describe('stream event entries', () => {
    it('renders debate_start events', () => {
      const events = [
        createStreamEvent({
          type: 'debate_start',
          data: { task: 'Design a rate limiter', agents: ['claude', 'gpt-4'] },
          timestamp: 1705420790,
        }),
      ];

      render(<DebateTimeline messages={[]} streamEvents={events} agents={['claude']} />);

      expect(screen.getByText('[DEBATE STARTED]')).toBeInTheDocument();
      expect(screen.getByText('Design a rate limiter')).toBeInTheDocument();
    });

    it('renders round_start events', () => {
      const events = [
        createStreamEvent({ type: 'round_start', data: { round: 2 }, timestamp: 1705420800 }),
      ];

      render(<DebateTimeline messages={[]} streamEvents={events} agents={['claude']} />);

      expect(screen.getByText('[ROUND]')).toBeInTheDocument();
      expect(screen.getByText('Round 2')).toBeInTheDocument();
    });

    it('renders agent_thinking events', () => {
      const events = [
        createStreamEvent({
          type: 'agent_thinking',
          data: { thinking: 'Analyzing trade-offs' },
          agent: 'claude',
          timestamp: 1705420800,
        }),
      ];

      render(<DebateTimeline messages={[]} streamEvents={events} agents={['claude']} />);

      expect(screen.getByText('[THINKING]')).toBeInTheDocument();
      expect(screen.getByText('Analyzing trade-offs')).toBeInTheDocument();
    });

    it('renders agent_evidence events', () => {
      const events = [
        createStreamEvent({
          type: 'agent_evidence',
          data: { sources: [{ title: 'Paper A' }, { title: 'Paper B' }] },
          agent: 'gpt-4',
          timestamp: 1705420800,
        }),
      ];

      render(<DebateTimeline messages={[]} streamEvents={events} agents={['gpt-4']} />);

      expect(screen.getByText('[EVIDENCE]')).toBeInTheDocument();
      expect(screen.getByText('Considering 2 source(s)')).toBeInTheDocument();
    });

    it('renders agent_confidence events', () => {
      const events = [
        createStreamEvent({
          type: 'agent_confidence',
          data: { confidence: 0.85, reason: 'Strong evidence' },
          agent: 'claude',
          timestamp: 1705420800,
        }),
      ];

      render(<DebateTimeline messages={[]} streamEvents={events} agents={['claude']} />);

      expect(screen.getByText('[CONFIDENCE]')).toBeInTheDocument();
      expect(screen.getByText('Confidence: 85%')).toBeInTheDocument();
    });

    it('filters out non-timeline event types', () => {
      const events = [
        createStreamEvent({
          type: 'log_message' as 'agent_message',
          data: {},
          timestamp: 1705420800,
        }),
      ];

      render(<DebateTimeline messages={[]} streamEvents={events} agents={[]} />);

      expect(screen.getByText('No timeline events to display')).toBeInTheDocument();
    });
  });

  describe('agent filtering', () => {
    it('shows agent filter dropdown with All Agents option', () => {
      render(<DebateTimeline messages={[]} streamEvents={[]} agents={['claude', 'gpt-4']} />);

      expect(screen.getByText('All Agents')).toBeInTheDocument();
    });

    it('shows agents as options in dropdown', () => {
      render(<DebateTimeline messages={[]} streamEvents={[]} agents={['claude', 'gpt-4']} />);

      const select = screen.getByRole('combobox');
      expect(select).toBeInTheDocument();
      const options = screen.getAllByRole('option');
      expect(options).toHaveLength(3); // All Agents + 2 agents
    });

    it('filters entries by selected agent', () => {
      const messages = [
        createMessage({ agent: 'claude', content: 'Claude message', timestamp: 1705420800 }),
        createMessage({ agent: 'gpt-4', content: 'GPT message', timestamp: 1705420810 }),
      ];

      render(<DebateTimeline messages={messages} streamEvents={[]} agents={['claude', 'gpt-4']} />);

      const select = screen.getByRole('combobox');
      fireEvent.change(select, { target: { value: 'claude' } });

      expect(screen.getByText('Claude message')).toBeInTheDocument();
      expect(screen.queryByText('GPT message')).not.toBeInTheDocument();
    });
  });

  describe('event type filtering', () => {
    it('shows type filter buttons for each timeline event type', () => {
      render(<DebateTimeline messages={[createMessage()]} streamEvents={[]} agents={['claude']} />);

      expect(screen.getByText('MESSAGE')).toBeInTheDocument();
      expect(screen.getByText('THINKING')).toBeInTheDocument();
      expect(screen.getByText('EVIDENCE')).toBeInTheDocument();
      expect(screen.getByText('DEBATE STARTED')).toBeInTheDocument();
    });

    it('toggles filter to hide event type', () => {
      render(
        <DebateTimeline
          messages={[createMessage({ content: 'Visible message' })]}
          streamEvents={[]}
          agents={['claude']}
        />,
      );

      // Click MESSAGE filter to toggle it off
      fireEvent.click(screen.getByText('MESSAGE'));

      // Message should be hidden
      expect(screen.queryByText('Visible message')).not.toBeInTheDocument();
    });
  });

  describe('entry expansion', () => {
    it('expands entry to show detail content on click', () => {
      const longContent = 'A'.repeat(250);
      const messages = [createMessage({ content: longContent, timestamp: 1705420800 })];

      render(<DebateTimeline messages={messages} streamEvents={[]} agents={['claude']} />);

      // Click on the entry area to expand
      const entryContent = screen.getByText(/^A{200}\.\.\./);
      fireEvent.click(entryContent.closest('.cursor-pointer')!);

      // After expansion, full content detail should be visible
      expect(screen.getByText(longContent)).toBeInTheDocument();
    });
  });

  describe('chronological ordering', () => {
    it('sorts entries by timestamp', () => {
      const messages = [
        createMessage({ agent: 'gpt-4', content: 'Second', timestamp: 1705420810 }),
        createMessage({ agent: 'claude', content: 'First', timestamp: 1705420800 }),
      ];

      const { container } = render(
        <DebateTimeline messages={messages} streamEvents={[]} agents={['claude', 'gpt-4']} />,
      );

      const entries = container.querySelectorAll('.cursor-pointer');
      expect(entries.length).toBe(2);

      // First entry should contain "First" (earlier timestamp)
      expect(entries[0].textContent).toContain('First');
      expect(entries[1].textContent).toContain('Second');
    });
  });
});
