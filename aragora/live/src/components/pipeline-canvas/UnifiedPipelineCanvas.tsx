'use client';

/**
 * UnifiedPipelineCanvas - All 4 pipeline stages on a single React Flow canvas
 * with semantic zoom: zoom level determines which stages show full detail vs collapsed.
 *
 * Stages:
 *   Idea (blue #3B82F6) -> Goal (green #10B981) -> Action (orange #F59E0B) -> Orchestration (purple #8B5CF6)
 *
 * Semantic zoom levels:
 *   > 1.5   : All stages with full detail
 *   0.8-1.5 : Ideas + Goals + Actions (Orchestration collapsed)
 *   < 0.8   : Ideas + Goals only (collapsed view)
 */

import { useCallback, useState, useMemo, useEffect } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  useReactFlow,
  ReactFlowProvider,
  Panel,
  BackgroundVariant,
  type NodeTypes,
  type Node,
  type Edge,
  type Viewport,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { IdeaNode, PrincipleNode, GoalNode, ActionNode, OrchestrationNode } from './nodes';
import {
  PIPELINE_STAGE_CONFIG,
  type PipelineStageType,
  type PipelineResultResponse,
  type ProvenanceLink,
  type StageTransition,
  type UnifiedPipelineLiveState,
} from './types';
import { usePipelineCanvas } from '../../hooks/usePipelineCanvas';
import { StageTransitionGate } from '../pipeline/StageTransitionGate';

// =============================================================================
// Constants
// =============================================================================

const nodeTypes: NodeTypes = {
  ideaNode: IdeaNode,
  principleNode: PrincipleNode,
  goalNode: GoalNode,
  actionNode: ActionNode,
  orchestrationNode: OrchestrationNode,
};

const ALL_STAGES: PipelineStageType[] = [
  'ideas',
  'principles',
  'goals',
  'actions',
  'orchestration',
];

const STAGE_OFFSET_X: Record<string, number> = {
  ideas: 0,
  principles: 600,
  goals: 1200,
  actions: 1800,
  orchestration: 2400,
};

/** Stage colors from the spec */
const STAGE_COLORS: Record<PipelineStageType, string> = {
  ideas: '#3B82F6',
  principles: '#8B5CF6',
  goals: '#10B981',
  actions: '#F59E0B',
  orchestration: '#8B5CF6',
};

/** Edge type visual configs */
const EDGE_STYLES: Record<
  string,
  { stroke: string; strokeDasharray?: string; animated?: boolean }
> = {
  inspires: { stroke: '#3B82F6', strokeDasharray: '5 5' },
  derives: { stroke: '#10B981' },
  decomposes: { stroke: '#F59E0B' },
  triggers: { stroke: '#8B5CF6' },
  depends_on: { stroke: '#6b7280', strokeDasharray: '2 2' },
};

/** Semantic zoom thresholds */
const ZOOM_FULL_DETAIL = 1.5;
const ZOOM_PARTIAL = 0.8;

// =============================================================================
// Helper: determine visible stages at a zoom level
// =============================================================================

function getVisibleStages(zoom: number): Set<PipelineStageType> {
  if (zoom > ZOOM_FULL_DETAIL) {
    return new Set(ALL_STAGES);
  }
  if (zoom >= ZOOM_PARTIAL) {
    return new Set<PipelineStageType>(['ideas', 'principles', 'goals', 'actions']);
  }
  return new Set<PipelineStageType>(['ideas', 'principles', 'goals']);
}

function getStageForNodeType(type: string): PipelineStageType | null {
  switch (type) {
    case 'ideaNode':
      return 'ideas';
    case 'principleNode':
      return 'principles';
    case 'goalNode':
      return 'goals';
    case 'actionNode':
      return 'actions';
    case 'orchestrationNode':
      return 'orchestration';
    default:
      return null;
  }
}

function buildIdeaClarifyingQuestions(nodes: Node[]): string[] {
  const prompts: string[] = [];

  for (const node of nodes) {
    const data = (node.data as Record<string, unknown> | undefined) ?? {};
    const label = (data.label as string) || node.id;
    const ideaType = String(data.ideaType ?? data.idea_type ?? '');
    const description = String(data.fullContent ?? data.full_content ?? '').trim();

    if (ideaType === 'question' || label.includes('?')) {
      prompts.push(`Answer the open question "${label}" before approval.`);
      continue;
    }
    if (ideaType === 'constraint') {
      prompts.push(`Confirm "${label}" remains a hard constraint in goals.`);
      continue;
    }
    if (ideaType === 'assumption') {
      prompts.push(`Validate the assumption "${label}" before promoting it.`);
      continue;
    }
    if (!description || description === label) {
      prompts.push(`Define the success condition for "${label}".`);
    }
  }

  return Array.from(new Set(prompts)).slice(0, 3);
}

const LIVE_ORCHESTRATION_COUNT_KEYS = [
  'pending',
  'in_progress',
  'succeeded',
  'failed',
  'partial',
  'awaiting_human',
] as const;

type LiveOrchestrationCountKey = (typeof LIVE_ORCHESTRATION_COUNT_KEYS)[number];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function humanizeLabel(value: string | null | undefined): string {
  if (!value) return 'unknown';
  return value.replace(/_/g, ' ');
}

