'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import { ORCH_NODE_CONFIGS, ORCH_STATUS_COLORS, type OrchNodeType, type OrchStatus } from './types';

interface OrchNodeProps {
  data: Record<string, unknown>;
  selected?: boolean;
}

export const OrchNode = memo(function OrchNode({ data, selected }: OrchNodeProps) {
  const orchType = (data.orchType || data.orch_type || 'agent_task') as OrchNodeType;
  const label = data.label as string;
  const description = data.description as string | undefined;
  const status = (data.status || 'pending') as OrchStatus;
  const assignedAgent = (data.assignedAgent || data.assigned_agent) as string | undefined;
  const agentType = (data.agentType || data.agent_type) as string | undefined;
  const capabilities = data.capabilities as string[] | undefined;
  const lockedBy = data.lockedBy as string | undefined;

  const isAgent = orchType === 'agent_task' || orchType === 'debate';
  const isHumanGate = orchType === 'human_gate';
  const config = ORCH_NODE_CONFIGS[orchType] || ORCH_NODE_CONFIGS.agent_task;
  const statusClass = ORCH_STATUS_COLORS[status] || ORCH_STATUS_COLORS.pending;

  return (
    <div
      className={`px-4 py-3 border-2 min-w-[200px] max-w-[270px] ${config.color} ${config.borderColor} ${isAgent ? 'rounded-full' : 'rounded-lg'} ${isHumanGate ? 'border-dashed' : ''} ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''} ${lockedBy ? 'opacity-70' : ''} transition-all duration-200`}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="w-3 h-3 bg-pink-500 border-2 border-bg"
      />

      <div className="flex items-center gap-2 mb-2">
        <span className="w-5 h-5 flex items-center justify-center text-xs font-bold rounded bg-pink-500/30 text-pink-200">
          {config.icon}
        </span>
        <span className="px-1.5 py-0.5 text-xs bg-pink-500/30 text-pink-200 rounded font-theme-data uppercase">
          {config.label}
        </span>
        <span className={`px-1.5 py-0.5 text-xs rounded font-theme-data ${statusClass}`}>
          {status.replace('_', ' ')}
        </span>
      </div>

      <div className="text-sm font-medium text-text mb-1 line-clamp-2">{label}</div>
      {description && (
        <div className="text-xs text-text-muted mb-1 line-clamp-2">{description}</div>
      )}
      {assignedAgent && <div className="text-xs text-pink-300/80 mb-1">agent: {assignedAgent}</div>}
      {agentType && <div className="text-xs text-pink-300 font-theme-data mb-1">{agentType}</div>}

      {capabilities && capabilities.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {capabilities.slice(0, 3).map((cap) => (
            <span
              key={cap}
              className="px-1 py-0.5 text-xs bg-pink-500/20 text-pink-200 rounded font-theme-data"
            >
              {cap}
            </span>
          ))}
          {capabilities.length > 3 && (
            <span className="text-xs text-pink-300 font-theme-data">
              +{capabilities.length - 3}
            </span>
          )}
        </div>
      )}

      {lockedBy && <div className="mt-1 text-xs text-amber-400">Locked by {lockedBy}</div>}
      <Handle
        type="source"
        position={Position.Right}
        className="w-3 h-3 bg-pink-500 border-2 border-bg"
      />
    </div>
  );
});

export default OrchNode;
