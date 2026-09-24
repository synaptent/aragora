'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';

interface ABTest {
  id: string;
  agent: string;
  baseline_prompt_version: number;
  evolved_prompt_version: number;
  baseline_wins: number;
  evolved_wins: number;
  baseline_debates: number;
  evolved_debates: number;
  evolved_win_rate: number;
  baseline_win_rate: number;
  total_debates: number;
  sample_size: number;
  is_significant: boolean;
  started_at: string;
  concluded_at: string | null;
  status: 'active' | 'concluded' | 'cancelled';
  metadata: Record<string, unknown>;
}

interface ABTestResultsPanelProps {
  testId?: string;
  apiBase?: string;
  authToken?: string;
  onTestSelect?: (test: ABTest) => void;
  showListView?: boolean;
}

function StatCard({
  label,
  value,
  subValue,
  color = 'acid-green',
  isPercentage = false,
}: {
  label: string;
  value: number | string;
  subValue?: string;
  color?: string;
  isPercentage?: boolean;
}) {
  const formattedValue = isPercentage ? `${((value as number) * 100).toFixed(1)}%` : value;

  return (
    <div className="p-4 bg-surface/50 border border-border rounded-lg">
      <div className="text-xs font-theme-data text-text-muted mb-1">{label}</div>
      <div className={`text-2xl font-theme-data text-${color}`}>{formattedValue}</div>
      {subValue && <div className="text-xs font-theme-data text-text-muted mt-1">{subValue}</div>}
    </div>
  );
}

function WinRateBar({
  baselineRate,
  evolvedRate,
  totalDebates,
}: {
  baselineRate: number;
  evolvedRate: number;
  totalDebates: number;
}) {
  const drawRate = Math.max(0, 1 - baselineRate - evolvedRate);

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-xs font-theme-data text-text-muted">
        <span>BASELINE ({(baselineRate * 100).toFixed(1)}%)</span>
        <span>EVOLVED ({(evolvedRate * 100).toFixed(1)}%)</span>
      </div>
      <div className="h-8 bg-surface border border-border rounded flex overflow-hidden">
        <div
          className="bg-[var(--acid-cyan)]/60 flex items-center justify-center transition-all"
          style={{ width: `${baselineRate * 100}%` }}
        >
          {baselineRate > 0.1 && (
            <span className="text-xs font-theme-data text-bg font-bold">B</span>
          )}
        </div>
        {drawRate > 0.05 && (
          <div
            className="bg-text-muted/30 flex items-center justify-center transition-all"
            style={{ width: `${drawRate * 100}%` }}
          >
            <span className="text-xs font-theme-data text-text-muted">-</span>
          </div>
        )}
        <div
          className="bg-[var(--accent)]/60 flex items-center justify-center transition-all"
          style={{ width: `${evolvedRate * 100}%` }}
        >
          {evolvedRate > 0.1 && (
            <span className="text-xs font-theme-data text-bg font-bold">E</span>
          )}
        </div>
      </div>
      <div className="text-center text-xs font-theme-data text-text-muted">
        {totalDebates} total debates
      </div>
    </div>
  );
}

