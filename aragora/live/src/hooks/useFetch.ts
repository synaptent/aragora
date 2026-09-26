'use client';

import { useState, useCallback, useRef, useEffect } from 'react';

interface UseFetchOptions<T> {
  /** Initial data value */
  initialData?: T;
  /** Whether to fetch immediately on mount */
  immediate?: boolean;
  /** Retry count on failure */
  retryCount?: number;
  /** Delay between retries in ms */
  retryDelay?: number;
  /** Callback on error */
  onError?: (error: Error) => void;
  /** Callback on success */
  onSuccess?: (data: T) => void;
}

interface UseFetchReturn<T> {
  data: T | null;
  loading: boolean;
  error: Error | null;
  retrying: boolean;
  retryAttempt: number;
  fetch: () => Promise<T | null>;
  retry: () => Promise<T | null>;
  reset: () => void;
}

export function useFetch<T>(
  fetcher: () => Promise<T>,
  options: UseFetchOptions<T> = {},
): UseFetchReturn<T> {
  const {
    initialData = null,
    immediate = false,
    retryCount = 3,
    retryDelay = 1000,
    onError,
    onSuccess,
  } = options;

  const [data, setData] = useState<T | null>(initialData);
  const [loading, setLoading] = useState(immediate);
  const [error, setError] = useState<Error | null>(null);
  const [retrying, setRetrying] = useState(false);
  const [retryAttempt, setRetryAttempt] = useState(0);

  const mountedRef = useRef(true);
  const abortControllerRef = useRef<AbortController | null>(null);

  // Track mounted state
  useEffect(() => {
    mountedRef.current = true;
    const abortController = abortControllerRef.current;
    return () => {
      mountedRef.current = false;
      abortController?.abort();
    };
  }, []);

  const executeFetch = useCallback(async (): Promise<T | null> => {
    if (!mountedRef.current) return null;

    setLoading(true);
    setError(null);

    try {
      const result = await fetcher();

      if (mountedRef.current) {
        setData(result);
        setError(null);
        setRetryAttempt(0);
        onSuccess?.(result);
      }

      return result;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));

      if (mountedRef.current) {
        setError(error);
        onError?.(error);
      }

      return null;
    } finally {
      if (mountedRef.current) {
        setLoading(false);
        setRetrying(false);
      }
    }
  }, [fetcher, onError, onSuccess]);

  const retryWithBackoff = useCallback(async (): Promise<T | null> => {
    if (retryAttempt >= retryCount) {
      return null;
    }

    setRetrying(true);
    setRetryAttempt((prev) => prev + 1);

    // Exponential backoff
    const delay = retryDelay * Math.pow(2, retryAttempt);
    await new Promise((resolve) => setTimeout(resolve, delay));

    if (!mountedRef.current) return null;

    return executeFetch();
  }, [retryAttempt, retryCount, retryDelay, executeFetch]);

  const reset = useCallback(() => {
    setData(initialData);
    setLoading(false);
    setError(null);
    setRetrying(false);
    setRetryAttempt(0);
  }, [initialData]);

  // Immediate fetch on mount
  useEffect(() => {
    if (immediate) {
      executeFetch();
    }
  }, [immediate, executeFetch]);

  return {
    data,
    loading,
    error,
    retrying,
    retryAttempt,
    fetch: executeFetch,
    retry: retryWithBackoff,
    reset,
  };
}

/**
 * Hook for simple async state management with retry
 */
export function useAsyncState<T>(asyncFn: () => Promise<T>, deps: React.DependencyList = []) {
  const [state, setState] = useState<{ data: T | null; loading: boolean; error: Error | null }>({
    data: null,
    loading: true,
    error: null,
  });

  const execute = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await asyncFn();
      setState({ data, loading: false, error: null });
      return data;
    } catch (err) {
      const error = err instanceof Error ? err : new Error(String(err));
      setState((s) => ({ ...s, loading: false, error }));
      return null;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    execute();
  }, [execute]);

  return { ...state, refetch: execute };
}
