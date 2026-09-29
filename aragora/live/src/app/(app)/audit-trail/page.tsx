'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { useSWRFetch } from '@/hooks/useSWRFetch';
import { apiPost } from '@/lib/api';

// ---------------------------------------------------------------------------
// Types matching backend audit_trail.py response shapes
// ---------------------------------------------------------------------------

interface AuditTrailSummary {
  trail_id: string;
  gauntlet_id: string | null;
  created_at: string;
  verdict: string | null;
  confidence: number | null;
  total_findings: number | null;
  duration_seconds: number | null;
  checksum: string | null;
}

interface AuditTrailsResponse {
  trails: AuditTrailSummary[];
  total: number;
  limit: number;
  offset: number;
}

interface ReceiptSummary {
  receipt_id: string;
  gauntlet_id: string | null;
  timestamp: string;
  verdict: string | null;
  confidence: number | null;
  risk_level: string | null;
  findings_count: number | null;
  checksum: string | null;
}

interface ReceiptsResponse {
  receipts: ReceiptSummary[];
  total: number;
  limit: number;
  offset: number;
}

interface VerifyResult {
  trail_id?: string;
  receipt_id?: string;
  valid: boolean;
  stored_checksum: string;
  computed_checksum: string;
  match: boolean;
  error?: string;
  request_failed?: boolean;
}

type VerifyResultState = 'valid' | 'invalid' | 'error' | 'unavailable';

const VERIFY_RESULT_STYLES: Record<VerifyResultState, string> = {
  valid: 'bg-[var(--acid-green)]/5 border-[var(--acid-green)]/30 text-[var(--acid-green)]',
  invalid: 'bg-red-500/5 border-red-500/30 text-red-400',
  error: 'bg-red-500/5 border-red-500/30 text-red-400',
  unavailable: 'bg-yellow-500/5 border-yellow-500/30 text-yellow-300',
};

const VERIFY_RESULT_LABELS: Record<VerifyResultState, string> = {
  valid: '[VALID]',
  invalid: '[INVALID]',
  error: '[ERROR]',
  unavailable: '[UNAVAILABLE]',
};

function getVerifyResultState(result: VerifyResult): VerifyResultState {
  if (result.request_failed) {
    return 'unavailable';
  }
  if (!result.valid && result.error && !result.stored_checksum && !result.computed_checksum) {
    return 'error';
  }
  return result.valid ? 'valid' : 'invalid';
}

function getVerifyErrorMessage(error: unknown): { message: string; requestFailed: boolean } {
  if (error instanceof Error && error.message) {
    const apiErrorMatch = error.message.match(/^API Error \((\d+)\):\s*([\s\S]*)$/);
    if (apiErrorMatch) {
      const [, , rawPayload] = apiErrorMatch;
      const trimmedPayload = rawPayload.trim();
      if (!trimmedPayload) {
        return { message: error.message, requestFailed: false };
      }
      try {
        const parsed = JSON.parse(trimmedPayload) as { error?: unknown };
        if (typeof parsed.error === 'string' && parsed.error.trim()) {
          return { message: parsed.error, requestFailed: false };
        }
      } catch {
        // Fall back to the raw response body when it is not JSON.
      }
      return { message: trimmedPayload, requestFailed: false };
    }

    return { message: error.message, requestFailed: true };
  }

  return { message: 'Verification failed. Please retry.', requestFailed: true };
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function VerdictBadge({ verdict }: { verdict: string | null }) {
  if (!verdict) return <span className="text-[var(--text-muted)] text-xs font-theme-data">--</span>;

  const colors: Record<string, string> = {
    approved: 'text-[var(--acid-green)] bg-[var(--acid-green)]/10 border-[var(--acid-green)]/30',
    rejected: 'text-red-400 bg-red-500/10 border-red-500/30',
    conditional: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
    inconclusive: 'text-[var(--text-muted)] bg-[var(--surface)] border-[var(--border)]',
  };

  const style = colors[verdict.toLowerCase()] || colors.inconclusive;

  return (
    <span className={`px-2 py-0.5 text-[10px] font-theme-data uppercase rounded border ${style}`}>
      {verdict}
    </span>
  );
}

function RiskBadge({ level }: { level: string | null }) {
  if (!level) return null;

  const colors: Record<string, string> = {
    high: 'text-red-400 bg-red-500/10',
    medium: 'text-yellow-400 bg-yellow-500/10',
    low: 'text-[var(--acid-green)] bg-[var(--acid-green)]/10',
  };

  return (
    <span
      className={`px-1.5 py-0.5 text-[10px] font-theme-data rounded ${colors[level.toLowerCase()] || 'text-[var(--text-muted)] bg-[var(--surface)]'}`}
    >
      {level.toUpperCase()}
    </span>
  );
}

function ConfidenceBar({ value }: { value: number | null }) {
  if (value == null)
    return <span className="text-[var(--text-muted)] text-xs font-theme-data">--</span>;

  const pct = Math.round(value * 100);
  const color = pct >= 80 ? 'bg-[var(--acid-green)]' : pct >= 50 ? 'bg-yellow-400' : 'bg-red-400';

  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-[var(--bg)] rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-theme-data text-[var(--text-muted)]">{pct}%</span>
    </div>
  );
}

