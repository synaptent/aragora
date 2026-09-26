/**
 * Tests for MemoryAnalyticsPanel component
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryAnalyticsPanel } from '../src/components/MemoryAnalyticsPanel';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockAnalyticsData = {
  summary: {
    total_memories: 1250,
    active_memories: 890,
    tier_distribution: { fast: 150, medium: 400, slow: 500, glacial: 200 },
  },
  promotions: { fast_to_medium: 45, medium_to_slow: 30, slow_to_glacial: 15, promotion_rate: 0.72 },
  learning_velocity: { current: 3.5, trend: 'increasing', percentile_7d: 85 },
  retrieval_stats: {
    avg_latency_ms: 12.5,
    hit_rate: 0.92,
    most_retrieved_topics: ['ethics', 'technology', 'climate', 'economics', 'healthcare'],
  },
  recommendations: [
    {
      type: 'optimization',
      message: 'Consider promoting high-access slow tier memories',
      priority: 'medium',
    },
    { type: 'cleanup', message: 'Archive 50 low-access glacial memories', priority: 'low' },
  ],
};

describe('MemoryAnalyticsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('shows a loading indicator while fetching', () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));

    render(<MemoryAnalyticsPanel />);

    expect(screen.getByText('MEMORY ANALYTICS')).toBeInTheDocument();
    expect(screen.getByText('...')).toBeInTheDocument();
  });

  it('displays an error message when fetch fails', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 500 });

    render(<MemoryAnalyticsPanel />);

    await waitFor(() => {
      expect(screen.getByText(/failed to fetch memory analytics/i)).toBeInTheDocument();
    });
  });

  it('shows empty state for 503 response', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 503 });

    render(<MemoryAnalyticsPanel />);

    await waitFor(() => {
      expect(screen.getByText(/memory analytics not available/i)).toBeInTheDocument();
    });
  });

  it('renders header badge and icon', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockAnalyticsData) });

    render(<MemoryAnalyticsPanel />);

    await waitFor(() => {
      expect(screen.getByText('MEMORY ANALYTICS')).toBeInTheDocument();
      expect(screen.getByText('1,250')).toBeInTheDocument();
      expect(screen.getByText('🧠')).toBeInTheDocument();
    });
  });

  it('renders tier distribution and key metrics', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockAnalyticsData) });

    render(<MemoryAnalyticsPanel />);

    await waitFor(() => {
      expect(screen.getByText('TIER DISTRIBUTION')).toBeInTheDocument();
    });

    expect(screen.getByText('fast:')).toBeInTheDocument();
    expect(screen.getByText('medium:')).toBeInTheDocument();
    expect(screen.getByText('slow:')).toBeInTheDocument();
    expect(screen.getByText('glacial:')).toBeInTheDocument();

    expect(screen.getByText('72.0%')).toBeInTheDocument();
    expect(screen.getByText('Promotion Rate')).toBeInTheDocument();
    expect(screen.getByText('3.5')).toBeInTheDocument();
    expect(screen.getByText('📈')).toBeInTheDocument();
  });

  it('renders retrieval stats and topics', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockAnalyticsData) });

    render(<MemoryAnalyticsPanel />);

    await waitFor(() => {
      expect(screen.getByText('RETRIEVAL PERFORMANCE')).toBeInTheDocument();
    });

    expect(screen.getByText('92%')).toBeInTheDocument();
    expect(screen.getByText('12.5ms avg')).toBeInTheDocument();
    expect(screen.getByText('ethics')).toBeInTheDocument();
    expect(screen.getByText('technology')).toBeInTheDocument();
  });

  it('limits displayed recommendations to 3', async () => {
    const manyRecommendations = [
      { type: 'a', message: 'Recommendation 1', priority: 'high' as const },
      { type: 'b', message: 'Recommendation 2', priority: 'medium' as const },
      { type: 'c', message: 'Recommendation 3', priority: 'low' as const },
      { type: 'd', message: 'Recommendation 4', priority: 'low' as const },
    ];

    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({ ...mockAnalyticsData, recommendations: manyRecommendations }),
    });

    render(<MemoryAnalyticsPanel />);

    await waitFor(() => {
      expect(screen.getByText('RECOMMENDATIONS')).toBeInTheDocument();
    });

    expect(screen.getByText('Recommendation 1')).toBeInTheDocument();
    expect(screen.getByText('Recommendation 2')).toBeInTheDocument();
    expect(screen.getByText('Recommendation 3')).toBeInTheDocument();
    expect(screen.queryByText('Recommendation 4')).not.toBeInTheDocument();
  });

  it('shows the summary footer', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockAnalyticsData) });

    render(<MemoryAnalyticsPanel />);

    await waitFor(() => {
      expect(screen.getByText('890 active')).toBeInTheDocument();
      expect(screen.getByText('30-day analysis')).toBeInTheDocument();
    });
  });

  it('refetches data when refresh is clicked', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockAnalyticsData) });

    render(<MemoryAnalyticsPanel />);

    await waitFor(() => {
      expect(screen.getByText('TIER DISTRIBUTION')).toBeInTheDocument();
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

  it('uses custom API base when provided', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockAnalyticsData) });

    render(<MemoryAnalyticsPanel apiBase="https://custom-api.example.com" />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('https://custom-api.example.com/api/memory/analytics?days=30'),
      );
    });
  });
});
