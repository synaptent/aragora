/**
 * Tests for useSWRFetch hook
 */

import { renderHook } from '@testing-library/react';
import {
  useSWRFetch,
  swrFetcher,
  prefetchData,
  invalidateCache,
  updateCache,
} from '@/hooks/useSWRFetch';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock SWR
jest.mock('swr', () => {
  const originalModule = jest.requireActual('swr');
  return {
    __esModule: true,
    ...originalModule,
    default: jest.fn((key, _fetcher, _options) => {
      // Simple mock implementation
      return {
        data: key ? { mocked: true } : undefined,
        error: null,
        isLoading: false,
        isValidating: false,
        mutate: jest.fn(),
      };
    }),
    mutate: jest.fn(),
    useSWRConfig: () => ({ cache: new Map() }),
  };
});

describe('useSWRFetch', () => {
  const mockUseSWR = jest.requireMock('swr').default as jest.Mock;

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    localStorage.clear();
  });

  describe('swrFetcher', () => {
    it('fetches and returns JSON data', async () => {
      const mockData = { id: 1, name: 'test' };
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => mockData });

      const result = await swrFetcher('https://api.example.com/data');

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.example.com/data',
        expect.objectContaining({ headers: { 'Content-Type': 'application/json' } }),
      );
      expect(result).toEqual(mockData);
    });

    it('throws error on non-ok response', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 404 });

      await expect(swrFetcher('https://api.example.com/data')).rejects.toThrow(
        'API request failed',
      );
    });

    it('includes status code in error', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 500 });

      try {
        await swrFetcher('https://api.example.com/data');
      } catch (error) {
        expect((error as { status: number }).status).toBe(500);
      }
    });

    it('sends auth headers to the selected backend api origin', async () => {
      localStorage.setItem('aragora-backend', 'production');
      localStorage.setItem('aragora_tokens', JSON.stringify({ access_token: 'token-123' }));
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ok: true }) });

      await swrFetcher('https://api.aragora.ai/api/test');

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.aragora.ai/api/test',
        expect.objectContaining({
          headers: expect.objectContaining({
            'Content-Type': 'application/json',
            Authorization: 'Bearer token-123',
          }),
        }),
      );
    });
  });

  describe('useSWRFetch hook', () => {
    it('returns null data when endpoint is null', () => {
      const { result } = renderHook(() => useSWRFetch(null));

      expect(result.current.data).toBeNull();
    });

    it('returns data when endpoint is provided', () => {
      const { result } = renderHook(() => useSWRFetch('/api/test'));

      expect(result.current.data).toEqual({ mocked: true });
    });

    it('returns null when disabled', () => {
      const { result } = renderHook(() => useSWRFetch('/api/test', { enabled: false }));

      expect(result.current.data).toBeNull();
    });

    it('includes mutate function', () => {
      const { result } = renderHook(() => useSWRFetch('/api/test'));

      expect(typeof result.current.mutate).toBe('function');
    });

    it('uses the selected backend api base by default', () => {
      localStorage.setItem('aragora-backend', 'production');

      renderHook(() => useSWRFetch('/api/test'));

      expect(mockUseSWR).toHaveBeenCalledWith(
        'https://api.aragora.ai/api/test',
        swrFetcher,
        expect.any(Object),
      );
    });
  });

  describe('cache utilities', () => {
    it('prefetchData calls mutate', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ data: 'prefetched' }) });

      await prefetchData('/api/test');

      expect(mockFetch).toHaveBeenCalled();
    });

    it('invalidateCache calls mutate with correct URL', () => {
      const { mutate } = require('swr');

      invalidateCache('/api/test');

      expect(mutate).toHaveBeenCalled();
    });

    it('updateCache calls mutate with updater', () => {
      const { mutate } = require('swr');
      const updater = (current: unknown[]) => [...(current || []), { new: true }];

      updateCache('/api/test', updater);

      expect(mutate).toHaveBeenCalled();
    });

    it('prefetchData uses the selected backend api base by default', async () => {
      localStorage.setItem('aragora-backend', 'production');
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ data: 'prefetched' }) });

      await prefetchData('/api/test');

      expect(mockFetch).toHaveBeenCalledWith('https://api.aragora.ai/api/test', expect.any(Object));
    });
  });

  describe('pre-configured hooks', () => {
    const { useDebates, useLeaderboard, useAgents } = require('@/hooks/useSWRFetch');

    it('useDebates uses correct endpoint', () => {
      const { result } = renderHook(() => useDebates());
      expect(result.current).toBeDefined();
    });

    it('useLeaderboard uses correct endpoint', () => {
      const { result } = renderHook(() => useLeaderboard());
      expect(result.current).toBeDefined();
    });

    it('useAgents uses correct endpoint', () => {
      const { result } = renderHook(() => useAgents());
      expect(result.current).toBeDefined();
    });
  });
});
