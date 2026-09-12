'use client';

import { useState, useEffect } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';
import { getCurrentReturnUrl, normalizeReturnUrl, RETURN_URL_STORAGE_KEY } from '@/utils/returnUrl';

interface Provider {
  id: string;
  name: string;
  enabled: boolean;
  auth_url: string;
}

interface SocialLoginButtonsProps {
  mode: 'login' | 'register';
}

// Google icon SVG
function GoogleIcon() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" />
      <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" />
      <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" />
      <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" />
    </svg>
  );
}

// GitHub icon SVG
function GitHubIcon() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
    </svg>
  );
}

// Microsoft icon SVG
function MicrosoftIcon() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M11.4 24H0V12.6h11.4V24zM24 24H12.6V12.6H24V24zM11.4 11.4H0V0h11.4v11.4zm12.6 0H12.6V0H24v11.4z" />
    </svg>
  );
}

// Apple icon SVG
function AppleIcon() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.81-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z" />
    </svg>
  );
}

// Generic SSO/OIDC icon
function SSOIcon() {
  return (
    <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z" />
    </svg>
  );
}

export function SocialLoginButtons({ mode }: SocialLoginButtonsProps) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, _setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchProviders = async () => {
      logger.debug(
        '[SocialLoginButtons] Fetching providers from:',
        `${API_BASE_URL}/api/auth/oauth/providers`,
      );
      try {
        // Use explicit API URL from config (handles production vs dev)
        const response = await fetch(`${API_BASE_URL}/api/auth/oauth/providers`);
        logger.debug('[SocialLoginButtons] Response status:', response.status);
        if (response.ok) {
          const data = await response.json();
          logger.debug('[SocialLoginButtons] Providers received:', data.providers?.length || 0);
          setProviders(data.providers || []);
        } else {
          // No OAuth providers configured - this is OK
          logger.debug('[SocialLoginButtons] Non-OK response, hiding buttons');
          setProviders([]);
        }
      } catch (err) {
        // API not available - hide social buttons
        logger.error('[SocialLoginButtons] Fetch error:', err);
        setProviders([]);
      } finally {
        setLoading(false);
      }
    };

    fetchProviders();
  }, []);

  const handleOAuthClick = (provider: Provider) => {
    // Save return URL before leaving for OAuth so callback can redirect back
    const params = new URLSearchParams(window.location.search);
    const queryReturnUrl = params.get('returnUrl');
    const returnUrl = normalizeReturnUrl(queryReturnUrl || getCurrentReturnUrl());
    sessionStorage.setItem(RETURN_URL_STORAGE_KEY, returnUrl);

    // Build callback URL for the current origin
    // IMPORTANT: Include trailing slash to prevent Next.js redirect which loses URL fragments
    const callbackUrl = `${window.location.origin}/auth/callback/`;
    const oauthUrl = `${API_BASE_URL}${provider.auth_url}?redirect_url=${encodeURIComponent(callbackUrl)}`;

    // Debug: Log the redirect URL
    logger.debug('[OAuth] Redirecting to:', oauthUrl);
    logger.debug('[OAuth] API_BASE_URL:', API_BASE_URL);
    logger.debug('[OAuth] provider.auth_url:', provider.auth_url);

    // Redirect to OAuth provider via our API
    window.location.href = oauthUrl;
  };

  // Don't render anything while loading or if no providers
  if (loading || providers.length === 0) {
    return null;
  }

  const actionText = mode === 'login' ? 'Sign in' : 'Sign up';

  return (
    <div className="mt-6 space-y-4">
      {/* Divider */}
      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-[var(--border)]"></div>
        </div>
        <div className="relative flex justify-center">
          <span className="px-4 bg-[var(--surface)] text-xs text-[var(--text-muted)] uppercase">
            Or continue with
          </span>
        </div>
      </div>

      {/* Provider Buttons */}
      <div className="grid gap-3">
        {providers.map((provider) => (
          <button
            key={provider.id}
            type="button"
            onClick={() => handleOAuthClick(provider)}
            className="w-full py-3 px-4 border border-[var(--border)] bg-[var(--bg)] text-[var(--text)] text-sm hover:border-[var(--accent)] hover:bg-[var(--accent)]/5 transition-colors flex items-center justify-center gap-3"
            style={{ borderRadius: 'var(--radius-button, 6px)' }}
          >
            {provider.id === 'google' && <GoogleIcon />}
            {provider.id === 'github' && <GitHubIcon />}
            {provider.id === 'microsoft' && <MicrosoftIcon />}
            {provider.id === 'apple' && <AppleIcon />}
            {provider.id === 'oidc' && <SSOIcon />}
            <span>
              {actionText} with {provider.name}
            </span>
          </button>
        ))}
      </div>

      {error && <p className="text-xs font-theme-data text-warning text-center">{error}</p>}
    </div>
  );
}

export default SocialLoginButtons;
