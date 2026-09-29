'use client';

import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';
import dynamic from 'next/dynamic';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';

const UncertaintyPanel = dynamic(
  () => import('@/components/UncertaintyPanel').then((m) => ({ default: m.UncertaintyPanel })),
  {
    ssr: false,
    loading: () => (
      <div className="card p-4 animate-pulse">
        <div className="h-[500px] bg-surface rounded" />
      </div>
    ),
  },
);

// Types
interface CalibrationAgent {
  agent: string;
  calibration_score: number;
  brier_score: number;
  accuracy: number;
  ece: number;
  predictions_count: number;
  correct_count: number;
  elo: number;
}

interface CalibrationBucket {
  x: number;
  expected: number;
  actual: number;
  count: number;
}

interface CalibrationVisualization {
  calibration_curves: Record<
    string,
    { buckets: CalibrationBucket[]; perfect_line: { x: number; y: number }[] }
  >;
  scatter_data: Array<{
    agent: string;
    accuracy: number;
    brier_score: number;
    ece: number;
    predictions: number;
    is_overconfident: boolean;
    is_underconfident: boolean;
  }>;
  confidence_histogram: Array<{ range: string; count: number }>;
  summary: {
    total_agents: number;
    avg_brier: number;
    avg_ece: number;
    best_calibrated: string | null;
    worst_calibrated: string | null;
  };
}

interface AgentCalibration {
  agent_id: string;
  calibration_quality: number;
  confidence_history: Array<{ confidence: number; was_correct?: boolean }>;
  calibration_history: Array<{ confidence: number; was_correct: boolean }>;
  brier_score: number | null;
}

type ActiveTab = 'debate' | 'leaderboard' | 'visualization' | 'agent';

