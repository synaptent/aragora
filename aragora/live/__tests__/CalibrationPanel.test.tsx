/**
 * Tests for CalibrationPanel component
 *
 * Tests cover:
 * - Loading and error states
 * - Agent leaderboard display
 * - Agent selection and detail view
 * - Expand/collapse functionality
 * - Empty state handling
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { CalibrationPanel } from '../src/components/CalibrationPanel';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

const mockLeaderboardData = {
  agents: [
    {
      name: 'claude-3-opus',
      elo: 1650,
      calibration_score: 0.85,
      brier_score: 0.12,
      accuracy: 0.78,
      games: 25,
    },
    {
      name: 'gemini-2.0-flash',
      elo: 1580,
      calibration_score: 0.72,
      brier_score: 0.18,
      accuracy: 0.72,
      games: 22,
    },
    {
      name: 'grok-2',
      elo: 1520,
      calibration_score: 0.55,
      brier_score: 0.28,
      accuracy: 0.65,
      games: 18,
    },
  ],
};

const mockAgentCalibration = {
  agent: 'claude-3-opus',
  ece: 0.08,
  buckets: [
    { bucket: '0.0-0.2', predicted: 0.1, actual: 0.12, count: 5 },
    { bucket: '0.2-0.4', predicted: 0.3, actual: 0.28, count: 8 },
    { bucket: '0.4-0.6', predicted: 0.5, actual: 0.52, count: 12 },
    { bucket: '0.6-0.8', predicted: 0.7, actual: 0.68, count: 15 },
    { bucket: '0.8-1.0', predicted: 0.9, actual: 0.88, count: 10 },
  ],
  domain_calibration: { technology: 0.88, philosophy: 0.82, science: 0.79 },
};

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/api/calibration/leaderboard')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockLeaderboardData) });
    }
    if (url.includes('/api/agent/') && url.includes('/calibration')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockAgentCalibration) });
    }
    return Promise.resolve({ ok: false });
  });
}

describe('CalibrationPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Loading States', () => {
    it('shows loading state while fetching data', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {}));
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });
      expect(screen.getByText('Loading calibration data...')).toBeInTheDocument();
    });

    it('shows panel header', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {}));
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });
      expect(screen.getByText('[CALIBRATION]')).toBeInTheDocument();
      expect(screen.getByText('Confidence accuracy scores')).toBeInTheDocument();
    });
  });

  describe('Data Display', () => {
    it('renders agent leaderboard after data loads', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      expect(screen.getByText('gemini-2.0-flash')).toBeInTheDocument();
      expect(screen.getByText('grok-2')).toBeInTheDocument();
    });

    it('displays calibration scores as percentages', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('85%')).toBeInTheDocument(); // claude calibration
      });

      expect(screen.getByText('72%')).toBeInTheDocument(); // gemini calibration
      expect(screen.getByText('55%')).toBeInTheDocument(); // grok calibration
    });

    it('displays brier scores', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('0.120')).toBeInTheDocument(); // claude brier
      });
    });

    it('displays game counts', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('25 games')).toBeInTheDocument();
      });
    });

    it('shows ranking numbers', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('#1')).toBeInTheDocument();
        expect(screen.getByText('#2')).toBeInTheDocument();
        expect(screen.getByText('#3')).toBeInTheDocument();
      });
    });
  });

  describe('Agent Selection', () => {
    it('shows agent detail when agent is clicked', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      // Click on the agent
      await act(async () => {
        fireEvent.click(screen.getByText('claude-3-opus'));
      });

      await waitFor(() => {
        // Should show ECE score
        expect(screen.getByText('0.080')).toBeInTheDocument();
      });
    });

    it('shows calibration buckets in detail view', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(screen.getByText('claude-3-opus'));
      });

      await waitFor(() => {
        expect(screen.getByText('Calibration by confidence:')).toBeInTheDocument();
        expect(screen.getByText('0.0-0.2')).toBeInTheDocument();
        expect(screen.getByText('0.8-1.0')).toBeInTheDocument();
      });
    });

    it('shows domain calibration in detail view', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      await act(async () => {
        fireEvent.click(screen.getByText('claude-3-opus'));
      });

      await waitFor(() => {
        expect(screen.getByText('By domain:')).toBeInTheDocument();
        expect(screen.getByText('technology: 88%')).toBeInTheDocument();
        expect(screen.getByText('philosophy: 82%')).toBeInTheDocument();
      });
    });

    it('deselects agent when clicked again', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      // Select agent
      await act(async () => {
        fireEvent.click(screen.getByText('claude-3-opus'));
      });

      await waitFor(() => {
        expect(screen.getByText('Calibration by confidence:')).toBeInTheDocument();
      });

      // Deselect by clicking again (there are now two claude-3-opus elements, click the first one in the list)
      const agentElements = screen.getAllByText('claude-3-opus');
      await act(async () => {
        fireEvent.click(agentElements[0]);
      });

      await waitFor(() => {
        expect(screen.queryByText('Calibration by confidence:')).not.toBeInTheDocument();
      });
    });
  });

  describe('Expand/Collapse', () => {
    it('is expanded by default', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      // Should show collapse indicator
      expect(screen.getByText('[-]')).toBeInTheDocument();
    });

    it('collapses when header is clicked', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      // Click header to collapse
      await act(async () => {
        fireEvent.click(screen.getByText('[CALIBRATION]'));
      });

      // Should show expand indicator and hide content
      expect(screen.getByText('[+]')).toBeInTheDocument();
      expect(screen.queryByText('claude-3-opus')).not.toBeInTheDocument();
    });

    it('expands when collapsed header is clicked', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      // Collapse first
      await act(async () => {
        fireEvent.click(screen.getByText('[CALIBRATION]'));
      });

      expect(screen.queryByText('claude-3-opus')).not.toBeInTheDocument();

      // Expand
      await act(async () => {
        fireEvent.click(screen.getByText('[CALIBRATION]'));
      });

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('shows error message when fetch fails', async () => {
      mockFetch.mockImplementation(() => Promise.resolve({ ok: false }));

      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('Failed to fetch calibration data')).toBeInTheDocument();
      });
    });

    it('handles network errors gracefully', async () => {
      mockFetch.mockImplementation(() => Promise.reject(new Error('Network error')));

      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('Network error')).toBeInTheDocument();
      });
    });
  });

  describe('Empty State', () => {
    it('shows empty state when no agents returned', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/calibration/leaderboard')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ agents: [] }) });
        }
        return Promise.resolve({ ok: false });
      });

      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(screen.getByText('No calibration data available')).toBeInTheDocument();
      });
    });
  });

  describe('Legend', () => {
    it('shows calibration explanation', async () => {
      setupSuccessfulFetch();
      await act(async () => {
        render(<CalibrationPanel apiBase="http://localhost:8080" />);
      });

      await waitFor(() => {
        expect(
          screen.getByText('Calibration = how well confidence matches accuracy'),
        ).toBeInTheDocument();
      });
    });
  });
});
