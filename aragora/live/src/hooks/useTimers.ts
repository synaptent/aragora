'use client';

import { useEffect, useRef, useCallback, useReducer } from 'react';

/**
 * Hook that provides a timeout function that's automatically cleaned up on unmount.
 * Returns a stable function reference that can be called to set a timeout.
 *
 * @example
 * const setTimeout = useTimeout();
 * setTimeout(() => console.log('Hello'), 1000);
 */
export function useTimeout() {
  const timeoutIds = useRef<Set<NodeJS.Timeout>>(new Set());

  // Cleanup all timeouts on unmount
  useEffect(() => {
    const ids = timeoutIds.current;
    return () => {
      ids.forEach((id) => clearTimeout(id));
      ids.clear();
    };
  }, []);

  const setTimeoutFn = useCallback((callback: () => void, delay: number) => {
    const id = setTimeout(() => {
      callback();
      timeoutIds.current.delete(id);
    }, delay);
    timeoutIds.current.add(id);
    return id;
  }, []);

  const clearTimeoutFn = useCallback((id: NodeJS.Timeout) => {
    clearTimeout(id);
    timeoutIds.current.delete(id);
  }, []);

  return { setTimeout: setTimeoutFn, clearTimeout: clearTimeoutFn };
}

/**
 * Hook that runs a callback after a delay. The timeout is automatically
 * cleaned up on unmount and reset when dependencies change.
 *
 * @example
 * useTimeoutEffect(() => {
 *   console.log('Delayed action');
 * }, 1000, [someDependency]);
 */
export function useTimeoutEffect(
  callback: () => void,
  delay: number | null,
  deps: React.DependencyList = [],
) {
  const callbackRef = useRef(callback);

  // Keep callback ref up to date
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    // Skip if delay is null
    if (delay === null) return;

    const id = setTimeout(() => callbackRef.current(), delay);

    return () => clearTimeout(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [delay, ...deps]);
}

/**
 * Hook that provides an interval function that's automatically cleaned up on unmount.
 * Returns stable function references for setting and clearing intervals.
 *
 * @example
 * const { setInterval, clearInterval } = useInterval();
 * const id = setInterval(() => console.log('Tick'), 1000);
 * clearInterval(id);
 */
export function useInterval() {
  const intervalIds = useRef<Set<NodeJS.Timeout>>(new Set());

  // Cleanup all intervals on unmount
  useEffect(() => {
    const ids = intervalIds.current;
    return () => {
      ids.forEach((id) => clearInterval(id));
      ids.clear();
    };
  }, []);

  const setIntervalFn = useCallback((callback: () => void, delay: number) => {
    const id = setInterval(callback, delay);
    intervalIds.current.add(id);
    return id;
  }, []);

  const clearIntervalFn = useCallback((id: NodeJS.Timeout) => {
    clearInterval(id);
    intervalIds.current.delete(id);
  }, []);

  return { setInterval: setIntervalFn, clearInterval: clearIntervalFn };
}

/**
 * Hook that runs a callback at a regular interval. The interval is automatically
 * cleaned up on unmount and reset when dependencies change.
 *
 * @example
 * useIntervalEffect(() => {
 *   fetchData();
 * }, 5000, [userId]);
 */
export function useIntervalEffect(
  callback: () => void,
  delay: number | null,
  deps: React.DependencyList = [],
) {
  const callbackRef = useRef(callback);

  // Keep callback ref up to date
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  useEffect(() => {
    // Skip if delay is null
    if (delay === null) return;

    const id = setInterval(() => callbackRef.current(), delay);

    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [delay, ...deps]);
}

/**
 * Hook for debouncing a value. Returns the debounced value that updates
 * after the specified delay.
 *
 * @example
 * const debouncedSearch = useDebounce(searchTerm, 300);
 */
export function useDebounce<T>(value: T, delay: number): T {
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const valueRef = useRef(value);
  const [, forceUpdate] = useReducer((x) => x + 1, 0);

  useEffect(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    timeoutRef.current = setTimeout(() => {
      valueRef.current = value;
      forceUpdate();
    }, delay);

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [value, delay]);

  return valueRef.current;
}

/**
 * Hook for throttling a callback. Returns a throttled version of the callback
 * that can only be called once per the specified delay.
 *
 * @example
 * const throttledScroll = useThrottle((e) => console.log(e), 100);
 */
export function useThrottle<T extends (...args: unknown[]) => unknown>(
  callback: T,
  delay: number,
): T {
  const lastRan = useRef(0);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);
  const callbackRef = useRef(callback);

  // Keep callback ref up to date
  useEffect(() => {
    callbackRef.current = callback;
  }, [callback]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, []);

  return useCallback(
    ((...args) => {
      const now = Date.now();
      const remaining = delay - (now - lastRan.current);

      if (remaining <= 0) {
        lastRan.current = now;
        callbackRef.current(...args);
      } else if (!timeoutRef.current) {
        timeoutRef.current = setTimeout(() => {
          lastRan.current = Date.now();
          timeoutRef.current = null;
          callbackRef.current(...args);
        }, remaining);
      }
    }) as T,
    [delay],
  );
}