function createEmptyLiveCounts(): Record<LiveOrchestrationCountKey, number> {
  return { pending: 0, in_progress: 0, succeeded: 0, failed: 0, partial: 0, awaiting_human: 0 };
}

function normalizeLiveCountKey(status: unknown): LiveOrchestrationCountKey {
  const normalized = String(status || 'pending').toLowerCase();
  if (normalized === 'running') return 'in_progress';
  if (normalized === 'completed') return 'succeeded';
  if (LIVE_ORCHESTRATION_COUNT_KEYS.includes(normalized as LiveOrchestrationCountKey)) {
    return normalized as LiveOrchestrationCountKey;
  }
  return 'pending';
}

function deriveFallbackLiveState(
  initialData: PipelineResultResponse | undefined,
  orchestrationNodes: Node[],
): UnifiedPipelineLiveState | null {
  const hasInitialData = Boolean(initialData);
  const hasOrchestrationNodes = orchestrationNodes.length > 0;
  if (!hasInitialData && !hasOrchestrationNodes) {
    return null;
  }

  const counts = createEmptyLiveCounts();
  let humanGates = 0;
  let mergeNodes = 0;
  const activeNodes = orchestrationNodes.slice(0, 5).map((node) => {
    const data = (node.data as Record<string, unknown> | undefined) ?? {};
    const orchType = String(data.orchType ?? data.orch_type ?? 'agent_task');
    const executionStatus = data.executionStatus ?? data.execution_status;
    const status = executionStatus ?? data.status ?? 'pending';
    counts[normalizeLiveCountKey(status)] += 1;
    if (orchType === 'human_gate' || orchType === 'verification') {
      humanGates += 1;
    }
    if (orchType === 'merge') {
      mergeNodes += 1;
    }
    return {
      node_id: node.id,
      label: String(data.label ?? node.id),
      orch_type: orchType,
      status: String(data.status ?? 'pending'),
      execution_status: executionStatus ? String(executionStatus) : null,
      assigned_agent: data.assignedAgent
        ? String(data.assignedAgent)
        : data.assigned_agent
          ? String(data.assigned_agent)
          : null,
    };
  });

  const transitions = initialData?.transitions ?? [];
  const transitionCounts = { pending: 0, approved: 0, rejected: 0, revised: 0 };
  const pendingReviews = transitions
    .filter((transition) => transition.status === 'pending')
    .map((transition) => ({
      id: transition.id,
      from_stage: transition.from_stage,
      to_stage: transition.to_stage,
      confidence: transition.confidence,
    }));

  for (const transition of transitions) {
    const status = transition.status || 'pending';
    if (status in transitionCounts) {
      transitionCounts[status as keyof typeof transitionCounts] += 1;
    }
  }

  const agentItems = Array.isArray(initialData?.agents) ? initialData.agents : [];
  const reviewerAgents = agentItems.filter(
    (agent) => isRecord(agent) && String(agent.role ?? '').toLowerCase() === 'reviewer',
  ).length;
  const pendingAgents = agentItems.filter(
    (agent) =>
      isRecord(agent) &&
      ['pending', 'awaiting_review', 'awaiting_human'].includes(
        String(agent.status ?? '').toLowerCase(),
      ),
  ).length;

  const repairSource = isRecord(initialData?.repair)
    ? initialData.repair
    : isRecord(initialData?.repairs)
      ? initialData.repairs
      : {};
  const repairItems = Array.isArray(repairSource.items) ? repairSource.items.filter(isRecord) : [];

  const mergeGateSource = isRecord(initialData?.merge_gate) ? initialData.merge_gate : {};
  const execution = isRecord(initialData?.execution) ? initialData.execution : {};
  const blockedReasons = Array.isArray(mergeGateSource.blocked_reasons)
    ? mergeGateSource.blocked_reasons.map((reason) => String(reason).trim()).filter(Boolean)
    : [];
  const expectedChecks = Array.isArray(mergeGateSource.expected_checks)
    ? mergeGateSource.expected_checks.map((check) => String(check).trim()).filter(Boolean)
    : [];

  return {
    orchestration: {
      status: String(
        execution.status ??
          initialData?.stage_status?.orchestration ??
          (counts.in_progress > 0 ? 'in_progress' : 'pending'),
      ),
      runtime: execution.runtime ? String(execution.runtime) : null,
      execution_id: execution.execution_id ? String(execution.execution_id) : null,
      correlation_id: execution.correlation_id ? String(execution.correlation_id) : null,
      tasks_total: typeof execution.tasks_total === 'number' ? execution.tasks_total : null,
      agent_tasks: typeof execution.agent_tasks === 'number' ? execution.agent_tasks : null,
      total_orchestration_nodes:
        typeof execution.total_orchestration_nodes === 'number'
          ? execution.total_orchestration_nodes
          : orchestrationNodes.length,
      counts,
      active_nodes: activeNodes,
    },
    review: {
      transition_counts: transitionCounts,
      pending_reviews: pendingReviews,
      reviewer_agents: reviewerAgents,
      pending_agents: pendingAgents,
      human_gates: humanGates,
    },
    repair: {
      status: String(
        repairSource.status ??
          repairSource.state ??
          (repairItems.length > 0 ? 'in_progress' : 'idle'),
      ),
      attempts:
        typeof repairSource.attempts === 'number'
          ? repairSource.attempts
          : typeof repairSource.repair_attempts === 'number'
            ? repairSource.repair_attempts
            : 0,
      active_items: repairItems,
    },
    merge_gate: {
      enabled: Boolean(mergeGateSource.enabled ?? (blockedReasons.length > 0 || mergeNodes > 0)),
      checks_passed: Boolean(mergeGateSource.checks_passed),
      merge_eligible: Boolean(mergeGateSource.merge_eligible),
      human_approval_required: Boolean(mergeGateSource.human_approval_required),
      blocked_reasons: blockedReasons,
      expected_checks: expectedChecks,
      merge_nodes: mergeNodes,
    },
  };
}

