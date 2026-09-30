'use client';

import { ReactNode, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { normalizeReturnUrl, RETURN_URL_STORAGE_KEY } from '@/utils/returnUrl';

interface ProtectedRouteProps {
  children: ReactNode;
  /** Optional redirect path after login (defaults to current page) */
  redirectTo?: string;
  /** Optional: require specific subscription tier */
  requiredTier?: 'starter' | 'professional' | 'enterprise';
}

/**
 * Wrapper component that protects routes requiring authentication.
 * Redirects to login if not authenticated, shows loading during auth check.
 */
export function ProtectedRoute({ children, redirectTo, requiredTier }: ProtectedRouteProps) {
  const { isAuthenticated, isLoading, organization } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      const returnUrl = normalizeReturnUrl(
        redirectTo || window.location.pathname + window.location.search,
      );
      sessionStorage.setItem(RETURN_URL_STORAGE_KEY, returnUrl);
      router.push(`/auth/login?returnUrl=${encodeURIComponent(returnUrl)}`);
    }
  }, [isLoading, isAuthenticated, router, redirectTo]);

  // Show loading state during auth check
  if (isLoading) {
    return (
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />
        <main className="min-h-screen bg-bg text-text flex items-center justify-center">
          <div className="text-center">
            <div className="font-theme-data text-[var(--accent)] animate-pulse text-lg mb-2">
              AUTHENTICATING...
            </div>
            <div className="font-theme-data text-text-muted text-xs">Verifying credentials</div>
          </div>
        </main>
      </>
    );
  }

  // Not authenticated - will redirect via useEffect
  if (!isAuthenticated) {
    return (
      <>
        <Scanlines opacity={0.02} />
        <CRTVignette />
        <main className="min-h-screen bg-bg text-text flex items-center justify-center">
          <div className="text-center">
            <div className="font-theme-data text-warning text-lg mb-2">AUTHENTICATION REQUIRED</div>
            <div className="font-theme-data text-text-muted text-xs">Redirecting to login...</div>
          </div>
        </main>
      </>
    );
  }

  // Check tier requirement if specified
  if (requiredTier && organization) {
    const tierHierarchy = ['free', 'starter', 'professional', 'enterprise'];
    const userTierIndex = tierHierarchy.indexOf(organization.tier);
    const requiredTierIndex = tierHierarchy.indexOf(requiredTier);

    if (userTierIndex < requiredTierIndex) {
      return (
        <>
          <Scanlines opacity={0.02} />
          <CRTVignette />
          <main className="min-h-screen bg-bg text-text flex items-center justify-center">
            <div className="text-center max-w-md">
              <div className="font-theme-data text-warning text-lg mb-2">UPGRADE REQUIRED</div>
              <div className="font-theme-data text-text-muted text-sm mb-4">
                This feature requires the {requiredTier.toUpperCase()} tier or higher.
              </div>
              <div className="font-theme-data text-text-muted text-xs mb-6">
                Your current tier: {organization.tier.toUpperCase()}
              </div>
              <button
                onClick={() => router.push('/pricing')}
                className="font-theme-data text-sm px-6 py-2 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
              >
                [VIEW PLANS]
              </button>
            </div>
          </main>
        </>
      );
    }
  }

  return <>{children}</>;
}
