'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import type { HumanCheckpointNodeData } from '../types';

const approvalTypeLabels: Record<string, string> = {
  review: 'Review',
  sign_off: 'Sign-Off',
  revision: 'Revision',
  presentation: 'Presentation',
};

interface HumanCheckpointNodeProps {
  data: HumanCheckpointNodeData;
  selected?: boolean;
}

export const HumanCheckpointNode = memo(function HumanCheckpointNode({
  data,
  selected,
}: HumanCheckpointNodeProps) {
  return (
    <div
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[180px] max-w-[250px]
        bg-green-500/20 border-green-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-green-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="text-lg">👤</span>
        <span className="text-sm font-theme-data font-bold text-green-300 uppercase tracking-wide">
          Human Review
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 truncate">{data.label}</div>

      {data.description && (
        <div className="text-xs text-text-muted mb-2 line-clamp-2">{data.description}</div>
      )}

      <div className="flex items-center gap-2 mb-2">
        <span className="px-2 py-0.5 text-xs bg-green-500/30 text-green-200 rounded font-theme-data">
          {approvalTypeLabels[data.approvalType] || data.approvalType}
        </span>
        {(data.requiredRole || data.requiredRoles?.[0]) && (
          <span className="text-xs text-green-300 font-theme-data">
            @{data.requiredRole || data.requiredRoles?.[0]}
          </span>
        )}
      </div>

      {data.checklist && data.checklist.length > 0 && (
        <div className="text-xs text-text-muted">
          {data.checklist.length} checklist item{data.checklist.length !== 1 ? 's' : ''}
        </div>
      )}

      {/* Approved branch (bottom) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="approved"
        className="w-3 h-3 bg-green-500 border-2 border-bg"
      />

      {/* Rejected branch (right) - for revision type */}
      {data.approvalType === 'revision' && (
        <Handle
          type="source"
          position={Position.Right}
          id="rejected"
          className="w-3 h-3 bg-red-500 border-2 border-bg"
          style={{ top: '60%' }}
        />
      )}
    </div>
  );
});

export default HumanCheckpointNode;
