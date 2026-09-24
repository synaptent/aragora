'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { MemoryReadNodeData, MemoryWriteNodeData } from '../types';

interface MemoryReadNodeProps {
  data: MemoryReadNodeData;
  selected?: boolean;
}

export const MemoryReadNode = memo(function MemoryReadNode({
  data,
  selected,
}: MemoryReadNodeProps) {
  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[250px]
        bg-cyan-500/20 border-cyan-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-cyan-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">📖</span>
        <span className="text-sm font-theme-data font-bold text-cyan-300 uppercase tracking-wide">
          Memory Read
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 truncate">{data.label}</div>

      {data.description && (
        <div className="text-xs text-text-muted mb-2 line-clamp-2">{data.description}</div>
      )}

      <div className="flex flex-wrap gap-1 mb-2">
        {data.domains.slice(0, 2).map((domain) => (
          <span
            key={domain}
            className="px-1.5 py-0.5 text-xs bg-cyan-500/30 text-cyan-200 rounded font-theme-data"
          >
            {domain}
          </span>
        ))}
        {data.domains.length > 2 && (
          <span className="px-1.5 py-0.5 text-xs bg-cyan-500/30 text-cyan-200 rounded font-theme-data">
            +{data.domains.length - 2}
          </span>
        )}
      </div>

      {data.queryTemplate && (
        <div className="text-xs text-cyan-300 font-theme-data truncate">
          Q: {data.queryTemplate}
        </div>
      )}

      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-cyan-500 border-2 border-bg"
      />
    </div>
  );
});

interface MemoryWriteNodeProps {
  data: MemoryWriteNodeData;
  selected?: boolean;
}

export const MemoryWriteNode = memo(function MemoryWriteNode({
  data,
  selected,
}: MemoryWriteNodeProps) {
  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[250px]
        bg-cyan-500/20 border-cyan-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-cyan-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">💾</span>
        <span className="text-sm font-theme-data font-bold text-cyan-300 uppercase tracking-wide">
          Memory Write
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 truncate">{data.label}</div>

      {data.description && (
        <div className="text-xs text-text-muted mb-2 line-clamp-2">{data.description}</div>
      )}

      <div className="flex items-center gap-2">
        <span className="px-2 py-0.5 text-xs bg-cyan-500/30 text-cyan-200 rounded font-theme-data">
          {data.domain}
        </span>
        {data.retentionYears && (
          <span className="text-xs text-cyan-300 font-theme-data">
            {data.retentionYears}y retention
          </span>
        )}
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-cyan-500 border-2 border-bg"
      />
    </div>
  );
});

export default MemoryReadNode;
