'use client';

import useSWR, { SWRConfiguration, mutate, useSWRConfig } from 'swr';
import { API_BASE_URL } from '@/config';
import { getRuntimeBackendConfig } from '@/lib/runtimeBackend';

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

function resolveApiBaseUrl(baseUrl?: string): string {
  if (baseUrl !== undefined) return baseUrl;

  const runtimeBaseUrl = getRuntimeBackendConfig().config.api;
  return runtimeBaseUrl ?? API_BASE_URL;
}

function isInternalApiRequest(url: string): boolean {
  if (typeof window === 'undefined') return false;
  try {
    const parsed = new URL(url, window.location.origin);
    const apiOrigin = new URL(resolveApiBaseUrl(), window.location.origin).origin;
    const isApiPath = parsed.pathname.startsWith('/api/');
    const isTrustedOrigin = parsed.origin === window.location.origin || parsed.origin === apiOrigin;
    return isApiPath && isTrustedOrigin;
  } catch {
    return false;
  }
}

function getAuthHeaders(url: string): HeadersInit {
  const headers: HeadersInit = { 'Content-Type': 'application/json' };
  const token = getAccessToken();
  if (token && isInternalApiRequest(url)) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

/**
 * Global fetcher function for SWR
 * Uses fetchWithRetry for resilience
 */
export async function swrFetcher<T>(url: string): Promise<T> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30000);
  let response: Response;
  try {
    response = await fetch(url, { headers: getAuthHeaders(url), signal: controller.signal });
  } finally {
    clearTimeout(timeoutId);
  }

  if (!response.ok) {
    const error = new Error('API request failed') as Error & { status: number };
    error.status = response.status;
    throw error;
  }

  return response.json();
}

/**
 * Options for useSWRFetch hook
 */
export interface UseSWRFetchOptions<T> extends SWRConfiguration<T> {
  /** Base URL for API requests (defaults to API_BASE_URL) */
  baseUrl?: string;
  /** Whether to fetch immediately (default: true) */
  enabled?: boolean;
}

/**
 * SWR-based data fetching hook with caching and automatic revalidation
 *
 * Features:
 * - Automatic caching with stale-while-revalidate
 * - Deduplication of requests
 * - Automatic revalidation on focus/reconnect
 * - Optimistic updates support
 * - Error retry with exponential backoff
 *
 * @example
 * // Basic usage
 * const { data, error, isLoading } = useSWRFetch('/api/leaderboard');
 *
 * // With options
 * const { data, error, isLoading, mutate } = useSWRFetch('/api/debates', {
 *   refreshInterval: 30000, // Refresh every 30 seconds
 *   revalidateOnFocus: true,
 * });
 *
 * // Conditional fetching
 * const { data } = useSWRFetch(userId ? `/api/users/${userId}` : null);
 */
export function useSWRFetch<T = unknown>(
  endpoint: string | null,
  options: UseSWRFetchOptions<T> = {},
) {
  const { baseUrl, enabled = true, ...swrOptions } = options;

  const url = endpoint && enabled ? `${resolveApiBaseUrl(baseUrl)}${endpoint}` : null;

  const {
    data,
    error,
    isLoading,
    isValidating,
    mutate: boundMutate,
  } = useSWR<T>(url, swrFetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    dedupingInterval: 2000,
    errorRetryCount: 2,
    errorRetryInterval: 5000,
    onErrorRetry: (err, _key, _config, revalidate, { retryCount }) => {
      // Never retry on auth errors — prevents infinite loop when backend is down
      const status = (err as Error & { status?: number }).status;
      if (status === 401 || status === 403 || status === 404) return;
      // Only retry up to 2 times with backoff
      if (retryCount >= 2) return;
      setTimeout(() => revalidate({ retryCount }), 5000 * (retryCount + 1));
    },
    ...swrOptions,
  });

  return {
    data: data ?? null,
    error: error as Error | null,
    isLoading,
    isValidating,
    mutate: boundMutate,
  };
}

/**
 * Hook for multiple endpoints with caching
 *
 * @example
 * const { data, errors, isLoading } = useSWRFetchMultiple([
 *   '/api/debates',
 *   '/api/leaderboard',
 *   '/api/agents',
 * ]);
 */
