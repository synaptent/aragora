import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import ArgumentAnalysisPage from '../page';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a>,
}));
jest.mock('@/components/MatrixRain', () => ({ Scanlines: () => null, CRTVignette: () => null }));
jest.mock('@/components/visualization/ArgumentMap', () => ({ ArgumentMap: () => null }));
jest.mock('@/components/ExplainabilityPanel', () => ({ ExplainabilityPanel: () => null }));

const mockFetch = global.fetch as jest.Mock;

describe('ArgumentAnalysisPage authenticated requests', () => {
  beforeEach(() => {
    storeTestSession();
    mockFetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) });
  });

  afterEach(() => clearTestSession());

  it('sends the session token with the argument graph and graph stats requests', async () => {
    render(<ArgumentAnalysisPage />);

    fireEvent.change(screen.getByPlaceholderText('Enter debate ID...'), { target: { value: 'debate-a' } });
    fireEvent.click(screen.getByRole('button', { name: '[LOAD]' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(authHeaderOf(mockFetch, '/api/v1/debates/debate-a/argument-graph')).toBe(`Bearer ${TEST_SESSION_TOKEN}`);
    expect(authHeaderOf(mockFetch, '/api/v1/debates/debate-a/graph/stats')).toBe(`Bearer ${TEST_SESSION_TOKEN}`);
  });
});
