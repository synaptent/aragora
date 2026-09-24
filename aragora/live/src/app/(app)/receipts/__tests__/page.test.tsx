import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useSWRFetch } from '@/hooks/useSWRFetch';

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

const mockReplace = jest.fn();
let mockPathname = '/receipts';
let mockQuery = '';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn(), prefetch: jest.fn() }),
  usePathname: () => mockPathname,
  useSearchParams: () => new URLSearchParams(mockQuery),
}));

jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://localhost:8080' } }),
}));

jest.mock('@/components/ErrorWithRetry', () => ({
  ErrorWithRetry: ({ error }: { error: string }) => <div>{error}</div>,
}));

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('@/components/receipts', () => ({ DeliveryModal: () => null }));

jest.mock('@/hooks/useSWRFetch', () => ({ useSWRFetch: jest.fn() }));

jest.mock('@/hooks/useAuthenticatedFetch', () => ({
  useAuthFetch: () => ({
    getAuthHeaders: () => ({
      Authorization: 'Bearer test-token',
      'Content-Type': 'application/json',
    }),
  }),
}));

const ReceiptsPage = require('../page').default;

const mockUseSWRFetch = useSWRFetch as jest.Mock;
const mockFetch = jest.fn();
global.fetch = mockFetch as unknown as typeof fetch;

const mockClipboardWriteText = jest.fn();
const mockConfirm = jest.fn(() => true);

type ReceiptRecord = Record<string, unknown>;

function setSearchQuery(query: string) {
  mockQuery = query;
}

function configureListMocks({
  gauntletReceipts = [],
  v2Receipts = [
    {
      id: 'receipt-123',
      receipt_id: 'receipt-123',
      verdict: 'PASS',
      confidence: 0.91,
      created_at: '2026-03-25T12:34:56Z',
      input_summary: 'Receipt 123 summary',
    },
  ],
  gauntletResults = [],
}: {
  gauntletReceipts?: ReceiptRecord[];
  v2Receipts?: ReceiptRecord[];
  gauntletResults?: ReceiptRecord[];
} = {}) {
  mockUseSWRFetch.mockImplementation((endpoint: string | null) => {
    if (endpoint === '/api/v1/gauntlet/receipts?limit=50') {
      return {
        data: { receipts: gauntletReceipts },
        error: null,
        isLoading: false,
        mutate: jest.fn(),
      };
    }

    if (endpoint === '/api/v2/receipts?limit=50') {
      return { data: { receipts: v2Receipts }, error: null, isLoading: false, mutate: jest.fn() };
    }

    if (endpoint === '/api/gauntlet/results?limit=50') {
      return {
        data: { results: gauntletResults },
        error: null,
        isLoading: false,
        mutate: jest.fn(),
      };
    }

    return { data: null, error: null, isLoading: false, mutate: jest.fn() };
  });
}

function configureDetailFetch(overrides: ReceiptRecord = {}) {
  mockFetch.mockImplementation(async (input: string | URL | Request) => {
    const url = String(input);
    if (url === 'http://localhost:8080/api/v2/receipts/receipt-123') {
      return {
        ok: true,
        json: async () => ({
          receipt_id: 'receipt-123',
          gauntlet_id: 'run-123',
          timestamp: '2026-03-25T12:34:56Z',
          input_summary: 'Receipt 123 summary',
          input_hash: 'input-hash-123',
          risk_summary: { critical: 0, high: 0, medium: 1, low: 0 },
          attacks_attempted: 1,
          attacks_successful: 0,
          probes_run: 2,
          vulnerabilities_found: 1,
          verdict: 'PASS',
          confidence: 0.91,
          robustness_score: 0.82,
          vulnerability_details: [],
          verdict_reasoning: 'Looks good.',
          dissenting_views: [],
          provenance_chain: [],
          artifact_hash: 'artifact-hash-123',
          ...overrides,
        }),
      } as Response;
    }

    return { ok: false, status: 404, json: async () => ({}) } as Response;
  });
}

