'use client';

import { memo, useCallback, useState } from 'react';
import {
  PIPELINE_STAGE_CONFIG,
  STAGE_COLOR_CLASSES,
  getMirroredNodeField,
  type PipelineStageType,
  type IdeaType,
  type GoalType,
  type ActionType,
  type OrchType,
  type ActionStatus,
  type OrchStatus,
  type ProvenanceLink,
  type StageTransition,
} from '../types';
import { InputField, SelectField, SliderField, CheckboxField } from './shared-fields';

/* -------------------------------------------------------------------------- */
/*  Props                                                                     */
/* -------------------------------------------------------------------------- */

type EditorTab = 'properties' | 'provenance';

interface PipelinePropertyEditorProps {
  node: Record<string, unknown> | null;
  stage: PipelineStageType;
  onUpdate: (updates: Record<string, unknown>) => void;
  onDelete: () => void;
  onShowProvenance?: () => void;
  readOnly?: boolean;
  /** Provenance links relevant to the selected node. */
  provenanceLinks?: ProvenanceLink[];
  /** Transitions that involve this node's stage. */
  transitions?: StageTransition[];
}

/* -------------------------------------------------------------------------- */
/*  Option lists                                                              */
/* -------------------------------------------------------------------------- */

const IDEA_TYPE_OPTIONS: Array<{ value: IdeaType; label: string }> = [
  { value: 'concept', label: 'Concept' },
  { value: 'cluster', label: 'Cluster' },
  { value: 'question', label: 'Question' },
  { value: 'insight', label: 'Insight' },
  { value: 'evidence', label: 'Evidence' },
  { value: 'assumption', label: 'Assumption' },
  { value: 'constraint', label: 'Constraint' },
];

const GOAL_TYPE_OPTIONS: Array<{ value: GoalType; label: string }> = [
  { value: 'goal', label: 'Goal' },
  { value: 'principle', label: 'Principle' },
  { value: 'strategy', label: 'Strategy' },
  { value: 'milestone', label: 'Milestone' },
  { value: 'metric', label: 'Metric' },
  { value: 'risk', label: 'Risk' },
];

const ACTION_TYPE_OPTIONS: Array<{ value: ActionType; label: string }> = [
  { value: 'task', label: 'Task' },
  { value: 'epic', label: 'Epic' },
  { value: 'checkpoint', label: 'Checkpoint' },
  { value: 'deliverable', label: 'Deliverable' },
  { value: 'dependency', label: 'Dependency' },
];

const ORCH_TYPE_OPTIONS: Array<{ value: OrchType; label: string }> = [
  { value: 'agent_task', label: 'Agent Task' },
  { value: 'debate', label: 'Debate' },
  { value: 'human_gate', label: 'Human Gate' },
  { value: 'parallel_fan', label: 'Parallel Fan' },
  { value: 'merge', label: 'Merge' },
  { value: 'verification', label: 'Verification' },
];

const ACTION_STATUS_OPTIONS: Array<{ value: ActionStatus; label: string }> = [
  { value: 'pending', label: 'Pending' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'completed', label: 'Completed' },
  { value: 'blocked', label: 'Blocked' },
];

const ORCH_STATUS_OPTIONS: Array<{ value: OrchStatus; label: string }> = [
  { value: 'pending', label: 'Pending' },
  { value: 'running', label: 'Running' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'awaiting_human', label: 'Awaiting Human' },
];

const PRIORITY_OPTIONS = [
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
];

/* -------------------------------------------------------------------------- */
/*  Stage sub-editors                                                         */
/* -------------------------------------------------------------------------- */

function IdeasEditor({
  node,
  onUpdate,
  readOnly,
}: {
  node: Record<string, unknown>;
  onUpdate: (updates: Record<string, unknown>) => void;
  readOnly?: boolean;
}) {
  if (readOnly) {
    return (
      <>
        <ReadOnlyField label="Idea Type" value={String(node.ideaType ?? '')} />
        <ReadOnlyField label="Full Content" value={String(node.fullContent ?? '')} />
        <ReadOnlyField label="Agent" value={String(node.agent ?? '')} />
      </>
    );
  }

  return (
    <>
      <SelectField
        label="Idea Type"
        value={String(node.ideaType ?? 'concept')}
        options={IDEA_TYPE_OPTIONS}
        onChange={(v) => onUpdate({ ideaType: v })}
      />
      <InputField
        label="Full Content"
        value={String(node.fullContent ?? '')}
        onChange={(v) => onUpdate({ fullContent: v })}
        placeholder="Describe this idea..."
        type="textarea"
      />
      <InputField
        label="Agent"
        value={String(node.agent ?? '')}
        onChange={(v) => onUpdate({ agent: v })}
        placeholder="Originating agent"
      />
    </>
  );
}

