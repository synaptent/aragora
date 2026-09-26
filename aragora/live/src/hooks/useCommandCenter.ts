'use client';

/**
 * useCommandCenter - Orchestrates the Command Center page.
 *
 * Manages brain dump -> auto-flow pipeline, node selection,
 * event streaming, and status tracking.
 */

import { useState, useCallback, useMemo } from 'react';
import { useUnifiedDAG, type DAGNodeData } from '@/hooks/useUnifiedDAG';
import { useEventStream } from '@/hooks/useEventStream';
import { apiFetch } from '@/lib/api';

export type InputMode = 'text' | 'list' | 'json';
export type AutoFlowPhase =
  'clustering' | 'goals' | 'tasks' | 'agents' | 'validating' | 'complete' | null;

export interface CommandStats {
  activeOps: number;
  budgetConsumed: number;
  agentsActive: number;
  totalNodes: number;
}

export function useCommandCenter() {
  const [graphId, setGraphId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [autoFlowPhase, setAutoFlowPhase] = useState<AutoFlowPhase>(null);
  const [inputMode, setInputMode] = useState<InputMode>('text');

  const dag = useUnifiedDAG(graphId);
  const eventStream = useEventStream(!!graphId);

  // Get selected node data
  const selectedNode = useMemo(() => {
    if (!selectedNodeId) return null;
    const node = dag.nodes.find((n) => n.id === selectedNodeId);
    if (!node) return null;
    return { id: node.id, ...(node.data as DAGNodeData) };
  }, [selectedNodeId, dag.nodes]);

  // Compute stats
  const stats: CommandStats = useMemo(
    () => ({
      activeOps: dag.operationLoading ? 1 : 0,
      budgetConsumed: 0, // Will be enriched by event stream data
      agentsActive: dag.nodes.filter(
        (n) =>
          (n.data as DAGNodeData).stage === 'orchestration' &&
          (n.data as DAGNodeData).status === 'running',
      ).length,
      totalNodes: dag.nodes.length,
    }),
    [dag.nodes, dag.operationLoading],
  );

  // Create a new graph and run auto-flow
  const submitBrainDump = useCallback(async (text: string, mode: InputMode) => {
    try {
      // Parse ideas from input
      let ideas: string[];
      if (mode === 'json') {
        try {
          const parsed = JSON.parse(text);
          ideas = Array.isArray(parsed) ? parsed.map(String) : [text];
        } catch {
          ideas = [text];
        }
      } else if (mode === 'list') {
        ideas = text
          .split('\n')
          .map((l) => l.replace(/^[\s\-*\u2022\d.]+/, '').trim())
          .filter(Boolean);
      } else {
        ideas = text
          .split('\n')
          .map((l) => l.trim())
          .filter(Boolean);
        if (ideas.length === 1) {
          // Single block of text - split by sentences for better clustering
          ideas = text
            .split(/[.!?]+/)
            .map((s) => s.trim())
            .filter((s) => s.length > 10);
          if (ideas.length === 0) ideas = [text];
        }
      }

      // Create a new DAG graph
      setAutoFlowPhase('clustering');
      const result = await apiFetch<{ data: { graph_id: string }; graph_id?: string }>(
        '/api/v1/pipeline/dag',
        {
          method: 'POST',
          body: JSON.stringify({ title: ideas[0]?.slice(0, 50) || 'Command Center', ideas }),
        },
      );

      const newGraphId = result.data?.graph_id || result.graph_id;
      if (newGraphId) {
        setGraphId(newGraphId);

        // Run auto-flow with phased animation
        setAutoFlowPhase('goals');
        await new Promise<void>((r) => setTimeout(r, 500));
        setAutoFlowPhase('tasks');
        await new Promise<void>((r) => setTimeout(r, 500));
        setAutoFlowPhase('agents');
        await new Promise<void>((r) => setTimeout(r, 500));
        setAutoFlowPhase('complete');
      }
    } catch (err) {
      console.error('Brain dump failed:', err);
      setAutoFlowPhase(null);
    }
  }, []);

  // Run auto-flow on existing graph
  const runAutoFlow = useCallback(
    async (ideas: string[]) => {
      if (!graphId) return;
      setAutoFlowPhase('clustering');
      const result = await dag.autoFlow(ideas);
      if (result?.success) {
        setAutoFlowPhase('complete');
      } else {
        setAutoFlowPhase(null);
      }
    },
    [graphId, dag],
  );

  // Node action dispatcher
  const handleNodeAction = useCallback(
    async (action: string, nodeId: string) => {
      switch (action) {
        case 'debate':
          return dag.debateNode(nodeId);
        case 'decompose':
          return dag.decomposeNode(nodeId);
        case 'prioritize':
          return dag.prioritizeChildren(nodeId);
        case 'assign':
          return dag.assignAgents(nodeId);
        case 'execute':
          return dag.executeNode(nodeId);
        case 'precedents':
          return dag.findPrecedents(nodeId);
        case 'delete':
          dag.deleteNode(nodeId);
          setSelectedNodeId(null);
          return;
      }
    },
    [dag],
  );

  // Filter events for selected node
  const nodeEvents = useMemo(() => {
    if (!selectedNodeId) return [];
    return eventStream.events.filter((e) => e.nodeId === selectedNodeId);
  }, [selectedNodeId, eventStream.events]);

  return {
    // Graph state
    graphId,
    dag,
    selectedNode,
    selectedNodeId,
    setSelectedNodeId,

    // Input
    inputMode,
    setInputMode,
    submitBrainDump,
    runAutoFlow,

    // Auto-flow
    autoFlowPhase,

    // Events
    events: eventStream.events,
    nodeEvents,
    eventStreamStatus: eventStream.status,

    // Stats
    stats,

    // Actions
    handleNodeAction,
  };
}
