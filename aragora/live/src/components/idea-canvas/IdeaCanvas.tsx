'use client';

import { useCallback, useRef, useState } from 'react';
import { ReactFlow, Background, Controls, MiniMap, type NodeTypes } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { IdeaNode } from './IdeaNode';
import { IdeaPalette } from './IdeaPalette';
import { IdeaPropertyEditor } from './IdeaPropertyEditor';
import { CollaborationOverlay } from './CollaborationOverlay';
import { useIdeaCanvas } from './useIdeaCanvas';
import { type IdeaNodeType } from './types';
import { apiPost } from '../../lib/api';

const nodeTypes: NodeTypes = { ideaNode: IdeaNode as unknown as NodeTypes[string] };

interface IdeaCanvasProps {
  canvasId: string;
  /** Callback when goals are generated, so the parent can navigate to goals stage */
  onGoalsGenerated?: (pipelineId: string) => void;
}

/**
 * Main Idea Canvas component with React Flow, palette, and property editor.
 */
export function IdeaCanvas({ canvasId, onGoalsGenerated }: IdeaCanvasProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const [ideasText, setIdeasText] = useState('');
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isGeneratingGoals, setIsGeneratingGoals] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    onDrop,
    selectedNodeId,
    setSelectedNodeId,
    selectedNodeData,
    updateSelectedNode,
    deleteSelectedNode,
    saveCanvas,
    cursors,
    onlineUsers,
    sendCursorMove: _sendCursorMove,
  } = useIdeaCanvas(canvasId);

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
      // screenToFlowPosition is provided by ReactFlow via the hook
      // For drop we use a simple offset calculation
      onDrop(e, bounds, (pos) => pos);
    },
    [onDrop],
  );

  const handlePromote = useCallback(async () => {
    if (!selectedNodeId) return;
    try {
      const res = await fetch(`/api/v1/ideas/${canvasId}/promote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_ids: [selectedNodeId] }),
      });
      if (res.ok) {
        updateSelectedNode({ promotedToGoalId: 'pending' });
      }
    } catch {
      // ignore
    }
  }, [canvasId, selectedNodeId, updateSelectedNode]);

  // -- Submit natural-language ideas ------------------------------------
  const handleSubmitIdeas = useCallback(async () => {
    if (!ideasText.trim()) return;
    setIsSubmitting(true);
    setSubmitError(null);
    try {
      const result = await apiPost<{
        pipeline_id: string;
        result?: { ideas?: { nodes?: Array<Record<string, unknown>> } };
      }>('/api/v1/canvas/pipeline/from-ideas', {
        ideas: ideasText
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean),
        auto_advance: false,
      });
      setIdeasText('');
      // If ideas returned, we could trigger a reload; for now just notify
      if (result.pipeline_id) {
        setSubmitError(null);
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to submit ideas');
    } finally {
      setIsSubmitting(false);
    }
  }, [ideasText]);

  // -- Generate goals from current ideas --------------------------------
  const handleGenerateGoals = useCallback(async () => {
    setIsGeneratingGoals(true);
    setSubmitError(null);
    try {
      const ideaNodes = nodes.map((n) => ({
        id: n.id,
        type: n.type,
        position: n.position,
        data: n.data,
      }));

      const result = await apiPost<{
        pipeline_id?: string;
        goals_count?: number;
        goals?: Array<Record<string, unknown>>;
      }>('/api/v1/canvas/pipeline/extract-goals', {
        ideas_canvas_id: canvasId,
        ideas_canvas_data: {
          nodes: ideaNodes,
          edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target })),
        },
      });

      if (onGoalsGenerated && result.goals_count && result.goals_count > 0) {
        onGoalsGenerated(canvasId);
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : 'Failed to generate goals');
    } finally {
      setIsGeneratingGoals(false);
    }
  }, [nodes, edges, canvasId, onGoalsGenerated]);

  // MiniMap color mapping
  const miniMapNodeColor = useCallback((node: { data?: Record<string, unknown> }) => {
    const ideaType = (node.data?.ideaType || 'concept') as IdeaNodeType;
    // Extract color name from tailwind class (e.g., 'bg-indigo-500/20' -> '#818cf8')
    const colorMap: Record<IdeaNodeType, string> = {
      concept: '#818cf8',
      observation: '#34d399',
      question: '#a78bfa',
      hypothesis: '#c084fc',
      insight: '#8b5cf6',
      evidence: '#7c3aed',
      cluster: '#6366f1',
      assumption: '#c4b5fd',
      constraint: '#ddd6fe',
    };
    return colorMap[ideaType] || '#818cf8';
  }, []);

  return (
    <div className="flex h-full">
      {/* Left: Palette */}
      <IdeaPalette />

      {/* Center: Canvas */}
      <div
        ref={reactFlowWrapper}
        className="flex-1 relative"
        onDragOver={handleDragOver}
        onDrop={handleDrop}
      >
        {/* Top bar: NL input + toolbar */}
        <div className="absolute top-2 left-2 right-2 z-20 flex flex-col gap-2">
          {/* Natural-language idea input */}
          <div className="flex gap-2 items-start">
            <textarea
              value={ideasText}
              onChange={(e) => setIdeasText(e.target.value)}
              placeholder="Paste your ideas here... (one per line)"
              rows={2}
              className="flex-1 px-3 py-2 text-sm font-theme-data rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] placeholder:text-[var(--text-muted)] resize-none focus:outline-none focus:border-[var(--acid-green)] transition-colors"
            />
            <button
              onClick={handleSubmitIdeas}
              disabled={isSubmitting || !ideasText.trim()}
              className="px-4 py-2 text-xs font-theme-data font-bold rounded bg-indigo-600 text-white hover:bg-indigo-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
            >
              {isSubmitting ? 'Adding...' : 'Add Ideas'}
            </button>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2 items-center">
            <button
              onClick={saveCanvas}
              className="px-3 py-1 text-xs font-theme-data rounded bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] hover:border-[var(--acid-green)] transition-colors"
            >
              Save
            </button>

            {/* Generate Goals CTA */}
            <button
              onClick={handleGenerateGoals}
              disabled={isGeneratingGoals || nodes.length === 0}
              className="px-4 py-1.5 text-xs font-theme-data font-bold rounded bg-emerald-600 text-white hover:bg-emerald-500 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              {isGeneratingGoals ? (
                <>
                  <span className="inline-block w-3 h-3 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Generating...
                </>
              ) : (
                <>Generate Goals &rarr;</>
              )}
            </button>

            {submitError && (
              <span className="text-xs font-theme-data text-red-400 truncate max-w-xs">
                {submitError}
              </span>
            )}
          </div>
        </div>

        <CollaborationOverlay cursors={cursors} onlineUsers={onlineUsers} />

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
      <IdeaPropertyEditor
        data={selectedNodeData}
        onChange={updateSelectedNode}
        onPromote={handlePromote}
        onDelete={deleteSelectedNode}
      />
    </div>
  );
}

export default IdeaCanvas;
