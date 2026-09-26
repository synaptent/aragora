'use client';

import { useMemo } from 'react';

export type ActivityEventType =
  | 'agent_registered'
  | 'agent_offline'
  | 'agent_error'
  | 'task_completed'
  | 'task_failed'
  | 'deliberation_started'
  | 'deliberation_consensus'
  | 'deliberation_failed'
  | 'connector_sync'
  | 'connector_error'
  | 'policy_violation'
  | 'sla_warning'
  | 'sla_violation';

export interface ActivityEvent {
  id: string;
  type: ActivityEventType;
  timestamp: string;
  title: string;
  description?: string;
  metadata?: Record<string, unknown>;
  severity?: 'info' | 'warning' | 'error' | 'success';
  actor?: { type: 'agent' | 'connector' | 'system' | 'user'; id: string; name?: string };
}

export interface ActivityEventItemProps {
  event: ActivityEvent;
  compact?: boolean;
  onClick?: (event: ActivityEvent) => void;
}

const eventConfig: Record<ActivityEventType, { icon: string; color: string; bgColor: string }> = {
  agent_registered: { icon: '+', color: 'text-green-400', bgColor: 'bg-green-900/20' },
  agent_offline: { icon: '-', color: 'text-gray-400', bgColor: 'bg-gray-900/20' },
  agent_error: { icon: '!', color: 'text-[var(--crimson)]', bgColor: 'bg-red-900/20' },
  task_completed: { icon: '\u2713', color: 'text-green-400', bgColor: 'bg-green-900/20' },
  task_failed: { icon: '\u2717', color: 'text-[var(--crimson)]', bgColor: 'bg-red-900/20' },
  deliberation_started: {
    icon: '\u25B6',
    color: 'text-[var(--acid-cyan)]',
    bgColor: 'bg-blue-900/20',
  },
  deliberation_consensus: {
    icon: '\u2605',
    color: 'text-[var(--accent)]',
    bgColor: 'bg-green-900/20',
  },
  deliberation_failed: { icon: '\u2716', color: 'text-[var(--crimson)]', bgColor: 'bg-red-900/20' },
  connector_sync: { icon: '\u21BB', color: 'text-[var(--acid-cyan)]', bgColor: 'bg-blue-900/20' },
  connector_error: { icon: '!', color: 'text-[var(--crimson)]', bgColor: 'bg-red-900/20' },
  policy_violation: { icon: '\u26A0', color: 'text-yellow-400', bgColor: 'bg-yellow-900/20' },
  sla_warning: { icon: '\u23F1', color: 'text-yellow-400', bgColor: 'bg-yellow-900/20' },
  sla_violation: { icon: '\u23F1', color: 'text-[var(--crimson)]', bgColor: 'bg-red-900/20' },
};

/**
 * Single event item in the activity feed.
 */
export function ActivityEventItem({ event, compact = false, onClick }: ActivityEventItemProps) {
  const config = eventConfig[event.type] || {
    icon: '\u2022',
    color: 'text-text-muted',
    bgColor: 'bg-surface',
  };

  const formattedTime = useMemo(() => {
    const date = new Date(event.timestamp);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);

    if (diffMins < 1) return 'just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
  }, [event.timestamp]);

  const handleClick = () => {
    onClick?.(event);
  };

  if (compact) {
    return (
      <div
        onClick={handleClick}
        className={`flex items-center gap-2 py-1.5 px-2 rounded transition-colors ${
          onClick ? 'cursor-pointer hover:bg-surface/50' : ''
        }`}
      >
        <span
          className={`w-5 h-5 rounded flex items-center justify-center text-xs ${config.bgColor} ${config.color}`}
        >
          {config.icon}
        </span>
        <span className="text-xs font-theme-data text-text truncate flex-1">{event.title}</span>
        <span className="text-xs font-theme-data text-text-muted">{formattedTime}</span>
      </div>
    );
  }

  return (
    <div
      onClick={handleClick}
      className={`flex gap-3 p-3 rounded border border-border/50 transition-colors ${
        onClick ? 'cursor-pointer hover:border-text-muted/50 hover:bg-surface/30' : ''
      }`}
    >
      {/* Icon */}
      <div
        className={`w-8 h-8 rounded-full flex items-center justify-center text-sm flex-shrink-0 ${config.bgColor} ${config.color}`}
      >
        {config.icon}
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2">
          <span className="text-sm font-theme-data text-text">{event.title}</span>
          <span className="text-xs font-theme-data text-text-muted whitespace-nowrap">
            {formattedTime}
          </span>
        </div>

        {event.description && (
          <p className="text-xs text-text-muted mt-1 line-clamp-2">{event.description}</p>
        )}

        {event.actor && (
          <div className="flex items-center gap-1 mt-2 text-xs text-text-muted">
            <span className="opacity-60">{event.actor.type}:</span>
            <span className="text-[var(--acid-cyan)]">{event.actor.name || event.actor.id}</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default ActivityEventItem;
