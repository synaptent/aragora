'use client';

import Link from 'next/link';

import { EmptyState } from '@/components/ui/EmptyState';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { useAgentBridgeRuns } from '@/hooks/useAgentBridgeRuns';

import type { AgentBridgeRunSummary } from './types';
import { formatBridgeTimestamp } from './types';

function getRunStatusVariant(status: AgentBridgeRunSummary['status']) {
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

function renderParticipants(run: AgentBridgeRunSummary) {
  return (
    <div className="flex flex-wrap gap-2">
      {run.participants.map((participant) => (
        <span
          key={`${run.run_id}-${participant.role}`}
          className="rounded border border-white/10 bg-black/20 px-2 py-1 text-xs text-white/70"
        >
          {participant.role} · {participant.harness}
        </span>
      ))}
    </div>
  );
}

export function BridgeRunList() {
  const { runs, hasMore, isLoading, isLoadingMore, error, errorStatus, loadMore, retry } =
    useAgentBridgeRuns();

  if (errorStatus === 403) {
    throw new Error('Forbidden: agent_bridge:read');
  }

  return (
    <div className="space-y-4">
      {error ? (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
          Bridge API unreachable
          <button onClick={retry} className="ml-3 underline underline-offset-2 hover:no-underline">
            Retry
          </button>
        </div>
      ) : null}

      {isLoading ? <div className="text-sm text-white/50">Loading bridge runs…</div> : null}

      {!isLoading && runs.length === 0 ? (
        <EmptyState
          title="No agent-bridge runs yet"
          description="Read-only bridge runs will appear here as soon as the broker writes them."
        />
      ) : null}

      {runs.length > 0 ? (
        <div className="overflow-hidden rounded-xl border border-white/10 bg-white/5">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-white/10">
              <thead className="bg-black/20">
                <tr className="text-left text-xs uppercase tracking-[0.2em] text-white/35">
                  <th className="px-4 py-3">run_id</th>
                  <th className="px-4 py-3">status</th>
                  <th className="px-4 py-3">active_role</th>
                  <th className="px-4 py-3">participants</th>
                  <th className="px-4 py-3">updated_at</th>
                  <th className="px-4 py-3">turn_count</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {runs.map((run) => (
                  <tr key={run.run_id} className="align-top text-sm text-white/80">
                    <td className="px-4 py-4 font-theme-data">
                      <Link
                        href={`/autonomous/bridge/${run.run_id}`}
                        className="text-white transition-colors hover:text-[var(--accent)]"
                      >
                        {run.run_id}
                      </Link>
                    </td>
                    <td className="px-4 py-4">
                      <StatusBadge label={run.status} variant={getRunStatusVariant(run.status)} />
                    </td>
                    <td className="px-4 py-4">{run.next_actor ?? 'none'}</td>
                    <td className="px-4 py-4">{renderParticipants(run)}</td>
                    <td className="px-4 py-4 text-white/60">
                      {formatBridgeTimestamp(run.updated_at)}
                    </td>
                    <td className="px-4 py-4">{run.last_turn_index}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}

      {hasMore ? (
        <div className="flex justify-center">
          <button
            type="button"
            onClick={loadMore}
            disabled={isLoadingMore}
            className="rounded border border-white/10 px-4 py-2 text-sm text-white/70 transition-colors hover:border-white/20 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isLoadingMore ? 'Loading…' : 'Load more'}
          </button>
        </div>
      ) : null}
    </div>
  );
}
