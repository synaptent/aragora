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
import { hardNavigate, reloadDocument } from '../src/utils/navigation';

jest.mock('../src/utils/navigation', () => ({
  hardNavigate: jest.fn(),
  reloadDocument: jest.fn(),
}));
const mockHardNavigate = hardNavigate as jest.MockedFunction<typeof hardNavigate>;
const mockReloadDocument = reloadDocument as jest.MockedFunction<typeof reloadDocument>;

function showPage(persisted: boolean) {
  act(() => {
    window.dispatchEvent(new PageTransitionEvent('pageshow', { persisted }));
  });
}

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
    Object.keys(mockLocalStorage).forEach(key => delete mockLocalStorage[key]);
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

const AUTH_KEYS = ['aragora_tokens', 'aragora_user', 'aragora_active_org', 'aragora_user_orgs'];

async function renderLoggedIn() {
  mockFetch.mockResolvedValueOnce({
    ok: true,
    json: () => Promise.resolve({
      user: mockUser,
      tokens: mockTokens,
      organization: mockOrganization,
      organizations: [{ org_id: 'org-123', organization: mockOrganization, role: 'owner' }],
    }),
  });

  const hook = renderHook(() => useAuth(), { wrapper });

  await waitFor(() => {
    expect(hook.result.current.isLoading).toBe(false);
  });

  await act(async () => {
    await hook.result.current.login('test@example.com', 'password123');
  });

  expect(hook.result.current.isAuthenticated).toBe(true);
  AUTH_KEYS.forEach((key) => expect(mockLocalStorage[key]).toBeDefined());
  return hook;
}

const CLEARED_STORAGE = Object.fromEntries(AUTH_KEYS.map((key) => [key, undefined]));

function recordStorageAtNavigation(): { snapshot: Record<string, string | undefined> | null } {
  const seen: { snapshot: Record<string, string | undefined> | null } = { snapshot: null };
  mockHardNavigate.mockImplementationOnce(() => {
    seen.snapshot = Object.fromEntries(AUTH_KEYS.map((key) => [key, mockLocalStorage[key]]));
  });
  return seen;
}

type FetchReply = { ok: boolean; status?: number; json?: () => Promise<unknown> };

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

const meReply: FetchReply = {
  ok: true,
  json: () => Promise.resolve({ user: mockUser, organization: mockOrganization }),
};

/** Answers /api/auth/me with `me` and /api/auth/refresh with `refresh`. */
function routeAuthFetches(refresh: () => Promise<FetchReply>, me: () => Promise<FetchReply> = () => Promise.resolve(meReply)) {
  mockFetch.mockImplementation((url: string) => {
    if (url.includes('/api/auth/refresh')) return refresh();
    if (url.includes('/api/auth/me')) return me();
    return Promise.resolve({ ok: false, status: 404, json: () => Promise.resolve({}) });
  });
}

function refreshCalls() {
  return mockFetch.mock.calls.filter(([url]) => String(url).includes('/api/auth/refresh'));
}

