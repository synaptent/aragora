'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  ReactFlow,
  Controls,
  Background,
  MiniMap,
  ReactFlowProvider,
  BackgroundVariant,
  type Node,
  type Edge,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { apiFetch } from '@/lib/api';

// =============================================================================
// Types
// =============================================================================

interface ProvenanceNode {
  id: string;
  type: 'debate' | 'goal' | 'action' | 'orchestration';
  label: string;
  hash: string;
  metadata?: Record<string, unknown>;
  [key: string]: unknown;
}

interface ProvenanceEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
}

interface ProvenanceData {
  nodes: ProvenanceNode[];
  edges: ProvenanceEdge[];
}

interface ReactFlowLayout {
  nodes: Array<{ id: string; position: { x: number; y: number }; data: ProvenanceNode }>;
  edges: Array<{ id: string; source: string; target: string; label?: string }>;
}

interface ProvenanceExplorerProps {
  graphId: string;
  nodeId?: string;
}

// =============================================================================
// Color mapping by pipeline stage
// =============================================================================

const STAGE_COLORS: Record<string, { bg: string; border: string; text: string }> = {
  debate: {
    bg: 'rgba(59, 130, 246, 0.15)',
    border: 'rgb(59, 130, 246)',
    text: 'rgb(147, 197, 253)',
  },
  goal: { bg: 'rgba(34, 197, 94, 0.15)', border: 'rgb(34, 197, 94)', text: 'rgb(134, 239, 172)' },
  action: {
    bg: 'rgba(249, 115, 22, 0.15)',
    border: 'rgb(249, 115, 22)',
    text: 'rgb(253, 186, 116)',
  },
  orchestration: {
    bg: 'rgba(168, 85, 247, 0.15)',
    border: 'rgb(168, 85, 247)',
    text: 'rgb(216, 180, 254)',
  },
};

function getStageColor(type: string) {
  return STAGE_COLORS[type] || STAGE_COLORS.debate;
}

// =============================================================================
// Node renderer
// =============================================================================

function ProvenanceNodeComponent({ data }: { data: ProvenanceNode }) {
  const colors = getStageColor(data.type);

  return (
    <div
      className="font-theme-data text-xs p-3 min-w-[180px]"
      style={{ background: colors.bg, border: `1px solid ${colors.border}`, color: colors.text }}
      data-testid={`provenance-node-${data.type}`}
    >
      <div className="flex items-center justify-between mb-1">
        <span
          className="px-1 py-0.5 text-[9px] font-bold uppercase"
          style={{ background: colors.border, color: '#000' }}
        >
          {data.type}
        </span>
      </div>
      <div className="text-[11px] mb-1 truncate" title={data.label}>
        {data.label}
      </div>
      <div
        className="text-[9px] opacity-60 font-theme-data truncate"
        title={data.hash}
        data-testid="provenance-hash"
      >
        SHA-256: {data.hash.slice(0, 12)}...
      </div>
    </div>
  );
}

const nodeTypes = { provenance: ProvenanceNodeComponent };

// =============================================================================
// Main component (inner, inside ReactFlowProvider)
// =============================================================================

function ProvenanceExplorerInner({ graphId, nodeId }: ProvenanceExplorerProps) {
  const [nodes, setNodes] = useState<Node[]>([]);
  const [edges, setEdges] = useState<Edge[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchProvenance = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      // Try React Flow layout endpoint first
      const layout = await apiFetch<ReactFlowLayout>(
        `/api/v1/pipeline/graph/${graphId}/react-flow`,
      );

      const flowNodes: Node[] = layout.nodes.map((n) => ({
        id: n.id,
        type: 'provenance',
        position: n.position,
        data: n.data,
      }));

      const flowEdges: Edge[] = layout.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        label: e.label,
        style: { stroke: 'var(--border)', strokeWidth: 1 },
        animated: true,
      }));

      setNodes(flowNodes);
      setEdges(flowEdges);
    } catch {
      // Fallback: fetch provenance data and auto-layout
      try {
        const endpoint = nodeId
          ? `/api/v1/pipeline/graph/${graphId}/provenance/${nodeId}`
          : `/api/v1/pipeline/graph/${graphId}/react-flow`;

        const data = await apiFetch<ProvenanceData>(endpoint);

        const flowNodes: Node[] = (data.nodes || []).map((n, i) => ({
          id: n.id,
          type: 'provenance',
          position: { x: (i % 4) * 250, y: Math.floor(i / 4) * 150 },
          data: n,
        }));

        const flowEdges: Edge[] = (data.edges || []).map((e) => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          style: { stroke: 'var(--border)', strokeWidth: 1 },
          animated: true,
        }));

        setNodes(flowNodes);
        setEdges(flowEdges);
      } catch (innerErr) {
        setError(innerErr instanceof Error ? innerErr.message : 'Failed to load provenance data');
      }
    } finally {
      setLoading(false);
    }
  }, [graphId, nodeId]);

  useEffect(() => {
    fetchProvenance();
  }, [fetchProvenance]);

  const minimapNodeColor = useCallback((node: Node) => {
    const type = (node.data as ProvenanceNode)?.type;
    return getStageColor(type || 'debate').border;
  }, []);

  if (loading) {
    return (
      <div className="border border-[var(--border)] p-4 h-[500px] flex items-center justify-center">
        <div className="text-center">
          <span className="text-[var(--acid-green)] font-theme-data text-sm font-bold block mb-2">
            PROVENANCE EXPLORER
          </span>
          <span className="text-[var(--text-muted)] font-theme-data text-xs animate-pulse">
            Loading provenance chain...
          </span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-[var(--border)] p-4 h-[500px] flex items-center justify-center">
        <div className="text-center">
          <span className="text-red-400 font-theme-data text-sm font-bold block mb-2">
            PROVENANCE ERROR
          </span>
          <span className="text-[var(--text-muted)] font-theme-data text-xs">{error}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="border border-[var(--border)] h-[500px]" data-testid="provenance-explorer">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--border)]">
        <span className="text-[var(--acid-green)] font-theme-data text-sm font-bold">
          PROVENANCE EXPLORER
        </span>
        <div className="flex items-center gap-3">
          {Object.entries(STAGE_COLORS).map(([stage, colors]) => (
            <span
              key={stage}
              className="flex items-center gap-1 text-[10px] font-theme-data"
              style={{ color: colors.text }}
            >
              <span className="w-2 h-2 inline-block" style={{ background: colors.border }} />
              {stage}
            </span>
          ))}
        </div>
      </div>

      {/* React Flow canvas */}
      <div className="h-[calc(100%-36px)]">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Controls className="font-theme-data" showInteractive={false} />
          <Background variant={BackgroundVariant.Dots} gap={16} size={1} />
          <MiniMap
            nodeColor={minimapNodeColor}
            maskColor="rgba(0,0,0,0.7)"
            style={{ background: '#111' }}
          />
        </ReactFlow>
      </div>
    </div>
  );
}

// =============================================================================
// Exported component (wraps with ReactFlowProvider)
// =============================================================================

export function ProvenanceExplorer(props: ProvenanceExplorerProps) {
  return (
    <ReactFlowProvider>
      <ProvenanceExplorerInner {...props} />
    </ReactFlowProvider>
  );
}
