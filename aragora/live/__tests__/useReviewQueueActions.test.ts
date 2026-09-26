/**
 * Tests for the low-level action helpers in useReviewQueue (fetchBrief, settlePR).
 *
 * These do not exercise SWR — the hook itself is covered via the Page/List
 * integration tests with a stub mock.
 */

jest.mock('../src/config', () => ({
  API_BASE_URL: 'http://localhost:8080',
  WS_URL: 'ws://localhost:8765/ws',
}));

import { fetchBrief, settlePR } from '../src/hooks/useReviewQueue';

function mockFetchOnce(init: Partial<Response> & { jsonValue?: unknown; okStatus?: number }) {
  const status = init.okStatus ?? init.status ?? 200;
  (global.fetch as jest.Mock).mockImplementationOnce(
    async () =>
      ({
        ok: status >= 200 && status < 300,
        status,
        json: async () => init.jsonValue,
      }) as unknown as Response,
  );
}

describe('fetchBrief', () => {
  beforeEach(() => {
    (global.fetch as jest.Mock).mockReset();
  });

  it('returns the brief on 200', async () => {
    mockFetchOnce({
      okStatus: 200,
      jsonValue: {
        brief: { pr_number: 42, head_sha: 'abc', verdict: 'approve_candidate', confidence: 4 },
      },
    });
    const brief = await fetchBrief(42);
    expect(brief?.verdict).toBe('approve_candidate');
    expect((global.fetch as jest.Mock).mock.calls[0][0]).toContain(
      '/api/v1/review-queue/prs/42/brief',
    );
  });

  it('returns null on 404', async () => {
    mockFetchOnce({ okStatus: 404 });
    expect(await fetchBrief(999)).toBeNull();
  });

  it('throws on 500', async () => {
    mockFetchOnce({ okStatus: 500 });
    await expect(fetchBrief(1)).rejects.toThrow();
  });
});

describe('settlePR', () => {
  beforeEach(() => {
    (global.fetch as jest.Mock).mockReset();
  });

  it('posts approve with options', async () => {
    mockFetchOnce({ okStatus: 200, jsonValue: { status: 'ok' } });
    const result = await settlePR(5, 'approve', { note: 'LGTM', decisionSeconds: 12.5 });
    expect(result.status).toBe('ok');
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toContain('/api/v1/review-queue/prs/5/approve');
    const parsed = JSON.parse((init as RequestInit).body as string);
    expect(parsed).toEqual({ note: 'LGTM', decision_seconds: 12.5 });
    expect((init as RequestInit).method).toBe('POST');
  });

  it('throws with API error detail on non-2xx', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 400,
      json: async () => ({ error: 'bad request' }),
    } as unknown as Response);
    await expect(settlePR(5, 'request-changes', { reason: '' })).rejects.toThrow('bad request');
  });

  it('falls back to status code if response has no body', async () => {
    (global.fetch as jest.Mock).mockResolvedValueOnce({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error('no body');
      },
    } as unknown as Response);
    await expect(settlePR(1, 'defer', { reason: 'x' })).rejects.toThrow('502');
  });
});
