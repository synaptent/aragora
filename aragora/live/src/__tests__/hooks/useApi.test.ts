import { renderHook, act } from '@testing-library/react';
import { useApi } from '@/hooks/useApi';
import { fetchWithRetry } from '@/lib/retry';

// Mock the retry module
jest.mock('@/lib/retry', () => ({ fetchWithRetry: jest.fn() }));

const mockFetchWithRetry = fetchWithRetry as jest.MockedFunction<typeof fetchWithRetry>;

describe('useApi', () => {
  const baseUrl = 'https://api.test.com';

  beforeEach(() => {
    jest.clearAllMocks();
  });

  describe('initial state', () => {
    it('should start with null data and not loading', () => {
      const { result } = renderHook(() => useApi(baseUrl));

      expect(result.current.data).toBeNull();
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('should have get, post, put, delete, request, and reset methods', () => {
      const { result } = renderHook(() => useApi(baseUrl));

      expect(typeof result.current.get).toBe('function');
      expect(typeof result.current.post).toBe('function');
      expect(typeof result.current.put).toBe('function');
      expect(typeof result.current.delete).toBe('function');
      expect(typeof result.current.request).toBe('function');
      expect(typeof result.current.reset).toBe('function');
    });
  });

  describe('GET requests', () => {
    it('should make GET request successfully', async () => {
      const mockData = { id: 1, name: 'test' };
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve(mockData),
      } as Response);

      const { result } = renderHook(() => useApi<typeof mockData>(baseUrl));

      let response: typeof mockData | undefined;
      await act(async () => {
        response = await result.current.get('/api/data');
      });

      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        'https://api.test.com/api/data',
        expect.objectContaining({ method: 'GET', headers: { 'Content-Type': 'application/json' } }),
        expect.any(Object),
      );
      expect(response).toEqual(mockData);
      expect(result.current.data).toEqual(mockData);
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it('should set loading state during request', async () => {
      let resolvePromise: (value: Response) => void;
      mockFetchWithRetry.mockReturnValueOnce(
        new Promise<Response>((resolve) => {
          resolvePromise = resolve;
        }),
      );

      const { result } = renderHook(() => useApi(baseUrl));

      act(() => {
        result.current.get('/api/data');
      });

      expect(result.current.loading).toBe(true);

      await act(async () => {
        resolvePromise!({ json: () => Promise.resolve({ data: 'test' }) } as Response);
      });

      expect(result.current.loading).toBe(false);
    });

    it('should handle GET error', async () => {
      const error = new Error('Network error');
      mockFetchWithRetry.mockRejectedValueOnce(error);

      const { result } = renderHook(() => useApi(baseUrl));

      await act(async () => {
        try {
          await result.current.get('/api/data');
        } catch {
          // Expected to throw
        }
      });

      expect(result.current.error).toBe('Network error');
      expect(result.current.data).toBeNull();
      expect(result.current.loading).toBe(false);
    });
  });

  describe('POST requests', () => {
    it('should make POST request with body', async () => {
      const mockData = { success: true };
      const body = { name: 'test', value: 123 };
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve(mockData),
      } as Response);

      const { result } = renderHook(() => useApi<typeof mockData>(baseUrl));

      await act(async () => {
        await result.current.post('/api/create', body);
      });

      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        'https://api.test.com/api/create',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify(body),
          headers: { 'Content-Type': 'application/json' },
        }),
        expect.any(Object),
      );
      expect(result.current.data).toEqual(mockData);
    });

    it('should make POST request without body', async () => {
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve({ created: true }),
      } as Response);

      const { result } = renderHook(() => useApi(baseUrl));

      await act(async () => {
        await result.current.post('/api/trigger');
      });

      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        'https://api.test.com/api/trigger',
        expect.objectContaining({ method: 'POST', body: undefined }),
        expect.any(Object),
      );
    });
  });

  describe('PUT requests', () => {
    it('should make PUT request with body', async () => {
      const mockData = { updated: true };
      const body = { id: 1, name: 'updated' };
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve(mockData),
      } as Response);

      const { result } = renderHook(() => useApi<typeof mockData>(baseUrl));

      await act(async () => {
        await result.current.put('/api/update/1', body);
      });

      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        'https://api.test.com/api/update/1',
        expect.objectContaining({ method: 'PUT', body: JSON.stringify(body) }),
        expect.any(Object),
      );
      expect(result.current.data).toEqual(mockData);
    });
  });

  describe('DELETE requests', () => {
    it('should make DELETE request', async () => {
      const mockData = { deleted: true };
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve(mockData),
      } as Response);

      const { result } = renderHook(() => useApi<typeof mockData>(baseUrl));

      await act(async () => {
        await result.current.delete('/api/delete/1');
      });

      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        'https://api.test.com/api/delete/1',
        expect.objectContaining({ method: 'DELETE' }),
        expect.any(Object),
      );
      expect(result.current.data).toEqual(mockData);
    });
  });

  describe('request deduplication', () => {
    it('should deduplicate in-flight requests to the same endpoint', async () => {
      let resolvePromise: (value: Response) => void;
      mockFetchWithRetry.mockReturnValue(
        new Promise<Response>((resolve) => {
          resolvePromise = resolve;
        }),
      );

      const { result } = renderHook(() => useApi(baseUrl));

      // Start two identical requests - use act to properly wrap state updates
      let promise1: Promise<unknown>;
      let promise2: Promise<unknown>;
      act(() => {
        promise1 = result.current.get('/api/data');
        promise2 = result.current.get('/api/data');
      });

      // Only one fetch call should be made (the key test)
      expect(mockFetchWithRetry).toHaveBeenCalledTimes(1);

      // Resolve and clean up
      await act(async () => {
        resolvePromise!({ json: () => Promise.resolve({ data: 'test' }) } as Response);
        await Promise.all([promise1!, promise2!]);
      });
    });

    it('should not deduplicate different endpoints', async () => {
      mockFetchWithRetry.mockResolvedValue({
        json: () => Promise.resolve({ data: 'test' }),
      } as Response);

      const { result } = renderHook(() => useApi(baseUrl));

      await act(async () => {
        await Promise.all([result.current.get('/api/data1'), result.current.get('/api/data2')]);
      });

      expect(mockFetchWithRetry).toHaveBeenCalledTimes(2);
    });

    it('should not deduplicate different methods', async () => {
      mockFetchWithRetry.mockResolvedValue({
        json: () => Promise.resolve({ data: 'test' }),
      } as Response);

      const { result } = renderHook(() => useApi(baseUrl));

      await act(async () => {
        await Promise.all([result.current.get('/api/data'), result.current.post('/api/data', {})]);
      });

      expect(mockFetchWithRetry).toHaveBeenCalledTimes(2);
    });

    it('should allow new request after previous completes', async () => {
      mockFetchWithRetry.mockResolvedValue({
        json: () => Promise.resolve({ data: 'test' }),
      } as Response);

      const { result } = renderHook(() => useApi(baseUrl));

      await act(async () => {
        await result.current.get('/api/data');
      });

      await act(async () => {
        await result.current.get('/api/data');
      });

      expect(mockFetchWithRetry).toHaveBeenCalledTimes(2);
    });
  });

  describe('callbacks', () => {
    it('should call onSuccess callback on success', async () => {
      const onSuccess = jest.fn();
      const mockData = { id: 1 };
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve(mockData),
      } as Response);

      const { result } = renderHook(() => useApi(baseUrl, { onSuccess }));

      await act(async () => {
        await result.current.get('/api/data');
      });

      expect(onSuccess).toHaveBeenCalledWith(mockData);
    });

    it('should call onError callback on error', async () => {
      const onError = jest.fn();
      const error = new Error('Request failed');
      mockFetchWithRetry.mockRejectedValueOnce(error);

      const { result } = renderHook(() => useApi(baseUrl, { onError }));

      await act(async () => {
        try {
          await result.current.get('/api/data');
        } catch {
          // Expected
        }
      });

      expect(onError).toHaveBeenCalledWith(error);
    });

    it('should convert non-Error throws to Error in onError', async () => {
      const onError = jest.fn();
      // The hook converts non-Error to "Request failed" message
      mockFetchWithRetry.mockRejectedValueOnce('string error');

      const { result } = renderHook(() => useApi(baseUrl, { onError }));

      await act(async () => {
        try {
          await result.current.get('/api/data');
        } catch {
          // Expected
        }
      });

      expect(onError).toHaveBeenCalledWith(expect.any(Error));
      // Hook uses "Request failed" as fallback for non-Error throws
      expect(onError.mock.calls[0][0].message).toBe('Request failed');
    });
  });

  describe('reset', () => {
    it('should reset state to initial values', async () => {
      const mockData = { id: 1 };
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve(mockData),
      } as Response);

      const { result } = renderHook(() => useApi<typeof mockData>(baseUrl));

      await act(async () => {
        await result.current.get('/api/data');
      });

      expect(result.current.data).toEqual(mockData);

      act(() => {
        result.current.reset();
      });

      expect(result.current.data).toBeNull();
      expect(result.current.loading).toBe(false);
      expect(result.current.error).toBeNull();
    });
  });

  describe('custom request', () => {
    it('should support custom request init options', async () => {
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve({ ok: true }),
      } as Response);

      const { result } = renderHook(() => useApi(baseUrl));

      await act(async () => {
        await result.current.request('/api/custom', {
          method: 'PATCH',
          headers: { 'X-Custom-Header': 'value' },
        });
      });

      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        'https://api.test.com/api/custom',
        expect.objectContaining({
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', 'X-Custom-Header': 'value' },
        }),
        expect.any(Object),
      );
    });

    it('should support custom retry config', async () => {
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve({ ok: true }),
      } as Response);

      const customRetryConfig = { maxAttempts: 5, initialDelayMs: 500 };

      const { result } = renderHook(() => useApi(baseUrl));

      await act(async () => {
        await result.current.get('/api/data', customRetryConfig);
      });

      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        expect.any(String),
        expect.any(Object),
        expect.objectContaining(customRetryConfig),
      );
    });
  });

  describe('retry config from options', () => {
    it('should pass retry config from hook options', async () => {
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve({ ok: true }),
      } as Response);

      const hookOptions = { maxAttempts: 10, initialDelayMs: 2000 };

      const { result } = renderHook(() => useApi(baseUrl, hookOptions));

      await act(async () => {
        await result.current.get('/api/data');
      });

      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        expect.any(String),
        expect.any(Object),
        expect.objectContaining(hookOptions),
      );
    });

    it('should merge method-level retry config with hook options', async () => {
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve({ ok: true }),
      } as Response);

      const hookOptions = { maxAttempts: 10 };
      const methodConfig = { initialDelayMs: 500 };

      const { result } = renderHook(() => useApi(baseUrl, hookOptions));

      await act(async () => {
        await result.current.get('/api/data', methodConfig);
      });

      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        expect.any(String),
        expect.any(Object),
        expect.objectContaining({ maxAttempts: 10, initialDelayMs: 500 }),
      );
    });
  });

  describe('error handling', () => {
    it('should extract error message from Error instances', async () => {
      mockFetchWithRetry.mockRejectedValueOnce(new Error('Custom error message'));

      const { result } = renderHook(() => useApi(baseUrl));

      await act(async () => {
        try {
          await result.current.get('/api/data');
        } catch {
          // Expected
        }
      });

      expect(result.current.error).toBe('Custom error message');
    });

    it('should use default message for non-Error throws', async () => {
      mockFetchWithRetry.mockRejectedValueOnce('string error');

      const { result } = renderHook(() => useApi(baseUrl));

      await act(async () => {
        try {
          await result.current.get('/api/data');
        } catch {
          // Expected
        }
      });

      // Hook uses "Request failed" as fallback for non-Error throws
      expect(result.current.error).toBe('Request failed');
    });

    it('should re-throw error after setting state', async () => {
      const error = new Error('Should throw');
      mockFetchWithRetry.mockRejectedValueOnce(error);

      const { result } = renderHook(() => useApi(baseUrl));

      let thrownError: Error | null = null;
      await act(async () => {
        try {
          await result.current.get('/api/data');
        } catch (e) {
          thrownError = e as Error;
        }
      });

      expect(thrownError?.message).toBe('Should throw');
    });
  });

  describe('default base URL', () => {
    it('should use default base URL when not provided', async () => {
      mockFetchWithRetry.mockResolvedValueOnce({
        json: () => Promise.resolve({ ok: true }),
      } as Response);

      const { result } = renderHook(() => useApi());

      await act(async () => {
        await result.current.get('/api/test');
      });

      // Should use the default or env URL
      expect(mockFetchWithRetry).toHaveBeenCalledWith(
        expect.stringContaining('/api/test'),
        expect.any(Object),
        expect.any(Object),
      );
    });
  });
});
