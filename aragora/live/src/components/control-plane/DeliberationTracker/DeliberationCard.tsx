'use client';

import { useMemo } from 'react';

export type DeliberationStatus =
  'pending' | 'in_progress' | 'consensus_reached' | 'no_consensus' | 'failed' | 'timeout';

export interface DeliberationAgent {
  id: string;
  name: string;
  position?: string;
  confidence?: number;
}

export interface Deliberation {
  id: string;
  question: string;
  status: DeliberationStatus;
  started_at?: string;
  completed_at?: string;
  current_round: number;
  max_rounds: number;
  agents: DeliberationAgent[];
  consensus_confidence?: number;
  final_answer?: string;
  sla_status?: 'compliant' | 'warning' | 'critical' | 'violated';
  timeout_seconds?: number;
}

export interface DeliberationCardProps {
  deliberation: Deliberation;
  compact?: boolean;
  onClick?: (deliberation: Deliberation) => void;
}

const statusConfig: Record<
  DeliberationStatus,
  { label: string; color: string; bgColor: string; icon: string }
> = {
  pending: {
    label: 'Pending',
    color: 'text-text-muted',
    bgColor: 'bg-gray-900/20',
    icon: '\u23F3',
  },
  in_progress: {
    label: 'In Progress',
    color: 'text-[var(--acid-cyan)]',
    bgColor: 'bg-blue-900/20',
    icon: '\u25B6',
  },
  consensus_reached: {
    label: 'Consensus',
    color: 'text-green-400',
    bgColor: 'bg-green-900/20',
    icon: '\u2713',
  },
  no_consensus: {
    label: 'No Consensus',
    color: 'text-yellow-400',
    bgColor: 'bg-yellow-900/20',
    icon: '\u2260',
  },
  failed: {
    label: 'Failed',
    color: 'text-[var(--crimson)]',
    bgColor: 'bg-red-900/20',
    icon: '\u2717',
  },
  timeout: {
    label: 'Timeout',
    color: 'text-[var(--crimson)]',
    bgColor: 'bg-red-900/20',
    icon: '\u23F1',
  },
};

const slaColors: Record<string, string> = {
  compliant: 'bg-green-400',
  warning: 'bg-yellow-400',
  critical: 'bg-orange-400',
  violated: 'bg-[var(--crimson)]',
};

/**
 * Card component for displaying a single debate session.
 */
export function DeliberationCard({
  deliberation,
  compact = false,
  onClick,
}: DeliberationCardProps) {
  const config = statusConfig[deliberation.status];
  const isActive = deliberation.status === 'in_progress';

  const progress = useMemo(() => {
    if (deliberation.max_rounds === 0) return 0;
    return (deliberation.current_round / deliberation.max_rounds) * 100;
  }, [deliberation.current_round, deliberation.max_rounds]);

  const elapsedTime = useMemo(() => {
    if (!deliberation.started_at) return null;
    const start = new Date(deliberation.started_at);
    const end = deliberation.completed_at ? new Date(deliberation.completed_at) : new Date();
    const diffMs = end.getTime() - start.getTime();
    const diffSecs = Math.floor(diffMs / 1000);

    if (diffSecs < 60) return `${diffSecs}s`;
    if (diffSecs < 3600) return `${Math.floor(diffSecs / 60)}m ${diffSecs % 60}s`;
    return `${Math.floor(diffSecs / 3600)}h ${Math.floor((diffSecs % 3600) / 60)}m`;
  }, [deliberation.started_at, deliberation.completed_at]);

  const handleClick = () => {
    onClick?.(deliberation);
  };

  if (compact) {
    return (
      <div
        onClick={handleClick}
        className={`flex items-center gap-3 p-2 rounded border border-border/50 transition-colors ${
          onClick ? 'cursor-pointer hover:border-text-muted/50' : ''
        }`}
      >
        <span className={`text-sm ${config.color}`}>{config.icon}</span>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-theme-data text-text truncate">
            {deliberation.question.substring(0, 50)}...
          </div>
          <div className="text-xs text-text-muted">
            Round {deliberation.current_round}/{deliberation.max_rounds}
          </div>
        </div>
        {deliberation.sla_status && (
          <span className={`w-2 h-2 rounded-full ${slaColors[deliberation.sla_status]}`} />
        )}
      </div>
    );
  }

  return (
    <div
      onClick={handleClick}
      className={`rounded-lg border transition-all ${
        isActive
          ? 'border-[var(--acid-cyan)]/50 bg-[var(--acid-cyan)]/5'
          : 'border-border hover:border-text-muted/50'
      } ${onClick ? 'cursor-pointer' : ''}`}
    >
      {/* Header */}
      <div className="p-4 border-b border-border/50">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-theme-data text-text line-clamp-2">
              {deliberation.question}
            </p>
          </div>

          {/* Status badge */}
          <div
            className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${config.bgColor} ${config.color} flex-shrink-0`}
          >
            <span>{config.icon}</span>
            {config.label}
          </div>
        </div>
      </div>

      {/* Progress bar (for in-progress) */}
      {isActive && (
        <div className="px-4 pt-3">
          <div className="flex items-center justify-between text-xs font-theme-data text-text-muted mb-1">
            <span>
              Round {deliberation.current_round}/{deliberation.max_rounds}
            </span>
            {elapsedTime && <span>{elapsedTime}</span>}
          </div>
          <div className="h-1.5 bg-surface rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--acid-cyan)] transition-all"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Agents */}
      <div className="p-4">
        <div className="text-xs text-text-muted font-theme-data mb-2">PARTICIPANTS</div>
        <div className="flex flex-wrap gap-2">
          {deliberation.agents.map((agent) => (
            <div
              key={agent.id}
              className="flex items-center gap-1.5 px-2 py-1 bg-surface rounded text-xs"
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  isActive ? 'bg-[var(--acid-cyan)] animate-pulse' : 'bg-text-muted'
                }`}
              />
              <span className="font-theme-data text-text">{agent.name}</span>
              {agent.confidence !== undefined && (
                <span className="text-text-muted">({Math.round(agent.confidence * 100)}%)</span>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Consensus result (if reached) */}
      {deliberation.status === 'consensus_reached' && deliberation.final_answer && (
        <div className="px-4 pb-4">
          <div className="p-3 bg-green-900/10 border border-green-800/30 rounded">
            <div className="text-xs text-green-400 font-theme-data mb-1">
              CONSENSUS ({Math.round((deliberation.consensus_confidence || 0) * 100)}%)
            </div>
            <p className="text-sm text-text line-clamp-3">{deliberation.final_answer}</p>
          </div>
        </div>
      )}

      {/* SLA indicator */}
      {deliberation.sla_status && (
        <div className="px-4 pb-3">
          <div className="flex items-center gap-2 text-xs">
            <span className={`w-2 h-2 rounded-full ${slaColors[deliberation.sla_status]}`} />
            <span className="text-text-muted font-theme-data">SLA: {deliberation.sla_status}</span>
            {deliberation.timeout_seconds && (
              <span className="text-text-muted">(timeout: {deliberation.timeout_seconds}s)</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export default DeliberationCard;
