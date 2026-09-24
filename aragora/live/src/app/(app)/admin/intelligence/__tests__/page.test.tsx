import { render, screen, fireEvent } from '@testing-library/react';
import IntelligencePage from '../page';

// Mock hooks
jest.mock('@/hooks/useSystemIntelligence', () => ({
  useSystemIntelligence: () => ({
    overview: {
      totalCycles: 15,
      successRate: 0.87,
      activeAgents: 8,
      knowledgeItems: 1200,
      topAgents: [
        { id: 'claude-opus', elo: 1650, wins: 30 },
        { id: 'gpt-4', elo: 1520, wins: 22 },
      ],
      recentImprovements: [{ id: 'imp-1', goal: 'Improve test coverage', status: 'completed' }],
    },
    isLoading: false,
    error: null,
    refresh: jest.fn(),
  }),
  useAgentPerformance: () => ({
    agents: [
      {
        id: 'agent-1',
        name: 'claude-opus',
        elo: 1650,
        eloHistory: [
          { date: '2026-01-01', elo: 1500 },
          { date: '2026-02-01', elo: 1650 },
        ],
        calibration: 0.85,
        winRate: 0.72,
        domains: ['security'],
      },
    ],
    isLoading: false,
    error: null,
    refresh: jest.fn(),
  }),
  useInstitutionalMemory: () => ({
    memory: {
      totalInjections: 50,
      retrievalCount: 200,
      topPatterns: [{ pattern: 'debate-consensus', frequency: 15, confidence: 0.9 }],
      confidenceChanges: [{ topic: 'architecture', before: 0.7, after: 0.85 }],
    },
    isLoading: false,
    error: null,
    refresh: jest.fn(),
  }),
  useImprovementQueue: () => ({
    queue: { items: [], totalSize: 0, sourceBreakdown: {} },
    items: [],
    isLoading: false,
    error: null,
    refresh: jest.fn(),
    addGoal: jest.fn(),
    reorderItem: jest.fn(),
    removeItem: jest.fn(),
  }),
}));

describe('Admin IntelligencePage', () => {
  it('renders the page heading', () => {
    render(<IntelligencePage />);
    expect(screen.getByText('System Intelligence')).toBeInTheDocument();
  });

  it('renders all four tab buttons', () => {
    render(<IntelligencePage />);
    expect(screen.getByText('Learning Insights')).toBeInTheDocument();
    expect(screen.getByText('Agent Performance')).toBeInTheDocument();
    expect(screen.getByText('Institutional Memory')).toBeInTheDocument();
    expect(screen.getByText('Improvement Queue')).toBeInTheDocument();
  });

  it('shows learning insights by default', () => {
    render(<IntelligencePage />);
    expect(screen.getByText('Total Cycles')).toBeInTheDocument();
    expect(screen.getByText('15')).toBeInTheDocument();
  });

  it('switches to agent performance tab', () => {
    render(<IntelligencePage />);
    fireEvent.click(screen.getByText('Agent Performance'));
    expect(screen.getByText('Agent Details')).toBeInTheDocument();
    // claude-opus appears in both learning tab (topAgents) and agent tab, use getAllByText
    expect(screen.getAllByText('claude-opus').length).toBeGreaterThan(0);
  });

  it('switches to institutional memory tab', () => {
    render(<IntelligencePage />);
    fireEvent.click(screen.getByText('Institutional Memory'));
    expect(screen.getByText('Total Injections')).toBeInTheDocument();
    expect(screen.getByText('Top Patterns')).toBeInTheDocument();
  });

  it('switches to improvement queue tab', () => {
    render(<IntelligencePage />);
    fireEvent.click(screen.getByText('Improvement Queue'));
    expect(screen.getByText('Submit Improvement Goal')).toBeInTheDocument();
  });

  it('renders ELO sparklines as SVG in agent tab', () => {
    const { container } = render(<IntelligencePage />);
    fireEvent.click(screen.getByText('Agent Performance'));
    const svgs = container.querySelectorAll('svg');
    expect(svgs.length).toBeGreaterThan(0);
  });
});
