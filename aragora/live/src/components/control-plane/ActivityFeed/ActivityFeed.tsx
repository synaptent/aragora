'use client';

import { useMemo, useState, useCallback, useEffect, useRef } from 'react';
import { ActivityEventItem, type ActivityEvent, type ActivityEventType } from './ActivityEventItem';

export interface ActivityFeedProps {
  /** Events to display */
  events: ActivityEvent[];
  /** Maximum events to show (rest are collapsed) */
  maxVisible?: number;
  /** Enable auto-scroll to new events */
  autoScroll?: boolean;
  /** Enable filtering by event type */
  showFilters?: boolean;
  /** Event types to show (null = all) */
  filterTypes?: ActivityEventType[] | null;
  /** Compact display mode */
  compact?: boolean;
  /** Show timestamps */
  showTimestamps?: boolean;
  /** Callback when an event is clicked */
  onEventClick?: (event: ActivityEvent) => void;
  /** Callback when filter changes */
  onFilterChange?: (types: ActivityEventType[] | null) => void;
  /** Additional className */
  className?: string;
  /** Title for the feed */
  title?: string;
  /** Show "View All" link */
  showViewAll?: boolean;
  /** Callback for "View All" */
  onViewAll?: () => void;
}

const filterPresets: { label: string; types: ActivityEventType[] }[] = [
  { label: 'All', types: [] },
  { label: 'Agents', types: ['agent_registered', 'agent_offline', 'agent_error'] },
  { label: 'Tasks', types: ['task_completed', 'task_failed'] },
  {
    label: 'Debates',
    types: ['deliberation_started', 'deliberation_consensus', 'deliberation_failed'],
  },
  { label: 'Connectors', types: ['connector_sync', 'connector_error'] },
  { label: 'Alerts', types: ['policy_violation', 'sla_warning', 'sla_violation', 'agent_error'] },
];

/**
 * Activity Feed - Real-time event timeline for the control plane.
 *
 * Displays:
 * - Agent registrations/failures
 * - Task completions/errors
 * - Debate events
 * - Connector sync events
 * - Policy violations
 */
export function ActivityFeed({
  events,
  maxVisible = 20,
  autoScroll = true,
  showFilters = true,
  filterTypes = null,
  compact = false,
  onEventClick,
  onFilterChange,
  className = '',
  title = 'Activity',
  showViewAll = false,
  onViewAll,
}: ActivityFeedProps) {
  const [activeFilter, setActiveFilter] = useState<string>('All');
  const [internalFilterTypes, setInternalFilterTypes] = useState<ActivityEventType[] | null>(
    filterTypes,
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const prevEventsLengthRef = useRef(events.length);

  // Handle filter change
  const handleFilterClick = useCallback(
    (preset: { label: string; types: ActivityEventType[] }) => {
      setActiveFilter(preset.label);
      const newTypes = preset.types.length > 0 ? preset.types : null;
      setInternalFilterTypes(newTypes);
      onFilterChange?.(newTypes);
    },
    [onFilterChange],
  );

  // Filter events
  const filteredEvents = useMemo(() => {
    const types = internalFilterTypes;
    if (!types || types.length === 0) {
      return events;
    }
    return events.filter((e) => types.includes(e.type));
  }, [events, internalFilterTypes]);

  // Limit visible events
  const visibleEvents = useMemo(() => {
    return filteredEvents.slice(0, maxVisible);
  }, [filteredEvents, maxVisible]);

  // Count by severity for header
  const severityCounts = useMemo(() => {
    const counts = { error: 0, warning: 0, info: 0, success: 0 };
    events.forEach((e) => {
      const severity = e.severity || 'info';
      counts[severity]++;
    });
    return counts;
  }, [events]);

  // Auto-scroll when new events arrive
  useEffect(() => {
    if (autoScroll && scrollRef.current && events.length > prevEventsLengthRef.current) {
      scrollRef.current.scrollTop = 0;
    }
    prevEventsLengthRef.current = events.length;
  }, [events.length, autoScroll]);

  return (
    <div className={`card ${className}`}>
      {/* Header */}
      <div className="p-4 border-b border-border">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-[var(--accent)] animate-pulse" />
            <h3 className="font-theme-data text-sm text-[var(--accent)]">{title}</h3>
            {events.length > 0 && (
              <span className="text-xs text-text-muted font-theme-data">
                ({filteredEvents.length})
              </span>
            )}
          </div>

          <div className="flex items-center gap-3">
            {/* Severity badges */}
            {severityCounts.error > 0 && (
              <span className="flex items-center gap-1 text-xs font-theme-data text-[var(--crimson)]">
                <span className="w-1.5 h-1.5 rounded-full bg-[var(--crimson)]" />
                {severityCounts.error}
              </span>
            )}
            {severityCounts.warning > 0 && (
              <span className="flex items-center gap-1 text-xs font-theme-data text-yellow-400">
                <span className="w-1.5 h-1.5 rounded-full bg-yellow-400" />
                {severityCounts.warning}
              </span>
            )}

            {showViewAll && onViewAll && (
              <button
                onClick={onViewAll}
                className="text-xs text-text-muted hover:text-[var(--accent)] transition-colors font-theme-data"
              >
                View All &rarr;
              </button>
            )}
          </div>
        </div>

        {/* Filters */}
        {showFilters && (
          <div className="flex gap-2 flex-wrap">
            {filterPresets.map((preset) => (
              <button
                key={preset.label}
                onClick={() => handleFilterClick(preset)}
                className={`px-2 py-1 text-xs font-theme-data rounded transition-colors ${
                  activeFilter === preset.label
                    ? 'bg-[var(--accent)]/20 text-[var(--accent)] border border-[var(--accent)]/30'
                    : 'bg-surface text-text-muted hover:text-text border border-transparent'
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Events List */}
      <div ref={scrollRef} className="max-h-[400px] overflow-y-auto">
        {visibleEvents.length === 0 ? (
          <div className="p-6 text-center text-text-muted font-theme-data text-sm">
            No activity to display
          </div>
        ) : (
          <div className={compact ? 'p-2 space-y-1' : 'p-4 space-y-3'}>
            {visibleEvents.map((event) => (
              <ActivityEventItem
                key={event.id}
                event={event}
                compact={compact}
                onClick={onEventClick}
              />
            ))}

            {filteredEvents.length > maxVisible && (
              <div className="text-center pt-2">
                <span className="text-xs font-theme-data text-text-muted">
                  + {filteredEvents.length - maxVisible} more events
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default ActivityFeed;
