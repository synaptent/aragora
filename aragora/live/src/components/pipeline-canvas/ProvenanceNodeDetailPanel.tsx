'use client';

/**
 * ProvenanceNodeDetailPanel - Rich detail panel shown when clicking a node in
 * the pipeline canvas. Displays full node properties, derivation chain,
 * upstream/downstream connections, stage transition rationale, and integrity
 * verification.
 */

import { useMemo, memo, useCallback, useState } from 'react';
import {
  PIPELINE_STAGE_CONFIG,
  PIPELINE_NODE_TYPE_CONFIGS,
  STAGE_COLOR_CLASSES,
  getMirroredNodeField,
  type PipelineStageType,
  type ProvenanceLink,
  type StageTransition,
} from './types';
import { ProvenanceTrail } from './ProvenanceTrail';

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface ProvenanceNodeDetailPanelProps {
  /** Currently selected node ID. */
  nodeId: string;
  /** Stage of the selected node. */
  stage: PipelineStageType;
  /** Full node data object from React Flow. */
  nodeData: Record<string, unknown> | null;
  /** Display label of the selected node. */
  nodeLabel: string;
  /** Full provenance chain from the pipeline result. */
  provenance: ProvenanceLink[];
  /** Stage transitions from the pipeline result. */
  transitions: StageTransition[];
  /** Lookup: nodeId -> { label, stage } for all pipeline nodes. */
  nodeLookup: Record<string, { label: string; stage: PipelineStageType }>;
  /** Pipeline ID for export/verification actions. */
  pipelineId?: string;
  /** Called when user clicks a related node to navigate. */
  onNavigate?: (nodeId: string, stage: PipelineStageType) => void;
  /** Called when panel is closed. */
  onClose: () => void;
  /** Whether the canvas is in edit mode (shows "Back to Editor" button). */
  isEditable?: boolean;
  /** Called to switch back to property editor. */
  onBackToEditor?: () => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Get the subtype label + icon for a node in a given stage. */
function getNodeTypeInfo(
  stage: PipelineStageType,
  nodeData: Record<string, unknown>,
): { label: string; icon: string } | null {
  const subtype =
    stage === 'ideas'
      ? getMirroredNodeField<string>(nodeData, 'ideaType', 'idea_type')
      : stage === 'principles'
        ? getMirroredNodeField<string>(nodeData, 'principleType', 'principle_type')
        : stage === 'goals'
          ? getMirroredNodeField<string>(nodeData, 'goalType', 'goal_type')
          : stage === 'actions'
            ? getMirroredNodeField<string>(nodeData, 'stepType', 'step_type')
            : getMirroredNodeField<string>(nodeData, 'orchType', 'orch_type');
  if (!subtype) return null;

  const config = PIPELINE_NODE_TYPE_CONFIGS[stage]?.[subtype];
  return config ? { label: config.label, icon: config.icon } : null;
}

/** Compute upstream nodes (ancestors) and downstream nodes (descendants). */
function computeConnections(
  nodeId: string,
  provenance: ProvenanceLink[],
  nodeLookup: Record<string, { label: string; stage: PipelineStageType }>,
) {
  const upstream: Array<{
    nodeId: string;
    label: string;
    stage: PipelineStageType;
    method: string;
    hash: string;
  }> = [];
  const downstream: Array<{
    nodeId: string;
    label: string;
    stage: PipelineStageType;
    method: string;
    hash: string;
  }> = [];

  for (const link of provenance) {
    if (link.target_node_id === nodeId) {
      const info = nodeLookup[link.source_node_id];
      upstream.push({
        nodeId: link.source_node_id,
        label: info?.label ?? link.source_node_id,
        stage: info?.stage ?? link.source_stage,
        method: link.method,
        hash: link.content_hash,
      });
    }
    if (link.source_node_id === nodeId) {
      const info = nodeLookup[link.target_node_id];
      downstream.push({
        nodeId: link.target_node_id,
        label: info?.label ?? link.target_node_id,
        stage: info?.stage ?? link.target_stage,
        method: link.method,
        hash: link.content_hash,
      });
    }
  }

  return { upstream, downstream };
}

/** Compute full ancestry depth by walking the chain backwards. */
function computeAncestryDepth(nodeId: string, provenance: ProvenanceLink[]): number {
  const visited = new Set<string>();
  let depth = 0;

  function walk(id: string, d: number) {
    if (visited.has(id)) return;
    visited.add(id);
    depth = Math.max(depth, d);
    for (const link of provenance) {
      if (link.target_node_id === id) {
        walk(link.source_node_id, d + 1);
      }
    }
  }

  walk(nodeId, 0);
  return depth;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SectionHeader({ title, count }: { title: string; count?: number }) {
  return (
    <label className="block text-xs text-text-muted mb-2 uppercase font-bold font-theme-data">
      {title}
      {count !== undefined && <span className="ml-1 text-text opacity-60">({count})</span>}
    </label>
  );
}

function ConnectionCard({
  nodeId,
  label,
  stage,
  method,
  hash,
  direction,
  onNavigate,
}: {
  nodeId: string;
  label: string;
  stage: PipelineStageType;
  method: string;
  hash: string;
  direction: 'upstream' | 'downstream';
  onNavigate?: (nodeId: string, stage: PipelineStageType) => void;
}) {
  const colors = STAGE_COLOR_CLASSES[stage];
  const config = PIPELINE_STAGE_CONFIG[stage];

  return (
    <button
      onClick={() => onNavigate?.(nodeId, stage)}
      className="w-full text-left p-2 bg-bg rounded border border-border hover:border-[var(--accent)]/50 transition-colors group"
      data-testid={`connection-${direction}-${nodeId}`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span
          className="w-2 h-2 rounded-full flex-shrink-0"
          style={{ backgroundColor: config.primary }}
        />
        <span className={`text-xs font-theme-data truncate ${colors.text}`}>{label}</span>
        <span className="text-xs text-text-muted font-theme-data ml-auto opacity-0 group-hover:opacity-100 transition-opacity">
          Go
        </span>
      </div>
      <div className="flex items-center gap-2 text-xs text-text-muted font-theme-data">
        <span className={`px-1 py-0.5 rounded ${colors.bg} ${colors.text}`}>{stage}</span>
        {method && <span>{method}</span>}
        {hash && <span>#{hash.slice(0, 8)}</span>}
      </div>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export const ProvenanceNodeDetailPanel = memo(function ProvenanceNodeDetailPanel({
  nodeId,
  stage,
  nodeData,
  nodeLabel,
  provenance,
  transitions,
  nodeLookup,
  pipelineId,
  onNavigate,
  onClose,
  isEditable,
  onBackToEditor,
}: ProvenanceNodeDetailPanelProps) {
  const [copiedHash, setCopiedHash] = useState(false);
  const [exportStatus, setExportStatus] = useState<string | null>(null);

  // Compute connections
  const { upstream, downstream } = useMemo(
    () => computeConnections(nodeId, provenance, nodeLookup),
    [nodeId, provenance, nodeLookup],
  );

  // Ancestry depth
  const ancestryDepth = useMemo(
    () => computeAncestryDepth(nodeId, provenance),
    [nodeId, provenance],
  );

  // Node type info
  const typeInfo = useMemo(
    () => (nodeData ? getNodeTypeInfo(stage, nodeData) : null),
    [stage, nodeData],
  );

  // Find relevant transition (the one that brought this node's stage into existence)
  const relevantTransition = useMemo(
    () => transitions.find((t) => t.to_stage === stage || t.from_stage === stage),
    [transitions, stage],
  );

  // Content hash from node data
  const contentHash =
    (nodeData && getMirroredNodeField<string>(nodeData, 'contentHash', 'content_hash')) ?? '';

  // Node description/content
  const description =
    (nodeData?.description as string) ??
    (nodeData && getMirroredNodeField<string>(nodeData, 'fullContent', 'full_content')) ??
    '';

  // Status from node data
  const status = (nodeData?.status as string) ?? '';

  // Confidence from node data
  const confidence = typeof nodeData?.confidence === 'number' ? nodeData.confidence : null;

  // Assigned agent/assignee
  const agent =
    (nodeData && getMirroredNodeField<string>(nodeData, 'assignedAgent', 'assigned_agent')) ??
    (nodeData?.assignee as string) ??
    (nodeData?.agent as string) ??
    '';

  // Copy hash to clipboard
  const handleCopyHash = useCallback(() => {
    if (!contentHash) return;
    navigator.clipboard.writeText(contentHash).then(() => {
      setCopiedHash(true);
      setTimeout(() => setCopiedHash(false), 2000);
    });
  }, [contentHash]);

  // Export ancestry as JSON
  const handleExportAncestry = useCallback(() => {
    const ancestryLinks = provenance.filter(
      (p) => p.source_node_id === nodeId || p.target_node_id === nodeId,
    );

    // Walk full ancestry
    const visited = new Set<string>();
    const chain: string[] = [];
    function walk(id: string) {
      if (visited.has(id)) return;
      visited.add(id);
      chain.push(id);
      for (const link of provenance) {
        if (link.target_node_id === id) walk(link.source_node_id);
      }
    }
    walk(nodeId);

    const exportData = {
      node_id: nodeId,
      stage,
      label: nodeLabel,
      content_hash: contentHash,
      ancestry_depth: ancestryDepth,
      ancestry_chain: chain,
      direct_links: ancestryLinks,
      pipeline_id: pipelineId,
      exported_at: new Date().toISOString(),
    };

    const blob = new Blob([JSON.stringify(exportData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `provenance-${nodeId.slice(0, 8)}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    setExportStatus('Exported');
    setTimeout(() => setExportStatus(null), 2000);
  }, [nodeId, stage, nodeLabel, contentHash, ancestryDepth, provenance, pipelineId]);

  const stageConfig = PIPELINE_STAGE_CONFIG[stage];
  const stageColors = STAGE_COLOR_CLASSES[stage];

  return (
    <div
      className="w-80 flex-shrink-0 bg-surface border-l border-border h-full overflow-y-auto"
      data-testid="provenance-detail-panel"
    >
      {/* Header */}
      <div
        className="sticky top-0 z-10 bg-surface border-b p-4"
        style={{ borderBottomColor: stageConfig.primary }}
      >
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <div
              className="w-1.5 h-8 rounded-full"
              style={{ backgroundColor: stageConfig.primary }}
            />
            <div>
              <div className="flex items-center gap-1.5">
                {typeInfo && (
                  <span className="text-sm" title={typeInfo.label}>
                    {typeInfo.icon}
                  </span>
                )}
                <h3
                  className="text-sm font-theme-data font-bold text-text truncate max-w-[180px]"
                  title={nodeLabel}
                >
                  {nodeLabel}
                </h3>
              </div>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span
                  className={`px-1.5 py-0.5 text-xs rounded font-theme-data ${stageColors.bg} ${stageColors.text}`}
                >
                  {stageConfig.label}
                </span>
                {typeInfo && (
                  <span className="text-xs text-text-muted font-theme-data">{typeInfo.label}</span>
                )}
                {status && (
                  <span className="text-xs text-text-muted font-theme-data">{status}</span>
                )}
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-text-muted hover:text-text text-lg leading-none p-1"
            aria-label="Close panel"
          >
            &times;
          </button>
        </div>

        {/* Quick stats */}
        <div className="flex items-center gap-3 text-xs text-text-muted font-theme-data mt-1">
          <span>
            depth: <span className="text-text">{ancestryDepth}</span>
          </span>
          {upstream.length > 0 && (
            <span>
              from: <span className="text-text">{upstream.length}</span>
            </span>
          )}
          {downstream.length > 0 && (
            <span>
              to: <span className="text-text">{downstream.length}</span>
            </span>
          )}
          {confidence !== null && (
            <span>
              conf: <span className="text-text">{confidence}%</span>
            </span>
          )}
        </div>
      </div>

      <div className="p-4 space-y-4">
        {/* Description / Content */}
        {description && (
          <div>
            <SectionHeader title="Content" />
            <p className="text-sm text-text font-theme-data bg-bg border border-border rounded p-2 whitespace-pre-wrap break-words max-h-32 overflow-y-auto">
              {description}
            </p>
          </div>
        )}

        {/* Agent / Assignee */}
        {agent && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted font-theme-data">Agent:</span>
            <span className="text-xs text-text font-theme-data px-1.5 py-0.5 bg-bg rounded border border-border">
              {agent}
            </span>
          </div>
        )}

        {/* Provenance Chain (breadcrumbs) */}
        <div className="p-3 bg-bg rounded border border-border">
          <SectionHeader title="Provenance Chain" />
          <ProvenanceTrail
            selectedNodeId={nodeId}
            selectedStage={stage}
            selectedLabel={nodeLabel}
            provenance={provenance}
            nodeLookup={nodeLookup}
            onNavigate={onNavigate}
          />
        </div>

        {/* Derivation Rationale (from StageTransition) */}
        {relevantTransition?.ai_rationale && (
          <div>
            <SectionHeader title="Derivation Rationale" />
            <div className="p-3 bg-bg rounded border border-border">
              <div className="flex items-center gap-2 mb-2">
                <span
                  className={`px-1 py-0.5 text-xs rounded font-theme-data ${STAGE_COLOR_CLASSES[relevantTransition.from_stage]?.bg} ${STAGE_COLOR_CLASSES[relevantTransition.from_stage]?.text}`}
                >
                  {relevantTransition.from_stage}
                </span>
                <svg
                  className="w-3 h-3 text-text-muted"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <polyline points="9 18 15 12 9 6" />
                </svg>
                <span
                  className={`px-1 py-0.5 text-xs rounded font-theme-data ${STAGE_COLOR_CLASSES[relevantTransition.to_stage]?.bg} ${STAGE_COLOR_CLASSES[relevantTransition.to_stage]?.text}`}
                >
                  {relevantTransition.to_stage}
                </span>
                <span className="text-xs text-text-muted font-theme-data ml-auto">
                  {(relevantTransition.confidence * 100).toFixed(0)}%
                </span>
              </div>
              <p className="text-xs text-text font-theme-data leading-relaxed">
                {relevantTransition.ai_rationale}
              </p>
              {relevantTransition.human_notes && (
                <p className="text-xs text-text-muted font-theme-data mt-2 pt-2 border-t border-border italic">
                  Note: {relevantTransition.human_notes}
                </p>
              )}
            </div>
          </div>
        )}

        {/* Upstream Connections (derived from) */}
        {upstream.length > 0 && (
          <div>
            <SectionHeader title="Derived From" count={upstream.length} />
            <div className="space-y-1.5">
              {upstream.map((conn) => (
                <ConnectionCard
                  key={conn.nodeId}
                  {...conn}
                  direction="upstream"
                  onNavigate={onNavigate}
                />
              ))}
            </div>
          </div>
        )}

        {/* Downstream Connections (produces) */}
        {downstream.length > 0 && (
          <div>
            <SectionHeader title="Produces" count={downstream.length} />
            <div className="space-y-1.5">
              {downstream.map((conn) => (
                <ConnectionCard
                  key={conn.nodeId}
                  {...conn}
                  direction="downstream"
                  onNavigate={onNavigate}
                />
              ))}
            </div>
          </div>
        )}

        {/* Integrity */}
        <div>
          <SectionHeader title="Integrity" />
          <div className="p-3 bg-bg rounded border border-border space-y-2">
            {contentHash ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-text-muted font-theme-data">SHA-256:</span>
                <span
                  className="text-xs text-emerald-400 font-theme-data truncate flex-1"
                  title={contentHash}
                >
                  {contentHash}
                </span>
                <button
                  onClick={handleCopyHash}
                  className="text-xs text-text-muted hover:text-text font-theme-data px-1.5 py-0.5 rounded border border-border hover:border-[var(--accent)]/50 transition-colors"
                  title="Copy full hash"
                >
                  {copiedHash ? 'Copied' : 'Copy'}
                </button>
              </div>
            ) : (
              <p className="text-xs text-text-muted font-theme-data">No content hash available</p>
            )}
            <div className="text-xs text-text-muted font-theme-data">
              Node ID: <span className="text-text break-all">{nodeId}</span>
            </div>
          </div>
        </div>

        {/* Actions */}
        <div className="space-y-2 pt-2 border-t border-border">
          <button
            onClick={handleExportAncestry}
            className="w-full px-3 py-2 bg-bg border border-border text-text font-theme-data text-xs hover:bg-surface hover:border-[var(--accent)]/50 transition-colors rounded flex items-center justify-center gap-2"
            data-testid="export-ancestry-btn"
          >
            <svg
              className="w-3.5 h-3.5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            {exportStatus ?? 'Export Ancestry (JSON)'}
          </button>

          {isEditable && onBackToEditor && (
            <button
              onClick={onBackToEditor}
              className="w-full px-3 py-2 bg-surface border border-border text-text font-theme-data text-xs hover:bg-bg transition-colors rounded"
            >
              Back to Editor
            </button>
          )}
        </div>
      </div>
    </div>
  );
});

export default ProvenanceNodeDetailPanel;
