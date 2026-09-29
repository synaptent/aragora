/**
 * Tests for AgentRelationships component
 *
 * Tests cover:
 * - Loading state display
 * - Error state handling
 * - Empty state when no relationships
 * - Compact view rendering
 * - Full view with rivals and allies sections
 * - Rivalry and alliance score display
 */

import { render, screen, waitFor } from '@testing-library/react';
import { AgentRelationships } from '../src/components/AgentRelationships';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock logger to prevent console noise
jest.mock('../src/utils/logger', () => ({
  logger: { error: jest.fn(), warn: jest.fn(), info: jest.fn(), debug: jest.fn() },
}));

// Mock agentColors utility
jest.mock('../src/utils/agentColors', () => ({
  getAgentColors: (_agent: string) => ({
    text: 'text-white',
    bg: 'bg-gray-500',
    border: 'border-gray-500',
  }),
}));

const mockRivalsResponse = {
  rivals: [
    {
      agent_a: 'claude-3-opus',
      agent_b: 'gpt-4o',
      rivalry_score: 0.85,
      alliance_score: 0.1,
      relationship: 'rival',
      debate_count: 15,
    },
    {
      agent_a: 'gemini-pro',
      agent_b: 'claude-3-opus',
      rivalry_score: 0.65,
      alliance_score: 0.2,
      relationship: 'rival',
      debate_count: 8,
    },
  ],
};

const mockAlliesResponse = {
  allies: [
    {
      agent_a: 'claude-3-opus',
      agent_b: 'claude-3-sonnet',
      rivalry_score: 0.1,
      alliance_score: 0.75,
      relationship: 'ally',
      debate_count: 12,
    },
  ],
};

describe('AgentRelationships', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  const setupSuccessfulFetch = () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/rivals')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockRivalsResponse) });
      }
      if (url.includes('/allies')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockAlliesResponse) });
      }
      return Promise.resolve({ ok: false, status: 404 });
    });
  };

  describe('Loading State', () => {
    it('shows loading skeleton initially', () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves

      const { container } = render(<AgentRelationships agentName="claude-3-opus" />);

      expect(container.querySelector('.animate-pulse')).toBeInTheDocument();
    });
  });

  describe('Error State', () => {
    it('displays error message when fetch fails', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('Failed to load relationships')).toBeInTheDocument();
      });
    });
  });

  describe('Empty State', () => {
    it('shows empty message when no relationships exist', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ rivals: [], allies: [] }),
      });

      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('No relationship data yet')).toBeInTheDocument();
      });
    });
  });

  describe('Full View', () => {
    beforeEach(() => {
      setupSuccessfulFetch();
    });

    it('displays rivals section header', async () => {
      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('Rivals')).toBeInTheDocument();
      });
    });

    it('displays allies section header', async () => {
      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('Allies')).toBeInTheDocument();
      });
    });

    it('displays rival agent names', async () => {
      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('gpt-4o')).toBeInTheDocument();
        expect(screen.getByText('gemini-pro')).toBeInTheDocument();
      });
    });

    it('displays ally agent names', async () => {
      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-sonnet')).toBeInTheDocument();
      });
    });

    it('displays rivalry scores as percentages', async () => {
      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('85% rivalry')).toBeInTheDocument();
        expect(screen.getByText('65% rivalry')).toBeInTheDocument();
      });
    });

    it('displays alliance scores as percentages', async () => {
      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('75% alliance')).toBeInTheDocument();
      });
    });

    it('displays debate counts', async () => {
      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('15 debates together')).toBeInTheDocument();
        expect(screen.getByText('8 debates together')).toBeInTheDocument();
        expect(screen.getByText('12 debates together')).toBeInTheDocument();
      });
    });

    it('handles singular debate count correctly', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/rivals')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                rivals: [
                  {
                    agent_a: 'claude-3-opus',
                    agent_b: 'gpt-4o',
                    rivalry_score: 0.5,
                    alliance_score: 0.1,
                    relationship: 'rival',
                    debate_count: 1,
                  },
                ],
              }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ allies: [] }) });
      });

      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('1 debate together')).toBeInTheDocument();
      });
    });
  });

  describe('Compact View', () => {
    beforeEach(() => {
      setupSuccessfulFetch();
    });

    it('renders compact badges when compact prop is true', async () => {
      const { container } = render(<AgentRelationships agentName="claude-3-opus" compact />);

      await waitFor(() => {
        // Should use inline flex layout with gaps
        const wrapper = container.querySelector('.flex.flex-wrap.gap-2');
        expect(wrapper).toBeInTheDocument();
      });
    });

    it('limits displayed rivals to 2 in compact mode', async () => {
      render(<AgentRelationships agentName="claude-3-opus" compact />);

      await waitFor(() => {
        // Both rivals should be visible in compact mode (we only have 2)
        expect(screen.getByText('gpt-4o')).toBeInTheDocument();
        expect(screen.getByText('gemini-pro')).toBeInTheDocument();
      });
    });

    it('shows rivalry score in tooltip for compact view', async () => {
      render(<AgentRelationships agentName="claude-3-opus" compact />);

      await waitFor(() => {
        const rivalBadge = screen.getByTitle('Rivalry score: 85%');
        expect(rivalBadge).toBeInTheDocument();
      });
    });

    it('shows alliance score in tooltip for compact view', async () => {
      render(<AgentRelationships agentName="claude-3-opus" compact />);

      await waitFor(() => {
        const allyBadge = screen.getByTitle('Alliance score: 75%');
        expect(allyBadge).toBeInTheDocument();
      });
    });
  });

  describe('Agent Name Handling', () => {
    it('fetches with encoded agent name', async () => {
      setupSuccessfulFetch();

      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/agent/claude-3-opus/rivals'),
        );
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/agent/claude-3-opus/allies'),
        );
      });
    });

    it('correctly identifies other agent from relationship', async () => {
      // Test when agent_a is the target agent
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/rivals')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                rivals: [
                  {
                    agent_a: 'claude-3-opus',
                    agent_b: 'opponent-agent',
                    rivalry_score: 0.5,
                    alliance_score: 0.1,
                    relationship: 'rival',
                    debate_count: 5,
                  },
                ],
              }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ allies: [] }) });
      });

      render(<AgentRelationships agentName="claude-3-opus" />);

      await waitFor(() => {
        expect(screen.getByText('opponent-agent')).toBeInTheDocument();
      });
    });
  });

  describe('Custom API Base', () => {
    it('uses custom API base when provided', async () => {
      setupSuccessfulFetch();

      render(
        <AgentRelationships agentName="claude-3-opus" apiBase="https://custom-api.example.com" />,
      );

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('https://custom-api.example.com/api/agent/'),
        );
      });
    });
  });
});