function normalizeLiveState(
  initialData: PipelineResultResponse | undefined,
  orchestrationNodes: Node[],
): UnifiedPipelineLiveState | null {
  const provided = initialData?.live_state;
  if (!provided) {
    return deriveFallbackLiveState(initialData, orchestrationNodes);
  }

  return {
    orchestration: {
      status: provided.orchestration?.status ?? 'pending',
      runtime: provided.orchestration?.runtime ?? null,
      execution_id: provided.orchestration?.execution_id ?? null,
      correlation_id: provided.orchestration?.correlation_id ?? null,
      tasks_total: provided.orchestration?.tasks_total ?? null,
      agent_tasks: provided.orchestration?.agent_tasks ?? null,
      total_orchestration_nodes:
        provided.orchestration?.total_orchestration_nodes ?? orchestrationNodes.length,
      counts: { ...createEmptyLiveCounts(), ...(provided.orchestration?.counts ?? {}) },
      active_nodes: provided.orchestration?.active_nodes ?? [],
    },
    review: {
      transition_counts: {
        pending: 0,
        approved: 0,
        rejected: 0,
        revised: 0,
        ...(provided.review?.transition_counts ?? {}),
      },
      pending_reviews: provided.review?.pending_reviews ?? [],
      reviewer_agents: provided.review?.reviewer_agents ?? 0,
      pending_agents: provided.review?.pending_agents ?? 0,
      human_gates: provided.review?.human_gates ?? 0,
    },
    repair: {
      status: provided.repair?.status ?? 'idle',
      attempts: provided.repair?.attempts ?? 0,
      active_items: provided.repair?.active_items ?? [],
    },
    merge_gate: {
      enabled: Boolean(provided.merge_gate?.enabled),
      checks_passed: Boolean(provided.merge_gate?.checks_passed),
      merge_eligible: Boolean(provided.merge_gate?.merge_eligible),
      human_approval_required: Boolean(provided.merge_gate?.human_approval_required),
      blocked_reasons: provided.merge_gate?.blocked_reasons ?? [],
      expected_checks: provided.merge_gate?.expected_checks ?? [],
      merge_nodes: provided.merge_gate?.merge_nodes ?? 0,
    },
  };
}

// =============================================================================
// Props
// =============================================================================

export interface UnifiedPipelineCanvasProps {
  pipelineId?: string;
  initialData?: PipelineResultResponse;
  readOnly?: boolean;
}

// =============================================================================
// Stage Filter Sidebar
// =============================================================================

interface StageFilterProps {
  enabledStages: Set<PipelineStageType>;
  onToggle: (stage: PipelineStageType) => void;
  onFocus: (stage: PipelineStageType) => void;
  nodeCounts: Record<PipelineStageType, number>;
}

