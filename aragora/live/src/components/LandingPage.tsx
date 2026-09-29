/**
 * @deprecated Use components/landing/LandingPage.tsx + HeroSection.tsx instead.
 * This file is the non-canonical landing page with duplicate debate logic.
 * All active debate flow lives in HeroSection.tsx.
 * TODO: Remove once confirmed no routes import this file.
 *
 * NOTE (audit 2026-04-04): HomePage now uses the canonical
 * components/landing/LandingPage.tsx path. Keep this file only as a
 * compatibility shim for legacy imports/tests until the remaining callers
 * are removed.
 */
'use client';

import { useState, useCallback, useRef, useEffect, useMemo, FormEvent } from 'react';
import Link from 'next/link';
import { WS_URL } from '@/config';
import {
  DebateResultPreview,
  RETURN_URL_KEY,
  PENDING_DEBATE_KEY,
  type DebateResponse,
} from './DebateResultPreview';
import type { LandingDebatePreflight, LandingPreparedDebateOption } from './landing/types';
import { submitLandingFeedback, trackLandingEvent } from './landing/landingTelemetry';
import { getCurrentReturnUrl, normalizeReturnUrl } from '@/utils/returnUrl';

interface LandingPageProps {
  apiBase?: string;
  wsUrl?: string;
  onDebateStarted?: (debateId: string) => void;
  onEnterDashboard?: () => void;
}

const PROGRESS_MESSAGES = [
  'Assembling analyst panel...',
  'Agents debating your question...',
  'Analyzing arguments...',
  'Building consensus...',
  'Generating verdict...',
];

