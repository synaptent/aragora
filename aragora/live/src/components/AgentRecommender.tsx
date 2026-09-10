'use client';

import { useState, useCallback, useEffect } from 'react';
import {
  useAgentRouting,
  type AgentRecommendation,
  type DomainLeaderboardEntry,
  type TeamCombination,
} from '@/hooks/useAgentRouting';

// ============================================================================
// Score Bar Component
// ============================================================================

function ScoreBar({
  score,
  maxScore = 1,
  color = 'bg-[var(--accent)]',
}: {
  score: number;
  maxScore?: number;
  color?: string;
}) {
  const percentage = Math.round((score / maxScore) * 100);
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-surface rounded overflow-hidden">
        <div
          className={`h-full ${color} transition-all duration-300`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-xs font-theme-data text-text-muted w-8 text-right">{percentage}%</span>
    </div>
  );
}

// ============================================================================
// Topic Analyzer
// ============================================================================

interface TopicAnalyzerProps {
  onAnalyze: (task: string) => Promise<void>;
  loading: boolean;
}

function TopicAnalyzer({ onAnalyze, loading }: TopicAnalyzerProps) {
  const [task, setTask] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (task.trim()) {
      await onAnalyze(task.trim());
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div>
        <label className="block text-xs font-theme-data text-text-muted mb-1">
          Enter your debate topic or question
        </label>
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          rows={3}
          placeholder="e.g., Should we migrate to microservices?"
          className="w-full px-3 py-2 bg-bg border border-[var(--accent)]/30 text-text font-theme-data text-sm focus:border-[var(--accent)] focus:outline-none resize-none"
        />
      </div>
      <button
        type="submit"
        disabled={loading || !task.trim()}
        className="w-full py-2 bg-[var(--accent)]/10 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-xs hover:bg-[var(--accent)]/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {loading ? 'ANALYZING...' : 'ANALYZE & RECOMMEND AGENTS'}
      </button>
    </form>
  );
}

// ============================================================================
// Team Preview
// ============================================================================

interface TeamPreviewProps {
  agents: string[];
  roles: Record<string, string>;
  expectedQuality: number;
  diversityScore: number;
  rationale: string;
  onSelect?: (agents: string[]) => void;
}

