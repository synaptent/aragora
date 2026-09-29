'use client';

import { useState, useEffect, useCallback, useMemo, memo, useRef } from 'react';
import { AgentMomentsModal } from './AgentMomentsModal';
import { withErrorBoundary } from './PanelErrorBoundary';
import type { StreamEvent } from '@/types/events';
import { API_BASE_URL } from '@/config';
import { useAuth } from '@/context/AuthContext';
import { logger } from '@/utils/logger';
import {
  RankingsTabPanel,
  MatchesTabPanel,
  StatsTabPanel,
  MindsTabPanel,
  ReputationTabPanel,
  TeamsTabPanel,
  type AgentRanking,
  type Match,
  type AgentReputation,
  type TeamCombination,
  type RankingStats,
  type AgentIntrospection,
} from './leaderboard';

interface LeaderboardPanelProps {
  wsMessages?: StreamEvent[];
  loopId?: string | null;
  apiBase?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

function LeaderboardPanelComponent({
  wsMessages = [],
  loopId,
  apiBase = DEFAULT_API_BASE,
}: LeaderboardPanelProps) {
  const { tokens } = useAuth();
  const [agents, setAgents] = useState<AgentRanking[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [reputations, setReputations] = useState<AgentReputation[]>([]);
  const [teams, setTeams] = useState<TeamCombination[]>([]);
  const [stats, setStats] = useState<RankingStats | null>(null);
  const [introspections, setIntrospections] = useState<AgentIntrospection[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [endpointErrors, setEndpointErrors] = useState<Record<string, string>>({});
  const [activeTab, setActiveTab] = useState<
    'rankings' | 'matches' | 'reputation' | 'teams' | 'stats' | 'minds'
  >('rankings');
  const [lastEventId, setLastEventId] = useState<string | null>(null);
  const [selectedDomain, setSelectedDomain] = useState<string | null>(null);
  const [availableDomains, setAvailableDomains] = useState<string[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    setLoading(true);

    // Build query params for consolidated endpoint
    const params = new URLSearchParams({ limit: '10' });
    if (loopId) params.set('loop_id', loopId);
    if (selectedDomain) params.set('domain', selectedDomain);

    // Build headers with auth token (outside try so it's accessible in catch)
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (tokens?.access_token) {
      headers['Authorization'] = `Bearer ${tokens.access_token}`;
    }

    try {
      // Single consolidated request instead of 6 separate calls
      const res = await fetch(`${apiBase}/api/leaderboard-view?${params}`, { headers });

      if (!res.ok) {
        const errorText = await res.text().catch(() => 'Unknown error');
        if (res.status === 401 || res.status === 403) {
          setError('Authentication required');
          setLoading(false);
          return;
        }
        if (res.status === 404) {
          setError('Leaderboard endpoint unavailable');
          setLoading(false);
          return;
        }
        throw new Error(`${res.status}: ${errorText.slice(0, 100)}`);
      }

      const response = await res.json();
      const { data, errors: apiErrors } = response;

      // Update state from consolidated response
      if (data.rankings) {
        const agentsList: AgentRanking[] = data.rankings.agents || [];
        setAgents(agentsList);
      }

      if (data.matches) {
        setMatches(data.matches.matches || []);
        const domainSet = new Set<string>(
          (data.matches.matches || []).map((m: Match) => m.domain).filter(Boolean),
        );
        const matchDomains = Array.from(domainSet);
        if (matchDomains.length > 0) {
          setAvailableDomains((prev) => Array.from(new Set([...prev, ...matchDomains])));
        }
      }

      if (data.reputation) {
        setReputations(data.reputation.reputations || []);
      }

      if (data.teams) {
        setTeams(data.teams.combinations || []);
      }

      if (data.stats) {
        setStats(data.stats);
      }

      if (data.introspection) {
        // Convert object to array for compatibility
        const introArray = Object.values(data.introspection.agents || {}) as AgentIntrospection[];
        setIntrospections(introArray);
      }

      // Handle partial failures from consolidated endpoint
      if (apiErrors?.partial_failure) {
        setEndpointErrors(apiErrors.messages || {});
        setError(`${apiErrors.failed_sections?.length || 0} section(s) unavailable`);
      } else {
        setEndpointErrors({});
        setError(null);
      }
    } catch (err) {
      // Check if this was a rate limit error - don't fallback to 6 endpoints if rate limited
      const errMessage = err instanceof Error ? err.message : String(err);
      if (errMessage.includes('429') || errMessage.toLowerCase().includes('rate limit')) {
        logger.warn('Rate limited on consolidated endpoint, not falling back to legacy endpoints');
        setError('Too many requests. Please wait a moment.');
        setLoading(false);
        return;
      }

      // Fallback: consolidated endpoint failed, try legacy endpoints
      logger.warn('Consolidated endpoint failed:', err);
      logger.warn('Attempting legacy endpoints fallback');
      const errors: Record<string, string> = {};
      const endpoints = [
        {
          key: 'rankings',
          url: `${apiBase}/api/leaderboard?limit=10${loopId ? `&loop_id=${loopId}` : ''}${selectedDomain ? `&domain=${selectedDomain}` : ''}`,
        },
        {
          key: 'matches',
          url: `${apiBase}/api/matches/recent?limit=5${loopId ? `&loop_id=${loopId}` : ''}`,
        },
        { key: 'reputation', url: `${apiBase}/api/reputation/all` },
        { key: 'teams', url: `${apiBase}/api/routing/best-teams?min_debates=3&limit=10` },
        { key: 'stats', url: `${apiBase}/api/ranking/stats` },
        { key: 'minds', url: `${apiBase}/api/introspection/all` },
      ];
      const results = await Promise.allSettled(
        endpoints.map(async ({ key, url }) => {
          const r = await fetch(url, { headers });
          if (!r.ok) throw new Error(`${r.status}`);
          return { key, data: await r.json() };
        }),
      );
      results.forEach((result, idx) => {
        const { key } = endpoints[idx];
        if (result.status === 'rejected') {
          errors[key] = result.reason?.message || 'Failed';
          return;
        }
        const { data } = result.value;
        switch (key) {
          case 'rankings':
            setAgents(data.agents || data.rankings || []);
            break;
          case 'matches':
            setMatches(data.matches || []);
            break;
          case 'reputation':
            setReputations(data.reputations || []);
            break;
          case 'teams':
            setTeams(data.combinations || []);
            break;
          case 'stats':
            setStats(data);
            break;
          case 'minds':
            setIntrospections(Object.values(data.agents || {}) as AgentIntrospection[]);
            break;
        }
      });
      setEndpointErrors(errors);
      if (Object.keys(errors).length === endpoints.length) {
        setError('All endpoints failed.');
      } else if (Object.keys(errors).length > 0) {
        setError(`${Object.keys(errors).length} endpoint(s) unavailable`);
      }
    }

    setLoading(false);
  }, [apiBase, loopId, selectedDomain, tokens?.access_token]);

  // Legacy fallback kept as separate function for testing
  const _fetchDataLegacy = useCallback(async () => {
    const headers: HeadersInit = { 'Content-Type': 'application/json' };
    if (tokens?.access_token) {
      headers['Authorization'] = `Bearer ${tokens.access_token}`;
    }
    const errors: Record<string, string> = {};
    const endpoints = [
      {
        key: 'rankings',
        url: `${apiBase}/api/leaderboard?limit=10${loopId ? `&loop_id=${loopId}` : ''}${selectedDomain ? `&domain=${selectedDomain}` : ''}`,
      },
      {
        key: 'matches',
        url: `${apiBase}/api/matches/recent?limit=5${loopId ? `&loop_id=${loopId}` : ''}`,
      },
      { key: 'reputation', url: `${apiBase}/api/reputation/all` },
      { key: 'teams', url: `${apiBase}/api/routing/best-teams?min_debates=3&limit=10` },
      { key: 'stats', url: `${apiBase}/api/ranking/stats` },
      { key: 'minds', url: `${apiBase}/api/introspection/all` },
    ];

    const results = await Promise.allSettled(
      endpoints.map(async ({ key, url }) => {
        const res = await fetch(url, { headers });
        if (!res.ok) throw new Error(`${res.status}`);
        return { key, data: await res.json() };
      }),
    );

    results.forEach((result, idx) => {
      const { key } = endpoints[idx];
      if (result.status === 'rejected') {
        errors[key] = result.reason?.message || 'Failed';
        return;
      }
      const { data } = result.value;
      switch (key) {
        case 'rankings':
          setAgents(data.agents || data.rankings || []);
          break;
        case 'matches':
          setMatches(data.matches || []);
          break;
        case 'reputation':
          setReputations(data.reputations || []);
          break;
        case 'teams':
          setTeams(data.combinations || []);
          break;
        case 'stats':
          setStats(data);
          break;
        case 'minds':
          setIntrospections(Object.values(data.agents || {}) as AgentIntrospection[]);
          break;
      }
    });

    setEndpointErrors(errors);
    const errorCount = Object.keys(errors).length;
    if (errorCount === endpoints.length) {
      setError('All endpoints failed.');
    } else if (errorCount > 0) {
      setError(`${errorCount} endpoint(s) unavailable`);
    } else {
      setError(null);
    }
  }, [apiBase, loopId, selectedDomain, tokens?.access_token]);

  // Use ref to store latest fetchData to avoid interval recreation on dependency changes
  const fetchDataRef = useRef(fetchData);
  fetchDataRef.current = fetchData;

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Separate effect for interval - runs once, uses ref to call latest fetchData
  useEffect(() => {
    const interval = setInterval(() => {
      fetchDataRef.current();
    }, 30000);
    return () => clearInterval(interval);
  }, []); // Empty deps - interval created once

  // Memoize filtered match events to avoid recalculating on every render
  const matchEvents = useMemo(() => {
    return wsMessages.filter((msg) => {
      if (msg.type !== 'match_recorded') return false;
      const msgData = msg.data as Record<string, unknown>;
      const msgLoopId = msgData?.loop_id as string | undefined;
      if (loopId && msgLoopId && msgLoopId !== loopId) return false;
      return true;
    });
  }, [wsMessages, loopId]);

  // Listen for match_recorded WebSocket events for real-time updates (debate consensus feature)
  useEffect(() => {
    if (matchEvents.length > 0) {
      const latestEvent = matchEvents[matchEvents.length - 1];
      const eventData = latestEvent.data as Record<string, unknown>;
      const eventId = eventData?.debate_id as string | undefined;

      // Only refresh if this is a new match event
      if (eventId && eventId !== lastEventId) {
        setLastEventId(eventId);
        fetchData(); // Refresh leaderboard when a match is recorded

        // Track new domains from match events
        const eventDomain = eventData?.domain as string | undefined;
        if (eventDomain && !availableDomains.includes(eventDomain)) {
          setAvailableDomains((prev) => [...prev, eventDomain]);
        }
      }
    }
  }, [matchEvents, lastEventId, fetchData, availableDomains]);

  return (
    <div className="panel">
      <div className="panel-header mb-4">
        <h3 className="panel-title">Agent Leaderboard</h3>
        <button
          onClick={fetchData}
          className="px-2 py-1 bg-surface border border-border rounded text-sm text-text hover:bg-surface-hover"
        >
          Refresh
        </button>
      </div>

      {/* Domain Filter */}
      {availableDomains.length > 0 && (
        <div className="flex items-center gap-2 mb-3">
          <span className="text-xs text-text-muted">Domain:</span>
          <select
            value={selectedDomain || ''}
            onChange={(e) => setSelectedDomain(e.target.value || null)}
            className="flex-1 bg-bg border border-border rounded px-2 py-1 text-sm text-text"
          >
            <option value="">All Domains</option>
            {availableDomains.map((domain) => (
              <option key={domain} value={domain}>
                {domain}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="panel-tabs mb-4" role="tablist" aria-label="Leaderboard views">
        <button
          id="rankings-tab"
          onClick={() => setActiveTab('rankings')}
          role="tab"
          aria-selected={activeTab === 'rankings'}
          aria-controls="rankings-panel"
          tabIndex={activeTab === 'rankings' ? 0 : -1}
          className={`px-3 py-1 rounded text-sm transition-colors whitespace-nowrap ${
            activeTab === 'rankings'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Rankings
        </button>
        <button
          id="matches-tab"
          onClick={() => setActiveTab('matches')}
          role="tab"
          aria-selected={activeTab === 'matches'}
          aria-controls="matches-panel"
          tabIndex={activeTab === 'matches' ? 0 : -1}
          className={`px-3 py-1 rounded text-sm transition-colors whitespace-nowrap ${
            activeTab === 'matches'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Matches
        </button>
        <button
          id="reputation-tab"
          onClick={() => setActiveTab('reputation')}
          role="tab"
          aria-selected={activeTab === 'reputation'}
          aria-controls="reputation-panel"
          tabIndex={activeTab === 'reputation' ? 0 : -1}
          className={`px-3 py-1 rounded text-sm transition-colors whitespace-nowrap ${
            activeTab === 'reputation'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Reputation
        </button>
        <button
          id="teams-tab"
          onClick={() => setActiveTab('teams')}
          role="tab"
          aria-selected={activeTab === 'teams'}
          aria-controls="teams-panel"
          tabIndex={activeTab === 'teams' ? 0 : -1}
          className={`px-3 py-1 rounded text-sm transition-colors whitespace-nowrap ${
            activeTab === 'teams'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Teams
        </button>
        <button
          id="stats-tab"
          onClick={() => setActiveTab('stats')}
          role="tab"
          aria-selected={activeTab === 'stats'}
          aria-controls="stats-panel"
          tabIndex={activeTab === 'stats' ? 0 : -1}
          className={`px-3 py-1 rounded text-sm transition-colors whitespace-nowrap ${
            activeTab === 'stats'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Stats
        </button>
        <button
          id="minds-tab"
          onClick={() => setActiveTab('minds')}
          role="tab"
          aria-selected={activeTab === 'minds'}
          aria-controls="minds-panel"
          tabIndex={activeTab === 'minds' ? 0 : -1}
          className={`px-3 py-1 rounded text-sm transition-colors whitespace-nowrap ${
            activeTab === 'minds'
              ? 'bg-accent text-bg font-medium'
              : 'text-text-muted hover:text-text'
          }`}
        >
          Minds
        </button>
      </div>

      {/* Rankings Tab */}
      {activeTab === 'rankings' && (
        <RankingsTabPanel
          agents={agents}
          loading={loading}
          error={error}
          endpointErrors={endpointErrors}
        />
      )}

      {/* Recent Matches Tab */}
      {activeTab === 'matches' && <MatchesTabPanel matches={matches} loading={loading} />}

      {/* Reputation Tab */}
      {activeTab === 'reputation' && (
        <ReputationTabPanel reputations={reputations} loading={loading} />
      )}

      {/* Teams Tab */}
      {activeTab === 'teams' && <TeamsTabPanel teams={teams} loading={loading} />}

      {/* Stats Tab */}
      {activeTab === 'stats' && <StatsTabPanel stats={stats} loading={loading} />}

      {/* Minds (Introspection) Tab */}
      {activeTab === 'minds' && <MindsTabPanel introspections={introspections} loading={loading} />}

      {/* Agent Moments Modal */}
      {selectedAgent && (
        <AgentMomentsModal
          agentName={selectedAgent}
          onClose={() => setSelectedAgent(null)}
          apiBase={apiBase}
        />
      )}
    </div>
  );
}

// Memoize the component and wrap with error boundary
const MemoizedLeaderboardPanel = memo(LeaderboardPanelComponent);
export const LeaderboardPanel = withErrorBoundary(MemoizedLeaderboardPanel, 'Leaderboard');
