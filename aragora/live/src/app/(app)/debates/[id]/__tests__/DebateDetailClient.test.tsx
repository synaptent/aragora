import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import DebateDetailClient from '../DebateDetailClient';

const mockFetch = jest.fn();
const mockSetContext = jest.fn();
const mockClearContext = jest.fn();
const mockSearchParamsGet = jest.fn();
const mockClipboardWriteText = jest.fn();
const mockConfirm = jest.fn();
const mockGetAuthHeaders = jest.fn(() => ({
  'Content-Type': 'application/json',
  Authorization: 'Bearer test-token',
}));

global.fetch = mockFetch as unknown as typeof fetch;

jest.mock('next/navigation', () => ({
  useParams: () => ({ id: 'debate-123' }),
  useSearchParams: () => ({ get: mockSearchParamsGet }),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));

jest.mock('@/context/RightSidebarContext', () => ({
  useRightSidebar: () => ({ setContext: mockSetContext, clearContext: mockClearContext }),
}));

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://backend.test', ws: 'ws://backend.test' } }),
}));

jest.mock('@/hooks/useAuthenticatedFetch', () => ({
  useAuthFetch: () => ({ getAuthHeaders: mockGetAuthHeaders }),
}));

jest.mock('@/components/debates/DecisionPackageView', () => ({
  DecisionPackageView: () => <div data-testid="decision-package" />,
}));

jest.mock('@/components/debates/CostBreakdown', () => ({
  CostBreakdown: () => <div data-testid="cost-breakdown" />,
}));

jest.mock('@/components/debates/ArgumentGraph', () => ({
  ArgumentGraph: () => <div data-testid="argument-graph" />,
}));

jest.mock('@/components/ExplanationPanel', () => ({
  ExplanationPanel: () => <div data-testid="explanation-panel" />,
}));

jest.mock('@/components/debates/RelatedKnowledge', () => ({
  RelatedKnowledge: () => <div data-testid="related-knowledge" />,
}));

jest.mock('@/components/debate-viewer/InterventionPanel', () => ({
  InterventionPanel: () => <div data-testid="intervention-panel" />,
}));

jest.mock('@/hooks/debate-websocket', () => ({
  useDebateWebSocket: () => ({ messages: [], status: 'closed' }),
}));

jest.mock('@/components/debate/LiveDebateStream', () => ({
  LiveDebateStream: () => <div data-testid="live-debate-stream" />,
}));

jest.mock('../normalizeDecisionPackage', () => ({
  normalizeDecisionPackage: (data: unknown) => data,
}));

function jsonResponse(data: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => data, text: async () => JSON.stringify(data) } as Response;
}

