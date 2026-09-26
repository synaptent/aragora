'use client';

import { useState, useCallback, useRef, useEffect } from 'react';

/**
 * Generic async data fetching hook that reduces boilerplate.
 *
 * Provides unified loading, error, and data state management with:
 * - Automatic loading state
 * - Error handling with typed errors
 * - Refetch capability
 * - Stale-while-revalidate pattern
 * - Abort controller for cleanup
 *
 * @example
 * ```tsx
 * const { data, loading, error, refetch } = useAsyncData(
 *   () => fetch('/api/data').then(r => r.json()),
 *   { immediate: true }
 * );
 * ```
 */

export interface UseAsyncDataOptions<T> {
  /** Fetch immediately on mount (default: false) */
  immediate?: boolean;
  /** Initial data value */
  initialData?: T;
  /** Dependencies that trigger refetch when changed */
  deps?: unknown[];
  /** Keep previous data while revalidating */
  keepPreviousData?: boolean;
  /** Callback when fetch succeeds */
  onSuccess?: (data: T) => void;
  /** Callback when fetch fails */
  onError?: (error: Error) => void;
  /** Transform response data */
  transform?: (data: unknown) => T;
  /** Auto-refresh interval in milliseconds (0 to disable) */
  refreshInterval?: number;
}

export interface UseAsyncDataReturn<T> {
  /** The fetched data */
  data: T | null;
  /** Loading state */
  loading: boolean;
  /** Error message if fetch failed */
  error: string | null;
  /** Full error object */
  errorObject: Error | null;
  /** Whether data has been fetched at least once */
  isInitialized: boolean;
  /** Whether currently revalidating (has data but loading) */
  isRevalidating: boolean;
  /** Manually trigger a fetch */
  refetch: () => Promise<T | null>;
  /** Reset state to initial */
  reset: () => void;
  /** Manually set data */
  setData: (data: T | null) => void;
  /** Manually set error */
  setError: (error: string | null) => void;
}

export function useAsyncData<T>(
  fetcher: (signal?: AbortSignal) => Promise<T>,
  options: UseAsyncDataOptions<T> = {},
): UseAsyncDataReturn<T> {
  const {
    immediate = false,
    initialData = null,
    deps = [],
    keepPreviousData = false,
    onSuccess,
    onError,
    transform,
    refreshInterval = 0,
  } = options;

  const [data, setData] = useState<T | null>(initialData as T | null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorObject, setErrorObject] = useState<Error | null>(null);
  const [isInitialized, setIsInitialized] = useState(false);

  const abortControllerRef = useRef<AbortController | null>(null);
  const mountedRef = useRef(true);

  const reset = useCallback(() => {
    setData(initialData as T | null);
    setLoading(false);
    setError(null);
    setErrorObject(null);
    setIsInitialized(false);
  }, [initialData]);

  const refetch = useCallback(async (): Promise<T | null> => {
    // Cancel any pending request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    abortControllerRef.current = new AbortController();
    const signal = abortControllerRef.current.signal;

    setLoading(true);
    if (!keepPreviousData) {
      setError(null);
      setErrorObject(null);
    }

    try {
      const result = await fetcher(signal);

      // Check if component unmounted or request was aborted
      if (!mountedRef.current || signal.aborted) {
        return null;
      }

      // Apply transform if provided
      const finalResult = transform ? transform(result as unknown) : result;

      setData(finalResult as T);
      setError(null);
      setErrorObject(null);
      setIsInitialized(true);
      onSuccess?.(finalResult as T);

      return finalResult as T;
    } catch (err) {
      // Don't set error state if aborted
      if (err instanceof Error && err.name === 'AbortError') {
        return null;
      }

      if (!mountedRef.current) {
        return null;
      }

      const error = err instanceof Error ? err : new Error(String(err));
      setError(error.message);
      setErrorObject(error);
      setIsInitialized(true);
      onError?.(error);

      return null;
    } finally {
      if (mountedRef.current) {
        setLoading(false);
      }
    }
  }, [fetcher, keepPreviousData, onSuccess, onError, transform]);

  // Cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, []);

  // Fetch on mount if immediate
  useEffect(() => {
    if (immediate) {
      refetch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [immediate, ...deps]);

  // Set up refresh interval
  useEffect(() => {
    if (refreshInterval <= 0) return;

    const intervalId = setInterval(() => {
      refetch();
    }, refreshInterval);

    return () => clearInterval(intervalId);
  }, [refreshInterval, refetch]);

  const isRevalidating = loading && data !== null;

  return {
    data,
    loading,
    error,
    errorObject,
    isInitialized,
    isRevalidating,
    refetch,
    reset,
    setData,
    setError,
  };
}

/**
 * Simplified hook for fetching JSON from a URL.
 *
 * @example
 * ```tsx
 * const { data, loading, error } = useFetch<User[]>('/api/users', {
 *   immediate: true,
 * });
 * ```
 */
export function useFetch<T>(
  url: string | null,
  options: UseAsyncDataOptions<T> & { fetchOptions?: RequestInit } = {},
): UseAsyncDataReturn<T> {
  const { fetchOptions, ...asyncOptions } = options;

  const fetcher = useCallback(
    async (signal?: AbortSignal): Promise<T> => {
      if (!url) {
        throw new Error('No URL provided');
      }

      const response = await fetch(url, { ...fetchOptions, signal });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || data.message || `HTTP ${response.status}`);
      }

      return response.json();
    },
    [url, fetchOptions],
  );

  return useAsyncData(fetcher, {
    ...asyncOptions,
    // Only fetch immediately if URL is provided
    immediate: asyncOptions.immediate && !!url,
    deps: [url, ...(asyncOptions.deps || [])],
  });
}

