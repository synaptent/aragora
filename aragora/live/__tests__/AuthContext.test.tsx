/**
 * Tests for AuthContext and AuthProvider
 *
 * Tests cover:
 * - Initial loading state
 * - Login flow
 * - Registration flow
 * - Logout flow
 * - Token refresh
 * - Stored auth restoration
 * - Error handling
 */

import { waitFor, act } from '@testing-library/react';
import { renderHook } from '@testing-library/react';
import { AuthProvider, useAuth } from '../src/context/AuthContext';

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;

// Mock localStorage
const mockLocalStorage: Record<string, string> = {};
const localStorageMock = {
  getItem: jest.fn((key: string) => mockLocalStorage[key] || null),
  setItem: jest.fn((key: string, value: string) => {
    mockLocalStorage[key] = value;
  }),
  removeItem: jest.fn((key: string) => {
    delete mockLocalStorage[key];
  }),
  clear: jest.fn(() => {
    Object.keys(mockLocalStorage).forEach((key) => delete mockLocalStorage[key]);
  }),
};
Object.defineProperty(window, 'localStorage', { value: localStorageMock });

const mockUser = {
  id: 'user-123',
  email: 'test@example.com',
  name: 'Test User',
  role: 'user',
  org_id: 'org-123',
  is_active: true,
  created_at: '2026-01-10T00:00:00Z',
};

const mockTokens = {
  access_token: 'access-token-123',
  refresh_token: 'refresh-token-123',
  expires_at: new Date(Date.now() + 3600000).toISOString(), // 1 hour from now
};

const mockOrganization = {
  id: 'org-123',
  name: 'Test Org',
  slug: 'test-org',
  tier: 'starter',
  owner_id: 'user-123',
};

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

describe('AuthContext', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
    localStorageMock.clear();
  });

  describe('Initial State', () => {
    it('initializes to unauthenticated after mount', async () => {
      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
    });
  });

  describe('Login', () => {
    it('successfully logs in with valid credentials', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ user: mockUser, tokens: mockTokens, organization: mockOrganization }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      let loginResult: { success: boolean; error?: string };
      await act(async () => {
        loginResult = await result.current.login('test@example.com', 'password123');
      });

      expect(loginResult!.success).toBe(true);
      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.user?.email).toBe('test@example.com');
      expect(result.current.tokens?.access_token).toBe('access-token-123');
    });

    it('handles login failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ error: 'Invalid credentials' }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      let loginResult: { success: boolean; error?: string };
      await act(async () => {
        loginResult = await result.current.login('test@example.com', 'wrong-password');
      });

      expect(loginResult!.success).toBe(false);
      expect(loginResult!.error).toBe('Invalid credentials');
      expect(result.current.isAuthenticated).toBe(false);
    });

    it('handles network errors during login', async () => {
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      let loginResult: { success: boolean; error?: string };
      await act(async () => {
        loginResult = await result.current.login('test@example.com', 'password123');
      });

      expect(loginResult!.success).toBe(false);
      expect(loginResult!.error).toContain('error');
    });
  });

  describe('Registration', () => {
    it('successfully registers a new user', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ user: mockUser, tokens: mockTokens, organization: mockOrganization }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      let registerResult: { success: boolean; error?: string };
      await act(async () => {
        registerResult = await result.current.register(
          'new@example.com',
          'password123',
          'New User',
          'New Org',
        );
      });

      expect(registerResult!.success).toBe(true);
      expect(result.current.isAuthenticated).toBe(true);
    });

    it('handles registration failure', async () => {
      mockFetch.mockResolvedValueOnce({
        ok: false,
        json: () => Promise.resolve({ error: 'Email already exists' }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      let registerResult: { success: boolean; error?: string };
      await act(async () => {
        registerResult = await result.current.register('existing@example.com', 'password123');
      });

      expect(registerResult!.success).toBe(false);
      expect(registerResult!.error).toBe('Email already exists');
    });
  });

  describe('Logout', () => {
    it('clears auth state on logout', async () => {
      // Setup: Login first
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () =>
          Promise.resolve({ user: mockUser, tokens: mockTokens, organization: mockOrganization }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      await act(async () => {
        await result.current.login('test@example.com', 'password123');
      });

      expect(result.current.isAuthenticated).toBe(true);

      // Mock logout API call
      mockFetch.mockResolvedValueOnce({ ok: true });

      await act(async () => {
        await result.current.logout();
      });

      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
      expect(result.current.tokens).toBeNull();
      expect(localStorageMock.removeItem).toHaveBeenCalled();
    });
  });

  describe('Token Refresh', () => {
    it('successfully refreshes expired token', async () => {
      const newTokens = {
        access_token: 'new-access-token',
        refresh_token: 'new-refresh-token',
        expires_at: new Date(Date.now() + 3600000).toISOString(),
      };

      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

      // Mock the /api/auth/me call during mount validation
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ user: mockUser, organization: mockOrganization }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Mock refresh response
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ tokens: newTokens }),
      });

      let refreshSuccess: boolean;
      await act(async () => {
        refreshSuccess = await result.current.refreshToken();
      });

      expect(refreshSuccess!).toBe(true);
      expect(result.current.tokens?.access_token).toBe('new-access-token');
    });

    it('handles refresh failure', async () => {
      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

      // Mock the /api/auth/me call during mount validation
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ user: mockUser, organization: mockOrganization }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Mock refresh failure (401 triggers auth clearing)
      mockFetch.mockResolvedValueOnce({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ error: 'Invalid refresh token' }),
      });

      let refreshSuccess: boolean;
      await act(async () => {
        refreshSuccess = await result.current.refreshToken();
      });

      expect(refreshSuccess!).toBe(false);
      expect(result.current.isAuthenticated).toBe(false);
    });
  });

  describe('Stored Auth Restoration', () => {
    it('restores auth from localStorage on mount', async () => {
      // Pre-populate localStorage
      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

      // Mock the /api/auth/me call during mount validation
      mockFetch.mockResolvedValueOnce({
        ok: true,
        json: () => Promise.resolve({ user: mockUser, organization: mockOrganization }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // After restoration, should be authenticated
      expect(result.current.user).toBeTruthy();
      expect(result.current.tokens).toBeTruthy();
    });

    it('clears expired tokens from localStorage', async () => {
      const expiredTokens = {
        ...mockTokens,
        expires_at: new Date(Date.now() - 3600000).toISOString(), // 1 hour ago
      };

      mockLocalStorage['aragora_tokens'] = JSON.stringify(expiredTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

      // No /api/auth/me mock needed - expired tokens are caught before the fetch

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      // Expired tokens should be cleared
      expect(result.current.isAuthenticated).toBe(false);
    });
  });
});
