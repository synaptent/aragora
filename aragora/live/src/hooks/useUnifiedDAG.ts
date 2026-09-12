'use client';

/**
 * useUnifiedDAG - Full-lifecycle hook for the Unified DAG Canvas.
 *
 * Manages a server-side UniversalGraph and projects it to React Flow
 * Node[]/Edge[] for the canvas.  Exposes AI operations (debate, decompose,
 * prioritize, assign, execute, find-precedents) plus bulk ops (cluster,
 * auto-flow) and undo/redo.
 */

import { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import type { Node, Edge } from '@xyflow/react';
import { useSWRFetch } from './useSWRFetch';
import { apiFetch } from '@/lib/api';
import type { ExecutionHistoryEntry } from '@/components/unified-dag/ExecutionSidebar';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export const DAG_STAGES = ['ideas', 'principles', 'goals', 'actions', 'orchestration'] as const;

export type DAGStage = (typeof DAG_STAGES)[number];

export interface DAGNodeData {
  label: string;
  description: string;
  stage: DAGStage;
  subtype: string;
  status: string;
  priority: number;
  metadata: Record<string, unknown>;
  [key: string]: unknown;
}

export interface DAGOperationResult {
  success: boolean;
  message: string;
  created_nodes: string[];
  metadata: Record<string, unknown>;
}

interface GraphSnapshot {
  nodes: Node<DAGNodeData>[];
  edges: Edge[];
}

type ServerGraphNode = Record<string, unknown>;
type ServerGraphEdge = Record<string, unknown>;

// Stage → swim-lane x position
const STAGE_X: Record<DAGStage, number> = {
  ideas: 0,
  principles: 320,
  goals: 640,
  actions: 960,
  orchestration: 1280,
};

// Stage → color hint
export const STAGE_COLORS: Record<DAGStage, string> = {
  ideas: '#6366f1', // indigo
  principles: '#8b5cf6', // violet
  goals: '#10b981', // emerald
  actions: '#f59e0b', // amber
  orchestration: '#ec4899', // pink
};

const NODE_TOP_PADDING = 96;
const NODE_VERTICAL_GAP = 160;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOwn(obj: Record<string, unknown>, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(obj, key);
}

function getNumericValue(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return null;
}

function getStringList(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.map((item) => String(item).trim()).filter(Boolean);
}

function normalizeStage(value: unknown): DAGStage {
  const raw = String(value || 'ideas').toLowerCase();
  if ((DAG_STAGES as readonly string[]).includes(raw)) {
    return raw as DAGStage;
  }
  return 'ideas';
}

function getNodeLabel(node: ServerGraphNode, data: Record<string, unknown>): string {
  const rawLabel = node.label ?? data.label ?? node.id;
  return typeof rawLabel === 'string' ? rawLabel : String(rawLabel || '');
}

function getNodeSubtype(node: ServerGraphNode, data: Record<string, unknown>): string {
  const rawSubtype = node.node_subtype ?? data.nodeSubtype ?? data.subtype ?? node.subtype;
  return typeof rawSubtype === 'string' ? rawSubtype : String(rawSubtype || '');
}

function getBaselineSortIndex(node: ServerGraphNode): [number, number, number, string] {
  const data = isRecord(node.data) ? node.data : {};
  const explicitY = getNumericValue(node.position_y ?? data.position_y ?? data.positionY);
  const priority = getNumericValue(node.priority ?? data.priority) ?? 0;
  const createdAt = getNumericValue(node.created_at) ?? Number.MAX_SAFE_INTEGER;
  const label = getNodeLabel(node, data).toLowerCase();

  return [explicitY ?? Number.MAX_SAFE_INTEGER, priority * -1, createdAt, label];
}

export function normalizeDagStatus(node: ServerGraphNode): string {
  const data = isRecord(node.data) ? node.data : {};
  const rawStatus =
    node.execution_status ??
    data.execution_status ??
    data.executionStatus ??
    node.status ??
    data.status ??
    node.approval_status ??
    data.approval_status ??
    data.approvalStatus ??
    'pending';

  switch (String(rawStatus).toLowerCase()) {
    case 'active':
      return 'ready';
    case 'in_progress':
      return 'running';
    case 'completed':
    case 'approved':
      return 'succeeded';
    case 'rejected':
      return 'failed';
    case 'revised':
    case 'partial':
      return 'blocked';
    default:
      return String(rawStatus || 'pending').toLowerCase();
  }
}

function buildLayoutLinks(
  serverNodes: ServerGraphNode[],
  serverEdges: ServerGraphEdge[],
): Array<{ source: string; target: string }> {
  const links: Array<{ source: string; target: string }> = [];
  const seen = new Set<string>();
  const validNodeIds = new Set(serverNodes.map((node) => String(node.id || '')));

  const pushLink = (source: string, target: string) => {
    if (!source || !target || source === target) return;
    if (!validNodeIds.has(source) || !validNodeIds.has(target)) return;
    const key = `${source}->${target}`;
    if (seen.has(key)) return;
    seen.add(key);
    links.push({ source, target });
  };

  for (const edge of serverEdges) {
    pushLink(
      String(edge.source ?? edge.source_id ?? ''),
      String(edge.target ?? edge.target_id ?? ''),
    );
  }

  for (const node of serverNodes) {
    const nodeId = String(node.id || '');
    for (const parentId of getStringList(node.parent_ids)) {
      pushLink(parentId, nodeId);
    }
  }

  return links;
}

function sortStageNodes(
  stageNodes: ServerGraphNode[],
  scores: Map<string, number | null>,
  fallbackOrder: Map<string, number>,
): ServerGraphNode[] {
  return [...stageNodes].sort((left, right) => {
    const leftId = String(left.id || '');
    const rightId = String(right.id || '');
    const leftScore = scores.get(leftId) ?? null;
    const rightScore = scores.get(rightId) ?? null;

    if (leftScore !== null && rightScore !== null && leftScore !== rightScore) {
      return leftScore - rightScore;
    }
    if (leftScore !== null) return -1;
    if (rightScore !== null) return 1;

    const leftFallback = fallbackOrder.get(leftId) ?? Number.MAX_SAFE_INTEGER;
    const rightFallback = fallbackOrder.get(rightId) ?? Number.MAX_SAFE_INTEGER;
    if (leftFallback !== rightFallback) {
      return leftFallback - rightFallback;
    }

    const [leftY, leftPriority, leftCreatedAt, leftLabel] = getBaselineSortIndex(left);
    const [rightY, rightPriority, rightCreatedAt, rightLabel] = getBaselineSortIndex(right);

    if (leftY !== rightY) return leftY - rightY;
    if (leftPriority !== rightPriority) return leftPriority - rightPriority;
    if (leftCreatedAt !== rightCreatedAt) return leftCreatedAt - rightCreatedAt;
    if (leftLabel !== rightLabel) return leftLabel.localeCompare(rightLabel);

    return leftId.localeCompare(rightId);
  });
}

function computeNodePositions(
  serverNodes: ServerGraphNode[],
  serverEdges: ServerGraphEdge[],
): Map<string, { x: number; y: number }> {
  const nodesByStage = new Map<DAGStage, ServerGraphNode[]>();
  const nodeById = new Map<string, ServerGraphNode>();
  const incoming = new Map<string, string[]>();
  const outgoing = new Map<string, string[]>();
  const fallbackOrder = new Map<string, number>();

  for (const stage of DAG_STAGES) {
    nodesByStage.set(stage, []);
  }

  for (const node of serverNodes) {
    const stage = normalizeStage(node.stage);
    nodesByStage.get(stage)?.push(node);
    nodeById.set(String(node.id || ''), node);
  }

  for (const stage of DAG_STAGES) {
    const ordered = [...(nodesByStage.get(stage) ?? [])].sort((left, right) => {
      const leftBaseline = getBaselineSortIndex(left);
      const rightBaseline = getBaselineSortIndex(right);
      if (leftBaseline[0] !== rightBaseline[0]) return leftBaseline[0] - rightBaseline[0];
      if (leftBaseline[1] !== rightBaseline[1]) return leftBaseline[1] - rightBaseline[1];
      if (leftBaseline[2] !== rightBaseline[2]) return leftBaseline[2] - rightBaseline[2];
      return leftBaseline[3].localeCompare(rightBaseline[3]);
    });
    ordered.forEach((node, index) => {
      fallbackOrder.set(String(node.id || ''), index);
    });
  }

  for (const link of buildLayoutLinks(serverNodes, serverEdges)) {
    incoming.set(link.target, [...(incoming.get(link.target) ?? []), link.source]);
    outgoing.set(link.source, [...(outgoing.get(link.source) ?? []), link.target]);
  }

  const stageOrders = new Map<DAGStage, string[]>();
  const forwardRank = new Map<string, number>();

  for (const stage of DAG_STAGES) {
    const stageNodes = nodesByStage.get(stage) ?? [];
    const scores = new Map<string, number | null>();

    for (const node of stageNodes) {
      const nodeId = String(node.id || '');
      const upstreamRanks = (incoming.get(nodeId) ?? [])
        .map((sourceId) => forwardRank.get(sourceId))
        .filter((value): value is number => value !== undefined);

      scores.set(
        nodeId,
        upstreamRanks.length > 0
          ? upstreamRanks.reduce((sum, rank) => sum + rank, 0) / upstreamRanks.length
          : null,
      );
    }

    const orderedNodes = sortStageNodes(stageNodes, scores, fallbackOrder);
    const orderedIds = orderedNodes.map((node) => String(node.id || ''));
    stageOrders.set(stage, orderedIds);
    orderedIds.forEach((id, index) => forwardRank.set(id, index));
  }

  const backwardRank = new Map<string, number>();

  for (const stage of [...DAG_STAGES].reverse()) {
    const orderedIds = stageOrders.get(stage) ?? [];
    const stageNodes = orderedIds
      .map((id) => nodeById.get(id))
      .filter((node): node is ServerGraphNode => node !== undefined);
    const scores = new Map<string, number | null>();

    for (const node of stageNodes) {
      const nodeId = String(node.id || '');
      const downstreamRanks = (outgoing.get(nodeId) ?? [])
        .map((targetId) => backwardRank.get(targetId))
        .filter((value): value is number => value !== undefined);

      scores.set(
        nodeId,
        downstreamRanks.length > 0
          ? downstreamRanks.reduce((sum, rank) => sum + rank, 0) / downstreamRanks.length
          : (fallbackOrder.get(nodeId) ?? null),
      );
    }

    const refinedNodes = sortStageNodes(stageNodes, scores, fallbackOrder);
    const refinedIds = refinedNodes.map((node) => String(node.id || ''));
    stageOrders.set(stage, refinedIds);
    refinedIds.forEach((id, index) => backwardRank.set(id, index));
  }

  const positions = new Map<string, { x: number; y: number }>();

  for (const stage of DAG_STAGES) {
    let nextY = NODE_TOP_PADDING;
    const orderedIds = stageOrders.get(stage) ?? [];

    orderedIds.forEach((id, index) => {
      const node = nodeById.get(id);
      if (!node) return;

      const data = isRecord(node.data) ? node.data : {};
      const explicitX = getNumericValue(node.position_x ?? data.position_x ?? data.positionX);
      const explicitY = getNumericValue(node.position_y ?? data.position_y ?? data.positionY);
      const hasExplicitX =
        hasOwn(node, 'position_x') || hasOwn(data, 'position_x') || hasOwn(data, 'positionX');
      const hasExplicitY =
        hasOwn(node, 'position_y') || hasOwn(data, 'position_y') || hasOwn(data, 'positionY');

      const preferredY =
        hasExplicitY && explicitY !== null
          ? explicitY
          : NODE_TOP_PADDING + index * NODE_VERTICAL_GAP;
      const y = index === 0 ? Math.max(NODE_TOP_PADDING, preferredY) : Math.max(nextY, preferredY);
      const x = hasExplicitX && explicitX !== null ? explicitX : STAGE_X[stage];

      positions.set(id, { x, y });
      nextY = y + NODE_VERTICAL_GAP;
    });
  }

  return positions;
}

function serverNodeToReactFlow(
  node: ServerGraphNode,
  position: { x: number; y: number },
): Node<DAGNodeData> {
  const data = isRecord(node.data) ? node.data : {};
  const metadata = {
    ...(isRecord(node.metadata) ? node.metadata : {}),
    ...(isRecord(data.metadata) ? data.metadata : {}),
  };
  const stage = normalizeStage(node.stage ?? data.stage);
  const subtype = getNodeSubtype(node, data);
  const executionStatus = node.execution_status ?? data.execution_status ?? data.executionStatus;
  const approvalStatus = node.approval_status ?? data.approval_status ?? data.approvalStatus;
  const priority = getNumericValue(node.priority ?? data.priority) ?? 0;

  return {
    id: String(node.id || ''),
    type: `${stage}Node`,
    position,
    data: {
      ...data,
      label: getNodeLabel(node, data),
      description:
        typeof node.description === 'string'
          ? node.description
          : typeof data.description === 'string'
            ? data.description
            : '',
      stage,
      subtype,
      status: normalizeDagStatus(node),
      priority,
      metadata,
      contentHash: node.content_hash ?? data.content_hash ?? data.contentHash ?? '',
      approvalStatus: approvalStatus ? String(approvalStatus) : undefined,
      approval_status: approvalStatus ? String(approvalStatus) : undefined,
      executionStatus: executionStatus ? String(executionStatus) : undefined,
      execution_status: executionStatus ? String(executionStatus) : undefined,
    },
    style: isRecord(node.style) ? (node.style as Node<DAGNodeData>['style']) : undefined,
  };
}

function serverEdgeToReactFlow(edge: ServerGraphEdge, stageByNodeId: Map<string, DAGStage>): Edge {
  const rawData = isRecord(edge.data) ? edge.data : {};
  const source = String(edge.source ?? edge.source_id ?? '');
  const target = String(edge.target ?? edge.target_id ?? '');
  const sourceStage = stageByNodeId.get(source) ?? 'ideas';
  const targetStage = stageByNodeId.get(target);
  const edgeType = String(edge.edge_type ?? rawData.edgeType ?? edge.type ?? 'default');
  const crossStage = Boolean(
    edge.cross_stage ?? rawData.crossStage ?? (targetStage ? sourceStage !== targetStage : false),
  );

  return {
    id: String(edge.id ?? `${source}-${target}`),
    source,
    target,
    type: crossStage ? 'crossStage' : String(edge.type ?? 'default'),
    label: edge.label ? String(edge.label) : edgeType || undefined,
    animated: Boolean(edge.animated ?? (crossStage || edgeType.toLowerCase() === 'similarity')),
    data: { edgeType, crossStage, ...rawData },
    style: crossStage
      ? { stroke: STAGE_COLORS[sourceStage], strokeDasharray: '6 4' }
      : { stroke: STAGE_COLORS[sourceStage] },
  };
}

export function mapServerGraphToReactFlow(graph: Record<string, unknown>): GraphSnapshot {
  const serverNodes = Array.isArray(graph.nodes) ? graph.nodes.filter(isRecord) : [];
  const serverEdges = Array.isArray(graph.edges) ? graph.edges.filter(isRecord) : [];
  const positions = computeNodePositions(serverNodes, serverEdges);
  const nodes = serverNodes.map((node) =>
    serverNodeToReactFlow(
      node,
      positions.get(String(node.id || '')) ?? {
        x: STAGE_X[normalizeStage(node.stage)],
        y: NODE_TOP_PADDING,
      },
    ),
  );
  const stageByNodeId = new Map(nodes.map((node) => [node.id, node.data.stage]));
  const edges = serverEdges
    .map((edge) => serverEdgeToReactFlow(edge, stageByNodeId))
    .filter((edge) => edge.source && edge.target);

  return { nodes, edges };
}

export function validateDagGraph(nodes: Node<DAGNodeData>[], edges: Edge[]): string[] {
  const errors: string[] = [];
  if (nodes.length === 0) {
    errors.push('Graph is empty — add at least one idea node');
    return errors;
  }

  const byStage = Object.fromEntries(
    DAG_STAGES.map((stage) => [stage, [] as Node<DAGNodeData>[]]),
  ) as Record<DAGStage, Node<DAGNodeData>[]>;

  for (const node of nodes) {
    const stage = normalizeStage((node.data as DAGNodeData).stage);
    byStage[stage].push(node);
  }

  if (byStage.ideas.length === 0) {
    errors.push('No idea nodes — ideas are required to start the pipeline');
  }

  for (let index = 1; index < DAG_STAGES.length; index += 1) {
    const stage = DAG_STAGES[index];
    if (byStage[stage].length === 0) continue;

    const upstreamStages = DAG_STAGES.slice(0, index).filter(
      (candidate) => byStage[candidate].length > 0,
    );
    const upstreamNodeIds = new Set(
      upstreamStages.flatMap((candidate) => byStage[candidate].map((node) => node.id)),
    );

    const hasIncoming = byStage[stage].some((node) =>
      edges.some((edge) => edge.target === node.id && upstreamNodeIds.has(edge.source)),
    );

    if (!hasIncoming) {
      const nearestUpstream = upstreamStages.at(-1) ?? 'earlier stages';
      errors.push(
        `${stage} nodes have no connections from ${nearestUpstream} — add cross-stage edges`,
      );
    }
  }

  const nodesWithEdges = new Set<string>();
  for (const edge of edges) {
    nodesWithEdges.add(edge.source);
    nodesWithEdges.add(edge.target);
  }
  const orphans = nodes.filter((node) => !nodesWithEdges.has(node.id));
  if (orphans.length > 0 && nodes.length > 1) {
    errors.push(`${orphans.length} orphan node(s) with no connections`);
  }

  return errors;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

const API_PREFIX = '/api/v1/pipeline/dag';

export function useUnifiedDAG(graphId: string | null) {
  // React Flow state
  const [nodes, setNodes] = useState<Node<DAGNodeData>[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [operationLoading, setOperationLoading] = useState(false);
  const [operationError, setOperationError] = useState<string | null>(null);

  // Undo/redo
  const undoStack = useRef<GraphSnapshot[]>([]);
  const redoStack = useRef<GraphSnapshot[]>([]);

  // Fetch initial graph
  const { data: graphData, mutate: mutateGraph } = useSWRFetch<{ data: Record<string, unknown> }>(
    graphId ? `${API_PREFIX}/${graphId}` : null,
  );

  // Sync server graph → React Flow
  useEffect(() => {
    if (!graphData?.data) return;
    const { nodes: nextNodes, edges: nextEdges } = mapServerGraphToReactFlow(graphData.data);
    setNodes(nextNodes);
    setEdges(nextEdges);
  }, [graphData]);

  // -------------------------------------------------------------------------
  // Snapshot helpers
  // -------------------------------------------------------------------------

  const pushUndo = useCallback(() => {
    undoStack.current.push({ nodes: [...nodes], edges: [...edges] });
    redoStack.current = [];
  }, [nodes, edges]);

  const undo = useCallback(() => {
    const snap = undoStack.current.pop();
    if (!snap) return;
    redoStack.current.push({ nodes, edges });
    setNodes(snap.nodes);
    setEdges(snap.edges);
  }, [nodes, edges]);

  const redo = useCallback(() => {
    const snap = redoStack.current.pop();
    if (!snap) return;
    undoStack.current.push({ nodes, edges });
    setNodes(snap.nodes);
    setEdges(snap.edges);
  }, [nodes, edges]);

  // -------------------------------------------------------------------------
  // Graph CRUD
  // -------------------------------------------------------------------------

  const addNode = useCallback(
    (node: Node<DAGNodeData>) => {
      pushUndo();
      setNodes((prev) => [...prev, node]);
    },
    [pushUndo],
  );

  const updateNode = useCallback(
    (id: string, data: Partial<DAGNodeData>) => {
      pushUndo();
      setNodes((prev) =>
        prev.map((n) => (n.id === id ? { ...n, data: { ...n.data, ...data } } : n)),
      );
    },
    [pushUndo],
  );

  const deleteNode = useCallback(
    (id: string) => {
      pushUndo();
      setNodes((prev) => prev.filter((n) => n.id !== id));
      setEdges((prev) => prev.filter((e) => e.source !== id && e.target !== id));
    },
    [pushUndo],
  );

  const addEdge = useCallback(
    (edge: Edge) => {
      pushUndo();
      setEdges((prev) => [...prev, edge]);
    },
    [pushUndo],
  );

  const deleteEdge = useCallback(
    (id: string) => {
      pushUndo();
      setEdges((prev) => prev.filter((e) => e.id !== id));
    },
    [pushUndo],
  );

  // -------------------------------------------------------------------------
  // AI Operations
  // -------------------------------------------------------------------------

  const runOperation = useCallback(
    async (
      nodeId: string,
      operation: string,
      body?: Record<string, unknown>,
    ): Promise<DAGOperationResult | null> => {
      if (!graphId) return null;
      setOperationLoading(true);
      setOperationError(null);
      try {
        const result = await apiFetch<{ data: DAGOperationResult }>(
          `${API_PREFIX}/${graphId}/nodes/${nodeId}/${operation}`,
          { method: 'POST', body: JSON.stringify(body || {}) },
        );
        pushUndo();
        await mutateGraph();
        return result.data ?? null;
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Operation failed';
        setOperationError(msg);
        return null;
      } finally {
        setOperationLoading(false);
      }
    },
    [graphId, pushUndo, mutateGraph],
  );

  const debateNode = useCallback(
    (nodeId: string, agents?: string[], rounds?: number) =>
      runOperation(nodeId, 'debate', { agents, rounds }),
    [runOperation],
  );

  const decomposeNode = useCallback(
    (nodeId: string) => runOperation(nodeId, 'decompose'),
    [runOperation],
  );

  const prioritizeChildren = useCallback(
    (nodeId: string) => runOperation(nodeId, 'prioritize'),
    [runOperation],
  );

  const assignAgents = useCallback(
    (nodeId: string) => runOperation(nodeId, 'assign-agents'),
    [runOperation],
  );

  const executeNode = useCallback(
    (nodeId: string) => runOperation(nodeId, 'execute'),
    [runOperation],
  );

  const findPrecedents = useCallback(
    (nodeId: string, maxResults?: number) =>
      runOperation(nodeId, 'find-precedents', { max_results: maxResults }),
    [runOperation],
  );

  // -------------------------------------------------------------------------
  // Bulk Operations
  // -------------------------------------------------------------------------

  const clusterIdeas = useCallback(
    async (ideas: string[], threshold?: number): Promise<DAGOperationResult | null> => {
      if (!graphId) return null;
      setOperationLoading(true);
      setOperationError(null);
      try {
        const result = await apiFetch<{ data: DAGOperationResult }>(
          `${API_PREFIX}/${graphId}/cluster-ideas`,
          { method: 'POST', body: JSON.stringify({ ideas, threshold }) },
        );
        pushUndo();
        await mutateGraph();
        return result.data ?? null;
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Clustering failed';
        setOperationError(msg);
        return null;
      } finally {
        setOperationLoading(false);
      }
    },
    [graphId, pushUndo, mutateGraph],
  );

  const autoFlow = useCallback(
    async (
      ideas: string[],
      config?: Record<string, unknown>,
    ): Promise<DAGOperationResult | null> => {
      if (!graphId) return null;
      setOperationLoading(true);
      setOperationError(null);
      try {
        const result = await apiFetch<{ data: DAGOperationResult }>(
          `${API_PREFIX}/${graphId}/auto-flow`,
          { method: 'POST', body: JSON.stringify({ ideas, config }) },
        );
        pushUndo();
        await mutateGraph();
        return result.data ?? null;
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Auto-flow failed';
        setOperationError(msg);
        return null;
      } finally {
        setOperationLoading(false);
      }
    },
    [graphId, pushUndo, mutateGraph],
  );

  // -------------------------------------------------------------------------
  // Validation
  // -------------------------------------------------------------------------

  const validateGraph = useCallback((): string[] => {
    return validateDagGraph(nodes, edges);
  }, [nodes, edges]);

  // -------------------------------------------------------------------------
  // Batch Execution
  // -------------------------------------------------------------------------

  const [executionHistory, setExecutionHistory] = useState<ExecutionHistoryEntry[]>([]);
  const [batchExecuting, setBatchExecuting] = useState(false);

  const executeAllReady = useCallback(async (): Promise<void> => {
    if (!graphId) return;
    const readyNodes = nodes.filter((n) => (n.data as unknown as DAGNodeData).status === 'ready');
    if (readyNodes.length === 0) return;

    setBatchExecuting(true);
    pushUndo();

    // Mark all ready nodes as running
    setNodes((prev) =>
      prev.map((n) => {
        if ((n.data as unknown as DAGNodeData).status === 'ready') {
          return { ...n, data: { ...n.data, status: 'running' } as DAGNodeData };
        }
        return n;
      }),
    );

    try {
      const result = await apiFetch<{
        data: { results: Array<{ node_id: string; status: string; duration_ms: number }> };
      }>(`${API_PREFIX}/${graphId}/execute-batch`, {
        method: 'POST',
        body: JSON.stringify({ node_ids: readyNodes.map((n) => n.id) }),
      });

      const batchResults = result?.data?.results || [];
      const newHistory: ExecutionHistoryEntry[] = batchResults.map((r) => {
        const node = readyNodes.find((n) => n.id === r.node_id);
        return {
          id: `${r.node_id}-${Date.now()}`,
          nodeId: r.node_id,
          nodeLabel: (node?.data as unknown as DAGNodeData)?.label || r.node_id,
          status: r.status === 'succeeded' ? 'succeeded' : 'failed',
          durationMs: r.duration_ms || 0,
          timestamp: Date.now(),
        };
      });
      setExecutionHistory((prev) => [...newHistory, ...prev]);

      // Update node statuses from batch results
      setNodes((prev) =>
        prev.map((n) => {
          const batchResult = batchResults.find((r) => r.node_id === n.id);
          if (batchResult) {
            return { ...n, data: { ...n.data, status: batchResult.status } as DAGNodeData };
          }
          return n;
        }),
      );

      await mutateGraph();
    } catch (err) {
      // On failure, revert running nodes back to ready
      setNodes((prev) =>
        prev.map((n) => {
          if ((n.data as unknown as DAGNodeData).status === 'running') {
            return { ...n, data: { ...n.data, status: 'ready' } as DAGNodeData };
          }
          return n;
        }),
      );
      setOperationError(err instanceof Error ? err.message : 'Batch execution failed');
    } finally {
      setBatchExecuting(false);
    }
  }, [graphId, nodes, pushUndo, mutateGraph]);

  const autoAdvanceAll = useCallback(async (): Promise<void> => {
    if (!graphId) return;
    setBatchExecuting(true);
    setOperationError(null);
    try {
      await apiFetch<{ data: DAGOperationResult }>(`${API_PREFIX}/${graphId}/auto-advance`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      pushUndo();
      await mutateGraph();
    } catch (err) {
      setOperationError(err instanceof Error ? err.message : 'Auto-advance failed');
    } finally {
      setBatchExecuting(false);
    }
  }, [graphId, pushUndo, mutateGraph]);

  // Computed stats
  const graphStats = useMemo(() => {
    const total = nodes.length;
    const succeeded = nodes.filter(
      (n) => (n.data as unknown as DAGNodeData).status === 'succeeded',
    ).length;
    const ready = nodes.filter((n) => (n.data as unknown as DAGNodeData).status === 'ready').length;
    const running = nodes.filter(
      (n) => (n.data as unknown as DAGNodeData).status === 'running',
    ).length;
    const failed = nodes.filter(
      (n) => (n.data as unknown as DAGNodeData).status === 'failed',
    ).length;
    return {
      total,
      succeeded,
      ready,
      running,
      failed,
      completionPct: total > 0 ? Math.round((succeeded / total) * 100) : 0,
    };
  }, [nodes]);

  return {
    // Graph state
    nodes,
    edges,
    setNodes,
    setEdges,

    // CRUD
    addNode,
    updateNode,
    deleteNode,
    addEdge,
    deleteEdge,

    // AI operations
    debateNode,
    decomposeNode,
    prioritizeChildren,
    assignAgents,
    executeNode,
    findPrecedents,

    // Bulk operations
    clusterIdeas,
    autoFlow,

    // Execution
    executeAllReady,
    autoAdvanceAll,
    validateGraph,
    executionHistory,
    batchExecuting,
    graphStats,

    // State
    operationLoading,
    operationError,

    // Undo/redo
    undo,
    redo,
    canUndo: undoStack.current.length > 0,
    canRedo: redoStack.current.length > 0,

    // Refresh
    refresh: mutateGraph,
  };
}
