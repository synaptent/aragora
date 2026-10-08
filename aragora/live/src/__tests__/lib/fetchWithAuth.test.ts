import { fetchWithAuth } from '@/lib/api';

const mockFetch = global.fetch as jest.Mock;

function storeSession(accessToken: string) {
  localStorage.setItem('aragora_tokens', JSON.stringify({ access_token: accessToken }));
}

function sentHeaders(): Record<string, string> {
  const init = mockFetch.mock.calls[0][1] as RequestInit | undefined;
  return (init?.headers ?? {}) as Record<string, string>;
}

describe('fetchWithAuth', () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch.mockReset();
    mockFetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({}) });
  });

  afterAll(() => {
    localStorage.clear();
  });

  it('adds the stored session as a Bearer token', async () => {
    storeSession('tok-a');

    await fetchWithAuth('http://localhost:8080/api/debates');

    expect(mockFetch).toHaveBeenCalledWith('http://localhost:8080/api/debates', {
      headers: { Authorization: 'Bearer tok-a' },
    });
  });

  it('returns the raw response so callers keep their own status handling', async () => {
    storeSession('tok-a');
    const response = { ok: false, status: 404, json: async () => ({ error: 'not found' }) };
    mockFetch.mockResolvedValueOnce(response);

    await expect(fetchWithAuth('/api/v1/debates/missing')).resolves.toBe(response);
  });

  it('keeps method, body, signal and existing headers', async () => {
    storeSession('tok-a');
    const controller = new AbortController();

    await fetchWithAuth('/api/debates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{"q":1}',
      signal: controller.signal,
    });

    const init = mockFetch.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe('POST');
    expect(init.body).toBe('{"q":1}');
    expect(init.signal).toBe(controller.signal);
    expect(sentHeaders()).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer tok-a',
    });
  });

  it('does not force a Content-Type, so FormData keeps its multipart boundary', async () => {
    storeSession('tok-a');
    const body = new FormData();
    body.append('file', new Blob(['x']), 'x.txt');

    await fetchWithAuth('/api/documents/upload', { method: 'POST', body });

    expect(sentHeaders()).toEqual({ Authorization: 'Bearer tok-a' });
    expect((mockFetch.mock.calls[0][1] as RequestInit).body).toBe(body);
  });

  it('accepts header tuples', async () => {
    storeSession('tok-a');

    await fetchWithAuth('/api/debates', { headers: [['X-Trace', 't1']] });

    expect(sentHeaders()).toEqual({ 'X-Trace': 't1', Authorization: 'Bearer tok-a' });
  });

  it('never overrides an explicit Authorization header', async () => {
    storeSession('tok-a');

    await fetchWithAuth('/api/debates', { headers: { authorization: 'Bearer other' } });

    expect(sentHeaders()).toEqual({ authorization: 'Bearer other' });
  });

  it('sends the request unchanged when there is no session', async () => {
    await fetchWithAuth('/api/debates', { method: 'HEAD' });

    expect(mockFetch).toHaveBeenCalledWith('/api/debates', { method: 'HEAD' });
  });

  it('ignores a corrupt stored session and keeps the plain single-argument call', async () => {
    localStorage.setItem('aragora_tokens', '{not json');

    await fetchWithAuth('/api/debates');

    expect(mockFetch.mock.calls[0]).toHaveLength(1);
    expect(mockFetch.mock.calls[0][0]).toBe('/api/debates');
  });
});
