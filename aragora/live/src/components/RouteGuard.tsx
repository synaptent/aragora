'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { API_BASE_URL } from '@/config';

interface RouteGuardProps {
  children: React.ReactNode;
  requireAuth?: boolean;
  fallbackPath?: string;
}

// Routes that don't require authentication
const PUBLIC_ROUTES = new Set([
  '/',
  '/about',
  '/pricing',
  '/docs',
  '/login',
  '/signup',
  '/forgot-password',
  '/reset-password',
  '/verify-email',
  '/terms',
  '/privacy',
]);

// Routes that require authentication
const PROTECTED_ROUTES_PREFIX = [
  '/debate',
  '/debates',
  '/gauntlet',
  '/batch',
  '/analytics',
  '/settings',
  '/training',
  '/evolution',
  '/workflows',
  '/webhooks',
  '/api-explorer',
];

interface AuthState {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: { id: string; email: string; name?: string } | null;
}

export function RouteGuard({
  children,
  requireAuth = false,
  fallbackPath = '/login',
}: RouteGuardProps) {
  const router = useRouter();
  const pathname = usePathname();
  const [authState, setAuthState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    user: null,
  });

  useEffect(() => {
    checkAuth();
  }, [pathname]);

  const checkAuth = async () => {
    try {
      // Check for auth tokens in localStorage (JSON object with access_token)
      const stored = localStorage.getItem('aragora_tokens');

      if (!stored) {
        setAuthState({ isAuthenticated: false, isLoading: false, user: null });
        return;
      }

      let token: string;
      try {
        const parsed = JSON.parse(stored);
        token = parsed.access_token;
      } catch {
        setAuthState({ isAuthenticated: false, isLoading: false, user: null });
        return;
      }

      if (!token) {
        setAuthState({ isAuthenticated: false, isLoading: false, user: null });
        return;
      }

      // Verify token with API
      const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (response.ok) {
        const data = await response.json();
        setAuthState({ isAuthenticated: true, isLoading: false, user: data.user });
      } else {
        // Token invalid, clear it
        localStorage.removeItem('aragora_tokens');
        setAuthState({ isAuthenticated: false, isLoading: false, user: null });
      }
    } catch {
      // Network error, assume not authenticated
      setAuthState({ isAuthenticated: false, isLoading: false, user: null });
    }
  };

  // Determine if current route requires auth
  const routeRequiresAuth = () => {
    if (requireAuth) return true;

    // Check if route is public
    if (PUBLIC_ROUTES.has(pathname)) return false;

    // Check if route matches protected prefix
    for (const prefix of PROTECTED_ROUTES_PREFIX) {
      if (pathname.startsWith(prefix)) return true;
    }

    // Default: don't require auth for unknown routes
    return false;
  };

  // Show loading state
  if (authState.isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <svg
            className="animate-spin h-8 w-8 text-accent"
            xmlns="http://www.w3.org/2000/svg"
            fill="none"
            viewBox="0 0 24 24"
          >
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
            />
          </svg>
          <p className="text-text-muted">Loading...</p>
        </div>
      </div>
    );
  }

  // Check authentication requirement
  if (routeRequiresAuth() && !authState.isAuthenticated) {
    // Redirect to login with return URL
    const returnUrl = encodeURIComponent(pathname);
    router.replace(`${fallbackPath}?returnUrl=${returnUrl}`);

    // Show redirect message while navigating
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="panel p-8 max-w-md text-center">
          <h2 className="text-xl font-semibold text-text mb-2">Authentication Required</h2>
          <p className="text-text-muted mb-4">Please sign in to access this page.</p>
          <button
            onClick={() => router.push(fallbackPath)}
            className="px-4 py-2 bg-accent hover:bg-accent/80 text-white font-medium rounded-lg transition-colors"
          >
            Sign In
          </button>
        </div>
      </div>
    );
  }

  // Render children if authenticated or route is public
  return <>{children}</>;
}

// Hook to get current auth state
export function useAuth(): AuthState & { logout: () => void; refresh: () => Promise<void> } {
  const router = useRouter();
  const [authState, setAuthState] = useState<AuthState>({
    isAuthenticated: false,
    isLoading: true,
    user: null,
  });

  useEffect(() => {
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const stored = localStorage.getItem('aragora_tokens');

      if (!stored) {
        setAuthState({ isAuthenticated: false, isLoading: false, user: null });
        return;
      }

      let token: string;
      try {
        const parsed = JSON.parse(stored);
        token = parsed.access_token;
      } catch {
        setAuthState({ isAuthenticated: false, isLoading: false, user: null });
        return;
      }

      if (!token) {
        setAuthState({ isAuthenticated: false, isLoading: false, user: null });
        return;
      }

      const response = await fetch(`${API_BASE_URL}/api/auth/me`, {
        headers: { Authorization: `Bearer ${token}` },
      });

      if (response.ok) {
        const data = await response.json();
        setAuthState({ isAuthenticated: true, isLoading: false, user: data.user });
      } else {
        localStorage.removeItem('aragora_tokens');
        setAuthState({ isAuthenticated: false, isLoading: false, user: null });
      }
    } catch {
      setAuthState({ isAuthenticated: false, isLoading: false, user: null });
    }
  };

  const logout = () => {
    localStorage.removeItem('aragora_tokens');
    localStorage.removeItem('aragora_user');
    setAuthState({ isAuthenticated: false, isLoading: false, user: null });
    router.push('/');
  };

  const refresh = async () => {
    setAuthState((prev) => ({ ...prev, isLoading: true }));
    await checkAuth();
  };

  return { ...authState, logout, refresh };
}

// Route configuration export
export const routeConfig = {
  publicRoutes: PUBLIC_ROUTES,
  protectedPrefixes: PROTECTED_ROUTES_PREFIX,
};
