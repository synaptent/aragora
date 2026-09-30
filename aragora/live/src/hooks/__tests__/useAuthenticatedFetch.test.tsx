/**
 * Tests for useAuthenticatedFetch and useAuthFetch hooks
 *
 * Tests cover:
 * - Auto-fetch on mount
 * - Auth-aware skipping (when not authenticated)
 * - Token handling and Authorization header
 * - Error handling (HTTP errors, network errors)
 * - Manual fetch mode
 * - Refetch functionality
 * - Loading states
 * - Callbacks (onSuccess, onError)
 * - Dependency-based refetching
 * - 401 silent handling
 */

import { renderHook, waitFor, act } from '@testing-library/react';
import { useAuthenticatedFetch, useAuthFetch } from '../useAuthenticatedFetch';

// Mock the AuthContext
jest.mock('@/context/AuthContext', () => ({
  ...jest.requireActual('@/context/AuthContext'),
  useAuth: jest.fn(),
}));

// Import mocked useAuth
import { useAuth } from '@/context/AuthContext';
const mockUseAuth = useAuth as jest.Mock;

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock config
jest.mock('@/config', () => ({ API_BASE_URL: 'http://localhost:8080' }));

// Mock logger
jest.mock('@/utils/logger', () => ({
  logger: { debug: jest.fn(), warn: jest.fn(), error: jest.fn() },
}));

describe('useAuthenticatedFetch', () => {
  const mockTokens = {
    access_token: 'test-access-token',
    refresh_token: 'test-refresh-token',
    expires_at: new Date(Date.now() + 3600000).toISOString(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    localStorage.clear();
  });

  describe('when authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        tokens: mockTokens,
        refreshToken: jest.fn().mockResolvedValue(false),
      });
    });

    it('auto-fetches on mount', async () => {
      const responseData = { items: [1, 2, 3] };
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => responseData });

      const { result } = renderHook(() => useAuthenticatedFetch<{ items: number[] }>('/api/items'));

      expect(result.current.loading).toBe(true);

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.data).toEqual(responseData);
      expect(result.current.error).toBeNull();
      expect(result.current.skipped).toBe(false);
    });

    it('includes Authorization header', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

      renderHook(() => useAuthenticatedFetch('/api/test'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/test',
        expect.objectContaining({
          headers: expect.objectContaining({ Authorization: 'Bearer test-access-token' }),
        }),
      );
    });

    it('uses the saved runtime backend for relative requests', async () => {
      localStorage.setItem('aragora-backend', 'production');
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

      renderHook(() => useAuthenticatedFetch('/api/test'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      expect(mockFetch).toHaveBeenCalledWith('https://api.aragora.ai/api/test', expect.any(Object));
    });

    it('handles HTTP errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 500,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ error: 'Internal server error' }),
      });

      const { result } = renderHook(() => useAuthenticatedFetch('/api/error'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Internal server error');
      expect(result.current.data).toBeNull();
    });

    it('handles network errors', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network failure'));

      const { result } = renderHook(() => useAuthenticatedFetch('/api/test'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.error).toBe('Network failure');
    });

    it('calls onSuccess callback', async () => {
      const onSuccess = jest.fn();
      const responseData = { success: true };
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => responseData });

      renderHook(() => useAuthenticatedFetch('/api/test', { onSuccess }));

      await waitFor(() => {
        expect(onSuccess).toHaveBeenCalledWith(responseData);
      });
    });

    it('calls onError callback', async () => {
      const onError = jest.fn();
      mockFetch.mockRejectedValueOnce(new Error('Test error'));

      renderHook(() => useAuthenticatedFetch('/api/test', { onError }));

      await waitFor(() => {
        expect(onError).toHaveBeenCalled();
      });

      expect(onError.mock.calls[0][0]).toBeInstanceOf(Error);
      expect(onError.mock.calls[0][0].message).toBe('Test error');
    });

    it('supports manual mode (no auto-fetch)', async () => {
      const { result } = renderHook(() => useAuthenticatedFetch('/api/test', { manual: true }));

      // Should not be loading since manual mode
      expect(result.current.loading).toBe(false);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('refetch works in manual mode', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ refetched: true }) });

      const { result } = renderHook(() => useAuthenticatedFetch('/api/test', { manual: true }));

      await act(async () => {
        await result.current.refetch();
      });

      expect(result.current.data).toEqual({ refetched: true });
    });

    it('handles 401 silently when requireAuth is true', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: async () => ({ error: 'Unauthorized' }),
      });

      const { result } = renderHook(() =>
        useAuthenticatedFetch('/api/test', { requireAuth: true }),
      );

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.skipped).toBe(true);
      expect(result.current.error).toBeNull();
    });

    it('uses defaultData when provided', async () => {
      mockFetch.mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) });

      const defaultData = { items: [] };
      const { result } = renderHook(() => useAuthenticatedFetch('/api/test', { defaultData }));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.data).toEqual(defaultData);
    });

    it('handles absolute URLs', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) });

      renderHook(() => useAuthenticatedFetch('https://external.api.com/data'));

      await waitFor(() => {
        expect(mockFetch).toHaveBeenCalled();
      });

      expect(mockFetch).toHaveBeenCalledWith('https://external.api.com/data', expect.any(Object));
    });
  });

  describe('when not authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false, tokens: null });
    });

    it('skips fetch when requireAuth is true (default)', async () => {
      const { result } = renderHook(() => useAuthenticatedFetch('/api/protected'));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.skipped).toBe(true);
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('returns defaultData when skipped', async () => {
      const defaultData = { empty: true };
      const { result } = renderHook(() => useAuthenticatedFetch('/api/test', { defaultData }));

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.data).toEqual(defaultData);
    });

    it('fetches when requireAuth is false', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ public: true }) });

      const { result } = renderHook(() =>
        useAuthenticatedFetch('/api/public', { requireAuth: false }),
      );

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(mockFetch).toHaveBeenCalled();
      expect(result.current.data).toEqual({ public: true });
    });
  });

  describe('when auth is loading', () => {
    it('waits for auth to finish loading', async () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: true, tokens: null });

      const { result, rerender } = renderHook(() => useAuthenticatedFetch('/api/test'));

      // Should still be in initial loading state
      expect(result.current.loading).toBe(true);
      expect(mockFetch).not.toHaveBeenCalled();

      // Simulate auth finishing
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        tokens: mockTokens,
        refreshToken: jest.fn().mockResolvedValue(false),
      });

      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ loaded: true }) });

      rerender();

      await waitFor(() => {
        expect(result.current.loading).toBe(false);
      });

      expect(result.current.data).toEqual({ loaded: true });
    });
  });
});

