'use client';

import React from 'react';

// =============================================================================
// Types
// =============================================================================

export type ProvenanceNodeType = 'debate' | 'goal' | 'action' | 'receipt' | 'orchestration';

export interface ProvenanceNode {
  id: string;
  type: ProvenanceNodeType;
  label: string;
  hash?: string;
  timestamp?: string;
  status?: 'completed' | 'pending' | 'failed';
  metadata?: Record<string, unknown>;
}

interface ProvenanceNodeCardProps {
  node: ProvenanceNode;
  onClick?: (node: ProvenanceNode) => void;
}

// =============================================================================
// Color mapping by node type
// =============================================================================

const TYPE_STYLES: Record<
  ProvenanceNodeType,
  { border: string; bg: string; badge: string; badgeText: string }
> = {
  debate: {
    border: 'border-blue-500/50',
    bg: 'bg-blue-500/10',
    badge: 'bg-blue-500/20 text-blue-400 border-blue-500/40',
    badgeText: 'text-blue-400',
  },
  goal: {
    border: 'border-green-500/50',
    bg: 'bg-green-500/10',
    badge: 'bg-green-500/20 text-green-400 border-green-500/40',
    badgeText: 'text-green-400',
  },
  action: {
    border: 'border-amber-500/50',
    bg: 'bg-amber-500/10',
    badge: 'bg-amber-500/20 text-amber-400 border-amber-500/40',
    badgeText: 'text-amber-400',
  },
  receipt: {
    border: 'border-purple-500/50',
    bg: 'bg-purple-500/10',
    badge: 'bg-purple-500/20 text-purple-400 border-purple-500/40',
    badgeText: 'text-purple-400',
  },
  orchestration: {
    border: 'border-cyan-500/50',
    bg: 'bg-cyan-500/10',
    badge: 'bg-cyan-500/20 text-cyan-400 border-cyan-500/40',
    badgeText: 'text-cyan-400',
  },
};

const STATUS_STYLES: Record<string, string> = {
  completed: 'text-green-400',
  pending: 'text-yellow-400',
  failed: 'text-red-400',
};

// =============================================================================
// Component
// =============================================================================

export function ProvenanceNodeCard({ node, onClick }: ProvenanceNodeCardProps) {
  const styles = TYPE_STYLES[node.type] || TYPE_STYLES.debate;
  const statusColor = node.status ? STATUS_STYLES[node.status] || '' : '';

  return (
    <button
      type="button"
      onClick={() => onClick?.(node)}
      className={`
        w-full text-left p-3 font-theme-data
        border ${styles.border} ${styles.bg}
        hover:brightness-125 transition-all cursor-pointer
        focus:outline-none focus:ring-2 focus:ring-[var(--acid-green)]/50
      `}
      data-testid={`provenance-node-${node.type}`}
      data-node-id={node.id}
    >
      {/* Top row: type badge + status */}
      <div className="flex items-center justify-between mb-1.5">
        <span
          className={`
            px-1.5 py-0.5 text-[9px] font-bold uppercase border
            ${styles.badge}
          `}
        >
          {node.type}
        </span>
        {node.status && (
          <span className={`text-[9px] font-theme-data uppercase ${statusColor}`}>
            {node.status}
          </span>
        )}
      </div>

      {/* Label */}
      <div className="text-xs text-[var(--text)] truncate mb-1" title={node.label}>
        {node.label}
      </div>

      {/* Hash */}
      {node.hash && (
        <div
          className="text-[9px] text-[var(--text-muted)] font-theme-data truncate"
          title={`SHA-256: ${node.hash}`}
          data-testid="provenance-node-hash"
        >
          SHA-256: {node.hash.slice(0, 8)}...
        </div>
      )}

      {/* Timestamp */}
      {node.timestamp && (
        <div className="text-[9px] text-[var(--text-muted)] font-theme-data mt-0.5">
          {new Date(node.timestamp).toLocaleString()}
        </div>
      )}
    </button>
  );
}

export default ProvenanceNodeCard;
