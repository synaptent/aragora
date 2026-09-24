'use client';

import { useState, useCallback, useEffect, useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { PanelTemplate } from '@/components/shared/PanelTemplate';
import { useApi } from '@/hooks/useApi';
import { useBackend } from '@/components/BackendSelector';
import { useControlPlaneWebSocket } from '@/hooks/useControlPlaneWebSocket';
import { AgentCard, type AgentInfo, type AgentStatus } from './AgentCard';

export type AgentFilter = 'all' | 'available' | 'working' | 'error';
export type AgentSort = 'name' | 'elo' | 'status' | 'activity';

export interface AgentCatalogProps {
  /** Callback when an agent is selected */
  onSelectAgent?: (agent: AgentInfo) => void;
  /** Callback when configure is clicked */
  onConfigureAgent?: (agent: AgentInfo) => void;
  /** Show compact card view */
  compact?: boolean;
  /** Maximum agents to display (0 = unlimited) */
  maxAgents?: number;
  /** Enable real-time updates */
  enableRealtime?: boolean;
  /** Custom CSS classes */
  className?: string;
}

/**
 * Agent Catalog component for browsing and selecting agents.
 * Displays agents with filtering, sorting, and real-time status updates.
 */
export function AgentCatalog({
  onSelectAgent,
  onConfigureAgent,
  compact = false,
  maxAgents = 0,
  enableRealtime = true,
  className = '',
}: AgentCatalogProps) {
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const api = useApi(backendConfig?.api);

  // State
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null);
  const [filter, setFilter] = useState<AgentFilter>('all');
  const [sort, setSort] = useState<AgentSort>('elo');
  const [searchQuery, setSearchQuery] = useState('');

  // Real-time updates via WebSocket
  const { agents: liveAgentsMap, isConnected } = useControlPlaneWebSocket({
    enabled: enableRealtime,
  });

  // Convert Map to Array for compatibility
  const liveAgents = useMemo(() => Array.from(liveAgentsMap.values()), [liveAgentsMap]);

  // Merge live agent data with static data
  const mergedAgents = useMemo(() => {
    if (!liveAgents || liveAgents.length === 0) return agents;

    return agents.map((agent) => {
      const live = liveAgents.find((a) => a.id === agent.id || a.name === agent.name);
      if (live) {
        return {
          ...agent,
          status: live.status as AgentStatus,
          current_task: live.current_task,
          tokens_used_today: live.tokens_used,
          requests_today: live.requests_today,
          last_active: live.last_active,
          error_message: live.error_message,
        };
      }
      return agent;
    });
  }, [agents, liveAgents]);

  // Filter agents
  const filteredAgents = useMemo(() => {
    let result = mergedAgents;

    // Apply search filter
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      result = result.filter(
        (a) =>
          a.name.toLowerCase().includes(query) ||
          a.model.toLowerCase().includes(query) ||
          a.description?.toLowerCase().includes(query) ||
          a.expertise?.some((e) => e.toLowerCase().includes(query)),
      );
    }

    // Apply status filter
    switch (filter) {
      case 'available':
        result = result.filter((a) => a.status === 'idle');
        break;
      case 'working':
        result = result.filter((a) => a.status === 'working');
        break;
      case 'error':
        result = result.filter((a) => a.status === 'error' || a.status === 'rate_limited');
        break;
    }

    // Apply sort
    result = [...result].sort((a, b) => {
      switch (sort) {
        case 'name':
          return a.name.localeCompare(b.name);
        case 'elo':
          return (b.elo ?? 0) - (a.elo ?? 0);
        case 'status': {
          const statusOrder: Record<AgentStatus, number> = {
            working: 0,
            idle: 1,
            rate_limited: 2,
            error: 3,
            offline: 4,
          };
          return statusOrder[a.status] - statusOrder[b.status];
        }
        case 'activity':
          return (b.requests_today ?? 0) - (a.requests_today ?? 0);
        default:
          return 0;
      }
    });

    // Apply limit
    if (maxAgents > 0) {
      result = result.slice(0, maxAgents);
    }

    return result;
  }, [mergedAgents, filter, sort, searchQuery, maxAgents]);

  // Load agents
  const loadAgents = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Load from multiple endpoints and merge
      const [agentsResponse, leaderboardResponse, calibrationResponse] = await Promise.all([
        api.get('/api/control-plane/agents').catch(() => ({ agents: [] })) as Promise<{
          agents: AgentInfo[];
        }>,
        api.get('/api/leaderboard').catch(() => ({ leaderboard: [] })) as Promise<{
          leaderboard: Array<{ name: string; elo: number; win_rate: number }>;
        }>,
        api.get('/api/calibration/leaderboard?limit=50').catch(() => ({ agents: [] })) as Promise<{
          agents: Array<{ name: string; calibration_score: number; brier_score: number }>;
        }>,
      ]);

      // Merge leaderboard and calibration data
      const agentList = agentsResponse.agents || [];
      const leaderboard = leaderboardResponse.leaderboard || [];
      const calibration = calibrationResponse.agents || [];

      const enrichedAgents = agentList.map((agent) => {
        const stats = leaderboard.find((l) => l.name.toLowerCase() === agent.name.toLowerCase());
        const calStats = calibration.find((c) => c.name.toLowerCase() === agent.name.toLowerCase());
        return {
          ...agent,
          elo: stats?.elo ?? agent.elo,
          win_rate: stats?.win_rate ?? agent.win_rate,
          calibration_score: calStats?.calibration_score ?? agent.calibration_score,
          brier_score: calStats?.brier_score ?? agent.brier_score,
        };
      });

      // If no agents from control plane, try personas
      if (enrichedAgents.length === 0) {
        const personasResponse = (await api
          .get('/api/personas')
          .catch(() => ({ personas: [] }))) as {
          personas: Array<{ name: string; description: string; model?: string }>;
        };

        const personas = personasResponse.personas || [];
        const personaAgents: AgentInfo[] = personas.map((p) => ({
          id: p.name,
          name: p.name,
          model: p.model || 'unknown',
          description: p.description,
          status: 'offline' as AgentStatus,
        }));

        setAgents(personaAgents);
      } else {
        setAgents(enrichedAgents);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load agents');
    } finally {
      setLoading(false);
    }
  }, [api]);

  // Load on mount
  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  // Handle agent selection
  const handleSelectAgent = useCallback(
    (agent: AgentInfo) => {
      setSelectedAgentId(agent.id);
      onSelectAgent?.(agent);
    },
    [onSelectAgent],
  );

  // Handle view calibration
  const handleViewCalibration = useCallback(
    (agent: AgentInfo) => {
      // Navigate to calibration page with agent pre-selected
      router.push(`/calibration?agent=${encodeURIComponent(agent.name)}`);
    },
    [router],
  );

  // Count by status
  const statusCounts = useMemo(() => {
    const counts = { all: mergedAgents.length, available: 0, working: 0, error: 0 };

    mergedAgents.forEach((agent) => {
      if (agent.status === 'idle') counts.available++;
      if (agent.status === 'working') counts.working++;
      if (agent.status === 'error' || agent.status === 'rate_limited') counts.error++;
    });

    return counts;
  }, [mergedAgents]);

  // Filter tabs
  const filterTabs = [
    { id: 'all', label: `All (${statusCounts.all})` },
    { id: 'available', label: `Available (${statusCounts.available})` },
    { id: 'working', label: `Working (${statusCounts.working})` },
    { id: 'error', label: `Issues (${statusCounts.error})` },
  ];

  return (
    <PanelTemplate
      title="Agent Catalog"
      icon="🤖"
      loading={loading}
      error={error}
      onRefresh={loadAgents}
      badge={enableRealtime && isConnected ? '●' : undefined}
      className={className}
      isEmpty={filteredAgents.length === 0 && !loading && !error}
      emptyState={
        <div className="text-center py-8">
          <div className="text-4xl mb-2">🔍</div>
          <p className="text-text-muted">No agents found</p>
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="mt-2 text-xs text-[var(--accent)] hover:underline"
            >
              Clear search
            </button>
          )}
        </div>
      }
      headerActions={
        <div className="flex items-center gap-2">
          {/* Sort dropdown */}
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as AgentSort)}
            className="text-xs bg-surface border border-border rounded px-2 py-1 text-text"
          >
            <option value="elo">By ELO</option>
            <option value="name">By Name</option>
            <option value="status">By Status</option>
            <option value="activity">By Activity</option>
          </select>
        </div>
      }
    >
      {/* Search and filters */}
      <div className="mb-4 space-y-3">
        {/* Search input */}
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search agents..."
          className="w-full px-3 py-2 text-sm bg-surface border border-border rounded focus:border-[var(--accent)] focus:outline-none"
        />

        {/* Filter tabs */}
        <div className="flex flex-wrap gap-1">
          {filterTabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setFilter(tab.id as AgentFilter)}
              className={`px-3 py-1 text-xs font-theme-data rounded transition-colors ${
                filter === tab.id
                  ? 'bg-[var(--accent)] text-bg'
                  : 'bg-surface text-text-muted hover:text-text'
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {/* Agent grid */}
      <div
        className={`grid gap-3 ${
          compact ? 'grid-cols-1' : 'grid-cols-1 md:grid-cols-2 lg:grid-cols-3'
        }`}
      >
        {filteredAgents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            selected={selectedAgentId === agent.id}
            onSelect={handleSelectAgent}
            onConfigure={onConfigureAgent}
            onViewCalibration={handleViewCalibration}
            compact={compact}
          />
        ))}
      </div>

      {/* Results count */}
      <div className="mt-4 text-xs text-text-muted text-center">
        Showing {filteredAgents.length} of {mergedAgents.length} agents
        {enableRealtime && (
          <span className={`ml-2 ${isConnected ? 'text-green-400' : 'text-yellow-400'}`}>
            {isConnected ? '● Live' : '○ Offline'}
          </span>
        )}
      </div>
    </PanelTemplate>
  );
}

export default AgentCatalog;
