'use client';
import { useState, useEffect, useCallback } from 'react';
import { logger } from '@/utils/logger';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { ErrorWithRetry } from '@/components/ErrorWithRetry';

interface AgentSummary {
  name: string;
  reputation_score?: number;
  total_critiques?: number;
}

interface IntrospectionData {
  agent_name: string;
  reputation?: {
    score: number;
    total_critiques: number;
    win_rate: number;
    average_helpfulness: number;
  };
  strengths: string[];
  weaknesses: string[];
  specializations: string[];
  recent_debates: {
    debate_id: string;
    task: string;
    role: string;
    outcome: string;
    timestamp: string;
  }[];
  calibration?: { confidence: number; accuracy: number; calibration_error: number };
  persona?: { display_name: string; description: string; traits: string[] };
}

interface LeaderboardEntry {
  agent_name: string;
  reputation_score: number;
  total_critiques: number;
  rank: number;
}

type TabType = 'agents' | 'leaderboard' | 'detail';

export default function IntrospectionPage() {
  const { config } = useBackend();
  const backendUrl = config.api;
  const [activeTab, setActiveTab] = useState<TabType>('agents');
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [leaderboard, setLeaderboard] = useState<LeaderboardEntry[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [introspection, setIntrospection] = useState<IntrospectionData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAgents = useCallback(async () => {
    try {
      const response = await fetch(`${backendUrl}/api/introspection/agents`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setAgents(data.agents || []);
    } catch (err) {
      logger.error('Failed to fetch agents:', err);
      throw err;
    }
  }, [backendUrl]);

  const fetchLeaderboard = useCallback(async () => {
    try {
      const response = await fetch(`${backendUrl}/api/introspection/leaderboard?limit=20`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      setLeaderboard(data.leaderboard || []);
    } catch (err) {
      logger.error('Failed to fetch leaderboard:', err);
      throw err;
    }
  }, [backendUrl]);

  const fetchIntrospection = useCallback(
    async (agentName: string) => {
      try {
        const response = await fetch(`${backendUrl}/api/introspection/agents/${agentName}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        setIntrospection(data);
      } catch (err) {
        logger.error('Failed to fetch introspection:', err);
        throw err;
      }
    },
    [backendUrl],
  );

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await Promise.all([fetchAgents(), fetchLeaderboard()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load data');
    } finally {
      setLoading(false);
    }
  }, [fetchAgents, fetchLeaderboard]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleAgentSelect = async (agentName: string) => {
    setSelectedAgent(agentName);
    setActiveTab('detail');
    try {
      await fetchIntrospection(agentName);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agent details');
    }
  };

  const getScoreColor = (score: number) => {
    if (score >= 0.8) return 'text-[var(--accent)]';
    if (score >= 0.6) return 'text-yellow-400';
    if (score >= 0.4) return 'text-orange-400';
    return 'text-red-400';
  };

  const renderAgentsList = () => (
    <div className="space-y-4">
      <h2 className="text-xl font-theme-data font-bold text-[var(--accent)] mb-4">
        Agent Registry
      </h2>
      {agents.length === 0 ? (
        <p className="text-text-muted">No agents found</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <button
              key={agent.name}
              onClick={() => handleAgentSelect(agent.name)}
              className="p-4 bg-surface border border-border rounded-lg hover:border-[var(--accent)]/50 transition-all text-left group"
            >
              <div className="flex items-center justify-between mb-2">
                <span className="font-theme-data font-bold text-text group-hover:text-[var(--accent)] transition-colors">
                  {agent.name}
                </span>
                {agent.reputation_score !== undefined && (
                  <span
                    className={`font-theme-data text-sm ${getScoreColor(agent.reputation_score)}`}
                  >
                    {(agent.reputation_score * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              {agent.total_critiques !== undefined && (
                <div className="text-xs text-text-muted font-theme-data">
                  {agent.total_critiques} critiques
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );

  const renderLeaderboard = () => (
    <div className="space-y-4">
      <h2 className="text-xl font-theme-data font-bold text-[var(--accent)] mb-4">
        Reputation Leaderboard
      </h2>
      {leaderboard.length === 0 ? (
        <p className="text-text-muted">No leaderboard data</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse font-theme-data text-sm">
            <thead>
              <tr className="border-b border-border">
                <th className="text-left py-2 px-3 text-text-muted">Rank</th>
                <th className="text-left py-2 px-3 text-text-muted">Agent</th>
                <th className="text-right py-2 px-3 text-text-muted">Score</th>
                <th className="text-right py-2 px-3 text-text-muted">Critiques</th>
              </tr>
            </thead>
            <tbody>
              {leaderboard.map((entry, idx) => (
                <tr
                  key={entry.agent_name}
                  className="border-b border-border/50 hover:bg-surface/50 cursor-pointer"
                  onClick={() => handleAgentSelect(entry.agent_name)}
                >
                  <td className="py-2 px-3">
                    <span
                      className={idx < 3 ? 'text-[var(--accent)] font-bold' : 'text-text-muted'}
                    >
                      #{entry.rank || idx + 1}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-text">{entry.agent_name}</td>
                  <td className={`py-2 px-3 text-right ${getScoreColor(entry.reputation_score)}`}>
                    {(entry.reputation_score * 100).toFixed(1)}%
                  </td>
                  <td className="py-2 px-3 text-right text-text-muted">{entry.total_critiques}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );

  const renderAgentDetail = () => {
    if (!introspection) {
      return <p className="text-text-muted">Loading agent details...</p>;
    }

    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">
            {introspection.persona?.display_name || introspection.agent_name}
          </h2>
          <button
            onClick={() => {
              setActiveTab('agents');
              setSelectedAgent(null);
              setIntrospection(null);
            }}
            className="px-3 py-1 text-sm font-theme-data border border-border rounded hover:border-[var(--accent)]/50 transition-colors"
          >
            Back to list
          </button>
        </div>

        {introspection.persona?.description && (
          <p className="text-text-muted">{introspection.persona.description}</p>
        )}

        {/* Reputation Card */}
        {introspection.reputation && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Reputation
            </h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-text-muted">Score</div>
                <div
                  className={`text-2xl font-theme-data font-bold ${getScoreColor(introspection.reputation.score)}`}
                >
                  {(introspection.reputation.score * 100).toFixed(0)}%
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Win Rate</div>
                <div className="text-2xl font-theme-data font-bold text-text">
                  {(introspection.reputation.win_rate * 100).toFixed(0)}%
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Helpfulness</div>
                <div className="text-2xl font-theme-data font-bold text-text">
                  {(introspection.reputation.average_helpfulness * 100).toFixed(0)}%
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Critiques</div>
                <div className="text-2xl font-theme-data font-bold text-text">
                  {introspection.reputation.total_critiques}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Calibration Card */}
        {introspection.calibration && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Calibration
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <div>
                <div className="text-xs text-text-muted">Confidence</div>
                <div className="text-xl font-theme-data font-bold text-text">
                  {(introspection.calibration.confidence * 100).toFixed(0)}%
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Accuracy</div>
                <div className="text-xl font-theme-data font-bold text-text">
                  {(introspection.calibration.accuracy * 100).toFixed(0)}%
                </div>
              </div>
              <div>
                <div className="text-xs text-text-muted">Calibration Error</div>
                <div className="text-xl font-theme-data font-bold text-text">
                  {(introspection.calibration.calibration_error * 100).toFixed(1)}%
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Strengths & Weaknesses */}
        <div className="grid md:grid-cols-2 gap-4">
          {introspection.strengths && introspection.strengths.length > 0 && (
            <div className="p-4 bg-surface border border-border rounded-lg">
              <h3 className="text-sm font-theme-data font-bold text-[var(--accent)] uppercase mb-3">
                Strengths
              </h3>
              <ul className="space-y-1">
                {introspection.strengths.map((s, i) => (
                  <li key={i} className="text-sm text-text font-theme-data flex items-start gap-2">
                    <span className="text-[var(--accent)]">+</span>
                    <span>{s}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {introspection.weaknesses && introspection.weaknesses.length > 0 && (
            <div className="p-4 bg-surface border border-border rounded-lg">
              <h3 className="text-sm font-theme-data font-bold text-red-400 uppercase mb-3">
                Weaknesses
              </h3>
              <ul className="space-y-1">
                {introspection.weaknesses.map((w, i) => (
                  <li key={i} className="text-sm text-text font-theme-data flex items-start gap-2">
                    <span className="text-red-400">-</span>
                    <span>{w}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        {/* Specializations */}
        {introspection.specializations && introspection.specializations.length > 0 && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Specializations
            </h3>
            <div className="flex flex-wrap gap-2">
              {introspection.specializations.map((spec, i) => (
                <span
                  key={i}
                  className="px-2 py-1 text-xs font-theme-data bg-[var(--accent)]/10 border border-[var(--accent)]/30 text-[var(--accent)] rounded"
                >
                  {spec}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Persona Traits */}
        {introspection.persona?.traits && introspection.persona.traits.length > 0 && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Persona Traits
            </h3>
            <div className="flex flex-wrap gap-2">
              {introspection.persona.traits.map((trait, i) => (
                <span
                  key={i}
                  className="px-2 py-1 text-xs font-theme-data bg-blue-500/10 border border-blue-500/30 text-blue-400 rounded"
                >
                  {trait}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Recent Debates */}
        {introspection.recent_debates && introspection.recent_debates.length > 0 && (
          <div className="p-4 bg-surface border border-border rounded-lg">
            <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase mb-3">
              Recent Debates
            </h3>
            <div className="space-y-2">
              {introspection.recent_debates.slice(0, 5).map((debate, i) => (
                <Link
                  key={i}
                  href={`/debate/${debate.debate_id}`}
                  className="block p-2 hover:bg-bg rounded transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-theme-data text-text truncate max-w-md">
                      {debate.task}
                    </span>
                    <span
                      className={`text-xs font-theme-data ${
                        debate.outcome === 'win'
                          ? 'text-[var(--accent)]'
                          : debate.outcome === 'loss'
                            ? 'text-red-400'
                            : 'text-text-muted'
                      }`}
                    >
                      {debate.outcome}
                    </span>
                  </div>
                  <div className="text-xs text-text-muted mt-1">
                    Role: {debate.role} | {new Date(debate.timestamp).toLocaleDateString()}
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-bg text-text relative overflow-hidden">
      <Scanlines />
      <CRTVignette />

      <div className="max-w-6xl mx-auto px-4 py-8 relative z-10">
        {/* Title */}
        <div className="mb-8">
          <h1 className="text-3xl font-theme-data font-bold text-[var(--accent)] mb-2">
            Agent Introspection
          </h1>
          <p className="text-text-muted font-theme-data text-sm">
            Explore agent self-awareness, reputation, and capabilities
          </p>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-6">
            <ErrorWithRetry error={error} onRetry={loadData} />
          </div>
        )}

        {/* Tabs */}
        <div className="flex gap-2 mb-6 border-b border-border pb-2">
          <button
            onClick={() => {
              setActiveTab('agents');
              setSelectedAgent(null);
              setIntrospection(null);
            }}
            className={`px-4 py-2 font-theme-data text-sm rounded-t transition-colors ${
              activeTab === 'agents'
                ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-b-2 border-[var(--accent)]'
                : 'text-text-muted hover:text-text'
            }`}
          >
            Agents
          </button>
          <button
            onClick={() => setActiveTab('leaderboard')}
            className={`px-4 py-2 font-theme-data text-sm rounded-t transition-colors ${
              activeTab === 'leaderboard'
                ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-b-2 border-[var(--accent)]'
                : 'text-text-muted hover:text-text'
            }`}
          >
            Leaderboard
          </button>
          {selectedAgent && (
            <button
              onClick={() => setActiveTab('detail')}
              className={`px-4 py-2 font-theme-data text-sm rounded-t transition-colors ${
                activeTab === 'detail'
                  ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-b-2 border-[var(--accent)]'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              {selectedAgent}
            </button>
          )}
        </div>

        {/* Content */}
        {loading ? (
          <div className="flex items-center justify-center py-12">
            <div className="text-[var(--accent)] font-theme-data animate-pulse">Loading...</div>
          </div>
        ) : (
          <div>
            {activeTab === 'agents' && renderAgentsList()}
            {activeTab === 'leaderboard' && renderLeaderboard()}
            {activeTab === 'detail' && renderAgentDetail()}
          </div>
        )}
      </div>
    </div>
  );
}
