'use client';

/**
 * MissionControlCanvas - Unified 6-stage React Flow canvas for Mission Control.
 *
 * Stages: Ideas -> Principles -> Goals -> Actions -> Orchestration -> Execution
 *
 * Features:
 * - Semantic zoom (zoom > 1.5: all 6, 0.8-1.5: first 4, < 0.8: first 3)
 * - Stage zone headers at top of each column
 * - Stage filter sidebar (left)
 * - Provenance sidebar (right) on node selection
 * - Keyboard shortcuts: 1-6 to focus stages, A for all
 * - WebSocket real-time updates
 */

import { useCallback, useState, useMemo, useEffect } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  useReactFlow,
  ReactFlowProvider,
  Panel,
  BackgroundVariant,
  type NodeTypes,
  type Node,
  type Viewport,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import IdeaNode from '../pipeline-canvas/nodes/IdeaNode';
import PrincipleNode from '../pipeline-canvas/nodes/PrincipleNode';
import GoalNode from '../pipeline-canvas/nodes/GoalNode';
import ActionNode from '../pipeline-canvas/nodes/ActionNode';
import OrchestrationNode from '../pipeline-canvas/nodes/OrchestrationNode';
import {
  PIPELINE_STAGE_CONFIG,
  STAGE_COLOR_CLASSES,
  type PipelineStageType,
} from '../pipeline-canvas/types';
import { ProvenanceTrail } from '../pipeline-canvas/ProvenanceTrail';
import { StatusBadge } from '../pipeline-canvas/StatusBadge';
import { StageZoneHeader } from './StageZoneHeader';
import { useMissionControl, STAGE_OFFSET_X } from '../../hooks/useMissionControl';

// =============================================================================
// Constants
// =============================================================================

const nodeTypes: NodeTypes = {
  ideaNode: IdeaNode,
  principleNode: PrincipleNode,
  goalNode: GoalNode,
  actionNode: ActionNode,
  orchestrationNode: OrchestrationNode,
};

const ALL_STAGES: PipelineStageType[] = [
  'ideas',
  'principles',
  'goals',
  'actions',
  'orchestration',
];

const STAGE_COLORS: Record<string, string> = {
  ideas: '#818cf8',
  principles: '#8B5CF6',
  goals: '#34d399',
  actions: '#fbbf24',
  orchestration: '#f472b6',
  execution: '#60a5fa',
};

/** Semantic zoom thresholds */
const ZOOM_FULL_DETAIL = 1.5;
const ZOOM_PARTIAL = 0.8;

function getVisibleStages(zoom: number): Set<PipelineStageType> {
  if (zoom > ZOOM_FULL_DETAIL) {
    return new Set(ALL_STAGES);
  }
  if (zoom >= ZOOM_PARTIAL) {
    return new Set<PipelineStageType>(['ideas', 'principles', 'goals', 'actions']);
  }
  return new Set<PipelineStageType>(['ideas', 'principles', 'goals']);
}

// =============================================================================
// Stage Filter Sidebar
// =============================================================================

interface StageFilterProps {
  enabledStages: Set<PipelineStageType>;
  onToggle: (stage: PipelineStageType) => void;
  onFocus: (stage: PipelineStageType) => void;
  nodeCounts: Record<PipelineStageType, number>;
}

