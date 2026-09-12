import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentPanel } from '../AgentPanel';
import type { StreamEvent } from '@/types/events';

// Mock the agent colors utility
jest.mock('@/utils/agentColors', () => ({
  getAgentColors: (_agent: string) => ({
    bg: 'bg-surface',
    border: 'border-acid-green/30',
    text: 'text-acid-green',
    glow: '',
  }),
}));

describe('AgentPanel', () => {
  const actUser = async (action: () => Promise<void>) => {
    await act(async () => {
      await action();
    });
  };

  const createAgentMessageEvent = (
    agent: string,
    content: string,
    options: Partial<StreamEvent> = {},
  ): StreamEvent => ({
    type: 'agent_message',
    timestamp: Date.now() / 1000,
    agent,
    round: 1,
    data: { content, role: 'proposer', ...options.data },
    ...options,
  });

  const createCritiqueEvent = (
    agent: string,
    target: string,
    issues: string[],
    options: Partial<StreamEvent> = {},
  ): StreamEvent => ({
    type: 'critique',
    timestamp: Date.now() / 1000,
    agent,
    round: 1,
    data: { target, issues, severity: 0.7, ...options.data },
    ...options,
  });

  const createVoteEvent = (agent: string, vote: string, confidence: number): StreamEvent => ({
    type: 'vote',
    timestamp: Date.now() / 1000,
    agent,
    round: 1,
    data: { vote, confidence },
  });

  const createConsensusEvent = (
    reached: boolean,
    confidence: number,
    answer: string,
  ): StreamEvent => ({
    type: 'consensus',
    timestamp: Date.now() / 1000,
    agent: null,
    round: 1,
    data: { reached, confidence, answer },
  });

  describe('empty state', () => {
    it('shows awaiting message when no events', () => {
      render(<AgentPanel events={[]} />);

      expect(screen.getByText(/Awaiting agent activity/i)).toBeInTheDocument();
    });

    it('shows event count of 0', () => {
      render(<AgentPanel events={[]} />);

      expect(screen.getByText('// 0 events')).toBeInTheDocument();
    });

    it('displays AGENT_STREAM header', () => {
      render(<AgentPanel events={[]} />);

      expect(screen.getByText('AGENT_STREAM')).toBeInTheDocument();
    });
  });

  describe('with agent events', () => {
    const events: StreamEvent[] = [
      createAgentMessageEvent('claude', 'First response from Claude', {
        timestamp: 1000,
        round: 1,
      }),
      createAgentMessageEvent('gpt4', 'Response from GPT-4', {
        timestamp: 1001,
        round: 1,
        data: { content: 'Response from GPT-4', role: 'critic' },
      }),
      createAgentMessageEvent('claude', 'Second response from Claude', {
        timestamp: 1002,
        round: 2,
      }),
    ];

    it('displays correct event count', () => {
      render(<AgentPanel events={events} />);

      expect(screen.getByText('// 3 events')).toBeInTheDocument();
    });

    it('renders all event cards', () => {
      render(<AgentPanel events={events} />);

      expect(screen.getByText('First response from Claude')).toBeInTheDocument();
      expect(screen.getByText('Response from GPT-4')).toBeInTheDocument();
      expect(screen.getByText('Second response from Claude')).toBeInTheDocument();
    });

    it('displays agent names in uppercase', () => {
      render(<AgentPanel events={events} />);

      expect(screen.getAllByText('CLAUDE').length).toBeGreaterThan(0);
      expect(screen.getAllByText('GPT4').length).toBeGreaterThan(0);
    });

    it('displays round badges for events', () => {
      render(<AgentPanel events={events} />);

      expect(screen.getAllByText('R1').length).toBeGreaterThan(0);
      expect(screen.getAllByText('R2').length).toBeGreaterThan(0);
    });
  });

  describe('expand/collapse functionality', () => {
    const events: StreamEvent[] = [createAgentMessageEvent('claude', 'Expandable content here')];

    it('shows expand button on event cards', () => {
      render(<AgentPanel events={events} />);

      expect(screen.getByText('[+]')).toBeInTheDocument();
    });

    it('toggles expand state on click', async () => {
      const user = userEvent.setup();
      render(<AgentPanel events={events} />);

      const expandButton = screen.getByRole('button', { name: /Expand claude event details/i });
      await actUser(() => user.click(expandButton));

      expect(screen.getByText('[-]')).toBeInTheDocument();
    });

    it('shows full content when expanded', async () => {
      const user = userEvent.setup();
      const longContent = 'A'.repeat(500);
      render(<AgentPanel events={[createAgentMessageEvent('claude', longContent)]} />);

      const expandButton = screen.getByRole('button', { name: /Expand claude event details/i });
      await actUser(() => user.click(expandButton));

      // The full content should be visible in the expanded section
      const expandedContent = screen.getAllByText(longContent);
      expect(expandedContent.length).toBeGreaterThan(0);
    });

    it('expand all button expands all events', async () => {
      const user = userEvent.setup();
      const events = [
        createAgentMessageEvent('claude', 'Message 1'),
        createAgentMessageEvent('gpt4', 'Message 2'),
      ];
      render(<AgentPanel events={events} />);

      await actUser(() => user.click(screen.getByLabelText('Expand all events')));

      // All should now show collapse indicator
      expect(screen.getAllByText('[-]').length).toBe(2);
    });

    it('collapse all button collapses all events', async () => {
      const user = userEvent.setup();
      const events = [
        createAgentMessageEvent('claude', 'Message 1'),
        createAgentMessageEvent('gpt4', 'Message 2'),
      ];
      render(<AgentPanel events={events} />);

      // First expand all
      await actUser(() => user.click(screen.getByLabelText('Expand all events')));
      expect(screen.getAllByText('[-]').length).toBe(2);

      // Then collapse all
      await actUser(() => user.click(screen.getByLabelText('Collapse all events')));
      expect(screen.getAllByText('[+]').length).toBe(2);
    });
  });

  describe('event types', () => {
    it('renders critique events with issue count', () => {
      const events = [createCritiqueEvent('claude', 'gpt4', ['Issue 1', 'Issue 2', 'Issue 3'])];
      render(<AgentPanel events={events} />);

      expect(screen.getByText(/3 issues/)).toBeInTheDocument();
      expect(screen.getByText(/severity 0.7/)).toBeInTheDocument();
    });

    it('renders vote events', () => {
      const events = [createVoteEvent('claude', 'yes', 0.9)];
      render(<AgentPanel events={events} />);

      expect(screen.getByText(/Vote: yes/)).toBeInTheDocument();
    });

    it('renders consensus events with status', () => {
      const events = [createConsensusEvent(true, 0.85, 'The agreed conclusion')];
      render(<AgentPanel events={events} />);

      expect(screen.getByText(/Consensus reached/)).toBeInTheDocument();
      expect(screen.getByText(/85%/)).toBeInTheDocument();
    });

    it('renders consensus not reached', () => {
      const events = [createConsensusEvent(false, 0.45, 'No agreement')];
      render(<AgentPanel events={events} />);

      expect(screen.getByText(/not reached/)).toBeInTheDocument();
    });
  });

  describe('log message filtering', () => {
    it('filters out duplicate log messages', () => {
      const content = 'Agent response content';
      const events: StreamEvent[] = [
        createAgentMessageEvent('claude', content, { timestamp: 1000 }),
        {
          type: 'log_message',
          timestamp: 1001,
          agent: 'system',
          round: 1,
          data: { message: content },
        },
      ];

      render(<AgentPanel events={events} />);

      // Content should only appear once (from agent_message)
      const matches = screen.getAllByText(content);
      expect(matches.length).toBe(1);
    });

    it('filters out role-prefixed log messages', () => {
      const events: StreamEvent[] = [
        {
          type: 'log_message',
          timestamp: 1000,
          agent: 'system',
          round: 1,
          data: { message: '[proposer] claude (round 1): Hello' },
        },
      ];

      render(<AgentPanel events={events} />);

      // Should show awaiting message since this log is filtered
      expect(screen.getByText(/Awaiting agent activity/i)).toBeInTheDocument();
    });
  });

  describe('role icons', () => {
    it('shows proposer icon [P]', () => {
      const events = [
        createAgentMessageEvent('claude', 'Proposal', {
          data: { content: 'Proposal', role: 'proposer' },
        }),
      ];
      render(<AgentPanel events={events} />);

      expect(screen.getByText('[P]')).toBeInTheDocument();
    });

    it('shows critic icon [C]', () => {
      const events = [
        createAgentMessageEvent('claude', 'Critique', {
          data: { content: 'Critique', role: 'critic' },
        }),
      ];
      render(<AgentPanel events={events} />);

      expect(screen.getByText('[C]')).toBeInTheDocument();
    });

    it('shows synthesizer icon [S]', () => {
      const events = [
        createAgentMessageEvent('claude', 'Synthesis', {
          data: { content: 'Synthesis', role: 'synthesizer' },
        }),
      ];
      render(<AgentPanel events={events} />);

      expect(screen.getByText('[S]')).toBeInTheDocument();
    });
  });

  describe('accessibility', () => {
    it('has accessible expand/collapse buttons', () => {
      const events = [createAgentMessageEvent('claude', 'Message')];
      render(<AgentPanel events={events} />);

      const button = screen.getByRole('button', { name: /Expand claude event details/i });
      expect(button).toHaveAttribute('aria-expanded', 'false');
    });

    it('updates aria-expanded on toggle', async () => {
      const user = userEvent.setup();
      const events = [createAgentMessageEvent('claude', 'Message')];
      render(<AgentPanel events={events} />);

      const button = screen.getByRole('button', { name: /Expand claude event details/i });
      await actUser(() => user.click(button));

      expect(button).toHaveAttribute('aria-expanded', 'true');
    });

    it('has accessible expand all button', () => {
      render(<AgentPanel events={[]} />);

      expect(screen.getByLabelText('Expand all events')).toBeInTheDocument();
    });

    it('has accessible collapse all button', () => {
      render(<AgentPanel events={[]} />);

      expect(screen.getByLabelText('Collapse all events')).toBeInTheDocument();
    });
  });

  describe('timestamp display', () => {
    it('formats timestamps correctly', () => {
      const timestamp = new Date('2026-01-12T15:30:45').getTime() / 1000;
      const events = [createAgentMessageEvent('claude', 'Message', { timestamp })];

      render(<AgentPanel events={events} />);

      // Should display time portion
      expect(screen.getByText(/\d{1,2}:\d{2}:\d{2}/)).toBeInTheDocument();
    });
  });
});
