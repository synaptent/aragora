'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { GOAL_NODE_CONFIGS, PRIORITY_COLORS, type GoalNodeType, type GoalPriority } from './types';

interface GoalNodeProps {
  data: Record<string, unknown>;
  selected?: boolean;
}

/**
 * Polymorphic React Flow node for all 6 goal types.
 * Color, icon, and layout determined by data.goalType.
 */
export const GoalNode = memo(function GoalNode({ data, selected }: GoalNodeProps) {
  const goalType = (data.goalType || data.goal_type || 'goal') as GoalNodeType;
  const label = data.label as string;
  const description = data.description as string | undefined;
  const priority = (data.priority || 'medium') as GoalPriority;
  const measurable = data.measurable as string | undefined;
  const confidence = data.confidence as number | undefined;
  const lockedBy = data.lockedBy as string | undefined;

  const config = GOAL_NODE_CONFIGS[goalType] || GOAL_NODE_CONFIGS.goal;
  const priorityClass = PRIORITY_COLORS[priority] || PRIORITY_COLORS.medium;

  return (
    <div
      className={`
        px-4 py-3 rounded-xl border-2 min-w-[200px] max-w-[270px]
        ${config.color} ${config.borderColor}
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        ${lockedBy ? 'opacity-70' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="w-3 h-3 bg-emerald-500 border-2 border-bg"
      />

      {/* Header: type badge + priority badge */}
      <div className="flex items-center gap-2 mb-2">
        <span className="w-5 h-5 flex items-center justify-center text-xs font-bold rounded bg-emerald-500/30 text-emerald-200">
          {config.icon}
        </span>
        <span className="px-1.5 py-0.5 text-xs bg-emerald-500/30 text-emerald-200 rounded font-theme-data uppercase">
          {config.label}
        </span>
        <span className={`px-1.5 py-0.5 text-xs rounded font-theme-data ${priorityClass}`}>
          {priority}
        </span>
      </div>

      {/* Label */}
      <div className="text-sm font-medium text-text mb-1 line-clamp-2">{label}</div>

      {/* Description */}
      {description && (
        <div className="text-xs text-text-muted mb-1 line-clamp-2">{description}</div>
      )}

      {/* Measurable criteria */}
      {measurable && (
        <div className="text-xs text-emerald-300/80 mb-1 italic line-clamp-1">{measurable}</div>
      )}

      {/* Confidence bar */}
      {typeof confidence === 'number' && (
        <div className="mt-2 flex items-center gap-1">
          <div className="flex-1 h-1 bg-emerald-900/50 rounded-full overflow-hidden">
            <div
              className="h-full bg-emerald-400 rounded-full"
              style={{ width: `${Math.round(confidence * 100)}%` }}
            />
          </div>
          <span className="text-xs text-emerald-300 font-theme-data">
            {Math.round(confidence * 100)}%
          </span>
        </div>
      )}

      {/* Lock indicator */}
      {lockedBy && <div className="mt-1 text-xs text-amber-400">Locked by {lockedBy}</div>}

      <Handle
        type="source"
        position={Position.Right}
        className="w-3 h-3 bg-emerald-500 border-2 border-bg"
      />
    </div>
  );
});

export default GoalNode;
