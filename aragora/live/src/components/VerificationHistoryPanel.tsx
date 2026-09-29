'use client';

import { useState, useEffect, useCallback } from 'react';
import { withErrorBoundary } from './PanelErrorBoundary';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

interface VerificationEntry {
  id: string;
  claim: string;
  claim_type: string | null;
  context: string;
  result: {
    status: string;
    formal_statement?: string;
    proof_hash?: string;
    confidence?: number;
    error_message?: string;
  };
  timestamp: number;
  timestamp_iso: string;
  has_proof_tree: boolean;
}

interface VerificationHistoryResponse {
  entries: VerificationEntry[];
  total: number;
  limit: number;
  offset: number;
}

interface ProofTreeNode {
  id: string;
  type: 'claim' | 'translation' | 'verification' | 'proof_step';
  content: string;
  children: string[];
  language?: string;
  is_verified?: boolean;
  proof_hash?: string;
  step_number?: number;
}

interface VerificationHistoryPanelProps {
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

const STATUS_COLORS: Record<string, string> = {
  proof_found: 'text-green-400',
  proof_failed: 'text-red-400',
  translation_failed: 'text-yellow-400',
  timeout: 'text-orange-400',
  not_attempted: 'text-gray-400',
  backend_unavailable: 'text-gray-500',
};

const STATUS_ICONS: Record<string, string> = {
  proof_found: '✓',
  proof_failed: '✗',
  translation_failed: '⚠',
  timeout: '⏱',
  not_attempted: '○',
  backend_unavailable: '◌',
};

function VerificationHistoryPanelInner({
  apiBase = DEFAULT_API_BASE,
}: VerificationHistoryPanelProps) {
  const [entries, setEntries] = useState<VerificationEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedEntry, setSelectedEntry] = useState<VerificationEntry | null>(null);
  const [proofTree, setProofTree] = useState<ProofTreeNode[] | null>(null);
  const [proofTreeError, setProofTreeError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const limit = 20;

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchWithRetry(
        `${apiBase}/api/verify/history?limit=${limit}&offset=${offset}`,
      );
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data: VerificationHistoryResponse = await response.json();
      setEntries(data.entries);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load history');
    } finally {
      setLoading(false);
    }
  }, [apiBase, offset]);

  const fetchProofTree = useCallback(
    async (entryId: string) => {
      setProofTreeError(null);
      try {
        const response = await fetchWithRetry(`${apiBase}/api/verify/history/${entryId}/tree`);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        setProofTree(data.nodes || []);
      } catch (err) {
        logger.error('Failed to load proof tree:', err);
        setProofTree(null);
        setProofTreeError('Unable to load proof tree. Click to retry.');
      }
    },
    [apiBase],
  );

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  useEffect(() => {
    if (selectedEntry?.has_proof_tree) {
      fetchProofTree(selectedEntry.id);
    } else {
      setProofTree(null);
      setProofTreeError(null);
    }
  }, [selectedEntry, fetchProofTree]);

  const formatTimestamp = (iso: string) => {
    const date = new Date(iso);
    return date.toLocaleString();
  };

  const truncate = (text: string, maxLen: number) => {
    if (text.length <= maxLen) return text;
    return text.substring(0, maxLen) + '...';
  };

  return (
    <div className="font-theme-data text-sm">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-green-400 text-lg">VERIFICATION HISTORY</h3>
        <button
          onClick={() => fetchHistory()}
          disabled={loading}
          className="px-3 py-1 border border-green-500/30 hover:bg-green-500/10 text-green-400 disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="p-2 mb-4 border border-red-500/30 bg-red-500/10 text-red-400">
          Error: {error}
        </div>
      )}

      <div className="space-y-2">
        {entries.length === 0 && !loading && (
          <div className="text-gray-500 text-center py-8">No verification history found</div>
        )}

        {entries.map((entry) => (
          <div
            key={entry.id}
            onClick={() => setSelectedEntry(selectedEntry?.id === entry.id ? null : entry)}
            className={`p-3 border cursor-pointer transition-colors ${
              selectedEntry?.id === entry.id
                ? 'border-green-500/50 bg-green-500/10'
                : 'border-green-500/20 hover:border-green-500/40'
            }`}
          >
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <span className={STATUS_COLORS[entry.result.status] || 'text-gray-400'}>
                    {STATUS_ICONS[entry.result.status] || '?'}
                  </span>
                  <span className="text-white/80">{truncate(entry.claim, 60)}</span>
                </div>
                <div className="text-gray-500 text-xs">
                  {formatTimestamp(entry.timestamp_iso)}
                  {entry.claim_type && ` | ${entry.claim_type}`}
                  {entry.has_proof_tree && ' | Has proof tree'}
                </div>
              </div>
              <div className="text-right">
                <div className={STATUS_COLORS[entry.result.status] || 'text-gray-400'}>
                  {entry.result.status.replace('_', ' ')}
                </div>
                {entry.result.confidence !== undefined && (
                  <div className="text-gray-500 text-xs">
                    {(entry.result.confidence * 100).toFixed(0)}% confidence
                  </div>
                )}
              </div>
            </div>

            {selectedEntry?.id === entry.id && (
              <div className="mt-3 pt-3 border-t border-green-500/20">
                <div className="space-y-2 text-xs">
                  <div>
                    <span className="text-gray-500">Full claim: </span>
                    <span className="text-white/70">{entry.claim}</span>
                  </div>
                  {entry.context && (
                    <div>
                      <span className="text-gray-500">Context: </span>
                      <span className="text-white/70">{entry.context}</span>
                    </div>
                  )}
                  {entry.result.formal_statement && (
                    <div>
                      <span className="text-gray-500">Formal: </span>
                      <code className="text-cyan-400">{entry.result.formal_statement}</code>
                    </div>
                  )}
                  {entry.result.proof_hash && (
                    <div>
                      <span className="text-gray-500">Proof hash: </span>
                      <code className="text-yellow-400">{entry.result.proof_hash}</code>
                    </div>
                  )}
                  {entry.result.error_message && (
                    <div>
                      <span className="text-gray-500">Error: </span>
                      <span className="text-red-400">{entry.result.error_message}</span>
                    </div>
                  )}

                  {proofTreeError && (
                    <div
                      className="mt-2 pt-2 border-t border-green-500/10 cursor-pointer"
                      onClick={(e) => {
                        e.stopPropagation();
                        if (selectedEntry) fetchProofTree(selectedEntry.id);
                      }}
                    >
                      <div className="text-red-400 text-xs hover:text-red-300 transition-colors">
                        {proofTreeError}
                      </div>
                    </div>
                  )}

                  {proofTree && proofTree.length > 0 && (
                    <div className="mt-2 pt-2 border-t border-green-500/10">
                      <div className="text-gray-500 mb-1">Proof Tree:</div>
                      <div className="space-y-1 pl-2">
                        {proofTree.map((node) => (
                          <div key={node.id} className="flex items-start gap-2">
                            <span className={node.is_verified ? 'text-green-400' : 'text-gray-500'}>
                              {node.is_verified ? '✓' : '○'}
                            </span>
                            <div>
                              <span className="text-gray-400">[{node.type}]</span>
                              <span className="text-white/70 ml-1">
                                {truncate(node.content, 50)}
                              </span>
                              {node.language && (
                                <span className="text-cyan-400/60 ml-1">({node.language})</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>

      {total > limit && (
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-green-500/20">
          <span className="text-gray-500">
            Showing {offset + 1}-{Math.min(offset + limit, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - limit))}
              disabled={offset === 0}
              className="px-3 py-1 border border-green-500/30 hover:bg-green-500/10 text-green-400 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Previous
            </button>
            <button
              onClick={() => setOffset(offset + limit)}
              disabled={offset + limit >= total}
              className="px-3 py-1 border border-green-500/30 hover:bg-green-500/10 text-green-400 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export const VerificationHistoryPanel = withErrorBoundary(
  VerificationHistoryPanelInner,
  'VerificationHistoryPanel',
);

export default VerificationHistoryPanel;