/**
 * Hook for mutations (POST, PUT, DELETE) with loading state.
 *
 * @example
 * ```tsx
 * const { mutate, loading, error } = useMutation(
 *   async (data: CreateUserInput) => {
 *     const res = await fetch('/api/users', {
 *       method: 'POST',
 *       body: JSON.stringify(data),
 *     });
 *     return res.json();
 *   },
 *   { onSuccess: () => refetchUsers() }
 * );
 *
 * // Later
 * await mutate({ name: 'John' });
 * ```
 */
export interface UseMutationOptions<T, V> {
  onSuccess?: (data: T, variables: V) => void;
  onError?: (error: Error, variables: V) => void;
  onSettled?: (data: T | null, error: Error | null, variables: V) => void;
}

export interface UseMutationReturn<T, V> {
  data: T | null;
  loading: boolean;
  error: string | null;
  errorObject: Error | null;
  mutate: (variables: V) => Promise<T | null>;
  reset: () => void;
}

export function useMutation<T, V = void>(
  mutationFn: (variables: V) => Promise<T>,
  options: UseMutationOptions<T, V> = {},
): UseMutationReturn<T, V> {
  const { onSuccess, onError, onSettled } = options;

  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorObject, setErrorObject] = useState<Error | null>(null);

  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const mutate = useCallback(
    async (variables: V): Promise<T | null> => {
      setLoading(true);
      setError(null);
      setErrorObject(null);

      try {
        const result = await mutationFn(variables);

        if (!mountedRef.current) return null;

        setData(result);
        onSuccess?.(result, variables);
        onSettled?.(result, null, variables);

        return result;
      } catch (err) {
        if (!mountedRef.current) return null;

        const error = err instanceof Error ? err : new Error(String(err));
        setError(error.message);
        setErrorObject(error);
        onError?.(error, variables);
        onSettled?.(null, error, variables);

        return null;
      } finally {
        if (mountedRef.current) {
          setLoading(false);
        }
      }
    },
    [mutationFn, onSuccess, onError, onSettled],
  );

  const reset = useCallback(() => {
    setData(null);
    setLoading(false);
    setError(null);
    setErrorObject(null);
  }, []);

  return { data, loading, error, errorObject, mutate, reset };
}

export default useAsyncData;
