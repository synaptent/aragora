/**
 * Tests for AgentComparePanel component
 */

import { renderWithProviders, screen, waitFor } from '@/test-utils';
import { AgentComparePanel } from '../src/components/AgentComparePanel';

// Mock useAuth to always return authenticated state
jest.mock('@/context/AuthContext', () => ({
  ...jest.requireActual('@/context/AuthContext'),
  useAuth: () => ({
    user: null,
    organization: null,
    organizations: [],
    tokens: { access_token: 'test-token', refresh_token: 'r', token_type: 'bearer' },
    isLoading: false,
    isAuthenticated: true,
    isLoadingOrganizations: false,
    login: jest.fn(),
    register: jest.fn(),
    logout: jest.fn(),
    refreshToken: jest.fn(),
    setTokens: jest.fn(),
    switchOrganization: jest.fn(),
    refreshOrganizations: jest.fn(),
    getCurrentOrgRole: jest.fn(),
  }),
}));

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('AgentComparePanel', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  const mockRankings = {
    rankings: [
      { name: 'claude', rating: 1800 },
      { name: 'gemini', rating: 1750 },
      { name: 'gpt-4', rating: 1700 },
      { name: 'llama', rating: 1650 },
    ],
  };

  const mockComparison = {
    agents: [
      {
        name: 'claude',
        rating: 1800,
        rank: 1,
        wins: 45,
        losses: 12,
        win_rate: 0.789,
        consistency_score: 0.92,
        domains: ['coding', 'reasoning', 'analysis'],
      },
      {
        name: 'gemini',
        rating: 1750,
        rank: 2,
        wins: 38,
        losses: 15,
        win_rate: 0.717,
        consistency_score: 0.88,
        domains: ['coding', 'creative', 'math'],
      },
    ],
    head_to_head: { matches: 8, agent1_wins: 5, agent2_wins: 3, draws: 0 },
  };

  describe('Agent Selection', () => {
    beforeEach(() => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/rankings')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockRankings) });
        }
        if (url.includes('/api/agent/compare')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockComparison) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });
    });

    it('renders agent selection dropdowns', async () => {
      renderWithProviders(<AgentComparePanel />);

      await waitFor(() => {
        expect(screen.getByText('Agent 1')).toBeInTheDocument();
        expect(screen.getByText('Agent 2')).toBeInTheDocument();
      });
    });

    it('loads available agents from rankings API', async () => {
      renderWithProviders(<AgentComparePanel />);

      await waitFor(() => {
        const selects = screen.getAllByRole('combobox');
        expect(selects.length).toBe(2);
      });
    });

    it('uses provided availableAgents if given', async () => {
      const agents = ['agent-a', 'agent-b', 'agent-c'];
      renderWithProviders(<AgentComparePanel availableAgents={agents} />);

      await waitFor(() => {
        // Each agent appears in both dropdowns, so use getAllByRole
        const agentAOptions = screen.getAllByRole('option', { name: 'agent-a' });
        const agentBOptions = screen.getAllByRole('option', { name: 'agent-b' });
        const agentCOptions = screen.getAllByRole('option', { name: 'agent-c' });
        expect(agentAOptions.length).toBe(2); // Appears in both dropdowns
        expect(agentBOptions.length).toBe(2);
        expect(agentCOptions.length).toBe(2);
      });
    });

    it('uses initialAgents for default selection', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['agent-a', 'agent-b', 'agent-c']}
          initialAgents={['agent-a', 'agent-c']}
        />,
      );

      await waitFor(() => {
        const selects = screen.getAllByRole('combobox');
        expect(selects[0]).toHaveValue('agent-a');
        expect(selects[1]).toHaveValue('agent-c');
      });
    });

    it('shows warning when same agent selected', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'claude']}
        />,
      );

      await waitFor(() => {
        expect(
          screen.getByText('Please select two different agents to compare'),
        ).toBeInTheDocument();
      });
    });
  });

  describe('Comparison Display', () => {
    beforeEach(() => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/rankings')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockRankings) });
        }
        if (url.includes('/api/agent/compare')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockComparison) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });
    });

    it('displays ELO ratings for both agents', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText('1800')).toBeInTheDocument();
        expect(screen.getByText('1750')).toBeInTheDocument();
      });
    });

    it('displays rating difference', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText('+50')).toBeInTheDocument();
      });
    });

    it('displays win/loss stats', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText('45')).toBeInTheDocument(); // claude wins
        expect(screen.getByText('38')).toBeInTheDocument(); // gemini wins
        expect(screen.getByText('12')).toBeInTheDocument(); // claude losses
        expect(screen.getByText('15')).toBeInTheDocument(); // gemini losses
      });
    });

    it('displays win rates with color coding', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText('78.9%')).toBeInTheDocument();
        expect(screen.getByText('71.7%')).toBeInTheDocument();
      });
    });

    it('displays ranks', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText('#1')).toBeInTheDocument();
        expect(screen.getByText('#2')).toBeInTheDocument();
      });
    });

    it('displays consistency scores', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText('92%')).toBeInTheDocument(); // claude
        expect(screen.getByText('88%')).toBeInTheDocument(); // gemini
      });
    });
  });

  describe('Head-to-Head Display', () => {
    beforeEach(() => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/rankings')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockRankings) });
        }
        if (url.includes('/api/agent/compare')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockComparison) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });
    });

    it('displays head-to-head record', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText('Head-to-Head Record')).toBeInTheDocument();
        expect(screen.getByText('8 matches')).toBeInTheDocument();
      });
    });

    it('displays win counts for each agent', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        // The head-to-head section shows wins: 5 for agent1, 3 for agent2
        const winElements = screen.getAllByText('Wins');
        expect(winElements.length).toBeGreaterThan(0);
      });
    });
  });

  describe('Domain Expertise', () => {
    beforeEach(() => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/rankings')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockRankings) });
        }
        if (url.includes('/api/agent/compare')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockComparison) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });
    });

    it('displays domain expertise section', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText('Domain Expertise')).toBeInTheDocument();
      });
    });

    it('displays domain badges', async () => {
      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        // coding appears in both agents' domains
        const codingBadges = screen.getAllByText('coding');
        expect(codingBadges.length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText('reasoning')).toBeInTheDocument();
        expect(screen.getByText('creative')).toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('displays error message when comparison fails', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/rankings')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockRankings) });
        }
        if (url.includes('/api/agent/compare')) {
          return Promise.resolve({ ok: false, status: 500 });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(screen.getByText(/Comparison failed: 500/)).toBeInTheDocument();
      });
    });
  });

  describe('Loading State', () => {
    it('shows loading spinner during comparison', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/rankings')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockRankings) });
        }
        if (url.includes('/api/agent/compare')) {
          return new Promise(() => {}); // Never resolves
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(
        <AgentComparePanel
          availableAgents={['claude', 'gemini']}
          initialAgents={['claude', 'gemini']}
        />,
      );

      await waitFor(() => {
        expect(document.querySelector('.animate-spin')).toBeInTheDocument();
      });
    });
  });
});
