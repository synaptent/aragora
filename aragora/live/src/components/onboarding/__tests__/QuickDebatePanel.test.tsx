import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { TEST_SESSION_TOKEN, authHeaderOf, clearTestSession, storeTestSession } from '@/test-utils';
import { QuickDebatePanel } from '../QuickDebatePanel';

jest.mock('@/components/BackendSelector', () => ({
  getRuntimeBackendConfig: () => ({ config: { api: 'http://backend.test' } }),
}));

const mockFetch = global.fetch as jest.Mock;

describe('QuickDebatePanel', () => {
  beforeEach(() => {
    jest.useFakeTimers();
    storeTestSession();
    mockFetch.mockImplementation(async (_input: string, init?: RequestInit) =>
      init?.method === 'POST'
        ? { ok: true, status: 200, json: async () => ({ id: 'debate-q' }) }
        : { ok: true, status: 200, json: async () => ({ status: 'completed', verdict: 'Ship it.' }) },
    );
  });

  afterEach(() => {
    jest.useRealTimers();
    clearTestSession();
  });

  it('creates the debate and polls its result with the session token', async () => {
    render(<QuickDebatePanel />);

    fireEvent.change(screen.getByPlaceholderText('Enter a question for AI agents to debate...'), {
      target: { value: 'Should we expand to Berlin?' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'START DEBATE' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    await act(async () => {
      jest.advanceTimersByTime(3000);
    });

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    const bearer = `Bearer ${TEST_SESSION_TOKEN}`;
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/v1/debates', 'POST')).toBe(bearer);
    expect(authHeaderOf(mockFetch, 'http://backend.test/api/v1/debates/debate-q', 'GET')).toBe(bearer);
  });
});
