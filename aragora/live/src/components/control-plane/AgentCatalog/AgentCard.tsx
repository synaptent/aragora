'use client';

import { useCallback } from 'react';
import { TrustBadge, type CalibrationData } from '@/components/TrustBadge';

export type AgentStatus = 'idle' | 'working' | 'error' | 'rate_limited' | 'offline';

export interface AgentInfo {
  id: string;
  name: string;
  model: string;
  description?: string;
  status: AgentStatus;
  current_task?: string;
  elo?: number;
  win_rate?: number;
  calibration_score?: number;
  brier_score?: number;
  calibration?: CalibrationData | null;
  expertise?: string[];
  tokens_used_today?: number;
  requests_today?: number;
  last_active?: string;
  error_message?: string;
}

export interface AgentCardProps {
  agent: AgentInfo;
  selected?: boolean;
  onSelect?: (agent: AgentInfo) => void;
  onConfigure?: (agent: AgentInfo) => void;
  onViewCalibration?: (agent: AgentInfo) => void;
  compact?: boolean;
}

const statusColors: Record<AgentStatus, { bg: string; text: string; dot: string }> = {
  idle: { bg: 'bg-green-900/20', text: 'text-green-400', dot: 'bg-green-400' },
  working: { bg: 'bg-blue-900/20', text: 'text-blue-400', dot: 'bg-blue-400 animate-pulse' },
  error: { bg: 'bg-red-900/20', text: 'text-red-400', dot: 'bg-red-400' },
  rate_limited: { bg: 'bg-yellow-900/20', text: 'text-yellow-400', dot: 'bg-yellow-400' },
  offline: { bg: 'bg-gray-900/20', text: 'text-gray-400', dot: 'bg-gray-400' },
};

const statusLabels: Record<AgentStatus, string> = {
  idle: 'Available',
  working: 'Working',
  error: 'Error',
  rate_limited: 'Rate Limited',
  offline: 'Offline',
};

/**
 * Card component for displaying an agent in the catalog.
 */
