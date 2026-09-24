/**
 * Pipeline Canvas Types
 *
 * TypeScript types mirroring aragora/canvas/stages.py for the
 * four-stage idea-to-execution pipeline.
 */

// =============================================================================
// Stage Types
// =============================================================================

export type PipelineStageType = 'ideas' | 'principles' | 'goals' | 'actions' | 'orchestration';

export type IdeaType =
  'concept' | 'cluster' | 'question' | 'insight' | 'evidence' | 'assumption' | 'constraint';
export type PrincipleType =
  'value' | 'principle' | 'priority' | 'constraint' | 'connection' | 'theme';
export type GoalType = 'goal' | 'principle' | 'strategy' | 'milestone' | 'metric' | 'risk';
export type ActionType = 'task' | 'epic' | 'checkpoint' | 'deliverable' | 'dependency';
export type OrchType =
  'agent_task' | 'debate' | 'human_gate' | 'parallel_fan' | 'merge' | 'verification';

// =============================================================================
// Status Types & Colors
// =============================================================================

export type ActionStatus = 'pending' | 'in_progress' | 'completed' | 'blocked';
export type OrchStatus = 'pending' | 'running' | 'completed' | 'failed' | 'awaiting_human';
export type ExecutionStatus = 'pending' | 'in_progress' | 'succeeded' | 'failed' | 'partial';

export const EXECUTION_STATUS_COLORS: Record<
  ExecutionStatus,
  { bg: string; text: string; ring: string }
> = {
  pending: { bg: 'bg-gray-500/20', text: 'text-gray-300', ring: 'ring-gray-500/50' },
  in_progress: { bg: 'bg-blue-500/20', text: 'text-blue-300', ring: 'ring-blue-500/50' },
  succeeded: { bg: 'bg-green-500/20', text: 'text-green-300', ring: 'ring-green-500/50' },
  failed: { bg: 'bg-red-500/20', text: 'text-red-300', ring: 'ring-red-500/50' },
  partial: { bg: 'bg-amber-500/20', text: 'text-amber-300', ring: 'ring-amber-500/50' },
};

export const ACTION_STATUS_COLORS: Record<ActionStatus, string> = {
  pending: 'bg-gray-500/30 text-gray-200',
  in_progress: 'bg-blue-500/30 text-blue-200',
  completed: 'bg-green-500/30 text-green-200',
  blocked: 'bg-red-500/30 text-red-200',
};

export const ORCH_STATUS_COLORS: Record<OrchStatus, string> = {
  pending: 'bg-gray-500/30 text-gray-200',
  running: 'bg-blue-500/30 text-blue-200',
  completed: 'bg-green-500/30 text-green-200',
  failed: 'bg-red-500/30 text-red-200',
  awaiting_human: 'bg-amber-500/30 text-amber-200',
};

/**
 * Persisted pipeline payloads arrive from Python handlers in snake_case, while
 * local editor and websocket mutations use camelCase. Keep both key spellings
 * aligned here so reloaded live state matches in-session live state.
 */
export function getMirroredNodeField<T>(
  node: Record<string, unknown>,
  ...keys: string[]
): T | undefined {
  for (const key of keys) {
    const value = node[key];
    if (value !== undefined && value !== null) {
      return value as T;
    }
  }
  return undefined;
}

// =============================================================================
// Node Data Interfaces
// =============================================================================

export interface IdeaNodeData {
  label: string;
  ideaType: IdeaType;
  agent?: string;
  fullContent?: string;
  contentHash: string;
}

export interface PrincipleNodeData {
  label: string;
  principleType: PrincipleType;
  description?: string;
  sourceIdeaIds?: string[];
  confidence?: number;
  theme?: string;
  contentHash?: string;
}

export interface GoalNodeData {
  label: string;
  goalType: GoalType;
  description: string;
  priority: 'high' | 'medium' | 'low';
  measurable?: boolean;
}

export interface ActionNodeData {
  label: string;
  stepType: ActionType;
  description?: string;
  optional?: boolean;
  timeoutSeconds?: number;
  status?: ActionStatus;
  assignee?: string;
  tags?: string[];
  lockedBy?: string;
}

export interface AlternativeAgent {
  name: string;
  score: number | null;
}

export interface OrchestrationNodeData {
  label: string;
  orchType: OrchType;
  assignedAgent?: string;
  capabilities?: string[];
  agentType?: string;
  status?: OrchStatus;
  description?: string;
  lockedBy?: string;
  eloScore?: number;
  selectionRationale?: string;
  alternativeAgents?: AlternativeAgent[];
  executionStatus?: ExecutionStatus;
  elapsedMs?: number;
  outputPreview?: string;
}

