'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type Connection,
  addEdge,
} from '@xyflow/react';
import { useBackend } from '@/components/BackendSelector';
import { joinBackendPath } from '@/lib/backendUrls';
import type { OrchCanvasMeta, OrchNodeData, OrchNodeType, RemoteCursor } from './types';
import { ORCH_NODE_CONFIGS } from './types';

const API_BASE = '/api/v1/orchestration';

export function useOrchCanvas(canvasId: string | null) {
  const { config: backendConfig } = useBackend();
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [canvasMeta, setCanvasMeta] = useState<OrchCanvasMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [cursors, setCursors] = useState<RemoteCursor[]>([]);
  const [onlineUsers, setOnlineUsers] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const cursorThrottleRef = useRef<number>(0);

  const buildApiUrl = useCallback(
    (path: string) => joinBackendPath(backendConfig.api, path),
    [backendConfig.api],
  );
  const buildWsUrl = useCallback(
    (path: string) => joinBackendPath(backendConfig.ws, path),
    [backendConfig.ws],
  );

  const loadCanvas = useCallback(async () => {
    if (!canvasId) return;
    setLoading(true);
    try {
      const res = await fetch(buildApiUrl(`${API_BASE}/${canvasId}`));
      if (!res.ok) return;
      const data = await res.json();
      setCanvasMeta(data);
      const rfNodes: Node[] = (data.nodes || []).map((n: Record<string, unknown>) => ({
        id: n.id as string,
        type: 'orchestrationNode',
        position: n.position as { x: number; y: number },
        data: {
          ...(n.data as Record<string, unknown>),
          label: n.label as string,
          orchType: ((n.data as Record<string, unknown>)?.orch_type ||
            'agent_task') as OrchNodeType,
          description: (n.data as Record<string, unknown>)?.description || '',
          assignedAgent: (n.data as Record<string, unknown>)?.assigned_agent || '',
          agentType: (n.data as Record<string, unknown>)?.agent_type || '',
          capabilities: (n.data as Record<string, unknown>)?.capabilities || [],
          status: (n.data as Record<string, unknown>)?.status || 'pending',
          sourceActionIds: (n.data as Record<string, unknown>)?.source_action_ids || [],
          stage: 'orchestration' as const,
          rfType: 'orchestrationNode' as const,
        },
      }));
      const rfEdges: Edge[] = (data.edges || []).map((e: Record<string, unknown>) => ({
        id: e.id as string,
        source: (e.source || e.source_id) as string,
        target: (e.target || e.target_id) as string,
        type: 'default',
        label: e.label as string,
        animated: !!e.animated,
      }));
      setNodes(rfNodes);
      setEdges(rfEdges);
    } finally {
      setLoading(false);
    }
  }, [buildApiUrl, canvasId, setEdges, setNodes]);

  useEffect(() => {
    loadCanvas();
  }, [loadCanvas]);

  useEffect(() => {
    if (!canvasId) return;
    const ws = new WebSocket(buildWsUrl(`/canvas/${canvasId}`));
    wsRef.current = ws;
    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case 'orchestration:cursor:move':
            setCursors((prev) => [
              ...prev.filter((c) => c.userId !== msg.user_id),
              { userId: msg.user_id, position: msg.position, color: '' },
            ]);
            break;
          case 'orchestration:presence:join':
          case 'orchestration:presence:leave':
            setOnlineUsers(msg.users || []);
            break;
          case 'canvas:node:create':
          case 'canvas:node:update':
          case 'canvas:node:delete':
          case 'canvas:edge:create':
          case 'canvas:edge:delete':
            loadCanvas();
            break;
        }
      } catch {
        /* ignore */
      }
    };
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'orchestration:presence:join' }));
    };
    return () => {
      ws.send(JSON.stringify({ type: 'orchestration:presence:leave' }));
      ws.close();
      wsRef.current = null;
    };
  }, [buildWsUrl, canvasId, loadCanvas]);

  const sendCursorMove = useCallback((position: { x: number; y: number }) => {
    const now = Date.now();
    if (now - cursorThrottleRef.current < 50) return;
    cursorThrottleRef.current = now;
    wsRef.current?.send(JSON.stringify({ type: 'orchestration:cursor:move', position }));
  }, []);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => addEdge({ ...connection, type: 'default' }, eds));
    },
    [setEdges],
  );

  const onDrop = useCallback(
    (
      event: React.DragEvent,
      reactFlowBounds: DOMRect,
      screenToFlowPosition: (pos: { x: number; y: number }) => { x: number; y: number },
    ) => {
      const orchType = event.dataTransfer.getData('application/orch-node-type') as OrchNodeType;
      if (!orchType) return;
      const position = screenToFlowPosition({
        x: event.clientX - reactFlowBounds.left,
        y: event.clientY - reactFlowBounds.top,
      });
      const config = ORCH_NODE_CONFIGS[orchType];
      setNodes((nds) => [
        ...nds,
        {
          id: `orch-${Date.now()}`,
          type: 'orchestrationNode',
          position,
          data: {
            orchType,
            label: config.label,
            description: '',
            assignedAgent: '',
            agentType: '',
            capabilities: [],
            status: 'pending',
            stage: 'orchestration' as const,
            rfType: 'orchestrationNode' as const,
          } satisfies OrchNodeData,
        },
      ]);
    },
    [setNodes],
  );

  const updateSelectedNode = useCallback(
    (updates: Partial<OrchNodeData>) => {
      if (!selectedNodeId) return;
      setNodes((nds) =>
        nds.map((n) => (n.id === selectedNodeId ? { ...n, data: { ...n.data, ...updates } } : n)),
      );
    },
    [selectedNodeId, setNodes],
  );

  const deleteSelectedNode = useCallback(() => {
    if (!selectedNodeId) return;
    setNodes((nds) => nds.filter((n) => n.id !== selectedNodeId));
    setEdges((eds) =>
      eds.filter((e) => e.source !== selectedNodeId && e.target !== selectedNodeId),
    );
    setSelectedNodeId(null);
  }, [selectedNodeId, setNodes, setEdges]);

  const saveCanvas = useCallback(async () => {
    if (!canvasId) return;
    await fetch(buildApiUrl(`${API_BASE}/${canvasId}`), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: canvasMeta?.name }),
    });
  }, [buildApiUrl, canvasId, canvasMeta]);

  const executePipeline = useCallback(async (): Promise<{
    pipelineId: string;
    workflowId?: string;
  } | null> => {
    if (!canvasId) return null;
    const pipelineId = canvasMeta?.metadata?.pipeline_id as string | undefined;
    if (!pipelineId) return null;

    // Mark all nodes as entering execution while the orchestration plan queues.
    setNodes((nds) =>
      nds.map((n) => ({ ...n, data: { ...n.data, workflowStatus: 'creating' as const } })),
    );

    try {
      const executionRes = await fetch(
        buildApiUrl(`/api/v1/canvas/pipeline/${pipelineId}/execute`),
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ dry_run: false, enable_receipts: true }),
        },
      );

      if (executionRes.ok) {
        const executionData = await executionRes.json();
        setNodes((nds) =>
          nds.map((n) => ({ ...n, data: { ...n.data, workflowStatus: 'started' as const } })),
        );
        return { pipelineId: (executionData.pipeline_id as string | undefined) || pipelineId };
      } else {
        setNodes((nds) =>
          nds.map((n) => ({ ...n, data: { ...n.data, workflowStatus: 'failed' as const } })),
        );
        return null;
      }
    } catch {
      setNodes((nds) =>
        nds.map((n) => ({ ...n, data: { ...n.data, workflowStatus: 'failed' as const } })),
      );
      return null;
    }
  }, [buildApiUrl, canvasId, canvasMeta, setNodes]);

  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const selectedNodeData = selectedNode?.data as OrchNodeData | undefined;

  return {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    onDrop,
    selectedNodeId,
    setSelectedNodeId,
    selectedNodeData: selectedNodeData || null,
    updateSelectedNode,
    deleteSelectedNode,
    canvasMeta,
    loading,
    saveCanvas,
    executePipeline,
    cursors,
    onlineUsers,
    sendCursorMove,
  };
}

export default useOrchCanvas;