function StageFilterSidebar({ enabledStages, onToggle, onFocus, nodeCounts }: StageFilterProps) {
  return (
    <div
      className="w-48 flex-shrink-0 bg-surface border-r border-border h-full overflow-y-auto p-4"
      data-testid="mc-stage-filter-sidebar"
    >
      <h3 className="text-sm font-theme-data font-bold text-text-muted uppercase tracking-wide mb-4">
        Stages
      </h3>
      <div className="space-y-2">
        {ALL_STAGES.map((stage, idx) => {
          const config = PIPELINE_STAGE_CONFIG[stage];
          const color = STAGE_COLORS[stage];
          const enabled = enabledStages.has(stage);
          const count = nodeCounts[stage];

          return (
            <div key={stage} className="space-y-1">
              <button
                onClick={() => onToggle(stage)}
                className={`
                  w-full flex items-center justify-between px-3 py-2 rounded font-theme-data text-xs
                  transition-all duration-200 border
                  ${
                    enabled
                      ? 'border-current opacity-100'
                      : 'border-border opacity-40 hover:opacity-60'
                  }
                `}
                style={{ color, borderColor: enabled ? color : undefined }}
                data-testid={`mc-stage-toggle-${stage}`}
              >
                <span className="flex items-center gap-1.5">
                  <span className="text-text-muted text-xs font-theme-data">{idx + 1}</span>
                  <span className="font-bold uppercase">{config.label}</span>
                </span>
                <span
                  className="px-1.5 py-0.5 rounded-full text-xs font-theme-data"
                  style={{ backgroundColor: enabled ? `${color}33` : 'transparent' }}
                >
                  {count}
                </span>
              </button>
              <button
                onClick={() => onFocus(stage)}
                className="w-full text-center text-xs font-theme-data text-text-muted hover:text-text transition-colors"
                data-testid={`mc-stage-focus-${stage}`}
              >
                Focus
              </button>
            </div>
          );
        })}
      </div>

      <div className="mt-6 pt-4 border-t border-border">
        <h4 className="text-xs font-theme-data text-text-muted mb-2 uppercase tracking-wide">
          Shortcuts
        </h4>
        <div className="space-y-1 text-xs font-theme-data text-text-muted">
          {ALL_STAGES.map((stage, idx) => (
            <div key={stage} className="flex justify-between">
              <span>{PIPELINE_STAGE_CONFIG[stage].label}</span>
              <kbd className="px-1 bg-surface border border-border rounded">{idx + 1}</kbd>
            </div>
          ))}
          <div className="flex justify-between">
            <span>Show All</span>
            <kbd className="px-1 bg-surface border border-border rounded">A</kbd>
          </div>
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Provenance Sidebar
// =============================================================================

interface ProvenanceSidebarProps {
  nodeId: string;
  nodeLabel: string;
  nodeStage: PipelineStageType;
  provenance: Array<{
    source_node_id: string;
    source_stage: PipelineStageType;
    target_node_id: string;
    target_stage: PipelineStageType;
    content_hash: string;
    method: string;
    timestamp: number;
  }>;
  nodeLookup: Record<string, { label: string; stage: PipelineStageType }>;
  provenanceChain: Array<{
    nodeId: string;
    nodeLabel: string;
    stage: PipelineStageType;
    contentHash: string;
    method: string;
  }>;
  downstreamExecution: Array<{
    nodeId: string;
    label: string;
    stage: PipelineStageType;
    status: 'pending' | 'in_progress' | 'succeeded' | 'failed' | 'partial';
    rawStatus: string;
    agent?: string;
    elapsedMs?: number;
    outputPreview?: string;
    navigable: boolean;
    isSelectedNode?: boolean;
  }>;
  onNavigate: (nodeId: string, stage: PipelineStageType) => void;
  onClose: () => void;
}

function ProvenanceSidebar({
  nodeId,
  nodeLabel,
  nodeStage,
  provenance,
  nodeLookup,
  provenanceChain,
  downstreamExecution,
  onNavigate,
  onClose,
}: ProvenanceSidebarProps) {
  return (
    <div
      className="w-72 flex-shrink-0 bg-surface border-l border-border h-full overflow-y-auto p-4"
      data-testid="mc-provenance-sidebar"
    >
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data font-bold text-text uppercase">Provenance</h3>
        <button
          onClick={onClose}
          className="text-text-muted hover:text-text text-lg leading-none"
          data-testid="mc-provenance-close"
        >
          &times;
        </button>
      </div>

      <div className="mb-4">
        <p className="text-sm text-text truncate">{nodeLabel}</p>
        <p className="text-xs text-text-muted font-theme-data">{nodeId}</p>
      </div>

      <div className="space-y-4">
        <div className="p-3 bg-bg rounded border border-border">
          <h4 className="text-xs font-theme-data font-bold text-text-muted uppercase mb-2">
            Upstream Provenance
          </h4>
          <ProvenanceTrail
            selectedNodeId={nodeId}
            selectedStage={nodeStage}
            selectedLabel={nodeLabel}
            provenance={provenance}
            nodeLookup={nodeLookup}
            onNavigate={onNavigate}
          />
        </div>

        {provenanceChain.length > 0 ? (
          <div className="space-y-2">
            <h4 className="text-xs font-theme-data font-bold text-text-muted uppercase mb-2">
              Derivation Chain
            </h4>
            {provenanceChain.map((entry, i) => {
              const stageColor = STAGE_COLORS[entry.stage] || '#6b7280';
              return (
                <div
                  key={i}
                  className="p-2 bg-bg rounded border border-border"
                  data-testid="mc-provenance-entry"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <span
                      className="w-2 h-2 rounded-full inline-block"
                      style={{ backgroundColor: stageColor }}
                    />
                    <span
                      className="text-xs font-theme-data uppercase"
                      style={{ color: stageColor }}
                    >
                      {entry.stage}
                    </span>
                    {entry.method && (
                      <span className="text-xs text-text-muted font-theme-data">
                        ({entry.method})
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-text truncate mb-1">{entry.nodeLabel}</p>
                  {entry.contentHash && (
                    <p className="text-xs text-text-muted font-theme-data">
                      #{entry.contentHash.slice(0, 12)}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-text-muted">No provenance chain for this node.</p>
        )}

        <div className="space-y-2">
          <h4 className="text-xs font-theme-data font-bold text-text-muted uppercase mb-2">
            Downstream Execution
          </h4>
          {downstreamExecution.length > 0 ? (
            downstreamExecution.map((entry) => {
              const colors = STAGE_COLOR_CLASSES[entry.stage];
              const stageLabel = PIPELINE_STAGE_CONFIG[entry.stage].label;
              return (
                <button
                  key={`${entry.nodeId}-${entry.stage}`}
                  type="button"
                  onClick={() => entry.navigable && onNavigate(entry.nodeId, entry.stage)}
                  disabled={!entry.navigable}
                  className={`w-full text-left p-2 bg-bg rounded border border-border transition-colors ${
                    entry.navigable
                      ? 'hover:border-[var(--accent)]/50'
                      : 'opacity-80 cursor-default'
                  }`}
                  data-testid="mc-downstream-execution-entry"
                >
                  <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                    <span
                      className={`px-1 py-0.5 text-xs rounded font-theme-data ${colors.bg} ${colors.text}`}
                    >
                      {stageLabel}
                    </span>
                    <StatusBadge status={entry.status} size="sm" agent={entry.agent} />
                    {entry.isSelectedNode && (
                      <span className="px-1 py-0.5 text-[10px] rounded font-theme-data bg-[var(--accent)]/10 text-[var(--accent)] border border-[var(--accent)]/30">
                        selected
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-text truncate mb-1">{entry.label}</p>
                  <div className="flex items-center gap-2 text-[10px] text-text-muted font-theme-data flex-wrap">
                    {entry.agent && <span>{entry.agent}</span>}
                    {entry.elapsedMs != null && <span>{(entry.elapsedMs / 1000).toFixed(1)}s</span>}
                    {entry.rawStatus && <span>{entry.rawStatus.replace('_', ' ')}</span>}
                  </div>
                  {entry.outputPreview && (
                    <p className="mt-1 text-[10px] text-text-muted font-theme-data bg-surface/40 rounded px-1.5 py-1 line-clamp-2">
                      {entry.outputPreview}
                    </p>
                  )}
                </button>
              );
            })
          ) : (
            <p className="text-sm text-text-muted">No downstream execution state yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}

// =============================================================================
// Inner component (inside ReactFlowProvider)
// =============================================================================

function MissionControlCanvasInner() {
  const {
    nodes: allNodes,
    edges: allEdges,
    stageStatus,
    stageNodeCounts,
    pipelineId,
    selectedNodeId,
    selectedNodeData,
    selectedNodeStage,
    onNodeSelect,
    provenance,
    provenanceChain,
    downstreamExecution,
    loading,
    error,
  } = useMissionControl();

  const { fitView } = useReactFlow();

  // -- Zoom tracking --------------------------------------------------------
  const [zoomLevel, setZoomLevel] = useState(1.0);

  const onViewportChange = useCallback((viewport: Viewport) => {
    setZoomLevel(viewport.zoom);
  }, []);

  // -- Stage filter state ---------------------------------------------------
  const [stageFilterOverrides, setStageFilterOverrides] = useState<Set<PipelineStageType>>(
    new Set(ALL_STAGES),
  );

  const toggleStage = useCallback((stage: PipelineStageType) => {
    setStageFilterOverrides((prev) => {
      const next = new Set(prev);
      if (next.has(stage)) {
        next.delete(stage);
      } else {
        next.add(stage);
      }
      return next;
    });
  }, []);

  const focusStage = useCallback(
    (stage: PipelineStageType) => {
      setStageFilterOverrides((prev) => {
        const next = new Set(prev);
        next.add(stage);
        return next;
      });
      setTimeout(() => {
        const offsetX = STAGE_OFFSET_X[stage];
        const stageNodes = allNodes.filter(
          (n) => (n.data as Record<string, unknown>)?.stage === stage,
        );
        if (stageNodes.length > 0) {
          fitView({
            padding: 0.3,
            nodes: stageNodes.map((n) => ({
              id: n.id,
              position: { x: n.position.x, y: n.position.y },
              measured: { width: 250, height: 120 },
            })),
          });
        } else {
          // Focus on the empty stage area
          fitView({
            padding: 0.3,
            nodes: [
              {
                id: `_focus_${stage}`,
                position: { x: offsetX + 100, y: 100 },
                measured: { width: 400, height: 400 },
              },
            ],
          });
        }
      }, 50);
    },
    [fitView, allNodes],
  );

  // -- Provenance sidebar ---------------------------------------------------
  const [showProvenance, setShowProvenance] = useState(false);

  // -- Compute visible stages -----------------------------------------------
  const semanticVisible = useMemo(() => getVisibleStages(zoomLevel), [zoomLevel]);
  const lineageStages = useMemo(() => {
    const stages = new Set<PipelineStageType>();
    if (selectedNodeStage) {
      stages.add(selectedNodeStage);
    }
    for (const crumb of provenanceChain) {
      stages.add(crumb.stage);
    }
    for (const entry of downstreamExecution) {
      stages.add(entry.stage);
    }
    return stages;
  }, [downstreamExecution, provenanceChain, selectedNodeStage]);

  const visibleStages = useMemo(() => {
    const result = new Set<PipelineStageType>();
    for (const stage of ALL_STAGES) {
      if (
        (semanticVisible.has(stage) && stageFilterOverrides.has(stage)) ||
        (showProvenance && lineageStages.has(stage))
      ) {
        result.add(stage);
      }
    }
    return result;
  }, [lineageStages, semanticVisible, showProvenance, stageFilterOverrides]);

  // -- Filter nodes/edges to visible stages ---------------------------------
  const { displayNodes, displayEdges } = useMemo(() => {
    const filteredNodes = allNodes.filter((n) => {
      const stage = (n.data as Record<string, unknown>)?.stage as PipelineStageType;
      return stage && visibleStages.has(stage);
    });
    const nodeIds = new Set(filteredNodes.map((n) => n.id));
    const filteredEdges = allEdges.filter((e) => nodeIds.has(e.source) && nodeIds.has(e.target));
    return { displayNodes: filteredNodes, displayEdges: filteredEdges };
  }, [allNodes, allEdges, visibleStages]);

  // -- Selected node label --------------------------------------------------
  const selectedNodeLabel = useMemo(() => {
    if (!selectedNodeId) return '';
    const node = allNodes.find((n) => n.id === selectedNodeId);
    return ((node?.data as Record<string, unknown>)?.label as string) || selectedNodeId;
  }, [selectedNodeId, allNodes]);

  const nodeLookup = useMemo(() => {
    const lookup: Record<string, { label: string; stage: PipelineStageType }> = {};
    for (const node of allNodes) {
      const data = node.data as Record<string, unknown>;
      const stage = data.stage as PipelineStageType | undefined;
      if (!stage) continue;
      lookup[node.id] = { label: (data.label as string) || node.id, stage };
    }
    return lookup;
  }, [allNodes]);

  // -- Node click -----------------------------------------------------------
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeSelect(node.id);
      setShowProvenance(true);
    },
    [onNodeSelect],
  );

  const onPaneClick = useCallback(() => {
    onNodeSelect(null);
    setShowProvenance(false);
  }, [onNodeSelect]);

  const handleSidebarNavigate = useCallback(
    (nodeId: string, stage: PipelineStageType) => {
      setStageFilterOverrides((prev) => {
        const next = new Set(prev);
        next.add(stage);
        return next;
      });
      onNodeSelect(nodeId);
      setShowProvenance(true);

      const targetNode = allNodes.find((node) => node.id === nodeId);
      setTimeout(() => {
        if (targetNode) {
          fitView({
            padding: 0.3,
            nodes: [
              {
                id: targetNode.id,
                position: targetNode.position,
                measured: { width: 260, height: 140 },
              },
            ],
          });
          return;
        }
        focusStage(stage);
      }, 50);
    },
    [allNodes, fitView, focusStage, onNodeSelect],
  );

  // -- MiniMap color --------------------------------------------------------
  const miniMapNodeColor = useCallback((node: { type?: string }) => {
    switch (node.type) {
      case 'ideaNode':
        return STAGE_COLORS.ideas;
      case 'principleNode':
        return STAGE_COLORS.principles;
      case 'goalNode':
        return STAGE_COLORS.goals;
      case 'actionNode':
        return STAGE_COLORS.actions;
      case 'orchestrationNode':
        return STAGE_COLORS.orchestration;
      default:
        return '#6b7280';
    }
  }, []);

  // -- Keyboard shortcuts ---------------------------------------------------
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Don't capture when typing in inputs
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) {
        return;
      }

      const key = e.key.toLowerCase();
      if (key >= '1' && key <= '5') {
        const idx = parseInt(key) - 1;
        const stage = ALL_STAGES[idx];
        if (stage) {
          focusStage(stage);
        }
      } else if (key === '6') {
        // Stage 6: Execution (not a PipelineStageType, just pan to offset)
        fitView({ padding: 0.3 });
      } else if (key === 'a') {
        setStageFilterOverrides(new Set(ALL_STAGES));
        setTimeout(() => fitView({ padding: 0.2 }), 50);
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [focusStage, fitView]);

  // -- Fit view on mount ----------------------------------------------------
  useEffect(() => {
    setTimeout(() => fitView({ padding: 0.2 }), 50);
  }, [fitView]);

  return (
    <div className="flex h-full bg-bg" data-testid="mission-control-canvas">
      {/* Left: Stage Filter Sidebar */}
      <StageFilterSidebar
        enabledStages={stageFilterOverrides}
        onToggle={toggleStage}
        onFocus={focusStage}
        nodeCounts={stageNodeCounts}
      />

      {/* Center: Canvas */}
      <div className="flex flex-col flex-1">
        {/* Stage zone headers */}
        <div className="flex border-b border-border bg-surface/50">
          {ALL_STAGES.filter((s) => visibleStages.has(s)).map((stage) => (
            <div key={stage} className="flex-1 min-w-0">
              <StageZoneHeader
                stage={stage}
                nodeCount={stageNodeCounts[stage]}
                status={
                  stageStatus[stage] === 'complete'
                    ? 'complete'
                    : stageStatus[stage] === 'active' || stageStatus[stage] === 'running'
                      ? 'active'
                      : stageStatus[stage] === 'error' || stageStatus[stage] === 'failed'
                        ? 'error'
                        : 'pending'
                }
              />
            </div>
          ))}
        </div>

        {/* React Flow canvas */}
        <div className="flex-1">
          <ReactFlow
            nodes={displayNodes}
            edges={displayEdges}
            onNodeClick={onNodeClick}
            onPaneClick={onPaneClick}
            onViewportChange={onViewportChange}
            nodeTypes={nodeTypes}
            fitView
            snapToGrid
            snapGrid={[16, 16]}
            defaultEdgeOptions={{ animated: true, style: { stroke: '#6b7280', strokeWidth: 2 } }}
            proOptions={{ hideAttribution: true }}
          >
            <Background variant={BackgroundVariant.Dots} gap={16} size={1} color="#333" />
            <Controls className="bg-surface border border-border rounded" />
            <MiniMap
              className="bg-surface border border-border rounded"
              nodeColor={miniMapNodeColor}
            />

            {/* Error banner */}
            {error && (
              <Panel position="top-center">
                <div className="px-4 py-2 bg-red-500/20 border border-red-500 rounded text-sm text-red-300 font-theme-data">
                  {error}
                </div>
              </Panel>
            )}

            {/* Loading indicator */}
            {loading && (
              <Panel position="top-center">
                <div className="px-4 py-2 bg-blue-500/20 border border-blue-500 rounded text-sm text-blue-300 font-theme-data flex items-center gap-2">
                  <span className="inline-block w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                  Processing...
                </div>
              </Panel>
            )}

            {/* Bottom panel: stats */}
            <Panel
              position="bottom-left"
              className="bg-surface/90 border border-border rounded p-2"
            >
              <div className="text-xs font-theme-data text-text-muted">
                {pipelineId && (
                  <>
                    Pipeline: <span className="text-text">{pipelineId.slice(0, 12)}</span>
                    <span className="mx-2">|</span>
                  </>
                )}
                <span className="text-text">{displayNodes.length}</span> nodes |{' '}
                <span className="text-text">{displayEdges.length}</span> edges |{' '}
                <span className="text-text">zoom: {zoomLevel.toFixed(2)}</span>
                <span className="ml-2 opacity-50" data-testid="mc-zoom-indicator">
                  {zoomLevel > ZOOM_FULL_DETAIL
                    ? 'all stages'
                    : zoomLevel >= ZOOM_PARTIAL
                      ? '4 stages'
                      : '3 stages'}
                </span>
              </div>
            </Panel>

            {/* Bottom right: keyboard hint */}
            <Panel
              position="bottom-right"
              className="bg-surface/90 border border-border rounded p-2"
            >
              <div className="text-xs font-theme-data text-text-muted">
                <kbd className="px-1 bg-bg border border-border rounded">1</kbd>-
                <kbd className="px-1 bg-bg border border-border rounded">5</kbd> stages |{' '}
                <kbd className="px-1 bg-bg border border-border rounded">A</kbd> all
              </div>
            </Panel>

            {/* Brain dump trigger placeholder */}
            <Panel position="top-left">
              <button
                className="px-3 py-1.5 bg-violet-600 text-white font-theme-data text-xs font-bold rounded
                           hover:bg-violet-500 transition-colors disabled:opacity-40"
                disabled={loading}
                data-testid="mc-brain-dump-trigger"
                title="Brain Dump (Phase 2)"
              >
                + Brain Dump
              </button>
            </Panel>
          </ReactFlow>
        </div>
      </div>

      {/* Right: Provenance Sidebar */}
      {showProvenance && selectedNodeId && selectedNodeData && selectedNodeStage && (
        <ProvenanceSidebar
          nodeId={selectedNodeId}
          nodeLabel={selectedNodeLabel}
          nodeStage={selectedNodeStage}
          provenance={provenance}
          nodeLookup={nodeLookup}
          provenanceChain={provenanceChain}
          downstreamExecution={downstreamExecution}
          onNavigate={handleSidebarNavigate}
          onClose={() => {
            setShowProvenance(false);
            onNodeSelect(null);
          }}
        />
      )}
    </div>
  );
}

// =============================================================================
// Exported wrapper with ReactFlowProvider
// =============================================================================

export function MissionControlCanvas() {
  return (
    <ReactFlowProvider>
      <MissionControlCanvasInner />
    </ReactFlowProvider>
  );
}

export default MissionControlCanvas;
