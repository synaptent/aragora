import { render, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import ForksPage from '../page';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));
jest.mock('@/components/AsciiBanner', () => ({ AsciiBannerCompact: () => null }));
jest.mock('@/components/ThemeToggle', () => ({ ThemeToggle: () => null }));
jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://backend.test' } }),
}));

const mockFetch = global.fetch as jest.Mock;

describe('ForksPage authenticated requests', () => {
  beforeEach(() => {
    storeTestSession();
    mockFetch.mockImplementation(async (input: string) => {
      if (String(input).includes('/fork-tree')) {
        return { ok: true, status: 200, json: async () => ({ forks: [] }) };
      }
      return {
        ok: true,
        status: 200,
        json: async () => ({ debates: [{ id: 'debate-a', task: 'Root task', agents: [] }] }),
      };
    });
  });

  afterEach(() => clearTestSession());

  it('sends the session token with the debate list and fork tree requests', async () => {
    render(<ForksPage />);

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    const bearer = `Bearer ${TEST_SESSION_TOKEN}`;
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/debates?has_forks=true')).toBe(bearer);
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/debates/debate-a/fork-tree')).toBe(bearer);
  });
});
