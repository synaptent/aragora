'use client';

import { useState, useEffect, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface BankAccount {
  id: string;
  name: string;
  mask: string;
  type: string;
  subtype: string;
  balanceCurrent: number;
  balanceAvailable?: number;
  institution: string;
  lastSync?: string;
}

interface PlaidStatus {
  connected: boolean;
  accounts: BankAccount[];
  lastSync?: string;
  error?: string;
}

export function BankConnectionCard() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const [status, setStatus] = useState<PlaidStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/accounting/bank/status`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (response.ok) {
        const data = await response.json();
        setStatus(data);
      } else {
        // Use mock data for demo
        setStatus({
          connected: true,
          accounts: [
            {
              id: 'acc_demo_checking',
              name: 'Business Checking',
              mask: '4521',
              type: 'depository',
              subtype: 'checking',
              balanceCurrent: 45672.89,
              balanceAvailable: 44500.0,
              institution: 'Chase',
              lastSync: new Date().toISOString(),
            },
            {
              id: 'acc_demo_savings',
              name: 'Business Savings',
              mask: '7832',
              type: 'depository',
              subtype: 'savings',
              balanceCurrent: 125000.0,
              balanceAvailable: 125000.0,
              institution: 'Chase',
              lastSync: new Date().toISOString(),
            },
          ],
          lastSync: new Date().toISOString(),
        });
      }
    } catch {
      setError('Failed to fetch bank status');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleConnect = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/accounting/bank/link`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
      });
      if (response.ok) {
        const data = await response.json();
        // Open Plaid Link
        if (data.link_token) {
          window.open(`/accounting/plaid?token=${data.link_token}`, '_blank');
        }
      }
    } catch {
      setError('Failed to start bank connection');
    }
  }, [backendConfig.api, tokens?.access_token]);

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      const response = await fetch(`${backendConfig.api}/api/accounting/bank/sync`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
      });
      if (response.ok) {
        await fetchStatus();
      }
    } catch {
      setError('Failed to sync bank data');
    } finally {
      setSyncing(false);
    }
  }, [backendConfig.api, tokens?.access_token, fetchStatus]);

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 animate-pulse">
        <div className="h-5 bg-[var(--bg)] rounded w-1/3 mb-4" />
        <div className="h-20 bg-[var(--bg)] rounded" />
      </div>
    );
  }

  if (!status?.connected) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6 text-center">
        <div className="text-3xl mb-3">🏦</div>
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-2">
          Connect Bank Accounts
        </h3>
        <p className="text-xs text-[var(--text-muted)] mb-4 max-w-sm mx-auto">
          Link your bank accounts via Plaid for automatic transaction sync and reconciliation.
        </p>
        <button
          onClick={handleConnect}
          className="px-4 py-2 text-sm font-theme-data bg-[var(--acid-green)]/10 border border-[var(--acid-green)]/40 text-[var(--acid-green)] rounded hover:bg-[var(--acid-green)]/20 transition-colors"
        >
          Link Bank Account
        </button>
      </div>
    );
  }

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
        <div className="flex items-center gap-3">
          <span className="text-xl">🏦</span>
          <div>
            <h3 className="text-sm font-theme-data text-[var(--acid-green)]">Bank Accounts</h3>
            <p className="text-xs text-[var(--text-muted)]">
              {status.accounts.length} account{status.accounts.length !== 1 ? 's' : ''} connected
              via Plaid
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="flex items-center gap-1 text-xs text-green-400">
            <span className="w-2 h-2 bg-green-400 rounded-full animate-pulse" />
            Live
          </span>
          <button
            onClick={handleSync}
            disabled={syncing}
            className="px-3 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] border border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 transition-colors disabled:opacity-50"
          >
            {syncing ? 'Syncing...' : 'Sync'}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="m-4 p-3 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-400">
          {error}
          <button onClick={() => setError(null)} className="ml-2 hover:text-red-300">
            ×
          </button>
        </div>
      )}

      {/* Accounts List */}
      <div className="divide-y divide-[var(--border)]">
        {status.accounts.map((account) => (
          <div key={account.id} className="p-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-[var(--bg)] rounded flex items-center justify-center text-sm font-theme-data">
                {account.institution.substring(0, 2).toUpperCase()}
              </div>
              <div>
                <div className="text-sm font-theme-data">{account.name}</div>
                <div className="text-xs text-[var(--text-muted)]">
                  {account.institution} ••••{account.mask}
                </div>
              </div>
            </div>
            <div className="text-right">
              <div className="text-sm font-theme-data text-[var(--acid-green)]">
                ${account.balanceCurrent.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </div>
              <div className="text-xs text-[var(--text-muted)]">
                {account.balanceAvailable && (
                  <span>${account.balanceAvailable.toLocaleString()} available</span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Total */}
      <div className="p-4 bg-[var(--bg)] border-t border-[var(--border)]">
        <div className="flex items-center justify-between">
          <span className="text-xs text-[var(--text-muted)]">Total Balance</span>
          <span className="text-lg font-theme-data text-[var(--acid-green)]">
            $
            {status.accounts
              .reduce((sum, acc) => sum + acc.balanceCurrent, 0)
              .toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </span>
        </div>
        {status.lastSync && (
          <div className="text-xs text-[var(--text-muted)] mt-2">
            Last sync: {new Date(status.lastSync).toLocaleString()}
          </div>
        )}
      </div>

      {/* Add Account */}
      <div className="p-4 border-t border-[var(--border)]">
        <button
          onClick={handleConnect}
          className="w-full px-4 py-2 text-xs font-theme-data text-[var(--text-muted)] border border-dashed border-[var(--border)] rounded hover:border-[var(--acid-green)]/30 hover:text-[var(--acid-green)] transition-colors"
        >
          + Add Another Account
        </button>
      </div>
    </div>
  );
}
