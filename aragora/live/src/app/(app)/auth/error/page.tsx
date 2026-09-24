'use client';

import { Suspense, useState, useEffect } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';

/** Map raw backend error strings to user-friendly messages. */
function friendlyMessage(raw: string): { message: string; isTransient: boolean } {
  const decoded = decodeURIComponent(raw);
  const lower = decoded.toLowerCase();

  // Transient database/connection errors - auto-retry is appropriate
  if (
    lower.includes('interfaceerror') ||
    lower.includes('connectiondoesnotexisterror') ||
    lower.includes('database error')
  ) {
    return {
      message:
        'A temporary database connection issue occurred. This usually resolves automatically. Retrying\u2026',
      isTransient: true,
    };
  }
  if (
    lower.includes('timeouterror') ||
    lower.includes('connectionrefusederror') ||
    lower.includes('connection refused')
  ) {
    return {
      message: 'The server is temporarily unreachable. Retrying automatically\u2026',
      isTransient: true,
    };
  }
  if (lower.includes('too many') || lower.includes('rate limit')) {
    return {
      message: 'Too many login attempts. Please wait a moment before trying again.',
      isTransient: true,
    };
  }
  if (lower.includes('pool') && (lower.includes('exhausted') || lower.includes('timeout'))) {
    return {
      message: 'The server is experiencing high load. Please wait a moment while we retry\u2026',
      isTransient: true,
    };
  }

  // Permanent errors - show a clear explanation
  if (lower.includes('invalid or expired state')) {
    return {
      message: 'Your login session expired. Please try signing in again.',
      isTransient: false,
    };
  }
  if (lower.includes('failed to exchange authorization code')) {
    return {
      message: 'The login provider returned an invalid response. Please try again.',
      isTransient: false,
    };
  }
  if (lower.includes('jwt') || lower.includes('secret not configured')) {
    return {
      message: 'Server configuration error. Please contact the administrator.',
      isTransient: false,
    };
  }
  if (lower.includes('user service unavailable')) {
    return {
      message: 'The authentication service is currently unavailable. Please try again shortly.',
      isTransient: true,
    };
  }
  if (lower.includes('email already') || lower.includes('already registered')) {
    return {
      message:
        'This email is already registered. Try signing in with your existing account or use a different provider.',
      isTransient: false,
    };
  }
  if (lower.includes('account linking failed') || lower.includes('failed to link')) {
    return {
      message:
        'Could not link your account to this provider. Please try again or use a different login method.',
      isTransient: false,
    };
  }
  if (lower.includes('network') || lower.includes('fetch failed')) {
    return {
      message: 'A network error occurred. Please check your connection and try again.',
      isTransient: true,
    };
  }

  // Fallback - show the decoded message as-is
  return { message: decoded, isTransient: false };
}

function OAuthErrorContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const rawError = searchParams.get('error') || 'An unknown error occurred';

  const { message, isTransient } = friendlyMessage(rawError);
  const [countdown, setCountdown] = useState(isTransient ? 3 : 0);

  useEffect(() => {
    if (!isTransient || countdown <= 0) return;

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          // Retry by navigating back to login
          router.push('/auth/login');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [isTransient, countdown, router]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10 flex flex-col items-center justify-center">
        <div className="w-full max-w-md p-8">
          <div className="border border-warning/30 bg-surface/50 p-8 text-center">
            {/* Error Icon */}
            <div className="mb-6">
              <div className="text-4xl text-warning">&#x26A0;</div>
            </div>

            {/* Title */}
            <h1 className="text-xl font-theme-data text-warning mb-4">
              {isTransient ? 'CONNECTION ISSUE' : 'AUTHENTICATION ERROR'}
            </h1>

            {/* User-friendly Error Message */}
            <div className="mb-6 p-4 border border-warning/30 bg-warning/5">
              <p className="text-text-muted text-sm font-theme-data break-words">{message}</p>
            </div>

            {/* Auto-retry countdown for transient errors */}
            {isTransient && countdown > 0 && (
              <p className="text-[var(--acid-cyan)] text-xs font-theme-data mb-4 animate-pulse">
                Retrying in {countdown}s...
              </p>
            )}

            {/* Actions */}
            <div className="space-y-3">
              <Link
                href="/auth/login"
                className="block w-full py-3 bg-[var(--accent)] text-bg font-theme-data font-bold hover:bg-[var(--accent)]/80 transition-colors text-center"
              >
                TRY AGAIN
              </Link>
              <Link
                href="/"
                className="block w-full py-3 border border-[var(--accent)]/30 text-[var(--acid-cyan)] font-theme-data hover:border-[var(--accent)] transition-colors text-center"
              >
                RETURN HOME
              </Link>
            </div>

            {/* Help Text */}
            {!isTransient && (
              <div className="mt-8 pt-6 border-t border-[var(--accent)]/20">
                <p className="text-xs font-theme-data text-text-muted">
                  If this error persists, please try:
                </p>
                <ul className="text-xs font-theme-data text-text-muted/70 mt-2 space-y-1">
                  <li>- Clearing your browser cookies</li>
                  <li>- Using a different browser</li>
                  <li>- Using a different login method (Google, GitHub, etc.)</li>
                  <li>- Waiting a few minutes and trying again</li>
                </ul>
              </div>
            )}

            {/* Debug Info (collapsible) - helps with support tickets */}
            <details className="mt-6 text-left">
              <summary className="text-xs font-theme-data text-text-muted/50 cursor-pointer hover:text-text-muted">
                Technical details
              </summary>
              <pre className="mt-2 p-2 bg-bg/50 border border-[var(--accent)]/10 text-xs font-theme-data text-text-muted/40 overflow-auto max-h-24 whitespace-pre-wrap break-all">
                {rawError}
              </pre>
            </details>
          </div>
        </div>
      </main>
    </>
  );
}

function LoadingFallback() {
  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />
      <main className="min-h-screen bg-bg text-text relative z-10 flex flex-col items-center justify-center">
        <div className="w-full max-w-md p-8">
          <div className="border border-warning/30 bg-surface/50 p-8 text-center">
            <div className="mb-6">
              <div className="text-4xl text-warning">&#x26A0;</div>
            </div>
            <h1 className="text-xl font-theme-data text-warning mb-4">AUTHENTICATION ERROR</h1>
            <div className="mb-6 p-4 border border-warning/30 bg-warning/5">
              <p className="text-text-muted text-sm font-theme-data">Loading...</p>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

export default function OAuthErrorPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <OAuthErrorContent />
    </Suspense>
  );
}
