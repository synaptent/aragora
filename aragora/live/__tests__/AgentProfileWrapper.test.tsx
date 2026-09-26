/**
 * Tests for AgentProfileWrapper component
 *
 * Tests cover:
 * - Profile data fetching and display
 * - Tab navigation (overview, performance, domains, history, moments, network, compare)
 * - Loading and error states
 * - Head-to-head comparison functionality
 * - Responsive layout
 */

import { renderWithProviders, screen, fireEvent, waitFor } from '@/test-utils';
import { AgentProfileWrapper } from '../src/app/(app)/agent/[[...name]]/AgentProfileWrapper';
import { mockRouter, useParams } from 'next/navigation';

const mockParams = { name: ['claude-3-opus'] };

// Mock next/link
jest.mock('next/link', () => {
  return ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  );
});

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Sample response data
const mockProfileData = {
  agent: 'claude-3-opus',
  ranking: {
    rating: { elo: 1650, wins: 25, losses: 10, draws: 5, games_played: 40 },
    recent_matches: 10,
  },
  persona: {
    type: 'analytical',
    primary_stance: 'evidence-based',
    specializations: ['technology', 'ethics'],
    debate_count: 40,
  },
  consistency: { score: 0.85, recent_flips: 2 },
  calibration: { brier_score: 0.15, prediction_count: 30 },
};

const mockMomentsData = {
  moments: [
    {
      type: 'breakthrough',
      description: 'First consensus leadership',
      timestamp: '2026-01-10T10:00:00Z',
      significance: 0.9,
    },
    {
      type: 'upset_win',
      description: 'Won against top-ranked opponent',
      timestamp: '2026-01-09T10:00:00Z',
      significance: 0.85,
    },
  ],
};

const mockNetworkData = {
  agent: 'claude-3-opus',
  rivals: [
    { agent: 'gpt-4o', score: 0.8, debate_count: 10 },
    { agent: 'gemini-pro', score: 0.6, debate_count: 5 },
  ],
  allies: [{ agent: 'claude-3-sonnet', score: 0.7, debate_count: 8 }],
  influences: [],
  influenced_by: [],
};

const mockDomainsData = {
  agent: 'claude-3-opus',
  overall_elo: 1650,
  domains: [
    { domain: 'technology', elo: 1700, relative: 50 },
    { domain: 'ethics', elo: 1600, relative: -50 },
  ],
  domain_count: 2,
};

const mockPerformanceData = {
  agent: 'claude-3-opus',
  elo: 1650,
  total_games: 40,
  wins: 25,
  losses: 10,
  draws: 5,
  win_rate: 0.625,
  recent_win_rate: 0.7,
  elo_trend: 25,
  critiques_accepted: 15,
  critiques_total: 20,
  critique_acceptance_rate: 0.75,
  calibration: { accuracy: 0.8, brier_score: 0.15, prediction_count: 30 },
};

const mockHistoryData = {
  agent: 'claude-3-opus',
  history: [
    {
      debate_id: 'debate-1',
      topic: 'AI Ethics',
      opponent: 'gpt-4o',
      result: 'win',
      elo_change: 15,
      elo_after: 1650,
      created_at: '2026-01-10T10:00:00Z',
    },
    {
      debate_id: 'debate-2',
      topic: 'Climate Policy',
      opponent: 'gemini-pro',
      result: 'loss',
      elo_change: -10,
      elo_after: 1635,
      created_at: '2026-01-09T10:00:00Z',
    },
  ],
};

const mockHeadToHeadData = {
  agent: 'claude-3-opus',
  opponent: 'gpt-4o',
  matches: 10,
  wins: 6,
  losses: 3,
  draws: 1,
  win_rate: 0.6,
};

