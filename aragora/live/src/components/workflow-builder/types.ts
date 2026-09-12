/**
 * Workflow Builder Type Definitions
 */

import type { Node, Edge } from '@xyflow/react';

// =============================================================================
// Node Data Types
// =============================================================================

export type WorkflowStepType =
  | 'debate'
  | 'task'
  | 'decision'
  | 'human_checkpoint'
  | 'memory_read'
  | 'memory_write'
  | 'parallel'
  | 'loop';

export interface BaseNodeData extends Record<string, unknown> {
  label: string;
  description?: string;
  stepId: string;
}

export interface DebateNodeData extends BaseNodeData {
  type: 'debate';
  agents: string[];
  rounds: number;
  topicTemplate?: string;
}

export interface TaskNodeData extends BaseNodeData {
  type: 'task';
  taskType: 'validate' | 'transform' | 'aggregate' | 'function' | 'http';
  functionName?: string;
  template?: string;
  validationRules?: string[];
}

export interface DecisionNodeData extends BaseNodeData {
  type: 'decision';
  condition: string;
  trueTarget?: string;
  falseTarget?: string;
}

export interface HumanCheckpointNodeData extends BaseNodeData {
  type: 'human_checkpoint';
  approvalType: 'review' | 'sign_off' | 'revision' | 'presentation';
  requiredRole?: string;
  requiredRoles?: string[];
  checklist?: string[];
  notificationRoles?: string[];
}

export interface MemoryReadNodeData extends BaseNodeData {
  type: 'memory_read';
  queryTemplate: string;
  domains: string[];
}

export interface MemoryWriteNodeData extends BaseNodeData {
  type: 'memory_write';
  domain: string;
  retentionYears?: number;
}

export interface ParallelNodeData extends BaseNodeData {
  type: 'parallel';
  branches: string[]; // IDs of branch start nodes
}

export interface LoopNodeData extends BaseNodeData {
  type: 'loop';
  maxIterations: number;
  condition: string;
  bodyStart?: string; // ID of loop body start node
}

export type WorkflowNodeData =
  | DebateNodeData
  | TaskNodeData
  | DecisionNodeData
  | HumanCheckpointNodeData
  | MemoryReadNodeData
  | MemoryWriteNodeData
  | ParallelNodeData
  | LoopNodeData;

// Use generic Node type with any data to avoid strict typing issues with @xyflow/react v12
export type WorkflowNode = Node;
export type WorkflowEdge = Edge;

// =============================================================================
// Workflow Definition
// =============================================================================

export interface WorkflowDefinition {
  id: string;
  name: string;
  description: string;
  category: string;
  version: string;
  tags: string[];
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  createdAt: string;
  updatedAt: string;
}

// =============================================================================
// Template Types (from backend)
// =============================================================================

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  category: string;
  version: string;
  tags: string[];
  steps: WorkflowStep[];
  transitions: WorkflowTransition[];
}

export interface WorkflowStep {
  id: string;
  type: WorkflowStepType;
  name: string;
  description?: string;
  config: Record<string, unknown>;
  branches?: WorkflowBranch[];
}

export interface WorkflowBranch {
  id: string;
  steps: WorkflowStep[];
}

export interface WorkflowTransition {
  from: string;
  to: string;
  condition?: string;
}

// =============================================================================
// Node Configuration
// =============================================================================

export interface NodeTypeConfig {
  type: WorkflowStepType;
  label: string;
  icon: string;
  color: string;
  borderColor: string;
  description: string;
}

export const NODE_TYPE_CONFIGS: Record<WorkflowStepType, NodeTypeConfig> = {
  debate: {
    type: 'debate',
    label: 'Debate',
    icon: '💬',
    color: 'bg-purple-500/20',
    borderColor: 'border-purple-500',
    description: 'Multi-agent debate step',
  },
  task: {
    type: 'task',
    label: 'Task',
    icon: '⚙️',
    color: 'bg-blue-500/20',
    borderColor: 'border-blue-500',
    description: 'Execute a task or function',
  },
  decision: {
    type: 'decision',
    label: 'Decision',
    icon: '🔀',
    color: 'bg-yellow-500/20',
    borderColor: 'border-yellow-500',
    description: 'Conditional branching',
  },
  human_checkpoint: {
    type: 'human_checkpoint',
    label: 'Human Review',
    icon: '👤',
    color: 'bg-green-500/20',
    borderColor: 'border-green-500',
    description: 'Human approval gate',
  },
  memory_read: {
    type: 'memory_read',
    label: 'Memory Read',
    icon: '📖',
    color: 'bg-cyan-500/20',
    borderColor: 'border-cyan-500',
    description: 'Read from knowledge base',
  },
  memory_write: {
    type: 'memory_write',
    label: 'Memory Write',
    icon: '💾',
    color: 'bg-cyan-500/20',
    borderColor: 'border-cyan-500',
    description: 'Write to knowledge base',
  },
  parallel: {
    type: 'parallel',
    label: 'Parallel',
    icon: '⚡',
    color: 'bg-orange-500/20',
    borderColor: 'border-orange-500',
    description: 'Execute branches in parallel',
  },
  loop: {
    type: 'loop',
    label: 'Loop',
    icon: '🔄',
    color: 'bg-pink-500/20',
    borderColor: 'border-pink-500',
    description: 'Repeat steps until condition',
  },
};

// =============================================================================
// Canvas State
// =============================================================================

export interface CanvasState {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  selectedNodeId: string | null;
  zoom: number;
  position: { x: number; y: number };
}

// =============================================================================
// Available Personas (for debate node configuration)
// =============================================================================

export const AVAILABLE_PERSONAS = {
  general: ['claude', 'gpt4', 'gemini', 'deepseek', 'mistral'],
  legal: [
    'contract_analyst',
    'compliance_officer',
    'litigation_support',
    'm_and_a_counsel',
    'ip_counsel',
    'employment_counsel',
    'regulatory_counsel',
    'ethics_counsel',
  ],
  healthcare: [
    'clinical_reviewer',
    'hipaa_auditor',
    'research_analyst_clinical',
    'medical_coder',
    'patient_safety_officer',
    'quality_assurance_nurse',
  ],
  accounting: [
    'financial_auditor',
    'tax_specialist',
    'forensic_accountant',
    'internal_auditor',
    'sox',
    'pci_dss',
  ],
  code: [
    'code_security_specialist',
    'architecture_reviewer',
    'code_quality_reviewer',
    'api_design_reviewer',
    'performance_engineer',
    'devops_engineer',
    'security_engineer',
    'data_architect',
  ],
  academic: ['research_methodologist', 'peer_reviewer', 'grant_reviewer', 'irb_reviewer'],
};