export type PipelineNodeData =
  IdeaNodeData | PrincipleNodeData | GoalNodeData | ActionNodeData | OrchestrationNodeData;

// =============================================================================
// Node Type Configurations (per-stage palette items)
// =============================================================================

export interface NodeTypeConfig {
  label: string;
  icon: string;
  description: string;
  color: string;
  borderColor: string;
  group?: string;
}

export const PIPELINE_NODE_TYPE_CONFIGS: Record<
  PipelineStageType,
  Record<string, NodeTypeConfig>
> = {
  ideas: {
    concept: {
      label: 'Concept',
      icon: '💡',
      description: 'A raw idea or concept',
      color: 'bg-indigo-500/20',
      borderColor: 'border-indigo-500',
    },
    cluster: {
      label: 'Cluster',
      icon: '🔗',
      description: 'Group of related ideas',
      color: 'bg-indigo-500/20',
      borderColor: 'border-indigo-400',
    },
    question: {
      label: 'Question',
      icon: '❓',
      description: 'Open question to resolve',
      color: 'bg-indigo-500/20',
      borderColor: 'border-indigo-300',
    },
    insight: {
      label: 'Insight',
      icon: '🔍',
      description: 'Key insight or finding',
      color: 'bg-indigo-500/20',
      borderColor: 'border-indigo-500',
    },
    evidence: {
      label: 'Evidence',
      icon: '📊',
      description: 'Supporting evidence',
      color: 'bg-indigo-500/20',
      borderColor: 'border-indigo-400',
    },
    assumption: {
      label: 'Assumption',
      icon: '⚠️',
      description: 'Assumption to validate',
      color: 'bg-indigo-500/20',
      borderColor: 'border-indigo-300',
    },
    constraint: {
      label: 'Constraint',
      icon: '🚧',
      description: 'Known constraint',
      color: 'bg-indigo-500/20',
      borderColor: 'border-indigo-400',
    },
  },
  principles: {
    value: {
      label: 'Value',
      icon: '◇',
      description: 'Core value to uphold',
      color: 'bg-violet-500/20',
      borderColor: 'border-violet-500',
    },
    principle: {
      label: 'Principle',
      icon: '◈',
      description: 'Guiding principle',
      color: 'bg-violet-500/20',
      borderColor: 'border-violet-400',
    },
    priority: {
      label: 'Priority',
      icon: '▲',
      description: 'Key priority',
      color: 'bg-violet-500/20',
      borderColor: 'border-violet-500',
    },
    constraint: {
      label: 'Constraint',
      icon: '◻',
      description: 'Hard constraint',
      color: 'bg-violet-500/20',
      borderColor: 'border-violet-400',
    },
    connection: {
      label: 'Connection',
      icon: '◎',
      description: 'Cross-cutting connection',
      color: 'bg-violet-500/20',
      borderColor: 'border-violet-300',
    },
    theme: {
      label: 'Theme',
      icon: '◆',
      description: 'Emergent theme',
      color: 'bg-violet-500/20',
      borderColor: 'border-violet-300',
    },
  },
  goals: {
    goal: {
      label: 'Goal',
      icon: '🎯',
      description: 'Concrete goal to achieve',
      color: 'bg-emerald-500/20',
      borderColor: 'border-emerald-500',
    },
    principle: {
      label: 'Principle',
      icon: '📐',
      description: 'Guiding principle',
      color: 'bg-emerald-500/20',
      borderColor: 'border-emerald-400',
    },
    strategy: {
      label: 'Strategy',
      icon: '♟️',
      description: 'Strategic approach',
      color: 'bg-emerald-500/20',
      borderColor: 'border-emerald-500',
    },
    milestone: {
      label: 'Milestone',
      icon: '🏁',
      description: 'Key milestone',
      color: 'bg-emerald-500/20',
      borderColor: 'border-emerald-400',
    },
    metric: {
      label: 'Metric',
      icon: '📈',
      description: 'Measurable metric',
      color: 'bg-emerald-500/20',
      borderColor: 'border-emerald-300',
    },
    risk: {
      label: 'Risk',
      icon: '⚡',
      description: 'Identified risk',
      color: 'bg-emerald-500/20',
      borderColor: 'border-emerald-500',
    },
  },
  actions: {
    task: {
      label: 'Task',
      icon: '✅',
      description: 'Actionable task',
      color: 'bg-amber-500/20',
      borderColor: 'border-amber-500',
      group: 'Execution',
    },
    epic: {
      label: 'Epic',
      icon: '📋',
      description: 'Large body of work',
      color: 'bg-amber-500/20',
      borderColor: 'border-amber-400',
      group: 'Execution',
    },
    checkpoint: {
      label: 'Checkpoint',
      icon: '🔖',
      description: 'Verification checkpoint',
      color: 'bg-amber-500/20',
      borderColor: 'border-amber-500',
      group: 'Verification',
    },
    deliverable: {
      label: 'Deliverable',
      icon: '📦',
      description: 'Tangible deliverable',
      color: 'bg-amber-500/20',
      borderColor: 'border-amber-400',
      group: 'Management',
    },
    dependency: {
      label: 'Dependency',
      icon: '🔄',
      description: 'External dependency',
      color: 'bg-amber-500/20',
      borderColor: 'border-amber-300',
      group: 'Management',
    },
  },
  orchestration: {
    agent_task: {
      label: 'Agent Task',
      icon: '🤖',
      description: 'Task assigned to an agent',
      color: 'bg-pink-500/20',
      borderColor: 'border-pink-500',
      group: 'Agents',
    },
    debate: {
      label: 'Debate',
      icon: '💬',
      description: 'Multi-agent debate',
      color: 'bg-pink-500/20',
      borderColor: 'border-pink-400',
      group: 'Agents',
    },
    human_gate: {
      label: 'Human Gate',
      icon: '👤',
      description: 'Human approval required',
      color: 'bg-pink-500/20',
      borderColor: 'border-pink-500',
      group: 'Gates',
    },
    parallel_fan: {
      label: 'Parallel Fan',
      icon: '🔀',
      description: 'Parallel execution',
      color: 'bg-pink-500/20',
      borderColor: 'border-pink-400',
      group: 'Control Flow',
    },
    merge: {
      label: 'Merge',
      icon: '🔁',
      description: 'Merge parallel results',
      color: 'bg-pink-500/20',
      borderColor: 'border-pink-300',
      group: 'Control Flow',
    },
    verification: {
      label: 'Verification',
      icon: '🔬',
      description: 'Verify results',
      color: 'bg-pink-500/20',
      borderColor: 'border-pink-500',
      group: 'Gates',
    },
  },
};

