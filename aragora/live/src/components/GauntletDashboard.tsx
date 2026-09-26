'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';
import {
  StatCard,
  VerdictBadge,
  HeatmapVisualization,
  ResultRow,
  CompareView,
  VERDICT_CONFIG,
  type GauntletResult,
  type HeatmapData,
  type GauntletDashboardProps,
} from './gauntlet-dashboard';

export function GauntletDashboard({
  apiBase = API_BASE_URL,
  authToken,
  onResultSelect,
}: GauntletDashboardProps) {
  const [results, setResults] = useState<GauntletResult[]>([]);
  const [selectedResult, setSelectedResult] = useState<GauntletResult | null>(null);
  const [compareResult, setCompareResult] = useState<GauntletResult | null>(null);
  const [heatmapData, setHeatmapData] = useState<HeatmapData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [heatmapError, setHeatmapError] = useState<string | null>(null);
  const [verdictFilter, setVerdictFilter] = useState<string | null>(null);
  const [showCompare, setShowCompare] = useState(false);

  const fetchResults = useCallback(async () => {
    try {
      setLoading(true);
      const headers: Record<string, string> = {};
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const url = new URL(`${apiBase}/api/gauntlet/results`);
      url.searchParams.set('limit', '50');
      if (verdictFilter) {
        url.searchParams.set('verdict', verdictFilter);
      }

      const response = await fetch(url.toString(), { headers });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      setResults(data.results || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch results');
    } finally {
      setLoading(false);
    }
  }, [apiBase, authToken, verdictFilter]);

  const fetchHeatmap = useCallback(
    async (gauntletId: string) => {
      try {
        setHeatmapError(null);
        const response = await fetch(`${apiBase}/api/gauntlet/${gauntletId}/heatmap`);
        if (response.ok) {
          const data = await response.json();
          setHeatmapData(data);
        } else {
          setHeatmapError('Failed to load heatmap data.');
        }
      } catch (err) {
        logger.error('Failed to fetch heatmap:', err);
        setHeatmapError('Unable to load heatmap. Please try again.');
      }
    },
    [apiBase],
  );

  useEffect(() => {
    fetchResults();
  }, [fetchResults]);

  useEffect(() => {
    if (selectedResult) {
      fetchHeatmap(selectedResult.gauntlet_id);
    } else {
      setHeatmapData(null);
    }
  }, [selectedResult, fetchHeatmap]);

  const handleResultSelect = (result: GauntletResult) => {
    if (showCompare && selectedResult) {
      setCompareResult(result);
    } else {
      setSelectedResult(result);
      if (onResultSelect) {
        onResultSelect(result);
      }
    }
  };

  const handleExport = (gauntletId: string, format: string) => {
    window.open(`${apiBase}/api/gauntlet/${gauntletId}/receipt?format=${format}`, '_blank');
  };

  const handleStartCompare = (result: GauntletResult) => {
    setSelectedResult(result);
    setShowCompare(true);
  };

  // Summary stats
  const summary = useMemo(() => {
    const passed = results.filter((r) => ['PASS', 'APPROVED'].includes(r.verdict)).length;
    const conditional = results.filter((r) =>
      ['CONDITIONAL', 'APPROVED_WITH_CONDITIONS', 'NEEDS_REVIEW'].includes(r.verdict),
    ).length;
    const failed = results.filter((r) => ['FAIL', 'REJECTED'].includes(r.verdict)).length;
    const totalCritical = results.reduce((sum, r) => sum + (r.critical_count || 0), 0);
    const totalHigh = results.reduce((sum, r) => sum + (r.high_count || 0), 0);
    const avgRobustness =
      results.length > 0
        ? results.reduce((sum, r) => sum + (r.robustness_score || 0), 0) / results.length
        : 0;

    return {
      passed,
      conditional,
      failed,
      totalCritical,
      totalHigh,
      avgRobustness,
      total: results.length,
    };
  }, [results]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h2 className="font-theme-data text-[var(--accent)] text-lg flex items-center gap-2">
          <span className="text-xl">{'\u2694\uFE0F'}</span> GAUNTLET DASHBOARD
        </h2>
        <button
          onClick={fetchResults}
          disabled={loading}
          className="px-4 py-2 text-sm font-theme-data border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50"
        >
          {loading ? 'LOADING...' : 'REFRESH'}
        </button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3">
        <StatCard label="TOTAL RUNS" value={summary.total} icon={'\u{1F3C3}'} />
        <StatCard label="PASSED" value={summary.passed} color="acid-green" icon={'\u2713'} />
        <StatCard
          label="CONDITIONAL"
          value={summary.conditional}
          color="acid-yellow"
          icon={'\u26A0'}
        />
        <StatCard label="FAILED" value={summary.failed} color="acid-red" icon={'\u2717'} />
        <StatCard
          label="CRITICAL ISSUES"
          value={summary.totalCritical}
          color="acid-red"
          icon={'\u{1F6A8}'}
        />
        <StatCard label="HIGH ISSUES" value={summary.totalHigh} color="warning" icon={'\u26A0'} />
        <StatCard
          label="AVG ROBUSTNESS"
          value={`${(summary.avgRobustness * 100).toFixed(0)}%`}
          color={
            summary.avgRobustness > 0.7
              ? 'acid-green'
              : summary.avgRobustness > 0.4
                ? 'acid-yellow'
                : 'acid-red'
          }
          icon={'\u{1F6E1}'}
        />
      </div>

      {/* Filters */}
      <div className="flex items-center gap-2">
        <span className="text-xs font-theme-data text-text-muted">FILTER:</span>
        {['PASS', 'CONDITIONAL', 'FAIL'].map((verdict) => (
          <button
            key={verdict}
            onClick={() => setVerdictFilter(verdictFilter === verdict ? null : verdict)}
            className={`px-2 py-1 text-xs font-theme-data border rounded transition-colors ${
              verdictFilter === verdict
                ? `${VERDICT_CONFIG[verdict]?.bg} ${VERDICT_CONFIG[verdict]?.border} ${VERDICT_CONFIG[verdict]?.text}`
                : 'bg-surface border-border text-text-muted hover:border-[var(--accent)]/30'
            }`}
          >
            {verdict}
          </button>
        ))}
        {verdictFilter && (
          <button
            onClick={() => setVerdictFilter(null)}
            className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
          >
            [CLEAR]
          </button>
        )}
        <div className="flex-1" />
        <button
          onClick={() => setShowCompare(!showCompare)}
          className={`px-3 py-1 text-xs font-theme-data border rounded transition-colors ${
            showCompare
              ? 'bg-accent/20 border-accent text-accent'
              : 'border-border text-text-muted hover:border-accent/30'
          }`}
        >
          {showCompare ? 'COMPARING...' : 'COMPARE MODE'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-warning/10 border border-warning/30 rounded-lg">
          <div className="text-warning font-theme-data text-sm">{error}</div>
        </div>
      )}

      {/* Comparison View */}
      {showCompare && selectedResult && compareResult && (
        <CompareView
          result1={selectedResult}
          result2={compareResult}
          apiBase={apiBase}
          onClose={() => {
            setShowCompare(false);
            setCompareResult(null);
          }}
        />
      )}

      {/* Main Content */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* Results List */}
        <div className="lg:col-span-2 bg-surface border border-border rounded-lg overflow-hidden">
          <div className="px-4 py-3 border-b border-border bg-bg/50">
            <span className="text-xs font-theme-data text-[var(--accent)] uppercase">
              {'>'} RECENT GAUNTLET RUNS ({results.length})
            </span>
            {showCompare && selectedResult && !compareResult && (
              <span className="ml-4 text-xs font-theme-data text-accent animate-pulse">
                Select another run to compare...
              </span>
            )}
          </div>
          <div className="max-h-[500px] overflow-y-auto divide-y divide-border">
            {loading && results.length === 0 && (
              <div className="p-8 text-center text-[var(--accent)] font-theme-data animate-pulse">
                Loading results...
              </div>
            )}
            {!loading && results.length === 0 && (
              <div className="p-8 text-center text-text-muted font-theme-data">
                No gauntlet runs found
              </div>
            )}
            {results.map((result) => (
              <ResultRow
                key={result.gauntlet_id}
                result={result}
                onClick={() => handleResultSelect(result)}
                isSelected={selectedResult?.gauntlet_id === result.gauntlet_id}
                onExport={(format) => handleExport(result.gauntlet_id, format)}
                onCompare={() => handleStartCompare(result)}
              />
            ))}
          </div>
        </div>

        {/* Detail Panel */}
        <div className="space-y-4">
          {/* Selected Result Details */}
          <div className="bg-surface border border-[var(--acid-cyan)]/30 rounded-lg p-4">
            <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-4">RESULT DETAILS</h3>
            {selectedResult ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <VerdictBadge verdict={selectedResult.verdict} />
                  <span className="text-xs font-theme-data text-text-muted">
                    {selectedResult.gauntlet_id.slice(-12)}
                  </span>
                </div>

                <div className="p-3 bg-bg/50 rounded text-xs font-theme-data text-text">
                  {selectedResult.input_summary}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div className="p-2 bg-bg/50 rounded">
                    <div className="text-xs text-text-muted">Confidence</div>
                    <div className="text-lg font-theme-data text-[var(--accent)]">
                      {(selectedResult.confidence * 100).toFixed(0)}%
                    </div>
                  </div>
                  <div className="p-2 bg-bg/50 rounded">
                    <div className="text-xs text-text-muted">Robustness</div>
                    <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
                      {(selectedResult.robustness_score * 100).toFixed(0)}%
                    </div>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2">
                  {selectedResult.critical_count > 0 && (
                    <span className="px-2 py-1 bg-acid-red/20 text-acid-red text-xs font-theme-data rounded">
                      {selectedResult.critical_count} Critical
                    </span>
                  )}
                  {selectedResult.high_count > 0 && (
                    <span className="px-2 py-1 bg-warning/20 text-warning text-xs font-theme-data rounded">
                      {selectedResult.high_count} High
                    </span>
                  )}
                  {(selectedResult.medium_count || 0) > 0 && (
                    <span className="px-2 py-1 bg-acid-yellow/20 text-[var(--acid-yellow)] text-xs font-theme-data rounded">
                      {selectedResult.medium_count} Medium
                    </span>
                  )}
                  {(selectedResult.low_count || 0) > 0 && (
                    <span className="px-2 py-1 bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] text-xs font-theme-data rounded">
                      {selectedResult.low_count} Low
                    </span>
                  )}
                </div>

                <div className="flex gap-2">
                  <a
                    href={`${apiBase}/api/gauntlet/${selectedResult.gauntlet_id}/receipt?format=html`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-1 py-2 text-center text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/20 rounded transition-colors"
                  >
                    VIEW RECEIPT
                  </a>
                  <a
                    href={`${apiBase}/api/gauntlet/${selectedResult.gauntlet_id}/heatmap?format=svg`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex-1 py-2 text-center text-xs font-theme-data bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/20 rounded transition-colors"
                  >
                    SVG HEATMAP
                  </a>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-text-muted font-theme-data text-sm">
                Select a result to view details
              </div>
            )}
          </div>

          {/* Heatmap */}
          {selectedResult && (heatmapData || heatmapError) && (
            <div className="bg-surface border border-acid-yellow/30 rounded-lg p-4">
              <h3 className="font-theme-data text-[var(--acid-yellow)] text-sm mb-4">
                RISK HEATMAP
              </h3>
              {heatmapError ? (
                <div className="p-3 bg-warning/10 border border-warning/30 rounded text-warning font-theme-data text-sm">
                  {heatmapError}
                </div>
              ) : heatmapData ? (
                <HeatmapVisualization data={heatmapData} />
              ) : null}
            </div>
          )}
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs font-theme-data pt-4 border-t border-border">
        {Object.entries(VERDICT_CONFIG)
          .slice(0, 5)
          .map(([verdict, config]) => (
            <div key={verdict} className="flex items-center gap-2">
              <div
                className={`w-4 h-4 rounded ${config.bg} ${config.border} border flex items-center justify-center`}
              >
                <span className={config.text}>{config.icon}</span>
              </div>
              <span className="text-text-muted">{verdict}</span>
            </div>
          ))}
      </div>
    </div>
  );
}

export default GauntletDashboard;
