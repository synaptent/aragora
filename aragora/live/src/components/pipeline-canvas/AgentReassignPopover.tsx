'use client';

import { useState, useCallback, useMemo } from 'react';
import { apiFetch } from '@/lib/api';

interface AlternativeAgent {
  name: string;
  score: number | null;
}

interface AgentReassignPopoverProps {
  nodeId: string;
  pipelineId: string;
  currentAgent?: string;
  alternativeAgents?: AlternativeAgent[];
  onReassign: (agent: string) => void;
  onClose: () => void;
}

export function AgentReassignPopover({
  nodeId,
  pipelineId,
  currentAgent,
  alternativeAgents,
  onReassign,
  onClose,
}: AgentReassignPopoverProps) {
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const sortedAgents = useMemo(() => {
    if (!alternativeAgents || alternativeAgents.length === 0) return [];
    return [...alternativeAgents].sort((a, b) => {
      if (a.score === null && b.score === null) return 0;
      if (a.score === null) return 1;
      if (b.score === null) return -1;
      return b.score - a.score;
    });
  }, [alternativeAgents]);

  const handleReassign = useCallback(
    async (agentName: string) => {
      setLoading(agentName);
      setError(null);
      try {
        await apiFetch(
          `/api/v1/pipeline/graph/${encodeURIComponent(pipelineId)}/node/${encodeURIComponent(nodeId)}/reassign`,
          { method: 'POST', body: JSON.stringify({ agent: agentName }) },
        );
        onReassign(agentName);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Reassignment failed');
      } finally {
        setLoading(null);
      }
    },
    [nodeId, pipelineId, onReassign],
  );

  return (
    <div className="w-64 rounded-lg border border-[var(--accent)]/30 bg-surface shadow-lg shadow-black/40">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--accent)]/30">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
          Reassign Agent
        </span>
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text text-lg leading-none p-0.5"
          aria-label="Close popover"
        >
          &times;
        </button>
      </div>

      {/* Current agent */}
      {currentAgent && (
        <div className="px-3 py-2 border-b border-border">
          <span className="text-xs font-theme-data text-text-muted">Current: </span>
          <span className="text-xs font-theme-data text-text">{currentAgent}</span>
        </div>
      )}

      {/* Agent list */}
      <div className="max-h-48 overflow-y-auto">
        {sortedAgents.length === 0 ? (
          <div className="px-3 py-4 text-xs font-theme-data text-text-muted text-center">
            No alternative agents available
          </div>
        ) : (
          <div className="py-1">
            {sortedAgents.map((agent) => {
              const isCurrentAgent = agent.name === currentAgent;
              const isLoading = loading === agent.name;

              return (
                <div
                  key={agent.name}
                  className="flex items-center justify-between px-3 py-1.5 hover:bg-[var(--accent)]/5 transition-colors"
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span
                      className={`text-xs font-theme-data truncate ${
                        isCurrentAgent ? 'text-text-muted' : 'text-text'
                      }`}
                    >
                      {agent.name}
                    </span>
                    {agent.score !== null && (
                      <span className="text-xs font-theme-data text-[var(--accent)]/70 flex-shrink-0">
                        {Math.round(agent.score)}
                      </span>
                    )}
                  </div>
                  <button
                    onClick={() => handleReassign(agent.name)}
                    disabled={isCurrentAgent || loading !== null}
                    className={`ml-2 px-2 py-0.5 text-[10px] font-theme-data rounded border transition-colors flex-shrink-0 ${
                      isCurrentAgent
                        ? 'border-border text-text-muted cursor-default'
                        : isLoading
                          ? 'border-[var(--accent)]/30 text-[var(--accent)]/60 animate-pulse cursor-wait'
                          : 'border-[var(--accent)]/30 text-[var(--accent)] hover:bg-[var(--accent)]/10 hover:border-[var(--accent)]/50'
                    }`}
                  >
                    {isCurrentAgent ? 'Active' : isLoading ? 'Reassigning...' : 'Reassign'}
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Error state */}
      {error && (
        <div className="px-3 py-2 border-t border-border">
          <span className="text-xs font-theme-data text-[var(--crimson)]/80">
            {'>'} {error}
          </span>
        </div>
      )}
    </div>
  );
}

export default AgentReassignPopover;
