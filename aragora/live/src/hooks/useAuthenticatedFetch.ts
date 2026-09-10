'use client';

import { useState, useCallback, useEffect, useRef } from 'react';
import { useAuth } from '@/context/AuthContext';
import { API_BASE_URL } from '@/config';
import { getRuntimeBackendConfig } from '@/lib/runtimeBackend';
import { logger } from '@/utils/logger';
import { createErrorFromResponse, isRetryableError } from '@/lib/api-error';

interface FetchState<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  /** True if user is not authenticated (skipped API call) */
  skipped: boolean;
}

interface UseAuthenticatedFetchOptions<T> {
  /** Skip the fetch if user is not authenticated (default: true) */
  requireAuth?: boolean;
  /** Default data to return when not authenticated */
  defaultData?: T;
  /** Dependencies to trigger refetch */
  deps?: unknown[];
  /** Called on successful fetch */
  onSuccess?: (data: T) => void;
  /** Called on error */
  onError?: (error: Error) => void;
  /** Disable automatic fetch on mount */
  manual?: boolean;
}

function resolveApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    return getRuntimeBackendConfig().config.api.replace(/\/$/, '');
  }
  return API_BASE_URL.replace(/\/$/, '');
}

function resolveRequestUrl(endpoint: string): string {
  if (endpoint.startsWith('http://') || endpoint.startsWith('https://')) {
    return endpoint;
  }
  const baseUrl = resolveApiBaseUrl();
  if (!baseUrl) {
    return endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  }
  return endpoint.startsWith('/') ? `${baseUrl}${endpoint}` : `${baseUrl}/${endpoint}`;
}

/**
 * Hook for making authenticated API calls that gracefully handles
 * unauthenticated users without flooding the console with 401 errors.
 *
 * @example
 * // Basic usage - auto-fetches on mount, skips if not authenticated
 * const { data, loading, error, skipped } = useAuthenticatedFetch<Debate[]>(
 *   '/api/debates',
 * );
 *
 * // With options
 * const { data, refetch } = useAuthenticatedFetch<LeaderboardData>(
 *   '/api/leaderboard',
 *   { defaultData: [], manual: true }
 * );
 */
