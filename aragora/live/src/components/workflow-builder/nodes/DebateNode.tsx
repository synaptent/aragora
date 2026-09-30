'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { DebateNodeData } from '../types';

interface DebateNodeProps {
  data: DebateNodeData;
  selected?: boolean;
}

export const DebateNode = memo(function DebateNode({ data, selected }: DebateNodeProps) {
  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[250px]
        bg-purple-500/20 border-purple-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-purple-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">💬</span>
        <span className="text-sm font-theme-data font-bold text-purple-300 uppercase tracking-wide">
          Debate
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 truncate">{data.label}</div>

      {data.description && (
        <div className="text-xs text-text-muted mb-2 line-clamp-2">{data.description}</div>
      )}

      <div className="flex flex-wrap gap-1 mb-2">
        {data.agents.slice(0, 3).map((agent) => (
          <span
            key={agent}
            className="px-1.5 py-0.5 text-xs bg-purple-500/30 text-purple-200 rounded font-theme-data"
          >
            {agent}
          </span>
        ))}
        {data.agents.length > 3 && (
          <span className="px-1.5 py-0.5 text-xs bg-purple-500/30 text-purple-200 rounded font-theme-data">
            +{data.agents.length - 3}
          </span>
        )}
      </div>

      <div className="text-xs font-theme-data text-purple-300">
        {data.rounds} round{data.rounds !== 1 ? 's' : ''}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-purple-500 border-2 border-bg"
      />
    </div>
  );
});

export default DebateNode;
