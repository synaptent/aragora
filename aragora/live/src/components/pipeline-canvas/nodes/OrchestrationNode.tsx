'use client';

import { memo } from 'react';
import { Handle, Position } from '@xyflow/react';
import {
  PIPELINE_NODE_TYPE_CONFIGS,
  ORCH_STATUS_COLORS,
  EXECUTION_STATUS_COLORS,
  getMirroredNodeField,
  type OrchType,
  type OrchStatus,
  type ExecutionStatus,
  type AlternativeAgent,
} from '../types';

interface OrchestrationNodeProps {
  data: Record<string, unknown>;
  selected?: boolean;
}

export const OrchestrationNode = memo(function OrchestrationNode({
  data,
  selected,
}: OrchestrationNodeProps) {
  const orchType = getMirroredNodeField<OrchType>(data, 'orchType', 'orch_type') ?? 'agent_task';
  const label = data.label as string;
  const description = data.description as string | undefined;
  const assignedAgent = getMirroredNodeField<string>(data, 'assignedAgent', 'assigned_agent');
  const agentType = getMirroredNodeField<string>(data, 'agentType', 'agent_type');
  const capabilities = data.capabilities as string[] | undefined;
  const status = getMirroredNodeField<OrchStatus>(data, 'status') ?? 'pending';
  const lockedBy = getMirroredNodeField<string>(data, 'lockedBy', 'locked_by');
  const executionStatus = getMirroredNodeField<ExecutionStatus>(
    data,
    'executionStatus',
    'execution_status',
  );
  const executionDuration = getMirroredNodeField<string>(
    data,
    'executionDuration',
    'execution_duration',
  );
  const executionAgent = getMirroredNodeField<string>(data, 'executionAgent', 'execution_agent');
  const eloScore = getMirroredNodeField<number>(data, 'eloScore', 'elo_score');
  const selectionRationale = getMirroredNodeField<string>(
    data,
    'selectionRationale',
    'selection_rationale',
  );
  const alternativeAgents = getMirroredNodeField<AlternativeAgent[]>(
    data,
    'alternativeAgents',
    'alternative_agents',
  );
  const elapsedMs = getMirroredNodeField<number>(data, 'elapsedMs', 'elapsed_ms');
  const outputPreview = getMirroredNodeField<string>(data, 'outputPreview', 'output_preview');

  const isAgent = orchType === 'agent_task' || orchType === 'debate';
  const isHumanGate = orchType === 'human_gate';

  const config =
    PIPELINE_NODE_TYPE_CONFIGS.orchestration[orchType] ||
    PIPELINE_NODE_TYPE_CONFIGS.orchestration.agent_task;
  const statusClass = ORCH_STATUS_COLORS[status] || ORCH_STATUS_COLORS.pending;

  return (
    <div
      className={`
        px-4 py-3 border-2 min-w-[200px] max-w-[270px]
        ${config.color} ${config.borderColor}
        ${isAgent ? 'rounded-full' : 'rounded-lg'}
        ${isHumanGate ? 'border-dashed' : ''}
        ${selected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        ${lockedBy ? 'opacity-70' : ''}
        transition-all duration-200
      `}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="w-3 h-3 bg-pink-500 border-2 border-bg"
      />

      {/* Header: icon + type badge + status badge */}
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

      {/* Label */}
      <div className="text-sm font-medium text-text mb-1 line-clamp-2">{label}</div>

      {/* Description */}
      {description && (
        <div className="text-xs text-text-muted mb-1 line-clamp-2">{description}</div>
      )}

      {/* Assigned agent */}
      {assignedAgent && <div className="text-xs text-pink-300/80 mb-1">agent: {assignedAgent}</div>}

      {/* Agent type */}
      {agentType && <div className="text-xs text-pink-300 font-theme-data mb-1">{agentType}</div>}

      {/* Capabilities badges */}
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

      {/* ELO score badge */}
      {eloScore != null && (
        <div className="mt-2 flex items-center gap-1.5">
          <span className="px-1.5 py-0.5 text-xs font-theme-data bg-[var(--accent)]/20 text-[var(--accent)] rounded border border-[var(--accent)]/30">
            ELO {eloScore}
          </span>
          {selectionRationale && (
            <span
              className="text-xs text-text-muted truncate max-w-[120px]"
              title={selectionRationale}
            >
              {selectionRationale}
            </span>
          )}
        </div>
      )}

      {/* Alternative agents */}
      {alternativeAgents && alternativeAgents.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {alternativeAgents.slice(0, 2).map((alt) => (
            <span
              key={alt.name}
              className="px-1 py-0.5 text-xs bg-pink-500/10 text-pink-300/60 rounded font-theme-data"
              title={`Alternative: ${alt.name} (${alt.score ?? '?'})`}
            >
              {alt.name}
              {alt.score != null ? ` ${alt.score}` : ''}
            </span>
          ))}
          {alternativeAgents.length > 2 && (
            <span className="text-xs text-pink-300/40 font-theme-data">
              +{alternativeAgents.length - 2}
            </span>
          )}
        </div>
      )}

      {/* Execution status */}
      {executionStatus && (
        <div
          className={`mt-2 flex items-center gap-1.5 text-xs font-theme-data ${EXECUTION_STATUS_COLORS[executionStatus]?.text || 'text-text-muted'}`}
        >
          {executionStatus === 'in_progress' && (
            <span className="inline-block w-2 h-2 border border-current border-t-transparent rounded-full animate-spin" />
          )}
          {executionStatus === 'succeeded' && <span>✓</span>}
          {executionStatus === 'failed' && <span>✗</span>}
          <span>{executionStatus.replace('_', ' ')}</span>
          {elapsedMs != null && (
            <span className="text-text-muted">({(elapsedMs / 1000).toFixed(1)}s)</span>
          )}
          {!elapsedMs && executionDuration && (
            <span className="text-text-muted">({executionDuration})</span>
          )}
        </div>
      )}
      {executionAgent && executionStatus && (
        <div className="text-xs text-text-muted mt-0.5">via {executionAgent}</div>
      )}

      {/* Output preview */}
      {outputPreview && executionStatus && (
        <div className="mt-1 text-xs text-text-muted font-theme-data bg-bg/50 rounded px-1.5 py-1 line-clamp-2">
          {outputPreview}
        </div>
      )}

      {/* Lock indicator */}
      {lockedBy && <div className="mt-1 text-xs text-amber-400">Locked by {lockedBy}</div>}

      <Handle
        type="source"
        position={Position.Right}
        className="w-3 h-3 bg-pink-500 border-2 border-bg"
      />
    </div>
  );
});

export default OrchestrationNode;
