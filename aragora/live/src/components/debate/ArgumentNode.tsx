'use client';

import { memo } from 'react';
import { Handle, Position, type NodeProps } from '@xyflow/react';

export type ArgumentType =
  'proposal' | 'critique' | 'evidence' | 'concession' | 'vote' | 'consensus';

export interface ArgumentNodeData {
  label: string;
  content: string;
  agent: string;
  round: number;
  argumentType: ArgumentType;
  timestamp: string;
  [key: string]: unknown;
}

const TYPE_COLORS: Record<ArgumentType, string> = {
  proposal: '#39FF14',
  critique: '#FF073A',
  evidence: '#00F0FF',
  concession: '#FFD700',
  vote: '#BF40BF',
  consensus: '#FFFFFF',
};

const TYPE_LABELS: Record<ArgumentType, string> = {
  proposal: 'PROPOSAL',
  critique: 'CRITIQUE',
  evidence: 'EVIDENCE',
  concession: 'CONCESSION',
  vote: 'VOTE',
  consensus: 'CONSENSUS',
};

function ArgumentNodeComponent({ data, selected }: NodeProps) {
  const nodeData = data as unknown as ArgumentNodeData;
  const color = TYPE_COLORS[nodeData.argumentType] || '#00F0FF';

  return (
    <div
      className="relative bg-[var(--surface)] border border-[var(--border)] rounded-md min-w-[200px] max-w-[280px] font-theme-data text-xs"
      style={{
        borderLeftWidth: 4,
        boxShadow: selected
          ? `0 0 12px ${color}40, 0 0 4px ${color}20`
          : '0 1px 3px rgba(0,0,0,0.3)',
        borderColor: selected ? color : undefined,
        borderLeftColor: color,
      }}
    >
      <Handle type="target" position={Position.Top} className="!bg-[var(--border)] !w-2 !h-2" />

      {/* Header: agent + type badge */}
      <div className="flex items-center justify-between px-3 pt-2 pb-1 gap-2">
        <span className="text-[var(--text-muted)] truncate" title={nodeData.agent}>
          {nodeData.agent}
        </span>
        <span
          className="shrink-0 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase"
          style={{ backgroundColor: `${color}20`, color: color, border: `1px solid ${color}40` }}
        >
          {TYPE_LABELS[nodeData.argumentType] || nodeData.argumentType}
        </span>
      </div>

      {/* Content */}
      <div className="px-3 pb-2 text-[var(--text)] leading-relaxed line-clamp-3">
        {nodeData.content || nodeData.label}
      </div>

      {/* Footer: round */}
      <div className="px-3 pb-2 text-[10px] text-[var(--text-muted)]">R{nodeData.round}</div>

      <Handle type="source" position={Position.Bottom} className="!bg-[var(--border)] !w-2 !h-2" />
    </div>
  );
}

export const ArgumentNode = memo(ArgumentNodeComponent);