export function useAuthenticatedFetch<T>(
  endpoint: string,
  options: UseAuthenticatedFetchOptions<T> = {},
): FetchState<T> & { refetch: () => Promise<void> } {
  const {
    requireAuth = true,
    defaultData = null as T,
    deps = [],
    onSuccess,
    onError,
    manual = false,
  } = options;

  const { tokens, isAuthenticated, isLoading: authLoading, refreshToken } = useAuth();
  const [state, setState] = useState<FetchState<T>>({
    data: defaultData,
    loading: !manual,
    error: null,
    skipped: false,
  });

  const mountedRef = useRef(true);
  const isRefreshingRef = useRef(false);

  const fetchData = useCallback(async () => {
    // Wait for auth to finish loading
    if (authLoading) {
      return;
    }

    // Skip if auth required but not authenticated
    if (requireAuth && (!isAuthenticated || !tokens?.access_token)) {
      setState({ data: defaultData, loading: false, error: null, skipped: true });
      return;
    }

    setState((prev) => ({ ...prev, loading: true, error: null, skipped: false }));

    const makeRequest = async (token?: string): Promise<Response> => {
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (token) {
        headers['Authorization'] = `Bearer ${token}`;
      }

      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000);
      const url = resolveRequestUrl(endpoint);
      try {
        return await fetch(url, { headers, signal: controller.signal });
      } finally {
        clearTimeout(timeoutId);
      }
    };

    try {
      let response = await makeRequest(tokens?.access_token);

      // 401 Interceptor: Try to refresh token and retry once
      if (response.status === 401 && requireAuth && !isRefreshingRef.current) {
        isRefreshingRef.current = true;
        logger.debug(`[useAuthenticatedFetch] 401 on ${endpoint}, attempting token refresh...`);

        try {
          const refreshed = await refreshToken();

          if (refreshed) {
            // Get fresh tokens from storage after refresh
            const storedTokens = localStorage.getItem('aragora_tokens');
            if (storedTokens) {
              const newTokens = JSON.parse(storedTokens);
              logger.debug(`[useAuthenticatedFetch] Token refreshed, retrying ${endpoint}...`);
              response = await makeRequest(newTokens.access_token);
            }
          } else {
            // Refresh failed - user will be logged out by AuthContext
            logger.warn(`[useAuthenticatedFetch] Token refresh failed for ${endpoint}`);
            if (mountedRef.current) {
              setState({ data: defaultData, loading: false, error: null, skipped: true });
            }
            return;
          }
        } finally {
          isRefreshingRef.current = false;
        }
      }

      if (!response.ok) {
        // Handle auth errors silently when requireAuth is true (after refresh attempt)
        if (response.status === 401 && requireAuth) {
          if (mountedRef.current) {
            setState({ data: defaultData, loading: false, error: null, skipped: true });
          }
          return;
        }

        throw await createErrorFromResponse(response);
      }

      const data = await response.json();

      if (mountedRef.current) {
        setState({ data, loading: false, error: null, skipped: false });
        onSuccess?.(data);
      }
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      const canRetry = isRetryableError(error);

      if (mountedRef.current) {
        setState((prev) => ({ ...prev, loading: false, error: error.message, skipped: false }));
        onError?.(error);

        // Log retryable errors at debug level since they may auto-resolve
        if (canRetry) {
          logger.debug(`[useAuthenticatedFetch] Retryable error on ${endpoint}:`, error.message);
        }
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    endpoint,
    tokens?.access_token,
    isAuthenticated,
    authLoading,
    requireAuth,
    refreshToken,
    ...deps,
  ]);

  // Auto-fetch on mount (unless manual)
  useEffect(() => {
    mountedRef.current = true;

    if (!manual) {
      fetchData();
    }

    return () => {
      mountedRef.current = false;
    };
  }, [fetchData, manual]);

  return { ...state, refetch: fetchData };
}

/**
 * Hook that provides auth-aware fetch function for manual API calls.
 * Use this when you need to make POST/PUT/DELETE requests or
 * have complex fetch logic.
 *
 * @example
 * const { authFetch, isAuthenticated } = useAuthFetch();
 *
 * const handleSubmit = async () => {
 *   if (!isAuthenticated) return;
 *   const data = await authFetch('/api/debates', {
 *     method: 'POST',
 *     body: JSON.stringify({ question: '...' }),
 *   });
 * };
 */
export function useAuthFetch() {
  const { tokens, isAuthenticated, isLoading, refreshToken } = useAuth();
  const isRefreshingRef = useRef(false);

  const authFetch = useCallback(
    async <T>(endpoint: string, init: RequestInit = {}): Promise<T | null> => {
      if (!isAuthenticated || !tokens?.access_token) {
        logger.warn(`[useAuthFetch] Skipped ${endpoint} - not authenticated`);
        return null;
      }

      const makeRequest = async (token: string): Promise<Response> => {
        const headers: HeadersInit = {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
          ...init.headers,
        };

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 30000);
        const url = resolveRequestUrl(endpoint);
        try {
          return await fetch(url, { ...init, headers, signal: controller.signal });
        } finally {
          clearTimeout(timeoutId);
        }
      };

      let response = await makeRequest(tokens.access_token);

      // 401 Interceptor: Try to refresh token and retry once
      if (response.status === 401 && !isRefreshingRef.current) {
        isRefreshingRef.current = true;
        logger.debug(`[useAuthFetch] 401 on ${endpoint}, attempting token refresh...`);

        try {
          const refreshed = await refreshToken();

          if (refreshed) {
            // Get fresh tokens from storage after refresh
            const storedTokens = localStorage.getItem('aragora_tokens');
            if (storedTokens) {
              const newTokens = JSON.parse(storedTokens);
              logger.debug(`[useAuthFetch] Token refreshed, retrying ${endpoint}...`);
              response = await makeRequest(newTokens.access_token);
            }
          } else {
            // Refresh failed - user will be logged out by AuthContext
            logger.warn(`[useAuthFetch] Token refresh failed for ${endpoint}`);
            return null;
          }
        } finally {
          isRefreshingRef.current = false;
        }
      }

      if (!response.ok) {
        throw await createErrorFromResponse(response);
      }

      return response.json();
    },
    [tokens?.access_token, isAuthenticated, refreshToken],
  );

  const getAuthHeaders = useCallback((): HeadersInit => {
    return {
      'Content-Type': 'application/json',
      ...(tokens?.access_token && { Authorization: `Bearer ${tokens.access_token}` }),
    };
  }, [tokens?.access_token]);

  return { authFetch, getAuthHeaders, isAuthenticated, isLoading };
}

export default useAuthenticatedFetch;
