'use client';

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import Link from 'next/link';
import { WS_URL } from '@/config';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */

interface PublicSpectateEvent {
  event_type: string;
  timestamp: string;
  data: Record<string, unknown>;
  debate_id: string | null;
  pipeline_id: string | null;
  agent_name: string | null;
  round_number: number | null;
}

interface PublicSpectateStatus {
  active: boolean;
  recent_activity_window_seconds?: number;
  recent_event_count?: number;
  last_event_at?: string | null;
}

interface LiveDebateSummary {
  debateId: string;
  task: string | null;
  agents: string[];
  lastEventAt: string | null;
  recentEventCount: number;
}

interface LivePreviewEvent {
  id: string;
  eventType: string;
  timestampMs: number;
  timeLabel: string;
  agent: string | null;
  roundNumber: number | null;
  body: string;
}

interface SpectateSocketMessage {
  type: string;
  timestamp?: number;
  agent?: string | null;
  details?: string | null;
  round?: number | null;
  task?: string;
  agents?: string[];
}

type LiveSocketStatus = 'idle' | 'connecting' | 'connected' | 'error';

export interface LiveDebatePanelProps {
  apiBase: string;
  wsUrl?: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

const LIVE_PREVIEW_POLL_MS = 12000;
const LIVE_PREVIEW_EVENT_LIMIT = 12;
const SAFE_DEBATE_ID_PATTERN = /^[A-Za-z0-9_-]+$/;

function toEpochMs(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}

function formatClockTime(timestampMs: number): string {
  return new Date(timestampMs).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  });
}

function sanitizeDebateId(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return SAFE_DEBATE_ID_PATTERN.test(trimmed) ? trimmed : null;
}

function buildSpectateSocketUrl(wsBase: string, debateId: string): string {
  const normalizedBase = wsBase.endsWith('/') ? wsBase : `${wsBase}/`;
  const url = new URL(normalizedBase);
  const basePath = url.pathname.replace(/\/+$/, '');
  url.pathname = `${basePath}/spectate/${encodeURIComponent(debateId)}`.replace(/\/{2,}/g, '/');
  return url.toString();
}

function readDetails(data: Record<string, unknown>): string | null {
  const details = data.details;
  return typeof details === 'string' && details.trim() ? details.trim() : null;
}

function readTask(data: Record<string, unknown>): string | null {
  const task = data.task;
  return typeof task === 'string' && task.trim() ? task.trim() : null;
}

function readAgents(data: Record<string, unknown>): string[] {
  const agents = data.agents;
  if (!Array.isArray(agents)) return [];
  return agents.filter(
    (agent): agent is string => typeof agent === 'string' && agent.trim().length > 0,
  );
}

function describeLiveEvent(
  eventType: string,
  details: string | null,
  roundNumber: number | null,
): string {
  if (details) return details;

  switch (eventType) {
    case 'debate_start':
      return 'The debate has started.';
    case 'round_start':
      return roundNumber ? `Round ${roundNumber} has started.` : 'A new round has started.';
    case 'proposal':
      return 'A proposer published a new argument.';
    case 'critique':
      return 'A critic challenged the current argument.';
    case 'refine':
      return 'An agent refined the current position.';
    case 'vote':
      return 'An agent cast a vote on the debate.';
    case 'consensus':
      return 'The panel reached a consensus checkpoint.';
    case 'round_end':
      return roundNumber ? `Round ${roundNumber} has closed.` : 'The current round has closed.';
    case 'debate_end':
      return 'The debate has completed.';
    default:
      return 'The public debate feed published a live update.';
  }
}

function eventBadgeClasses(eventType: string): string {
  switch (eventType) {
    case 'proposal':
    case 'refine':
      return 'bg-[var(--accent)]/10 text-[var(--accent)] border-[var(--accent)]/30';
    case 'critique':
      return 'bg-[var(--crimson)]/10 text-[var(--crimson)] border-[var(--crimson)]/30';
    case 'vote':
    case 'consensus':
      return 'bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30';
    case 'round_start':
    case 'round_end':
      return 'bg-acid-yellow/10 text-[var(--acid-yellow)] border-acid-yellow/30';
    default:
      return 'bg-surface text-text-muted border-border';
  }
}

