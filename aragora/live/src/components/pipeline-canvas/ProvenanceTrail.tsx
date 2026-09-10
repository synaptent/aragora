'use client';

/**
 * ProvenanceTrail - Breadcrumb trail showing the provenance chain for a
 * selected node. Traces the path from the originating Idea through
 * Goals, Actions, and Orchestration stages.
 *
 * Each breadcrumb shows the node label and stage color; clicking one
 * navigates to that node on the canvas.
 */

import { useMemo, memo, useCallback } from 'react';
import {
  PIPELINE_STAGE_CONFIG,
  STAGE_COLOR_CLASSES,
  type PipelineStageType,
  type ProvenanceLink,
  type ProvenanceBreadcrumb,
} from './types';

// Order of stages for sorting breadcrumbs
const STAGE_ORDER: Record<PipelineStageType, number> = {
  ideas: 0,
  principles: 1,
  goals: 2,
  actions: 3,
  orchestration: 4,
};

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ProvenanceTrailProps {
  /** Currently selected node ID. */
  selectedNodeId: string;
  /** Stage of the selected node. */
  selectedStage: PipelineStageType;
  /** Label of the selected node. */
  selectedLabel: string;
  /** Full provenance chain from the pipeline result. */
  provenance: ProvenanceLink[];
  /** Lookup: nodeId -> { label, stage } for all pipeline nodes. */
  nodeLookup: Record<string, { label: string; stage: PipelineStageType }>;
  /** Called when user clicks a breadcrumb to navigate. */
  onNavigate?: (nodeId: string, stage: PipelineStageType) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Walk the provenance chain backwards from a target node to find all
 * ancestor nodes. Returns breadcrumbs ordered Ideas -> Orch.
 */
function buildTrail(
  nodeId: string,
  provenance: ProvenanceLink[],
  nodeLookup: Record<string, { label: string; stage: PipelineStageType }>,
): ProvenanceBreadcrumb[] {
  const visited = new Set<string>();
  const crumbs: ProvenanceBreadcrumb[] = [];

  function walk(currentId: string) {
    if (visited.has(currentId)) return;
    visited.add(currentId);

    const info = nodeLookup[currentId];
    if (!info) return;

    // Find links where this node is the target (i.e., derived from something)
    const incomingLinks = provenance.filter((p) => p.target_node_id === currentId);

    // Walk upstream first (depth-first, ancestors before self)
    for (const link of incomingLinks) {
      walk(link.source_node_id);
    }

    // Get the link that points TO this node (for method/hash metadata)
    const derivedLink = provenance.find((p) => p.target_node_id === currentId);

    crumbs.push({
      nodeId: currentId,
      nodeLabel: info.label,
      stage: info.stage,
      contentHash: derivedLink?.content_hash ?? '',
      method: derivedLink?.method ?? '',
    });
  }

  walk(nodeId);

  // Sort by stage order
  crumbs.sort((a, b) => STAGE_ORDER[a.stage] - STAGE_ORDER[b.stage]);

  return crumbs;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const ProvenanceTrail = memo(function ProvenanceTrail({
  selectedNodeId,
  selectedStage,
  selectedLabel,
  provenance,
  nodeLookup,
  onNavigate,
}: ProvenanceTrailProps) {
  const trail = useMemo(
    () => buildTrail(selectedNodeId, provenance, nodeLookup),
    [selectedNodeId, provenance, nodeLookup],
  );

  const handleClick = useCallback(
    (nodeId: string, stage: PipelineStageType) => {
      if (onNavigate) {
        onNavigate(nodeId, stage);
      }
    },
    [onNavigate],
  );

  // If no trail (no provenance links), show the selected node alone
  const displayTrail =
    trail.length > 0
      ? trail
      : [
          {
            nodeId: selectedNodeId,
            nodeLabel: selectedLabel,
            stage: selectedStage,
            contentHash: '',
            method: '',
          },
        ];

  return (
    <div className="flex flex-col gap-1" data-testid="provenance-trail">
      {/* Breadcrumb row */}
      <div className="flex items-center gap-1 flex-wrap">
        {displayTrail.map((crumb, idx) => {
          const stageColors = STAGE_COLOR_CLASSES[crumb.stage];
          const stageConfig = PIPELINE_STAGE_CONFIG[crumb.stage];
          const isActive = crumb.nodeId === selectedNodeId;

          return (
            <div key={crumb.nodeId} className="flex items-center gap-1">
              {/* Separator arrow */}
              {idx > 0 && (
                <svg
                  className="w-4 h-4 text-text-muted flex-shrink-0"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              )}

              {/* Breadcrumb chip */}
              <button
                onClick={() => handleClick(crumb.nodeId, crumb.stage)}
                className={`
                  inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-theme-data
                  transition-all duration-150
                  ${stageColors.bg} ${stageColors.text} ${stageColors.border}
                  ${isActive ? 'ring-2 ring-offset-1 ring-offset-bg border' : 'border border-transparent'}
                  hover:brightness-125 cursor-pointer
                `}
                title={`${stageConfig.label}: ${crumb.nodeLabel}`}
                data-testid={`provenance-crumb-${crumb.stage}`}
              >
                {/* Stage dot */}
                <span
                  className="w-2 h-2 rounded-full flex-shrink-0"
                  style={{ backgroundColor: stageConfig.primary }}
                />
                {/* Label (truncated) */}
                <span className="truncate max-w-[120px]">{crumb.nodeLabel}</span>
              </button>
            </div>
          );
        })}
      </div>

      {/* Metadata row: hash + method for the selected node */}
      {displayTrail.length > 1 && (
        <div className="flex items-center gap-3 text-xs text-text-muted font-theme-data pl-1 mt-1">
          {(() => {
            const selected = displayTrail.find((c) => c.nodeId === selectedNodeId);
            if (!selected?.contentHash) return null;
            return (
              <>
                <span>
                  hash:{' '}
                  <span className="text-emerald-400">#{selected.contentHash.slice(0, 8)}</span>
                </span>
                {selected.method && (
                  <span>
                    method: <span className="text-text">{selected.method}</span>
                  </span>
                )}
              </>
            );
          })()}
          <span>
            depth: <span className="text-text">{displayTrail.length}</span>
          </span>
        </div>
      )}
    </div>
  );
});

export default ProvenanceTrail;
