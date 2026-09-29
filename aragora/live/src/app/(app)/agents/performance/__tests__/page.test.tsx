import { render, screen } from '@testing-library/react';
import AgentPerformancePage from '../page';

// Mock MatrixRain (decorative, not testable)
jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));

// Mock PanelErrorBoundary to pass children through
jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

// Mock hooks
const mockAgents = [
  {
    id: 'agent-1',
    name: 'claude-opus',
    elo: 1650,
    eloHistory: [
      { date: '2026-01-01', elo: 1500 },
      { date: '2026-01-15', elo: 1600 },
      { date: '2026-02-01', elo: 1650 },
    ],
    calibration: 0.85,
    winRate: 0.72,
    domains: ['security', 'architecture', 'testing'],
  },
  {
    id: 'agent-2',
    name: 'gpt-4',
    elo: 1520,
    eloHistory: [
      { date: '2026-01-01', elo: 1550 },
      { date: '2026-02-01', elo: 1520 },
    ],
    calibration: 0.78,
    winRate: 0.55,
    domains: ['api-design', 'documentation'],
  },
];

jest.mock('@/hooks/useSystemIntelligence', () => ({
  useAgentPerformance: () => ({
    agents: mockAgents,
    isLoading: false,
    error: null,
    refresh: jest.fn(),
  }),
}));

jest.mock('@/hooks/useSWRFetch', () => ({
  useSWRFetch: () => ({
    data: {
      data: { total_debates: 42, consensus_rate: 0.78, avg_duration_ms: 5000, avg_rounds: 3 },
    },
    error: null,
    isLoading: false,
    isValidating: false,
    mutate: jest.fn(),
  }),
}));

describe('AgentPerformancePage', () => {
  it('renders the page heading', () => {
    render(<AgentPerformancePage />);
    expect(screen.getByText(/AGENT PERFORMANCE ANALYTICS/)).toBeInTheDocument();
  });

  it('renders agent names in the table', () => {
    render(<AgentPerformancePage />);
    expect(screen.getByText('claude-opus')).toBeInTheDocument();
    expect(screen.getByText('gpt-4')).toBeInTheDocument();
  });

  it('renders summary stat cards', () => {
    render(<AgentPerformancePage />);
    // 2 agents
    expect(screen.getByText('2')).toBeInTheDocument();
    // Average ELO (1650 + 1520) / 2 = 1585
    expect(screen.getByText('1585')).toBeInTheDocument();
    // Total debates from debate summary
    expect(screen.getByText('42')).toBeInTheDocument();
  });

  it('renders model comparison section', () => {
    render(<AgentPerformancePage />);
    expect(screen.getByText('Model Provider Comparison')).toBeInTheDocument();
  });

  it('renders domain heatmap section', () => {
    render(<AgentPerformancePage />);
    expect(screen.getByText('Domain Expertise')).toBeInTheDocument();
  });

  it('renders breadcrumb navigation', () => {
    render(<AgentPerformancePage />);
    // "Agents" link in breadcrumb (there may be multiple "Agents" text nodes)
    const breadcrumbLink = screen.getAllByText('Agents')[0];
    expect(breadcrumbLink).toBeInTheDocument();
    expect(screen.getByText('Performance')).toBeInTheDocument();
  });

  it('renders quick links footer', () => {
    render(<AgentPerformancePage />);
    expect(screen.getByText('Agent Leaderboard')).toBeInTheDocument();
    expect(screen.getByText('Calibration Details')).toBeInTheDocument();
    expect(screen.getByText('System Intelligence')).toBeInTheDocument();
  });

  it('renders domain filter dropdown', () => {
    render(<AgentPerformancePage />);
    expect(screen.getByText('All Domains')).toBeInTheDocument();
  });

  it('renders ELO sparklines as SVG elements', () => {
    const { container } = render(<AgentPerformancePage />);
    const svgs = container.querySelectorAll('svg');
    // Should have at least sparklines in the table rows
    expect(svgs.length).toBeGreaterThan(0);
  });
});
