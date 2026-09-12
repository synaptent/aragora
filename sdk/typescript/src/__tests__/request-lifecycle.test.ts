import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AragoraClient } from '../client';
import { AragoraError, ConnectionError, TimeoutError } from '../errors';

describe('HTTP successful-response lifecycle', () => {
  let client: AragoraClient;
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.useFakeTimers();
    fetchMock.mockReset();
    vi.stubGlobal('fetch', fetchMock);
    client = new AragoraClient({
      baseUrl: 'https://api.example.test',
      maxRetries: 3,
    });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  // Attach rejection handling before advancing timers, including on broken base.
  async function outcome<T>(request: Promise<T>) {
    const settled = request.then(
      value => ({ value, error: undefined }),
      (error: unknown) => ({ value: undefined, error }),
    );
    await vi.runAllTimersAsync();
    return settled;
  }

  it.each(['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS', 'post'])(
    '%s does not replay a successful response containing invalid JSON',
    async method => {
      fetchMock.mockImplementation(async () => new Response('{invalid', { status: 200 }));
      const started = Date.now();
      const result = await outcome(client.request(method, '/api/v1/debates', {
        body: { task: 'deterministic test' },
      }));
      expect(result.error).toBeInstanceOf(SyntaxError);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(Date.now()).toBe(started); // No retry backoff either.
      expect(fetchMock.mock.calls[0][1]?.method).toBe(method);
    },
  );

  it.each([false, true])('preserves decoding errors with retryEnabled=%s', async retryEnabled => {
    client = new AragoraClient({ baseUrl: 'https://api.example.test', retryEnabled });
    const decodingError = new SyntaxError('invalid JSON body');
    fetchMock.mockResolvedValue(new Response('not JSON'));
    vi.spyOn(JSON, 'parse').mockImplementation(() => { throw decodingError; });
    const result = await outcome(client.post('/api/v1/debates', { task: 'example' }));
    expect(result.error).toBe(decodingError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  const bodyFailures: Array<[string, unknown]> = [
    ['ordinary error', new Error('body stream interrupted')],
    ['network-named TypeError', new TypeError('network body failure')],
    ['abort', new DOMException('body aborted', 'AbortError')],
    ['SDK server error', new AragoraError('body failed', 503, 'SERVICE_UNAVAILABLE')],
    ['string', 'body failed'],
    ['null', null],
  ];

  describe.each(['json', 'text'] as const)('%s response consumption', responseType => {
    it.each(bodyFailures)('preserves %s without reclassification or replay', async (_name, failure) => {
      fetchMock.mockImplementation(async () => {
        const response = new Response('unread');
        vi.spyOn(response, 'text').mockRejectedValue(failure);
        return response;
      });
      const result = await outcome(client.request('POST', '/api/v1/debates', { responseType }));
      expect(result.error).toBe(failure);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(0);
    });
  });

  it.each([
    ['object JSON', 'json', '{"ok":true}', 200, { ok: true }],
    ['array JSON', 'json', '[1,2]', 200, [1, 2]],
    ['null JSON', 'json', 'null', 200, null],
    ['empty JSON', 'json', '', 200, {}],
    ['no-content JSON', 'json', null, 204, {}],
    ['plain text', 'text', '{invalid', 200, '{invalid'],
    ['empty text', 'text', '', 200, ''],
    ['no-content text', 'text', null, 204, ''],
  ] as const)('preserves %s success', async (_label, responseType, body, status, expected) => {
    fetchMock.mockResolvedValue(new Response(body, { status }));
    const result = await outcome(client.request('GET', '/api/v1/debates', { responseType }));
    expect(result.error).toBeUndefined();
    expect(result.value).toEqual(expected);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each(['invalid JSON', 'body failure'])('stops after a retried request succeeds with %s', async kind => {
    const bodyError = new Error('read failed after retry');
    fetchMock.mockResolvedValueOnce(new Response('{"error":"busy"}', { status: 503 }));
    fetchMock.mockImplementation(async () => {
      const response = new Response('{invalid');
      if (kind === 'body failure') vi.spyOn(response, 'text').mockRejectedValue(bodyError);
      return response;
    });
    const started = Date.now();
    const result = await outcome(client.post('/api/v1/debates', {}));
    if (kind === 'body failure') expect(result.error).toBe(bodyError);
    else expect(result.error).toBeInstanceOf(SyntaxError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(Date.now() - started).toBe(1000);
  });

  it('retains server-error attempts and exponential backoff', async () => {
    fetchMock.mockImplementation(async () => new Response('{"error":"busy"}', { status: 503 }));
    const started = Date.now();
    const result = await outcome(client.post('/api/v1/debates', {}));
    expect(result.error).toBeInstanceOf(AragoraError);
    expect((result.error as AragoraError).statusCode).toBe(503);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(Date.now() - started).toBe(3000);
  });

  it.each([false, true])('retains server-error recovery (malformed error body=%s)', async malformed => {
    fetchMock
      .mockResolvedValueOnce(new Response(malformed ? 'bad JSON' : '{"error":"busy"}', { status: 500 }))
      .mockResolvedValueOnce(new Response('{"id":"created-once"}', { status: 201 }));
    const started = Date.now();
    const result = await outcome(client.post('/api/v1/debates', {}));
    expect(result).toEqual({ value: { id: 'created-once' }, error: undefined });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(Date.now() - started).toBe(1000);
  });

  it.each([400, 401, 429])('retains immediate HTTP %s rejection', async status => {
    fetchMock.mockImplementation(async () => new Response('bad JSON', { status }));
    const result = await outcome(client.post('/api/v1/debates', {}));
    expect(result.error).toBeInstanceOf(AragoraError);
    expect((result.error as AragoraError).statusCode).toBe(status);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ['network', new TypeError('Failed to fetch'), ConnectionError],
    ['timeout', new DOMException('aborted', 'AbortError'), TimeoutError],
  ] as const)('retains existing immediate %s classification before a response', async (_label, error, expected) => {
    fetchMock.mockRejectedValue(error);
    const result = await outcome(client.post('/api/v1/debates', {}));
    expect(result.error).toBeInstanceOf(expected);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('retains existing retries for other pre-response errors', async () => {
    const error = new Error('transport unavailable');
    fetchMock.mockRejectedValue(error);
    const result = await outcome(client.post('/api/v1/debates', {}));
    expect(result.error).toBe(error);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