export function AgentCard({
  agent,
  selected = false,
  onSelect,
  onConfigure,
  onViewCalibration,
  compact = false,
}: AgentCardProps) {
  const colors = statusColors[agent.status];

  const handleClick = useCallback(() => {
    onSelect?.(agent);
  }, [agent, onSelect]);

  const handleConfigure = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onConfigure?.(agent);
    },
    [agent, onConfigure],
  );

  const handleViewCalibration = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      onViewCalibration?.(agent);
    },
    [agent, onViewCalibration],
  );

  // Calibration score color (higher is better)
  const getCalibrationColor = (score: number) => {
    if (score >= 0.8) return 'text-green-400';
    if (score >= 0.6) return 'text-[var(--acid-cyan)]';
    if (score >= 0.4) return 'text-yellow-400';
    return 'text-red-400';
  };

  if (compact) {
    return (
      <div
        onClick={handleClick}
        className={`flex items-center gap-3 p-3 rounded border transition-colors cursor-pointer ${
          selected
            ? 'border-[var(--accent)] bg-[var(--accent)]/10'
            : 'border-border hover:border-text-muted'
        }`}
      >
        {/* Status dot */}
        <div className={`w-2 h-2 rounded-full ${colors.dot}`} />

        {/* Name and model */}
        <div className="flex-1 min-w-0">
          <div className="text-sm font-theme-data text-text truncate">{agent.name}</div>
          <div className="text-xs text-text-muted truncate">{agent.model}</div>
        </div>

        {/* ELO if available */}
        {agent.elo !== undefined && (
          <div className="text-xs text-[var(--accent)] font-theme-data">{agent.elo}</div>
        )}
      </div>
    );
  }

  return (
    <div
      onClick={handleClick}
      className={`p-4 rounded-lg border transition-all cursor-pointer ${
        selected
          ? 'border-[var(--accent)] bg-[var(--accent)]/10 shadow-lg shadow-acid-green/20'
          : 'border-border hover:border-text-muted hover:bg-surface/50'
      }`}
    >
      {/* Header */}
      <div className="flex items-start justify-between mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5">
            <h4 className="text-sm font-theme-data text-text truncate">{agent.name}</h4>
            <TrustBadge calibration={agent.calibration} size="sm" />
          </div>
          <p className="text-xs text-text-muted truncate">{agent.model}</p>
        </div>

        {/* Status badge */}
        <div
          className={`flex items-center gap-1.5 px-2 py-1 rounded text-xs ${colors.bg} ${colors.text}`}
        >
          <div className={`w-1.5 h-1.5 rounded-full ${colors.dot}`} />
          {statusLabels[agent.status]}
        </div>
      </div>

      {/* Description */}
      {agent.description && (
        <p className="text-xs text-text-muted mb-3 line-clamp-2">{agent.description}</p>
      )}

      {/* Current task (if working) */}
      {agent.status === 'working' && agent.current_task && (
        <div className="mb-3 p-2 bg-blue-900/10 border border-blue-800/30 rounded text-xs">
          <span className="text-blue-400">Working on: </span>
          <span className="text-text-muted">{agent.current_task}</span>
        </div>
      )}

      {/* Error message (if error) */}
      {agent.status === 'error' && agent.error_message && (
        <div className="mb-3 p-2 bg-red-900/10 border border-red-800/30 rounded text-xs text-red-400">
          {agent.error_message}
        </div>
      )}

      {/* Stats row */}
      <div className="flex items-center justify-between text-xs">
        <div className="flex items-center gap-3">
          {/* ELO */}
          {agent.elo !== undefined && (
            <div className="flex items-center gap-1">
              <span className="text-text-muted">ELO:</span>
              <span className="text-[var(--accent)] font-theme-data">{agent.elo}</span>
            </div>
          )}

          {/* Win rate */}
          {agent.win_rate !== undefined && (
            <div className="flex items-center gap-1">
              <span className="text-text-muted">Win:</span>
              <span className="text-[var(--acid-cyan)] font-theme-data">
                {Math.round(agent.win_rate * 100)}%
              </span>
            </div>
          )}

          {/* Calibration score */}
          {agent.calibration_score !== undefined && (
            <div className="flex items-center gap-1">
              <span className="text-text-muted">Cal:</span>
              <span className={`font-theme-data ${getCalibrationColor(agent.calibration_score)}`}>
                {Math.round(agent.calibration_score * 100)}%
              </span>
            </div>
          )}
        </div>

        {/* Action buttons */}
        <div className="flex items-center gap-2">
          {/* Calibration button */}
          {onViewCalibration && (
            <button
              onClick={handleViewCalibration}
              className="text-text-muted hover:text-[var(--acid-cyan)] transition-colors"
              title="View calibration curve"
            >
              📊
            </button>
          )}

          {/* Configure button */}
          {onConfigure && (
            <button
              onClick={handleConfigure}
              className="text-text-muted hover:text-[var(--accent)] transition-colors"
              title="Configure agent"
            >
              ⚙
            </button>
          )}
        </div>
      </div>

      {/* Expertise tags */}
      {agent.expertise && agent.expertise.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-1">
          {agent.expertise.slice(0, 3).map((skill) => (
            <span key={skill} className="px-1.5 py-0.5 text-xs bg-surface rounded text-text-muted">
              {skill}
            </span>
          ))}
          {agent.expertise.length > 3 && (
            <span className="px-1.5 py-0.5 text-xs text-text-muted">
              +{agent.expertise.length - 3}
            </span>
          )}
        </div>
      )}

      {/* Usage stats (subtle footer) */}
      {(agent.tokens_used_today !== undefined || agent.requests_today !== undefined) && (
        <div className="mt-3 pt-2 border-t border-border/50 flex items-center gap-3 text-xs text-text-muted">
          {agent.tokens_used_today !== undefined && (
            <span>{agent.tokens_used_today.toLocaleString()} tokens today</span>
          )}
          {agent.requests_today !== undefined && <span>{agent.requests_today} requests</span>}
        </div>
      )}
    </div>
  );
}

export default AgentCard;
