'use client';

import ReactMarkdown from 'react-markdown';

import EmptyState from '@/components/ui/EmptyState';
import { StatusBadge } from '@/components/shared/StatusBadge';

import type { AgentBridgeTurnRecord, BridgeApiError, BridgeParseStatus } from './types';
import { formatBridgeTimestamp } from './types';

interface BridgeTranscriptViewProps {
  turns: AgentBridgeTurnRecord[];
  isLoading?: boolean;
  error?: BridgeApiError | null;
}

function getParseStatusVariant(parseStatus: BridgeParseStatus) {
  switch (parseStatus) {
    case 'ok':
      return 'success' as const;
    case 'missing':
      return 'warning' as const;
    case 'malformed':
      return 'error' as const;
  }
}

export function BridgeTranscriptView({
  turns,
  isLoading = false,
  error = null,
}: BridgeTranscriptViewProps) {
  const orderedTurns = [...turns].sort((left, right) => left.turn_index - right.turn_index);

  if (error) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
        Bridge API unreachable
      </div>
    );
  }

  if (isLoading && orderedTurns.length === 0) {
    return <div className="text-sm text-white/50">Loading transcript…</div>;
  }

  if (orderedTurns.length === 0) {
    return (
      <EmptyState title="No transcript turns yet" description="Bridge turns will appear here." />
    );
  }

  return (
    <div className="space-y-4">
      {orderedTurns.map((turn) => (
        <article
          key={`${turn.turn_index}-${turn.author_role}`}
          className="rounded-xl border border-white/10 bg-white/5 p-4"
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="text-xs uppercase tracking-[0.2em] text-white/35">
                Turn {turn.turn_index}
              </div>
              <h3 className="mt-1 text-lg text-white">{turn.author_role}</h3>
              <div className="mt-1 text-xs text-white/45">
                {formatBridgeTimestamp(turn.started_at)} to{' '}
                {formatBridgeTimestamp(turn.completed_at)}
              </div>
            </div>
            <StatusBadge
              label={turn.parse_status}
              variant={getParseStatusVariant(turn.parse_status)}
            />
          </div>

          <div className="mt-4 rounded-lg border border-white/10 bg-black/20 p-4">
            <div className="mb-2 text-xs uppercase tracking-[0.2em] text-white/35">Message</div>
            {turn.body_markdown ? (
              <div className="prose prose-invert max-w-none text-sm text-white/80">
                <ReactMarkdown>{turn.body_markdown}</ReactMarkdown>
              </div>
            ) : (
              <div className="text-sm text-white/45">No parsed message captured.</div>
            )}
          </div>

          <div className="mt-4 rounded-lg border border-white/10 bg-white/[0.03] p-4">
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <div className="text-xs uppercase tracking-[0.2em] text-white/35">Bridge Footer</div>
              <StatusBadge
                label={turn.parse_status}
                variant={getParseStatusVariant(turn.parse_status)}
              />
            </div>

            {turn.footer ? (
              <div className="space-y-3 text-sm text-white/80">
                <div>
                  <div className="text-xs uppercase tracking-[0.2em] text-white/35">Summary</div>
                  <p className="mt-1">{turn.footer.summary}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <StatusBadge
                    label={`next_actor: ${turn.footer.next_actor ?? 'null'}`}
                    variant="neutral"
                  />
                  <StatusBadge
                    label={turn.footer.done ? 'done: true' : 'done: false'}
                    variant={turn.footer.done ? 'success' : 'neutral'}
                  />
                  <StatusBadge
                    label={turn.footer.needs_human ? 'needs_human: true' : 'needs_human: false'}
                    variant={turn.footer.needs_human ? 'warning' : 'neutral'}
                  />
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-white/35">
                      Artifacts
                    </div>
                    <div className="mt-1 text-white/70">
                      {turn.footer.artifacts.length > 0 ? turn.footer.artifacts.join(', ') : 'None'}
                    </div>
                  </div>
                  <div>
                    <div className="text-xs uppercase tracking-[0.2em] text-white/35">
                      Tests Run
                    </div>
                    <div className="mt-1 text-white/70">
                      {turn.footer.tests_run.length > 0 ? turn.footer.tests_run.join(', ') : 'None'}
                    </div>
                  </div>
                </div>
              </div>
            ) : (
              <div className="text-sm text-white/55">
                No valid bridge footer was parsed for this turn.
              </div>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
