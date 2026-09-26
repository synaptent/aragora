'use client';

import { useState, useEffect, useCallback } from 'react';
import { getAgentColors } from '@/utils/agentColors';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';

interface CalibrationMetrics {
  agents: Record<string, { calibration_bias: number; predictions: number }>;
  overall_calibration: number;
  overconfident_agents: string[];
  underconfident_agents: string[];
}

interface PerformanceMetrics {
  agents: Record<string, { avg_latency_ms: number; success_rate: number; calls: number }>;
  avg_latency_ms: number;
  success_rate: number;
  total_calls: number;
}

interface EvolutionMetrics {
  agents: Record<
    string,
    { current_version: number; performance_score: number; debates_count: number }
  >;
  total_versions: number;
  patterns_extracted: number;
  last_evolution: string | null;
}

interface DebateQualityMetrics {
  avg_confidence: number;
  consensus_rate: number;
  avg_rounds: number;
  evidence_quality: number;
  recent_winners: string[];
}

interface QualityMetricsData {
  calibration: CalibrationMetrics;
  performance: PerformanceMetrics;
  evolution: EvolutionMetrics;
  debate_quality: DebateQualityMetrics;
  generated_at: number;
}

function MetricCard({
  title,
  value,
  subtitle,
  color = 'text-[var(--accent)]',
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  color?: string;
}) {
  return (
    <div className="bg-bg/50 border border-[var(--accent)]/20 p-3">
      <div className="text-xs font-theme-data text-text-muted uppercase mb-1">{title}</div>
      <div className={`text-xl font-theme-data ${color}`}>{value}</div>
      {subtitle && <div className="text-xs font-theme-data text-text-muted mt-1">{subtitle}</div>}
    </div>
  );
}

function AgentBadge({ agent, metric, label }: { agent: string; metric: number; label: string }) {
  const colors = getAgentColors(agent);
  return (
    <div className={`px-2 py-1 border ${colors.border} ${colors.bg} flex items-center gap-2`}>
      <span className={`text-xs font-theme-data ${colors.text}`}>{agent}</span>
      <span className="text-xs font-theme-data text-text-muted">
        {label}: {typeof metric === 'number' ? metric.toFixed(1) : metric}
      </span>
    </div>
  );
}

