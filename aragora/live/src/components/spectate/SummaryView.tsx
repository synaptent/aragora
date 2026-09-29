'use client';

import { useSpectateStore, type SpectatorEvent } from '@/store/spectateStore';

/**
 * Real-time consensus summary view for spectating debates.
 * Aggregates events into a dashboard showing debate progress,
 * agent stances, and consensus metrics.
 */
export function SummaryView() {
  const events = useSpectateStore((s) => s.events);
  const agents = useSpectateStore((s) => s.agents);
  const currentRound = useSpectateStore((s) => s.currentRound);
  const task = useSpectateStore((s) => s.task);

  // Derive summary stats from events
  const stats = deriveSummaryStats(events, agents);

  if (events.length === 0) {
    return (
      <div className="flex items-center justify-center h-[500px]">
        <div className="text-center text-text-muted">
          <div className="w-8 h-8 border-2 border-accent/30 border-t-accent rounded-full animate-spin mx-auto mb-4" />
          <p className="font-theme-data text-sm">Waiting for events...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-6">
      {/* Debate Topic */}
      {task && (
        <div className="card-theme p-4">
          <div className="text-[10px] font-theme-data text-text-muted uppercase mb-1">Topic</div>
          <div className="text-sm font-theme-data text-text">{task}</div>
        </div>
      )}

      {/* Progress Overview */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard label="Round" value={`${currentRound}`} color="accent" />
        <StatCard label="Agents" value={`${agents.length}`} color="acid-cyan" />
        <StatCard label="Proposals" value={`${stats.proposalCount}`} color="acid-cyan" />
        <StatCard label="Critiques" value={`${stats.critiqueCount}`} color="crimson" />
      </div>

      {/* Consensus Indicator */}
      <div className="card-theme p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase">
            Consensus Progress
          </h3>
          <span
            className={`text-xs font-theme-data px-2 py-0.5 border badge-theme ${
              stats.hasConsensus
                ? 'text-success border-success/30 bg-success/10'
                : stats.latestConvergence !== null && stats.latestConvergence > 0.7
                  ? 'text-warning border-warning/30 bg-warning/10'
                  : 'text-text-muted border-border bg-surface'
            }`}
          >
            {stats.hasConsensus
              ? 'REACHED'
              : stats.latestConvergence !== null
                ? `${(stats.latestConvergence * 100).toFixed(0)}%`
                : 'PENDING'}
          </span>
        </div>

        {/* Convergence bar */}
        {stats.latestConvergence !== null && (
          <div className="w-full h-2 bg-bg rounded-full overflow-hidden">
            <div
              className={`h-full transition-all duration-500 ${
                stats.hasConsensus
                  ? 'bg-success'
                  : stats.latestConvergence > 0.7
                    ? 'bg-warning'
                    : 'bg-accent'
              }`}
              style={{ width: `${Math.min(stats.latestConvergence * 100, 100)}%` }}
            />
          </div>
        )}

        {/* Convergence history */}
        {stats.convergenceHistory.length > 1 && (
          <div className="mt-3 flex items-end gap-1 h-8">
            {stats.convergenceHistory.map((val, i) => (
              <div
                key={i}
                className="flex-1 bg-[var(--accent)]/30 rounded-t transition-all"
                style={{ height: `${Math.max(val * 100, 4)}%` }}
                title={`${(val * 100).toFixed(1)}%`}
              />
            ))}
          </div>
        )}
      </div>

      {/* Agent Activity Summary */}
      <div className="card-theme overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase">Agent Activity</h3>
        </div>
        <div className="divide-y divide-border">
          {agents.map((agent) => {
            const agentStats = stats.agentStats.get(agent);
            if (!agentStats) return null;

            return (
              <div key={agent} className="px-4 py-3 flex items-center justify-between gap-4">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-xs font-theme-data text-acid-cyan font-bold truncate">
                    {agent}
                  </span>
                </div>
                <div className="flex items-center gap-3 text-[10px] font-theme-data text-text-muted shrink-0">
                  {agentStats.proposals > 0 && (
                    <span className="text-acid-cyan">{agentStats.proposals}P</span>
                  )}
                  {agentStats.critiques > 0 && (
                    <span className="text-crimson">{agentStats.critiques}C</span>
                  )}
                  {agentStats.votes > 0 && (
                    <span className="text-warning">{agentStats.votes}V</span>
                  )}
                  {agentStats.refines > 0 && (
                    <span className="text-accent">{agentStats.refines}R</span>
                  )}
                  {agentStats.lastMetric !== null && (
                    <span className="text-accent">({agentStats.lastMetric.toFixed(2)})</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* Latest Key Events */}
      <div className="card-theme overflow-hidden">
        <div className="px-4 py-3 border-b border-border">
          <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase">Key Events</h3>
        </div>
        <div className="p-4 space-y-2">
          {stats.keyEvents.length === 0 ? (
            <p className="text-xs font-theme-data text-text-muted">No key events yet</p>
          ) : (
            stats.keyEvents.map((ev, i) => (
              <div key={i} className="flex items-start gap-2 text-xs font-theme-data">
                <span className="text-text-muted shrink-0">R{ev.round ?? 0}</span>
                <span
                  className={
                    ev.type === 'consensus'
                      ? 'text-success'
                      : ev.type === 'vote'
                        ? 'text-warning'
                        : 'text-acid-cyan'
                  }
                >
                  [{ev.type.toUpperCase()}]
                </span>
                {ev.agent && <span className="text-acid-cyan">{ev.agent}</span>}
                {ev.details && <span className="text-text truncate">{ev.details}</span>}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div className="card-theme p-3">
      <div className="text-[10px] font-theme-data text-text-muted uppercase">{label}</div>
      <div className={`text-lg font-theme-data font-bold text-${color}`}>{value}</div>
    </div>
  );
}

interface AgentStats {
  proposals: number;
  critiques: number;
  votes: number;
  refines: number;
  lastMetric: number | null;
}

interface SummaryStats {
  proposalCount: number;
  critiqueCount: number;
  hasConsensus: boolean;
  latestConvergence: number | null;
  convergenceHistory: number[];
  agentStats: Map<string, AgentStats>;
  keyEvents: SpectatorEvent[];
}

function deriveSummaryStats(events: SpectatorEvent[], agents: string[]): SummaryStats {
  const agentStats = new Map<string, AgentStats>();
  for (const agent of agents) {
    agentStats.set(agent, { proposals: 0, critiques: 0, votes: 0, refines: 0, lastMetric: null });
  }

  let proposalCount = 0;
  let critiqueCount = 0;
  let hasConsensus = false;
  let latestConvergence: number | null = null;
  const convergenceHistory: number[] = [];
  const keyEventTypes = new Set(['consensus', 'converged', 'vote', 'judge', 'debate_end']);
  const keyEvents: SpectatorEvent[] = [];

  for (const ev of events) {
    if (ev.type === 'proposal') proposalCount++;
    if (ev.type === 'critique') critiqueCount++;
    if (ev.type === 'consensus' || ev.type === 'converged') hasConsensus = true;
    if (ev.type === 'convergence' && ev.metric !== null) {
      latestConvergence = ev.metric;
      convergenceHistory.push(ev.metric);
    }

    if (ev.agent && agentStats.has(ev.agent)) {
      const stats = agentStats.get(ev.agent)!;
      if (ev.type === 'proposal') stats.proposals++;
      if (ev.type === 'critique') stats.critiques++;
      if (ev.type === 'vote') stats.votes++;
      if (ev.type === 'refine') stats.refines++;
      if (ev.metric !== null) stats.lastMetric = ev.metric;
    }

    if (keyEventTypes.has(ev.type)) {
      keyEvents.push(ev);
    }
  }

  // Keep only the last 10 key events
  const recentKeyEvents = keyEvents.slice(-10);

  return {
    proposalCount,
    critiqueCount,
    hasConsensus,
    latestConvergence,
    convergenceHistory,
    agentStats,
    keyEvents: recentKeyEvents,
  };
}