describe('DebateDetailClient bridge actions', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockClipboardWriteText.mockResolvedValue(undefined);
    const clipboard = navigator.clipboard ?? { writeText: async (_text: string) => undefined };
    clipboard.writeText = mockClipboardWriteText;
    Object.defineProperty(navigator, 'clipboard', {
      value: clipboard,
      writable: true,
      configurable: true,
    });
    Object.defineProperty(window, 'confirm', {
      value: mockConfirm,
      writable: true,
      configurable: true,
    });
    mockConfirm.mockReturnValue(true);

    mockFetch.mockImplementation((input: string | URL | Request) => {
      const url = String(input);

      if (url === 'http://backend.test/api/v1/debates/debate-123') {
        return Promise.resolve(jsonResponse({ status: 'completed' }));
      }

      if (url === 'http://backend.test/api/v1/debates/debate-123/package') {
        return Promise.resolve(
          jsonResponse({
            id: 'debate-123',
            question: 'Should we bridge this decision?',
            verdict: 'Yes',
            confidence: 0.93,
            consensus_reached: true,
            agents: ['claude', 'codex'],
            rounds: 3,
            duration_seconds: 42,
            final_answer: 'Bridge it.',
            receipt: {
              receipt_id: 'receipt-123',
              hash: 'sha256:test-receipt',
              timestamp: '2026-03-26T20:00:00Z',
              signers: ['sig-1'],
            },
            cost_breakdown: null,
            total_cost: 0,
          }),
        );
      }

      if (url === 'http://backend.test/api/v1/debates/debate-123/bridge') {
        return Promise.resolve(jsonResponse({ success: true }));
      }

      if (url === 'http://backend.test/api/v1/debates/debate-123/share') {
        return Promise.resolve(
          jsonResponse({
            debate_id: 'debate-123',
            public_spectate: true,
            share_url: '/debate/debate-123',
            full_url: 'https://backend.test/debate/debate-123',
          }),
        );
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });

    mockSearchParamsGet.mockReturnValue(null);
  });

  it('sends authenticated headers when triggering the bridge action', async () => {
    const user = userEvent.setup();

    render(<DebateDetailClient />);

    await user.click(await screen.findByRole('button', { name: /export/i }));
    await user.click(screen.getByRole('button', { name: /create jira issues/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'http://backend.test/api/v1/debates/debate-123/bridge',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer test-token',
            'Content-Type': 'application/json',
          }),
          body: JSON.stringify({ target: 'jira' }),
        }),
      );
    });

    expect(mockGetAuthHeaders).toHaveBeenCalled();
    expect(await screen.findByText(/jira triggered/i)).toBeInTheDocument();
  });

  it('opens the receipt tab directly when requested in the URL', async () => {
    mockSearchParamsGet.mockImplementation((key: string) => (key === 'tab' ? 'receipt' : null));

    render(<DebateDetailClient />);

    expect(await screen.findByText(/cryptographic receipt/i)).toBeInTheDocument();
    expect(screen.getByText('sha256:test-receipt')).toBeInTheDocument();
  });

  it('links the current debate into the side-by-side compare flow', async () => {
    render(<DebateDetailClient />);

    expect(await screen.findAllByRole('link', { name: /compare/i })).not.toHaveLength(0);
    expect(screen.getByRole('link', { name: 'COMPARE' })).toHaveAttribute(
      'href',
      '/debates/compare?left=debate-123',
    );
  });

  it('deep-links to the exact receipt when the package includes a receipt id', async () => {
    render(<DebateDetailClient />);

    expect(await screen.findByRole('link', { name: 'VIEW RECEIPTS' })).toHaveAttribute(
      'href',
      '/receipts?id=receipt-123',
    );
  });

  it('sends auth headers when loading protected debate endpoints', async () => {
    render(<DebateDetailClient />);

    await screen.findByTestId('decision-package');

    expect(mockFetch).toHaveBeenCalledWith(
      'http://backend.test/api/v1/debates/debate-123',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer test-token',
          'Content-Type': 'application/json',
        }),
      }),
    );
    expect(mockFetch).toHaveBeenCalledWith(
      'http://backend.test/api/v1/debates/debate-123/package',
      expect.objectContaining({
        headers: expect.objectContaining({
          Authorization: 'Bearer test-token',
          'Content-Type': 'application/json',
        }),
      }),
    );
  });

  it('creates a public share link and copies the standalone debate URL', async () => {
    const user = userEvent.setup();

    render(<DebateDetailClient />);

    const [shareButton] = await screen.findAllByRole('button', { name: 'MAKE PUBLIC LINK' });
    await user.click(shareButton);

    expect(mockConfirm).toHaveBeenCalledWith(
      expect.stringContaining('Make this debate publicly viewable to anyone with the link?'),
    );

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'http://backend.test/api/v1/debates/debate-123/share',
        {
          method: 'POST',
          headers: { Authorization: 'Bearer test-token', 'Content-Type': 'application/json' },
        },
      );
    });

    await waitFor(() => {
      expect(mockClipboardWriteText).toHaveBeenCalledWith('http://localhost/debate/debate-123');
    });

    expect(screen.getAllByText(/copied!/i)).not.toHaveLength(0);
  });

  it('does not make the debate public when the share confirmation is declined', async () => {
    const user = userEvent.setup();
    mockConfirm.mockReturnValue(false);

    render(<DebateDetailClient />);

    const [shareButton] = await screen.findAllByRole('button', { name: 'MAKE PUBLIC LINK' });
    await user.click(shareButton);

    await waitFor(() => {
      expect(mockConfirm).toHaveBeenCalledWith(
        expect.stringContaining('Make this debate publicly viewable to anyone with the link?'),
      );
    });

    expect(mockFetch).not.toHaveBeenCalledWith(
      'http://backend.test/api/v1/debates/debate-123/share',
      expect.anything(),
    );
    expect(mockClipboardWriteText).not.toHaveBeenCalled();
  });
});
