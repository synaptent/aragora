'use client';

import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { ProofTreeVisualization } from './ProofTreeVisualization';

interface BackendConfig {
  apiUrl: string;
  wsUrl: string;
}

interface BackendStatus {
  language: string;
  available: boolean;
}

interface VerificationStatus {
  backends: BackendStatus[];
  any_available: boolean;
  deepseek_prover_available: boolean;
}

interface VerificationResult {
  status: string;
  language?: string;
  is_verified?: boolean;
  formal_statement?: string;
  proof_hash?: string;
  translation_time_ms?: number;
  proof_search_time_ms?: number;
  error_message?: string;
  prover_version?: string;
  history_id?: string;
}

interface HistoryEntry {
  id: string;
  claim: string;
  result: VerificationResult;
  timestamp: number;
  proof_tree?: Array<{ id: string; type: string; content: string; children: string[] }>;
}

interface BatchResult {
  results: VerificationResult[];
  status?: 'error' | 'success';
  error?: string;
  summary?: { total: number; verified: number; failed: number; timeout: number };
}

interface TranslationResult {
  success?: boolean;
  formal_statement?: string;
  language?: string;
  model_used?: string;
  confidence?: number;
  translation_time_ms?: number;
  error_message?: string;
  status?: 'error' | 'success';
  error?: string;
}

interface ProofVisualizerPanelProps {
  backendConfig?: BackendConfig;
  debateId?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

const STATUS_COLORS: Record<string, { text: string; bg: string }> = {
  proof_found: { text: 'text-[var(--accent)]', bg: 'bg-[var(--accent)]/20' },
  translation_failed: { text: 'text-acid-red', bg: 'bg-acid-red/20' },
  proof_failed: { text: 'text-[var(--acid-yellow)]', bg: 'bg-acid-yellow/20' },
  timeout: { text: 'text-text-muted', bg: 'bg-surface' },
  error: { text: 'text-acid-red', bg: 'bg-acid-red/20' },
};

export function ProofVisualizerPanel({
  backendConfig,
  debateId: _debateId,
}: ProofVisualizerPanelProps) {
  const apiBase = backendConfig?.apiUrl || DEFAULT_API_BASE;

  const [activeTab, setActiveTab] = useState<'single' | 'batch' | 'translate' | 'history'>(
    'single',
  );
  const [backendStatus, setBackendStatus] = useState<VerificationStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [statusLoading, setStatusLoading] = useState(true);

  // Single verification state
  const [claim, setClaim] = useState('');
  const [claimType, setClaimType] = useState('');
  const [context, setContext] = useState('');
  const [timeout, setTimeout] = useState(60);
  const [singleResult, setSingleResult] = useState<VerificationResult | null>(null);

  // Batch verification state
  const [batchClaims, setBatchClaims] = useState('');
  const [batchResult, setBatchResult] = useState<BatchResult | null>(null);

  // Translation state
  const [translateClaim, setTranslateClaim] = useState('');
  const [targetLanguage, setTargetLanguage] = useState<'lean4' | 'z3_smt'>('lean4');
  const [translationResult, setTranslationResult] = useState<TranslationResult | null>(null);

  // History state (server-side)
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(0);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyFilter, setHistoryFilter] = useState<string>('');
  const [selectedHistoryEntry, setSelectedHistoryEntry] = useState<HistoryEntry | null>(null);
  const [showProofTree, setShowProofTree] = useState(false);