export function getDefaultPipelineNodeData(
  stage: PipelineStageType,
  subtype: string,
): PipelineNodeData {
  switch (stage) {
    case 'ideas':
      return {
        label: PIPELINE_NODE_TYPE_CONFIGS.ideas[subtype]?.label || 'New Idea',
        ideaType: subtype as IdeaType,
        contentHash: '',
        fullContent: '',
      };
    case 'principles':
      return {
        label: PIPELINE_NODE_TYPE_CONFIGS.principles[subtype]?.label || 'New Principle',
        principleType: subtype as PrincipleType,
        description: '',
      };
    case 'goals':
      return {
        label: PIPELINE_NODE_TYPE_CONFIGS.goals[subtype]?.label || 'New Goal',
        goalType: subtype as GoalType,
        description: '',
        priority: 'medium',
      };
    case 'actions':
      return {
        label: PIPELINE_NODE_TYPE_CONFIGS.actions[subtype]?.label || 'New Action',
        stepType: subtype as ActionType,
        description: '',
        optional: false,
      };
    case 'orchestration':
      return {
        label: PIPELINE_NODE_TYPE_CONFIGS.orchestration[subtype]?.label || 'New Node',
        orchType: subtype as OrchType,
        assignedAgent: '',
        capabilities: [],
      };
  }
}

export function getNodeTypeForStage(stage: PipelineStageType): string {
  const map: Record<PipelineStageType, string> = {
    ideas: 'ideaNode',
    principles: 'principleNode',
    goals: 'goalNode',
    actions: 'actionNode',
    orchestration: 'orchestrationNode',
  };
  return map[stage];
}

// =============================================================================
// Stage Configuration
// =============================================================================

export interface StageConfig {
  label: string;
  primary: string;
  secondary: string;
  accent: string;
  icon: string;
}

export const PIPELINE_STAGE_CONFIG: Record<PipelineStageType, StageConfig> = {
  ideas: {
    label: 'Ideas',
    primary: '#818cf8',
    secondary: '#c7d2fe',
    accent: '#4f46e5',
    icon: 'lightbulb',
  },
  principles: {
    label: 'Principles',
    primary: '#8B5CF6',
    secondary: '#A78BFA',
    accent: '#C4B5FD',
    icon: '◈',
  },
  goals: {
    label: 'Goals',
    primary: '#34d399',
    secondary: '#a7f3d0',
    accent: '#059669',
    icon: 'target',
  },
  actions: {
    label: 'Actions',
    primary: '#fbbf24',
    secondary: '#fde68a',
    accent: '#d97706',
    icon: 'list',
  },
  orchestration: {
    label: 'Orchestration',
    primary: '#f472b6',
    secondary: '#fbcfe8',
    accent: '#db2777',
    icon: 'cpu',
  },
};