function ChecksumDisplay({ checksum }: { checksum: string | null }) {
  if (!checksum)
    return <span className="text-[var(--text-muted)] text-xs font-theme-data">--</span>;
  return (
    <span className="text-[10px] font-theme-data text-purple-400" title={checksum}>
      {checksum.substring(0, 12)}...
    </span>
  );
}

function formatTimestamp(ts: string | null): string {
  if (!ts) return '--';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

// ---------------------------------------------------------------------------
// Page Component
// ---------------------------------------------------------------------------

type ActiveTab = 'trails' | 'receipts';

export default function AuditTrailPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('trails');
  const [trailOffset, setTrailOffset] = useState(0);
  const [receiptOffset, setReceiptOffset] = useState(0);
  const [verdictFilter, setVerdictFilter] = useState('');
  const [verifying, setVerifying] = useState<string | null>(null);
  const [verifyResult, setVerifyResult] = useState<VerifyResult | null>(null);

  const PAGE_SIZE = 20;

  // Fetch audit trails
  const trailParams = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(trailOffset),
    ...(verdictFilter ? { verdict: verdictFilter } : {}),
  });

  const {
    data: trailsData,
    isLoading: trailsLoading,
    error: trailsError,
  } = useSWRFetch<AuditTrailsResponse>(
    activeTab === 'trails' ? `/api/v1/audit-trails?${trailParams}` : null,
    { refreshInterval: 30000 },
  );

  // Fetch receipts
  const receiptParams = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(receiptOffset),
  });

  const {
    data: receiptsData,
    isLoading: receiptsLoading,
    error: receiptsError,
  } = useSWRFetch<ReceiptsResponse>(
    activeTab === 'receipts' ? `/api/v1/receipts?${receiptParams}` : null,
    { refreshInterval: 30000 },
  );

  const trails = trailsData?.trails ?? [];
  const trailsTotal = trailsData?.total ?? 0;
  const receipts = receiptsData?.receipts ?? [];
  const receiptsTotal = receiptsData?.total ?? 0;

  // Verify integrity
  const handleVerify = useCallback(async (type: 'trail' | 'receipt', id: string) => {
    setVerifying(id);
    setVerifyResult(null);
    try {
      const endpoint =
        type === 'trail' ? `/api/v1/audit-trails/${id}/verify` : `/api/v1/receipts/${id}/verify`;
      const data = await apiPost<VerifyResult>(endpoint);
      setVerifyResult(data);
    } catch (error) {
      const { message, requestFailed } = getVerifyErrorMessage(error);
      const failureResult: VerifyResult = {
        valid: false,
        request_failed: requestFailed,
        stored_checksum: '',
        computed_checksum: '',
        match: false,
        error: message,
      };
      if (type === 'trail') {
        failureResult.trail_id = id;
      } else {
        failureResult.receipt_id = id;
      }
      setVerifyResult(failureResult);
    } finally {
      setVerifying(null);
    }
  }, []);

  const isLoading = activeTab === 'trails' ? trailsLoading : receiptsLoading;
  const error = activeTab === 'trails' ? trailsError : receiptsError;
  const verifyState = verifyResult ? getVerifyResultState(verifyResult) : null;
  const showChecksumComparison = Boolean(
    verifyResult && (verifyResult.stored_checksum || verifyResult.computed_checksum),
  );

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6">
          {/* Header */}
          <div className="mb-6">
            <div className="flex items-center gap-2 mb-2">
              <Link
                href="/audit"
                className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                Audit
              </Link>
              <span className="text-[var(--text-muted)]">/</span>
              <span className="text-xs font-theme-data text-[var(--acid-green)]">Trail</span>
            </div>
            <h1 className="text-xl font-theme-data text-[var(--acid-green)]">
              {'>'} AUDIT TRAIL & DECISION RECEIPTS
            </h1>
            <p className="text-xs text-[var(--text-muted)] font-theme-data mt-1">
              Cryptographically verified audit trails and decision receipts. Full provenance for
              compliance documentation with SHA-256 integrity checks.
            </p>
          </div>

          {/* Tabs */}
          <div className="flex gap-2 mb-6">
            {[
              { key: 'trails' as const, label: 'AUDIT TRAILS' },
              { key: 'receipts' as const, label: 'DECISION RECEIPTS' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => {
                  setActiveTab(key);
                  setVerifyResult(null);
                }}
                className={`px-4 py-2 font-theme-data text-sm border transition-colors ${
                  activeTab === key
                    ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10 text-[var(--acid-green)]'
                    : 'border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--text)]'
                }`}
              >
                [{label}]
              </button>
            ))}
          </div>

          {/* Error State */}
          {error && (
            <div className="mb-6 p-4 bg-red-500/10 border border-red-500/30 text-red-400 font-theme-data text-sm">
              Failed to load data. The server may be unreachable.
            </div>
          )}

          {/* Verification Result */}
          {verifyResult && (
            <div
              className={`mb-6 p-4 border font-theme-data text-sm ${VERIFY_RESULT_STYLES[verifyState!]}`}
            >
              <div className="flex items-center gap-3 mb-2">
                <span className="text-lg">{VERIFY_RESULT_LABELS[verifyState!]}</span>
                <span className="text-xs text-[var(--text-muted)]">
                  {verifyResult.trail_id || verifyResult.receipt_id}
                </span>
              </div>
              {showChecksumComparison && (
                <div className="grid grid-cols-2 gap-2 text-xs">
                  <div>
                    <span className="text-[var(--text-muted)]">Stored: </span>
                    <span className="text-purple-400">{verifyResult.stored_checksum || '--'}</span>
                  </div>
                  <div>
                    <span className="text-[var(--text-muted)]">Computed: </span>
                    <span className="text-purple-400">
                      {verifyResult.computed_checksum || '--'}
                    </span>
                  </div>
                </div>
              )}
              {verifyResult.request_failed && (
                <div className="mt-2 text-xs text-[var(--text-muted)]">
                  Verification could not reach the backend, so no checksum comparison was performed.
                </div>
              )}
              {verifyResult.error && (
                <div
                  className={`mt-2 text-xs ${verifyResult.request_failed ? 'text-yellow-200' : 'text-red-400'}`}
                >
                  {verifyResult.error}
                </div>
              )}
              <button
                onClick={() => setVerifyResult(null)}
                className="mt-2 text-xs text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
              >
                [DISMISS]
              </button>
            </div>
          )}

          <PanelErrorBoundary panelName="Audit Trail">
            {/* Audit Trails Tab */}
            {activeTab === 'trails' && (
              <div>
                {/* Filter */}
                <div className="flex items-center gap-3 mb-4">
                  <select
                    value={verdictFilter}
                    onChange={(e) => {
                      setVerdictFilter(e.target.value);
                      setTrailOffset(0);
                    }}
                    className="px-3 py-1.5 bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] text-xs font-theme-data rounded focus:outline-none focus:border-[var(--acid-green)]/50"
                  >
                    <option value="">All Verdicts</option>
                    <option value="approved">Approved</option>
                    <option value="rejected">Rejected</option>
                    <option value="conditional">Conditional</option>
                    <option value="inconclusive">Inconclusive</option>
                  </select>
                  <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    {trailsTotal} trail{trailsTotal !== 1 ? 's' : ''} total
                  </span>
                </div>

                {/* Table */}
                <div className="bg-[var(--surface)] border border-[var(--border)] overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-[10px] font-theme-data text-[var(--text-muted)] uppercase border-b border-[var(--border)]">
                          <th className="px-4 py-3">Trail ID</th>
                          <th className="px-4 py-3">Created</th>
                          <th className="px-4 py-3">Verdict</th>
                          <th className="px-4 py-3">Confidence</th>
                          <th className="px-4 py-3">Findings</th>
                          <th className="px-4 py-3">Duration</th>
                          <th className="px-4 py-3">Checksum</th>
                          <th className="px-4 py-3">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {isLoading ? (
                          <tr>
                            <td
                              colSpan={8}
                              className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data animate-pulse"
                            >
                              Loading audit trails...
                            </td>
                          </tr>
                        ) : trails.length === 0 ? (
                          <tr>
                            <td
                              colSpan={8}
                              className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data"
                            >
                              No audit trails found. Run a Gauntlet to generate trails.
                            </td>
                          </tr>
                        ) : (
                          trails.map((trail) => (
                            <tr
                              key={trail.trail_id}
                              className="border-b border-[var(--border)]/50 hover:bg-[var(--acid-green)]/5 transition-colors"
                            >
                              <td className="px-4 py-3">
                                <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                                  {trail.trail_id.substring(0, 20)}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-xs font-theme-data text-[var(--text-muted)]">
                                {formatTimestamp(trail.created_at)}
                              </td>
                              <td className="px-4 py-3">
                                <VerdictBadge verdict={trail.verdict} />
                              </td>
                              <td className="px-4 py-3">
                                <ConfidenceBar value={trail.confidence} />
                              </td>
                              <td className="px-4 py-3 font-theme-data text-xs text-[var(--text)]">
                                {trail.total_findings ?? '--'}
                              </td>
                              <td className="px-4 py-3 text-xs font-theme-data text-[var(--text-muted)]">
                                {trail.duration_seconds != null
                                  ? `${trail.duration_seconds.toFixed(1)}s`
                                  : '--'}
                              </td>
                              <td className="px-4 py-3">
                                <ChecksumDisplay checksum={trail.checksum} />
                              </td>
                              <td className="px-4 py-3">
                                <button
                                  onClick={() => handleVerify('trail', trail.trail_id)}
                                  disabled={verifying === trail.trail_id}
                                  className="px-2 py-1 text-[10px] font-theme-data text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/10 transition-colors disabled:opacity-50"
                                >
                                  {verifying === trail.trail_id ? 'VERIFYING...' : 'VERIFY'}
                                </button>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Pagination */}
                {trailsTotal > PAGE_SIZE && (
                  <div className="flex items-center justify-between mt-4">
                    <button
                      onClick={() => setTrailOffset(Math.max(0, trailOffset - PAGE_SIZE))}
                      disabled={trailOffset === 0}
                      className="px-3 py-1.5 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 disabled:opacity-30 transition-colors"
                    >
                      PREV
                    </button>
                    <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                      {trailOffset + 1}-{Math.min(trailOffset + PAGE_SIZE, trailsTotal)} of{' '}
                      {trailsTotal}
                    </span>
                    <button
                      onClick={() => setTrailOffset(trailOffset + PAGE_SIZE)}
                      disabled={trailOffset + PAGE_SIZE >= trailsTotal}
                      className="px-3 py-1.5 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 disabled:opacity-30 transition-colors"
                    >
                      NEXT
                    </button>
                  </div>
                )}
              </div>
            )}

            {/* Decision Receipts Tab */}
            {activeTab === 'receipts' && (
              <div>
                <div className="flex items-center gap-3 mb-4">
                  <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    {receiptsTotal} receipt{receiptsTotal !== 1 ? 's' : ''} total
                  </span>
                </div>

                <div className="bg-[var(--surface)] border border-[var(--border)] overflow-hidden">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-[10px] font-theme-data text-[var(--text-muted)] uppercase border-b border-[var(--border)]">
                          <th className="px-4 py-3">Receipt ID</th>
                          <th className="px-4 py-3">Timestamp</th>
                          <th className="px-4 py-3">Verdict</th>
                          <th className="px-4 py-3">Confidence</th>
                          <th className="px-4 py-3">Risk</th>
                          <th className="px-4 py-3">Findings</th>
                          <th className="px-4 py-3">Checksum</th>
                          <th className="px-4 py-3">Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {receiptsLoading ? (
                          <tr>
                            <td
                              colSpan={8}
                              className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data animate-pulse"
                            >
                              Loading receipts...
                            </td>
                          </tr>
                        ) : receipts.length === 0 ? (
                          <tr>
                            <td
                              colSpan={8}
                              className="px-4 py-12 text-center text-[var(--text-muted)] font-theme-data"
                            >
                              No decision receipts found. Run a Gauntlet to generate receipts.
                            </td>
                          </tr>
                        ) : (
                          receipts.map((receipt) => (
                            <tr
                              key={receipt.receipt_id}
                              className="border-b border-[var(--border)]/50 hover:bg-[var(--acid-green)]/5 transition-colors"
                            >
                              <td className="px-4 py-3">
                                <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                                  {receipt.receipt_id.substring(0, 20)}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-xs font-theme-data text-[var(--text-muted)]">
                                {formatTimestamp(receipt.timestamp)}
                              </td>
                              <td className="px-4 py-3">
                                <VerdictBadge verdict={receipt.verdict} />
                              </td>
                              <td className="px-4 py-3">
                                <ConfidenceBar value={receipt.confidence} />
                              </td>
                              <td className="px-4 py-3">
                                <RiskBadge level={receipt.risk_level} />
                              </td>
                              <td className="px-4 py-3 font-theme-data text-xs text-[var(--text)]">
                                {receipt.findings_count ?? '--'}
                              </td>
                              <td className="px-4 py-3">
                                <ChecksumDisplay checksum={receipt.checksum} />
                              </td>
                              <td className="px-4 py-3">
                                <button
                                  onClick={() => handleVerify('receipt', receipt.receipt_id)}
                                  disabled={verifying === receipt.receipt_id}
                                  className="px-2 py-1 text-[10px] font-theme-data text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/10 transition-colors disabled:opacity-50"
                                >
                                  {verifying === receipt.receipt_id ? 'VERIFYING...' : 'VERIFY'}
                                </button>
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                {/* Pagination */}
                {receiptsTotal > PAGE_SIZE && (
                  <div className="flex items-center justify-between mt-4">
                    <button
                      onClick={() => setReceiptOffset(Math.max(0, receiptOffset - PAGE_SIZE))}
                      disabled={receiptOffset === 0}
                      className="px-3 py-1.5 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 disabled:opacity-30 transition-colors"
                    >
                      PREV
                    </button>
                    <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
                      {receiptOffset + 1}-{Math.min(receiptOffset + PAGE_SIZE, receiptsTotal)} of{' '}
                      {receiptsTotal}
                    </span>
                    <button
                      onClick={() => setReceiptOffset(receiptOffset + PAGE_SIZE)}
                      disabled={receiptOffset + PAGE_SIZE >= receiptsTotal}
                      className="px-3 py-1.5 text-xs font-theme-data text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 disabled:opacity-30 transition-colors"
                    >
                      NEXT
                    </button>
                  </div>
                )}
              </div>
            )}
          </PanelErrorBoundary>

          {/* Quick Links */}
          <div className="mt-8 flex flex-wrap gap-3">
            <Link
              href="/audit"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Audit Dashboard
            </Link>
            <Link
              href="/gauntlet"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Run Gauntlet
            </Link>
            <Link
              href="/receipts"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Receipt Viewer
            </Link>
            <Link
              href="/compliance"
              className="px-3 py-2 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              Compliance
            </Link>
          </div>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--acid-green)]/20 mt-8">
          <div className="text-[var(--acid-green)]/50 mb-2" aria-hidden="true">
            {'='.repeat(40)}
          </div>
          <p className="text-[var(--text-muted)]">{'>'} ARAGORA // AUDIT TRAIL</p>
        </footer>
      </main>
    </>
  );
}
