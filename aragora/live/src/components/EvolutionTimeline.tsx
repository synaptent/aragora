'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { API_BASE_URL } from '@/config';

interface GenesisEvent {
  event_id: string;
  event_type: string;
  timestamp: string;
  parent_event_id?: string;
  content_hash?: string;
  data: {
    genome_id?: string;
    agent_name?: string;
    fitness_change?: number;
    old_fitness?: number;
    new_fitness?: number;
    parent_ids?: string[];
    mutation_type?: string;
    strategy?: string;
    [key: string]: unknown;
  };
}

interface EvolutionTimelineProps {
  apiBase?: string;
  limit?: number;
  eventTypeFilter?: string;
  onEventClick?: (event: GenesisEvent) => void;
  autoRefresh?: boolean;
  refreshInterval?: number;
}

const EVENT_COLORS: Record<string, { bg: string; border: string; text: string; icon: string }> = {
  agent_birth: {
    bg: 'bg-[var(--accent)]/20',
    border: 'border-[var(--accent)]',
    text: 'text-[var(--accent)]',
    icon: '\u{1F423}', // hatching chick
  },
  agent_death: {
    bg: 'bg-acid-red/20',
    border: 'border-acid-red',
    text: 'text-acid-red',
    icon: '\u{1F480}', // skull
  },
  mutation: {
    bg: 'bg-[var(--acid-cyan)]/20',
    border: 'border-[var(--acid-cyan)]',
    text: 'text-[var(--acid-cyan)]',
    icon: '\u{1F9EC}', // dna
  },
  crossover: {
    bg: 'bg-accent/20',
    border: 'border-accent',
    text: 'text-accent',
    icon: '\u{1F517}', // link
  },
  fitness_update: {
    bg: 'bg-acid-yellow/20',
    border: 'border-acid-yellow',
    text: 'text-[var(--acid-yellow)]',
    icon: '\u{1F4C8}', // chart
  },
  selection: {
    bg: 'bg-acid-magenta/20',
    border: 'border-acid-magenta',
    text: 'text-[var(--acid-magenta)]',
    icon: '\u{2705}', // check
  },
  extinction: {
    bg: 'bg-warning/20',
    border: 'border-warning',
    text: 'text-warning',
    icon: '\u{1F4A5}', // collision
  },
  speciation: {
    bg: 'bg-[var(--accent)]/20',
    border: 'border-[var(--accent)]',
    text: 'text-[var(--accent)]',
    icon: '\u{1F33F}', // seedling
  },
};

const DEFAULT_COLORS = {
  bg: 'bg-text-muted/20',
  border: 'border-text-muted',
  text: 'text-text-muted',
  icon: '\u{2022}', // bullet
};

function TimelineEvent({
  event,
  onClick,
  isSelected,
}: {
  event: GenesisEvent;
  onClick?: () => void;
  isSelected?: boolean;
}) {
  const colors = EVENT_COLORS[event.event_type] || DEFAULT_COLORS;
  const timestamp = new Date(event.timestamp);

  const getEventSummary = () => {
    const data = event.data;
    switch (event.event_type) {
      case 'agent_birth':
        return `New agent: ${data.agent_name || data.genome_id?.slice(0, 8) || 'unknown'}`;
      case 'agent_death':
        return `Agent retired: ${data.agent_name || data.genome_id?.slice(0, 8) || 'unknown'}`;
      case 'mutation':
        return `Mutation: ${data.mutation_type || 'standard'} on ${data.genome_id?.slice(0, 8) || 'unknown'}`;
      case 'crossover':
        return `Crossover: ${data.parent_ids?.length || 2} parents`;
      case 'fitness_update':
        const change =
          data.fitness_change ||
          (data.new_fitness && data.old_fitness ? data.new_fitness - data.old_fitness : 0);
        return `Fitness ${change >= 0 ? '+' : ''}${(change * 100).toFixed(1)}%`;
      case 'selection':
        return `Selection: ${data.strategy || 'tournament'}`;
      case 'extinction':
        return `Extinction event`;
      case 'speciation':
        return `New species emerged`;
      default:
        return event.event_type.replace(/_/g, ' ');
    }
  };

  return (
    <button
      onClick={onClick}
      className={`
        relative w-full text-left transition-all
        ${isSelected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg rounded-lg' : ''}
        group
      `}
    >
      {/* Timeline node */}
      <div className="flex items-start gap-4">
        {/* Timeline dot and line */}
        <div className="flex flex-col items-center">
          <div
            className={`
              w-10 h-10 rounded-full flex items-center justify-center text-lg
              ${colors.bg} ${colors.border} border-2
              group-hover:brightness-125 transition-all
            `}
          >
            {colors.icon}
          </div>
          <div className="w-0.5 h-full min-h-[20px] bg-[var(--accent)]/20" />
        </div>

        {/* Event content */}
        <div
          className={`
            flex-1 p-3 rounded-lg border mb-2
            ${colors.bg} ${colors.border}
            group-hover:brightness-110 transition-all
          `}
        >
          <div className="flex items-center justify-between mb-1">
            <span className={`font-theme-data text-xs uppercase ${colors.text}`}>
              {event.event_type.replace(/_/g, ' ')}
            </span>
            <span className="text-xs font-theme-data text-text-muted">
              {timestamp.toLocaleTimeString()}
            </span>
          </div>
          <div className="font-theme-data text-sm text-text">{getEventSummary()}</div>
          <div className="text-xs font-theme-data text-text-muted mt-1">
            {timestamp.toLocaleDateString()}
          </div>
        </div>
      </div>
    </button>
  );
}

