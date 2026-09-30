/**
 * Tests for LeaderboardPanel component
 *
 * Tests cover:
 * - Rendering with mock data
 * - Tab switching functionality
 * - Error handling and display
 * - Domain filtering
 * - Consistency score display
 */

import { renderWithProviders, screen, fireEvent, waitFor, act } from '@/test-utils';
import { LeaderboardPanel } from '../src/components/LeaderboardPanel';

// Mock next/link
jest.mock('next/link', () => {
  return ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  );
});

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockLeaderboardData = {
  agents: [
    {
      name: 'claude-3-opus',
      elo: 1650,
      wins: 15,
      losses: 5,
      draws: 2,
      win_rate: 75,
      games: 22,
      consistency: 0.85,
      consistency_class: 'high',
    },
    {
      name: 'gemini-2.0-flash',
      elo: 1580,
      wins: 12,
      losses: 8,
      draws: 3,
      win_rate: 60,
      games: 23,
      consistency: 0.72,
      consistency_class: 'medium',
    },
    {
      name: 'grok-2',
      elo: 1520,
      wins: 10,
      losses: 10,
      draws: 2,
      win_rate: 50,
      games: 22,
      consistency: 0.55,
      consistency_class: 'low',
    },
  ],
  domains: ['technology', 'philosophy', 'science'],
};

const mockMatchesData = {
  matches: [
    {
      debate_id: 'debate-1',
      winner: 'claude-3-opus',
      participants: ['claude-3-opus', 'gemini-2.0-flash'],
      domain: 'technology',
      elo_changes: { 'claude-3-opus': 15, 'gemini-2.0-flash': -15 },
      created_at: '2024-01-15T10:30:00Z',
    },
  ],
};

const mockReputationData = {
  reputations: [
    {
      agent: 'claude-3-opus',
      score: 0.85,
      vote_weight: 1.2,
      proposal_acceptance_rate: 0.75,
      critique_value: 0.9,
      debates_participated: 22,
    },
  ],
};

const mockTeamsData = {
  combinations: [
    {
      agents: ['claude-3-opus', 'gemini-2.0-flash'],
      success_rate: 0.78,
      total_debates: 9,
      wins: 7,
    },
  ],
};

const mockStatsData = {
  mean_elo: 1550,
  median_elo: 1520,
  total_agents: 8,
  total_matches: 45,
  rating_distribution: { '1600': 2, '1500': 4, '1400': 2 },
  trending_up: ['claude-3-opus'],
  trending_down: ['grok-2'],
};

const mockIntrospectionData = {
  agents: {
    'claude-3-opus': {
      agent: 'claude-3-opus',
      self_model: { strengths: ['reasoning'], weaknesses: ['verbosity'], biases: ['formality'] },
      confidence_calibration: 0.82,
      recent_performance_assessment: 'Performing well in technical debates',
      improvement_focus: ['conciseness'],
      last_updated: '2024-01-15T10:00:00Z',
    },
  },
  count: 1,
};

