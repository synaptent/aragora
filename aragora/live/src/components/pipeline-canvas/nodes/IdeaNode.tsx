'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

const ideaTypeLabels: Record<string, string> = {
  concept: 'Concept',
  cluster: 'Cluster',
  question: 'Question',
  insight: 'Insight',
  evidence: 'Evidence',
  assumption: 'Assumption',
  constraint: 'Constraint',
};

interface IdeaNodeProps {
  data: Record<string, unknown>;
  selected?: boolean;
}

export const IdeaNode = memo(function IdeaNode({ data, selected }: IdeaNodeProps) {
  const ideaType = (data.ideaType || data.idea_type || 'concept') as string;
  const label = data.label as string;
  const agent = data.agent as string | undefined;
  const contentHash = (data.contentHash || data.content_hash || '') as string;
  const fullContent = (data.fullContent || data.full_content) as string | undefined;

  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[250px]
        bg-indigo-500/20 border-indigo-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="w-3 h-3 bg-indigo-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="px-1.5 py-0.5 text-xs bg-indigo-500/30 text-indigo-200 rounded font-theme-data uppercase">
          {ideaTypeLabels[ideaType] || ideaType}
        </span>
        {agent && <span className="text-xs text-text-muted font-theme-data">{agent}</span>}
      </div>

      <div className="text-sm font-medium text-text mb-1 truncate">{label}</div>

      {fullContent && fullContent !== label && (
        <div className="text-xs text-text-muted mb-1 line-clamp-2">{fullContent}</div>
      )}

      {contentHash && (
        <div className="text-xs font-theme-data text-indigo-300 truncate">
          #{contentHash.slice(0, 8)}
        </div>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className="w-3 h-3 bg-indigo-500 border-2 border-bg"
      />
    </div>
  );
});

export default IdeaNode;
