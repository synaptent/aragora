'use client';

/**
 * useMissionControl - State management for the 6-stage Mission Control canvas.
 *
 * Extends the usePipelineCanvas pattern to support 6 stages:
 *   Ideas -> Principles -> Goals -> Actions -> Orchestration -> Execution
 *
 * Manages per-stage node/edge arrays, selection, provenance chain walking,
 * and WebSocket integration for real-time updates.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { Node, Edge } from '@xyflow/react';
import type {
  PipelineStageType,
  PipelineResultResponse,
  ReactFlowData,
  ProvenanceBreadcrumb,
  ProvenanceLink,
  ExecutionStatus,
} from '../components/pipeline-canvas/types';
import { getNodeTypeForStage, PIPELINE_STAGE_CONFIG } from '../components/pipeline-canvas/types';
import {
  usePipelineWebSocket,
  type PipelineStageEvent,
  type PipelineNodeEvent,
  type PipelineNodeStatusEvent,
} from './usePipelineWebSocket';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const API_PREFIX = '/api/v1/canvas/pipeline';

const ALL_STAGES: PipelineStageType[] = [
  'ideas',
  'principles',
  'goals',
  'actions',
  'orchestration',
];

const EXECUTION_STAGE = 'execution';

type MissionStageType = PipelineStageType | typeof EXECUTION_STAGE;

const _ALL_MISSION_STAGES: MissionStageType[] = [...ALL_STAGES, EXECUTION_STAGE];

const EMPTY_STAGE_NODES: Record<PipelineStageType, Node[]> = {
  ideas: [],
  principles: [],
  goals: [],
  actions: [],
  orchestration: [],
};

const EMPTY_STAGE_EDGES: Record<PipelineStageType, Edge[]> = {
  ideas: [],
  principles: [],
  goals: [],
  actions: [],
  orchestration: [],
};

const DEFAULT_STATUS: Record<PipelineStageType, string> = {
  ideas: 'pending',
  principles: 'pending',
  goals: 'pending',
  actions: 'pending',
  orchestration: 'pending',
};

const EXECUTION_STATUS_MAP: Record<string, ExecutionStatus> = {
  pending: 'pending',
  queued: 'pending',
  running: 'in_progress',
  in_progress: 'in_progress',
  active: 'in_progress',
  complete: 'succeeded',
  completed: 'succeeded',
  succeeded: 'succeeded',
  success: 'succeeded',
  failed: 'failed',
  error: 'failed',
  blocked: 'partial',
  awaiting_human: 'partial',
  partial: 'partial',
};

export const STAGE_OFFSET_X: Record<string, number> = {
  ideas: 0,
  principles: 600,
  goals: 1200,
  actions: 1800,
  orchestration: 2400,
  execution: 3000,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function parseStageNodes(
  stage: PipelineStageType,
  data: ReactFlowData | Record<string, unknown> | null,
): Node[] {
  if (!data) return [];

  const rawNodes: Array<Record<string, unknown>> =
    (data as ReactFlowData).nodes ??
    ((data as Record<string, unknown>)[stage] as Array<Record<string, unknown>>) ??
    ((data as Record<string, unknown>).goals as Array<Record<string, unknown>>) ??
    [];

  const nodeType = getNodeTypeForStage(stage);

  return rawNodes.map((n) => ({
    id: (n.id as string) || `${stage}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    type: (n.type as string) || nodeType,
    position: (n.position as { x: number; y: number }) || { x: 0, y: 0 },
    data: {
      ...((n.data as Record<string, unknown>) ?? {}),
      label:
        (n.data as Record<string, unknown>)?.label ??
        (n as Record<string, unknown>).label ??
        (n as Record<string, unknown>).title ??
        '',
      stage,
    },
    style: (n.style as Record<string, string>) ?? {},
  }));
}

function parseStageEdges(
  stage: PipelineStageType,
  data: ReactFlowData | Record<string, unknown> | null,
): Edge[] {
  if (!data) return [];

  const rawEdges: Array<Record<string, unknown>> = (data as ReactFlowData).edges ?? [];
  const stageColor = PIPELINE_STAGE_CONFIG[stage].primary;

  return rawEdges.map((e) => ({
    id: (e.id as string) || `e-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    source: (e.source || e.source_id) as string,
    target: (e.target || e.target_id) as string,
    type: (e.type as string) || 'default',
    label: e.label as string | undefined,
    animated: e.animated !== undefined ? !!e.animated : true,
    style: { stroke: stageColor, ...((e.style as Record<string, string>) ?? {}) },
  }));
}

function normalizeExecutionStatus(status?: string | null): ExecutionStatus {
  if (!status) return 'pending';
  return EXECUTION_STATUS_MAP[status] ?? 'pending';
}

function findNodeInStages(
  stageNodes: Record<PipelineStageType, Node[]>,
  nodeId: string,
): { stage: PipelineStageType; node: Node } | null {
  for (const stage of ALL_STAGES) {
    const node = stageNodes[stage].find((candidate) => candidate.id === nodeId);
    if (node) {
      return { stage, node };
    }
  }
  return null;
}

export interface MissionControlExecutionState {
  nodeId: string;
  label: string;
  stage: PipelineStageType;
  status: ExecutionStatus;
  rawStatus: string;
  agent?: string;
  elapsedMs?: number;
  outputPreview?: string;
  navigable: boolean;
  isSelectedNode?: boolean;
}

// ---------------------------------------------------------------------------
// Return type
// ---------------------------------------------------------------------------

export interface UseMissionControlReturn {
  // All nodes/edges (positioned with stage offsets)
  nodes: Node[];
  edges: Edge[];

  // Stage state
  stageStatus: Record<PipelineStageType, string>;
  stageNodeCounts: Record<PipelineStageType, number>;

  // Pipeline
  pipelineId: string | null;
  isExecuting: boolean;

  // Actions
  loadPipeline: (id: string) => Promise<void>;
  startBrainDump: (text: string, automationLevel: string) => Promise<string | null>;
  advanceStage: (targetStage: PipelineStageType) => Promise<void>;

  // Selection
  selectedNodeId: string | null;
  selectedNodeData: Record<string, unknown> | null;
  selectedNodeStage: PipelineStageType | null;
  onNodeSelect: (nodeId: string | null) => void;

  // Provenance
  provenance: ProvenanceLink[];
  provenanceChain: ProvenanceBreadcrumb[];
  downstreamExecution: MissionControlExecutionState[];

  // WebSocket
  wsStatus: string;
  completedStages: string[];
  streamedNodes: PipelineNodeEvent[];

  // Loading
  loading: boolean;
  error: string | null;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useMissionControl(initialPipelineId?: string | null): UseMissionControlReturn {
  const [pipelineId, setPipelineId] = useState<string | null>(initialPipelineId ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isExecuting, setIsExecuting] = useState(false);

  // Per-stage caches
  const stageNodesRef = useRef<Record<PipelineStageType, Node[]>>({ ...EMPTY_STAGE_NODES });
  const stageEdgesRef = useRef<Record<PipelineStageType, Edge[]>>({ ...EMPTY_STAGE_EDGES });
  const [stageNodes, setStageNodes] = useState<Record<PipelineStageType, Node[]>>({
    ...EMPTY_STAGE_NODES,
  });
  const [stageEdges, setStageEdges] = useState<Record<PipelineStageType, Edge[]>>({
    ...EMPTY_STAGE_EDGES,
  });
  const [stageStatus, setStageStatus] = useState<Record<PipelineStageType, string>>({
    ...DEFAULT_STATUS,
  });
  const [provenance, setProvenance] = useState<ProvenanceLink[]>([]);

  // Selection
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const syncCacheToState = useCallback(() => {
    setStageNodes({ ...stageNodesRef.current });
    setStageEdges({ ...stageEdgesRef.current });
  }, []);

  // -- Populate from API result -------------------------------------------
  const populateFromResult = useCallback(
    (result: PipelineResultResponse) => {
      if (result.stage_status) {
        setStageStatus(result.stage_status);
      }

      for (const stage of ALL_STAGES) {
        const stageData = (result as unknown as Record<string, unknown>)[stage] as
          ReactFlowData | Record<string, unknown> | null;
        stageNodesRef.current[stage] = parseStageNodes(stage, stageData);
        stageEdgesRef.current[stage] = parseStageEdges(stage, stageData);
      }

      setProvenance((result.provenance ?? []) as ProvenanceLink[]);

      syncCacheToState();
    },
    [syncCacheToState],
  );

  // -- Load pipeline from API ---------------------------------------------
  const loadPipeline = useCallback(
    async (id: string) => {
      setLoading(true);
      setError(null);
      setPipelineId(id);
      try {
        const res = await fetch(`${API_PREFIX}/${id}`);
        if (!res.ok) {
          setError(`Failed to load pipeline: ${res.status}`);
          return;
        }
        const data: PipelineResultResponse = await res.json();
        populateFromResult(data);
      } catch {
        setError('Failed to load pipeline');
      } finally {
        setLoading(false);
      }
    },
    [populateFromResult],
  );

  // -- Start brain dump ---------------------------------------------------
  const startBrainDump = useCallback(
    async (text: string, automationLevel: string): Promise<string | null> => {
      setLoading(true);
      setError(null);
      try {
        if (automationLevel === 'full') {
          setIsExecuting(true);
        }
        const res = await fetch(`${API_PREFIX}/from-ideas`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            ideas: text
              .split('\n')
              .map((s) => s.trim())
              .filter(Boolean),
            auto_advance: automationLevel === 'full',
          }),
        });

        if (!res.ok) {
          if (automationLevel === 'full') {
            setIsExecuting(false);
          }
          setError(`Failed to start brain dump: ${res.status}`);
          return null;
        }

        const data = await res.json();
        const newId = data.pipeline_id as string;
        setPipelineId(newId);

        if (data.result) {
          populateFromResult(data.result as PipelineResultResponse);
        }

        return newId;
      } catch {
        if (automationLevel === 'full') {
          setIsExecuting(false);
        }
        setError('Failed to start brain dump');
        return null;
      } finally {
        setLoading(false);
      }
    },
    [populateFromResult],
  );

  // -- Advance stage ------------------------------------------------------
  const advanceStage = useCallback(
    async (targetStage: PipelineStageType) => {
      if (!pipelineId) return;
      setLoading(true);
      setError(null);
      setIsExecuting(true);
      try {
        const res = await fetch(`${API_PREFIX}/advance`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pipeline_id: pipelineId, target_stage: targetStage }),
        });

        if (!res.ok) {
          setIsExecuting(false);
          setError(`Failed to advance to ${targetStage}: ${res.status}`);
          return;
        }

        const data = await res.json();
        if (data.result) {
          populateFromResult(data.result as PipelineResultResponse);
        }
      } catch {
        setIsExecuting(false);
        setError(`Failed to advance to ${targetStage}`);
      } finally {
        setLoading(false);
      }
    },
    [pipelineId, populateFromResult],
  );

  // -- Node selection -----------------------------------------------------
  const onNodeSelect = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId);
  }, []);

  const selectedNode = useMemo(() => {
    if (!selectedNodeId) return null;
    const result = findNodeInStages(stageNodes, selectedNodeId);
    if (!result) return null;
    return { stage: result.stage, data: result.node.data as Record<string, unknown> };
  }, [selectedNodeId, stageNodes]);

  const selectedNodeData = selectedNode?.data ?? null;
  const selectedNodeStage = selectedNode?.stage ?? null;

  // -- Provenance chain ---------------------------------------------------
  const provenanceChain = useMemo((): ProvenanceBreadcrumb[] => {
    if (!selectedNodeId) return [];

    const chain: ProvenanceBreadcrumb[] = [];
    let currentId = selectedNodeId;
    const visited = new Set<string>();

    while (currentId && !visited.has(currentId)) {
      visited.add(currentId);
      const link = provenance.find((entry) => entry.target_node_id === currentId);
      if (!link) break;

      const sourceStage = link.source_stage as PipelineStageType;
      const sourceNode = stageNodes[sourceStage]?.find((n) => n.id === link.source_node_id);

      chain.unshift({
        nodeId: link.source_node_id,
        nodeLabel:
          ((sourceNode?.data as Record<string, unknown>)?.label as string) || link.source_node_id,
        stage: sourceStage,
        contentHash: link.content_hash || '',
        method: link.method || '',
      });

      currentId = link.source_node_id;
    }

    return chain;
  }, [selectedNodeId, provenance, stageNodes]);

  const downstreamExecution = useMemo((): MissionControlExecutionState[] => {
    if (!selectedNodeId || !selectedNodeStage) return [];

    const entries = new Map<string, MissionControlExecutionState>();
    const addExecutionState = (
      nodeId: string,
      stage: PipelineStageType,
      data: Record<string, unknown>,
      options?: { isSelectedNode?: boolean; navigable?: boolean; label?: string },
    ) => {
      const rawStatus =
        (data.executionStatus as string | undefined) ??
        (data.status as string | undefined) ??
        stageStatus[stage] ??
        'pending';
      entries.set(nodeId, {
        nodeId,
        label: options?.label ?? (data.label as string) ?? nodeId,
        stage,
        status: normalizeExecutionStatus(rawStatus),
        rawStatus,
        agent:
          (data.executionAgent as string | undefined) ??
          (data.assignedAgent as string | undefined) ??
          (data.assignee as string | undefined) ??
          (data.agent as string | undefined),
        elapsedMs:
          typeof data.elapsedMs === 'number'
            ? data.elapsedMs
            : typeof data.elapsed_ms === 'number'
              ? (data.elapsed_ms as number)
              : undefined,
        outputPreview:
          (data.outputPreview as string | undefined) ?? (data.output_preview as string | undefined),
        navigable: options?.navigable ?? true,
        isSelectedNode: options?.isSelectedNode ?? false,
      });
    };

    if (
      selectedNodeData &&
      (selectedNodeStage === 'actions' || selectedNodeStage === 'orchestration')
    ) {
      addExecutionState(selectedNodeId, selectedNodeStage, selectedNodeData, {
        isSelectedNode: true,
      });
    }

    const queue = [selectedNodeId];
    const visited = new Set<string>(queue);
    while (queue.length > 0) {
      const currentId = queue.shift();
      if (!currentId) continue;

      for (const link of provenance) {
        if (link.source_node_id !== currentId) continue;

        const nextId = link.target_node_id;
        if (!visited.has(nextId)) {
          visited.add(nextId);
          queue.push(nextId);
        }

        const nodeMatch = findNodeInStages(stageNodes, nextId);
        if (!nodeMatch) continue;
        addExecutionState(nextId, nodeMatch.stage, nodeMatch.node.data as Record<string, unknown>);
      }
    }

    const selectedStageIndex = ALL_STAGES.indexOf(selectedNodeStage);
    for (const stage of ALL_STAGES.slice(selectedStageIndex + 1)) {
      const hasStageEntry = Array.from(entries.values()).some((entry) => entry.stage === stage);
      if (hasStageEntry) continue;
      entries.set(`stage:${stage}`, {
        nodeId: `stage:${stage}`,
        label: `${PIPELINE_STAGE_CONFIG[stage].label} stage`,
        stage,
        status: normalizeExecutionStatus(stageStatus[stage]),
        rawStatus: stageStatus[stage] ?? 'pending',
        navigable: false,
      });
    }

    return Array.from(entries.values()).sort((left, right) => {
      if (left.isSelectedNode && !right.isSelectedNode) return -1;
      if (right.isSelectedNode && !left.isSelectedNode) return 1;
      const stageDelta = ALL_STAGES.indexOf(left.stage) - ALL_STAGES.indexOf(right.stage);
      if (stageDelta !== 0) return stageDelta;
      return left.label.localeCompare(right.label);
    });
  }, [selectedNodeData, selectedNodeId, selectedNodeStage, provenance, stageNodes, stageStatus]);

  // -- Stage node counts --------------------------------------------------
  const stageNodeCounts = useMemo(() => {
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

  // -- Assemble all nodes/edges with stage offsets ------------------------
  const { nodes, edges } = useMemo(() => {
    const allNodes: Node[] = [];
    const allEdges: Edge[] = [];

    for (const stage of ALL_STAGES) {
      const offsetX = STAGE_OFFSET_X[stage];
      for (const n of stageNodes[stage]) {
        allNodes.push({ ...n, position: { x: n.position.x + offsetX, y: n.position.y } });
      }
      for (const e of stageEdges[stage]) {
        const stageColor = PIPELINE_STAGE_CONFIG[stage].primary;
        allEdges.push({
          ...e,
          style: { stroke: stageColor, strokeWidth: 2, ...(e.style || {}) },
          animated: e.animated ?? true,
        });
      }
    }

    return { nodes: allNodes, edges: allEdges };
  }, [stageNodes, stageEdges]);

  const handleStageStarted = useCallback((event: PipelineStageEvent) => {
    const stage = event.stage as PipelineStageType;
    if (!ALL_STAGES.includes(stage)) return;
    setStageStatus((prev) => ({ ...prev, [stage]: 'running' }));
    setIsExecuting(true);
  }, []);

  // -- WebSocket integration ----------------------------------------------
  const handleStageCompleted = useCallback(
    (event: PipelineStageEvent) => {
      const stage = event.stage as PipelineStageType;
      if (!ALL_STAGES.includes(stage)) return;
      setStageStatus((prev) => ({ ...prev, [stage]: 'complete' }));

      // Reload stage data
      if (pipelineId) {
        fetch(`${API_PREFIX}/${pipelineId}/stage/${stage}`)
          .then((res) => (res.ok ? res.json() : null))
          .then((data) => {
            if (!data) return;
            const stageData = data.data ?? data;
            stageNodesRef.current[stage] = parseStageNodes(stage, stageData);
            stageEdgesRef.current[stage] = parseStageEdges(stage, stageData);
            syncCacheToState();
          })
          .catch(() => {
            /* retain cache */
          });
      }
    },
    [pipelineId, syncCacheToState],
  );

  const handleNodeStatus = useCallback(
    (event: PipelineNodeStatusEvent) => {
      let updated = false;

      for (const stage of ALL_STAGES) {
        stageNodesRef.current[stage] = stageNodesRef.current[stage].map((node) => {
          if (node.id !== event.node_id) {
            return node;
          }

          updated = true;
          return {
            ...node,
            data: {
              ...(node.data as Record<string, unknown>),
              executionStatus: normalizeExecutionStatus(event.status),
              ...(event.agent ? { executionAgent: event.agent } : {}),
              ...(event.elapsed_ms != null ? { elapsedMs: event.elapsed_ms } : {}),
              ...(event.output_preview ? { outputPreview: event.output_preview } : {}),
            },
          };
        });
      }

      if (updated) {
        syncCacheToState();
      }
    },
    [syncCacheToState],
  );

  const {
    status: wsStatus,
    completedStages,
    streamedNodes,
  } = usePipelineWebSocket({
    pipelineId: pipelineId ?? undefined,
    enabled: !!pipelineId,
    onStageStarted: handleStageStarted,
    onStageCompleted: handleStageCompleted,
    onNodeStatus: handleNodeStatus,
    onCompleted: () => setIsExecuting(false),
    onFailed: () => setIsExecuting(false),
  });

  // -- Initial load -------------------------------------------------------
  useEffect(() => {
    if (initialPipelineId) {
      loadPipeline(initialPipelineId);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialPipelineId]);

  return {
    nodes,
    edges,
    stageStatus,
    stageNodeCounts,
    pipelineId,
    isExecuting,
    loadPipeline,
    startBrainDump,
    advanceStage,
    selectedNodeId,
    selectedNodeData,
    selectedNodeStage,
    onNodeSelect,
    provenance,
    provenanceChain,
    downstreamExecution,
    wsStatus: wsStatus as string,
    completedStages,
    streamedNodes,
    loading,
    error,
  };
}

export default useMissionControl;
