'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';
import { STAGE_COLORS, type DAGNodeData, type DAGStage } from '@/hooks/useUnifiedDAG';

/** Status color mapping for execution states. */
const STATUS_CONFIG: Record<string, { ring: string; bg: string; label: string; pulse: boolean }> = {
  pending: { ring: '#6b7280', bg: 'bg-gray-500/15', label: 'Pending', pulse: false },
  ready: { ring: '#3b82f6', bg: 'bg-blue-500/15', label: 'Ready', pulse: false },
  running: { ring: '#f59e0b', bg: 'bg-amber-500/15', label: 'Running', pulse: true },
  in_progress: { ring: '#f59e0b', bg: 'bg-amber-500/15', label: 'Running', pulse: true },
  succeeded: { ring: '#10b981', bg: 'bg-emerald-500/15', label: 'Done', pulse: false },
  completed: { ring: '#10b981', bg: 'bg-emerald-500/15', label: 'Done', pulse: false },
  approved: { ring: '#10b981', bg: 'bg-emerald-500/15', label: 'Done', pulse: false },
  failed: { ring: '#ef4444', bg: 'bg-red-500/15', label: 'Failed', pulse: false },
  rejected: { ring: '#ef4444', bg: 'bg-red-500/15', label: 'Failed', pulse: false },
  blocked: { ring: '#6b7280', bg: 'bg-gray-500/10', label: 'Blocked', pulse: false },
  partial: { ring: '#f59e0b', bg: 'bg-amber-500/10', label: 'Partial', pulse: false },
  active: { ring: '#3b82f6', bg: 'bg-blue-500/15', label: 'Ready', pulse: false },
};

/** Stage-specific icons for node headers. */
const STAGE_ICONS: Record<DAGStage, string> = {
  ideas: '\u2726', // four-pointed star
  principles: '\u25C8', // diamond
  goals: '\u25CE', // bullseye
  actions: '\u2611', // ballot box with check
  orchestration: '\u2699', // gear
};

interface ExecutionDAGNodeProps extends NodeProps {
  onExecuteNode?: (nodeId: string) => void;
}

/**
 * ExecutionDAGNode renders any pipeline node with execution status
 * indicators, an inline run button, and stage-colored styling.
 */
export function ExecutionDAGNode({ id, data, selected, onExecuteNode }: ExecutionDAGNodeProps) {
  const nodeData = data as unknown as DAGNodeData;
  const stage = nodeData.stage || 'ideas';
  const status = nodeData.status || 'pending';
  const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.pending;
  const stageColor = STAGE_COLORS[stage] || '#6366f1';
  const icon = STAGE_ICONS[stage];
  const agents = (nodeData.metadata?.agents as string[]) || [];
  const progress = (nodeData.metadata?.progress as number) || 0;
  const executeHandler =
    onExecuteNode ??
    (typeof nodeData.onExecuteNode === 'function'
      ? (nodeData.onExecuteNode as (nodeId: string) => void)
      : undefined);

  return (
    <div
      className={`relative rounded-lg border-2 shadow-md bg-surface min-w-[180px] max-w-[240px] transition-all ${
        selected ? 'ring-2 ring-indigo-400/60' : ''
      } ${cfg.pulse ? 'animate-pulse' : ''}`}
      style={{ borderColor: stageColor }}
      data-testid={`dag-node-${id}`}
    >
      <Handle type="target" position={Position.Left} className="!bg-indigo-400" />

      {/* Header */}
      <div
        className="flex items-center gap-1.5 px-3 py-1.5 rounded-t-md text-[10px] font-theme-data font-bold uppercase tracking-wider"
        style={{ background: `${stageColor}18`, color: stageColor }}
      >
        <span>{icon}</span>
        <span>{stage}</span>
        {nodeData.subtype && <span className="ml-auto opacity-60">{nodeData.subtype}</span>}
      </div>

      {/* Body */}
      <div className="px-3 py-2 space-y-1.5">
        <div className="text-sm font-medium text-text truncate" title={nodeData.label}>
          {nodeData.label}
        </div>
        {nodeData.description && (
          <div className="text-[11px] text-text-muted line-clamp-2">{nodeData.description}</div>
        )}

        {/* Agents row (orchestration stage) */}
        {agents.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-1">
            {agents.slice(0, 3).map((a) => (
              <span
                key={a}
                className="px-1.5 py-0.5 text-[10px] font-theme-data rounded bg-pink-500/15 text-pink-300 border border-pink-500/20"
              >
                {a}
              </span>
            ))}
            {agents.length > 3 && (
              <span className="text-[10px] font-theme-data text-text-muted">
                +{agents.length - 3}
              </span>
            )}
          </div>
        )}
      </div>

      {/* Footer: status + run */}
      <div className="flex items-center justify-between px-3 py-1.5 border-t border-border">
        <div className="flex items-center gap-1.5">
          {/* Status dot */}
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: cfg.ring }}
            data-testid={`status-${status}`}
          />
          <span className="text-[10px] font-theme-data text-text-muted">{cfg.label}</span>
        </div>

        {/* Progress bar for running nodes */}
        {status === 'running' && progress > 0 && (
          <div className="flex-1 mx-2 h-1 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-amber-400 rounded-full transition-all"
              style={{ width: `${Math.min(100, progress)}%` }}
            />
          </div>
        )}

        {/* Inline execute button for ready/failed nodes */}
        {(status === 'ready' || status === 'failed') && executeHandler && (
          <button
            onClick={(e) => {
              e.stopPropagation();
              executeHandler(id);
            }}
            className="px-2 py-0.5 text-[10px] font-theme-data rounded bg-emerald-600/20 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-600/40 transition-colors"
            title={status === 'failed' ? 'Retry execution' : 'Execute this node'}
            data-testid={`run-btn-${id}`}
          >
            {status === 'failed' ? 'Retry' : 'Run'}
          </button>
        )}
      </div>

      <Handle type="source" position={Position.Right} className="!bg-indigo-400" />
    </div>
  );
}
