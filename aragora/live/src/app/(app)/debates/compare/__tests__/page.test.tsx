import { render, screen, waitFor } from '@testing-library/react';

import DebateComparePage from '../page';

const mockFetch = jest.fn();
const mockReplace = jest.fn();
const mockSearchParamsGet = jest.fn();

global.fetch = mockFetch as typeof fetch;

jest.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace }),
  useSearchParams: () => ({ get: mockSearchParamsGet }),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));

jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://backend.test' } }),
}));

jest.mock('@/utils/logger', () => ({ logger: { error: jest.fn() } }));

function jsonResponse(data: unknown, ok = true, status = 200): Response {
  return { ok, status, json: async () => data } as Response;
}

describe('DebateComparePage', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    mockSearchParamsGet.mockImplementation((key: string) => {
      if (key === 'left') return 'debate-alpha';
      if (key === 'right') return 'debate-beta';
      return null;
    });

    mockFetch.mockImplementation((input: string | URL | Request) => {
      const url = String(input);

      if (url === 'http://backend.test/api/v1/debates/debate-alpha/package') {
        return Promise.resolve(
          jsonResponse({
            id: 'debate-alpha',
            question: 'Should we ship the staged rollout?',
            verdict: 'APPROVED',
            confidence: 0.91,
            consensus_reached: true,
            agents: ['claude', 'codex'],
            rounds: 3,
            duration_seconds: 28,
            total_cost: 0.0042,
            final_answer: 'Ship the staged rollout.',
            explanation: 'Both agents preferred a guarded release.',
            next_steps: [{ action: 'Enable the flag for 10% of traffic.', priority: 'high' }],
            created_at: '2026-03-28T10:00:00Z',
          }),
        );
      }

      if (url === 'http://backend.test/api/v1/debates/debate-beta/package') {
        return Promise.resolve(
          jsonResponse({
            id: 'debate-beta',
            question: 'Should we ship the staged rollout?',
            verdict: 'NEEDS_REVIEW',
            confidence: 0.67,
            consensus_reached: false,
            agents: ['codex', 'gemini'],
            rounds: 4,
            duration_seconds: 44,
            total_cost: 0.0061,
            final_answer: 'Hold the rollout until the metrics gap is explained.',
            explanation: 'The second configuration surfaced unresolved risk.',
            next_steps: [{ action: 'Investigate the error-rate spike.', priority: 'high' }],
            created_at: '2026-03-28T11:00:00Z',
          }),
        );
      }

      return Promise.reject(new Error(`Unexpected fetch: ${url}`));
    });
  });

  it('loads two debate packages and renders the side-by-side outcome delta', async () => {
    render(<DebateComparePage />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'http://backend.test/api/v1/debates/debate-alpha/package',
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'http://backend.test/api/v1/debates/debate-beta/package',
        expect.objectContaining({ signal: expect.any(AbortSignal) }),
      );
    });

    expect(await screen.findByText(/outcome shift detected/i)).toBeInTheDocument();
    expect(screen.getByText(/configuration delta/i)).toBeInTheDocument();
    expect(screen.getAllByText('claude').length).toBeGreaterThan(0);
    expect(screen.getAllByText('gemini').length).toBeGreaterThan(0);
    expect(screen.getByText('Ship the staged rollout.')).toBeInTheDocument();
    expect(
      screen.getByText('Hold the rollout until the metrics gap is explained.'),
    ).toBeInTheDocument();
  });
});
