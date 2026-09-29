'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { DecisionNodeData } from '../types';

interface DecisionNodeProps {
  data: DecisionNodeData;
  selected?: boolean;
}

export const DecisionNode = memo(function DecisionNode({ data, selected }: DecisionNodeProps) {
  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[250px]
        bg-yellow-500/20 border-yellow-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
      style={{ transform: 'rotate(0deg)' }} // Diamond shape handled differently
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-yellow-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">🔀</span>
        <span className="text-sm font-theme-data font-bold text-yellow-300 uppercase tracking-wide">
          Decision
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 truncate">{data.label}</div>

      {data.description && (
        <div className="text-xs text-text-muted mb-2 line-clamp-2">{data.description}</div>
      )}

      <div className="px-2 py-1 bg-yellow-500/30 rounded text-xs font-theme-data text-yellow-200 truncate">
        if: {data.condition}
      </div>

      {/* True branch handle (right) */}
      <Handle
        type="source"
        position={Position.Right}
        id="true"
        className="w-3 h-3 bg-green-500 border-2 border-bg"
        style={{ top: '60%' }}
      />

      {/* False branch handle (bottom) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="false"
        className="w-3 h-3 bg-red-500 border-2 border-bg"
      />

      {/* Labels for branches */}
      <div className="absolute -right-8 top-1/2 text-xs font-theme-data text-green-400">T</div>
      <div className="absolute bottom-0 left-1/2 -translate-x-1/2 translate-y-full text-xs font-theme-data text-red-400">
        F
      </div>
    </div>
  );
});

export default DecisionNode;
