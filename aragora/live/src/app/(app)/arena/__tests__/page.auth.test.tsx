import { render, waitFor } from '@testing-library/react';
import { useSearchParams } from 'next/navigation';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import ArenaPage from '../page';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));
jest.mock('@/components/DebateInput', () => ({ DebateInput: () => null }));
jest.mock('@/components/arena/TemplateSuggestions', () => ({ TemplateSuggestions: () => null }));
jest.mock('@/context/RightSidebarContext', () => ({
  useRightSidebar: () => ({ setContext: jest.fn(), clearContext: jest.fn() }),
}));
jest.mock('@/context/ToastContext', () => ({ useToast: () => ({ showSuccess: jest.fn() }) }));

const mockFetch = global.fetch as jest.Mock;

describe('ArenaPage authenticated requests', () => {
  beforeEach(() => {
    storeTestSession();
    (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams('template=custom-template'));
    mockFetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ debates: [] }) });
  });

  afterEach(() => {
    clearTestSession();
    (useSearchParams as jest.Mock).mockReturnValue(new URLSearchParams());
  });

  it('sends the session token with the recent debates and template requests', async () => {
    render(<ArenaPage />);

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    const bearer = `Bearer ${TEST_SESSION_TOKEN}`;
    expect(authHeaderOf(mockFetch, '/api/debates?limit=5')).toBe(bearer);
    expect(authHeaderOf(mockFetch, '/api/v1/templates/custom-template')).toBe(bearer);
  });
});
