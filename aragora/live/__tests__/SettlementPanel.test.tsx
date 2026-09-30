/**
 * Tests for the SettlementPanel dashboard component.
 *
 * Covers rendering with data, empty state, loading state, and status badge colors.
 */
import { render, screen } from '@testing-library/react';

// Mock next/link
jest.mock('next/link', () => {
  return ({
    children,
    href,
    ...props
  }: {
    children: React.ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  );
});

// Mock config
jest.mock('../src/config', () => ({
  API_BASE_URL: 'http://localhost:8080',
  WS_URL: 'ws://localhost:8765/ws',
}));

// Mock useSettlements hook -- routed via a mutable response object
let mockSettlementResponse: {
  summary: unknown;
  dueCount: number;
  isLoading: boolean;
  isValidating: boolean;
  error: Error | null;
  mutate: jest.Mock;
};

jest.mock('../src/hooks/useSettlements', () => ({ useSettlements: () => mockSettlementResponse }));

import { SettlementPanel } from '../src/components/dashboard/SettlementPanel';

function resetMock() {
  mockSettlementResponse = {
    summary: null,
    dueCount: 0,
    isLoading: false,
    isValidating: false,
    error: null,
    mutate: jest.fn(),
  };
}

describe('SettlementPanel', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    resetMock();
  });

  // -------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------

  it('renders loading state', () => {
    mockSettlementResponse.isLoading = true;

    render(<SettlementPanel />);

    expect(screen.getByTestId('settlement-panel-loading')).toBeInTheDocument();
    expect(screen.getByText('Loading...')).toBeInTheDocument();
    expect(screen.getByText(/SETTLEMENT STATUS/)).toBeInTheDocument();
  });

  // -------------------------------------------------------------------
  // Empty / error state
  // -------------------------------------------------------------------

  it('renders empty state when no data is available', () => {
    mockSettlementResponse.summary = null;
    mockSettlementResponse.error = null;

    render(<SettlementPanel />);

    expect(screen.getByTestId('settlement-panel')).toBeInTheDocument();
    expect(screen.getByText('No settlement data available')).toBeInTheDocument();
  });

  it('renders error state when fetch fails', () => {
    mockSettlementResponse.error = new Error('Network error');

    render(<SettlementPanel />);

    expect(screen.getByText('No settlement data available')).toBeInTheDocument();
  });

  it('renders empty recent message when total is 0', () => {
    mockSettlementResponse.summary = {
      total: 0,
      by_status: {},
      due_for_review: 0,
      average_confidence: 0,
      recent: [],
    };
    mockSettlementResponse.dueCount = 0;

    render(<SettlementPanel />);

    expect(screen.getByText(/No settlements yet/)).toBeInTheDocument();
  });

  // -------------------------------------------------------------------
  // Full data rendering
  // -------------------------------------------------------------------

  it('renders settlement summary with status counts', () => {
    mockSettlementResponse.summary = {
      total: 12,
      by_status: { settled: 5, due_review: 3, confirmed: 2, invalidated: 2 },
      due_for_review: 3,
      average_confidence: 0.82,
      recent: [],
    };
    mockSettlementResponse.dueCount = 3;

    render(<SettlementPanel />);

    // Header
    expect(screen.getByText(/SETTLEMENT STATUS/)).toBeInTheDocument();

    // Status counts
    expect(screen.getByText('5')).toBeInTheDocument(); // settled
    expect(screen.getByText('3')).toBeInTheDocument(); // due_review (count)
    // confirmed=2, invalidated=2 -- both render "2"
    const twos = screen.getAllByText('2');
    expect(twos).toHaveLength(2);

    // Labels
    expect(screen.getByText('SETTLED')).toBeInTheDocument();
    expect(screen.getByText('DUE REVIEW')).toBeInTheDocument();
    expect(screen.getByText('CONFIRMED')).toBeInTheDocument();
    expect(screen.getByText('INVALIDATED')).toBeInTheDocument();

    // Average confidence
    expect(screen.getByText('82%')).toBeInTheDocument();

    // Due badge in header
    expect(screen.getByTestId('due-review-badge')).toBeInTheDocument();
    expect(screen.getByText('3 DUE')).toBeInTheDocument();
  });

  it('does not render due badge when dueCount is 0', () => {
    mockSettlementResponse.summary = {
      total: 4,
      by_status: { settled: 4 },
      due_for_review: 0,
      average_confidence: 0.9,
      recent: [],
    };
    mockSettlementResponse.dueCount = 0;

    render(<SettlementPanel />);

    expect(screen.queryByTestId('due-review-badge')).not.toBeInTheDocument();
  });

  // -------------------------------------------------------------------
  // Recent settlements
  // -------------------------------------------------------------------

  it('renders recent settlement records with status badges', () => {
    const futureDate = new Date();
    futureDate.setDate(futureDate.getDate() + 7);

    mockSettlementResponse.summary = {
      total: 3,
      by_status: { settled: 1, confirmed: 1, invalidated: 1 },
      due_for_review: 0,
      average_confidence: 0.75,
      recent: [
        {
          debate_id: 'debate-abc123',
          settled_at: '2026-02-01T00:00:00Z',
          confidence: 0.9,
          falsifiers: [],
          alternatives: [],
          review_horizon: futureDate.toISOString(),
          cruxes: [],
          status: 'settled',
          review_notes: [],
          reviewed_at: null,
          reviewed_by: null,
        },
        {
          debate_id: 'debate-def456',
          settled_at: '2026-02-02T00:00:00Z',
          confidence: 0.65,
          falsifiers: [],
          alternatives: [],
          review_horizon: '2026-01-01T00:00:00Z',
          cruxes: [],
          status: 'invalidated',
          review_notes: [],
          reviewed_at: '2026-02-10T00:00:00Z',
          reviewed_by: 'admin',
        },
        {
          debate_id: 'debate-ghi789',
          settled_at: '2026-02-03T00:00:00Z',
          confidence: 0.88,
          falsifiers: [],
          alternatives: [],
          review_horizon: futureDate.toISOString(),
          cruxes: [],
          status: 'confirmed',
          review_notes: [],
          reviewed_at: '2026-02-15T00:00:00Z',
          reviewed_by: 'admin',
        },
      ],
    };
    mockSettlementResponse.dueCount = 0;

    render(<SettlementPanel />);

    // Recent settlements header
    expect(screen.getByText('Recent Settlements')).toBeInTheDocument();

    // Debate IDs (truncated)
    expect(screen.getByText('debate-abc...')).toBeInTheDocument();
    expect(screen.getByText('debate-def...')).toBeInTheDocument();
    expect(screen.getByText('debate-ghi...')).toBeInTheDocument();

    // Confidence values
    expect(screen.getByText('90%')).toBeInTheDocument();
    expect(screen.getByText('65%')).toBeInTheDocument();
    expect(screen.getByText('88%')).toBeInTheDocument();

    // Status badges present (SETTLED appears both in count label and badge)
    expect(screen.getByTestId('status-badge-settled')).toBeInTheDocument();
    expect(screen.getByTestId('status-badge-invalidated')).toBeInTheDocument();
    expect(screen.getByTestId('status-badge-confirmed')).toBeInTheDocument();
  });

  // -------------------------------------------------------------------
  // Status badge colors
  // -------------------------------------------------------------------

  it('applies correct colors to status badges', () => {
    const futureDate = new Date();
    futureDate.setDate(futureDate.getDate() + 30);

    mockSettlementResponse.summary = {
      total: 4,
      by_status: { settled: 1, due_review: 1, confirmed: 1, invalidated: 1 },
      due_for_review: 1,
      average_confidence: 0.8,
      recent: [
        {
          debate_id: 'settled-001',
          settled_at: '2026-02-01T00:00:00Z',
          confidence: 0.85,
          falsifiers: [],
          alternatives: [],
          review_horizon: futureDate.toISOString(),
          cruxes: [],
          status: 'settled',
          review_notes: [],
          reviewed_at: null,
          reviewed_by: null,
        },
        {
          debate_id: 'duereview-001',
          settled_at: '2026-02-01T00:00:00Z',
          confidence: 0.7,
          falsifiers: [],
          alternatives: [],
          review_horizon: '2026-01-15T00:00:00Z',
          cruxes: [],
          status: 'due_review',
          review_notes: [],
          reviewed_at: null,
          reviewed_by: null,
        },
        {
          debate_id: 'invalidated-001',
          settled_at: '2026-02-01T00:00:00Z',
          confidence: 0.4,
          falsifiers: [],
          alternatives: [],
          review_horizon: '2026-01-01T00:00:00Z',
          cruxes: [],
          status: 'invalidated',
          review_notes: [],
          reviewed_at: '2026-02-10T00:00:00Z',
          reviewed_by: 'admin',
        },
        {
          debate_id: 'confirmed-001',
          settled_at: '2026-02-01T00:00:00Z',
          confidence: 0.95,
          falsifiers: [],
          alternatives: [],
          review_horizon: futureDate.toISOString(),
          cruxes: [],
          status: 'confirmed',
          review_notes: [],
          reviewed_at: '2026-02-15T00:00:00Z',
          reviewed_by: 'admin',
        },
      ],
    };
    mockSettlementResponse.dueCount = 1;

    render(<SettlementPanel />);

    // Settled -> green
    const settledBadge = screen.getByTestId('status-badge-settled');
    expect(settledBadge.className).toContain('bg-green-500/20');
    expect(settledBadge.className).toContain('text-green-400');

    // Due review -> yellow
    const dueBadge = screen.getByTestId('status-badge-due_review');
    expect(dueBadge.className).toContain('bg-yellow-500/20');
    expect(dueBadge.className).toContain('text-yellow-400');

    // Invalidated -> red
    const invalidBadge = screen.getByTestId('status-badge-invalidated');
    expect(invalidBadge.className).toContain('bg-red-500/20');
    expect(invalidBadge.className).toContain('text-red-400');

    // Confirmed -> blue
    const confirmedBadge = screen.getByTestId('status-badge-confirmed');
    expect(confirmedBadge.className).toContain('bg-blue-500/20');
    expect(confirmedBadge.className).toContain('text-blue-400');
  });

  // -------------------------------------------------------------------
  // VIEW ALL link
  // -------------------------------------------------------------------

  it('renders VIEW ALL link pointing to /settlements', () => {
    mockSettlementResponse.summary = {
      total: 1,
      by_status: { settled: 1 },
      due_for_review: 0,
      average_confidence: 0.9,
      recent: [],
    };
    mockSettlementResponse.dueCount = 0;

    render(<SettlementPanel />);

    const link = screen.getByText('VIEW ALL');
    expect(link).toBeInTheDocument();
    expect(link.closest('a')?.getAttribute('href')).toBe('/settlements');
  });
});
