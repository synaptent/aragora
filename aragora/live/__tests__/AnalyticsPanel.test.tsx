/**
 * Tests for AnalyticsPanel component
 *
 * Tests cover:
 * - Collapsed/expanded state
 * - Tab switching (disagreements, roles, early-stops, graph)
 * - Conditional fetching based on active tab
 * - Data display for each tab
 * - Error handling
 * - Empty states
 * - Graph tab with/without loopId
 */

import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { AnalyticsPanel } from '../src/components/AnalyticsPanel';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock data
const mockDisagreements = [
  {
    debate_id: 'debate-001',
    topic: 'Should AI be regulated?',
    agents: ['claude-3-opus', 'gemini-2.0-flash'],
    dissent_count: 3,
    consensus_reached: false,
    confidence: 0.45,
    timestamp: '2026-01-05T10:00:00Z',
  },
  {
    debate_id: 'debate-002',
    topic: 'Is functional programming better?',
    agents: ['claude-3-opus', 'gpt-4'],
    dissent_count: 2,
    consensus_reached: true,
    confidence: 0.72,
    timestamp: '2026-01-04T14:00:00Z',
  },
];

const mockRoleRotations = [
  {
    agent: 'claude-3-opus',
    role_counts: { proposer: 15, critic: 12, synthesizer: 8 },
    total_debates: 35,
  },
  {
    agent: 'gemini-2.0-flash',
    role_counts: { proposer: 10, critic: 18, synthesizer: 7 },
    total_debates: 35,
  },
];

const mockEarlyStops = [
  {
    debate_id: 'debate-003',
    topic: 'Rate limiter design',
    rounds_completed: 2,
    rounds_planned: 5,
    reason: 'unanimous_agreement',
    consensus_early: true,
    timestamp: '2026-01-05T08:00:00Z',
  },
  {
    debate_id: 'debate-004',
    topic: 'Cache invalidation strategy',
    rounds_completed: 3,
    rounds_planned: 5,
    reason: 'timeout',
    consensus_early: false,
    timestamp: '2026-01-04T16:00:00Z',
  },
];

const mockGraphStats = {
  node_count: 42,
  edge_count: 67,
  max_depth: 5,
  avg_branching: 2.35,
  complexity_score: 0.78,
  claim_count: 28,
  rebuttal_count: 14,
};

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/api/analytics/disagreements')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ disagreements: mockDisagreements }),
      });
    }
    if (url.includes('/api/analytics/role-rotation')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ summary: mockRoleRotations }),
      });
    }
    if (url.includes('/api/analytics/early-stops')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ early_stops: mockEarlyStops }),
      });
    }
    if (url.includes('/api/debate/') && url.includes('/graph/stats')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockGraphStats) });
    }
    return Promise.resolve({ ok: false });
  });
}

