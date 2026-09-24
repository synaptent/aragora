'use client';

import { memo, useState } from 'react';
import { AgentCard, type AgentStatus } from './AgentCard';

export interface AgentExecutionPanelProps {
  agents: AgentStatus[];
  onApprove?: (agentId: string, notes?: string) => void;
  onReject?: (agentId: string, feedback: string) => void;
}

export const AgentExecutionPanel = memo(function AgentExecutionPanel({
  agents,
  onApprove,
  onReject,
}: AgentExecutionPanelProps) {
  const [isOpen, setIsOpen] = useState(true);

  const active = agents.filter((a) => a.status === 'executing' || a.status === 'awaiting_approval');
  const completed = agents.filter((a) => a.status === 'completed');
  const failed = agents.filter((a) => a.status === 'failed');

  return (
    <div
      className="flex flex-col border-l border-[var(--border)] bg-[var(--surface)] w-80"
      data-testid="agent-execution-panel"
    >
      {/* Header */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center justify-between px-4 py-3 border-b border-[var(--border)] hover:bg-[var(--bg)] transition-colors"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm">🤖</span>
          <span className="text-xs font-theme-data font-bold text-[var(--text)]">Agents</span>
          <span className="px-1.5 py-0.5 text-xs font-theme-data rounded-full bg-blue-500/20 text-blue-400">
            {agents.length}
          </span>
        </div>
        <div className="flex items-center gap-2">
          {active.length > 0 && (
            <span
              className="w-2 h-2 rounded-full bg-blue-400 animate-pulse"
              title={`${active.length} active`}
            />
          )}
          {failed.length > 0 && (
            <span className="w-2 h-2 rounded-full bg-red-400" title={`${failed.length} failed`} />
          )}
          <span className="text-xs text-[var(--text-muted)]">{isOpen ? '\u25BC' : '\u25B6'}</span>
        </div>
      </button>

      {isOpen && (
        <div className="flex-1 overflow-y-auto">
          {/* Summary stats */}
          <div className="flex gap-3 px-4 py-2 text-xs font-theme-data text-[var(--text-muted)] border-b border-[var(--border)]">
            <span className="text-blue-400">{active.length} active</span>
            <span className="text-emerald-400">{completed.length} done</span>
            {failed.length > 0 && <span className="text-red-400">{failed.length} failed</span>}
          </div>

          {/* Active agents first */}
          {active.map((agent) => (
            <AgentCard key={agent.id} agent={agent} onApprove={onApprove} onReject={onReject} />
          ))}

          {/* Then completed */}
          {completed.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}

          {/* Then failed */}
          {failed.map((agent) => (
            <AgentCard key={agent.id} agent={agent} />
          ))}

          {agents.length === 0 && (
            <div className="p-4 text-xs font-theme-data text-[var(--text-muted)] text-center">
              No agents assigned yet
            </div>
          )}
        </div>
      )}
    </div>
  );
});

export default AgentExecutionPanel;