function TestCard({
  test,
  onClick,
  isSelected,
}: {
  test: ABTest;
  onClick?: () => void;
  isSelected?: boolean;
}) {
  const winner =
    test.evolved_win_rate > test.baseline_win_rate
      ? 'evolved'
      : test.baseline_win_rate > test.evolved_win_rate
        ? 'baseline'
        : 'tie';
  const winnerColor =
    winner === 'evolved' ? 'acid-green' : winner === 'baseline' ? 'acid-cyan' : 'acid-yellow';

  return (
    <button
      onClick={onClick}
      className={`
        w-full text-left p-4 rounded-lg border-2 transition-all
        ${
          test.status === 'active'
            ? 'border-[var(--accent)]/50 bg-[var(--accent)]/5'
            : test.status === 'concluded'
              ? 'border-[var(--acid-cyan)]/30 bg-surface/30'
              : 'border-warning/30 bg-warning/5'
        }
        ${isSelected ? 'ring-2 ring-offset-2 ring-acid-green ring-offset-bg' : ''}
        hover:brightness-110
      `}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="font-theme-data text-[var(--accent)] font-bold">{test.agent}</div>
          <div className="text-xs font-theme-data text-text-muted">
            v{test.baseline_prompt_version} vs v{test.evolved_prompt_version}
          </div>
        </div>
        <span
          className={`px-2 py-0.5 rounded text-xs font-theme-data ${
            test.status === 'active'
              ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
              : test.status === 'concluded'
                ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]'
                : 'bg-warning/20 text-warning'
          }`}
        >
          {test.status.toUpperCase()}
        </span>
      </div>

      <div className="grid grid-cols-3 gap-3 text-center">
        <div>
          <div className="text-lg font-theme-data text-[var(--acid-cyan)]">
            {(test.baseline_win_rate * 100).toFixed(0)}%
          </div>
          <div className="text-xs font-theme-data text-text-muted">Baseline</div>
        </div>
        <div>
          <div className="text-lg font-theme-data text-text-muted">{test.total_debates}</div>
          <div className="text-xs font-theme-data text-text-muted">Debates</div>
        </div>
        <div>
          <div className="text-lg font-theme-data text-[var(--accent)]">
            {(test.evolved_win_rate * 100).toFixed(0)}%
          </div>
          <div className="text-xs font-theme-data text-text-muted">Evolved</div>
        </div>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs font-theme-data">
        {test.is_significant && (
          <span className={`text-${winnerColor}`}>
            * {winner === 'tie' ? 'TIE' : winner.toUpperCase()} LEADING
          </span>
        )}
        {!test.is_significant && <span className="text-text-muted">Not significant yet</span>}
        <span className="text-text-muted">{new Date(test.started_at).toLocaleDateString()}</span>
      </div>
    </button>
  );
}

