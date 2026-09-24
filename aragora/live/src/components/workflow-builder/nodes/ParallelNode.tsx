'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { ParallelNodeData, LoopNodeData } from '../types';

interface ParallelNodeProps {
  data: ParallelNodeData;
  selected?: boolean;
}

export const ParallelNode = memo(function ParallelNode({ data, selected }: ParallelNodeProps) {
  const branchCount = data.branches?.length || 2;

  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[200px] max-w-[280px]
        bg-orange-500/20 border-orange-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-orange-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">⚡</span>
        <span className="text-sm font-theme-data font-bold text-orange-300 uppercase tracking-wide">
          Parallel
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 truncate">{data.label}</div>

      {data.description && (
        <div className="text-xs text-text-muted mb-2 line-clamp-2">{data.description}</div>
      )}

      <div className="text-xs font-theme-data text-orange-300">
        {branchCount} parallel branch{branchCount !== 1 ? 'es' : ''}
      </div>

      {/* Multiple source handles for parallel branches */}
      {Array.from({ length: Math.min(branchCount, 4) }).map((_, i) => (
        <Handle
          key={i}
          type="source"
          position={Position.Bottom}
          id={`branch-${i}`}
          className="w-3 h-3 bg-orange-500 border-2 border-bg"
          style={{ left: `${20 + (i * 60) / Math.min(branchCount, 4)}%` }}
        />
      ))}

      {/* Join handle (for parallel completion) */}
      <Handle
        type="target"
        position={Position.Bottom}
        id="join"
        className="w-3 h-3 bg-orange-500 border-2 border-bg opacity-50"
        style={{ left: '90%' }}
      />
    </div>
  );
});

interface LoopNodeProps {
  data: LoopNodeData;
  selected?: boolean;
}

export const LoopNode = memo(function LoopNode({ data, selected }: LoopNodeProps) {
  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[250px]
        bg-pink-500/20 border-pink-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-pink-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">🔄</span>
        <span className="text-sm font-theme-data font-bold text-pink-300 uppercase tracking-wide">
          Loop
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 truncate">{data.label}</div>

      {data.description && (
        <div className="text-xs text-text-muted mb-2 line-clamp-2">{data.description}</div>
      )}

      <div className="px-2 py-1 bg-pink-500/30 rounded text-xs font-theme-data text-pink-200 mb-2 truncate">
        while: {data.condition}
      </div>

      <div className="text-xs font-theme-data text-pink-300">
        max {data.maxIterations} iterations
      </div>

      {/* Loop body handle */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="body"
        className="w-3 h-3 bg-pink-500 border-2 border-bg"
      />

      {/* Loop back handle (left side) */}
      <Handle
        type="target"
        position={Position.Left}
        id="back"
        className="w-3 h-3 bg-pink-500 border-2 border-bg opacity-50"
        style={{ top: '70%' }}
      />

      {/* Exit handle (right side) */}
      <Handle
        type="source"
        position={Position.Right}
        id="exit"
        className="w-3 h-3 bg-green-500 border-2 border-bg"
        style={{ top: '70%' }}
      />
    </div>
  );
});

export default ParallelNode;