describe('AnalyticsPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Initial State', () => {
    it('shows panel header with collapsed state', () => {
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);
      expect(screen.getByText('[ANALYTICS]')).toBeInTheDocument();
      expect(screen.getByText('[+]')).toBeInTheDocument();
    });

    it('does not fetch data when collapsed', () => {
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('shows description text', () => {
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);
      expect(screen.getByText('Debate patterns & insights')).toBeInTheDocument();
    });
  });

  describe('Expand/Collapse', () => {
    it('expands panel and fetches data when clicked', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));

      await waitFor(() => {
        expect(screen.getByText('[-]')).toBeInTheDocument();
      });
      expect(mockFetch).toHaveBeenCalledWith(
        expect.stringContaining('/api/analytics/disagreements'),
      );
    });

    it('collapses panel when clicked again', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      // Expand
      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('[-]')).toBeInTheDocument();
      });

      // Collapse
      fireEvent.click(screen.getByText('[ANALYTICS]'));
      expect(screen.getByText('[+]')).toBeInTheDocument();
    });
  });

  describe('Tabs', () => {
    it('shows all 4 tabs when expanded', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));

      await waitFor(() => {
        expect(screen.getByText('DISAGREEMENTS')).toBeInTheDocument();
        expect(screen.getByText('ROLES')).toBeInTheDocument();
        expect(screen.getByText('EARLY-STOPS')).toBeInTheDocument();
        expect(screen.getByText('GRAPH')).toBeInTheDocument();
      });
    });

    it('fetches roles data when roles tab clicked', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('ROLES')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('ROLES'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/analytics/role-rotation'),
        );
      });
    });

    it('fetches early-stops data when tab clicked', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('EARLY-STOPS')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('EARLY-STOPS'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/analytics/early-stops'),
        );
      });
    });
  });

  describe('Disagreements Tab', () => {
    it('displays disagreement topics', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));

      await waitFor(() => {
        expect(screen.getByText('Should AI be regulated?')).toBeInTheDocument();
        expect(screen.getByText('Is functional programming better?')).toBeInTheDocument();
      });
    });

    it('shows confidence percentages', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));

      await waitFor(() => {
        expect(screen.getByText('45% conf')).toBeInTheDocument();
        expect(screen.getByText('72% conf')).toBeInTheDocument();
      });
    });

    it('shows dissent counts', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));

      await waitFor(() => {
        expect(screen.getByText(/3 dissent/)).toBeInTheDocument();
        expect(screen.getByText(/2 dissent/)).toBeInTheDocument();
      });
    });

    it('shows empty state when no disagreements', async () => {
      mockFetch.mockResolvedValue({ ok: true, json: () => Promise.resolve({ disagreements: [] }) });
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));

      await waitFor(() => {
        expect(screen.getByText('No disagreements recorded yet')).toBeInTheDocument();
      });
    });
  });

  describe('Roles Tab', () => {
    it('displays agent names', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('ROLES')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('ROLES'));

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
        expect(screen.getByText('gemini-2.0-flash')).toBeInTheDocument();
      });
    });

    it('shows role counts', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('ROLES')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('ROLES'));

      await waitFor(() => {
        expect(screen.getByText('proposer: 15')).toBeInTheDocument();
        expect(screen.getByText('critic: 12')).toBeInTheDocument();
      });
    });

    it('shows total debates', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('ROLES')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('ROLES'));

      await waitFor(() => {
        expect(screen.getAllByText('35 debates total')).toHaveLength(2);
      });
    });

    it('shows empty state when no role data', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/analytics/disagreements')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ disagreements: mockDisagreements }),
          });
        }
        if (url.includes('/api/analytics/role-rotation')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ summary: [] }) });
        }
        return Promise.resolve({ ok: false });
      });
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('ROLES')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('ROLES'));

      await waitFor(() => {
        expect(screen.getByText('No role data available')).toBeInTheDocument();
      });
    });
  });

  describe('Early-Stops Tab', () => {
    it('displays early stop topics', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('EARLY-STOPS')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('EARLY-STOPS'));

      await waitFor(() => {
        expect(screen.getByText('Rate limiter design')).toBeInTheDocument();
        expect(screen.getByText('Cache invalidation strategy')).toBeInTheDocument();
      });
    });

    it('shows rounds completed', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('EARLY-STOPS')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('EARLY-STOPS'));

      await waitFor(() => {
        expect(screen.getByText(/Rounds: 2\/5/)).toBeInTheDocument();
        expect(screen.getByText(/Rounds: 3\/5/)).toBeInTheDocument();
      });
    });

    it('shows consensus indicator for early consensus', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('EARLY-STOPS')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('EARLY-STOPS'));

      await waitFor(() => {
        expect(screen.getByText('consensus')).toBeInTheDocument();
        expect(screen.getByText('timeout')).toBeInTheDocument();
      });
    });

    it('shows empty state when no early stops', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/analytics/disagreements')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ disagreements: mockDisagreements }),
          });
        }
        if (url.includes('/api/analytics/early-stops')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ early_stops: [] }) });
        }
        return Promise.resolve({ ok: false });
      });
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('EARLY-STOPS')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('EARLY-STOPS'));

      await waitFor(() => {
        expect(screen.getByText('No early terminations recorded')).toBeInTheDocument();
      });
    });
  });

  describe('Graph Tab', () => {
    it('shows message when no loopId provided', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('GRAPH')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('GRAPH'));

      await waitFor(() => {
        expect(screen.getByText('No debate selected for graph analysis')).toBeInTheDocument();
      });
    });

    it('fetches graph stats when loopId is provided', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" loopId="debate-123" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('GRAPH')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('GRAPH'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalledWith(
          expect.stringContaining('/api/debate/debate-123/graph/stats'),
        );
      });
    });

    it('displays graph stats', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" loopId="debate-123" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('GRAPH')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('GRAPH'));

      await waitFor(() => {
        expect(screen.getByText('42')).toBeInTheDocument(); // node_count
        expect(screen.getByText('67')).toBeInTheDocument(); // edge_count
        expect(screen.getByText('5')).toBeInTheDocument(); // max_depth
        expect(screen.getByText('2.35')).toBeInTheDocument(); // avg_branching
      });
    });

    it('shows complexity score percentage', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" loopId="debate-123" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('GRAPH')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('GRAPH'));

      await waitFor(() => {
        expect(screen.getByText('78%')).toBeInTheDocument();
      });
    });

    it('shows claim and rebuttal counts', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" loopId="debate-123" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('GRAPH')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('GRAPH'));

      await waitFor(() => {
        expect(screen.getByText('28')).toBeInTheDocument(); // claim_count
        expect(screen.getByText('14')).toBeInTheDocument(); // rebuttal_count
      });
    });

    it('shows message when graph data not available', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/analytics/disagreements')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ disagreements: mockDisagreements }),
          });
        }
        if (url.includes('/api/debate/') && url.includes('/graph/stats')) {
          return Promise.resolve({ ok: false });
        }
        return Promise.resolve({ ok: false });
      });
      render(<AnalyticsPanel apiBase="http://localhost:8080" loopId="debate-123" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('GRAPH')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('GRAPH'));

      await waitFor(() => {
        expect(screen.getByText('No graph data available for this debate')).toBeInTheDocument();
      });
    });
  });

  describe('Loading State', () => {
    it('shows loading indicator while fetching', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));

      await waitFor(() => {
        expect(screen.getByText('Loading analytics...')).toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('shows error message on fetch failure', async () => {
      mockFetch.mockResolvedValue({ ok: false });
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));

      await waitFor(() => {
        expect(screen.getByText('Failed to fetch disagreements')).toBeInTheDocument();
      });
    });

    it('shows error for roles tab failure', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/analytics/disagreements')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ disagreements: mockDisagreements }),
          });
        }
        return Promise.resolve({ ok: false });
      });
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('ROLES')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('ROLES'));

      await waitFor(() => {
        expect(screen.getByText('Failed to fetch roles')).toBeInTheDocument();
      });
    });
  });

  describe('Refresh', () => {
    it('shows refresh button', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));

      await waitFor(() => {
        expect(screen.getByText('[REFRESH]')).toBeInTheDocument();
      });
    });

    it('refetches data when refresh clicked', async () => {
      setupSuccessfulFetch();
      render(<AnalyticsPanel apiBase="http://localhost:8080" />);

      fireEvent.click(screen.getByText('[ANALYTICS]'));
      await waitFor(() => {
        expect(screen.getByText('[REFRESH]')).toBeInTheDocument();
      });

      const initialCalls = mockFetch.mock.calls.filter((call: string[]) =>
        call[0].includes('/api/analytics/'),
      ).length;

      fireEvent.click(screen.getByText('[REFRESH]'));

      await waitFor(() => {
        const afterCalls = mockFetch.mock.calls.filter((call: string[]) =>
          call[0].includes('/api/analytics/'),
        ).length;
        expect(afterCalls).toBeGreaterThan(initialCalls);
      });
    });
  });
});
