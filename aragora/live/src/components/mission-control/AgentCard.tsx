'use client';

import { memo, useState } from 'react';
import { DiffPreview } from './DiffPreview';

export interface AgentStatus {
  id: string;
  name: string;
  agentType: string;
  currentTask?: string;
  status: 'pending' | 'executing' | 'awaiting_approval' | 'completed' | 'failed';
  progress: number;
  worktreePath?: string;
  diffPreview?: string;
  phase?: 'design' | 'implement' | 'verify';
  duration?: number;
  error?: string;
}

export interface AgentCardProps {
  agent: AgentStatus;
  onApprove?: (agentId: string, notes?: string) => void;
  onReject?: (agentId: string, feedback: string) => void;
}

const STATUS_STYLES: Record<string, { bg: string; text: string; dot: string }> = {
  pending: { bg: 'bg-gray-500/10', text: 'text-gray-400', dot: 'bg-gray-400' },
  executing: { bg: 'bg-blue-500/10', text: 'text-blue-400', dot: 'bg-blue-400 animate-pulse' },
  awaiting_approval: {
    bg: 'bg-amber-500/10',
    text: 'text-amber-400',
    dot: 'bg-amber-400 animate-pulse',
  },
  completed: { bg: 'bg-emerald-500/10', text: 'text-emerald-400', dot: 'bg-emerald-400' },
  failed: { bg: 'bg-red-500/10', text: 'text-red-400', dot: 'bg-red-400' },
};

const AGENT_TYPE_ICONS: Record<string, string> = {
  claude: '🟣',
  codex: '🟢',
  gemini: '🔵',
  grok: '⚫',
  deepseek: '🟠',
  default: '🤖',
};

export const AgentCard = memo(function AgentCard({ agent, onApprove, onReject }: AgentCardProps) {
  const [expanded, setExpanded] = useState(false);
  const [rejectFeedback, setRejectFeedback] = useState('');
  const [showRejectInput, setShowRejectInput] = useState(false);
  const style = STATUS_STYLES[agent.status] || STATUS_STYLES.pending;
  const icon = AGENT_TYPE_ICONS[agent.agentType] || AGENT_TYPE_ICONS.default;

  return (
    <div
      className={`border-b border-[var(--border)] ${style.bg}`}
      data-testid={`agent-card-${agent.id}`}
    >
      {/* Agent header */}
      <button
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left hover:bg-[var(--bg)]/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <span className="text-sm">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs font-theme-data font-bold text-[var(--text)] truncate">
              {agent.name}
            </span>
            <span className={`w-1.5 h-1.5 rounded-full ${style.dot}`} />
          </div>
          {agent.currentTask && (
            <p className="text-xs text-[var(--text-muted)] truncate mt-0.5">{agent.currentTask}</p>
          )}
        </div>
        {agent.phase && (
          <span className="px-1.5 py-0.5 text-[10px] font-theme-data bg-[var(--surface)] text-[var(--text-muted)] rounded">
            {agent.phase}
          </span>
        )}
        <span className="text-xs text-[var(--text-muted)]">{expanded ? '\u25BC' : '\u25B6'}</span>
      </button>

      {/* Progress bar */}
      {(agent.status === 'executing' || agent.status === 'awaiting_approval') && (
        <div className="px-4 pb-2">
          <div className="flex items-center gap-2">
            <div className="flex-1 h-1 bg-[var(--border)] rounded-full overflow-hidden">
              <div
                className="h-full bg-[var(--acid-green)] rounded-full transition-all duration-500"
                style={{ width: `${Math.min(100, agent.progress)}%` }}
              />
            </div>
            <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
              {agent.progress}%
            </span>
          </div>
        </div>
      )}

      {/* Expanded details */}
      {expanded && (
        <div className="px-4 pb-3 space-y-2">
          {agent.worktreePath && (
            <div className="text-xs font-theme-data text-[var(--text-muted)]">
              <span className="text-[var(--text-muted)]">worktree:</span>{' '}
              <span className="text-[var(--text)]">{agent.worktreePath}</span>
            </div>
          )}
          {agent.duration != null && (
            <div className="text-xs font-theme-data text-[var(--text-muted)]">
              <span>duration:</span> {Math.round(agent.duration / 1000)}s
            </div>
          )}
          {agent.error && (
            <div className="text-xs font-theme-data text-red-400 bg-red-500/10 rounded p-2">
              {agent.error}
            </div>
          )}
          {agent.diffPreview && <DiffPreview diff={agent.diffPreview} />}

          {/* Approval actions */}
          {agent.status === 'awaiting_approval' && onApprove && onReject && (
            <div className="space-y-2 pt-1">
              {showRejectInput ? (
                <div className="space-y-1.5">
                  <textarea
                    className="w-full text-xs font-theme-data bg-[var(--bg)] text-[var(--text)] border border-[var(--border)] rounded p-2 resize-none"
                    placeholder="Feedback for rejection..."
                    rows={2}
                    value={rejectFeedback}
                    onChange={(e) => setRejectFeedback(e.target.value)}
                  />
                  <div className="flex gap-2">
                    <button
                      className="flex-1 px-2 py-1 text-xs font-theme-data bg-red-500/20 text-red-400 rounded hover:bg-red-500/30"
                      onClick={() => {
                        onReject(agent.id, rejectFeedback);
                        setShowRejectInput(false);
                        setRejectFeedback('');
                      }}
                    >
                      Reject
                    </button>
                    <button
                      className="px-2 py-1 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)]"
                      onClick={() => setShowRejectInput(false)}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <div className="flex gap-2">
                  <button
                    className="flex-1 px-3 py-1.5 text-xs font-theme-data bg-emerald-500/20 text-emerald-400 rounded hover:bg-emerald-500/30 transition-colors"
                    onClick={() => onApprove(agent.id)}
                    data-testid={`approve-${agent.id}`}
                  >
                    ✓ Approve
                  </button>
                  <button
                    className="flex-1 px-3 py-1.5 text-xs font-theme-data bg-red-500/20 text-red-400 rounded hover:bg-red-500/30 transition-colors"
                    onClick={() => setShowRejectInput(true)}
                    data-testid={`reject-${agent.id}`}
                  >
                    ✗ Reject
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
});

export default AgentCard;
