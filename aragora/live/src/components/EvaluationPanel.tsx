'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';

interface Rubric {
  score_1: string;
  score_2: string;
  score_3: string;
  score_4: string;
  score_5: string;
}

interface Dimension {
  id: string;
  name: string;
  description: string;
  rubric: Rubric;
}

interface Profile {
  id: string;
  name: string;
  description: string;
  weights: Record<string, number>;
}

interface EvaluationScore {
  dimension: string;
  score: number;
  rationale: string;
}

interface EvaluationResult {
  overall_score: number;
  passed: boolean;
  scores: EvaluationScore[];
  summary: string;
  strengths: string[];
  weaknesses: string[];
}

interface ComparisonResult {
  winner: string;
  confidence: number;
  rationale: string;
  dimension_comparisons: Array<{ dimension: string; winner: string; explanation: string }>;
}

interface EvaluationPanelProps {
  apiBase: string;
}

export function EvaluationPanel({ apiBase: _apiBase }: EvaluationPanelProps) {
  const [dimensions, setDimensions] = useState<Dimension[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'evaluate' | 'compare' | 'dimensions' | 'profiles'>(
    'evaluate',
  );

  // Evaluate state
  const [evalQuery, setEvalQuery] = useState('');
  const [evalResponse, setEvalResponse] = useState('');
  const [evalContext, setEvalContext] = useState('');
  const [evalReference, setEvalReference] = useState('');
  const [selectedProfile, setSelectedProfile] = useState('default');
  const [selectedDimensions, setSelectedDimensions] = useState<string[]>([]);
  const [threshold, setThreshold] = useState(3.5);
  const [evalResult, setEvalResult] = useState<EvaluationResult | null>(null);
  const [evalLoading, setEvalLoading] = useState(false);

  // Compare state
  const [compareQuery, setCompareQuery] = useState('');
  const [responseA, setResponseA] = useState('');
  const [responseB, setResponseB] = useState('');
  const [compareContext, setCompareContext] = useState('');
  const [compareProfile, setCompareProfile] = useState('default');
  const [compareResult, setCompareResult] = useState<ComparisonResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);

  // Dimension detail state
  const [expandedDimension, setExpandedDimension] = useState<string | null>(null);

  const fetchMetadata = useCallback(async () => {
    setLoading(true);
    setError(null);

    const [dimRes, profRes] = await Promise.all([
      apiFetch<{ dimensions: Dimension[] }>('/api/evaluate/dimensions'),
      apiFetch<{ profiles: Profile[] }>('/api/evaluate/profiles'),
    ]);

    if (dimRes.error) {
      setError(dimRes.error);
    } else if (dimRes.data) {
      setDimensions(dimRes.data.dimensions);
    }

    if (profRes.data) {
      setProfiles(profRes.data.profiles);
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    fetchMetadata();
  }, [fetchMetadata]);

  const handleEvaluate = async () => {
    if (!evalQuery.trim() || !evalResponse.trim()) return;

    setEvalLoading(true);
    setEvalResult(null);
    setError(null);

    const { data, error: evalError } = await apiFetch<EvaluationResult>('/api/evaluate', {
      method: 'POST',
      body: JSON.stringify({
        query: evalQuery,
        response: evalResponse,
        context: evalContext || undefined,
        reference: evalReference || undefined,
        use_case: selectedProfile,
        dimensions: selectedDimensions.length > 0 ? selectedDimensions : undefined,
        threshold,
      }),
    });

    if (evalError) {
      setError(evalError);
    } else if (data) {
      setEvalResult(data);
    }
    setEvalLoading(false);
  };

  const handleCompare = async () => {
    if (!compareQuery.trim() || !responseA.trim() || !responseB.trim()) return;

    setCompareLoading(true);
    setCompareResult(null);
    setError(null);

    const { data, error: compareError } = await apiFetch<ComparisonResult>(
      '/api/evaluate/compare',
      {
        method: 'POST',
        body: JSON.stringify({
          query: compareQuery,
          response_a: responseA,
          response_b: responseB,
          context: compareContext || undefined,
          use_case: compareProfile,
          response_a_id: 'Response A',
          response_b_id: 'Response B',
        }),
      },
    );

    if (compareError) {
      setError(compareError);
    } else if (data) {
      setCompareResult(data);
    }
    setCompareLoading(false);
  };

  const toggleDimension = (dimId: string) => {
    setSelectedDimensions((prev) =>
      prev.includes(dimId) ? prev.filter((d) => d !== dimId) : [...prev, dimId],
    );
  };

  const getScoreColor = (score: number) => {
    if (score >= 4.5) return 'text-green-400';
    if (score >= 3.5) return 'text-[var(--accent)]';
    if (score >= 2.5) return 'text-yellow-400';
    if (score >= 1.5) return 'text-orange-400';
    return 'text-red-400';
  };

  const getScoreBg = (score: number) => {
    if (score >= 4.5) return 'bg-green-500';
    if (score >= 3.5) return 'bg-[var(--accent)]';
    if (score >= 2.5) return 'bg-yellow-500';
    if (score >= 1.5) return 'bg-orange-500';
    return 'bg-red-500';
  };

  if (loading) {
    return (
      <div className="card p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-6 bg-surface rounded w-1/4" />
          <div className="h-32 bg-surface rounded" />
          <div className="h-32 bg-surface rounded" />
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Error display */}
      {error && (
        <div className="p-4 border border-red-500/30 bg-red-500/10 rounded text-red-400 text-sm font-theme-data">
          {error}
          <button onClick={() => setError(null)} className="ml-4 text-red-500 hover:text-red-400">
            [DISMISS]
          </button>
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-2 border-b border-[var(--accent)]/30 pb-2">
        {(['evaluate', 'compare', 'dimensions', 'profiles'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-xs font-theme-data rounded-t transition-colors ${
              activeTab === tab
                ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 border-b-0'
                : 'text-text-muted hover:text-[var(--accent)] hover:bg-[var(--accent)]/5'
            }`}
          >
            [{tab.toUpperCase()}]
          </button>
        ))}
      </div>

      {/* Evaluate Tab */}
      {activeTab === 'evaluate' && (
        <div className="space-y-4">
          <div className="card p-6 space-y-4">
            <h3 className="text-lg font-theme-data text-[var(--accent)]">Evaluate Response</h3>
            <p className="text-xs text-text-muted font-theme-data">
              Use LLM-as-Judge to evaluate a response across multiple quality dimensions.
            </p>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Query/Prompt *
              </label>
              <textarea
                value={evalQuery}
                onChange={(e) => setEvalQuery(e.target.value)}
                placeholder="The original question or task..."
                className="w-full h-20 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Response to Evaluate *
              </label>
              <textarea
                value={evalResponse}
                onChange={(e) => setEvalResponse(e.target.value)}
                placeholder="The response to be evaluated..."
                className="w-full h-32 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Context (optional)
                </label>
                <textarea
                  value={evalContext}
                  onChange={(e) => setEvalContext(e.target.value)}
                  placeholder="Additional context..."
                  className="w-full h-20 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Reference Answer (optional)
                </label>
                <textarea
                  value={evalReference}
                  onChange={(e) => setEvalReference(e.target.value)}
                  placeholder="Ground truth or ideal answer..."
                  className="w-full h-20 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Evaluation Profile
                </label>
                <select
                  value={selectedProfile}
                  onChange={(e) => setSelectedProfile(e.target.value)}
                  className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
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
                  Pass Threshold
                  <span className="ml-2 text-[var(--accent)]">{threshold.toFixed(1)}</span>
                </label>
                <input
                  type="range"
                  value={threshold}
                  onChange={(e) => setThreshold(parseFloat(e.target.value))}
                  min={1}
                  max={5}
                  step={0.5}
                  className="w-full"
                />
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Dimensions
                </label>
                <div className="text-xs text-text-muted">
                  {selectedDimensions.length === 0
                    ? 'All (default)'
                    : `${selectedDimensions.length} selected`}
                </div>
              </div>
            </div>

            {/* Dimension selector */}
            <div className="flex flex-wrap gap-2">
              {dimensions.map((dim) => (
                <button
                  key={dim.id}
                  onClick={() => toggleDimension(dim.id)}
                  className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
                    selectedDimensions.includes(dim.id)
                      ? 'bg-[var(--accent)]/30 text-[var(--accent)] border border-[var(--accent)]/50'
                      : 'bg-surface text-text-muted hover:bg-[var(--accent)]/10 border border-transparent'
                  }`}
                >
                  {dim.name}
                </button>
              ))}
            </div>

            <button
              onClick={handleEvaluate}
              disabled={evalLoading || !evalQuery.trim() || !evalResponse.trim()}
              className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {evalLoading ? '[EVALUATING...]' : '[EVALUATE]'}
            </button>
          </div>

          {/* Evaluation Results */}
          {evalResult && (
            <div className="card p-6 space-y-4">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-theme-data text-[var(--acid-cyan)]">
                  Evaluation Results
                </h4>
                <span
                  className={`px-3 py-1 text-sm font-theme-data rounded ${
                    evalResult.passed
                      ? 'bg-green-500/20 text-green-400 border border-green-500/50'
                      : 'bg-red-500/20 text-red-400 border border-red-500/50'
                  }`}
                >
                  {evalResult.passed ? 'PASSED' : 'FAILED'}
                </span>
              </div>

              {/* Overall Score */}
              <div className="flex items-center gap-4">
                <div
                  className={`text-4xl font-theme-data font-bold ${getScoreColor(evalResult.overall_score)}`}
                >
                  {evalResult.overall_score.toFixed(2)}
                </div>
                <div className="flex-1">
                  <div className="h-3 bg-surface rounded overflow-hidden">
                    <div
                      className={`h-full ${getScoreBg(evalResult.overall_score)} transition-all`}
                      style={{ width: `${(evalResult.overall_score / 5) * 100}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-xs text-text-muted mt-1">
                    <span>1</span>
                    <span>Threshold: {threshold}</span>
                    <span>5</span>
                  </div>
                </div>
              </div>

              {/* Summary */}
              <div className="p-3 bg-surface border border-[var(--accent)]/20 rounded">
                <p className="text-sm font-theme-data text-text">{evalResult.summary}</p>
              </div>

              {/* Dimension Scores */}
              <div className="space-y-2">
                <h5 className="text-xs font-theme-data text-text-muted">DIMENSION SCORES</h5>
                {evalResult.scores.map((score) => (
                  <div
                    key={score.dimension}
                    className="p-3 bg-surface border border-[var(--accent)]/20 rounded"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-theme-data text-text">
                        {score.dimension
                          .replace(/_/g, ' ')
                          .replace(/\b\w/g, (l) => l.toUpperCase())}
                      </span>
                      <span className={`font-theme-data font-bold ${getScoreColor(score.score)}`}>
                        {score.score.toFixed(1)}/5
                      </span>
                    </div>
                    <div className="h-2 bg-bg rounded overflow-hidden mb-2">
                      <div
                        className={`h-full ${getScoreBg(score.score)}`}
                        style={{ width: `${(score.score / 5) * 100}%` }}
                      />
                    </div>
                    <p className="text-xs text-text-muted">{score.rationale}</p>
                  </div>
                ))}
              </div>

              {/* Strengths & Weaknesses */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {evalResult.strengths.length > 0 && (
                  <div className="p-3 bg-green-500/10 border border-green-500/30 rounded">
                    <h5 className="text-xs font-theme-data text-green-400 mb-2">STRENGTHS</h5>
                    <ul className="space-y-1">
                      {evalResult.strengths.map((s, i) => (
                        <li key={i} className="text-xs text-text-muted">
                          + {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {evalResult.weaknesses.length > 0 && (
                  <div className="p-3 bg-red-500/10 border border-red-500/30 rounded">
                    <h5 className="text-xs font-theme-data text-red-400 mb-2">WEAKNESSES</h5>
                    <ul className="space-y-1">
                      {evalResult.weaknesses.map((w, i) => (
                        <li key={i} className="text-xs text-text-muted">
                          - {w}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Compare Tab */}
      {activeTab === 'compare' && (
        <div className="space-y-4">
          <div className="card p-6 space-y-4">
            <h3 className="text-lg font-theme-data text-[var(--accent)]">Compare Responses</h3>
            <p className="text-xs text-text-muted font-theme-data">
              Pairwise comparison to determine which response is better.
            </p>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Query/Prompt *
              </label>
              <textarea
                value={compareQuery}
                onChange={(e) => setCompareQuery(e.target.value)}
                placeholder="The original question or task..."
                className="w-full h-20 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-[var(--acid-cyan)] mb-1">
                  Response A *
                </label>
                <textarea
                  value={responseA}
                  onChange={(e) => setResponseA(e.target.value)}
                  placeholder="First response..."
                  className="w-full h-32 p-3 bg-surface border border-[var(--acid-cyan)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--acid-cyan)]"
                />
              </div>

              <div>
                <label className="block text-xs font-theme-data text-purple-400 mb-1">
                  Response B *
                </label>
                <textarea
                  value={responseB}
                  onChange={(e) => setResponseB(e.target.value)}
                  placeholder="Second response..."
                  className="w-full h-32 p-3 bg-surface border border-purple-400/30 rounded font-theme-data text-sm focus:outline-none focus:border-purple-400"
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Context (optional)
                </label>
                <textarea
                  value={compareContext}
                  onChange={(e) => setCompareContext(e.target.value)}
                  placeholder="Additional context..."
                  className="w-full h-16 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Evaluation Profile
                </label>
                <select
                  value={compareProfile}
                  onChange={(e) => setCompareProfile(e.target.value)}
                  className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <button
              onClick={handleCompare}
              disabled={
                compareLoading || !compareQuery.trim() || !responseA.trim() || !responseB.trim()
              }
              className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {compareLoading ? '[COMPARING...]' : '[COMPARE]'}
            </button>
          </div>

          {/* Comparison Results */}
          {compareResult && (
            <div className="card p-6 space-y-4">
              <h4 className="text-sm font-theme-data text-[var(--acid-cyan)]">
                Comparison Results
              </h4>

              {/* Winner */}
              <div className="text-center p-6 bg-surface border border-[var(--accent)]/30 rounded">
                <div className="text-xs font-theme-data text-text-muted mb-2">WINNER</div>
                <div
                  className={`text-3xl font-theme-data font-bold ${
                    compareResult.winner === 'Response A'
                      ? 'text-[var(--acid-cyan)]'
                      : compareResult.winner === 'Response B'
                        ? 'text-purple-400'
                        : 'text-yellow-400'
                  }`}
                >
                  {compareResult.winner}
                </div>
                <div className="text-sm font-theme-data text-text-muted mt-2">
                  Confidence: {(compareResult.confidence * 100).toFixed(0)}%
                </div>
              </div>

              {/* Rationale */}
              <div className="p-3 bg-surface border border-[var(--accent)]/20 rounded">
                <h5 className="text-xs font-theme-data text-text-muted mb-2">RATIONALE</h5>
                <p className="text-sm font-theme-data text-text">{compareResult.rationale}</p>
              </div>

              {/* Dimension Comparisons */}
              {compareResult.dimension_comparisons &&
                compareResult.dimension_comparisons.length > 0 && (
                  <div className="space-y-2">
                    <h5 className="text-xs font-theme-data text-text-muted">DIMENSION BREAKDOWN</h5>
                    {compareResult.dimension_comparisons.map((comp, idx) => (
                      <div
                        key={idx}
                        className="p-3 bg-surface border border-[var(--accent)]/20 rounded"
                      >
                        <div className="flex items-center justify-between mb-1">
                          <span className="font-theme-data text-text text-sm">
                            {comp.dimension
                              .replace(/_/g, ' ')
                              .replace(/\b\w/g, (l) => l.toUpperCase())}
                          </span>
                          <span
                            className={`text-xs font-theme-data ${
                              comp.winner === 'Response A'
                                ? 'text-[var(--acid-cyan)]'
                                : comp.winner === 'Response B'
                                  ? 'text-purple-400'
                                  : 'text-yellow-400'
                            }`}
                          >
                            {comp.winner}
                          </span>
                        </div>
                        <p className="text-xs text-text-muted">{comp.explanation}</p>
                      </div>
                    ))}
                  </div>
                )}
            </div>
          )}
        </div>
      )}

      {/* Dimensions Tab */}
      {activeTab === 'dimensions' && (
        <div className="space-y-4">
          <div className="card p-6">
            <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
              Evaluation Dimensions
            </h3>
            <p className="text-xs text-text-muted font-theme-data mb-4">
              Click on a dimension to view its detailed rubric.
            </p>

            <div className="space-y-2">
              {dimensions.map((dim) => (
                <div
                  key={dim.id}
                  className="border border-[var(--accent)]/20 rounded overflow-hidden"
                >
                  <button
                    onClick={() =>
                      setExpandedDimension(expandedDimension === dim.id ? null : dim.id)
                    }
                    className="w-full p-3 flex items-center justify-between bg-surface hover:bg-[var(--accent)]/5 transition-colors"
                  >
                    <div className="text-left">
                      <span className="font-theme-data text-text">{dim.name}</span>
                      <p className="text-xs text-text-muted mt-1">{dim.description}</p>
                    </div>
                    <span className="text-[var(--accent)] font-theme-data text-xs">
                      {expandedDimension === dim.id ? '[-]' : '[+]'}
                    </span>
                  </button>

                  {expandedDimension === dim.id && (
                    <div className="p-4 bg-bg border-t border-[var(--accent)]/20 space-y-2">
                      <h5 className="text-xs font-theme-data text-[var(--acid-cyan)] mb-3">
                        SCORING RUBRIC
                      </h5>
                      {[5, 4, 3, 2, 1].map((score) => (
                        <div key={score} className="flex gap-3 items-start">
                          <span
                            className={`w-8 h-8 flex items-center justify-center rounded font-theme-data font-bold text-sm ${
                              score >= 4
                                ? 'bg-green-500/20 text-green-400'
                                : score === 3
                                  ? 'bg-yellow-500/20 text-yellow-400'
                                  : 'bg-red-500/20 text-red-400'
                            }`}
                          >
                            {score}
                          </span>
                          <p className="flex-1 text-xs text-text-muted">
                            {dim.rubric[`score_${score}` as keyof Rubric]}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Profiles Tab */}
      {activeTab === 'profiles' && (
        <div className="space-y-4">
          <div className="card p-6">
            <h3 className="text-lg font-theme-data text-[var(--accent)] mb-4">
              Evaluation Profiles
            </h3>
            <p className="text-xs text-text-muted font-theme-data mb-4">
              Pre-configured dimension weights for different use cases.
            </p>

            <div className="space-y-4">
              {profiles.map((profile) => (
                <div
                  key={profile.id}
                  className="p-4 border border-[var(--accent)]/20 rounded bg-surface"
                >
                  <div className="flex items-center justify-between mb-2">
                    <div>
                      <span className="font-theme-data text-text">{profile.name}</span>
                      {profile.id === 'default' && (
                        <span className="ml-2 px-2 py-0.5 text-xs bg-[var(--accent)]/20 text-[var(--accent)] rounded">
                          default
                        </span>
                      )}
                    </div>
                  </div>
                  <p className="text-xs text-text-muted mb-3">{profile.description}</p>

                  {/* Weight bars */}
                  <div className="space-y-1">
                    {Object.entries(profile.weights)
                      .sort((a, b) => b[1] - a[1])
                      .map(([dim, weight]) => (
                        <div key={dim} className="flex items-center gap-2">
                          <span className="w-24 text-xs font-theme-data text-text-muted truncate">
                            {dim.replace(/_/g, ' ')}
                          </span>
                          <div className="flex-1 h-2 bg-bg rounded overflow-hidden">
                            <div
                              className="h-full bg-[var(--accent)]"
                              style={{ width: `${weight * 100}%` }}
                            />
                          </div>
                          <span className="w-10 text-xs font-theme-data text-text-muted text-right">
                            {(weight * 100).toFixed(0)}%
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
