import { render, screen, waitFor } from '@testing-library/react';
import SettlementsPage from '../page';
import { apiFetch } from '@/lib/api';
import { useSettlementOracleTelemetry } from '@/hooks/useObservabilityDashboard';

jest.mock('@/lib/api', () => ({ apiFetch: jest.fn() }));
jest.mock('@/hooks/useObservabilityDashboard', () => ({ useSettlementOracleTelemetry: jest.fn() }));

const mockApiFetch = apiFetch as jest.MockedFunction<typeof apiFetch>;
const mockUseSettlementOracleTelemetry = useSettlementOracleTelemetry as jest.MockedFunction<
  typeof useSettlementOracleTelemetry
>;

describe('SettlementsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it('renders settlement and oracle telemetry strip when observability data is available', async () => {
    mockApiFetch.mockImplementation(async (path: string) => {
      if (path === '/api/v1/settlements') {
        return { settlements: [] };
      }
      throw new Error(`Unexpected path: ${path}`);
    });
    mockUseSettlementOracleTelemetry.mockReturnValue({
      settlementReview: {
        running: true,
        interval_hours: 6,
        max_receipts_per_run: 500,
        startup_delay_seconds: 60,
        available: true,
        stats: {
          total_runs: 3,
          total_receipts_scanned: 0,
          total_receipts_updated: 11,
          total_calibration_predictions: 0,
          failures: 0,
          success_rate: 0.875,
          last_run: null,
          last_result: {
            receipts_scanned: 0,
            receipts_due: 0,
            receipts_updated: 0,
            calibration_predictions_recorded: 0,
            unresolved_due: 2,
            started_at: '',
            completed_at: '',
            duration_seconds: 0,
            success: true,
            error: null,
          },
        },
      },
      oracleStream: {
        sessions_started: 0,
        sessions_completed: 0,
        sessions_cancelled: 0,
        sessions_errors: 0,
        active_sessions: 3,
        stalls_waiting_first_token: 0,
        stalls_stream_inactive: 0,
        stalls_total: 1,
        ttft_samples: 0,
        ttft_avg_ms: 112.4,
        ttft_last_ms: null,
        available: true,
      },
      isLoading: false,
      isValidating: false,
      error: null,
      data: null,
      mutate: jest.fn(),
    });

    render(<SettlementsPage />);

    await waitFor(() => {
      expect(screen.getByText('Scheduler: RUNNING')).toBeInTheDocument();
    });

    expect(screen.getByText('Interval: 6h')).toBeInTheDocument();
    expect(screen.getByText('Success: 87.5%')).toBeInTheDocument();
    expect(screen.getByText('Updated: 11 | Unresolved: 2')).toBeInTheDocument();
    expect(screen.getByText('Active: 3 | Stalls: 1')).toBeInTheDocument();
    expect(screen.getByText('TTFT: 112ms')).toBeInTheDocument();
  });

  it('shows fallback telemetry messages when observability endpoint fails', async () => {
    mockApiFetch.mockImplementation(async (path: string) => {
      if (path === '/api/v1/settlements') {
        return { settlements: [] };
      }
      throw new Error(`Unexpected path: ${path}`);
    });
    mockUseSettlementOracleTelemetry.mockReturnValue({
      settlementReview: null,
      oracleStream: null,
      isLoading: false,
      isValidating: false,
      error: null,
      data: null,
      mutate: jest.fn(),
    });

    render(<SettlementsPage />);

    await waitFor(() => {
      expect(screen.getByText('Ops telemetry unavailable')).toBeInTheDocument();
    });

    expect(screen.getByText('No settlement rollup')).toBeInTheDocument();
    expect(screen.getByText('No oracle stream telemetry')).toBeInTheDocument();
  });
});