function GoalsEditor({
  node,
  onUpdate,
  readOnly,
}: {
  node: Record<string, unknown>;
  onUpdate: (updates: Record<string, unknown>) => void;
  readOnly?: boolean;
}) {
  const confidence = typeof node.confidence === 'number' ? node.confidence : 50;
  const tagsRaw = node.tags;
  const tagsStr = Array.isArray(tagsRaw)
    ? tagsRaw.join(', ')
    : typeof tagsRaw === 'string'
      ? tagsRaw
      : '';

  if (readOnly) {
    return (
      <>
        <ReadOnlyField label="Goal Type" value={String(node.goalType ?? '')} />
        <ReadOnlyField label="Description" value={String(node.description ?? '')} />
        <ReadOnlyField label="Priority" value={String(node.priority ?? '')} />
        <ReadOnlyField label="Confidence" value={`${confidence}%`} />
        <ReadOnlyField label="Tags" value={tagsStr} />
      </>
    );
  }

  return (
    <>
      <SelectField
        label="Goal Type"
        value={String(node.goalType ?? 'goal')}
        options={GOAL_TYPE_OPTIONS}
        onChange={(v) => onUpdate({ goalType: v })}
      />
      <InputField
        label="Description"
        value={String(node.description ?? '')}
        onChange={(v) => onUpdate({ description: v })}
        placeholder="Describe this goal..."
        type="textarea"
      />
      <SelectField
        label="Priority"
        value={String(node.priority ?? 'medium')}
        options={PRIORITY_OPTIONS}
        onChange={(v) => onUpdate({ priority: v })}
      />
      <SliderField
        label="Confidence"
        value={confidence}
        onChange={(v) => onUpdate({ confidence: v })}
        min={0}
        max={100}
        formatLabel={(v) => `${v}%`}
      />
      <InputField
        label="Tags (comma-separated)"
        value={tagsStr}
        onChange={(v) =>
          onUpdate({
            tags: v
              .split(',')
              .map((t) => t.trim())
              .filter(Boolean),
          })
        }
        placeholder="e.g., ux, backend, critical"
      />
    </>
  );
}

function ActionsEditor({
  node,
  onUpdate,
  readOnly,
}: {
  node: Record<string, unknown>;
  onUpdate: (updates: Record<string, unknown>) => void;
  readOnly?: boolean;
}) {
  const tagsRaw = node.tags;
  const tagsStr = Array.isArray(tagsRaw)
    ? tagsRaw.join(', ')
    : typeof tagsRaw === 'string'
      ? tagsRaw
      : '';

  if (readOnly) {
    return (
      <>
        <ReadOnlyField label="Step Type" value={String(node.stepType ?? '')} />
        <ReadOnlyField label="Status" value={String(node.status ?? 'pending').replace('_', ' ')} />
        <ReadOnlyField label="Description" value={String(node.description ?? '')} />
        <ReadOnlyField label="Assignee" value={String(node.assignee ?? '')} />
        <ReadOnlyField label="Optional" value={node.optional ? 'Yes' : 'No'} />
        <ReadOnlyField label="Tags" value={tagsStr} />
        <ReadOnlyField
          label="Timeout (seconds)"
          value={node.timeoutSeconds != null ? String(node.timeoutSeconds) : ''}
        />
      </>
    );
  }

  return (
    <>
      <SelectField
        label="Step Type"
        value={String(node.stepType ?? 'task')}
        options={ACTION_TYPE_OPTIONS}
        onChange={(v) => onUpdate({ stepType: v })}
      />
      <SelectField
        label="Status"
        value={String(node.status ?? 'pending')}
        options={ACTION_STATUS_OPTIONS}
        onChange={(v) => onUpdate({ status: v })}
      />
      <InputField
        label="Description"
        value={String(node.description ?? '')}
        onChange={(v) => onUpdate({ description: v })}
        placeholder="What does this step do?"
        type="textarea"
      />
      <InputField
        label="Assignee"
        value={String(node.assignee ?? '')}
        onChange={(v) => onUpdate({ assignee: v })}
        placeholder="e.g., john, team-alpha"
      />
      <CheckboxField
        label="Optional"
        checked={!!node.optional}
        onChange={(v) => onUpdate({ optional: v })}
        description="Can be skipped without blocking the pipeline"
      />
      <InputField
        label="Tags (comma-separated)"
        value={tagsStr}
        onChange={(v) =>
          onUpdate({
            tags: v
              .split(',')
              .map((t) => t.trim())
              .filter(Boolean),
          })
        }
        placeholder="e.g., backend, critical, sprint-3"
      />
      <InputField
        label="Timeout (seconds)"
        value={node.timeoutSeconds != null ? String(node.timeoutSeconds) : ''}
        onChange={(v) => onUpdate({ timeoutSeconds: v ? parseInt(v, 10) || 0 : undefined })}
        placeholder="e.g., 300"
        type="number"
      />
    </>
  );
}

