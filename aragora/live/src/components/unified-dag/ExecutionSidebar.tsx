'use client';

/**
 * ExecutionSidebar - Right-hand panel for DAG execution controls.
 *
 * Shows graph validation status, batch execution controls, per-stage
 * progress, and execution history.
 */

import { useMemo } from 'react';
import type { Node } from '@xyflow/react';
import { DAG_STAGES, STAGE_COLORS, type DAGNodeData, type DAGStage } from '@/hooks/useUnifiedDAG';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ExecutionHistoryEntry {
  id: string;
  nodeId: string;
  nodeLabel: string;
  status: 'succeeded' | 'failed';
  durationMs: number;
  timestamp: number;
}

interface ExecutionSidebarProps {
  nodes: Node<DAGNodeData>[];
  executing: boolean;
  onExecuteAll: () => void;
  onAutoAdvance: () => void;
  onValidate: () => void;
  validationErrors: string[];
  executionHistory: ExecutionHistoryEntry[];
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface StageSummary {
  stage: DAGStage;
  total: number;
  ready: number;
  running: number;
  succeeded: number;
  failed: number;
  blocked: number;
  pending: number;
}

function computeStageSummaries(nodes: Node<DAGNodeData>[]): StageSummary[] {
  return DAG_STAGES.map((stage) => {
    const stageNodes = nodes.filter((n) => (n.data as unknown as DAGNodeData).stage === stage);
    const counts = { ready: 0, running: 0, succeeded: 0, failed: 0, blocked: 0, pending: 0 };
    for (const n of stageNodes) {
      const s = (n.data as unknown as DAGNodeData).status || 'pending';
      if (s in counts) counts[s as keyof typeof counts]++;
      else counts.pending++;
    }
    return { stage, total: stageNodes.length, ...counts };
  });
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function ExecutionSidebar({
  nodes,
  executing,
  onExecuteAll,
  onAutoAdvance,
  onValidate,
  validationErrors,
  executionHistory,
  onClose,
}: ExecutionSidebarProps) {
  const summaries = useMemo(() => computeStageSummaries(nodes), [nodes]);
  const totalNodes = nodes.length;
  const succeededNodes = nodes.filter(
    (n) => (n.data as unknown as DAGNodeData).status === 'succeeded',
  ).length;
  const readyNodes = nodes.filter(
    (n) => (n.data as unknown as DAGNodeData).status === 'ready',
  ).length;
  const completionPct = totalNodes > 0 ? Math.round((succeededNodes / totalNodes) * 100) : 0;

  return (
    <aside
      className="w-80 h-full border-l border-border bg-surface flex-shrink-0 overflow-y-auto"
      data-testid="execution-sidebar"
    >
      <div className="p-4 space-y-5">
        {/* Header */}
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-theme-data font-bold text-text uppercase tracking-wide">
            Execution
          </h3>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text text-xs font-theme-data"
            title="Close"
          >
            {'\u00D7'}
          </button>
        </div>

        {/* Overall progress */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs font-theme-data text-text-muted">
            <span>Overall Progress</span>
            <span className="text-text">{completionPct}%</span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-emerald-500 rounded-full transition-all duration-500"
              style={{ width: `${completionPct}%` }}
              data-testid="progress-bar"
            />
          </div>
          <div className="flex items-center justify-between text-[10px] font-theme-data text-text-muted">
            <span>
              {succeededNodes}/{totalNodes} nodes complete
            </span>
            <span>{readyNodes} ready</span>
          </div>
        </div>

        {/* Stage breakdown */}
        <div className="space-y-2">
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
            Stage Progress
          </h4>
          {summaries.map((s) => {
            const color = STAGE_COLORS[s.stage];
            const pct = s.total > 0 ? Math.round((s.succeeded / s.total) * 100) : 0;
            return (
              <div key={s.stage} className="space-y-1">
                <div className="flex items-center justify-between text-xs font-theme-data">
                  <span style={{ color }} className="capitalize font-bold">
                    {s.stage}
                  </span>
                  <span className="text-text-muted">
                    {s.succeeded}/{s.total}
                  </span>
                </div>
                <div className="h-1.5 bg-gray-700/50 rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${pct}%`, background: color }}
                  />
                </div>
                {/* Mini status counts */}
                <div className="flex gap-2 text-[9px] font-theme-data text-text-muted">
                  {s.running > 0 && <span className="text-amber-400">{s.running} running</span>}
                  {s.ready > 0 && <span className="text-blue-400">{s.ready} ready</span>}
                  {s.failed > 0 && <span className="text-red-400">{s.failed} failed</span>}
                  {s.blocked > 0 && <span>{s.blocked} blocked</span>}
                </div>
              </div>
            );
          })}
        </div>

        {/* Validation */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
              Validation
            </h4>
            <button
              onClick={onValidate}
              className="px-2 py-0.5 text-[10px] font-theme-data rounded bg-indigo-600/20 text-indigo-300 border border-indigo-500/30 hover:bg-indigo-600/40 transition-colors"
            >
              Check
            </button>
          </div>
          {validationErrors.length === 0 ? (
            <div className="flex items-center gap-1.5 text-xs font-theme-data text-emerald-400">
              <span>{'\u2713'}</span>
              <span>Graph is valid and executable</span>
            </div>
          ) : (
            <div className="space-y-1">
              {validationErrors.map((err, i) => (
                <div
                  key={i}
                  className="flex items-start gap-1.5 text-[11px] font-theme-data text-red-400"
                >
                  <span className="mt-0.5">{'\u2717'}</span>
                  <span>{err}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Batch controls */}
        <div className="space-y-2 pt-2 border-t border-border">
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
            Batch Operations
          </h4>
          <button
            onClick={onExecuteAll}
            disabled={executing || readyNodes === 0}
            className="w-full px-3 py-2 text-sm font-theme-data rounded bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            data-testid="execute-all-btn"
          >
            {executing ? 'Executing...' : `Execute All Ready (${readyNodes})`}
          </button>
          <button
            onClick={onAutoAdvance}
            disabled={executing || totalNodes === 0}
            className="w-full px-3 py-2 text-sm font-theme-data rounded bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            data-testid="auto-advance-btn"
          >
            {executing ? 'Advancing...' : 'Auto-Advance All Stages'}
          </button>
          <p className="text-[10px] font-theme-data text-text-muted">
            Auto-advance decomposes ideas, sets goals, creates actions, assigns agents, and executes
            the full pipeline.
          </p>
        </div>

        {/* Execution history */}
        {executionHistory.length > 0 && (
          <div className="space-y-2 pt-2 border-t border-border">
            <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
              Recent Executions
            </h4>
            <div className="space-y-1 max-h-48 overflow-y-auto">
              {executionHistory.slice(0, 20).map((entry) => (
                <div
                  key={entry.id}
                  className="flex items-center justify-between px-2 py-1 rounded bg-bg/50 text-[11px] font-theme-data"
                >
                  <div className="flex items-center gap-1.5 truncate">
                    <span
                      className={`inline-block w-1.5 h-1.5 rounded-full ${
                        entry.status === 'succeeded' ? 'bg-emerald-400' : 'bg-red-400'
                      }`}
                    />
                    <span className="text-text truncate">{entry.nodeLabel}</span>
                  </div>
                  <span className="text-text-muted ml-2 flex-shrink-0">
                    {formatDuration(entry.durationMs)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  );
}

export type { ExecutionHistoryEntry };
