'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

function GmailOAuthCallbackContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const [status, setStatus] = useState<'processing' | 'success' | 'error'>('processing');
  const [message, setMessage] = useState('Processing Gmail authorization...');

  useEffect(() => {
    const handleCallback = async () => {
      const code = searchParams.get('code');
      const state = searchParams.get('state');
      const error = searchParams.get('error');

      if (error) {
        setStatus('error');
        setMessage(`Authorization failed: ${error}`);
        return;
      }

      if (!code) {
        setStatus('error');
        setMessage('No authorization code received');
        return;
      }

      try {
        // Exchange code for tokens via our API
        const response = await fetch(`${backendConfig.api}/api/email/gmail/oauth/callback`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({
            code,
            state,
            redirect_uri: `${window.location.origin}/inbox/callback`,
          }),
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || 'Failed to complete authorization');
        }

        const data = await response.json();
        setStatus('success');
        setMessage(data.message || 'Gmail connected successfully!');

        // Redirect to inbox after short delay
        setTimeout(() => {
          router.push('/inbox');
        }, 2000);
      } catch (err) {
        setStatus('error');
        setMessage(err instanceof Error ? err.message : 'Authorization failed');
      }
    };

    handleCallback();
  }, [searchParams, backendConfig.api, tokens?.access_token, router]);

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50 p-8 rounded max-w-md w-full mx-4">
      <div className="text-center">
        {status === 'processing' && (
          <>
            <div className="animate-pulse text-6xl mb-4">📧</div>
            <h2 className="text-xl font-theme-data text-[var(--accent)] mb-2">Connecting Gmail</h2>
            <p className="text-text-muted font-theme-data text-sm">{message}</p>
            <div className="mt-6 flex justify-center gap-1">
              <div
                className="w-2 h-2 bg-[var(--accent)] rounded-full animate-bounce"
                style={{ animationDelay: '0ms' }}
              />
              <div
                className="w-2 h-2 bg-[var(--accent)] rounded-full animate-bounce"
                style={{ animationDelay: '150ms' }}
              />
              <div
                className="w-2 h-2 bg-[var(--accent)] rounded-full animate-bounce"
                style={{ animationDelay: '300ms' }}
              />
            </div>
          </>
        )}

        {status === 'success' && (
          <>
            <div className="text-6xl mb-4">✅</div>
            <h2 className="text-xl font-theme-data text-[var(--accent)] mb-2">Connected!</h2>
            <p className="text-text-muted font-theme-data text-sm">{message}</p>
            <p className="text-text-muted font-theme-data text-xs mt-4">Redirecting to inbox...</p>
          </>
        )}

        {status === 'error' && (
          <>
            <div className="text-6xl mb-4">❌</div>
            <h2 className="text-xl font-theme-data text-acid-red mb-2">Connection Failed</h2>
            <p className="text-text-muted font-theme-data text-sm mb-6">{message}</p>
            <button
              onClick={() => router.push('/inbox')}
              className="px-4 py-2 text-sm font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/40 text-[var(--accent)] hover:bg-[var(--accent)]/20"
            >
              Return to Inbox
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function LoadingFallback() {
  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50 p-8 rounded max-w-md w-full mx-4">
      <div className="text-center">
        <div className="animate-pulse text-6xl mb-4">📧</div>
        <h2 className="text-xl font-theme-data text-[var(--accent)] mb-2">Loading...</h2>
        <div className="mt-6 flex justify-center gap-1">
          <div
            className="w-2 h-2 bg-[var(--accent)] rounded-full animate-bounce"
            style={{ animationDelay: '0ms' }}
          />
          <div
            className="w-2 h-2 bg-[var(--accent)] rounded-full animate-bounce"
            style={{ animationDelay: '150ms' }}
          />
          <div
            className="w-2 h-2 bg-[var(--accent)] rounded-full animate-bounce"
            style={{ animationDelay: '300ms' }}
          />
        </div>
      </div>
    </div>
  );
}

export default function GmailOAuthCallbackPage() {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center">
      <Scanlines />
      <CRTVignette />
      <Suspense fallback={<LoadingFallback />}>
        <GmailOAuthCallbackContent />
      </Suspense>
    </div>
  );
}
