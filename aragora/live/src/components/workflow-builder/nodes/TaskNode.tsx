'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { TaskNodeData } from '../types';

const taskTypeLabels: Record<string, string> = {
  validate: 'Validate',
  transform: 'Transform',
  aggregate: 'Aggregate',
  function: 'Function',
  http: 'HTTP Call',
};

interface TaskNodeProps {
  data: TaskNodeData;
  selected?: boolean;
}

export const TaskNode = memo(function TaskNode({ data, selected }: TaskNodeProps) {
  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[250px]
        bg-blue-500/20 border-blue-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-blue-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">⚙️</span>
        <span className="text-sm font-theme-data font-bold text-blue-300 uppercase tracking-wide">
          Task
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 truncate">{data.label}</div>

      {data.description && (
        <div className="text-xs text-text-muted mb-2 line-clamp-2">{data.description}</div>
      )}

      <div className="flex items-center gap-2">
        <span className="px-2 py-0.5 text-xs bg-blue-500/30 text-blue-200 rounded font-theme-data">
          {taskTypeLabels[data.taskType] || data.taskType}
        </span>
        {data.functionName && (
          <span className="text-xs text-blue-300 font-theme-data truncate">
            {data.functionName}
          </span>
        )}
      </div>

      {data.validationRules && data.validationRules.length > 0 && (
        <div className="mt-2 text-xs text-text-muted">
          {data.validationRules.length} validation rule
          {data.validationRules.length !== 1 ? 's' : ''}
        </div>
      )}

      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-blue-500 border-2 border-bg"
      />
    </div>
  );
});

export default TaskNode;