describe('ReceiptsPage', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPathname = '/receipts';
    setSearchQuery('');
    configureListMocks();
    configureDetailFetch();
    mockClipboardWriteText.mockResolvedValue(undefined);
    const clipboard = navigator.clipboard ?? { writeText: async (_text: string) => undefined };
    clipboard.writeText = mockClipboardWriteText;
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      writable: true,
      value: clipboard,
    });
    window.confirm = mockConfirm;
  });

  it('auto-opens receipt detail when the id query param matches a loaded receipt', async () => {
    setSearchQuery('id=receipt-123');

    render(<ReceiptsPage />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/v2/receipts/receipt-123',
        expect.objectContaining({ signal: expect.anything() }),
      );
    });

    expect(await screen.findByText('Decision Receipt')).toBeInTheDocument();
    expect(screen.getByText(/ID: receipt-123/)).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('updates the URL when a receipt is opened and clears it on back', async () => {
    const user = userEvent.setup();

    render(<ReceiptsPage />);

    await user.click(screen.getByRole('button', { name: /Receipt 123 summary/i }));

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith('/receipts?id=receipt-123');
    });

    await user.click(screen.getByRole('button', { name: 'Back' }));

    expect(mockReplace).toHaveBeenLastCalledWith('/receipts');
    expect(screen.queryByText('Decision Receipt')).not.toBeInTheDocument();
  });

  it('leaves the page on the list view when the id query param does not match', async () => {
    setSearchQuery('id=missing-receipt');

    render(<ReceiptsPage />);

    expect(await screen.findByRole('button', { name: /Receipt 123 summary/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(mockFetch).not.toHaveBeenCalled();
    });

    expect(screen.queryByText('Decision Receipt')).not.toBeInTheDocument();
  });

  it('renders receipts from both gauntlet and v2 feeds when both contain unique items', async () => {
    configureListMocks({
      gauntletReceipts: [
        {
          id: 'legacy-receipt-456',
          receipt_id: 'legacy-receipt-456',
          gauntlet_id: 'run-456',
          verdict: 'CONDITIONAL',
          confidence: 0.74,
          created_at: '2026-03-24T10:00:00Z',
          input_summary: 'Legacy receipt summary',
        },
      ],
    });

    render(<ReceiptsPage />);

    expect(await screen.findByRole('button', { name: /Receipt 123 summary/i })).toBeInTheDocument();
    expect(
      await screen.findByRole('button', { name: /Legacy receipt summary/i }),
    ).toBeInTheDocument();
  });

  it('prefers the v2 receipt detail endpoint when a receipt exists in both feeds', async () => {
    configureListMocks({
      gauntletReceipts: [
        {
          id: 'legacy-receipt-123',
          receipt_id: 'receipt-123',
          gauntlet_id: 'run-123',
          verdict: 'PASS',
          confidence: 0.9,
          created_at: '2026-03-25T12:34:56Z',
          input_summary: 'Legacy receipt 123 summary',
        },
      ],
    });

    const user = userEvent.setup();

    render(<ReceiptsPage />);

    await user.click(await screen.findByRole('button', { name: /Receipt 123 summary/i }));

    await waitFor(() => {
      expect(mockFetch.mock.calls[0]?.[0]).toBe(
        'http://localhost:8080/api/v2/receipts/receipt-123',
      );
    });
  });

  it('renders execution metrics and cost summary from the canonical receipt payload', async () => {
    configureDetailFetch({
      duration_seconds: 45.2,
      rounds_completed: 3,
      agents_involved: ['claude', 'codex'],
      cost_summary: {
        total_cost_usd: '0.0321',
        total_tokens_in: 1200,
        total_tokens_out: 340,
        total_calls: 4,
        per_agent: {
          claude: {
            agent_name: 'claude',
            total_cost_usd: '0.0200',
            total_tokens_in: 800,
            total_tokens_out: 200,
            call_count: 2,
          },
          codex: {
            agent_name: 'codex',
            total_cost_usd: '0.0121',
            total_tokens_in: 400,
            total_tokens_out: 140,
            call_count: 2,
          },
        },
      },
    });

    const user = userEvent.setup();

    render(<ReceiptsPage />);

    await user.click(await screen.findByRole('button', { name: /Receipt 123 summary/i }));

    expect(await screen.findByText('Execution Summary')).toBeInTheDocument();
    expect(screen.getByText('45.2s')).toBeInTheDocument();
    expect(screen.getByText('$0.0321')).toBeInTheDocument();
    expect(screen.getByText('1,540')).toBeInTheDocument();
    expect(screen.getByText('Per-Agent Cost')).toBeInTheDocument();
    expect(screen.getByText('claude')).toBeInTheDocument();
    expect(screen.getByText('codex')).toBeInTheDocument();
  });

  it('renders a view result handoff when the receipt detail includes a debate id', async () => {
    configureDetailFetch({ debate_id: 'debate-456' });

    const user = userEvent.setup();

    render(<ReceiptsPage />);

    await user.click(await screen.findByRole('button', { name: /Receipt 123 summary/i }));

    expect(await screen.findByRole('link', { name: 'View result' })).toHaveAttribute(
      'href',
      '/debates/debate-456',
    );
  });

  it('does not render a view result handoff when the debate id is malformed', async () => {
    configureDetailFetch({ debate_id: 'debate-456?tab=private' });

    const user = userEvent.setup();

    render(<ReceiptsPage />);

    await user.click(await screen.findByRole('button', { name: /Receipt 123 summary/i }));

    await screen.findByText('Decision Receipt');
    expect(screen.queryByRole('link', { name: 'View result' })).not.toBeInTheDocument();
  });

  it('renders structured dissent reasons from canonical receipt payloads', async () => {
    configureDetailFetch({
      dissenting_views: [
        {
          agent: 'gpt-4',
          reasons: ['Too risky', 'Too expensive'],
          alternative: 'Ship a narrower pilot first.',
        },
      ],
    });

    const user = userEvent.setup();

    render(<ReceiptsPage />);

    await user.click(await screen.findByRole('button', { name: /Receipt 123 summary/i }));

    expect(
      await screen.findByText(
        'gpt-4: Too risky; Too expensive Alternative: Ship a narrower pilot first.',
      ),
    ).toBeInTheDocument();
  });

  it('creates a receipt share link and copies the public token URL', async () => {
    const user = userEvent.setup();
    const detailImplementation = mockFetch.getMockImplementation();

    mockFetch.mockImplementation(async (input: string | URL | Request, init?: RequestInit) => {
      const url = String(input);
      if (url === 'http://localhost:8080/api/v2/receipts/receipt-123/share') {
        return {
          ok: true,
          json: async () => ({
            receipt_id: 'receipt-123',
            share_url: '/api/v2/receipts/share/share-token-123',
            token: 'share-token-123',
            expires_at: '2026-03-26T12:34:56Z',
          }),
        } as Response;
      }

      if (detailImplementation) {
        return detailImplementation(input, init) as Promise<Response>;
      }

      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });

    render(<ReceiptsPage />);

    await user.click(await screen.findByRole('button', { name: /Receipt 123 summary/i }));
    await screen.findByText('Decision Receipt');

    await user.click(screen.getByRole('button', { name: 'Share link' }));

    expect(mockConfirm).toHaveBeenCalledWith(
      expect.stringContaining('Create a public share link for this receipt?'),
    );

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'http://localhost:8080/api/v2/receipts/receipt-123/share',
        {
          method: 'POST',
          headers: { Authorization: 'Bearer test-token', 'Content-Type': 'application/json' },
          body: JSON.stringify({ expires_in_hours: 24 }),
        },
      );
    });

    await waitFor(() => {
      expect(mockClipboardWriteText).toHaveBeenCalledWith(
        'http://localhost:8080/api/v2/receipts/share/share-token-123',
      );
    });

    expect(await screen.findByRole('button', { name: 'Copied!' })).toBeInTheDocument();
  });

  it('shows a canonical proof link for fetched canonical receipts', async () => {
    const user = userEvent.setup();

    render(<ReceiptsPage />);

    await user.click(await screen.findByRole('button', { name: /Receipt 123 summary/i }));

    expect(await screen.findByRole('link', { name: 'Canonical proof' })).toHaveAttribute(
      'href',
      'http://localhost:8080/api/v2/receipts/receipt-123',
    );
  });

  it('uses the resolved fallback receipt endpoint for the canonical proof link', async () => {
    configureListMocks({
      v2Receipts: [],
      gauntletReceipts: [
        {
          id: 'legacy-receipt-123',
          receipt_id: 'receipt-123',
          gauntlet_id: 'run-123',
          created_at: '2026-03-25T12:34:56Z',
          input_summary: 'Legacy receipt 123 summary',
        },
      ],
      gauntletResults: [],
    });

    mockFetch.mockImplementation(async (input: string | URL | Request) => {
      const url = String(input);
      if (url === 'http://localhost:8080/api/v2/receipts/receipt-123') {
        return { ok: false, status: 404, json: async () => ({}) } as Response;
      }

      if (url === 'http://localhost:8080/api/v1/gauntlet/run-123/receipt') {
        return {
          ok: true,
          json: async () => ({
            receipt_id: 'receipt-123',
            gauntlet_id: 'run-123',
            timestamp: '2026-03-25T12:34:56Z',
            input_summary: 'Legacy receipt 123 summary',
            input_hash: 'input-hash-123',
            risk_summary: { critical: 0, high: 0, medium: 1, low: 0 },
            attacks_attempted: 1,
            attacks_successful: 0,
            probes_run: 2,
            vulnerabilities_found: 1,
            verdict: 'PASS',
            confidence: 0.91,
            robustness_score: 0.82,
            vulnerability_details: [],
            verdict_reasoning: 'Looks good.',
            dissenting_views: [],
            provenance_chain: [],
            artifact_hash: 'artifact-hash-123',
          }),
        } as Response;
      }

      return { ok: false, status: 404, json: async () => ({}) } as Response;
    });

    const user = userEvent.setup();

    render(<ReceiptsPage />);

    await user.click(await screen.findByRole('button', { name: /Legacy receipt 123 summary/i }));

    expect(await screen.findByRole('link', { name: 'Canonical proof' })).toHaveAttribute(
      'href',
      'http://localhost:8080/api/v1/gauntlet/run-123/receipt',
    );
  });

  it('renders blocked result-only entries with truthful next steps', async () => {
    configureListMocks({
      v2Receipts: [],
      gauntletReceipts: [],
      gauntletResults: [
        {
          id: 'run-blocked',
          gauntlet_id: 'run-blocked',
          debate_id: 'debate-blocked',
          status: 'blocked',
        },
      ],
    });

    render(<ReceiptsPage />);

    expect(await screen.findByText('BLOCKED')).toBeInTheDocument();
    expect(
      screen.getByText(
        /Execution is blocked upstream\. Fix provider access or the execution gate, then rerun to publish a canonical receipt\./i,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole('link', { name: 'Open debate to inspect the blocker' }),
    ).toHaveAttribute('href', '/debates/debate-blocked');
    expect(screen.queryByText(/ready for audit review/i)).not.toBeInTheDocument();
  });

  it('shows blocked guidance even when the row already has an input summary', async () => {
    configureListMocks({
      v2Receipts: [],
      gauntletReceipts: [],
      gauntletResults: [
        {
          id: 'run-blocked-with-summary',
          gauntlet_id: 'run-blocked-with-summary',
          status: 'blocked',
          input_summary: 'Provider credentials expired during execution',
        },
      ],
    });

    render(<ReceiptsPage />);

    expect(
      await screen.findByText(/Provider credentials expired during execution/i),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        /Execution is blocked upstream\. Fix provider access or the execution gate, then rerun to publish a canonical receipt\./i,
      ),
    ).toBeInTheDocument();
  });

  it('labels completed gauntlet results as partial until canonical proof exists', async () => {
    configureListMocks({
      v2Receipts: [],
      gauntletReceipts: [],
      gauntletResults: [
        {
          id: 'run-partial',
          gauntlet_id: 'run-partial',
          debate_id: 'debate-partial',
          status: 'completed',
        },
      ],
    });

    render(<ReceiptsPage />);

    expect(await screen.findByText('PARTIAL')).toBeInTheDocument();
    expect(
      screen.getByText(
        /Partial result only\. Canonical receipt and proof have not been published yet\./i,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open debate' })).toHaveAttribute(
      'href',
      '/debates/debate-partial',
    );
  });
});
