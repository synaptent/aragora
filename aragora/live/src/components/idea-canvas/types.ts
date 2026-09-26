/**
 * Idea Canvas type definitions.
 *
 * Matches the Python IdeaNodeType enum and StageEdgeType idea subset.
 */

export type IdeaNodeType =
  | 'concept'
  | 'cluster'
  | 'question'
  | 'insight'
  | 'evidence'
  | 'assumption'
  | 'constraint'
  | 'observation'
  | 'hypothesis';

export type IdeaEdgeType =
  'supports' | 'refutes' | 'inspires' | 'refines' | 'challenges' | 'exemplifies' | 'relates_to';

export interface IdeaNodeData {
  ideaType: IdeaNodeType;
  label: string;
  body: string;
  confidence: number;
  tags: string[];
  creatorId?: string;
  kmNodeId?: string;
  lockedBy?: string;
  promotedToGoalId?: string;
  stage: 'ideas';
  rfType: 'ideaNode';
}

export interface NodeTypeConfig {
  icon: string;
  color: string;
  borderColor: string;
  label: string;
  description: string;
  group: 'Core' | 'Analysis' | 'Structure';
}

export const IDEA_NODE_CONFIGS: Record<IdeaNodeType, NodeTypeConfig> = {
  concept: {
    icon: '~',
    color: 'bg-indigo-500/20',
    borderColor: 'border-indigo-500',
    label: 'Concept',
    description: 'Core idea or theme',
    group: 'Core',
  },
  observation: {
    icon: '.',
    color: 'bg-emerald-500/20',
    borderColor: 'border-emerald-500',
    label: 'Observation',
    description: 'Empirical data point',
    group: 'Core',
  },
  question: {
    icon: '?',
    color: 'bg-violet-500/20',
    borderColor: 'border-violet-500',
    label: 'Question',
    description: 'Open question to resolve',
    group: 'Core',
  },
  hypothesis: {
    icon: 'H',
    color: 'bg-purple-500/20',
    borderColor: 'border-purple-500',
    label: 'Hypothesis',
    description: 'Testable prediction',
    group: 'Analysis',
  },
  insight: {
    icon: '*',
    color: 'bg-violet-600/20',
    borderColor: 'border-violet-600',
    label: 'Insight',
    description: 'Derived understanding',
    group: 'Analysis',
  },
  evidence: {
    icon: '#',
    color: 'bg-purple-700/20',
    borderColor: 'border-purple-700',
    label: 'Evidence',
    description: 'Supporting evidence',
    group: 'Analysis',
  },
  cluster: {
    icon: '@',
    color: 'bg-indigo-600/20',
    borderColor: 'border-indigo-600',
    label: 'Cluster',
    description: 'Group of related ideas',
    group: 'Structure',
  },
  assumption: {
    icon: '!',
    color: 'bg-violet-300/20',
    borderColor: 'border-violet-300',
    label: 'Assumption',
    description: 'Underlying assumption',
    group: 'Structure',
  },
  constraint: {
    icon: '|',
    color: 'bg-violet-200/20',
    borderColor: 'border-violet-200',
    label: 'Constraint',
    description: 'Limiting factor',
    group: 'Structure',
  },
};

export interface IdeaCanvasMeta {
  id: string;
  name: string;
  owner_id: string | null;
  workspace_id: string | null;
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
