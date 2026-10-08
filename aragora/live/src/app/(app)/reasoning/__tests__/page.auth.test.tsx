import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import ReasoningPage from '../page';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));
jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://backend.test' } }),
}));

const mockFetch = global.fetch as jest.Mock;

describe('ReasoningPage authenticated requests', () => {
  beforeEach(() => {
    storeTestSession();
    mockFetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
  });

  afterEach(() => clearTestSession());

  it('sends the session token with the debate positions and belief network requests', async () => {
    render(<ReasoningPage />);

    fireEvent.change(screen.getByPlaceholderText('Enter debate ID...'), { target: { value: 'debate-a' } });
    fireEvent.click(screen.getByRole('button', { name: '[LOAD]' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(4));
    const bearer = `Bearer ${TEST_SESSION_TOKEN}`;
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/v1/debates/debate-a/positions')).toBe(bearer);
    expect(authHeaderOf(mockFetch, '/api/belief-network/debate-a/cruxes')).toBe(bearer);
    expect(authHeaderOf(mockFetch, '/api/belief-network/debate-a/load-bearing-claims')).toBe(bearer);
    expect(authHeaderOf(mockFetch, '/api/belief-network/debate-a/graph')).toBe(bearer);
  });
});
