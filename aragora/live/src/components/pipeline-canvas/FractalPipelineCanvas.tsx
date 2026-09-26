'use client';

/**
 * FractalPipelineCanvas - Wrapper around UnifiedPipelineCanvas that adds
 * fractal drill-down navigation.
 *
 * At the top level, shows all nodes for the active stage. When the user
 * double-clicks or presses Enter on a node, drills down to show its
 * provenance-linked children in the next stage.
 *
 * Renders FractalBreadcrumb for navigation and FractalMiniMap for overview.
 */

import { memo, useCallback, useMemo } from 'react';
import { ReactFlowProvider } from '@xyflow/react';
import { UnifiedPipelineCanvas } from './UnifiedPipelineCanvas';
import { FractalBreadcrumb } from './FractalBreadcrumb';
import { FractalMiniMap } from './FractalMiniMap';
import { useFractalNavigation } from '../../hooks/useFractalNavigation';
import type { PipelineStageType, PipelineResultResponse, ReactFlowData } from './types';

interface FractalPipelineCanvasProps {
  /** Full pipeline result from the API. */
  pipelineResult: PipelineResultResponse;
  /** Called when the user selects a different stage via minimap or breadcrumb. */
  onStageChange?: (stage: PipelineStageType) => void;
  /** Read-only mode disables editing. */
  readOnly?: boolean;
}

const STAGE_DATA_KEYS: Record<PipelineStageType, keyof PipelineResultResponse> = {
  ideas: 'ideas',
  principles: 'principles',
  goals: 'goals',
  actions: 'actions',
  orchestration: 'orchestration',
};

export const FractalPipelineCanvas = memo(function FractalPipelineCanvas({
  pipelineResult,
  onStageChange,
  readOnly = false,
}: FractalPipelineCanvasProps) {
  const provenance = pipelineResult.provenance ?? [];

  const nav = useFractalNavigation('ideas', provenance);

  // Filter nodes for current navigation level
  const filteredData = useMemo((): ReactFlowData | null => {
    const stageKey = STAGE_DATA_KEYS[nav.current.stage];
    const stageData = pipelineResult[stageKey] as ReactFlowData | Record<string, unknown> | null;
    if (!stageData || !('nodes' in stageData)) return null;

    const rfData = stageData as ReactFlowData;

    // If we've drilled into a specific node, only show its children
    if (nav.current.nodeId) {
      const childIds = new Set(nav.getChildNodeIds(nav.current.nodeId));
      if (childIds.size === 0) return rfData; // Show all if no children found

      const filteredNodes = rfData.nodes.filter((n) => childIds.has(n.id));
      const filteredNodeIds = new Set(filteredNodes.map((n) => n.id));
      const filteredEdges = rfData.edges.filter(
        (e) => filteredNodeIds.has(e.source) && filteredNodeIds.has(e.target),
      );

      return { nodes: filteredNodes, edges: filteredEdges, metadata: rfData.metadata };
    }

    return rfData;
  }, [pipelineResult, nav]);

  // Handle node double-click for drill-down
  const _handleNodeDoubleClick = useCallback(
    (_event: React.MouseEvent, nodeId: string, nodeLabel: string) => {
      const children = nav.getChildNodeIds(nodeId);
      if (children.length > 0) {
        nav.drillDown(nodeId, nodeLabel);
      }
    },
    [nav],
  );

  // Handle stage selection from minimap
  const handleMiniMapStageSelect = useCallback(
    (stage: PipelineStageType) => {
      nav.reset(stage);
      onStageChange?.(stage);
    },
    [nav, onStageChange],
  );

  // Stage status from pipeline result
  const stageStatus = pipelineResult.stage_status ?? {
    ideas: 'pending',
    goals: 'pending',
    actions: 'pending',
    orchestration: 'pending',
  };

  return (
    <div className="flex flex-col h-full">
      {/* Top bar: Breadcrumb */}
      <div className="flex items-center gap-3 px-4 py-2 border-b border-border">
        <FractalBreadcrumb breadcrumbs={nav.breadcrumbs} onJumpTo={nav.jumpTo} />
        {nav.canDrillUp && (
          <button
            onClick={nav.drillUp}
            className="px-2 py-1 text-xs font-theme-data text-text-muted hover:text-text bg-surface hover:bg-white/5 border border-border rounded transition-colors"
          >
            &larr; Back
          </button>
        )}
      </div>

      {/* Main canvas */}
      <div className="flex-1 relative">
        <ReactFlowProvider>
          {filteredData ? (
            <UnifiedPipelineCanvas
              pipelineId={pipelineResult.pipeline_id}
              initialData={pipelineResult}
              readOnly={readOnly}
            />
          ) : (
            <div className="flex items-center justify-center h-full text-text-muted text-sm font-theme-data">
              No data for {nav.current.stage} stage
            </div>
          )}
        </ReactFlowProvider>

        {/* Minimap overlay */}
        <div className="absolute bottom-4 right-4">
          <FractalMiniMap
            stageStatus={stageStatus}
            activeStage={nav.current.stage}
            drillDepth={nav.depth}
            onStageSelect={handleMiniMapStageSelect}
          />
        </div>
      </div>
    </div>
  );
});

export default FractalPipelineCanvas;
