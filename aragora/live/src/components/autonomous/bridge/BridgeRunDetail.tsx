'use client';

import { TabPanel, Tabs } from '@/components/Tabs';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { BridgeEventStream } from '@/components/autonomous/bridge/BridgeEventStream';
import { BridgeOperatorActions } from '@/components/autonomous/bridge/BridgeOperatorActions';
import { BridgeRoleCard } from '@/components/autonomous/bridge/BridgeRoleCard';
import { BridgeTranscriptView } from '@/components/autonomous/bridge/BridgeTranscriptView';
import { useAgentBridgeEvents } from '@/hooks/useAgentBridgeEvents';
import { useAgentBridgeRun } from '@/hooks/useAgentBridgeRun';
import { useAgentBridgeTranscript } from '@/hooks/useAgentBridgeTranscript';

import type { AgentBridgeRunDetail } from './types';
import { formatBridgeTimestamp } from './types';

interface BridgeRunDetailProps {
  runId: string;
}

function getRunStatusVariant(status: AgentBridgeRunDetail['status']) {
  switch (status) {
    case 'running':
      return 'info' as const;
    case 'awaiting_human':
      return 'warning' as const;
    case 'completed':
      return 'success' as const;
    case 'failed':
      return 'error' as const;
  }
}

function buildRunJsonView(run: AgentBridgeRunDetail) {
  return {
    schema_version: run.schema_version,
    run_id: run.run_id,
    task: run.task,
    status: run.status,
    created_at: run.created_at,
    updated_at: run.updated_at,
    completed_at: run.completed_at,
    last_turn_index: run.last_turn_index,
    next_actor: run.next_actor,
    repair_budget_per_turn: run.repair_budget_per_turn,
    footer_mode: run.footer_mode,
    worktree_cleanup_mode: run.worktree_cleanup_mode,
    participants: run.participants,
    worktree_path: run.worktree_path,
    worktree_agent_slug: run.worktree_agent_slug,
    last_event_id: run.last_event_id,
  };
}

function buildSessionsJsonView(run: AgentBridgeRunDetail) {
  return {
    schema_version: run.schema_version,
    run_id: run.run_id,
    updated_at: run.updated_at,
    sessions: run.roles,
  };
}

function orderedRoleEntries(run: AgentBridgeRunDetail) {
  const orderedEntries = run.participants
    .map((participant) => [participant.role, run.roles[participant.role]] as const)
    .filter((entry): entry is [string, AgentBridgeRunDetail['roles'][string]] => Boolean(entry[1]));

  const seenRoles = new Set(orderedEntries.map(([role]) => role));
  const remainingEntries = Object.entries(run.roles).filter(([role]) => !seenRoles.has(role));

  return [...orderedEntries, ...remainingEntries];
}