function StageFilterSidebar({ enabledStages, onToggle, onFocus, nodeCounts }: StageFilterProps) {
  return (
    <div
      className="w-48 flex-shrink-0 bg-surface border-r border-border h-full overflow-y-auto p-4"
      data-testid="stage-filter-sidebar"
    >
      <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase tracking-wide mb-4">
        Stages
      </h3>
      <div className="space-y-2">
        {ALL_STAGES.map((stage) => {
          const config = PIPELINE_STAGE_CONFIG[stage];
          const color = STAGE_COLORS[stage];
          const enabled = enabledStages.has(stage);
          const count = nodeCounts[stage];

          return (
            <div key={stage} className="space-y-1">
              <button
                onClick={() => onToggle(stage)}
                className={`
                  w-full flex items-center justify-between px-3 py-2 rounded font-theme-data text-xs
                  transition-all duration-200 border
                  ${
                    enabled
                      ? 'border-current opacity-100'
                      : 'border-border opacity-40 hover:opacity-60'
                  }
                `}
                style={{ color, borderColor: enabled ? color : undefined }}
                data-testid={`stage-toggle-${stage}`}
              >
                <span className="font-bold uppercase">{config.label}</span>
                <span
                  className="px-1.5 py-0.5 rounded-full text-xs font-theme-data"
                  style={{ backgroundColor: enabled ? `${color}33` : 'transparent' }}
                  data-testid={`stage-count-${stage}`}
                >
                  {count}
                </span>
              </button>
              <button
                onClick={() => onFocus(stage)}
                className="w-full text-center text-xs font-theme-data text-text-muted hover:text-text transition-colors"
                data-testid={`stage-focus-${stage}`}
              >
                Focus
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// =============================================================================
// AI Transition Toolbar
// =============================================================================

interface AITransitionToolbarProps {
  selectedStages: Set<PipelineStageType>;
  loading: boolean;
  onGenerateGoals: () => void;
  onGenerateTasks: () => void;
  onGenerateWorkflow: () => void;
}

function AITransitionToolbar({
  selectedStages,
  loading,
  onGenerateGoals,
  onGenerateTasks,
  onGenerateWorkflow,
}: AITransitionToolbarProps) {
  const hasIdeas = selectedStages.has('ideas');
  const hasGoals = selectedStages.has('goals');
  const hasActions = selectedStages.has('actions');

  return (
    <div className="flex items-center gap-2" data-testid="ai-transition-toolbar">
      <button
        onClick={onGenerateGoals}
        disabled={!hasIdeas || loading}
        className="px-3 py-1.5 bg-emerald-600 text-white font-theme-data text-xs font-bold rounded
                   hover:bg-emerald-500 transition-colors
                   disabled:opacity-40 disabled:cursor-not-allowed"
        data-testid="btn-generate-goals"
      >
        {loading ? 'Generating...' : 'Generate Goals'}
      </button>
      <button
        onClick={onGenerateTasks}
        disabled={!hasGoals || loading}
        className="px-3 py-1.5 bg-amber-600 text-white font-theme-data text-xs font-bold rounded
                   hover:bg-amber-500 transition-colors
                   disabled:opacity-40 disabled:cursor-not-allowed"
        data-testid="btn-generate-tasks"
      >
        {loading ? 'Generating...' : 'Generate Tasks'}
      </button>
      <button
        onClick={onGenerateWorkflow}
        disabled={!hasActions || loading}
        className="px-3 py-1.5 bg-purple-600 text-white font-theme-data text-xs font-bold rounded
                   hover:bg-purple-500 transition-colors
                   disabled:opacity-40 disabled:cursor-not-allowed"
        data-testid="btn-generate-workflow"
      >
        {loading ? 'Generating...' : 'Generate Workflow'}
      </button>
    </div>
  );
}

// =============================================================================
// Provenance Sidebar
// =============================================================================

interface ProvenanceSidebarProps {
  nodeId: string;
  nodeLabel: string;
  provenanceChain: Array<{ stage: string; nodeId: string; label: string; hash: string }>;
  onClose: () => void;
}

function ProvenanceSidebar({
  nodeId,
  nodeLabel,
  provenanceChain,
  onClose,
}: ProvenanceSidebarProps) {
  return (
    <div
      className="w-72 flex-shrink-0 bg-surface border-l border-border h-full overflow-y-auto p-4"
      data-testid="provenance-sidebar"
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data font-bold text-text uppercase">Provenance</h3>
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text text-lg leading-none"
          data-testid="provenance-close"
        >
          &times;
        </button>
      </div>

      <div className="mb-4">
        <p className="text-sm text-text truncate">{nodeLabel}</p>
        <p className="text-xs text-text-muted font-theme-data">{nodeId}</p>
      </div>

      {provenanceChain.length > 0 ? (
        <div className="space-y-2">
          <h4 className="text-xs font-theme-data font-bold text-text-muted uppercase mb-2">
            Derivation Chain
          </h4>
          {provenanceChain.map((entry, i) => {
            const stageColor = STAGE_COLORS[entry.stage as PipelineStageType] || '#6b7280';
            return (
              <div
                key={i}
                className="p-2 bg-bg rounded border border-border"
                data-testid="provenance-entry"
              >
                <div className="flex items-center gap-2 mb-1">
                  <span
                    className="w-2 h-2 rounded-full inline-block"
                    style={{ backgroundColor: stageColor }}
                  />
                  <span className="text-xs font-theme-data uppercase" style={{ color: stageColor }}>
                    {entry.stage}
                  </span>
                </div>
                <p className="text-xs text-text truncate mb-1">{entry.label}</p>
                <p className="text-xs text-text-muted font-theme-data">
                  SHA-256: {entry.hash.slice(0, 12)}...
                </p>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="text-sm text-text-muted">No provenance chain for this node.</p>
      )}
    </div>
  );
}

interface UnifiedLiveStatePanelProps {
  liveState: UnifiedPipelineLiveState;
}

function UnifiedLiveStatePanel({ liveState }: UnifiedLiveStatePanelProps) {
  const orchestration = liveState.orchestration;
  const review = liveState.review;
  const repair = liveState.repair;
  const mergeGate = liveState.merge_gate;

  const pendingReviews = review.transition_counts.pending ?? review.pending_reviews.length;
  const runningCount = orchestration.counts.in_progress ?? 0;
  const failedCount = orchestration.counts.failed ?? 0;
  const blockedReason = mergeGate.blocked_reasons[0];
  const repairHeadline = repair.active_items[0];
  const repairLabel = isRecord(repairHeadline)
    ? String(
        repairHeadline.title ??
          repairHeadline.problem_statement ??
          repairHeadline.blocker_kind ??
          'Repair item queued',
      )
    : 'Repair item queued';

  return (
    <div
      className="w-80 rounded-lg border border-border bg-surface/95 p-3 backdrop-blur"
      data-testid="unified-live-state-panel"
    >
      <div className="flex items-start justify-between gap-2 mb-3">
        <div>
          <p className="text-[11px] font-theme-data uppercase tracking-wide text-text-muted">
            Unified Canvas Live State
          </p>
          <h3 className="text-sm font-theme-data font-bold text-text">
            Orchestration, review, and repair
          </h3>
        </div>
        <span className="rounded-full border border-border px-2 py-1 text-[11px] font-theme-data text-text">
          {humanizeLabel(orchestration.status)}
        </span>
      </div>

      <div className="space-y-2">
        <section
          className="rounded border border-border bg-bg/60 p-2"
          data-testid="live-state-orchestration"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-theme-data uppercase tracking-wide text-text-muted">
              Orchestration
            </span>
            <span className="text-xs font-theme-data text-text">
              {humanizeLabel(orchestration.status)}
            </span>
          </div>
          <p className="mt-1 text-xs text-text">
            {orchestration.agent_tasks ?? 0} agent tasks, {runningCount} running, {failedCount}{' '}
            failed
          </p>
          {orchestration.active_nodes.length > 0 && (
            <div className="mt-2 space-y-1">
              {orchestration.active_nodes.slice(0, 3).map((node) => (
                <div
                  key={node.node_id}
                  className="flex items-center justify-between gap-2 rounded border border-border/60 px-2 py-1"
                  data-testid={`live-state-node-${node.node_id}`}
                >
                  <div className="min-w-0">
                    <p className="truncate text-xs text-text">{node.label}</p>
                    <p className="text-[11px] font-theme-data text-text-muted">
                      {humanizeLabel(node.orch_type)}
                    </p>
                  </div>
                  <span className="text-[11px] font-theme-data text-text-muted">
                    {humanizeLabel(node.execution_status ?? node.status)}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section
          className="rounded border border-border bg-bg/60 p-2"
          data-testid="live-state-review"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-theme-data uppercase tracking-wide text-text-muted">
              Review
            </span>
            <span className="text-xs font-theme-data text-text">{pendingReviews} pending</span>
          </div>
          <p className="mt-1 text-xs text-text">
            {review.reviewer_agents} reviewers, {review.pending_agents} waiting agents,{' '}
            {review.human_gates} human gates
          </p>
          {review.pending_reviews[0] && isRecord(review.pending_reviews[0]) && (
            <p className="mt-1 text-[11px] font-theme-data text-text-muted">
              Next: {humanizeLabel(String(review.pending_reviews[0].from_stage ?? 'stage'))} {'->'}{' '}
              {humanizeLabel(String(review.pending_reviews[0].to_stage ?? 'stage'))}
            </p>
          )}
        </section>

        <section
          className="rounded border border-border bg-bg/60 p-2"
          data-testid="live-state-repair"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-theme-data uppercase tracking-wide text-text-muted">
              Repair
            </span>
            <span className="text-xs font-theme-data text-text">
              {humanizeLabel(repair.status)}
            </span>
          </div>
          <p className="mt-1 text-xs text-text">
            {repair.attempts} attempt{repair.attempts === 1 ? '' : 's'}
          </p>
          {repair.active_items.length > 0 && (
            <p className="mt-1 text-[11px] font-theme-data text-text-muted">
              Active: {repairLabel}
            </p>
          )}
        </section>

        <section
          className="rounded border border-border bg-bg/60 p-2"
          data-testid="live-state-merge-gate"
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-theme-data uppercase tracking-wide text-text-muted">
              Merge Gate
            </span>
            <span className="text-xs font-theme-data text-text">
              {mergeGate.merge_eligible
                ? 'eligible'
                : mergeGate.checks_passed
                  ? 'ready'
                  : 'blocked'}
            </span>
          </div>
          <p className="mt-1 text-xs text-text">
            {mergeGate.expected_checks.length} expected checks, {mergeGate.merge_nodes} merge nodes
          </p>
          {blockedReason && (
            <p className="mt-1 text-[11px] font-theme-data text-text-muted">{blockedReason}</p>
          )}
        </section>
      </div>
    </div>
  );
}

// =============================================================================
// Inner component (inside ReactFlowProvider)
// =============================================================================

function UnifiedPipelineCanvasInner({
  pipelineId,
  initialData,
  readOnly = false,
}: UnifiedPipelineCanvasProps) {
  const { stageNodes, stageEdges, loading, aiGenerate, approveTransition, rejectTransition } =
    usePipelineCanvas(pipelineId ?? null, initialData);

  const { fitView } = useReactFlow();

  // -- Zoom tracking --------------------------------------------------------
  const [zoomLevel, setZoomLevel] = useState(1.0);

  const onViewportChange = useCallback((viewport: Viewport) => {
    setZoomLevel(viewport.zoom);
  }, []);

  // -- Stage filter state ---------------------------------------------------
  const [stageFilterOverrides, setStageFilterOverrides] = useState<Set<PipelineStageType>>(
    new Set(ALL_STAGES),
  );

  const toggleStage = useCallback((stage: PipelineStageType) => {
    setStageFilterOverrides((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) {
        next.delete(stage);
      } else {
        next.add(stage);
      }
      return next;
    });
  }, []);

  const focusStage = useCallback(
    (stage: PipelineStageType) => {
      // Ensure the stage is enabled
      setStageFilterOverrides((prev) => {
        const next = new Set(prev);
        next.add(stage);
        return next;
      });
      // Fit view to nodes of that stage after a tick
      setTimeout(() => {
        const offsetX = STAGE_OFFSET_X[stage];
        fitView({
          padding: 0.3,
          nodes: stageNodes[stage].map((n) => ({
            id: n.id,
            position: { x: n.position.x + offsetX, y: n.position.y },
            measured: { width: 250, height: 120 },
          })),
        });
      }, 50);
    },
    [fitView, stageNodes],
  );

  // -- Node selection & provenance ------------------------------------------
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [showProvenance, setShowProvenance] = useState(false);

  // -- Selected nodes per stage (for AI transition buttons) -----------------
  const [selectedNodeIds, setSelectedNodeIds] = useState<Set<string>>(new Set());
  const selectedNodeStages = useMemo(() => {
    const stages = new Set<PipelineStageType>();
    for (const stage of ALL_STAGES) {
      for (const n of stageNodes[stage]) {
        if (selectedNodeIds.has(n.id)) {
          stages.add(stage);
        }
      }
    }
    return stages;
  }, [selectedNodeIds, stageNodes]);

  const transitionNodeLookup = useMemo(() => {
    const lookup: Record<string, { label: string; stage: PipelineStageType }> = {};
    for (const stage of ALL_STAGES) {
      for (const node of stageNodes[stage]) {
        const data = node.data as Record<string, unknown>;
        lookup[node.id] = { label: (data.label as string) || node.id, stage };
      }
    }
    return lookup;
  }, [stageNodes]);

  // -- Compute visible stages: intersection of semantic zoom + filter -------
  const semanticVisible = useMemo(() => getVisibleStages(zoomLevel), [zoomLevel]);

  const visibleStages = useMemo(() => {
    const result = new Set<PipelineStageType>();
    for (const stage of ALL_STAGES) {
      if (semanticVisible.has(stage) && stageFilterOverrides.has(stage)) {
        result.add(stage);
      }
    }
    return result;
  }, [semanticVisible, stageFilterOverrides]);

  // -- Assemble nodes/edges from all visible stages -------------------------
  const { displayNodes, displayEdges } = useMemo(() => {
    const allNodes: Node[] = [];
    const allEdges: Edge[] = [];
    for (const stage of ALL_STAGES) {
      if (!visibleStages.has(stage)) continue;
      const offsetX = STAGE_OFFSET_X[stage];
      for (const n of stageNodes[stage]) {
        allNodes.push({ ...n, position: { x: n.position.x + offsetX, y: n.position.y } });
      }
      for (const e of stageEdges[stage]) {
        const edgeType = (e.data as Record<string, unknown>)?.edgeType as string | undefined;
        const styleOverride = edgeType ? EDGE_STYLES[edgeType] : undefined;
        allEdges.push({
          ...e,
          style: {
            stroke: STAGE_COLORS[stage],
            strokeWidth: 2,
            ...styleOverride,
            ...(e.style || {}),
          },
          animated: styleOverride?.animated ?? e.animated ?? true,
        });
      }
    }
    return { displayNodes: allNodes, displayEdges: allEdges };
  }, [visibleStages, stageNodes, stageEdges]);

  // -- Per-stage node counts ------------------------------------------------
  const nodeCounts = useMemo(() => {
    const counts: Record<PipelineStageType, number> = {
      ideas: 0,
      principles: 0,
      goals: 0,
      actions: 0,
      orchestration: 0,
    };
    for (const stage of ALL_STAGES) {
      counts[stage] = stageNodes[stage].length;
    }
    return counts;
  }, [stageNodes]);

  // -- Provenance chain for selected node -----------------------------------
  const provenanceChain = useMemo(() => {
    if (!selectedNodeId || !initialData) return [];

    const chain: Array<{ stage: string; nodeId: string; label: string; hash: string }> = [];
    const provLinks = (initialData.goals?.provenance ?? []) as Array<{
      source_node_id: string;
      target_node_id: string;
      source_stage: string;
      target_stage: string;
      content_hash: string;
    }>;

    // Walk the chain backward from the selected node
    let currentId = selectedNodeId;
    const visited = new Set<string>();
    while (currentId && !visited.has(currentId)) {
      visited.add(currentId);
      const link = provLinks.find((l) => l.target_node_id === currentId);
      if (!link) break;

      // Find the source node label
      const sourceStage = link.source_stage as PipelineStageType;
      const sourceNode = stageNodes[sourceStage]?.find((n) => n.id === link.source_node_id);
      chain.unshift({
        stage: link.source_stage,
        nodeId: link.source_node_id,
        label:
          ((sourceNode?.data as Record<string, unknown>)?.label as string) || link.source_node_id,
        hash: link.content_hash || '',
      });
      currentId = link.source_node_id;
    }

    return chain;
  }, [selectedNodeId, initialData, stageNodes]);

  const selectedNodeLabel = useMemo(() => {
    if (!selectedNodeId) return '';
    const node = displayNodes.find((n) => n.id === selectedNodeId);
    return ((node?.data as Record<string, unknown>)?.label as string) || selectedNodeId;
  }, [selectedNodeId, displayNodes]);

  const selectedIdeaNodes = useMemo(
    () => stageNodes.ideas.filter((node) => selectedNodeIds.has(node.id)),
    [selectedNodeIds, stageNodes],
  );

  const ideasToGoalsTransition = useMemo<StageTransition | null>(
    () =>
      initialData?.transitions?.find(
        (transition) => transition.from_stage === 'ideas' && transition.to_stage === 'goals',
      ) ?? null,
    [initialData],
  );

  const ideasToGoalsProvenance = useMemo(() => {
    const baseLinks = (
      ideasToGoalsTransition?.provenance?.length
        ? ideasToGoalsTransition.provenance
        : (initialData?.provenance ?? [])
    ) as ProvenanceLink[];

    const stageLinks = baseLinks.filter(
      (link) => link.source_stage === 'ideas' && link.target_stage === 'goals',
    );

    if (selectedIdeaNodes.length === 0) {
      return stageLinks;
    }

    const selectedIdeaIds = new Set(selectedIdeaNodes.map((node) => node.id));
    return stageLinks.filter((link) => selectedIdeaIds.has(link.source_node_id));
  }, [ideasToGoalsTransition, initialData, selectedIdeaNodes]);

  const focusedGoalLabels = useMemo(
    () =>
      Array.from(
        new Set(
          ideasToGoalsProvenance.map(
            (link) => transitionNodeLookup[link.target_node_id]?.label ?? link.target_node_id,
          ),
        ),
      ).slice(0, 3),
    [ideasToGoalsProvenance, transitionNodeLookup],
  );

  const ideaClarifyingQuestions = useMemo(
    () => buildIdeaClarifyingQuestions(selectedIdeaNodes),
    [selectedIdeaNodes],
  );

  const ideasToGoalsFocusLabel = useMemo(() => {
    if (selectedIdeaNodes.length === 0) return null;
    return `${selectedIdeaNodes.length} idea${selectedIdeaNodes.length === 1 ? '' : 's'} selected for promotion`;
  }, [selectedIdeaNodes]);

  const liveState = useMemo(
    () => normalizeLiveState(initialData, stageNodes.orchestration),
    [initialData, stageNodes.orchestration],
  );

  const showIdeasToGoalsPanel = !readOnly && selectedIdeaNodes.length > 0;

  // -- Node click -----------------------------------------------------------
  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    setSelectedNodeId(node.id);
    setShowProvenance(true);

    // Track selected nodes by stage for AI transition buttons
    const stage = getStageForNodeType(node.type || '');
    if (stage) {
      setSelectedNodeIds((prev) => {
        const next = new Set(prev);
        next.add(node.id);
        return next;
      });
    }
  }, []);

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setShowProvenance(false);
    setSelectedNodeIds(new Set());
  }, []);

  // -- AI transition handlers -----------------------------------------------
  const handleGenerateGoals = useCallback(() => {
    aiGenerate('goals');
  }, [aiGenerate]);

  const handleGenerateTasks = useCallback(() => {
    aiGenerate('actions');
  }, [aiGenerate]);

  const handleGenerateWorkflow = useCallback(() => {
    aiGenerate('orchestration');
  }, [aiGenerate]);

  // -- MiniMap color --------------------------------------------------------
  const miniMapNodeColor = useCallback((node: { type?: string }) => {
    switch (node.type) {
      case 'ideaNode':
        return STAGE_COLORS.ideas;
      case 'principleNode':
        return STAGE_COLORS.principles;
      case 'goalNode':
        return STAGE_COLORS.goals;
      case 'actionNode':
        return STAGE_COLORS.actions;
      case 'orchestrationNode':
        return STAGE_COLORS.orchestration;
      default:
        return '#6b7280';
    }
  }, []);

  // -- Fit view on mount ----------------------------------------------------
  useEffect(() => {
    setTimeout(() => fitView({ padding: 0.2 }), 50);
  }, [fitView]);

  return (
    <div className="flex h-full bg-bg" data-testid="unified-pipeline-canvas">
      {/* Left: Stage Filter Sidebar */}
      <StageFilterSidebar
        enabledStages={stageFilterOverrides}
        onToggle={toggleStage}
        onFocus={focusStage}
        nodeCounts={nodeCounts}
      />

      {/* Center: Canvas */}
      <div className="flex flex-col flex-1">
        <div className="flex-1">
          <ReactFlow
            nodes={displayNodes}
            edges={displayEdges}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onViewportChange={onViewportChange}
            nodeTypes={nodeTypes}
            fitView
            snapToGrid
            snapGrid={[16, 16]}
            defaultEdgeOptions={{ animated: true, style: { stroke: '#6b7280', strokeWidth: 2 } }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#333" />
            <Controls
              className="bg-surface border border-border rounded"
              showInteractive={!readOnly}
            />
            <MiniMap
              className="bg-surface border border-border rounded"
              nodeColor={miniMapNodeColor}
            />

            {/* AI Transition Toolbar */}
            {!readOnly && (
              <Panel position="top-center">
                <AITransitionToolbar
                  selectedStages={selectedNodeStages}
                  loading={loading}
                  onGenerateGoals={handleGenerateGoals}
                  onGenerateTasks={handleGenerateTasks}
                  onGenerateWorkflow={handleGenerateWorkflow}
                />
              </Panel>
            )}

            {(showIdeasToGoalsPanel || liveState) && (
              <Panel position="bottom-right">
                <div className="w-80 space-y-2">
                  {showIdeasToGoalsPanel && (
                    <>
                      <div
                        className="rounded-lg border border-border bg-surface/95 p-3"
                        data-testid="ideas-to-goals-panel"
                      >
                        <div className="flex items-start justify-between gap-2 mb-2">
                          <div>
                            <p className="text-[11px] font-theme-data uppercase tracking-wide text-text-muted">
                              Ideas {'->'} Goals
                            </p>
                            <h3 className="text-sm font-theme-data font-bold text-text">
                              Promote focused ideas
                            </h3>
                          </div>
                          <button
                            onClick={handleGenerateGoals}
                            className="px-2 py-1 text-[11px] font-theme-data rounded bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50"
                            disabled={loading}
                            data-testid="btn-refresh-goal-draft"
                          >
                            {loading ? 'Generating...' : 'Refresh goal draft'}
                          </button>
                        </div>

                        <div className="flex flex-wrap gap-1.5">
                          {selectedIdeaNodes.slice(0, 3).map((node) => (
                            <span
                              key={node.id}
                              className="px-2 py-1 rounded-full bg-indigo-500/15 text-indigo-200 text-[11px] font-theme-data"
                            >
                              {((node.data as Record<string, unknown>)?.label as string) || node.id}
                            </span>
                          ))}
                        </div>

                        {focusedGoalLabels.length > 0 ? (
                          <div
                            className="mt-3 rounded border border-border bg-bg/60 p-2"
                            data-testid="ideas-to-goals-goal-preview"
                          >
                            <p className="text-[11px] font-theme-data uppercase tracking-wide text-text-muted mb-1">
                              Goal Draft
                            </p>
                            <p className="text-xs text-text">{focusedGoalLabels.join(', ')}</p>
                          </div>
                        ) : (
                          <p className="mt-3 text-xs text-text-muted font-theme-data">
                            Generate or refresh the goal draft to inspect provenance before
                            approval.
                          </p>
                        )}
                      </div>

                      {ideasToGoalsTransition && (
                        <StageTransitionGate
                          transition={ideasToGoalsTransition}
                          pipelineId={pipelineId || ''}
                          provenance={ideasToGoalsProvenance}
                          nodeLookup={transitionNodeLookup}
                          questions={ideaClarifyingQuestions}
                          focusLabel={ideasToGoalsFocusLabel ?? undefined}
                          onApprove={(_, transitionId) => {
                            approveTransition(transitionId);
                          }}
                          onReject={(_, transitionId) => {
                            rejectTransition(transitionId);
                          }}
                        />
                      )}
                    </>
                  )}

                  {liveState && <UnifiedLiveStatePanel liveState={liveState} />}
                </div>
              </Panel>
            )}

            {/* Stats + zoom info panel */}
            <Panel
              position="bottom-left"
              className="bg-surface/90 border border-border rounded p-2"
            >
              <div className="text-xs font-theme-data text-text-muted">
                <span className="text-text">{displayNodes.length}</span> nodes |{' '}
                <span className="text-text">{displayEdges.length}</span> edges |{' '}
                <span className="text-text">zoom: {zoomLevel.toFixed(2)}</span>
                <span className="ml-2 opacity-50" data-testid="zoom-indicator">
                  {zoomLevel > ZOOM_FULL_DETAIL
                    ? 'all stages'
                    : zoomLevel >= ZOOM_PARTIAL
                      ? 'ideas + principles + goals + actions'
                      : 'ideas + principles + goals'}
                </span>
              </div>
            </Panel>

            {/* Pipeline ID + integrity */}
            {pipelineId && (
              <Panel
                position="top-right"
                className="bg-surface/90 border border-border rounded p-2"
              >
                <div className="text-xs font-theme-data text-text-muted">
                  Pipeline: <span className="text-text">{pipelineId}</span>
                  {initialData?.integrity_hash && (
                    <span className="ml-2 text-emerald-400">
                      #{initialData.integrity_hash.slice(0, 8)}
                    </span>
                  )}
                </div>
              </Panel>
            )}

            {/* Stage lane labels */}
            {ALL_STAGES.filter((s) => visibleStages.has(s)).map((stage) => (
              <Panel key={stage} position="top-left" className="pointer-events-none">
                <div
                  className="font-theme-data text-xs font-bold uppercase tracking-wide opacity-30 ml-2 mt-1"
                  style={{
                    color: STAGE_COLORS[stage],
                    transform: `translateX(${STAGE_OFFSET_X[stage]}px)`,
                  }}
                >
                  {PIPELINE_STAGE_CONFIG[stage].label}
                </div>
              </Panel>
            ))}
          </ReactFlow>
        </div>
      </div>

      {/* Right: Provenance Sidebar */}
      {showProvenance && selectedNodeId && (
        <ProvenanceSidebar
          nodeId={selectedNodeId}
          nodeLabel={selectedNodeLabel}
          provenanceChain={provenanceChain}
          onClose={() => {
            setShowProvenance(false);
            setSelectedNodeId(null);
          }}
        />
      )}
    </div>
  );
}

// =============================================================================
// Exported wrapper with ReactFlowProvider
// =============================================================================

export function UnifiedPipelineCanvas(props: UnifiedPipelineCanvasProps) {
  return (
    <ReactFlowProvider>
      <UnifiedPipelineCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

export default UnifiedPipelineCanvas;
