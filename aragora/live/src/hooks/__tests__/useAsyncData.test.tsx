/**
 * Tests for useAsyncData, useFetch, and useMutation hooks
 *
 * Tests cover:
 * - useAsyncData: Basic fetching, loading states, error handling, callbacks
 * - useFetch: URL-based fetching, fetchOptions, error handling
 * - useMutation: Mutation execution, callbacks, loading states
 * - All hooks: Abort controller, unmount cleanup, reset functionality
 */

import { renderHook, act, waitFor } from '@testing-library/react';
import { useAsyncData, useFetch, useMutation } from '../useAsyncData';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

describe('useAsyncData', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Initial State', () => {
    it('starts with null data and not loading', () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      const { result } = renderHook(() => useAsyncData(fetcher));

      expect(result.current.data).toBeNull();
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.isInitialized).toBe(false);
      expect(result.current.isRevalidating).toBe(false);
    });

    it('uses initialData when provided', () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'new' });
      const initialData = { value: 'initial' };
      const { result } = renderHook(() => useAsyncData(fetcher, { initialData }));

      expect(result.current.data).toEqual(initialData);
    });
  });

  describe('Immediate Fetch', () => {
    it('fetches immediately when immediate is true', async () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      const { result } = renderHook(() => useAsyncData(fetcher, { immediate: true }));

      expect(result.current.loading).toBe(true);

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.data).toEqual({ value: 'test' });
      expect(result.current.isInitialized).toBe(true);
    });

    it('does not fetch immediately when immediate is false', () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      renderHook(() => useAsyncData(fetcher, { immediate: false }));

      expect(fetcher).not.toHaveBeenCalled();
    });
  });

  describe('Manual Refetch', () => {
    it('refetch triggers the fetcher', async () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      const { result } = renderHook(() => useAsyncData(fetcher));

      expect(fetcher).not.toHaveBeenCalled();

      await act(async () => {
        await result.current.refetch();
      });

      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(result.current.data).toEqual({ value: 'test' });
    });

    it('refetch returns the fetched data', async () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      const { result } = renderHook(() => useAsyncData(fetcher));

      let returnedData;
      await act(async () => {
        returnedData = await result.current.refetch();
      });

      expect(returnedData).toEqual({ value: 'test' });
    });

    it('cancels previous request on new refetch', async () => {
      let resolveFirst: (value: unknown) => void;
      const firstPromise = new Promise((resolve, _reject) => {
        resolveFirst = resolve;
      });

      const fetcher = jest
        .fn()
        .mockImplementationOnce(() => firstPromise)
        .mockResolvedValueOnce({ value: 'second' });

      const { result } = renderHook(() => useAsyncData(fetcher));

      // Start first fetch
      act(() => {
        result.current.refetch();
      });

      // Start second fetch before first completes
      await act(async () => {
        await result.current.refetch();
      });

      // Resolve first (should be ignored due to abort)
      resolveFirst!({ value: 'first' });

      expect(result.current.data).toEqual({ value: 'second' });
    });
  });

  describe('Loading States', () => {
    it('sets loading to true during fetch', async () => {
      let resolvePromise: (value: unknown) => void;
      const promise = new Promise((resolve) => {
        resolvePromise = resolve;
      });
      const fetcher = jest.fn().mockReturnValue(promise);

      const { result } = renderHook(() => useAsyncData(fetcher));

      act(() => {
        result.current.refetch();
      });

      expect(result.current.loading).toBe(true);

      await act(async () => {
        resolvePromise!({ value: 'test' });
      });

      expect(result.current.loading).toBe(false);
    });

    it('isRevalidating is true when loading with existing data', async () => {
      let resolvePromise: (value: unknown) => void;
      const fetcher = jest
        .fn()
        .mockResolvedValueOnce({ value: 'first' })
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolvePromise = resolve;
            }),
        );

      const { result } = renderHook(() => useAsyncData(fetcher));

      // First fetch
      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.data).toEqual({ value: 'first' });
      expect(result.current.isRevalidating).toBe(false);

      // Start second fetch
      act(() => {
        result.current.refetch();
      });

      expect(result.current.loading).toBe(true);
      expect(result.current.data).toEqual({ value: 'first' });
      expect(result.current.isRevalidating).toBe(true);

      await act(async () => {
        resolvePromise!({ value: 'second' });
      });

      expect(result.current.isRevalidating).toBe(false);
    });
  });

  describe('Error Handling', () => {
    it('sets error on fetch failure', async () => {
      const fetcher = jest.fn().mockRejectedValue(new Error('Fetch failed'));
      const { result } = renderHook(() => useAsyncData(fetcher));

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.error).toBe('Fetch failed');
      expect(result.current.errorObject).toBeInstanceOf(Error);
      expect(result.current.data).toBeNull();
      expect(result.current.isInitialized).toBe(true);
    });

    it('clears error on successful fetch', async () => {
      const fetcher = jest
        .fn()
        .mockRejectedValueOnce(new Error('Fetch failed'))
        .mockResolvedValueOnce({ value: 'success' });

      const { result } = renderHook(() => useAsyncData(fetcher));

      // First fetch fails
      await act(async () => {
        await result.current.refetch();
      });
      expect(result.current.error).toBe('Fetch failed');

      // Second fetch succeeds
      await act(async () => {
        await result.current.refetch();
      });
      expect(result.current.error).toBeNull();
      expect(result.current.errorObject).toBeNull();
    });

    it('handles non-Error throw', async () => {
      const fetcher = jest.fn().mockRejectedValue('String error');
      const { result } = renderHook(() => useAsyncData(fetcher));

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.error).toBe('String error');
    });

    it('does not set error on abort', async () => {
      const abortError = new Error('Aborted');
      abortError.name = 'AbortError';
      const fetcher = jest.fn().mockRejectedValue(abortError);
      const { result } = renderHook(() => useAsyncData(fetcher));

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.error).toBeNull();
    });
  });

  describe('Callbacks', () => {
    it('calls onSuccess with data', async () => {
      const onSuccess = jest.fn();
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      const { result } = renderHook(() => useAsyncData(fetcher, { onSuccess }));

      await act(async () => {
        await result.current.refetch();
      });

      expect(onSuccess).toHaveBeenCalledWith({ value: 'test' });
    });

    it('calls onError with error', async () => {
      const onError = jest.fn();
      const error = new Error('Fetch failed');
      const fetcher = jest.fn().mockRejectedValue(error);
      const { result } = renderHook(() => useAsyncData(fetcher, { onError }));

      await act(async () => {
        await result.current.refetch();
      });

      expect(onError).toHaveBeenCalledWith(error);
    });
  });

  describe('Transform', () => {
    it('applies transform to result', async () => {
      const fetcher = jest.fn().mockResolvedValue({ items: [1, 2, 3] });
      const transform = (data: unknown) => (data as { items: number[] }).items.length;

      const { result } = renderHook(() => useAsyncData(fetcher, { transform }));

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.data).toBe(3);
    });
  });

  describe('keepPreviousData', () => {
    it('keeps previous data while revalidating', async () => {
      let resolveSecond: (value: unknown) => void;
      const fetcher = jest
        .fn()
        .mockResolvedValueOnce({ value: 'first' })
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              resolveSecond = resolve;
            }),
        );

      const { result } = renderHook(() => useAsyncData(fetcher, { keepPreviousData: true }));

      // First fetch
      await act(async () => {
        await result.current.refetch();
      });
      expect(result.current.data).toEqual({ value: 'first' });

      // Start second fetch
      act(() => {
        result.current.refetch();
      });

      // Previous data should be preserved
      expect(result.current.data).toEqual({ value: 'first' });
      expect(result.current.loading).toBe(true);

      // Complete second fetch
      await act(async () => {
        resolveSecond!({ value: 'second' });
      });
      expect(result.current.data).toEqual({ value: 'second' });
    });
  });

  describe('Reset', () => {
    it('resets to initial state', async () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      const { result } = renderHook(() =>
        useAsyncData(fetcher, { initialData: { value: 'initial' } }),
      );

      // Fetch data
      await act(async () => {
        await result.current.refetch();
      });
      expect(result.current.data).toEqual({ value: 'test' });
      expect(result.current.isInitialized).toBe(true);

      // Reset
      act(() => {
        result.current.reset();
      });

      expect(result.current.data).toEqual({ value: 'initial' });
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.isInitialized).toBe(false);
    });
  });

  describe('Manual State Updates', () => {
    it('setData updates data', () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      const { result } = renderHook(() => useAsyncData(fetcher));

      act(() => {
        result.current.setData({ value: 'manual' });
      });

      expect(result.current.data).toEqual({ value: 'manual' });
    });

    it('setError updates error', () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      const { result } = renderHook(() => useAsyncData(fetcher));

      act(() => {
        result.current.setError('Manual error');
      });

      expect(result.current.error).toBe('Manual error');
    });
  });

  describe('Refresh Interval', () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    it('refetches at specified interval', async () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      renderHook(() => useAsyncData(fetcher, { refreshInterval: 1000 }));

      expect(fetcher).not.toHaveBeenCalled();

      // Advance time
      await act(async () => {
        jest.advanceTimersByTime(1000);
      });
      expect(fetcher).toHaveBeenCalledTimes(1);

      await act(async () => {
        jest.advanceTimersByTime(1000);
      });
      expect(fetcher).toHaveBeenCalledTimes(2);
    });

    it('clears interval on unmount', async () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      const { unmount } = renderHook(() => useAsyncData(fetcher, { refreshInterval: 1000 }));

      await act(async () => {
        jest.advanceTimersByTime(1000);
      });
      expect(fetcher).toHaveBeenCalledTimes(1);

      unmount();

      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
      // Should not increase after unmount
      expect(fetcher).toHaveBeenCalledTimes(1);
    });
  });

  describe('Dependencies', () => {
    it('refetches when deps change', async () => {
      const fetcher = jest.fn().mockResolvedValue({ value: 'test' });
      let dep = 'initial';

      const { rerender } = renderHook(() =>
        useAsyncData(fetcher, { immediate: true, deps: [dep] }),
      );

      await waitFor(() => {
        expect(fetcher).toHaveBeenCalledTimes(1);
      });

      // Change dependency
      dep = 'changed';
      rerender();

      await waitFor(() => {
        expect(fetcher).toHaveBeenCalledTimes(2);
      });
    });
  });
});