// Consolidated endpoint response (primary endpoint used by LeaderboardPanel)
const mockConsolidatedResponse = {
  data: {
    rankings: { agents: mockLeaderboardData.agents, count: mockLeaderboardData.agents.length },
    matches: { matches: mockMatchesData.matches, count: mockMatchesData.matches.length },
    reputation: {
      reputations: mockReputationData.reputations,
      count: mockReputationData.reputations.length,
    },
    teams: { combinations: mockTeamsData.combinations, count: mockTeamsData.combinations.length },
    stats: mockStatsData,
    introspection: mockIntrospectionData,
  },
  errors: { partial_failure: false, failed_sections: [], messages: {} },
};

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string) => {
    const baseResponse = { ok: true, status: 200, url };
    // Consolidated endpoint (primary) - must check before /api/leaderboard
    if (url.includes('/api/leaderboard-view')) {
      return Promise.resolve({
        ...baseResponse,
        json: () => Promise.resolve(mockConsolidatedResponse),
      });
    }
    // Legacy individual endpoints (fallback)
    if (url.includes('/api/leaderboard')) {
      return Promise.resolve({ ...baseResponse, json: () => Promise.resolve(mockLeaderboardData) });
    }
    if (url.includes('/api/matches/recent')) {
      return Promise.resolve({ ...baseResponse, json: () => Promise.resolve(mockMatchesData) });
    }
    if (url.includes('/api/reputation/all')) {
      return Promise.resolve({ ...baseResponse, json: () => Promise.resolve(mockReputationData) });
    }
    if (url.includes('/api/routing/best-teams')) {
      return Promise.resolve({ ...baseResponse, json: () => Promise.resolve(mockTeamsData) });
    }
    if (url.includes('/api/ranking/stats')) {
      return Promise.resolve({ ...baseResponse, json: () => Promise.resolve(mockStatsData) });
    }
    if (url.includes('/api/introspection/all')) {
      return Promise.resolve({
        ...baseResponse,
        json: () => Promise.resolve(mockIntrospectionData),
      });
    }
    return Promise.resolve({
      ok: false,
      status: 404,
      url,
      text: () => Promise.resolve('Not found'),
    });
  });
}

