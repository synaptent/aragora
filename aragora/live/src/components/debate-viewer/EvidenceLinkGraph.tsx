'use client';

import { useState, useEffect, useMemo } from 'react';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

interface Claim {
  text: string;
  supported: boolean;
  confidence?: number;
  citations?: string[];
}

interface Citation {
  text: string;
  source?: string;
  url?: string;
}

interface EvidenceData {
  debate_id: string;
  task: string;
  has_evidence: boolean;
  grounded_verdict: {
    grounding_score: number;
    confidence: number;
    claims_count: number;
    citations_count: number;
    verdict: string;
  } | null;
  claims: Claim[];
  citations: Citation[];
  related_evidence: {
    id: string;
    content: string;
    source: string;
    importance: number;
    tier: string;
  }[];
  evidence_count: number;
}

interface ClaimNode {
  id: string;
  type: 'claim';
  text: string;
  supported: boolean;
  confidence: number;
}

interface EvidenceNode {
  id: string;
  type: 'evidence';
  text: string;
  source: string;
  importance: number;
}

type GraphNode = ClaimNode | EvidenceNode;

interface GraphLink {
  source: string;
  target: string;
  strength: number;
}

interface EvidenceLinkGraphProps {
  debateId: string;
}

const NODE_COLORS = {
  claim_supported: 'bg-green-500/20 border-green-500/50 text-green-300',
  claim_unsupported: 'bg-red-500/20 border-red-500/50 text-red-300',
  evidence: 'bg-blue-500/20 border-blue-500/50 text-blue-300',
};

