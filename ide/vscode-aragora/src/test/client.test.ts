/**
 * Tests for the resilient API client (src/client.ts): timeout, retry with
 * backoff for idempotent requests, and the circuit breaker.
 */

import {
  AragoraHttpError,
  AragoraTimeoutError,
  CircuitBreaker,
  CircuitOpenError,
  ResilientHttpClient,
  type ClientOptions,
  type Transport,
  type TransportInit,
  type TransportResponse,
} from '../client';

function respond(status: number, body: unknown = {}): TransportResponse {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  return { ok: status >= 200 && status < 300, status, text: async () => text };
}

/** A transport that answers with `responses` in order and records each call. */
function scriptedTransport(...responses: Array<TransportResponse | Error>) {
  const calls: Array<{ url: string; init: TransportInit; at: number }> = [];
  const transport: Transport = async (url, init) => {
    calls.push({ url, init, at: Date.now() });
    const next = responses[Math.min(calls.length - 1, responses.length - 1)];
    if (next instanceof Error) throw next;
    return next;
  };
  return { transport, calls };
}

/** Never answers, but honours the abort signal the way fetch does. */
function hangingTransport() {
  const signals: AbortSignal[] = [];
  const transport: Transport = (_url, init) => {
    signals.push(init.signal);
    return new Promise<TransportResponse>((_resolve, reject) => {
      init.signal.addEventListener('abort', () => {
        const error = new Error('This operation was aborted');
        error.name = 'AbortError';
        reject(error);
      });
    });
  };
  return { transport, signals };
}

function client(transport: Transport, options: Partial<ClientOptions> = {}): ResilientHttpClient {
  return new ResilientHttpClient({ baseUrl: 'http://api.test', transport, ...options });
}

/** Settles `promise` into a result so fake-timer loops can drive it to completion. */
async function settle<T>(promise: Promise<T>): Promise<{ value?: T; error?: unknown }> {
  const outcome = promise.then(
    (value) => ({ value }),
    (error: unknown) => ({ error }),
  );
  await jest.runAllTimersAsync();
  return outcome;
}

