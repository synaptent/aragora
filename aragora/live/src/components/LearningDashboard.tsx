'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface CycleSummary {
  cycle: number;
  topic: string;
  agents: string[];
  started_at: string;
  status: string;
  success: boolean;
  event_count: number;
}

interface Pattern {
  successful_patterns: Array<{ cycle: number; phase: string; confidence: number }>;
  failed_patterns: Array<{ cycle: number; phase: string; error: string }>;
  recurring_themes: Array<{ theme: string; count: number }>;
  agent_specializations: Record<string, number>;
}

interface AgentEvolution {
  data_points: Array<{ cycle: number; is_winner: boolean }>;
  total_cycles: number;
  total_wins: number;
  trend: 'improving' | 'declining' | 'stable';
}

interface LearningDashboardProps {
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

export function LearningDashboard({ apiBase = DEFAULT_API_BASE }: LearningDashboardProps) {
  const [cycles, setCycles] = useState<CycleSummary[]>([]);
  const [patterns, setPatterns] = useState<Pattern | null>(null);
  const [evolution, setEvolution] = useState<Record<string, AgentEvolution>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'cycles' | 'patterns' | 'evolution'>('cycles');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const [cyclesRes, patternsRes, evolutionRes] = await Promise.all([
        fetch(`${apiBase}/api/learning/cycles?limit=20`),
        fetch(`${apiBase}/api/learning/patterns`),
        fetch(`${apiBase}/api/learning/agent-evolution`),
      ]);

      if (cyclesRes.ok) {
        const data = await cyclesRes.json();
        setCycles(data.cycles || []);
      }

      if (patternsRes.ok) {
        const data = await patternsRes.json();
        setPatterns(data);
      }

      if (evolutionRes.ok) {
        const data = await evolutionRes.json();
        setEvolution(data.agents || {});
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch learning data');
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const getTrendIcon = (trend: string) => {
    switch (trend) {
      case 'improving':
        return '↑';
      case 'declining':
        return '↓';
      default:
        return '→';
    }
  };

  const getTrendColor = (trend: string) => {
    switch (trend) {
      case 'improving':
        return 'text-green-400';
      case 'declining':
        return 'text-red-400';
      default:
        return 'text-yellow-400';
    }
  };

  return (
    <div className="card p-4 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-[var(--accent)] font-theme-data text-sm font-bold">
          [CROSS-CYCLE LEARNING]
        </h3>
        <button
          onClick={fetchData}
          disabled={loading}
          className="text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] disabled:opacity-50"
        >
          {loading ? 'LOADING...' : 'REFRESH'}
        </button>
      </div>

      {error && (
        <div className="text-warning text-xs font-theme-data p-2 bg-warning/10 rounded">
          {error}
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex gap-1 border-b border-[var(--accent)]/30 pb-2">
        {(['cycles', 'patterns', 'evolution'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1 text-xs font-theme-data transition-colors ${
              activeTab === tab
                ? 'bg-[var(--accent)] text-bg'
                : 'text-text-muted hover:text-[var(--accent)]'
            }`}
          >
            {tab.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Cycles Tab */}
      {activeTab === 'cycles' && (
        <div className="space-y-2 max-h-64 overflow-y-auto">
          {cycles.length === 0 ? (
            <p className="text-text-muted text-xs font-theme-data">No cycles found</p>
          ) : (
            cycles.map((cycle) => (
              <div
                key={cycle.cycle}
                className="p-2 bg-surface rounded border border-[var(--accent)]/20"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[var(--acid-cyan)] font-theme-data text-xs">
                    Cycle {cycle.cycle}
                  </span>
                  <span
                    className={`text-xs font-theme-data ${
                      cycle.success ? 'text-green-400' : 'text-yellow-400'
                    }`}
                  >
                    {cycle.success ? '✓ SUCCESS' : cycle.status.toUpperCase()}
                  </span>
                </div>
                <p className="text-text-muted text-xs mt-1 truncate">
                  {cycle.topic || 'Self-improvement'}
                </p>
                <div className="flex gap-1 mt-1 flex-wrap">
                  {cycle.agents.map((agent) => (
                    <span
                      key={agent}
                      className="text-[10px] px-1 bg-[var(--accent)]/10 text-[var(--accent)] rounded"
                    >
                      {agent}
                    </span>
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}

      {/* Patterns Tab */}
      {activeTab === 'patterns' && patterns && (
        <div className="space-y-4">
          {/* Recurring Themes */}
          <div>
            <h4 className="text-[var(--acid-cyan)] text-xs font-theme-data mb-2">
              RECURRING THEMES
            </h4>
            <div className="flex flex-wrap gap-2">
              {patterns.recurring_themes.length === 0 ? (
                <span className="text-text-muted text-xs">No themes detected</span>
              ) : (
                patterns.recurring_themes.map((theme) => (
                  <span
                    key={theme.theme}
                    className="text-xs px-2 py-1 bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] rounded"
                  >
                    {theme.theme} ({theme.count})
                  </span>
                ))
              )}
            </div>
          </div>

          {/* Agent Specializations */}
          <div>
            <h4 className="text-[var(--acid-cyan)] text-xs font-theme-data mb-2">AGENT WINS</h4>
            <div className="space-y-1">
              {Object.entries(patterns.agent_specializations).length === 0 ? (
                <span className="text-text-muted text-xs">No wins recorded</span>
              ) : (
                Object.entries(patterns.agent_specializations)
                  .sort((a, b) => b[1] - a[1])
                  .map(([agent, wins]) => (
                    <div key={agent} className="flex items-center gap-2">
                      <span className="text-xs font-theme-data text-[var(--accent)] w-16">
                        {agent}
                      </span>
                      <div className="flex-1 h-2 bg-surface rounded overflow-hidden">
                        <div
                          className="h-full bg-[var(--accent)]"
                          style={{ width: `${Math.min(wins * 10, 100)}%` }}
                        />
                      </div>
                      <span className="text-xs text-text-muted w-8">{wins}</span>
                    </div>
                  ))
              )}
            </div>
          </div>

          {/* Recent Failures */}
          {patterns.failed_patterns.length > 0 && (
            <div>
              <h4 className="text-warning text-xs font-theme-data mb-2">RECENT FAILURES</h4>
              <div className="space-y-1">
                {patterns.failed_patterns.slice(0, 3).map((fail, i) => (
                  <div key={i} className="text-xs text-text-muted p-1 bg-warning/5 rounded">
                    Cycle {fail.cycle}: {fail.phase} - {fail.error?.slice(0, 50)}...
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Evolution Tab */}
      {activeTab === 'evolution' && (
        <div className="space-y-3">
          {Object.keys(evolution).length === 0 ? (
            <p className="text-text-muted text-xs font-theme-data">No evolution data</p>
          ) : (
            Object.entries(evolution).map(([agent, data]) => (
              <div key={agent} className="p-2 bg-surface rounded">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-[var(--accent)] font-theme-data text-sm">{agent}</span>
                  <span className={`text-sm font-theme-data ${getTrendColor(data.trend)}`}>
                    {getTrendIcon(data.trend)} {data.trend.toUpperCase()}
                  </span>
                </div>
                <div className="flex items-center gap-4 text-xs text-text-muted">
                  <span>Cycles: {data.total_cycles}</span>
                  <span>Wins: {data.total_wins}</span>
                  <span>
                    Win Rate:{' '}
                    {data.total_cycles > 0
                      ? `${Math.round((data.total_wins / data.total_cycles) * 100)}%`
                      : 'N/A'}
                  </span>
                </div>
                {/* Mini chart */}
                <div className="flex gap-0.5 mt-2 h-4">
                  {data.data_points.slice(-15).map((point, i) => (
                    <div
                      key={i}
                      className={`flex-1 rounded-sm ${
                        point.is_winner ? 'bg-green-400' : 'bg-surface-dark'
                      }`}
                      title={`Cycle ${point.cycle}: ${point.is_winner ? 'Won' : 'Lost'}`}
                    />
                  ))}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
