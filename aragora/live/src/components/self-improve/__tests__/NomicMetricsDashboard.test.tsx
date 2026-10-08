import React from 'react';
import { render, screen } from '@testing-library/react';
import { NomicMetricsDashboard } from '../NomicMetricsDashboard';
import { useSWRFetch } from '@/hooks/useSWRFetch';

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('@/components/nomic/HealthScoreGauge', () => ({
  HealthScoreGauge: ({ score, label }: { score: number; label: string }) => (
    <div data-testid="health-gauge">
      {label}:{score}
    </div>
  ),
}));

jest.mock('../RegressionGuard', () => ({
  RegressionGuard: () => <div>Regression Guard</div>,
}));

jest.mock('@/hooks/useSWRFetch', () => ({
  useSWRFetch: jest.fn(),
}));

const mockUseSWRFetch = useSWRFetch as jest.Mock;

type DashboardMockInput = {
  metrics: Record<string, unknown>;
  goals?: Record<string, unknown>[];
  runs?: Record<string, unknown>[];
};

function configureDashboardMocks({ metrics, goals = [], runs = [] }: DashboardMockInput) {
  mockUseSWRFetch.mockImplementation((url: string) => {
    if (url.includes('/api/self-improve/metrics/summary')) {
      return { data: { data: metrics }, isLoading: false };
    }
    if (url.includes('/api/self-improve/goals')) {
      return { data: { data: { goals, total: goals.length } }, isLoading: false };
    }
    if (url.includes('/api/self-improve/runs')) {
      return { data: { runs, total: runs.length }, isLoading: false };
    }
    return { data: null, isLoading: false };
  });
}

describe('NomicMetricsDashboard autopilot panel', () => {
  beforeEach(() => {
    mockUseSWRFetch.mockReset();
  });

  it('renders active autopilot worktree telemetry when available', () => {
    configureDashboardMocks({
      metrics: {
        health_score: 0.88,
        cycle_success_rate: 0.75,
        goal_completion_rate: 0.66,
        test_pass_rate: 0.92,
        total_cycles: 20,
        completed_cycles: 15,
        failed_cycles: 2,
        total_subtasks: 50,
        completed_subtasks: 33,
        total_goals_queued: 4,
        recent_activity: [],
        autopilot_worktrees: {
          ok: true,
          managed_dir: '.worktrees/codex-auto',
          sessions_total: 6,
          sessions_active: 2,
        },
      },
    });

    render(<NomicMetricsDashboard />);

    expect(screen.getByText('AUTOPILOT WORKTREES')).toBeInTheDocument();
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    expect(screen.getByText('.worktrees/codex-auto')).toBeInTheDocument();
    expect(screen.getByText('33% in use')).toBeInTheDocument();
    expect(screen.getByText('tracked by autopilot')).toBeInTheDocument();
  });

  it('renders degraded autopilot status when telemetry reports an error', () => {
    configureDashboardMocks({
      metrics: {
        health_score: 0.4,
        cycle_success_rate: 0.1,
        goal_completion_rate: 0.2,
        test_pass_rate: 0.5,
        total_cycles: 3,
        completed_cycles: 0,
        failed_cycles: 2,
        total_subtasks: 10,
        completed_subtasks: 1,
        total_goals_queued: 6,
        recent_activity: [],
        autopilot_worktrees: {
          ok: false,
          managed_dir: '.worktrees/codex-auto',
          sessions_total: 0,
          sessions_active: 0,
          error: 'autopilot_script_missing',
        },
      },
    });

    render(<NomicMetricsDashboard />);

    expect(screen.getByText('AUTOPILOT WORKTREES')).toBeInTheDocument();
    expect(screen.getByText('DEGRADED')).toBeInTheDocument();
    expect(screen.getByText('error: autopilot_script_missing')).toBeInTheDocument();
  });
});
