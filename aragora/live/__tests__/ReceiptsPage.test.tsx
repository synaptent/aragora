import type { ReactNode } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

jest.mock('next/link', () => {
  return ({
    children,
    href,
    ...props
  }: {
    children: ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  );
});

jest.mock('../src/config', () => ({
  API_BASE_URL: 'http://localhost:8080',
  WS_URL: 'ws://localhost:8765/ws',
}));

jest.mock('../src/components/MatrixRain', () => ({
  Scanlines: () => null,
  CRTVignette: () => null,
}));

jest.mock('../src/components/BackendSelector', () => ({
  BackendSelector: () => <div>Backend</div>,
  useBackend: () => ({ config: { api: 'http://localhost:8080', ws: 'ws://localhost:8765' } }),
}));

jest.mock('../src/components/ErrorWithRetry', () => ({
  ErrorWithRetry: ({ error, onRetry }: { error: string; onRetry: () => void }) => (
    <div data-testid="error-retry">
      <span>{error}</span>
      <button onClick={onRetry}>Retry</button>
    </div>
  ),
}));

jest.mock('../src/components/receipts', () => ({ DeliveryModal: () => null }));

jest.mock('../src/utils/logger', () => ({
  logger: { warn: jest.fn(), error: jest.fn(), info: jest.fn(), debug: jest.fn() },
}));

const mockUseSWRFetch = jest.fn();
jest.mock('../src/hooks/useSWRFetch', () => ({
  useSWRFetch: (...args: unknown[]) => mockUseSWRFetch(...args),
}));

jest.mock('../src/hooks/useAuthenticatedFetch', () => ({
  useAuthFetch: () => ({
    getAuthHeaders: () => ({
      Authorization: 'Bearer test-token',
      'Content-Type': 'application/json',
    }),
  }),
}));

const ReceiptsPage = require('../src/app/(app)/receipts/page').default;

type HookResult = {
  data: Record<string, unknown> | null;
  error: Error | null;
  isLoading: boolean;
  mutate: jest.Mock;
};

const mockMutate = jest.fn();
const originalFetch = global.fetch;
const originalCreateObjectUrl = URL.createObjectURL;
const originalRevokeObjectUrl = URL.revokeObjectURL;
const originalAnchorClick = HTMLAnchorElement.prototype.click;

function hookResult(overrides: Partial<HookResult> = {}): HookResult {
  return { data: null, error: null, isLoading: false, mutate: mockMutate, ...overrides };
}

function queueHookResponses(responses: [HookResult, HookResult, HookResult]) {
  let callIndex = 0;
  mockUseSWRFetch.mockImplementation(() => {
    const response = responses[callIndex % responses.length] ?? hookResult();
    callIndex += 1;
    return response;
  });
}

describe('ReceiptsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    global.fetch = jest.fn();
    URL.createObjectURL = jest.fn(() => 'blob:receipt');
    URL.revokeObjectURL = jest.fn();
    HTMLAnchorElement.prototype.click = jest.fn();
  });

  afterAll(() => {
    global.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectUrl;
    URL.revokeObjectURL = originalRevokeObjectUrl;
    HTMLAnchorElement.prototype.click = originalAnchorClick;
  });

  it('loads gauntlet receipt summaries from the live receipts endpoint first', async () => {
    queueHookResponses([
      hookResult({
        data: {
          receipts: [
            {
              id: 'receipt-abc123456789',
              receipt_id: 'receipt-abc123456789',
              run_id: 'gauntlet-123',
              verdict: 'APPROVED',
              created_at: '2026-03-01T00:00:00Z',
              input_summary: 'Review deployment rollback plan',
              confidence: 0.91,
              metadata: { risk_level: 'HIGH' },
            },
          ],
        },
      }),
      hookResult(),
      hookResult(),
    ]);

    render(<ReceiptsPage />);

    expect(mockUseSWRFetch).toHaveBeenCalledWith(
      '/api/v1/gauntlet/receipts?limit=50',
      expect.objectContaining({ refreshInterval: 30000, baseUrl: 'http://localhost:8080' }),
    );

    await waitFor(() => {
      expect(screen.getByText('Review deployment rollback plan')).toBeInTheDocument();
      expect(screen.getAllByText('PASS').length).toBeGreaterThan(0);
      expect(screen.getByText('Risk: HIGH')).toBeInTheDocument();
    });
  });

  it('falls back to v2 receipts when the gauntlet summary list is empty', async () => {
    const expectedDate = new Date(1_700_000_000 * 1000).toLocaleDateString();

    queueHookResponses([
      hookResult({ data: { receipts: [] } }),
      hookResult({
        data: {
          receipts: [
            {
              receipt_id: 'receipt-001234567890',
              gauntlet_id: 'gauntlet-001',
              verdict: 'APPROVED_WITH_CONDITIONS',
              created_at: 1_700_000_000,
              risk_level: 'MEDIUM',
              confidence: 0.85,
            },
          ],
        },
      }),
      hookResult(),
    ]);

    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getAllByText('CONDITIONAL').length).toBeGreaterThan(0);
      expect(screen.getByText('Risk: MEDIUM')).toBeInTheDocument();
      expect(screen.getByText(expectedDate)).toBeInTheDocument();
    });
  });

  it('falls back to gauntlet results when receipt endpoints have no entries', async () => {
    queueHookResponses([
      hookResult({ data: { receipts: [] } }),
      hookResult({ data: { receipts: [] } }),
      hookResult({
        data: {
          results: [
            {
              id: 'gauntlet-running-123',
              status: 'running',
              verdict: 'FAIL',
              created_at: '2026-03-01T00:00:00Z',
              input_summary: 'Still executing',
            },
          ],
        },
      }),
    ]);

    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByText('Still executing')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /Still executing/i })).toBeNull();
    });
  });

  it('shows the empty state when all live sources are empty', async () => {
    queueHookResponses([
      hookResult({ data: { receipts: [] } }),
      hookResult({ data: { receipts: [] } }),
      hookResult({ data: { results: [] } }),
    ]);

    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByText(/No decision receipts yet/)).toBeInTheDocument();
      expect(screen.getByText('Ask the Oracle').closest('a')).toHaveAttribute('href', '/oracle');
      expect(screen.getByText('Start a debate').closest('a')).toHaveAttribute('href', '/debate');
    });
  });

  it('opens receipt detail through the v2 receipt endpoint and normalizes the payload', async () => {
    queueHookResponses([
      hookResult({
        data: {
          receipts: [
            {
              id: 'receipt-123',
              receipt_id: 'receipt-123',
              run_id: 'gauntlet-123',
              verdict: 'APPROVED',
              created_at: '2026-03-01T00:00:00Z',
              input_summary: 'Review deployment rollback plan',
            },
          ],
        },
      }),
      hookResult(),
      hookResult(),
    ]);

    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        receipt_id: 'receipt-123',
        gauntlet_id: 'gauntlet-123',
        verdict: 'APPROVED',
        confidence: 0.92,
        risk_level: 'HIGH',
        critical_count: 1,
        high_count: 2,
        low_count: 1,
        input_summary: 'Review deployment rollback plan',
        checksum: 'hash-123',
        findings: [
          {
            id: 'finding-1',
            title: 'Sandbox escape',
            severity: 'critical',
            description: 'Need tighter isolation',
          },
        ],
        provenance_chain: [
          {
            timestamp: '2026-03-01T00:00:00Z',
            event_type: 'ingested',
            agent: 'critic-1',
            description: 'Stored in receipt ledger',
            evidence_hash: 'abc12345',
          },
        ],
      }),
    });

    render(<ReceiptsPage />);

    fireEvent.click(await screen.findByText('Review deployment rollback plan'));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/v2/receipts/receipt-123',
        expect.any(Object),
      );
      expect(screen.getByText('Decision Receipt')).toBeInTheDocument();
      expect(screen.getByText('Sandbox escape')).toBeInTheDocument();
      expect(screen.getByText('PASS')).toBeInTheDocument();
      expect(screen.getByText('ingested')).toBeInTheDocument();
    });
  });

  it('exports via the corrected v2 export route when a receipt only has a receipt id', async () => {
    queueHookResponses([
      hookResult({ data: { receipts: [] } }),
      hookResult({
        data: {
          receipts: [
            {
              receipt_id: 'receipt-456',
              verdict: 'APPROVED',
              created_at: '2026-03-01T00:00:00Z',
              input_summary: 'Receipt from v2 store',
            },
          ],
        },
      }),
      hookResult(),
    ]);

    (global.fetch as jest.Mock)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          receipt_id: 'receipt-456',
          verdict: 'APPROVED',
          confidence: 0.8,
          input_summary: 'Receipt from v2 store',
          checksum: 'hash-456',
        }),
      })
      .mockResolvedValueOnce({
        ok: true,
        blob: async () => new Blob(['{}'], { type: 'application/json' }),
      });

    render(<ReceiptsPage />);

    fireEvent.click(await screen.findByText('Receipt from v2 store'));

    await screen.findByText('Decision Receipt');
    fireEvent.click(screen.getByText('JSON'));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenNthCalledWith(
        1,
        'http://localhost:8080/api/v2/receipts/receipt-456',
        expect.any(Object),
      );
      expect(global.fetch).toHaveBeenNthCalledWith(
        2,
        'http://localhost:8080/api/v2/receipts/receipt-456/export?format=json&raw=true',
        expect.any(Object),
      );
      expect(URL.createObjectURL).toHaveBeenCalled();
      expect(HTMLAnchorElement.prototype.click).toHaveBeenCalled();
    });
  });

  it('shows a retryable error when every live source fails', async () => {
    queueHookResponses([
      hookResult({ error: new Error('gauntlet down') }),
      hookResult({ error: new Error('v2 down') }),
      hookResult({ error: new Error('results down') }),
    ]);

    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(screen.getByTestId('error-retry')).toBeInTheDocument();
      expect(screen.getByText('gauntlet down')).toBeInTheDocument();
    });
  });
});
