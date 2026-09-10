'use client';

import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { useBackend } from '@/components/BackendSelector';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import {
  DeliberationGrid,
  ConsensusFormationChart,
  AgentInfluenceNetwork,
  DeliberationStats,
  type Deliberation,
  type DeliberationEvent,
  type AgentInfluence,
  type DeliberationStatsType,
} from '@/components/deliberation-dashboard';

export default function DeliberationsPage() {
  const { config: backendConfig } = useBackend();
  const [deliberations, setDeliberations] = useState<Deliberation[]>([]);
  const [stats, setStats] = useState<DeliberationStatsType | null>(null);
  const [events, setEvents] = useState<DeliberationEvent[]>([]);
  const [agentInfluence, setAgentInfluence] = useState<AgentInfluence[]>([]);
  const [loading, setLoading] = useState(true);
  const [wsConnected, setWsConnected] = useState(false);
  const [filter, setFilter] = useState<'all' | 'active' | 'complete'>('all');

  // Fetch active debate sessions
  const fetchDeliberations = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/v1/deliberations/active`);
      if (!response.ok) {
        // API error - show empty state (component handles gracefully)
        console.error('Failed to fetch deliberations:', response.status);
        setDeliberations([]);
        setAgentInfluence([]);
        return;
      }
      const data = await response.json();
      setDeliberations(data.deliberations || []);

      // Extract agent influence from decisionmaking sessions
      const agentMap = new Map<string, AgentInfluence>();
      (data.deliberations || []).forEach((d: Deliberation) => {
        d.agents.forEach((agent) => {
          if (!agentMap.has(agent)) {
            agentMap.set(agent, {
              agent_id: agent,
              influence_score: Math.random() * 0.5 + 0.5, // Placeholder until real data
              message_count: 0,
              consensus_contributions: Math.random() * 0.3 + 0.7,
              average_confidence: Math.random() * 0.2 + 0.8,
            });
          }
        });
      });
      setAgentInfluence(Array.from(agentMap.values()));
    } catch (error) {
      // Network error - show empty state
      console.error('Error fetching deliberations:', error);
      setDeliberations([]);
      setAgentInfluence([]);
    }
  }, [backendConfig.api]);

  // Fetch stats
  const fetchStats = useCallback(async () => {
    try {
      const response = await fetch(`${backendConfig.api}/api/v1/deliberations/stats`);
      if (!response.ok) {
        // API error - show null stats (component handles gracefully)
        console.error('Failed to fetch deliberation stats:', response.status);
        setStats(null);
        return;
      }
      const data = await response.json();
      setStats(data);
    } catch (error) {
      // Network error - show null stats
      console.error('Error fetching deliberation stats:', error);
      setStats(null);
    } finally {
      setLoading(false);
    }
  }, [backendConfig.api]);

  // WebSocket for real-time updates
  useEffect(() => {
    const wsUrl = backendConfig.api.replace('http', 'ws');
    let ws: WebSocket | null = null;

    const connect = () => {
      try {
        ws = new WebSocket(`${wsUrl}/api/v1/deliberations/stream`);

        ws.onopen = () => setWsConnected(true);
        ws.onclose = () => {
          setWsConnected(false);
          // Reconnect after 5 seconds
          setTimeout(connect, 5000);
        };
        ws.onerror = () => setWsConnected(false);

        ws.onmessage = (event) => {
          try {
            const data = JSON.parse(event.data) as DeliberationEvent;
            setEvents((prev) => [...prev.slice(-99), data]);

            // Update decisionmaking sessions based on events
            if (data.type === 'consensus_progress' || data.type === 'round_complete') {
              fetchDeliberations();
            }
          } catch {
            // Ignore parse errors
          }
        };
      } catch {
        // WebSocket not available, use polling
        setWsConnected(false);
      }
    };

    connect();

    return () => {
      if (ws) {
        ws.close();
      }
    };
  }, [backendConfig.api, fetchDeliberations]);

  // Initial fetch and polling fallback
  useEffect(() => {
    fetchDeliberations();
    fetchStats();

    // Poll every 10 seconds if WebSocket not connected
    const interval = setInterval(() => {
      if (!wsConnected) {
        fetchDeliberations();
        fetchStats();
      }
    }, 10000);

    return () => clearInterval(interval);
  }, [fetchDeliberations, fetchStats, wsConnected]);

  // Filter decisionmaking sessions
  const filteredDeliberations = deliberations.filter((d) => {
    if (filter === 'active')
      return (
        d.status === 'active' || d.status === 'consensus_forming' || d.status === 'initializing'
      );
    if (filter === 'complete') return d.status === 'complete';
    return true;
  });

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10">
        {/* Header */}
        <div className="border-b border-[var(--accent)]/20 bg-surface/40">
          <div className="container mx-auto px-4 py-6">
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-2xl font-theme-data text-[var(--accent)] mb-2">
                  Debate Dashboard
                </h1>
                <p className="text-text-muted font-theme-data text-sm">
                  Real-time view of AI debate sessions across your organization
                </p>
              </div>
              <div className="flex items-center gap-2">
                {wsConnected ? (
                  <span className="flex items-center gap-2 px-3 py-1 bg-success/10 border border-success/30 text-success text-xs font-theme-data">
                    <span className="w-2 h-2 rounded-full bg-success animate-pulse" />
                    LIVE
                  </span>
                ) : (
                  <span className="flex items-center gap-2 px-3 py-1 bg-acid-yellow/10 border border-acid-yellow/30 text-[var(--acid-yellow)] text-xs font-theme-data">
                    <span className="w-2 h-2 rounded-full bg-acid-yellow" />
                    POLLING
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>

        <div className="container mx-auto px-4 py-6 space-y-6">
          <PanelErrorBoundary panelName="Debates">
            {/* Stats */}
            <DeliberationStats stats={stats} loading={loading} />

            {/* Charts Row */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              <ConsensusFormationChart events={events} height={160} />
              <AgentInfluenceNetwork agents={agentInfluence} height={160} />
            </div>

            {/* Filter tabs */}
            <div className="flex items-center gap-4 border-b border-[var(--accent)]/20 pb-4">
              <span className="text-xs font-theme-data text-text-muted uppercase">Filter:</span>
              {(['all', 'active', 'complete'] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f)}
                  className={`px-3 py-1 text-xs font-theme-data uppercase transition-colors ${
                    filter === f
                      ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/40'
                      : 'text-text-muted hover:text-text border border-transparent'
                  }`}
                >
                  {f}
                  {f === 'active' && (
                    <span className="ml-1 text-[var(--acid-cyan)]">
                      (
                      {
                        deliberations.filter(
                          (d) => d.status === 'active' || d.status === 'consensus_forming',
                        ).length
                      }
                      )
                    </span>
                  )}
                </button>
              ))}
            </div>

            {/* Debate Grid */}
            <DeliberationGrid
              deliberations={filteredDeliberations}
              loading={loading}
              emptyMessage={
                filter === 'active' ? 'No active debate sessions' : 'No debate sessions found'
              }
            />
          </PanelErrorBoundary>
        </div>

        {/* Footer */}
        <footer className="text-center text-xs font-theme-data py-8 border-t border-[var(--accent)]/20 mt-8">
          <div className="text-[var(--accent)]/50 mb-2">{'='.repeat(40)}</div>
          <p className="text-text-muted">{'>'} ARAGORA // MULTI-AGENT DEBATE PLATFORM</p>
        </footer>
      </main>
    </>
  );
}
