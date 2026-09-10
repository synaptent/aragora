/**
 * Tests for LaboratoryPanel component
 *
 * Tests cover:
 * - Loading states and panel rendering
 * - Data display for all 4 tabs (traits, pollinations, evolution, patterns)
 * - Tab switching functionality
 * - Partial failure handling (Promise.allSettled)
 * - Error handling with retry
 * - Empty states
 * - Refresh functionality
 * - Collapsed/expanded states
 */

import { renderWithProviders, screen, fireEvent, waitFor } from '@/test-utils';
import { LaboratoryPanel } from '../src/components/LaboratoryPanel';

// Mock useAuth to always return authenticated state
jest.mock('@/context/AuthContext', () => ({
  ...jest.requireActual('@/context/AuthContext'),
  useAuth: () => ({
    user: null,
    organization: null,
    organizations: [],
    tokens: { access_token: 'test-token', refresh_token: 'r', token_type: 'bearer' },
    isLoading: false,
    isAuthenticated: true,
    isLoadingOrganizations: false,
    login: jest.fn(),
    register: jest.fn(),
    logout: jest.fn(),
    refreshToken: jest.fn(),
    setTokens: jest.fn(),
    switchOrganization: jest.fn(),
    refreshOrganizations: jest.fn(),
    getCurrentOrgRole: jest.fn(),
  }),
}));

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock data
const mockTraits = [
  {
    agent: 'claude-3-opus',
    trait: 'logical_reasoning',
    domain: 'technical',
    confidence: 0.85,
    evidence: ['Strong deductive arguments', 'Clear logical chains', 'Third evidence'],
    detected_at: '2026-01-05T10:00:00Z',
  },
  {
    agent: 'gemini-2.0-flash',
    trait: 'creative_synthesis',
    domain: 'creative',
    confidence: 0.72,
    evidence: ['Novel combinations'],
    detected_at: '2026-01-04T15:30:00Z',
  },
];

const mockPollinations = [
  {
    source_agent: 'claude-3-opus',
    target_agent: 'gemini-2.0-flash',
    trait: 'conciseness',
    expected_improvement: 0.15,
    rationale: 'Observed verbose responses in target agent during technical debates.',
  },
];

const mockGenesisStats = {
  total_events: 100,
  total_births: 5,
  total_deaths: 2,
  net_population_change: 3,
  avg_fitness_change_recent: 0.0245,
  integrity_verified: true,
  event_counts: { birth: 5, death: 2, mutation: 10 },
};

const mockPatterns = [
  {
    pattern: 'Strawman argument detected in opposing position',
    issue_type: 'fallacy',
    suggested_rebuttal: 'Address the actual argument rather than a simplified version',
    success_rate: 0.75,
    usage_count: 12,
  },
  {
    pattern: 'Circular reasoning in conclusion',
    issue_type: 'logic',
    suggested_rebuttal: 'Break the circular dependency by introducing external evidence',
    success_rate: 0.45,
    usage_count: 8,
  },
];

function setupSuccessfulFetch() {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/api/laboratory/emergent-traits')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ emergent_traits: mockTraits }),
      });
    }
    if (url.includes('/api/laboratory/cross-pollinations/suggest')) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ suggestions: mockPollinations }),
      });
    }
    if (url.includes('/api/genesis/stats')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve(mockGenesisStats) });
    }
    if (url.includes('/api/critiques/patterns')) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ patterns: mockPatterns }) });
    }
    return Promise.resolve({ ok: false });
  });
}

