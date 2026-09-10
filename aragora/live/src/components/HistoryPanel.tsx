'use client';

import { useSupabaseHistory } from '@/hooks/useSupabaseHistory';
import { useLocalHistory } from '@/hooks/useLocalHistory';
import { PanelHeader, StatsGrid } from './shared';
import { getSupabaseWarning } from '@/utils/supabase';
import { API_BASE_URL } from '@/config';

const DEFAULT_API_BASE = API_BASE_URL;

function formatLoopId(loopId: string): string {
  // nomic-20260102-091500 -> Jan 2, 09:15
  const match = loopId.match(/nomic-(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})/);
  if (match) {
    const [, year, month, day, hour, minute] = match;
    const date = new Date(
      parseInt(year),
      parseInt(month) - 1,
      parseInt(day),
      parseInt(hour),
      parseInt(minute),
    );
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }
  return loopId;
}

export function HistoryPanel() {
  const supabaseHistory = useSupabaseHistory();
  const localHistory = useLocalHistory(DEFAULT_API_BASE);

  // Use Supabase if configured, otherwise fall back to local API
  const useSupabase = supabaseHistory.isConfigured;

  const isLoading = useSupabase ? supabaseHistory.isLoading : localHistory.isLoading;
  const error = useSupabase ? supabaseHistory.error : localHistory.error;
  const cycles = useSupabase ? supabaseHistory.cycles : localHistory.cycles;
  const events = useSupabase ? supabaseHistory.events : localHistory.events;
  const debates = useSupabase ? supabaseHistory.debates : localHistory.debates;
  const refresh = useSupabase ? supabaseHistory.refresh : localHistory.refresh;

  // Only for Supabase mode
  const { recentLoops, selectedLoopId, selectLoop } = supabaseHistory;

  const stats = [
    { value: cycles.length, label: 'Cycles', color: 'text-[var(--acid-cyan)]' },
    { value: events.length, label: 'Events', color: 'text-[var(--accent)]' },
    { value: debates.length, label: 'Debates', color: 'text-purple' },
  ];

  // Get Supabase warning if not configured
  const supabaseWarning = getSupabaseWarning();

  return (
    <div className="panel">
      <PanelHeader title="History" loading={isLoading} onRefresh={refresh} />

      {/* Show warning when Supabase not configured */}
      {supabaseWarning && !useSupabase && (
        <div
          className="mb-4 p-2 bg-yellow-900/20 border border-yellow-600/50 text-yellow-200 text-xs font-theme-data"
          role="alert"
        >
          <span className="text-yellow-300">!</span> {supabaseWarning}
        </div>
      )}

      {error && (
        <div className="mb-4 p-2 bg-[var(--crimson)]/10 border border-[var(--crimson)] text-[var(--crimson)] text-xs font-theme-data">
          {error}
        </div>
      )}

      {/* Loop selector - only for Supabase mode */}
      {useSupabase && (
        <div className="mb-4">
          <label
            htmlFor="loop-selector"
            className="text-xs text-text-muted block mb-1 font-theme-data"
          >
            SELECT_LOOP
          </label>
          <select
            id="loop-selector"
            value={selectedLoopId || ''}
            onChange={(e) => selectLoop(e.target.value)}
            className="w-full bg-bg border border-border px-2 py-1 text-sm font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
          >
            {recentLoops.length === 0 && <option value="">No loops found</option>}
            {recentLoops.map((loopId) => (
              <option key={loopId} value={loopId}>
                {formatLoopId(loopId)}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Local API summary */}
      {!useSupabase && localHistory.summary && (
        <div className="mb-4 p-2 bg-bg border border-border text-xs font-theme-data text-text-muted">
          <span className="text-[var(--accent)]">&gt;</span> Using local API
          {localHistory.summary.recent_loop_id && (
            <span className="ml-2 text-text">
              • {formatLoopId(localHistory.summary.recent_loop_id)}
            </span>
          )}
        </div>
      )}

      {/* Stats */}
      {(useSupabase ? selectedLoopId : true) && (
        <StatsGrid stats={stats} columns={3} className="mb-4" />
      )}

      {/* Cycles list */}
      {cycles.length > 0 && (
        <div className="mb-4">
          <h4 id="phases-heading" className="text-xs font-theme-data text-text-muted mb-2">
            PHASES
          </h4>
          <div
            role="list"
            aria-labelledby="phases-heading"
            className="space-y-1 max-h-40 overflow-y-auto"
          >
            {cycles.map((cycle) => (
              <div
                key={cycle.id}
                role="listitem"
                aria-label={`Cycle ${cycle.cycle_number}: ${cycle.phase}, status: ${cycle.success === true ? 'success' : cycle.success === false ? 'failed' : 'in progress'}`}
                className="flex items-center justify-between text-xs font-theme-data bg-bg border border-border px-2 py-1"
              >
                <span className="text-text">
                  C{cycle.cycle_number}: {cycle.phase}
                </span>
                <span
                  className={
                    cycle.success === true
                      ? 'text-[var(--accent)]'
                      : cycle.success === false
                        ? 'text-[var(--crimson)]'
                        : 'text-warning'
                  }
                  aria-hidden="true"
                >
                  {cycle.success === true ? '[OK]' : cycle.success === false ? '[FAIL]' : '[...]'}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent events */}
      {events.length > 0 && (
        <div>
          <h4 id="events-heading" className="text-xs font-theme-data text-text-muted mb-2">
            EVENTS ({events.length})
          </h4>
          <div
            role="log"
            aria-labelledby="events-heading"
            aria-live="polite"
            className="space-y-1 max-h-40 overflow-y-auto text-xs font-theme-data"
          >
            {events.slice(-100).map((event) => (
              <div
                key={event.id}
                className="text-text-muted truncate"
                title={JSON.stringify(event.event_data)}
              >
                <span className="text-text-muted opacity-50">
                  {new Date(event.timestamp).toLocaleTimeString()}
                </span>{' '}
                <span className="text-[var(--acid-cyan)]">{event.event_type}</span>
                {event.agent && <span className="text-purple"> [{event.agent}]</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Debates preview */}
      {debates.length > 0 && (
        <div className="mt-4">
          <h4 id="debates-heading" className="text-xs font-theme-data text-text-muted mb-2">
            DEBATES
          </h4>
          <div
            role="list"
            aria-labelledby="debates-heading"
            className="space-y-2 max-h-40 overflow-y-auto"
          >
            {debates.map((debate) => (
              <article
                key={debate.id}
                role="listitem"
                aria-label={`${debate.phase} debate in cycle ${debate.cycle_number}, ${debate.consensus_reached ? `consensus reached with ${(debate.confidence * 100).toFixed(0)}% confidence` : 'no consensus'}`}
                className="bg-bg border border-border p-2 text-xs font-theme-data"
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="text-text">
                    {debate.phase} (C{debate.cycle_number})
                  </span>
                  <span
                    className={debate.consensus_reached ? 'text-[var(--accent)]' : 'text-warning'}
                    aria-hidden="true"
                  >
                    {debate.consensus_reached
                      ? `[${(debate.confidence * 100).toFixed(0)}%]`
                      : '[NO_CONSENSUS]'}
                  </span>
                </div>
                <div className="text-text-muted truncate" title={debate.task}>
                  {debate.task}
                </div>
                <div className="text-text-muted opacity-50 mt-1">
                  agents: {debate.agents.join(', ')}
                </div>
              </article>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
