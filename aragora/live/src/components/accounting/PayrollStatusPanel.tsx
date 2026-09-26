'use client';

import { useState, useEffect, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface PayrollRun {
  id: string;
  payPeriodStart: string;
  payPeriodEnd: string;
  checkDate: string;
  status: 'pending' | 'processed' | 'synced' | 'failed';
  totalGross: number;
  totalNet: number;
  totalTaxes: number;
  employeeCount: number;
  qboSynced: boolean;
  journalEntryId?: string;
}

interface PayrollStatus {
  connected: boolean;
  companyName?: string;
  lastSync?: string;
  recentRuns: PayrollRun[];
  ytdGross: number;
  ytdTaxes: number;
}

export function PayrollStatusPanel() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const [status, setStatus] = useState<PayrollStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/accounting/payroll/status`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (response.ok) {
        const data = await response.json();
        setStatus(data);
      } else {
        // Use mock data for demo
        setStatus({
          connected: true,
          companyName: 'Demo Company',
          lastSync: new Date(Date.now() - 7200000).toISOString(),
          recentRuns: [
            {
              id: 'pr_1',
              payPeriodStart: '2025-01-01',
              payPeriodEnd: '2025-01-15',
              checkDate: '2025-01-17',
              status: 'synced',
              totalGross: 45250.0,
              totalNet: 32175.5,
              totalTaxes: 13074.5,
              employeeCount: 12,
              qboSynced: true,
              journalEntryId: 'JE-1234',
            },
            {
              id: 'pr_2',
              payPeriodStart: '2025-01-16',
              payPeriodEnd: '2025-01-31',
              checkDate: '2025-02-01',
              status: 'processed',
              totalGross: 46100.0,
              totalNet: 32780.25,
              totalTaxes: 13319.75,
              employeeCount: 12,
              qboSynced: false,
            },
          ],
          ytdGross: 91350.0,
          ytdTaxes: 26394.25,
        });
      }
    } catch {
      setError('Failed to fetch payroll status');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleConnect = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/accounting/payroll/connect`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
      });
      if (response.ok) {
        const data = await response.json();
        if (data.auth_url) {
          window.open(data.auth_url, '_blank');
        }
      }
    } catch {
      setError('Failed to start Gusto connection');
    }
  }, [backendConfig.api, tokens?.access_token]);

  const handleSyncToQBO = useCallback(
    async (runId: string) => {
      setSyncing(runId);
      try {
        const response = await fetch(`${backendConfig.api}/api/accounting/payroll/sync`, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${tokens?.access_token || ''}`,
          },
          body: JSON.stringify({ payroll_run_id: runId }),
        });
        if (response.ok) {
          fetchStatus();
        } else {
          setError('Failed to sync payroll to QuickBooks');
        }
      } catch {
        setError('Failed to sync payroll');
      } finally {
        setSyncing(null);
      }
    },
    [backendConfig.api, tokens?.access_token, fetchStatus],
  );

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 animate-pulse">
        <div className="h-5 bg-[var(--bg)] rounded w-1/3 mb-4" />
        <div className="h-24 bg-[var(--bg)] rounded" />
      </div>
    );
  }

  if (!status?.connected) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-6 text-center">
        <div className="text-3xl mb-3">💰</div>
        <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-2">
          Connect Gusto Payroll
        </h3>
        <p className="text-xs text-[var(--text-muted)] mb-4 max-w-sm mx-auto">
          Link your Gusto account to automatically sync payroll data and generate QuickBooks journal
          entries.
        </p>
        <button
          onClick={handleConnect}
          className="px-4 py-2 text-sm font-theme-data bg-[#F45D48]/10 border border-[#F45D48]/40 text-[#F45D48] rounded hover:bg-[#F45D48]/20 transition-colors"
        >
          Connect to Gusto
        </button>
      </div>
    );
  }

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
        <div className="flex items-center gap-3">
          <span className="text-xl">💰</span>
          <div>
            <h3 className="text-sm font-theme-data text-[var(--acid-green)]">Payroll (Gusto)</h3>
            <p className="text-xs text-[var(--text-muted)]">Connected to {status.companyName}</p>
          </div>
        </div>
        <span className="flex items-center gap-1 text-xs text-green-400">
          <span className="w-2 h-2 bg-green-400 rounded-full" />
          Synced
        </span>
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

      {/* YTD Stats */}
      <div className="grid grid-cols-2 gap-4 p-4 border-b border-[var(--border)]">
        <div>
          <div className="text-xs text-[var(--text-muted)]">YTD Gross Wages</div>
          <div className="text-xl font-theme-data text-[var(--acid-green)]">
            ${status.ytdGross.toLocaleString()}
          </div>
        </div>
        <div>
          <div className="text-xs text-[var(--text-muted)]">YTD Taxes</div>
          <div className="text-xl font-theme-data text-red-400">
            ${status.ytdTaxes.toLocaleString()}
          </div>
        </div>
      </div>

      {/* Recent Payroll Runs */}
      <div className="p-4 border-b border-[var(--border)]">
        <h4 className="text-xs text-[var(--text-muted)] mb-3">Recent Payroll Runs</h4>
        <div className="space-y-3">
          {status.recentRuns.map((run) => (
            <div key={run.id} className="p-3 bg-[var(--bg)] rounded border border-[var(--border)]">
              <div className="flex items-center justify-between mb-2">
                <div>
                  <div className="text-sm font-theme-data">
                    Pay Period: {run.payPeriodStart} - {run.payPeriodEnd}
                  </div>
                  <div className="text-xs text-[var(--text-muted)]">
                    Check Date: {run.checkDate} | {run.employeeCount} employees
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {run.status === 'synced' && (
                    <span className="px-2 py-1 text-xs font-theme-data bg-green-500/10 border border-green-500/30 rounded text-green-400">
                      QBO Synced
                    </span>
                  )}
                  {run.status === 'processed' && !run.qboSynced && (
                    <button
                      onClick={() => handleSyncToQBO(run.id)}
                      disabled={syncing === run.id}
                      className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 border border-[var(--acid-green)]/40 text-[var(--acid-green)] rounded hover:bg-[var(--acid-green)]/20 transition-colors disabled:opacity-50"
                    >
                      {syncing === run.id ? 'Syncing...' : 'Sync to QBO'}
                    </button>
                  )}
                  {run.status === 'pending' && (
                    <span className="px-2 py-1 text-xs font-theme-data bg-yellow-500/10 border border-yellow-500/30 rounded text-yellow-400">
                      Pending
                    </span>
                  )}
                  {run.status === 'failed' && (
                    <span className="px-2 py-1 text-xs font-theme-data bg-red-500/10 border border-red-500/30 rounded text-red-400">
                      Failed
                    </span>
                  )}
                </div>
              </div>
              <div className="grid grid-cols-3 gap-4 text-sm">
                <div>
                  <span className="text-[var(--text-muted)] text-xs">Gross</span>
                  <div className="font-theme-data">${run.totalGross.toLocaleString()}</div>
                </div>
                <div>
                  <span className="text-[var(--text-muted)] text-xs">Taxes</span>
                  <div className="font-theme-data text-red-400">
                    ${run.totalTaxes.toLocaleString()}
                  </div>
                </div>
                <div>
                  <span className="text-[var(--text-muted)] text-xs">Net</span>
                  <div className="font-theme-data text-[var(--acid-green)]">
                    ${run.totalNet.toLocaleString()}
                  </div>
                </div>
              </div>
              {run.journalEntryId && (
                <div className="mt-2 text-xs text-[var(--text-muted)]">
                  Journal Entry: {run.journalEntryId}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Last Sync */}
      {status.lastSync && (
        <div className="p-4 text-xs text-[var(--text-muted)]">
          Last sync: {new Date(status.lastSync).toLocaleString()}
        </div>
      )}
    </div>
  );
}
