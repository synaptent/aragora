/**
 * Tests for InsightsPanel component
 *
 * Note: This is a placeholder test file. To run these tests, you would need to:
 * 1. Install Jest and React Testing Library: npm install --save-dev jest @testing-library/react @testing-library/jest-dom
 * 2. Configure Jest in package.json or jest.config.js
 * 3. Add test script to package.json
 */

import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { InsightsPanel } from '../src/components/InsightsPanel';

// Mock fetch globally
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('InsightsPanel', () => {
  beforeEach(() => {
    mockFetch.mockClear();
  });

  describe('Tab Navigation', () => {
    it('renders all four tabs', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ insights: [], flips: [], summary: {} }),
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      // Use getByRole with tab role since the tabs have role="tab"
      await waitFor(() => {
        expect(screen.getByRole('tab', { name: /Insights/ })).toBeInTheDocument();
      });
      expect(screen.getByRole('tab', { name: /Memory/ })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: /Flips/ })).toBeInTheDocument();
      expect(screen.getByRole('tab', { name: /Learning/ })).toBeInTheDocument();
    });

    it('defaults to Insights tab', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ insights: [], flips: [], summary: {} }),
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      // Check that Insights tab is active (has different styling)
      await waitFor(() => {
        const insightsTab = screen.getByRole('tab', { name: /Insights/ });
        expect(insightsTab).toHaveClass('bg-accent');
      });
    });

    it('switches to Flips tab when clicked', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ insights: [], flips: [], summary: {} }),
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      const flipsTab = screen.getByRole('tab', { name: /Flips/ });
      await act(async () => {
        fireEvent.click(flipsTab);
      });

      expect(flipsTab).toHaveClass('bg-accent');
    });
  });

  describe('Flips Tab Content', () => {
    const mockFlips = [
      {
        id: 'flip-1',
        agent: 'claude',
        type: 'contradiction',
        type_emoji: '🔄',
        before: { claim: 'Original position A', confidence: '85%' },
        after: { claim: 'New position B', confidence: '70%' },
        similarity: '45%',
        domain: 'architecture',
        timestamp: '2026-01-04T12:00:00Z',
      },
      {
        id: 'flip-2',
        agent: 'gemini',
        type: 'refinement',
        type_emoji: '🔧',
        before: { claim: 'Initial approach', confidence: '60%' },
        after: { claim: 'Improved approach', confidence: '80%' },
        similarity: '75%',
        domain: 'performance',
        timestamp: '2026-01-04T11:00:00Z',
      },
    ];

    const mockSummary = {
      total_flips: 5,
      by_type: { contradiction: 2, refinement: 3 },
      by_agent: { claude: 3, gemini: 2 },
      recent_24h: 2,
    };

    it('displays flips when available', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/flips/recent')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ flips: mockFlips }) });
        }
        if (url.includes('/api/flips/summary')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ summary: mockSummary }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ insights: [] }) });
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      // Switch to Flips tab
      const flipsTab = screen.getByRole('tab', { name: /Flips/ });
      await act(async () => {
        fireEvent.click(flipsTab);
      });

      await waitFor(() => {
        expect(screen.getByText('claude')).toBeInTheDocument();
        expect(screen.getByText('gemini')).toBeInTheDocument();
      });
    });

    it('displays flip type badges with correct colors', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/flips/recent')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ flips: mockFlips }) });
        }
        if (url.includes('/api/flips/summary')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ summary: mockSummary }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ insights: [] }) });
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      const flipsTab = screen.getByRole('tab', { name: /Flips/ });
      await act(async () => {
        fireEvent.click(flipsTab);
      });

      await waitFor(() => {
        // Get all elements containing the type text - there may be multiple (badge + summary)
        const contradictionElements = screen.getAllByText(/contradiction/i);
        // Find the one that's in the flip type badge (has text-red-400 class)
        const contradictionBadge = contradictionElements.find(
          (el) => el.closest('[class*="text-red-400"]') || el.classList.contains('text-red-400'),
        );
        expect(contradictionBadge).toBeTruthy();

        const refinementElements = screen.getAllByText(/refinement/i);
        const refinementBadge = refinementElements.find(
          (el) =>
            el.closest('[class*="text-green-400"]') || el.classList.contains('text-green-400'),
        );
        expect(refinementBadge).toBeTruthy();
      });
    });

    it('displays before/after claims', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/flips/recent')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ flips: mockFlips }) });
        }
        if (url.includes('/api/flips/summary')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ summary: mockSummary }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ insights: [] }) });
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      const flipsTab = screen.getByRole('tab', { name: /Flips/ });
      await act(async () => {
        fireEvent.click(flipsTab);
      });

      // Wait for flips data to load - use findByText for async content
      const flipContent = await screen.findByText('Initial approach', {}, { timeout: 3000 });
      expect(flipContent).toBeInTheDocument();
    });

    it('displays flip summary when available', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/flips/recent')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ flips: mockFlips }) });
        }
        if (url.includes('/api/flips/summary')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ summary: mockSummary }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ insights: [] }) });
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      const flipsTab = screen.getByRole('tab', { name: /Flips/ });
      await act(async () => {
        fireEvent.click(flipsTab);
      });

      await waitFor(() => {
        expect(screen.getByText('Position Reversals')).toBeInTheDocument();
        expect(screen.getByText('2 in 24h')).toBeInTheDocument();
        expect(screen.getByText('2 contradictions')).toBeInTheDocument();
        expect(screen.getByText('3 refinements')).toBeInTheDocument();
      });
    });

    it('shows empty state when no flips', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/flips/recent')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ flips: [] }) });
        }
        if (url.includes('/api/flips/summary')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ summary: null }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ insights: [] }) });
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      const flipsTab = screen.getByRole('tab', { name: /Flips/ });
      await act(async () => {
        fireEvent.click(flipsTab);
      });

      await waitFor(() => {
        expect(screen.getByText(/No position flips detected yet/)).toBeInTheDocument();
      });
    });

    it('displays domain tag when present', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/flips/recent')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ flips: mockFlips }) });
        }
        if (url.includes('/api/flips/summary')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ summary: mockSummary }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ insights: [] }) });
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      const flipsTab = screen.getByRole('tab', { name: /Flips/ });
      await act(async () => {
        fireEvent.click(flipsTab);
      });

      await waitFor(() => {
        expect(screen.getByText('architecture')).toBeInTheDocument();
        expect(screen.getByText('performance')).toBeInTheDocument();
      });
    });
  });

  describe('API Integration', () => {
    it('uses provided apiBase for API calls', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ insights: [], flips: [], summary: {} }),
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} apiBase="https://custom-api.example.com" />);
      });

      // Wait for the loading state to complete and check fetch was called
      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      // Check that at least one call was to the custom API base
      const hasCustomApiCall = mockFetch.mock.calls.some(
        (call) => call[0] && call[0].includes('https://custom-api.example.com'),
      );
      expect(hasCustomApiCall).toBe(true);
    });

    it('handles API errors gracefully', async () => {
      // Mock fetch to reject (network error) - this will cause fetchWithRetry to fail after retries
      mockFetch.mockRejectedValue(new Error('Network error'));

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      // Component should handle errors and still render (not crash)
      // After error, component may show error state or empty state
      await waitFor(() => {
        // Just verify the component rendered without crashing
        expect(screen.getByText('Debate Insights')).toBeInTheDocument();
      });
    });

    it('calls refresh when Refresh button is clicked', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ insights: [] }) });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      const initialCallCount = mockFetch.mock.calls.length;

      const refreshButton = screen.getByText('Refresh');
      await act(async () => {
        fireEvent.click(refreshButton);
      });

      await waitFor(() => {
        expect(mockFetch.mock.calls.length).toBeGreaterThan(initialCallCount);
      });
    });
  });

  describe('Memory Tab', () => {
    it('displays memory recalls from WebSocket messages', async () => {
      const wsMessages = [
        {
          type: 'memory_recall',
          data: {
            query: 'Test query',
            hits: [
              { topic: 'Related topic 1', similarity: 0.85 },
              { topic: 'Related topic 2', similarity: 0.72 },
            ],
            count: 2,
          },
          timestamp: '2026-01-04T12:00:00Z',
        },
      ];

      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ insights: [], flips: [], summary: {} }),
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={wsMessages} />);
      });

      const memoryTab = screen.getByRole('tab', { name: /Memory/ });
      await act(async () => {
        fireEvent.click(memoryTab);
      });

      expect(screen.getByText('Query: Test query')).toBeInTheDocument();
      expect(screen.getByText('Related topic 1')).toBeInTheDocument();
      expect(screen.getByText('85%')).toBeInTheDocument();
    });

    it('shows empty state when no memory recalls', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: () => Promise.resolve({ insights: [], flips: [], summary: {} }),
      });

      await act(async () => {
        render(<InsightsPanel wsMessages={[]} />);
      });

      const memoryTab = screen.getByRole('tab', { name: /Memory/ });
      await act(async () => {
        fireEvent.click(memoryTab);
      });

      expect(screen.getByText(/No memory recalls yet/)).toBeInTheDocument();
    });
  });
});
