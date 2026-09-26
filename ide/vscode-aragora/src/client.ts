/**
 * HTTP client for the Aragora API with a per-attempt timeout, exponential
 * backoff retry for idempotent requests, and a circuit breaker.
 */

export interface TransportInit {
  method: string;
  headers: Record<string, string>;
  body?: string;
  signal: AbortSignal;
}

export interface TransportResponse {
  ok: boolean;
  status: number;
  text(): Promise<string>;
}

export type Transport = (url: string, init: TransportInit) => Promise<TransportResponse>;

export interface ClientOptions {
  baseUrl: string;
  apiKey?: string;
  /** Sends one HTTP request; defaults to the global `fetch`. */
  transport?: Transport;
  /** Budget for one attempt, including reading the response body. */
  timeoutMs?: number;
  /** Total attempts for idempotent requests (GET, HEAD). Other methods are sent once. */
  maxAttempts?: number;
  /** Delay before the second attempt; doubled for each further attempt. */
  backoffBaseMs?: number;
  backoffMaxMs?: number;
  /** Consecutive failures that open the circuit. */
  failMax?: number;
  /** How long the circuit stays open before a single trial request is let through. */
  resetTimeoutMs?: number;
}

export interface RequestOptions {
  method?: string;
  body?: string;
  headers?: Record<string, string>;
  /** Overrides the client's `timeoutMs` for this request. */
  timeoutMs?: number;
}

export class AragoraTimeoutError extends Error {
  override readonly name = 'AragoraTimeoutError';

  constructor(
    readonly method: string,
    readonly path: string,
    readonly timeoutMs: number,
  ) {
    super(`${method} ${path} timed out after ${timeoutMs} ms`);
  }
}

export class AragoraHttpError extends Error {
  override readonly name = 'AragoraHttpError';

  constructor(
    readonly status: number,
    readonly body: string,
  ) {
    super(`API Error: ${status} - ${body}`);
  }
}

export class CircuitOpenError extends Error {
  override readonly name = 'CircuitOpenError';

  constructor(readonly retryAfterMs: number) {
    super(`Aragora API circuit is open; retry in ${retryAfterMs} ms`);
  }
}

export type CircuitState = 'closed' | 'open' | 'half-open';

interface CircuitBreakerOptions {
  failMax: number;
  resetTimeoutMs: number;
  now?: () => number;
}

export class CircuitBreaker {
  private readonly failMax: number;
  private readonly resetTimeoutMs: number;
  private readonly now: () => number;
  private failures = 0;
  private openedAt: number | undefined;
  private trialInFlight = false;

  constructor(options: CircuitBreakerOptions) {
    if (!Number.isInteger(options.failMax) || options.failMax < 1) {
      throw new RangeError('failMax must be a positive integer');
    }
    if (!(options.resetTimeoutMs >= 0)) {
      throw new RangeError('resetTimeoutMs must not be negative');
    }
    this.failMax = options.failMax;
    this.resetTimeoutMs = options.resetTimeoutMs;
    this.now = options.now ?? Date.now;
  }

  get state(): CircuitState {
    if (this.openedAt === undefined) return 'closed';
    return this.now() - this.openedAt >= this.resetTimeoutMs ? 'half-open' : 'open';
  }

  /**
   * Runs `operation` unless the circuit is open. Errors for which `isFailure`
   * returns false (e.g. a 404) count as a healthy answer.
   */
  async execute<T>(
    operation: () => Promise<T>,
    isFailure: (error: unknown) => boolean = () => true,
  ): Promise<T> {
    const state = this.state;
    if (state === 'open' || (state === 'half-open' && this.trialInFlight)) {
      throw new CircuitOpenError(this.retryAfterMs());
    }
    const isTrial = state === 'half-open';
    if (isTrial) this.trialInFlight = true;
    try {
      const result = await operation();
      this.recordSuccess();
      return result;
    } catch (error) {
      if (isFailure(error)) {
        this.recordFailure();
      } else {
        this.recordSuccess();
      }
      throw error;
    } finally {
      if (isTrial) this.trialInFlight = false;
    }
  }

  private recordSuccess(): void {
    this.failures = 0;
    this.openedAt = undefined;
  }