export default function UncertaintyPage() {
  const { config: backendConfig } = useBackend();
  const apiBase = backendConfig.api;
  const [activeTab, setActiveTab] = useState<ActiveTab>('leaderboard');

  // Debate analysis state
  const [debateId, setDebateId] = useState<string>('');
  const [activeDebateId, setActiveDebateId] = useState<string | null>(null);

  // Calibration leaderboard state
  const [leaderboard, setLeaderboard] = useState<CalibrationAgent[]>([]);
  const [leaderboardLoading, setLeaderboardLoading] = useState(true);
  const [sortMetric, setSortMetric] = useState<'brier' | 'ece' | 'accuracy' | 'composite'>('brier');

  // Visualization state
  const [visualization, setVisualization] = useState<CalibrationVisualization | null>(null);
  const [vizLoading, setVizLoading] = useState(true);

  // Agent profile state
  const [selectedAgent, setSelectedAgent] = useState<string>('');
  const [agentCalibration, setAgentCalibration] = useState<AgentCalibration | null>(null);
  const [agentLoading, setAgentLoading] = useState(false);

  // Fetch leaderboard
  const fetchLeaderboard = useCallback(async () => {
    try {
      setLeaderboardLoading(true);
      const response = await fetch(
        `${apiBase}/api/calibration/leaderboard?metric=${sortMetric}&limit=20`,
      );
      if (response.ok) {
        const data = await response.json();
        setLeaderboard(data.agents || []);
      }
    } catch (error) {
      logger.error('Failed to fetch leaderboard:', error);
    } finally {
      setLeaderboardLoading(false);
    }
  }, [apiBase, sortMetric]);

  // Fetch visualization
  const fetchVisualization = useCallback(async () => {
    try {
      setVizLoading(true);
      const response = await fetch(`${apiBase}/api/calibration/visualization?limit=5`);
      if (response.ok) {
        const data = await response.json();
        setVisualization(data);
      }
    } catch (error) {
      logger.error('Failed to fetch visualization:', error);
    } finally {
      setVizLoading(false);
    }
  }, [apiBase]);

  // Fetch agent calibration
  const fetchAgentCalibration = useCallback(
    async (agentId: string) => {
      if (!agentId) return;
      try {
        setAgentLoading(true);
        const response = await fetch(`${apiBase}/api/uncertainty/agent/${agentId}`);
        if (response.ok) {
          const data = await response.json();
          setAgentCalibration(data);
        }
      } catch (error) {
        logger.error('Failed to fetch agent calibration:', error);
      } finally {
        setAgentLoading(false);
      }
    },
    [apiBase],
  );

  // Load data on mount and tab change
  useEffect(() => {
    if (activeTab === 'leaderboard') {
      fetchLeaderboard();
    } else if (activeTab === 'visualization') {
      fetchVisualization();
    }
  }, [activeTab, fetchLeaderboard, fetchVisualization]);

  // Handle debate load
  const handleLoadDebate = () => {
    if (debateId.trim()) {
      setActiveDebateId(debateId.trim());
    }
  };

  // Handle agent selection
  const handleSelectAgent = (agent: string) => {
    setSelectedAgent(agent);
    setActiveTab('agent');
    fetchAgentCalibration(agent);
  };

  // Color helpers
  const getScoreColor = (score: number, inverse = false) => {
    const value = inverse ? 1 - score : score;
    if (value >= 0.8) return 'text-[var(--accent)]';
    if (value >= 0.6) return 'text-[var(--acid-cyan)]';
    if (value >= 0.4) return 'text-warning';
    return 'text-error';
  };

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        <div className="container mx-auto px-4 py-6">
          <div className="mb-6">
            <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
              {'>'} UNCERTAINTY & CALIBRATION
            </h1>
            <p className="text-text-muted font-theme-data text-sm">
              Analyze collective confidence, calibration quality, and agent reliability.
            </p>
          </div>

          {/* Tab Navigation */}
          <div className="flex border-b border-[var(--accent)]/30 mb-6">
            {(['leaderboard', 'visualization', 'debate', 'agent'] as ActiveTab[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-4 py-2 font-theme-data text-sm uppercase transition-colors ${
                  activeTab === tab
                    ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-[var(--accent)]/5'
                    : 'text-text-muted hover:text-text'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* Leaderboard Tab */}
          {activeTab === 'leaderboard' && (
            <div className="space-y-4">
              {/* Sort Controls */}
              <div className="flex items-center gap-4">
                <span className="text-xs font-theme-data text-text-muted">SORT BY:</span>
                {(['brier', 'ece', 'accuracy', 'composite'] as const).map((metric) => (
                  <button
                    key={metric}
                    onClick={() => setSortMetric(metric)}
                    className={`px-3 py-1 text-xs font-theme-data border transition-colors ${
                      sortMetric === metric
                        ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/50'
                        : 'text-text-muted border-text-muted/30 hover:border-text-muted'
                    }`}
                  >
                    {metric.toUpperCase()}
                  </button>
                ))}
              </div>

              {/* Leaderboard Table */}
              {leaderboardLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-pulse text-text-muted font-theme-data">
                    Loading leaderboard...
                  </div>
                </div>
              ) : leaderboard.length === 0 ? (
                <div className="text-center py-12 border border-[var(--accent)]/20 rounded">
                  <p className="text-text-muted font-theme-data text-sm">
                    No calibration data available yet.
                  </p>
                </div>
              ) : (
                <div className="border border-[var(--accent)]/30 rounded overflow-hidden">
                  <table className="w-full">
                    <thead>
                      <tr className="bg-[var(--accent)]/10">
                        <th className="px-4 py-2 text-left text-xs font-theme-data text-[var(--accent)]">
                          RANK
                        </th>
                        <th className="px-4 py-2 text-left text-xs font-theme-data text-[var(--accent)]">
                          AGENT
                        </th>
                        <th className="px-4 py-2 text-right text-xs font-theme-data text-[var(--accent)]">
                          BRIER
                        </th>
                        <th className="px-4 py-2 text-right text-xs font-theme-data text-[var(--accent)]">
                          ECE
                        </th>
                        <th className="px-4 py-2 text-right text-xs font-theme-data text-[var(--accent)]">
                          ACCURACY
                        </th>
                        <th className="px-4 py-2 text-right text-xs font-theme-data text-[var(--accent)]">
                          PREDICTIONS
                        </th>
                        <th className="px-4 py-2 text-right text-xs font-theme-data text-[var(--accent)]">
                          ELO
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {leaderboard.map((agent, idx) => (
                        <tr
                          key={agent.agent}
                          className="border-t border-[var(--accent)]/10 hover:bg-[var(--accent)]/5 cursor-pointer transition-colors"
                          onClick={() => handleSelectAgent(agent.agent)}
                        >
                          <td className="px-4 py-2 font-theme-data text-sm text-text-muted">
                            #{idx + 1}
                          </td>
                          <td className="px-4 py-2 font-theme-data text-sm text-text">
                            {agent.agent}
                          </td>
                          <td
                            className={`px-4 py-2 font-theme-data text-sm text-right ${getScoreColor(1 - agent.brier_score)}`}
                          >
                            {agent.brier_score.toFixed(3)}
                          </td>
                          <td
                            className={`px-4 py-2 font-theme-data text-sm text-right ${getScoreColor(1 - agent.ece)}`}
                          >
                            {agent.ece.toFixed(3)}
                          </td>
                          <td
                            className={`px-4 py-2 font-theme-data text-sm text-right ${getScoreColor(agent.accuracy)}`}
                          >
                            {(agent.accuracy * 100).toFixed(1)}%
                          </td>
                          <td className="px-4 py-2 font-theme-data text-sm text-right text-text-muted">
                            {agent.predictions_count}
                          </td>
                          <td className="px-4 py-2 font-theme-data text-sm text-right text-text-muted">
                            {agent.elo.toFixed(0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Metric Explanations */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded">
                <div>
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                    Brier Score
                  </span>
                  <p className="text-xs text-text-muted">Lower is better (0 = perfect)</p>
                </div>
                <div>
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)]">ECE</span>
                  <p className="text-xs text-text-muted">Expected Calibration Error</p>
                </div>
                <div>
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)]">Accuracy</span>
                  <p className="text-xs text-text-muted">Correct predictions %</p>
                </div>
                <div>
                  <span className="text-xs font-theme-data text-[var(--acid-cyan)]">Composite</span>
                  <p className="text-xs text-text-muted">Overall calibration quality</p>
                </div>
              </div>
            </div>
          )}

          {/* Visualization Tab */}
          {activeTab === 'visualization' && (
            <div className="space-y-6">
              {vizLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-pulse text-text-muted font-theme-data">
                    Loading visualization...
                  </div>
                </div>
              ) : !visualization ? (
                <div className="text-center py-12 border border-[var(--accent)]/20 rounded">
                  <p className="text-text-muted font-theme-data text-sm">
                    No visualization data available yet.
                  </p>
                </div>
              ) : (
                <>
                  {/* Summary Stats */}
                  <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
                    <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded text-center">
                      <div className="text-2xl font-theme-data text-[var(--accent)]">
                        {visualization.summary.total_agents}
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">TOTAL AGENTS</div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded text-center">
                      <div
                        className={`text-2xl font-theme-data ${getScoreColor(1 - visualization.summary.avg_brier)}`}
                      >
                        {visualization.summary.avg_brier.toFixed(3)}
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">AVG BRIER</div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded text-center">
                      <div
                        className={`text-2xl font-theme-data ${getScoreColor(1 - visualization.summary.avg_ece)}`}
                      >
                        {visualization.summary.avg_ece.toFixed(3)}
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">AVG ECE</div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded text-center">
                      <div className="text-sm font-theme-data text-[var(--accent)] truncate">
                        {visualization.summary.best_calibrated || '-'}
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">BEST CALIBRATED</div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded text-center">
                      <div className="text-sm font-theme-data text-error truncate">
                        {visualization.summary.worst_calibrated || '-'}
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">
                        NEEDS IMPROVEMENT
                      </div>
                    </div>
                  </div>

                  {/* Calibration Curves */}
                  <div className="border border-[var(--accent)]/30 rounded p-4">
                    <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
                      CALIBRATION CURVES
                    </h3>
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                      {Object.entries(visualization.calibration_curves).map(([agent, data]) => (
                        <div
                          key={agent}
                          className="p-3 border border-[var(--accent)]/20 bg-bg rounded"
                        >
                          <div className="text-xs font-theme-data text-text mb-2">{agent}</div>
                          <div className="h-32 relative">
                            {/* Perfect calibration line */}
                            <svg
                              className="absolute inset-0 w-full h-full"
                              viewBox="0 0 100 100"
                              preserveAspectRatio="none"
                            >
                              <line
                                x1="0"
                                y1="100"
                                x2="100"
                                y2="0"
                                stroke="rgba(0,255,65,0.3)"
                                strokeWidth="1"
                                strokeDasharray="4"
                              />
                              {/* Actual calibration curve */}
                              <polyline
                                fill="none"
                                stroke="#00ffff"
                                strokeWidth="2"
                                points={data.buckets
                                  .map((b) => `${b.x * 100},${100 - b.actual * 100}`)
                                  .join(' ')}
                              />
                              {/* Data points */}
                              {data.buckets.map((b, i) => (
                                <circle
                                  key={i}
                                  cx={b.x * 100}
                                  cy={100 - b.actual * 100}
                                  r="3"
                                  fill={b.count > 0 ? '#00ffff' : 'transparent'}
                                />
                              ))}
                            </svg>
                            {/* Axis labels */}
                            <div className="absolute bottom-0 left-0 text-xs text-text-muted">
                              0%
                            </div>
                            <div className="absolute bottom-0 right-0 text-xs text-text-muted">
                              100%
                            </div>
                            <div className="absolute top-0 left-0 text-xs text-text-muted">
                              100%
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="mt-2 text-xs text-text-muted text-center">
                      <span className="text-[var(--accent)]/50">---</span> Perfect calibration |
                      <span className="text-[var(--acid-cyan)] ml-2">●</span> Actual performance
                    </div>
                  </div>

                  {/* Confidence Distribution */}
                  <div className="border border-[var(--accent)]/30 rounded p-4">
                    <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
                      CONFIDENCE DISTRIBUTION
                    </h3>
                    <div className="flex items-end gap-1 h-32">
                      {visualization.confidence_histogram.map((bucket, i) => {
                        const maxCount = Math.max(
                          ...visualization.confidence_histogram.map((b) => b.count),
                        );
                        const height = maxCount > 0 ? (bucket.count / maxCount) * 100 : 0;
                        return (
                          <div key={i} className="flex-1 flex flex-col items-center">
                            <div
                              className="w-full bg-[var(--acid-cyan)]/50 border border-[var(--acid-cyan)]/30 transition-all"
                              style={{ height: `${height}%` }}
                              title={`${bucket.range}: ${bucket.count}`}
                            />
                            <div className="text-xs text-text-muted mt-1 -rotate-45 origin-top-left w-8">
                              {bucket.range.split('-')[0]}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Scatter Data */}
                  {visualization.scatter_data.length > 0 && (
                    <div className="border border-[var(--accent)]/30 rounded p-4">
                      <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
                        AGENT COMPARISON
                      </h3>
                      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                        {visualization.scatter_data.map((agent) => (
                          <div
                            key={agent.agent}
                            className="p-3 border border-[var(--accent)]/20 hover:bg-[var(--accent)]/5 cursor-pointer transition-colors rounded"
                            onClick={() => handleSelectAgent(agent.agent)}
                          >
                            <div className="flex items-center justify-between mb-2">
                              <span className="font-theme-data text-sm text-text">
                                {agent.agent}
                              </span>
                              <span
                                className={`text-xs font-theme-data px-2 py-0.5 border rounded ${
                                  agent.is_overconfident
                                    ? 'bg-error/10 text-error border-error/30'
                                    : agent.is_underconfident
                                      ? 'bg-warning/10 text-warning border-warning/30'
                                      : 'bg-[var(--accent)]/10 text-[var(--accent)] border-[var(--accent)]/30'
                                }`}
                              >
                                {agent.is_overconfident
                                  ? 'OVERCONFIDENT'
                                  : agent.is_underconfident
                                    ? 'UNDERCONFIDENT'
                                    : 'WELL-CALIBRATED'}
                              </span>
                            </div>
                            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
                              <div>
                                <span className="text-text-muted">Accuracy:</span>
                                <span className={`ml-1 ${getScoreColor(agent.accuracy)}`}>
                                  {(agent.accuracy * 100).toFixed(1)}%
                                </span>
                              </div>
                              <div>
                                <span className="text-text-muted">Brier:</span>
                                <span className={`ml-1 ${getScoreColor(1 - agent.brier_score)}`}>
                                  {agent.brier_score.toFixed(3)}
                                </span>
                              </div>
                              <div>
                                <span className="text-text-muted">Preds:</span>
                                <span className="ml-1 text-text">{agent.predictions}</span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Debate Analysis Tab */}
          {activeTab === 'debate' && (
            <div className="space-y-4">
              <div className="p-4 border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 rounded">
                <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-2">
                  Uncertainty Metrics
                </h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-theme-data text-text-muted">
                  <div>
                    <span className="text-[var(--accent)]">Collective Confidence</span>
                    <p>Aggregate certainty level</p>
                  </div>
                  <div>
                    <span className="text-[var(--accent)]">Disagreement Sources</span>
                    <p>Where agents diverge</p>
                  </div>
                  <div>
                    <span className="text-[var(--accent)]">Calibration Quality</span>
                    <p>Confidence vs accuracy</p>
                  </div>
                  <div>
                    <span className="text-[var(--accent)]">Crux Detection</span>
                    <p>Key disputed claims</p>
                  </div>
                </div>
              </div>

              {/* Debate ID Input */}
              <div className="p-4 border border-[var(--accent)]/30 rounded">
                <label className="block text-sm font-theme-data text-text-muted mb-2">
                  Enter Debate ID to Analyze
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={debateId}
                    onChange={(e) => setDebateId(e.target.value)}
                    placeholder="debate-uuid-here"
                    className="flex-1 bg-bg border border-[var(--accent)]/30 px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
                  />
                  <button
                    onClick={handleLoadDebate}
                    className="px-4 py-2 bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] text-sm font-theme-data hover:bg-[var(--accent)]/20 transition-colors"
                  >
                    [ANALYZE]
                  </button>
                </div>
              </div>

              {activeDebateId ? (
                <PanelErrorBoundary panelName="Uncertainty Analysis">
                  <UncertaintyPanel events={[]} debateId={activeDebateId} />
                </PanelErrorBoundary>
              ) : (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="text-text-muted font-theme-data text-sm">
                    Enter a debate ID above to analyze uncertainty and confidence patterns.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Agent Profile Tab */}
          {activeTab === 'agent' && (
            <div className="space-y-4">
              {/* Agent Selector */}
              <div className="p-4 border border-[var(--accent)]/30 rounded">
                <label className="block text-sm font-theme-data text-text-muted mb-2">
                  Agent Name
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={selectedAgent}
                    onChange={(e) => setSelectedAgent(e.target.value)}
                    placeholder="claude, gpt-4, etc."
                    className="flex-1 bg-bg border border-[var(--accent)]/30 px-3 py-2 text-sm font-theme-data text-text focus:outline-none focus:border-[var(--accent)]"
                  />
                  <button
                    onClick={() => fetchAgentCalibration(selectedAgent)}
                    disabled={!selectedAgent || agentLoading}
                    className="px-4 py-2 bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] text-sm font-theme-data hover:bg-[var(--accent)]/20 transition-colors disabled:opacity-50"
                  >
                    {agentLoading ? '[...]' : '[LOAD]'}
                  </button>
                </div>
              </div>

              {agentLoading ? (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-pulse text-text-muted font-theme-data">
                    Loading agent data...
                  </div>
                </div>
              ) : agentCalibration ? (
                <div className="space-y-4">
                  {/* Agent Summary */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded text-center">
                      <div className="text-2xl font-theme-data text-[var(--accent)]">
                        {agentCalibration.agent_id}
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">AGENT</div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded text-center">
                      <div
                        className={`text-2xl font-theme-data ${getScoreColor(agentCalibration.calibration_quality)}`}
                      >
                        {(agentCalibration.calibration_quality * 100).toFixed(0)}%
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">
                        CALIBRATION QUALITY
                      </div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded text-center">
                      <div
                        className={`text-2xl font-theme-data ${agentCalibration.brier_score !== null ? getScoreColor(1 - agentCalibration.brier_score) : 'text-text-muted'}`}
                      >
                        {agentCalibration.brier_score !== null
                          ? agentCalibration.brier_score.toFixed(3)
                          : 'N/A'}
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">BRIER SCORE</div>
                    </div>
                    <div className="p-4 border border-[var(--accent)]/30 bg-[var(--accent)]/5 rounded text-center">
                      <div className="text-2xl font-theme-data text-text">
                        {agentCalibration.calibration_history.length}
                      </div>
                      <div className="text-xs text-text-muted font-theme-data">PREDICTIONS</div>
                    </div>
                  </div>

                  {/* Confidence History */}
                  {agentCalibration.confidence_history.length > 0 && (
                    <div className="border border-[var(--accent)]/30 rounded p-4">
                      <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
                        RECENT CONFIDENCE HISTORY
                      </h3>
                      <div className="space-y-2">
                        {agentCalibration.confidence_history.map((entry, idx) => (
                          <div key={idx} className="flex items-center gap-2">
                            <div className="flex-1 h-4 bg-bg rounded overflow-hidden">
                              <div
                                className={`h-full ${entry.was_correct ? 'bg-[var(--accent)]' : 'bg-error'}`}
                                style={{ width: `${entry.confidence * 100}%` }}
                              />
                            </div>
                            <span className="text-xs font-theme-data text-text-muted w-16 text-right">
                              {(entry.confidence * 100).toFixed(0)}%
                            </span>
                            <span
                              className={`text-xs font-theme-data ${entry.was_correct ? 'text-[var(--accent)]' : 'text-error'}`}
                            >
                              {entry.was_correct ? '✓' : '✗'}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Calibration History */}
                  {agentCalibration.calibration_history.length > 0 && (
                    <div className="border border-[var(--accent)]/30 rounded p-4">
                      <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
                        CALIBRATION HISTORY
                      </h3>
                      <div className="flex items-end gap-1 h-24">
                        {agentCalibration.calibration_history.map((entry, idx) => (
                          <div
                            key={idx}
                            className={`flex-1 border ${entry.was_correct ? 'bg-[var(--accent)]/50 border-[var(--accent)]/30' : 'bg-error/50 border-error/30'}`}
                            style={{ height: `${entry.confidence * 100}%` }}
                            title={`${(entry.confidence * 100).toFixed(0)}% - ${entry.was_correct ? 'Correct' : 'Incorrect'}`}
                          />
                        ))}
                      </div>
                      <div className="flex justify-between text-xs text-text-muted mt-1">
                        <span>Oldest</span>
                        <span>Most Recent</span>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-8 border border-[var(--accent)]/20 rounded text-center">
                  <p className="text-text-muted font-theme-data text-sm">
                    Select an agent from the leaderboard or enter an agent name above.
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // UNCERTAINTY & CALIBRATION</p>
        </footer>
      </main>
    </>
  );
}
