'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

const priorityColors: Record<string, string> = {
  critical: 'bg-red-500/30 text-red-200',
  high: 'bg-orange-500/30 text-orange-200',
  medium: 'bg-amber-500/30 text-amber-200',
  low: 'bg-green-500/30 text-green-200',
};

const goalTypeLabels: Record<string, string> = {
  goal: 'Goal',
  principle: 'Principle',
  strategy: 'Strategy',
  milestone: 'Milestone',
  metric: 'Metric',
  risk: 'Risk',
};

interface GoalNodeProps {
  data: Record<string, unknown>;
  selected?: boolean;
}

export const GoalNode = memo(function GoalNode({ data, selected }: GoalNodeProps) {
  const goalType = (data.goalType || data.goal_type || 'goal') as string;
  const label = data.label as string;
  const description = data.description as string | undefined;
  const priority = (data.priority || 'medium') as string;
  const confidence = data.confidence as number | undefined;

  return (
    <div
      className={`
        px-4 py-3 rounded-xl border-2 min-w-[200px] max-w-[270px]
        bg-emerald-500/20 border-emerald-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="w-3 h-3 bg-emerald-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="px-1.5 py-0.5 text-xs bg-emerald-500/30 text-emerald-200 rounded font-theme-data uppercase">
          {goalTypeLabels[goalType] || goalType}
        </span>
        <span
          className={`px-1.5 py-0.5 text-xs rounded font-theme-data ${priorityColors[priority] || priorityColors.medium}`}
        >
          {priority}
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1">{label}</div>

      {description && (
        <div className="text-xs text-text-muted mb-1 line-clamp-2">{description}</div>
      )}

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

      <Handle
        type="source"
        position={Position.Right}
        className="w-3 h-3 bg-emerald-500 border-2 border-bg"
      />
    </div>
  );
});

export default GoalNode;
