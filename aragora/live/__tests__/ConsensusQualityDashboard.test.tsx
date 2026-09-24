/**
 * Tests for ConsensusQualityDashboard component
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ConsensusQualityDashboard } from '../src/components/ConsensusQualityDashboard';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockQualityData = {
  stats: {
    total_debates: 50,
    confidence_history: [
      {
        debate_id: 'd1',
        confidence: 0.85,
        consensus_reached: true,
        timestamp: '2026-01-10T10:00:00Z',
      },
      {
        debate_id: 'd2',
        confidence: 0.72,
        consensus_reached: true,
        timestamp: '2026-01-10T09:00:00Z',
      },
      {
        debate_id: 'd3',
        confidence: 0.45,
        consensus_reached: false,
        timestamp: '2026-01-10T08:00:00Z',
      },
    ],
    trend: 'improving',
    average_confidence: 0.78,
    consensus_rate: 0.84,
    consensus_reached_count: 42,
  },
  quality_score: 82,
  alert: null,
};

const mockQualityDataWithAlert = {
  ...mockQualityData,
  quality_score: 35,
  alert: { level: 'warning', message: 'Consensus rate declining over the past week' },
};

describe('ConsensusQualityDashboard', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('shows a loading indicator while fetching', () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));

    render(<ConsensusQualityDashboard />);

    expect(screen.getByText('CONSENSUS QUALITY')).toBeInTheDocument();
    expect(screen.getByText('...')).toBeInTheDocument();
  });

  it('displays an error message for failed responses', async () => {
    mockFetch.mockResolvedValue({ ok: false, status: 500 });

    render(<ConsensusQualityDashboard />);

    await waitFor(() => {
      expect(screen.getByText(/failed to fetch consensus quality/i)).toBeInTheDocument();
    });
  });

  it('shows empty state when no debates exist', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () =>
        Promise.resolve({
          stats: {
            total_debates: 0,
            confidence_history: [],
            trend: 'insufficient_data',
            average_confidence: 0,
            consensus_rate: 0,
            consensus_reached_count: 0,
          },
          quality_score: 0,
          alert: null,
        }),
    });

    render(<ConsensusQualityDashboard />);

    await waitFor(() => {
      expect(screen.getByText(/no debate data available yet/i)).toBeInTheDocument();
    });
  });

  it('renders quality score and key metrics', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockQualityData) });

    render(<ConsensusQualityDashboard />);

    await waitFor(() => {
      expect(screen.getByText('82')).toBeInTheDocument();
      expect(screen.getByText('Quality Score')).toBeInTheDocument();
    });

    expect(screen.getByText('84%')).toBeInTheDocument();
    expect(screen.getByText('78%')).toBeInTheDocument();
    expect(screen.getByText(/improving/i)).toBeInTheDocument();

    expect(screen.getByText('CONFIDENCE HISTORY')).toBeInTheDocument();
    expect(screen.getByText('Older')).toBeInTheDocument();
    expect(screen.getByText('Recent')).toBeInTheDocument();

    expect(screen.getByText('50 total debates')).toBeInTheDocument();
    expect(screen.getByText('42 reached consensus')).toBeInTheDocument();
  });

  it('applies green color for high quality scores', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockQualityData) });

    render(<ConsensusQualityDashboard />);

    await waitFor(() => {
      const scoreElement = screen.getByText('82');
      expect(scoreElement).toHaveClass('text-green-400');
    });
  });

  it('shows alert banner when provided', async () => {
    mockFetch.mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockQualityDataWithAlert),
    });

    render(<ConsensusQualityDashboard />);

    await waitFor(() => {
      expect(screen.getByText('⚠️')).toBeInTheDocument();
      expect(screen.getByText('Consensus rate declining over the past week')).toBeInTheDocument();
    });
  });

  it('refetches data when refresh is clicked', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve(mockQualityData) });

    render(<ConsensusQualityDashboard />);

    await waitFor(() => {
      expect(screen.getByText('82')).toBeInTheDocument();
    });

    expect(mockFetch).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole('button', { name: '↻' }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledTimes(2);
    });
  });
});