  // Fetch backend status
  const fetchStatus = useCallback(async () => {
    try {
      setStatusLoading(true);
      const response = await fetchWithRetry(`${apiBase}/api/verify/status`, undefined, {
        maxRetries: 2,
      });
      if (response.ok) {
        const data = await response.json();
        setBackendStatus(data);
      }
    } catch (err) {
      logger.error('Failed to fetch verification status:', err);
    } finally {
      setStatusLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  // Fetch server-side verification history
  const fetchHistory = useCallback(async () => {
    try {
      setHistoryLoading(true);
      const params = new URLSearchParams({ limit: '20', offset: String(historyPage * 20) });
      if (historyFilter) {
        params.append('status', historyFilter);
      }

      const response = await fetchWithRetry(`${apiBase}/api/verify/history?${params}`, undefined, {
        maxRetries: 2,
      });
      if (response.ok) {
        const data = await response.json();
        setHistory(data.entries || []);
        setHistoryTotal(data.total || 0);
      }
    } catch (err) {
      logger.error('Failed to fetch verification history:', err);
    } finally {
      setHistoryLoading(false);
    }
  }, [apiBase, historyPage, historyFilter]);

  // Fetch specific history entry details
  const fetchHistoryEntry = async (id: string) => {
    try {
      const response = await fetch(`${apiBase}/api/verify/history/${id}`);
      if (response.ok) {
        const data = await response.json();
        setSelectedHistoryEntry(data);
        setShowProofTree(false);
      }
    } catch (err) {
      logger.error('Failed to fetch history entry:', err);
    }
  };

  // Load history when tab changes
  useEffect(() => {
    if (activeTab === 'history') {
      fetchHistory();
    }
  }, [activeTab, fetchHistory]);

  // Single claim verification
  const handleVerifyClaim = async () => {
    if (!claim.trim()) return;

    setLoading(true);
    setSingleResult(null);

    try {
      const response = await fetch(`${apiBase}/api/verify/claim`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          claim: claim.trim(),
          claim_type: claimType || undefined,
          context: context || undefined,
          timeout,
        }),
      });

      const data = await response.json();
      setSingleResult(data);
      // Refresh server-side history
      if (activeTab === 'history') {
        fetchHistory();
      }
    } catch (err) {
      logger.error('Verification failed:', err);
      setSingleResult({ status: 'error', error_message: String(err), is_verified: false });
    } finally {
      setLoading(false);
    }
  };

