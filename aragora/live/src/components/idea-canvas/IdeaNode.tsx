'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';
import { IDEA_NODE_CONFIGS, type IdeaNodeData } from './types';

/**
 * Single polymorphic React Flow node for all 9 idea types.
 * Color and icon are determined by data.ideaType.
 */
export const IdeaNode = memo(function IdeaNode({
  data,
  selected,
}: NodeProps & { data: IdeaNodeData }) {
  const config = IDEA_NODE_CONFIGS[data.ideaType] || IDEA_NODE_CONFIGS.concept;

  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[250px]
        ${config.color} ${config.borderColor}
        ${selected ? 'ring-2 ring-[var(--acid-green)] ring-offset-2 ring-offset-[var(--bg)]' : ''}
        ${data.lockedBy ? 'opacity-70' : ''}
        ${data.promotedToGoalId ? 'border-dashed' : ''}
        font-theme-data transition-all
      `}
    >
      <Handle type="target" position={Position.Top} className="!bg-[var(--text-muted)]" />

      {/* Header */}
      <div className="flex items-center gap-2 mb-1">
        <span className="text-xs opacity-60">{config.icon}</span>
        <span className="text-xs font-bold text-[var(--text)] truncate">
          {data.label || config.label}
        </span>
      </div>

      {/* Body preview */}
      {data.body && (
        <p className="text-[10px] text-[var(--text-muted)] line-clamp-2 mb-1">{data.body}</p>
      )}

      {/* Tags */}
      {data.tags && data.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1">
          {data.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="text-[9px] px-1 rounded bg-[var(--surface)] text-[var(--text-muted)]"
            >
              {tag}
            </span>
          ))}
          {data.tags.length > 3 && (
            <span className="text-[9px] text-[var(--text-muted)]">+{data.tags.length - 3}</span>
          )}
        </div>
      )}

      {/* Confidence bar */}
      {data.confidence > 0 && (
        <div className="w-full h-1 rounded bg-[var(--surface)] mt-1">
          <div
            className="h-full rounded bg-[var(--acid-green)]"
            style={{ width: `${Math.round(data.confidence * 100)}%` }}
          />
        </div>
      )}

      {/* Lock indicator */}
      {data.lockedBy && (
        <div className="absolute -top-2 -right-2 text-[10px] bg-[var(--surface)] rounded px-1">
          locked
        </div>
      )}

      <Handle type="source" position={Position.Bottom} className="!bg-[var(--text-muted)]" />
    </div>
  );
});

export default IdeaNode;
