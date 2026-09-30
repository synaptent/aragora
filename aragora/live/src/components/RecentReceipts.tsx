'use client';

import { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { apiFetch } from '@/lib/api';
import { DebateThisButton } from './DebateThisButton';

interface ReceiptSummary {
  receipt_id: string;
  gauntlet_id?: string;
  timestamp?: string;
  input_summary?: string;
  verdict: string;
  findings_count: number;
  confidence?: number;
}

interface RecentReceiptsProps {
  limit?: number;
}

const VERDICT_STYLES: Record<string, string> = {
  PASS: 'text-[var(--acid-green)] border-[var(--acid-green)]/30 bg-[var(--acid-green)]/10',
  FAIL: 'text-red-400 border-red-400/30 bg-red-400/10',
  WARN: 'text-[var(--acid-yellow)] border-[var(--acid-yellow)]/30 bg-[var(--acid-yellow)]/10',
  CONDITIONAL:
    'text-[var(--acid-yellow)] border-[var(--acid-yellow)]/30 bg-[var(--acid-yellow)]/10',
};

function normalizeVerdict(verdict: string): 'PASS' | 'FAIL' | 'WARN' | 'CONDITIONAL' {
  switch (verdict.toUpperCase()) {
    case 'PASS':
    case 'APPROVED':
      return 'PASS';
    case 'FAIL':
    case 'REJECTED':
      return 'FAIL';
    case 'CONDITIONAL':
    case 'WARNING':
    case 'WARN':
      return 'CONDITIONAL';
    default:
      return 'WARN';
  }
}

export function RecentReceipts({ limit = 5 }: RecentReceiptsProps) {
  const [receipts, setReceipts] = useState<ReceiptSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchReceipts = useCallback(async () => {
    try {
      const data = await apiFetch<{ receipts: ReceiptSummary[] }>(
        `/api/v2/receipts?limit=${limit}`,
      );
      setReceipts(data.receipts || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load receipts');
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    fetchReceipts();
  }, [fetchReceipts]);

  if (loading) {
    return (
      <div className="border border-[var(--border)] p-4">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[var(--acid-green)] font-theme-data text-sm font-bold">
            RECENT RECEIPTS
          </span>
          <span className="text-[var(--text-muted)] font-theme-data text-xs animate-pulse">
            loading...
          </span>
        </div>
      </div>
    );
  }

  if (error || receipts.length === 0) {
    return (
      <div className="border border-[var(--border)] p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[var(--acid-green)] font-theme-data text-sm font-bold">
            DECISION RECEIPTS
          </span>
          <Link
            href="/receipts"
            className="text-[var(--acid-cyan)] font-theme-data text-xs hover:text-[var(--acid-green)]"
          >
            [VIEW ALL]
          </Link>
        </div>
        <p className="text-[var(--text-muted)] font-theme-data text-xs">
          {error
            ? 'Could not load receipts.'
            : 'No decision receipts yet. Run a debate to generate your first receipt.'}
        </p>
      </div>
    );
  }

  return (
    <div className="border border-[var(--border)] p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-[var(--acid-green)] font-theme-data text-sm font-bold">
          DECISION RECEIPTS
        </span>
        <Link
          href="/receipts"
          className="text-[var(--acid-cyan)] font-theme-data text-xs hover:text-[var(--acid-green)]"
        >
          [VIEW ALL]
        </Link>
      </div>

      <div className="space-y-2">
        {receipts.map((receipt) => (
          <Link
            key={receipt.receipt_id}
            href={`/receipts?id=${receipt.receipt_id}`}
            className="block border border-[var(--border)] p-3 hover:border-[var(--acid-green)]/40 transition-colors"
          >
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2 min-w-0">
                <span
                  className={`px-1.5 py-0.5 text-[10px] font-theme-data font-bold border ${VERDICT_STYLES[normalizeVerdict(receipt.verdict)] || VERDICT_STYLES.WARN}`}
                >
                  {normalizeVerdict(receipt.verdict)}
                </span>
                <span className="text-xs font-theme-data text-[var(--text)] truncate">
                  {receipt.input_summary || `Receipt ${receipt.receipt_id.slice(0, 8)}`}
                </span>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {receipt.confidence !== undefined && (
                  <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    {(receipt.confidence * 100).toFixed(0)}%
                  </span>
                )}
                <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                  {receipt.timestamp ? new Date(receipt.timestamp).toLocaleDateString() : 'Unknown'}
                </span>
                <DebateThisButton
                  question={
                    receipt.input_summary || `Re-examine receipt ${receipt.receipt_id.slice(0, 8)}`
                  }
                  source="receipt"
                  variant="icon"
                />
              </div>
            </div>
            {receipt.findings_count > 0 && (
              <div className="mt-1 text-[10px] font-theme-data text-[var(--text-muted)]">
                {receipt.findings_count} finding{receipt.findings_count !== 1 ? 's' : ''}
              </div>
            )}
          </Link>
        ))}
      </div>

      <div className="mt-3 pt-2 border-t border-[var(--border)] flex items-center justify-between">
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
          SHA-256 verified audit trail
        </span>
        <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
          {receipts.length} receipt{receipts.length !== 1 ? 's' : ''}
        </span>
      </div>
    </div>
  );
}
