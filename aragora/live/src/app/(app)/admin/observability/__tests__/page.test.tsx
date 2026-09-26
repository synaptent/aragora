import { render, screen, waitFor } from '@testing-library/react';
import ObservabilityPage from '../page';
import { useObservabilityDashboard } from '@/hooks/useObservabilityDashboard';

// Keep test focused on page data rendering.
jest.mock('@/components/admin/AdminLayout', () => ({
  AdminLayout: ({
    title,
    description,
    actions,
    children,
  }: {
    title: string;
    description?: string;
    actions?: React.ReactNode;
    children: React.ReactNode;
  }) => (
    <div>
      <h1>{title}</h1>
      {description && <p>{description}</p>}
      {actions}
      <div>{children}</div>
    </div>
  ),
}));

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://localhost:8080' } }),
}));
jest.mock('@/hooks/useObservabilityDashboard', () => ({ useObservabilityDashboard: jest.fn() }));

const mockUseObservabilityDashboard = useObservabilityDashboard as jest.MockedFunction<
  typeof useObservabilityDashboard
>;

function buildDashboardData(overrides?: Record<string, unknown>) {
  return {
    timestamp: Date.now() / 1000,
    collection_time_ms: 8.2,
    debate_metrics: {
      total_debates: 10,
      avg_duration_seconds: 31,
      consensus_rate: 0.6,
      available: true,
    },
    agent_rankings: { top_agents: [], available: true },
    circuit_breakers: { breakers: [], available: true },
    self_improve: { total_cycles: 2, successful: 2, failed: 0, recent_runs: [], available: true },
    oracle_stream: {
      sessions_started: 8,
      sessions_completed: 7,
      sessions_cancelled: 0,
      sessions_errors: 1,
      active_sessions: 2,
      stalls_waiting_first_token: 1,
      stalls_stream_inactive: 1,
      stalls_total: 2,
      ttft_samples: 7,
      ttft_avg_ms: 111.4,
      ttft_last_ms: 95.2,
      available: true,
    },
    settlement_review: {
      running: true,
      interval_hours: 6,
      max_receipts_per_run: 500,
      startup_delay_seconds: 60,
      stats: {
        total_runs: 3,
        total_receipts_scanned: 400,
        total_receipts_updated: 21,
        total_calibration_predictions: 15,
        failures: 0,
        success_rate: 0.85,
        last_run: '2026-02-25T20:00:00Z',
        last_result: {
          receipts_scanned: 120,
          receipts_due: 14,
          receipts_updated: 9,
          calibration_predictions_recorded: 6,
          unresolved_due: 5,
          started_at: '2026-02-25T19:59:30Z',
          completed_at: '2026-02-25T20:00:00Z',
          duration_seconds: 30,
          success: true,
          error: null,
        },
      },
      available: true,
    },
    system_health: { memory_percent: 40, cpu_percent: 8, pid: 12345, available: true },
    error_rates: { total_requests: 100, total_errors: 1, error_rate: 0.01, available: true },
    ...(overrides ?? {}),
  };
}

describe('Admin ObservabilityPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseObservabilityDashboard.mockReturnValue({
      dashboard: buildDashboardData(),
      isLoading: false,
      isValidating: false,
      error: null,
      mutate: jest.fn(),
      data: buildDashboardData(),
    });
  });

  it('renders settlement review and oracle metrics when available', async () => {
    render(<ObservabilityPage />);

    await screen.findByText('Every 6h');
    expect(screen.getByText('Settlement Review')).toBeInTheDocument();
    expect(screen.getByText('RUNNING')).toBeInTheDocument();
    expect(screen.getByText('85.0%')).toBeInTheDocument();
    expect(screen.getByText('Calibration Records')).toBeInTheDocument();

    expect(screen.getByText('Oracle Streaming')).toBeInTheDocument();
    expect(screen.getByText('Active Sessions')).toBeInTheDocument();
    expect(screen.getByText('111ms')).toBeInTheDocument();
  });

  it('shows unavailable messages when settlement and oracle telemetry are disabled', async () => {
    mockUseObservabilityDashboard.mockReturnValue({
      dashboard: buildDashboardData({
        settlement_review: {
          running: false,
          interval_hours: null,
          max_receipts_per_run: null,
          startup_delay_seconds: null,
          stats: null,
          available: false,
        },
        oracle_stream: {
          sessions_started: 0,
          sessions_completed: 0,
          sessions_cancelled: 0,
          sessions_errors: 0,
          active_sessions: 0,
          stalls_waiting_first_token: 0,
          stalls_stream_inactive: 0,
          stalls_total: 0,
          ttft_samples: 0,
          ttft_avg_ms: null,
          ttft_last_ms: null,
          available: false,
        },
      }),
      isLoading: false,
      isValidating: false,
      error: null,
      mutate: jest.fn(),
      data: buildDashboardData(),
    });

    render(<ObservabilityPage />);

    await waitFor(() =>
      expect(screen.getByText('Settlement review scheduler unavailable')).toBeInTheDocument(),
    );
    expect(screen.getByText('Oracle stream metrics unavailable')).toBeInTheDocument();
  });
});
