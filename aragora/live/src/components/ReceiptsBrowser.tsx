'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/lib/api';

interface Finding {
  id: string;
  category: string;
  severity: string;
  description: string;
}

interface Receipt {
  id: string;
  run_id: string;
  verdict: 'PASS' | 'FAIL' | 'WARN';
  created_at: string;
  artifact_hash: string;
  findings_count: number;
  findings_by_severity: { critical: number; high: number; medium: number; low: number };
  findings: Finding[];
  metadata?: Record<string, unknown>;
}

interface ReceiptsBrowserProps {
  runId?: string;
}

export function ReceiptsBrowser({ runId }: ReceiptsBrowserProps) {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedReceipt, setSelectedReceipt] = useState<Receipt | null>(null);
  const [verifyingId, setVerifyingId] = useState<string | null>(null);
  const [verifyResult, setVerifyResult] = useState<{ valid: boolean; message: string } | null>(
    null,
  );
  const [verdictFilter, setVerdictFilter] = useState<string | null>(null);

  const fetchReceipts = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams();
      if (runId) params.set('run_id', runId);
      if (verdictFilter) params.set('verdict', verdictFilter);

      const data = await apiFetch<{ receipts: Receipt[] }>(
        `/api/gauntlet/receipts?${params.toString()}`,
      );
      setReceipts(data.receipts || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch receipts');
    } finally {
      setLoading(false);
    }
  }, [runId, verdictFilter]);

  useEffect(() => {
    fetchReceipts();
  }, [fetchReceipts]);

  const handleVerify = async (receiptId: string) => {
    setVerifyingId(receiptId);
    setVerifyResult(null);

    try {
      const result = await apiFetch<{ valid: boolean; message: string }>(
        `/api/gauntlet/receipts/${receiptId}/verify`,
        { method: 'POST' },
      );
      setVerifyResult({ valid: result.valid, message: result.message });
    } catch (err) {
      setVerifyResult({
        valid: false,
        message: err instanceof Error ? err.message : 'Verification failed',
      });
    } finally {
      setVerifyingId(null);
    }
  };

  const handleExport = async (receiptId: string, format: 'json' | 'html') => {
    try {
      const data = await apiFetch<{ html?: string }>(
        `/api/gauntlet/receipts/${receiptId}/export?format=${format}`,
      );

      // Create blob and download
      const blob = new Blob([format === 'json' ? JSON.stringify(data, null, 2) : data.html || ''], {
        type: format === 'json' ? 'application/json' : 'text/html',
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `receipt-${receiptId}.${format}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      alert(`Export failed: ${err instanceof Error ? err.message : 'Unknown error'}`);
    }
  };

  const getVerdictColor = (verdict: string) => {
    switch (verdict) {
      case 'PASS':
        return 'text-green-400 bg-green-400/20';
      case 'FAIL':
        return 'text-red-400 bg-red-400/20';
      case 'WARN':
        return 'text-yellow-400 bg-yellow-400/20';
      default:
        return 'text-text-muted bg-surface';
    }
  };

  const getSeverityColor = (severity: string) => {
    switch (severity.toLowerCase()) {
      case 'critical':
        return 'text-red-500';
      case 'high':
        return 'text-red-400';
      case 'medium':
        return 'text-yellow-400';
      case 'low':
        return 'text-blue-400';
      default:
        return 'text-text-muted';
    }
  };

  if (loading) {
    return (
      <div className="card p-6">
        <div className="text-center text-text-muted font-theme-data">
          <span className="animate-pulse">Loading receipts...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-6">
        <div className="text-center text-red-400 font-theme-data">
          <p>Error: {error}</p>
          <button
            onClick={fetchReceipts}
            className="mt-4 px-4 py-2 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10"
          >
            [RETRY]
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="font-theme-data text-[var(--accent)] text-xl">{'>'} DECISION RECEIPTS</h2>
        <div className="text-xs font-theme-data text-text-muted">{receipts.length} receipts</div>
      </div>

      {/* Filters */}
      <div className="flex gap-2">
        {['ALL', 'PASS', 'FAIL', 'WARN'].map((verdict) => (
          <button
            key={verdict}
            onClick={() => setVerdictFilter(verdict === 'ALL' ? null : verdict)}
            className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
              (verdict === 'ALL' && !verdictFilter) || verdictFilter === verdict
                ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                : 'border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)]/60'
            }`}
          >
            [{verdict}]
          </button>
        ))}
      </div>

      {/* Receipts List */}
      <div className="space-y-4">
        {receipts.map((receipt) => (
          <div
            key={receipt.id}
            className="card p-4 hover:border-[var(--accent)]/60 transition-colors cursor-pointer"
            onClick={() => setSelectedReceipt(receipt)}
          >
            <div className="flex items-start justify-between">
              <div className="flex-1">
                <div className="flex items-center gap-3 mb-2">
                  <span
                    className={`px-2 py-0.5 text-xs font-theme-data ${getVerdictColor(receipt.verdict)}`}
                  >
                    {receipt.verdict}
                  </span>
                  <span className="font-theme-data text-sm text-text-muted">
                    {receipt.id.slice(0, 8)}...
                  </span>
                </div>

                {/* Findings Summary */}
                <div className="flex gap-4 text-xs font-theme-data">
                  {receipt.findings_by_severity.critical > 0 && (
                    <span className="text-red-500">
                      {receipt.findings_by_severity.critical} critical
                    </span>
                  )}
                  {receipt.findings_by_severity.high > 0 && (
                    <span className="text-red-400">{receipt.findings_by_severity.high} high</span>
                  )}
                  {receipt.findings_by_severity.medium > 0 && (
                    <span className="text-yellow-400">
                      {receipt.findings_by_severity.medium} medium
                    </span>
                  )}
                  {receipt.findings_by_severity.low > 0 && (
                    <span className="text-blue-400">{receipt.findings_by_severity.low} low</span>
                  )}
                  {receipt.findings_count === 0 && (
                    <span className="text-green-400">No findings</span>
                  )}
                </div>
              </div>

              <div className="text-xs font-theme-data text-text-muted text-right">
                <div>{new Date(receipt.created_at).toLocaleDateString()}</div>
                <div>{new Date(receipt.created_at).toLocaleTimeString()}</div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {receipts.length === 0 && (
        <div className="text-center py-12">
          <p className="text-text-muted font-theme-data">No receipts found.</p>
        </div>
      )}

      {/* Receipt Detail Modal */}
      {selectedReceipt && (
        <div className="fixed inset-0 z-[100] bg-bg/95 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="max-w-3xl w-full border border-[var(--accent)]/50 bg-surface p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-start mb-6">
              <div>
                <span
                  className={`px-2 py-0.5 text-xs font-theme-data ${getVerdictColor(selectedReceipt.verdict)}`}
                >
                  {selectedReceipt.verdict}
                </span>
                <h2 className="text-lg font-theme-data text-[var(--accent)] mt-2">
                  Receipt: {selectedReceipt.id.slice(0, 16)}...
                </h2>
              </div>
              <button
                onClick={() => {
                  setSelectedReceipt(null);
                  setVerifyResult(null);
                }}
                className="text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [X]
              </button>
            </div>

            {/* Artifact Hash */}
            <div className="p-4 bg-bg border border-[var(--accent)]/20 mb-6">
              <div className="text-xs font-theme-data text-text-muted mb-1">
                ARTIFACT HASH (SHA-256)
              </div>
              <code className="font-theme-data text-xs text-[var(--acid-cyan)] break-all">
                {selectedReceipt.artifact_hash}
              </code>
            </div>

            {/* Verify Button */}
            <div className="mb-6">
              <button
                onClick={() => handleVerify(selectedReceipt.id)}
                disabled={verifyingId === selectedReceipt.id}
                className="px-4 py-2 text-sm font-theme-data border border-[var(--acid-cyan)] text-[var(--acid-cyan)]
                         hover:bg-[var(--acid-cyan)]/10 disabled:opacity-50 transition-colors"
              >
                {verifyingId === selectedReceipt.id ? '[VERIFYING...]' : '[VERIFY INTEGRITY]'}
              </button>
              {verifyResult && (
                <div
                  className={`mt-2 text-sm font-theme-data ${verifyResult.valid ? 'text-green-400' : 'text-red-400'}`}
                >
                  {verifyResult.valid ? '✓' : '✗'} {verifyResult.message}
                </div>
              )}
            </div>

            {/* Findings */}
            <div className="mb-6">
              <h3 className="text-sm font-theme-data text-text-muted mb-4">
                FINDINGS ({selectedReceipt.findings_count})
              </h3>
              <div className="space-y-3">
                {selectedReceipt.findings.map((finding) => (
                  <div key={finding.id} className="border border-[var(--accent)]/20 p-3">
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className={`text-xs font-theme-data ${getSeverityColor(finding.severity)}`}
                      >
                        [{finding.severity.toUpperCase()}]
                      </span>
                      <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                        {finding.category}
                      </span>
                    </div>
                    <p className="text-sm font-theme-data text-text">{finding.description}</p>
                  </div>
                ))}
                {selectedReceipt.findings.length === 0 && (
                  <p className="text-sm font-theme-data text-text-muted">
                    No findings in this receipt.
                  </p>
                )}
              </div>
            </div>

            {/* Export Actions */}
            <div className="flex gap-3">
              <button
                onClick={() => handleExport(selectedReceipt.id, 'json')}
                className="px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/30
                         text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
              >
                [EXPORT JSON]
              </button>
              <button
                onClick={() => handleExport(selectedReceipt.id, 'html')}
                className="px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/30
                         text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
              >
                [EXPORT HTML]
              </button>
              <button
                onClick={() => {
                  setSelectedReceipt(null);
                  setVerifyResult(null);
                }}
                className="ml-auto px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/30
                         text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
              >
                [CLOSE]
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default ReceiptsBrowser;
