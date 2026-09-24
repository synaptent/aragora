'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface ImpasseIndicators {
  repeated_critiques: boolean;
  no_convergence: boolean;
  high_severity_critiques: boolean;
  position_oscillation?: boolean;
  semantic_stagnation?: boolean;
}

interface PivotClaim {
  claim_id: string | null;
  statement: string | null;
  importance_score: number | null;
  contention_level: string | null;
}

interface ImpasseData {
  debate_id: string;
  is_impasse: boolean;
  has_impasse?: boolean;
  indicators: ImpasseIndicators;
  pivot_claim?: PivotClaim;
  should_branch?: boolean;
}

interface ImpasseDetectionPanelProps {
  debateId: string;
  apiBase?: string;
  onBranchRequest?: (pivotClaim: PivotClaim) => void;
  autoRefresh?: boolean;
  refreshInterval?: number;
}

const DEFAULT_API_BASE = API_BASE_URL;

export function ImpasseDetectionPanel({
  debateId,
  apiBase = DEFAULT_API_BASE,
  onBranchRequest,
  autoRefresh = true,
  refreshInterval = 30000,
}: ImpasseDetectionPanelProps) {
  const [data, setData] = useState<ImpasseData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const fetchImpasse = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetch(`${apiBase}/api/debates/${debateId}/impasse`);
      if (res.ok) {
        const impasseData = await res.json();
        setData(impasseData);
        setLastChecked(new Date());
        setError(null);
      } else if (res.status === 404) {
        setError('Debate not found');
      } else {
        setError('Failed to check impasse');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Network error');
    } finally {
      setLoading(false);
    }
  }, [apiBase, debateId]);

  useEffect(() => {
    fetchImpasse();
  }, [fetchImpasse]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchImpasse, refreshInterval);
    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, fetchImpasse]);

  const isImpasse = data?.is_impasse || data?.has_impasse || false;
  const shouldBranch =
    data?.should_branch ||
    (data?.pivot_claim?.importance_score && data.pivot_claim.importance_score > 0.5);

  const getIndicatorIcon = (active: boolean) => (active ? 'text-red-400' : 'text-green-400');
  const getIndicatorLabel = (key: string): { label: string; description: string } => {
    const labels: Record<string, { label: string; description: string }> = {
      repeated_critiques: {
        label: 'Repetitive Arguments',
        description: 'Same critiques being raised multiple times',
      },
      no_convergence: {
        label: 'No Convergence',
        description: 'Positions are not moving toward agreement',
      },
      high_severity_critiques: {
        label: 'High Severity',
        description: 'Critical issues being raised',
      },
      position_oscillation: {
        label: 'Position Oscillation',
        description: 'Agents flip-flopping between stances',
      },
      semantic_stagnation: {
        label: 'Semantic Stagnation',
        description: 'Little new information being introduced',
      },
    };
    return labels[key] || { label: key, description: '' };
  };

  if (error) {
    return (
      <div className="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
        Error: {error}
      </div>
    );
  }

  const indicatorCount = data?.indicators
    ? Object.values(data.indicators).filter(Boolean).length
    : 0;

  return (
    <div
      className={`panel transition-all ${
        isImpasse ? 'bg-gradient-to-br from-red-500/10 to-orange-500/10 border-red-500/40' : ''
      }`}
      style={{ padding: 0 }}
    >
      {/* Header */}
      <button
        onClick={() => setIsCollapsed(!isCollapsed)}
        className="panel-collapsible-header w-full text-left"
      >
        <div className="flex items-center gap-3">
          <div
            className={`w-3 h-3 rounded-full ${
              loading
                ? 'bg-yellow-400 animate-pulse'
                : isImpasse
                  ? 'bg-red-500 animate-pulse'
                  : 'bg-green-500'
            }`}
          />
          <div>
            <h3 className="text-sm font-semibold text-text flex items-center gap-2">
              Impasse Detection
              {isImpasse && (
                <span className="px-1.5 py-0.5 text-xs bg-red-500/20 text-red-400 rounded">
                  DETECTED
                </span>
              )}
            </h3>
            <p className="text-xs text-text-muted">
              {loading
                ? 'Analyzing...'
                : isImpasse
                  ? 'Debate may be stuck'
                  : 'Debate progressing normally'}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {lastChecked && (
            <span className="text-xs text-text-muted">
              {lastChecked.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          )}
          <span className="panel-toggle">{isCollapsed ? '[+]' : '[-]'}</span>
        </div>
      </button>

      {/* Expanded Content */}
      {!isCollapsed && !loading && data && (
        <div className="px-3 pb-3 space-y-3">
          {/* Indicators Grid */}
          <div className="grid grid-cols-2 gap-2">
            {data.indicators &&
              Object.entries(data.indicators).map(([key, active]) => {
                const { label, description } = getIndicatorLabel(key);
                return (
                  <div
                    key={key}
                    className={`p-2 rounded border transition-all ${
                      active ? 'bg-red-500/10 border-red-500/30' : 'bg-bg border-border'
                    }`}
                    title={description}
                  >
                    <div className="flex items-center gap-2">
                      <span className={getIndicatorIcon(active)}>{active ? '⚠' : '✓'}</span>
                      <span className={`text-xs ${active ? 'text-red-400' : 'text-text-muted'}`}>
                        {label}
                      </span>
                    </div>
                  </div>
                );
              })}
          </div>

          {/* Indicator Summary */}
          <div className="flex items-center justify-between text-xs">
            <span className="text-text-muted">
              {indicatorCount} of {Object.keys(data.indicators || {}).length} indicators active
            </span>
            <div className="flex gap-1">
              {[...Array(Object.keys(data.indicators || {}).length)].map((_, i) => (
                <div
                  key={i}
                  className={`w-2 h-2 rounded-full ${
                    i < indicatorCount ? 'bg-red-500' : 'bg-border'
                  }`}
                />
              ))}
            </div>
          </div>

          {/* Pivot Claim */}
          {data.pivot_claim && data.pivot_claim.statement && (
            <div className="p-3 bg-amber-500/10 border border-amber-500/30 rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-amber-400">🔀</span>
                <span className="text-sm font-medium text-amber-400">Pivot Point Identified</span>
              </div>
              <p className="text-sm text-text mb-2">&quot;{data.pivot_claim.statement}&quot;</p>
              <div className="flex items-center justify-between text-xs">
                <div className="flex gap-3 text-text-muted">
                  {data.pivot_claim.importance_score !== null && (
                    <span>Importance: {Math.round(data.pivot_claim.importance_score * 100)}%</span>
                  )}
                  {data.pivot_claim.contention_level && (
                    <span>Contention: {data.pivot_claim.contention_level}</span>
                  )}
                </div>
                {shouldBranch && onBranchRequest && (
                  <button
                    onClick={() => onBranchRequest(data.pivot_claim!)}
                    className="px-2 py-1 bg-amber-500/20 text-amber-400 border border-amber-500/30 rounded hover:bg-amber-500/30 transition-colors"
                  >
                    Branch Debate
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Actions */}
          {isImpasse && (
            <div className="p-3 bg-bg border border-border rounded-lg">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-cyan-400">💡</span>
                <span className="text-sm font-medium text-cyan-400">Suggested Actions</span>
              </div>
              <ul className="space-y-1 text-xs text-text-muted">
                <li className="flex items-center gap-2">
                  <span className="text-text-muted">•</span>
                  Introduce a new perspective or assumption
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-text-muted">•</span>
                  Request clarification on key terms
                </li>
                {shouldBranch && (
                  <li className="flex items-center gap-2">
                    <span className="text-amber-400">•</span>
                    <span className="text-amber-400">Fork into counterfactual branches</span>
                  </li>
                )}
              </ul>
            </div>
          )}

          {/* Manual Refresh */}
          <button
            onClick={fetchImpasse}
            disabled={loading}
            className="w-full py-2 text-xs text-text-muted hover:text-text border border-border rounded hover:border-accent/50 transition-colors disabled:opacity-50"
          >
            {loading ? 'Analyzing...' : 'Refresh Analysis'}
          </button>
        </div>
      )}
    </div>
  );
}

// Compact inline version for status bars
export function ImpasseStatusBadge({
  debateId,
  apiBase = DEFAULT_API_BASE,
}: {
  debateId: string;
  apiBase?: string;
}) {
  const [isImpasse, setIsImpasse] = useState<boolean | null>(null);

  useEffect(() => {
    async function check() {
      try {
        const res = await fetch(`${apiBase}/api/debates/${debateId}/impasse`);
        if (res.ok) {
          const data = await res.json();
          setIsImpasse(data.is_impasse || data.has_impasse || false);
        }
      } catch {
        // Silently fail for inline badge
      }
    }
    check();
    const interval = setInterval(check, 60000);
    return () => clearInterval(interval);
  }, [apiBase, debateId]);

  if (isImpasse === null) return null;

  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded ${
        isImpasse
          ? 'bg-red-500/20 text-red-400 border border-red-500/30'
          : 'bg-green-500/20 text-green-400 border border-green-500/30'
      }`}
      title={isImpasse ? 'Debate may be stuck' : 'Debate progressing'}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${isImpasse ? 'bg-red-400 animate-pulse' : 'bg-green-400'}`}
      />
      {isImpasse ? 'Impasse' : 'Flowing'}
    </span>
  );
}
