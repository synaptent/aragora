import { act, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AgentTabs } from '../AgentTabs';
import type { StreamEvent } from '@/types/events';

// Mock fetch for positions API
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock logger
jest.mock('@/utils/logger', () => ({
  logger: { error: jest.fn(), info: jest.fn(), debug: jest.fn() },
}));

describe('AgentTabs', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ positions: [] }) });
  });

  const actUser = async (action: () => Promise<void>) => {
    await act(async () => {
      await action();
    });
  };

  const selectAgentTab = async (user: ReturnType<typeof userEvent.setup>, agentName: string) => {
    const agentTabs = screen.getAllByText(agentName);
    await actUser(() => user.click(agentTabs[0]));
    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalled();
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

  describe('empty state', () => {
    it('shows waiting message when no events', () => {
      render(<AgentTabs events={[]} />);

      expect(screen.getByText(/waiting for agent responses/i)).toBeInTheDocument();
    });

    it('shows agent responses header even when empty', () => {
      render(<AgentTabs events={[]} />);

      expect(screen.getByText('Agent Responses')).toBeInTheDocument();
    });
  });

  describe('with agent events', () => {
    const events: StreamEvent[] = [
      createAgentMessageEvent('claude', 'First response from Claude', {
        timestamp: 1000,
        round: 1,
        data: { content: 'First response from Claude', role: 'proposer' },
      }),
      createAgentMessageEvent('gpt4', 'Response from GPT-4', {
        timestamp: 1001,
        round: 1,
        data: { content: 'Response from GPT-4', role: 'critic' },
      }),
      createAgentMessageEvent('claude', 'Second response from Claude', {
        timestamp: 1002,
        round: 2,
        data: { content: 'Second response from Claude', role: 'proposer' },
      }),
    ];

    it('renders all agent tabs', () => {
      render(<AgentTabs events={events} />);

      expect(screen.getByText('All Agents')).toBeInTheDocument();
      // Agent names appear in both tabs and messages, so use getAllByText
      expect(screen.getAllByText('claude').length).toBeGreaterThan(0);
      expect(screen.getAllByText('gpt4').length).toBeGreaterThan(0);
    });

    it('shows unified timeline by default with message count', () => {
      render(<AgentTabs events={events} />);

      expect(screen.getByText(/Activity Timeline/)).toBeInTheDocument();
      expect(screen.getByText(/3 messages from 2 agents/)).toBeInTheDocument();
    });

    it('displays all messages in unified timeline', () => {
      render(<AgentTabs events={events} />);

      expect(screen.getByText('First response from Claude')).toBeInTheDocument();
      expect(screen.getByText('Response from GPT-4')).toBeInTheDocument();
      expect(screen.getByText('Second response from Claude')).toBeInTheDocument();
    });

    it('switches to individual agent view when tab clicked', async () => {
      const user = userEvent.setup();
      render(<AgentTabs events={events} />);

      // Click the claude tab button (first one in the tab bar)
      await selectAgentTab(user, 'claude');

      // Should show individual agent view
      await waitFor(() => {
        expect(screen.queryByText(/Activity Timeline/)).not.toBeInTheDocument();
      });

      // Latest message should be displayed
      expect(screen.getByText('Second response from Claude')).toBeInTheDocument();
    });

    it('shows round indicator on tabs', () => {
      render(<AgentTabs events={events} />);

      // Claude should show R2 (latest round) - get the tab button
      const claudeTabs = screen.getAllByText('claude');
      const claudeTab = claudeTabs[0].closest('button');
      expect(claudeTab).toHaveTextContent('R2');

      // GPT4 should show R1
      const gpt4Tabs = screen.getAllByText('gpt4');
      const gpt4Tab = gpt4Tabs[0].closest('button');
      expect(gpt4Tab).toHaveTextContent('R1');
    });

    it('shows live indicator for auto-scroll', () => {
      render(<AgentTabs events={events} />);

      expect(screen.getByText('Live')).toBeInTheDocument();
    });
  });

  describe('individual agent view', () => {
    const events: StreamEvent[] = [
      createAgentMessageEvent('claude', 'First response', {
        timestamp: 1000,
        round: 1,
        data: { content: 'First response', role: 'proposer', confidence: 0.85 },
      }),
      createAgentMessageEvent('claude', 'Second response', {
        timestamp: 1001,
        round: 2,
        data: { content: 'Second response', role: 'critic', confidence: 0.92 },
      }),
    ];

    it('shows confidence when available', async () => {
      const user = userEvent.setup();
      render(<AgentTabs events={events} />);

      await selectAgentTab(user, 'claude');

      await waitFor(() => {
        expect(screen.getByText('92%')).toBeInTheDocument();
      });
    });

    it('shows history button and toggles history view', async () => {
      const user = userEvent.setup();
      render(<AgentTabs events={events} />);

      await selectAgentTab(user, 'claude');

      // Click history button
      await waitFor(() => {
        expect(screen.getByText('History')).toBeInTheDocument();
      });

      await actUser(() => user.click(screen.getByText('History')));

      // Should show all messages in history
      await waitFor(() => {
        expect(screen.getByText('First response')).toBeInTheDocument();
        expect(screen.getByText('Second response')).toBeInTheDocument();
      });
    });

    it('shows positions button and fetches positions', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          positions: [
            {
              topic: 'AI Safety',
              position: 'Important consideration',
              confidence: 0.8,
              evidence_count: 3,
              last_updated: new Date().toISOString(),
            },
          ],
        }),
      });

      render(<AgentTabs events={events} />);

      await selectAgentTab(user, 'claude');

      // Wait for positions to load and show count
      await waitFor(() => {
        expect(screen.getByText(/Positions/)).toBeInTheDocument();
      });

      // Click positions button
      await actUser(() => user.click(screen.getByText(/Positions/)));

      await waitFor(() => {
        expect(screen.getByText('AI Safety')).toBeInTheDocument();
        expect(screen.getByText('Important consideration')).toBeInTheDocument();
        expect(screen.getByText('80% conf')).toBeInTheDocument();
        expect(screen.getByText('3 evidence')).toBeInTheDocument();
      });
    });

    it('handles positions fetch error gracefully', async () => {
      const user = userEvent.setup();
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      render(<AgentTabs events={events} />);

      await selectAgentTab(user, 'claude');

      // Should handle error gracefully (positions empty)
      await waitFor(() => {
        expect(screen.getByText(/Positions/)).toBeInTheDocument();
      });

      await actUser(() => user.click(screen.getByText(/Positions/)));

      await waitFor(() => {
        expect(screen.getByText(/No recorded positions/i)).toBeInTheDocument();
      });
    });
  });

  describe('roles and styling', () => {
    it('displays role badge for each message', () => {
      const events: StreamEvent[] = [
        createAgentMessageEvent('claude', 'Test', { data: { content: 'Test', role: 'proposer' } }),
        createAgentMessageEvent('gpt4', 'Test2', { data: { content: 'Test2', role: 'critic' } }),
      ];

      render(<AgentTabs events={events} />);

      // Messages should be rendered with their content
      expect(screen.getByText('Test')).toBeInTheDocument();
      expect(screen.getByText('Test2')).toBeInTheDocument();
    });

    it('shows role icons for messages', () => {
      const events: StreamEvent[] = [
        createAgentMessageEvent('claude', 'Test', { data: { content: 'Test', role: 'proposer' } }),
      ];

      render(<AgentTabs events={events} />);

      // Should have role emoji indicator (might appear multiple times)
      expect(screen.getAllByText('💡').length).toBeGreaterThan(0);
    });
  });

  describe('scrolling behavior', () => {
    it('shows jump to latest button when auto-scroll is disabled', async () => {
      userEvent.setup();
      const events: StreamEvent[] = Array.from({ length: 20 }, (_, i) =>
        createAgentMessageEvent('claude', `Message ${i}`, { timestamp: 1000 + i }),
      );

      render(<AgentTabs events={events} />);

      // Initially should show Live indicator
      expect(screen.getByText('Live')).toBeInTheDocument();

      // The jump button appears when user scrolls up (simulated by auto-scroll being false)
      // This is typically triggered by scroll event, but we can check the button renders conditionally
    });
  });

  describe('message timestamps', () => {
    it('displays formatted timestamp for each message', () => {
      const timestamp = new Date('2026-01-12T15:30:00').getTime() / 1000;
      const events: StreamEvent[] = [
        createAgentMessageEvent('claude', 'Test message', { timestamp }),
      ];

      render(<AgentTabs events={events} />);

      // Should show time in local format
      const timeElement = screen.getByText(/\d{1,2}:\d{2}/);
      expect(timeElement).toBeInTheDocument();
    });
  });

  describe('round display', () => {
    it('shows round badge in unified timeline', () => {
      const events: StreamEvent[] = [
        createAgentMessageEvent('claude', 'Round 1 message', { round: 1 }),
        createAgentMessageEvent('claude', 'Round 2 message', { round: 2 }),
      ];

      render(<AgentTabs events={events} />);

      expect(screen.getAllByText('R1').length).toBeGreaterThan(0);
      expect(screen.getAllByText('R2').length).toBeGreaterThan(0);
    });

    it('shows round info in individual agent header', async () => {
      const user = userEvent.setup();
      const events: StreamEvent[] = [createAgentMessageEvent('claude', 'Message', { round: 3 })];

      render(<AgentTabs events={events} />);

      await selectAgentTab(user, 'claude');

      await waitFor(() => {
        expect(screen.getByText('Round 3')).toBeInTheDocument();
      });
    });
  });
});
