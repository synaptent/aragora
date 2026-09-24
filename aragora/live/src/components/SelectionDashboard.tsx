'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/config';

interface Plugin {
  name: string;
  description: string;
  version: string;
  configurable: boolean;
}

interface PluginsList {
  scorers: Plugin[];
  team_selectors: Plugin[];
  role_assigners: Plugin[];
}

interface Defaults {
  scorer: string;
  team_selector: string;
  role_assigner: string;
}

interface ScoredAgent {
  name: string;
  type: string;
  score: number;
  domain_expertise: number;
  elo_rating: number;
}

interface TeamMember {
  name: string;
  type: string;
  role: string;
  score: number;
  expertise: Record<string, number>;
  elo_rating: number;
}

interface TeamResult {
  team_id: string;
  task_id: string;
  agents: TeamMember[];
  expected_quality: number;
  expected_cost: number;
  diversity_score: number;
  rationale: string;
  plugins_used: { scorer: string; team_selector: string; role_assigner: string };
}

interface SelectionDashboardProps {
  apiBase: string;
}

export function SelectionDashboard({ apiBase: _apiBase }: SelectionDashboardProps) {
  const [plugins, setPlugins] = useState<PluginsList | null>(null);
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'plugins' | 'score' | 'team'>('plugins');

  // Score agents state
  const [scoreTask, setScoreTask] = useState('');
  const [selectedScorer, setSelectedScorer] = useState('');
  const [scoredAgents, setScoredAgents] = useState<ScoredAgent[]>([]);
  const [scoreLoading, setScoreLoading] = useState(false);

  // Team selection state
  const [teamTask, setTeamTask] = useState('');
  const [teamScorer, setTeamScorer] = useState('');
  const [teamSelector, setTeamSelector] = useState('');
  const [roleAssigner, setRoleAssigner] = useState('');
  const [minAgents, setMinAgents] = useState(2);
  const [maxAgents, setMaxAgents] = useState(5);
  const [qualityPriority, setQualityPriority] = useState(0.5);
  const [diversityPreference, setDiversityPreference] = useState(0.5);
  const [teamResult, setTeamResult] = useState<TeamResult | null>(null);
  const [teamLoading, setTeamLoading] = useState(false);

  const fetchPlugins = useCallback(async () => {
    setLoading(true);
    setError(null);

    const [pluginsRes, defaultsRes] = await Promise.all([
      apiFetch<PluginsList>('/api/selection/plugins'),
      apiFetch<Defaults>('/api/selection/defaults'),
    ]);

    if (pluginsRes.error) {
      setError(pluginsRes.error);
    } else if (pluginsRes.data) {
      setPlugins(pluginsRes.data);
    }

    if (defaultsRes.data) {
      setDefaults(defaultsRes.data);
      setSelectedScorer(defaultsRes.data.scorer);
      setTeamScorer(defaultsRes.data.scorer);
      setTeamSelector(defaultsRes.data.team_selector);
      setRoleAssigner(defaultsRes.data.role_assigner);
    }

    setLoading(false);
  }, []);

  useEffect(() => {
    fetchPlugins();
  }, [fetchPlugins]);

  const handleScoreAgents = async () => {
    if (!scoreTask.trim()) return;
    setScoreLoading(true);
    setScoredAgents([]);
    setError(null);

    const { data, error: scoreError } = await apiFetch<{
      scorer_used: string;
      agents: ScoredAgent[];
      task_id: string;
    }>('/api/selection/score', {
      method: 'POST',
      body: JSON.stringify({ task_description: scoreTask, scorer: selectedScorer || undefined }),
    });

    if (scoreError) {
      setError(scoreError);
    } else if (data) {
      setScoredAgents(data.agents);
    }
    setScoreLoading(false);
  };

  const handleSelectTeam = async () => {
    if (!teamTask.trim()) return;
    setTeamLoading(true);
    setTeamResult(null);
    setError(null);

    const { data, error: teamError } = await apiFetch<TeamResult>('/api/selection/team', {
      method: 'POST',
      body: JSON.stringify({
        task_description: teamTask,
        scorer: teamScorer || undefined,
        team_selector: teamSelector || undefined,
        role_assigner: roleAssigner || undefined,
        min_agents: minAgents,
        max_agents: maxAgents,
        quality_priority: qualityPriority,
        diversity_preference: diversityPreference,
      }),
    });

    if (teamError) {
      setError(teamError);
    } else if (data) {
      setTeamResult(data);
    }
    setTeamLoading(false);
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
        {(['plugins', 'score', 'team'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-4 py-2 text-xs font-theme-data rounded-t transition-colors ${
              activeTab === tab
                ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 border-b-0'
                : 'text-text-muted hover:text-[var(--accent)] hover:bg-[var(--accent)]/5'
            }`}
          >
            [{tab === 'plugins' ? 'PLUGINS' : tab === 'score' ? 'SCORE AGENTS' : 'SELECT TEAM'}]
          </button>
        ))}
      </div>

      {/* Plugins Tab */}
      {activeTab === 'plugins' && plugins && (
        <div className="space-y-6">
          {/* Scorers */}
          <PluginSection
            title="Agent Scorers"
            description="Score agents based on task requirements and agent capabilities"
            plugins={plugins.scorers}
            defaultPlugin={defaults?.scorer}
          />

          {/* Team Selectors */}
          <PluginSection
            title="Team Selectors"
            description="Select optimal agent combinations for tasks"
            plugins={plugins.team_selectors}
            defaultPlugin={defaults?.team_selector}
          />

          {/* Role Assigners */}
          <PluginSection
            title="Role Assigners"
            description="Assign roles to selected team members"
            plugins={plugins.role_assigners}
            defaultPlugin={defaults?.role_assigner}
          />

          <button
            onClick={fetchPlugins}
            className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors"
          >
            [REFRESH PLUGINS]
          </button>
        </div>
      )}

      {/* Score Agents Tab */}
      {activeTab === 'score' && plugins && (
        <div className="space-y-4">
          <div className="card p-6 space-y-4">
            <h3 className="text-lg font-theme-data text-[var(--accent)]">Score Agents</h3>
            <p className="text-xs text-text-muted font-theme-data">
              Evaluate how well each agent matches the requirements of your task.
            </p>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Task Description *
              </label>
              <textarea
                value={scoreTask}
                onChange={(e) => setScoreTask(e.target.value)}
                placeholder="Describe the task to find the best agents..."
                className="w-full h-24 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Scorer Plugin
              </label>
              <select
                value={selectedScorer}
                onChange={(e) => setSelectedScorer(e.target.value)}
                className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              >
                {plugins.scorers.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.name} {p.name === defaults?.scorer ? '(default)' : ''}
                  </option>
                ))}
              </select>
            </div>

            <button
              onClick={handleScoreAgents}
              disabled={scoreLoading || !scoreTask.trim()}
              className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {scoreLoading ? '[SCORING...]' : '[SCORE AGENTS]'}
            </button>
          </div>

          {/* Results */}
          {scoredAgents.length > 0 && (
            <div className="card p-6 space-y-4">
              <h4 className="text-sm font-theme-data text-[var(--acid-cyan)]">Agent Scores</h4>
              <div className="space-y-2">
                {scoredAgents.map((agent, index) => (
                  <div
                    key={agent.name}
                    className="flex items-center gap-3 p-3 bg-surface border border-[var(--accent)]/20 rounded"
                  >
                    <div
                      className={`w-8 h-8 flex items-center justify-center rounded-full text-sm font-bold ${
                        index === 0
                          ? 'bg-yellow-500/20 text-yellow-500 border border-yellow-500/50'
                          : index === 1
                            ? 'bg-gray-400/20 text-gray-400 border border-gray-400/50'
                            : index === 2
                              ? 'bg-orange-500/20 text-orange-600 border border-orange-500/50'
                              : 'bg-surface text-text-muted border border-border'
                      }`}
                    >
                      {index + 1}
                    </div>

                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-theme-data text-text">{agent.name}</span>
                        <span className="text-xs text-text-muted">({agent.type})</span>
                      </div>
                      <div className="flex gap-3 text-xs font-theme-data text-text-muted mt-1">
                        <span>ELO: {agent.elo_rating}</span>
                        <span>Domain: {(agent.domain_expertise * 100).toFixed(0)}%</span>
                      </div>
                    </div>

                    <div className="text-right">
                      <div className="text-lg font-theme-data font-bold text-[var(--accent)]">
                        {(agent.score * 100).toFixed(1)}%
                      </div>
                      <div className="w-24 h-2 bg-surface rounded overflow-hidden">
                        <div
                          className="h-full bg-[var(--accent)]"
                          style={{ width: `${agent.score * 100}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Select Team Tab */}
      {activeTab === 'team' && plugins && (
        <div className="space-y-4">
          <div className="card p-6 space-y-4">
            <h3 className="text-lg font-theme-data text-[var(--accent)]">Select Team</h3>
            <p className="text-xs text-text-muted font-theme-data">
              Build an optimal team of agents for your task with role assignments.
            </p>

            <div>
              <label className="block text-xs font-theme-data text-text-muted mb-1">
                Task Description *
              </label>
              <textarea
                value={teamTask}
                onChange={(e) => setTeamTask(e.target.value)}
                placeholder="Describe the task to build a team..."
                className="w-full h-24 p-3 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
              />
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">Scorer</label>
                <select
                  value={teamScorer}
                  onChange={(e) => setTeamScorer(e.target.value)}
                  className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  {plugins.scorers.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Team Selector
                </label>
                <select
                  value={teamSelector}
                  onChange={(e) => setTeamSelector(e.target.value)}
                  className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  {plugins.team_selectors.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Role Assigner
                </label>
                <select
                  value={roleAssigner}
                  onChange={(e) => setRoleAssigner(e.target.value)}
                  className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                >
                  {plugins.role_assigners.map((p) => (
                    <option key={p.name} value={p.name}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Min Agents
                </label>
                <input
                  type="number"
                  value={minAgents}
                  onChange={(e) => setMinAgents(parseInt(e.target.value) || 2)}
                  min={1}
                  max={10}
                  className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Max Agents
                </label>
                <input
                  type="number"
                  value={maxAgents}
                  onChange={(e) => setMaxAgents(parseInt(e.target.value) || 5)}
                  min={1}
                  max={10}
                  className="w-full p-2 bg-surface border border-[var(--accent)]/30 rounded font-theme-data text-sm focus:outline-none focus:border-[var(--accent)]"
                />
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Quality Priority
                  <span className="ml-1 text-[var(--accent)]">
                    {(qualityPriority * 100).toFixed(0)}%
                  </span>
                </label>
                <input
                  type="range"
                  value={qualityPriority}
                  onChange={(e) => setQualityPriority(parseFloat(e.target.value))}
                  min={0}
                  max={1}
                  step={0.1}
                  className="w-full"
                />
              </div>

              <div>
                <label className="block text-xs font-theme-data text-text-muted mb-1">
                  Diversity Pref
                  <span className="ml-1 text-[var(--accent)]">
                    {(diversityPreference * 100).toFixed(0)}%
                  </span>
                </label>
                <input
                  type="range"
                  value={diversityPreference}
                  onChange={(e) => setDiversityPreference(parseFloat(e.target.value))}
                  min={0}
                  max={1}
                  step={0.1}
                  className="w-full"
                />
              </div>
            </div>

            <button
              onClick={handleSelectTeam}
              disabled={teamLoading || !teamTask.trim()}
              className="px-4 py-2 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/50 rounded hover:bg-[var(--accent)]/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {teamLoading ? '[SELECTING...]' : '[SELECT TEAM]'}
            </button>
          </div>

          {/* Team Result */}
          {teamResult && (
            <div className="card p-6 space-y-4">
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-theme-data text-[var(--acid-cyan)]">Selected Team</h4>
                <span className="text-xs font-theme-data text-text-muted">
                  ID: {teamResult.team_id}
                </span>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-3 gap-4">
                <MetricCard
                  label="Expected Quality"
                  value={`${(teamResult.expected_quality * 100).toFixed(1)}%`}
                  color="acid-green"
                />
                <MetricCard
                  label="Diversity Score"
                  value={`${(teamResult.diversity_score * 100).toFixed(0)}%`}
                  color="acid-cyan"
                />
                <MetricCard
                  label="Expected Cost"
                  value={teamResult.expected_cost.toFixed(2)}
                  color="yellow-500"
                />
              </div>

              {/* Rationale */}
              <div className="p-3 bg-surface border border-[var(--accent)]/20 rounded">
                <p className="text-xs font-theme-data text-text-muted italic">
                  {teamResult.rationale}
                </p>
              </div>

              {/* Team Members */}
              <div className="space-y-2">
                {teamResult.agents.map((agent) => (
                  <div
                    key={agent.name}
                    className="flex items-center gap-3 p-3 bg-surface border border-[var(--accent)]/20 rounded"
                  >
                    <RoleBadge role={agent.role} />

                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-theme-data text-text">{agent.name}</span>
                        <span className="text-xs text-text-muted">({agent.type})</span>
                      </div>
                      <div className="flex gap-3 text-xs font-theme-data text-text-muted mt-1">
                        <span>ELO: {agent.elo_rating}</span>
                        <span>Score: {(agent.score * 100).toFixed(1)}%</span>
                      </div>
                    </div>

                    {/* Top expertise areas */}
                    <div className="flex flex-wrap gap-1">
                      {Object.entries(agent.expertise)
                        .filter(([, v]) => v > 0.6)
                        .slice(0, 3)
                        .map(([domain, value]) => (
                          <span
                            key={domain}
                            className="px-2 py-0.5 text-xs bg-[var(--accent)]/10 text-[var(--accent)] rounded"
                          >
                            {domain}: {(value * 100).toFixed(0)}%
                          </span>
                        ))}
                    </div>
                  </div>
                ))}
              </div>

              {/* Plugins Used */}
              <div className="flex gap-4 text-xs font-theme-data text-text-muted">
                <span>
                  Scorer:{' '}
                  <span className="text-[var(--accent)]">{teamResult.plugins_used.scorer}</span>
                </span>
                <span>
                  Selector:{' '}
                  <span className="text-[var(--accent)]">
                    {teamResult.plugins_used.team_selector}
                  </span>
                </span>
                <span>
                  Assigner:{' '}
                  <span className="text-[var(--accent)]">
                    {teamResult.plugins_used.role_assigner}
                  </span>
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function PluginSection({
  title,
  description,
  plugins,
  defaultPlugin,
}: {
  title: string;
  description: string;
  plugins: Plugin[];
  defaultPlugin?: string;
}) {
  return (
    <div className="card p-4 space-y-3">
      <div>
        <h4 className="text-sm font-theme-data text-[var(--accent)]">{title}</h4>
        <p className="text-xs text-text-muted font-theme-data">{description}</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
        {plugins.map((plugin) => (
          <div
            key={plugin.name}
            className={`p-3 border rounded transition-colors ${
              plugin.name === defaultPlugin
                ? 'border-[var(--accent)]/50 bg-[var(--accent)]/5'
                : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/40'
            }`}
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="font-theme-data text-text">{plugin.name}</span>
              {plugin.name === defaultPlugin && (
                <span className="px-1.5 py-0.5 text-xs bg-[var(--accent)]/20 text-[var(--accent)] rounded">
                  default
                </span>
              )}
              <span className="text-xs text-text-muted ml-auto">v{plugin.version}</span>
            </div>
            <p className="text-xs text-text-muted">{plugin.description}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="p-3 bg-surface border border-[var(--accent)]/20 rounded text-center">
      <p className="text-xs font-theme-data text-text-muted">{label}</p>
      <p className={`text-xl font-theme-data font-bold text-${color}`}>{value}</p>
    </div>
  );
}

function RoleBadge({ role }: { role: string }) {
  const roleStyles: Record<string, { bg: string; text: string }> = {
    lead: { bg: 'bg-yellow-500/20', text: 'text-yellow-500' },
    primary: { bg: 'bg-[var(--accent)]/20', text: 'text-[var(--accent)]' },
    specialist: { bg: 'bg-[var(--acid-cyan)]/20', text: 'text-[var(--acid-cyan)]' },
    devil_advocate: { bg: 'bg-red-500/20', text: 'text-red-400' },
    critic: { bg: 'bg-orange-500/20', text: 'text-orange-400' },
    synthesizer: { bg: 'bg-purple-500/20', text: 'text-purple-400' },
    participant: { bg: 'bg-gray-500/20', text: 'text-gray-400' },
  };

  const style = roleStyles[role] || roleStyles.participant;

  return (
    <span
      className={`px-2 py-1 text-xs font-theme-data rounded ${style.bg} ${style.text} uppercase`}
    >
      {role.replace('_', ' ')}
    </span>
  );
}
