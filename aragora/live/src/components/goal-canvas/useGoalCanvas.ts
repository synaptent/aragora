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
import type { GoalCanvasMeta, GoalNodeData, GoalNodeType, RemoteCursor } from './types';
import { GOAL_NODE_CONFIGS } from './types';

const API_BASE = '/api/v1/goals';

/**
 * Core state management hook for the Goal Canvas.
 */
export function useGoalCanvas(canvasId: string | null) {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [canvasMeta, setCanvasMeta] = useState<GoalCanvasMeta | null>(null);
  const [loading, setLoading] = useState(false);
  const [cursors, setCursors] = useState<RemoteCursor[]>([]);
  const [onlineUsers, setOnlineUsers] = useState<string[]>([]);
  const wsRef = useRef<WebSocket | null>(null);
  const cursorThrottleRef = useRef<number>(0);

  // ── Load canvas ──────────────────────────────────────────────
  const loadCanvas = useCallback(async () => {
    if (!canvasId) return;
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/${canvasId}`);
      if (!res.ok) return;
      const data = await res.json();
      setCanvasMeta(data);

      const rfNodes: Node[] = (data.nodes || []).map((n: Record<string, unknown>) => ({
        id: n.id as string,
        type: 'goalNode',
        position: n.position as { x: number; y: number },
        data: {
          ...(n.data as Record<string, unknown>),
          label: n.label as string,
          goalType: ((n.data as Record<string, unknown>)?.goal_type || 'goal') as GoalNodeType,
          description: (n.data as Record<string, unknown>)?.description || '',
          priority: (n.data as Record<string, unknown>)?.priority || 'medium',
          measurable: (n.data as Record<string, unknown>)?.measurable || '',
          confidence: (n.data as Record<string, unknown>)?.confidence || 0.5,
          tags: (n.data as Record<string, unknown>)?.tags || [],
          sourceIdeaIds: (n.data as Record<string, unknown>)?.source_idea_ids || [],
          stage: 'goals' as const,
          rfType: 'goalNode' as const,
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
  }, [canvasId, setNodes, setEdges]);

  useEffect(() => {
    loadCanvas();
  }, [loadCanvas]);

  // ── WebSocket ────────────────────────────────────────────────
  useEffect(() => {
    if (!canvasId) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/canvas/${canvasId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
          case 'goals:cursor:move':
            setCursors((prev) => {
              const filtered = prev.filter((c) => c.userId !== msg.user_id);
              return [...filtered, { userId: msg.user_id, position: msg.position, color: '' }];
            });
            break;
          case 'goals:presence:join':
          case 'goals:presence:leave':
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
        // ignore parse errors
      }
    };

    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'goals:presence:join' }));
    };

    return () => {
      ws.send(JSON.stringify({ type: 'goals:presence:leave' }));
      ws.close();
      wsRef.current = null;
    };
  }, [canvasId, loadCanvas]);

  // ── Cursor broadcasting ──────────────────────────────────────
  const sendCursorMove = useCallback((position: { x: number; y: number }) => {
    const now = Date.now();
    if (now - cursorThrottleRef.current < 50) return;
    cursorThrottleRef.current = now;

    wsRef.current?.send(JSON.stringify({ type: 'goals:cursor:move', position }));
  }, []);

  // ── Connection handler ───────────────────────────────────────
  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((eds) => addEdge({ ...connection, type: 'default' }, eds));
    },
    [setEdges],
  );

  // ── Drop handler ─────────────────────────────────────────────
  const onDrop = useCallback(
    (
      event: React.DragEvent,
      reactFlowBounds: DOMRect,
      screenToFlowPosition: (pos: { x: number; y: number }) => { x: number; y: number },
    ) => {
      const goalType = event.dataTransfer.getData('application/goal-node-type') as GoalNodeType;
      if (!goalType) return;

      const position = screenToFlowPosition({
        x: event.clientX - reactFlowBounds.left,
        y: event.clientY - reactFlowBounds.top,
      });

      const config = GOAL_NODE_CONFIGS[goalType];
      const newNode: Node = {
        id: `goal-${Date.now()}`,
        type: 'goalNode',
        position,
        data: {
          goalType,
          label: config.label,
          description: '',
          priority: 'medium',
          measurable: '',
          confidence: 0.5,
          tags: [],
          stage: 'goals' as const,
          rfType: 'goalNode' as const,
        } satisfies GoalNodeData,
      };

      setNodes((nds) => [...nds, newNode]);
    },
    [setNodes],
  );

  // ── Node property updates ────────────────────────────────────
  const updateSelectedNode = useCallback(
    (updates: Partial<GoalNodeData>) => {
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

  // ── Save ─────────────────────────────────────────────────────
  const saveCanvas = useCallback(async () => {
    if (!canvasId) return;
    await fetch(`${API_BASE}/${canvasId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: canvasMeta?.name }),
    });
  }, [canvasId, canvasMeta]);

  // ── Selected node data ───────────────────────────────────────
  const selectedNode = nodes.find((n) => n.id === selectedNodeId);
  const selectedNodeData = selectedNode?.data as GoalNodeData | undefined;

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
    cursors,
    onlineUsers,
    sendCursorMove,
  };
}

export default useGoalCanvas;
