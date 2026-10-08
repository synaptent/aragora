import { render, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import PortalPage from '../page';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));
jest.mock('@/components/AsciiBanner', () => ({ AsciiBannerCompact: () => null }));
jest.mock('@/components/BackendSelector', () => ({
  useBackend: () => ({ config: { api: 'http://backend.test' } }),
}));
jest.mock('@/components/landing', () => ({ UseCaseSelector: () => null, QuickStartCards: () => null }));
jest.mock('@/components/ui/AdaptiveModeToggle', () => ({ AdaptiveModeToggle: () => null }));
jest.mock('@/context/AdaptiveModeContext', () => ({ useAdaptiveMode: () => ({ mode: 'simple' }) }));

const mockFetch = global.fetch as jest.Mock;

describe('PortalPage authenticated requests', () => {
  beforeEach(() => {
    storeTestSession();
    mockFetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ debates: [] }) });
  });

  afterEach(() => clearTestSession());

  it('sends the session token with the live debates preview request', async () => {
    render(<PortalPage />);

    await waitFor(() => expect(mockFetch).toHaveBeenCalled());
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/debates?limit=5&status=active')).toBe(
      `Bearer ${TEST_SESSION_TOKEN}`,
    );
  });
});
