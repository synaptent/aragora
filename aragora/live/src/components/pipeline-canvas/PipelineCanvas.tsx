'use client';

import { useCallback, useState, useMemo, useEffect, useRef } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  useReactFlow,
  ReactFlowProvider,
  type NodeTypes,
  type Node,
  type Edge,
  Panel,
  BackgroundVariant,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { IdeaNode, GoalNode, ActionNode, OrchestrationNode } from './nodes';
import { StageNavigator } from './StageNavigator';
import { PipelinePalette } from './PipelinePalette';
import { PipelineToolbar } from './PipelineToolbar';
import { PipelinePropertyEditor } from './editors/PipelinePropertyEditor';
import { ProvenanceNodeDetailPanel } from './ProvenanceNodeDetailPanel';
import { TemplateSelector } from './TemplateSelector';
import { ProgressIndicator } from './ProgressIndicator';
import {
  PIPELINE_STAGE_CONFIG,
  type PipelineStageType,
  type PipelineResultResponse,
  type ProvenanceLink,
} from './types';
import { usePipelineCanvas } from '../../hooks/usePipelineCanvas';
import { usePipelineWebSocket } from '../../hooks/usePipelineWebSocket';
import { StageTransitionGate } from '../pipeline/StageTransitionGate';
import { StageSidebar } from './StageSidebar';
import { useBackend } from '@/components/BackendSelector';
import { joinBackendPath } from '@/lib/backendUrls';

// =============================================================================
// Constants
// =============================================================================

const nodeTypes: NodeTypes = {
  ideaNode: IdeaNode,
  goalNode: GoalNode,
  actionNode: ActionNode,
  orchestrationNode: OrchestrationNode,
};

type ViewMode = PipelineStageType | 'all';

const STAGE_KEYS: Record<string, ViewMode> = {
  '1': 'ideas',
  '2': 'goals',
  '3': 'actions',
  '4': 'orchestration',
  a: 'all',
};

const ALL_STAGES: PipelineStageType[] = ['ideas', 'goals', 'actions', 'orchestration'];

const STAGE_OFFSET_X: Record<string, number> = {
  ideas: 0,
  goals: 600,
  actions: 1200,
  orchestration: 1800,
};

const PROVENANCE_STAGES: PipelineStageType[] = [
  'ideas',
  'principles',
  'goals',
  'actions',
  'orchestration',
];

function buildTransitionQuestions(
  provenance: ProvenanceLink[],
  stageNodes: Record<PipelineStageType, Node[]>,
): string[] {
  const prompts: string[] = [];

  for (const link of provenance) {
    const sourceNode = (stageNodes[link.source_stage] ?? []).find(
      (node) => node.id === link.source_node_id,
    );
    const data = (sourceNode?.data as Record<string, unknown> | undefined) ?? {};
    const label = (data.label as string) || sourceNode?.id || link.source_node_id;
    const ideaType = String(data.ideaType ?? data.idea_type ?? '');
    const description = String(
      data.fullContent ?? data.full_content ?? data.description ?? '',
    ).trim();

    if (ideaType === 'question' || label.includes('?')) {
      prompts.push(`Answer the open question "${label}" before approval.`);
      continue;
    }
    if (ideaType === 'constraint') {
      prompts.push(`Confirm "${label}" remains a hard constraint in goals.`);
      continue;
    }
    if (ideaType === 'assumption') {
      prompts.push(`Validate the assumption "${label}" before promoting it.`);
      continue;
    }
    if (!description || description === label) {
      prompts.push(`Define the success condition for "${label}".`);
    }
  }

  return Array.from(new Set(prompts)).slice(0, 3);
}

// =============================================================================
// Props
// =============================================================================

interface PipelineCanvasProps {
  pipelineId?: string;
  initialData?: PipelineResultResponse;
  initialStage?: PipelineStageType;
  onStageAdvance?: (pipelineId: string, stage: PipelineStageType) => void;
  onTransitionApprove?: (pipelineId: string, transitionId: string) => void;
  onTransitionReject?: (pipelineId: string, transitionId: string) => void;
  readOnly?: boolean;
}

// =============================================================================
// Inner component (inside ReactFlowProvider)
// =============================================================================

