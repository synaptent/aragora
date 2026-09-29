'use client';

import { Suspense, useEffect, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useAuth } from '@/context/AuthContext';
import { logger } from '@/utils/logger';
import { normalizeReturnUrl, RETURN_URL_STORAGE_KEY } from '@/utils/returnUrl';

type Status = 'processing' | 'success' | 'error';
const CALLBACK_PROCESSING_TIMEOUT_MS = 30_000;

function OAuthCallbackContent() {
  const router = useRouter();
  const { setTokens } = useAuth();
  const [status, setStatus] = useState<Status>('processing');
  const [message, setMessage] = useState('Processing authentication...');
  const isMountedRef = useRef(true);
  const redirectTimerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    const controller = new AbortController();
    const processingTimeoutRef: { id?: ReturnType<typeof setTimeout> } = {};
    const clearProcessingTimeout = () => {
      if (processingTimeoutRef.id) {
        clearTimeout(processingTimeoutRef.id);
        processingTimeoutRef.id = undefined;
      }
    };

    processingTimeoutRef.id = setTimeout(() => {
      if (!isMountedRef.current) return;
      logger.error('[OAuth Callback] Processing timed out');
      controller.abort();
      setStatus('error');
      setMessage('Authentication timed out. Please try again.');
    }, CALLBACK_PROCESSING_TIMEOUT_MS);

    const processCallback = async () => {
      // Debug: Log the full URL to help diagnose OAuth callback issues
      logger.debug('[OAuth Callback] Full URL:', window.location.href);
      logger.debug('[OAuth Callback] Hash:', window.location.hash);
      logger.debug('[OAuth Callback] Search:', window.location.search);

      // Parse query params directly from window.location (more reliable in static export)
      const urlParams = new URLSearchParams(window.location.search);

      // Check for account linking success
      const linked = urlParams.get('linked');
      if (linked) {
        if (!isMountedRef.current) return;
        clearProcessingTimeout();
        setStatus('success');
        setMessage(
          `Successfully linked ${linked.charAt(0).toUpperCase() + linked.slice(1)} account`,
        );
        redirectTimerRef.current = setTimeout(() => {
          if (isMountedRef.current) router.replace('/settings');
        }, 1500);
        return;
      }

      // SECURITY: Parse tokens from URL fragment (primary) - fragments are NOT sent to servers
      // Query params are a fallback but should be avoided as they leak via logs, referer headers, etc.
      let tokenString = window.location.hash.substring(1); // Remove leading '#'
      logger.debug('[OAuth Callback] Hash fragment present:', !!tokenString);

      // Fallback to query params (less secure, but some OAuth flows may use them)
      if (!tokenString) {
        tokenString = window.location.search.substring(1);
        logger.debug('[OAuth Callback] Query params fallback present:', !!tokenString);
        if (tokenString) {
          logger.warn(
            '[OAuth Callback] Tokens received via query params - this is less secure than fragments',
          );
        }
      }

      if (!tokenString) {
        if (!isMountedRef.current) return;
        clearProcessingTimeout();
        setStatus('error');
        setMessage('No authentication data received');
        logger.error('[OAuth Callback] No query params or hash fragment with tokens found');
        return;
      }

      const params = new URLSearchParams(tokenString);
      const accessToken = params.get('access_token');
      const refreshToken = params.get('refresh_token');
      const expiresIn = params.get('expires_in');

      if (accessToken && refreshToken) {
        try {
          logger.debug('[OAuth Callback] Processing OAuth token pair');
          // Pass AbortSignal so in-flight retries cancel on unmount
          // Pass server-provided expiry if available
          await setTokens(
            accessToken,
            refreshToken,
            controller.signal,
            expiresIn ? parseInt(expiresIn, 10) : undefined,
          );
          logger.debug('[OAuth Callback] setTokens completed successfully');

          // Bail if unmounted during await
          if (!isMountedRef.current || controller.signal.aborted) return;

          clearProcessingTimeout();
          setStatus('success');
          setMessage('Authentication successful');
          // Clear the hash from URL for security
          window.history.replaceState(null, '', window.location.pathname);

          // Verify tokens are stored before redirect
          const storedTokens = localStorage.getItem('aragora_tokens');
          const storedUser = localStorage.getItem('aragora_user');
          logger.debug(
            '[OAuth Callback] Pre-redirect check - tokens:',
            !!storedTokens,
            'user:',
            !!storedUser,
          );

          // Check for a saved return URL (e.g., user was viewing a debate before login)
          const returnUrl = sessionStorage.getItem(RETURN_URL_STORAGE_KEY);
          if (returnUrl) {
            sessionStorage.removeItem(RETURN_URL_STORAGE_KEY);
          }
          const destination = normalizeReturnUrl(returnUrl);

          // Redirect immediately — setTokens already processed auth state.
          // Minimal delay just to flash "ACCESS GRANTED" for UX feedback.
          logger.debug('[OAuth Callback] Redirecting to:', destination);
          redirectTimerRef.current = setTimeout(() => {
            if (isMountedRef.current) {
              router.replace(destination);
            }
          }, 100);
        } catch (err) {
          // Silently ignore aborts (component unmounted intentionally)
          if (err instanceof DOMException && err.name === 'AbortError') return;

          logger.error('[OAuth Callback] Failed to set tokens:', err);
          if (!isMountedRef.current) return;
          clearProcessingTimeout();
          setStatus('error');
          // Provide more descriptive error messages
          if (err instanceof Error) {
            if (err.message.includes('Invalid tokens')) {
              setMessage('OAuth tokens were rejected by the server. Please try logging in again.');
            } else if (err.message.includes('401')) {
              setMessage('Authentication failed. Please try logging in again.');
            } else if (
              err.message.includes('Network error') ||
              err.message.includes('Server error')
            ) {
              setMessage(err.message + ' Your tokens have been saved.');
            } else {
              setMessage(err.message || 'Failed to complete authentication');
            }
          } else {
            setMessage('Failed to complete authentication');
          }
        }
      } else {
        if (!isMountedRef.current) return;
        clearProcessingTimeout();
        setStatus('error');
        setMessage('Missing authentication tokens');
        logger.error(
          '[OAuth Callback] Tokens missing from URL params. access_token:',
          !!accessToken,
          'refresh_token:',
          !!refreshToken,
        );
      }
    };

    processCallback();

    return () => {
      isMountedRef.current = false;
      controller.abort();
      clearProcessingTimeout();
      if (redirectTimerRef.current) clearTimeout(redirectTimerRef.current);
    };
  }, [router, setTokens]);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10 flex flex-col items-center justify-center">
        <div className="w-full max-w-md p-8">
          <div className="border border-[var(--accent)]/30 bg-surface/50 p-8 text-center">
            {/* Status Icon */}
            <div className="mb-6">
              {status === 'processing' && (
                <div className="inline-block animate-spin text-4xl text-[var(--acid-cyan)]">
                  &#x21BB;
                </div>
              )}
              {status === 'success' && (
                <div className="text-4xl text-[var(--accent)]">&#x2713;</div>
              )}
              {status === 'error' && <div className="text-4xl text-warning">&#x2717;</div>}
            </div>

            {/* Title */}
            <h1 className="text-xl font-theme-data text-[var(--accent)] mb-4">
              {status === 'processing' && 'AUTHENTICATING...'}
              {status === 'success' && 'ACCESS GRANTED'}
              {status === 'error' && 'AUTHENTICATION FAILED'}
            </h1>

            {/* Message */}
            <p className="text-text-muted text-sm font-theme-data mb-6">{message}</p>

            {/* Actions */}
            {status === 'error' && (
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
            )}

            {status === 'success' && (
              <p className="text-[var(--acid-cyan)] text-xs font-theme-data animate-pulse">
                Redirecting...
              </p>
            )}

            {status === 'processing' && (
              <div className="text-[var(--accent)]/50 text-xs font-theme-data">
                <p>{'═'.repeat(25)}</p>
                <p className="mt-2">Please wait...</p>
              </div>
            )}
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
          <div className="border border-[var(--accent)]/30 bg-surface/50 p-8 text-center">
            <div className="mb-6">
              <div className="inline-block animate-spin text-4xl text-[var(--acid-cyan)]">
                &#x21BB;
              </div>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--accent)] mb-4">AUTHENTICATING...</h1>
            <p className="text-text-muted text-sm font-theme-data mb-6">
              Processing authentication...
            </p>
            <div className="text-[var(--accent)]/50 text-xs font-theme-data">
              <p>{'═'.repeat(25)}</p>
              <p className="mt-2">Please wait...</p>
            </div>
          </div>
        </div>
      </main>
    </>
  );
}

export default function OAuthCallbackPage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <OAuthCallbackContent />
    </Suspense>
  );
}
