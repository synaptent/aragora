'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { useTheme } from '@/context/ThemeContext';
import { useSpectate, type SpectateEvent } from '@/hooks/useSpectate';

interface TranscriptEvent {
  id: string;
  label: string;
  accent: string;
  background: string;
  eventType: string;
  agentName: string | null;
  roundNumber: number | null;
  copy: string;
  source: 'live' | 'demo';
}

const FALLBACK_TASK =
  'Should a fast-growing software org split the monolith now or sequence the migration later?';

const FALLBACK_STREAM: TranscriptEvent[] = [
  {
    id: 'demo-1',
    label: 'Proposal',
    accent: '#2563eb',
    background: 'rgba(37, 99, 235, 0.08)',
    eventType: 'proposal',
    agentName: 'Strategic Analyst',
    roundNumber: 1,
    copy: 'Keep the monolith for now, but carve out the most volatile billing workflows behind stable APIs first.',
    source: 'demo',
  },
  {
    id: 'demo-2',
    label: 'Critique',
    accent: '#dc2626',
    background: 'rgba(220, 38, 38, 0.08)',
    eventType: 'critique',
    agentName: "Devil's Advocate",
    roundNumber: 1,
    copy: 'That plan still centralizes deploy risk. Until ownership moves to product teams, the migration cost will outrun the reliability gain.',
    source: 'demo',
  },
  {
    id: 'demo-3',
    label: 'Reasoning',
    accent: '#0f766e',
    background: 'rgba(15, 118, 110, 0.08)',
    eventType: 'agent_reasoning',
    agentName: 'Implementation Expert',
    roundNumber: 2,
    copy: 'Sequence the move around change frequency: checkout and pricing first, auth and reporting later.',
    source: 'demo',
  },
  {
    id: 'demo-4',
    label: 'Crux',
    accent: '#be123c',
    background: 'rgba(190, 18, 60, 0.08)',
    eventType: 'crux_identified',
    agentName: 'Systems Judge',
    roundNumber: 2,
    copy: 'The real disagreement is whether team boundaries are mature enough to own independent services.',
    source: 'demo',
  },
  {
    id: 'demo-5',
    label: 'Vote',
    accent: '#ca8a04',
    background: 'rgba(202, 138, 4, 0.08)',
    eventType: 'vote',
    agentName: 'Systems Judge',
    roundNumber: 3,
    copy: 'The panel leans toward a staged migration with two pilot domains and explicit observability gates.',
    source: 'demo',
  },
  {
    id: 'demo-6',
    label: 'Consensus',
    accent: '#059669',
    background: 'rgba(5, 150, 105, 0.08)',
    eventType: 'consensus',
    agentName: 'Systems Judge',
    roundNumber: 3,
    copy: 'Consensus reached: keep the monolith as the control plane, then extract only the domains with sustained delivery pressure.',
    source: 'demo',
  },
];

const INTERESTING_EVENT_TYPES = new Set([
  'debate_start',
  'round_start',
  'round_end',
  'proposal',
  'critique',
  'refine',
  'vote',
  'judge',
  'consensus',
  'converged',
  'agent_reasoning',
  'agent_thinking',
  'argument_strength',
  'crux_identified',
]);

const EVENT_METADATA: Record<string, { label: string; accent: string; background: string }> = {
  debate_start: { label: 'Opening', accent: '#7c3aed', background: 'rgba(124, 58, 237, 0.08)' },
  round_start: { label: 'Round', accent: '#0891b2', background: 'rgba(8, 145, 178, 0.08)' },
  round_end: { label: 'Checkpoint', accent: '#0f766e', background: 'rgba(15, 118, 110, 0.08)' },
  proposal: { label: 'Proposal', accent: '#2563eb', background: 'rgba(37, 99, 235, 0.08)' },
  critique: { label: 'Critique', accent: '#dc2626', background: 'rgba(220, 38, 38, 0.08)' },
  refine: { label: 'Revision', accent: '#1d4ed8', background: 'rgba(29, 78, 216, 0.08)' },
  vote: { label: 'Vote', accent: '#ca8a04', background: 'rgba(202, 138, 4, 0.08)' },
  judge: { label: 'Judge', accent: '#d97706', background: 'rgba(217, 119, 6, 0.08)' },
  consensus: { label: 'Consensus', accent: '#059669', background: 'rgba(5, 150, 105, 0.08)' },
  converged: { label: 'Converged', accent: '#059669', background: 'rgba(5, 150, 105, 0.08)' },
  agent_reasoning: {
    label: 'Reasoning',
    accent: '#0f766e',
    background: 'rgba(15, 118, 110, 0.08)',
  },
  agent_thinking: { label: 'Thinking', accent: '#0891b2', background: 'rgba(8, 145, 178, 0.08)' },
  argument_strength: {
    label: 'Strength',
    accent: '#ca8a04',
    background: 'rgba(202, 138, 4, 0.08)',
  },
  crux_identified: { label: 'Crux', accent: '#be123c', background: 'rgba(190, 18, 60, 0.08)' },
  default: { label: 'Update', accent: '#475569', background: 'rgba(71, 85, 105, 0.08)' },
};