function normalizeRecentEvent(event: PublicSpectateEvent): LivePreviewEvent {
  const timestampMs = toEpochMs(event.timestamp) ?? Date.now();
  const details = readDetails(event.data);
  const id = [
    event.event_type,
    timestampMs,
    event.agent_name ?? 'anon',
    event.round_number ?? 'nr',
    details ?? 'nd',
  ].join(':');

  return {
    id,
    eventType: event.event_type,
    timestampMs,
    timeLabel: formatClockTime(timestampMs),
    agent: event.agent_name,
    roundNumber: event.round_number,
    body: describeLiveEvent(event.event_type, details, event.round_number),
  };
}

function normalizeSocketEvent(message: SpectateSocketMessage): LivePreviewEvent {
  const timestampMs =
    typeof message.timestamp === 'number' ? Math.round(message.timestamp * 1000) : Date.now();
  const details =
    typeof message.details === 'string' && message.details.trim() ? message.details.trim() : null;
  const roundNumber = typeof message.round === 'number' ? message.round : null;
  const id = [
    message.type,
    timestampMs,
    message.agent ?? 'anon',
    roundNumber ?? 'nr',
    details ?? 'nd',
  ].join(':');

  return {
    id,
    eventType: message.type,
    timestampMs,
    timeLabel: formatClockTime(timestampMs),
    agent: message.agent ?? null,
    roundNumber,
    body: describeLiveEvent(message.type, details, roundNumber),
  };
}

function mergePreviewEvents(...eventGroups: LivePreviewEvent[][]): LivePreviewEvent[] {
  const merged = new Map<string, LivePreviewEvent>();
  for (const group of eventGroups) {
    for (const event of group) {
      merged.set(event.id, event);
    }
  }

  return Array.from(merged.values())
    .sort((left, right) => left.timestampMs - right.timestampMs)
    .slice(-LIVE_PREVIEW_EVENT_LIMIT);
}

function summarizeLiveDebates(
  events: PublicSpectateEvent[],
  activityWindowSeconds: number,
): LiveDebateSummary[] {
  const now = Date.now();
  const debates = new Map<string, LiveDebateSummary>();

  for (const event of events) {
    const timestampMs = toEpochMs(event.timestamp);
    if (timestampMs === null) continue;
    if (now - timestampMs > activityWindowSeconds * 1000) continue;
    const debateId = sanitizeDebateId(event.debate_id);
    if (!debateId) continue;

    const existing = debates.get(debateId);
    const task = readTask(event.data);
    const agents = readAgents(event.data);

    if (!existing) {
      debates.set(debateId, {
        debateId,
        task,
        agents,
        lastEventAt: event.timestamp,
        recentEventCount: 1,
      });
      continue;
    }

    existing.recentEventCount += 1;
    if (!existing.task && task) existing.task = task;
    if (existing.agents.length === 0 && agents.length > 0) existing.agents = agents;

    const existingTimestampMs = toEpochMs(existing.lastEventAt);
    if (existingTimestampMs === null || timestampMs >= existingTimestampMs) {
      existing.lastEventAt = event.timestamp;
    }
  }

  return Array.from(debates.values()).sort((left, right) => {
    const rightMs = toEpochMs(right.lastEventAt) ?? 0;
    const leftMs = toEpochMs(left.lastEventAt) ?? 0;
    return rightMs - leftMs;
  });
}

/* ------------------------------------------------------------------ */
/*  Component                                                          */
/* ------------------------------------------------------------------ */

