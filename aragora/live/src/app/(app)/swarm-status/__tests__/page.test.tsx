import { render, screen } from '@testing-library/react';
import { useSWRFetch } from '@/hooks/useSWRFetch';

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

jest.mock('@/components/AsciiBanner', () => ({
  AsciiBannerCompact: () => <div data-testid="ascii-banner">ARAGORA</div>,
}));

jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

jest.mock('@/components/ThemeToggle', () => ({
  ThemeToggle: () => <button type="button">Theme</button>,
}));

jest.mock('@/components/BackendSelector', () => ({
  BackendSelector: () => <div data-testid="backend-selector" />,
  useBackend: () => ({ config: { api: 'http://localhost:8080' } }),
}));

jest.mock('@/components/ErrorWithRetry', () => ({
  ErrorWithRetry: ({ error, onRetry }: { error: string; onRetry: () => void }) => (
    <button type="button" onClick={onRetry}>
      {error}
    </button>
  ),
}));

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('@/hooks/useSWRFetch', () => ({ useSWRFetch: jest.fn() }));

const mockUseSWRFetch = useSWRFetch as jest.Mock;
const SwarmStatusPage = require('../page').default;

describe('SwarmStatusPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders swarm metrics and blocker rows from the status endpoint', async () => {
    mockUseSWRFetch.mockReturnValue({
      data: {
        status: 'active',
        metrics_path: '.aragora/overnight/boss_metrics.jsonl',
        window: 50,
        total_ticks: 12,
        unique_issues_attempted: 10,
        unique_issues_succeeded: 8,
        success_rate: 0.8,
        tick_success_rate: 0.75,
        terminal_class_distribution: { success_pr_created: 8, blocked_auth_failure: 2 },
        failure_reason_distribution: { missing_contract_slice: 2 },
        rescue_class_summary: { rescue_timeout: 1 },
        recent_blockers: [
          {
            issue_number: 123,
            terminal_class: 'blocked_auth_failure',
            failure_reason: 'missing_contract_slice',
            blocker_kind: 'auth',
            blocker_evidence: 'validation_contract missing for dispatch_ready gate',
            issue_title: 'Persist missing credential envelope',
          },
        ],
        latest_tick: {
          timestamp: '2026-04-14T15:00:00Z',
          issue_number: 123,
          terminal_class: 'blocked_auth_failure',
          elapsed_seconds: 31,
        },
      },
      error: null,
      isLoading: false,
      mutate: jest.fn(),
    });

    render(<SwarmStatusPage />);

    expect(screen.getByRole('heading', { name: 'Swarm Status' })).toBeInTheDocument();
    expect(screen.getByText('80.0%')).toBeInTheDocument();
    expect(screen.getByText('75.0%')).toBeInTheDocument();
    expect(screen.getByText('Persist missing credential envelope')).toBeInTheDocument();
    expect(
      screen.getByText('validation_contract missing for dispatch_ready gate'),
    ).toBeInTheDocument();
    expect(screen.getAllByText('missing_contract_slice')).toHaveLength(2);
    expect(screen.getAllByText('blocked_auth_failure')).toHaveLength(3);
    expect(screen.getByText('rescue_timeout')).toBeInTheDocument();
  });

  it('renders the error state through ErrorWithRetry when the fetch fails', () => {
    mockUseSWRFetch.mockReturnValue({
      data: null,
      error: new Error('swarm endpoint unavailable'),
      isLoading: false,
      mutate: jest.fn(),
    });

    render(<SwarmStatusPage />);

    expect(screen.getByRole('button', { name: 'swarm endpoint unavailable' })).toBeInTheDocument();
  });

  it('renders the no-data placeholder when the endpoint has no metrics yet', () => {
    mockUseSWRFetch.mockReturnValue({
      data: {
        status: 'no_data',
        metrics_path: '.aragora/overnight/boss_metrics.jsonl',
        window: 50,
        total_ticks: 0,
      },
      error: null,
      isLoading: false,
      mutate: jest.fn(),
    });

    render(<SwarmStatusPage />);

    expect(screen.getByText('NO DATA')).toBeInTheDocument();
    expect(
      screen.getByText('No blockers recorded in the current metrics window.'),
    ).toBeInTheDocument();
    expect(screen.getByText('No latest tick metadata available yet.')).toBeInTheDocument();
  });
});