  // Batch verification
  const handleBatchVerify = async () => {
    const lines = batchClaims.split('\n').filter((l) => l.trim());
    if (lines.length === 0) return;

    setLoading(true);
    setBatchResult(null);

    try {
      const claims = lines.map((line) => ({ claim: line.trim() }));
      const response = await fetch(`${apiBase}/api/verify/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ claims, timeout_per_claim: 30, max_concurrent: 3 }),
      });

      const data = await response.json();
      setBatchResult(data);
    } catch (err) {
      logger.error('Batch verification failed:', err);
      setBatchResult({
        status: 'error',
        error: 'Batch verification failed. Please try again.',
        results: [],
      });
    } finally {
      setLoading(false);
    }
  };

  // Translation
  const handleTranslate = async () => {
    if (!translateClaim.trim()) return;

    setLoading(true);
    setTranslationResult(null);

    try {
      const response = await fetch(`${apiBase}/api/verify/translate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ claim: translateClaim.trim(), target_language: targetLanguage }),
      });

      const data = await response.json();
      setTranslationResult(data);
    } catch (err) {
      logger.error('Translation failed:', err);
      setTranslationResult({ status: 'error', error: 'Translation failed. Please try again.' });
    } finally {
      setLoading(false);
    }
  };

  const renderStatusBadge = (status: string) => {
    const style = STATUS_COLORS[status] || STATUS_COLORS.error;
    return (
      <span className={`px-2 py-0.5 rounded text-xs font-theme-data ${style.bg} ${style.text}`}>
        {status.replace('_', ' ').toUpperCase()}
      </span>
    );
  };

  return (
    <div className="space-y-6">
      {/* Backend Status */}
      <div className="card p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-theme-data text-[var(--accent)] text-lg">VERIFICATION BACKENDS</h3>
            <p className="text-xs font-theme-data text-text-muted mt-1">
              Available proof backends for formal verification
            </p>
          </div>
          <button
            onClick={fetchStatus}
            className="px-3 py-1 text-xs font-theme-data bg-surface border border-[var(--accent)]/30 rounded hover:border-[var(--accent)]/50 transition-colors"
          >
            [REFRESH]
          </button>
        </div>

        {statusLoading ? (
          <div className="text-[var(--accent)] font-theme-data animate-pulse">
            Loading status...
          </div>
        ) : backendStatus ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {backendStatus.backends.map((backend) => (
              <div
                key={backend.language}
                className={`p-3 rounded border ${
                  backend.available
                    ? 'border-[var(--accent)]/40 bg-[var(--accent)]/10'
                    : 'border-acid-red/40 bg-acid-red/10'
                }`}
              >
                <div className="font-theme-data text-sm mb-1">{backend.language.toUpperCase()}</div>
                <div
                  className={`text-xs font-theme-data ${
                    backend.available ? 'text-[var(--accent)]' : 'text-acid-red'
                  }`}
                >
                  {backend.available ? 'ONLINE' : 'OFFLINE'}
                </div>
              </div>
            ))}
            <div
              className={`p-3 rounded border ${
                backendStatus.deepseek_prover_available
                  ? 'border-[var(--acid-cyan)]/40 bg-[var(--acid-cyan)]/10'
                  : 'border-text-muted/40 bg-surface'
              }`}
            >
              <div className="font-theme-data text-sm mb-1">DEEPSEEK-PROVER</div>
              <div
                className={`text-xs font-theme-data ${
                  backendStatus.deepseek_prover_available
                    ? 'text-[var(--acid-cyan)]'
                    : 'text-text-muted'
                }`}
              >
                {backendStatus.deepseek_prover_available ? 'ONLINE' : 'OFFLINE'}
              </div>
            </div>
          </div>
        ) : (
          <div className="text-text-muted font-theme-data">Failed to load status</div>
        )}
      </div>

      {/* Tab Navigation */}
      <div className="flex gap-2 border-b border-[var(--accent)]/20 pb-2">
        {(['single', 'batch', 'translate', 'history'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 font-theme-data text-sm rounded-t transition-colors ${
              activeTab === tab
                ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-b-2 border-[var(--accent)]'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Single Verification Tab */}
      {activeTab === 'single' && (
        <div className="space-y-4">
          <div className="card p-4">
            <h4 className="font-theme-data text-[var(--acid-cyan)] mb-4">VERIFY SINGLE CLAIM</h4>

            <div className="space-y-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-2">CLAIM</label>
                <textarea
                  value={claim}
                  onChange={(e) => setClaim(e.target.value)}
                  placeholder="Enter a claim to verify, e.g., 'For all natural numbers n, n + 0 = n'"
                  className="w-full h-24 bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)] resize-none"
                />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-theme-data text-text-muted mb-2">
                    CLAIM TYPE (optional)
                  </label>
                  <select
                    value={claimType}
                    onChange={(e) => setClaimType(e.target.value)}
                    className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                  >
                    <option value="">Auto-detect</option>
                    <option value="MATHEMATICAL">Mathematical</option>
                    <option value="LOGICAL">Logical</option>
                    <option value="FACTUAL">Factual</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-theme-data text-text-muted mb-2">
                    TIMEOUT (seconds)
                  </label>
                  <input
                    type="number"
                    value={timeout}
                    onChange={(e) => setTimeout(Number(e.target.value))}
                    min={5}
                    max={300}
                    className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                  />
                </div>

                <div className="flex items-end">
                  <button
                    onClick={handleVerifyClaim}
                    disabled={loading || !claim.trim()}
                    className="w-full px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loading ? '[VERIFYING...]' : '[VERIFY CLAIM]'}
                  </button>
                </div>
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-2">
                  CONTEXT (optional)
                </label>
                <input
                  type="text"
                  value={context}
                  onChange={(e) => setContext(e.target.value)}
                  placeholder="Additional context for the claim"
                  className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>
            </div>
          </div>

          {/* Single Result */}
          {singleResult && (
            <div className="card p-4">
              <div className="flex items-center justify-between mb-4">
                <h4 className="font-theme-data text-[var(--acid-cyan)]">VERIFICATION RESULT</h4>
                {renderStatusBadge(singleResult.status)}
              </div>

              <div className="space-y-4">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                  <div className="p-2 bg-surface rounded">
                    <div
                      className={`text-lg font-theme-data ${singleResult.is_verified ? 'text-[var(--accent)]' : 'text-acid-red'}`}
                    >
                      {singleResult.is_verified ? 'YES' : 'NO'}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">verified</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
                      {singleResult.language?.toUpperCase() || 'N/A'}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">language</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-text">
                      {singleResult.translation_time_ms?.toFixed(0) || '0'}ms
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">translation</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-text">
                      {singleResult.proof_search_time_ms?.toFixed(0) || '0'}ms
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">proof search</div>
                  </div>
                </div>

                {singleResult.formal_statement && (
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-2">
                      FORMAL STATEMENT
                    </label>
                    <pre className="bg-surface p-3 rounded font-theme-data text-sm overflow-x-auto border border-[var(--accent)]/20">
                      {singleResult.formal_statement}
                    </pre>
                  </div>
                )}

                {singleResult.error_message && (
                  <div>
                    <label className="block text-xs font-theme-data text-acid-red mb-2">
                      ERROR
                    </label>
                    <pre className="bg-acid-red/10 p-3 rounded font-theme-data text-sm text-acid-red border border-acid-red/30">
                      {singleResult.error_message}
                    </pre>
                  </div>
                )}

                {singleResult.proof_hash && (
                  <div className="text-xs font-theme-data text-text-muted">
                    Proof hash: {singleResult.proof_hash}
                  </div>
                )}

                {/* Proof Tree Visualization */}
                {singleResult.history_id && singleResult.is_verified && (
                  <div className="mt-6 pt-4 border-t border-[var(--accent)]/20">
                    <ProofTreeVisualization historyId={singleResult.history_id} apiBase={apiBase} />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Batch Verification Tab */}
      {activeTab === 'batch' && (
        <div className="space-y-4">
          <div className="card p-4">
            <h4 className="font-theme-data text-[var(--acid-cyan)] mb-4">BATCH VERIFICATION</h4>
            <p className="text-xs font-theme-data text-text-muted mb-4">
              Enter one claim per line (max 20 claims)
            </p>

            <textarea
              value={batchClaims}
              onChange={(e) => setBatchClaims(e.target.value)}
              placeholder="1 + 1 = 2&#10;For all x, x = x&#10;If A implies B and B implies C, then A implies C"
              className="w-full h-40 bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)] resize-none mb-4"
            />

            <button
              onClick={handleBatchVerify}
              disabled={loading || !batchClaims.trim()}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? '[VERIFYING...]' : '[VERIFY BATCH]'}
            </button>
          </div>

          {/* Batch Results */}
          {batchResult && (
            <div className="card p-4">
              <h4 className="font-theme-data text-[var(--acid-cyan)] mb-4">BATCH RESULTS</h4>

              {/* Error state */}
              {batchResult.status === 'error' && batchResult.error && (
                <div className="text-acid-red text-sm mb-4">{batchResult.error}</div>
              )}

              {/* Summary */}
              {batchResult.summary && (
                <div className="grid grid-cols-4 gap-4 mb-6 text-center">
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-text">
                      {batchResult.summary.total}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">total</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-[var(--accent)]">
                      {batchResult.summary.verified}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">verified</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-acid-red">
                      {batchResult.summary.failed}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">failed</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-[var(--acid-yellow)]">
                      {batchResult.summary.timeout}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">timeout</div>
                  </div>
                </div>
              )}

              {/* Individual Results */}
              <div className="space-y-2">
                {batchResult.results.map((result, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between p-2 bg-surface rounded"
                  >
                    <span className="font-theme-data text-sm text-text-muted">
                      Claim {index + 1}
                    </span>
                    {renderStatusBadge(result.status)}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Translation Tab */}
      {activeTab === 'translate' && (
        <div className="space-y-4">
          <div className="card p-4">
            <h4 className="font-theme-data text-[var(--acid-cyan)] mb-4">
              TRANSLATE TO FORMAL LANGUAGE
            </h4>
            <p className="text-xs font-theme-data text-text-muted mb-4">
              Convert natural language claims to formal notation without verification
            </p>

            <div className="space-y-4">
              <textarea
                value={translateClaim}
                onChange={(e) => setTranslateClaim(e.target.value)}
                placeholder="Enter a claim to translate..."
                className="w-full h-24 bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)] resize-none"
              />

              <div className="flex gap-4">
                <div className="flex-1">
                  <label className="block text-xs font-theme-data text-text-muted mb-2">
                    TARGET LANGUAGE
                  </label>
                  <select
                    value={targetLanguage}
                    onChange={(e) => setTargetLanguage(e.target.value as 'lean4' | 'z3_smt')}
                    className="w-full bg-surface border border-[var(--accent)]/30 rounded px-3 py-2 font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                  >
                    <option value="lean4">Lean 4</option>
                    <option value="z3_smt">Z3 SMT</option>
                  </select>
                </div>

                <div className="flex items-end">
                  <button
                    onClick={handleTranslate}
                    disabled={loading || !translateClaim.trim()}
                    className="px-4 py-2 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)]/40 text-[var(--acid-cyan)] font-theme-data text-sm rounded hover:bg-[var(--acid-cyan)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {loading ? '[TRANSLATING...]' : '[TRANSLATE]'}
                  </button>
                </div>
              </div>
            </div>
          </div>

          {/* Translation Result */}
          {translationResult && (
            <div className="card p-4">
              <div className="flex items-center justify-between mb-4">
                <h4 className="font-theme-data text-[var(--acid-cyan)]">TRANSLATION RESULT</h4>
                <span
                  className={`px-2 py-0.5 rounded text-xs font-theme-data ${
                    translationResult.status === 'error' || !translationResult.success
                      ? 'bg-acid-red/20 text-acid-red'
                      : 'bg-[var(--accent)]/20 text-[var(--accent)]'
                  }`}
                >
                  {translationResult.status === 'error'
                    ? 'ERROR'
                    : translationResult.success
                      ? 'SUCCESS'
                      : 'FAILED'}
                </span>
              </div>

              {/* Error state */}
              {translationResult.status === 'error' && translationResult.error && (
                <div className="text-acid-red text-sm mb-4">{translationResult.error}</div>
              )}

              {translationResult.formal_statement && (
                <div className="mb-4">
                  <label className="block text-xs font-theme-data text-text-muted mb-2">
                    FORMAL STATEMENT
                  </label>
                  <pre className="bg-surface p-3 rounded font-theme-data text-sm overflow-x-auto border border-[var(--accent)]/20">
                    {translationResult.formal_statement}
                  </pre>
                </div>
              )}

              {/* Only show metrics if we have valid data (not error state) */}
              {translationResult.language && (
                <div className="grid grid-cols-3 gap-4 text-center">
                  <div className="p-2 bg-surface rounded">
                    <div className="text-sm font-theme-data text-[var(--acid-cyan)]">
                      {translationResult.language.toUpperCase()}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">language</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-sm font-theme-data text-text">
                      {((translationResult.confidence ?? 0) * 100).toFixed(0)}%
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">confidence</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-sm font-theme-data text-text">
                      {(translationResult.translation_time_ms ?? 0).toFixed(0)}ms
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">time</div>
                  </div>
                </div>
              )}

              {translationResult.error_message && (
                <div className="mt-4">
                  <pre className="bg-acid-red/10 p-3 rounded font-theme-data text-sm text-acid-red border border-acid-red/30">
                    {translationResult.error_message}
                  </pre>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* History Tab */}
      {activeTab === 'history' && (
        <div className="space-y-4">
          <div className="card p-4">
            <div className="flex items-center justify-between mb-4">
              <h4 className="font-theme-data text-[var(--acid-cyan)]">VERIFICATION HISTORY</h4>
              <div className="flex items-center gap-3">
                <select
                  value={historyFilter}
                  onChange={(e) => {
                    setHistoryFilter(e.target.value);
                    setHistoryPage(0);
                  }}
                  className="bg-surface border border-[var(--accent)]/30 rounded px-2 py-1 font-theme-data text-xs focus:outline-none focus:border-[var(--accent)]"
                >
                  <option value="">All statuses</option>
                  <option value="proof_found">Proof Found</option>
                  <option value="proof_failed">Proof Failed</option>
                  <option value="translation_failed">Translation Failed</option>
                  <option value="timeout">Timeout</option>
                </select>
                <button
                  onClick={fetchHistory}
                  className="px-3 py-1 text-xs font-theme-data bg-surface border border-[var(--accent)]/30 rounded hover:border-[var(--accent)]/50 transition-colors"
                >
                  [REFRESH]
                </button>
              </div>
            </div>

            {historyLoading ? (
              <div className="text-[var(--accent)] font-theme-data animate-pulse py-8 text-center">
                Loading history...
              </div>
            ) : history.length === 0 ? (
              <div className="text-center py-8 text-text-muted font-theme-data">
                No verification history yet. Run some verifications to see them here.
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  {history.map((entry) => (
                    <div
                      key={entry.id}
                      className="flex items-center justify-between p-3 bg-surface rounded border border-[var(--accent)]/20 hover:border-[var(--accent)]/40 cursor-pointer transition-colors"
                      onClick={() => fetchHistoryEntry(entry.id)}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-theme-data text-sm text-text truncate">
                          {entry.claim.slice(0, 80) || 'No claim'}
                          {entry.claim.length > 80 ? '...' : ''}
                        </div>
                        <div className="text-xs font-theme-data text-text-muted mt-1 flex items-center gap-2">
                          <span>{entry.result.language?.toUpperCase() || 'N/A'}</span>
                          <span>|</span>
                          <span>{new Date(entry.timestamp * 1000).toLocaleString()}</span>
                        </div>
                      </div>
                      {renderStatusBadge(entry.result.status)}
                    </div>
                  ))}
                </div>

                {/* Pagination */}
                <div className="flex items-center justify-between mt-4 pt-4 border-t border-[var(--accent)]/20">
                  <div className="text-xs font-theme-data text-text-muted">
                    Showing {historyPage * 20 + 1} -{' '}
                    {Math.min((historyPage + 1) * 20, historyTotal)} of {historyTotal}
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => setHistoryPage(Math.max(0, historyPage - 1))}
                      disabled={historyPage === 0}
                      className="px-3 py-1 text-xs font-theme-data bg-surface border border-[var(--accent)]/30 rounded hover:border-[var(--accent)]/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      [PREV]
                    </button>
                    <button
                      onClick={() => setHistoryPage(historyPage + 1)}
                      disabled={(historyPage + 1) * 20 >= historyTotal}
                      className="px-3 py-1 text-xs font-theme-data bg-surface border border-[var(--accent)]/30 rounded hover:border-[var(--accent)]/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      [NEXT]
                    </button>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* Selected Entry Details */}
          {selectedHistoryEntry && (
            <div className="card p-4">
              <div className="flex items-center justify-between mb-4">
                <h4 className="font-theme-data text-[var(--acid-cyan)]">ENTRY DETAILS</h4>
                <div className="flex items-center gap-2">
                  {selectedHistoryEntry.result.is_verified && (
                    <button
                      onClick={() => setShowProofTree(!showProofTree)}
                      className={`px-3 py-1 text-xs font-theme-data border rounded transition-colors ${
                        showProofTree
                          ? 'bg-[var(--acid-cyan)]/20 border-[var(--acid-cyan)] text-[var(--acid-cyan)]'
                          : 'border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:border-[var(--acid-cyan)]/50'
                      }`}
                    >
                      {showProofTree ? '[HIDE PROOF TREE]' : '[VIEW PROOF TREE]'}
                    </button>
                  )}
                  <button
                    onClick={() => setSelectedHistoryEntry(null)}
                    className="px-3 py-1 text-xs font-theme-data bg-surface border border-[var(--accent)]/30 rounded hover:border-[var(--accent)]/50 transition-colors"
                  >
                    [CLOSE]
                  </button>
                </div>
              </div>

              <div className="space-y-4">
                {/* Claim */}
                <div>
                  <label className="block text-xs font-theme-data text-text-muted mb-2">
                    ORIGINAL CLAIM
                  </label>
                  <div className="bg-surface p-3 rounded font-theme-data text-sm border border-[var(--accent)]/20">
                    {selectedHistoryEntry.claim}
                  </div>
                </div>

                {/* Result status and metrics */}
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-center">
                  <div className="p-2 bg-surface rounded">
                    <div
                      className={`text-lg font-theme-data ${selectedHistoryEntry.result.is_verified ? 'text-[var(--accent)]' : 'text-acid-red'}`}
                    >
                      {selectedHistoryEntry.result.is_verified ? 'YES' : 'NO'}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">verified</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
                      {selectedHistoryEntry.result.language?.toUpperCase() || 'N/A'}
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">language</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-text">
                      {selectedHistoryEntry.result.translation_time_ms?.toFixed(0) || '0'}ms
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">translation</div>
                  </div>
                  <div className="p-2 bg-surface rounded">
                    <div className="text-lg font-theme-data text-text">
                      {selectedHistoryEntry.result.proof_search_time_ms?.toFixed(0) || '0'}ms
                    </div>
                    <div className="text-xs font-theme-data text-text-muted">proof search</div>
                  </div>
                </div>

                {/* Formal statement */}
                {selectedHistoryEntry.result.formal_statement && (
                  <div>
                    <label className="block text-xs font-theme-data text-text-muted mb-2">
                      FORMAL STATEMENT
                    </label>
                    <pre className="bg-surface p-3 rounded font-theme-data text-sm overflow-x-auto border border-[var(--accent)]/20">
                      {selectedHistoryEntry.result.formal_statement}
                    </pre>
                  </div>
                )}

                {/* Error message */}
                {selectedHistoryEntry.result.error_message && (
                  <div>
                    <label className="block text-xs font-theme-data text-acid-red mb-2">
                      ERROR
                    </label>
                    <pre className="bg-acid-red/10 p-3 rounded font-theme-data text-sm text-acid-red border border-acid-red/30">
                      {selectedHistoryEntry.result.error_message}
                    </pre>
                  </div>
                )}

                {/* Proof hash */}
                {selectedHistoryEntry.result.proof_hash && (
                  <div className="text-xs font-theme-data text-text-muted">
                    Proof hash: {selectedHistoryEntry.result.proof_hash}
                  </div>
                )}

                {/* Timestamp */}
                <div className="text-xs font-theme-data text-text-muted">
                  Verified at: {new Date(selectedHistoryEntry.timestamp * 1000).toLocaleString()}
                </div>
              </div>

              {/* Proof Tree Visualization */}
              {showProofTree && selectedHistoryEntry.id && (
                <div className="mt-6 pt-4 border-t border-[var(--accent)]/20">
                  <ProofTreeVisualization historyId={selectedHistoryEntry.id} apiBase={apiBase} />
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
