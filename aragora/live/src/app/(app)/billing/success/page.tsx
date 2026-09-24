'use client';

import { Suspense, useEffect, useState } from 'react';
import { useSearchParams } from 'next/navigation';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';

function BillingSuccessContent() {
  const searchParams = useSearchParams();
  const sessionId = searchParams.get('session_id');
  const [status, setStatus] = useState<'loading' | 'success' | 'error'>('loading');

  useEffect(() => {
    // Brief delay to let webhook process
    const timer = setTimeout(() => {
      setStatus('success');
    }, 1500);

    return () => clearTimeout(timer);
  }, [sessionId]);

  return (
    <div className="max-w-md w-full border border-[var(--accent)]/30 bg-surface/30 p-8 text-center">
      {status === 'loading' ? (
        <>
          <div className="text-4xl mb-4 animate-pulse">⟳</div>
          <h1 className="text-xl font-theme-data text-[var(--acid-cyan)] mb-2">
            PROCESSING PAYMENT...
          </h1>
          <p className="text-sm font-theme-data text-text-muted">
            Please wait while we confirm your subscription.
          </p>
        </>
      ) : status === 'success' ? (
        <>
          <div className="text-4xl mb-4 text-[var(--accent)]">✓</div>
          <h1 className="text-xl font-theme-data text-[var(--accent)] mb-2">
            SUBSCRIPTION ACTIVATED
          </h1>
          <p className="text-sm font-theme-data text-text-muted mb-6">
            Thank you for subscribing! Your account has been upgraded.
          </p>
          <div className="space-y-3">
            <Link
              href="/"
              className="block w-full py-3 font-theme-data font-bold bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
            >
              GO TO DASHBOARD
            </Link>
            <Link
              href="/billing"
              className="block w-full py-3 font-theme-data font-bold border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
            >
              VIEW SUBSCRIPTION
            </Link>
          </div>
        </>
      ) : (
        <>
          <div className="text-4xl mb-4 text-warning">⚠</div>
          <h1 className="text-xl font-theme-data text-warning mb-2">SOMETHING WENT WRONG</h1>
          <p className="text-sm font-theme-data text-text-muted mb-6">
            There was an issue processing your payment. Please contact support.
          </p>
          <Link
            href="/pricing"
            className="block w-full py-3 font-theme-data font-bold border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
          >
            TRY AGAIN
          </Link>
        </>
      )}
    </div>
  );
}

function BillingSuccessLoading() {
  return (
    <div className="max-w-md w-full border border-[var(--accent)]/30 bg-surface/30 p-8 text-center">
      <div className="text-4xl mb-4 animate-pulse">⟳</div>
      <h1 className="text-xl font-theme-data text-[var(--acid-cyan)] mb-2">LOADING...</h1>
    </div>
  );
}

export default function BillingSuccessPage() {
  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10 flex flex-col">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <Link href="/">
              <AsciiBannerCompact connected={true} />
            </Link>
          </div>
        </header>

        {/* Content */}
        <div className="flex-1 flex items-center justify-center p-4">
          <Suspense fallback={<BillingSuccessLoading />}>
            <BillingSuccessContent />
          </Suspense>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-4 border-t border-[var(--accent)]/20">
          <p className="text-text-muted">
            Questions? Contact{' '}
            <a
              href="mailto:support@aragora.ai"
              className="text-[var(--acid-cyan)] hover:text-[var(--accent)]"
            >
              support@aragora.ai
            </a>
          </p>
        </footer>
      </main>
    </>
  );
}
