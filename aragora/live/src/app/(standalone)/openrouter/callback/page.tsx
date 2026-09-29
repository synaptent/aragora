'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { exchangeCodeForKey, SESSION_RETURN_KEY } from '@/lib/openrouter-pkce';
import { getStoredProviderKeys, storeProviderKeys } from '@/lib/provider-keys';

type Status = 'processing' | 'success' | 'error';

function CallbackContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [status, setStatus] = useState<Status>('processing');
  const [message, setMessage] = useState('Connecting to OpenRouter...');

  useEffect(() => {
    const code = searchParams.get('code');
    if (!code) {
      setStatus('error');
      setMessage('No authorization code received. Please try connecting again.');
      return;
    }

    let cancelled = false;

    async function exchange() {
      try {
        const { key } = await exchangeCodeForKey(code!);

        if (cancelled) return;

        // Store the key in the same slot as manual paste
        const keys = getStoredProviderKeys();
        keys.openrouter = key;
        storeProviderKeys(keys);

        // Notify other components / tabs
        window.dispatchEvent(new Event('openrouter:updated'));

        setStatus('success');
        setMessage('Connected! Redirecting...');

        // Redirect to where the user came from
        const returnPath = sessionStorage.getItem(SESSION_RETURN_KEY) || '/landing/';
        sessionStorage.removeItem(SESSION_RETURN_KEY);

        setTimeout(() => {
          if (!cancelled) router.replace(returnPath);
        }, 1200);
      } catch (err) {
        if (cancelled) return;
        setStatus('error');
        setMessage(err instanceof Error ? err.message : 'Failed to connect. Please try again.');
      }
    }

    exchange();
    return () => {
      cancelled = true;
    };
  }, [searchParams, router]);

  const statusIcon = status === 'processing' ? '...' : status === 'success' ? '\u2713' : '\u2717';
  const statusColor =
    status === 'processing'
      ? 'var(--accent)'
      : status === 'success'
        ? 'var(--accent)'
        : 'var(--crimson, #ff0040)';

  return (
    <div
      className="min-h-screen flex items-center justify-center px-4"
      style={{ backgroundColor: 'var(--bg)', color: 'var(--text)' }}
    >
      <div className="text-center max-w-md w-full">
        <div className="text-5xl font-theme-data mb-6" style={{ color: statusColor }}>
          {statusIcon}
        </div>
        <h1 className="font-theme-data text-lg mb-2" style={{ color: 'var(--text)' }}>
          {status === 'processing' && 'Connecting OpenRouter'}
          {status === 'success' && 'Connected'}
          {status === 'error' && 'Connection Failed'}
        </h1>
        <p className="font-theme-data text-sm" style={{ color: 'var(--text-muted)' }}>
          {message}
        </p>

        {status === 'processing' && (
          <div className="mt-6 flex justify-center">
            <div
              className="w-6 h-6 border-2 rounded-full animate-spin"
              style={{
                borderColor: 'color-mix(in srgb, var(--accent) 20%, transparent)',
                borderTopColor: 'var(--accent)',
              }}
            />
          </div>
        )}

        {status === 'error' && (
          <div className="mt-6 flex gap-3 justify-center">
            <button
              onClick={() => router.replace('/landing/')}
              className="px-4 py-2 font-theme-data text-xs rounded transition-colors cursor-pointer"
              style={{
                color: 'var(--accent)',
                border: '1px solid color-mix(in srgb, var(--accent) 40%, transparent)',
              }}
            >
              Back to home
            </button>
            <button
              onClick={() => router.replace('/settings/')}
              className="px-4 py-2 font-theme-data text-xs rounded transition-colors cursor-pointer"
              style={{ color: 'var(--text-muted)', border: '1px solid var(--border)' }}
            >
              Paste key manually
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export default function OpenRouterCallbackPage() {
  return (
    <Suspense
      fallback={
        <div
          className="min-h-screen flex items-center justify-center"
          style={{ backgroundColor: 'var(--bg)', color: 'var(--text-muted)' }}
        >
          <span className="font-theme-data text-sm">Loading...</span>
        </div>
      }
    >
      <CallbackContent />
    </Suspense>
  );
}
