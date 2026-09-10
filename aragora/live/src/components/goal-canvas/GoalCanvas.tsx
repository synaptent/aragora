'use client';

import { useCallback, useRef, useState } from 'react';
import { ReactFlow, Background, Controls, MiniMap, type NodeTypes } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { GoalNode } from './GoalNode';
import { GoalPalette } from './GoalPalette';
import { GoalPropertyEditor } from './GoalPropertyEditor';
import { useGoalCanvas } from './useGoalCanvas';
import { type GoalNodeType } from './types';
import { apiPost } from '../../lib/api';

const nodeTypes: NodeTypes = { goalNode: GoalNode as unknown as NodeTypes[string] };

interface GoalCanvasProps {
  canvasId: string;
  /** Pipeline ID for stage advancement */
  pipelineId?: string;
  /** Callback when actions are generated */
  onActionsGenerated?: (pipelineId: string) => void;
}

/**
 * Main Goal Canvas component with React Flow, palette, and property editor.
 */
export function GoalCanvas({ canvasId, pipelineId, onActionsGenerated }: GoalCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [isGeneratingActions, setIsGeneratingActions] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
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
    cursors: _cursors,
    onlineUsers: _onlineUsers,
  } = useGoalCanvas(canvasId);

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

  // -- Generate Actions from goals ----------------------------------------
  const handleGenerateActions = useCallback(async () => {
    if (!pipelineId) {
      setActionError('No pipeline ID available');
      return;
    }
    setIsGeneratingActions(true);
    setActionError(null);
    try {
      const result = await apiPost<{
        pipeline_id: string;
        advanced_to: string;
        stage_status: Record<string, string>;
      }>('/api/v1/canvas/pipeline/advance', { pipeline_id: pipelineId, target_stage: 'actions' });

      if (onActionsGenerated) {
        onActionsGenerated(result.pipeline_id);
      }
    } catch (err) {
      setActionError(err instanceof Error ? err.message : 'Failed to generate actions');
    } finally {
      setIsGeneratingActions(false);
    }
  }, [pipelineId, onActionsGenerated]);

  // MiniMap color mapping
  const miniMapNodeColor = useCallback((node: { data?: Record<string, unknown> }) => {
    const goalType = (node.data?.goalType || 'goal') as GoalNodeType;
    const colorMap: Record<GoalNodeType, string> = {
      goal: '#34d399',
      principle: '#059669',
      strategy: '#14b8a6',
      milestone: '#6ee7b7',
      metric: '#2dd4bf',
      risk: '#ef4444',
    };
    return colorMap[goalType] || '#34d399';
  }, []);

  return (
    <div className="flex h-full">
      {/* Left: Palette */}
      <GoalPalette />

      {/* Center: Canvas */}
      <div
        ref={reactFlowWrapper}
        className="flex-1 relative"
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        {/* Toolbar */}
        <div className="absolute top-2 left-2 z-20 flex gap-2 items-center">
          <button
            onClick={saveCanvas}
            className="px-3 py-1 text-xs font-theme-data rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] hover:border-[var(--acid-green)] transition-colors"
          >
            Save
          </button>

          {/* Generate Actions CTA */}
          <button
            onClick={handleGenerateActions}
            disabled={isGeneratingActions || nodes.length === 0 || !pipelineId}
            className="px-4 py-1.5 text-xs font-theme-data font-bold rounded bg-amber-600 text-white hover:bg-amber-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
          >
            {isGeneratingActions ? (
              <>
                <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                Generating...
              </>
            ) : (
              <>Generate Actions &rarr;</>
            )}
          </button>

          {actionError && (
            <span className="text-xs font-theme-data text-red-400 truncate max-w-xs">
              {actionError}
            </span>
          )}
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

      {/* Right: Property Editor */}
      <GoalPropertyEditor
        data={selectedNodeData}
        onChange={updateSelectedNode}
        onDelete={deleteSelectedNode}
      />
    </div>
  );
}

export default GoalCanvas;