export function EvolutionTimeline({
  apiBase = API_BASE_URL,
  limit = 50,
  eventTypeFilter,
  onEventClick,
  autoRefresh = false,
  refreshInterval = 30000,
}: EvolutionTimelineProps) {
  const [events, setEvents] = useState<GenesisEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<string | null>(null);
  const [filter, setFilter] = useState(eventTypeFilter || '');

  const fetchEvents = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: limit.toString() });
      if (filter) {
        params.append('event_type', filter);
      }

      const response = await fetch(`${apiBase}/api/genesis/events?${params}`);
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      const data = await response.json();
      setEvents(data.events || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch events');
    } finally {
      setLoading(false);
    }
  }, [apiBase, limit, filter]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  // Auto-refresh
  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchEvents, refreshInterval);
    return () => clearInterval(interval);
  }, [autoRefresh, refreshInterval, fetchEvents]);

  const handleEventClick = (event: GenesisEvent) => {
    setSelectedEventId(event.event_id);
    if (onEventClick) {
      onEventClick(event);
    }
  };

  // Group events by date
  const eventsByDate = useMemo(() => {
    const groups = new Map<string, GenesisEvent[]>();
    events.forEach((event) => {
      const date = new Date(event.timestamp).toDateString();
      if (!groups.has(date)) groups.set(date, []);
      groups.get(date)!.push(event);
    });
    return Array.from(groups.entries());
  }, [events]);

  // Get unique event types for filter
  const eventTypes = useMemo(() => {
    const types = new Set<string>();
    events.forEach((e) => types.add(e.event_type));
    return Array.from(types).sort();
  }, [events]);

  // Stats
  const stats = useMemo(() => {
    const typeCounts: Record<string, number> = {};
    let totalFitnessChange = 0;
    let fitnessUpdateCount = 0;

    events.forEach((e) => {
      typeCounts[e.event_type] = (typeCounts[e.event_type] || 0) + 1;
      if (e.event_type === 'fitness_update' && e.data.fitness_change !== undefined) {
        totalFitnessChange += e.data.fitness_change;
        fitnessUpdateCount++;
      }
    });

    return {
      typeCounts,
      avgFitnessChange: fitnessUpdateCount > 0 ? totalFitnessChange / fitnessUpdateCount : 0,
      totalEvents: events.length,
    };
  }, [events]);

  const selectedEvent = events.find((e) => e.event_id === selectedEventId);

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="font-theme-data text-[var(--accent)] text-sm">EVOLUTION TIMELINE</h4>
        <div className="flex items-center gap-2">
          {autoRefresh && (
            <span className="text-xs font-theme-data text-[var(--accent)] animate-pulse">LIVE</span>
          )}
          <button
            onClick={fetchEvents}
            disabled={loading}
            className="px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10 transition-colors disabled:opacity-50"
          >
            {loading ? 'LOADING...' : 'REFRESH'}
          </button>
        </div>
      </div>

      {/* Stats bar */}
      <div className="flex flex-wrap gap-4 p-3 bg-surface/50 border border-border rounded-lg">
        <div>
          <span className="text-xs font-theme-data text-text-muted">Total Events</span>
          <div className="text-lg font-theme-data text-[var(--accent)]">{stats.totalEvents}</div>
        </div>
        <div>
          <span className="text-xs font-theme-data text-text-muted">Avg Fitness Change</span>
          <div
            className={`text-lg font-theme-data ${stats.avgFitnessChange >= 0 ? 'text-[var(--accent)]' : 'text-acid-red'}`}
          >
            {stats.avgFitnessChange >= 0 ? '+' : ''}
            {(stats.avgFitnessChange * 100).toFixed(2)}%
          </div>
        </div>
        {Object.entries(stats.typeCounts)
          .slice(0, 4)
          .map(([type, count]) => (
            <div key={type}>
              <span className="text-xs font-theme-data text-text-muted capitalize">
                {type.replace(/_/g, ' ')}
              </span>
              <div className="text-lg font-theme-data text-text">{count}</div>
            </div>
          ))}
      </div>

      {/* Filter */}
      <div className="flex gap-2">
        <label htmlFor="event-type-filter" className="sr-only">
          Filter by event type
        </label>
        <select
          id="event-type-filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          aria-label="Filter by event type"
          className="bg-bg border border-[var(--accent)]/30 px-3 py-2 font-theme-data text-sm text-text focus:border-[var(--accent)] focus:outline-none"
        >
          <option value="">All Event Types</option>
          {eventTypes.map((type) => (
            <option key={type} value={type}>
              {type.replace(/_/g, ' ').toUpperCase()}
            </option>
          ))}
        </select>
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 bg-warning/10 border border-warning/30 rounded-lg">
          <div className="text-warning font-theme-data text-sm">{error}</div>
        </div>
      )}

      {/* Timeline */}
      <div className="grid lg:grid-cols-3 gap-6">
        {/* Event list */}
        <div className="lg:col-span-2 space-y-1 max-h-[600px] overflow-y-auto">
          {loading && events.length === 0 && (
            <div className="text-center py-8">
              <div className="text-[var(--accent)] font-theme-data animate-pulse">
                Loading timeline...
              </div>
            </div>
          )}

          {!loading && events.length === 0 && (
            <div className="text-center py-8 border border-[var(--accent)]/20 rounded-lg bg-surface/50">
              <div className="text-text-muted font-theme-data text-sm">
                No evolution events found
              </div>
            </div>
          )}

          {eventsByDate.map(([date, dateEvents]) => (
            <div key={date}>
              <div className="text-xs font-theme-data text-[var(--acid-cyan)] mb-2 mt-4 first:mt-0 sticky top-0 bg-bg/90 py-1">
                {date}
              </div>
              {dateEvents.map((event) => (
                <TimelineEvent
                  key={event.event_id}
                  event={event}
                  onClick={() => handleEventClick(event)}
                  isSelected={selectedEventId === event.event_id}
                />
              ))}
            </div>
          ))}
        </div>

        {/* Selected event details */}
        <div className="bg-surface border border-[var(--acid-cyan)]/30 rounded-lg p-4 h-fit sticky top-4">
          <h5 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-4">EVENT DETAILS</h5>
          {selectedEvent ? (
            <div className="space-y-4">
              <div>
                <div className="text-xs text-text-muted mb-1">EVENT ID</div>
                <div className="font-theme-data text-xs text-[var(--accent)] break-all">
                  {selectedEvent.event_id}
                </div>
              </div>

              <div>
                <div className="text-xs text-text-muted mb-1">TYPE</div>
                <div
                  className={`font-theme-data text-sm uppercase ${EVENT_COLORS[selectedEvent.event_type]?.text || 'text-text'}`}
                >
                  {selectedEvent.event_type.replace(/_/g, ' ')}
                </div>
              </div>

              <div>
                <div className="text-xs text-text-muted mb-1">TIMESTAMP</div>
                <div className="font-theme-data text-sm text-text">
                  {new Date(selectedEvent.timestamp).toLocaleString()}
                </div>
              </div>

              {selectedEvent.parent_event_id && (
                <div>
                  <div className="text-xs text-text-muted mb-1">PARENT EVENT</div>
                  <div className="font-theme-data text-xs text-text-muted">
                    {selectedEvent.parent_event_id.slice(0, 16)}...
                  </div>
                </div>
              )}

              {selectedEvent.content_hash && (
                <div>
                  <div className="text-xs text-text-muted mb-1">CONTENT HASH</div>
                  <div className="font-theme-data text-xs text-text-muted">
                    {selectedEvent.content_hash}
                  </div>
                </div>
              )}

              <div>
                <div className="text-xs text-text-muted mb-1">DATA</div>
                <pre className="font-theme-data text-xs text-text bg-bg/50 p-2 rounded overflow-x-auto max-h-48">
                  {JSON.stringify(selectedEvent.data, null, 2)}
                </pre>
              </div>
            </div>
          ) : (
            <div className="text-center text-text-muted font-theme-data text-sm py-8">
              Select an event to view details
            </div>
          )}
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-4 text-xs font-theme-data pt-4 border-t border-border">
        {Object.entries(EVENT_COLORS).map(([type, colors]) => (
          <div key={type} className="flex items-center gap-2">
            <div
              className={`w-6 h-6 rounded-full flex items-center justify-center text-sm ${colors.bg} ${colors.border} border`}
            >
              {colors.icon}
            </div>
            <span className="text-text-muted capitalize">{type.replace(/_/g, ' ')}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default EvolutionTimeline;