export function QualityDashboard() {
  const { isAuthenticated, isLoading: authLoading, tokens } = useAuth();
  const [data, setData] = useState<QualityMetricsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    // Skip if not authenticated
    if (!isAuthenticated || authLoading) {
      setLoading(false);
      return;
    }

    try {
      const apiUrl = API_BASE_URL;
      const headers: HeadersInit = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }
      const response = await fetch(`${apiUrl}/api/dashboard/quality-metrics`, { headers });
      if (!response.ok) throw new Error('Failed to fetch metrics');
      const json = await response.json();
      setData(json);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, authLoading, tokens?.access_token]);

  useEffect(() => {
    fetchMetrics();
    const interval = setInterval(fetchMetrics, 60000); // Refresh every minute
    return () => clearInterval(interval);
  }, [fetchMetrics]);

  if (loading) {
    return (
      <div className="bg-surface border border-[var(--accent)]/30 p-6">
        <div className="text-xs font-theme-data text-text-muted animate-pulse">
          Loading quality metrics...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-surface border border-[var(--crimson)]/30 p-6">
        <div className="text-xs font-theme-data text-[var(--crimson)]">Error: {error}</div>
      </div>
    );
  }

  if (!data) return null;

  const { calibration, performance, evolution, debate_quality } = data;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-theme-data text-[var(--accent)]">{'>'} QUALITY METRICS</h2>
          <span className="text-xs font-theme-data text-text-muted">
            Updated: {new Date(data.generated_at * 1000).toLocaleTimeString()}
          </span>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <MetricCard
          title="Consensus Rate"
          value={`${(debate_quality.consensus_rate * 100).toFixed(0)}%`}
          color={debate_quality.consensus_rate > 0.5 ? 'text-[var(--accent)]' : 'text-yellow-400'}
        />
        <MetricCard
          title="Avg Confidence"
          value={`${(debate_quality.avg_confidence * 100).toFixed(0)}%`}
          color={
            debate_quality.avg_confidence > 0.7 ? 'text-[var(--accent)]' : 'text-[var(--acid-cyan)]'
          }
        />
        <MetricCard
          title="Success Rate"
          value={`${(performance.success_rate * 100).toFixed(0)}%`}
          color={performance.success_rate > 0.9 ? 'text-[var(--accent)]' : 'text-yellow-400'}
        />
        <MetricCard
          title="Patterns Extracted"
          value={evolution.patterns_extracted}
          subtitle={`${evolution.total_versions} versions`}
        />
      </div>

      {/* Calibration Section */}
      <div className="bg-surface border border-[var(--acid-cyan)]/30">
        <div className="px-4 py-3 border-b border-[var(--acid-cyan)]/20 bg-bg/50">
          <span className="text-xs font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider">
            {'>'} CALIBRATION
          </span>
        </div>
        <div className="p-4 space-y-4">
          <div className="flex items-center gap-4">
            <div className="text-xs font-theme-data text-text-muted">Overall:</div>
            <div className="flex-1 h-2 bg-bg border border-[var(--acid-cyan)]/20">
              <div
                className="h-full bg-[var(--acid-cyan)]/60"
                style={{ width: `${Math.abs(calibration.overall_calibration) * 100}%` }}
              />
            </div>
            <div className="text-xs font-theme-data text-[var(--acid-cyan)]">
              {calibration.overall_calibration > 0 ? '+' : ''}
              {(calibration.overall_calibration * 100).toFixed(1)}%
            </div>
          </div>

          {calibration.overconfident_agents.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <span className="text-xs font-theme-data text-yellow-400">Overconfident:</span>
              {calibration.overconfident_agents.map((agent) => (
                <span
                  key={agent}
                  className="px-2 py-0.5 text-xs font-theme-data bg-yellow-400/10 text-yellow-400 border border-yellow-400/30"
                >
                  {agent}
                </span>
              ))}
            </div>
          )}

          {calibration.underconfident_agents.length > 0 && (
            <div className="flex flex-wrap gap-2">
              <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                Underconfident:
              </span>
              {calibration.underconfident_agents.map((agent) => (
                <span
                  key={agent}
                  className="px-2 py-0.5 text-xs font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30"
                >
                  {agent}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Performance Section */}
      <div className="bg-surface border border-gold/30">
        <div className="px-4 py-3 border-b border-gold/20 bg-bg/50">
          <span className="text-xs font-theme-data text-gold uppercase tracking-wider">
            {'>'} PERFORMANCE
          </span>
        </div>
        <div className="p-4 space-y-3">
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-center">
            <div>
              <div className="text-xs font-theme-data text-text-muted">Avg Latency</div>
              <div className="text-lg font-theme-data text-gold">
                {performance.avg_latency_ms.toFixed(0)}ms
              </div>
            </div>
            <div>
              <div className="text-xs font-theme-data text-text-muted">Success Rate</div>
              <div className="text-lg font-theme-data text-gold">
                {(performance.success_rate * 100).toFixed(0)}%
              </div>
            </div>
            <div>
              <div className="text-xs font-theme-data text-text-muted">Total Calls</div>
              <div className="text-lg font-theme-data text-gold">{performance.total_calls}</div>
            </div>
          </div>

          {Object.keys(performance.agents).length > 0 && (
            <div className="flex flex-wrap gap-2 pt-2 border-t border-gold/20">
              {Object.entries(performance.agents).map(([agent, stats]) => (
                <AgentBadge key={agent} agent={agent} metric={stats.avg_latency_ms} label="ms" />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Evolution Section */}
      <div className="bg-surface border border-purple/30">
        <div className="px-4 py-3 border-b border-purple/20 bg-bg/50">
          <span className="text-xs font-theme-data text-purple uppercase tracking-wider">
            {'>'} EVOLUTION
          </span>
        </div>
        <div className="p-4 space-y-3">
          <div className="grid grid-cols-2 gap-4 text-center">
            <div>
              <div className="text-xs font-theme-data text-text-muted">Patterns</div>
              <div className="text-lg font-theme-data text-purple">
                {evolution.patterns_extracted}
              </div>
            </div>
            <div>
              <div className="text-xs font-theme-data text-text-muted">Total Versions</div>
              <div className="text-lg font-theme-data text-purple">{evolution.total_versions}</div>
            </div>
          </div>

          {Object.keys(evolution.agents).length > 0 && (
            <div className="flex flex-wrap gap-2 pt-2 border-t border-purple/20">
              {Object.entries(evolution.agents).map(([agent, stats]) => (
                <AgentBadge
                  key={agent}
                  agent={agent}
                  metric={stats.current_version}
                  label={`v${stats.current_version}`}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Recent Winners */}
      {debate_quality.recent_winners.length > 0 && (
        <div className="bg-surface border border-[var(--accent)]/30">
          <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
            <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
              {'>'} RECENT WINNERS
            </span>
          </div>
          <div className="p-4 flex flex-wrap gap-2">
            {debate_quality.recent_winners.map((winner, idx) => {
              const colors = getAgentColors(winner);
              return (
                <span
                  key={idx}
                  className={`px-2 py-1 text-xs font-theme-data ${colors.bg} ${colors.text} ${colors.border} border`}
                >
                  {winner}
                </span>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