export function EvidenceLinkGraph({ debateId }: EvidenceLinkGraphProps) {
  const [data, setData] = useState<EvidenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  useEffect(() => {
    async function fetchEvidenceData() {
      try {
        setLoading(true);
        const response = await fetch(`${API_BASE_URL}/api/debates/${debateId}/evidence`);
        if (!response.ok) {
          if (response.status === 404) {
            setError('Evidence analysis not available for this debate');
          } else {
            throw new Error(`HTTP ${response.status}`);
          }
          return;
        }
        const result = await response.json();
        setData(result);
      } catch (err) {
        logger.error('Failed to fetch evidence data:', err);
        setError('Failed to load evidence analysis');
      } finally {
        setLoading(false);
      }
    }

    fetchEvidenceData();
  }, [debateId]);

  // Build graph nodes and links
  const { nodes, links } = useMemo(() => {
    if (!data) return { nodes: [], links: [] };

    const graphNodes: GraphNode[] = [];
    const graphLinks: GraphLink[] = [];

    // Add claim nodes
    data.claims.forEach((claim, idx) => {
      graphNodes.push({
        id: `claim-${idx}`,
        type: 'claim',
        text: claim.text,
        supported: claim.supported,
        confidence: claim.confidence ?? 0.5,
      });
    });

    // Add evidence nodes from citations
    data.citations.forEach((citation, idx) => {
      graphNodes.push({
        id: `citation-${idx}`,
        type: 'evidence',
        text: citation.text,
        source: citation.source ?? 'citation',
        importance: 0.7,
      });
    });

    // Add evidence nodes from related evidence
    data.related_evidence.forEach((evidence) => {
      graphNodes.push({
        id: `evidence-${evidence.id}`,
        type: 'evidence',
        text: evidence.content,
        source: evidence.source,
        importance: evidence.importance,
      });
    });

    // Create links: claims with citations link to those citations
    data.claims.forEach((claim, claimIdx) => {
      if (claim.citations && claim.citations.length > 0) {
        claim.citations.forEach((citationRef) => {
          // Try to find matching citation
          const citationIdx = data.citations.findIndex(
            (c) => c.text.includes(citationRef) || citationRef.includes(c.text.slice(0, 50)),
          );
          if (citationIdx !== -1) {
            graphLinks.push({
              source: `claim-${claimIdx}`,
              target: `citation-${citationIdx}`,
              strength: claim.confidence ?? 0.5,
            });
          }
        });
      }
      // Link supported claims to all citations (weak links if no specific mapping)
      if (claim.supported && (!claim.citations || claim.citations.length === 0)) {
        data.citations.slice(0, 3).forEach((_, citIdx) => {
          graphLinks.push({
            source: `claim-${claimIdx}`,
            target: `citation-${citIdx}`,
            strength: 0.3,
          });
        });
      }
    });

    return { nodes: graphNodes, links: graphLinks };
  }, [data]);

  if (loading) {
    return (
      <div className="bg-surface border border-[var(--accent)]/30 p-4">
        <div className="text-xs font-theme-data text-text-muted animate-pulse">
          Analyzing evidence links...
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="bg-surface border border-yellow-500/30 p-4">
        <div className="text-xs font-theme-data text-yellow-500">
          {error || 'No evidence data available'}
        </div>
      </div>
    );
  }

  if (!data.has_evidence) {
    return (
      <div className="bg-surface border border-gray-500/30 p-4">
        <div className="flex items-center gap-2">
          <span className="text-gray-400">○</span>
          <span className="text-xs font-theme-data text-gray-400">
            EVIDENCE: No evidence analysis available for this debate
          </span>
        </div>
      </div>
    );
  }

  const claimNodes = nodes.filter((n): n is ClaimNode => n.type === 'claim');
  const evidenceNodes = nodes.filter((n): n is EvidenceNode => n.type === 'evidence');
  const supportedClaims = claimNodes.filter((n) => n.supported).length;
  const coveragePercent =
    claimNodes.length > 0 ? Math.round((supportedClaims / claimNodes.length) * 100) : 0;

  return (
    <div className="bg-surface border border-[var(--accent)]/30">
      {/* Header */}
      <div
        className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 cursor-pointer flex items-center justify-between"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center gap-2">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {'>'} EVIDENCE LINK GRAPH
          </span>
          <span className="text-xs font-theme-data text-text-muted">
            ({claimNodes.length} claims, {evidenceNodes.length} evidence)
          </span>
        </div>
        <div className="flex items-center gap-4">
          <span
            className={`text-xs font-theme-data ${
              coveragePercent >= 70
                ? 'text-green-400'
                : coveragePercent >= 40
                  ? 'text-yellow-400'
                  : 'text-red-400'
            }`}
          >
            {coveragePercent}% coverage
          </span>
          <span className="text-xs font-theme-data text-[var(--accent)]">
            {expanded ? '[-]' : '[+]'}
          </span>
        </div>
      </div>

      {expanded && (
        <div className="p-4 space-y-4">
          {/* Summary Stats */}
          {data.grounded_verdict && (
            <div className="bg-bg/50 border border-border rounded p-3">
              <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
                Grounding Analysis
              </div>
              <div className="grid grid-cols-4 gap-4 text-xs font-theme-data">
                <div>
                  <span className="text-text-muted">Score: </span>
                  <span
                    className={`${
                      data.grounded_verdict.grounding_score >= 0.7
                        ? 'text-green-400'
                        : data.grounded_verdict.grounding_score >= 0.4
                          ? 'text-yellow-400'
                          : 'text-red-400'
                    }`}
                  >
                    {Math.round(data.grounded_verdict.grounding_score * 100)}%
                  </span>
                </div>
                <div>
                  <span className="text-text-muted">Confidence: </span>
                  <span className="text-text">
                    {Math.round(data.grounded_verdict.confidence * 100)}%
                  </span>
                </div>
                <div>
                  <span className="text-text-muted">Claims: </span>
                  <span className="text-text">{data.grounded_verdict.claims_count}</span>
                </div>
                <div>
                  <span className="text-text-muted">Citations: </span>
                  <span className="text-text">{data.grounded_verdict.citations_count}</span>
                </div>
              </div>
              {data.grounded_verdict.verdict && (
                <div className="mt-2 text-xs font-theme-data text-text-muted">
                  <span className="text-text-muted">Verdict: </span>
                  <span className="text-text">{data.grounded_verdict.verdict}</span>
                </div>
              )}
            </div>
          )}

          {/* Visual Graph */}
          <div className="bg-bg/30 border border-border rounded p-4 min-h-[200px]">
            <div className="flex gap-8">
              {/* Claims Column */}
              <div className="flex-1">
                <div className="text-xs font-theme-data text-text-muted uppercase mb-3">
                  Claims ({claimNodes.length})
                </div>
                <div className="space-y-2">
                  {claimNodes.slice(0, 10).map((node) => (
                    <div
                      key={node.id}
                      className={`p-2 border rounded cursor-pointer transition-all ${
                        node.supported ? NODE_COLORS.claim_supported : NODE_COLORS.claim_unsupported
                      } ${selectedNode === node.id ? 'ring-1 ring-current' : ''}`}
                      onClick={() => setSelectedNode(selectedNode === node.id ? null : node.id)}
                    >
                      <div className="text-xs font-theme-data line-clamp-2">
                        {node.text.slice(0, 100)}
                        {node.text.length > 100 ? '...' : ''}
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span
                          className={`text-[10px] font-theme-data ${
                            node.supported ? 'text-green-400' : 'text-red-400'
                          }`}
                        >
                          {node.supported ? '✓ SUPPORTED' : '✗ UNSUPPORTED'}
                        </span>
                        {node.confidence > 0 && (
                          <span className="text-[10px] font-theme-data text-text-muted">
                            {Math.round(node.confidence * 100)}%
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                  {claimNodes.length > 10 && (
                    <div className="text-xs font-theme-data text-text-muted text-center py-1">
                      + {claimNodes.length - 10} more claims
                    </div>
                  )}
                </div>
              </div>

              {/* Links Visualization */}
              <div className="w-16 flex flex-col items-center justify-center">
                {links.length > 0 && (
                  <div className="text-xs font-theme-data text-text-muted text-center">
                    <div className="text-[var(--accent)]">{links.length}</div>
                    <div>links</div>
                  </div>
                )}
              </div>

              {/* Evidence Column */}
              <div className="flex-1">
                <div className="text-xs font-theme-data text-text-muted uppercase mb-3">
                  Evidence ({evidenceNodes.length})
                </div>
                <div className="space-y-2">
                  {evidenceNodes.slice(0, 10).map((node) => (
                    <div
                      key={node.id}
                      className={`p-2 border rounded cursor-pointer transition-all ${NODE_COLORS.evidence} ${
                        selectedNode === node.id ? 'ring-1 ring-current' : ''
                      }`}
                      onClick={() => setSelectedNode(selectedNode === node.id ? null : node.id)}
                    >
                      <div className="text-xs font-theme-data line-clamp-2">
                        {node.text.slice(0, 100)}
                        {node.text.length > 100 ? '...' : ''}
                      </div>
                      <div className="flex items-center gap-2 mt-1">
                        <span className="text-[10px] font-theme-data text-blue-400">
                          {node.source}
                        </span>
                        <span className="text-[10px] font-theme-data text-text-muted">
                          {Math.round(node.importance * 100)}% imp.
                        </span>
                      </div>
                    </div>
                  ))}
                  {evidenceNodes.length > 10 && (
                    <div className="text-xs font-theme-data text-text-muted text-center py-1">
                      + {evidenceNodes.length - 10} more evidence
                    </div>
                  )}
                  {evidenceNodes.length === 0 && (
                    <div className="text-xs font-theme-data text-text-muted text-center py-4">
                      No evidence nodes found
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Selected Node Detail */}
          {selectedNode && (
            <div className="bg-bg/50 border border-[var(--accent)]/30 rounded p-3">
              <div className="text-xs font-theme-data text-text-muted uppercase mb-2">
                Selected: {selectedNode}
              </div>
              {(() => {
                const node = nodes.find((n) => n.id === selectedNode);
                if (!node) return null;

                const connectedLinks = links.filter(
                  (l) => l.source === selectedNode || l.target === selectedNode,
                );

                return (
                  <div className="space-y-2">
                    <div className="text-xs font-theme-data text-text">{node.text}</div>
                    {connectedLinks.length > 0 && (
                      <div className="text-xs font-theme-data text-text-muted">
                        Connected to:{' '}
                        {connectedLinks
                          .map((l) => (l.source === selectedNode ? l.target : l.source))
                          .join(', ')}
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          )}

          {/* Legend */}
          <div className="flex gap-4 text-[10px] font-theme-data text-text-muted">
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-green-500/50"></span>
              <span>Supported Claim</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-red-500/50"></span>
              <span>Unsupported Claim</span>
            </div>
            <div className="flex items-center gap-1">
              <span className="w-2 h-2 rounded bg-blue-500/50"></span>
              <span>Evidence</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