describe('useFetch', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  it('fetches from URL successfully', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ data: 'test' }) });

    const { result } = renderHook(() =>
      useFetch<{ data: string }>('/api/test', { immediate: true }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.data).toEqual({ data: 'test' });
    expect(mockFetch).toHaveBeenCalledWith(
      '/api/test',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('handles HTTP errors', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ error: 'Not found' }),
    });

    const { result } = renderHook(() => useFetch('/api/test', { immediate: true }));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBe('Not found');
  });

  it('handles HTTP error without error body', async () => {
    mockFetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error('Invalid JSON');
      },
    });

    const { result } = renderHook(() => useFetch('/api/test', { immediate: true }));

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(result.current.error).toBe('HTTP 500');
  });

  it('handles null URL', async () => {
    const { result } = renderHook(() => useFetch(null, { immediate: true }));

    // Should not fetch with null URL
    expect(mockFetch).not.toHaveBeenCalled();
    expect(result.current.loading).toBe(false);
  });

  it('passes fetchOptions to fetch', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ data: 'test' }) });

    const { result } = renderHook(() =>
      useFetch('/api/test', {
        immediate: true,
        fetchOptions: {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ key: 'value' }),
        },
      }),
    );

    await waitFor(() => {
      expect(result.current.loading).toBe(false);
    });

    expect(mockFetch).toHaveBeenCalledWith(
      '/api/test',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: 'value' }),
      }),
    );
  });

  it('refetches when URL changes', async () => {
    mockFetch.mockResolvedValue({ ok: true, json: async () => ({ data: 'test' }) });

    let url = '/api/test1';
    const { rerender } = renderHook(() => useFetch(url, { immediate: true }));

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith('/api/test1', expect.any(Object));
    });

    url = '/api/test2';
    rerender();

    await waitFor(() => {
      expect(mockFetch).toHaveBeenCalledWith('/api/test2', expect.any(Object));
    });
  });
});

