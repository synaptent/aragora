'use client';

import React, { useMemo } from 'react';
import type { AgentInfluence } from './types';
import { getAgentColors } from '@/utils/agentColors';

interface AgentInfluenceNetworkProps {
  agents: AgentInfluence[];
  height?: number;
}

export function AgentInfluenceNetwork({ agents, height = 200 }: AgentInfluenceNetworkProps) {
  const sortedAgents = useMemo(
    () => [...agents].sort((a, b) => b.influence_score - a.influence_score),
    [agents],
  );

  const maxInfluence = Math.max(...agents.map((a) => a.influence_score), 1);

  if (agents.length === 0) {
    return (
      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="text-xs font-theme-data text-[var(--accent)] mb-2 uppercase">
          {'>'} AGENT INFLUENCE
        </div>
        <div
          className="flex items-center justify-center text-text-muted font-theme-data text-xs"
          style={{ height }}
        >
          No agent data available
        </div>
      </div>
    );
  }

  return (
    <div className="bg-surface border border-[var(--accent)]/30 p-4">
      <div className="text-xs font-theme-data text-[var(--accent)] mb-3 uppercase">
        {'>'} AGENT INFLUENCE
      </div>

      <div className="space-y-3" style={{ maxHeight: height, overflowY: 'auto' }}>
        {sortedAgents.map((agent) => {
          const colors = getAgentColors(agent.agent_id);
          const barWidth = (agent.influence_score / maxInfluence) * 100;

          return (
            <div key={agent.agent_id} className="space-y-1">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`px-1.5 py-0.5 text-xs font-theme-data ${colors.bg} ${colors.text} ${colors.border} border`}
                  >
                    {agent.agent_id.split('-')[0]}
                  </span>
                  <span className="text-xs font-theme-data text-text-muted">
                    {agent.message_count} msgs
                  </span>
                </div>
                <span className="text-xs font-theme-data text-text">
                  {Math.round(agent.influence_score * 100)}%
                </span>
              </div>

              <div className="h-1.5 bg-bg rounded-full overflow-hidden">
                <div
                  className={`h-full transition-all ${colors.bg.replace('/20', '/60')}`}
                  style={{ width: `${barWidth}%` }}
                />
              </div>

              <div className="flex items-center gap-4 text-xs font-theme-data text-text-muted">
                <span>Consensus: {Math.round(agent.consensus_contributions * 100)}%</span>
                <span>Conf: {Math.round(agent.average_confidence * 100)}%</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
