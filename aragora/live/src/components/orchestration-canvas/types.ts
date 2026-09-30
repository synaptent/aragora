/**
 * Orchestration Canvas type definitions.
 *
 * Matches the Python OrchNodeType enum from aragora/canvas/stages.py.
 */

export type OrchNodeType =
  'agent_task' | 'debate' | 'human_gate' | 'parallel_fan' | 'merge' | 'verification';
export type OrchEdgeType = 'sequence' | 'parallel' | 'conditional' | 'fallback' | 'feedback';
export type OrchStatus = 'pending' | 'running' | 'completed' | 'failed' | 'awaiting_human';

export type WorkflowStatus = 'idle' | 'creating' | 'started' | 'running' | 'completed' | 'failed';

export interface OrchNodeData {
  orchType: OrchNodeType;
  label: string;
  description: string;
  assignedAgent: string;
  agentType: string;
  capabilities: string[];
  status: OrchStatus;
  sourceActionIds?: string[];
  creatorId?: string;
  kmNodeId?: string;
  lockedBy?: string;
  workflowStatus?: WorkflowStatus;
  stage: 'orchestration';
  rfType: 'orchestrationNode';
}

export interface OrchTypeConfig {
  icon: string;
  color: string;
  borderColor: string;
  label: string;
  description: string;
  group: 'Agents' | 'Control Flow' | 'Gates';
}

export const ORCH_NODE_CONFIGS: Record<OrchNodeType, OrchTypeConfig> = {
  agent_task: {
    icon: 'A',
    color: 'bg-pink-500/20',
    borderColor: 'border-pink-500',
    label: 'Agent Task',
    description: 'Task assigned to an agent',
    group: 'Agents',
  },
  debate: {
    icon: 'D',
    color: 'bg-pink-600/20',
    borderColor: 'border-pink-600',
    label: 'Debate',
    description: 'Multi-agent debate',
    group: 'Agents',
  },
  parallel_fan: {
    icon: '=',
    color: 'bg-pink-400/20',
    borderColor: 'border-pink-400',
    label: 'Parallel Fan',
    description: 'Parallel execution',
    group: 'Control Flow',
  },
  merge: {
    icon: 'M',
    color: 'bg-pink-400/20',
    borderColor: 'border-pink-400',
    label: 'Merge',
    description: 'Merge parallel results',
    group: 'Control Flow',
  },
  human_gate: {
    icon: 'H',
    color: 'bg-pink-500/20',
    borderColor: 'border-pink-500',
    label: 'Human Gate',
    description: 'Human approval required',
    group: 'Gates',
  },
  verification: {
    icon: 'V',
    color: 'bg-pink-500/20',
    borderColor: 'border-pink-500',
    label: 'Verification',
    description: 'Verify results',
    group: 'Gates',
  },
};

export const ORCH_STATUS_COLORS: Record<OrchStatus, string> = {
  pending: 'bg-gray-500/30 text-gray-200',
  running: 'bg-blue-500/30 text-blue-200',
  completed: 'bg-green-500/30 text-green-200',
  failed: 'bg-red-500/30 text-red-200',
  awaiting_human: 'bg-amber-500/30 text-amber-200',
};

export interface OrchCanvasMeta {
  id: string;
  name: string;
  owner_id: string | null;
  workspace_id: string | null;
  source_canvas_id: string | null;
  description: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface RemoteCursor {
  userId: string;
  position: { x: number; y: number };
  color: string;
}