describe('useMutation', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('Initial State', () => {
    it('starts with null data and not loading', () => {
      const mutationFn = jest.fn().mockResolvedValue({ success: true });
      const { result } = renderHook(() => useMutation(mutationFn));

      expect(result.current.data).toBeNull();
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });
  });

  describe('Mutation Execution', () => {
    it('executes mutation with variables', async () => {
      const mutationFn = jest.fn().mockResolvedValue({ id: 1 });
      const { result } = renderHook(() => useMutation(mutationFn));

      await act(async () => {
        await result.current.mutate({ name: 'test' });
      });

      expect(mutationFn).toHaveBeenCalledWith({ name: 'test' });
      expect(result.current.data).toEqual({ id: 1 });
    });

    it('returns mutation result', async () => {
      const mutationFn = jest.fn().mockResolvedValue({ id: 1 });
      const { result } = renderHook(() => useMutation(mutationFn));

      let returnedData;
      await act(async () => {
        returnedData = await result.current.mutate({ name: 'test' });
      });

      expect(returnedData).toEqual({ id: 1 });
    });

    it('sets loading during mutation', async () => {
      let resolvePromise: (value: unknown) => void;
      const promise = new Promise((resolve) => {
        resolvePromise = resolve;
      });
      const mutationFn = jest.fn().mockReturnValue(promise);

      const { result } = renderHook(() => useMutation(mutationFn));

      act(() => {
        result.current.mutate({});
      });

      expect(result.current.loading).toBe(true);

      await act(async () => {
        resolvePromise!({ success: true });
      });

      expect(result.current.loading).toBe(false);
    });
  });

  describe('Error Handling', () => {
    it('sets error on mutation failure', async () => {
      const mutationFn = jest.fn().mockRejectedValue(new Error('Mutation failed'));
      const { result } = renderHook(() => useMutation(mutationFn));

      await act(async () => {
        await result.current.mutate({});
      });

      expect(result.current.error).toBe('Mutation failed');
      expect(result.current.errorObject).toBeInstanceOf(Error);
      expect(result.current.data).toBeNull();
    });

    it('returns null on failure', async () => {
      const mutationFn = jest.fn().mockRejectedValue(new Error('Failed'));
      const { result } = renderHook(() => useMutation(mutationFn));

      let returnedData;
      await act(async () => {
        returnedData = await result.current.mutate({});
      });

      expect(returnedData).toBeNull();
    });

    it('clears error on next mutation', async () => {
      const mutationFn = jest
        .fn()
        .mockRejectedValueOnce(new Error('Failed'))
        .mockResolvedValueOnce({ success: true });

      const { result } = renderHook(() => useMutation(mutationFn));

      // First mutation fails
      await act(async () => {
        await result.current.mutate({});
      });
      expect(result.current.error).toBe('Failed');

      // Second mutation succeeds
      await act(async () => {
        await result.current.mutate({});
      });
      expect(result.current.error).toBeNull();
    });
  });

  describe('Callbacks', () => {
    it('calls onSuccess with data and variables', async () => {
      const onSuccess = jest.fn();
      const mutationFn = jest.fn().mockResolvedValue({ id: 1 });
      const { result } = renderHook(() => useMutation(mutationFn, { onSuccess }));

      await act(async () => {
        await result.current.mutate({ name: 'test' });
      });

      expect(onSuccess).toHaveBeenCalledWith({ id: 1 }, { name: 'test' });
    });

    it('calls onError with error and variables', async () => {
      const onError = jest.fn();
      const error = new Error('Failed');
      const mutationFn = jest.fn().mockRejectedValue(error);
      const { result } = renderHook(() => useMutation(mutationFn, { onError }));

      await act(async () => {
        await result.current.mutate({ name: 'test' });
      });

      expect(onError).toHaveBeenCalledWith(error, { name: 'test' });
    });

    it('calls onSettled on success', async () => {
      const onSettled = jest.fn();
      const mutationFn = jest.fn().mockResolvedValue({ id: 1 });
      const { result } = renderHook(() => useMutation(mutationFn, { onSettled }));

      await act(async () => {
        await result.current.mutate({ name: 'test' });
      });

      expect(onSettled).toHaveBeenCalledWith({ id: 1 }, null, { name: 'test' });
    });

    it('calls onSettled on error', async () => {
      const onSettled = jest.fn();
      const error = new Error('Failed');
      const mutationFn = jest.fn().mockRejectedValue(error);
      const { result } = renderHook(() => useMutation(mutationFn, { onSettled }));

      await act(async () => {
        await result.current.mutate({ name: 'test' });
      });

      expect(onSettled).toHaveBeenCalledWith(null, error, { name: 'test' });
    });
  });

  describe('Reset', () => {
    it('resets state', async () => {
      const mutationFn = jest.fn().mockResolvedValue({ id: 1 });
      const { result } = renderHook(() => useMutation(mutationFn));

      await act(async () => {
        await result.current.mutate({});
      });
      expect(result.current.data).toEqual({ id: 1 });

      act(() => {
        result.current.reset();
      });

      expect(result.current.data).toBeNull();
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });
  });

  describe('Typed Variables', () => {
    interface CreateUserInput {
      name: string;
      email: string;
    }

    interface User {
      id: number;
      name: string;
      email: string;
    }

    it('supports typed variables', async () => {
      const mutationFn = jest
        .fn()
        .mockImplementation((variables: CreateUserInput): Promise<User> =>
          Promise.resolve({ id: 1, name: variables.name, email: variables.email }),
        );

      const { result } = renderHook(() => useMutation<User, CreateUserInput>(mutationFn));

      await act(async () => {
        await result.current.mutate({ name: 'John', email: 'john@example.com' });
      });

      expect(result.current.data).toEqual({ id: 1, name: 'John', email: 'john@example.com' });
    });
  });
});
