'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';

const principleTypeLabels: Record<string, string> = {
  value: 'Value',
  principle: 'Principle',
  priority: 'Priority',
  constraint: 'Constraint',
  connection: 'Connection',
  theme: 'Theme',
};

const principleTypeIcons: Record<string, string> = {
  value: '\u25C7',
  principle: '\u25C8',
  priority: '\u25B2',
  constraint: '\u25FB',
  connection: '\u25CE',
  theme: '\u25C6',
};

interface PrincipleNodeProps {
  data: Record<string, unknown>;
  selected?: boolean;
}

export const PrincipleNode = memo(function PrincipleNode({ data, selected }: PrincipleNodeProps) {
  const principleType = (data.principleType || data.principle_type || 'principle') as string;
  const label = data.label as string;
  const description = data.description as string | undefined;
  const confidence = data.confidence as number | undefined;
  const theme = data.theme as string | undefined;
  const contentHash = (data.contentHash || data.content_hash || '') as string;

  return (
    <div
      className={`
        px-4 py-3 rounded-xl border-2 min-w-[200px] max-w-[260px]
        bg-violet-500/20 border-violet-500
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="w-3 h-3 bg-violet-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="w-5 h-5 flex items-center justify-center text-xs font-bold rounded bg-violet-500/30 text-violet-200">
          {principleTypeIcons[principleType] || '\u25C8'}
        </span>
        <span className="px-1.5 py-0.5 text-xs bg-violet-500/30 text-violet-200 rounded font-theme-data uppercase">
          {principleTypeLabels[principleType] || principleType}
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 line-clamp-2">{label}</div>

      {description && (
        <div className="text-xs text-text-muted mb-1 line-clamp-2">{description}</div>
      )}

      {typeof confidence === 'number' && (
        <div className="mt-2 flex items-center gap-1">
          <div className="flex-1 h-1 bg-violet-900/50 rounded-full overflow-hidden">
            <div
              className="h-full bg-violet-400 rounded-full"
              style={{ width: `${Math.round(confidence * 100)}%` }}
            />
          </div>
          <span className="text-xs text-violet-300 font-theme-data">
            {Math.round(confidence * 100)}%
          </span>
        </div>
      )}

      {theme && (
        <div className="mt-1">
          <span className="px-1.5 py-0.5 text-xs bg-violet-500/20 text-violet-300 rounded font-theme-data">
            {theme}
          </span>
        </div>
      )}

      {contentHash && (
        <div className="text-xs font-theme-data text-violet-300 truncate mt-1">
          #{contentHash.slice(0, 8)}
        </div>
      )}

      <Handle
        type="source"
        position={Position.Right}
        className="w-3 h-3 bg-violet-500 border-2 border-bg"
      />
    </div>
  );
});

export default PrincipleNode;
