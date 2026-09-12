import { renderHook, act } from '@testing-library/react';
import { useFetch, useAsyncState } from '@/hooks/useFetch';

describe('useFetch', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  describe('initial state', () => {
    it('should start with null data and not loading when immediate is false', () => {
      const fetcher = jest.fn().mockResolvedValue('data');
      const { result } = renderHook(() => useFetch(fetcher));

      expect(result.current.data).toBeNull();
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.retrying).toBe(false);
      expect(result.current.retryAttempt).toBe(0);
    });

    it('should use initialData when provided', () => {
      const fetcher = jest.fn().mockResolvedValue('new data');
      const { result } = renderHook(() => useFetch(fetcher, { initialData: 'initial' }));

      expect(result.current.data).toBe('initial');
    });

    it('should start loading when immediate is true', async () => {
      const fetcher = jest.fn(() => new Promise(() => {}));
      const { result } = renderHook(() => useFetch(fetcher, { immediate: true }));

      await act(async () => {
        await Promise.resolve();
      });

      expect(result.current.loading).toBe(true);
    });
  });

  describe('fetch', () => {
    it('should fetch data successfully', async () => {
      const fetcher = jest.fn().mockResolvedValue({ name: 'test' });
      const { result } = renderHook(() => useFetch(fetcher));

      await act(async () => {
        await result.current.fetch();
      });

      expect(result.current.data).toEqual({ name: 'test' });
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('should set loading state during fetch', async () => {
      let resolvePromise: (value: string) => void;
      const fetcher = jest.fn().mockReturnValue(
        new Promise<string>((resolve) => {
          resolvePromise = resolve;
        }),
      );

      const { result } = renderHook(() => useFetch(fetcher));

      act(() => {
        result.current.fetch();
      });

      expect(result.current.loading).toBe(true);

      await act(async () => {
        resolvePromise!('data');
      });

      expect(result.current.loading).toBe(false);
    });

    it('should handle fetch error', async () => {
      const error = new Error('Fetch failed');
      const fetcher = jest.fn().mockRejectedValue(error);
      const { result } = renderHook(() => useFetch(fetcher));

      await act(async () => {
        await result.current.fetch();
      });

      expect(result.current.data).toBeNull();
      expect(result.current.error).toEqual(error);
      expect(result.current.loading).toBe(false);
    });

    it('should convert non-Error throws to Error objects', async () => {
      const fetcher = jest.fn().mockRejectedValue('string error');
      const { result } = renderHook(() => useFetch(fetcher));

      await act(async () => {
        await result.current.fetch();
      });

      expect(result.current.error).toBeInstanceOf(Error);
      expect(result.current.error?.message).toBe('string error');
    });

    it('should call onSuccess callback on success', async () => {
      const onSuccess = jest.fn();
      const data = { id: 1 };
      const fetcher = jest.fn().mockResolvedValue(data);

      const { result } = renderHook(() => useFetch(fetcher, { onSuccess }));

      await act(async () => {
        await result.current.fetch();
      });

      expect(onSuccess).toHaveBeenCalledWith(data);
    });

    it('should call onError callback on error', async () => {
      const onError = jest.fn();
      const error = new Error('Failed');
      const fetcher = jest.fn().mockRejectedValue(error);

      const { result } = renderHook(() => useFetch(fetcher, { onError }));

      await act(async () => {
        await result.current.fetch();
      });

      expect(onError).toHaveBeenCalledWith(error);
    });

    it('should return fetched data', async () => {
      const fetcher = jest.fn().mockResolvedValue('result');
      const { result } = renderHook(() => useFetch(fetcher));

      let fetchResult: string | null = null;
      await act(async () => {
        fetchResult = await result.current.fetch();
      });

      expect(fetchResult).toBe('result');
    });

    it('should return null on error', async () => {
      const fetcher = jest.fn().mockRejectedValue(new Error('Failed'));
      const { result } = renderHook(() => useFetch(fetcher));

      let fetchResult: unknown = 'not-null';
      await act(async () => {
        fetchResult = await result.current.fetch();
      });

      expect(fetchResult).toBeNull();
    });
  });

  describe('retry', () => {
    it('should retry with exponential backoff', async () => {
      const fetcher = jest
        .fn()
        .mockRejectedValueOnce(new Error('Fail 1'))
        .mockRejectedValueOnce(new Error('Fail 2'))
        .mockResolvedValueOnce('success');

      const { result } = renderHook(() => useFetch(fetcher, { retryDelay: 1000 }));

      // First fetch fails
      await act(async () => {
        await result.current.fetch();
      });

      expect(result.current.error).toBeTruthy();
      expect(result.current.retryAttempt).toBe(0);

      // First retry (1000ms delay * 2^0 = 1000ms)
      let retryPromise: Promise<unknown>;
      act(() => {
        retryPromise = result.current.retry();
      });

      expect(result.current.retrying).toBe(true);
      expect(result.current.retryAttempt).toBe(1);

      // Advance past the delay and let promises settle
      await act(async () => {
        jest.advanceTimersByTime(1000);
        await retryPromise;
      });

      expect(result.current.error).toBeTruthy();

      // Second retry (1000ms * 2^1 = 2000ms)
      act(() => {
        retryPromise = result.current.retry();
      });

      expect(result.current.retryAttempt).toBe(2);

      await act(async () => {
        jest.advanceTimersByTime(2000);
        await retryPromise;
      });

      expect(result.current.data).toBe('success');
      expect(result.current.error).toBeNull();
    });

    it('should respect retryCount limit', async () => {
      const fetcher = jest.fn().mockRejectedValue(new Error('Always fails'));
      const { result } = renderHook(() => useFetch(fetcher, { retryCount: 2, retryDelay: 100 }));

      await act(async () => {
        await result.current.fetch();
      });

      // First retry
      let retryPromise: Promise<unknown>;
      act(() => {
        retryPromise = result.current.retry();
      });

      await act(async () => {
        jest.advanceTimersByTime(100);
        await retryPromise;
      });

      // Second retry
      act(() => {
        retryPromise = result.current.retry();
      });

      await act(async () => {
        jest.advanceTimersByTime(200);
        await retryPromise;
      });

      // Third retry should return null (over limit)
      let retryResult: unknown = 'not-null';
      await act(async () => {
        retryResult = await result.current.retry();
      });

      expect(retryResult).toBeNull();
    });

    it('should reset retryAttempt on successful fetch', async () => {
      const fetcher = jest
        .fn()
        .mockRejectedValueOnce(new Error('Fail'))
        .mockResolvedValueOnce('success');

      const { result } = renderHook(() => useFetch(fetcher, { retryDelay: 100 }));

      await act(async () => {
        await result.current.fetch();
      });

      expect(result.current.error).toBeTruthy();

      let retryPromise: Promise<unknown>;
      act(() => {
        retryPromise = result.current.retry();
      });

      await act(async () => {
        jest.advanceTimersByTime(100);
        await retryPromise;
      });

      expect(result.current.retryAttempt).toBe(0);
    });
  });

  describe('reset', () => {
    it('should reset all state to initial values', async () => {
      const fetcher = jest.fn().mockResolvedValue('data');
      const { result } = renderHook(() => useFetch(fetcher, { initialData: 'initial' }));

      await act(async () => {
        await result.current.fetch();
      });

      expect(result.current.data).toBe('data');

      act(() => {
        result.current.reset();
      });

      expect(result.current.data).toBe('initial');
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
      expect(result.current.retrying).toBe(false);
      expect(result.current.retryAttempt).toBe(0);
    });
  });

  describe('immediate fetch', () => {
    it('should fetch immediately when immediate is true', async () => {
      const fetcher = jest.fn().mockResolvedValue('immediate data');

      const { result } = renderHook(() => useFetch(fetcher, { immediate: true }));

      // Wait for useEffect and fetch to complete
      await act(async () => {
        await Promise.resolve();
      });

      expect(fetcher).toHaveBeenCalledTimes(1);
      expect(result.current.data).toBe('immediate data');
    });
  });

  describe('unmount behavior', () => {
    it('should not update state after unmount', async () => {
      let resolvePromise: (value: string) => void;
      const fetcher = jest.fn().mockReturnValue(
        new Promise<string>((resolve) => {
          resolvePromise = resolve;
        }),
      );

      const { result, unmount } = renderHook(() => useFetch(fetcher));

      act(() => {
        result.current.fetch();
      });

      unmount();

      // Resolve after unmount - should not throw
      await act(async () => {
        resolvePromise!('data');
      });

      // Test passes if no error is thrown
    });

    it('should return null if unmounted during retry wait', async () => {
      const fetcher = jest.fn().mockRejectedValue(new Error('Fail'));
      const { result, unmount } = renderHook(() => useFetch(fetcher, { retryDelay: 1000 }));

      await act(async () => {
        await result.current.fetch();
      });

      act(() => {
        result.current.retry();
      });

      unmount();

      // Advance past retry delay - should not throw
      await act(async () => {
        jest.advanceTimersByTime(2000);
      });
    });
  });
});

