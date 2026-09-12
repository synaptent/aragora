'use client';

import { useState, useEffect, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface ProofTreeNode {
  id: string;
  type: 'claim' | 'translation' | 'verification' | 'proof_step';
  content: string;
  children: string[];
  language?: string;
  is_verified?: boolean;
  proof_hash?: string;
  step_number?: number;
}

interface ProofTreeVisualizationProps {
  historyId?: string;
  nodes?: ProofTreeNode[];
  apiBase?: string;
  onNodeClick?: (node: ProofTreeNode) => void;
}

const NODE_COLORS: Record<string, { border: string; bg: string; text: string }> = {
  claim: {
    border: 'border-[var(--acid-cyan)]',
    bg: 'bg-[var(--acid-cyan)]/10',
    text: 'text-[var(--acid-cyan)]',
  },
  translation: {
    border: 'border-acid-yellow',
    bg: 'bg-acid-yellow/10',
    text: 'text-[var(--acid-yellow)]',
  },
  verification: {
    border: 'border-[var(--accent)]',
    bg: 'bg-[var(--accent)]/10',
    text: 'text-[var(--accent)]',
  },
  proof_step: {
    border: 'border-acid-magenta',
    bg: 'bg-acid-magenta/10',
    text: 'text-[var(--acid-magenta)]',
  },
};

const NODE_ICONS: Record<string, string> = {
  claim: '\u{1F4DD}', // memo
  translation: '\u{1F504}', // arrows
  verification: '\u{2714}', // check
  proof_step: '\u{1F9EA}', // test tube
};

function TreeNode({
  node,
  nodes,
  level = 0,
  onNodeClick,
}: {
  node: ProofTreeNode;
  nodes: ProofTreeNode[];
  level?: number;
  onNodeClick?: (node: ProofTreeNode) => void;
}) {
  const [expanded, setExpanded] = useState(true);
  const colors = NODE_COLORS[node.type] || NODE_COLORS.claim;
  const icon = NODE_ICONS[node.type] || '';

  const childNodes = nodes.filter((n) => node.children.includes(n.id));
  const hasChildren = childNodes.length > 0;

  return (
    <div className="relative">
      {/* Connector line */}
      {level > 0 && <div className="absolute -left-4 top-0 h-full w-px bg-[var(--accent)]/20" />}

      {/* Node */}
      <div
        className={`
          relative ml-${level > 0 ? 4 : 0} mb-2 p-3 rounded-lg border
          ${colors.border} ${colors.bg}
          cursor-pointer hover:brightness-110 transition-all
        `}
        onClick={() => {
          if (onNodeClick) onNodeClick(node);
          if (hasChildren) setExpanded(!expanded);
        }}
      >
        {/* Node header */}
        <div className="flex items-center gap-2 mb-1">
          <span className="text-lg">{icon}</span>
          <span className={`font-theme-data text-xs uppercase ${colors.text}`}>
            {node.type.replace('_', ' ')}
          </span>
          {node.step_number && (
            <span className="text-xs text-text-muted font-theme-data">#{node.step_number}</span>
          )}
          {node.is_verified !== undefined && (
            <span
              className={`text-xs font-theme-data px-1 rounded ${
                node.is_verified
                  ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                  : 'bg-acid-red/20 text-acid-red'
              }`}
            >
              {node.is_verified ? 'VERIFIED' : 'FAILED'}
            </span>
          )}
          {hasChildren && (
            <span className="ml-auto text-text-muted text-xs">{expanded ? '[-]' : '[+]'}</span>
          )}
        </div>

        {/* Node content */}
        <div className="font-theme-data text-sm text-text whitespace-pre-wrap break-all">
          {node.content.length > 200 ? `${node.content.slice(0, 200)}...` : node.content}
        </div>

        {/* Metadata */}
        <div className="flex gap-3 mt-2 text-xs text-text-muted font-theme-data">
          {node.language && <span>Lang: {node.language}</span>}
          {node.proof_hash && (
            <span title={node.proof_hash}>Hash: {node.proof_hash.slice(0, 8)}...</span>
          )}
        </div>
      </div>

      {/* Children */}
      {expanded && hasChildren && (
        <div className="ml-6 pl-4 border-l border-[var(--accent)]/20">
          {childNodes.map((child) => (
            <TreeNode
              key={child.id}
              node={child}
              nodes={nodes}
              level={level + 1}
              onNodeClick={onNodeClick}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export function ProofTreeVisualization({
  historyId,
  nodes: initialNodes,
  apiBase = API_BASE_URL,
  onNodeClick,
}: ProofTreeVisualizationProps) {
  const [nodes, setNodes] = useState<ProofTreeNode[]>(initialNodes || []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<ProofTreeNode | null>(null);

  const fetchProofTree = useCallback(async () => {
    if (!historyId) return;

    setLoading(true);
    setError(null);

    try {
      const response = await fetch(`${apiBase}/api/verify/history/${historyId}/tree`);
      if (!response.ok) {
        const data = await response.json();
        throw new Error(data.error || `HTTP ${response.status}`);
      }
      const data = await response.json();
      setNodes(data.nodes || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch proof tree');
      setNodes([]);
    } finally {
      setLoading(false);
    }
  }, [historyId, apiBase]);

  useEffect(() => {
    if (historyId && !initialNodes) {
      fetchProofTree();
    }
  }, [historyId, initialNodes, fetchProofTree]);

  const handleNodeClick = (node: ProofTreeNode) => {
    setSelectedNode(node);
    if (onNodeClick) onNodeClick(node);
  };

  const rootNode = nodes.find((n) => n.id === 'root');

  if (loading) {
    return (
      <div className="p-4 text-center">
        <div className="text-[var(--accent)] font-theme-data animate-pulse">
          Loading proof tree...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 bg-acid-red/10 border border-acid-red/30 rounded-lg">
        <div className="text-acid-red font-theme-data text-sm">{error}</div>
      </div>
    );
  }

  if (nodes.length === 0) {
    return (
      <div className="p-4 bg-surface border border-border rounded-lg">
        <div className="text-text-muted font-theme-data text-sm text-center">
          No proof tree available
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h4 className="font-theme-data text-[var(--accent)] text-sm">PROOF TREE</h4>
        <div className="flex gap-2">
          {Object.entries(NODE_COLORS).map(([type, colors]) => (
            <div key={type} className="flex items-center gap-1">
              <div className={`w-3 h-3 rounded ${colors.bg} ${colors.border} border`} />
              <span className="text-xs text-text-muted font-theme-data">{type}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Tree visualization */}
      <div className="bg-surface/50 border border-border rounded-lg p-4 overflow-x-auto">
        {rootNode ? (
          <TreeNode node={rootNode} nodes={nodes} level={0} onNodeClick={handleNodeClick} />
        ) : (
          <div className="text-text-muted font-theme-data text-sm">
            No root node found in proof tree
          </div>
        )}
      </div>

      {/* Selected node details */}
      {selectedNode && (
        <div className="bg-surface border border-[var(--acid-cyan)]/30 rounded-lg p-4">
          <h5 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-2">
            SELECTED NODE: {selectedNode.type.toUpperCase()}
          </h5>
          <pre className="font-theme-data text-xs text-text whitespace-pre-wrap overflow-x-auto">
            {selectedNode.content}
          </pre>
          {selectedNode.proof_hash && (
            <div className="mt-2 text-xs text-text-muted font-theme-data">
              Proof Hash: {selectedNode.proof_hash}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ProofTreeVisualization;
