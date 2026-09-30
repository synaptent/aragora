'use client';

import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
  useMemo,
  ReactNode,
} from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';
import { normalizeReturnUrl, RETURN_URL_STORAGE_KEY } from '@/utils/returnUrl';

interface User {
  id: string;
  email: string;
  name: string;
  role: string;
  org_id: string | null;
  is_active: boolean;
  created_at: string;
}

interface Tokens {
  access_token: string;
  refresh_token: string;
  expires_at: string;
}

interface Organization {
  id: string;
  name: string;
  slug: string;
  tier: string;
  owner_id: string;
}

/**
 * Represents a user's membership in an organization (multi-org support).
 */
interface UserOrganization {
  user_id: string;
  org_id: string;
  organization: Organization;
  role: 'member' | 'admin' | 'owner';
  is_default: boolean;
  joined_at: string;
}

interface AuthState {
  user: User | null;
  /** Currently active organization */
  organization: Organization | null;
  /** All organizations the user belongs to (multi-org support) */
  organizations: UserOrganization[];
  tokens: Tokens | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  /** Whether organizations are being loaded */
  isLoadingOrganizations: boolean;
}

interface AuthContextType extends AuthState {
  login: (email: string, password: string) => Promise<{ success: boolean; error?: string }>;
  register: (
    email: string,
    password: string,
    name?: string,
    organization?: string,
  ) => Promise<{ success: boolean; error?: string }>;
  logout: () => Promise<void>;
  refreshToken: () => Promise<boolean>;
  setTokens: (
    accessToken: string,
    refreshToken: string,
    signal?: AbortSignal,
    expiresIn?: number,
  ) => Promise<void>;
  /** Switch to a different organization context */
  switchOrganization: (
    orgId: string,
    setAsDefault?: boolean,
  ) => Promise<{ success: boolean; error?: string }>;
  /** Refresh the list of user's organizations */
  refreshOrganizations: () => Promise<void>;
  /** Get the user's role in the current organization */
  getCurrentOrgRole: () => 'member' | 'admin' | 'owner' | null;
}

// Exported for test-utils to provide mock values via AuthContext.Provider
// without triggering AuthProvider's side effects (fetch, localStorage).
export const AuthContext = createContext<AuthContextType | undefined>(undefined);

const API_BASE = API_BASE_URL;

// Storage keys
const TOKENS_KEY = 'aragora_tokens';
const USER_KEY = 'aragora_user';
const ACTIVE_ORG_KEY = 'aragora_active_org';
const USER_ORGS_KEY = 'aragora_user_orgs';

function getStoredTokens(): Tokens | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(TOKENS_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

function getStoredUser(): User | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(USER_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

function storeAuth(user: User, tokens: Tokens): void {
  localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));
  localStorage.setItem(USER_KEY, JSON.stringify(user));
}

function storeActiveOrg(org: Organization | null): void {
  if (org) {
    localStorage.setItem(ACTIVE_ORG_KEY, JSON.stringify(org));
  } else {
    localStorage.removeItem(ACTIVE_ORG_KEY);
  }
}