describe('ResilientHttpClient', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('requests', () => {
    it('sends JSON headers and the bearer token and parses the JSON body', async () => {
      const { transport, calls } = scriptedTransport(respond(200, { debates: [] }));
      const api = client(transport, { apiKey: 'secret-key' });

      await expect(api.request('/api/debates', { method: 'POST', body: '{}' })).resolves.toEqual({
        debates: [],
      });

      expect(calls).toHaveLength(1);
      expect(calls[0].url).toBe('http://api.test/api/debates');
      expect(calls[0].init.method).toBe('POST');
      expect(calls[0].init.body).toBe('{}');
      expect(calls[0].init.headers).toEqual({
        'Content-Type': 'application/json',
        Authorization: 'Bearer secret-key',
      });
    });

    it('omits Authorization without an API key and defaults to GET', async () => {
      const { transport, calls } = scriptedTransport(respond(200));

      await client(transport).request('/api/agents');

      expect(calls[0].init.method).toBe('GET');
      expect(calls[0].init.headers).toEqual({ 'Content-Type': 'application/json' });
    });

    it('raises AragoraHttpError with the status and body for a non-2xx answer', async () => {
      const { transport } = scriptedTransport(respond(404, 'not found'));

      const { error } = await settle(client(transport).request('/api/debates/missing'));

      expect(error).toBeInstanceOf(AragoraHttpError);
      expect(error).toMatchObject({ status: 404, body: 'not found' });
      expect((error as Error).message).toBe('API Error: 404 - not found');
    });
  });

  describe('timeout', () => {
    it('rejects a never-answering request with AragoraTimeoutError after timeoutMs', async () => {
      const { transport, signals } = hangingTransport();
      const api = client(transport, { timeoutMs: 1000, maxAttempts: 1 });

      let settled = false;
      const pending = api.request('/api/slow');
      const outcome = pending.then(
        () => 'resolved',
        (error: unknown) => error,
      );
      void outcome.then(() => {
        settled = true;
      });

      await jest.advanceTimersByTimeAsync(999);
      expect(settled).toBe(false);
      expect(signals[0].aborted).toBe(false);

      await jest.advanceTimersByTimeAsync(1);
      const error = await outcome;

      expect(settled).toBe(true);
      expect(error).toBeInstanceOf(AragoraTimeoutError);
      expect(error).toMatchObject({
        name: 'AragoraTimeoutError',
        method: 'GET',
        path: '/api/slow',
        timeoutMs: 1000,
      });
      expect((error as Error).message).toBe('GET /api/slow timed out after 1000 ms');
      expect(signals[0].aborted).toBe(true);
    });

    it('times out even when the transport ignores the abort signal', async () => {
      const transport: Transport = () => new Promise<TransportResponse>(() => undefined);

      const { error } = await settle(
        client(transport, { timeoutMs: 250, maxAttempts: 1 }).request('/api/ignored'),
      );

      expect(error).toBeInstanceOf(AragoraTimeoutError);
      expect(Date.now()).toBeGreaterThanOrEqual(250);
    });

    it('covers reading the body, not only the response headers', async () => {
      const slowBody: TransportResponse = {
        ok: true,
        status: 200,
        text: () => new Promise<string>(() => undefined),
      };
      const { transport } = scriptedTransport(slowBody);

      const { error } = await settle(
        client(transport, { timeoutMs: 500, maxAttempts: 1 }).request('/api/body'),
      );

      expect(error).toBeInstanceOf(AragoraTimeoutError);
    });
  });

  describe('retry', () => {
    it('retries a failing GET exactly maxAttempts times with increasing backoff', async () => {
      const { transport, calls } = scriptedTransport(respond(503, 'unavailable'));
      const api = client(transport, { maxAttempts: 4, backoffBaseMs: 100 });

      const { error } = await settle(api.request('/api/agents'));

      expect(error).toBeInstanceOf(AragoraHttpError);
      expect((error as AragoraHttpError).status).toBe(503);
      expect(calls).toHaveLength(4);
      const gaps = calls.slice(1).map((call, index) => call.at - calls[index].at);
      expect(gaps).toEqual([100, 200, 400]);
      for (let i = 1; i < gaps.length; i++) {
        expect(gaps[i]).toBeGreaterThan(gaps[i - 1]);
      }
    });

    it('caps the backoff at backoffMaxMs', async () => {
      const { transport, calls } = scriptedTransport(respond(500));
      const api = client(transport, { maxAttempts: 5, backoffBaseMs: 100, backoffMaxMs: 250 });

      await settle(api.request('/api/agents'));

      const gaps = calls.slice(1).map((call, index) => call.at - calls[index].at);
      expect(gaps).toEqual([100, 200, 250, 250]);
    });

    it('returns the first successful answer after transient failures', async () => {
      const { transport, calls } = scriptedTransport(
        respond(503),
        new TypeError('fetch failed'),
        respond(200, { agents: ['claude'] }),
      );

      const { value } = await settle(client(transport, { maxAttempts: 3 }).request('/api/agents'));

      expect(value).toEqual({ agents: ['claude'] });
      expect(calls).toHaveLength(3);
    });

    it('retries a timed-out GET', async () => {
      const { transport, signals } = hangingTransport();

      const { error } = await settle(
        client(transport, { timeoutMs: 100, maxAttempts: 2 }).request('/api/slow'),
      );

      expect(error).toBeInstanceOf(AragoraTimeoutError);
      expect(signals).toHaveLength(2);
    });

    it('does not retry a GET that failed with a client error', async () => {
      const { transport, calls } = scriptedTransport(respond(400, 'bad request'));

      const { error } = await settle(client(transport, { maxAttempts: 3 }).request('/api/x'));

      expect((error as AragoraHttpError).status).toBe(400);
      expect(calls).toHaveLength(1);
    });

    it.each(['POST', 'PUT', 'PATCH', 'DELETE'])(
      'never retries a failing %s request',
      async (method) => {
        const { transport, calls } = scriptedTransport(respond(503));

        const { error } = await settle(
          client(transport, { maxAttempts: 5 }).request('/api/tasks', { method }),
        );

        expect(error).toBeInstanceOf(AragoraHttpError);
        expect(calls).toHaveLength(1);
      },
    );

    it('never retries a POST after a network error or timeout', async () => {
      const network = scriptedTransport(new TypeError('fetch failed'));
      const networkResult = await settle(
        client(network.transport, { maxAttempts: 5 }).request('/api/debates', { method: 'POST' }),
      );
      expect(networkResult.error).toBeInstanceOf(TypeError);
      expect(network.calls).toHaveLength(1);

      const hanging = hangingTransport();
      const timeoutResult = await settle(
        client(hanging.transport, { maxAttempts: 5, timeoutMs: 100 }).request('/api/debates', {
          method: 'post',
        }),
      );
      expect(timeoutResult.error).toBeInstanceOf(AragoraTimeoutError);
      expect(hanging.signals).toHaveLength(1);
    });
  });

  describe('circuit breaker', () => {
    const breakerOptions: Partial<ClientOptions> = {
      maxAttempts: 1,
      failMax: 3,
      resetTimeoutMs: 10_000,
    };

    it('opens after failMax consecutive failures and rejects without calling the transport', async () => {
      const { transport, calls } = scriptedTransport(respond(503));
      const api = client(transport, breakerOptions);

      for (let i = 0; i < 3; i++) {
        const { error } = await settle(api.request('/api/status'));
        expect(error).toBeInstanceOf(AragoraHttpError);
      }
      expect(calls).toHaveLength(3);
      expect(api.circuitState).toBe('open');

      const { error } = await settle(api.request('/api/status'));
      expect(error).toBeInstanceOf(CircuitOpenError);
      expect(error).toMatchObject({ name: 'CircuitOpenError' });
      expect(calls).toHaveLength(3);
    });

    it('half-opens after resetTimeoutMs and closes when the trial succeeds', async () => {
      const { transport, calls } = scriptedTransport(
        respond(503),
        respond(503),
        respond(503),
        respond(200, { ok: true }),
      );
      const api = client(transport, breakerOptions);
      for (let i = 0; i < 3; i++) await settle(api.request('/api/status'));
      expect(api.circuitState).toBe('open');

      await jest.advanceTimersByTimeAsync(9_999);
      expect(api.circuitState).toBe('open');
      expect((await settle(api.request('/api/status'))).error).toBeInstanceOf(CircuitOpenError);
      expect(calls).toHaveLength(3);

      await jest.advanceTimersByTimeAsync(1);
      expect(api.circuitState).toBe('half-open');

      const { value } = await settle(api.request('/api/status'));
      expect(value).toEqual({ ok: true });
      expect(calls).toHaveLength(4);
      expect(api.circuitState).toBe('closed');
    });

    it('re-opens when the half-open trial fails', async () => {
      const { transport, calls } = scriptedTransport(respond(503));
      const api = client(transport, breakerOptions);
      for (let i = 0; i < 3; i++) await settle(api.request('/api/status'));

      await jest.advanceTimersByTimeAsync(10_000);
      expect(api.circuitState).toBe('half-open');

      expect((await settle(api.request('/api/status'))).error).toBeInstanceOf(AragoraHttpError);
      expect(calls).toHaveLength(4);
      expect(api.circuitState).toBe('open');

      expect((await settle(api.request('/api/status'))).error).toBeInstanceOf(CircuitOpenError);
      expect(calls).toHaveLength(4);
    });

    it('counts each retry attempt and stops retrying once the circuit opens', async () => {
      const { transport, calls } = scriptedTransport(respond(503));
      const api = client(transport, { maxAttempts: 5, failMax: 2, resetTimeoutMs: 60_000 });

      const { error } = await settle(api.request('/api/agents'));

      expect(error).toBeInstanceOf(AragoraHttpError);
      expect(calls).toHaveLength(2);
      expect(api.circuitState).toBe('open');
    });

    it('does not count client errors as failures', async () => {
      const { transport, calls } = scriptedTransport(respond(404));
      const api = client(transport, breakerOptions);

      for (let i = 0; i < 5; i++) await settle(api.request('/api/missing'));

      expect(calls).toHaveLength(5);
      expect(api.circuitState).toBe('closed');
    });

    it('resets the failure count after a success', async () => {
      const { transport, calls } = scriptedTransport(
        respond(503),
        respond(503),
        respond(200),
        respond(503),
        respond(503),
      );
      const api = client(transport, breakerOptions);

      for (let i = 0; i < 5; i++) await settle(api.request('/api/status'));

      expect(calls).toHaveLength(5);
      expect(api.circuitState).toBe('closed');
    });
  });
});