/** Mounts with a stored session and waits until its background validation has finished. */
async function renderRestoredSession(tokens = mockTokens) {
  mockLocalStorage['aragora_tokens'] = JSON.stringify(tokens);
  mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

  const hook = renderHook(() => useAuth(), { wrapper });
  await waitFor(() => {
    expect(hook.result.current.organization).toEqual(mockOrganization);
  });
  expect(hook.result.current.isAuthenticated).toBe(true);
  return hook;
}

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
        json: () => Promise.resolve({
          user: mockUser,
          tokens: mockTokens,
          organization: mockOrganization,
        }),
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
        json: () => Promise.resolve({
          user: mockUser,
          tokens: mockTokens,
          organization: mockOrganization,
        }),
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
          'New Org'
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
        registerResult = await result.current.register(
          'existing@example.com',
          'password123'
        );
      });

      expect(registerResult!.success).toBe(false);
      expect(registerResult!.error).toBe('Email already exists');
    });
  });

  describe('Logout', () => {
    it('clears auth storage and then navigates to /auth/login', async () => {
      const { result } = await renderLoggedIn();
      const seen = recordStorageAtNavigation();

      mockFetch.mockResolvedValueOnce({ ok: true });

      await act(async () => {
        await result.current.logout();
      });

      expect(mockFetch).toHaveBeenLastCalledWith(
        expect.stringContaining('/api/auth/logout'),
        expect.objectContaining({
          method: 'POST',
          headers: { Authorization: 'Bearer access-token-123' },
        }),
      );
      expect(mockHardNavigate).toHaveBeenCalledTimes(1);
      expect(mockHardNavigate).toHaveBeenCalledWith('/auth/login');
      expect(seen.snapshot).toEqual(CLEARED_STORAGE);
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
      expect(result.current.tokens).toBeNull();
      expect(result.current.organization).toBeNull();
      expect(result.current.organizations).toEqual([]);
    });

    it('still clears auth and navigates to /auth/login when the logout request fails', async () => {
      const { result } = await renderLoggedIn();
      const seen = recordStorageAtNavigation();

      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      await act(async () => {
        await result.current.logout();
      });

      expect(mockHardNavigate).toHaveBeenCalledTimes(1);
      expect(mockHardNavigate).toHaveBeenCalledWith('/auth/login');
      expect(seen.snapshot).toEqual(CLEARED_STORAGE);
      expect(result.current.isAuthenticated).toBe(false);
    });

    it('still clears auth and navigates to /auth/login within 5 s when the logout request hangs', async () => {
      const { result } = await renderLoggedIn();
      const seen = recordStorageAtNavigation();

      let logoutSignal: AbortSignal | null | undefined;
      // Never settles, even when aborted, so only the client-side bound can end the wait.
      mockFetch.mockImplementationOnce((_url: string, init?: RequestInit) => {
        logoutSignal = init?.signal;
        return new Promise(() => {});
      });

      jest.useFakeTimers();
      try {
        act(() => {
          void result.current.logout();
        });
        await act(async () => {
          jest.advanceTimersByTime(4_999);
        });
        expect(mockHardNavigate).not.toHaveBeenCalled();
        expect(mockLocalStorage['aragora_tokens']).toBeDefined();

        await act(async () => {
          jest.advanceTimersByTime(1);
        });
      } finally {
        jest.useRealTimers();
      }

      expect(logoutSignal?.aborted).toBe(true);
      expect(mockHardNavigate).toHaveBeenCalledTimes(1);
      expect(mockHardNavigate).toHaveBeenCalledWith('/auth/login');
      expect(seen.snapshot).toEqual(CLEARED_STORAGE);
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.tokens).toBeNull();
    });

    it('does not navigate on login or session restore', async () => {
      await renderLoggedIn();

      expect(mockHardNavigate).not.toHaveBeenCalled();
    });
  });

  describe('Back/forward cache restore', () => {
    it('reloads a page restored after this page logged out', async () => {
      const { result } = await renderLoggedIn();
      mockFetch.mockResolvedValueOnce({ ok: true });
      await act(async () => {
        await result.current.logout();
      });
      expect(mockReloadDocument).not.toHaveBeenCalled();

      showPage(true);

      expect(mockReloadDocument).toHaveBeenCalledTimes(1);
    });

    it('reloads a restored page when another session has signed in since', async () => {
      await renderLoggedIn();
      mockLocalStorage['aragora_tokens'] = JSON.stringify({ ...mockTokens, access_token: 'access-token-other' });

      showPage(true);

      expect(mockReloadDocument).toHaveBeenCalledTimes(1);
    });

    it('reloads a restored page when its session was signed out elsewhere', async () => {
      await renderLoggedIn();
      delete mockLocalStorage['aragora_tokens'];

      showPage(true);

      expect(mockReloadDocument).toHaveBeenCalledTimes(1);
    });

    it('keeps a restored page whose session is still current', async () => {
      await renderLoggedIn();

      showPage(true);

      expect(mockReloadDocument).not.toHaveBeenCalled();
    });

    it('ignores ordinary page shows', async () => {
      const { result } = await renderLoggedIn();
      mockFetch.mockResolvedValueOnce({ ok: true });
      await act(async () => {
        await result.current.logout();
      });

      showPage(false);

      expect(mockReloadDocument).not.toHaveBeenCalled();
    });

    it('keeps a restored page that never had a session', async () => {
      const { result } = renderHook(() => useAuth(), { wrapper });
      await waitFor(() => {
        expect(result.current.isLoading).toBe(false);
      });

      showPage(true);

      expect(mockReloadDocument).not.toHaveBeenCalled();
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
        json: () => Promise.resolve({
          user: mockUser,
          organization: mockOrganization,
        }),
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
        json: () => Promise.resolve({
          user: mockUser,
          organization: mockOrganization,
        }),
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

    it.each([401, 403])('clears auth storage and then navigates to /auth/login when the refresh is rejected with %i', async (status) => {
      routeAuthFetches(() => Promise.resolve({ ok: false, status, json: () => Promise.resolve({ error: 'rejected' }) }));
      const { result } = await renderRestoredSession();
      const seen = recordStorageAtNavigation();

      let refreshSuccess: boolean | undefined;
      await act(async () => {
        refreshSuccess = await result.current.refreshToken();
      });

      expect(refreshSuccess).toBe(false);
      expect(mockHardNavigate).toHaveBeenCalledTimes(1);
      expect(mockHardNavigate).toHaveBeenCalledWith('/auth/login');
      expect(seen.snapshot).toEqual(CLEARED_STORAGE);
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
    });

    it('navigates to /auth/login when the automatic refresh before expiry is rejected', async () => {
      const seen = recordStorageAtNavigation();
      routeAuthFetches(() => Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({ error: 'rejected' }) }));
      mockLocalStorage['aragora_tokens'] = JSON.stringify({
        ...mockTokens,
        expires_at: new Date(Date.now() + 30_000).toISOString(),
      });
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

      renderHook(() => useAuth(), { wrapper });

      await waitFor(() => {
        expect(mockHardNavigate).toHaveBeenCalledWith('/auth/login');
      });
      expect(refreshCalls()).toHaveLength(1);
      expect(seen.snapshot).toEqual(CLEARED_STORAGE);
    });

    it.each([
      ['a network error', () => Promise.reject(new TypeError('Failed to fetch'))],
      ['a 500 response', () => Promise.resolve({ ok: false, status: 500, json: () => Promise.resolve({}) })],
      ['a 503 response', () => Promise.resolve({ ok: false, status: 503, json: () => Promise.resolve({}) })],
      ['a 429 response', () => Promise.resolve({ ok: false, status: 429, json: () => Promise.resolve({}) })],
    ])('keeps the session and does not navigate after %s', async (_label, refresh: () => Promise<FetchReply>) => {
      routeAuthFetches(refresh);
      const { result } = await renderRestoredSession();

      let refreshSuccess: boolean | undefined;
      await act(async () => {
        refreshSuccess = await result.current.refreshToken();
      });

      expect(refreshSuccess).toBe(false);
      expect(mockHardNavigate).not.toHaveBeenCalled();
      expect(mockLocalStorage['aragora_tokens']).toBe(JSON.stringify(mockTokens));
      expect(mockLocalStorage['aragora_user']).toBeDefined();
      expect(result.current.isAuthenticated).toBe(true);
      expect(result.current.tokens?.access_token).toBe('access-token-123');
    });

    it('sends one refresh request for concurrent callers, since refresh tokens are single-use', async () => {
      const newTokens = {
        access_token: 'new-access-token',
        refresh_token: 'new-refresh-token',
        expires_at: new Date(Date.now() + 3600000).toISOString(),
      };
      const reply = deferred<FetchReply>();
      routeAuthFetches(() => reply.promise);
      const { result } = await renderRestoredSession();

      let results: boolean[] = [];
      await act(async () => {
        const pending = Promise.all([result.current.refreshToken(), result.current.refreshToken()]);
        reply.resolve({ ok: true, json: () => Promise.resolve({ tokens: newTokens }) });
        results = await pending;
      });

      expect(refreshCalls()).toHaveLength(1);
      expect(results).toEqual([true, true]);
      expect(result.current.tokens?.access_token).toBe('new-access-token');
      expect(mockHardNavigate).not.toHaveBeenCalled();

      await act(async () => {
        await result.current.refreshToken();
      });
      expect(refreshCalls()).toHaveLength(2);
    });

    it('does not restore a session whose refresh was rejected while its validation was in flight', async () => {
      const me = deferred<FetchReply>();
      routeAuthFetches(
        () => Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({ error: 'rejected' }) }),
        () => me.promise,
      );
      mockLocalStorage['aragora_tokens'] = JSON.stringify(mockTokens);
      mockLocalStorage['aragora_user'] = JSON.stringify(mockUser);

      const { result } = renderHook(() => useAuth(), { wrapper });
      await waitFor(() => {
        expect(result.current.isAuthenticated).toBe(true);
      });

      await act(async () => {
        await result.current.refreshToken();
      });
      expect(mockHardNavigate).toHaveBeenCalledWith('/auth/login');

      await act(async () => {
        me.resolve(meReply);
        await new Promise((resolve) => setTimeout(resolve, 0));
      });

      expect(Object.fromEntries(AUTH_KEYS.map((key) => [key, mockLocalStorage[key]]))).toEqual(CLEARED_STORAGE);
      expect(result.current.isAuthenticated).toBe(false);
      expect(result.current.user).toBeNull();
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
        json: () => Promise.resolve({
          user: mockUser,
          organization: mockOrganization,
        }),
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
