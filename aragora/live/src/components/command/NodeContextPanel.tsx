'use client';

import { useMemo } from 'react';
import type { DAGStage } from '@/hooks/useUnifiedDAG';
import type { StreamEvent } from '@/hooks/useEventStream';

interface NodeData {
  id: string;
  label: string;
  description: string;
  stage: DAGStage;
  subtype: string;
  status: string;
  priority: number;
  metadata: Record<string, unknown>;
}

interface NodeContextPanelProps {
  node: NodeData;
  events: StreamEvent[];
  onAction: (action: string, nodeId: string) => void;
  onClose: () => void;
}

const STAGE_CONFIG: Record<
  DAGStage,
  {
    color: string;
    bg: string;
    border: string;
    actions: { label: string; action: string; icon: string }[];
  }
> = {
  ideas: {
    color: 'text-indigo-400',
    bg: 'bg-indigo-500/10',
    border: 'border-indigo-500/30',
    actions: [
      { label: 'Debate This', action: 'debate', icon: '\u2694' },
      { label: 'Decompose', action: 'decompose', icon: '\u2702' },
      { label: 'Find Precedents', action: 'precedents', icon: '\uD83D\uDD0D' },
    ],
  },
  principles: {
    color: 'text-violet-400',
    bg: 'bg-violet-500/10',
    border: 'border-violet-500/30',
    actions: [
      { label: 'Debate This', action: 'debate', icon: '\u2694' },
      { label: 'Validate', action: 'validate', icon: '\uD83D\uDEE1' },
      { label: 'Find Precedents', action: 'precedents', icon: '\uD83D\uDD0D' },
    ],
  },
  goals: {
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
    actions: [
      { label: 'Prioritize', action: 'prioritize', icon: '\u2195' },
      { label: 'Create Tasks', action: 'decompose', icon: '\u2702' },
      { label: 'Validate', action: 'validate', icon: '\uD83D\uDEE1' },
    ],
  },
  actions: {
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
    actions: [
      { label: 'Assign Agent', action: 'assign', icon: '\uD83D\uDC64' },
      { label: 'Execute', action: 'execute', icon: '\u25B6' },
      { label: 'Validate', action: 'validate', icon: '\uD83D\uDEE1' },
    ],
  },
  orchestration: {
    color: 'text-pink-400',
    bg: 'bg-pink-500/10',
    border: 'border-pink-500/30',
    actions: [
      { label: 'Start', action: 'execute', icon: '\u25B6' },
      { label: 'View Receipt', action: 'receipt', icon: '\uD83D\uDCC4' },
      { label: 'Find Precedents', action: 'precedents', icon: '\uD83D\uDD0D' },
    ],
  },
};

export function NodeContextPanel({ node, events, onAction, onClose }: NodeContextPanelProps) {
  const config = STAGE_CONFIG[node.stage];

  const recentEvents = useMemo(() => events.slice(-10), [events]);

  return (
    <aside className="w-96 h-full border-l border-border bg-surface flex-shrink-0 overflow-y-auto">
      <div className="p-4 space-y-4">
        {/* Header */}
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span
                className={`px-2 py-0.5 text-[10px] font-theme-data uppercase tracking-wider rounded ${config.bg} ${config.color} border ${config.border}`}
              >
                {node.stage}
              </span>
              <span className="px-2 py-0.5 text-[10px] font-theme-data text-text-muted bg-bg rounded border border-border">
                {node.subtype}
              </span>
            </div>
            <h3 className="text-sm font-theme-data font-bold text-text truncate">{node.label}</h3>
          </div>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text text-sm font-theme-data ml-2 flex-shrink-0"
          >
            {'\u00D7'}
          </button>
        </div>

        {/* Description */}
        {node.description && (
          <div className="text-xs font-theme-data text-text-muted bg-bg p-3 rounded border border-border">
            {node.description}
          </div>
        )}

        {/* Status & Priority */}
        <div className="flex items-center gap-2">
          <StatusBadge status={node.status} />
          {node.priority > 0 && (
            <span className="px-2 py-0.5 text-[10px] font-theme-data bg-amber-500/10 text-amber-400 rounded border border-amber-500/30">
              Priority: {node.priority}
            </span>
          )}
        </div>

        {/* Action Buttons */}
        <div className="space-y-2">
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
            Actions
          </h4>
          <div className="grid grid-cols-1 gap-1.5">
            {config.actions.map((a) => (
              <button
                key={a.action}
                onClick={() => onAction(a.action, node.id)}
                className="flex items-center gap-2 px-3 py-2 text-xs font-theme-data rounded border border-border bg-bg hover:bg-indigo-500/10 hover:border-indigo-500/30 text-text transition-colors"
              >
                <span>{a.icon}</span>
                <span>{a.label}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Related Knowledge (placeholder) */}
        <div className="space-y-2">
          <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
            Related Knowledge
          </h4>
          <div className="text-xs font-theme-data text-text-muted/50 bg-bg p-3 rounded border border-border text-center">
            Select a node to see related knowledge from the Knowledge Mound
          </div>
        </div>

        {/* Node Events */}
        {recentEvents.length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
              Events ({events.length})
            </h4>
            <div className="space-y-1">
              {recentEvents.map((e) => (
                <div
                  key={e.id}
                  className="flex items-center gap-2 px-2 py-1.5 text-[11px] font-theme-data bg-bg rounded border border-border"
                >
                  <span
                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      e.severity === 'error'
                        ? 'bg-red-500'
                        : e.severity === 'warning'
                          ? 'bg-amber-500'
                          : e.severity === 'success'
                            ? 'bg-emerald-500'
                            : 'bg-gray-500'
                    }`}
                  />
                  <span className="truncate text-text-muted">{e.summary}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Metadata */}
        {Object.keys(node.metadata).length > 0 && (
          <div className="space-y-2">
            <h4 className="text-xs font-theme-data text-text-muted uppercase tracking-wider">
              Metadata
            </h4>
            <pre className="text-[10px] font-theme-data text-text-muted bg-bg p-2 rounded border border-border overflow-x-auto max-h-32">
              {JSON.stringify(node.metadata, null, 2)}
            </pre>
          </div>
        )}

        {/* Delete */}
        <button
          onClick={() => onAction('delete', node.id)}
          className="w-full px-3 py-2 text-xs font-theme-data text-red-400 border border-red-500/20 rounded hover:bg-red-500/10 transition-colors"
        >
          Delete Node
        </button>
      </div>
    </aside>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-gray-500/10 text-gray-400 border-gray-500/30',
    running: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    in_progress: 'bg-blue-500/10 text-blue-400 border-blue-500/30',
    completed: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    succeeded: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30',
    failed: 'bg-red-500/10 text-red-400 border-red-500/30',
    blocked: 'bg-amber-500/10 text-amber-400 border-amber-500/30',
  };
  return (
    <span
      className={`px-2 py-0.5 text-[10px] font-theme-data uppercase rounded border ${colors[status] || colors.pending}`}
    >
      {status}
    </span>
  );
}
