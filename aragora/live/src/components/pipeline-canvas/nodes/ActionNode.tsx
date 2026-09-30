'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import {
  PIPELINE_NODE_TYPE_CONFIGS,
  ACTION_STATUS_COLORS,
  getMirroredNodeField,
  type ActionType,
  type ActionStatus,
} from '../types';

interface ActionNodeProps {
  data: Record<string, unknown>;
  selected?: boolean;
}

export const ActionNode = memo(function ActionNode({ data, selected }: ActionNodeProps) {
  const stepType = getMirroredNodeField<ActionType>(data, 'stepType', 'step_type') ?? 'task';
  const label = data.label as string;
  const description = data.description as string | undefined;
  const optional = data.optional as boolean | undefined;
  const timeout = getMirroredNodeField<number>(data, 'timeoutSeconds', 'timeout');
  const status = getMirroredNodeField<ActionStatus>(data, 'status') ?? 'pending';
  const assignee = data.assignee as string | undefined;
  const lockedBy = getMirroredNodeField<string>(data, 'lockedBy', 'locked_by');

  const config =
    PIPELINE_NODE_TYPE_CONFIGS.actions[stepType] || PIPELINE_NODE_TYPE_CONFIGS.actions.task;
  const statusClass = ACTION_STATUS_COLORS[status] || ACTION_STATUS_COLORS.pending;

  return (
    <div
      className={`
        px-4 py-3 rounded-md border-2 min-w-[200px] max-w-[270px]
        ${config.color} ${config.borderColor}
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        ${lockedBy ? 'opacity-70' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="w-3 h-3 bg-amber-500 border-2 border-bg"
      />

      {/* Header: icon + type badge + status badge */}
      <div className="flex items-center gap-2 mb-2">
        <span className="w-5 h-5 flex items-center justify-center text-xs font-bold rounded bg-amber-500/30 text-amber-200">
          {config.icon}
        </span>
        <span className="px-1.5 py-0.5 text-xs bg-amber-500/30 text-amber-200 rounded font-theme-data uppercase">
          {config.label}
        </span>
        <span className={`px-1.5 py-0.5 text-xs rounded font-theme-data ${statusClass}`}>
          {status.replace('_', ' ')}
        </span>
      </div>

      {/* Label */}
      <div className="text-sm font-medium text-text mb-1 line-clamp-2">{label}</div>

      {/* Description */}
      {description && (
        <div className="text-xs text-text-muted mb-1 line-clamp-2">{description}</div>
      )}

      {/* Optional indicator */}
      {optional && (
        <span className="inline-block px-1.5 py-0.5 text-xs bg-gray-500/30 text-gray-300 rounded font-theme-data mb-1">
          optional
        </span>
      )}

      {/* Assignee */}
      {assignee && <div className="text-xs text-amber-300/80 mb-1">assigned: {assignee}</div>}

      {/* Timeout */}
      {timeout && timeout > 0 && (
        <div className="text-xs font-theme-data text-amber-300">timeout: {timeout}s</div>
      )}

      {/* Lock indicator */}
      {lockedBy && <div className="mt-1 text-xs text-amber-400">Locked by {lockedBy}</div>}

      <Handle
        type="source"
        position={Position.Right}
        className="w-3 h-3 bg-amber-500 border-2 border-bg"
      />
    </div>
  );
});

export default ActionNode;
