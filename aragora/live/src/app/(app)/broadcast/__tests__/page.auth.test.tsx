import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import BroadcastPage from '../page';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));
jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://backend.test' } }),
}));

const mockFetch = global.fetch as jest.Mock;

describe('BroadcastPage authenticated requests', () => {
  beforeEach(() => {
    storeTestSession();
    mockFetch.mockImplementation(async () => ({
      ok: true,
      status: 200,
      json: async () => ({
        episodes: [],
        debates: [{ id: 'debate-a', task: 'Org A debate', created_at: '2026-10-01T00:00:00Z' }],
        success: false,
        error: 'stub',
      }),
    }));
  });

  afterEach(() => clearTestSession());

  it('sends the session token when listing debates and generating an episode', async () => {
    render(<BroadcastPage />);

    const open = await screen.findByRole('button', { name: '[+ GENERATE NEW EPISODE]' });
    await waitFor(() => expect(open).not.toBeDisabled());
    fireEvent.click(open);

    await screen.findByRole('option', { name: /Org A debate/ });
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'debate-a' } });
    fireEvent.click(screen.getByRole('button', { name: 'GENERATE EPISODE' }));

    await waitFor(() => expect(authHeaderOf(mockFetch, '/broadcast/full', 'POST')).toBeDefined());
    const bearer = `Bearer ${TEST_SESSION_TOKEN}`;
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/debates?status=completed&limit=100')).toBe(bearer);
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/debates/debate-a/broadcast/full', 'POST')).toBe(bearer);
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/podcast/episodes?limit=1')).toBe(bearer);
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/podcast/episodes?limit=50')).toBe(bearer);
  });
});