function getText(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function toEpochMs(timestamp: string | null | undefined): number | null {
  if (!timestamp) return null;

  const parsed = Date.parse(timestamp);
  return Number.isNaN(parsed) ? null : parsed;
}

function getMetric(data: Record<string, unknown>): number | null {
  const metric = data.metric;
  return typeof metric === 'number' ? metric : null;
}

function buildEventCopy(event: SpectateEvent): string | null {
  const data = event.data || {};

  const directCopy =
    getText(data.details) ??
    getText(data.summary) ??
    getText(data.message) ??
    getText(data.reasoning) ??
    getText(data.crux_description) ??
    getText(data.verdict);

  if (directCopy) {
    return directCopy;
  }

  const metric = getMetric(data);
  switch (event.event_type) {
    case 'debate_start':
      return getText(data.task) ?? 'A new live debate just opened.';
    case 'round_start':
      return `Round ${event.round_number ?? '?'} is underway.`;
    case 'round_end':
      return `Round ${event.round_number ?? '?'} closed and the panel is reassessing.`;
    case 'proposal':
      return 'A new proposal just landed in the debate.';
    case 'critique':
      return metric === null
        ? 'An agent is challenging the current proposal.'
        : `An agent is challenging the current proposal with ${Math.round(metric * 100)}% severity.`;
    case 'vote':
      return metric === null
        ? 'Agents are voting on the strongest path forward.'
        : `The panel is voting with ${(metric * 100).toFixed(0)}% agreement pressure.`;
    case 'judge':
      return 'The judge is synthesizing the strongest arguments.';
    case 'consensus':
    case 'converged':
      return metric === null
        ? 'Consensus reached.'
        : `Consensus reached at ${(metric * 100).toFixed(0)}% confidence.`;
    case 'argument_strength':
      return metric === null
        ? 'Argument strength was rescored.'
        : `Argument strength updated to ${(metric * 100).toFixed(0)}%.`;
    case 'agent_reasoning':
      return 'An agent exposed more of its reasoning trace.';
    case 'agent_thinking':
      return 'An agent is thinking through the next move.';
    case 'crux_identified':
      return 'The system isolated the crux driving disagreement.';
    default:
      return null;
  }
}

function isNarrativeEvent(event: SpectateEvent): boolean {
  return INTERESTING_EVENT_TYPES.has(event.event_type) && Boolean(buildEventCopy(event));
}

function pickDominantDebateId(events: SpectateEvent[]): string | null {
  const grouped = new Map<string, { count: number; lastEventMs: number }>();

  for (const event of events) {
    if (!event.debate_id) continue;

    const timestamp = toEpochMs(event.timestamp) ?? 0;
    const current = grouped.get(event.debate_id);
    if (!current) {
      grouped.set(event.debate_id, { count: 1, lastEventMs: timestamp });
      continue;
    }

    current.count += 1;
    current.lastEventMs = Math.max(current.lastEventMs, timestamp);
  }

  let winner: string | null = null;
  let winnerCount = -1;
  let winnerTimestamp = -1;

  for (const [debateId, summary] of grouped.entries()) {
    if (
      summary.count > winnerCount ||
      (summary.count === winnerCount && summary.lastEventMs > winnerTimestamp)
    ) {
      winner = debateId;
      winnerCount = summary.count;
      winnerTimestamp = summary.lastEventMs;
    }
  }

  return winner;
}

function deriveTask(events: SpectateEvent[]): string {
  for (const event of events) {
    const task = getText(event.data?.task);
    if (task) return task;

    const details = getText(event.data?.details);
    if (details?.startsWith('Task:')) {
      return details.replace(/^Task:\s*/, '').replace(/\.\.\.$/, '');
    }
  }

  return FALLBACK_TASK;
}

function toTranscriptEvent(event: SpectateEvent, index: number): TranscriptEvent | null {
  const copy = buildEventCopy(event);
  if (!copy) return null;

  const metadata = EVENT_METADATA[event.event_type] ?? EVENT_METADATA.default;

  return {
    id: `${event.timestamp}-${event.event_type}-${event.agent_name ?? 'system'}-${index}`,
    label: metadata.label,
    accent: metadata.accent,
    background: metadata.background,
    eventType: event.event_type,
    agentName: event.agent_name,
    roundNumber: event.round_number,
    copy,
    source: 'live',
  };
}

export function LiveDemoSection() {
  const { theme } = useTheme();
  const { status, loaded, events } = useSpectate(undefined, undefined, {
    pollInterval: 3000,
    maxEvents: 24,
  });
  const [demoVisibleCount, setDemoVisibleCount] = useState(3);
  const isDark = theme === 'dark';
  const recentEventCount = status?.recent_event_count ?? 0;
  const recentActivityWindowSeconds = status?.recent_activity_window_seconds ?? 120;
  const activityWindowMinutes = Math.max(1, Math.round(recentActivityWindowSeconds / 60));
  const activityAgeSeconds = status?.activity_age_seconds;

  const narrativeEvents = events.filter(isNarrativeEvent);
  const dominantDebateId = pickDominantDebateId(narrativeEvents);
  const focusedLiveEvents = dominantDebateId
    ? narrativeEvents.filter((event) => event.debate_id === dominantDebateId)
    : narrativeEvents;
  const liveTranscript = focusedLiveEvents
    .slice(-7)
    .map((event, index) => toTranscriptEvent(event, index))
    .filter((event): event is TranscriptEvent => event !== null);
  const hasLiveTranscript = liveTranscript.length > 0;
  const transcriptEvents = hasLiveTranscript
    ? liveTranscript
    : FALLBACK_STREAM.slice(0, demoVisibleCount);
  const debateTask = hasLiveTranscript ? deriveTask(focusedLiveEvents) : FALLBACK_TASK;
  const spectateHref = dominantDebateId
    ? `/spectate/${encodeURIComponent(dominantDebateId)}`
    : '/spectate';
  const activeRound = transcriptEvents[transcriptEvents.length - 1]?.roundNumber ?? null;
  const participants = Array.from(
    new Set(
      transcriptEvents
        .map((event) => event.agentName)
        .filter((agentName): agentName is string => Boolean(agentName)),
    ),
  );

  useEffect(() => {
    if (hasLiveTranscript) {
      setDemoVisibleCount(3);
      return undefined;
    }

    const intervalId = window.setInterval(() => {
      setDemoVisibleCount((current) => (current >= FALLBACK_STREAM.length ? 3 : current + 1));
    }, 1500);

    return () => window.clearInterval(intervalId);
  }, [hasLiveTranscript]);

  let bridgeBadge = 'Checking public bridge';
  let bridgeSummary = 'Checking public live bridge before showing recent activity.';

  if (loaded) {
    if (!status?.active) {
      bridgeBadge = 'Bridge offline';
      bridgeSummary =
        'Public spectate is offline right now, so the sample debate below stays illustrative.';
    } else if (recentEventCount > 0) {
      bridgeBadge = 'Bridge active';
      bridgeSummary = `${recentEventCount} recent event${recentEventCount === 1 ? '' : 's'} in the last ${activityWindowMinutes} minute${activityWindowMinutes === 1 ? '' : 's'}.`;
    } else {
      bridgeBadge = 'Bridge ready';
      bridgeSummary =
        'Public spectate is online, but no recent live debate activity is visible yet.';
    }
  }

  let activityAgeLabel: string | null = null;
  if (typeof activityAgeSeconds === 'number') {
    if (activityAgeSeconds < 60) {
      activityAgeLabel = `Last activity ${Math.round(activityAgeSeconds)}s ago`;
    } else if (activityAgeSeconds < 3600) {
      activityAgeLabel = `Last activity ${Math.round(activityAgeSeconds / 60)}m ago`;
    } else {
      activityAgeLabel = `Last activity ${Math.round(activityAgeSeconds / 3600)}h ago`;
    }
  }

  return (
    <section
      data-testid="live-demo-section"
      className="px-4"
      style={{
        paddingTop: '120px',
        paddingBottom: '120px',
        borderTop: '1px solid var(--border)',
        fontFamily: 'var(--font-landing)',
      }}
    >
      <div className="max-w-4xl mx-auto">
        <p
          className="text-center uppercase tracking-widest"
          style={{
            fontSize: isDark ? '16px' : '18px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '20px',
          }}
        >
          {isDark ? '> SEE IT IN ACTION' : 'SEE IT IN ACTION'}
        </p>
        <p
          className="text-center"
          style={{
            fontSize: isDark ? '16px' : '18px',
            color: 'var(--text)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '48px',
          }}
        >
          Watch agents argue, critique, and converge without leaving the landing page.
        </p>

        <div
          data-testid="live-demo-bridge-status"
          className="flex flex-wrap items-center gap-3"
          style={{
            backgroundColor: 'var(--surface)',
            borderRadius: 'var(--radius-card)',
            border: '1px solid var(--border)',
            boxShadow: 'var(--shadow-card)',
            padding: '16px 20px',
            margin: '0 24px 20px',
          }}
        >
          <span
            className="font-bold uppercase tracking-wider"
            style={{
              fontSize: '10px',
              padding: '4px 10px',
              backgroundColor: status?.active ? 'var(--accent)' : 'var(--border)',
              color: status?.active ? 'var(--bg)' : 'var(--text)',
              borderRadius: 'var(--radius-button)',
            }}
          >
            {bridgeBadge}
          </span>
          <span
            style={{
              fontSize: isDark ? '13px' : '14px',
              color: 'var(--text)',
              fontFamily: 'var(--font-landing)',
            }}
          >
            {bridgeSummary}
          </span>
          {activityAgeLabel ? (
            <span
              className="ml-auto"
              style={{
                fontSize: '11px',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-landing)',
              }}
            >
              {activityAgeLabel}
            </span>
          ) : null}
        </div>

        <div
          data-testid="live-debate-card"
          style={{
            backgroundColor: 'var(--surface)',
            borderRadius: 'var(--radius-card)',
            border: '1px solid var(--border)',
            borderTopColor: 'var(--accent)',
            borderTopWidth: '3px',
            boxShadow: 'var(--shadow-card)',
            overflow: 'hidden',
            margin: '0 24px',
          }}
        >
          <div
            className="flex flex-wrap items-center gap-3"
            style={{ padding: '16px 20px', borderBottom: '1px solid var(--border)' }}
          >
            <span
              className="font-bold uppercase tracking-wider"
              style={{
                fontSize: '10px',
                padding: '4px 10px',
                backgroundColor: hasLiveTranscript ? 'var(--accent)' : 'var(--border)',
                color: hasLiveTranscript ? 'var(--bg)' : 'var(--text)',
                borderRadius: 'var(--radius-button)',
              }}
            >
              {hasLiveTranscript ? 'Live public debate' : 'Looping public debate'}
            </span>
            <span
              data-testid="live-debate-topic"
              className="font-medium"
              style={{ fontSize: '12px', color: 'var(--text)', fontFamily: 'var(--font-landing)' }}
            >
              {debateTask}
            </span>
            <span
              className="ml-auto"
              style={{
                fontSize: '10px',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-landing)',
              }}
            >
              {hasLiveTranscript
                ? `Streaming recent bridge events${activeRound ? ` · Round ${activeRound}` : ''}`
                : 'Streaming sample exchange while the bridge idles'}
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-[minmax(0,1.7fr)_minmax(260px,0.9fr)]">
            <div style={{ borderRight: '1px solid var(--border)' }}>
              <div
                data-testid="live-debate-transcript"
                aria-live="polite"
                style={{ display: 'grid', gap: '12px', padding: '20px' }}
              >
                {transcriptEvents.map((event, index) => (
                  <article
                    key={event.id}
                    data-testid="live-debate-event"
                    data-event-source={event.source}
                    style={{
                      border: '1px solid var(--border)',
                      borderRadius: '18px',
                      backgroundColor: event.background,
                      padding: '14px 16px',
                      boxShadow:
                        hasLiveTranscript && index === transcriptEvents.length - 1
                          ? `0 0 0 1px ${event.accent}22`
                          : 'none',
                    }}
                  >
                    <div
                      className="flex flex-wrap items-center gap-2"
                      style={{ marginBottom: '10px', fontFamily: 'var(--font-landing)' }}
                    >
                      <span
                        className="font-bold px-2 py-0.5 uppercase tracking-wider"
                        style={{
                          fontSize: '10px',
                          color: event.accent,
                          backgroundColor: 'rgba(255,255,255,0.5)',
                          borderRadius: '999px',
                        }}
                      >
                        {event.label}
                      </span>
                      {event.agentName ? (
                        <span style={{ fontSize: '12px', color: 'var(--text)', fontWeight: 700 }}>
                          {event.agentName}
                        </span>
                      ) : null}
                      {event.roundNumber ? (
                        <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                          Round {event.roundNumber}
                        </span>
                      ) : null}
                      {hasLiveTranscript && index === transcriptEvents.length - 1 ? (
                        <span
                          className="ml-auto animate-pulse"
                          style={{
                            fontSize: '10px',
                            color: event.accent,
                            textTransform: 'uppercase',
                            letterSpacing: '0.12em',
                          }}
                        >
                          Now streaming
                        </span>
                      ) : null}
                    </div>
                    <p
                      style={{
                        fontSize: '13px',
                        lineHeight: '1.7',
                        color: 'var(--text)',
                        fontFamily: 'var(--font-landing)',
                        margin: 0,
                      }}
                    >
                      {event.copy}
                    </p>
                  </article>
                ))}
              </div>
            </div>

            <div style={{ padding: '20px', display: 'grid', gap: '18px', alignContent: 'start' }}>
              <div>
                <p
                  className="uppercase tracking-widest"
                  style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '10px' }}
                >
                  Stream source
                </p>
                <div className="flex items-center gap-2" style={{ marginBottom: '10px' }}>
                  <div
                    className="w-2 h-2 rounded-full"
                    style={{ backgroundColor: hasLiveTranscript ? 'var(--accent)' : '#64748b' }}
                  />
                  <span
                    className="text-xs font-bold uppercase tracking-wider"
                    style={{
                      color: hasLiveTranscript ? 'var(--accent)' : 'var(--text)',
                      fontFamily: 'var(--font-landing)',
                    }}
                  >
                    {hasLiveTranscript ? 'Public spectate bridge' : 'Live fallback preview'}
                  </span>
                </div>
                <p
                  style={{
                    fontSize: '12px',
                    color: 'var(--text-muted)',
                    fontFamily: 'var(--font-landing)',
                    lineHeight: '1.7',
                    margin: 0,
                  }}
                >
                  {hasLiveTranscript
                    ? 'The transcript on the left is populated from recent public spectate events, refreshing every few seconds.'
                    : 'No public debate is active right now, so the landing page loops a sample exchange instead of going blank.'}
                </p>
              </div>

              <div>
                <p
                  className="uppercase tracking-widest"
                  style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '10px' }}
                >
                  Agents on stage
                </p>
                <div className="flex flex-wrap gap-2">
                  {participants.map((participant) => (
                    <span
                      key={participant}
                      style={{
                        border: '1px solid var(--border)',
                        borderRadius: '999px',
                        padding: '6px 10px',
                        fontSize: '11px',
                        color: 'var(--text)',
                        fontFamily: 'var(--font-landing)',
                      }}
                    >
                      {participant}
                    </span>
                  ))}
                </div>
              </div>

              <div
                style={{
                  border: '1px solid var(--border)',
                  borderRadius: '18px',
                  padding: '14px 16px',
                  backgroundColor: 'rgba(15, 23, 42, 0.03)',
                }}
              >
                <p
                  className="uppercase tracking-widest"
                  style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '8px' }}
                >
                  What visitors see
                </p>
                <p
                  style={{
                    fontSize: '12px',
                    color: 'var(--text)',
                    lineHeight: '1.7',
                    fontFamily: 'var(--font-landing)',
                    margin: 0,
                  }}
                >
                  Proposal, critique, reasoning, and consensus events land in-order so visitors can
                  follow the argument instead of reading a static summary.
                </p>
              </div>
            </div>
          </div>
        </div>

        <div className="text-center mt-12 flex flex-wrap justify-center gap-4">
          <Link
            href={spectateHref}
            className="text-sm font-semibold transition-all hover:scale-[1.02] cursor-pointer"
            style={{
              display: 'inline-block',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-button)',
              color: 'var(--text)',
              backgroundColor: 'var(--surface)',
              fontFamily: 'var(--font-landing)',
              padding: '18px 32px',
            }}
          >
            {hasLiveTranscript ? 'Watch this debate live' : 'Open full spectate view'}
          </Link>
          <Link
            href="/demo"
            className="text-sm font-semibold transition-all hover:scale-[1.02] cursor-pointer"
            style={{
              display: 'inline-block',
              border: '1px solid var(--accent)',
              borderRadius: 'var(--radius-button)',
              color: 'var(--accent)',
              backgroundColor: 'transparent',
              fontFamily: 'var(--font-landing)',
              padding: '18px 48px',
            }}
          >
            Run your own debate
          </Link>
        </div>
      </div>
    </section>
  );
}