describe('useAuthFetch', () => {
  const mockTokens = {
    access_token: 'test-access-token',
    refresh_token: 'test-refresh-token',
    expires_at: new Date(Date.now() + 3600000).toISOString(),
  };

  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    localStorage.clear();
  });

  describe('when authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        isLoading: false,
        tokens: mockTokens,
        refreshToken: jest.fn().mockResolvedValue(false),
      });
    });

    it('provides authFetch function', () => {
      const { result } = renderHook(() => useAuthFetch());

      expect(typeof result.current.authFetch).toBe('function');
      expect(result.current.isAuthenticated).toBe(true);
    });

    it('authFetch includes Authorization header', async () => {
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ created: true }) });

      const { result } = renderHook(() => useAuthFetch());

      await act(async () => {
        await result.current.authFetch('/api/items', { method: 'POST' });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/items',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({
            Authorization: 'Bearer test-access-token',
            'Content-Type': 'application/json',
          }),
        }),
      );
    });

    it('authFetch uses the saved runtime backend for relative requests', async () => {
      localStorage.setItem('aragora-backend', 'production');
      mockFetch.mockResolvedValueOnce({ ok: true, json: async () => ({ created: true }) });

      const { result } = renderHook(() => useAuthFetch());

      await act(async () => {
        await result.current.authFetch('/api/items', { method: 'POST' });
      });

      expect(mockFetch).toHaveBeenCalledWith(
        'https://api.aragora.ai/api/items',
        expect.objectContaining({
          method: 'POST',
          headers: expect.objectContaining({ Authorization: 'Bearer test-access-token' }),
        }),
      );
    });

    it('authFetch handles HTTP errors', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 400,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ error: 'Bad request' }),
      });

      const { result } = renderHook(() => useAuthFetch());

      await expect(result.current.authFetch('/api/error')).rejects.toThrow('Bad request');
    });

    it('getAuthHeaders returns headers with token', () => {
      const { result } = renderHook(() => useAuthFetch());

      const headers = result.current.getAuthHeaders();

      expect(headers).toEqual({
        'Content-Type': 'application/json',
        Authorization: 'Bearer test-access-token',
      });
    });
  });

  describe('when not authenticated', () => {
    beforeEach(() => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, isLoading: false, tokens: null });
    });

    it('authFetch returns null', async () => {
      const { result } = renderHook(() => useAuthFetch());

      const response = await result.current.authFetch('/api/test');

      expect(response).toBeNull();
      expect(mockFetch).not.toHaveBeenCalled();
    });

    it('getAuthHeaders returns headers without Authorization', () => {
      const { result } = renderHook(() => useAuthFetch());

      const headers = result.current.getAuthHeaders();

      expect(headers).toEqual({ 'Content-Type': 'application/json' });
      expect(headers).not.toHaveProperty('Authorization');
    });

    it('isAuthenticated is false', () => {
      const { result } = renderHook(() => useAuthFetch());

      expect(result.current.isAuthenticated).toBe(false);
    });
  });
});
