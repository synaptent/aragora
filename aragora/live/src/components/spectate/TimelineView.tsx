'use client';

import { useSpectateStore, EVENT_STYLES, type SpectatorEvent } from '@/store/spectateStore';

/**
 * Round-based timeline view for spectating debates.
 * Groups events by round and shows agent activity within each round.
 */
export function TimelineView() {
  const events = useSpectateStore((s) => s.events);
  const currentRound = useSpectateStore((s) => s.currentRound);
  const agents = useSpectateStore((s) => s.agents);

  // Group events by round (null round goes into round 0)
  const rounds = new Map<number, SpectatorEvent[]>();
  for (const event of events) {
    const r = event.round ?? 0;
    const list = rounds.get(r) || [];
    list.push(event);
    rounds.set(r, list);
  }

  const sortedRounds = [...rounds.keys()].sort((a, b) => a - b);

  if (events.length === 0) {
    return (
      <div className="flex items-center justify-center h-[500px]">
        <div className="text-center text-text-muted">
          <div className="w-8 h-8 border-2 border-accent/30 border-t-accent rounded-full animate-spin mx-auto mb-4" />
          <p className="font-theme-data text-sm">Waiting for events...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-4">
      {/* Agent Legend */}
      {agents.length > 0 && (
        <div className="flex flex-wrap gap-2 pb-4 border-b border-border">
          {agents.map((agent) => (
            <span
              key={agent}
              className="px-2 py-1 text-xs font-theme-data bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30"
            >
              {agent}
            </span>
          ))}
        </div>
      )}

      {/* Round Timeline */}
      {sortedRounds.map((roundNum) => {
        const roundEvents = rounds.get(roundNum) || [];
        const isCurrentRound = roundNum === currentRound;

        // Collect per-agent activity in this round
        const agentActivity = new Map<string, SpectatorEvent[]>();
        for (const ev of roundEvents) {
          if (ev.agent) {
            const list = agentActivity.get(ev.agent) || [];
            list.push(ev);
            agentActivity.set(ev.agent, list);
          }
        }

        return (
          <div key={roundNum} className="relative">
            {/* Round Header */}
            <div className="flex items-center gap-3 mb-3">
              <div
                className={`w-8 h-8 flex items-center justify-center text-xs font-theme-data font-bold border ${
                  isCurrentRound
                    ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-[var(--accent)]/50'
                    : 'bg-surface text-text-muted border-border'
                }`}
              >
                R{roundNum}
              </div>
              <div className="flex-1 h-px bg-border" />
              {isCurrentRound && (
                <span className="text-xs font-theme-data text-[var(--accent)] animate-pulse">
                  ACTIVE
                </span>
              )}
              <span className="text-[10px] font-theme-data text-text-muted">
                {roundEvents.length} events
              </span>
            </div>

            {/* Agent Swim Lanes */}
            <div className="ml-11 space-y-2">
              {/* System events (no agent) */}
              {roundEvents
                .filter((ev) => !ev.agent)
                .map((ev, i) => {
                  const style = EVENT_STYLES[ev.type] || {
                    icon: '.',
                    color: 'text-text-muted',
                    label: 'UNKNOWN',
                  };
                  return (
                    <div
                      key={`sys-${i}`}
                      className="flex items-center gap-2 text-xs font-theme-data py-1 px-2 bg-surface/50 border-l-2 border-text-muted/30"
                    >
                      <span>{style.icon}</span>
                      <span className={style.color}>{style.label}</span>
                      {ev.details && <span className="text-text-muted truncate">{ev.details}</span>}
                    </div>
                  );
                })}

              {/* Per-agent lanes */}
              {[...agentActivity.entries()].map(([agent, agentEvents]) => (
                <div key={agent} className="border-l-2 border-[var(--acid-cyan)]/30 pl-3 py-1">
                  <div className="text-xs font-theme-data text-[var(--acid-cyan)] font-bold mb-1">
                    {agent}
                  </div>
                  <div className="flex flex-wrap gap-1">
                    {agentEvents.map((ev, i) => {
                      const style = EVENT_STYLES[ev.type] || {
                        icon: '.',
                        color: 'text-text-muted',
                        label: 'UNKNOWN',
                      };
                      return (
                        <div
                          key={i}
                          className="group relative flex items-center gap-1 px-2 py-1 card-theme hover:border-accent/30 transition-colors"
                          title={ev.details || style.label}
                        >
                          <span className="text-xs">{style.icon}</span>
                          <span className={`text-[10px] font-theme-data ${style.color}`}>
                            {style.label}
                          </span>
                          {ev.metric !== null && (
                            <span className="text-[10px] font-theme-data text-text-muted">
                              ({ev.metric.toFixed(2)})
                            </span>
                          )}
                          {/* Tooltip */}
                          {ev.details && (
                            <div className="absolute left-0 bottom-full mb-1 hidden group-hover:block z-10 max-w-xs">
                              <div className="bg-bg border border-border p-2 text-xs font-theme-data text-text shadow-lg">
                                {ev.details}
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
