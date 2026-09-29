'use client';

import EmptyState from '@/components/ui/EmptyState';
import { StatusBadge } from '@/components/shared/StatusBadge';

import type {
  AgentBridgeEvent,
  AgentBridgeFooter,
  BridgeApiError,
  BridgeParseStatus,
} from './types';
import {
  formatBridgeTimestamp,
  getBridgeStringArray,
  isBridgeRecord,
  truncateBridgeSessionId,
} from './types';

interface BridgeEventStreamProps {
  events: AgentBridgeEvent[];
  isLoading?: boolean;
  error?: BridgeApiError | null;
}

function getParseStatusVariant(parseStatus: BridgeParseStatus | null) {
  switch (parseStatus) {
    case 'ok':
      return 'success' as const;
    case 'missing':
      return 'warning' as const;
    case 'malformed':
      return 'error' as const;
    default:
      return 'neutral' as const;
  }
}

function readFooter(payload: Record<string, unknown>): AgentBridgeFooter | null {
  const footer = payload.footer;
  if (!isBridgeRecord(footer)) {
    return null;
  }

  const summary = footer.summary;
  const nextActor = footer.next_actor;
  const needsHuman = footer.needs_human;
  const done = footer.done;
  const artifacts = getBridgeStringArray(footer.artifacts);
  const testsRun = getBridgeStringArray(footer.tests_run);

  if (
    typeof summary !== 'string' ||
    (nextActor !== null && typeof nextActor !== 'string') ||
    typeof needsHuman !== 'boolean' ||
    typeof done !== 'boolean'
  ) {
    return null;
  }

  return {
    summary,
    next_actor: nextActor,
    needs_human: needsHuman,
    done,
    artifacts,
    tests_run: testsRun,
  };
}

function buildEventSummary(event: AgentBridgeEvent): string {
  const footer = readFooter(event.payload);
  if (footer?.summary) {
    return footer.summary;
  }

  const reason = event.payload.reason;
  if (typeof reason === 'string' && reason.length > 0) {
    return reason;
  }

  const messageText = event.payload.message_text;
  if (typeof messageText === 'string' && messageText.length > 0) {
    return messageText;
  }

  return event.event_type;
}

export function BridgeEventStream({
  events,
  isLoading = false,
  error = null,
}: BridgeEventStreamProps) {
  if (error) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
        Bridge API unreachable
      </div>
    );
  }

  if (isLoading && events.length === 0) {
    return <div className="text-sm text-white/50">Loading events…</div>;
  }

  if (events.length === 0) {
    return (
      <EmptyState title="No bridge events yet" description="Event records will appear here." />
    );
  }

  return (
    <div className="max-h-[34rem] space-y-3 overflow-y-auto pr-1">
      {events.map((event) => (
        <article key={event.event_id} className="rounded-xl border border-white/10 bg-white/5 p-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <StatusBadge label={event.event_type} variant="neutral" />
              <StatusBadge
                label={event.parse_status ?? 'n/a'}
                variant={getParseStatusVariant(event.parse_status)}
              />
            </div>
            <div className="text-xs text-white/45">{formatBridgeTimestamp(event.ts)}</div>
          </div>

          <div className="mt-3 text-sm text-white/80">{buildEventSummary(event)}</div>

          <div className="mt-3 flex flex-wrap gap-3 text-xs text-white/50">
            <span>role: {event.role}</span>
            <span>harness: {event.harness}</span>
            <span>turn: {event.turn_index}</span>
            <span title={event.session_id ?? ''}>
              session: {truncateBridgeSessionId(event.session_id)}
            </span>
          </div>
        </article>
      ))}
    </div>
  );
}