// =============================================================================
// Provenance Types
// =============================================================================

export interface ProvenanceLink {
  source_node_id: string;
  source_stage: PipelineStageType;
  target_node_id: string;
  target_stage: PipelineStageType;
  content_hash: string;
  timestamp: number;
  method: string;
}

export interface StageTransition {
  id: string;
  from_stage: PipelineStageType;
  to_stage: PipelineStageType;
  provenance: ProvenanceLink[];
  status: string;
  confidence: number;
  ai_rationale: string;
  human_notes: string;
  created_at: number;
  reviewed_at: number | null;
}

/** A single step in a provenance breadcrumb trail. */
export interface ProvenanceBreadcrumb {
  nodeId: string;
  nodeLabel: string;
  stage: PipelineStageType;
  contentHash: string;
  method: string;
}

/** Stage color classes for provenance display. */
export const STAGE_COLOR_CLASSES: Record<
  PipelineStageType,
  { text: string; bg: string; border: string }
> = {
  ideas: { text: 'text-indigo-300', bg: 'bg-indigo-500/20', border: 'border-indigo-500' },
  principles: { text: 'text-violet-400', bg: 'bg-violet-500/20', border: 'border-violet-500' },
  goals: { text: 'text-emerald-300', bg: 'bg-emerald-500/20', border: 'border-emerald-500' },
  actions: { text: 'text-amber-300', bg: 'bg-amber-500/20', border: 'border-amber-500' },
  orchestration: { text: 'text-pink-300', bg: 'bg-pink-500/20', border: 'border-pink-500' },
};

// =============================================================================
// API Response Types
// =============================================================================

export interface ReactFlowData {
  nodes: Array<{
    id: string;
    type: string;
    position: { x: number; y: number };
    data: Record<string, unknown>;
    style?: Record<string, string>;
  }>;
  edges: Array<{
    id: string;
    source: string;
    target: string;
    type: string;
    label?: string;
    animated?: boolean;
    style?: Record<string, string>;
    data?: Record<string, unknown>;
  }>;
  metadata: Record<string, unknown>;
}

export interface LiveStateNodeSummary {
  node_id: string;
  label: string;
  orch_type: string;
  status: string;
  execution_status?: string | null;
  assigned_agent?: string | null;
}

export interface UnifiedLiveOrchestrationState {
  status: string;
  runtime?: string | null;
  execution_id?: string | null;
  correlation_id?: string | null;
  tasks_total?: number | null;
  agent_tasks?: number | null;
  total_orchestration_nodes?: number | null;
  counts: Record<string, number>;
  active_nodes: LiveStateNodeSummary[];
}

export interface UnifiedLiveReviewState {
  transition_counts: Record<string, number>;
  pending_reviews: Array<Record<string, unknown>>;
  reviewer_agents: number;
  pending_agents: number;
  human_gates: number;
}

export interface UnifiedLiveRepairState {
  status: string;
  attempts: number;
  active_items: Array<Record<string, unknown>>;
}

export interface UnifiedLiveMergeGateState {
  enabled: boolean;
  checks_passed: boolean;
  merge_eligible: boolean;
  human_approval_required: boolean;
  blocked_reasons: string[];
  expected_checks: string[];
  merge_nodes: number;
}

export interface UnifiedPipelineLiveState {
  orchestration: UnifiedLiveOrchestrationState;
  review: UnifiedLiveReviewState;
  repair: UnifiedLiveRepairState;
  merge_gate: UnifiedLiveMergeGateState;
}

export interface PipelineResultResponse {
  pipeline_id: string;
  ideas: ReactFlowData | null;
  principles: ReactFlowData | null;
  goals: Record<string, unknown> | null;
  actions: ReactFlowData | null;
  orchestration: ReactFlowData | null;
  transitions: StageTransition[];
  provenance: ProvenanceLink[];
  provenance_count: number;
  stage_status: Record<PipelineStageType, string>;
  integrity_hash: string;
  live_state?: UnifiedPipelineLiveState | null;
  execution?: Record<string, unknown> | null;
  agents?: Array<Record<string, unknown>>;
  repair?: Record<string, unknown> | null;
  repairs?: Record<string, unknown> | Array<Record<string, unknown>> | null;
  merge_gate?: Record<string, unknown> | null;
}
