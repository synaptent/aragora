/**
 * Additional Tests for AuthContext
 *
 * Tests cover features NOT in the root __tests__/AuthContext.test.tsx:
 * - setTokens (OAuth callback flow)
 * - Organization switching
 * - getCurrentOrgRole
 * - useAuth hook throws outside provider
 * - useRequireAuth redirects when not authenticated
 */

import React from 'react';
import { waitFor, act, renderHook } from '@testing-library/react';
import { AuthProvider, useAuth, useRequireAuth } from '../AuthContext';

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

// Mock data
const mockUser = {
  id: 'user-123',
  email: 'test@example.com',
  name: 'Test User',
  role: 'user',
  org_id: 'org-123',
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
};

const mockTokens = {
  access_token: 'access-token-123',
  refresh_token: 'refresh-token-123',
  expires_at: new Date(Date.now() + 3600000).toISOString(),
};

const mockOrganization = {
  id: 'org-123',
  name: 'Test Org',
  slug: 'test-org',
  tier: 'pro',
  owner_id: 'user-123',
};

const mockUserOrganization = {
  user_id: 'user-123',
  org_id: 'org-123',
  organization: mockOrganization,
  role: 'owner' as const,
  is_default: true,
  joined_at: '2026-01-01T00:00:00Z',
};

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <AuthProvider>{children}</AuthProvider>
);

// Test consumer component (prefixed with _ as currently unused, kept for reference)
function _TestConsumer() {
  const auth = useAuth();
  return (
    <div>
      <span data-testid="is-authenticated">{auth.isAuthenticated.toString()}</span>
      <span data-testid="is-loading">{auth.isLoading.toString()}</span>
      <span data-testid="user-email">{auth.user?.email || 'none'}</span>
      <span data-testid="org-name">{auth.organization?.name || 'none'}</span>
    </div>
  );
}