const LIVE_PREVIEW_POLL_MS = 4000;
const LIVE_PREVIEW_EVENT_LIMIT = 12;

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
    if (!event.debate_id) continue;

    const existing = debates.get(event.debate_id);
    const task = readTask(event.data);
    const agents = readAgents(event.data);

    if (!existing) {
      debates.set(event.debate_id, {
        debateId: event.debate_id,
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

function LiveDebatePanel({ apiBase, wsUrl }: { apiBase: string; wsUrl?: string }) {
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

  useEffect(() => {
    const hottestDebateId = liveDebates[0]?.debateId ?? null;
    setSelectedDebateId(hottestDebateId);
  }, [liveDebates]);

  useEffect(() => {
    if (!selectedDebateId) {
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

    const socket = new WebSocket(`${resolvedWsBase}/spectate/${selectedDebateId}`);
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
        setSocketEvents((currentEvents) => {
          const nextEvents = new Map(
            currentEvents.map((previewEvent) => [previewEvent.id, previewEvent]),
          );
          nextEvents.set(normalizedEvent.id, normalizedEvent);
          return Array.from(nextEvents.values())
            .sort((left, right) => left.timestampMs - right.timestampMs)
            .slice(-LIVE_PREVIEW_EVENT_LIMIT);
        });
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
  }, [resolvedWsBase, selectedDebateId]);

  const selectedDebate = useMemo(
    () => liveDebates.find((debate) => debate.debateId === selectedDebateId) ?? null,
    [liveDebates, selectedDebateId],
  );

  const recentDebateEvents = useMemo(() => {
    if (!selectedDebateId) return [];
    return recentEvents
      .filter((event) => event.debate_id === selectedDebateId)
      .map(normalizeRecentEvent);
  }, [recentEvents, selectedDebateId]);

  const mergedEvents = useMemo(() => {
    const merged = new Map<string, LivePreviewEvent>();
    for (const event of [...recentDebateEvents, ...socketEvents]) {
      merged.set(event.id, event);
    }

    return Array.from(merged.values())
      .sort((left, right) => left.timestampMs - right.timestampMs)
      .slice(-LIVE_PREVIEW_EVENT_LIMIT);
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
              {selectedDebateId && (
                <span className="font-theme-data text-xs text-text-muted">
                  Debate {selectedDebateId.slice(-8).toUpperCase()}
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
                href={selectedDebateId ? `/spectate/${selectedDebateId}` : '/spectate'}
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

function parseRetryAfterSeconds(retryAfter: string | null): number {
  if (!retryAfter) return 60;

  const deltaSeconds = Number.parseInt(retryAfter, 10);
  if (Number.isFinite(deltaSeconds) && deltaSeconds >= 0) {
    return deltaSeconds;
  }

  const retryTime = Date.parse(retryAfter);
  if (Number.isNaN(retryTime)) return 60;

  return Math.max(1, Math.ceil((retryTime - Date.now()) / 1000));
}

function buildLandingErrorMessage(status: number, data: Record<string, unknown> | null): string {
  const message = typeof data?.message === 'string' ? data.message.trim() : '';
  const error = typeof data?.error === 'string' ? data.error.trim() : '';
  const code = typeof data?.code === 'string' ? data.code : '';
  const timeoutSeconds =
    typeof data?.timeout_seconds === 'number' ? Math.round(data.timeout_seconds) : null;

  if (code === 'request_timeout' && timeoutSeconds !== null) {
    return `Request timed out after ${timeoutSeconds}s. The landing page works best with one focused question. Shorten the prompt, pick one interpretation, or retry with a narrower scope.`;
  }

  if (code === 'landing_preview_timeout') {
    if (message) return message;
    if (timeoutSeconds !== null) {
      return `The landing preview timed out after ${timeoutSeconds}s. Shorten the prompt or pick one interpretation first.`;
    }
    return error || 'The landing preview timed out before the models returned a clean result.';
  }

  if (code === 'landing_preview_needs_clarification') {
    return (
      message ||
      error ||
      'The fast preview drifted away from your question. Tighten the wording or pick one interpretation first.'
    );
  }

  if (code === 'timeout') {
    return message || error || 'The live debate timed out. Try a shorter, more focused question.';
  }

  if (message) return message;
  if (error) return error;
  return `Something went wrong (${status}). Please try again.`;
}

export function LandingPage({ apiBase, wsUrl, onEnterDashboard }: LandingPageProps) {
  const [question, setQuestion] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<DebateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editorNotice, setEditorNotice] = useState<string | null>(null);
  const [lastTopic, setLastTopic] = useState('');
  const [lastPreparedOption, setLastPreparedOption] = useState<LandingPreparedDebateOption | null>(
    null,
  );
  const [pendingPreflight, setPendingPreflight] = useState<LandingDebatePreflight | null>(null);
  const [progressMsg, setProgressMsg] = useState(PROGRESS_MESSAGES[0]);
  const abortRef = useRef<AbortController | null>(null);
  const progressRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const focusFrameRef = useRef<number | null>(null);

  const resolvedApiBase = apiBase || 'https://api.aragora.ai';
  const livePreviewApiBase = useMemo(() => resolvedApiBase.replace(/\/$/, ''), [resolvedApiBase]);
  const trackEvent = useCallback(
    (
      eventType: Parameters<typeof trackLandingEvent>[1],
      data: Parameters<typeof trackLandingEvent>[2] = {},
    ) => {
      trackLandingEvent(resolvedApiBase, eventType, data);
    },
    [resolvedApiBase],
  );
  const focusComposer = useCallback(() => {
    const focus = () => {
      textareaRef.current?.focus();
      textareaRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    };
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      if (focusFrameRef.current !== null && typeof window.cancelAnimationFrame === 'function') {
        window.cancelAnimationFrame(focusFrameRef.current);
      }
      focusFrameRef.current = window.requestAnimationFrame(() => {
        focusFrameRef.current = null;
        focus();
      });
      return;
    }
    setTimeout(focus, 0);
  }, []);

  useEffect(() => {
    return () => {
      if (focusFrameRef.current !== null && typeof window.cancelAnimationFrame === 'function') {
        window.cancelAnimationFrame(focusFrameRef.current);
        focusFrameRef.current = null;
      }
      abortRef.current?.abort();
      if (progressRef.current) {
        clearInterval(progressRef.current);
      }
    };
  }, []);

  const saveDebateBeforeLogin = useCallback(() => {
    if (result) {
      sessionStorage.setItem(PENDING_DEBATE_KEY, JSON.stringify(result));
      const debateDestination = result.id
        ? `/debates/${encodeURIComponent(result.id)}`
        : getCurrentReturnUrl();
      sessionStorage.setItem(RETURN_URL_KEY, normalizeReturnUrl(debateDestination));
    }
  }, [result]);

  async function executeDebate(option: LandingPreparedDebateOption) {
    abortRef.current?.abort();
    if (progressRef.current) {
      clearInterval(progressRef.current);
    }

    setIsRunning(true);
    setError(null);
    setEditorNotice(null);
    setResult(null);
    setPendingPreflight(null);
    setLastTopic(option.originalQuestion);
    setLastPreparedOption(option);
    setProgressMsg(PROGRESS_MESSAGES[0]);
    trackEvent('preflight_selected', {
      option_id: option.id,
      recommended: Boolean(option.recommended),
      rewritten: option.interpretedQuestion !== option.originalQuestion,
      agents: option.agents,
      rounds: option.rounds,
      question_length: option.originalQuestion.length,
    });

    // Rotate progress messages
    let progressIdx = 0;
    progressRef.current = setInterval(() => {
      progressIdx = (progressIdx + 1) % PROGRESS_MESSAGES.length;
      setProgressMsg(PROGRESS_MESSAGES[progressIdx]);
    }, 4000);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${resolvedApiBase}/api/v1/playground/debate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: option.debatePrompt,
          question: option.debatePrompt,
          original_question: option.originalQuestion,
          interpreted_question: option.interpretedQuestion,
          rounds: option.rounds,
          agents: option.agents,
          source: 'landing',
        }),
        signal: controller.signal,
      });

      if (res.status === 429) {
        const retryAfter = parseRetryAfterSeconds(res.headers.get('Retry-After'));
        const waitText =
          retryAfter > 60 ? `${Math.ceil(retryAfter / 60)} minutes` : `${retryAfter} seconds`;
        setError(`Rate limit reached. Please try again in ${waitText}.`);
        return;
      }

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const code = typeof data?.code === 'string' ? data.code : '';
        if (code === 'landing_preview_timeout') {
          trackEvent('preview_timeout', {
            timeout_seconds:
              typeof data?.timeout_seconds === 'number' ? Math.round(data.timeout_seconds) : null,
            rewritten: option.interpretedQuestion !== option.originalQuestion,
            question_length: option.originalQuestion.length,
          });
        } else if (code === 'landing_preview_needs_clarification') {
          trackEvent('preview_clarification_requested', {
            rewritten: option.interpretedQuestion !== option.originalQuestion,
            question_length: option.originalQuestion.length,
          });
        }
        setError(buildLandingErrorMessage(res.status, data));
        return;
      }

      const data: DebateResponse = await res.json();
      const nextResult: DebateResponse = {
        ...data,
        original_question: option.originalQuestion,
        interpreted_question: option.interpretedQuestion,
        result_warning:
          data.result_warning ||
          (option.interpretedQuestion !== option.originalQuestion
            ? 'Aragora debated the focused interpretation you chose before opening the full transcript.'
            : undefined),
      };
      trackEvent('preview_rendered', {
        result_mode: nextResult.result_mode || 'full',
        rewritten: option.interpretedQuestion !== option.originalQuestion,
        participant_count: nextResult.participants.length,
        has_warning: Boolean(nextResult.result_warning),
      });
      setResult(nextResult);
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      if (err instanceof Error && err.message.includes('Failed to fetch')) {
        setError('Could not connect to the server. Check your connection and try again.');
        return;
      }
      setError('Network error. Please try again.');
    } finally {
      if (progressRef.current) {
        clearInterval(progressRef.current);
        progressRef.current = null;
      }
      setIsRunning(false);
      setProgressMsg('');
    }
  }

  async function runDebate(rawQuestion: string) {
    setError(null);
    setEditorNotice(null);
    setResult(null);
    setLastTopic(rawQuestion);
    setIsRunning(true);

    const fallbackOption: LandingPreparedDebateOption = {
      id: 'original',
      label: rawQuestion,
      description: rawQuestion,
      originalQuestion: rawQuestion,
      interpretedQuestion: rawQuestion,
      debatePrompt: rawQuestion,
      agents: 3,
      rounds: 2,
    };

    try {
      const assessRes = await fetch(`${livePreviewApiBase}/api/v1/playground/assess`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: rawQuestion }),
        signal: AbortSignal.timeout(8000),
      });

      if (!assessRes.ok) {
        setPendingPreflight(null);
        setIsRunning(false);
        void executeDebate(fallbackOption);
        return;
      }

      const assessment = await assessRes.json();

      if (assessment.type === 'confirm') {
        setPendingPreflight(assessment.preflight);
        setIsRunning(false);
        trackEvent('preflight_shown', {
          option_count: assessment.preflight.options.length,
          question_length: rawQuestion.length,
        });
        return;
      }

      // Clear -- proceed directly
      setPendingPreflight(null);
      setIsRunning(false);
      void executeDebate(assessment.option ?? fallbackOption);
    } catch {
      setIsRunning(false);
      setPendingPreflight(null);
      void executeDebate(fallbackOption);
    }
  }

  const handleWrongAnswer = useCallback(
    (currentResult: DebateResponse) => {
      const sourceQuestion =
        currentResult.original_question || question || lastTopic || currentResult.topic;
      const rewritten =
        Boolean(currentResult.interpreted_question) &&
        currentResult.interpreted_question !==
          (currentResult.original_question || currentResult.topic);

      setQuestion(sourceQuestion);
      setResult(null);
      setError(null);
      setLastTopic(sourceQuestion);
      setLastPreparedOption(null);
      setPendingPreflight(null);
      setEditorNotice('Edit the wording below and rerun the debate with one more specific detail.');

      submitLandingFeedback(resolvedApiBase, {
        question: sourceQuestion,
        interpreted_question: currentResult.interpreted_question || currentResult.topic,
        final_answer: currentResult.final_answer,
        result_warning: currentResult.result_warning || null,
        result_mode: currentResult.result_mode || 'full',
        debate_id: currentResult.id || null,
        verdict: currentResult.verdict || null,
        participant_count: currentResult.participants.length,
        rewritten,
      });
      trackEvent('wrong_answer_clicked', {
        result_mode: currentResult.result_mode || 'full',
        rewritten,
      });
      focusComposer();
    },
    [focusComposer, lastTopic, question, resolvedApiBase, trackEvent],
  );

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (question.trim()) {
      void runDebate(question.trim());
    }
  }

  return (
    <main className="min-h-screen bg-bg text-text">
      {/* Nav */}
      <nav className="border-b border-border bg-surface/80 backdrop-blur-sm shadow-[0_1px_0_var(--border-glow)] sticky top-0 z-50">
        <div className="max-w-5xl mx-auto px-4 py-3 flex items-center justify-between">
          <span className="font-theme-data text-[var(--accent)] font-bold text-sm tracking-wider">
            ARAGORA
          </span>
          <div className="flex items-center gap-4">
            <a
              href="#how-it-works"
              className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors hidden sm:block"
            >
              How it works
            </a>
            <Link
              href="/oracle"
              className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors hidden sm:block"
            >
              Oracle
            </Link>
            {onEnterDashboard ? (
              <button
                onClick={() => {
                  saveDebateBeforeLogin();
                  onEnterDashboard();
                }}
                className="text-xs font-theme-data px-3 py-1.5 border border-[var(--accent)]/40 text-text-muted hover:text-[var(--accent)] hover:border-[var(--accent)] transition-colors"
              >
                Log in
              </button>
            ) : (
              <Link
                href="/login"
                onClick={saveDebateBeforeLogin}
                className="text-xs font-theme-data px-3 py-1.5 border border-[var(--accent)]/40 text-text-muted hover:text-[var(--accent)] hover:border-[var(--accent)] transition-colors"
              >
                Log in
              </Link>
            )}
            <Link
              href="/signup"
              onClick={saveDebateBeforeLogin}
              className="text-xs font-theme-data px-3 py-1.5 bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors font-bold"
            >
              Sign up free
            </Link>
          </div>
        </div>
      </nav>

      {/* Hero */}
      <section className="py-20 sm:py-32 px-4">
        <div className="max-w-2xl mx-auto text-center">
          <h1 className="font-theme-data text-3xl sm:text-5xl text-text mb-6 leading-tight">
            Don&apos;t trust one AI.
            <br />
            <span className="text-[var(--accent)]">Make them argue.</span>
          </h1>
          <p className="font-theme-data text-sm text-text-muted max-w-lg mx-auto mb-12 leading-relaxed">
            Multiple AI models debate your question, stress-test each answer, and deliver an
            audit-ready verdict you can actually defend.
          </p>

          <form onSubmit={handleSubmit} className="text-left max-w-xl mx-auto">
            <textarea
              ref={textareaRef}
              value={question}
              onChange={(e) => {
                setQuestion(e.target.value);
                setPendingPreflight(null);
                setEditorNotice(null);
              }}
              placeholder="What decision are you facing?"
              disabled={isRunning}
              rows={2}
              className="w-full bg-surface border border-border text-text px-4 py-3 font-theme-data text-sm placeholder:text-text-muted/50 focus:outline-none focus:border-[var(--accent)] transition-colors resize-none disabled:opacity-50"
            />
            <button
              type="submit"
              disabled={isRunning || !question.trim()}
              className="w-full mt-3 font-theme-data text-sm px-8 py-3 bg-[var(--accent)] text-bg font-bold hover:opacity-90 transition-opacity disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {isRunning ? 'Agents debating...' : 'Run a free debate'}
            </button>
          </form>

          {editorNotice && !isRunning && (
            <div className="mt-4 max-w-xl mx-auto rounded-xl border border-[var(--acid-cyan)]/20 bg-[var(--acid-cyan)]/10 px-4 py-3 text-left">
              <p className="text-xs text-text-muted leading-relaxed">{editorNotice}</p>
            </div>
          )}

          {/* Example topics — reduce blank-page friction */}
          {!result && !isRunning && (
            <div className="max-w-xl mx-auto mt-4">
              <p className="text-xs font-theme-data text-text-muted/60 mb-2 text-center">
                Or try an example:
              </p>
              <div className="flex flex-wrap justify-center gap-2">
                {[
                  'Should we build or buy our analytics platform?',
                  'Is remote work better for a 50-person company?',
                  'Should we adopt microservices or keep our monolith?',
                ].map((topic) => (
                  <button
                    key={topic}
                    onClick={() => {
                      setQuestion(topic);
                      void runDebate(topic);
                    }}
                    className="text-xs font-theme-data px-3 py-1.5 border border-border text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
                  >
                    {topic}
                  </button>
                ))}
              </div>
            </div>
          )}

          {pendingPreflight && !isRunning && (
            <div className="border border-acid-yellow/30 bg-acid-yellow/10 p-4 mt-6 text-left max-w-xl mx-auto space-y-4">
              <div>
                <p className="text-sm font-theme-data text-text mb-2">{pendingPreflight.title}</p>
                <p className="text-xs font-theme-data text-text-muted leading-relaxed">
                  {pendingPreflight.prompt}
                </p>
                {pendingPreflight.warning && (
                  <p className="text-xs font-theme-data text-[var(--acid-yellow)] mt-3 leading-relaxed">
                    {pendingPreflight.warning}
                  </p>
                )}
              </div>
              <div className="space-y-2">
                {pendingPreflight.options.map((option) => (
                  <button
                    key={option.id}
                    type="button"
                    onClick={() => {
                      void executeDebate(option);
                    }}
                    className="w-full text-left border border-border bg-surface px-4 py-3 hover:border-[var(--accent)]/40 transition-colors"
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className="text-sm font-theme-data text-text">{option.label}</span>
                      {option.recommended && (
                        <span className="px-2 py-0.5 text-[10px] font-theme-data uppercase tracking-[0.18em] border border-[var(--accent)]/30 bg-[var(--accent)]/10 text-[var(--accent)]">
                          Recommended
                        </span>
                      )}
                    </div>
                    <p className="text-xs font-theme-data text-text-muted leading-relaxed">
                      {option.description}
                    </p>
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => setPendingPreflight(null)}
                className="font-theme-data text-xs text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                Edit the question instead
              </button>
            </div>
          )}

          {isRunning && (
            <div className="flex flex-col items-center py-8 gap-3">
              <div className="flex items-center gap-3 text-[var(--accent)]">
                <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                <span className="text-sm font-theme-data">{progressMsg}</span>
              </div>
              <span className="text-xs font-theme-data text-text-muted/60">
                Usually takes 10-20 seconds
              </span>
            </div>
          )}

          {error && (
            <div className="border border-[var(--crimson)]/40 bg-[var(--crimson)]/5 p-4 mt-6 text-left max-w-xl mx-auto">
              <p className="text-sm text-[var(--crimson)] font-theme-data mb-3">{error}</p>
              {(lastPreparedOption || lastTopic) && (
                <button
                  onClick={() => {
                    trackEvent('retry_clicked', {
                      has_prepared_option: Boolean(lastPreparedOption),
                      has_question: Boolean(lastTopic),
                    });
                    setError(null);
                    if (lastPreparedOption) {
                      void executeDebate(lastPreparedOption);
                      return;
                    }
                    void runDebate(lastTopic);
                  }}
                  className="font-theme-data text-xs px-4 py-2 border border-[var(--crimson)]/40 text-[var(--crimson)] hover:bg-[var(--crimson)]/10 transition-colors"
                >
                  Try again
                </button>
              )}
            </div>
          )}

          {result && (
            <DebateResultPreview
              result={result}
              condensed
              onFlagWrongAnswer={handleWrongAnswer}
              onOpenFullDebate={(debateResult, surface) => {
                trackEvent('open_full_debate_clicked', {
                  result_mode: debateResult.result_mode || 'full',
                  surface,
                });
              }}
              onShare={(debateResult) => {
                trackEvent('share_clicked', { result_mode: debateResult.result_mode || 'full' });
              }}
            />
          )}
        </div>
      </section>

      <LiveDebatePanel apiBase={livePreviewApiBase} wsUrl={wsUrl} />

      {/* How it works */}
      <section id="how-it-works" className="py-20 px-4 border-t border-border">
        <div className="max-w-3xl mx-auto">
          <h2 className="font-theme-data text-sm text-text-muted text-center mb-12 tracking-widest uppercase">
            How it works
          </h2>
          <div className="space-y-12">
            {[
              {
                step: '01',
                title: 'You ask a question',
                desc: 'Any decision, strategy, or architecture question you need vetted.',
              },
              {
                step: '02',
                title: 'AI agents debate it',
                desc: 'Claude, GPT, Gemini, Mistral, and others argue every angle. Different models catch different blind spots.',
              },
              {
                step: '03',
                title: 'You get a decision receipt',
                desc: 'An audit-ready verdict with evidence chains, confidence scores, and dissenting views preserved.',
              },
            ].map((item) => (
              <div key={item.step} className="flex gap-6 items-start">
                <span className="font-theme-data text-[var(--accent)] text-sm mt-0.5 flex-shrink-0">
                  {item.step}
                </span>
                <div>
                  <h3 className="font-theme-data text-base text-text mb-1">{item.title}</h3>
                  <p className="font-theme-data text-sm text-text-muted leading-relaxed">
                    {item.desc}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Why debate */}
      <section className="py-20 px-4 border-t border-border">
        <div className="max-w-3xl mx-auto">
          <h2 className="font-theme-data text-sm text-text-muted text-center mb-4 tracking-widest uppercase">
            Why this matters
          </h2>
          <p className="font-theme-data text-lg text-center text-text mb-12 max-w-xl mx-auto leading-relaxed">
            A single AI hallucinates, agrees with you, and contradicts itself. Adversarial debate
            fixes all three.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            {[
              {
                problem: 'Hallucination',
                fix: 'Cross-model verification catches fabrications before they reach you.',
              },
              {
                problem: 'Sycophancy',
                fix: 'Agents are structurally incentivized to disagree and find flaws.',
              },
              {
                problem: 'Inconsistency',
                fix: 'Debate convergence produces stable, defensible positions.',
              },
            ].map((item) => (
              <div key={item.problem}>
                <h3 className="font-theme-data text-sm text-[var(--accent)] mb-2">
                  {item.problem}
                </h3>
                <p className="font-theme-data text-xs text-text-muted leading-relaxed">
                  {item.fix}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Bottom CTA */}
      <section className="py-20 px-4 border-t border-border">
        <div className="max-w-2xl mx-auto text-center">
          <p className="font-theme-data text-sm text-text-muted mb-6">
            No signup required. First result in under 30 seconds.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-3">
            <button
              onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
              className="font-theme-data text-sm px-8 py-3 bg-[var(--accent)] text-bg font-bold hover:opacity-90 transition-opacity"
            >
              Try it now
            </button>
            <Link
              href="/signup"
              className="font-theme-data text-sm px-8 py-3 border border-border text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
            >
              Create an account
            </Link>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-6 px-4 border-t border-border">
        <div className="max-w-5xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4">
          <span className="font-theme-data text-xs text-text-muted/50">Aragora</span>
          <div className="flex items-center gap-6">
            <a
              href="/about"
              className="font-theme-data text-xs text-text-muted/50 hover:text-text-muted transition-colors"
            >
              About
            </a>
            <a
              href="/pricing"
              className="font-theme-data text-xs text-text-muted/50 hover:text-text-muted transition-colors"
            >
              Pricing
            </a>
            <a
              href="mailto:support@aragora.ai"
              className="font-theme-data text-xs text-text-muted/50 hover:text-text-muted transition-colors"
            >
              Support
            </a>
          </div>
        </div>
      </footer>
    </main>
  );
}