export function LiveDebatePanel({ apiBase, wsUrl }: LiveDebatePanelProps) {
  const resolvedWsBase = (wsUrl || WS_URL).replace(/\/ws\/?$/, '');
  const wsRef = useRef<WebSocket | null>(null);

  const [status, setStatus] = useState<PublicSpectateStatus | null>(null);
  const [recentEvents, setRecentEvents] = useState<PublicSpectateEvent[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [bridgeReachable, setBridgeReachable] = useState(false);
  const [selectedDebateId, setSelectedDebateId] = useState<string | null>(null);
  const [socketStatus, setSocketStatus] = useState<LiveSocketStatus>('idle');
  const [socketTask, setSocketTask] = useState<string | null>(null);
  const [socketAgents, setSocketAgents] = useState<string[]>([]);
  const [socketEvents, setSocketEvents] = useState<LivePreviewEvent[]>([]);
  const [mergedEvents, setMergedEvents] = useState<LivePreviewEvent[]>([]);

  const refreshPreview = useCallback(async () => {
    try {
      const [recentRes, statusRes] = await Promise.all([
        fetch(`${apiBase}/api/v1/spectate/recent?count=40`),
        fetch(`${apiBase}/api/v1/spectate/status`),
      ]);

      const recentData = recentRes.ok ? await recentRes.json() : { events: [] };
      const statusData = statusRes.ok ? await statusRes.json() : null;

      setRecentEvents(Array.isArray(recentData.events) ? recentData.events : []);
      setStatus(statusData);
      setBridgeReachable(recentRes.ok);
    } catch {
      setRecentEvents([]);
      setStatus(null);
      setBridgeReachable(false);
    } finally {
      setLoaded(true);
    }
  }, [apiBase]);

  useEffect(() => {
    void refreshPreview();
    const interval = window.setInterval(() => {
      void refreshPreview();
    }, LIVE_PREVIEW_POLL_MS);

    return () => {
      window.clearInterval(interval);
    };
  }, [refreshPreview]);

  const activityWindowSeconds = status?.recent_activity_window_seconds ?? 120;
  const liveDebates = useMemo(
    () => summarizeLiveDebates(recentEvents, activityWindowSeconds),
    [activityWindowSeconds, recentEvents],
  );
  const safeSelectedDebateId = useMemo(
    () => sanitizeDebateId(selectedDebateId),
    [selectedDebateId],
  );

  useEffect(() => {
    if (selectedDebateId && !safeSelectedDebateId) {
      setSelectedDebateId(null);
    }
  }, [safeSelectedDebateId, selectedDebateId]);

  useEffect(() => {
    const hottestDebateId = liveDebates[0]?.debateId ?? null;
    setSelectedDebateId((currentDebateId) =>
      currentDebateId === hottestDebateId ? currentDebateId : hottestDebateId,
    );
  }, [liveDebates]);

  useEffect(() => {
    if (!safeSelectedDebateId) {
      setSocketStatus('idle');
      setSocketTask(null);
      setSocketAgents([]);
      setSocketEvents([]);
      return;
    }

    setSocketStatus('connecting');
    setSocketTask(null);
    setSocketAgents([]);
    setSocketEvents([]);

    const socket = new WebSocket(buildSpectateSocketUrl(resolvedWsBase, safeSelectedDebateId));
    wsRef.current = socket;

    socket.onopen = () => {
      setSocketStatus('connected');
    };

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data) as SpectateSocketMessage;

        if (message.type === 'metadata') {
          if (typeof message.task === 'string' && message.task.trim()) {
            setSocketTask(message.task.trim());
          }
          if (Array.isArray(message.agents)) {
            setSocketAgents(
              message.agents.filter(
                (agent): agent is string => typeof agent === 'string' && agent.trim().length > 0,
              ),
            );
          }
          return;
        }

        const normalizedEvent = normalizeSocketEvent(message);
        setSocketEvents((currentEvents) => mergePreviewEvents(currentEvents, [normalizedEvent]));
      } catch {
        setSocketStatus('error');
      }
    };

    socket.onerror = () => {
      setSocketStatus('error');
    };

    socket.onclose = () => {
      setSocketStatus((currentStatus) => (currentStatus === 'connected' ? 'idle' : currentStatus));
    };

    return () => {
      socket.close(1000, 'Landing live preview disconnected');
      if (wsRef.current === socket) {
        wsRef.current = null;
      }
    };
  }, [resolvedWsBase, safeSelectedDebateId]);

  const selectedDebate = useMemo(
    () => liveDebates.find((debate) => debate.debateId === safeSelectedDebateId) ?? null,
    [liveDebates, safeSelectedDebateId],
  );

  const recentDebateEvents = useMemo(() => {
    if (!safeSelectedDebateId) return [];
    return recentEvents
      .filter((event) => sanitizeDebateId(event.debate_id) === safeSelectedDebateId)
      .map(normalizeRecentEvent);
  }, [recentEvents, safeSelectedDebateId]);

  useEffect(() => {
    setMergedEvents(mergePreviewEvents(recentDebateEvents, socketEvents));
  }, [recentDebateEvents, socketEvents]);

  const bridgeTone =
    socketStatus === 'connected'
      ? 'bg-[var(--accent)]/10 text-[var(--accent)] border-[var(--accent)]/30'
      : bridgeReachable
        ? 'bg-[var(--acid-cyan)]/10 text-[var(--acid-cyan)] border-[var(--acid-cyan)]/30'
        : 'bg-[var(--crimson)]/10 text-[var(--crimson)] border-[var(--crimson)]/30';

  const bridgeLabel =
    socketStatus === 'connected'
      ? 'STREAMING NOW'
      : bridgeReachable
        ? 'FOLLOWING LIVE BRIDGE'
        : 'BRIDGE OFFLINE';

  const bridgeSummary = !loaded
    ? 'Checking the public spectate bridge before claiming a live debate.'
    : selectedDebate
      ? `${selectedDebate.recentEventCount} recent event${selectedDebate.recentEventCount === 1 ? '' : 's'} discovered for this debate.`
      : bridgeReachable
        ? 'The bridge is online. This panel will attach as soon as a public debate starts emitting events.'
        : 'The public spectate bridge is unreachable right now, so no live debate is shown.';

  const activeTask =
    socketTask ??
    selectedDebate?.task ??
    'Waiting for a public debate to surface in the live bridge.';
  const activeAgents = socketAgents.length > 0 ? socketAgents : (selectedDebate?.agents ?? []);
  const spectatorHref = safeSelectedDebateId
    ? `/spectate/${encodeURIComponent(safeSelectedDebateId)}`
    : '/spectate';

  return (
    <section className="px-4 pb-20">
      <div className="max-w-5xl mx-auto border border-border bg-surface/50 overflow-hidden">
        <div className="grid lg:grid-cols-[0.95fr,1.05fr]">
          <div className="p-6 sm:p-8 border-b border-border lg:border-b-0 lg:border-r lg:border-border">
            <div className="flex flex-wrap items-center gap-2 mb-5">
              <span className="px-2 py-1 text-[10px] font-theme-data border border-[var(--accent)]/30 bg-[var(--accent)]/10 text-[var(--accent)] tracking-[0.2em]">
                LIVE DEBATE
              </span>
              <span
                className={`px-2 py-1 text-[10px] font-theme-data border tracking-[0.16em] ${bridgeTone}`}
              >
                {bridgeLabel}
              </span>
            </div>

            <h2 className="font-theme-data text-2xl text-text mb-3">
              Watch agents argue in real time.
            </h2>
            <p className="font-theme-data text-sm text-text-muted leading-relaxed mb-4">
              {bridgeSummary}
            </p>
            <p className="font-theme-data text-sm text-text leading-relaxed mb-6">{activeTask}</p>

            {liveDebates.length > 1 && (
              <div className="mb-6">
                <p className="font-theme-data text-[11px] uppercase tracking-[0.2em] text-text-muted mb-2">
                  Public debates
                </p>
                <div className="flex flex-wrap gap-2">
                  {liveDebates.slice(0, 3).map((debate) => (
                    <button
                      key={debate.debateId}
                      type="button"
                      onClick={() => setSelectedDebateId(debate.debateId)}
                      className={`px-3 py-2 text-xs font-theme-data border transition-colors ${
                        debate.debateId === selectedDebateId
                          ? 'border-[var(--accent)]/40 text-[var(--accent)] bg-[var(--accent)]/10'
                          : 'border-border text-text-muted hover:border-[var(--accent)]/30 hover:text-[var(--accent)]'
                      }`}
                    >
                      {debate.task?.slice(0, 48) || debate.debateId}
                    </button>
                  ))}
                </div>
              </div>
            )}

            <div className="flex flex-wrap gap-3 mb-6">
              <span className="font-theme-data text-xs text-text-muted">
                {(status?.recent_event_count ?? recentEvents.length).toString()} recent bridge
                events
              </span>
              {safeSelectedDebateId && (
                <span className="font-theme-data text-xs text-text-muted">
                  Debate {safeSelectedDebateId.slice(-8).toUpperCase()}
                </span>
              )}
              {activeAgents.length > 0 && (
                <span className="font-theme-data text-xs text-text-muted">
                  {activeAgents.length} agents visible
                </span>
              )}
            </div>

            <div className="flex flex-wrap gap-3">
              <Link
                href={spectatorHref}
                className="font-theme-data text-xs px-4 py-2 bg-[var(--accent)] text-bg font-bold hover:opacity-90 transition-opacity"
              >
                Open spectator view
              </Link>
              <Link
                href="/spectate"
                className="font-theme-data text-xs px-4 py-2 border border-border text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
              >
                Browse live debates
              </Link>
            </div>
          </div>

          <div className="min-h-[420px] flex flex-col">
            <div className="px-4 py-3 border-b border-border bg-bg/70 flex flex-wrap items-center gap-2">
              <span className="font-theme-data text-[10px] tracking-[0.2em] text-[var(--accent)]">
                PUBLIC FEED
              </span>
              {activeAgents.slice(0, 4).map((agent) => (
                <span
                  key={agent}
                  className="px-2 py-1 text-[10px] font-theme-data border border-border text-text-muted bg-surface"
                >
                  {agent}
                </span>
              ))}
            </div>

            <div className="flex-1 p-4">
              {mergedEvents.length > 0 ? (
                <div aria-live="polite" className="space-y-3 max-h-[360px] overflow-y-auto pr-1">
                  {mergedEvents.map((event) => (
                    <div key={event.id} className="border border-border bg-bg/60 p-3">
                      <div className="flex flex-wrap items-center gap-2 mb-2">
                        <span
                          className={`px-2 py-1 text-[10px] font-theme-data border tracking-[0.14em] ${eventBadgeClasses(event.eventType)}`}
                        >
                          {event.eventType.replace(/_/g, ' ').toUpperCase()}
                        </span>
                        {event.agent && (
                          <span className="font-theme-data text-xs text-text">{event.agent}</span>
                        )}
                        {event.roundNumber !== null && (
                          <span className="font-theme-data text-[10px] text-text-muted">
                            R{event.roundNumber}
                          </span>
                        )}
                        <span className="ml-auto font-theme-data text-[10px] text-text-muted">
                          {event.timeLabel}
                        </span>
                      </div>
                      <p className="font-theme-data text-sm text-text-muted leading-relaxed">
                        {event.body}
                      </p>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="h-full flex items-center justify-center border border-dashed border-border bg-bg/40 p-8">
                  <div className="max-w-sm text-center">
                    <p className="font-theme-data text-sm text-text mb-2">
                      No live public debate is attached yet.
                    </p>
                    <p className="font-theme-data text-xs text-text-muted leading-relaxed">
                      As soon as the bridge sees a debate ID in recent spectate events, this panel
                      will lock onto it and stream the argument feed here.
                    </p>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
