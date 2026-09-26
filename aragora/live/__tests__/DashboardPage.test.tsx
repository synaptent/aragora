/**
 * Tests for Dashboard page — backend API integration, Supabase fallback, and system status
 */
import { render, screen, waitFor, act } from '@testing-library/react';

// Mock next/link
jest.mock('next/link', () => {
  return ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  );
});

// Mock config
jest.mock('../src/config', () => ({
  API_BASE_URL: 'http://localhost:8080',
  WS_URL: 'ws://localhost:8765/ws',
}));

// Mock MatrixRain
jest.mock('../src/components/MatrixRain', () => ({
  Scanlines: () => null,
  CRTVignette: () => null,
}));

// Mock auth gate for legacy dashboard integration tests
jest.mock('../src/components/auth/ProtectedRoute', () => ({
  ProtectedRoute: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock ExecutiveSummary
jest.mock('../src/components/dashboard/ExecutiveSummary', () => ({
  ExecutiveSummary: () => <div data-testid="executive-summary">Executive Summary</div>,
}));

// Mock CostSummaryWidget
jest.mock('../src/components/costs/CostSummaryWidget', () => ({
  CostSummaryWidget: () => <div data-testid="cost-summary">Cost Summary</div>,
}));

// Mock TrialStatusWidget
jest.mock('../src/components/billing/TrialStatusWidget', () => ({
  TrialStatusWidget: () => <div data-testid="trial-status">Trial Status</div>,
}));

// Mock TemplateMarketplace
jest.mock('../src/components/templates/TemplateMarketplace', () => ({
  TemplateMarketplace: () => <div data-testid="template-marketplace">Templates</div>,
}));

// Mock RightSidebarContext
jest.mock('../src/context/RightSidebarContext', () => ({
  useRightSidebar: () => ({ setContext: jest.fn(), clearContext: jest.fn() }),
}));

// Mock useDashboardEvents
jest.mock('../src/hooks/useDashboardEvents', () => ({
  useDashboardEvents: () => ({ isConnected: false, updateCount: 0 }),
}));

// Mock logger
jest.mock('../src/utils/logger', () => ({
  logger: { warn: jest.fn(), error: jest.fn(), info: jest.fn(), debug: jest.fn() },
}));

// Mock Supabase
const mockFetchRecentDebates = jest.fn();
jest.mock('../src/utils/supabase', () => ({
  fetchRecentDebates: (...args: unknown[]) => mockFetchRecentDebates(...args),
}));

// Mock agent colors
jest.mock('../src/utils/agentColors', () => ({
  getAgentColors: () => ({ bg: 'bg-blue-500/20', text: 'text-blue-400' }),
}));

// Mock useSWRFetch — route by endpoint to survive re-renders
let swrResponses: Record<string, { data: unknown; error: unknown; isLoading: boolean }> = {};

jest.mock('../src/hooks/useSWRFetch', () => ({
  useSWRFetch: (endpoint: string, _options?: unknown) => {
    // Match the endpoint prefix to route the response
    if (endpoint?.includes('/api/v1/debates')) {
      return swrResponses['debates'] ?? { data: null, error: null, isLoading: false };
    }
    if (endpoint?.includes('/api/health')) {
      return swrResponses['health'] ?? { data: null, error: null, isLoading: false };
    }
    return { data: null, error: null, isLoading: false };
  },
  useActiveDebates: () => ({ data: { debates: [] }, isLoading: false }),
}));

import DashboardPage from '../src/app/(app)/dashboard/page';

describe('DashboardPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetchRecentDebates.mockResolvedValue([]);
    swrResponses = {};
  });

  it('renders page header', () => {
    render(<DashboardPage />);

    expect(screen.getByText(/EXECUTIVE DASHBOARD/)).toBeInTheDocument();
  });

  it('shows loading state while backend is fetching', () => {
    swrResponses['debates'] = { data: null, error: null, isLoading: true };
    swrResponses['health'] = { data: null, error: null, isLoading: true };

    render(<DashboardPage />);

    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('renders debates from backend API', async () => {
    swrResponses['debates'] = {
      data: {
        debates: [
          {
            id: 'debate-1',
            task: 'Should we use microservices?',
            agents: ['claude', 'gpt-4'],
            consensus_reached: true,
            confidence: 0.87,
            created_at: new Date().toISOString(),
          },
        ],
      },
      error: null,
      isLoading: false,
    };
    swrResponses['health'] = { data: { status: 'ok' }, error: null, isLoading: false };

    await act(async () => {
      render(<DashboardPage />);
    });

    await waitFor(() => {
      expect(screen.getByText('Should we use microservices?')).toBeInTheDocument();
    });
  });

  it('renders debates from backend without Supabase fallback', async () => {
    swrResponses['debates'] = {
      data: {
        debates: [
          {
            id: 'debate-1',
            task: 'Test debate',
            agents: ['claude'],
            consensus_reached: false,
            confidence: 0.5,
            created_at: new Date().toISOString(),
          },
        ],
      },
      error: null,
      isLoading: false,
    };
    swrResponses['health'] = { data: { status: 'ok' }, error: null, isLoading: false };

    await act(async () => {
      render(<DashboardPage />);
    });

    await waitFor(() => {
      expect(screen.getByText('Test debate')).toBeInTheDocument();
    });
    // Backend data used — Supabase fallback should NOT be called
    expect(mockFetchRecentDebates).not.toHaveBeenCalled();
  });

  it('falls back to Supabase when backend errors', async () => {
    swrResponses['debates'] = { data: null, error: new Error('Backend down'), isLoading: false };
    swrResponses['health'] = { data: null, error: null, isLoading: false };

    mockFetchRecentDebates.mockResolvedValue([
      {
        id: 'supa-1',
        task: 'Supabase debate',
        agents: ['claude'],
        consensus_reached: true,
        confidence: 0.9,
        created_at: new Date().toISOString(),
        loop_id: '',
        cycle_number: 0,
        phase: 'completed',
        transcript: [],
        winning_proposal: null,
        vote_tally: null,
      },
    ]);

    await act(async () => {
      render(<DashboardPage />);
    });

    await waitFor(() => {
      expect(mockFetchRecentDebates).toHaveBeenCalledWith(5);
    });
  });

  it('normalizes debate_id to id field', async () => {
    swrResponses['debates'] = {
      data: {
        debates: [
          {
            id: 'raw-id',
            debate_id: 'canonical-id',
            task: 'Normalized debate',
            agents: ['claude'],
            consensus_reached: true,
            confidence: 0.8,
            created_at: new Date().toISOString(),
          },
        ],
      },
      error: null,
      isLoading: false,
    };
    swrResponses['health'] = { data: { status: 'ok' }, error: null, isLoading: false };

    await act(async () => {
      render(<DashboardPage />);
    });

    await waitFor(() => {
      expect(screen.getByText('Normalized debate')).toBeInTheDocument();
    });

    const link = screen.getByText('Normalized debate').closest('a');
    expect(link?.getAttribute('href')).toBe('/debate/canonical-id');
  });

  it('normalizes question field to task', async () => {
    swrResponses['debates'] = {
      data: {
        results: [
          {
            id: 'debate-q',
            question: 'What is the meaning of life?',
            agents: ['claude'],
            consensus_reached: false,
            confidence: 0.42,
            created_at: new Date().toISOString(),
          },
        ],
      },
      error: null,
      isLoading: false,
    };

    await act(async () => {
      render(<DashboardPage />);
    });

    await waitFor(() => {
      expect(screen.getByText('What is the meaning of life?')).toBeInTheDocument();
    });
  });

  it('shows empty state when no debates exist', async () => {
    swrResponses['debates'] = { data: { debates: [] }, error: null, isLoading: false };
    swrResponses['health'] = { data: { status: 'ok' }, error: null, isLoading: false };

    await act(async () => {
      render(<DashboardPage />);
    });

    await waitFor(() => {
      expect(screen.getByText(/No recent debates/)).toBeInTheDocument();
      expect(screen.getAllByText('Start one').length).toBeGreaterThan(0);
    });
  });

  describe('SystemStatusPanel', () => {
    it('shows LIVE when health check returns ok', async () => {
      swrResponses['debates'] = { data: { debates: [] }, error: null, isLoading: false };
      swrResponses['health'] = { data: { status: 'ok' }, error: null, isLoading: false };

      await act(async () => {
        render(<DashboardPage />);
      });

      await waitFor(() => {
        // Two LIVE badges: page header + SystemStatusPanel
        const liveElements = screen.getAllByText('LIVE');
        expect(liveElements.length).toBeGreaterThanOrEqual(1);
      });
    });

    it('shows OFFLINE when health check fails', async () => {
      swrResponses['debates'] = { data: { debates: [] }, error: null, isLoading: false };
      swrResponses['health'] = {
        data: null,
        error: new Error('Connection refused'),
        isLoading: false,
      };

      await act(async () => {
        render(<DashboardPage />);
      });

      await waitFor(() => {
        expect(screen.getByText('OFFLINE')).toBeInTheDocument();
      });
    });

    it('shows CHECKING when health check is loading', async () => {
      swrResponses['debates'] = { data: { debates: [] }, error: null, isLoading: false };
      swrResponses['health'] = { data: null, error: null, isLoading: false };

      // When no health data and no error, component shows CHECKING
      await act(async () => {
        render(<DashboardPage />);
      });

      expect(screen.getByText('CHECKING')).toBeInTheDocument();
    });

    it('displays component statuses from health response', async () => {
      swrResponses['debates'] = { data: { debates: [] }, error: null, isLoading: false };
      swrResponses['health'] = {
        data: {
          status: 'ok',
          components: {
            debate_engine: { status: 'operational' },
            agent_pool: { healthy: true },
            knowledge_mound: { status: 'degraded' },
          },
        },
        error: null,
        isLoading: false,
      };

      await act(async () => {
        render(<DashboardPage />);
      });

      await waitFor(() => {
        const statuses = screen.getAllByText('operational');
        expect(statuses.length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText('degraded')).toBeInTheDocument();
      });
    });

    it('shows uptime percentage when available', async () => {
      swrResponses['debates'] = { data: { debates: [] }, error: null, isLoading: false };
      swrResponses['health'] = {
        data: { status: 'ok', uptime_percent: 99.95 },
        error: null,
        isLoading: false,
      };

      await act(async () => {
        render(<DashboardPage />);
      });

      await waitFor(() => {
        expect(screen.getByText('99.95%')).toBeInTheDocument();
      });
    });
  });

  it('renders quick access grid', async () => {
    swrResponses['debates'] = { data: { debates: [] }, error: null, isLoading: false };
    swrResponses['health'] = { data: { status: 'ok' }, error: null, isLoading: false };

    await act(async () => {
      render(<DashboardPage />);
    });

    await waitFor(() => {
      // Text includes the '>' prefix: "> QUICK ACCESS"
      expect(screen.getByText(/QUICK ACCESS/)).toBeInTheDocument();
    });
    expect(screen.getByText('New Debate')).toBeInTheDocument();
    expect(screen.getByText('Debates')).toBeInTheDocument();
    expect(screen.getByText('Oracle')).toBeInTheDocument();
  });

  it('renders executive summary and cost widgets', async () => {
    swrResponses['debates'] = { data: { debates: [] }, error: null, isLoading: false };
    swrResponses['health'] = { data: { status: 'ok' }, error: null, isLoading: false };

    await act(async () => {
      render(<DashboardPage />);
    });

    expect(screen.getByTestId('executive-summary')).toBeInTheDocument();
    expect(screen.getByTestId('cost-summary')).toBeInTheDocument();
  });

  it('displays confidence percentage for debates', async () => {
    swrResponses['debates'] = {
      data: {
        debates: [
          {
            id: 'debate-c',
            task: 'High confidence debate',
            agents: ['claude', 'gpt-4'],
            consensus_reached: true,
            confidence: 0.95,
            created_at: new Date().toISOString(),
          },
        ],
      },
      error: null,
      isLoading: false,
    };
    swrResponses['health'] = { data: { status: 'ok' }, error: null, isLoading: false };

    await act(async () => {
      render(<DashboardPage />);
    });

    await waitFor(() => {
      expect(screen.getByText(/95%/)).toBeInTheDocument();
    });
  });
});