describe('LaboratoryPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Loading States', () => {
    it('shows panel title', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {}));
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);
      expect(screen.getByText('Persona Laboratory')).toBeInTheDocument();
    });

    it('shows loading message while fetching traits', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);
      expect(screen.getByText('Detecting emergent traits...')).toBeInTheDocument();
    });

    it('fetches all 4 endpoints on mount', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        // Check that all endpoints were called
        const calls = mockFetch.mock.calls.map((call: string[]) => call[0]);
        expect(calls.some((url: string) => url.includes('/api/laboratory/emergent-traits'))).toBe(
          true,
        );
        expect(
          calls.some((url: string) => url.includes('/api/laboratory/cross-pollinations')),
        ).toBe(true);
        expect(calls.some((url: string) => url.includes('/api/genesis/stats'))).toBe(true);
        expect(calls.some((url: string) => url.includes('/api/critiques/patterns'))).toBe(true);
      });

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });
    });
  });

  describe('Summary Stats', () => {
    it('displays trait count in summary', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('Traits:')).toBeInTheDocument();
      });
    });

    it('displays pollination count in summary', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('Pollinations:')).toBeInTheDocument();
      });
    });

    it('displays genesis population change', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('Population:')).toBeInTheDocument();
        expect(screen.getByText('+3')).toBeInTheDocument(); // net_population_change
      });
    });
  });

  describe('Traits Tab', () => {
    it('displays emergent traits with agent names', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
        expect(screen.getByText('gemini-2.0-flash')).toBeInTheDocument();
      });
    });

    it('shows trait domain badges', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('technical')).toBeInTheDocument();
        expect(screen.getByText('creative')).toBeInTheDocument();
      });
    });

    it('displays confidence percentages', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('85%')).toBeInTheDocument(); // 0.85 * 100
        expect(screen.getByText('72%')).toBeInTheDocument(); // 0.72 * 100
      });
    });

    it('shows evidence with truncation for long lists', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('Strong deductive arguments')).toBeInTheDocument();
        expect(screen.getByText('+1 more evidence')).toBeInTheDocument(); // 3 evidence, shows 2
      });
    });

    it('shows empty state when no traits', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/laboratory/emergent-traits')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ emergent_traits: [] }),
          });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText(/No emergent traits detected yet/)).toBeInTheDocument();
      });
    });
  });

  describe('Tab Switching', () => {
    it('switches to pollinations tab', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('POLLINATIONS'));

      await waitFor(() => {
        expect(screen.getByText('Transfer: conciseness')).toBeInTheDocument();
      });
    });

    it('switches to evolution tab', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('EVOLUTION'));

      await waitFor(() => {
        expect(screen.getByText('Births')).toBeInTheDocument();
        expect(screen.getByText('Deaths')).toBeInTheDocument();
        expect(screen.getByText('Net Change')).toBeInTheDocument();
      });
    });

    it('switches to patterns tab', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('PATTERNS'));

      await waitFor(() => {
        expect(screen.getByText('fallacy')).toBeInTheDocument();
        expect(screen.getByText('75% success')).toBeInTheDocument();
        expect(screen.getByText('12 uses')).toBeInTheDocument();
      });
    });

    it('preserves data when switching tabs', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      // Switch to patterns then back to traits
      fireEvent.click(screen.getByText('PATTERNS'));
      fireEvent.click(screen.getByText('EMERGENT TRAITS'));

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });
    });
  });

  describe('Pollinations Tab', () => {
    it('displays cross-pollination suggestions', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('POLLINATIONS'));

      await waitFor(() => {
        expect(screen.getByText(/claude-3-opus/)).toBeInTheDocument();
        expect(screen.getByText(/gemini-2.0-flash/)).toBeInTheDocument();
        expect(screen.getByText('+15%')).toBeInTheDocument(); // expected_improvement
      });
    });

    it('shows empty state when no pollinations', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/laboratory/cross-pollinations')) {
          return Promise.resolve({ ok: true, json: () => Promise.resolve({ suggestions: [] }) });
        }
        return Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
      });

      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);
      fireEvent.click(screen.getByText('POLLINATIONS'));

      await waitFor(() => {
        expect(screen.getByText(/No cross-pollination suggestions yet/)).toBeInTheDocument();
      });
    });
  });

  describe('Evolution Tab', () => {
    it('displays population stats grid', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('EVOLUTION'));

      await waitFor(() => {
        expect(screen.getByText('Births')).toBeInTheDocument();
        expect(screen.getByText('Deaths')).toBeInTheDocument();
        expect(screen.getByText('Net Change')).toBeInTheDocument();
      });
    });

    it('shows fitness change trend', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('EVOLUTION'));

      await waitFor(() => {
        expect(screen.getByText('Avg Fitness Change (Recent)')).toBeInTheDocument();
        expect(screen.getByText('+0.0245')).toBeInTheDocument();
      });
    });

    it('displays ledger integrity status', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('EVOLUTION'));

      await waitFor(() => {
        expect(screen.getByText('Ledger Integrity')).toBeInTheDocument();
        expect(screen.getByText('VERIFIED')).toBeInTheDocument();
      });
    });
  });

  describe('Patterns Tab', () => {
    it('displays critique patterns with success rates', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('PATTERNS'));

      await waitFor(() => {
        expect(screen.getByText(/Strawman argument detected/)).toBeInTheDocument();
        expect(screen.getByText('75% success')).toBeInTheDocument();
      });
    });

    it('shows suggested rebuttals', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('PATTERNS'));

      await waitFor(() => {
        expect(screen.getByText(/Address the actual argument/)).toBeInTheDocument();
      });
    });
  });

  describe('Error Handling', () => {
    it('shows partial failure message when some endpoints fail', async () => {
      mockFetch.mockImplementation((url: string) => {
        if (url.includes('/api/laboratory/emergent-traits')) {
          return Promise.resolve({
            ok: true,
            json: () => Promise.resolve({ emergent_traits: mockTraits }),
          });
        }
        // Other endpoints fail
        return Promise.resolve({ ok: false });
      });

      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText(/Some data failed to load/)).toBeInTheDocument();
      });

      // Should still show traits
      expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
    });

    it('has retry button on error', async () => {
      mockFetch.mockImplementation(() => Promise.resolve({ ok: false }));

      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText(/Some data failed to load/)).toBeInTheDocument();
      });

      // ErrorWithRetry component should be rendered
      expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
    });
  });

  describe('Refresh Functionality', () => {
    it('refreshes data when refresh button clicked', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      const initialCalls = mockFetch.mock.calls.length;

      fireEvent.click(screen.getByText('[REFRESH]'));

      await waitFor(() => {
        expect(mockFetch.mock.calls.length).toBeGreaterThan(initialCalls);
      });
    });

    it('disables refresh button while loading', async () => {
      mockFetch.mockImplementation(() => new Promise(() => {})); // Never resolves
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      const refreshButton = screen.getByText('[REFRESH]');
      expect(refreshButton).toBeDisabled();
    });
  });

  describe('Expand/Collapse', () => {
    it('collapses panel when collapse button clicked', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('[-]'));

      // Tab buttons should be hidden when collapsed
      expect(screen.queryByText('EMERGENT TRAITS')).not.toBeInTheDocument();
    });

    it('expands panel when expand button clicked', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      // Collapse first
      fireEvent.click(screen.getByText('[-]'));

      // Then expand
      fireEvent.click(screen.getByText('[+]'));

      await waitFor(() => {
        expect(screen.getByText('EMERGENT TRAITS')).toBeInTheDocument();
      });
    });

    it('shows help text when collapsed', async () => {
      setupSuccessfulFetch();
      renderWithProviders(<LaboratoryPanel apiBase="http://localhost:8080" />);

      await waitFor(() => {
        expect(screen.getByText('claude-3-opus')).toBeInTheDocument();
      });

      fireEvent.click(screen.getByText('[-]'));

      expect(screen.getByText(/Discovered specializations/)).toBeInTheDocument();
    });
  });
});