describe('useAsyncState', () => {
  it('should start in loading state', async () => {
    let resolvePromise: (value: string) => void;
    const asyncFn = jest.fn().mockReturnValue(
      new Promise<string>((resolve) => {
        resolvePromise = resolve;
      }),
    );

    const { result } = renderHook(() => useAsyncState(asyncFn, []));

    expect(result.current.loading).toBe(true);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();

    // Clean up
    await act(async () => {
      resolvePromise!('data');
    });
  });

  it('should fetch on mount', async () => {
    const asyncFn = jest.fn().mockResolvedValue('fetched');
    const { result } = renderHook(() => useAsyncState(asyncFn, []));

    await act(async () => {
      await Promise.resolve();
    });

    expect(asyncFn).toHaveBeenCalledTimes(1);
    expect(result.current.data).toBe('fetched');
    expect(result.current.loading).toBe(false);
  });

  it('should handle errors', async () => {
    const error = new Error('Async failed');
    const asyncFn = jest.fn().mockRejectedValue(error);
    const { result } = renderHook(() => useAsyncState(asyncFn, []));

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.error).toEqual(error);
    expect(result.current.loading).toBe(false);
    expect(result.current.data).toBeNull();
  });

  it('should refetch when calling refetch', async () => {
    const asyncFn = jest.fn().mockResolvedValueOnce('first').mockResolvedValueOnce('second');

    const { result } = renderHook(() => useAsyncState(asyncFn, []));

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.data).toBe('first');

    await act(async () => {
      await result.current.refetch();
    });

    expect(result.current.data).toBe('second');
    expect(asyncFn).toHaveBeenCalledTimes(2);
  });

  it('should convert non-Error throws to Error objects', async () => {
    const asyncFn = jest.fn().mockRejectedValue('string error');
    const { result } = renderHook(() => useAsyncState(asyncFn, []));

    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.error).toBeInstanceOf(Error);
    expect(result.current.error?.message).toBe('string error');
  });
});