function TeamPreview({
  agents,
  roles,
  expectedQuality,
  diversityScore,
  rationale,
  onSelect,
}: TeamPreviewProps) {
  return (
    <div className="p-4 bg-surface border border-[var(--accent)]/30">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase">
          RECOMMENDED TEAM
        </span>
        {onSelect && (
          <button
            onClick={() => onSelect(agents)}
            className="px-3 py-1 text-xs font-theme-data border border-[var(--acid-cyan)] text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
          >
            USE TEAM
          </button>
        )}
      </div>

      {/* Agents */}
      <div className="flex flex-wrap gap-2 mb-4">
        {agents.map((agent) => (
          <div
            key={agent}
            className="px-3 py-1.5 bg-bg border border-[var(--accent)]/40 text-sm font-theme-data text-[var(--accent)]"
          >
            {agent}
            {roles[agent] && <span className="ml-2 text-xs text-text-muted">({roles[agent]})</span>}
          </div>
        ))}
      </div>

      {/* Scores */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <div className="text-xs font-theme-data text-text-muted mb-1">Expected Quality</div>
          <ScoreBar score={expectedQuality} />
        </div>
        <div>
          <div className="text-xs font-theme-data text-text-muted mb-1">Diversity</div>
          <ScoreBar score={diversityScore} color="bg-[var(--acid-cyan)]" />
        </div>
      </div>

      {/* Rationale */}
      <div className="p-2 bg-bg/50 rounded text-xs font-theme-data text-text-muted">
        {rationale}
      </div>
    </div>
  );
}

// ============================================================================
// Recommendations List
// ============================================================================

function RecommendationsList({ recommendations }: { recommendations: AgentRecommendation[] }) {
  if (recommendations.length === 0) {
    return (
      <div className="p-4 text-center text-xs font-theme-data text-text-muted">
        No recommendations available
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {recommendations.map((rec, idx) => (
        <div
          key={rec.agent}
          className="p-3 bg-surface border border-[var(--accent)]/20 hover:border-[var(--accent)]/40 transition-colors"
        >
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-theme-data text-text-muted">#{idx + 1}</span>
              <span className="font-theme-data text-sm text-[var(--accent)]">{rec.agent}</span>
            </div>
            <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
              {Math.round(rec.score * 100)}%
            </span>
          </div>
          <ScoreBar score={rec.score} />
          {rec.traits.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {rec.traits.slice(0, 3).map((trait) => (
                <span
                  key={trait}
                  className="px-1.5 py-0.5 text-xs font-theme-data text-text-muted bg-bg rounded"
                >
                  {trait}
                </span>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ============================================================================
// Domain Leaderboard
// ============================================================================

interface DomainLeaderboardProps {
  domain: string;
  leaderboard: DomainLeaderboardEntry[];
  onDomainChange: (domain: string) => void;
  loading: boolean;
}

function DomainLeaderboard({
  domain,
  leaderboard,
  onDomainChange,
  loading,
}: DomainLeaderboardProps) {
  const domains = [
    'general',
    'programming',
    'architecture',
    'security',
    'ml',
    'devops',
    'database',
  ];

  return (
    <div className="space-y-3">
      {/* Domain Selector */}
      <div className="flex flex-wrap gap-1">
        {domains.map((d) => (
          <button
            key={d}
            onClick={() => onDomainChange(d)}
            className={`px-2 py-1 text-xs font-theme-data border transition-colors ${
              domain === d
                ? 'border-[var(--accent)] text-[var(--accent)] bg-[var(--accent)]/10'
                : 'border-[var(--accent)]/30 text-text-muted hover:text-text'
            }`}
          >
            {d.toUpperCase()}
          </button>
        ))}
      </div>

      {/* Leaderboard */}
      {loading ? (
        <div className="p-4 text-center text-xs font-theme-data text-text-muted animate-pulse">
          Loading leaderboard...
        </div>
      ) : leaderboard.length === 0 ? (
        <div className="p-4 text-center text-xs font-theme-data text-text-muted">
          No data for {domain} domain
        </div>
      ) : (
        <div className="space-y-2">
          {leaderboard.map((entry, idx) => (
            <div
              key={entry.agent}
              className="flex items-center gap-3 p-2 bg-surface/50 border border-[var(--accent)]/10"
            >
              <span className="w-6 text-center text-xs font-theme-data text-text-muted">
                {idx + 1}
              </span>
              <span className="flex-1 font-theme-data text-sm text-text">{entry.agent}</span>
              <span className="text-xs font-theme-data text-[var(--accent)]">
                {Math.round(entry.score * 100)}%
              </span>
              <span className="text-xs font-theme-data text-text-muted">
                {entry.wins}W/{entry.losses}L
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Best Teams Panel
// ============================================================================

function BestTeamsPanel({
  teams,
  loading,
  onRefresh,
}: {
  teams: TeamCombination[];
  loading: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="space-y-3">
      <button
        onClick={onRefresh}
        disabled={loading}
        className="w-full py-1 text-xs font-theme-data text-text-muted hover:text-[var(--accent)] border border-[var(--accent)]/20 hover:border-[var(--accent)]/40 transition-colors disabled:opacity-50"
      >
        {loading ? 'Loading...' : 'Refresh Best Teams'}
      </button>

      {teams.length === 0 ? (
        <div className="p-4 text-center text-xs font-theme-data text-text-muted">
          No team data available
        </div>
      ) : (
        <div className="space-y-2">
          {teams.map((team, idx) => (
            <div key={idx} className="p-3 bg-surface border border-[var(--accent)]/20">
              <div className="flex flex-wrap gap-1 mb-2">
                {team.agents.map((agent) => (
                  <span
                    key={agent}
                    className="px-2 py-0.5 text-xs font-theme-data text-[var(--accent)] bg-[var(--accent)]/10 rounded"
                  >
                    {agent}
                  </span>
                ))}
              </div>
              <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted">
                <span>
                  Win Rate:{' '}
                  <span className="text-[var(--acid-cyan)]">
                    {Math.round(team.win_rate * 100)}%
                  </span>
                </span>
                <span>Debates: {team.debates}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ============================================================================
// Main Component
// ============================================================================

interface AgentRecommenderProps {
  onTeamSelect?: (agents: string[]) => void;
}

export function AgentRecommender({ onTeamSelect }: AgentRecommenderProps) {
  const routing = useAgentRouting();
  const [activeTab, setActiveTab] = useState<'analyze' | 'leaderboard' | 'teams'>('analyze');
  const [selectedDomain, setSelectedDomain] = useState('general');

  // Fetch leaderboard when domain changes
  useEffect(() => {
    if (activeTab === 'leaderboard') {
      routing.getDomainLeaderboard(selectedDomain, 10);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedDomain, activeTab]);

  // Fetch best teams when tab changes
  useEffect(() => {
    if (activeTab === 'teams') {
      routing.getBestTeams(3, 10);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  const handleAnalyze = useCallback(
    async (task: string) => {
      await routing.autoRoute(task);
    },
    [routing],
  );

  const handleDomainChange = useCallback((domain: string) => {
    setSelectedDomain(domain);
  }, []);

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
          {'>'} AGENT RECOMMENDER
        </span>
      </div>

      {/* Tabs */}
      <div
        className="flex border-b border-[var(--accent)]/10"
        role="tablist"
        aria-label="Agent recommender views"
      >
        {(['analyze', 'leaderboard', 'teams'] as const).map((tab) => (
          <button
            key={tab}
            role="tab"
            aria-selected={activeTab === tab}
            aria-controls={`tabpanel-${tab}`}
            id={`tab-${tab}`}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 px-4 py-2 text-xs font-theme-data uppercase transition-colors ${
              activeTab === tab
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-[var(--accent)]/5'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Error Display */}
      {(routing.autoRouteError || routing.leaderboardError || routing.bestTeamsError) && (
        <div className="px-4 py-2 border-b border-acid-red/30">
          <div className="p-2 text-xs font-theme-data text-acid-red bg-acid-red/10 border border-acid-red/30">
            {'>'} {routing.autoRouteError || routing.leaderboardError || routing.bestTeamsError}
          </div>
        </div>
      )}

      {/* Content */}
      <div className="p-4">
        {activeTab === 'analyze' && (
          <div
            id="tabpanel-analyze"
            role="tabpanel"
            aria-labelledby="tab-analyze"
            className="space-y-4"
          >
            <TopicAnalyzer onAnalyze={handleAnalyze} loading={routing.autoRouteLoading} />

            {routing.autoRouteResult && (
              <>
                {/* Detected Domains */}
                <div className="p-3 bg-bg/50 border border-[var(--accent)]/20">
                  <div className="text-xs font-theme-data text-text-muted mb-2">
                    DETECTED DOMAIN
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {Object.entries(routing.autoRouteResult.detected_domain).map(
                      ([domain, score]) => (
                        <span
                          key={domain}
                          className="px-2 py-1 text-xs font-theme-data bg-surface border border-[var(--acid-cyan)]/30 text-[var(--acid-cyan)]"
                        >
                          {domain}: {Math.round((score as number) * 100)}%
                        </span>
                      ),
                    )}
                  </div>
                </div>

                {/* Team Preview */}
                <TeamPreview
                  agents={routing.autoRouteResult.team.agents}
                  roles={routing.autoRouteResult.team.roles}
                  expectedQuality={routing.autoRouteResult.team.expected_quality}
                  diversityScore={routing.autoRouteResult.team.diversity_score}
                  rationale={routing.autoRouteResult.rationale}
                  onSelect={onTeamSelect}
                />
              </>
            )}

            {routing.recommendations.length > 0 && (
              <div>
                <div className="text-xs font-theme-data text-text-muted mb-2">
                  INDIVIDUAL RECOMMENDATIONS
                </div>
                <RecommendationsList recommendations={routing.recommendations} />
              </div>
            )}
          </div>
        )}

        {activeTab === 'leaderboard' && (
          <div id="tabpanel-leaderboard" role="tabpanel" aria-labelledby="tab-leaderboard">
            <DomainLeaderboard
              domain={selectedDomain}
              leaderboard={routing.domainLeaderboard}
              onDomainChange={handleDomainChange}
              loading={routing.leaderboardLoading}
            />
          </div>
        )}

        {activeTab === 'teams' && (
          <div id="tabpanel-teams" role="tabpanel" aria-labelledby="tab-teams">
            <BestTeamsPanel
              teams={routing.bestTeams}
              loading={routing.bestTeamsLoading}
              onRefresh={() => routing.getBestTeams(3, 10)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