  private recordFailure(): void {
    this.failures += 1;
    // A failed half-open trial re-opens the circuit for another full reset period.
    if (this.openedAt !== undefined || this.failures >= this.failMax) {
      this.openedAt = this.now();
    }
  }

  private retryAfterMs(): number {
    if (this.openedAt === undefined) return 0;
    return Math.max(0, this.openedAt + this.resetTimeoutMs - this.now());
  }
}

const IDEMPOTENT_METHODS = new Set(['GET', 'HEAD']);

/** Client errors are answers from a healthy server, except timeouts and rate limits. */
function isServerFailure(error: unknown): boolean {
  if (error instanceof AragoraHttpError) {
    return error.status >= 500 || error.status === 408 || error.status === 429;
  }
  return !(error instanceof CircuitOpenError);
}

const defaultTransport: Transport = (url, init) => fetch(url, init);

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class ResilientHttpClient {
  private readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly transport: Transport;
  private readonly timeoutMs: number;
  private readonly maxAttempts: number;
  private readonly backoffBaseMs: number;
  private readonly backoffMaxMs: number;
  private readonly breaker: CircuitBreaker;

  constructor(options: ClientOptions) {
    this.baseUrl = options.baseUrl.replace(/\/+$/, '');
    this.apiKey = options.apiKey ?? '';
    this.transport = options.transport ?? defaultTransport;
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.maxAttempts = options.maxAttempts ?? 3;
    this.backoffBaseMs = options.backoffBaseMs ?? 500;
    this.backoffMaxMs = options.backoffMaxMs ?? 8_000;
    this.breaker = new CircuitBreaker({
      failMax: options.failMax ?? 5,
      resetTimeoutMs: options.resetTimeoutMs ?? 30_000,
    });
    if (!Number.isInteger(this.maxAttempts) || this.maxAttempts < 1) {
      throw new RangeError('maxAttempts must be a positive integer');
    }
    if (!(this.timeoutMs > 0)) {
      throw new RangeError('timeoutMs must be positive');
    }
  }

  get circuitState(): CircuitState {
    return this.breaker.state;
  }

  async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const method = (options.method ?? 'GET').toUpperCase();
    const attempts = IDEMPOTENT_METHODS.has(method) ? this.maxAttempts : 1;
    const init = {
      method,
      body: options.body,
      headers: {
        'Content-Type': 'application/json',
        ...(this.apiKey ? { Authorization: `Bearer ${this.apiKey}` } : {}),
        ...options.headers,
      },
    };
    const timeoutMs = options.timeoutMs ?? this.timeoutMs;

    for (let attempt = 1; ; attempt++) {
      try {
        return await this.breaker.execute(
          () => this.attempt<T>(path, init, timeoutMs),
          isServerFailure,
        );
      } catch (error) {
        const retryable = isServerFailure(error) && this.breaker.state === 'closed';
        if (attempt >= attempts || !retryable) throw error;
      }
      await sleep(this.backoffDelay(attempt));
    }
  }

  /** Delay after the given failed attempt: base, 2x base, 4x base, ... capped at the maximum. */
  private backoffDelay(failedAttempt: number): number {
    return Math.min(this.backoffBaseMs * 2 ** (failedAttempt - 1), this.backoffMaxMs);
  }

  private async attempt<T>(
    path: string,
    init: Omit<TransportInit, 'signal'>,
    timeoutMs: number,
  ): Promise<T> {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Racing the timer, rather than relying on the abort alone, also bounds a
    // transport or body read that ignores the signal.
    const timeout = new Promise<never>((_resolve, reject) => {
      timer = setTimeout(() => {
        reject(new AragoraTimeoutError(init.method, path, timeoutMs));
        controller.abort();
      }, timeoutMs);
    });
    try {
      return await Promise.race([
        this.send<T>(path, { ...init, signal: controller.signal }),
        timeout,
      ]);
    } finally {
      clearTimeout(timer);
    }
  }

  private async send<T>(path: string, init: TransportInit): Promise<T> {
    const response = await this.transport(`${this.baseUrl}${path}`, init);
    const text = await response.text();
    if (!response.ok) {
      throw new AragoraHttpError(response.status, text);
    }
    return (text ? JSON.parse(text) : undefined) as T;
  }
}
