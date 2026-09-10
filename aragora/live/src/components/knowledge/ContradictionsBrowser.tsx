'use client';

import { useState, useCallback } from 'react';
import { useSWRFetch } from '@/hooks/useSWRFetch';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

// ─── Types ───────────────────────────────────────────────────────────────────

interface ContradictionItem {
  id: string;
  item_a_id: string;
  item_b_id: string;
  contradiction_type: string;
  similarity_score: number;
  conflict_score: number;
  severity: string;
  detected_at: string;
  resolved: boolean;
  resolution: string | null;
  resolved_at: string | null;
  resolved_by: string | null;
  notes: string;
  metadata: Record<string, unknown>;
  validator_votes: Array<{
    validator_id: string;
    vote: string;
    confidence: number;
    reason: string;
  }>;
  validation_consensus: string | null;
  calibrated_conflict_score: number | null;
}

interface ContradictionsResponse {
  workspace_id: string | null;
  min_severity: string | null;
  count: number;
  contradictions: ContradictionItem[];
}

interface ContradictionStatsResponse {
  total: number;
  unresolved: number;
  resolved: number;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
}

type ResolutionStrategy =
  | 'prefer_newer'
  | 'prefer_higher_confidence'
  | 'prefer_more_sources'
  | 'merge'
  | 'human_review'
  | 'keep_both';

const SEVERITY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  critical: { bg: 'bg-red-900/30', text: 'text-red-400', border: 'border-red-500/40' },
  high: { bg: 'bg-orange-900/30', text: 'text-orange-400', border: 'border-orange-500/40' },
  medium: { bg: 'bg-yellow-900/30', text: 'text-yellow-400', border: 'border-yellow-500/40' },
  low: { bg: 'bg-blue-900/30', text: 'text-blue-400', border: 'border-blue-500/40' },
};

const CONTRADICTION_TYPE_LABELS: Record<string, string> = {
  semantic: 'Semantic Conflict',
  temporal: 'Temporal Inconsistency',
  logical: 'Logical Contradiction',
  statistical: 'Statistical Discrepancy',
  factual: 'Factual Conflict',
};

const RESOLUTION_OPTIONS: { value: ResolutionStrategy; label: string; description: string }[] = [
  { value: 'prefer_newer', label: 'Prefer Newer', description: 'Keep the more recent item' },
  {
    value: 'prefer_higher_confidence',
    label: 'Prefer Higher Confidence',
    description: 'Keep the item with higher confidence',
  },
  {
    value: 'prefer_more_sources',
    label: 'Prefer More Sources',
    description: 'Keep the item backed by more sources',
  },
  { value: 'merge', label: 'Merge', description: 'Combine into a nuanced item' },
  { value: 'human_review', label: 'Flag for Review', description: 'Escalate for manual review' },
  { value: 'keep_both', label: 'Keep Both', description: 'Mark as disputed, keep both' },
];

// ─── Severity Filter ─────────────────────────────────────────────────────────

type SeverityFilter = 'all' | 'critical' | 'high' | 'medium' | 'low';

// ─── Sub-components ──────────────────────────────────────────────────────────

function SeverityBadge({ severity }: { severity: string }) {
  const style = SEVERITY_STYLES[severity] ?? SEVERITY_STYLES.low;
  return (
    <span
      className={`px-2 py-0.5 text-xs font-theme-data rounded border ${style.bg} ${style.text} ${style.border}`}
    >
      {severity.toUpperCase()}
    </span>
  );
}

