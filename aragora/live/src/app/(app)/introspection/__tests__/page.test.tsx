import { renderWithProviders, screen, act, waitFor } from '@/test-utils';
import userEvent from '@testing-library/user-event';
import IntrospectionPage from '../page';

// Mock next/link
jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

// Mock visual components
jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

jest.mock('@/components/AsciiBanner', () => ({
  AsciiBannerCompact: () => <div data-testid="ascii-banner">ARAGORA</div>,
}));

jest.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button data-testid="theme-toggle">Theme</button>,
}));

// Mock BackendSelector with context
const mockBackendConfig = { api: 'http://localhost:8080' };
jest.mock('@/components/BackendSelector', () => ({
  BackendSelector: () => <div data-testid="backend-selector">Backend</div>,
  useBackend: () => ({ config: mockBackendConfig }),
}));

// Mock ErrorWithRetry
jest.mock('@/components/ErrorWithRetry', () => ({
  ErrorWithRetry: ({ error, onRetry }: { error: string; onRetry: () => void }) => (
    <div data-testid="error-display">
      <span>{error}</span>
      <button onClick={onRetry} data-testid="retry-button">
        Retry
      </button>
    </div>
  ),
}));

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('IntrospectionPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  describe('initial render', () => {
    it('renders visual effects', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ agents: [], leaderboard: [] }),
      });

      renderWithProviders(<IntrospectionPage />);

      expect(screen.getByTestId('scanlines')).toBeInTheDocument();
      expect(screen.getByTestId('crt-vignette')).toBeInTheDocument();
    });

    it('renders header elements', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ agents: [], leaderboard: [] }),
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByText('Agent Introspection')).toBeInTheDocument();
      });
    });

    it('renders page title', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ agents: [], leaderboard: [] }),
      });

      renderWithProviders(<IntrospectionPage />);

      expect(screen.getByText('Agent Introspection')).toBeInTheDocument();
    });

    it('shows loading state initially', () => {
      mockFetch.mockReturnValue(new Promise(() => {})); // Never resolves

      renderWithProviders(<IntrospectionPage />);

      expect(screen.getByText('Loading...')).toBeInTheDocument();
    });

    it('renders tab navigation', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ agents: [], leaderboard: [] }),
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      expect(screen.getByRole('button', { name: 'Agents' })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Leaderboard' })).toBeInTheDocument();
    });
  });

  describe('data fetching', () => {
    it('fetches agents and leaderboard on mount', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ agents: [], leaderboard: [] }),
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith('http://localhost:8080/api/introspection/agents');
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/introspection/leaderboard?limit=20',
        );
      });
    });

    it('displays agents when fetched successfully', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                agents: [
                  { name: 'claude', reputation_score: 0.85, total_critiques: 100 },
                  { name: 'gpt-4', reputation_score: 0.78, total_critiques: 80 },
                ],
              }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ leaderboard: [] }) });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
        expect(screen.getByText('gpt-4')).toBeInTheDocument();
      });
    });

    it('shows empty state when no agents', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ agents: [], leaderboard: [] }),
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByText('No agents found')).toBeInTheDocument();
      });
    });

    it('displays error when fetch fails', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByTestId('error-display')).toBeInTheDocument();
      });
    });

    it('displays error for non-ok response', async () => {
      mockFetch.mockResolvedValue({ ok: false, status: 500 });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByTestId('error-display')).toBeInTheDocument();
      });
    });
  });

  describe('agent list tab', () => {
    it('displays agent reputation scores', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                agents: [{ name: 'claude', reputation_score: 0.85, total_critiques: 100 }],
              }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ leaderboard: [] }) });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByText('85%')).toBeInTheDocument();
        expect(screen.getByText('100 critiques')).toBeInTheDocument();
      });
    });

    it('allows selecting an agent', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents/claude')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                agent_name: 'claude',
                strengths: ['Logical reasoning'],
                weaknesses: ['Verbose'],
                specializations: ['Code review'],
                recent_debates: [],
              }),
          });
        }
        if (url.includes('/agents')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ agents: [{ name: 'claude', reputation_score: 0.85 }] }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ leaderboard: [] }) });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('claude'));
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/introspection/agents/claude',
        );
      });
    });
  });

  describe('leaderboard tab', () => {
    it('switches to leaderboard tab', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ agents: [], leaderboard: [] }),
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Leaderboard' }));
      });

      expect(screen.getByText('Reputation Leaderboard')).toBeInTheDocument();
    });

    it('displays leaderboard entries', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValue({
        ok: true,
        json: () =>
          Promise.resolve({
            agents: [],
            leaderboard: [
              { agent_name: 'claude', reputation_score: 0.92, total_critiques: 150, rank: 1 },
              { agent_name: 'gpt-4', reputation_score: 0.88, total_critiques: 120, rank: 2 },
            ],
          }),
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Leaderboard' }));
      });

      expect(screen.getByText('#1')).toBeInTheDocument();
      expect(screen.getByText('#2')).toBeInTheDocument();
      expect(screen.getByText('92.0%')).toBeInTheDocument();
    });

    it('shows empty state when no leaderboard data', async () => {
      const user = userEvent.setup();
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ agents: [], leaderboard: [] }),
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Leaderboard' }));
      });

      expect(screen.getByText('No leaderboard data')).toBeInTheDocument();
    });

    it('allows clicking on leaderboard entry to view agent', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents/claude')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                agent_name: 'claude',
                strengths: [],
                weaknesses: [],
                specializations: [],
                recent_debates: [],
              }),
          });
        }
        return Promise.resolve({
          ok: true,
          json: () =>
            Promise.resolve({
              agents: [],
              leaderboard: [
                { agent_name: 'claude', reputation_score: 0.92, total_critiques: 150, rank: 1 },
              ],
            }),
        });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.queryByText('Loading...')).not.toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByRole('button', { name: 'Leaderboard' }));
      });

      const row = screen.getByText('claude').closest('tr');
      await act(async () => {
        await user.click(row!);
      });

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          'http://localhost:8080/api/introspection/agents/claude',
        );
      });
    });
  });

  describe('agent detail view', () => {
    it('displays agent details when selected', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents/claude') && !url.includes('?')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                agent_name: 'claude',
                reputation: {
                  score: 0.85,
                  total_critiques: 100,
                  win_rate: 0.72,
                  average_helpfulness: 0.88,
                },
                strengths: ['Logical reasoning', 'Clear explanations'],
                weaknesses: ['Sometimes verbose'],
                specializations: ['Code review', 'Documentation'],
                recent_debates: [],
              }),
          });
        }
        if (url.includes('/agents')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ agents: [{ name: 'claude', reputation_score: 0.85 }] }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ leaderboard: [] }) });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('claude'));
      });

      await waitFor(() => {
        expect(screen.getByText('Reputation')).toBeInTheDocument();
        expect(screen.getByText('Strengths')).toBeInTheDocument();
        expect(screen.getByText('Logical reasoning')).toBeInTheDocument();
        expect(screen.getByText('Weaknesses')).toBeInTheDocument();
        expect(screen.getByText('Sometimes verbose')).toBeInTheDocument();
      });
    });

    it('displays calibration data when available', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents/claude') && !url.includes('?')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                agent_name: 'claude',
                calibration: { confidence: 0.75, accuracy: 0.82, calibration_error: 0.07 },
                strengths: [],
                weaknesses: [],
                specializations: [],
                recent_debates: [],
              }),
          });
        }
        if (url.includes('/agents')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ agents: [{ name: 'claude' }] }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ leaderboard: [] }) });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('claude'));
      });

      await waitFor(() => {
        expect(screen.getByText('Calibration')).toBeInTheDocument();
        expect(screen.getByText('Confidence')).toBeInTheDocument();
        expect(screen.getByText('Accuracy')).toBeInTheDocument();
        expect(screen.getByText('Calibration Error')).toBeInTheDocument();
      });
    });

    it('displays recent debates when available', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents/claude') && !url.includes('?')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                agent_name: 'claude',
                strengths: [],
                weaknesses: [],
                specializations: [],
                recent_debates: [
                  {
                    debate_id: 'debate-123',
                    task: 'Code review for authentication module',
                    role: 'critic',
                    outcome: 'win',
                    timestamp: '2024-01-15T10:00:00Z',
                  },
                ],
              }),
          });
        }
        if (url.includes('/agents')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ agents: [{ name: 'claude' }] }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ leaderboard: [] }) });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('claude'));
      });

      await waitFor(() => {
        expect(screen.getByText('Recent Debates')).toBeInTheDocument();
        expect(screen.getByText('Code review for authentication module')).toBeInTheDocument();
        expect(screen.getByText('win')).toBeInTheDocument();
      });
    });

    it('shows back button that returns to agent list', async () => {
      const user = userEvent.setup();
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents/claude') && !url.includes('?')) {
          return Promise.resolve({
            ok: true,
            json: () =>
              Promise.resolve({
                agent_name: 'claude',
                strengths: [],
                weaknesses: [],
                specializations: [],
                recent_debates: [],
              }),
          });
        }
        if (url.includes('/agents')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ agents: [{ name: 'claude' }] }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ leaderboard: [] }) });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('claude'));
      });

      await waitFor(() => {
        expect(screen.getByText('Back to list')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByText('Back to list'));
      });

      expect(screen.getByText('Agent Registry')).toBeInTheDocument();
    });
  });

  describe('retry functionality', () => {
    it('retries loading data when retry button is clicked', async () => {
      const user = userEvent.setup();
      let callCount = 0;
      mockFetch.mockImplementation(() => {
        callCount++;
        if (callCount <= 2) {
          return Promise.reject(new Error('Network error'));
        }
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ agents: [], leaderboard: [] }),
        });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        expect(screen.getByTestId('error-display')).toBeInTheDocument();
      });

      await act(async () => {
        await user.click(screen.getByTestId('retry-button'));
      });

      await waitFor(() => {
        expect(screen.queryByTestId('error-display')).not.toBeInTheDocument();
      });
    });
  });

  describe('score color coding', () => {
    it('applies green color for high scores (>= 0.8)', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ agents: [{ name: 'claude', reputation_score: 0.85 }] }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ leaderboard: [] }) });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        const scoreElement = screen.getByText('85%');
        expect(scoreElement).toHaveClass('text-[var(--accent)]');
      });
    });

    it('applies yellow color for medium scores (0.6-0.8)', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/agents')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ agents: [{ name: 'claude', reputation_score: 0.7 }] }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ leaderboard: [] }) });
      });

      renderWithProviders(<IntrospectionPage />);

      await waitFor(() => {
        const scoreElement = screen.getByText('70%');
        expect(scoreElement).toHaveClass('text-yellow-400');
      });
    });
  });
});
