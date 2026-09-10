'use client';

import { useEffect, useState } from 'react';

interface OrgSummaryData {
  period: string;
  cost_summary: {
    total_cost_usd: string;
    budget_limit_usd: string;
    budget_percentage_used: number;
    cost_trend_percent: number;
    projected_month_end_usd: string;
  };
  debate_summary: {
    debates_completed: number;
    debates_in_progress: number;
    consensus_reached: number;
    consensus_rate_percent: number;
    avg_rounds_to_consensus: number;
    avg_debate_duration_minutes: number;
  };
  user_summary: {
    active_users: number;
    new_users_this_period: number;
    user_growth_percent: number;
    avg_debates_per_user: number;
    power_users: number;
  };
  agent_summary: {
    active_agents: number;
    top_agents: Array<{
      name: string;
      efficiency_score: number;
      debates_participated: number;
      win_rate: number;
    }>;
  };
  health: {
    status: string;
    api_availability_percent: number;
    avg_response_time_ms: number;
    error_rate_percent: number;
  };
}

interface OrgSummaryProps {
  backendUrl: string;
}

export function OrgSummary({ backendUrl }: OrgSummaryProps) {
  const [data, setData] = useState<OrgSummaryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [period, setPeriod] = useState('monthly');

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(
          `${backendUrl}/api/v1/intelligence/org-summary?period=${period}`,
        );
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        const result = await response.json();
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch data');
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [backendUrl, period]);

  if (loading) {
    return (
      <div className="card p-6">
        <div className="animate-pulse">
          <div className="h-6 bg-surface rounded w-1/3 mb-4"></div>
          <div className="grid grid-cols-4 gap-4">
            {[1, 2, 3, 4].map((i) => (
              <div key={i} className="h-24 bg-surface rounded"></div>
            ))}
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-6 border-red-500/50">
        <p className="text-red-500 font-theme-data text-sm">Error: {error}</p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="card p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-lg font-theme-data text-[var(--accent)]">Organization Summary</h2>
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          className="bg-surface border border-[var(--accent)]/30 rounded px-2 py-1 text-xs font-theme-data"
        >
          <option value="daily">Daily</option>
          <option value="weekly">Weekly</option>
          <option value="monthly">Monthly</option>
          <option value="quarterly">Quarterly</option>
        </select>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        {/* Cost KPI */}
        <div className="bg-surface/50 rounded-lg p-4 border border-[var(--accent)]/20">
          <p className="text-text-muted text-xs font-theme-data mb-1">Total Cost</p>
          <p className="text-2xl font-theme-data text-[var(--accent)]">
            ${data.cost_summary.total_cost_usd}
          </p>
          <p className="text-xs font-theme-data mt-1">
            <span
              className={
                data.cost_summary.cost_trend_percent > 0 ? 'text-red-400' : 'text-green-400'
              }
            >
              {data.cost_summary.cost_trend_percent > 0 ? '+' : ''}
              {data.cost_summary.cost_trend_percent}%
            </span>
            <span className="text-text-muted"> vs last period</span>
          </p>
          <div className="mt-2 h-1 bg-bg rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--accent)]"
              style={{ width: `${data.cost_summary.budget_percentage_used}%` }}
            ></div>
          </div>
          <p className="text-xs text-text-muted mt-1">
            {data.cost_summary.budget_percentage_used}% of ${data.cost_summary.budget_limit_usd}{' '}
            budget
          </p>
        </div>

        {/* Debates KPI */}
        <div className="bg-surface/50 rounded-lg p-4 border border-[var(--accent)]/20">
          <p className="text-text-muted text-xs font-theme-data mb-1">Debates Completed</p>
          <p className="text-2xl font-theme-data text-[var(--accent)]">
            {data.debate_summary.debates_completed}
          </p>
          <p className="text-xs font-theme-data mt-1">
            <span className="text-yellow-400">{data.debate_summary.debates_in_progress}</span>
            <span className="text-text-muted"> in progress</span>
          </p>
        </div>

        {/* Consensus KPI */}
        <div className="bg-surface/50 rounded-lg p-4 border border-[var(--accent)]/20">
          <p className="text-text-muted text-xs font-theme-data mb-1">Consensus Rate</p>
          <p className="text-2xl font-theme-data text-[var(--accent)]">
            {data.debate_summary.consensus_rate_percent}%
          </p>
          <p className="text-xs font-theme-data mt-1">
            <span className="text-text-muted">{data.debate_summary.consensus_reached} reached</span>
          </p>
          <p className="text-xs text-text-muted mt-1">
            Avg {data.debate_summary.avg_rounds_to_consensus} rounds
          </p>
        </div>

        {/* Users KPI */}
        <div className="bg-surface/50 rounded-lg p-4 border border-[var(--accent)]/20">
          <p className="text-text-muted text-xs font-theme-data mb-1">Active Users</p>
          <p className="text-2xl font-theme-data text-[var(--accent)]">
            {data.user_summary.active_users}
          </p>
          <p className="text-xs font-theme-data mt-1">
            <span className="text-green-400">+{data.user_summary.new_users_this_period}</span>
            <span className="text-text-muted"> new</span>
          </p>
          <p className="text-xs text-text-muted mt-1">
            {data.user_summary.user_growth_percent}% growth
          </p>
        </div>
      </div>

      {/* Top Agents */}
      <div className="bg-surface/30 rounded-lg p-4 border border-[var(--accent)]/10">
        <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">
          Top Agents by Efficiency
        </h3>
        <div className="space-y-2">
          {data.agent_summary.top_agents.map((agent, index) => (
            <div key={agent.name} className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-xs font-theme-data text-text-muted">#{index + 1}</span>
                <span className="text-sm font-theme-data">{agent.name}</span>
              </div>
              <div className="flex items-center gap-4">
                <span className="text-xs font-theme-data text-text-muted">
                  {agent.debates_participated} debates
                </span>
                <span className="text-xs font-theme-data text-text-muted">
                  {(agent.win_rate * 100).toFixed(0)}% win
                </span>
                <div className="w-16 h-2 bg-bg rounded-full overflow-hidden">
                  <div
                    className="h-full bg-[var(--accent)]"
                    style={{ width: `${agent.efficiency_score * 100}%` }}
                  ></div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Health Status */}
      <div className="mt-4 flex items-center justify-between text-xs font-theme-data">
        <div className="flex items-center gap-2">
          <div
            className={`w-2 h-2 rounded-full ${
              data.health.status === 'healthy' ? 'bg-green-400' : 'bg-yellow-400'
            }`}
          ></div>
          <span className="text-text-muted">System {data.health.status}</span>
        </div>
        <div className="flex items-center gap-4 text-text-muted">
          <span>{data.health.api_availability_percent}% uptime</span>
          <span>{data.health.avg_response_time_ms}ms avg</span>
          <span>{data.health.error_rate_percent}% errors</span>
        </div>
      </div>
    </div>
  );
}
