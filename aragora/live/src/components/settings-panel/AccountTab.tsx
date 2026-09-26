'use client';

import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';
import { MFASettings } from '@/components/settings/MFASettings';
import { SessionHistory } from '@/components/session/SessionHistory';

interface User {
  id: string;
  email: string;
  name?: string;
  role: string;
  created_at: string;
}

interface OAuthProvider {
  id: string;
  name: string;
  enabled: boolean;
  auth_url: string;
}

interface LinkedProvider {
  provider: string;
  email: string | null;
  linked_at: string;
}

export interface AccountTabProps {
  user: User | null;
  isAuthenticated: boolean;
  backendApi: string;
}

export function AccountTab({ user, isAuthenticated, backendApi }: AccountTabProps) {
  const [logoutAllStatus, setLogoutAllStatus] = useState<'idle' | 'loading' | 'success' | 'error'>(
    'idle',
  );
  const [oauthProviders, setOauthProviders] = useState<OAuthProvider[]>([]);
  const [linkedProviders, setLinkedProviders] = useState<LinkedProvider[]>([]);
  const [oauthLoading, setOauthLoading] = useState(true);
  const [oauthLinkStatus, setOauthLinkStatus] = useState<
    Record<string, 'idle' | 'linking' | 'unlinking' | 'error'>
  >({});

  // Fetch OAuth providers and user's linked accounts
  useEffect(() => {
    if (!isAuthenticated) {
      setOauthLoading(false);
      return;
    }

    async function fetchOAuthData() {
      setOauthLoading(true);
      try {
        // Fetch available providers
        const providersRes = await fetch(`${backendApi}/api/auth/oauth/providers`);
        if (providersRes.ok) {
          const data = await providersRes.json();
          setOauthProviders(data.providers || []);
        }

        // Fetch user's linked providers
        const linkedRes = await fetch(`${backendApi}/api/user/oauth-providers`, {
          credentials: 'include',
        });
        if (linkedRes.ok) {
          const data = await linkedRes.json();
          setLinkedProviders(data.providers || []);
        }
      } catch (error) {
        logger.warn('Failed to fetch OAuth data:', error);
      } finally {
        setOauthLoading(false);
      }
    }

    fetchOAuthData();
  }, [isAuthenticated, backendApi]);

  // Handle OAuth link
  const handleOAuthLink = useCallback(
    async (providerId: string) => {
      setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'linking' }));
      try {
        const response = await fetch(`${backendApi}/api/auth/oauth/link`, {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            provider: providerId,
            redirect_url: `${window.location.origin}/settings?linked=${providerId}`,
          }),
        });

        if (response.ok) {
          const data = await response.json();
          if (data.auth_url) {
            window.location.href = data.auth_url;
          }
        } else {
          setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'error' }));
          setTimeout(() => setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'idle' })), 3000);
        }
      } catch (error) {
        logger.error('OAuth link error:', error);
        setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'error' }));
        setTimeout(() => setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'idle' })), 3000);
      }
    },
    [backendApi],
  );

  // Handle OAuth unlink
  const handleOAuthUnlink = useCallback(
    async (providerId: string) => {
      const confirmed = window.confirm(
        `Unlink your ${providerId} account? You can still sign in with email/password.`,
      );
      if (!confirmed) return;

      setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'unlinking' }));
      try {
        const response = await fetch(`${backendApi}/api/auth/oauth/unlink`, {
          method: 'DELETE',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ provider: providerId }),
        });

        if (response.ok) {
          setLinkedProviders((prev) => prev.filter((p) => p.provider !== providerId));
          setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'idle' }));
        } else {
          const data = await response.json().catch(() => ({}));
          alert(data.error || 'Failed to unlink account');
          setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'error' }));
          setTimeout(() => setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'idle' })), 3000);
        }
      } catch (error) {
        logger.error('OAuth unlink error:', error);
        setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'error' }));
        setTimeout(() => setOauthLinkStatus((prev) => ({ ...prev, [providerId]: 'idle' })), 3000);
      }
    },
    [backendApi],
  );

  // Logout from all devices
  const handleLogoutAllDevices = useCallback(async () => {
    if (logoutAllStatus === 'loading') return;

    const confirmed = window.confirm(
      'This will log you out from all devices and sessions. You will need to sign in again. Continue?',
    );
    if (!confirmed) return;

    setLogoutAllStatus('loading');
    try {
      const response = await fetch(`${backendApi}/api/auth/logout-all`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
      });

      if (response.ok) {
        setLogoutAllStatus('success');
        setTimeout(() => {
          window.location.href = '/auth/login?reason=logout_all';
        }, 1500);
      } else {
        const data = await response.json().catch(() => ({}));
        logger.error('Logout all failed:', data);
        setLogoutAllStatus('error');
        setTimeout(() => setLogoutAllStatus('idle'), 3000);
      }
    } catch (error) {
      logger.error('Logout all error:', error);
      setLogoutAllStatus('error');
      setTimeout(() => setLogoutAllStatus('idle'), 3000);
    }
  }, [backendApi, logoutAllStatus]);

  if (!isAuthenticated || !user) {
    return (
      <div
        className="card p-6 text-center"
        role="tabpanel"
        id="panel-account"
        aria-labelledby="tab-account"
      >
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Not Signed In</h3>
        <p className="font-theme-data text-sm text-text-muted mb-4">
          Sign in to manage your account settings and access personalized features.
        </p>
        <a
          href="/auth/login"
          className="inline-block px-6 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors"
        >
          Sign In
        </a>
      </div>
    );
  }

  return (
    <div className="space-y-6" role="tabpanel" id="panel-account" aria-labelledby="tab-account">
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Account Information</h3>
        <div className="space-y-4">
          <div>
            <label className="font-theme-data text-xs text-text-muted">Email</label>
            <div className="font-theme-data text-sm text-text">{user.email}</div>
          </div>
          <div>
            <label className="font-theme-data text-xs text-text-muted">Name</label>
            <div className="font-theme-data text-sm text-text">{user.name || 'Not set'}</div>
          </div>
          <div>
            <label className="font-theme-data text-xs text-text-muted">Role</label>
            <div className="font-theme-data text-sm text-text capitalize">{user.role}</div>
          </div>
          <div>
            <label className="font-theme-data text-xs text-text-muted">Member Since</label>
            <div className="font-theme-data text-sm text-text">
              {new Date(user.created_at).toLocaleDateString()}
            </div>
          </div>
        </div>
      </div>

      {/* Connected Accounts (OAuth) */}
      <div className="card p-6">
        <h3 className="font-theme-data text-[var(--accent)] mb-4">Connected Accounts</h3>
        <p className="font-theme-data text-xs text-text-muted mb-4">
          Link your social accounts for quick sign-in. You can always use email/password.
        </p>

        {oauthLoading ? (
          <div className="animate-pulse space-y-3">
            <div className="h-12 bg-surface rounded" />
          </div>
        ) : oauthProviders.length === 0 ? (
          <p className="font-theme-data text-xs text-text-muted">No OAuth providers configured.</p>
        ) : (
          <div className="space-y-3">
            {oauthProviders.map((provider) => {
              const linked = linkedProviders.find((p) => p.provider === provider.id);
              const status = oauthLinkStatus[provider.id] || 'idle';

              return (
                <div
                  key={provider.id}
                  className={`flex items-center justify-between p-3 rounded border ${
                    linked
                      ? 'border-[var(--accent)]/30 bg-[var(--accent)]/5'
                      : 'border-[var(--accent)]/20 bg-surface/50'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 flex items-center justify-center bg-surface rounded">
                      {provider.id === 'google' && (
                        <svg className="w-5 h-5" viewBox="0 0 24 24" aria-hidden="true">
                          <path
                            fill="#4285F4"
                            d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z"
                          />
                          <path
                            fill="#34A853"
                            d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z"
                          />
                          <path
                            fill="#FBBC05"
                            d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z"
                          />
                          <path
                            fill="#EA4335"
                            d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z"
                          />
                        </svg>
                      )}
                    </div>

                    <div>
                      <div className="font-theme-data text-sm text-text">{provider.name}</div>
                      {linked ? (
                        <div className="font-theme-data text-xs text-[var(--accent)]">
                          Connected {linked.email ? `as ${linked.email}` : ''}
                        </div>
                      ) : (
                        <div className="font-theme-data text-xs text-text-muted">Not connected</div>
                      )}
                    </div>
                  </div>

                  {linked ? (
                    <button
                      onClick={() => handleOAuthUnlink(provider.id)}
                      disabled={status === 'unlinking'}
                      className={`px-3 py-1 font-theme-data text-xs rounded transition-colors ${
                        status === 'unlinking'
                          ? 'text-text-muted cursor-wait'
                          : status === 'error'
                            ? 'text-acid-red'
                            : 'text-acid-red/70 hover:text-acid-red hover:bg-acid-red/10'
                      }`}
                    >
                      {status === 'unlinking'
                        ? 'Unlinking...'
                        : status === 'error'
                          ? 'Error'
                          : 'Unlink'}
                    </button>
                  ) : (
                    <button
                      onClick={() => handleOAuthLink(provider.id)}
                      disabled={status === 'linking'}
                      className={`px-3 py-1 font-theme-data text-xs rounded transition-colors ${
                        status === 'linking'
                          ? 'text-text-muted cursor-wait'
                          : status === 'error'
                            ? 'text-acid-red'
                            : 'text-[var(--acid-cyan)] hover:text-[var(--accent)] hover:bg-[var(--accent)]/10'
                      }`}
                    >
                      {status === 'linking' ? 'Linking...' : status === 'error' ? 'Error' : 'Link'}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="card p-6 border-acid-yellow/30">
        <h3 className="font-theme-data text-[var(--acid-yellow)] mb-4">Security</h3>

        {/* MFA Settings */}
        <MFASettings user={user} />

        <div className="mt-6 pt-4 border-t border-acid-yellow/20">
          <h4 className="font-theme-data text-sm text-text mb-4">Session Management</h4>
          <SessionHistory className="mb-4" />
          <button
            onClick={handleLogoutAllDevices}
            disabled={logoutAllStatus === 'loading'}
            className={`w-full px-4 py-2 border font-theme-data text-sm rounded transition-colors text-left ${
              logoutAllStatus === 'success'
                ? 'border-[var(--accent)]/40 text-[var(--accent)] bg-[var(--accent)]/10'
                : logoutAllStatus === 'error'
                  ? 'border-acid-red/40 text-acid-red bg-acid-red/10'
                  : 'border-acid-yellow/40 text-[var(--acid-yellow)] hover:bg-acid-yellow/10'
            } disabled:opacity-50`}
          >
            {logoutAllStatus === 'loading'
              ? 'Logging out...'
              : logoutAllStatus === 'success'
                ? 'Logged out! Redirecting...'
                : logoutAllStatus === 'error'
                  ? 'Failed - try again'
                  : 'Logout All Devices (Including Current)'}
          </button>
          <p className="font-theme-data text-xs text-text-muted mt-2">
            Invalidates all sessions including your current one. You will be signed out everywhere.
          </p>
        </div>
      </div>

      <div className="card p-6 border-acid-red/30">
        <h3 className="font-theme-data text-acid-red mb-4">Danger Zone</h3>
        <p className="font-theme-data text-xs text-text-muted mb-4">
          These actions are irreversible. Please proceed with caution.
        </p>
        <div className="space-y-3">
          <button className="w-full px-4 py-2 border border-acid-yellow/40 text-[var(--acid-yellow)] font-theme-data text-sm rounded hover:bg-acid-yellow/10 transition-colors text-left">
            Export All Data
          </button>
          <button className="w-full px-4 py-2 border border-acid-red/40 text-acid-red font-theme-data text-sm rounded hover:bg-acid-red/10 transition-colors text-left">
            Delete Account
          </button>
        </div>
      </div>
    </div>
  );
}

export default AccountTab;
