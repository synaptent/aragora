'use client';

import { useState, useEffect, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

interface ReconciliationStatus {
  status: 'idle' | 'running' | 'completed' | 'failed';
  progress: number;
  totalTransactions: number;
  matchedTransactions: number;
  unmatchedBank: number;
  unmatchedBook: number;
  discrepancies: number;
  lastRun?: string;
  error?: string;
}

interface ReconciliationSummary {
  period: string;
  bankBalance: number;
  bookBalance: number;
  difference: number;
  matchRate: number;
  status: 'reconciled' | 'pending' | 'issues';
}

export function ReconciliationProgress() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const [status, setStatus] = useState<ReconciliationStatus | null>(null);
  const [summaries, setSummaries] = useState<ReconciliationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const fetchStatus = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/accounting/reconciliation/status`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (response.ok) {
        const data = await response.json();
        setStatus(data.status);
        setSummaries(data.summaries || []);
      } else {
        // Use mock data for demo
        setStatus({
          status: 'completed',
          progress: 100,
          totalTransactions: 156,
          matchedTransactions: 142,
          unmatchedBank: 8,
          unmatchedBook: 6,
          discrepancies: 3,
          lastRun: new Date(Date.now() - 3600000).toISOString(),
        });
        setSummaries([
          {
            period: 'January 2025',
            bankBalance: 45672.89,
            bookBalance: 45680.5,
            difference: -7.61,
            matchRate: 97.2,
            status: 'issues',
          },
          {
            period: 'December 2024',
            bankBalance: 52340.0,
            bookBalance: 52340.0,
            difference: 0,
            matchRate: 100,
            status: 'reconciled',
          },
          {
            period: 'November 2024',
            bankBalance: 48750.25,
            bookBalance: 48750.25,
            difference: 0,
            matchRate: 100,
            status: 'reconciled',
          },
        ]);
      }
    } catch {
      // Silently fail
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api, tokens?.access_token]);

  useEffect(() => {
    fetchStatus();
    // Poll while running
    const interval = setInterval(() => {
      if (status?.status === 'running') {
        fetchStatus();
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [fetchStatus, status?.status]);

  const handleRunReconciliation = useCallback(async () => {
    setRunning(true);
    try {
      const response = await fetch(`${backendConfig.api}/api/accounting/reconcile`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${tokens?.access_token || ''}`,
        },
      });
      if (response.ok) {
        fetchStatus();
      }
    } catch {
      // Handle error
    } finally {
      setRunning(false);
    }
  }, [backendConfig.api, tokens?.access_token, fetchStatus]);

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 animate-pulse">
        <div className="h-5 bg-[var(--bg)] rounded w-1/3 mb-4" />
        <div className="h-32 bg-[var(--bg)] rounded" />
      </div>
    );
  }

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
        <div>
          <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
            {'>'} BANK RECONCILIATION
          </h3>
          {status?.lastRun && (
            <p className="text-xs text-[var(--text-muted)] mt-1">
              Last run: {new Date(status.lastRun).toLocaleString()}
            </p>
          )}
        </div>
        <button
          onClick={handleRunReconciliation}
          disabled={running || status?.status === 'running'}
          className="px-4 py-2 text-xs font-theme-data bg-[var(--acid-green)]/10 border border-[var(--acid-green)]/40 text-[var(--acid-green)] rounded hover:bg-[var(--acid-green)]/20 transition-colors disabled:opacity-50"
        >
          {running || status?.status === 'running' ? 'Running...' : 'Run Reconciliation'}
        </button>
      </div>

      {/* Progress Bar (when running) */}
      {status?.status === 'running' && (
        <div className="p-4 bg-[var(--bg)] border-b border-[var(--border)]">
          <div className="flex items-center justify-between text-xs mb-2">
            <span className="text-[var(--text-muted)]">Processing transactions...</span>
            <span className="text-[var(--acid-green)]">{status.progress}%</span>
          </div>
          <div className="h-2 bg-[var(--border)] rounded overflow-hidden">
            <div
              className="h-full bg-[var(--acid-green)] transition-all duration-300"
              style={{ width: `${status.progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Stats Grid */}
      {status?.status === 'completed' && (
        <div className="grid grid-cols-4 gap-4 p-4 border-b border-[var(--border)]">
          <div className="text-center">
            <div className="text-2xl font-theme-data text-[var(--acid-green)]">
              {status.matchedTransactions}
            </div>
            <div className="text-xs text-[var(--text-muted)]">Matched</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-theme-data text-yellow-400">{status.unmatchedBank}</div>
            <div className="text-xs text-[var(--text-muted)]">Bank Only</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-theme-data text-yellow-400">{status.unmatchedBook}</div>
            <div className="text-xs text-[var(--text-muted)]">Book Only</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-theme-data text-red-400">{status.discrepancies}</div>
            <div className="text-xs text-[var(--text-muted)]">Discrepancies</div>
          </div>
        </div>
      )}

      {/* Period Summaries */}
      <div className="divide-y divide-[var(--border)]">
        {summaries.map((summary) => (
          <div key={summary.period} className="p-4 flex items-center justify-between">
            <div>
              <div className="text-sm font-theme-data">{summary.period}</div>
              <div className="text-xs text-[var(--text-muted)] mt-1">
                Match rate: {summary.matchRate.toFixed(1)}%
              </div>
            </div>
            <div className="flex items-center gap-6">
              <div className="text-right">
                <div className="text-xs text-[var(--text-muted)]">Bank</div>
                <div className="text-sm font-theme-data">
                  ${summary.bankBalance.toLocaleString()}
                </div>
              </div>
              <div className="text-right">
                <div className="text-xs text-[var(--text-muted)]">Book</div>
                <div className="text-sm font-theme-data">
                  ${summary.bookBalance.toLocaleString()}
                </div>
              </div>
              <div className="text-right min-w-[80px]">
                <div className="text-xs text-[var(--text-muted)]">Difference</div>
                <div
                  className={`text-sm font-theme-data ${
                    summary.difference === 0
                      ? 'text-green-400'
                      : Math.abs(summary.difference) < 10
                        ? 'text-yellow-400'
                        : 'text-red-400'
                  }`}
                >
                  {summary.difference >= 0 ? '+' : ''}${summary.difference.toFixed(2)}
                </div>
              </div>
              <div>
                {summary.status === 'reconciled' && (
                  <span className="px-2 py-1 text-xs font-theme-data bg-green-500/10 border border-green-500/30 rounded text-green-400">
                    Reconciled
                  </span>
                )}
                {summary.status === 'pending' && (
                  <span className="px-2 py-1 text-xs font-theme-data bg-yellow-500/10 border border-yellow-500/30 rounded text-yellow-400">
                    Pending
                  </span>
                )}
                {summary.status === 'issues' && (
                  <span className="px-2 py-1 text-xs font-theme-data bg-red-500/10 border border-red-500/30 rounded text-red-400">
                    Issues
                  </span>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* AI Assist */}
      {status?.discrepancies && status.discrepancies > 0 && (
        <div className="p-4 bg-[var(--acid-green)]/5 border-t border-[var(--acid-green)]/20">
          <div className="flex items-center gap-3">
            <span className="text-xl">🤖</span>
            <div className="flex-1">
              <div className="text-sm font-theme-data text-[var(--acid-green)]">
                AI Resolution Available
              </div>
              <p className="text-xs text-[var(--text-muted)]">
                {status.discrepancies} discrepancies can be analyzed by multi-agent debate
              </p>
            </div>
            <button className="px-4 py-2 text-xs font-theme-data bg-[var(--acid-green)]/10 border border-[var(--acid-green)]/40 text-[var(--acid-green)] rounded hover:bg-[var(--acid-green)]/20 transition-colors">
              Analyze Discrepancies
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