function OrchestrationEditor({
  node,
  onUpdate,
  readOnly,
}: {
  node: Record<string, unknown>;
  onUpdate: (updates: Record<string, unknown>) => void;
  readOnly?: boolean;
}) {
  const capsRaw = node.capabilities;
  const capsStr = Array.isArray(capsRaw)
    ? capsRaw.join(', ')
    : typeof capsRaw === 'string'
      ? capsRaw
      : '';

  if (readOnly) {
    return (
      <>
        <ReadOnlyField
          label="Orchestration Type"
          value={String(getMirroredNodeField(node, 'orchType', 'orch_type') ?? '')}
        />
        <ReadOnlyField label="Status" value={String(node.status ?? 'pending').replace('_', ' ')} />
        <ReadOnlyField label="Description" value={String(node.description ?? '')} />
        <ReadOnlyField
          label="Assigned Agent"
          value={String(getMirroredNodeField(node, 'assignedAgent', 'assigned_agent') ?? '')}
        />
        <ReadOnlyField
          label="Agent Type"
          value={String(getMirroredNodeField(node, 'agentType', 'agent_type') ?? '')}
        />
        <ReadOnlyField label="Capabilities" value={capsStr} />
      </>
    );
  }

  return (
    <>
      <SelectField
        label="Orchestration Type"
        value={String(getMirroredNodeField(node, 'orchType', 'orch_type') ?? 'agent_task')}
        options={ORCH_TYPE_OPTIONS}
        onChange={(v) => onUpdate({ orchType: v })}
      />
      <SelectField
        label="Status"
        value={String(node.status ?? 'pending')}
        options={ORCH_STATUS_OPTIONS}
        onChange={(v) => onUpdate({ status: v })}
      />
      <InputField
        label="Description"
        value={String(node.description ?? '')}
        onChange={(v) => onUpdate({ description: v })}
        placeholder="Describe this orchestration step..."
        type="textarea"
      />
      <InputField
        label="Assigned Agent"
        value={String(getMirroredNodeField(node, 'assignedAgent', 'assigned_agent') ?? '')}
        onChange={(v) => onUpdate({ assignedAgent: v })}
        placeholder="e.g., claude, gpt-4"
      />
      <InputField
        label="Agent Type"
        value={String(getMirroredNodeField(node, 'agentType', 'agent_type') ?? '')}
        onChange={(v) => onUpdate({ agentType: v })}
        placeholder="e.g., reviewer, coder"
      />
      <InputField
        label="Capabilities (comma-separated)"
        value={capsStr}
        onChange={(v) =>
          onUpdate({
            capabilities: v
              .split(',')
              .map((c) => c.trim())
              .filter(Boolean),
          })
        }
        placeholder="e.g., code_review, testing"
      />
    </>
  );
}

/* -------------------------------------------------------------------------- */
/*  ReadOnlyField helper                                                      */
/* -------------------------------------------------------------------------- */

