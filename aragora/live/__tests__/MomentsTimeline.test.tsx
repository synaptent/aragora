/**
 * Tests for MomentsTimeline component
 */

import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { MomentsTimeline } from '../src/components/MomentsTimeline';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockSummaryData = {
  total_moments: 15,
  by_type: {
    upset_victory: 5,
    consensus_breakthrough: 4,
    position_reversal: 3,
    streak_achievement: 3,
  },
  by_agent: { 'claude-3-opus': 6, 'gpt-4o': 5, 'gemini-pro': 4 },
  most_significant: {
    id: 'moment-1',
    type: 'upset_victory',
    agent: 'claude-3-opus',
    description: 'Won against heavily favored opponent in ethics debate',
    significance: 0.95,
    created_at: '2026-01-10T10:00:00Z',
  },
  recent: [
    {
      id: 'moment-1',
      type: 'upset_victory',
      agent: 'claude-3-opus',
      description: 'Won against heavily favored opponent',
      significance: 0.95,
      created_at: '2026-01-10T10:00:00Z',
    },
    {
      id: 'moment-2',
      type: 'consensus_breakthrough',
      agent: 'gpt-4o',
      description: 'First to propose winning consensus',
      significance: 0.85,
      created_at: '2026-01-10T09:00:00Z',
    },
    {
      id: 'moment-3',
      type: 'position_reversal',
      agent: 'gemini-pro',
      description: 'Changed stance based on new evidence',
      significance: 0.7,
      created_at: '2026-01-10T08:00:00Z',
    },
  ],
};

describe('MomentsTimeline', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('shows a loading indicator while fetching', () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));

    render(<MomentsTimeline />);

    expect(screen.getByText('MOMENTS')).toBeInTheDocument();
    expect(screen.getByText('...')).toBeInTheDocument();
  });

  it('displays an error message when fetch fails', async () => {
    mockFetch.mockRejectedValue(new Error('Network error'));

    render(<MomentsTimeline />);

    await waitFor(() => {
      expect(screen.getByText('Network error')).toBeInTheDocument();
    });
  });

  it('shows empty state when no moments exist', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ total_moments: 0, by_type: {}, by_agent: {}, recent: [] }),
    });

    render(<MomentsTimeline />);

    await waitFor(() => {
      expect(screen.getByText(/no significant moments recorded yet/i)).toBeInTheDocument();
    });
  });

  it('handles 503 responses as empty state', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 503 });

    render(<MomentsTimeline />);

    await waitFor(() => {
      expect(screen.getByText(/no significant moments recorded yet/i)).toBeInTheDocument();
    });
  });

  it('renders highlight and recent moments', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockSummaryData) });

    render(<MomentsTimeline />);

    await waitFor(() => {
      expect(screen.getByText('MOMENTS')).toBeInTheDocument();
      expect(screen.getByText('15')).toBeInTheDocument();
    });

    expect(screen.getByText('HIGHLIGHT')).toBeInTheDocument();
    const highlight = screen.getByTestId('moments-highlight');
    expect(within(highlight).getByText('Upset Victory')).toBeInTheDocument();
    expect(within(highlight).getByText('95%')).toBeInTheDocument();
    expect(within(highlight).getByText('claude-3-opus')).toBeInTheDocument();

    const recentList = screen.getByTestId('moments-recent-list');
    expect(within(recentList).getByText('gpt-4o')).toBeInTheDocument();
    expect(within(recentList).getByText('gemini-pro')).toBeInTheDocument();
  });

  it('filters moments by type and clears the filter', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockSummaryData) });

    render(<MomentsTimeline />);

    await waitFor(() => {
      expect(screen.getByText('All')).toBeInTheDocument();
    });

    const upsetButton = screen
      .getAllByRole('button')
      .find((btn) => btn.textContent?.includes('🏆'));
    if (upsetButton) {
      fireEvent.click(upsetButton);

      await waitFor(() => {
        expect(screen.getByText('Upset Victory')).toBeInTheDocument();
      });

      fireEvent.click(upsetButton);

      await waitFor(() => {
        expect(screen.getByText('RECENT')).toBeInTheDocument();
      });
    }
  });

  it('shows agent distribution chips', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockSummaryData) });

    render(<MomentsTimeline />);

    await waitFor(() => {
      expect(screen.getByText('BY AGENT')).toBeInTheDocument();
    });

    const distribution = screen.getByTestId('moments-agent-distribution');
    expect(within(distribution).getByText('claude-3-opus')).toBeInTheDocument();
    expect(within(distribution).getByText('(6)')).toBeInTheDocument();
  });

  it('refetches data when refresh is clicked', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockSummaryData) });

    render(<MomentsTimeline />);

    await waitFor(() => {
      expect(screen.getByText('HIGHLIGHT')).toBeInTheDocument();
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);

    await waitFor(() => {
      expect(screen.getByRole('button', { name: '↻' })).toBeEnabled();
    });

    fireEvent.click(screen.getByRole('button', { name: '↻' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });
});
