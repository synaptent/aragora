import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import DebatesPage from '../(app)/debates/page';
import DebateDetailClient from '../(app)/debates/[id]/DebateDetailClient';
import { useDebateWebSocket } from '@/hooks/debate-websocket';

const mockFetch = jest.fn();
const mockPush = jest.fn();
const mockFetchRecentDebates = jest.fn();

global.fetch = mockFetch as typeof fetch;

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn(), prefetch: jest.fn() }),
  useParams: () => ({ id: 'debate-123' }),
  useSearchParams: () => ({ get: () => null }),
}));

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

jest.mock('@/components/PanelErrorBoundary', () => ({
  PanelErrorBoundary: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

jest.mock('@/context/RightSidebarContext', () => ({
  useRightSidebar: () => ({ setContext: jest.fn(), clearContext: jest.fn() }),
}));

jest.mock('@/utils/logger', () => ({
  logger: { warn: jest.fn(), error: jest.fn(), debug: jest.fn() },
}));

jest.mock('@/hooks/useAuthenticatedFetch', () => ({
  useAuthFetch: () => ({
    getAuthHeaders: () => ({
      'Content-Type': 'application/json',
      Authorization: 'Bearer test-token',
    }),
  }),
}));

jest.mock('@/utils/supabase', () => ({
  fetchRecentDebates: (...args: unknown[]) => mockFetchRecentDebates(...args),
}));

jest.mock('@/components/DebateInput', () => ({
  DebateInput: ({ apiBase }: { apiBase: string }) => (
    <div data-testid="debate-input" data-api-base={apiBase} />
  ),
}));

jest.mock('@/components/ui/EmptyState', () => ({
  DebatesEmptyState: () => <div data-testid="debates-empty-state" />,
}));

jest.mock('@/components/debates/DecisionPackageView', () => ({
  DecisionPackageView: () => <div data-testid="decision-package-view" />,
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

jest.mock('@/components/debate/LiveDebateStream', () => ({
  LiveDebateStream: () => <div data-testid="live-debate-stream" />,
}));

jest.mock('@/hooks/debate-websocket', () => ({
  useDebateWebSocket: jest.fn(() => ({
    status: 'connected',
    error: null,
    errorDetails: null,
    task: '',
    agents: [],
    messages: [],
    streamingMessages: new Map(),
    streamEvents: [],
    reconnectAttempt: 0,
    connectionQuality: null,
    isPolling: false,
    reconnect: jest.fn(),
  })),
}));

jest.mock('../(app)/debates/[id]/normalizeDecisionPackage', () => ({
  normalizeDecisionPackage: (data: Record<string, unknown>, id: string) => ({
    id,
    question: (data.question as string) ?? 'Should Aragora trust the selected backend?',
    verdict: (data.verdict as string) ?? 'Proceed',
    final_answer: (data.final_answer as string) ?? 'Proceed',
    consensus_reached: true,
    confidence: 0.93,
    created_at: '2026-03-26T00:00:00Z',
    agents: ['claude', 'gpt'],
    rounds: 2,
    duration_seconds: 12,
    receipt: null,
    arguments: [],
    cost_breakdown: [],
    total_cost: 0,
  }),
}));

function jsonResponse(data: unknown, init?: { status?: number; ok?: boolean }): Response {
  const status = init?.status ?? 200;
  const ok = init?.ok ?? (status >= 200 && status < 300);

  return {
    ok,
    status,
    headers: { get: () => 'application/json' },
    json: async () => data,
    text: async () => JSON.stringify(data),
  } as Response;
}

describe('runtime backend selection for debate archive surfaces', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('aragora-backend', 'production');
    mockFetch.mockReset();
    mockFetchRecentDebates.mockReset();
    mockPush.mockReset();
  });

  it('uses the selected backend for the debates archive fetch', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        debates: [
          {
            id: 'debate-123',
            question: 'Should the debate archive follow the selected backend?',
            agents: ['claude'],
            consensus_reached: true,
            confidence: 0.94,
            created_at: '2026-03-26T00:00:00Z',
          },
        ],
        has_more: false,
      }),
    );

    render(<DebatesPage />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.aragora.ai/api/v1/debates?limit=20&offset=0&sort=created_at:desc',
        expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
      );
    });
  });

  it('uses the selected backend for debate detail status, package, and live websocket config', async () => {
    mockFetch
      .mockResolvedValueOnce(jsonResponse({ status: 'completed' }))
      .mockResolvedValueOnce(
        jsonResponse({
          question: 'Should debate detail use the selected backend?',
          verdict: 'Yes',
          final_answer: 'Yes',
        }),
      );

    render(<DebateDetailClient />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenNthCalledWith(
        1,
        'https://api.aragora.ai/api/v1/debates/debate-123',
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.aragora.ai/api/v1/debates/debate-123/package',
        expect.objectContaining({
          headers: { Authorization: 'Bearer test-token', 'Content-Type': 'application/json' },
        }),
      );
    });

    expect(useDebateWebSocket).toHaveBeenCalledWith(
      expect.objectContaining({ debateId: 'debate-123', wsUrl: 'wss://api.aragora.ai/ws' }),
    );
  });

  it('launches the debate comparison route from two archived selections', async () => {
    const user = userEvent.setup();

    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        debates: [
          {
            id: 'debate-123',
            question: 'Should we ship the first configuration?',
            agents: ['claude'],
            consensus_reached: true,
            confidence: 0.94,
            created_at: '2026-03-26T00:00:00Z',
          },
          {
            id: 'debate-456',
            question: 'Should we ship the second configuration?',
            agents: ['codex'],
            consensus_reached: false,
            confidence: 0.61,
            created_at: '2026-03-26T01:00:00Z',
          },
        ],
        has_more: false,
      }),
    );

    render(<DebatesPage />);

    await screen.findByText(/should we ship the first configuration/i);

    const compareButtons = screen.getAllByRole('button', { name: /compare [ab]/i });
    await user.click(compareButtons[0]);
    await user.click(screen.getByRole('button', { name: /compare b/i }));
    await user.click(screen.getByRole('button', { name: /compare selected/i }));

    expect(mockPush).toHaveBeenCalledWith('/debates/compare?left=debate-123&right=debate-456');
  });
});
