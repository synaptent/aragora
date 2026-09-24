'use client';

/**
 * usePipelineCanvas - State management, API persistence, and WebSocket sync
 * for the interactive pipeline canvas.
 *
 * Manages per-stage node/edge arrays, stage switching, CRUD operations,
 * AI generation, drag-and-drop, and real-time WebSocket updates.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  useNodesState,
  useEdgesState,
  addEdge,
  type Node,
  type Edge,
  type OnConnect,
  type Connection,
} from '@xyflow/react';
import { useBackend } from '@/components/BackendSelector';
import { joinBackendPath } from '@/lib/backendUrls';
import type {
  PipelineStageType,
  PipelineResultResponse,
  ReactFlowData,
} from '../components/pipeline-canvas/types';
import {
  getDefaultPipelineNodeData,
  getNodeTypeForStage,
  PIPELINE_STAGE_CONFIG,
} from '../components/pipeline-canvas/types';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PIPELINE_API_PATH = '/api/v1/canvas/pipeline';
const PIPELINE_GRAPH_API_PATH = '/api/v1/pipeline/graph';

/** A single transition suggestion returned from the suggestions endpoint. */
export interface TransitionSuggestion {
  target_stage: string;
  confidence: number;
  rationale: string;
  node_ids: string[];
  auto_promotable: boolean;
}

