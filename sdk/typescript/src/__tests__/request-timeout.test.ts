import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AragoraClient } from '../client';
import { AragoraError, ConnectionError, TimeoutError } from '../errors';

describe('HTTP attempt deadline ownership', () => {
  const fetchMock = vi.fn<typeof fetch>();
  let client: AragoraClient;

  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', fetchMock);
    fetchMock.mockReset();
    client = new AragoraClient({ baseUrl: 'https://api.example.test', timeout: 50, maxRetries: 3 });
  });

  afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  function observe<T>(promise: Promise<T>) {
    return promise.then(value => ({ value, error: undefined }),
      (error: unknown) => ({ value: undefined, error }));
  }

  // No extra timeout: the test transport owns only an abort listener. Completion
  // is controlled explicitly so a broken SDK cannot pass by waiting for the body.
  function stalledBody(status: number) {
    let finish!: (body: string) => void;
    fetchMock.mockImplementation(async (_url, init) => {
      const signal = init!.signal!;
      const text = new Promise<string>((resolve, reject) => {
        const abort = () => reject(signal.reason);
        signal.addEventListener('abort', abort, { once: true });
        finish = body => {
          signal.removeEventListener('abort', abort);
          resolve(body);
        };
      });
      return { ok: status < 400, status, statusText: 'unavailable',
        text: () => text, json: () => text.then(JSON.parse) } as Response;
    });
    return (body = '{}') => finish(body);
  }

  it.each([200, 400, 503])('keeps the deadline through a stalled HTTP %s body', async status => {
    const finish = stalledBody(status);
    const result = observe(client.post('/api/debate', { task: 'fixture' }));
    await vi.advanceTimersByTimeAsync(0);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(50);
    finish(); // Prevent a broken implementation leaving the assertion pending.
    expect((await result).error).toBeInstanceOf(TimeoutError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('times out before headers and removes the timer', async () => {
    fetchMock.mockImplementation((_url, init) => new Promise((_resolve, reject) => {
      init!.signal!.addEventListener('abort', () => reject(init!.signal!.reason), { once: true });
    }));
    const result = observe(client.get('/api/debate'));
    await vi.advanceTimersByTimeAsync(50);
    expect((await result).error).toBeInstanceOf(TimeoutError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cleans up immediately after fetch rejection without firing a late abort', async () => {
    const aborted = vi.fn();
    fetchMock.mockImplementation(async (_url, init) => {
      init!.signal!.addEventListener('abort', aborted);
      throw new TypeError('fetch failed');
    });
    expect((await observe(client.get('/api/debate'))).error).toBeInstanceOf(ConnectionError);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(100);
    expect(aborted).not.toHaveBeenCalled();
  });

  it.each([new Error('offline'), new Response('{}', { status: 503 })])(
    'clears the first attempt timer before backoff', async failure => {
      const sleep = vi.spyOn(client as unknown as { sleep(ms: number): Promise<void> }, 'sleep');
      sleep.mockImplementation(async () => { expect(vi.getTimerCount()).toBe(0); });
      fetchMock.mockImplementationOnce(async () => {
        if (failure instanceof Error) throw failure;
        return failure.clone();
      }).mockResolvedValue(new Response('{}'));
      expect((await observe(client.post('/api/debate', {}))).value).toEqual({});
      expect(sleep).toHaveBeenCalledExactlyOnceWith(1000);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it.each([
    ['json', '{"id":"ok"}', { id: 'ok' }],
    ['json', '', {}],
    ['text', '', ''],
    ['text', 'hello', 'hello'],
  ] as const)('cleans up a completed %s body', async (responseType, body, expected) => {
    const finish = stalledBody(200);
    const result = observe(client.request('POST', '/api/debate', { responseType }));
    await vi.advanceTimersByTimeAsync(49);
    finish(body);
    expect((await result).value).toEqual(expected);
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchMock.mock.calls[0][1]!.signal!.aborted).toBe(false);
  });

  it.each([new DOMException('unrelated abort', 'AbortError'), new TypeError('terminated'), null])(
    'preserves unrelated successful-body errors and cleans up', async error => {
      fetchMock.mockImplementation(async () => {
        const response = new Response('{}');
        vi.spyOn(response, 'text').mockRejectedValue(error);
        return response;
      });
      expect((await observe(client.post('/api/debate', {}))).error).toBe(error);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(vi.getTimerCount()).toBe(0);
    },
  );

  it('does not replay malformed success after a failed attempt', async () => {
    fetchMock.mockResolvedValueOnce(new Response('{}', { status: 503 }))
      .mockResolvedValueOnce(new Response('{bad'));
    const result = observe(client.post('/api/debate', {}));
    await vi.advanceTimersByTimeAsync(1000);
    expect((await result).error).toBeInstanceOf(SyntaxError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('keeps independent per-request body deadlines and overrides', async () => {
    const finish = stalledBody(200);
    const fast = observe(client.request('GET', '/fast', { timeout: 10 }));
    const slow = observe(client.request('GET', '/slow', { timeout: 80 }));
    await vi.advanceTimersByTimeAsync(10);
    expect(fetchMock.mock.calls[0][1]!.signal!.aborted).toBe(true);
    expect((await fast).error).toBeInstanceOf(TimeoutError);
    expect(fetchMock.mock.calls[1][1]!.signal!.aborted).toBe(false);
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(69);
    finish('{"ok":true}');
    expect((await slow).value).toEqual({ ok: true });
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not swallow an error-body abort or spend retry backoff', async () => {
    const finish = stalledBody(503);
    const result = observe(client.post('/api/debate', {}));
    await vi.advanceTimersByTimeAsync(50);
    finish('{"error":"busy"}');
    expect(fetchMock.mock.calls[0][1]!.signal!.aborted).toBe(true);
    expect((await result).error).toBeInstanceOf(TimeoutError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it.each([true, false])('honors completion/deadline ordering (completion first=%s)', async first => {
    const finish = stalledBody(200);
    if (first) setTimeout(() => finish(), 50);
    const result = observe(client.get('/api/debate'));
    if (!first) setTimeout(() => finish(), 50);
    await vi.advanceTimersByTimeAsync(50);
    const settled = await result;
    if (first) expect(settled.value).toEqual({});
    else expect(settled.error).toBeInstanceOf(TimeoutError);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('does not replay a body timeout after an earlier server failure', async () => {
    const finish = stalledBody(200);
    fetchMock.mockResolvedValueOnce(new Response('{}', { status: 503 }));
    const result = observe(client.post('/api/debate', {}));
    await vi.advanceTimersByTimeAsync(1050);
    finish();
    expect((await result).error).toBeInstanceOf(TimeoutError);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('retains malformed error-body fallback and attempt counts', async () => {
    fetchMock.mockImplementation(async () => new Response('invalid', { status: 503 }));
    const result = observe(client.post('/api/debate', {}));
    await vi.runAllTimersAsync();
    expect((await result).error).toBeInstanceOf(AragoraError);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(vi.getTimerCount()).toBe(0);
  });
});