describe('LeaderboardPanel', () => {
  let consoleWarnSpy: jest.SpyInstance;

  beforeEach(() => {
    jest.resetAllMocks();
    jest.useFakeTimers();
    // Suppress expected fallback warnings during tests
    consoleWarnSpy = jest.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    jest.useRealTimers();
    consoleWarnSpy.mockRestore();
  });

  it('renders skeleton loading state initially', async () => {
    mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves
    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });
    // Component uses skeleton loaders instead of text during loading
    // Just verify the component renders without error during loading
    expect(screen.getByText('Agent Leaderboard')).toBeInTheDocument();
  });

  it('renders agent rankings after data loads', async () => {
    setupSuccessfulFetch();
    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });

    await waitFor(() => {
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    expect(screen.getByText('gemini-2.0-flash')).toBeInTheDocument();
    expect(screen.getByText('grok-2')).toBeInTheDocument();
    expect(screen.getByText('1650')).toBeInTheDocument(); // ELO score
  });

  it('displays consistency scores for agents', async () => {
    setupSuccessfulFetch();
    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });

    await waitFor(() => {
      expect(screen.getByText('85%')).toBeInTheDocument(); // claude consistency
    });

    expect(screen.getByText('72%')).toBeInTheDocument(); // gemini consistency
    expect(screen.getByText('55%')).toBeInTheDocument(); // grok consistency
  });

  it('switches between tabs correctly', async () => {
    setupSuccessfulFetch();
    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });

    await waitFor(() => {
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    // Switch to Matches tab
    await act(async () => {
      fireEvent.click(screen.getByText('Matches'));
    });
    await waitFor(() => {
      expect(screen.getByText('claude-3-opus wins')).toBeInTheDocument();
    });

    // Switch to Stats tab
    await act(async () => {
      fireEvent.click(screen.getByText('Stats'));
    });
    await waitFor(() => {
      expect(screen.getByText('Mean ELO')).toBeInTheDocument();
      expect(screen.getByText('1550')).toBeInTheDocument();
    });

    // Switch to Minds tab
    await act(async () => {
      fireEvent.click(screen.getByText('Minds'));
    });
    await waitFor(() => {
      expect(screen.getByText('82% calibrated')).toBeInTheDocument();
    });
  });

  it('shows domain filter when domains are available', async () => {
    setupSuccessfulFetch();
    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });

    await waitFor(() => {
      expect(screen.getByText('Domain:')).toBeInTheDocument();
    });

    const select = screen.getByRole('combobox');
    expect(select).toBeInTheDocument();
    expect(screen.getByText('All Domains')).toBeInTheDocument();
  });

  it('handles partial endpoint failures gracefully', async () => {
    const partialFailureResponse = {
      data: {
        rankings: { agents: mockLeaderboardData.agents, count: mockLeaderboardData.agents.length },
        matches: { matches: [], count: 0 },
        reputation: { reputations: [], count: 0 },
        teams: {
          combinations: mockTeamsData.combinations,
          count: mockTeamsData.combinations.length,
        },
        stats: mockStatsData,
        introspection: { agents: {}, count: 0 },
      },
      errors: {
        partial_failure: true,
        failed_sections: ['matches', 'reputation'],
        messages: { matches: '503 Service Unavailable', reputation: '503 Service Unavailable' },
      },
    };
    mockFetch.mockImplementation((url: string) =>
      Promise.resolve({
        ok: true,
        status: 200,
        url,
        json: () => Promise.resolve(partialFailureResponse),
      }),
    );

    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });

    await waitFor(() => {
      // Should still show rankings even if other endpoints fail
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    // Should show partial error (consolidated uses "section(s)")
    expect(screen.getByText(/section\(s\) unavailable/)).toBeInTheDocument();
  });

  it('handles complete API failure', async () => {
    mockFetch.mockImplementation((url: string) =>
      Promise.resolve({
        ok: false,
        status: 500,
        url,
        text: () => Promise.resolve('500 Internal Server Error'),
      }),
    );

    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });

    await waitFor(() => {
      // Text may be split across elements
      expect(screen.getByText('All endpoints failed.')).toBeInTheDocument();
    });
  });

  it('shows error details when expanded', async () => {
    const errorResponse = {
      data: {
        rankings: { agents: [], count: 0 },
        matches: { matches: [], count: 0 },
        reputation: { reputations: [], count: 0 },
        teams: { combinations: [], count: 0 },
        stats: { mean_elo: 1500, median_elo: 1500, total_agents: 0, total_matches: 0 },
        introspection: { agents: {}, count: 0 },
      },
      errors: {
        partial_failure: true,
        failed_sections: ['rankings'],
        messages: { rankings: '503: ELO system not available' },
      },
    };
    mockFetch.mockImplementation((url: string) =>
      Promise.resolve({ ok: true, status: 200, url, json: () => Promise.resolve(errorResponse) }),
    );

    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });

    await waitFor(() => {
      // Consolidated uses "section(s)" for partial failures
      expect(screen.getByText(/section\(s\) unavailable/)).toBeInTheDocument();
    });

    await act(async () => {
      fireEvent.click(screen.getByText('Show details'));
    });
    expect(screen.getByText(/rankings:/)).toBeInTheDocument();
  });

  it('refreshes data when refresh button is clicked', async () => {
    setupSuccessfulFetch();
    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });

    await waitFor(() => {
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    expect(mockFetch).toHaveBeenCalledTimes(1); // 1 consolidated endpoint

    await act(async () => {
      fireEvent.click(screen.getByText('Refresh'));
    });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2); // 1 more call
    });
  });

  it('auto-refreshes every 30 seconds', async () => {
    setupSuccessfulFetch();
    await act(async () => {
      renderWithProviders(<LeaderboardPanel apiBase="http://localhost:3001" />);
    });

    await waitFor(() => {
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);

    // Advance timer by 30 seconds
    await act(async () => {
      jest.advanceTimersByTime(30000);
    });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });

  it('includes loopId in API requests when provided', async () => {
    setupSuccessfulFetch();
    await act(async () => {
      renderWithProviders(
        <LeaderboardPanel apiBase="http://localhost:3001" loopId="test-loop-123" />,
      );
    });

    await waitFor(() => {
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    const leaderboardCall = mockFetch.mock.calls.find((call: string[]) =>
      call[0].includes('/api/leaderboard-view'),
    );
    expect(leaderboardCall[0]).toContain('loop_id=test-loop-123');
  });
});