describe('AgentProfileWrapper', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    mockRouter.push.mockClear();
    mockRouter.back.mockClear();
    useParams.mockReturnValue(mockParams);
  });

  const setupSuccessfulFetch = () => {
    mockFetch.mockImplementation((url: string) => {
      if (url.includes('/profile')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockProfileData) });
      }
      if (url.includes('/moments')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockMomentsData) });
      }
      if (url.includes('/network')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockNetworkData) });
      }
      if (url.includes('/domains')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockDomainsData) });
      }
      if (url.includes('/performance')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockPerformanceData) });
      }
      if (url.includes('/history')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockHistoryData) });
      }
      if (url.includes('/head-to-head')) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve(mockHeadToHeadData) });
      }
      return Promise.resolve({ ok: false, status: 404 });
    });
  };

  describe('Initial Render', () => {
    it('shows loading state initially', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves

      renderWithProviders(<AgentProfileWrapper />);

      expect(screen.getByText(/loading/i)).toBeInTheDocument();
    });

    it('displays agent name in header after loading', async () => {
      setupSuccessfulFetch();

      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });
    });

    it('displays ELO rating', async () => {
      setupSuccessfulFetch();

      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('1650')).toBeInTheDocument();
      });
    });

    it('displays persona type badge', async () => {
      setupSuccessfulFetch();

      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('analytical')).toBeInTheDocument();
      });
    });
  });

  describe('Stats Cards', () => {
    beforeEach(() => {
      setupSuccessfulFetch();
    });

    it('displays win rate', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('63%')).toBeInTheDocument(); // 25/40 = 62.5% rounds to 63%
      });
    });

    it('displays win/loss/draw record', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('25W-10L-5D')).toBeInTheDocument();
      });
    });

    it('displays consistency score', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('85%')).toBeInTheDocument();
      });
    });

    it('displays calibration brier score', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('0.150')).toBeInTheDocument();
      });
    });
  });

  describe('Tab Navigation', () => {
    beforeEach(() => {
      setupSuccessfulFetch();
    });

    it('renders all tabs', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /overview/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /performance/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /domains/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /history/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /moments/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /network/i })).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /compare/i })).toBeInTheDocument();
      });
    });

    it('switches to performance tab when clicked', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /performance/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /performance/i }));

      await waitFor(() => {
        expect(screen.getByText('Performance Statistics')).toBeInTheDocument();
      });
    });

    it('switches to domains tab when clicked', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /domains/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /domains/i }));

      await waitFor(() => {
        expect(screen.getByText('Domain Expertise')).toBeInTheDocument();
      });
    });

    it('switches to history tab when clicked', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /history/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /history/i }));

      await waitFor(() => {
        expect(screen.getByText('Debate History')).toBeInTheDocument();
      });
    });

    it('switches to moments tab when clicked', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /moments/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /moments/i }));

      await waitFor(() => {
        expect(screen.getByText('Moments Timeline')).toBeInTheDocument();
      });
    });

    it('switches to network tab when clicked', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /network/i })).toBeInTheDocument();
      });

      fireEvent.click(screen.getByRole('button', { name: /network/i }));

      await waitFor(() => {
        expect(screen.getByText('Relationship Network')).toBeInTheDocument();
      });
    });
  });

  describe('Overview Tab Content', () => {
    beforeEach(() => {
      setupSuccessfulFetch();
    });

    it('displays persona information', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('Persona')).toBeInTheDocument();
        expect(screen.getByText('evidence-based')).toBeInTheDocument();
      });
    });

    it('displays specializations', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('technology')).toBeInTheDocument();
        expect(screen.getByText('ethics')).toBeInTheDocument();
      });
    });

    it('displays recent moments preview', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('Recent Moments')).toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('displays error message when fetch fails', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText(/network error/i)).toBeInTheDocument();
      });
    });

    it('shows return link on error', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText(/return to dashboard/i)).toBeInTheDocument();
      });
    });
  });

  describe('Navigation', () => {
    beforeEach(() => {
      setupSuccessfulFetch();
    });

    it('has back button that navigates back', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        const backButton = screen.getByText('← Back');
        expect(backButton).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('← Back'));
      expect(mockRouter.back).toHaveBeenCalled();
    });

    it('has dashboard link', async () => {
      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        const dashboardLink = screen.getByText('Dashboard');
        expect(dashboardLink).toBeInTheDocument();
        expect(dashboardLink.closest('a')).toHaveAttribute('href', '/');
      });
    });
  });

  describe('No Agent Selected', () => {
    it('shows agent list prompt when no agent name', async () => {
      // Override params to have no name
      jest.spyOn(require('next/navigation'), 'useParams').mockReturnValue({ name: undefined });

      renderWithProviders(<AgentProfileWrapper />);

      await waitFor(() => {
        expect(screen.getByText('Agent Profiles')).toBeInTheDocument();
        expect(screen.getByText(/select an agent/i)).toBeInTheDocument();
      });
    });
  });
});
