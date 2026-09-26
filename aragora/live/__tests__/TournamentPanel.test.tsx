/**
 * Tests for TournamentPanel component
 *
 * Tests cover:
 * - Loading and error states
 * - Tournament selector
 * - Tournament stats display
 * - Standings display with rankings
 * - Auto-refresh functionality
 * - Empty state handling
 */

import { renderWithProviders, screen, fireEvent, waitFor, act } from '@/test-utils';
import { TournamentPanel } from '../src/components/TournamentPanel';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockTournamentsData = {
  tournaments: [
    {
      tournament_id: 'tournament-2026-01',
      participants: 8,
      total_matches: 28,
      top_agent: 'claude-3-opus',
    },
    {
      tournament_id: 'tournament-2025-12',
      participants: 6,
      total_matches: 15,
      top_agent: 'gemini-2.0-flash',
    },
  ],
};

const mockStandingsData = {
  standings: [
    {
      agent: 'claude-3-opus',
      wins: 6,
      losses: 1,
      draws: 0,
      points: 18,
      total_score: 42,
      win_rate: 0.86,
    },
    {
      agent: 'gemini-2.0-flash',
      wins: 5,
      losses: 2,
      draws: 0,
      points: 15,
      total_score: 38,
      win_rate: 0.71,
    },
    { agent: 'grok-2', wins: 4, losses: 3, draws: 0, points: 12, total_score: 32, win_rate: 0.57 },
    { agent: 'llama-3', wins: 2, losses: 5, draws: 0, points: 6, total_score: 20, win_rate: 0.29 },
  ],
};

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/api/tournaments/') && url.includes('/standings')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStandingsData) });
    }
    if (url.includes('/api/tournaments')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTournamentsData) });
    }
    return Promise.resolve({ ok: false });
  });
}

