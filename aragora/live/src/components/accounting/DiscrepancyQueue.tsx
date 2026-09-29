'use client';

import { useState, useEffect, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { useAuth } from '@/context/AuthContext';

type DiscrepancyType =
  'amount_mismatch' | 'missing_bank' | 'missing_book' | 'date_mismatch' | 'duplicate';
type ResolutionStatus = 'pending' | 'investigating' | 'resolved' | 'rejected';

interface Discrepancy {
  id: string;
  type: DiscrepancyType;
  bankTransaction?: { id: string; date: string; description: string; amount: number };
  bookTransaction?: { id: string; date: string; description: string; amount: number };
  difference?: number;
  status: ResolutionStatus;
  aiSuggestion?: string;
  aiConfidence?: number;
  resolvedBy?: string;
  resolvedAt?: string;
  resolution?: string;
}

const TYPE_LABELS: Record<DiscrepancyType, { label: string; icon: string; color: string }> = {
  amount_mismatch: { label: 'Amount Mismatch', icon: '💰', color: 'text-yellow-400' },
  missing_bank: { label: 'Missing in Bank', icon: '🏦', color: 'text-orange-400' },
  missing_book: { label: 'Missing in Books', icon: '📕', color: 'text-red-400' },
  date_mismatch: { label: 'Date Mismatch', icon: '📅', color: 'text-blue-400' },
  duplicate: { label: 'Potential Duplicate', icon: '👯', color: 'text-purple-400' },
};

export function DiscrepancyQueue() {
  const { config: backendConfig } = useBackend();
  const { tokens } = useAuth();
  const [discrepancies, setDiscrepancies] = useState<Discrepancy[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [investigating, setInvestigating] = useState<string | null>(null);
  const [filter, setFilter] = useState<'all' | 'pending' | 'resolved'>('pending');

  const fetchDiscrepancies = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/accounting/discrepancies`, {
        headers: { Authorization: `Bearer ${tokens?.access_token || ''}` },
      });
      if (response.ok) {
        const data = await response.json();
        setDiscrepancies(data.discrepancies || []);
      } else {
        // Use mock data for demo
        setDiscrepancies([
          {
            id: 'disc_1',
            type: 'amount_mismatch',
            bankTransaction: {
              id: 'bank_tx_1',
              date: '2025-01-15',
              description: 'PAYMENT TO VENDOR XYZ',
              amount: -1250.0,
            },
            bookTransaction: {
              id: 'book_tx_1',
              date: '2025-01-15',
              description: 'Vendor XYZ - Invoice #1234',
              amount: -1245.0,
            },
            difference: 5.0,
            status: 'pending',
            aiSuggestion:
              'The $5.00 difference appears to be a bank fee. Recommend recording as "Bank Service Charges" expense.',
            aiConfidence: 0.87,
          },
          {
            id: 'disc_2',
            type: 'missing_book',
            bankTransaction: {
              id: 'bank_tx_2',
              date: '2025-01-18',
              description: 'WIRE TRANSFER FROM ACME CORP',
              amount: 3500.0,
            },
            status: 'investigating',
            aiSuggestion:
              'This appears to be a customer payment from Acme Corporation. Match with open Invoice #1087 ($3,500.00).',
            aiConfidence: 0.94,
          },
          {
            id: 'disc_3',
            type: 'duplicate',
            bankTransaction: {
              id: 'bank_tx_3',
              date: '2025-01-12',
              description: 'PAYROLL - ADP',
              amount: -15420.5,
            },
            bookTransaction: {
              id: 'book_tx_3',
              date: '2025-01-12',
              description: 'Payroll - January 1st',
              amount: -15420.5,
            },
            status: 'resolved',
            aiSuggestion:
              'Transaction appears to be recorded twice in books. Recommend removing duplicate entry.',
            aiConfidence: 0.91,
            resolvedBy: 'AI Assistant',
            resolvedAt: '2025-01-20T14:30:00Z',
            resolution: 'Duplicate removed from books',
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
    fetchDiscrepancies();
  }, [fetchDiscrepancies]);

  const handleInvestigate = useCallback(
    async (id: string) => {
      setInvestigating(id);
      try {
        const response = await fetch(
          `${backendConfig.api}/api/accounting/discrepancies/${id}/investigate`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${tokens?.access_token || ''}`,
            },
          },
        );
        if (response.ok) {
          fetchDiscrepancies();
        }
      } catch {
        // Handle error
      } finally {
        setInvestigating(null);
      }
    },
    [backendConfig.api, tokens?.access_token, fetchDiscrepancies],
  );

  const handleResolve = useCallback(
    async (id: string, action: 'accept' | 'reject') => {
      try {
        const response = await fetch(
          `${backendConfig.api}/api/accounting/discrepancies/${id}/resolve`,
          {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              Authorization: `Bearer ${tokens?.access_token || ''}`,
            },
            body: JSON.stringify({ action }),
          },
        );
        if (response.ok) {
          fetchDiscrepancies();
          setSelectedId(null);
        }
      } catch {
        // Handle error
      }
    },
    [backendConfig.api, tokens?.access_token, fetchDiscrepancies],
  );

  const filteredDiscrepancies = discrepancies.filter((d) => {
    if (filter === 'pending') return d.status === 'pending' || d.status === 'investigating';
    if (filter === 'resolved') return d.status === 'resolved' || d.status === 'rejected';
    return true;
  });

  const pendingCount = discrepancies.filter(
    (d) => d.status === 'pending' || d.status === 'investigating',
  ).length;
  const resolvedCount = discrepancies.filter(
    (d) => d.status === 'resolved' || d.status === 'rejected',
  ).length;

  if (loading) {
    return (
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded p-4 animate-pulse">
        <div className="h-5 bg-[var(--bg)] rounded w-1/3 mb-4" />
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="h-20 bg-[var(--bg)] rounded" />
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] rounded">
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-[var(--border)]">
        <div>
          <h3 className="text-sm font-theme-data text-[var(--acid-green)]">
            {'>'} DISCREPANCY QUEUE
          </h3>
          <p className="text-xs text-[var(--text-muted)] mt-1">
            {pendingCount} pending, {resolvedCount} resolved
          </p>
        </div>
        <div className="flex items-center gap-2">
          {(['pending', 'resolved', 'all'] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 text-xs font-theme-data rounded transition-colors ${
                filter === f
                  ? 'bg-[var(--acid-green)]/20 border border-[var(--acid-green)]/40 text-[var(--acid-green)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* List */}
      {filteredDiscrepancies.length === 0 ? (
        <div className="p-8 text-center">
          <div className="text-3xl mb-2">✅</div>
          <p className="text-sm text-[var(--text-muted)]">
            {filter === 'pending' ? 'No pending discrepancies' : 'No discrepancies found'}
          </p>
        </div>
      ) : (
        <div className="divide-y divide-[var(--border)]">
          {filteredDiscrepancies.map((disc) => {
            const typeInfo = TYPE_LABELS[disc.type];
            const isSelected = selectedId === disc.id;

            return (
              <div key={disc.id}>
                {/* Summary Row */}
                <div
                  onClick={() => setSelectedId(isSelected ? null : disc.id)}
                  className={`p-4 cursor-pointer hover:bg-[var(--bg)] transition-colors ${
                    isSelected ? 'bg-[var(--bg)]' : ''
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-xl">{typeInfo.icon}</span>
                      <div>
                        <div className={`text-sm font-theme-data ${typeInfo.color}`}>
                          {typeInfo.label}
                        </div>
                        <div className="text-xs text-[var(--text-muted)]">
                          {disc.bankTransaction?.description || disc.bookTransaction?.description}
                        </div>
                      </div>
                    </div>
                    <div className="flex items-center gap-4">
                      {disc.difference !== undefined && (
                        <div className="text-right">
                          <div className="text-xs text-[var(--text-muted)]">Difference</div>
                          <div className="text-sm font-theme-data text-yellow-400">
                            ${Math.abs(disc.difference).toFixed(2)}
                          </div>
                        </div>
                      )}
                      <div>
                        {disc.status === 'pending' && (
                          <span className="px-2 py-1 text-xs font-theme-data bg-yellow-500/10 border border-yellow-500/30 rounded text-yellow-400">
                            Pending
                          </span>
                        )}
                        {disc.status === 'investigating' && (
                          <span className="px-2 py-1 text-xs font-theme-data bg-blue-500/10 border border-blue-500/30 rounded text-blue-400">
                            Investigating
                          </span>
                        )}
                        {disc.status === 'resolved' && (
                          <span className="px-2 py-1 text-xs font-theme-data bg-green-500/10 border border-green-500/30 rounded text-green-400">
                            Resolved
                          </span>
                        )}
                        {disc.status === 'rejected' && (
                          <span className="px-2 py-1 text-xs font-theme-data bg-red-500/10 border border-red-500/30 rounded text-red-400">
                            Rejected
                          </span>
                        )}
                      </div>
                      <span className="text-[var(--text-muted)]">{isSelected ? '▲' : '▼'}</span>
                    </div>
                  </div>
                </div>

                {/* Expanded Details */}
                {isSelected && (
                  <div className="px-4 pb-4 bg-[var(--bg)]">
                    <div className="grid grid-cols-2 gap-4 mb-4">
                      {/* Bank Transaction */}
                      {disc.bankTransaction && (
                        <div className="p-3 bg-[var(--surface)] rounded border border-[var(--border)]">
                          <div className="text-xs text-[var(--text-muted)] mb-2">
                            Bank Transaction
                          </div>
                          <div className="text-sm font-theme-data">
                            {disc.bankTransaction.description}
                          </div>
                          <div className="flex justify-between mt-2">
                            <span className="text-xs text-[var(--text-muted)]">
                              {disc.bankTransaction.date}
                            </span>
                            <span
                              className={`text-sm font-theme-data ${
                                disc.bankTransaction.amount >= 0 ? 'text-green-400' : 'text-red-400'
                              }`}
                            >
                              ${Math.abs(disc.bankTransaction.amount).toFixed(2)}
                            </span>
                          </div>
                        </div>
                      )}

                      {/* Book Transaction */}
                      {disc.bookTransaction && (
                        <div className="p-3 bg-[var(--surface)] rounded border border-[var(--border)]">
                          <div className="text-xs text-[var(--text-muted)] mb-2">
                            Book Transaction
                          </div>
                          <div className="text-sm font-theme-data">
                            {disc.bookTransaction.description}
                          </div>
                          <div className="flex justify-between mt-2">
                            <span className="text-xs text-[var(--text-muted)]">
                              {disc.bookTransaction.date}
                            </span>
                            <span
                              className={`text-sm font-theme-data ${
                                disc.bookTransaction.amount >= 0 ? 'text-green-400' : 'text-red-400'
                              }`}
                            >
                              ${Math.abs(disc.bookTransaction.amount).toFixed(2)}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>

                    {/* AI Suggestion */}
                    {disc.aiSuggestion && (
                      <div className="p-3 bg-[var(--acid-green)]/5 border border-[var(--acid-green)]/20 rounded mb-4">
                        <div className="flex items-start gap-3">
                          <span className="text-xl">🤖</span>
                          <div className="flex-1">
                            <div className="flex items-center justify-between">
                              <span className="text-sm font-theme-data text-[var(--acid-green)]">
                                AI Suggestion
                              </span>
                              {disc.aiConfidence && (
                                <span className="text-xs text-[var(--text-muted)]">
                                  {(disc.aiConfidence * 100).toFixed(0)}% confidence
                                </span>
                              )}
                            </div>
                            <p className="text-xs text-[var(--text-muted)] mt-1">
                              {disc.aiSuggestion}
                            </p>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Resolution Info */}
                    {disc.resolution && (
                      <div className="p-3 bg-green-500/5 border border-green-500/20 rounded mb-4">
                        <div className="text-xs text-green-400">
                          Resolved by {disc.resolvedBy} on{' '}
                          {disc.resolvedAt && new Date(disc.resolvedAt).toLocaleString()}
                        </div>
                        <p className="text-xs text-[var(--text-muted)] mt-1">{disc.resolution}</p>
                      </div>
                    )}

                    {/* Actions */}
                    {(disc.status === 'pending' || disc.status === 'investigating') && (
                      <div className="flex items-center gap-3">
                        {disc.status === 'pending' && (
                          <button
                            onClick={() => handleInvestigate(disc.id)}
                            disabled={investigating === disc.id}
                            className="px-4 py-2 text-xs font-theme-data bg-blue-500/10 border border-blue-500/30 text-blue-400 rounded hover:bg-blue-500/20 transition-colors disabled:opacity-50"
                          >
                            {investigating === disc.id ? 'Analyzing...' : 'Investigate with AI'}
                          </button>
                        )}
                        <button
                          onClick={() => handleResolve(disc.id, 'accept')}
                          className="px-4 py-2 text-xs font-theme-data bg-green-500/10 border border-green-500/30 text-green-400 rounded hover:bg-green-500/20 transition-colors"
                        >
                          Accept Suggestion
                        </button>
                        <button
                          onClick={() => handleResolve(disc.id, 'reject')}
                          className="px-4 py-2 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] rounded hover:bg-[var(--surface)] transition-colors"
                        >
                          Reject
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
