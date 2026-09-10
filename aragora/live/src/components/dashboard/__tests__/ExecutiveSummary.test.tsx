import { render, screen } from '@testing-library/react';

import { ExecutiveSummary } from '../ExecutiveSummary';

const mockUseSWRFetch = jest.fn();
const mockUseUsageDashboard = jest.fn();

jest.mock('@/hooks/useSWRFetch', () => ({
  useSWRFetch: (...args: unknown[]) => mockUseSWRFetch(...args),
}));

jest.mock('@/hooks/useUsageDashboard', () => ({
  useUsageDashboard: (...args: unknown[]) => mockUseUsageDashboard(...args),
}));

describe('ExecutiveSummary', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUseUsageDashboard.mockReturnValue({
      roi: null,
      budget: null,
      forecast: null,
      isLoading: false,
      error: null,
    });
  });

  it('shows the requested executive dashboard metrics from the usage summary payload', () => {
    mockUseSWRFetch.mockReturnValue({
      data: {
        data: {
          period: {
            type: 'month',
            start: '2026-03-01T00:00:00Z',
            end: '2026-03-31T12:34:56Z',
            days: 30,
          },
          debates: { total: 42, completed: 39, consensus_rate: 88.5 },
          costs: { total_usd: '123.45', avg_per_debate_usd: '2.94', by_provider: {} },
          quality: { avg_confidence: 0.83 },
          agents: {
            top_agents: [
              {
                agent_id: 'claude',
                agent_name: 'Claude',
                participations: 12,
                consensus_contributions: 11,
                consensus_rate: '92%',
                avg_agreement_score: 0.92,
              },
              {
                agent_id: 'gpt-4',
                agent_name: 'GPT-4',
                participations: 10,
                consensus_contributions: 8,
                consensus_rate: '80%',
                avg_agreement_score: 0.8,
              },
              {
                agent_id: 'gemini',
                agent_name: 'Gemini',
                participations: 8,
                consensus_contributions: 6,
                consensus_rate: '75%',
                avg_agreement_score: 0.75,
              },
            ],
          },
        },
      },
      isLoading: false,
      error: null,
    });

    render(<ExecutiveSummary />);

    expect(screen.getByText('Total Debates')).toBeInTheDocument();
    expect(screen.getByText('42')).toBeInTheDocument();
    expect(screen.getByText('39 completed')).toBeInTheDocument();

    expect(screen.getByText('Avg Confidence')).toBeInTheDocument();
    expect(screen.getByText('83%')).toBeInTheDocument();
    expect(screen.getByText('88.5% consensus rate')).toBeInTheDocument();

    expect(screen.getByText('Top Agents')).toBeInTheDocument();
    expect(screen.getByText('3 ranked')).toBeInTheDocument();
    expect(screen.getByText('Claude, GPT-4, Gemini')).toBeInTheDocument();

    expect(screen.getByText('Total Spend')).toBeInTheDocument();
    expect(screen.getByText('$123.45')).toBeInTheDocument();
    expect(screen.getByText('$2.94 per debate')).toBeInTheDocument();

    expect(screen.getByText('#1 Agent')).toBeInTheDocument();
    expect(screen.getByText('#2 Agent')).toBeInTheDocument();
    expect(screen.getByText('#3 Agent')).toBeInTheDocument();
  });
});
