/**
 * Action Canvas type definitions.
 *
 * Matches the Python ActionNodeType enum from aragora/canvas/stages.py.
 */

export type ActionNodeType = 'task' | 'epic' | 'checkpoint' | 'deliverable' | 'dependency';

export type ActionEdgeType = 'requires' | 'blocks' | 'follows' | 'derived_from' | 'depends_on';

export type ActionStatus = 'pending' | 'in_progress' | 'completed' | 'blocked';

export interface ActionNodeData {
  actionType: ActionNodeType;
  label: string;
  description: string;
  status: ActionStatus;
  assignee: string;
  optional: boolean;
  timeoutSeconds: number;
  tags: string[];
  sourceGoalIds?: string[];
  creatorId?: string;
  kmNodeId?: string;
  lockedBy?: string;
  stage: 'actions';
  rfType: 'actionNode';
}

export interface ActionTypeConfig {
  icon: string;
  color: string;
  borderColor: string;
  label: string;
  description: string;
  group: 'Execution' | 'Verification' | 'Management';
}

export const ACTION_NODE_CONFIGS: Record<ActionNodeType, ActionTypeConfig> = {
  task: {
    icon: 'T',
    color: 'bg-amber-500/20',
    borderColor: 'border-amber-500',
    label: 'Task',
    description: 'Actionable task',
    group: 'Execution',
  },
  epic: {
    icon: 'E',
    color: 'bg-amber-600/20',
    borderColor: 'border-amber-600',
    label: 'Epic',
    description: 'Large body of work',
    group: 'Execution',
  },
  checkpoint: {
    icon: 'C',
    color: 'bg-amber-400/20',
    borderColor: 'border-amber-400',
    label: 'Checkpoint',
    description: 'Verification checkpoint',
    group: 'Verification',
  },
  deliverable: {
    icon: 'D',
    color: 'bg-amber-500/20',
    borderColor: 'border-amber-500',
    label: 'Deliverable',
    description: 'Tangible deliverable',
    group: 'Management',
  },
  dependency: {
    icon: '~',
    color: 'bg-amber-300/20',
    borderColor: 'border-amber-300',
    label: 'Dependency',
    description: 'External dependency',
    group: 'Management',
  },
};

export const STATUS_COLORS: Record<ActionStatus, string> = {
  pending: 'bg-gray-500/30 text-gray-200',
  in_progress: 'bg-blue-500/30 text-blue-200',
  completed: 'bg-green-500/30 text-green-200',
  blocked: 'bg-red-500/30 text-red-200',
};

export interface ActionCanvasMeta {
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
