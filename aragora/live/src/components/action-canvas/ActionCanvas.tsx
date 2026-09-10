'use client';

import { useCallback, useRef, useState } from 'react';
import { ReactFlow, Background, Controls, MiniMap, type NodeTypes } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { ActionNode } from './ActionNode';
import { ActionPalette } from './ActionPalette';
import { ActionPropertyEditor } from './ActionPropertyEditor';
import { useActionCanvas } from './useActionCanvas';
import { type ActionNodeType } from './types';

const nodeTypes: NodeTypes = { actionNode: ActionNode as unknown as NodeTypes[string] };

interface ActionCanvasProps {
  canvasId: string;
}

export function ActionCanvas({ canvasId }: ActionCanvasProps) {
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
    advanceToOrchestration,
  } = useActionCanvas(canvasId);
  const [advancing, setAdvancing] = useState(false);

  const handleAdvance = useCallback(async () => {
    setAdvancing(true);
    try {
      await advanceToOrchestration();
    } finally {
      setAdvancing(false);
    }
  }, [advanceToOrchestration]);

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
    const actionType = (node.data?.actionType || node.data?.stepType || 'task') as ActionNodeType;
    const colorMap: Record<ActionNodeType, string> = {
      task: '#fbbf24',
      epic: '#d97706',
      checkpoint: '#fbbf24',
      deliverable: '#f59e0b',
      dependency: '#fcd34d',
    };
    return colorMap[actionType] || '#fbbf24';
  }, []);

  return (
    <div className="flex h-full">
      <ActionPalette />
      <div
        ref={reactFlowWrapper}
        className="flex-1 relative"
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        <div className="absolute top-2 left-2 z-20 flex gap-2">
          <button
            onClick={saveCanvas}
            className="px-3 py-1 text-xs font-theme-data rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] hover:border-amber-500 transition-colors"
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
      </div>
      <ActionPropertyEditor
        data={selectedNodeData}
        onChange={updateSelectedNode}
        onAdvance={handleAdvance}
        onDelete={deleteSelectedNode}
        advancing={advancing}
      />
    </div>
  );
}

export default ActionCanvas;
