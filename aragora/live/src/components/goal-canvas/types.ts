/**
 * Goal Canvas type definitions.
 *
 * Matches the Python GoalNodeType enum from aragora/canvas/stages.py.
 */

export type GoalNodeType = 'goal' | 'principle' | 'strategy' | 'milestone' | 'metric' | 'risk';

export type GoalEdgeType =
  'requires' | 'blocks' | 'follows' | 'derived_from' | 'supports' | 'conflicts' | 'decomposes_into';

export type GoalPriority = 'critical' | 'high' | 'medium' | 'low';

export interface GoalNodeData {
  goalType: GoalNodeType;
  label: string;
  description: string;
  priority: GoalPriority;
  measurable: string;
  confidence: number;
  tags: string[];
  sourceIdeaIds?: string[];
  creatorId?: string;
  kmNodeId?: string;
  lockedBy?: string;
  stage: 'goals';
  rfType: 'goalNode';
}

export interface GoalTypeConfig {
  icon: string;
  color: string;
  borderColor: string;
  label: string;
  description: string;
  group: 'Objectives' | 'Strategy' | 'Tracking';
}

export const GOAL_NODE_CONFIGS: Record<GoalNodeType, GoalTypeConfig> = {
  goal: {
    icon: 'G',
    color: 'bg-emerald-500/20',
    borderColor: 'border-emerald-500',
    label: 'Goal',
    description: 'Actionable objective',
    group: 'Objectives',
  },
  principle: {
    icon: 'P',
    color: 'bg-emerald-600/20',
    borderColor: 'border-emerald-600',
    label: 'Principle',
    description: 'Guiding principle',
    group: 'Objectives',
  },
  strategy: {
    icon: 'S',
    color: 'bg-teal-500/20',
    borderColor: 'border-teal-500',
    label: 'Strategy',
    description: 'Strategic approach',
    group: 'Strategy',
  },
  milestone: {
    icon: 'M',
    color: 'bg-emerald-400/20',
    borderColor: 'border-emerald-400',
    label: 'Milestone',
    description: 'Key checkpoint',
    group: 'Strategy',
  },
  metric: {
    icon: '#',
    color: 'bg-teal-400/20',
    borderColor: 'border-teal-400',
    label: 'Metric',
    description: 'Measurable KPI',
    group: 'Tracking',
  },
  risk: {
    icon: '!',
    color: 'bg-red-500/20',
    borderColor: 'border-red-500',
    label: 'Risk',
    description: 'Identified risk',
    group: 'Tracking',
  },
};

export const PRIORITY_COLORS: Record<GoalPriority, string> = {
  critical: 'bg-red-500/30 text-red-200',
  high: 'bg-orange-500/30 text-orange-200',
  medium: 'bg-amber-500/30 text-amber-200',
  low: 'bg-green-500/30 text-green-200',
};

export interface GoalCanvasMeta {
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
