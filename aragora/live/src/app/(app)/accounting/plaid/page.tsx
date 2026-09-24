'use client';

/**
 * Plaid Link Integration Page
 *
 * Handles the Plaid Link flow for connecting bank accounts:
 * 1. Receives link_token from URL parameter
 * 2. Initializes Plaid Link SDK
 * 3. Opens Plaid modal for user to connect accounts
 * 4. On success, exchanges public_token for access_token
 * 5. Redirects back to accounting page
 *
 * Note: In production, install react-plaid-link:
 *   npm install react-plaid-link
 */

import { useEffect, useState, useCallback, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';
import { logger } from '@/utils/logger';

// Plaid Link types (from react-plaid-link)
interface PlaidLinkOnSuccessMetadata {
  institution: { name: string; institution_id: string } | null;
  accounts: Array<{ id: string; name: string; mask: string; type: string; subtype: string }>;
  link_session_id: string;
}

interface PlaidLinkOnExitMetadata {
  institution: { name: string; institution_id: string } | null;
  status: string;
  link_session_id: string;
}

interface PlaidLinkError {
  error_type: string;
  error_code: string;
  error_message: string;
  display_message: string | null;
}

type PlaidLinkOnSuccess = (public_token: string, metadata: PlaidLinkOnSuccessMetadata) => void;
type PlaidLinkOnExit = (error: PlaidLinkError | null, metadata: PlaidLinkOnExitMetadata) => void;
type PlaidLinkOnEvent = (eventName: string, metadata: unknown) => void;

function PlaidLinkContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();

  const [linkToken, setLinkToken] = useState<string | null>(null);
  const [status, setStatus] = useState<
    'loading' | 'ready' | 'linking' | 'exchanging' | 'success' | 'error'
  >('loading');
  const [error, setError] = useState<string | null>(null);
  const [linkedAccounts, setLinkedAccounts] = useState<PlaidLinkOnSuccessMetadata['accounts']>([]);
  const [institutionName, setInstitutionName] = useState<string>('');

  // Get link token from URL or fetch new one
  useEffect(() => {
    const tokenFromUrl = searchParams.get('token');
    if (tokenFromUrl) {
      setLinkToken(tokenFromUrl);
      setStatus('ready');
    } else {
      // Fetch new link token
      fetchLinkToken();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetchLinkToken is stable, only run on mount
  }, [searchParams]);

  const fetchLinkToken = async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/accounting/bank/link`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
      });

      if (!response.ok) throw new Error('Failed to get link token');

      const data = await response.json();
      if (data.link_token) {
        setLinkToken(data.link_token);
        setStatus('ready');
      } else {
        throw new Error('No link token received');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to initialize Plaid Link');
      setStatus('error');
    }
  };

  const onSuccess: PlaidLinkOnSuccess = useCallback(
    async (public_token, metadata) => {
      setStatus('exchanging');
      setLinkedAccounts(metadata.accounts);
      setInstitutionName(metadata.institution?.name || 'Bank');

      try {
        // Exchange public_token for access_token
        const response = await fetch(`${backendConfig.api}/api/accounting/bank/exchange`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({
            public_token,
            institution_id: metadata.institution?.institution_id,
            institution_name: metadata.institution?.name,
            accounts: metadata.accounts,
          }),
        });

        if (!response.ok) throw new Error('Failed to link bank account');

        setStatus('success');

        // Redirect after a moment
        setTimeout(() => {
          router.push('/accounting');
        }, 2000);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to complete bank connection');
        setStatus('error');
      }
    },
    [backendConfig.api, tokens?.access_token, router],
  );

  const onExit: PlaidLinkOnExit = useCallback(
    (plaidError, _metadata) => {
      if (plaidError) {
        setError(plaidError.display_message || plaidError.error_message);
        setStatus('error');
      } else {
        // User cancelled
        router.push('/accounting');
      }
    },
    [router],
  );

  const onEvent: PlaidLinkOnEvent = useCallback((eventName, metadata) => {
    // Log events for debugging
    logger.debug('[Plaid Link Event]', eventName, metadata);
  }, []);

  const openPlaidLink = useCallback(() => {
    if (!linkToken) return;
    setStatus('linking');

    // Check if Plaid Link SDK is available
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const Plaid = (window as any).Plaid;

    if (Plaid) {
      const handler = Plaid.create({ token: linkToken, onSuccess, onExit, onEvent });
      handler.open();
    } else {
      // Plaid SDK not loaded - show manual fallback or demo mode
      logger.warn('Plaid Link SDK not loaded. Using demo mode.');
      // Simulate success for demo
      setTimeout(() => {
        onSuccess('demo_public_token', {
          institution: { name: 'Demo Bank', institution_id: 'demo_inst' },
          accounts: [
            {
              id: 'demo_acc_1',
              name: 'Checking',
              mask: '1234',
              type: 'depository',
              subtype: 'checking',
            },
            {
              id: 'demo_acc_2',
              name: 'Savings',
              mask: '5678',
              type: 'depository',
              subtype: 'savings',
            },
          ],
          link_session_id: 'demo_session',
        });
      }, 1500);
    }
  }, [linkToken, onSuccess, onExit, onEvent]);

  return (
    <div className="min-h-screen bg-[var(--background)] flex items-center justify-center p-4">
      <div className="max-w-md w-full">
        <div className="bg-[var(--surface)] border border-[var(--border)] rounded-lg p-8 text-center">
          {/* Loading State */}
          {status === 'loading' && (
            <>
              <div className="w-16 h-16 mx-auto mb-6 border-4 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
              <h2 className="text-lg font-theme-data mb-2">Initializing...</h2>
              <p className="text-sm text-[var(--muted)]">Preparing secure bank connection</p>
            </>
          )}

          {/* Ready State */}
          {status === 'ready' && (
            <>
              <div className="text-5xl mb-6">🏦</div>
              <h2 className="text-xl font-theme-data text-[var(--accent)] mb-2">
                Connect Your Bank
              </h2>
              <p className="text-sm text-[var(--muted)] mb-6">
                Securely link your bank accounts via Plaid for automatic transaction sync and
                reconciliation.
              </p>

              <div className="space-y-4 mb-6 text-left">
                <div className="flex items-start gap-3 text-sm">
                  <span className="text-green-400">&#10003;</span>
                  <span>Bank-level security encryption</span>
                </div>
                <div className="flex items-start gap-3 text-sm">
                  <span className="text-green-400">&#10003;</span>
                  <span>Read-only access to transactions</span>
                </div>
                <div className="flex items-start gap-3 text-sm">
                  <span className="text-green-400">&#10003;</span>
                  <span>Disconnect anytime from settings</span>
                </div>
              </div>

              <button
                onClick={openPlaidLink}
                className="w-full px-6 py-3 bg-[var(--accent)] text-[var(--background)] font-theme-data rounded hover:opacity-90 transition-opacity"
              >
                Connect Bank Account
              </button>

              <button
                onClick={() => router.push('/accounting')}
                className="w-full mt-3 px-6 py-2 text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors"
              >
                Cancel
              </button>
            </>
          )}

          {/* Linking State */}
          {status === 'linking' && (
            <>
              <div className="w-16 h-16 mx-auto mb-6 border-4 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
              <h2 className="text-lg font-theme-data mb-2">Connecting...</h2>
              <p className="text-sm text-[var(--muted)]">
                Follow the instructions in the Plaid window
              </p>
            </>
          )}

          {/* Exchanging State */}
          {status === 'exchanging' && (
            <>
              <div className="w-16 h-16 mx-auto mb-6 border-4 border-green-400 border-t-transparent rounded-full animate-spin" />
              <h2 className="text-lg font-theme-data mb-2">Almost Done...</h2>
              <p className="text-sm text-[var(--muted)]">Securely linking your accounts</p>
            </>
          )}

          {/* Success State */}
          {status === 'success' && (
            <>
              <div className="w-16 h-16 mx-auto mb-6 bg-green-500/20 rounded-full flex items-center justify-center">
                <span className="text-3xl text-green-400">&#10003;</span>
              </div>
              <h2 className="text-xl font-theme-data text-green-400 mb-2">Bank Connected!</h2>
              <p className="text-sm text-[var(--muted)] mb-4">
                Successfully linked {linkedAccounts.length} account
                {linkedAccounts.length !== 1 ? 's' : ''} from {institutionName}
              </p>

              <div className="bg-[var(--background)] rounded p-4 mb-4">
                {linkedAccounts.map((account) => (
                  <div
                    key={account.id}
                    className="flex items-center justify-between py-2 border-b border-[var(--border)] last:border-0"
                  >
                    <span className="text-sm">{account.name}</span>
                    <span className="text-xs text-[var(--muted)]">••••{account.mask}</span>
                  </div>
                ))}
              </div>

              <p className="text-xs text-[var(--muted)]">Redirecting to accounting...</p>
            </>
          )}

          {/* Error State */}
          {status === 'error' && (
            <>
              <div className="w-16 h-16 mx-auto mb-6 bg-red-500/20 rounded-full flex items-center justify-center">
                <span className="text-3xl text-red-400">&#10007;</span>
              </div>
              <h2 className="text-xl font-theme-data text-red-400 mb-2">Connection Failed</h2>
              <p className="text-sm text-[var(--muted)] mb-6">
                {error || 'Something went wrong. Please try again.'}
              </p>

              <button
                onClick={() => {
                  setStatus('ready');
                  setError(null);
                }}
                className="w-full px-6 py-3 bg-[var(--surface)] border border-[var(--border)] font-theme-data rounded hover:border-[var(--accent)] transition-colors mb-3"
              >
                Try Again
              </button>

              <button
                onClick={() => router.push('/accounting')}
                className="w-full px-6 py-2 text-sm text-[var(--muted)] hover:text-[var(--text)] transition-colors"
              >
                Cancel
              </button>
            </>
          )}
        </div>

        {/* Security Note */}
        <div className="mt-6 text-center">
          <p className="text-xs text-[var(--muted)]">
            <span className="inline-flex items-center gap-1">
              <span>&#128274;</span> Powered by Plaid
            </span>
          </p>
          <p className="text-xs text-[var(--muted)] mt-1">
            Your credentials are never stored on our servers
          </p>
        </div>
      </div>
    </div>
  );
}

export default function PlaidLinkPage() {
  return (
    <Suspense
      fallback={
        <div className="min-h-screen bg-[var(--background)] flex items-center justify-center">
          <div className="w-16 h-16 border-4 border-[var(--accent)] border-t-transparent rounded-full animate-spin" />
        </div>
      }
    >
      <PlaidLinkContent />
    </Suspense>
  );
}
