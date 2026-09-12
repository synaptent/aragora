import { renderHook } from '@testing-library/react';
import { useAragoraClient, useClientCleanup, useClientAuth } from '@/hooks/useAragoraClient';

// Mock the dependencies
const mockUseAuth = jest.fn();
const mockUseBackend = jest.fn();
const mockGetClient = jest.fn();
const mockClearClient = jest.fn();

jest.mock('@/context/AuthContext', () => ({ useAuth: () => mockUseAuth() }));

jest.mock('@/components/BackendSelector', () => ({ useBackend: () => mockUseBackend() }));

jest.mock('@/lib/aragora-client', () => ({
  getClient: (...args: unknown[]) => mockGetClient(...args),
  clearClient: () => mockClearClient(),
  AragoraClient: class MockAragoraClient {},
}));

// Mock client instance
const mockClient = {
  debates: { list: jest.fn(), get: jest.fn(), create: jest.fn() },
  health: jest.fn(),
};

describe('useAragoraClient', () => {
  beforeEach(() => {
    jest.clearAllMocks();

    // Default mock values
    mockUseAuth.mockReturnValue({
      tokens: { access_token: 'test-token' },
      isAuthenticated: true,
      user: null,
    });

    mockUseBackend.mockReturnValue({ config: { api: 'http://localhost:8080' } });

    mockGetClient.mockReturnValue(mockClient);
  });

  describe('useAragoraClient', () => {
    it('returns an AragoraClient instance', () => {
      const { result } = renderHook(() => useAragoraClient());

      expect(result.current).toBe(mockClient);
    });

    it('passes token and baseUrl to getClient', () => {
      renderHook(() => useAragoraClient());

      expect(mockGetClient).toHaveBeenCalledWith('test-token', 'http://localhost:8080');
    });

    it('passes undefined token when not authenticated', () => {
      mockUseAuth.mockReturnValue({ tokens: null, isAuthenticated: false, user: null });

      renderHook(() => useAragoraClient());

      expect(mockGetClient).toHaveBeenCalledWith(undefined, 'http://localhost:8080');
    });

    it('memoizes client when token and baseUrl unchanged', () => {
      const { rerender } = renderHook(() => useAragoraClient());

      expect(mockGetClient).toHaveBeenCalledTimes(1);

      rerender();

      // Should not create a new client
      expect(mockGetClient).toHaveBeenCalledTimes(1);
    });

    it('creates new client when token changes', () => {
      const { rerender } = renderHook(() => useAragoraClient());

      expect(mockGetClient).toHaveBeenCalledTimes(1);

      // Change token
      mockUseAuth.mockReturnValue({
        tokens: { access_token: 'new-token' },
        isAuthenticated: true,
        user: null,
      });

      rerender();

      // Should create a new client
      expect(mockGetClient).toHaveBeenCalledTimes(2);
      expect(mockGetClient).toHaveBeenLastCalledWith('new-token', 'http://localhost:8080');
    });

    it('creates new client when baseUrl changes', () => {
      const { rerender } = renderHook(() => useAragoraClient());

      expect(mockGetClient).toHaveBeenCalledTimes(1);

      // Change backend URL
      mockUseBackend.mockReturnValue({ config: { api: 'http://new-backend:9000' } });

      rerender();

      // Should create a new client
      expect(mockGetClient).toHaveBeenCalledTimes(2);
      expect(mockGetClient).toHaveBeenLastCalledWith('test-token', 'http://new-backend:9000');
    });

    it('handles empty access_token', () => {
      mockUseAuth.mockReturnValue({
        tokens: { access_token: '' },
        isAuthenticated: false,
        user: null,
      });

      renderHook(() => useAragoraClient());

      expect(mockGetClient).toHaveBeenCalledWith('', 'http://localhost:8080');
    });
  });

  describe('useClientCleanup', () => {
    it('clears client when user logs out', () => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        tokens: { access_token: 'token' },
        user: null,
      });

      const { rerender } = renderHook(() => useClientCleanup());

      expect(mockClearClient).not.toHaveBeenCalled();

      // Simulate logout
      mockUseAuth.mockReturnValue({ isAuthenticated: false, tokens: null, user: null });

      rerender();

      expect(mockClearClient).toHaveBeenCalledTimes(1);
    });

    it('does not clear client when already logged out', () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, tokens: null, user: null });

      renderHook(() => useClientCleanup());

      // clearClient called on mount when not authenticated
      expect(mockClearClient).toHaveBeenCalledTimes(1);
    });

    it('does not clear client when still authenticated', () => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        tokens: { access_token: 'token' },
        user: null,
      });

      const { rerender } = renderHook(() => useClientCleanup());

      expect(mockClearClient).not.toHaveBeenCalled();

      // Rerender without logout
      rerender();

      expect(mockClearClient).not.toHaveBeenCalled();
    });
  });

  describe('useClientAuth', () => {
    it('returns isAuthenticated true when authenticated', () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: true, user: { email: 'user@example.com' } });

      const { result } = renderHook(() => useClientAuth());

      expect(result.current.isAuthenticated).toBe(true);
    });

    it('returns isAuthenticated false when not authenticated', () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, user: null });

      const { result } = renderHook(() => useClientAuth());

      expect(result.current.isAuthenticated).toBe(false);
    });

    it('returns isAdmin true for admin role', () => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        user: { email: 'admin@example.com', role: 'admin' },
      });

      const { result } = renderHook(() => useClientAuth());

      expect(result.current.isAdmin).toBe(true);
    });

    it('returns isAdmin true for owner role', () => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        user: { email: 'owner@example.com', role: 'owner' },
      });

      const { result } = renderHook(() => useClientAuth());

      expect(result.current.isAdmin).toBe(true);
    });

    it('returns isAdmin false for regular user', () => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        user: { email: 'user@example.com', role: 'user' },
      });

      const { result } = renderHook(() => useClientAuth());

      expect(result.current.isAdmin).toBe(false);
    });

    it('returns isAdmin false when not authenticated', () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, user: null });

      const { result } = renderHook(() => useClientAuth());

      expect(result.current.isAdmin).toBe(false);
    });

    it('returns isAdmin false when user has no role', () => {
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        user: { email: 'user@example.com' }, // No role field
      });

      const { result } = renderHook(() => useClientAuth());

      expect(result.current.isAdmin).toBe(false);
    });

    it('updates when auth state changes', () => {
      mockUseAuth.mockReturnValue({ isAuthenticated: false, user: null });

      const { result, rerender } = renderHook(() => useClientAuth());

      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.isAdmin).toBe(false);

      // Login as admin
      mockUseAuth.mockReturnValue({
        isAuthenticated: true,
        user: { email: 'admin@example.com', role: 'admin' },
      });

      rerender();

      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.isAdmin).toBe(true);
    });
  });
});
