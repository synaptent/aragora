'use client';

import { useCallback, useMemo } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Node,
  Edge,
  Handle,
  Position,
  MarkerType,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

interface WorkflowStep {
  id: string;
  name: string;
  type: 'agent' | 'task' | 'decision' | 'human_checkpoint' | 'parallel' | 'memory';
  status: 'pending' | 'running' | 'completed' | 'failed' | 'waiting_approval';
  startedAt?: string;
  completedAt?: string;
  error?: string;
  output?: Record<string, unknown>;
  approvalRequired?: boolean;
  approvalMessage?: string;
}

interface WorkflowExecution {
  id: string;
  workflowId: string;
  workflowName: string;
  status: 'running' | 'completed' | 'failed' | 'paused' | 'waiting_approval';
  progress: number;
  currentStep: string;
  steps: WorkflowStep[];
  startedAt: string;
  completedAt?: string;
  error?: string;
  metadata?: Record<string, unknown>;
}

interface ExecutionDAGViewProps {
  execution: WorkflowExecution;
  onStepSelect?: (step: WorkflowStep) => void;
  selectedStepId?: string;
}

const STATUS_STYLES: Record<
  string,
  { bg: string; border: string; glow: string; animate: boolean }
> = {
  pending: { bg: 'bg-gray-900/50', border: 'border-gray-500', glow: '', animate: false },
  running: {
    bg: 'bg-blue-900/40',
    border: 'border-blue-400',
    glow: 'shadow-[0_0_15px_rgba(59,130,246,0.5)]',
    animate: true,
  },
  completed: { bg: 'bg-green-900/40', border: 'border-green-500', glow: '', animate: false },
  failed: {
    bg: 'bg-red-900/40',
    border: 'border-red-500',
    glow: 'shadow-[0_0_15px_rgba(239,68,68,0.5)]',
    animate: false,
  },
  waiting_approval: {
    bg: 'bg-purple-900/40',
    border: 'border-purple-400',
    glow: 'shadow-[0_0_15px_rgba(168,85,247,0.5)]',
    animate: true,
  },
};

const STEP_ICONS: Record<string, string> = {
  agent: '🤖',
  task: '📋',
  decision: '🔀',
  human_checkpoint: '👤',
  parallel: '⚡',
  memory: '💾',
};

const TYPE_COLORS: Record<string, string> = {
  agent: 'text-[var(--accent)]',
  task: 'text-blue-400',
  decision: 'text-yellow-400',
  human_checkpoint: 'text-purple-400',
  parallel: 'text-cyan-400',
  memory: 'text-orange-400',
};

// Custom node component for execution steps
interface ExecutionNodeData extends Record<string, unknown> {
  step: WorkflowStep;
  isSelected: boolean;
  onSelect: () => void;
}

function ExecutionNodeComponent({ data }: { data: ExecutionNodeData }) {
  const { step, isSelected, onSelect } = data;
  const styles = STATUS_STYLES[step.status] || STATUS_STYLES.pending;
  const icon = STEP_ICONS[step.type] || '📦';
  const typeColor = TYPE_COLORS[step.type] || 'text-text';

  return (
    <div
      onClick={onSelect}
      className={`
        px-4 py-3 rounded-lg border-2 min-w-[200px] max-w-[280px] cursor-pointer
        ${styles.bg} ${styles.border} ${styles.glow}
        ${isSelected ? 'ring-2 ring-acid-green ring-offset-2 ring-offset-bg' : ''}
        ${styles.animate ? 'animate-pulse' : ''}
        transition-all duration-200 hover:scale-105
      `}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="w-3 h-3 bg-surface border-2 border-[var(--accent)]"
      />

      {/* Header with type and status */}
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-lg">{icon}</span>
          <span className={`text-xs font-theme-data uppercase tracking-wide ${typeColor}`}>
            {step.type.replace('_', ' ')}
          </span>
        </div>
        <StatusBadge status={step.status} />
      </div>

      {/* Step name */}
      <div className="text-sm font-medium text-text mb-1 truncate">{step.name}</div>

      {/* Timing info */}
      {step.startedAt && (
        <div className="text-xs text-text-muted">
          {step.completedAt ? (
            <span className="text-green-400">
              Completed in {formatDuration(step.startedAt, step.completedAt)}
            </span>
          ) : step.status === 'running' ? (
            <span className="text-blue-400">Running for {formatDuration(step.startedAt)}...</span>
          ) : null}
        </div>
      )}

      {/* Error indicator */}
      {step.error && <div className="mt-2 text-xs text-red-400 truncate">Error: {step.error}</div>}

      {/* Approval indicator */}
      {step.status === 'waiting_approval' && step.approvalMessage && (
        <div className="mt-2 text-xs text-purple-300">Awaiting approval</div>
      )}

      <Handle
        type="source"
        position={Position.Bottom}
        className="w-3 h-3 bg-surface border-2 border-[var(--accent)]"
      />
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-gray-600 text-gray-200',
    running: 'bg-blue-600 text-blue-100',
    completed: 'bg-green-600 text-green-100',
    failed: 'bg-red-600 text-red-100',
    waiting_approval: 'bg-purple-600 text-purple-100',
  };

  const labels: Record<string, string> = {
    pending: 'PENDING',
    running: 'RUNNING',
    completed: 'DONE',
    failed: 'FAILED',
    waiting_approval: 'APPROVAL',
  };

  return (
    <span
      className={`px-2 py-0.5 text-[10px] font-theme-data rounded ${colors[status] || colors.pending}`}
    >
      {labels[status] || status.toUpperCase()}
    </span>
  );
}