export function BridgeRunDetail({ runId }: BridgeRunDetailProps) {
  const runQuery = useAgentBridgeRun(runId, { enabled: Boolean(runId) });
  const shouldPoll = runQuery.run?.status === 'running';
  const eventsQuery = useAgentBridgeEvents(runId, {
    enabled: Boolean(runId),
    poll: shouldPoll,
    limit: 500,
  });
  const transcriptQuery = useAgentBridgeTranscript(runId, {
    enabled: Boolean(runId),
    poll: shouldPoll,
  });

  if (
    runQuery.errorStatus === 403 ||
    eventsQuery.errorStatus === 403 ||
    transcriptQuery.errorStatus === 403
  ) {
    throw new Error('Forbidden: agent_bridge:read');
  }

  if (runQuery.isLoading && !runQuery.run) {
    return <div className="text-sm text-white/50">Loading bridge run…</div>;
  }

  if (runQuery.error && !runQuery.run) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
        Bridge API unreachable
        <button
          onClick={runQuery.retry}
          className="ml-3 underline underline-offset-2 hover:no-underline"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!runQuery.run) {
    return null;
  }

  const run = runQuery.run;
  const roleEntries = orderedRoleEntries(run);
  const runJson = buildRunJsonView(run);
  const sessionsJson = buildSessionsJsonView(run);

  return (
    <div className="space-y-6">
      <section className="rounded-xl border border-white/10 bg-white/5 p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs uppercase tracking-[0.25em] text-white/35">
              Agent Bridge Run
            </div>
            <h1 className="mt-1 text-3xl font-theme-display text-white">{run.run_id}</h1>
            <p className="mt-2 max-w-3xl text-sm text-white/60">{run.task}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <StatusBadge label={run.status} variant={getRunStatusVariant(run.status)} size="md" />
            <StatusBadge label={run.footer_mode} variant="neutral" size="md" />
          </div>
        </div>

        <div className="mt-5 grid gap-4 md:grid-cols-2">
          <div className="rounded-lg border border-white/10 bg-black/20 p-4">
            <div className="text-xs uppercase tracking-[0.2em] text-white/35">Worktree path</div>
            <div className="mt-2 break-all text-sm text-white/80">{run.worktree_path ?? 'n/a'}</div>
          </div>
          <div className="rounded-lg border border-white/10 bg-black/20 p-4">
            <div className="text-xs uppercase tracking-[0.2em] text-white/35">Active role</div>
            <div className="mt-2 text-sm text-white/80">{run.next_actor ?? 'none'}</div>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-4 text-xs text-white/50">
          <span>created: {formatBridgeTimestamp(run.created_at)}</span>
          <span>updated: {formatBridgeTimestamp(run.updated_at)}</span>
          <span>turns: {run.last_turn_index}</span>
          <span>cleanup: {run.worktree_cleanup_mode}</span>
        </div>
      </section>

      <BridgeOperatorActions
        run={run}
        onDispatched={() => {
          runQuery.retry();
          eventsQuery.retry();
          transcriptQuery.retry();
        }}
      />

      <section className="space-y-3">
        <div className="text-xs uppercase tracking-[0.25em] text-white/35">
          Participant sessions
        </div>
        <div className="grid gap-4 lg:grid-cols-2">
          {roleEntries.map(([role, session]) => (
            <BridgeRoleCard key={role} role={role} session={session} />
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-white/10 bg-white/5 p-5">
        <Tabs
          ariaLabel="Bridge run detail tabs"
          defaultTab="transcript"
          tabs={[
            { id: 'transcript', label: 'Transcript', badge: transcriptQuery.turns.length },
            { id: 'events', label: 'Events', badge: eventsQuery.events.length },
            { id: 'metadata', label: 'Metadata' },
          ]}
          variant="underline"
        >
          <TabPanel tabId="transcript">
            <BridgeTranscriptView
              turns={transcriptQuery.turns}
              isLoading={transcriptQuery.isLoading}
              error={transcriptQuery.error}
            />
          </TabPanel>

          <TabPanel tabId="events">
            <BridgeEventStream
              events={eventsQuery.events}
              isLoading={eventsQuery.isLoading}
              error={eventsQuery.error}
            />
          </TabPanel>

          <TabPanel tabId="metadata">
            <div className="grid gap-4 lg:grid-cols-2">
              <div className="rounded-lg border border-white/10 bg-black/20 p-4">
                <div className="mb-3 text-xs uppercase tracking-[0.2em] text-white/35">
                  run.json
                </div>
                <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-all text-xs text-white/70">
                  {JSON.stringify(runJson, null, 2)}
                </pre>
              </div>
              <div className="rounded-lg border border-white/10 bg-black/20 p-4">
                <div className="mb-3 text-xs uppercase tracking-[0.2em] text-white/35">
                  sessions.json
                </div>
                <pre className="max-h-[32rem] overflow-auto whitespace-pre-wrap break-all text-xs text-white/70">
                  {JSON.stringify(sessionsJson, null, 2)}
                </pre>
              </div>
            </div>
          </TabPanel>
        </Tabs>
      </section>
    </div>
  );
}