describe('AuthContext - Additional Tests', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorageMock.clear();
    (global.fetch as jest.Mock).mockReset();
  });

  describe('setTokens (OAuth flow)', () => {
    it('successfully sets tokens and fetches user profile', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({
          user: mockUser,
          organization: mockOrganization,
          organizations: [mockUserOrganization],
        }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      await act(async () => {
        await result.current.setTokens('new-access-token', 'new-refresh-token');
      });

      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.user?.email).toBe('test@example.com');
    });

    it('clears tokens on 401 response', async () => {
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: false,
        status: 401,
        headers: new Headers({ 'content-type': 'application/json' }),
        json: async () => ({ error: 'Invalid token' }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      await act(async () => {
        await expect(result.current.setTokens('invalid-token', 'refresh-token')).rejects.toThrow(
          'Authentication failed: Invalid tokens',
        );
      });

      expect(localStorageMock.removeItem).toHaveBeenCalledWith('aragora_tokens');
    });

    it('retries on network failure', async () => {
      // First two calls fail, third succeeds
      (global.fetch as jest.Mock)
        .mockRejectedValueOnce(new Error('Network error'))
        .mockRejectedValueOnce(new Error('Network error'))
        .mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({
            user: mockUser,
            organization: mockOrganization,
            organizations: [mockUserOrganization], // Include orgs to prevent auto-refresh
          }),
        });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      await act(async () => {
        await result.current.setTokens('access-token', 'refresh-token');
      });

      expect(result.current.isAuthenticated).toBe(true);
      // 3 retries for the /me call
      expect(global.fetch).toHaveBeenCalledTimes(3);
    });

    it('retries when /me request aborts and eventually succeeds', async () => {
      const abortError = new DOMException('The operation was aborted.', 'AbortError');

      (global.fetch as jest.Mock)
        .mockRejectedValueOnce(abortError)
        .mockRejectedValueOnce(abortError)
        .mockResolvedValueOnce({
          ok: true,
          headers: new Headers({ 'content-type': 'application/json' }),
          json: async () => ({
            user: mockUser,
            organization: mockOrganization,
            organizations: [mockUserOrganization],
          }),
        });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      await act(async () => {
        await result.current.setTokens('access-token', 'refresh-token');
      });

      expect(result.current.isAuthenticated).toBe(true);
      expect(global.fetch).toHaveBeenCalledTimes(3);
    });
  });

  describe('Organization Switching', () => {
    it('successfully switches organization', async () => {
      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);
      mockLocalStorage['aragora_user_orgs'] = JSON.stringify([mockUserOrganization]);

      const newOrg = {
        id: 'org-456',
        name: 'New Org',
        slug: 'new-org',
        tier: 'enterprise',
        owner_id: 'user-123',
      };

      // Mock /api/auth/me for mount validation
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          user: mockUser,
          organization: mockOrganization,
          organizations: [mockUserOrganization],
        }),
      });
      // Mock the switch API call
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ organization: newOrg }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      let switchResult: { success: boolean; error?: string };
      await act(async () => {
        switchResult = await result.current.switchOrganization('org-456');
      });

      expect(switchResult!.success).toBe(true);
      expect(result.current.organization?.name).toBe('New Org');
    });

    it('returns error when not authenticated', async () => {
      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      let switchResult: { success: boolean; error?: string };
      await act(async () => {
        switchResult = await result.current.switchOrganization('org-456');
      });

      expect(switchResult!.success).toBe(false);
      expect(switchResult!.error).toBe('Not authenticated');
    });

    it('handles network error during switch', async () => {
      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

      // Mock /api/auth/me validation on mount to succeed
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          user: mockUser,
          organization: mockOrganization,
          organizations: [mockUserOrganization],
        }),
      });
      // Then mock the switch call to fail with network error
      (global.fetch as jest.Mock).mockRejectedValueOnce(new Error('Network error'));

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      let switchResult: { success: boolean; error?: string };
      await act(async () => {
        switchResult = await result.current.switchOrganization('org-456');
      });

      expect(switchResult!.success).toBe(false);
      expect(switchResult!.error).toBe('Network error. Please try again.');
    });
  });

  describe('getCurrentOrgRole', () => {
    it('returns the correct role for current organization', async () => {
      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);
      mockLocalStorage['aragora_active_org'] = JSON.stringify(mockOrganization);
      mockLocalStorage['aragora_user_orgs'] = JSON.stringify([mockUserOrganization]);

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      expect(result.current.getCurrentOrgRole()).toBe('owner');
    });

    it('returns null when no organization is active', async () => {
      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      expect(result.current.getCurrentOrgRole()).toBeNull();
    });
  });

  describe('useAuth hook', () => {
    it('throws error when used outside AuthProvider', () => {
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation();

      expect(() => {
        renderHook(() => useAuth());
      }).toThrow('useAuth must be used within an AuthProvider');

      consoleSpy.mockRestore();
    });
  });

  describe('useRequireAuth hook', () => {
    it('returns auth context when authenticated', async () => {
      // Test that it returns the auth context properly when authenticated
      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

      const { result } = renderHook(() => useRequireAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      // Should have user data
      expect(result.current.user?.email).toBe('test@example.com');
    });

    it('returns unauthenticated state when no stored auth', async () => {
      const { result } = renderHook(() => useRequireAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      expect(result.current.isAuthenticated).toBe(false);
    });
  });

  describe('refreshOrganizations', () => {
    it('fetches and updates organizations list', async () => {
      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);
      // Pre-populate with one org so auto-fetch doesn't trigger
      mockLocalStorage['aragora_user_orgs'] = JSON.stringify([mockUserOrganization]);

      const newOrgs = [
        mockUserOrganization,
        {
          ...mockUserOrganization,
          org_id: 'org-456',
          organization: { ...mockOrganization, id: 'org-456', name: 'Second Org' },
          is_default: false,
        },
      ];

      // Mock /api/auth/me validation on mount
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          user: mockUser,
          organization: mockOrganization,
          organizations: [mockUserOrganization],
        }),
      });

      const { result } = renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      // Mock the refresh call
      (global.fetch as jest.Mock).mockResolvedValueOnce({
        ok: true,
        json: async () => ({ organizations: newOrgs }),
      });

      await act(async () => {
        await result.current.refreshOrganizations();
      });

      expect(result.current.organizations).toHaveLength(2);
    });
  });
});
