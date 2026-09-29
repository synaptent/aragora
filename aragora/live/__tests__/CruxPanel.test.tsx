/**
 * Tests for CruxPanel component
 *
 * Tests cover:
 * - Form with debate ID input
 * - Form validation (non-empty ID)
 * - Parallel fetch of cruxes and load-bearing claims
 * - Tabs: cruxes, load-bearing
 * - Crux display with centrality, entropy, belief probabilities
 * - Load-bearing claims display
 * - Error handling
 * - Empty states
 */

import { renderWithProviders, screen, fireEvent, waitFor } from '@/test-utils';
import { CruxPanel } from '../src/components/CruxPanel';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock data
const mockCruxes = [
  {
    claim_id: 'crux-001',
    statement: 'AI alignment requires formal verification methods',
    author: 'claude-3-opus',
    crux_score: 0.856,
    centrality: 0.42,
    entropy: 0.75,
    current_belief: { true_prob: 0.6, false_prob: 0.15, uncertain_prob: 0.25, confidence: 0.7 },
  },
  {
    claim_id: 'crux-002',
    statement: 'Interpretability is key to safe AI deployment',
    author: 'gemini-2.0-flash',
    crux_score: 0.723,
    centrality: 0.35,
    entropy: 0.62,
    current_belief: { true_prob: 0.7, false_prob: 0.1, uncertain_prob: 0.2, confidence: 0.8 },
  },
];

const mockLoadBearingClaims = [
  {
    claim_id: 'lb-001',
    statement: 'Current AI systems lack robust goal stability',
    author: 'claude-3-opus',
    centrality: 0.55,
  },
  {
    claim_id: 'lb-002',
    statement: 'Value learning is tractable with sufficient oversight',
    author: 'gpt-4',
    centrality: 0.38,
  },
];

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/api/belief-network/') && url.includes('/cruxes')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ cruxes: mockCruxes }) });
    }
    if (url.includes('/api/belief-network/') && url.includes('/load-bearing-claims')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ load_bearing_claims: mockLoadBearingClaims }),
      });
    }
    return Promise.resolve({ ok: false });
  });
}