describe('CircuitBreaker', () => {
  it('allows only one trial call while half-open', async () => {
    let now = 0;
    const breaker = new CircuitBreaker({ failMax: 1, resetTimeoutMs: 100, now: () => now });
    await expect(breaker.execute(() => Promise.reject(new Error('down')))).rejects.toThrow('down');
    expect(breaker.state).toBe('open');

    now = 100;
    let finishTrial: (value: string) => void = () => undefined;
    const trial = breaker.execute(
      () =>
        new Promise<string>((resolve) => {
          finishTrial = resolve;
        }),
    );
    const operation = jest.fn(() => Promise.resolve('second'));

    await expect(breaker.execute(operation)).rejects.toBeInstanceOf(CircuitOpenError);
    expect(operation).not.toHaveBeenCalled();

    finishTrial('first');
    await expect(trial).resolves.toBe('first');
    expect(breaker.state).toBe('closed');
    await expect(breaker.execute(operation)).resolves.toBe('second');
  });

  it('reports the time left until the next trial', async () => {
    let now = 1_000;
    const breaker = new CircuitBreaker({ failMax: 1, resetTimeoutMs: 5_000, now: () => now });
    await breaker.execute(() => Promise.reject(new Error('down'))).catch(() => undefined);

    now = 3_000;
    const error = await breaker.execute(() => Promise.resolve(1)).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(CircuitOpenError);
    expect((error as CircuitOpenError).retryAfterMs).toBe(3_000);
  });

  it('rejects invalid options', () => {
    expect(() => new CircuitBreaker({ failMax: 0, resetTimeoutMs: 1 })).toThrow(RangeError);
    expect(() => new CircuitBreaker({ failMax: 1, resetTimeoutMs: -1 })).toThrow(RangeError);
    expect(() => new ResilientHttpClient({ baseUrl: 'http://api.test', maxAttempts: 0 })).toThrow(
      RangeError,
    );
    expect(() => new ResilientHttpClient({ baseUrl: 'http://api.test', timeoutMs: 0 })).toThrow(
      RangeError,
    );
  });
});