export function useSWRFetchMultiple<T = unknown>(
  endpoints: (string | null)[],
  options: UseSWRFetchOptions<T> = {},
) {
  const { baseUrl, enabled = true } = options;
  const resolvedBaseUrl = resolveApiBaseUrl(baseUrl);

  const results = endpoints.map((endpoint) => {
    const url = endpoint && enabled ? `${resolvedBaseUrl}${endpoint}` : null;
    // eslint-disable-next-line react-hooks/rules-of-hooks
    return useSWR<T>(url, swrFetcher);
  });

  return {
    data: results.map((r) => r.data ?? null),
    errors: results.map((r) => r.error as Error | null),
    isLoading: results.some((r) => r.isLoading),
    isValidating: results.some((r) => r.isValidating),
  };
}

/**
 * Prefetch data for a given endpoint
 * Useful for preloading data before navigation
 *
 * @example
 * // Prefetch on hover
 * <Link
 *   href="/debates/123"
 *   onMouseEnter={() => prefetchData('/api/debates/123')}
 * >
 */
export function prefetchData(endpoint: string, baseUrl?: string) {
  const url = `${resolveApiBaseUrl(baseUrl)}${endpoint}`;
  return mutate(url, swrFetcher(url));
}

/**
 * Invalidate cached data for a given endpoint
 * Forces a revalidation on next access
 *
 * @example
 * // After creating a new debate
 * await createDebate(data);
 * invalidateCache('/api/debates');
 */
export function invalidateCache(endpoint: string, baseUrl?: string) {
  const url = `${resolveApiBaseUrl(baseUrl)}${endpoint}`;
  return mutate(url);
}

/**
 * Invalidate all cached data matching a pattern
 *
 * @example
 * // Invalidate all debate-related caches
 * invalidateCachePattern(/\/api\/debates/);
 */
export function invalidateCachePattern(pattern: RegExp) {
  return mutate((key) => typeof key === 'string' && pattern.test(key), undefined, {
    revalidate: true,
  });
}

/**
 * Update cached data optimistically
 *
 * @example
 * // Optimistic update
 * const newDebate = { id: '123', title: 'New Debate' };
 * updateCache('/api/debates', (current) => [...(current || []), newDebate]);
 */
export function updateCache<T>(
  endpoint: string,
  updater: (current: T | undefined) => T,
  baseUrl?: string,
) {
  const url = `${resolveApiBaseUrl(baseUrl)}${endpoint}`;
  return mutate(url, updater, { revalidate: false });
}

/**
 * Hook to get the global SWR cache for debugging
 */
export function useSWRCache() {
  const { cache } = useSWRConfig();
  return cache;
}

/**
 * Pre-configured hooks for common endpoints
 */

export function useDebates(options?: UseSWRFetchOptions<unknown>) {
  return useSWRFetch('/api/debates', {
    refreshInterval: 30000, // Refresh every 30 seconds
    ...options,
  });
}

export interface ActiveDebate {
  id: string;
  topic: string;
  status: string;
  started_at: string;
  agents: string[];
  round: number;
  total_rounds: number;
  elapsed_seconds: number;
}

export interface ActiveDebatesResponse {
  debates: ActiveDebate[];
}

export function useActiveDebates(options?: UseSWRFetchOptions<ActiveDebatesResponse>) {
  return useSWRFetch<ActiveDebatesResponse>('/api/v1/debates/active', {
    refreshInterval: 5000, // Refresh every 5 seconds for live data
    ...options,
  });
}

export function useDebate(debateId: string | null, options?: UseSWRFetchOptions<unknown>) {
  return useSWRFetch(debateId ? `/api/debates/${debateId}` : null, options);
}

export function useLeaderboard(options?: UseSWRFetchOptions<unknown>) {
  return useSWRFetch('/api/leaderboard', {
    refreshInterval: 60000, // Refresh every minute
    ...options,
  });
}

export function useAgents(options?: UseSWRFetchOptions<unknown>) {
  return useSWRFetch('/api/agents', { refreshInterval: 60000, ...options });
}

export function useConnectors(options?: UseSWRFetchOptions<unknown>) {
  return useSWRFetch('/api/scheduler/jobs', { refreshInterval: 30000, ...options });
}

export function useSchedulerStats(options?: UseSWRFetchOptions<unknown>) {
  return useSWRFetch('/api/scheduler/stats', {
    refreshInterval: 10000, // Refresh every 10 seconds
    ...options,
  });
}

export function usePulseTopics(options?: UseSWRFetchOptions<unknown>) {
  return useSWRFetch('/api/pulse/topics', { refreshInterval: 60000, ...options });
}

export function useMemoryStats(options?: UseSWRFetchOptions<unknown>) {
  return useSWRFetch('/api/memory/stats', { refreshInterval: 30000, ...options });
}
