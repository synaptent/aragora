'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';

interface MLCapabilities {
  routing: boolean;
  scoring: boolean;
  consensus: boolean;
  embeddings: boolean;
  training_export: boolean;
}

interface MLModelsResponse {
  capabilities: MLCapabilities;
  models: Record<string, unknown>;
  version: string;
}

interface MLStatsResponse {
  stats: {
    routing?: { registered_agents: number; historical_records: number };
    consensus?: {
      calibration_samples: number;
      accuracy: number;
      precision: number;
      recall: number;
    };
  };
  status: string;
}

interface RoutingResult {
  selected_agents: string[];
  task_type: string;
  confidence: number;
  reasoning: string[];
  agent_scores: Record<string, number>;
  diversity_score: number;
}

interface ScoringResult {
  overall: number;
  coherence: number;
  completeness: number;
  relevance: number;
  clarity: number;
  confidence: number;
  is_high_quality: boolean;
  needs_review: boolean;
}

interface ConsensusPrediction {
  will_converge: boolean;
  confidence: number;
  estimated_rounds: number;
  risk_factors: string[];
  recommended_actions: string[];
}

interface MLDashboardProps {
  apiBase: string;
}

export function MLDashboard({ apiBase: _apiBase }: MLDashboardProps) {
  const [capabilities, setCapabilities] = useState<MLCapabilities | null>(null);
  const [stats, setStats] = useState<MLStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Routing state
  const [routingTask, setRoutingTask] = useState('');
  const [availableAgents, setAvailableAgents] = useState(
    'anthropic-api,openai-api,grok,deepseek,mistral',
  );
  const [teamSize, setTeamSize] = useState(3);
  const [routingResult, setRoutingResult] = useState<RoutingResult | null>(null);
  const [routingLoading, setRoutingLoading] = useState(false);

  // Scoring state
  const [scoreText, setScoreText] = useState('');
  const [scoreTask, setScoreTask] = useState('');
  const [scoringResult, setScoringResult] = useState<ScoringResult | null>(null);
  const [scoringLoading, setScoringLoading] = useState(false);

  // Consensus prediction state
  const [predictionTask, setPredictionTask] = useState('');
  const [predictionAgents, setPredictionAgents] = useState('anthropic-api,openai-api,grok');
  const [predictionResult, setPredictionResult] = useState<ConsensusPrediction | null>(null);
  const [predictionLoading, setPredictionLoading] = useState(false);

  // Active tab
  const [activeTab, setActiveTab] = useState<'route' | 'score' | 'predict' | 'stats'>('stats');

  const fetchStats = useCallback(async () => {
    setLoading(true);
    setError(null);

    // Fetch both models (capabilities) and stats in parallel
    const [modelsRes, statsRes] = await Promise.all([
      apiFetch<MLModelsResponse>('/api/ml/models'),
      apiFetch<MLStatsResponse>('/api/ml/stats'),
    ]);

    if (modelsRes.error) {
      setError(modelsRes.error);
    } else if (modelsRes.data) {
      setCapabilities(modelsRes.data.capabilities);
    }

    if (statsRes.data) {
      setStats(statsRes.data);
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    fetchStats();
  }, [fetchStats]);

  const handleRouting = async () => {
    if (!routingTask.trim()) return;
    setRoutingLoading(true);
    setRoutingResult(null);

    const agents = availableAgents
      .split(',')
      .map((a) => a.trim())
      .filter(Boolean);
    const { data, error: routeError } = await apiFetch<RoutingResult>('/api/ml/route', {
      method: 'POST',
      body: JSON.stringify({ task: routingTask, available_agents: agents, team_size: teamSize }),
    });

    if (routeError) {
      setError(routeError);
    } else if (data) {
      setRoutingResult(data);
    }
    setRoutingLoading(false);
  };

  const handleScoring = async () => {
    if (!scoreText.trim()) return;
    setScoringLoading(true);
    setScoringResult(null);

    // Backend expects 'text' and 'context', not 'response' and 'task'
    const { data, error: scoreError } = await apiFetch<ScoringResult>('/api/ml/score', {
      method: 'POST',
      body: JSON.stringify({ text: scoreText, context: scoreTask || undefined }),
    });

    if (scoreError) {
      setError(scoreError);
    } else if (data) {
      setScoringResult(data);
    }
    setScoringLoading(false);
  };

  const handlePrediction = async () => {
    if (!predictionTask.trim()) return;
    setPredictionLoading(true);
    setPredictionResult(null);

    const agents = predictionAgents
      .split(',')
      .map((a) => a.trim())
      .filter(Boolean);
    const { data, error: predError } = await apiFetch<ConsensusPrediction>('/api/ml/consensus', {
      method: 'POST',
      body: JSON.stringify({ task: predictionTask, agents: agents }),
    });

    if (predError) {
      setError(predError);
    } else if (data) {
      setPredictionResult(data);
    }
    setPredictionLoading(false);
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
        {(['stats', 'route', 'score', 'predict'] as const).map((tab) => (
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

      {/* Stats Tab */}
      {activeTab === 'stats' && (
        <div className="card p-6 space-y-6">
          <h3 className="text-lg font-theme-data text-[var(--accent)]">ML Module Status</h3>

          {capabilities && (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <StatusIndicator label="Agent Router" available={capabilities.routing} />
              <StatusIndicator label="Quality Scorer" available={capabilities.scoring} />
              <StatusIndicator label="Consensus Predictor" available={capabilities.consensus} />
              <StatusIndicator label="Embeddings" available={capabilities.embeddings} />
              <StatusIndicator label="Training Exporter" available={capabilities.training_export} />
            </div>
          )}

          {stats?.stats && (
            <div className="space-y-4 mt-6">
              {stats.stats.routing && (
                <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded">
                  <h4 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3">
                    Routing Stats
                  </h4>
                  <div className="grid grid-cols-2 gap-4">
                    <MetricCard
                      label="Registered Agents"
                      value={stats.stats.routing.registered_agents}
                    />
                    <MetricCard
                      label="Historical Records"
                      value={stats.stats.routing.historical_records}
                    />
                  </div>
                </div>
              )}

              {stats.stats.consensus && (
                <div className="p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded">
                  <h4 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-3">
                    Consensus Predictor Calibration
                  </h4>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <MetricCard
                      label="Calibration Samples"
                      value={stats.stats.consensus.calibration_samples}
                    />
                    <MetricCard
                      label="Accuracy"
                      value={`${(stats.stats.consensus.accuracy * 100).toFixed(1)}%`}
                    />
                    <MetricCard
                      label="Precision"
                      value={`${(stats.stats.consensus.precision * 100).toFixed(1)}%`}
                    />
                    <MetricCard
                      label="Recall"
                      value={`${(stats.stats.consensus.recall * 100).toFixed(1)}%`}
                    />
                  </div>
                </div>
              )}

              <div className="text-xs font-theme-data text-text-muted">
                Status:{' '}
                <span
                  className={
                    stats.status === 'healthy'
                      ? 'text-[var(--accent)]'
                      : 'text-[var(--acid-yellow)]'
                  }
                >
                  {stats.status.toUpperCase()}
                </span>
              </div>
            </div>
          )}

          {!capabilities && !stats && (
            <div className="text-center py-8 text-text-muted font-theme-data">
              ML module not available. Check if the backend has ML dependencies installed.
            </div>
          )}

          <button
            onClick={fetchStats}
            className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors"
          >
            [REFRESH STATS]
          </button>
        </div>
      )}

      {/* Routing Tab */}
      {activeTab === 'route' && (
        <div className="card p-6 space-y-4">
          <h3 className="text-lg font-theme-data text-[var(--accent)]">Agent Routing</h3>
          <p className="text-xs text-text-muted font-theme-data">
            Get ML-based recommendations for which agents to include in a debate team.
          </p>

          <div className="space-y-3">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Task Description
              </label>
              <textarea
                value={routingTask}
                onChange={(e) => setRoutingTask(e.target.value)}
                placeholder="Describe the task for the debate..."
                className="w-full h-24 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Available Agents (comma-separated)
                </label>
                <input
                  type="text"
                  value={availableAgents}
                  onChange={(e) => setAvailableAgents(e.target.value)}
                  className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Team Size
                </label>
                <input
                  type="number"
                  value={teamSize}
                  onChange={(e) => setTeamSize(parseInt(e.target.value) || 3)}
                  min={1}
                  max={10}
                  className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>
            </div>

            <button
              onClick={handleRouting}
              disabled={routingLoading || !routingTask.trim()}
              className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {routingLoading ? '[ROUTING...]' : '[GET RECOMMENDATION]'}
            </button>
          </div>

          {routingResult && (
            <div className="mt-6 p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded space-y-3">
              <h4 className="text-sm font-theme-data text-[var(--acid-cyan)]">Routing Result</h4>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-xs text-text-muted">Selected Agents:</span>
                  <div className="flex flex-wrap gap-2 mt-1">
                    {routingResult.selected_agents.map((agent) => (
                      <span
                        key={agent}
                        className="px-2 py-1 bg-[var(--accent)]/20 text-[var(--accent)] text-xs font-theme-data rounded"
                      >
                        {agent}
                      </span>
                    ))}
                  </div>
                </div>
                <div>
                  <span className="text-xs text-text-muted">Task Type:</span>
                  <p className="text-[var(--accent)] font-theme-data">{routingResult.task_type}</p>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-xs text-text-muted">Confidence:</span>
                  <ProgressBar value={routingResult.confidence} />
                </div>
                <div>
                  <span className="text-xs text-text-muted">Diversity Score:</span>
                  <ProgressBar value={routingResult.diversity_score} />
                </div>
              </div>

              {routingResult.reasoning.length > 0 && (
                <div>
                  <span className="text-xs text-text-muted">Reasoning:</span>
                  <ul className="mt-1 text-xs font-theme-data text-text-muted">
                    {routingResult.reasoning.map((r, i) => (
                      <li key={i}>- {r}</li>
                    ))}
                  </ul>
                </div>
              )}

              <div>
                <span className="text-xs text-text-muted">Agent Scores:</span>
                <div className="mt-1 space-y-1">
                  {Object.entries(routingResult.agent_scores)
                    .sort(([, a], [, b]) => b - a)
                    .map(([agent, score]) => (
                      <div key={agent} className="flex items-center gap-2">
                        <span className="text-xs font-theme-data w-32">{agent}</span>
                        <div className="flex-1">
                          <ProgressBar value={score} />
                        </div>
                      </div>
                    ))}
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Scoring Tab */}
      {activeTab === 'score' && (
        <div className="card p-6 space-y-4">
          <h3 className="text-lg font-theme-data text-[var(--accent)]">Quality Scoring</h3>
          <p className="text-xs text-text-muted font-theme-data">
            Analyze response quality across multiple dimensions.
          </p>

          <div className="space-y-3">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Response to Score
              </label>
              <textarea
                value={scoreText}
                onChange={(e) => setScoreText(e.target.value)}
                placeholder="Paste response text to analyze..."
                className="w-full h-32 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Original Task (optional)
              </label>
              <input
                type="text"
                value={scoreTask}
                onChange={(e) => setScoreTask(e.target.value)}
                placeholder="What task was this response for?"
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <button
              onClick={handleScoring}
              disabled={scoringLoading || !scoreText.trim()}
              className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {scoringLoading ? '[SCORING...]' : '[ANALYZE QUALITY]'}
            </button>
          </div>

          {scoringResult && (
            <div className="mt-6 p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded space-y-3">
              <h4 className="text-sm font-theme-data text-[var(--acid-cyan)]">Quality Analysis</h4>

              <div className="flex items-center gap-4">
                <div>
                  <span className="text-xs text-text-muted">Overall Quality:</span>
                  <div className="flex items-center gap-3 mt-1">
                    <ProgressBar value={scoringResult.overall} />
                    <span className="text-[var(--accent)] font-theme-data">
                      {(scoringResult.overall * 100).toFixed(0)}%
                    </span>
                  </div>
                </div>
                <div className="flex gap-2">
                  <span
                    className={`px-2 py-1 text-xs font-theme-data rounded ${scoringResult.is_high_quality ? 'bg-[var(--accent)]/20 text-[var(--accent)]' : 'bg-yellow-500/20 text-yellow-500'}`}
                  >
                    {scoringResult.is_high_quality ? 'HIGH QUALITY' : 'NEEDS IMPROVEMENT'}
                  </span>
                  {scoringResult.needs_review && (
                    <span className="px-2 py-1 text-xs font-theme-data rounded bg-yellow-500/20 text-yellow-500">
                      NEEDS REVIEW
                    </span>
                  )}
                </div>
              </div>

              <div>
                <span className="text-xs text-text-muted">Dimensions:</span>
                <div className="mt-1 space-y-1">
                  {[
                    { name: 'Coherence', value: scoringResult.coherence },
                    { name: 'Completeness', value: scoringResult.completeness },
                    { name: 'Relevance', value: scoringResult.relevance },
                    { name: 'Clarity', value: scoringResult.clarity },
                  ].map(({ name, value }) => (
                    <div key={name} className="flex items-center gap-2">
                      <span className="text-xs font-theme-data w-32">{name}</span>
                      <div className="flex-1">
                        <ProgressBar value={value} />
                      </div>
                      <span className="text-xs font-theme-data w-12 text-right">
                        {(value * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="text-xs text-text-muted">
                Confidence:{' '}
                <span className="text-[var(--acid-cyan)] font-theme-data">
                  {(scoringResult.confidence * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Prediction Tab */}
      {activeTab === 'predict' && (
        <div className="card p-6 space-y-4">
          <h3 className="text-lg font-theme-data text-[var(--accent)]">Consensus Prediction</h3>
          <p className="text-xs text-text-muted font-theme-data">
            Predict likelihood of consensus and estimated rounds to convergence.
          </p>

          <div className="space-y-3">
            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Task Description
              </label>
              <textarea
                value={predictionTask}
                onChange={(e) => setPredictionTask(e.target.value)}
                placeholder="Describe the debate topic..."
                className="w-full h-24 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Participating Agents (comma-separated)
              </label>
              <input
                type="text"
                value={predictionAgents}
                onChange={(e) => setPredictionAgents(e.target.value)}
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <button
              onClick={handlePrediction}
              disabled={predictionLoading || !predictionTask.trim()}
              className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {predictionLoading ? '[PREDICTING...]' : '[PREDICT CONSENSUS]'}
            </button>
          </div>

          {predictionResult && (
            <div className="mt-6 p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded space-y-3">
              <h4 className="text-sm font-theme-data text-[var(--acid-cyan)]">Prediction Result</h4>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <span className="text-xs text-text-muted">Will Converge:</span>
                  <p
                    className={`font-theme-data text-lg ${predictionResult.will_converge ? 'text-[var(--accent)]' : 'text-yellow-500'}`}
                  >
                    {predictionResult.will_converge ? 'YES' : 'UNCERTAIN'}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-text-muted">Confidence:</span>
                  <p className="font-theme-data text-lg text-[var(--accent)]">
                    {(predictionResult.confidence * 100).toFixed(0)}%
                  </p>
                </div>
                <div>
                  <span className="text-xs text-text-muted">Est. Rounds:</span>
                  <p className="font-theme-data text-lg text-[var(--acid-cyan)]">
                    {predictionResult.estimated_rounds}
                  </p>
                </div>
              </div>

              {predictionResult.risk_factors.length > 0 && (
                <div>
                  <span className="text-xs text-text-muted">Risk Factors:</span>
                  <ul className="mt-1 text-xs font-theme-data text-yellow-500">
                    {predictionResult.risk_factors.map((r, i) => (
                      <li key={i}>- {r}</li>
                    ))}
                  </ul>
                </div>
              )}

              {predictionResult.recommended_actions.length > 0 && (
                <div>
                  <span className="text-xs text-text-muted">Recommended Actions:</span>
                  <ul className="mt-1 text-xs font-theme-data text-[var(--acid-cyan)]">
                    {predictionResult.recommended_actions.map((a, i) => (
                      <li key={i}>- {a}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatusIndicator({ label, available }: { label: string; available: boolean }) {
  return (
    <div
      className={`p-3 rounded border ${available ? 'border-[var(--accent)]/30 bg-[var(--accent)]/5' : 'border-red-500/30 bg-red-500/5'}`}
    >
      <div className="flex items-center gap-2">
        <div
          className={`w-2 h-2 rounded-full ${available ? 'bg-[var(--accent)] animate-pulse' : 'bg-red-500'}`}
        />
        <span className="text-xs font-theme-data">{label}</span>
      </div>
      <p
        className={`text-xs font-theme-data mt-1 ${available ? 'text-[var(--accent)]' : 'text-red-400'}`}
      >
        {available ? 'ONLINE' : 'UNAVAILABLE'}
      </p>
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="p-3 rounded border border-[var(--accent)]/20 bg-surface">
      <p className="text-xs font-theme-data text-text-muted">{label}</p>
      <p className="text-lg font-theme-data text-[var(--accent)]">{value}</p>
    </div>
  );
}

function ProgressBar({ value }: { value: number }) {
  const pct = Math.min(100, Math.max(0, value * 100));
  return (
    <div className="h-2 bg-surface rounded overflow-hidden flex-1">
      <div
        className="h-full bg-[var(--accent)] transition-all duration-300"
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}
