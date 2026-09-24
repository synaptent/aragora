import { fireEvent, renderWithProviders, screen, waitFor } from '@/test-utils';

import PublicDemoPage from '../(standalone)/demo/page';
import TryPage from '../try/page';

const mockFetch = jest.fn();

global.fetch = mockFetch as typeof fetch;

jest.mock('next/navigation', () => ({ useSearchParams: () => ({ get: () => null }) }));

jest.mock('next/link', () => {
  return function MockLink({ children, href }: { children: React.ReactNode; href: string }) {
    return <a href={href}>{children}</a>;
  };
});

jest.mock('@/components/MatrixRain', () => ({
  Scanlines: () => <div data-testid="scanlines" />,
  CRTVignette: () => <div data-testid="crt-vignette" />,
}));

jest.mock('@/components/try/TeaserResult', () => ({
  TeaserResult: ({ verdict }: { verdict: string }) => <div>{verdict}</div>,
}));

jest.mock('react-markdown', () => {
  return function MockMarkdown({ children }: { children: React.ReactNode }) {
    return <div>{children}</div>;
  };
});

function jsonResponse(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => data,
  } as Response;
}

describe('runtime backend selection for public debate surfaces', () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem('aragora-backend', 'production');
    mockFetch.mockReset();
    window.scrollTo = jest.fn();
  });

  it('uses the selected backend for /try debate requests', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        verdict: 'Use the selected backend',
        confidence: 0.91,
        explanation: 'Production path confirmed.',
      }),
    );

    renderWithProviders(<TryPage />);
    fireEvent.change(screen.getByPlaceholderText('Enter your decision question...'), {
      target: { value: 'Should we use the production backend for public try flows?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /analyze/i }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.aragora.ai/api/v1/playground/debate',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });

  it('uses the selected backend for the standalone live demo run', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        id: 'debate-demo-1',
        topic: 'Demo topic',
        status: 'completed',
        rounds_used: 2,
        consensus_reached: true,
        confidence: 0.88,
        verdict: 'Proceed carefully',
        duration_seconds: 12,
        participants: ['claude', 'gpt'],
        proposals: { claude: 'yes', gpt: 'yes' },
        final_answer: 'Proceed carefully',
        receipt_hash: 'hash-123',
      }),
    );

    renderWithProviders(<PublicDemoPage />);

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.aragora.ai/api/v1/playground/debate',
        expect.objectContaining({ method: 'POST' }),
      );
    });
  });
});