describe('CruxPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Initial State', () => {
    it('shows panel title', () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);
      expect(screen.getByText('Belief Network Analysis')).toBeInTheDocument();
    });

    it('shows cruxes label', () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);
      expect(screen.getByText('[CRUXES]')).toBeInTheDocument();
    });

    it('shows debate ID input', () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);
      expect(screen.getByPlaceholderText('Enter debate ID...')).toBeInTheDocument();
    });

    it('shows ANALYZE button', () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);
      expect(screen.getByText('ANALYZE')).toBeInTheDocument();
    });

    it('shows help text about cruxes', () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);
      expect(
        screen.getByText(/Claims with high uncertainty and high centrality/),
      ).toBeInTheDocument();
    });

    it('shows help text about load-bearing claims', () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);
      expect(screen.getByText(/Claims that many other claims depend on/)).toBeInTheDocument();
    });

    it('shows initial empty state', () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);
      expect(
        screen.getByText('Enter a debate ID to analyze belief network cruxes.'),
      ).toBeInTheDocument();
    });

    it('uses initial debateId if provided', () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" debateId="test-debate-123" />);
      expect(screen.getByPlaceholderText('Enter debate ID...')).toHaveValue('test-debate-123');
    });
  });

  describe('Form Validation', () => {
    it('shows error for empty debate ID', async () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('Please enter a debate ID')).toBeInTheDocument();
      });
    });

    it('does not fetch when debate ID is empty', async () => {
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('Please enter a debate ID')).toBeInTheDocument();
      });

      expect(mockFetch).not.toHaveBeenCalled();
    });
  });

  describe('Data Fetching', () => {
    it('fetches both cruxes and load-bearing claims', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/belief-network/debate-123/cruxes'),
          expect.anything(),
        );
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/belief-network/debate-123/load-bearing-claims'),
          expect.anything(),
        );
      });
    });

    it('shows loading state during fetch', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('...')).toBeInTheDocument();
      });
    });
  });

  describe('Cruxes Display', () => {
    it('displays crux statements', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(
          screen.getByText('AI alignment requires formal verification methods'),
        ).toBeInTheDocument();
        expect(
          screen.getByText('Interpretability is key to safe AI deployment'),
        ).toBeInTheDocument();
      });
    });

    it('shows crux numbers', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('CRUX #1')).toBeInTheDocument();
        expect(screen.getByText('CRUX #2')).toBeInTheDocument();
      });
    });

    it('shows crux scores', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('score: 0.856')).toBeInTheDocument();
        expect(screen.getByText('score: 0.723')).toBeInTheDocument();
      });
    });

    it('shows authors', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
        expect(screen.getByText('gemini-2.0-flash')).toBeInTheDocument();
      });
    });

    it('shows centrality percentages', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('centrality: 42.0%')).toBeInTheDocument();
        expect(screen.getByText('centrality: 35.0%')).toBeInTheDocument();
      });
    });

    it('shows entropy values', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('entropy: 0.75')).toBeInTheDocument();
        expect(screen.getByText('entropy: 0.62')).toBeInTheDocument();
      });
    });

    it('shows belief probabilities', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('T: 60%')).toBeInTheDocument();
        expect(screen.getByText('F: 15%')).toBeInTheDocument();
        expect(screen.getByText('?: 25%')).toBeInTheDocument();
      });
    });
  });

  describe('Tabs', () => {
    it('shows tabs when data is loaded', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('CRUXES (2)')).toBeInTheDocument();
        expect(screen.getByText('LOAD-BEARING (2)')).toBeInTheDocument();
      });
    });

    it('switches to load-bearing tab', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('LOAD-BEARING (2)')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('LOAD-BEARING (2)'));

      await waitFor(() => {
        expect(
          screen.getByText('Current AI systems lack robust goal stability'),
        ).toBeInTheDocument();
        expect(
          screen.getByText('Value learning is tractable with sufficient oversight'),
        ).toBeInTheDocument();
      });
    });
  });

  describe('Load-Bearing Claims Display', () => {
    it('displays load-bearing claim statements', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('LOAD-BEARING (2)')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('LOAD-BEARING (2)'));

      await waitFor(() => {
        expect(screen.getByText('#1 STRUCTURAL')).toBeInTheDocument();
        expect(screen.getByText('#2 STRUCTURAL')).toBeInTheDocument();
      });
    });

    it('shows load-bearing centrality', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('LOAD-BEARING (2)')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('LOAD-BEARING (2)'));

      await waitFor(() => {
        expect(screen.getByText('centrality: 55.0%')).toBeInTheDocument();
        expect(screen.getByText('centrality: 38.0%')).toBeInTheDocument();
      });
    });

    it('shows empty state for load-bearing when none found', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/cruxes')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ cruxes: mockCruxes }) });
        }
        if (url.includes('/load-bearing-claims')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ load_bearing_claims: [] }),
          });
        }
        return Promise.resolve({ ok: false });
      });

      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('LOAD-BEARING (0)')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('LOAD-BEARING (0)'));

      await waitFor(() => {
        expect(
          screen.getByText('No load-bearing claims found for this debate.'),
        ).toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('shows error on crux fetch failure', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/cruxes')) {
          return Promise.resolve({
            ok: false,
            status: 404,
            json: () => Promise.resolve({ error: 'Debate not found' }),
          });
        }
        return Promise.resolve({ ok: false });
      });

      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'nonexistent' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('Debate not found')).toBeInTheDocument();
      });
    });

    it('clears data on error', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<CruxPanel apiBase="http://localhost:8080" />);

      // First load data
      const input = screen.getByPlaceholderText('Enter debate ID...');
      fireEvent.change(input, { target: { value: 'debate-123' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('CRUX #1')).toBeInTheDocument();
      });

      // Now set up error response
      mockFetch.mockImplementation(() =>
        Promise.resolve({
          ok: false,
          status: 500,
          json: () => Promise.resolve({ error: 'Server error' }),
        }),
      );

      // Search again
      fireEvent.change(input, { target: { value: 'bad-debate' } });
      fireEvent.click(screen.getByText('ANALYZE'));

      await waitFor(() => {
        expect(screen.getByText('Server error')).toBeInTheDocument();
      });

      // Cruxes should be cleared
      expect(screen.queryByText('CRUX #1')).not.toBeInTheDocument();
    });
  });
});
