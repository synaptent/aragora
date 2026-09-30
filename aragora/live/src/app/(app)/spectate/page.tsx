'use client';

import { useEffect, useMemo } from 'react';
import Link from 'next/link';
import { ThemeEffects } from '@/components/ThemeEffects';
import { useRightSidebar } from '@/context/RightSidebarContext';
import { useSpectate, type SpectateEvent, type SpectateStatus } from '@/hooks/useSpectate';

type BridgeState =
  SpectateStatus['bridge_state'] | 'checking' | 'status_unavailable' | 'unreachable';

function EventTypeIcon({ eventType }: { eventType: string }) {
  const icons: Record<string, string> = {
    proposal: '$',
    critique: '!',
    vote: '#',
    consensus: '*',
    round_start: '>',
    round_end: '<',
    agent_message: '@',
  };
  return <span>{icons[eventType] || '>'}</span>;
}

function toEpochMs(timestamp: string | null | undefined): number | null {
  if (!timestamp) return null;
  const parsed = Date.parse(timestamp);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatRelativeAge(timestamp: string | null | undefined): string {
  const epochMs = toEpochMs(timestamp);
  if (epochMs === null) return '—';

  const ageSeconds = Math.max(0, Math.round((Date.now() - epochMs) / 1000));
  if (ageSeconds < 60) return `${ageSeconds}s ago`;

  const ageMinutes = Math.round(ageSeconds / 60);
  if (ageMinutes < 60) return `${ageMinutes}m ago`;

  const ageHours = Math.round(ageMinutes / 60);
  if (ageHours < 24) return `${ageHours}h ago`;

  const ageDays = Math.round(ageHours / 24);
  return `${ageDays}d ago`;
}

function getBridgeState(
  loaded: boolean,
  connected: boolean,
  status: SpectateStatus | null,
): BridgeState {
  if (!loaded) return 'checking';
  if (status) return status.bridge_state;
  return connected ? 'status_unavailable' : 'unreachable';
}

function getBridgeLabel(state: BridgeState): string {
  switch (state) {
    case 'live_debates_available':
      return 'LIVE';
    case 'activity_unattributed':
      return 'PARTIAL';
    case 'idle':
      return 'IDLE';
    case 'inactive':
      return 'OFF';
    case 'status_unavailable':
      return 'STATUS UNKNOWN';
    case 'unreachable':
      return 'API OFFLINE';
    case 'checking':
    default:
      return 'CHECKING';
  }
}

function getBridgeTone(state: BridgeState): string {
  switch (state) {
    case 'live_debates_available':
      return 'bg-[var(--accent)]/10 text-[var(--accent)] border-[var(--accent)]/30';
    case 'activity_unattributed':
    case 'status_unavailable':
      return 'bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30';
    case 'idle':
    case 'checking':
      return 'bg-[var(--acid-yellow)]/10 text-[var(--acid-yellow)] border-[var(--acid-yellow)]/30';
    case 'inactive':
    case 'unreachable':
    default:
      return 'bg-[var(--crimson)]/10 text-[var(--crimson)] border-[var(--crimson)]/30';
  }
}

function getReadinessTitle(state: BridgeState): string {
  switch (state) {
    case 'live_debates_available':
      return 'Live debate IDs are available from the spectate bridge.';
    case 'activity_unattributed':
      return 'Recent bridge activity is visible, but it is not linked to a debate ID yet.';
    case 'idle':
      return 'The spectate bridge is running, but no recent debate activity is visible.';
    case 'inactive':
      return 'The spectate bridge is installed but currently inactive.';
    case 'status_unavailable':
      return 'Recent events are reachable, but bridge readiness details are unavailable.';
    case 'unreachable':
      return 'The spectate API is unreachable from this surface right now.';
    case 'checking':
    default:
      return 'Checking live debate availability and bridge readiness…';
  }
}

function getReadinessBody(
  state: BridgeState,
  discoverableDebates: number,
  unattributedRecentEvents: number,
): string {
  switch (state) {
    case 'live_debates_available':
      return `${discoverableDebates} debate ID${discoverableDebates === 1 ? '' : 's'} can be opened from this surface.`;
    case 'activity_unattributed':
      return `${unattributedRecentEvents} recent event${unattributedRecentEvents === 1 ? '' : 's'} arrived without a debate ID, so this page stays partial instead of fabricating a live debate list.`;
    case 'idle':
      return 'Nothing recent is being surfaced by the live bridge, so the page does not claim a debate is in progress.';
    case 'inactive':
      return 'Turn on the bridge before expecting this page to reflect live debate readiness.';
    case 'status_unavailable':
      return 'This page only trusts explicit bridge status before showing live readiness details.';
    case 'unreachable':
      return 'No bridge facts can be confirmed until the spectate endpoints respond again.';
    case 'checking':
    default:
      return 'The page will only surface debate links once live activity is observed and attributed.';
  }
}

function getEmptyStateTitle(state: BridgeState): string {
  switch (state) {
    case 'inactive':
      return 'Spectate Bridge Offline';
    case 'idle':
      return 'No Recent Debate Activity';
    case 'status_unavailable':
      return 'Bridge Status Unavailable';
    case 'unreachable':
      return 'Spectate API Unreachable';
    case 'checking':
      return 'Scanning Spectate Bridge';
    default:
      return 'No Discoverable Live Debates';
  }
}

function getEmptyStateBody(state: BridgeState): string {
  switch (state) {
    case 'inactive':
      return 'This surface cannot confirm live debate readiness until the spectate bridge is active.';
    case 'idle':
      return 'The bridge is up, but it has not observed recent live debate events within the current readiness window.';
    case 'status_unavailable':
      return 'Bridge status did not load, so this page avoids presenting debate links as live.';
    case 'unreachable':
      return 'The spectate endpoints did not respond, so no live readiness claim is shown.';
    case 'checking':
      return 'Waiting for the first readiness snapshot…';
    default:
      return 'Only debate IDs seen in recent bridge events are listed here.';
  }
}

function isRecentEvent(event: SpectateEvent, windowSeconds: number): boolean {
  const epochMs = toEpochMs(event.timestamp);
  if (epochMs === null) return false;
  return Date.now() - epochMs <= windowSeconds * 1000;
}

export default function SpectatePage() {
  const { setContext, clearContext } = useRightSidebar();
  const {
    events: spectateEvents,
    connected: spectateConnected,
    loaded: spectateLoaded,
    status: spectateStatus,
  } = useSpectate(undefined, undefined, { pollInterval: 3000 });

  const bridgeState = getBridgeState(spectateLoaded, spectateConnected, spectateStatus);
  const activityWindowSeconds = spectateStatus?.recent_activity_window_seconds ?? 120;

  const recentBridgeEvents = useMemo(
    () => spectateEvents.filter((event) => isRecentEvent(event, activityWindowSeconds)),
    [activityWindowSeconds, spectateEvents],
  );

  const fallbackDiscoverableDebates = useMemo(() => {
    const grouped = new Map<
      string,
      {
        debate_id: string;
        recent_event_count: number;
        last_event_at: string | null;
        event_types: Set<string>;
      }
    >();

    for (const event of recentBridgeEvents) {
      if (!event.debate_id) continue;

      const existing = grouped.get(event.debate_id);
      if (!existing) {
        grouped.set(event.debate_id, {
          debate_id: event.debate_id,
          recent_event_count: 1,
          last_event_at: event.timestamp,
          event_types: new Set([event.event_type]),
        });
        continue;
      }

      existing.recent_event_count += 1;
      existing.event_types.add(event.event_type);

      const existingTs = toEpochMs(existing.last_event_at);
      const eventTs = toEpochMs(event.timestamp);
      if (eventTs !== null && (existingTs === null || eventTs >= existingTs)) {
        existing.last_event_at = event.timestamp;
      }
    }

    return Array.from(grouped.values())
      .map((debate) => ({
        debate_id: debate.debate_id,
        recent_event_count: debate.recent_event_count,
        last_event_at: debate.last_event_at,
        event_types: Array.from(debate.event_types).sort(),
      }))
      .sort(
        (left, right) =>
          (toEpochMs(right.last_event_at) ?? 0) - (toEpochMs(left.last_event_at) ?? 0),
      );
  }, [recentBridgeEvents]);

  const discoverableDebates = spectateStatus?.live_debates ?? fallbackDiscoverableDebates;
  const recentEventCount = spectateStatus?.recent_event_count ?? recentBridgeEvents.length;
  const unattributedRecentEvents =
    spectateStatus?.unattributed_recent_event_count ??
    recentBridgeEvents.filter((event) => !event.debate_id).length;

  useEffect(() => {
    setContext({
      title: 'Spectate Mode',
      subtitle: 'Truthful live readiness',
      statsContent: (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Bridge</span>
            <span
              className={`text-sm font-theme-data ${
                bridgeState === 'live_debates_available'
                  ? 'text-[var(--accent)]'
                  : bridgeState === 'activity_unattributed' || bridgeState === 'status_unavailable'
                    ? 'text-[var(--acid-cyan)]'
                    : bridgeState === 'idle' || bridgeState === 'checking'
                      ? 'text-[var(--acid-yellow)]'
                      : 'text-[var(--crimson)]'
              }`}
            >
              {getBridgeLabel(bridgeState)}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Discoverable Debates</span>
            <span className="text-sm font-theme-data text-[var(--accent)]">
              {discoverableDebates.length}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Recent Events</span>
            <span className="text-sm font-theme-data text-[var(--acid-cyan)]">
              {recentEventCount}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Last Activity</span>
            <span className="text-sm font-theme-data text-[var(--text)]">
              {formatRelativeAge(spectateStatus?.last_event_at)}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Buffered Events</span>
            <span className="text-sm font-theme-data text-[var(--text)]">
              {spectateStatus?.buffer_size ?? spectateEvents.length}
            </span>
          </div>
        </div>
      ),
      actionsContent: (
        <div className="space-y-2">
          <Link
            href="/arena"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center btn-theme-primary"
          >
            + START DEBATE
          </Link>
          <Link
            href="/debates"
            className="block w-full px-3 py-2 text-xs font-theme-data text-center btn-theme-secondary"
          >
            VIEW ARCHIVE
          </Link>
        </div>
      ),
    });

    return () => clearContext();
  }, [
    bridgeState,
    clearContext,
    discoverableDebates.length,
    recentEventCount,
    setContext,
    spectateEvents.length,
    spectateStatus?.buffer_size,
    spectateStatus?.last_event_at,
  ]);

  return (
    <>
      <ThemeEffects opacity={0.02} />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="max-w-6xl mx-auto px-4 py-8">
          {/* Header */}
          <div className="mb-8">
            <div className="flex items-center gap-3 mb-2">
              <div
                className={`w-3 h-3 rounded-full ${
                  bridgeState === 'live_debates_available'
                    ? 'bg-[var(--accent)] animate-pulse'
                    : bridgeState === 'activity_unattributed'
                      ? 'bg-[var(--acid-cyan)] animate-pulse'
                      : bridgeState === 'idle' || bridgeState === 'checking'
                        ? 'bg-[var(--acid-yellow)] animate-pulse'
                        : 'bg-[var(--crimson)]'
                }`}
              />
              <h1 className="text-2xl font-theme-heading text-[var(--accent)]">Spectate Mode</h1>
              <span className={`badge-theme ${getBridgeTone(bridgeState)}`}>
                {getBridgeLabel(bridgeState)}
              </span>
            </div>
            <p className="text-[var(--text-muted)] text-sm">
              Watch only what the live bridge can actually confirm.
            </p>
          </div>

          {/* Bridge Readiness Panel */}
          <div className="card-theme-info p-4 mb-6">
            <div className="flex items-start justify-between gap-4 flex-col sm:flex-row">
              <div>
                <h2 className="text-sm font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider mb-2">
                  Bridge Readiness
                </h2>
                <p className="text-sm text-[var(--text)] mb-2">{getReadinessTitle(bridgeState)}</p>
                <p className="text-xs text-[var(--text-muted)] max-w-3xl">
                  {getReadinessBody(
                    bridgeState,
                    discoverableDebates.length,
                    unattributedRecentEvents,
                  )}
                </p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs font-theme-data min-w-[240px]">
                <div className="card-theme px-3 py-2">
                  <div className="text-[var(--text-muted)] mb-1">Bridge State</div>
                  <div className="text-[var(--accent)] break-words">
                    {getBridgeLabel(bridgeState)}
                  </div>
                </div>
                <div className="card-theme px-3 py-2">
                  <div className="text-[var(--text-muted)] mb-1">Last Event</div>
                  <div className="text-[var(--acid-cyan)]">
                    {formatRelativeAge(spectateStatus?.last_event_at)}
                  </div>
                </div>
                <div className="card-theme px-3 py-2">
                  <div className="text-[var(--text-muted)] mb-1">Recent Events</div>
                  <div className="text-[var(--accent)]">{recentEventCount}</div>
                </div>
                <div className="card-theme px-3 py-2">
                  <div className="text-[var(--text-muted)] mb-1">Debate IDs</div>
                  <div className="text-[var(--acid-cyan)]">{discoverableDebates.length}</div>
                </div>
              </div>
            </div>
          </div>

          {/* Loading State */}
          {!spectateLoaded && (
            <div className="card-theme p-8 text-center mb-6">
              <div className="w-8 h-8 border-2 border-[var(--accent)]/30 border-t-[var(--accent)] rounded-full animate-spin mx-auto mb-4" />
              <p className="text-[var(--text-muted)] text-sm">Checking live bridge readiness...</p>
            </div>
          )}

          {/* Discoverable Debates Grid */}
          {spectateLoaded && discoverableDebates.length > 0 && (
            <div className="space-y-4 mb-6">
              <h2 className="text-sm font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider">
                Discoverable Live Debates ({discoverableDebates.length})
              </h2>

              <div className="grid gap-4">
                {discoverableDebates.map((debate) => (
                  <Link
                    key={debate.debate_id}
                    href={`/spectate/${debate.debate_id}`}
                    className="block card-theme p-4 hover:border-[var(--accent)]/60 transition-all group"
                  >
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="text-xs font-theme-data text-[var(--text-muted)] mb-2">
                          Debate ID
                        </div>
                        <h3 className="text-sm font-theme-data text-[var(--text)] break-all group-hover:text-[var(--accent)] transition-colors">
                          {debate.debate_id}
                        </h3>
                        <div className="flex flex-wrap gap-2 mt-3">
                          {debate.event_types.map((eventType) => (
                            <span
                              key={`${debate.debate_id}-${eventType}`}
                              className="badge-theme inline-flex items-center gap-1 bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30"
                            >
                              <EventTypeIcon eventType={eventType} />
                              {eventType}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div className="flex flex-col items-end gap-1 text-xs font-theme-data">
                        <div className="flex items-center gap-2">
                          <span className="text-[var(--text-muted)]">Recent Events</span>
                          <span className="text-[var(--accent)]">{debate.recent_event_count}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <span className="text-[var(--text-muted)]">Last Seen</span>
                          <span className="text-[var(--acid-cyan)]">
                            {formatRelativeAge(debate.last_event_at)}
                          </span>
                        </div>
                        <div className="flex items-center gap-1 text-[var(--accent)]">
                          <div className="w-2 h-2 bg-[var(--accent)] rounded-full animate-pulse" />
                          OPEN FEED
                        </div>
                      </div>
                    </div>
                  </Link>
                ))}
              </div>
            </div>
          )}

          {/* Partial Readiness Warning */}
          {spectateLoaded &&
            bridgeState === 'activity_unattributed' &&
            discoverableDebates.length === 0 && (
              <div
                className="border border-[var(--acid-yellow)]/30 bg-[var(--acid-yellow)]/10 p-4 mb-6"
                style={{ borderRadius: 'var(--radius-card, 6px)' }}
              >
                <h2 className="text-sm font-theme-data text-[var(--acid-yellow)] mb-2">
                  Partial Readiness
                </h2>
                <p className="text-xs text-[var(--text-muted)]">
                  Recent bridge activity is flowing, but the current events are not tagged with a
                  debate ID. This surface stays honest and does not invent clickable live debates
                  until attribution is present.
                </p>
              </div>
            )}

          {/* Recent Bridge Event Feed */}
          {spectateLoaded && recentBridgeEvents.length > 0 && (
            <div className="mt-6 space-y-4">
              <h2 className="text-sm font-theme-data text-[var(--acid-cyan)] uppercase tracking-wider">
                Recent Bridge Event Feed ({recentBridgeEvents.length} events)
              </h2>
              <div className="card-theme divide-y divide-[var(--border)] max-h-[400px] overflow-y-auto">
                {recentBridgeEvents
                  .slice(-20)
                  .reverse()
                  .map((event, index) => {
                    const details =
                      typeof event.data.details === 'string' ? event.data.details : null;

                    return (
                      <div
                        key={`${event.timestamp}-${index}`}
                        className="px-4 py-2 flex items-start gap-3 text-xs font-theme-data hover:bg-[var(--surface-elevated)] transition-colors"
                      >
                        <span className="text-[var(--accent)] mt-0.5">
                          <EventTypeIcon eventType={event.event_type} />
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-[var(--acid-cyan)]">{event.event_type}</span>
                            {event.agent_name && (
                              <span className="text-[var(--text-muted)]">
                                by {event.agent_name}
                              </span>
                            )}
                            {event.round_number != null && (
                              <span className="text-[var(--text-muted)]">
                                R{event.round_number}
                              </span>
                            )}
                          </div>
                          {details && (
                            <span className="text-[var(--text-muted)]/80 truncate block">
                              {details}
                            </span>
                          )}
                          {event.debate_id && (
                            <span className="text-[var(--text-muted)]/60 truncate block">
                              debate: {event.debate_id}
                            </span>
                          )}
                        </div>
                        <span className="text-[var(--text-muted)]/40 flex-shrink-0">
                          {new Date(event.timestamp).toLocaleTimeString()}
                        </span>
                      </div>
                    );
                  })}
              </div>
            </div>
          )}

          {/* Empty State */}
          {spectateLoaded &&
            discoverableDebates.length === 0 &&
            recentBridgeEvents.length === 0 && (
              <div className="card-theme p-8 text-center">
                <div className="text-4xl mb-4">👁️</div>
                <h2 className="text-lg font-theme-heading text-[var(--accent)] mb-2">
                  {getEmptyStateTitle(bridgeState)}
                </h2>
                <p className="text-[var(--text-muted)] text-sm mb-6 max-w-md mx-auto">
                  {getEmptyStateBody(bridgeState)}
                </p>
                <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
                  <Link href="/arena" className="px-6 py-2 btn-theme-primary">
                    START DEBATE
                  </Link>
                  <Link href="/debates" className="px-6 py-2 btn-theme-secondary">
                    VIEW ARCHIVE
                  </Link>
                </div>
              </div>
            )}

          {/* About Section */}
          <div className="mt-8 card-theme-info p-4">
            <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] mb-2">
              About Spectate Mode
            </h3>
            <ul className="text-xs text-[var(--text-muted)] space-y-1">
              <li>
                • This page only lists debates that appear in recent bridge events with a debate ID.
              </li>
              <li>
                • If activity is real but unattributed, the surface stays partial instead of
                inventing a live card.
              </li>
              <li>• Recent bridge status is shown separately from the raw event feed.</li>
              <li>• Read-only: spectators cannot influence debates.</li>
              <li>• Use the archive when no live debate is currently discoverable.</li>
            </ul>
          </div>
        </div>
      </main>
    </>
  );
}