function PipelineCanvasInner({
  pipelineId,
  initialData,
  initialStage,
  onStageAdvance,
  onTransitionApprove,
  onTransitionReject,
  readOnly = false,
}: PipelineCanvasProps) {
  const { config: backendConfig } = useBackend();

  // -- Hook: central state management -----------------------------------------
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onConnect,
    selectedNodeId,
    setSelectedNodeId,
    selectedNodeData,
    updateSelectedNode,
    deleteSelectedNode,
    addNode,
    activeStage,
    setActiveStage,
    stageStatus,
    stageNodes,
    stageEdges,
    savePipeline,
    aiGenerate,
    runPipeline,
    clearStage,
    approveTransition,
    rejectTransition,
    loading,
    error: _hookError,
    onDragOver: _hookDragOver,
  } = usePipelineCanvas(pipelineId ?? null, initialData);

  const { fitView, screenToFlowPosition } = useReactFlow();
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  // -- View mode: adds 'all' view on top of the hook's active stage -----------
  const [viewMode, setViewMode] = useState<ViewMode>(initialStage || 'all');
  const [showProvenance, setShowProvenance] = useState(false);
  const [showTemplates, setShowTemplates] = useState(!pipelineId && !initialData);

  // -- Stage sidebar (stranded features) -------------------------------------
  const [showStageSidebar, setShowStageSidebar] = useState(false);

  // -- Run pipeline state ----------------------------------------------------
  const [runInputText, setRunInputText] = useState('');
  const [activePipelineRunId, setActivePipelineRunId] = useState<string | null>(null);
  const [runNotification, setRunNotification] = useState<string | null>(null);

  // -- WebSocket: real-time pipeline progress --------------------------------
  const {
    completedStages,
    pendingTransitions: wsPendingTransitions,
    isComplete: pipelineComplete,
    isConnected,
  } = usePipelineWebSocket({
    pipelineId: activePipelineRunId ?? undefined,
    enabled: !!activePipelineRunId,
    onStageCompleted: (event) => {
      setRunNotification(`Stage "${event.stage}" completed`);
      setTimeout(() => setRunNotification(null), 3000);
    },
    onCompleted: () => {
      setRunNotification('Pipeline completed successfully');
      setActivePipelineRunId(null);
      setTimeout(() => setRunNotification(null), 5000);
    },
    onFailed: (error) => {
      setRunNotification(`Pipeline failed: ${error}`);
      setActivePipelineRunId(null);
      setTimeout(() => setRunNotification(null), 5000);
    },
  });

  // Sync initialStage into the hook's activeStage on mount
  useEffect(() => {
    if (initialStage) {
      setActiveStage(initialStage);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const isEditable = viewMode !== 'all' && !readOnly;

  // -- Stage switching --------------------------------------------------------
  const handleStageSelect = useCallback(
    (stage: PipelineStageType) => {
      setViewMode(stage);
      setActiveStage(stage);
      setSelectedNodeId(null);
      setShowProvenance(false);
    },
    [setActiveStage, setSelectedNodeId],
  );

  const handleViewAll = useCallback(() => {
    setViewMode('all');
    setSelectedNodeId(null);
    setShowProvenance(false);
  }, [setSelectedNodeId]);

  // -- Keyboard shortcuts: 1-4 for stages, A for all -------------------------
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      const view = STAGE_KEYS[e.key];
      if (view) {
        e.preventDefault();
        if (view === 'all') {
          handleViewAll();
        } else {
          handleStageSelect(view);
        }
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [handleStageSelect, handleViewAll]);

  // -- Combined "all stages" view from caches --------------------------------
  const allStagesData = useMemo(() => {
    if (viewMode !== 'all') return { nodes: [] as Node[], edges: [] as Edge[] };
    const allNodes: Node[] = [];
    const allEdges: Edge[] = [];
    for (const stage of ALL_STAGES) {
      const offsetX = STAGE_OFFSET_X[stage] || 0;
      for (const n of stageNodes[stage]) {
        allNodes.push({ ...n, position: { x: n.position.x + offsetX, y: n.position.y } });
      }
      allEdges.push(...stageEdges[stage]);
    }
    return { nodes: allNodes, edges: allEdges };
  }, [viewMode, stageNodes, stageEdges]);

  const displayNodes = viewMode === 'all' ? allStagesData.nodes : nodes;

  // -- Provenance data (from initialData) -------------------------------------
  const allProvenance: ProvenanceLink[] = useMemo(
    () => (initialData?.provenance ?? []) as ProvenanceLink[],
    [initialData],
  );

  // Build a node lookup from all display nodes for the provenance trail
  const nodeLookup = useMemo(() => {
    const lookup: Record<string, { label: string; stage: PipelineStageType }> = {};
    // Gather from all stages to build complete lookup
    for (const stage of PROVENANCE_STAGES) {
      for (const n of stageNodes[stage]) {
        const data = n.data as Record<string, unknown>;
        lookup[n.id] = { label: (data?.label as string) || n.id, stage };
      }
    }
    return lookup;
  }, [stageNodes]);

  // Provenance links relevant to the selected node
  const selectedProvenance = useMemo(() => {
    if (!selectedNodeId) return [];
    return allProvenance.filter(
      (p) => p.source_node_id === selectedNodeId || p.target_node_id === selectedNodeId,
    );
  }, [selectedNodeId, allProvenance]);

  // Compute the set of provenance-connected node IDs for highlighting
  const provenanceHighlightIds = useMemo(() => {
    if (!selectedNodeId) return new Set<string>();
    const ids = new Set<string>();
    // Walk the full chain (upstream and downstream)
    function walk(nodeId: string, visited: Set<string>) {
      if (visited.has(nodeId)) return;
      visited.add(nodeId);
      ids.add(nodeId);
      for (const link of allProvenance) {
        if (link.target_node_id === nodeId) walk(link.source_node_id, visited);
        if (link.source_node_id === nodeId) walk(link.target_node_id, visited);
      }
    }
    walk(selectedNodeId, new Set());
    return ids;
  }, [selectedNodeId, allProvenance]);

  // Cross-stage edge highlighting: modify edge styles when a node is selected
  const baseEdges = viewMode === 'all' ? allStagesData.edges : edges;
  const displayEdges = useMemo(() => {
    if (!selectedNodeId || provenanceHighlightIds.size === 0) return baseEdges;

    return baseEdges.map((edge) => {
      const sourceInChain = provenanceHighlightIds.has(edge.source);
      const targetInChain = provenanceHighlightIds.has(edge.target);
      const isCrossStage = edge.data?.provenance === true;

      if (sourceInChain && targetInChain) {
        // This edge connects two provenance-linked nodes: highlight it
        return {
          ...edge,
          animated: true,
          style: {
            ...edge.style,
            stroke: isCrossStage ? '#34d399' : '#818cf8',
            strokeWidth: 3,
            opacity: 1,
          },
        };
      }

      // Dim non-provenance edges when a node is selected
      return { ...edge, style: { ...edge.style, opacity: 0.25 } };
    });
  }, [baseEdges, selectedNodeId, provenanceHighlightIds]);

  // -- Fit view on stage switch -----------------------------------------------
  useEffect(() => {
    setTimeout(() => fitView({ padding: 0.2 }), 50);
  }, [viewMode, fitView]);

  // -- Node click -------------------------------------------------------------
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      setSelectedNodeId(node.id);
      if (readOnly || viewMode === 'all') {
        setShowProvenance(true);
      }
    },
    [setSelectedNodeId, readOnly, viewMode],
  );

  const onPaneClick = useCallback(() => {
    setSelectedNodeId(null);
    setShowProvenance(false);
  }, [setSelectedNodeId]);

  // -- DnD: zoom-aware drop coordinates ---------------------------------------
  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const raw = event.dataTransfer.getData('application/pipeline-node');
      if (!raw) return;

      let parsed: { stage: PipelineStageType; subtype: string };
      try {
        parsed = JSON.parse(raw);
      } catch {
        return;
      }

      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      addNode(parsed.stage, parsed.subtype, position);
    },
    [screenToFlowPosition, addNode],
  );

  // -- Toolbar handlers -------------------------------------------------------
  const handleAdvance = useCallback(
    (stage: PipelineStageType) => {
      if (pipelineId && onStageAdvance) {
        onStageAdvance(pipelineId, stage);
      }
    },
    [pipelineId, onStageAdvance],
  );

  const handleToolbarAdvance = useCallback(() => {
    const idx = ALL_STAGES.indexOf(activeStage);
    if (idx >= 0 && idx < ALL_STAGES.length - 1) {
      const next = ALL_STAGES[idx + 1];
      handleAdvance(next);
      handleStageSelect(next);
    }
  }, [activeStage, handleAdvance, handleStageSelect]);

  const handleAIGenerate = useCallback(() => {
    aiGenerate(activeStage);
  }, [aiGenerate, activeStage]);

  const handleClear = useCallback(() => {
    clearStage();
  }, [clearStage]);

  const handleSave = useCallback(() => {
    savePipeline();
  }, [savePipeline]);

  // -- Run Pipeline handler -------------------------------------------------
  const handleRunPipeline = useCallback(async () => {
    if (!runInputText.trim()) return;
    const newPipelineId = await runPipeline(runInputText.trim());
    if (newPipelineId) {
      setActivePipelineRunId(newPipelineId);
      setRunInputText('');
      setRunNotification(`Pipeline started: ${newPipelineId}`);
      setTimeout(() => setRunNotification(null), 3000);
    }
  }, [runInputText, runPipeline]);

  // -- Export Receipt handler --------------------------------------------------
  const handleExportReceipt = useCallback(async () => {
    if (!pipelineId) return;
    try {
      const response = await fetch(
        joinBackendPath(
          backendConfig.api,
          `/api/v1/canvas/pipeline/${encodeURIComponent(pipelineId)}/receipt`,
        ),
      );
      if (!response.ok) {
        console.error('Failed to fetch receipt:', response.status);
        return;
      }
      const receipt = await response.json();
      const blob = new Blob([JSON.stringify(receipt, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `receipt-${pipelineId}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      console.error('Export receipt failed:', err);
    }
  }, [backendConfig.api, pipelineId]);

  // -- Provenance navigation handler ------------------------------------------
  const handleProvenanceNavigate = useCallback(
    (nodeId: string, stage: PipelineStageType) => {
      setSelectedNodeId(nodeId);
      setViewMode(stage);
      setActiveStage(stage);
      setTimeout(() => fitView({ padding: 0.2 }), 50);
    },
    [setSelectedNodeId, setActiveStage, fitView],
  );

  // -- Template selection handlers --------------------------------------------
  const handleSelectTemplate = useCallback(
    async (templateName: string) => {
      try {
        const res = await fetch(
          joinBackendPath(backendConfig.api, '/api/v1/canvas/pipeline/from-template'),
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ template_name: templateName, auto_advance: false }),
          },
        );
        if (res.ok) {
          setShowTemplates(false);
          setRunNotification(`Pipeline created from "${templateName}" template`);
          setTimeout(() => setRunNotification(null), 3000);
        }
      } catch {
        // Template creation failed silently, user can retry
      }
    },
    [backendConfig.api],
  );

  const handleStartBlank = useCallback(() => {
    setShowTemplates(false);
  }, []);

  // -- Can advance: current stage has nodes and next stage exists -------------
  const canAdvance = useMemo(() => {
    const idx = ALL_STAGES.indexOf(activeStage);
    return idx >= 0 && idx < ALL_STAGES.length - 1 && nodes.length > 0;
  }, [activeStage, nodes.length]);

  // -- MiniMap color ----------------------------------------------------------
  const miniMapNodeColor = useCallback((node: { type?: string }) => {
    switch (node.type) {
      case 'ideaNode':
        return PIPELINE_STAGE_CONFIG.ideas.primary;
      case 'goalNode':
        return PIPELINE_STAGE_CONFIG.goals.primary;
      case 'actionNode':
        return PIPELINE_STAGE_CONFIG.actions.primary;
      case 'orchestrationNode':
        return PIPELINE_STAGE_CONFIG.orchestration.primary;
      default:
        return '#6b7280';
    }
  }, []);

  // -- Transition data ---------------------------------------------------------
  // Merge static transitions from initialData with live WebSocket transitions
  const pendingTransitions = useMemo(() => {
    const staticPending = (initialData?.transitions || []).filter((t) => t.status === 'pending');
    if (wsPendingTransitions.length === 0) return staticPending;
    // WebSocket transitions use a slightly different shape; normalize them
    const wsNormalized = wsPendingTransitions.map((t) => ({
      id: `transition-${t.from_stage}-${t.to_stage}`,
      from_stage: t.from_stage,
      to_stage: t.to_stage,
      ai_rationale: t.ai_rationale,
      confidence: t.confidence,
      status: 'pending' as const,
    }));
    // Deduplicate by from_stage+to_stage
    const seen = new Set(staticPending.map((t) => `${t.from_stage}-${t.to_stage}`));
    const merged = [...staticPending];
    for (const t of wsNormalized) {
      const key = `${t.from_stage}-${t.to_stage}`;
      if (!seen.has(key)) {
        merged.push(t as (typeof staticPending)[number]);
        seen.add(key);
      }
    }
    return merged;
  }, [initialData, wsPendingTransitions]);

  const selectedNodeLabel = useMemo(() => {
    if (!selectedNodeId) return '';
    const node = displayNodes.find((n) => n.id === selectedNodeId);
    return ((node?.data as Record<string, unknown>)?.label as string) || selectedNodeId;
  }, [selectedNodeId, displayNodes]);

  // Stage of the selected node
  const selectedNodeStage = useMemo<PipelineStageType>(() => {
    if (!selectedNodeId) return activeStage;
    return nodeLookup[selectedNodeId]?.stage ?? activeStage;
  }, [selectedNodeId, nodeLookup, activeStage]);

  // Transitions relevant to the selected node's stage
  const selectedTransitions = useMemo(
    () =>
      (initialData?.transitions || []).filter(
        (t) => t.from_stage === selectedNodeStage || t.to_stage === selectedNodeStage,
      ),
    [initialData, selectedNodeStage],
  );

  // -- Visual config ----------------------------------------------------------
  const stageConfig = viewMode === 'all' ? null : PIPELINE_STAGE_CONFIG[viewMode];
  const edgeColor = stageConfig?.primary || '#6b7280';

  // -- Right panel logic ------------------------------------------------------
  const showPropertyEditor = !!selectedNodeId && !showProvenance && isEditable;
  const showProvenanceSidebar =
    !!selectedNodeId && (showProvenance || readOnly || viewMode === 'all') && !showPropertyEditor;

  // -- Template selector: shown when no pipeline is active -------------------
  if (showTemplates) {
    return (
      <div className="flex h-full bg-bg">
        <TemplateSelector onSelectTemplate={handleSelectTemplate} onStartBlank={handleStartBlank} />
      </div>
    );
  }

  return (
    <div className="flex h-full bg-bg">
      {/* Left: Node Palette */}
      {isEditable && (
        <div className="w-56 flex-shrink-0">
          <PipelinePalette stage={activeStage} />
        </div>
      )}

      {/* Center: Navigator + Canvas */}
      <div className="flex flex-col flex-1">
        {/* Run Pipeline bar */}
        {!readOnly && (
          <div className="flex items-center gap-2 px-4 py-2 bg-surface/80 border-b border-border">
            <input
              type="text"
              value={runInputText}
              onChange={(e) => setRunInputText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleRunPipeline();
              }}
              placeholder="Describe your idea or problem..."
              className="flex-1 px-3 py-2 text-sm font-theme-data rounded bg-bg border border-border text-text placeholder:text-text-muted focus:outline-none focus:border-[var(--accent)] transition-colors"
            />
            <button
              onClick={handleRunPipeline}
              disabled={loading || !runInputText.trim() || !!activePipelineRunId}
              className="px-6 py-2 text-sm font-theme-data font-bold rounded bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 whitespace-nowrap"
            >
              {activePipelineRunId ? (
                <>
                  <span className="inline-block w-3 h-3 border-2 border-bg/30 border-t-bg rounded-full animate-spin" />
                  Running...
                </>
              ) : (
                <>
                  <svg
                    className="w-4 h-4"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth={2.5}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <polygon points="5 3 19 12 5 21 5 3" />
                  </svg>
                  Run Pipeline
                </>
              )}
            </button>

            {/* Progress indicators */}
            {activePipelineRunId && (
              <div className="flex items-center gap-1.5">
                {['ideas', 'goals', 'actions', 'orchestration'].map((stage) => (
                  <div
                    key={stage}
                    className={`w-2.5 h-2.5 rounded-full transition-colors ${
                      completedStages.includes(stage) ? 'bg-[var(--accent)]' : 'bg-border'
                    }`}
                    title={`${stage}: ${completedStages.includes(stage) ? 'complete' : 'pending'}`}
                  />
                ))}
                {isConnected && (
                  <span className="text-xs font-theme-data text-text-muted ml-1">LIVE</span>
                )}
              </div>
            )}

            {/* Notification toast */}
            {runNotification && (
              <span className="text-xs font-theme-data text-[var(--accent)] animate-pulse truncate max-w-xs">
                {runNotification}
              </span>
            )}
          </div>
        )}

        {/* Stage Navigator + Progress */}
        <div className="flex items-center justify-center gap-2 p-2">
          <ProgressIndicator stageStatus={stageStatus} activeStage={activeStage} />
          <button
            onClick={handleViewAll}
            className={`px-3 py-1.5 rounded font-theme-data text-xs font-bold uppercase tracking-wide transition-all duration-200 ${
              viewMode === 'all'
                ? 'bg-surface ring-2 ring-acid-green ring-offset-1 ring-offset-bg text-text'
                : 'bg-transparent text-text-muted hover:text-text hover:bg-surface/50'
            }`}
          >
            All Stages
          </button>
          <StageNavigator
            stageStatus={stageStatus}
            activeStage={viewMode === 'all' ? 'ideas' : viewMode}
            onStageSelect={handleStageSelect}
            onAdvance={readOnly ? undefined : handleAdvance}
            readOnly={readOnly}
          />
        </div>

        {/* Canvas */}
        <div className="flex-1" ref={reactFlowWrapper}>
          <ReactFlow
            nodes={displayNodes}
            edges={displayEdges}
            onNodesChange={isEditable ? onNodesChange : undefined}
            onEdgesChange={isEditable ? onEdgesChange : undefined}
            onConnect={isEditable ? onConnect : undefined}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onDragOver={isEditable ? handleDragOver : undefined}
            onDrop={isEditable ? handleDrop : undefined}
            nodeTypes={nodeTypes}
            fitView
            snapToGrid
            snapGrid={[16, 16]}
            defaultEdgeOptions={{ animated: true, style: { stroke: edgeColor, strokeWidth: 2 } }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#333" />
            <Controls
              className="bg-surface border border-border rounded"
              showInteractive={isEditable}
            />
            <MiniMap
              className="bg-surface border border-border rounded"
              nodeColor={miniMapNodeColor}
            />

            {/* Toolbar */}
            {isEditable && (
              <Panel position="top-center">
                <PipelineToolbar
                  stage={activeStage}
                  nodeCount={nodes.length}
                  edgeCount={edges.length}
                  readOnly={readOnly}
                  loading={loading}
                  onSave={handleSave}
                  onClear={handleClear}
                  onAIGenerate={handleAIGenerate}
                  canAdvance={canAdvance}
                  onAdvance={handleToolbarAdvance}
                  onExportReceipt={handleExportReceipt}
                  pipelineId={pipelineId}
                />
              </Panel>
            )}

            {/* Stats panel */}
            <Panel
              position="bottom-left"
              className="bg-surface/90 border border-border rounded p-2"
            >
              <div className="text-xs font-theme-data text-text-muted flex items-center gap-2">
                <span>
                  <span className="text-text">{displayNodes.length}</span> nodes |{' '}
                  <span className="text-text">{displayEdges.length}</span> edges
                  {stageConfig && (
                    <>
                      {' | '}
                      <span style={{ color: stageConfig.primary }} className="uppercase font-bold">
                        {stageConfig.label}
                      </span>
                    </>
                  )}
                  {viewMode === 'all' && (
                    <>
                      {' | '}
                      <span className="text-[var(--accent)] uppercase font-bold">ALL STAGES</span>
                    </>
                  )}
                  <span className="ml-2 opacity-50">1-4: stages | A: all</span>
                </span>
                <button
                  onClick={() => setShowStageSidebar((s) => !s)}
                  className={`ml-2 px-2 py-0.5 rounded text-xs font-theme-data transition-colors ${
                    showStageSidebar
                      ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                      : 'text-text-muted hover:text-text'
                  }`}
                  title="Toggle stage tools panel"
                >
                  Tools
                </button>
              </div>
            </Panel>

            {/* Pipeline ID + integrity */}
            {pipelineId && (
              <Panel
                position="top-right"
                className="bg-surface/90 border border-border rounded p-2"
              >
                <div className="text-xs font-theme-data text-text-muted">
                  Pipeline: <span className="text-text">{pipelineId}</span>
                  {initialData?.integrity_hash && (
                    <span className="ml-2 text-emerald-400">
                      #{initialData.integrity_hash.slice(0, 8)}
                    </span>
                  )}
                </div>
              </Panel>
            )}

            {/* Pending transition gates */}
            {pendingTransitions.length > 0 && !readOnly && (
              <Panel position="bottom-right" className="space-y-2">
                {pendingTransitions.map((transition, idx) => {
                  const transitionProvenance = (
                    Array.isArray(transition.provenance) && transition.provenance.length > 0
                      ? transition.provenance
                      : allProvenance.filter(
                          (link) =>
                            link.source_stage === transition.from_stage &&
                            link.target_stage === transition.to_stage,
                        )
                  ) as ProvenanceLink[];

                  return (
                    <StageTransitionGate
                      key={(transition.id as string) || idx}
                      transition={{
                        id: transition.id as string,
                        from_stage: transition.from_stage as string,
                        to_stage: transition.to_stage as string,
                        ai_rationale: transition.ai_rationale as string | undefined,
                        confidence: transition.confidence as number | undefined,
                        status: transition.status as string | undefined,
                        human_notes: transition.human_notes as string | undefined,
                        reviewed_at: transition.reviewed_at as number | null | undefined,
                      }}
                      pipelineId={pipelineId || ''}
                      provenance={transitionProvenance}
                      nodeLookup={nodeLookup}
                      questions={buildTransitionQuestions(transitionProvenance, stageNodes)}
                      onApprove={(pid, tid) => {
                        approveTransition(tid);
                        onTransitionApprove?.(pid, tid);
                      }}
                      onReject={(pid, tid) => {
                        rejectTransition(tid);
                        onTransitionReject?.(pid, tid);
                      }}
                    />
                  );
                })}
              </Panel>
            )}

            {/* Pipeline completion indicator */}
            {pipelineComplete && (
              <Panel position="bottom-center">
                <div className="bg-emerald-900/80 text-emerald-200 text-xs font-theme-data px-3 py-1 rounded-full">
                  Pipeline complete
                </div>
              </Panel>
            )}
          </ReactFlow>
        </div>
      </div>

      {/* Right: Property Editor */}
      {showPropertyEditor && (
        <PipelinePropertyEditor
          node={selectedNodeData}
          stage={activeStage}
          onUpdate={updateSelectedNode}
          onDelete={deleteSelectedNode}
          onShowProvenance={() => setShowProvenance(true)}
          readOnly={readOnly}
          provenanceLinks={selectedProvenance}
          transitions={selectedTransitions}
        />
      )}

      {/* Right: Stage Feature Sidebar */}
      {showStageSidebar && !showPropertyEditor && !showProvenanceSidebar && (
        <StageSidebar
          stage={viewMode === 'all' ? activeStage : viewMode}
          isOpen={showStageSidebar}
          onClose={() => setShowStageSidebar(false)}
        />
      )}

      {/* Right: Provenance Detail Panel */}
      {showProvenanceSidebar && selectedNodeId && (
        <ProvenanceNodeDetailPanel
          nodeId={selectedNodeId}
          stage={selectedNodeStage}
          nodeData={selectedNodeData}
          nodeLabel={selectedNodeLabel}
          provenance={allProvenance}
          transitions={initialData?.transitions ?? []}
          nodeLookup={nodeLookup}
          pipelineId={pipelineId}
          onNavigate={handleProvenanceNavigate}
          onClose={() => {
            setShowProvenance(false);
            setSelectedNodeId(null);
          }}
          isEditable={isEditable}
          onBackToEditor={() => setShowProvenance(false)}
        />
      )}
    </div>
  );
}

// =============================================================================
// Exported wrapper with ReactFlowProvider
// =============================================================================

export function PipelineCanvas(props: PipelineCanvasProps) {
  return (
    <ReactFlowProvider>
      <PipelineCanvasInner {...props} />
    </ReactFlowProvider>
  );
}

export default PipelineCanvas;