describe('TournamentPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('Loading States', () => {
    it('shows loading state while fetching data', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {}));
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
      });
      expect(screen.getByText('Loading tournaments...')).toBeInTheDocument();
    });

    it('shows panel title', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {}));
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
      });
      expect(screen.getByText('Tournaments')).toBeInTheDocument();
    });
  });

  describe('Data Display', () => {
    it('renders tournament selector after data loads', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByRole('combobox')).toBeInTheDocument();
      });
    });

    it('auto-selects first tournament', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        const select = screen.getByRole('combobox') as HTMLSelectElement;
        expect(select.value).toBe('tournament-2026-01');
      });
    });

    it('displays tournament options with agent and match counts', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText(/tournament-2026-01/)).toBeInTheDocument();
        expect(screen.getByText(/8 agents, 28 matches/)).toBeInTheDocument();
      });
    });
  });

  describe('Tournament Stats', () => {
    it('displays participant count', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('8')).toBeInTheDocument();
        expect(screen.getByText('Agents')).toBeInTheDocument();
      });
    });

    it('displays match count', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('28')).toBeInTheDocument();
        expect(screen.getByText('Matches')).toBeInTheDocument();
      });
    });

    it('displays top agent', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('Leader')).toBeInTheDocument();
      });
    });
  });

  describe('Standings Display', () => {
    it('shows standings with agent names', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
        await jest.runAllTimersAsync();
      });

      await waitFor(() => {
        // claude-3-opus appears in both Leader and standings
        const claudeElements = screen.getAllByText('claude-3-opus');
        expect(claudeElements.length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText('gemini-2.0-flash')).toBeInTheDocument();
        expect(screen.getByText('grok-2')).toBeInTheDocument();
      });
    });

    it('shows win-loss-draw records', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
        await jest.runAllTimersAsync();
      });

      await waitFor(() => {
        expect(screen.getByText('6W-1L-0D')).toBeInTheDocument(); // claude
        expect(screen.getByText('5W-2L-0D')).toBeInTheDocument(); // gemini
      });
    });

    it('shows points', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
        await jest.runAllTimersAsync();
      });

      await waitFor(() => {
        expect(screen.getByText('18.0 pts')).toBeInTheDocument();
        expect(screen.getByText('15.0 pts')).toBeInTheDocument();
      });
    });

    it('shows win rates as percentages', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
        await jest.runAllTimersAsync();
      });

      await waitFor(() => {
        expect(screen.getByText('86%')).toBeInTheDocument(); // claude
        expect(screen.getByText('71%')).toBeInTheDocument(); // gemini
      });
    });

    it('shows rank badges', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
        await jest.runAllTimersAsync();
      });

      await waitFor(() => {
        // Rank numbers should be visible
        expect(screen.getByText('1')).toBeInTheDocument();
        expect(screen.getByText('2')).toBeInTheDocument();
        expect(screen.getByText('3')).toBeInTheDocument();
        expect(screen.getByText('4')).toBeInTheDocument();
      });
    });
  });

  describe('Tournament Selection', () => {
    it('changes standings when different tournament selected', async () => {
      jest.useRealTimers(); // Use real timers for this test

      const secondStandingsData = {
        standings: [
          {
            agent: 'different-agent',
            wins: 4,
            losses: 2,
            draws: 0,
            points: 12,
            total_score: 30,
            win_rate: 0.67,
          },
        ],
      };

      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/standings')) {
          if (url.includes('tournament-2025-12')) {
            return Promise.resolve({ ok: true, json: () => Promise.resolve(secondStandingsData) });
          }
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockStandingsData) });
        }
        if (url.includes('/api/tournaments')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTournamentsData) });
        }
        return Promise.resolve({ ok: false });
      });

      renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        const claudeElements = screen.getAllByText('claude-3-opus');
        expect(claudeElements.length).toBeGreaterThanOrEqual(1);
      });

      // Change to second tournament
      const select = screen.getByRole('combobox');
      fireEvent.change(select, { target: { value: 'tournament-2025-12' } });

      await waitFor(() => {
        expect(screen.getByText('different-agent')).toBeInTheDocument();
      });
    });
  });

  describe('Refresh Button', () => {
    it('fetches fresh data when clicked', async () => {
      jest.useRealTimers(); // Use real timers for this test
      setupSuccessfulFetch();

      renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        const claudeElements = screen.getAllByText('claude-3-opus');
        expect(claudeElements.length).toBeGreaterThanOrEqual(1);
      });

      const initialCalls = mockFetch.mock.calls.length;

      fireEvent.click(screen.getByText('Refresh'));

      await waitFor(() => {
        expect(mockFetch.mock.calls.length).toBeGreaterThan(initialCalls);
      });
    });
  });

  describe('Auto-refresh', () => {
    it('refreshes data every 60 seconds', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        const claudeElements = screen.getAllByText('claude-3-opus');
        expect(claudeElements.length).toBeGreaterThanOrEqual(1);
      });

      const initialCalls = mockFetch.mock.calls.length;

      // Advance timer by 60 seconds
      await act(async () => {
        jest.advanceTimersByTime(60000);
      });

      await waitFor(() => {
        expect(mockFetch.mock.calls.length).toBeGreaterThan(initialCalls);
      });
    });

    it('cleans up interval on unmount', async () => {
      setupSuccessfulFetch();

      const { unmount } = renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        const claudeElements = screen.getAllByText('claude-3-opus');
        expect(claudeElements.length).toBeGreaterThanOrEqual(1);
      });

      const callsBeforeUnmount = mockFetch.mock.calls.length;
      unmount();

      await act(async () => {
        jest.advanceTimersByTime(60000);
      });

      // No new calls after unmount
      expect(mockFetch.mock.calls.length).toBe(callsBeforeUnmount);
    });
  });

  describe('Error Handling', () => {
    it('shows error message when fetch fails', async () => {
      jest.useRealTimers(); // Use real timers for this test
      mockFetch.mockImplementation(() => Promise.reject(new Error('Network error')));

      renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('Network error')).toBeInTheDocument();
      });
    });
  });

  describe('Empty State', () => {
    it('shows empty state when no tournaments exist', async () => {
      jest.useRealTimers(); // Use real timers for this test
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/tournaments')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ tournaments: [] }) });
        }
        return Promise.resolve({ ok: false });
      });

      renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText(/No tournaments yet/)).toBeInTheDocument();
      });
    });

    it('shows empty standings message when tournament has no standings', async () => {
      jest.useRealTimers(); // Use real timers for this test
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/standings')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ standings: [] }) });
        }
        if (url.includes('/api/tournaments')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTournamentsData) });
        }
        return Promise.resolve({ ok: false });
      });

      renderWithProviders(<TournamentPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('No standings available for this tournament.')).toBeInTheDocument();
      });
    });
  });
});