function ConflictScoreBar({ score, label }: { score: number; label: string }) {
  const pct = Math.round(score * 100);
  const barColor = pct > 70 ? 'bg-red-500' : pct > 40 ? 'bg-yellow-500' : 'bg-blue-500';

  return (
    <div className="flex-1">
      <div className="flex justify-between text-[10px] font-theme-data mb-0.5">
        <span className="text-text-muted">{label}</span>
        <span className="text-text">{pct}%</span>
      </div>
      <div className="h-1.5 bg-bg rounded overflow-hidden">
        <div className={`h-full ${barColor} transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ResolutionStatusBadge({
  resolved,
  resolution,
}: {
  resolved: boolean;
  resolution: string | null;
}) {
  if (!resolved) {
    return (
      <span className="px-2 py-0.5 text-[10px] font-theme-data rounded border bg-amber-900/20 text-amber-400 border-amber-500/30">
        UNRESOLVED
      </span>
    );
  }

  const label = resolution ? resolution.replace(/_/g, ' ').toUpperCase() : 'RESOLVED';
  return (
    <span className="px-2 py-0.5 text-[10px] font-theme-data rounded border bg-green-900/20 text-green-400 border-green-500/30">
      {label}
    </span>
  );
}

function StatsBar({ stats }: { stats: ContradictionStatsResponse | null }) {
  if (!stats) return null;

  return (
    <div className="grid grid-cols-4 gap-3 mb-4">
      <div className="p-3 bg-surface border border-border rounded-lg text-center">
        <div className="text-xl font-theme-data text-[var(--accent)]">{stats.total}</div>
        <div className="text-[10px] text-text-muted">Total</div>
      </div>
      <div className="p-3 bg-surface border border-border rounded-lg text-center">
        <div className="text-xl font-theme-data text-amber-400">{stats.unresolved}</div>
        <div className="text-[10px] text-text-muted">Unresolved</div>
      </div>
      <div className="p-3 bg-surface border border-border rounded-lg text-center">
        <div className="text-xl font-theme-data text-green-400">{stats.resolved}</div>
        <div className="text-[10px] text-text-muted">Resolved</div>
      </div>
      <div className="p-3 bg-surface border border-border rounded-lg text-center">
        <div className="text-xl font-theme-data text-red-400">
          {(stats.by_severity?.critical ?? 0) + (stats.by_severity?.high ?? 0)}
        </div>
        <div className="text-[10px] text-text-muted">Critical+High</div>
      </div>
    </div>
  );
}

// ─── Main Component ──────────────────────────────────────────────────────────

export function ContradictionsBrowser() {
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all');
  const [resolvingId, setResolvingId] = useState<string | null>(null);
  const [selectedStrategy, setSelectedStrategy] = useState<ResolutionStrategy>('prefer_newer');
  const [resolutionNotes, setResolutionNotes] = useState('');
  const [resolveError, setResolveError] = useState<string | null>(null);
  const [showResolveFor, setShowResolveFor] = useState<string | null>(null);

  // Fetch contradictions list
  const endpoint =
    severityFilter === 'all'
      ? '/api/v1/knowledge/mound/contradictions'
      : `/api/v1/knowledge/mound/contradictions?min_severity=${severityFilter}`;

  const {
    data: contradictionsData,
    error: contradictionsError,
    isLoading: contradictionsLoading,
    mutate: refreshContradictions,
  } = useSWRFetch<ContradictionsResponse>(endpoint, { refreshInterval: 60000 });

  // Fetch contradiction stats
  const { data: statsData, mutate: refreshStats } = useSWRFetch<ContradictionStatsResponse>(
    '/api/v1/knowledge/mound/contradictions/stats',
    { refreshInterval: 60000 },
  );

  // Resolve a contradiction
  const handleResolve = useCallback(
    async (contradictionId: string) => {
      setResolvingId(contradictionId);
      setResolveError(null);

      try {
        const response = await fetch(
          `${API_BASE_URL}/api/v1/knowledge/mound/contradictions/${contradictionId}/resolve`,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              strategy: selectedStrategy,
              notes: resolutionNotes.trim() || undefined,
            }),
          },
        );

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || `Resolution failed (${response.status})`);
        }

        // Refresh data
        await Promise.all([refreshContradictions(), refreshStats()]);
        setShowResolveFor(null);
        setResolutionNotes('');
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Resolution failed';
        setResolveError(message);
        logger.error('Failed to resolve contradiction:', err);
      } finally {
        setResolvingId(null);
      }
    },
    [selectedStrategy, resolutionNotes, refreshContradictions, refreshStats],
  );

  // Trigger a new scan
  const [scanning, setScanning] = useState(false);
  const handleScan = useCallback(async () => {
    setScanning(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/knowledge/mound/contradictions/detect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });

      if (response.ok) {
        await Promise.all([refreshContradictions(), refreshStats()]);
      }
    } catch (err) {
      logger.error('Contradiction scan failed:', err);
    } finally {
      setScanning(false);
    }
  }, [refreshContradictions, refreshStats]);

  const contradictions = contradictionsData?.contradictions ?? [];
  const stats = statsData ?? null;

  function formatDate(iso: string): string {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    const hours = Math.floor(diff / (1000 * 60 * 60));
    if (hours < 1) return 'Just now';
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}d ago`;
    return d.toLocaleDateString();
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-theme-data text-red-400 uppercase tracking-wider">
            Knowledge Contradictions
          </h3>
          <p className="text-xs text-text-muted mt-0.5">
            Detected conflicts between knowledge items requiring resolution
          </p>
        </div>
        <button
          onClick={handleScan}
          disabled={scanning}
          className="px-3 py-1.5 text-xs font-theme-data bg-red-500/20 border border-red-500/40 text-red-400 rounded hover:bg-red-500/30 transition-colors disabled:opacity-50"
        >
          {scanning ? 'Scanning...' : 'Run Scan'}
        </button>
      </div>

      {/* Stats */}
      <StatsBar stats={stats} />

      {/* Severity Filter */}
      <div className="flex gap-1">
        {(['all', 'critical', 'high', 'medium', 'low'] as SeverityFilter[]).map((sev) => (
          <button
            key={sev}
            onClick={() => setSeverityFilter(sev)}
            className={`px-3 py-1.5 text-xs font-theme-data rounded transition-colors ${
              severityFilter === sev
                ? 'bg-[var(--accent)] text-bg'
                : 'bg-surface text-text-muted hover:text-text border border-border'
            }`}
          >
            {sev === 'all' ? 'ALL' : sev.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Loading State */}
      {contradictionsLoading && (
        <div className="text-center py-8 text-text-muted font-theme-data animate-pulse">
          Loading contradictions...
        </div>
      )}

      {/* Error State */}
      {contradictionsError && !contradictionsLoading && (
        <div className="p-4 bg-surface border border-border rounded-lg text-center">
          <p className="text-text-muted font-theme-data text-sm">
            Unable to load contradictions. The backend may not be running.
          </p>
          <button
            onClick={() => refreshContradictions()}
            className="mt-2 px-3 py-1 text-xs font-theme-data text-[var(--accent)] border border-[var(--accent)]/30 rounded hover:bg-[var(--accent)]/10"
          >
            Retry
          </button>
        </div>
      )}

      {/* Empty State */}
      {!contradictionsLoading && !contradictionsError && contradictions.length === 0 && (
        <div className="p-8 bg-surface border border-border rounded-lg text-center">
          <div className="text-3xl mb-2">--</div>
          <p className="text-text-muted font-theme-data text-sm">No contradictions detected</p>
          <p className="text-text-muted/60 font-theme-data text-xs mt-1">
            Run a contradiction scan or add more knowledge to detect conflicts
          </p>
        </div>
      )}

      {/* Contradictions List */}
      {!contradictionsLoading && contradictions.length > 0 && (
        <div className="space-y-3 max-h-[600px] overflow-y-auto pr-1">
          {contradictions.map((c) => {
            const typeLabel =
              CONTRADICTION_TYPE_LABELS[c.contradiction_type] ?? c.contradiction_type;
            const isResolving = resolvingId === c.id;
            const showResolve = showResolveFor === c.id;

            return (
              <div
                key={c.id}
                className={`p-4 bg-surface border rounded-lg transition-colors ${
                  c.resolved
                    ? 'border-green-500/20 opacity-70'
                    : 'border-border hover:border-red-500/30'
                }`}
              >
                {/* Header row */}
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <SeverityBadge severity={c.severity} />
                    <span className="text-xs font-theme-data text-text-muted">{typeLabel}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <ResolutionStatusBadge resolved={c.resolved} resolution={c.resolution} />
                    <span className="text-[10px] font-theme-data text-text-muted">
                      {formatDate(c.detected_at)}
                    </span>
                  </div>
                </div>

                {/* Conflicting Items (side by side) */}
                <div className="grid grid-cols-2 gap-3 mb-3">
                  <div className="p-2 bg-bg rounded border border-red-500/10">
                    <div className="text-[10px] font-theme-data text-red-400/70 mb-1">Item A</div>
                    <div className="text-xs font-theme-data text-[var(--acid-cyan)] break-all">
                      {c.item_a_id}
                    </div>
                  </div>
                  <div className="p-2 bg-bg rounded border border-red-500/10">
                    <div className="text-[10px] font-theme-data text-red-400/70 mb-1">Item B</div>
                    <div className="text-xs font-theme-data text-[var(--acid-cyan)] break-all">
                      {c.item_b_id}
                    </div>
                  </div>
                </div>

                {/* Scores */}
                <div className="flex gap-4 mb-3">
                  <ConflictScoreBar score={c.conflict_score} label="Conflict" />
                  <ConflictScoreBar score={c.similarity_score} label="Similarity" />
                </div>

                {/* Validation info */}
                {c.validation_consensus && (
                  <div className="text-[10px] font-theme-data text-text-muted mb-2">
                    Validation consensus:{' '}
                    <span className="text-[var(--acid-cyan)]">{c.validation_consensus}</span>
                    {c.validator_votes.length > 0 && (
                      <span className="ml-2">({c.validator_votes.length} votes)</span>
                    )}
                  </div>
                )}

                {/* Notes */}
                {c.notes && <div className="text-xs text-text-muted mb-2 italic">{c.notes}</div>}

                {/* Resolution info for resolved items */}
                {c.resolved && c.resolved_at && (
                  <div className="text-[10px] font-theme-data text-green-400/70 mb-2">
                    Resolved {formatDate(c.resolved_at)}
                    {c.resolved_by && <span> by {c.resolved_by}</span>}
                  </div>
                )}

                {/* Resolve Action */}
                {!c.resolved && (
                  <div className="border-t border-border pt-3 mt-3">
                    {!showResolve ? (
                      <button
                        onClick={() => setShowResolveFor(c.id)}
                        className="px-3 py-1.5 text-xs font-theme-data bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] rounded hover:bg-[var(--accent)]/30 transition-colors"
                      >
                        Resolve
                      </button>
                    ) : (
                      <div className="space-y-2">
                        {/* Strategy selector */}
                        <div className="grid grid-cols-3 gap-1">
                          {RESOLUTION_OPTIONS.map((opt) => (
                            <button
                              key={opt.value}
                              onClick={() => setSelectedStrategy(opt.value)}
                              title={opt.description}
                              className={`px-2 py-1.5 text-[10px] font-theme-data rounded transition-colors ${
                                selectedStrategy === opt.value
                                  ? 'bg-[var(--accent)] text-bg'
                                  : 'bg-bg text-text-muted border border-border hover:border-[var(--accent)]/30'
                              }`}
                            >
                              {opt.label}
                            </button>
                          ))}
                        </div>

                        {/* Notes input */}
                        <input
                          type="text"
                          value={resolutionNotes}
                          onChange={(e) => setResolutionNotes(e.target.value)}
                          placeholder="Optional resolution notes..."
                          className="w-full px-2 py-1.5 text-xs font-theme-data bg-bg border border-border rounded text-text focus:border-[var(--accent)] focus:outline-none"
                        />

                        {/* Error message */}
                        {resolveError && (
                          <div className="text-[10px] font-theme-data text-red-400">
                            {resolveError}
                          </div>
                        )}

                        {/* Action buttons */}
                        <div className="flex gap-2">
                          <button
                            onClick={() => handleResolve(c.id)}
                            disabled={isResolving}
                            className="px-3 py-1.5 text-xs font-theme-data bg-[var(--accent)] text-bg rounded hover:bg-[var(--accent)]/80 disabled:opacity-50 transition-colors"
                          >
                            {isResolving ? 'Resolving...' : 'Confirm'}
                          </button>
                          <button
                            onClick={() => {
                              setShowResolveFor(null);
                              setResolveError(null);
                            }}
                            className="px-3 py-1.5 text-xs font-theme-data border border-border text-text-muted rounded hover:border-text-muted transition-colors"
                          >
                            Cancel
                          </button>
                        </div>
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