function getStoredActiveOrg(): Organization | null {
  if (typeof window === 'undefined') return null;
  const stored = localStorage.getItem(ACTIVE_ORG_KEY);
  if (!stored) return null;
  try {
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

function storeUserOrgs(orgs: UserOrganization[]): void {
  localStorage.setItem(USER_ORGS_KEY, JSON.stringify(orgs));
}

function getStoredUserOrgs(): UserOrganization[] {
  if (typeof window === 'undefined') return [];
  const stored = localStorage.getItem(USER_ORGS_KEY);
  if (!stored) return [];
  try {
    return JSON.parse(stored);
  } catch {
    return [];
  }
}

function clearAuth(): void {
  localStorage.removeItem(TOKENS_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem(ACTIVE_ORG_KEY);
  localStorage.removeItem(USER_ORGS_KEY);
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({
    user: null,
    organization: null,
    organizations: [],
    tokens: null,
    isLoading: true,
    isAuthenticated: false,
    isLoadingOrganizations: false,
  });

  // Track whether we've already attempted to fetch organizations this session
  // to prevent infinite refetch loops when the endpoint returns 403/empty
  const orgsFetchAttemptedRef = useRef(false);

  // Fetch user's organizations
  const fetchOrganizations = useCallback(
    async (accessToken: string): Promise<UserOrganization[]> => {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10_000);

      try {
        const response = await fetch(`${API_BASE}/api/v1/user/organizations`, {
          headers: { Authorization: `Bearer ${accessToken}` },
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (response.ok) {
          const data = await response.json();
          return data.organizations || [];
        }
        return [];
      } catch {
        clearTimeout(timeoutId);
        return [];
      }
    },
    [],
  );

  // Refresh organizations list
  // NOTE: Uses getStoredTokens() instead of state.tokens to avoid
  // dependency on the tokens object reference (which changes on every state update)
  const refreshOrganizations = useCallback(async () => {
    const tokens = getStoredTokens();
    if (!tokens?.access_token) return;

    setState((prev) => ({ ...prev, isLoadingOrganizations: true }));

    try {
      const orgs = await fetchOrganizations(tokens.access_token);
      storeUserOrgs(orgs);
      orgsFetchAttemptedRef.current = true;
      setState((prev) => ({ ...prev, organizations: orgs, isLoadingOrganizations: false }));
    } catch {
      orgsFetchAttemptedRef.current = true;
      setState((prev) => ({ ...prev, isLoadingOrganizations: false }));
    }
  }, [fetchOrganizations]);

  // Switch organization context
  const switchOrganization = useCallback(
    async (orgId: string, setAsDefault = false): Promise<{ success: boolean; error?: string }> => {
      const tokens = getStoredTokens();
      if (!tokens?.access_token) {
        return { success: false, error: 'Not authenticated' };
      }

      try {
        const response = await fetch(`${API_BASE}/api/v1/user/organizations/switch`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens.access_token}`,
          },
          body: JSON.stringify({ org_id: orgId, set_as_default: setAsDefault }),
        });

        const data = await response.json();

        if (!response.ok) {
          return { success: false, error: data.error || 'Failed to switch organization' };
        }

        const newOrg = data.organization;
        storeActiveOrg(newOrg);

        // Update organizations list if default was changed
        setState((prev) => {
          if (setAsDefault && prev.organizations.length > 0) {
            const updatedOrgs = prev.organizations.map((o) => ({
              ...o,
              is_default: o.org_id === orgId,
            }));
            storeUserOrgs(updatedOrgs);
            return { ...prev, organization: newOrg, organizations: updatedOrgs };
          }
          return { ...prev, organization: newOrg };
        });

        // If a new token was issued with org context, update it
        if (data.access_token) {
          const newTokens = { ...tokens, access_token: data.access_token };
          localStorage.setItem(TOKENS_KEY, JSON.stringify(newTokens));
          setState((prev) => ({ ...prev, tokens: newTokens }));
        }

        return { success: true };
      } catch {
        return { success: false, error: 'Network error. Please try again.' };
      }
    },
    [],
  );

  // Get current org role
  const getCurrentOrgRole = useCallback((): 'member' | 'admin' | 'owner' | null => {
    if (!state.organization) return null;
    const membership = state.organizations.find((o) => o.org_id === state.organization?.id);
    return membership?.role || null;
  }, [state.organization, state.organizations]);

  // Check for stored auth on mount and validate tokens
  useEffect(() => {
    let active = true;

    const validateStoredSession = async () => {
      const tokens = getStoredTokens();
      const user = getStoredUser();
      const activeOrg = getStoredActiveOrg();
      const userOrgs = getStoredUserOrgs();

      if (!tokens || !user) {
        if (active) {
          setState((prev) => ({ ...prev, isLoading: false }));
        }
        return;
      }

      const expiresAt = new Date(tokens.expires_at);
      if (expiresAt <= new Date()) {
        clearAuth();
        if (active) {
          setState({
            user: null,
            organization: null,
            organizations: [],
            tokens: null,
            isLoading: false,
            isAuthenticated: false,
            isLoadingOrganizations: false,
          });
          window.dispatchEvent(
            new CustomEvent('auth:session-expired', { detail: { reason: 'token_expired' } }),
          );
        }
        return;
      }

      // Optimistic: show dashboard immediately with cached data.
      // Backend validation happens in the background below.
      if (active) {
        setState({
          user,
          organization: activeOrg,
          organizations: userOrgs,
          tokens,
          isLoading: false,
          isAuthenticated: true,
          isLoadingOrganizations: false,
        });
      }

      // Background validation — silently updates user data or clears auth
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 10_000);

      try {
        const response = await fetch(`${API_BASE}/api/auth/me`, {
          headers: { Authorization: `Bearer ${tokens.access_token}` },
          signal: controller.signal,
        });

        clearTimeout(timeoutId);

        if (!response.ok) {
          throw new Error(`Auth validation failed: ${response.status}`);
        }

        const data = await response.json();
        const validatedUser = data.user || user;
        const validatedOrg = data.organization ?? activeOrg;
        const validatedOrgs = data.organizations || userOrgs;

        storeAuth(validatedUser, tokens);
        storeActiveOrg(validatedOrg);
        storeUserOrgs(validatedOrgs);

        if (active) {
          setState({
            user: validatedUser,
            organization: validatedOrg,
            organizations: validatedOrgs,
            tokens,
            isLoading: false,
            isAuthenticated: true,
            isLoadingOrganizations: false,
          });
        }
      } catch (err) {
        clearTimeout(timeoutId);
        if (err instanceof DOMException && err.name === 'AbortError') {
          logger.warn('[AuthContext] Session validation timed out, keeping cached session');
          // Timeout: backend unreachable — keep optimistic auth, don't lock user out
        } else {
          logger.warn('[AuthContext] Stored session invalid, clearing auth');
          clearAuth();
          window.dispatchEvent(
            new CustomEvent('auth:session-expired', { detail: { reason: 'validation_failed' } }),
          );
          if (active) {
            setState({
              user: null,
              organization: null,
              organizations: [],
              tokens: null,
              isLoading: false,
              isAuthenticated: false,
              isLoadingOrganizations: false,
            });
          }
        }
      }
    };

    validateStoredSession();

    return () => {
      active = false;
    };
  }, []);

  // Fetch organizations when authenticated (once per session)
  // Guard with orgsFetchAttemptedRef to prevent infinite loop when
  // the endpoint returns 403 or empty array (organizations.length stays 0)
  useEffect(() => {
    if (
      !state.isLoading &&
      state.isAuthenticated &&
      state.tokens?.access_token &&
      state.organizations.length === 0 &&
      !orgsFetchAttemptedRef.current
    ) {
      refreshOrganizations();
    }
  }, [
    state.isAuthenticated,
    state.isLoading,
    state.tokens?.access_token,
    state.organizations.length,
    refreshOrganizations,
  ]);

  const login = useCallback(async (email: string, password: string) => {
    try {
      const response = await fetch(`${API_BASE}/api/auth/login`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });

      const data = await response.json();

      if (!response.ok) {
        return { success: false, error: data.error || 'Login failed' };
      }

      const { user, tokens } = data;
      const organization = data.organization || null;
      const organizations = data.organizations || [];

      storeAuth(user, tokens);
      storeActiveOrg(organization);
      storeUserOrgs(organizations);

      setState({
        user,
        organization,
        organizations,
        tokens,
        isLoading: false,
        isAuthenticated: true,
        isLoadingOrganizations: false,
      });

      return { success: true };
    } catch {
      return { success: false, error: 'Network error. Please try again.' };
    }
  }, []);

  const register = useCallback(
    async (email: string, password: string, name?: string, organization?: string) => {
      try {
        const response = await fetch(`${API_BASE}/api/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password, name, organization }),
        });

        const data = await response.json();

        if (!response.ok) {
          return { success: false, error: data.error || 'Registration failed' };
        }

        const { user, tokens } = data;
        const org = data.organization || null;
        const orgs = data.organizations || [];

        storeAuth(user, tokens);
        storeActiveOrg(org);
        storeUserOrgs(orgs);

        setState({
          user,
          organization: org,
          organizations: orgs,
          tokens,
          isLoading: false,
          isAuthenticated: true,
          isLoadingOrganizations: false,
        });

        return { success: true };
      } catch {
        return { success: false, error: 'Network error. Please try again.' };
      }
    },
    [],
  );

  const logout = useCallback(async () => {
    try {
      if (state.tokens?.access_token) {
        await fetch(`${API_BASE}/api/auth/logout`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${state.tokens.access_token}` },
        });
      }
    } catch {
      // Ignore logout errors
    }

    clearAuth();
    orgsFetchAttemptedRef.current = false;
    setState({
      user: null,
      organization: null,
      organizations: [],
      tokens: null,
      isLoading: false,
      isAuthenticated: false,
      isLoadingOrganizations: false,
    });
  }, [state.tokens?.access_token]);

  const refreshToken = useCallback(async () => {
    const tokens = getStoredTokens();
    if (!tokens?.refresh_token) return false;

    try {
      const response = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: tokens.refresh_token }),
      });

      if (!response.ok) {
        // Only clear auth on definitive rejection (401/403), not transient errors
        if (response.status === 401 || response.status === 403) {
          clearAuth();
          setState({
            user: null,
            organization: null,
            organizations: [],
            tokens: null,
            isLoading: false,
            isAuthenticated: false,
            isLoadingOrganizations: false,
          });
          window.dispatchEvent(
            new CustomEvent('auth:session-expired', { detail: { reason: 'refresh_rejected' } }),
          );
        } else {
          logger.warn(
            `[AuthContext] Token refresh failed with ${response.status}, keeping session`,
          );
        }
        return false;
      }

      const data = await response.json();
      const newTokens = data.tokens;

      setState((prev) => {
        const user = prev.user || getStoredUser();
        if (user) {
          storeAuth(user, newTokens);
        }
        return { ...prev, tokens: newTokens };
      });

      return true;
    } catch {
      // Network error — don't clear auth, keep session alive
      logger.warn('[AuthContext] Token refresh network error, keeping session');
      return false;
    }
  }, []);

  // Set tokens from OAuth callback - fetches user profile from API
  const setTokens = useCallback(
    async (
      accessToken: string,
      refreshTokenValue: string,
      signal?: AbortSignal,
      expiresIn?: number,
    ) => {
      logger.debug('[AuthContext] setTokens called');

      // Use server-provided expiry if available, default 1 hour
      const expiresAt = new Date(Date.now() + (expiresIn || 3600) * 1000).toISOString();

      const tokens: Tokens = {
        access_token: accessToken,
        refresh_token: refreshTokenValue,
        expires_at: expiresAt,
      };

      // IMPORTANT: Store tokens IMMEDIATELY (optimistically) before validation
      // This ensures tokens survive page navigation even if validation is slow
      logger.debug('[AuthContext] Storing tokens optimistically...');
      localStorage.setItem(TOKENS_KEY, JSON.stringify(tokens));

      // Fetch user profile using the access token to validate and get user info
      try {
        logger.debug('[AuthContext] Fetching user profile to validate tokens...');
        const PROFILE_FETCH_TIMEOUT_MS = 12_000;

        // Retry logic for network and transient server errors
        let response: Response | null = null;
        let lastError: Error | null = null;

        for (let attempt = 1; attempt <= 3; attempt++) {
          if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
          const attemptController = new AbortController();
          const timeoutId = setTimeout(() => attemptController.abort(), PROFILE_FETCH_TIMEOUT_MS);
          const onOuterAbort = () => attemptController.abort();
          signal?.addEventListener('abort', onOuterAbort);

          try {
            response = await fetch(`${API_BASE}/api/auth/me`, {
              headers: { Authorization: `Bearer ${accessToken}` },
              signal: attemptController.signal,
            });

            clearTimeout(timeoutId);
            signal?.removeEventListener('abort', onOuterAbort);

            // Retry on 500/502/503/504 (transient server errors)
            if (response.status >= 500 && attempt < 3) {
              logger.warn(
                `[AuthContext] /me returned ${response.status}, retrying (attempt ${attempt}/3)...`,
              );
              await new Promise((r) => setTimeout(r, 1000 * attempt));
              continue;
            }
            break; // Success or non-retryable status, exit loop
          } catch (fetchErr) {
            clearTimeout(timeoutId);
            signal?.removeEventListener('abort', onOuterAbort);

            // External abort (unmount/navigation) should stop immediately.
            if (
              fetchErr instanceof DOMException &&
              fetchErr.name === 'AbortError' &&
              signal?.aborted
            ) {
              throw fetchErr;
            }

            // Per-attempt timeout should retry like other transient failures.
            if (fetchErr instanceof DOMException && fetchErr.name === 'AbortError') {
              lastError = new Error(
                `Token validation timed out after ${PROFILE_FETCH_TIMEOUT_MS}ms`,
              );
              logger.warn(`[AuthContext] /me fetch attempt ${attempt} timed out`);
              if (attempt < 3) {
                await new Promise((r) => setTimeout(r, 1000 * attempt));
              }
              continue;
            }

            lastError = fetchErr instanceof Error ? fetchErr : new Error(String(fetchErr));
            logger.warn(`[AuthContext] /me fetch attempt ${attempt} failed:`, lastError.message);
            if (attempt < 3) {
              await new Promise((r) => setTimeout(r, 1000 * attempt));
            }
          }
        }

        if (!response) {
          // All retries failed - but tokens are stored, user can retry
          logger.error('[AuthContext] All /me fetch attempts failed:', lastError?.message);
          throw new Error('Network error: Unable to validate tokens. Please try again.');
        }

        logger.debug('[AuthContext] /me response:', {
          status: response.status,
          ok: response.ok,
          contentType: response.headers.get('content-type'),
        });

        if (response.ok) {
          const data = await response.json();
          const user = data.user;
          const organization = data.organization || null;
          const organizations = data.organizations || [];

          logger.debug('[AuthContext] User profile fetched successfully:', user?.email);

          // Store user info alongside already-stored tokens
          localStorage.setItem(USER_KEY, JSON.stringify(user));
          storeActiveOrg(organization);
          storeUserOrgs(organizations);

          // Update state - use a callback to ensure state is properly merged
          setState({
            user,
            organization,
            organizations,
            tokens,
            isLoading: false,
            isAuthenticated: true,
            isLoadingOrganizations: false,
          });

          // Small delay to ensure React state update is processed
          await new Promise((r) => setTimeout(r, 50));
        } else if (response.status === 401) {
          // 401 means tokens are invalid - clear optimistically stored tokens
          logger.error('[AuthContext] Token validation failed: 401 Unauthorized');
          const contentType = response.headers.get('content-type') || '';
          let errorDetail = '';
          if (contentType.includes('application/json')) {
            try {
              const errData = await response.json();
              errorDetail = errData.error || errData.message || '';
            } catch {
              /* ignore */
            }
          }
          logger.error('[AuthContext] Error detail:', errorDetail || '(no detail)');

          // Clear the optimistically stored tokens
          clearAuth();
          throw new Error('Authentication failed: Invalid tokens');
        } else {
          // Other error (500, 404, etc.) - keep tokens but report error
          // User may be able to retry or the backend may recover
          let body = '';
          try {
            body = await response.text();
          } catch {
            /* ignore */
          }
          logger.error('[AuthContext] /me error response:', { status: response.status, body });
          // Don't clear tokens on server errors - let user retry
          throw new Error(
            `Server error (${response.status}): ${body || 'No details'}. Please try again.`,
          );
        }
      } catch (err) {
        // Re-throw abort errors without logging (clean unmount)
        if (err instanceof DOMException && err.name === 'AbortError') throw err;
        logger.error('[AuthContext] setTokens error:', err);
        // Re-throw so callback page can handle it
        throw err;
      }
    },
    [],
  );

  // Auto-refresh token before expiry
  useEffect(() => {
    if (!state.tokens?.expires_at) return;

    const expiresAt = new Date(state.tokens.expires_at);
    const refreshTime = expiresAt.getTime() - Date.now() - 60000; // 1 min before expiry

    if (refreshTime <= 0) {
      refreshToken();
      return;
    }

    const timeout = setTimeout(refreshToken, refreshTime);
    return () => clearTimeout(timeout);
  }, [state.tokens?.expires_at, refreshToken]);

  const contextValue = useMemo<AuthContextType>(
    () => ({
      ...state,
      login,
      register,
      logout,
      refreshToken,
      setTokens,
      switchOrganization,
      refreshOrganizations,
      getCurrentOrgRole,
    }),
    [
      state,
      login,
      register,
      logout,
      refreshToken,
      setTokens,
      switchOrganization,
      refreshOrganizations,
      getCurrentOrgRole,
    ],
  );

  return <AuthContext.Provider value={contextValue}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}

export function useRequireAuth() {
  const auth = useAuth();

  useEffect(() => {
    if (!auth.isLoading && !auth.isAuthenticated) {
      const currentPath = normalizeReturnUrl(window.location.pathname + window.location.search);
      sessionStorage.setItem(RETURN_URL_STORAGE_KEY, currentPath);
      window.location.href = `/auth/login?returnUrl=${encodeURIComponent(currentPath)}`;
    }
  }, [auth.isLoading, auth.isAuthenticated]);

  return auth;
}

// Export types for external use
export type { User, Tokens, Organization, UserOrganization, AuthState, AuthContextType };
