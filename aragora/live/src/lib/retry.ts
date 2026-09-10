/**
 * Retry utility with exponential backoff
 *
 * Provides resilient HTTP request handling with configurable retry logic,
 * following the same patterns as useNomicStream's circuit breaker.
 */

import { API_BASE_URL } from '@/config';

export interface RetryConfig {
  /** Maximum number of retry attempts (default: 3) */
  maxAttempts?: number;
  /** Initial delay in ms before first retry (default: 1000) */
  initialDelayMs?: number;
  /** Maximum delay in ms between retries (default: 10000) */
  maxDelayMs?: number;
  /** Request timeout in ms (default: 30000) */
  timeoutMs?: number;
  /** Custom function to determine if error should trigger retry */
  shouldRetry?: (error: Error, attempt: number) => boolean;
  /** Callback fired before each retry attempt */
  onRetry?: (error: Error, attempt: number, delayMs: number) => void;
}

export interface RetryResult<T> {
  data: T | null;
  error: Error | null;
  attempts: number;
  success: boolean;
}

const DEFAULT_CONFIG: Required<RetryConfig> = {
  maxAttempts: 3,
  initialDelayMs: 1000,
  maxDelayMs: 10000,
  timeoutMs: 30000,
  shouldRetry: (error: Error) => {
    const message = error.message.toLowerCase();
    // Retry on network errors, timeouts, and server errors
    const isNetworkError =
      message.includes('failed to fetch') ||
      message.includes('network') ||
      message.includes('timeout') ||
      message.includes('aborted');
    const isServerError =
      message.includes('500') ||
      message.includes('502') ||
      message.includes('503') ||
      message.includes('504');
    // Don't retry on 429 rate limit errors - let rate limiting work as intended
    // Retrying on 429 creates thundering herd effects and amplifies the problem
    const isRateLimited = message.includes('429');
    return (isNetworkError || isServerError) && !isRateLimited;
  },
  onRetry: () => {},
};

const TOKENS_KEY = 'aragora_tokens';

function getAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(TOKENS_KEY);
  if (!stored) return null;
  try {
    const parsed = JSON.parse(stored) as { access_token?: string };
    return parsed.access_token || null;
  } catch {
    return null;
  }
}

function isInternalApiRequest(url: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const parsed = new URL(url, window.location.origin);
    const apiOrigin = new URL(API_BASE_URL, window.location.origin).origin;
    const isApiPath = parsed.pathname.startsWith('/api/');
    const isTrustedOrigin = parsed.origin === window.location.origin || parsed.origin === apiOrigin;
    return isApiPath && isTrustedOrigin;
  } catch {
    return false;
  }
}

function withAuthHeaders(url: string, init: RequestInit): RequestInit {
  const token = getAccessToken();
  if (!token || !isInternalApiRequest(url)) {
    return init;
  }
  const headers = new Headers(init.headers || {});
  if (!headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${token}`);
  }
  return { ...init, headers };
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Execute an async function with retry logic
 */
export async function retryAsync<T>(
  fn: () => Promise<T>,
  config: RetryConfig = {},
): Promise<RetryResult<T>> {
  const finalConfig = { ...DEFAULT_CONFIG, ...config };
  let lastError: Error | null = null;

  for (let attempt = 1; attempt <= finalConfig.maxAttempts; attempt++) {
    try {
      const data = await fn();
      return { data, error: null, attempts: attempt, success: true };
    } catch (error) {
      lastError = error instanceof Error ? error : new Error(String(error));

      const isLastAttempt = attempt === finalConfig.maxAttempts;
      if (isLastAttempt || !finalConfig.shouldRetry(lastError, attempt)) {
        break;
      }

      // Exponential backoff: 1s → 2s → 4s → 8s → 10s (capped)
      const delayMs = Math.min(
        finalConfig.initialDelayMs * Math.pow(2, attempt - 1),
        finalConfig.maxDelayMs,
      );

      finalConfig.onRetry(lastError, attempt, delayMs);
      await delay(delayMs);
    }
  }

  return { data: null, error: lastError, attempts: finalConfig.maxAttempts, success: false };
}

/**
 * Fetch with automatic retry on failure
 */
export async function fetchWithRetry(
  url: string,
  options: RequestInit = {},
  config: RetryConfig = {},
): Promise<Response> {
  const timeoutMs = config.timeoutMs || DEFAULT_CONFIG.timeoutMs;
  const internalController = new AbortController();
  const timeoutId = setTimeout(() => internalController.abort(), timeoutMs);

  // If caller provided an abort signal, listen to it and abort internal controller
  const externalSignal = options.signal;
  if (externalSignal) {
    if (externalSignal.aborted) {
      // Already aborted, abort immediately
      internalController.abort();
    } else {
      externalSignal.addEventListener('abort', () => internalController.abort());
    }
  }

  const fetchOptions: RequestInit = withAuthHeaders(url, {
    ...options,
    signal: internalController.signal,
  });

  const result = await retryAsync(async () => {
    const response = await fetch(url, fetchOptions);

    // Throw on HTTP errors to trigger retry for server errors
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }

    return response;
  }, config);

  clearTimeout(timeoutId);

  if (!result.success || !result.data) {
    throw result.error || new Error('Request failed');
  }

  return result.data;
}

/**
 * Fetch JSON with automatic retry
 */
export async function fetchJsonWithRetry<T = unknown>(
  url: string,
  options: RequestInit = {},
  config: RetryConfig = {},
): Promise<T> {
  const response = await fetchWithRetry(url, options, config);
  return response.json() as Promise<T>;
}
