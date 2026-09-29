'use client';

import { Handle, Position, type NodeProps } from '@xyflow/react';
import type { DAGNodeData } from '@/hooks/useUnifiedDAG';

export function ValueNode({ data }: NodeProps) {
  const nodeData = data as unknown as DAGNodeData;
  return (
    <div
      className="relative px-4 py-3 rounded-lg border-2 shadow-md bg-surface min-w-[140px]"
      style={{ borderColor: '#8b5cf6', transform: 'rotate(45deg)' }}
    >
      <div style={{ transform: 'rotate(-45deg)' }} className="text-center">
        <Handle type="target" position={Position.Left} className="!bg-violet-500" />
        <div className="text-xs font-theme-data font-bold text-violet-400 uppercase tracking-wide mb-1">
          Value
        </div>
        <div className="text-sm font-medium text-text truncate max-w-[120px]">{nodeData.label}</div>
        <Handle type="source" position={Position.Right} className="!bg-violet-500" />
      </div>
    </div>
  );
}
