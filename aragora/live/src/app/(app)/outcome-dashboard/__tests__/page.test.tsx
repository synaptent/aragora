import { render, screen } from '@testing-library/react';
import OutcomeDashboardPage from '../page';

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

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

jest.mock('@/components/BackendSelector', () => ({
  BackendSelector: () => <div data-testid="backend-selector">Backend</div>,
  useBackend: () => ({ config: { api: 'http://localhost:8080' } }),
}));

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { panelName: string; children: React.ReactNode }) => (
    <div>{children}</div>
  ),
}));

jest.mock('@/hooks/useOutcomeAnalytics', () => ({
  useQualityScore: () => ({
    quality: {
      quality_score: 0.82,
      consensus_rate: 0.7,
      avg_rounds: 2.3,
      total_decisions: 12,
      completion_rate: 0.9,
    },
    isLoading: false,
  }),
  useOutcomeAgents: () => ({ leaderboard: { agents: [] }, isLoading: false }),
  useDecisionHistory: () => ({ history: { decisions: [] }, isLoading: false }),
  useCalibrationCurve: () => ({ calibration: { bins: [] }, isLoading: false }),
}));

jest.mock('@/hooks/useObservabilityDashboard', () => ({
  useSettlementOracleTelemetry: () => ({
    settlementReview: {
      running: true,
      interval_hours: 12,
      stats: { success_rate: 0.91, total_receipts_updated: 14 },
      available: true,
    },
    oracleStream: { active_sessions: 4, stalls_total: 2, ttft_avg_ms: 122.4, available: true },
    isLoading: false,
    error: null,
    mutate: jest.fn(),
  }),
}));

describe('OutcomeDashboardPage', () => {
  it('renders settlement/oracle operations health summary', () => {
    render(<OutcomeDashboardPage />);

    expect(screen.getByText('Settlement and Oracle Health')).toBeInTheDocument();
    expect(screen.getByText('Settlement Scheduler')).toBeInTheDocument();
    expect(screen.getByText('RUNNING')).toBeInTheDocument();
    expect(screen.getByText('Every 12h')).toBeInTheDocument();

    expect(screen.getByText('Settlement Success')).toBeInTheDocument();
    expect(screen.getByText('91.0%')).toBeInTheDocument();
    expect(screen.getByText('Updated 14')).toBeInTheDocument();

    expect(screen.getByText('Oracle Active Sessions')).toBeInTheDocument();
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('Stalls 2')).toBeInTheDocument();

    expect(screen.getByText('Oracle TTFT Avg')).toBeInTheDocument();
    expect(screen.getByText('122ms')).toBeInTheDocument();
  });
});
