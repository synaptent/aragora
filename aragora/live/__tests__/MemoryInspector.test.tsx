/**
 * Tests for MemoryInspector component
 *
 * Tests cover:
 * - Loading states and panel rendering
 * - Tier stats display (fast/medium/slow/glacial)
 * - Tier toggle selection
 * - Memory search functionality
 * - Search results display
 * - Consolidation POST request and feedback
 * - Error handling
 * - Expanded/collapsed states
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryInspector } from '../src/components/MemoryInspector';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock data
const mockTierStats = {
  tiers: {
    fast: {
      count: 50,
      avg_importance: 0.75,
      avg_consolidation: 0.4,
      oldest_entry: '2026-01-01',
      newest_entry: '2026-01-05',
    },
    medium: {
      count: 120,
      avg_importance: 0.6,
      avg_consolidation: 0.6,
      oldest_entry: '2025-12-15',
      newest_entry: '2026-01-05',
    },
    slow: {
      count: 300,
      avg_importance: 0.5,
      avg_consolidation: 0.8,
      oldest_entry: '2025-11-01',
      newest_entry: '2026-01-04',
    },
    glacial: {
      count: 80,
      avg_importance: 0.45,
      avg_consolidation: 0.9,
      oldest_entry: '2025-06-01',
      newest_entry: '2026-01-01',
    },
  },
};

const mockMemories = [
  {
    id: 'mem-001',
    tier: 'fast',
    content: 'Agent claude-3-opus excels at logical reasoning in technical debates',
    importance: 0.85,
    surprise_score: 0.3,
    consolidation_score: 0.6,
    update_count: 5,
    created_at: '2026-01-01T10:00:00Z',
    updated_at: '2026-01-05T15:30:00Z',
  },
  {
    id: 'mem-002',
    tier: 'medium',
    content: 'Consensus often emerges after round 3 in multi-agent debates',
    importance: 0.72,
    surprise_score: 0.2,
    consolidation_score: 0.45,
    update_count: 12,
    created_at: '2025-12-20T08:00:00Z',
    updated_at: '2026-01-04T12:00:00Z',
  },
];

const mockConsolidationResult = {
  success: true,
  entries_processed: 550,
  entries_promoted: 15,
  entries_consolidated: 8,
  duration_seconds: 2.45,
};

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string, options?: RequestInit) => {
    if (url.includes('/api/memory/tier-stats')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTierStats) });
    }
    if (url.includes('/api/memory/continuum/retrieve')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ memories: mockMemories }) });
    }
    if (url.includes('/api/memory/continuum/consolidate') && options?.method === 'POST') {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockConsolidationResult) });
    }
    return Promise.resolve({ ok: false });
  });
}

const renderWithTierStats = async () => {
  render(<MemoryInspector apiBase="http://localhost:8080" />);
  await waitFor(() => {
    expect(screen.getByText('FAST')).toBeInTheDocument();
  });
};

describe('MemoryInspector', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Loading States', () => {
    it('shows panel title', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();
      expect(screen.getByText('Continuum Memory')).toBeInTheDocument();
    });

    it('fetches tier stats on mount', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining('/api/memory/tier-stats'));
      });
    });
  });

  describe('Tier Overview', () => {
    it('displays all 4 tier buttons', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      await waitFor(() => {
        expect(screen.getByText('FAST')).toBeInTheDocument();
        expect(screen.getByText('MEDIUM')).toBeInTheDocument();
        expect(screen.getByText('SLOW')).toBeInTheDocument();
        expect(screen.getByText('GLACIAL')).toBeInTheDocument();
      });
    });

    it('shows entry counts for each tier', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      await waitFor(() => {
        expect(screen.getByText('50 entries')).toBeInTheDocument();
        expect(screen.getByText('120 entries')).toBeInTheDocument();
        expect(screen.getByText('300 entries')).toBeInTheDocument();
        expect(screen.getByText('80 entries')).toBeInTheDocument();
      });
    });

    it('calculates total memories correctly', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      await waitFor(() => {
        // 50 + 120 + 300 + 80 = 550
        expect(screen.getByText('550')).toBeInTheDocument();
      });
    });
  });

  describe('Tier Selection', () => {
    it('has fast and medium selected by default', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      await waitFor(() => {
        expect(screen.getByText('FAST')).toBeInTheDocument();
      });

      // Check that 2 tiers are selected - text split across elements
      const selectedLabel = screen.getByText(/Selected:/);
      const selectedContainer = selectedLabel.closest('span');
      expect(selectedContainer?.textContent).toMatch(/Selected:.*2.*tiers/);
    });

    it('toggles tier selection on click', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      await waitFor(() => {
        expect(screen.getByText('SLOW')).toBeInTheDocument();
      });

      // Click SLOW tier to select it
      fireEvent.click(screen.getByText('SLOW'));

      // Should now have 3 tiers selected - text split across elements
      await waitFor(() => {
        const selectedLabel = screen.getByText(/Selected:/);
        const selectedContainer = selectedLabel.closest('span');
        expect(selectedContainer?.textContent).toMatch(/Selected:.*3.*tiers/);
      });
    });

    it('deselects tier on second click', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      await waitFor(() => {
        expect(screen.getByText('FAST')).toBeInTheDocument();
      });

      // Click FAST tier to deselect it
      fireEvent.click(screen.getByText('FAST'));

      // Should now have 1 tier selected - text split across elements
      await waitFor(() => {
        const selectedLabel = screen.getByText(/Selected:/);
        const selectedContainer = selectedLabel.closest('span');
        expect(selectedContainer?.textContent).toMatch(/Selected:.*1.*tier/);
      });
    });
  });

  describe('Search Functionality', () => {
    it('shows search input', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      expect(screen.getByPlaceholderText('Search memories...')).toBeInTheDocument();
    });

    it('shows error for empty search', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        expect(screen.getByText('Enter a search query')).toBeInTheDocument();
      });
    });

    it('performs search with query', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      const input = screen.getByPlaceholderText('Search memories...');
      fireEvent.change(input, { target: { value: 'reasoning' } });
      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/memory/continuum/retrieve?query=reasoning'),
        );
      });
    });

    it('includes selected tiers in search request', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      const input = screen.getByPlaceholderText('Search memories...');
      fireEvent.change(input, { target: { value: 'test' } });
      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        const searchCall = mockFetch.mock.calls.find((call: string[]) =>
          call[0].includes('/api/memory/continuum/retrieve'),
        );
        expect(searchCall[0]).toContain('tiers=fast,medium');
      });
    });
  });

  describe('Search Results', () => {
    it('displays search results', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      const input = screen.getByPlaceholderText('Search memories...');
      fireEvent.change(input, { target: { value: 'reasoning' } });
      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        expect(screen.getByText(/Agent claude-3-opus excels/)).toBeInTheDocument();
        expect(screen.getByText(/Consensus often emerges/)).toBeInTheDocument();
      });
    });

    it('shows importance percentages', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      const input = screen.getByPlaceholderText('Search memories...');
      fireEvent.change(input, { target: { value: 'test' } });
      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        expect(screen.getByText('IMP: 85%')).toBeInTheDocument(); // 0.85 * 100
        expect(screen.getByText('IMP: 72%')).toBeInTheDocument(); // 0.72 * 100
      });
    });

    it('shows consolidation scores', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      const input = screen.getByPlaceholderText('Search memories...');
      fireEvent.change(input, { target: { value: 'test' } });
      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        expect(screen.getByText('CON: 60%')).toBeInTheDocument(); // 0.6 * 100
        expect(screen.getByText('CON: 45%')).toBeInTheDocument(); // 0.45 * 100
      });
    });

    it('shows update counts', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      const input = screen.getByPlaceholderText('Search memories...');
      fireEvent.change(input, { target: { value: 'test' } });
      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        expect(screen.getByText('Updates: 5')).toBeInTheDocument();
        expect(screen.getByText('Updates: 12')).toBeInTheDocument();
      });
    });

    it('shows empty state when no results', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/memory/tier-stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTierStats) });
        }
        if (url.includes('/api/memory/continuum/retrieve')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ memories: [] }) });
        }
        return Promise.resolve({ ok: false });
      });

      await renderWithTierStats();

      const input = screen.getByPlaceholderText('Search memories...');
      fireEvent.change(input, { target: { value: 'nonexistent' } });
      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        expect(screen.getByText(/Search the continuum memory system/)).toBeInTheDocument();
      });
    });
  });

  describe('Consolidation', () => {
    it('shows consolidate button', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      expect(screen.getByText('CONSOLIDATE')).toBeInTheDocument();
    });

    it('sends POST request on consolidate click', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      fireEvent.click(screen.getByText('CONSOLIDATE'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/memory/continuum/consolidate'),
          expect.objectContaining({ method: 'POST' }),
        );
      });
    });

    it('shows consolidation success feedback', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      fireEvent.click(screen.getByText('CONSOLIDATE'));

      await waitFor(() => {
        expect(screen.getByText('✓ CONSOLIDATED')).toBeInTheDocument();
        expect(screen.getByText(/2.45s/)).toBeInTheDocument();
      });
    });

    it('shows consolidation stats', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      fireEvent.click(screen.getByText('CONSOLIDATE'));

      // Text split across elements, check container text content
      await waitFor(() => {
        const processedLabel = screen.getByText(/Processed:/);
        const processedContainer = processedLabel.closest('span');
        expect(processedContainer?.textContent).toMatch(/Processed:.*550/);

        const promotedLabel = screen.getByText(/Promoted:/);
        const promotedContainer = promotedLabel.closest('span');
        expect(promotedContainer?.textContent).toMatch(/Promoted:.*15/);
      });
    });

    it('shows loading state during consolidation', async () => {
      mockFetch.mockImplementation((url: string, _options?: RequestInit) => {
        if (url.includes('/api/memory/tier-stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTierStats) });
        }
        if (url.includes('/api/memory/continuum/consolidate')) {
          return new Promise(() => {}); // Never resolves
        }
        return Promise.resolve({ ok: false });
      });

      await renderWithTierStats();

      fireEvent.click(screen.getByText('CONSOLIDATE'));

      await waitFor(() => {
        expect(screen.getByText('CONSOLIDATING...')).toBeInTheDocument();
      });
    });

    it('refreshes tier stats after consolidation', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      await waitFor(() => {
        expect(screen.getByText('FAST')).toBeInTheDocument();
      });

      const initialCalls = mockFetch.mock.calls.filter((call: string[]) =>
        call[0].includes('/api/memory/tier-stats'),
      ).length;

      fireEvent.click(screen.getByText('CONSOLIDATE'));

      await waitFor(() => {
        const afterCalls = mockFetch.mock.calls.filter((call: string[]) =>
          call[0].includes('/api/memory/tier-stats'),
        ).length;
        expect(afterCalls).toBeGreaterThan(initialCalls);
      });
    });
  });

  describe('Error Handling', () => {
    it('shows error on search failure', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/memory/tier-stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTierStats) });
        }
        if (url.includes('/api/memory/continuum/retrieve')) {
          return Promise.resolve({
            ok: false,
            json: () => Promise.resolve({ error: 'Database unavailable' }),
          });
        }
        return Promise.resolve({ ok: false });
      });

      await renderWithTierStats();

      const input = screen.getByPlaceholderText('Search memories...');
      fireEvent.change(input, { target: { value: 'test' } });
      fireEvent.click(screen.getByText('SEARCH'));

      await waitFor(() => {
        expect(screen.getByText('Database unavailable')).toBeInTheDocument();
      });
    });

    it('shows error on consolidation failure', async () => {
      mockFetch.mockImplementation((url: string, _options?: RequestInit) => {
        if (url.includes('/api/memory/tier-stats')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve(mockTierStats) });
        }
        if (url.includes('/api/memory/continuum/consolidate')) {
          return Promise.resolve({
            ok: false,
            json: () => Promise.resolve({ error: 'Consolidation timeout' }),
          });
        }
        return Promise.resolve({ ok: false });
      });

      await renderWithTierStats();

      fireEvent.click(screen.getByText('CONSOLIDATE'));

      await waitFor(() => {
        expect(screen.getByText('Consolidation timeout')).toBeInTheDocument();
      });
    });
  });

  describe('Expand/Collapse', () => {
    it('collapses panel when collapse button clicked', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      fireEvent.click(screen.getByText('[-]'));

      // Search input should be hidden when collapsed
      expect(screen.queryByPlaceholderText('Search memories...')).not.toBeInTheDocument();
    });

    it('shows tier legend when collapsed', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      fireEvent.click(screen.getByText('[-]'));

      expect(screen.getByText(/Updates on every event/)).toBeInTheDocument();
      expect(screen.getByText(/Updates per debate round/)).toBeInTheDocument();
    });

    it('expands panel when expand button clicked', async () => {
      setupSuccessfulFetch();
      await renderWithTierStats();

      // Collapse first
      fireEvent.click(screen.getByText('[-]'));

      // Then expand
      fireEvent.click(screen.getByText('[+]'));

      await waitFor(() => {
        expect(screen.getByPlaceholderText('Search memories...')).toBeInTheDocument();
      });
    });
  });
});