function formatDuration(startedAt: string, completedAt?: string): string {
  const start = new Date(startedAt).getTime();
  const end = completedAt ? new Date(completedAt).getTime() : Date.now();
  const seconds = Math.floor((end - start) / 1000);

  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

// Node types for React Flow
const nodeTypes = { executionStep: ExecutionNodeComponent };

export function ExecutionDAGView({
  execution,
  onStepSelect,
  selectedStepId,
}: ExecutionDAGViewProps) {
  const handleStepClick = useCallback(
    (step: WorkflowStep) => {
      onStepSelect?.(step);
    },
    [onStepSelect],
  );

  // Convert steps to nodes with automatic layout
  const { nodes, edges } = useMemo(() => {
    const nodeWidth = 240;
    const nodeHeight = 120;
    const horizontalGap = 80;
    const verticalGap = 60;

    // Simple layout: vertical flow with wrapping
    const nodesPerRow = 3;
    const nodes: Node<ExecutionNodeData>[] = execution.steps.map((step, index) => {
      const row = Math.floor(index / nodesPerRow);
      const col = index % nodesPerRow;

      return {
        id: step.id,
        type: 'executionStep',
        position: { x: col * (nodeWidth + horizontalGap), y: row * (nodeHeight + verticalGap) },
        data: {
          step,
          isSelected: step.id === selectedStepId,
          onSelect: () => handleStepClick(step),
        },
      };
    });

    // Create edges between consecutive steps
    const edges: Edge[] = execution.steps.slice(0, -1).map((step, index) => {
      const nextStep = execution.steps[index + 1];
      const isCompleted = step.status === 'completed';
      const isRunning = step.status === 'running' || nextStep.status === 'running';

      return {
        id: `${step.id}-${nextStep.id}`,
        source: step.id,
        target: nextStep.id,
        type: 'smoothstep',
        animated: isRunning,
        style: {
          stroke: isCompleted ? '#22c55e' : isRunning ? '#3b82f6' : '#6b7280',
          strokeWidth: 2,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: isCompleted ? '#22c55e' : isRunning ? '#3b82f6' : '#6b7280',
        },
      };
    });

    return { nodes, edges };
  }, [execution.steps, selectedStepId, handleStepClick]);

  // Progress summary
  const completedCount = execution.steps.filter((s) => s.status === 'completed').length;
  const totalCount = execution.steps.length;

  return (
    <div className="w-full h-full relative">
      {/* Progress overlay */}
      <div className="absolute top-4 left-4 z-10 bg-surface/90 border border-border rounded-lg p-3">
        <div className="text-xs font-theme-data text-text-muted mb-1">PROGRESS</div>
        <div className="flex items-center gap-3">
          <div className="text-xl font-theme-data text-[var(--accent)]">
            {completedCount}/{totalCount}
          </div>
          <div className="flex-1 h-2 bg-bg rounded-full overflow-hidden min-w-[100px]">
            <div
              className="h-full bg-[var(--accent)] transition-all duration-300"
              style={{ width: `${(completedCount / totalCount) * 100}%` }}
            />
          </div>
          <div className="text-sm font-theme-data text-text-muted">
            {Math.round((completedCount / totalCount) * 100)}%
          </div>
        </div>
      </div>

      {/* Legend */}
      <div className="absolute top-4 right-4 z-10 bg-surface/90 border border-border rounded-lg p-3">
        <div className="text-xs font-theme-data text-text-muted mb-2">STATUS</div>
        <div className="flex flex-wrap gap-2">
          {['pending', 'running', 'completed', 'failed', 'waiting_approval'].map((status) => (
            <div key={status} className="flex items-center gap-1.5">
              <div
                className={`w-2 h-2 rounded-full ${
                  status === 'pending'
                    ? 'bg-gray-500'
                    : status === 'running'
                      ? 'bg-blue-400 animate-pulse'
                      : status === 'completed'
                        ? 'bg-green-500'
                        : status === 'failed'
                          ? 'bg-red-500'
                          : 'bg-purple-400 animate-pulse'
                }`}
              />
              <span className="text-[10px] font-theme-data text-text-muted capitalize">
                {status.replace('_', ' ')}
              </span>
            </div>
          ))}
        </div>
      </div>

      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.5}
        maxZoom={1.5}
        defaultViewport={{ x: 0, y: 0, zoom: 1 }}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#1a1a2e" gap={20} />
        <Controls className="!bg-surface !border-border !shadow-none" showInteractive={false} />
        <MiniMap
          className="!bg-surface !border-border"
          nodeColor={(node) => {
            const step = (node.data as ExecutionNodeData)?.step;
            if (!step) return '#6b7280';
            switch (step.status) {
              case 'completed':
                return '#22c55e';
              case 'running':
                return '#3b82f6';
              case 'failed':
                return '#ef4444';
              case 'waiting_approval':
                return '#a855f7';
              default:
                return '#6b7280';
            }
          }}
          maskColor="rgba(0,0,0,0.8)"
        />
      </ReactFlow>
    </div>
  );
}

export default ExecutionDAGView;
