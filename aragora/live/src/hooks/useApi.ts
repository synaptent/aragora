'use client';

import { useState, useCallback, useRef } from 'react';
import { fetchWithRetry, type RetryConfig } from '@/lib/retry';
import { API_BASE_URL } from '@/config';

const TOKENS_KEY = 'aragora_tokens';

function getStoredAccessToken(): string | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(TOKENS_KEY);
  if (!stored) return null;
  try {
    return (JSON.parse(stored) as { access_token?: string }).access_token || null;
  } catch {
    return null;
  }
}

interface ApiState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
}

interface UseApiOptions extends RetryConfig {
  /** Callback on successful response */
  onSuccess?: (data: unknown) => void;
  /** Callback on error */
  onError?: (error: Error) => void;
}

/**
 * React hook for resilient API calls with automatic retry
 *
 * Features:
 * - Automatic retry with exponential backoff
 * - Loading and error state management
 * - Request deduplication (prevents duplicate in-flight requests)
 * - TypeScript generics for type-safe responses
 *
 * @example
 * const api = useApi('https://api.aragora.ai');
 * const { data, loading, error } = api;
 *
 * // Make a GET request
 * await api.get('/api/leaderboard');
 *
 * // Make a POST request
 * await api.post('/api/debate', { question: 'Is AI good?' });
 */
export function useApi<T = unknown>(baseUrl: string = API_BASE_URL, options: UseApiOptions = {}) {
  const [state, setState] = useState<ApiState<T>>({ data: null, loading: false, error: null });

  // Track in-flight requests to prevent duplicates
  const inFlightRef = useRef<Map<string, Promise<T>>>(new Map());

  const request = useCallback(
    async (
      endpoint: string,
      init: RequestInit = {},
      customRetryConfig?: RetryConfig,
    ): Promise<T> => {
      const url = `${baseUrl}${endpoint}`;
      const requestKey = `${init.method || 'GET'}:${url}`;

      // Deduplicate in-flight requests
      const existingRequest = inFlightRef.current.get(requestKey);
      if (existingRequest) {
        return existingRequest;
      }

      setState((prev) => ({ ...prev, loading: true, error: null }));

      const retryConfig: RetryConfig = {
        maxAttempts: 3,
        initialDelayMs: 1000,
        maxDelayMs: 10000,
        timeoutMs: 30000,
        // onRetry callback can be overridden via customRetryConfig if logging is needed
        ...options,
        ...customRetryConfig,
      };

      const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(init.headers as Record<string, string>),
      };
      const storedToken = getStoredAccessToken();
      if (storedToken && !headers['Authorization']) {
        headers['Authorization'] = `Bearer ${storedToken}`;
      }

      const fetchPromise = (async (): Promise<T> => {
        try {
          const response = await fetchWithRetry(url, { ...init, headers }, retryConfig);

          const data = await response.json();

          setState({ data, loading: false, error: null });
          options.onSuccess?.(data);

          return data;
        } catch (error) {
          const errorMessage = error instanceof Error ? error.message : 'Request failed';
          setState({ data: null, loading: false, error: errorMessage });

          const err = error instanceof Error ? error : new Error(errorMessage);
          options.onError?.(err);

          throw err;
        } finally {
          inFlightRef.current.delete(requestKey);
        }
      })();

      inFlightRef.current.set(requestKey, fetchPromise);
      return fetchPromise;
    },
    [baseUrl, options],
  );

  const get = useCallback(
    (endpoint: string, retryConfig?: RetryConfig): Promise<T> => {
      return request(endpoint, { method: 'GET' }, retryConfig);
    },
    [request],
  );

  const post = useCallback(
    (endpoint: string, body?: unknown, retryConfig?: RetryConfig): Promise<T> => {
      return request(
        endpoint,
        { method: 'POST', body: body ? JSON.stringify(body) : undefined },
        retryConfig,
      );
    },
    [request],
  );

  const put = useCallback(
    (endpoint: string, body?: unknown, retryConfig?: RetryConfig): Promise<T> => {
      return request(
        endpoint,
        { method: 'PUT', body: body ? JSON.stringify(body) : undefined },
        retryConfig,
      );
    },
    [request],
  );

  const del = useCallback(
    (endpoint: string, retryConfig?: RetryConfig) => {
      return request(endpoint, { method: 'DELETE' }, retryConfig);
    },
    [request],
  );

  const reset = useCallback(() => {
    setState({ data: null, loading: false, error: null });
  }, []);

  return { ...state, get, post, put, delete: del, request, reset };
}
