'use client';

import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { ErrorWithRetry } from '@/components/ErrorWithRetry';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import {
  type Dimension,
  type Profile,
  type EvaluationResult,
  type CompareResult,
  getScoreColor,
} from './types';

export default function EvaluationPage() {
  const { config: backendConfig } = useBackend();
  const [dimensions, setDimensions] = useState<Dimension[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'evaluate' | 'compare' | 'dimensions' | 'profiles'>(
    'evaluate',
  );

  // Evaluate state
  const [query, setQuery] = useState('');
  const [response, setResponse] = useState('');
  const [context, setContext] = useState('');
  const [reference, setReference] = useState('');
  const [selectedProfile, setSelectedProfile] = useState('default');
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [threshold, setThreshold] = useState(3.5);
  const [evaluating, setEvaluating] = useState(false);
  const [evalResult, setEvalResult] = useState<EvaluationResult | null>(null);

  // Compare state
  const [compareQuery, setCompareQuery] = useState('');
  const [responseA, setResponseA] = useState('');
  const [responseB, setResponseB] = useState('');
  const [compareContext, setCompareContext] = useState('');
  const [comparing, setComparing] = useState(false);
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [dimRes, profRes] = await Promise.all([
        fetch(`${backendConfig.api}/api/evaluate/dimensions`),
        fetch(`${backendConfig.api}/api/evaluate/profiles`),
      ]);

      if (dimRes.ok) {
        const data = await dimRes.json();
        setDimensions(data.dimensions || []);
      }

      if (profRes.ok) {
        const data = await profRes.json();
        setProfiles(data.profiles || []);
      }

      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch evaluation data');
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleEvaluate = async () => {
    if (!query.trim() || !response.trim()) return;
    setEvaluating(true);
    setEvalResult(null);

    try {
      const res = await fetch(`${backendConfig.api}/api/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query,
          response,
          context: context || undefined,
          reference: reference || undefined,
          use_case: selectedProfile,
          dimensions: selectedDimensions.length > 0 ? selectedDimensions : undefined,
          threshold,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setEvalResult(data);
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.error || 'Evaluation failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Evaluation failed');
    } finally {
      setEvaluating(false);
    }
  };

  const handleCompare = async () => {
    if (!compareQuery.trim() || !responseA.trim() || !responseB.trim()) return;
    setComparing(true);
    setCompareResult(null);

    try {
      const res = await fetch(`${backendConfig.api}/api/evaluate/compare`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: compareQuery,
          response_a: responseA,
          response_b: responseB,
          context: compareContext || undefined,
          use_case: selectedProfile,
        }),
      });

      if (res.ok) {
        const data = await res.json();
        setCompareResult(data);
      } else {
        const errData = await res.json().catch(() => ({}));
        setError(errData.error || 'Comparison failed');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Comparison failed');
    } finally {
      setComparing(false);
    }
  };

  const toggleDimension = (dim: string) => {
    setSelectedDimensions((prev) =>
      prev.includes(dim) ? prev.filter((d) => d !== dim) : [...prev, dim],
    );
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <PanelErrorBoundary panelName="Evaluation">
          <div className="container mx-auto px-4 py-8">
            {/* Title */}
            <div className="mb-8">
              <h1 className="text-2xl font-theme-data font-bold text-[var(--accent)] mb-2">
                [LLM_JUDGE]
              </h1>
              <p className="text-text-muted font-theme-data text-sm">
                LLM-as-Judge evaluation for response quality assessment
              </p>
            </div>

            {error && <ErrorWithRetry error={error} onRetry={fetchData} className="mb-6" />}

            {loading ? (
              <div className="text-center py-12">
                <div className="text-[var(--accent)] font-theme-data animate-pulse">
                  Loading evaluation data...
                </div>
              </div>
            ) : (
              <>
                {/* Tabs */}
                <div className="flex gap-2 mb-6 border-b border-border pb-2">
                  {(['evaluate', 'compare', 'dimensions', 'profiles'] as const).map((tab) => (
                    <button
                      key={tab}
                      onClick={() => setActiveTab(tab)}
                      className={`px-4 py-2 font-theme-data text-sm transition-colors ${
                        activeTab === tab
                          ? 'text-[var(--accent)] border-b-2 border-[var(--accent)]'
                          : 'text-text-muted hover:text-text'
                      }`}
                    >
                      {tab.toUpperCase()}
                    </button>
                  ))}
                </div>

                {/* Evaluate Tab */}
                {activeTab === 'evaluate' && (
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <div className="space-y-4">
                      <div className="card p-4">
                        <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                          [INPUT]
                        </h3>

                        <div className="space-y-4">
                          <div>
                            <label className="block text-xs font-theme-data text-text-muted mb-1">
                              Query/Prompt *
                            </label>
                            <textarea
                              value={query}
                              onChange={(e) => setQuery(e.target.value)}
                              placeholder="Enter the original question or prompt..."
                              className="w-full h-24 p-3 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                            />
                          </div>

                          <div>
                            <label className="block text-xs font-theme-data text-text-muted mb-1">
                              Response to Evaluate *
                            </label>
                            <textarea
                              value={response}
                              onChange={(e) => setResponse(e.target.value)}
                              placeholder="Enter the response to evaluate..."
                              className="w-full h-32 p-3 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                            />
                          </div>

                          <div>
                            <label className="block text-xs font-theme-data text-text-muted mb-1">
                              Context (optional)
                            </label>
                            <textarea
                              value={context}
                              onChange={(e) => setContext(e.target.value)}
                              placeholder="Additional context..."
                              className="w-full h-16 p-3 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                            />
                          </div>

                          <div>
                            <label className="block text-xs font-theme-data text-text-muted mb-1">
                              Reference Answer (optional)
                            </label>
                            <textarea
                              value={reference}
                              onChange={(e) => setReference(e.target.value)}
                              placeholder="Ground truth or expected answer..."
                              className="w-full h-16 p-3 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                            />
                          </div>
                        </div>
                      </div>

                      <div className="card p-4">
                        <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                          [OPTIONS]
                        </h3>

                        <div className="space-y-4">
                          <div>
                            <label className="block text-xs font-theme-data text-text-muted mb-1">
                              Profile
                            </label>
                            <select
                              value={selectedProfile}
                              onChange={(e) => setSelectedProfile(e.target.value)}
                              className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                            >
                              {profiles.map((p) => (
                                <option key={p.id} value={p.id}>
                                  {p.name}
                                </option>
                              ))}
                            </select>
                          </div>

                          <div>
                            <label className="block text-xs font-theme-data text-text-muted mb-1">
                              Pass Threshold: {threshold.toFixed(1)}
                            </label>
                            <input
                              type="range"
                              min="1"
                              max="5"
                              step="0.5"
                              value={threshold}
                              onChange={(e) => setThreshold(parseFloat(e.target.value))}
                              className="w-full"
                            />
                          </div>

                          <div>
                            <label className="block text-xs font-theme-data text-text-muted mb-2">
                              Dimensions (optional)
                            </label>
                            <div className="flex flex-wrap gap-2">
                              {dimensions.map((d) => (
                                <button
                                  key={d.id}
                                  onClick={() => toggleDimension(d.id)}
                                  className={`px-2 py-1 text-xs font-theme-data border rounded transition-colors ${
                                    selectedDimensions.includes(d.id)
                                      ? 'border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                                      : 'border-border text-text-muted hover:border-[var(--accent)]/50'
                                  }`}
                                >
                                  {d.name}
                                </button>
                              ))}
                            </div>
                          </div>

                          <button
                            onClick={handleEvaluate}
                            disabled={evaluating || !query.trim() || !response.trim()}
                            className="w-full py-3 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
                          >
                            {evaluating ? '[EVALUATING...]' : '[EVALUATE]'}
                          </button>
                        </div>
                      </div>
                    </div>

                    <div className="card p-4">
                      <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                        [RESULT]
                      </h3>

                      {evalResult ? (
                        <div className="space-y-4">
                          <div className="grid grid-cols-2 gap-4">
                            <div className="p-4 bg-bg rounded border border-border">
                              <div className="text-xs font-theme-data text-text-muted mb-1">
                                Overall Score
                              </div>
                              <div
                                className={`text-3xl font-theme-data ${getScoreColor(evalResult.overall_score)}`}
                              >
                                {evalResult.overall_score.toFixed(2)}
                              </div>
                            </div>
                            <div className="p-4 bg-bg rounded border border-border">
                              <div className="text-xs font-theme-data text-text-muted mb-1">
                                Status
                              </div>
                              <div
                                className={`text-2xl font-theme-data ${evalResult.passed ? 'text-[var(--accent)]' : 'text-[var(--crimson)]'}`}
                              >
                                {evalResult.passed ? 'PASSED' : 'FAILED'}
                              </div>
                            </div>
                          </div>

                          <div>
                            <div className="text-xs font-theme-data text-text-muted mb-2">
                              Dimension Scores
                            </div>
                            <div className="space-y-2">
                              {Object.entries(evalResult.dimension_scores || {}).map(
                                ([dim, score]) => (
                                  <div key={dim} className="flex items-center gap-2">
                                    <span className="text-xs font-theme-data w-32 truncate">
                                      {dim}
                                    </span>
                                    <div className="flex-1 h-2 bg-bg rounded overflow-hidden">
                                      <div
                                        className="h-full bg-[var(--accent)] transition-all"
                                        style={{ width: `${(score / 5) * 100}%` }}
                                      />
                                    </div>
                                    <span
                                      className={`text-xs font-theme-data w-8 ${getScoreColor(score)}`}
                                    >
                                      {score.toFixed(1)}
                                    </span>
                                  </div>
                                ),
                              )}
                            </div>
                          </div>

                          {evalResult.reasoning && (
                            <div>
                              <div className="text-xs font-theme-data text-text-muted mb-1">
                                Reasoning
                              </div>
                              <div className="p-3 bg-bg rounded border border-border text-sm font-theme-data whitespace-pre-wrap">
                                {evalResult.reasoning}
                              </div>
                            </div>
                          )}
                        </div>
                      ) : (
                        <div className="text-center py-12 text-text-muted font-theme-data text-sm">
                          Enter a query and response, then click Evaluate
                        </div>
                      )}
                    </div>
                  </div>
                )}

                {/* Compare Tab */}
                {activeTab === 'compare' && (
                  <div className="space-y-6">
                    <div className="card p-4">
                      <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                        [PAIRWISE COMPARISON]
                      </h3>

                      <div className="space-y-4">
                        <div>
                          <label className="block text-xs font-theme-data text-text-muted mb-1">
                            Query/Prompt *
                          </label>
                          <textarea
                            value={compareQuery}
                            onChange={(e) => setCompareQuery(e.target.value)}
                            placeholder="Enter the original question..."
                            className="w-full h-20 p-3 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                          />
                        </div>

                        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div>
                            <label className="block text-xs font-theme-data text-text-muted mb-1">
                              Response A *
                            </label>
                            <textarea
                              value={responseA}
                              onChange={(e) => setResponseA(e.target.value)}
                              placeholder="First response..."
                              className="w-full h-32 p-3 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                            />
                          </div>
                          <div>
                            <label className="block text-xs font-theme-data text-text-muted mb-1">
                              Response B *
                            </label>
                            <textarea
                              value={responseB}
                              onChange={(e) => setResponseB(e.target.value)}
                              placeholder="Second response..."
                              className="w-full h-32 p-3 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                            />
                          </div>
                        </div>

                        <div>
                          <label className="block text-xs font-theme-data text-text-muted mb-1">
                            Context (optional)
                          </label>
                          <input
                            type="text"
                            value={compareContext}
                            onChange={(e) => setCompareContext(e.target.value)}
                            placeholder="Additional context..."
                            className="w-full p-2 bg-bg border border-border rounded font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none"
                          />
                        </div>

                        <button
                          onClick={handleCompare}
                          disabled={
                            comparing ||
                            !compareQuery.trim() ||
                            !responseA.trim() ||
                            !responseB.trim()
                          }
                          className="w-full py-3 font-theme-data text-sm bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50"
                        >
                          {comparing ? '[COMPARING...]' : '[COMPARE]'}
                        </button>
                      </div>
                    </div>

                    {compareResult && (
                      <div className="card p-4">
                        <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
                          [COMPARISON RESULT]
                        </h3>

                        <div className="space-y-4">
                          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                            <div
                              className={`p-4 bg-bg rounded border ${compareResult.winner === 'A' ? 'border-[var(--accent)]' : 'border-border'}`}
                            >
                              <div className="text-xs font-theme-data text-text-muted mb-1">
                                Response A
                              </div>
                              <div
                                className={`text-xl font-theme-data ${compareResult.winner === 'A' ? 'text-[var(--accent)]' : 'text-text-muted'}`}
                              >
                                {compareResult.winner === 'A'
                                  ? 'WINNER'
                                  : compareResult.winner === 'tie'
                                    ? 'TIE'
                                    : '-'}
                              </div>
                            </div>
                            <div className="p-4 bg-bg rounded border border-border text-center">
                              <div className="text-xs font-theme-data text-text-muted mb-1">
                                Confidence
                              </div>
                              <div className="text-xl font-theme-data text-[var(--acid-cyan)]">
                                {(compareResult.confidence * 100).toFixed(0)}%
                              </div>
                            </div>
                            <div
                              className={`p-4 bg-bg rounded border ${compareResult.winner === 'B' ? 'border-[var(--accent)]' : 'border-border'}`}
                            >
                              <div className="text-xs font-theme-data text-text-muted mb-1">
                                Response B
                              </div>
                              <div
                                className={`text-xl font-theme-data ${compareResult.winner === 'B' ? 'text-[var(--accent)]' : 'text-text-muted'}`}
                              >
                                {compareResult.winner === 'B'
                                  ? 'WINNER'
                                  : compareResult.winner === 'tie'
                                    ? 'TIE'
                                    : '-'}
                              </div>
                            </div>
                          </div>

                          <div>
                            <div className="text-xs font-theme-data text-text-muted mb-1">
                              Reasoning
                            </div>
                            <div className="p-3 bg-bg rounded border border-border text-sm font-theme-data whitespace-pre-wrap">
                              {compareResult.reasoning}
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                  </div>
                )}

                {/* Dimensions Tab */}
                {activeTab === 'dimensions' && (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {dimensions.map((dim) => (
                      <div key={dim.id} className="card p-4">
                        <h3 className="text-lg font-theme-data text-[var(--accent)] mb-2">
                          {dim.name}
                        </h3>
                        <p className="text-sm text-text-muted mb-4">{dim.description}</p>

                        <div className="space-y-2 text-xs font-theme-data">
                          <div className="grid grid-cols-[auto,1fr] gap-2">
                            <span className="text-[var(--accent)]">5:</span>
                            <span className="text-text-muted">{dim.rubric.score_5}</span>
                          </div>
                          <div className="grid grid-cols-[auto,1fr] gap-2">
                            <span className="text-[var(--acid-yellow)]">4:</span>
                            <span className="text-text-muted">{dim.rubric.score_4}</span>
                          </div>
                          <div className="grid grid-cols-[auto,1fr] gap-2">
                            <span className="text-text">3:</span>
                            <span className="text-text-muted">{dim.rubric.score_3}</span>
                          </div>
                          <div className="grid grid-cols-[auto,1fr] gap-2">
                            <span className="text-warning">2:</span>
                            <span className="text-text-muted">{dim.rubric.score_2}</span>
                          </div>
                          <div className="grid grid-cols-[auto,1fr] gap-2">
                            <span className="text-[var(--crimson)]">1:</span>
                            <span className="text-text-muted">{dim.rubric.score_1}</span>
                          </div>
                        </div>
                      </div>
                    ))}

                    {dimensions.length === 0 && (
                      <div className="col-span-2 text-center py-12 text-text-muted font-theme-data">
                        No dimensions available. LLM Judge may not be configured.
                      </div>
                    )}
                  </div>
                )}

                {/* Profiles Tab */}
                {activeTab === 'profiles' && (
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                    {profiles.map((profile) => (
                      <div key={profile.id} className="card p-4">
                        <h3 className="text-lg font-theme-data text-[var(--accent)] mb-2">
                          {profile.name}
                        </h3>
                        <p className="text-sm text-text-muted mb-4">{profile.description}</p>

                        <div className="text-xs font-theme-data text-text-muted mb-2">Weights:</div>
                        <div className="space-y-1">
                          {Object.entries(profile.weights).map(([dim, weight]) => (
                            <div key={dim} className="flex items-center gap-2">
                              <span className="flex-1 truncate">{dim}</span>
                              <div className="w-16 h-1.5 bg-bg rounded overflow-hidden">
                                <div
                                  className="h-full bg-[var(--accent)]"
                                  style={{ width: `${weight * 100}%` }}
                                />
                              </div>
                              <span className="w-8 text-right">{(weight * 100).toFixed(0)}%</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}

                    {profiles.length === 0 && (
                      <div className="col-span-3 text-center py-12 text-text-muted font-theme-data">
                        No profiles available. LLM Judge may not be configured.
                      </div>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
        </PanelErrorBoundary>
      </main>
    </>
  );
}