export function ABTestResultsPanel({
  testId,
  apiBase = API_BASE_URL,
  authToken,
  onTestSelect,
  showListView = true,
}: ABTestResultsPanelProps) {
  const [tests, setTests] = useState<ABTest[]>([]);
  const [selectedTest, setSelectedTest] = useState<ABTest | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchTests = useCallback(async () => {
    try {
      setLoading(true);
      const headers: Record<string, string> = {};
      if (authToken) {
        headers['Authorization'] = `Bearer ${authToken}`;
      }

      const response = await fetch(`${apiBase}/api/evolution/ab-tests?limit=50`, { headers });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      setTests(data.tests || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch tests');
    } finally {
      setLoading(false);
    }
  }, [apiBase, authToken]);

  const fetchTestById = useCallback(
    async (id: string) => {
      try {
        const headers: Record<string, string> = {};
        if (authToken) {
          headers['Authorization'] = `Bearer ${authToken}`;
        }

        const response = await fetch(`${apiBase}/api/evolution/ab-tests/${id}`, { headers });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data = await response.json();
        setSelectedTest(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch test');
      }
    },
    [apiBase, authToken],
  );

  useEffect(() => {
    if (testId) {
      fetchTestById(testId);
    } else {
      fetchTests();
    }
  }, [testId, fetchTests, fetchTestById]);

  const handleTestSelect = (test: ABTest) => {
    setSelectedTest(test);
    if (onTestSelect) {
      onTestSelect(test);
    }
  };

  // Summary stats
  const summary = useMemo(() => {
    const active = tests.filter((t) => t.status === 'active').length;
    const concluded = tests.filter((t) => t.status === 'concluded').length;
    const significant = tests.filter((t) => t.is_significant).length;
    const avgImprovement = tests
      .filter((t) => t.status === 'concluded' && t.is_significant)
      .reduce((sum, t) => sum + (t.evolved_win_rate - t.baseline_win_rate), 0);
    const significantConcluded = tests.filter(
      (t) => t.status === 'concluded' && t.is_significant,
    ).length;

    return {
      active,
      concluded,
      significant,
      avgImprovement: significantConcluded > 0 ? avgImprovement / significantConcluded : 0,
      totalDebates: tests.reduce((sum, t) => sum + t.total_debates, 0),
    };
  }, [tests]);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="font-theme-data text-[var(--accent)] text-sm">A/B TEST RESULTS</h4>
        <button
          onClick={fetchTests}
          disabled={loading}
          className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50"
        >
          {loading ? 'LOADING...' : 'REFRESH'}
        </button>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="ACTIVE TESTS" value={summary.active} color="acid-green" />
        <StatCard label="CONCLUDED" value={summary.concluded} color="acid-cyan" />
        <StatCard label="SIGNIFICANT" value={summary.significant} color="acid-yellow" />
        <StatCard
          label="AVG IMPROVEMENT"
          value={summary.avgImprovement}
          isPercentage={true}
          color={summary.avgImprovement > 0 ? 'acid-green' : 'acid-red'}
        />
        <StatCard label="TOTAL DEBATES" value={summary.totalDebates} color="text" />
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-warning/10 border border-warning/30 rounded-lg">
          <div className="text-warning font-theme-data text-sm">{error}</div>
        </div>
      )}

      {/* Main content */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* Test list */}
        {showListView && (
          <div className="lg:col-span-1 space-y-3 max-h-[500px] overflow-y-auto">
            {loading && tests.length === 0 && (
              <div className="text-center py-8">
                <div className="text-[var(--accent)] font-theme-data animate-pulse">
                  Loading tests...
                </div>
              </div>
            )}

            {!loading && tests.length === 0 && (
              <div className="text-center py-8 border border-[var(--accent)]/20 rounded-lg bg-surface/50">
                <div className="text-text-muted font-theme-data text-sm">No A/B tests found</div>
              </div>
            )}

            {tests.map((test) => (
              <TestCard
                key={test.id}
                test={test}
                onClick={() => handleTestSelect(test)}
                isSelected={selectedTest?.id === test.id}
              />
            ))}
          </div>
        )}

        {/* Selected test detail */}
        <div
          className={`${showListView ? 'lg:col-span-2' : 'lg:col-span-3'} bg-surface border border-[var(--acid-cyan)]/30 rounded-lg p-6`}
        >
          {selectedTest ? (
            <div className="space-y-6">
              {/* Test header */}
              <div className="flex items-start justify-between">
                <div>
                  <h3 className="text-xl font-theme-data text-[var(--accent)]">
                    {selectedTest.agent}
                  </h3>
                  <div className="text-sm font-theme-data text-text-muted mt-1">
                    Test ID: {selectedTest.id.slice(0, 12)}...
                  </div>
                </div>
                <span
                  className={`px-3 py-1 rounded text-sm font-theme-data ${
                    selectedTest.status === 'active'
                      ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                      : selectedTest.status === 'concluded'
                        ? 'bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)]'
                        : 'bg-warning/20 text-warning'
                  }`}
                >
                  {selectedTest.status.toUpperCase()}
                </span>
              </div>

              {/* Version comparison */}
              <div className="grid md:grid-cols-2 gap-6">
                <div className="p-4 border border-[var(--acid-cyan)]/30 rounded-lg">
                  <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3">
                    BASELINE (v{selectedTest.baseline_prompt_version})
                  </div>
                  <div className="text-4xl font-theme-data text-[var(--acid-cyan)] mb-2">
                    {(selectedTest.baseline_win_rate * 100).toFixed(1)}%
                  </div>
                  <div className="text-sm font-theme-data text-text-muted">
                    {selectedTest.baseline_wins} wins / {selectedTest.baseline_debates} debates
                  </div>
                </div>

                <div className="p-4 border border-[var(--accent)]/30 rounded-lg">
                  <div className="text-xs font-theme-data text-[var(--accent)] mb-3">
                    EVOLVED (v{selectedTest.evolved_prompt_version})
                  </div>
                  <div className="text-4xl font-theme-data text-[var(--accent)] mb-2">
                    {(selectedTest.evolved_win_rate * 100).toFixed(1)}%
                  </div>
                  <div className="text-sm font-theme-data text-text-muted">
                    {selectedTest.evolved_wins} wins / {selectedTest.evolved_debates} debates
                  </div>
                </div>
              </div>

              {/* Win rate bar */}
              <WinRateBar
                baselineRate={selectedTest.baseline_win_rate}
                evolvedRate={selectedTest.evolved_win_rate}
                totalDebates={selectedTest.total_debates}
              />

              {/* Analysis */}
              <div className="p-4 bg-surface/50 border border-border rounded-lg">
                <div className="text-xs font-theme-data text-[var(--acid-yellow)] mb-3">
                  ANALYSIS
                </div>
                <div className="space-y-2 text-sm font-theme-data">
                  <div className="flex justify-between">
                    <span className="text-text-muted">Improvement:</span>
                    <span
                      className={
                        selectedTest.evolved_win_rate > selectedTest.baseline_win_rate
                          ? 'text-[var(--accent)]'
                          : 'text-acid-red'
                      }
                    >
                      {selectedTest.evolved_win_rate > selectedTest.baseline_win_rate ? '+' : ''}
                      {(
                        (selectedTest.evolved_win_rate - selectedTest.baseline_win_rate) *
                        100
                      ).toFixed(1)}
                      %
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-muted">Sample Size:</span>
                    <span className="text-text">{selectedTest.sample_size}</span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-muted">Statistical Significance:</span>
                    <span
                      className={
                        selectedTest.is_significant ? 'text-[var(--accent)]' : 'text-warning'
                      }
                    >
                      {selectedTest.is_significant ? 'YES' : 'NOT YET'}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-text-muted">Started:</span>
                    <span className="text-text">
                      {new Date(selectedTest.started_at).toLocaleString()}
                    </span>
                  </div>
                  {selectedTest.concluded_at && (
                    <div className="flex justify-between">
                      <span className="text-text-muted">Concluded:</span>
                      <span className="text-text">
                        {new Date(selectedTest.concluded_at).toLocaleString()}
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Recommendation */}
              {selectedTest.is_significant && selectedTest.status === 'concluded' && (
                <div
                  className={`p-4 rounded-lg ${
                    selectedTest.evolved_win_rate > selectedTest.baseline_win_rate
                      ? 'bg-[var(--accent)]/10 border border-[var(--accent)]/30'
                      : 'bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30'
                  }`}
                >
                  <div className="text-xs font-theme-data text-text-muted mb-2">RECOMMENDATION</div>
                  <div
                    className={`font-theme-data ${
                      selectedTest.evolved_win_rate > selectedTest.baseline_win_rate
                        ? 'text-[var(--accent)]'
                        : 'text-[var(--acid-cyan)]'
                    }`}
                  >
                    {selectedTest.evolved_win_rate > selectedTest.baseline_win_rate
                      ? `ADOPT evolved prompt v${selectedTest.evolved_prompt_version} - ${((selectedTest.evolved_win_rate - selectedTest.baseline_win_rate) * 100).toFixed(1)}% improvement`
                      : `KEEP baseline prompt v${selectedTest.baseline_prompt_version} - evolved version underperformed`}
                  </div>
                </div>
              )}

              {/* Metadata */}
              {selectedTest.metadata && Object.keys(selectedTest.metadata).length > 0 && (
                <div className="p-4 bg-surface/50 border border-border rounded-lg">
                  <div className="text-xs font-theme-data text-text-muted mb-2">METADATA</div>
                  <pre className="text-xs font-theme-data text-text overflow-x-auto">
                    {JSON.stringify(selectedTest.metadata, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          ) : (
            <div className="text-center text-text-muted font-theme-data py-12">
              Select a test to view detailed results
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ABTestResultsPanel;