function ReadOnlyField({ label, value }: { label: string; value: string }) {
  return (
    <div className="mb-3">
      <label className="block text-xs text-text-muted mb-1">{label}</label>
      <p className="text-sm text-text font-theme-data bg-bg border border-border rounded px-2 py-1.5 opacity-70">
        {value || <span className="text-text-muted italic">--</span>}
      </p>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Provenance tab content                                                     */
/* -------------------------------------------------------------------------- */

function ProvenanceTab({
  provenanceLinks,
  transitions,
  stage,
}: {
  provenanceLinks: ProvenanceLink[];
  transitions: StageTransition[];
  stage: PipelineStageType;
}) {
  if (provenanceLinks.length === 0 && transitions.length === 0) {
    return (
      <div className="text-center text-text-muted py-6">
        <p className="text-sm font-theme-data">No provenance data for this node.</p>
      </div>
    );
  }

  // Find the deepest chain depth by counting unique stages in the links
  const stagesInChain = new Set<string>();
  for (const link of provenanceLinks) {
    stagesInChain.add(link.source_stage);
    stagesInChain.add(link.target_stage);
  }
  const chainDepth = stagesInChain.size;

  // Find the relevant transition for this stage
  const relevantTransition = transitions.find(
    (t) => t.to_stage === stage || t.from_stage === stage,
  );

  return (
    <div data-testid="provenance-tab">
      {/* Chain depth indicator */}
      <div className="mb-4">
        <label className="block text-xs text-text-muted mb-2">Chain Depth</label>
        <div className="flex items-center gap-1">
          {(['ideas', 'goals', 'actions', 'orchestration'] as PipelineStageType[]).map((s) => {
            const colors = STAGE_COLOR_CLASSES[s];
            const config = PIPELINE_STAGE_CONFIG[s];
            const isActive = stagesInChain.has(s);
            return (
              <div
                key={s}
                className={`flex-1 h-2 rounded-full transition-opacity ${isActive ? colors.bg : 'bg-border'}`}
                style={
                  isActive ? { backgroundColor: config.primary, opacity: 1 } : { opacity: 0.3 }
                }
                title={`${config.label}${isActive ? ' (in chain)' : ''}`}
              />
            );
          })}
        </div>
        <p className="text-xs text-text-muted font-theme-data mt-1">
          {chainDepth} stage{chainDepth !== 1 ? 's' : ''} in provenance chain
        </p>
      </div>

      {/* Transition details */}
      {relevantTransition && (
        <div className="mb-4 p-3 bg-bg border border-border rounded">
          <label className="block text-xs text-text-muted mb-2 uppercase font-bold">
            Transition
          </label>
          <div className="space-y-1 text-xs font-theme-data">
            <div className="flex justify-between">
              <span className="text-text-muted">From</span>
              <span className={STAGE_COLOR_CLASSES[relevantTransition.from_stage]?.text}>
                {relevantTransition.from_stage}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">To</span>
              <span className={STAGE_COLOR_CLASSES[relevantTransition.to_stage]?.text}>
                {relevantTransition.to_stage}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Confidence</span>
              <span className="text-text">{(relevantTransition.confidence * 100).toFixed(0)}%</span>
            </div>
            <div className="flex justify-between">
              <span className="text-text-muted">Status</span>
              <span className="text-text">{relevantTransition.status}</span>
            </div>
            {relevantTransition.ai_rationale && (
              <div className="mt-2 pt-2 border-t border-border">
                <span className="text-text-muted">Rationale: </span>
                <span className="text-text">{relevantTransition.ai_rationale}</span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Individual provenance links */}
      <label className="block text-xs text-text-muted mb-2 uppercase font-bold">
        Provenance Links ({provenanceLinks.length})
      </label>
      <div className="space-y-2">
        {provenanceLinks.map((link, i) => {
          const sourceColors = STAGE_COLOR_CLASSES[link.source_stage];
          const targetColors = STAGE_COLOR_CLASSES[link.target_stage];
          return (
            <div
              key={i}
              className="p-2 bg-bg rounded border border-border"
              data-testid="provenance-link"
            >
              <div className="flex items-center gap-1 text-xs font-theme-data mb-1">
                <span className={`px-1 py-0.5 rounded ${sourceColors?.bg} ${sourceColors?.text}`}>
                  {link.source_stage}
                </span>
                <svg
                  className="w-3 h-3 text-text-muted"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>
                <span className={`px-1 py-0.5 rounded ${targetColors?.bg} ${targetColors?.text}`}>
                  {link.target_stage}
                </span>
              </div>
              <div className="text-xs font-theme-data text-text-muted space-y-0.5">
                <p className="truncate">
                  Source: <span className="text-text">{link.source_node_id}</span>
                </p>
                <p className="truncate">
                  Target: <span className="text-text">{link.target_node_id}</span>
                </p>
                <div className="flex gap-3 mt-1">
                  <span>#{link.content_hash.slice(0, 8)}</span>
                  {link.method && <span>{link.method}</span>}
                </div>
                {link.timestamp > 0 && (
                  <p className="text-text-muted opacity-60">
                    {new Date(link.timestamp * 1000).toLocaleString()}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/*  Main component                                                            */
/* -------------------------------------------------------------------------- */

export const PipelinePropertyEditor = memo(function PipelinePropertyEditor({
  node,
  stage,
  onUpdate,
  onDelete,
  onShowProvenance,
  readOnly,
  provenanceLinks = [],
  transitions = [],
}: PipelinePropertyEditorProps) {
  const [activeTab, setActiveTab] = useState<EditorTab>('properties');

  const handleLabelChange = useCallback((label: string) => onUpdate({ label }), [onUpdate]);

  /* -- Empty state -------------------------------------------------------- */
  if (!node) {
    return (
      <div className="w-72 flex-shrink-0 bg-surface border-l border-border h-full overflow-y-auto p-4">
        <div className="text-center text-text-muted py-8">
          <p className="text-sm font-theme-data">Select a node to edit its properties.</p>
        </div>
      </div>
    );
  }

  const stageConfig = PIPELINE_STAGE_CONFIG[stage];
  const hasProvenance = provenanceLinks.length > 0 || transitions.length > 0;

  return (
    <div className="w-72 flex-shrink-0 bg-surface border-l border-border h-full overflow-y-auto p-4">
      {/* Stage-colored header bar */}
      <div
        className="flex items-center gap-2 mb-3 pb-3 border-b border-border"
        style={{ borderBottomColor: stageConfig.primary }}
      >
        <div className="w-1 h-8 rounded-full" style={{ backgroundColor: stageConfig.primary }} />
        <div>
          <h3 className="text-sm font-theme-data font-bold text-text uppercase">
            {stageConfig.label} Properties
          </h3>
          <p className="text-xs text-text-muted font-theme-data">
            Stage: <span style={{ color: stageConfig.primary }}>{stage}</span>
          </p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 mb-4">
        <button
          onClick={() => setActiveTab('properties')}
          className={`flex-1 px-2 py-1.5 text-xs font-theme-data font-bold uppercase rounded transition-colors ${
            activeTab === 'properties'
              ? 'bg-bg text-text border border-border'
              : 'text-text-muted hover:text-text'
          }`}
          data-testid="tab-properties"
        >
          Properties
        </button>
        <button
          onClick={() => setActiveTab('provenance')}
          className={`flex-1 px-2 py-1.5 text-xs font-theme-data font-bold uppercase rounded transition-colors flex items-center justify-center gap-1 ${
            activeTab === 'provenance'
              ? 'bg-bg text-text border border-border'
              : 'text-text-muted hover:text-text'
          }`}
          data-testid="tab-provenance"
        >
          Provenance
          {hasProvenance && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />}
        </button>
      </div>

      {/* Tab content: Properties */}
      {activeTab === 'properties' && (
        <>
          {/* Common field: Label */}
          {readOnly ? (
            <ReadOnlyField label="Label" value={String(node.label ?? '')} />
          ) : (
            <InputField
              label="Label"
              value={String(node.label ?? '')}
              onChange={handleLabelChange}
              placeholder="Node label"
            />
          )}

          {/* Stage-specific fields */}
          <div className="mt-4 pt-4 border-t border-border">
            {stage === 'ideas' && (
              <IdeasEditor node={node} onUpdate={onUpdate} readOnly={readOnly} />
            )}
            {stage === 'goals' && (
              <GoalsEditor node={node} onUpdate={onUpdate} readOnly={readOnly} />
            )}
            {stage === 'actions' && (
              <ActionsEditor node={node} onUpdate={onUpdate} readOnly={readOnly} />
            )}
            {stage === 'orchestration' && (
              <OrchestrationEditor node={node} onUpdate={onUpdate} readOnly={readOnly} />
            )}
          </div>
        </>
      )}

      {/* Tab content: Provenance */}
      {activeTab === 'provenance' && (
        <ProvenanceTab provenanceLinks={provenanceLinks} transitions={transitions} stage={stage} />
      )}

      {/* Bottom actions */}
      <div className="mt-6 pt-4 border-t border-border space-y-2">
        {onShowProvenance && activeTab === 'properties' && (
          <button
            onClick={onShowProvenance}
            className="w-full px-4 py-2 bg-surface border border-border text-text font-theme-data text-sm hover:bg-bg transition-colors rounded"
          >
            View Provenance
          </button>
        )}
        {!readOnly && (
          <button
            onClick={onDelete}
            className="w-full px-4 py-2 bg-red-500/20 border border-red-500/50 text-red-400 font-theme-data text-sm hover:bg-red-500/30 transition-colors rounded"
          >
            Delete Node
          </button>
        )}
      </div>
    </div>
  );
});

export default PipelinePropertyEditor;
