'use client';

import { Suspense, useState, useEffect } from 'react';
import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { useTheme } from '@/context/ThemeContext';
import { Header } from '@/components/landing/Header';
import { SocialLoginButtons } from '@/components/auth/SocialLoginButtons';
import { normalizeReturnUrl, RETURN_URL_STORAGE_KEY } from '@/utils/returnUrl';

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const requestedReturnUrl =
    searchParams.get('returnUrl') ||
    searchParams.get('redirect') ||
    (typeof window !== 'undefined' ? sessionStorage.getItem(RETURN_URL_STORAGE_KEY) : null);
  const redirectTo = normalizeReturnUrl(requestedReturnUrl);
  const { login, isLoading: authLoading } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  // Save return URL to sessionStorage so the OAuth callback can use it too
  useEffect(() => {
    if (redirectTo && redirectTo !== '/') {
      sessionStorage.setItem(RETURN_URL_STORAGE_KEY, redirectTo);
    }
  }, [redirectTo]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setIsLoading(true);

    const result = await login(email, password);

    if (result.success) {
      sessionStorage.removeItem(RETURN_URL_STORAGE_KEY);
      router.push(redirectTo);
    } else {
      setError(result.error || 'Login failed');
    }

    setIsLoading(false);
  };

  return (
    <div className="w-full" style={{ maxWidth: '380px' }}>
      <div
        style={{
          border: '1px solid var(--border)',
          backgroundColor: 'var(--surface)',
          borderRadius: 'var(--radius-card, 0)',
          padding: '40px 32px',
          boxShadow: 'var(--shadow-card)',
        }}
      >
        <div className="text-center" style={{ marginBottom: '32px' }}>
          <h1
            style={{
              fontFamily: 'var(--font-display, var(--font-landing))',
              fontSize: '22px',
              fontWeight: 600,
              color: 'var(--text)',
              marginBottom: '8px',
            }}
          >
            Welcome back
          </h1>
          <p
            style={{
              color: 'var(--text-muted)',
              fontSize: '14px',
              fontFamily: 'var(--font-landing)',
            }}
          >
            Sign in to your account
          </p>
        </div>

        {error && (
          <div
            role="alert"
            style={{
              marginBottom: '24px',
              padding: '12px',
              border: '1px solid var(--warning, #e67700)',
              backgroundColor: 'color-mix(in srgb, var(--warning, #e67700) 10%, transparent)',
              color: 'var(--warning, #e67700)',
              fontSize: '13px',
              fontFamily: 'var(--font-landing)',
              borderRadius: 'var(--radius-button, 0)',
            }}
          >
            <p>{error}</p>
            {(error.toLowerCase().includes('invalid') ||
              error.toLowerCase().includes('failed')) && (
              <p style={{ marginTop: '8px', color: 'var(--text-muted)', fontSize: '12px' }}>
                Tip: Try signing in with Google or GitHub below
              </p>
            )}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-5">
          <div>
            <label
              htmlFor="email"
              style={{
                display: 'block',
                fontSize: '12px',
                fontFamily: 'var(--font-landing)',
                fontWeight: 600,
                color: 'var(--text-muted)',
                marginBottom: '6px',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Email address
            </label>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              disabled={isLoading || authLoading}
              autoComplete="email"
              aria-describedby={error ? 'login-error' : undefined}
              placeholder="user@example.com"
              style={{
                width: '100%',
                padding: '10px 14px',
                backgroundColor: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-button, 0)',
                color: 'var(--text)',
                fontFamily: 'var(--font-landing)',
                fontSize: '14px',
                outline: 'none',
              }}
            />
          </div>

          <div>
            <label
              htmlFor="password"
              style={{
                display: 'block',
                fontSize: '12px',
                fontFamily: 'var(--font-landing)',
                fontWeight: 600,
                color: 'var(--text-muted)',
                marginBottom: '6px',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={isLoading || authLoading}
              autoComplete="current-password"
              aria-describedby={error ? 'login-error' : undefined}
              placeholder="********"
              style={{
                width: '100%',
                padding: '10px 14px',
                backgroundColor: 'var(--bg)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-button, 0)',
                color: 'var(--text)',
                fontFamily: 'var(--font-landing)',
                fontSize: '14px',
                outline: 'none',
              }}
            />
          </div>

          <button
            type="submit"
            disabled={isLoading || authLoading}
            className="transition-opacity hover:opacity-80 disabled:opacity-50 disabled:cursor-not-allowed"
            style={{
              width: '100%',
              padding: '12px',
              backgroundColor: 'var(--accent)',
              color: 'var(--bg)',
              fontFamily: 'var(--font-landing)',
              fontWeight: 700,
              fontSize: '14px',
              border: 'none',
              borderRadius: 'var(--radius-button, 0)',
              cursor: 'pointer',
            }}
          >
            {isLoading ? 'Signing in...' : 'Sign in'}
          </button>
        </form>

        <SocialLoginButtons mode="login" />

        <div className="text-center" style={{ marginTop: '24px' }}>
          <Link
            href="/signup"
            className="transition-opacity hover:opacity-70"
            style={{ fontSize: '14px', fontFamily: 'var(--font-landing)', color: 'var(--accent)' }}
          >
            No account? Sign up free
          </Link>
        </div>

        <div
          style={{ marginTop: '32px', paddingTop: '24px', borderTop: '1px solid var(--border)' }}
        >
          <p
            style={{
              fontSize: '12px',
              fontFamily: 'var(--font-landing)',
              color: 'var(--text-muted)',
              textAlign: 'center',
            }}
          >
            Free tier: 10 debates/month with real AI models
          </p>
        </div>
      </div>
    </div>
  );
}

/**
 * Login page at /login (canonical URL).
 * Wrapped in Suspense for static export compatibility with useSearchParams.
 */
export default function LoginPage() {
  const { theme } = useTheme();

  return (
    <div
      className="min-h-screen"
      style={{ backgroundColor: 'var(--bg)', color: 'var(--text)' }}
      data-landing-theme={theme}
    >
      <Header />

      <main
        className="flex-1 flex items-center justify-center px-4 py-16"
        style={{ minHeight: 'calc(100vh - 60px)' }}
      >
        <Suspense
          fallback={
            <div
              style={{ color: 'var(--accent)', fontFamily: 'var(--font-landing)' }}
              className="animate-pulse"
            >
              Loading...
            </div>
          }
        >
          <LoginForm />
        </Suspense>
      </main>
    </div>
  );
}
