'use client';

import { useState, useCallback, useMemo, useEffect } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import type { StreamEvent } from '@/types/events';
import { API_BASE_URL } from '@/config';

import type { MatrixDebateResult, ScenarioInput, FilterState, ViewMode } from './types';
import { MetricCard } from './MetricCard';
import { ScenarioCard } from './ScenarioCard';
import { ScenarioBuilder } from './ScenarioBuilder';
import { CompareView } from './CompareView';
import { GridView } from './GridView';

export interface ScenarioMatrixViewProps {
  events?: StreamEvent[];
  initialMatrixId?: string | null;
}

export function ScenarioMatrixView({ events = [], initialMatrixId }: ScenarioMatrixViewProps) {
  const [task, setTask] = useState('');
  const [scenarios, setScenarios] = useState<ScenarioInput[]>([
    { name: 'Baseline', parameters: {}, constraints: [], is_baseline: true },
  ]);
  const [result, setResult] = useState<MatrixDebateResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedScenarios, setExpandedScenarios] = useState<Set<number>>(new Set());
  const [viewMode, setViewMode] = useState<ViewMode>('list');
  const [compareIndexes, setCompareIndexes] = useState<[number, number] | null>(null);
  const [filters, setFilters] = useState<FilterState>({
    consensusOnly: false,
    minConfidence: 0,
    searchTerm: '',
  });

  // Listen for matrix debate events
  const latestMatrixEvent = useMemo(() => {
    const relevant = events.filter(
      (e) => e.type === 'scenario_complete' || e.type === 'matrix_complete',
    );
    return relevant[relevant.length - 1];
  }, [events]);

  // Auto-fetch matrix when initialMatrixId is provided
  useEffect(() => {
    if (!initialMatrixId) return;

    const fetchInitialMatrix = async () => {
      try {
        setLoading(true);
        const apiUrl = API_BASE_URL;
        const response = await fetch(`${apiUrl}/api/debates/matrix/${initialMatrixId}`);
        if (response.ok) {
          const data = await response.json();
          setResult(data);
          setTask(data.task || '');
        } else {
          setError(`Failed to load matrix: ${initialMatrixId}`);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load matrix');
      } finally {
        setLoading(false);
      }
    };

    fetchInitialMatrix();
  }, [initialMatrixId]);

  // Refresh on matrix events
  useEffect(() => {
    if (latestMatrixEvent && result) {
      // Re-fetch the matrix result
      const refreshResult = async () => {
        try {
          const apiUrl = API_BASE_URL;
          const response = await fetch(`${apiUrl}/api/debates/matrix/${result.matrix_id}`);
          if (response.ok) {
            const data = await response.json();
            setResult(data);
          }
        } catch {
          // Ignore refresh errors
        }
      };
      refreshResult();
    }
  }, [latestMatrixEvent, result]);

  // Filter results
  const filteredResults = useMemo(() => {
    if (!result) return [];
    return result.results.filter((r) => {
      if (filters.consensusOnly && !r.consensus_reached) return false;
      if (r.confidence < filters.minConfidence) return false;
      if (filters.searchTerm) {
        const term = filters.searchTerm.toLowerCase();
        if (
          !r.scenario_name.toLowerCase().includes(term) &&
          !r.final_answer.toLowerCase().includes(term)
        ) {
          return false;
        }
      }
      return true;
    });
  }, [result, filters]);

  const addScenario = useCallback(() => {
    setScenarios((prev) => [
      ...prev,
      { name: `Scenario ${prev.length + 1}`, parameters: {}, constraints: [], is_baseline: false },
    ]);
  }, []);

  const removeScenario = useCallback((index: number) => {
    setScenarios((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const updateScenario = useCallback((index: number, scenario: ScenarioInput) => {
    setScenarios((prev) => prev.map((s, i) => (i === index ? scenario : s)));
  }, []);

  const toggleExpanded = useCallback((index: number) => {
    setExpandedScenarios((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }, []);

  const runMatrix = async () => {
    if (!task.trim() || scenarios.length === 0) return;

    try {
      setLoading(true);
      setError(null);

      const apiUrl = API_BASE_URL;
      const response = await fetch(`${apiUrl}/api/debates/matrix`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          task,
          agents: ['claude', 'gpt4'],
          scenarios: scenarios.map((s) => ({
            name: s.name,
            parameters: s.parameters,
            constraints: s.constraints,
            is_baseline: s.is_baseline,
          })),
          max_rounds: 3,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to run matrix debate');
      }

      const data = await response.json();
      setResult(data);
      setExpandedScenarios(new Set());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run matrix debate');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-theme-data text-[var(--accent)]">{'>'} SCENARIO MATRIX</h2>
          <span className="text-xs font-theme-data text-text-muted">
            Parallel scenario comparison
          </span>
        </div>

        {/* Task input */}
        <div className="mb-4">
          <label className="text-xs font-theme-data text-text-muted block mb-1">BASE TASK</label>
          <textarea
            value={task}
            onChange={(e) => setTask(e.target.value)}
            placeholder="Enter the debate topic that will be explored across all scenarios..."
            className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:outline-none focus:border-[var(--accent)] resize-none"
            rows={2}
          />
        </div>

        {/* Scenario builder */}
        <div className="mb-4">
          <label className="text-xs font-theme-data text-text-muted block mb-2">
            SCENARIOS ({scenarios.length})
          </label>
          <ScenarioBuilder
            scenarios={scenarios}
            onAdd={addScenario}
            onRemove={removeScenario}
            onUpdate={updateScenario}
          />
        </div>

        {/* Run button */}
        <button
          onClick={runMatrix}
          disabled={loading || !task.trim() || scenarios.length === 0}
          className="w-full py-3 bg-[var(--accent)]/20 border border-[var(--accent)]/40 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'RUNNING MATRIX...' : 'RUN SCENARIO MATRIX'}
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="bg-surface border border-[var(--crimson)]/30 p-4">
          <div className="text-xs font-theme-data text-[var(--crimson)]">Error: {error}</div>
        </div>
      )}

      {/* Results */}
      {result && (
        <>
          {/* Summary metrics */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <MetricCard
              label="Scenarios"
              value={result.scenario_count}
              color="text-[var(--acid-cyan)]"
            />
            <MetricCard
              label="Consensus Rate"
              value={`${(result.comparison_matrix.consensus_rate * 100).toFixed(0)}%`}
              color={
                result.comparison_matrix.consensus_rate > 0.5
                  ? 'text-[var(--accent)]'
                  : 'text-yellow-400'
              }
            />
            <MetricCard
              label="Avg Confidence"
              value={`${(result.comparison_matrix.avg_confidence * 100).toFixed(0)}%`}
            />
            <MetricCard
              label="Avg Rounds"
              value={result.comparison_matrix.avg_rounds.toFixed(1)}
              color="text-gold"
            />
          </div>

          {/* Universal conclusions */}
          {result.universal_conclusions.length > 0 && (
            <div className="bg-surface border border-[var(--accent)]/30">
              <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
                <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
                  {'>'} UNIVERSAL CONCLUSIONS
                </span>
              </div>
              <div className="p-4 space-y-2">
                {result.universal_conclusions.map((conclusion, i) => (
                  <div
                    key={i}
                    className="px-3 py-2 bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-sm font-theme-data text-text"
                  >
                    {conclusion}
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Comparison view */}
          {compareIndexes &&
            result.results[compareIndexes[0]] &&
            result.results[compareIndexes[1]] && (
              <CompareView
                left={result.results[compareIndexes[0]]}
                right={result.results[compareIndexes[1]]}
                onClose={() => setCompareIndexes(null)}
              />
            )}

          {/* Scenario results */}
          <div className="bg-surface border border-[var(--acid-cyan)]/30">
            <div className="px-4 py-3 border-b border-[var(--acid-cyan)]/20 bg-bg/50 flex items-center justify-between flex-wrap gap-2">
              <span className="text-xs font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider">
                {'>'} SCENARIO RESULTS ({filteredResults.length}/{result.results.length})
              </span>

              {/* View mode toggle */}
              <div className="flex items-center gap-1">
                {(['list', 'grid'] as ViewMode[]).map((mode) => (
                  <button
                    key={mode}
                    onClick={() => setViewMode(mode)}
                    className={`px-2 py-1 text-[10px] font-theme-data transition-colors ${
                      viewMode === mode
                        ? 'bg-[var(--acid-cyan)] text-bg'
                        : 'text-text-muted hover:text-[var(--acid-cyan)]'
                    }`}
                  >
                    {mode.toUpperCase()}
                  </button>
                ))}
              </div>
            </div>

            {/* Filters */}
            <div className="px-4 py-2 border-b border-[var(--acid-cyan)]/10 bg-bg/30 flex items-center gap-4 flex-wrap">
              <input
                type="text"
                value={filters.searchTerm}
                onChange={(e) => setFilters({ ...filters, searchTerm: e.target.value })}
                placeholder="Search scenarios..."
                className="px-2 py-1 bg-bg border border-border text-xs font-theme-data text-text focus:outline-none focus:border-[var(--acid-cyan)]"
              />
              <label className="flex items-center gap-1 text-[10px] font-theme-data text-text-muted">
                <input
                  type="checkbox"
                  checked={filters.consensusOnly}
                  onChange={(e) => setFilters({ ...filters, consensusOnly: e.target.checked })}
                  className="accent-acid-green"
                />
                Consensus only
              </label>
              <label className="flex items-center gap-1 text-[10px] font-theme-data text-text-muted">
                Min confidence:
                <input
                  type="range"
                  min="0"
                  max="100"
                  value={filters.minConfidence * 100}
                  onChange={(e) =>
                    setFilters({ ...filters, minConfidence: parseInt(e.target.value) / 100 })
                  }
                  className="w-20 h-1 accent-acid-cyan"
                />
                <span className="text-[var(--acid-cyan)]">
                  {Math.round(filters.minConfidence * 100)}%
                </span>
              </label>
            </div>

            <div className="p-4">
              {viewMode === 'grid' ? (
                <GridView
                  results={filteredResults}
                  onSelectCompare={(left, right) => {
                    // Find original indexes from filtered results
                    const leftIdx = result.results.indexOf(filteredResults[left]);
                    const rightIdx = result.results.indexOf(filteredResults[right]);
                    setCompareIndexes([leftIdx, rightIdx]);
                  }}
                />
              ) : (
                <div className="space-y-3" role="list" aria-label="Scenario results">
                  {filteredResults.map((scenarioResult) => {
                    const originalIdx = result.results.indexOf(scenarioResult);
                    return (
                      <ScenarioCard
                        key={originalIdx}
                        result={scenarioResult}
                        isExpanded={expandedScenarios.has(originalIdx)}
                        onToggle={() => toggleExpanded(originalIdx)}
                        index={originalIdx}
                      />
                    );
                  })}
                  {filteredResults.length === 0 && (
                    <div className="text-center text-text-muted text-xs font-theme-data py-4">
                      No scenarios match your filters
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* Conditional conclusions */}
          {result.conditional_conclusions.length > 0 && (
            <div className="bg-surface border border-gold/30">
              <div className="px-4 py-3 border-b border-gold/20 bg-bg/50">
                <span className="text-xs font-theme-data text-gold uppercase tracking-wider">
                  {'>'} CONDITIONAL CONCLUSIONS
                </span>
              </div>
              <div className="p-4 space-y-3">
                {result.conditional_conclusions.map((cc, i) => (
                  <div key={i} className="p-3 bg-bg/50 border border-gold/20">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs font-theme-data text-gold">{cc.condition}</span>
                      <span className="text-xs font-theme-data text-text-muted">
                        ({(cc.confidence * 100).toFixed(0)}% confidence)
                      </span>
                    </div>
                    {Object.keys(cc.parameters).length > 0 && (
                      <div className="flex flex-wrap gap-1 mb-2">
                        {Object.entries(cc.parameters).map(([key, value]) => (
                          <span
                            key={key}
                            className="px-1 py-0.5 bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] text-[10px] font-theme-data"
                          >
                            {key}={String(value)}
                          </span>
                        ))}
                      </div>
                    )}
                    <div className="text-sm font-theme-data text-text">
                      {cc.conclusion.length > 300
                        ? cc.conclusion.slice(0, 300) + '...'
                        : cc.conclusion}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Comparison grid */}
          <div className="bg-surface border border-purple/30">
            <div className="px-4 py-3 border-b border-purple/20 bg-bg/50">
              <span className="text-xs font-theme-data text-purple uppercase tracking-wider">
                {'>'} COMPARISON GRID
              </span>
            </div>

            {/* Mobile card layout */}
            <div className="block md:hidden p-4 space-y-3">
              {result.results.map((r, i) => {
                const winnerColors = r.winner ? getAgentColors(r.winner) : null;
                return (
                  <div
                    key={i}
                    className={`p-3 border ${
                      r.is_baseline ? 'border-gold/40 bg-gold/5' : 'border-purple/20 bg-bg/30'
                    }`}
                  >
                    <div className="flex items-center justify-between mb-3">
                      <span
                        className={`text-sm font-theme-data ${r.is_baseline ? 'text-gold' : 'text-text'}`}
                      >
                        {r.scenario_name}
                      </span>
                      {r.is_baseline && (
                        <span className="text-[10px] font-theme-data text-gold">[BASELINE]</span>
                      )}
                    </div>
                    <div className="grid grid-cols-2 gap-2 text-xs font-theme-data">
                      <div className="flex justify-between items-center p-2 bg-bg/50 rounded">
                        <span className="text-text-muted">Consensus</span>
                        <span
                          className={`px-2 py-0.5 ${
                            r.consensus_reached
                              ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                              : 'bg-[var(--crimson)]/20 text-[var(--crimson)]'
                          }`}
                        >
                          {r.consensus_reached ? 'YES' : 'NO'}
                        </span>
                      </div>
                      <div className="flex justify-between items-center p-2 bg-bg/50 rounded">
                        <span className="text-text-muted">Confidence</span>
                        <span className="text-[var(--acid-cyan)]">
                          {(r.confidence * 100).toFixed(0)}%
                        </span>
                      </div>
                      <div className="flex justify-between items-center p-2 bg-bg/50 rounded">
                        <span className="text-text-muted">Rounds</span>
                        <span className="text-text">{r.rounds_used}</span>
                      </div>
                      <div className="flex justify-between items-center p-2 bg-bg/50 rounded">
                        <span className="text-text-muted">Winner</span>
                        {r.winner && winnerColors ? (
                          <span className={`px-2 py-0.5 ${winnerColors.bg} ${winnerColors.text}`}>
                            {r.winner}
                          </span>
                        ) : (
                          <span className="text-text-muted">-</span>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Desktop table layout */}
            <div className="hidden md:block overflow-x-auto">
              <table className="w-full text-xs font-theme-data">
                <thead>
                  <tr className="bg-bg/50">
                    <th className="px-4 py-2 text-left text-text-muted">Scenario</th>
                    <th className="px-4 py-2 text-center text-text-muted">Consensus</th>
                    <th className="px-4 py-2 text-center text-text-muted">Confidence</th>
                    <th className="px-4 py-2 text-center text-text-muted">Rounds</th>
                    <th className="px-4 py-2 text-center text-text-muted">Winner</th>
                  </tr>
                </thead>
                <tbody>
                  {result.results.map((r, i) => {
                    const winnerColors = r.winner ? getAgentColors(r.winner) : null;
                    return (
                      <tr key={i} className="border-t border-border">
                        <td className="px-4 py-2">
                          <span className={r.is_baseline ? 'text-gold' : 'text-text'}>
                            {r.scenario_name}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-center">
                          <span
                            className={`px-2 py-0.5 ${
                              r.consensus_reached
                                ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                                : 'bg-[var(--crimson)]/20 text-[var(--crimson)]'
                            }`}
                          >
                            {r.consensus_reached ? 'YES' : 'NO'}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-center text-[var(--acid-cyan)]">
                          {(r.confidence * 100).toFixed(0)}%
                        </td>
                        <td className="px-4 py-2 text-center text-text-muted">{r.rounds_used}</td>
                        <td className="px-4 py-2 text-center">
                          {r.winner && winnerColors ? (
                            <span className={`px-2 py-0.5 ${winnerColors.bg} ${winnerColors.text}`}>
                              {r.winner}
                            </span>
                          ) : (
                            <span className="text-text-muted">-</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {/* Empty state */}
      {!result && !loading && (
        <div className="bg-surface border border-[var(--accent)]/30 p-8 text-center">
          <div className="text-4xl font-theme-data text-[var(--accent)]/30 mb-4">[...]</div>
          <div className="text-sm font-theme-data text-text-muted">
            Configure scenarios above and run the matrix to see results
          </div>
        </div>
      )}
    </div>
  );
}

// Re-export types and sub-components for external use
export type {
  ScenarioResult,
  ConditionalConclusion,
  ComparisonMatrix,
  MatrixDebateResult,
  ScenarioInput,
  FilterState,
  ViewMode,
} from './types';
export { MetricCard } from './MetricCard';
export { ScenarioCard } from './ScenarioCard';
export { ScenarioBuilder } from './ScenarioBuilder';
export { CompareView } from './CompareView';
export { GridView } from './GridView';

export default ScenarioMatrixView;
