'use client';

import { useCallback, useRef, useState } from 'react';
import { ReactFlow, Background, Controls, MiniMap, type NodeTypes } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { OrchNode } from './OrchNode';
import { OrchPalette } from './OrchPalette';
import { OrchPropertyEditor } from './OrchPropertyEditor';
import { useOrchCanvas } from './useOrchCanvas';
import { type OrchNodeType } from './types';
import { usePipelineWebSocket } from '@/hooks/usePipelineWebSocket';
import { ExecutionProgressOverlay } from '../pipeline-canvas/ExecutionProgressOverlay';

const nodeTypes: NodeTypes = { orchestrationNode: OrchNode as unknown as NodeTypes[string] };

interface OrchestrationCanvasProps {
  canvasId: string;
}

export function OrchestrationCanvas({ canvasId }: OrchestrationCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    onDrop,
    selectedNodeId: _selectedNodeId,
    setSelectedNodeId,
    selectedNodeData,
    updateSelectedNode,
    deleteSelectedNode,
    saveCanvas,
    executePipeline,
  } = useOrchCanvas(canvasId);

  const [executing, setExecuting] = useState(false);
  const [pipelineRunId, setPipelineRunId] = useState<string | null>(null);
  const [executeStatus, setExecuteStatus] = useState<'idle' | 'success' | 'failed'>('idle');
  const [currentStage, setCurrentStage] = useState<string | undefined>();
  const [completedSubtasks, setCompletedSubtasks] = useState(0);
  const [totalSubtasks, setTotalSubtasks] = useState(0);

  const { completedStages, streamedNodes } = usePipelineWebSocket({
    pipelineId: pipelineRunId ?? undefined,
    enabled: executing && !!pipelineRunId,
    onStageStarted: (e) => setCurrentStage(e.stage),
    onStepProgress: (e) => {
      if (e.completed != null) setCompletedSubtasks(e.completed);
      if (e.total != null) setTotalSubtasks(e.total);
    },
    onCompleted: () => {
      setExecuting(false);
      setExecuteStatus('success');
    },
    onFailed: () => {
      setExecuting(false);
      setExecuteStatus('failed');
    },
  });

  const handleExecute = useCallback(async () => {
    setExecuting(true);
    setExecuteStatus('idle');
    setCurrentStage(undefined);
    setCompletedSubtasks(0);
    setTotalSubtasks(0);
    try {
      const result = await executePipeline();
      if (result?.pipelineId) {
        setPipelineRunId(result.pipelineId);
      }
    } catch {
      setExecuting(false);
      setExecuteStatus('failed');
    }
  }, [executePipeline]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: { id: string }) => {
      setSelectedNodeId(node.id);
    },
    [setSelectedNodeId],
  );
  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
  }, [setSelectedNodeId]);
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);
  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      const bounds = reactFlowWrapper.current?.getBoundingClientRect();
      if (!bounds) return;
      onDrop(e, bounds, (pos) => pos);
    },
    [onDrop],
  );

  const miniMapNodeColor = useCallback((node: { data?: Record<string, unknown> }) => {
    const orchType = (node.data?.orchType || node.data?.orch_type || 'agent_task') as OrchNodeType;
    const colorMap: Record<OrchNodeType, string> = {
      agent_task: '#f472b6',
      debate: '#db2777',
      human_gate: '#f472b6',
      parallel_fan: '#f9a8d4',
      merge: '#f9a8d4',
      verification: '#ec4899',
    };
    return colorMap[orchType] || '#f472b6';
  }, []);

  return (
    <div className="flex h-full">
      <OrchPalette />
      <div
        ref={reactFlowWrapper}
        className="flex-1 relative"
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <div className="absolute top-2 left-2 z-20 flex gap-2">
          <button
            onClick={saveCanvas}
            className="px-3 py-1 text-xs font-theme-data rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] hover:border-pink-500 transition-colors"
          >
            Save
          </button>
        </div>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          nodeTypes={nodeTypes}
          snapToGrid
          snapGrid={[16, 16]}
          fitView
          className="bg-[var(--bg)]"
        >
          <Background gap={16} size={1} />
          <Controls className="!bg-[var(--surface)] !border-[var(--border)]" />
          <MiniMap
            nodeColor={miniMapNodeColor}
            maskColor="rgba(0,0,0,0.6)"
            className="!bg-[var(--surface)] !border-[var(--border)]"
          />
        </ReactFlow>
        <ExecutionProgressOverlay
          executing={executing}
          currentStage={currentStage}
          completedStages={completedStages}
          streamedNodeCount={streamedNodes.length}
          completedSubtasks={completedSubtasks}
          totalSubtasks={totalSubtasks}
          executeStatus={executeStatus}
        />
      </div>
      <OrchPropertyEditor
        data={selectedNodeData}
        onChange={updateSelectedNode}
        onExecute={handleExecute}
        onDelete={deleteSelectedNode}
      />
    </div>
  );
}

export default OrchestrationCanvas;
