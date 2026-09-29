'use client';

import { useState, useEffect, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { logger } from '@/utils/logger';
import { API_BASE_URL } from '@/config';
import {
  type AgentProfile,
  type Moment,
  type NetworkData,
  type HeadToHeadData,
  type DomainData,
  type PerformanceData,
  type HistoryEntry,
  getEloColor,
  getConsistencyColor,
  getMomentIcon,
} from './types';
import { TrustBadge } from '@/components/TrustBadge';

const DEFAULT_API_BASE = API_BASE_URL;

export function AgentProfileWrapper() {
  const params = useParams();
  const router = useRouter();

  // Handle optional catch-all - name could be undefined or an array
  const nameParam = params.name;
  const agentName = Array.isArray(nameParam) ? decodeURIComponent(nameParam[0]) : null;

  const [profile, setProfile] = useState<AgentProfile | null>(null);
  const [moments, setMoments] = useState<Moment[]>([]);
  const [network, setNetwork] = useState<NetworkData | null>(null);
  const [headToHead, setHeadToHead] = useState<HeadToHeadData | null>(null);
  const [domains, setDomains] = useState<DomainData | null>(null);
  const [performance, setPerformance] = useState<PerformanceData | null>(null);
  const [history, setHistory] = useState<HistoryEntry[]>([]);
  const [selectedRival, setSelectedRival] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    'overview' | 'moments' | 'network' | 'compare' | 'domains' | 'performance' | 'history'
  >('overview');

  const apiBase = DEFAULT_API_BASE;

  const fetchData = useCallback(async () => {
    if (!agentName) {
      setLoading(false);
      return;
    }

    try {
      setLoading(true);
      setError(null);

      // Fetch profile, moments, network, domains, performance, and history in parallel
      const [profileRes, momentsRes, networkRes, domainsRes, performanceRes, historyRes] =
        await Promise.all([
          fetch(`${apiBase}/api/agent/${encodeURIComponent(agentName)}/profile`),
          fetch(`${apiBase}/api/agent/${encodeURIComponent(agentName)}/moments?limit=10`),
          fetch(`${apiBase}/api/agent/${encodeURIComponent(agentName)}/network`),
          fetch(`${apiBase}/api/agent/${encodeURIComponent(agentName)}/domains`),
          fetch(`${apiBase}/api/agent/${encodeURIComponent(agentName)}/performance`),
          fetch(`${apiBase}/api/agent/${encodeURIComponent(agentName)}/history?limit=20`),
        ]);

      if (profileRes.ok) {
        const data = await profileRes.json();
        setProfile(data);
      }

      if (momentsRes.ok) {
        const data = await momentsRes.json();
        setMoments(data.moments || []);
      }

      if (networkRes.ok) {
        const data = await networkRes.json();
        setNetwork(data);
        // Auto-select first rival for comparison
        if (data.rivals?.length > 0) {
          setSelectedRival((prev) => prev ?? data.rivals[0].agent);
        }
      }

      if (domainsRes.ok) {
        const data = await domainsRes.json();
        setDomains(data);
      }

      if (performanceRes.ok) {
        const data = await performanceRes.json();
        setPerformance(data);
      }

      if (historyRes.ok) {
        const data = await historyRes.json();
        setHistory(data.history || []);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch agent data');
    } finally {
      setLoading(false);
    }
  }, [agentName, apiBase]);

  // Fetch head-to-head when rival is selected
  const fetchHeadToHead = useCallback(
    async (opponent: string) => {
      if (!agentName) return;

      try {
        const res = await fetch(
          `${apiBase}/api/agent/${encodeURIComponent(agentName)}/head-to-head/${encodeURIComponent(opponent)}`,
        );
        if (res.ok) {
          const data = await res.json();
          setHeadToHead(data);
        }
      } catch (err) {
        logger.error('Failed to fetch head-to-head:', err);
      }
    },
    [agentName, apiBase],
  );

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (selectedRival) {
      fetchHeadToHead(selectedRival);
    }
  }, [selectedRival, fetchHeadToHead]);

  // Base route - show agent list or redirect to dashboard
  if (!agentName) {
    return (
      <div className="min-h-screen bg-bg p-6">
        <div className="max-w-4xl mx-auto text-center">
          <h1 className="text-2xl font-bold text-text mb-4">Agent Profiles</h1>
          <p className="text-text-muted mb-6">
            Select an agent from the leaderboard to view their profile.
          </p>
          <Link
            href="/"
            className="px-4 py-2 bg-accent text-bg rounded hover:bg-accent/80 transition-colors"
          >
            Go to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-bg p-6">
        <div className="max-w-4xl mx-auto">
          <div className="text-center text-text-muted py-20">Loading agent profile...</div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="min-h-screen bg-bg p-6">
        <div className="max-w-4xl mx-auto">
          <div className="text-center text-red-400 py-20">{error}</div>
          <div className="text-center">
            <Link href="/" className="text-accent hover:underline">
              Return to Dashboard
            </Link>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bg p-6">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-4">
            <button
              onClick={() => router.back()}
              className="text-text-muted hover:text-text transition-colors"
            >
              ← Back
            </button>
            <h1 className="text-2xl font-bold text-text font-theme-data">{agentName}</h1>
            {profile?.calibration && (
              <TrustBadge
                calibration={{
                  brier_score: profile.calibration.brier_score,
                  ece: profile.calibration.ece ?? 0,
                  trust_tier: profile.calibration.trust_tier ?? 'unrated',
                  prediction_count: profile.calibration.prediction_count,
                }}
                size="lg"
              />
            )}
            {profile?.persona?.type && (
              <span className="px-2 py-1 bg-accent/20 text-accent text-sm rounded">
                {profile.persona.type}
              </span>
            )}
          </div>
          <Link
            href="/"
            className="px-3 py-1.5 bg-surface border border-border rounded text-sm text-text hover:bg-surface-hover"
          >
            Dashboard
          </Link>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          {/* ELO */}
          <div className="bg-surface border border-border rounded-lg p-4">
            <div className="text-xs text-text-muted mb-1">ELO Rating</div>
            <div
              className={`text-2xl font-bold font-theme-data ${getEloColor(profile?.ranking?.rating?.elo || 1500)}`}
            >
              {profile?.ranking?.rating?.elo || 1500}
            </div>
          </div>

          {/* Win Rate */}
          <div className="bg-surface border border-border rounded-lg p-4">
            <div className="text-xs text-text-muted mb-1">Win Rate</div>
            <div className="text-2xl font-bold font-theme-data text-text">
              {profile?.ranking?.rating?.games_played
                ? `${((profile.ranking.rating.wins / profile.ranking.rating.games_played) * 100).toFixed(0)}%`
                : 'N/A'}
            </div>
            <div className="text-xs text-text-muted">
              {profile?.ranking?.rating?.wins || 0}W-{profile?.ranking?.rating?.losses || 0}L-
              {profile?.ranking?.rating?.draws || 0}D
            </div>
          </div>

          {/* Consistency */}
          <div className="bg-surface border border-border rounded-lg p-4">
            <div className="text-xs text-text-muted mb-1">Consistency</div>
            <div
              className={`text-2xl font-bold font-theme-data ${getConsistencyColor(profile?.consistency?.score || 0)}`}
            >
              {profile?.consistency?.score
                ? `${(profile.consistency.score * 100).toFixed(0)}%`
                : 'N/A'}
            </div>
            {profile?.consistency?.recent_flips !== undefined && (
              <div className="text-xs text-text-muted">
                {profile.consistency.recent_flips} recent flips
              </div>
            )}
          </div>

          {/* Calibration */}
          <div className="bg-surface border border-border rounded-lg p-4">
            <div className="text-xs text-text-muted mb-1">Calibration</div>
            <div className="text-2xl font-bold font-theme-data text-text">
              {profile?.calibration?.brier_score !== undefined
                ? profile.calibration.brier_score.toFixed(3)
                : 'N/A'}
            </div>
            {profile?.calibration?.prediction_count !== undefined && (
              <div className="text-xs text-text-muted">
                {profile.calibration.prediction_count} predictions
              </div>
            )}
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="flex flex-wrap gap-1 bg-surface border border-border rounded p-1 mb-6">
          {(
            [
              'overview',
              'performance',
              'domains',
              'history',
              'moments',
              'network',
              'compare',
            ] as const
          ).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-2 rounded text-sm transition-colors capitalize ${
                activeTab === tab
                  ? 'bg-accent text-bg font-medium'
                  : 'text-text-muted hover:text-text'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Tab Content */}
        <div className="bg-surface border border-border rounded-lg p-6">
          {/* Overview Tab */}
          {activeTab === 'overview' && (
            <div className="space-y-6">
              {/* Persona Info */}
              {profile?.persona && (
                <div>
                  <h3 className="text-lg font-semibold text-text mb-3">Persona</h3>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-xs text-text-muted mb-1">Primary Stance</div>
                      <div className="text-text">{profile.persona.primary_stance || 'Neutral'}</div>
                    </div>
                    <div>
                      <div className="text-xs text-text-muted mb-1">Debate Count</div>
                      <div className="text-text">{profile.persona.debate_count || 0}</div>
                    </div>
                  </div>
                  {profile.persona.specializations?.length > 0 && (
                    <div className="mt-4">
                      <div className="text-xs text-text-muted mb-2">Specializations</div>
                      <div className="flex flex-wrap gap-2">
                        {profile.persona.specializations.map((spec) => (
                          <span
                            key={spec}
                            className="px-2 py-1 bg-bg border border-border rounded text-sm text-text"
                          >
                            {spec}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Recent Moments Preview */}
              {moments.length > 0 && (
                <div>
                  <h3 className="text-lg font-semibold text-text mb-3">Recent Moments</h3>
                  <div className="space-y-2">
                    {moments.slice(0, 3).map((moment, idx) => (
                      <div
                        key={idx}
                        className="flex items-center gap-3 p-3 bg-bg border border-border rounded"
                      >
                        <span className="text-xl">{getMomentIcon(moment.type)}</span>
                        <div className="flex-1">
                          <div className="text-sm font-medium text-text">
                            {moment.type
                              .replace(/_/g, ' ')
                              .replace(/\b\w/g, (c) => c.toUpperCase())}
                          </div>
                          <div className="text-xs text-text-muted">{moment.description}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                  {moments.length > 3 && (
                    <button
                      onClick={() => setActiveTab('moments')}
                      className="mt-3 text-sm text-accent hover:underline"
                    >
                      View all {moments.length} moments →
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Moments Tab */}
          {activeTab === 'moments' && (
            <div className="space-y-3">
              <h3 className="text-lg font-semibold text-text mb-4">Moments Timeline</h3>
              {moments.length === 0 ? (
                <div className="text-center text-text-muted py-8">
                  No significant moments recorded yet.
                </div>
              ) : (
                moments.map((moment, idx) => (
                  <div key={idx} className="p-4 bg-bg border border-border rounded-lg">
                    <div className="flex items-start gap-3">
                      <span className="text-2xl">{getMomentIcon(moment.type)}</span>
                      <div className="flex-1">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-medium text-text">
                            {moment.type
                              .replace(/_/g, ' ')
                              .replace(/\b\w/g, (c) => c.toUpperCase())}
                          </span>
                          <span className="text-xs text-yellow-400">
                            {(moment.significance * 100).toFixed(0)}% significance
                          </span>
                        </div>
                        <p className="text-sm text-text-muted">{moment.description}</p>
                        {moment.context && (
                          <p className="text-xs text-text-muted/70 mt-1">{moment.context}</p>
                        )}
                        <p className="text-xs text-text-muted/50 mt-2">
                          {new Date(moment.timestamp).toLocaleString()}
                        </p>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* Network Tab */}
          {activeTab === 'network' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold text-text mb-4">Relationship Network</h3>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Rivals */}
                <div>
                  <h4 className="text-sm font-medium text-red-400 mb-3 flex items-center gap-2">
                    <span>⚔️</span> Rivals
                  </h4>
                  {network?.rivals?.length ? (
                    <div className="space-y-2">
                      {network.rivals.map((rival) => (
                        <Link
                          key={rival.agent}
                          href={`/agent/${encodeURIComponent(rival.agent)}/`}
                          className="flex items-center justify-between p-2 bg-red-900/20 border border-red-800/30 rounded hover:border-red-500/50 transition-colors"
                        >
                          <span className="text-red-400 font-medium">{rival.agent}</span>
                          <span className="text-xs text-red-400/70">
                            {(rival.score * 100).toFixed(0)}% rivalry
                          </span>
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <div className="text-text-muted text-sm">No rivals yet</div>
                  )}
                </div>

                {/* Allies */}
                <div>
                  <h4 className="text-sm font-medium text-green-400 mb-3 flex items-center gap-2">
                    <span>🤝</span> Allies
                  </h4>
                  {network?.allies?.length ? (
                    <div className="space-y-2">
                      {network.allies.map((ally) => (
                        <Link
                          key={ally.agent}
                          href={`/agent/${encodeURIComponent(ally.agent)}/`}
                          className="flex items-center justify-between p-2 bg-green-900/20 border border-green-800/30 rounded hover:border-green-500/50 transition-colors"
                        >
                          <span className="text-green-400 font-medium">{ally.agent}</span>
                          <span className="text-xs text-green-400/70">
                            {(ally.score * 100).toFixed(0)}% alliance
                          </span>
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <div className="text-text-muted text-sm">No allies yet</div>
                  )}
                </div>

                {/* Influences */}
                <div>
                  <h4 className="text-sm font-medium text-blue-400 mb-3 flex items-center gap-2">
                    <span>📤</span> Influences
                  </h4>
                  {network?.influences?.length ? (
                    <div className="space-y-2">
                      {network.influences.map((inf) => (
                        <Link
                          key={inf.agent}
                          href={`/agent/${encodeURIComponent(inf.agent)}/`}
                          className="flex items-center justify-between p-2 bg-blue-900/20 border border-blue-800/30 rounded hover:border-blue-500/50 transition-colors"
                        >
                          <span className="text-blue-400 font-medium">{inf.agent}</span>
                          <span className="text-xs text-blue-400/70">
                            {(inf.score * 100).toFixed(0)}%
                          </span>
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <div className="text-text-muted text-sm">No influence data</div>
                  )}
                </div>

                {/* Influenced By */}
                <div>
                  <h4 className="text-sm font-medium text-purple-400 mb-3 flex items-center gap-2">
                    <span>📥</span> Influenced By
                  </h4>
                  {network?.influenced_by?.length ? (
                    <div className="space-y-2">
                      {network.influenced_by.map((inf) => (
                        <Link
                          key={inf.agent}
                          href={`/agent/${encodeURIComponent(inf.agent)}/`}
                          className="flex items-center justify-between p-2 bg-purple-900/20 border border-purple-800/30 rounded hover:border-purple-500/50 transition-colors"
                        >
                          <span className="text-purple-400 font-medium">{inf.agent}</span>
                          <span className="text-xs text-purple-400/70">
                            {(inf.score * 100).toFixed(0)}%
                          </span>
                        </Link>
                      ))}
                    </div>
                  ) : (
                    <div className="text-text-muted text-sm">No influence data</div>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* Compare Tab */}
          {activeTab === 'compare' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold text-text mb-4">Head-to-Head Comparison</h3>

              {/* Opponent Selector */}
              <div className="flex items-center gap-4">
                <label className="text-sm text-text-muted">Compare with:</label>
                <select
                  value={selectedRival || ''}
                  onChange={(e) => setSelectedRival(e.target.value || null)}
                  className="flex-1 bg-bg border border-border rounded px-3 py-2 text-text"
                >
                  <option value="">Select an opponent...</option>
                  {network?.rivals?.map((rival) => (
                    <option key={rival.agent} value={rival.agent}>
                      {rival.agent} (Rival)
                    </option>
                  ))}
                  {network?.allies?.map((ally) => (
                    <option key={ally.agent} value={ally.agent}>
                      {ally.agent} (Ally)
                    </option>
                  ))}
                </select>
              </div>

              {/* Head-to-Head Stats */}
              {headToHead && headToHead.matches > 0 ? (
                <div className="bg-bg border border-border rounded-lg p-6">
                  <div className="flex items-center justify-center gap-8 mb-6">
                    <div className="text-center">
                      <div className="text-xl font-bold text-accent">{agentName}</div>
                    </div>
                    <div className="text-2xl text-text-muted">vs</div>
                    <div className="text-center">
                      <Link
                        href={`/agent/${encodeURIComponent(headToHead.opponent)}/`}
                        className="text-xl font-bold text-text hover:text-accent transition-colors"
                      >
                        {headToHead.opponent}
                      </Link>
                    </div>
                  </div>

                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 text-center">
                    <div className="bg-green-900/20 border border-green-800/30 rounded-lg p-4">
                      <div className="text-3xl font-bold text-green-400">
                        {headToHead.wins || 0}
                      </div>
                      <div className="text-xs text-green-400/70">Wins</div>
                    </div>
                    <div className="bg-surface border border-border rounded-lg p-4">
                      <div className="text-3xl font-bold text-text-muted">
                        {headToHead.draws || 0}
                      </div>
                      <div className="text-xs text-text-muted">Draws</div>
                    </div>
                    <div className="bg-red-900/20 border border-red-800/30 rounded-lg p-4">
                      <div className="text-3xl font-bold text-red-400">
                        {headToHead.losses || 0}
                      </div>
                      <div className="text-xs text-red-400/70">Losses</div>
                    </div>
                  </div>

                  <div className="mt-4 text-center text-text-muted">
                    {headToHead.matches} total matches
                    {headToHead.win_rate !== undefined && (
                      <span className="ml-2">
                        ({(headToHead.win_rate * 100).toFixed(0)}% win rate)
                      </span>
                    )}
                  </div>

                  {/* Domain Breakdown */}
                  {headToHead.by_domain && Object.keys(headToHead.by_domain).length > 0 && (
                    <div className="mt-6">
                      <h4 className="text-sm font-medium text-text-muted mb-3">By Domain</h4>
                      <div className="space-y-2">
                        {Object.entries(headToHead.by_domain).map(([domain, stats]) => (
                          <div
                            key={domain}
                            className="flex items-center justify-between p-2 bg-surface border border-border rounded"
                          >
                            <span className="text-sm text-text">{domain}</span>
                            <span className="text-xs text-text-muted">
                              {stats.wins}W-{stats.losses}L-{stats.draws}D
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              ) : selectedRival ? (
                <div className="text-center text-text-muted py-8">
                  No head-to-head data available with {selectedRival}
                </div>
              ) : (
                <div className="text-center text-text-muted py-8">
                  Select an opponent to see head-to-head statistics
                </div>
              )}
            </div>
          )}

          {/* Performance Tab */}
          {activeTab === 'performance' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold text-text mb-4">Performance Statistics</h3>

              {performance ? (
                <>
                  {/* Key Metrics */}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="bg-bg border border-border rounded-lg p-4 text-center">
                      <div className="text-2xl font-bold text-text font-theme-data">
                        {(performance.win_rate * 100).toFixed(1)}%
                      </div>
                      <div className="text-xs text-text-muted">Win Rate</div>
                    </div>
                    <div className="bg-bg border border-border rounded-lg p-4 text-center">
                      <div className="text-2xl font-bold text-accent font-theme-data">
                        {(performance.recent_win_rate * 100).toFixed(1)}%
                      </div>
                      <div className="text-xs text-text-muted">Recent (Last 10)</div>
                    </div>
                    <div className="bg-bg border border-border rounded-lg p-4 text-center">
                      <div
                        className={`text-2xl font-bold font-theme-data ${
                          performance.elo_trend > 0
                            ? 'text-green-400'
                            : performance.elo_trend < 0
                              ? 'text-red-400'
                              : 'text-text-muted'
                        }`}
                      >
                        {performance.elo_trend > 0 ? '+' : ''}
                        {performance.elo_trend}
                      </div>
                      <div className="text-xs text-text-muted">ELO Trend</div>
                    </div>
                    <div className="bg-bg border border-border rounded-lg p-4 text-center">
                      <div className="text-2xl font-bold text-text font-theme-data">
                        {performance.total_games}
                      </div>
                      <div className="text-xs text-text-muted">Total Games</div>
                    </div>
                  </div>

                  {/* Win/Loss Breakdown */}
                  <div className="bg-bg border border-border rounded-lg p-4">
                    <h4 className="text-sm font-medium text-text mb-3">Match Breakdown</h4>
                    <div className="flex items-center gap-4">
                      <div className="flex-1">
                        <div className="flex h-4 rounded overflow-hidden bg-surface">
                          {performance.total_games > 0 && (
                            <>
                              <div
                                className="bg-green-500"
                                style={{
                                  width: `${(performance.wins / performance.total_games) * 100}%`,
                                }}
                                title={`${performance.wins} wins`}
                              />
                              <div
                                className="bg-gray-500"
                                style={{
                                  width: `${(performance.draws / performance.total_games) * 100}%`,
                                }}
                                title={`${performance.draws} draws`}
                              />
                              <div
                                className="bg-red-500"
                                style={{
                                  width: `${(performance.losses / performance.total_games) * 100}%`,
                                }}
                                title={`${performance.losses} losses`}
                              />
                            </>
                          )}
                        </div>
                      </div>
                      <div className="text-xs text-text-muted whitespace-nowrap">
                        {performance.wins}W / {performance.draws}D / {performance.losses}L
                      </div>
                    </div>
                  </div>

                  {/* Critique Stats */}
                  <div className="bg-bg border border-border rounded-lg p-4">
                    <h4 className="text-sm font-medium text-text mb-3">Critique Performance</h4>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <div className="text-xs text-text-muted mb-1">Acceptance Rate</div>
                        <div className="text-lg font-theme-data text-text">
                          {(performance.critique_acceptance_rate * 100).toFixed(1)}%
                        </div>
                        <div className="text-xs text-text-muted">
                          {performance.critiques_accepted}/{performance.critiques_total} accepted
                        </div>
                      </div>
                      <div>
                        <div className="text-xs text-text-muted mb-1">Calibration Accuracy</div>
                        <div className="text-lg font-theme-data text-text">
                          {(performance.calibration.accuracy * 100).toFixed(1)}%
                        </div>
                        <div className="text-xs text-text-muted">
                          Brier: {performance.calibration.brier_score.toFixed(3)} (
                          {performance.calibration.prediction_count} predictions)
                        </div>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="text-center text-text-muted py-8">
                  No performance data available.
                </div>
              )}
            </div>
          )}

          {/* Domains Tab */}
          {activeTab === 'domains' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold text-text mb-4">Domain Expertise</h3>

              {domains && domains.domains.length > 0 ? (
                <>
                  <div className="text-sm text-text-muted mb-4">
                    Overall ELO:{' '}
                    <span className="font-theme-data text-text">{domains.overall_elo}</span>{' '}
                    &middot; {domains.domain_count} domain{domains.domain_count !== 1 ? 's' : ''}
                  </div>

                  <div className="space-y-3">
                    {domains.domains.map((domain) => (
                      <div
                        key={domain.domain}
                        className="bg-bg border border-border rounded-lg p-4"
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-medium text-text capitalize">
                            {domain.domain.replace(/_/g, ' ')}
                          </span>
                          <div className="flex items-center gap-2">
                            <span className="font-theme-data text-text">
                              {Math.round(domain.elo)}
                            </span>
                            <span
                              className={`text-xs font-theme-data ${
                                domain.relative > 0
                                  ? 'text-green-400'
                                  : domain.relative < 0
                                    ? 'text-red-400'
                                    : 'text-text-muted'
                              }`}
                            >
                              {domain.relative > 0 ? '+' : ''}
                              {domain.relative}
                            </span>
                          </div>
                        </div>
                        {/* Progress bar showing ELO relative to range */}
                        <div className="h-2 rounded overflow-hidden bg-surface">
                          <div
                            className={`h-full ${
                              domain.elo >= 1600
                                ? 'bg-green-500'
                                : domain.elo >= 1500
                                  ? 'bg-yellow-500'
                                  : domain.elo >= 1400
                                    ? 'bg-orange-500'
                                    : 'bg-red-500'
                            }`}
                            style={{
                              width: `${Math.min(100, Math.max(0, (domain.elo - 1000) / 10))}%`,
                            }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : (
                <div className="text-center text-text-muted py-8">
                  No domain expertise data available. This agent needs more debates in specific
                  topic areas.
                </div>
              )}
            </div>
          )}

          {/* History Tab */}
          {activeTab === 'history' && (
            <div className="space-y-6">
              <h3 className="text-lg font-semibold text-text mb-4">Debate History</h3>

              {history.length > 0 ? (
                <div className="space-y-3">
                  {history.map((entry) => (
                    <div
                      key={entry.debate_id}
                      className="bg-bg border border-border rounded-lg p-4"
                    >
                      <div className="flex items-center justify-between mb-2">
                        <div className="flex items-center gap-3">
                          <span
                            className={`text-xl ${
                              entry.result === 'win'
                                ? 'text-green-400'
                                : entry.result === 'loss'
                                  ? 'text-red-400'
                                  : 'text-yellow-400'
                            }`}
                          >
                            {entry.result === 'win' ? '🏆' : entry.result === 'loss' ? '💔' : '🤝'}
                          </span>
                          <div>
                            <div className="text-sm font-medium text-text">
                              {entry.result === 'win'
                                ? 'Won'
                                : entry.result === 'loss'
                                  ? 'Lost'
                                  : 'Draw'}
                              {entry.opponent && (
                                <span className="text-text-muted">
                                  {' '}
                                  vs{' '}
                                  <Link
                                    href={`/agent/${encodeURIComponent(entry.opponent)}/`}
                                    className="text-accent hover:underline"
                                  >
                                    {entry.opponent}
                                  </Link>
                                </span>
                              )}
                            </div>
                            {entry.topic && (
                              <div className="text-xs text-text-muted truncate max-w-md">
                                {entry.topic}
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="text-right">
                          <div
                            className={`text-sm font-theme-data ${
                              entry.elo_change > 0
                                ? 'text-green-400'
                                : entry.elo_change < 0
                                  ? 'text-red-400'
                                  : 'text-text-muted'
                            }`}
                          >
                            {entry.elo_change > 0 ? '+' : ''}
                            {entry.elo_change}
                          </div>
                          <div className="text-xs text-text-muted">→ {entry.elo_after}</div>
                        </div>
                      </div>
                      <div className="text-xs text-text-muted/50">
                        {new Date(entry.created_at).toLocaleString()}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-center text-text-muted py-8">
                  No debate history available yet.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