const EMPTY_STAGES: Record<PipelineStageType, Node[]> = {
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

const DEFAULT_STAGE_STATUS: Record<PipelineStageType, string> = {
  ideas: 'pending',
  principles: 'pending',
  goals: 'pending',
  actions: 'pending',
  orchestration: 'pending',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Convert API response stage data into React Flow nodes. */
function parseStageNodes(
  stage: PipelineStageType,
  data: ReactFlowData | Record<string, unknown> | null,
): Node[] {
  if (!data) return [];

  // Goals stage may come as { goals: [...], provenance: [...] } rather than ReactFlowData
  const rawNodes: Array<Record<string, unknown>> =
    (data as ReactFlowData).nodes ??
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

/** Convert API response stage data into React Flow edges. */
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

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function usePipelineCanvas(
  pipelineId: string | null,
  initialData?: PipelineResultResponse | null,
) {
  const { config: backendConfig } = useBackend();

  // -- React Flow state (active stage) ------------------------------------
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  // -- Selection ----------------------------------------------------------
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  // -- Stage management ---------------------------------------------------
  const [activeStage, setActiveStageRaw] = useState<PipelineStageType>('ideas');
  const [stageStatus, setStageStatus] = useState<Record<PipelineStageType, string>>({
    ...DEFAULT_STAGE_STATUS,
  });

  // -- Per-stage caches ---------------------------------------------------
  const stageNodesRef = useRef<Record<PipelineStageType, Node[]>>({ ...EMPTY_STAGES });
  const stageEdgesRef = useRef<Record<PipelineStageType, Edge[]>>({ ...EMPTY_STAGE_EDGES });

  // Expose the caches as state so consumers can read them reactively
  const [stageNodes, setStageNodes] = useState<Record<PipelineStageType, Node[]>>({
    ...EMPTY_STAGES,
  });
  const [stageEdges, setStageEdges] = useState<Record<PipelineStageType, Edge[]>>({
    ...EMPTY_STAGE_EDGES,
  });

  // -- Loading state ------------------------------------------------------
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // -- Suggestions state --------------------------------------------------
  const [suggestions, setSuggestions] = useState<TransitionSuggestion[]>([]);
  const [suggestionsLoading, setSuggestionsLoading] = useState(false);

  // -- WebSocket ref ------------------------------------------------------
  const wsRef = useRef<WebSocket | null>(null);
  const previousApiBaseRef = useRef(backendConfig.api);

  const buildApiUrl = useCallback(
    (path: string) => joinBackendPath(backendConfig.api, path),
    [backendConfig.api],
  );
  const buildWsUrl = useCallback(
    (path: string) => joinBackendPath(backendConfig.ws, path),
    [backendConfig.ws],
  );

  // -- Sync helpers -------------------------------------------------------
  const syncCacheToState = useCallback(() => {
    setStageNodes({ ...stageNodesRef.current });
    setStageEdges({ ...stageEdgesRef.current });
  }, []);

  const saveCurrentToCache = useCallback(() => {
    stageNodesRef.current[activeStage] = nodes;
    stageEdgesRef.current[activeStage] = edges;
    syncCacheToState();
  }, [activeStage, nodes, edges, syncCacheToState]);

  const loadStageIntoFlow = useCallback(
    (stage: PipelineStageType) => {
      setNodes(stageNodesRef.current[stage]);
      setEdges(stageEdgesRef.current[stage]);
    },
    [setNodes, setEdges],
  );

  // ---- Populate caches from pipeline result response --------------------
  const populateFromResult = useCallback(
    (result: PipelineResultResponse) => {
      if (result.stage_status) {
        setStageStatus(result.stage_status);
      }

      const stages: PipelineStageType[] = [
        'ideas',
        'principles',
        'goals',
        'actions',
        'orchestration',
      ];
      for (const stage of stages) {
        const stageData = (result as unknown as Record<string, unknown>)[stage] as
          ReactFlowData | Record<string, unknown> | null;
        stageNodesRef.current[stage] = parseStageNodes(stage, stageData);
        stageEdgesRef.current[stage] = parseStageEdges(stage, stageData);
      }

      syncCacheToState();
    },
    [syncCacheToState],
  );

  // ---- Load pipeline from API -------------------------------------------
  const loadPipeline = useCallback(
    async (id: string) => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(buildApiUrl(`${PIPELINE_API_PATH}/${id}`));
        if (!res.ok) {
          setError(`Failed to load pipeline: ${res.status}`);
          return;
        }
        const data: PipelineResultResponse = await res.json();
        populateFromResult(data);
        // Load the active stage into React Flow
        loadStageIntoFlow(activeStage);
      } catch {
        setError('Failed to load pipeline');
      } finally {
        setLoading(false);
      }
    },
    [activeStage, buildApiUrl, loadStageIntoFlow, populateFromResult],
  );

  // ---- Reload a single stage from API ----------------------------------
  const reloadStage = useCallback(
    async (stage: PipelineStageType) => {
      if (!pipelineId) return;
      try {
        const res = await fetch(buildApiUrl(`${PIPELINE_API_PATH}/${pipelineId}/stage/${stage}`));
        if (!res.ok) return;
        const data = await res.json();
        const stageData = data.data ?? data;
        stageNodesRef.current[stage] = parseStageNodes(stage, stageData);
        stageEdgesRef.current[stage] = parseStageEdges(stage, stageData);
        syncCacheToState();

        // If this is the currently visible stage, update React Flow
        if (stage === activeStage) {
          loadStageIntoFlow(stage);
        }
      } catch {
        // Silently fail -- the cache retains its previous state
      }
    },
    [activeStage, buildApiUrl, loadStageIntoFlow, pipelineId, syncCacheToState],
  );

  // ---- Clear current stage -----------------------------------------------
  const clearStage = useCallback(() => {
    setNodes([]);
    setEdges([]);
  }, [setNodes, setEdges]);

  // ---- Initial load when pipelineId changes -----------------------------
  useEffect(() => {
    if (pipelineId) {
      if (initialData) {
        populateFromResult(initialData);
        loadStageIntoFlow(activeStage);
      } else {
        loadPipeline(pipelineId);
      }
    } else {
      // Reset everything
      stageNodesRef.current = { ...EMPTY_STAGES };
      stageEdgesRef.current = { ...EMPTY_STAGE_EDGES };
      syncCacheToState();
      setNodes([]);
      setEdges([]);
      setStageStatus({ ...DEFAULT_STAGE_STATUS });
      setSelectedNodeId(null);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pipelineId]);

  useEffect(() => {
    if (previousApiBaseRef.current === backendConfig.api) return;
    previousApiBaseRef.current = backendConfig.api;
    if (pipelineId) {
      void loadPipeline(pipelineId);
    }
  }, [backendConfig.api, loadPipeline, pipelineId]);

  // ---- WebSocket --------------------------------------------------------
  useEffect(() => {
    if (!pipelineId) return;

    const wsUrl = buildWsUrl(`/pipeline?pipeline_id=${encodeURIComponent(pipelineId)}`);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        const eventType: string = msg.type ?? '';
        const stage: PipelineStageType | undefined = msg.data?.stage ?? msg.stage;

        switch (eventType) {
          case 'pipeline_stage_completed':
            if (stage) {
              setStageStatus((prev) => ({ ...prev, [stage]: 'complete' }));
              reloadStage(stage);
            }
            break;

          case 'pipeline_graph_updated':
            if (stage) {
              reloadStage(stage);
            }
            break;

          // Canvas collaboration events -- reload the affected stage
          case 'canvas:node:create':
          case 'canvas:node:update':
          case 'canvas:node:delete':
          case 'canvas:edge:create':
          case 'canvas:edge:delete':
            if (stage) {
              reloadStage(stage);
            } else {
              // No stage hint -- reload active
              reloadStage(activeStage);
            }
            break;

          default:
            break;
        }
      } catch {
        // Ignore malformed messages
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [activeStage, buildWsUrl, pipelineId, reloadStage]);

  // ---- Stage switching --------------------------------------------------
  const setActiveStage = useCallback(
    (newStage: PipelineStageType) => {
      if (newStage === activeStage) return;
      // Persist current stage to cache
      saveCurrentToCache();
      // Swap in the new stage
      setActiveStageRaw(newStage);
      loadStageIntoFlow(newStage);
      setSelectedNodeId(null);
    },
    [activeStage, saveCurrentToCache, loadStageIntoFlow],
  );

  // ---- Selection helpers ------------------------------------------------
  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const selectedNodeData = (selectedNode?.data as Record<string, unknown>) ?? null;

  // ---- CRUD: update selected node ---------------------------------------
  const updateSelectedNode = useCallback(
    (updates: Record<string, unknown>) => {
      if (!selectedNodeId) return;
      setNodes((nds) =>
        nds.map((n) => (n.id === selectedNodeId ? { ...n, data: { ...n.data, ...updates } } : n)),
      );
    },
    [selectedNodeId, setNodes],
  );

  // ---- CRUD: delete selected node ---------------------------------------
  const deleteSelectedNode = useCallback(() => {
    if (!selectedNodeId) return;
    setNodes((nds) => nds.filter((n) => n.id !== selectedNodeId));
    setEdges((eds) =>
      eds.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId),
    );
    setSelectedNodeId(null);
  }, [selectedNodeId, setNodes, setEdges]);

  // ---- CRUD: add node ---------------------------------------------------
  const addNode = useCallback(
    (stage: PipelineStageType, subtype: string, position: { x: number; y: number }) => {
      const nodeType = getNodeTypeForStage(stage);
      const data = getDefaultPipelineNodeData(stage, subtype);
      const newNode: Node = {
        id: `${stage}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
        type: nodeType,
        position,
        data: { ...data, stage },
      };

      // If the target stage is the active stage, add directly to React Flow
      if (stage === activeStage) {
        setNodes((nds) => [...nds, newNode]);
      } else {
        // Otherwise add to the cache
        stageNodesRef.current[stage] = [...stageNodesRef.current[stage], newNode];
        syncCacheToState();
      }
    },
    [activeStage, setNodes, syncCacheToState],
  );

  // ---- Connection handler -----------------------------------------------
  const onConnect: OnConnect = useCallback(
    (connection: Connection) => {
      const stageColor = PIPELINE_STAGE_CONFIG[activeStage].primary;
      setEdges((eds) =>
        addEdge(
          { ...connection, type: 'default', animated: true, style: { stroke: stageColor } },
          eds,
        ),
      );
    },
    [activeStage, setEdges],
  );

  // ---- Drag and drop ----------------------------------------------------
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent, wrapperRect: DOMRect) => {
      event.preventDefault();

      const raw = event.dataTransfer.getData('application/pipeline-node');
      if (!raw) return;

      let parsed: { stage: PipelineStageType; subtype: string };
      try {
        parsed = JSON.parse(raw);
      } catch {
        return;
      }

      const position = { x: event.clientX - wrapperRect.left, y: event.clientY - wrapperRect.top };

      addNode(parsed.stage, parsed.subtype, position);
    },
    [addNode],
  );

  // ---- API: save pipeline -----------------------------------------------
  const savePipeline = useCallback(async () => {
    if (!pipelineId) return;

    // Persist the current React Flow state into cache first
    saveCurrentToCache();

    setLoading(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        pipeline_id: pipelineId,
        stages: {} as Record<string, unknown>,
      };

      const stages: PipelineStageType[] = [
        'ideas',
        'principles',
        'goals',
        'actions',
        'orchestration',
      ];
      const stagesPayload: Record<string, unknown> = {};
      for (const stage of stages) {
        stagesPayload[stage] = {
          nodes: stageNodesRef.current[stage],
          edges: stageEdgesRef.current[stage],
        };
      }
      body.stages = stagesPayload;

      const res = await fetch(buildApiUrl(`${PIPELINE_API_PATH}/${pipelineId}`), {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        setError(`Save failed: ${res.status}`);
      }
    } catch {
      setError('Failed to save pipeline');
    } finally {
      setLoading(false);
    }
  }, [buildApiUrl, pipelineId, saveCurrentToCache]);

  // ---- API: AI generate stage -------------------------------------------
  const aiGenerate = useCallback(
    async (stage: PipelineStageType) => {
      if (!pipelineId) return;

      setLoading(true);
      setError(null);
      try {
        let res: Response;

        if (stage === 'goals') {
          // Extract goals from current ideas nodes
          const ideaNodes = stageNodesRef.current.ideas;
          res = await fetch(buildApiUrl(`${PIPELINE_API_PATH}/extract-goals`), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              pipeline_id: pipelineId,
              ideas: ideaNodes.map((n) => ({
                id: n.id,
                type: n.type,
                position: n.position,
                data: n.data,
              })),
            }),
          });
        } else {
          // Advance to 'actions' or 'orchestration'
          res = await fetch(buildApiUrl(`${PIPELINE_API_PATH}/advance`), {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pipeline_id: pipelineId, target_stage: stage }),
          });
        }

        if (!res.ok) {
          setError(`AI generation failed: ${res.status}`);
          return;
        }

        const data = await res.json();

        // The response may include a full result or stage-specific data
        if (data.result) {
          populateFromResult(data.result as PipelineResultResponse);
        } else if (data.stage_status) {
          setStageStatus(data.stage_status);
        }

        // If stage-level data is present, merge it
        const stageData = data[stage] ?? data.data ?? data.stage_data;
        if (stageData) {
          stageNodesRef.current[stage] = parseStageNodes(stage, stageData);
          stageEdgesRef.current[stage] = parseStageEdges(stage, stageData);
          syncCacheToState();
        }

        // Refresh React Flow if we're viewing this stage
        if (stage === activeStage) {
          loadStageIntoFlow(stage);
        }
      } catch {
        setError('AI generation failed');
      } finally {
        setLoading(false);
      }
    },
    [activeStage, buildApiUrl, loadStageIntoFlow, pipelineId, populateFromResult, syncCacheToState],
  );

  // ---- API: create pipeline from natural-language ideas ----------------
  const createFromIdeas = useCallback(
    async (ideasText: string): Promise<string | null> => {
      setLoading(true);
      setError(null);
      try {
        // Split text into individual idea strings (one per line, filter blanks)
        const ideas = ideasText
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean);

        if (ideas.length === 0) {
          setError('No ideas provided');
          setLoading(false);
          return null;
        }

        const res = await fetch(buildApiUrl(`${PIPELINE_API_PATH}/from-ideas`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ideas, auto_advance: false }),
        });

        if (!res.ok) {
          setError(`Failed to create pipeline: ${res.status}`);
          return null;
        }

        const data = await res.json();
        const newPipelineId = data.pipeline_id as string;

        if (data.result) {
          populateFromResult(data.result as PipelineResultResponse);
          loadStageIntoFlow(activeStage);
        }

        return newPipelineId;
      } catch {
        setError('Failed to create pipeline from ideas');
        return null;
      } finally {
        setLoading(false);
      }
    },
    [activeStage, buildApiUrl, loadStageIntoFlow, populateFromResult],
  );

  // ---- API: run full pipeline ------------------------------------------
  const runPipeline = useCallback(
    async (inputText: string): Promise<string | null> => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(buildApiUrl(`${PIPELINE_API_PATH}/run`), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ input_text: inputText }),
        });

        if (!res.ok) {
          setError(`Failed to run pipeline: ${res.status}`);
          return null;
        }

        const data = await res.json();
        return data.pipeline_id as string;
      } catch {
        setError('Failed to run pipeline');
        return null;
      } finally {
        setLoading(false);
      }
    },
    [buildApiUrl],
  );

  // ---- API: approve transition ------------------------------------------
  const approveTransition = useCallback(
    async (transitionId: string) => {
      if (!pipelineId) return;
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(
          buildApiUrl(`${PIPELINE_API_PATH}/${pipelineId}/approve-transition`),
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ transition_id: transitionId, approved: true }),
          },
        );
        if (!res.ok) {
          setError(`Transition approval failed: ${res.status}`);
        }
      } catch {
        setError('Failed to approve transition');
      } finally {
        setLoading(false);
      }
    },
    [buildApiUrl, pipelineId],
  );

  // ---- API: reject transition -------------------------------------------
  const rejectTransition = useCallback(
    async (transitionId: string, reason?: string) => {
      if (!pipelineId) return;
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(
          buildApiUrl(`${PIPELINE_API_PATH}/${pipelineId}/approve-transition`),
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              transition_id: transitionId,
              approved: false,
              reason: reason ?? '',
            }),
          },
        );
        if (!res.ok) {
          setError(`Transition rejection failed: ${res.status}`);
        }
      } catch {
        setError('Failed to reject transition');
      } finally {
        setLoading(false);
      }
    },
    [buildApiUrl, pipelineId],
  );

  // ---- API: fetch transition suggestions ---------------------------------
  const fetchSuggestions = useCallback(
    async (stage: PipelineStageType) => {
      if (!pipelineId) return;

      setSuggestionsLoading(true);
      try {
        const res = await fetch(
          buildApiUrl(
            `${PIPELINE_GRAPH_API_PATH}/${encodeURIComponent(pipelineId)}/suggestions?stage=${encodeURIComponent(stage)}`,
          ),
        );
        if (!res.ok) {
          setSuggestions([]);
          return;
        }
        const data = await res.json();
        const items: TransitionSuggestion[] = Array.isArray(data.suggestions)
          ? data.suggestions
          : [];
        setSuggestions(items);
      } catch {
        setSuggestions([]);
      } finally {
        setSuggestionsLoading(false);
      }
    },
    [buildApiUrl, pipelineId],
  );

  // ---- Node status updates (from WebSocket) ------------------------------
  const updateNodeStatus = useCallback(
    (nodeId: string, status: string, elapsedMs?: number, outputPreview?: string) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId
            ? {
                ...n,
                data: {
                  ...n.data,
                  executionStatus: status,
                  ...(elapsedMs != null ? { elapsedMs } : {}),
                  ...(outputPreview ? { outputPreview } : {}),
                },
              }
            : n,
        ),
      );
      // Also update the stage cache for orchestration nodes
      stageNodesRef.current.orchestration = stageNodesRef.current.orchestration.map((n) =>
        n.id === nodeId
          ? {
              ...n,
              data: {
                ...n.data,
                executionStatus: status,
                ...(elapsedMs != null ? { elapsedMs } : {}),
                ...(outputPreview ? { outputPreview } : {}),
              },
            }
          : n,
      );
    },
    [setNodes],
  );

  // ---- Return -----------------------------------------------------------
  return {
    // React Flow state
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,

    // Selection
    selectedNodeId,
    setSelectedNodeId,
    selectedNodeData,

    // CRUD operations
    updateSelectedNode,
    deleteSelectedNode,
    addNode,

    // Stage management
    activeStage,
    setActiveStage,
    stageStatus,

    // Per-stage data cache
    stageNodes,
    stageEdges,

    // API operations
    savePipeline,
    aiGenerate,
    createFromIdeas,
    runPipeline,
    approveTransition,
    rejectTransition,
    fetchSuggestions,

    // Suggestions
    suggestions,
    suggestionsLoading,

    // Node status (for WebSocket-driven updates)
    updateNodeStatus,

    // Stage mutations
    clearStage,
    populateFromResult,

    // Loading state
    loading,
    error,

    // DnD handlers
    onDrop,
    onDragOver,
  };
}

export default usePipelineCanvas;
