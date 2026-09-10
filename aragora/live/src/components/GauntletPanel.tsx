'use client';

import { useState, useEffect, useCallback } from 'react';
import dynamic from 'next/dynamic';
import { logger } from '@/utils/logger';

// Lazy load the heatmap component
const GauntletHeatmap = dynamic(() => import('./GauntletHeatmap'), {
  ssr: false,
  loading: () => (
    <div className="p-4 text-center text-text-muted text-sm font-theme-data">
      Loading heatmap...
    </div>
  ),
});

interface GauntletResult {
  gauntlet_id: string;
  input_summary: string;
  input_hash: string;
  verdict: string;
  confidence: number;
  robustness_score: number;
  critical_count: number;
  high_count: number;
  total_findings: number;
  created_at: string;
  duration_seconds?: number;
}

interface GauntletPanelProps {
  apiBase: string;
}

const verdictBadges: Record<string, string> = {
  PASS: 'bg-[var(--accent)]/20 border-[var(--accent)]/50 text-[var(--accent)]',
  CONDITIONAL: 'bg-amber-400/20 border-amber-400/50 text-amber-400',
  FAIL: 'bg-red-500/20 border-red-500/50 text-red-500',
  UNKNOWN: 'bg-surface border-border text-text-muted',
};

export function GauntletPanel({ apiBase }: GauntletPanelProps) {
  const [results, setResults] = useState<GauntletResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [total, setTotal] = useState(0);
  const [selectedVerdict, setSelectedVerdict] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [, setExpandedDetails] = useState<Record<string, unknown> | null>(null);
  const [detailsError, setDetailsError] = useState<string | null>(null);

  const fetchResults = useCallback(async () => {
    try {
      setLoading(true);
      const url = new URL(`${apiBase}/api/gauntlet/results`);
      url.searchParams.set('limit', '20');
      if (selectedVerdict) {
        url.searchParams.set('verdict', selectedVerdict);
      }

      const response = await fetch(url.toString());
      if (!response.ok) throw new Error('Failed to fetch gauntlet results');

      const data = await response.json();
      setResults(data.results || []);
      setTotal(data.total || 0);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load results');
    } finally {
      setLoading(false);
    }
  }, [apiBase, selectedVerdict]);

  useEffect(() => {
    fetchResults();
  }, [fetchResults]);

  const fetchDetails = async (gauntletId: string) => {
    try {
      setDetailsError(null);
      const response = await fetch(`${apiBase}/api/gauntlet/${gauntletId}`);
      if (!response.ok) throw new Error('Failed to fetch details');
      const data = await response.json();
      setExpandedDetails(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load details';
      setDetailsError(message);
      logger.error('Failed to fetch gauntlet details:', err);
    }
  };

  const handleExpand = (gauntletId: string) => {
    if (expandedId === gauntletId) {
      setExpandedId(null);
      setExpandedDetails(null);
      setDetailsError(null);
    } else {
      setExpandedId(gauntletId);
      setDetailsError(null);
      fetchDetails(gauntletId);
    }
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleString();
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '-';
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  return (
    <div className="bg-surface border border-border rounded-lg">
      <div className="border-b border-border p-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-theme-data text-[var(--accent)] flex items-center gap-2">
            <span className="text-xl">⚔️</span> GAUNTLET RESULTS
          </h2>
          <p className="text-xs text-text-muted mt-1">
            {total} stress test{total !== 1 ? 's' : ''} recorded
          </p>
        </div>
        <button
          onClick={fetchResults}
          className="px-3 py-1 text-xs font-theme-data bg-bg border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors"
        >
          REFRESH
        </button>
      </div>

      <div className="border-b border-border p-3 flex items-center gap-2 bg-bg/50">
        <span className="text-xs text-text-muted font-theme-data">FILTER:</span>
        {['PASS', 'CONDITIONAL', 'FAIL'].map((verdict) => (
          <button
            key={verdict}
            onClick={() => setSelectedVerdict(selectedVerdict === verdict ? null : verdict)}
            className={`px-2 py-0.5 text-xs font-theme-data border transition-colors ${
              selectedVerdict === verdict
                ? verdictBadges[verdict]
                : 'bg-bg border-border text-text-muted hover:border-[var(--accent)]/30'
            }`}
          >
            {verdict}
          </button>
        ))}
        {selectedVerdict && (
          <button
            onClick={() => setSelectedVerdict(null)}
            className="text-xs text-text-muted hover:text-[var(--accent)]"
          >
            [CLEAR]
          </button>
        )}
      </div>

      <div className="max-h-[600px] overflow-y-auto">
        {loading ? (
          <div className="p-8 text-center">
            <div className="inline-block animate-spin text-[var(--accent)] text-2xl">⟳</div>
            <p className="text-text-muted mt-2 font-theme-data text-sm">Loading results...</p>
          </div>
        ) : error ? (
          <div className="p-4 text-center text-red-500 font-theme-data text-sm">{error}</div>
        ) : results.length === 0 ? (
          <div className="p-8 text-center text-text-muted font-theme-data">
            <p className="text-2xl mb-2">∅</p>
            <p>No stress test results yet</p>
            <p className="text-xs mt-2 text-text-muted/60">
              Run a security or compliance audit to see results here.
            </p>
          </div>
        ) : (
          <div className="divide-y divide-border">
            {results.map((result) => (
              <div key={result.gauntlet_id}>
                <div
                  className="p-4 hover:bg-bg/50 cursor-pointer transition-colors"
                  onClick={() => handleExpand(result.gauntlet_id)}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span
                          className={`px-2 py-0.5 text-xs font-theme-data border ${verdictBadges[result.verdict] || verdictBadges.UNKNOWN}`}
                        >
                          {result.verdict}
                        </span>
                        <span className="text-xs text-text-muted font-theme-data">
                          {result.gauntlet_id.slice(-12)}
                        </span>
                      </div>
                      <p className="text-sm text-text truncate font-theme-data">
                        {result.input_summary}
                      </p>
                      <div className="flex items-center gap-4 mt-2 text-xs text-text-muted font-theme-data">
                        <span>{formatDate(result.created_at)}</span>
                        <span>⏱ {formatDuration(result.duration_seconds)}</span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="flex items-center gap-2">
                        {result.critical_count > 0 && (
                          <span className="px-2 py-0.5 bg-red-500/20 text-red-500 text-xs font-theme-data border border-red-500/30">
                            {result.critical_count} CRIT
                          </span>
                        )}
                        {result.high_count > 0 && (
                          <span className="px-2 py-0.5 bg-amber-500/20 text-amber-500 text-xs font-theme-data border border-amber-500/30">
                            {result.high_count} HIGH
                          </span>
                        )}
                      </div>
                      <div className="mt-2 text-xs text-text-muted font-theme-data">
                        {result.total_findings} finding{result.total_findings !== 1 ? 's' : ''}
                      </div>
                    </div>
                  </div>
                </div>

                {expandedId === result.gauntlet_id && (
                  <div className="bg-bg border-t border-border p-4">
                    {/* Details Error */}
                    {detailsError && (
                      <div className="mb-4 p-3 bg-red-500/10 border border-red-500/30 rounded text-red-500 font-theme-data text-sm flex items-center justify-between">
                        <span>{detailsError}</span>
                        <button
                          onClick={() => fetchDetails(result.gauntlet_id)}
                          className="text-xs hover:text-red-400 transition-colors"
                        >
                          [RETRY]
                        </button>
                      </div>
                    )}

                    {/* Inline Heatmap */}
                    <div className="mb-4">
                      <GauntletHeatmap gauntletId={result.gauntlet_id} apiBase={apiBase} />
                    </div>

                    {/* Action buttons */}
                    <div className="flex items-center gap-2 pt-3 border-t border-border">
                      <a
                        href={`${apiBase}/api/gauntlet/${result.gauntlet_id}/receipt?format=html`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-3 py-1 text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors"
                      >
                        📜 VIEW RECEIPT
                      </a>
                      <a
                        href={`${apiBase}/api/gauntlet/${result.gauntlet_id}/heatmap?format=svg`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/20 transition-colors"
                      >
                        🔥 EXPORT SVG
                      </a>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
