'use client';

import Link from 'next/link';
import { useState, useEffect, useCallback, useMemo } from 'react';
import { logger } from '@/utils/logger';
import { API_BASE_URL } from '@/config';
import { PanelErrorBoundary } from '@/components/PanelErrorBoundary';
import { EmptyState, KnowledgeEmptyState, SearchEmptyState } from '@/components/ui/EmptyState';
import { useRightSidebar } from '@/context/RightSidebarContext';
import { useKnowledgeQuery } from '@/hooks';
import type {
  KnowledgeNode as StoreKnowledgeNode,
  KnowledgeRelationship as StoreKnowledgeRelationship,
  MoundStats as StoreMoundStats,
} from '@/store/knowledgeExplorerStore';
import {
  type KnowledgeNode,
  type KnowledgeRelationship,
  type Contradiction,
  type VerificationResult,
  type KnowledgeStats,
  type StaleItem,
  SOURCE_COLORS,
  TIER_COLORS,
  NODE_TYPE_ICONS,
  getConfidenceColor,
  formatRelativeDate,
} from './types';
import { KnowledgeGraphView } from './KnowledgeGraphView';
import { KnowledgeFlowDiagram } from '@/components/knowledge/KnowledgeFlowDiagram';
import { KnowledgeConfidenceHistory } from '@/components/knowledge/KnowledgeConfidenceHistory';
import { AdapterHealthGrid } from '@/components/knowledge/AdapterHealthGrid';
import { ContradictionsBrowser } from '@/components/knowledge/ContradictionsBrowser';

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function toCountMap(value: unknown): Record<string, number> {
  if (!isRecord(value)) {
    return {};
  }

  return Object.entries(value).reduce<Record<string, number>>((acc, [key, count]) => {
    if (typeof count === 'number') {
      acc[key] = count;
    }
    return acc;
  }, {});
}

function normalizeKnowledgeNode(node: StoreKnowledgeNode): KnowledgeNode {
  const rawNode = node as unknown as Record<string, unknown>;
  const metadata = isRecord(node.metadata) ? node.metadata : undefined;
  const topics = Array.isArray(rawNode.topics)
    ? rawNode.topics.filter((topic): topic is string => typeof topic === 'string')
    : [];
  const createdAt =
    (typeof rawNode.created_at === 'string' ? rawNode.created_at : undefined) ||
    (typeof rawNode.createdAt === 'string' ? rawNode.createdAt : undefined) ||
    node.accessed_at ||
    new Date().toISOString();

  const sourceType =
    (typeof rawNode.source_type === 'string' ? rawNode.source_type : undefined) ||
    node.provenance?.source_type ||
    (metadata && typeof metadata.source_type === 'string' ? metadata.source_type : undefined) ||
    (metadata && typeof metadata.source === 'string' ? metadata.source : undefined) ||
    'unknown';

  const debateId =
    node.provenance?.debate_id ||
    (metadata && typeof metadata.debate_id === 'string' ? metadata.debate_id : undefined);
  const documentId =
    node.provenance?.document_id ||
    (metadata && typeof metadata.document_id === 'string' ? metadata.document_id : undefined);
  const agentId =
    node.provenance?.agent_name ||
    (metadata && typeof metadata.agent_id === 'string' ? metadata.agent_id : undefined);

  return {
    id: node.id,
    nodeType:
      (typeof rawNode.node_type === 'string' ? rawNode.node_type : undefined) ||
      (typeof rawNode.type === 'string' ? rawNode.type : undefined) ||
      (metadata && typeof metadata.node_type === 'string' ? metadata.node_type : undefined) ||
      'fact',
    content: node.content,
    confidence: node.confidence,
    tier: (typeof rawNode.tier === 'string' ? rawNode.tier : undefined) || 'slow',
    sourceType,
    documentId,
    debateId,
    agentId,
    topics,
    createdAt,
    updatedAt:
      (typeof rawNode.accessed_at === 'string' ? rawNode.accessed_at : undefined) || createdAt,
    metadata: metadata || node.metadata,
  };
}

function normalizeKnowledgeRelationship(
  relationship: StoreKnowledgeRelationship,
): KnowledgeRelationship {
  const rawRelationship = relationship as unknown as Record<string, unknown>;
  const source =
    (typeof rawRelationship.from_node_id === 'string' ? rawRelationship.from_node_id : undefined) ||
    (typeof rawRelationship.source_id === 'string' ? rawRelationship.source_id : undefined) ||
    (typeof rawRelationship.source === 'string' ? rawRelationship.source : undefined) ||
    (isRecord(rawRelationship.source) && typeof rawRelationship.source.id === 'string'
      ? rawRelationship.source.id
      : '');
  const target =
    (typeof rawRelationship.to_node_id === 'string' ? rawRelationship.to_node_id : undefined) ||
    (typeof rawRelationship.target_id === 'string' ? rawRelationship.target_id : undefined) ||
    (typeof rawRelationship.target === 'string' ? rawRelationship.target : undefined) ||
    (isRecord(rawRelationship.target) && typeof rawRelationship.target.id === 'string'
      ? rawRelationship.target.id
      : '');

  return {
    id: relationship.id,
    sourceId: source,
    targetId: target,
    relationshipType:
      (typeof rawRelationship.relationship_type === 'string'
        ? rawRelationship.relationship_type
        : undefined) ||
      (typeof rawRelationship.type === 'string' ? rawRelationship.type : undefined) ||
      'related_to',
    strength: relationship.strength,
    createdAt:
      (typeof rawRelationship.created_at === 'string' ? rawRelationship.created_at : undefined) ||
      new Date().toISOString(),
  };
}

function normalizeKnowledgeStats(
  stats: StoreMoundStats | Record<string, unknown> | null,
): KnowledgeStats | null {
  if (!stats) {
    return null;
  }

  const rawStats = stats as Record<string, unknown>;

  return {
    totalNodes:
      (typeof rawStats.total_nodes === 'number' ? rawStats.total_nodes : undefined) ||
      (typeof rawStats.totalNodes === 'number' ? rawStats.totalNodes : undefined) ||
      0,
    nodesByType: toCountMap(rawStats.nodes_by_type ?? rawStats.nodesByType ?? rawStats.by_type),
    nodesByTier: toCountMap(rawStats.nodes_by_tier ?? rawStats.nodesByTier ?? rawStats.by_tier),
    nodesBySource: toCountMap(
      rawStats.nodes_by_source ??
        rawStats.nodesBySource ??
        rawStats.by_source_type ??
        rawStats.by_source,
    ),
    totalRelationships:
      (typeof rawStats.total_relationships === 'number'
        ? rawStats.total_relationships
        : undefined) ||
      (typeof rawStats.totalRelationships === 'number' ? rawStats.totalRelationships : undefined) ||
      0,
  };
}

function getDebateHref(debateId: string): string {
  return `/debate/${encodeURIComponent(debateId)}`;
}

function formatDebateId(debateId: string): string {
  if (debateId.length <= 18) {
    return debateId;
  }

  return `${debateId.slice(0, 14)}...`;
}

function DebatePrecedent({
  debateId,
  confidence,
  showFallback,
}: {
  debateId?: string;
  confidence: number;
  showFallback?: boolean;
}) {
  if (!debateId && !showFallback) {
    return null;
  }

  return (
    <div className="mt-3 rounded-lg border border-[var(--acid-cyan)]/20 bg-[var(--acid-cyan)]/5 px-3 py-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-theme-data uppercase tracking-wide text-text-muted">
            Debate Precedent
          </div>
          {debateId ? (
            <div className="mt-1 flex items-center gap-2">
              <span
                title={debateId}
                className="truncate font-theme-data text-xs text-[var(--acid-cyan)]"
              >
                {formatDebateId(debateId)}
              </span>
              <span className={`text-xs font-theme-data ${getConfidenceColor(confidence)}`}>
                {Math.round(confidence * 100)}%
              </span>
            </div>
          ) : (
            <div className="mt-1 flex items-center gap-2">
              <span className="text-xs text-text-muted">No linked source debate</span>
              <span className={`text-xs font-theme-data ${getConfidenceColor(confidence)}`}>
                {Math.round(confidence * 100)}%
              </span>
            </div>
          )}
        </div>
        {debateId && (
          <Link
            href={getDebateHref(debateId)}
            onClick={(event) => event.stopPropagation()}
            className="shrink-0 text-xs font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] hover:underline"
          >
            Open debate
          </Link>
        )}
      </div>
    </div>
  );
}

export default function KnowledgeMoundPage() {
  // Core data operations via hook (replaces manual fetch + state)
  const {
    queryText: searchQuery,
    setQueryText: setSearchQuery,
    executeQuery,
    queryResults,
    isQueryExecuting,
    queryError,
    browserNodes,
    browserLoading,
    browserError,
    loadNodes,
    stats: hookStats,
    loadStats,
    getNodeRelationships,
  } = useKnowledgeQuery({ autoLoadStats: true });

  // UI-only state
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [tierFilter, setTierFilter] = useState<string>('all');
  const [typeFilter, setTypeFilter] = useState<string>('all');
  const [selectedNode, setSelectedNode] = useState<KnowledgeNode | null>(null);
  const [relationships, setRelationships] = useState<KnowledgeRelationship[]>([]);

  const isSearching = searchQuery.trim().length > 0;
  const rawNodes = useMemo(
    () => (isSearching ? queryResults : browserNodes).map(normalizeKnowledgeNode),
    [browserNodes, isSearching, queryResults],
  );
  const nodes = useMemo(
    () =>
      sourceFilter === 'all'
        ? rawNodes
        : rawNodes.filter((node) => node.sourceType === sourceFilter),
    [rawNodes, sourceFilter],
  );
  const stats = useMemo(() => normalizeKnowledgeStats(hookStats), [hookStats]);
  const loading = isSearching ? isQueryExecuting : browserLoading;
  const errorMessage = isSearching ? queryError : browserError;
  const hasActiveFilters = sourceFilter !== 'all' || tierFilter !== 'all' || typeFilter !== 'all';

  // Verification state
  const [verifying, setVerifying] = useState(false);
  const [verificationResult, setVerificationResult] = useState<VerificationResult | null>(null);

  // Contradictions state
  const [contradictions, setContradictions] = useState<Contradiction[]>([]);
  const [loadingContradictions, setLoadingContradictions] = useState(false);

  // Add fact state
  const [showAddFact, setShowAddFact] = useState(false);
  const [newFactContent, setNewFactContent] = useState('');
  const [newFactSource, setNewFactSource] = useState('');
  const [newFactTopics, setNewFactTopics] = useState('');
  const [addingFact, setAddingFact] = useState(false);

  // Repository indexing state
  const [showIndexRepo, setShowIndexRepo] = useState(false);
  const [repoUrl, setRepoUrl] = useState('');
  const [indexing, setIndexing] = useState(false);
  const [indexingStatus, setIndexingStatus] = useState<string | null>(null);

  // Staleness state
  const [staleItems, setStaleItems] = useState<StaleItem[]>([]);
  const [loadingStale, setLoadingStale] = useState(false);
  const [showStalePanel, setShowStalePanel] = useState(false);

  // Export state
  const [exporting, setExporting] = useState(false);

  // View mode state
  const [viewMode, setViewMode] = useState<
    'list' | 'graph' | 'flow' | 'adapters' | 'contradictions'
  >('list');

  const { setContext, clearContext } = useRightSidebar();

  // Set up right sidebar content
  useEffect(() => {
    setContext({
      title: 'Knowledge Mound',
      subtitle: stats ? `${stats.totalNodes} nodes` : 'Loading...',
      statsContent: stats ? (
        <div className="space-y-3">
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Total Nodes</span>
            <span className="text-sm font-theme-data text-[var(--acid-green)]">
              {stats.totalNodes}
            </span>
          </div>
          <div className="flex justify-between items-center">
            <span className="text-xs text-[var(--text-muted)]">Relationships</span>
            <span className="text-sm font-theme-data text-[var(--text)]">
              {stats.totalRelationships}
            </span>
          </div>
          {stats.nodesByTier && (
            <div className="pt-2 border-t border-[var(--border)]">
              <span className="text-xs text-[var(--text-muted)] block mb-2">By Tier</span>
              {Object.entries(stats.nodesByTier).map(([tier, count]) => (
                <div key={tier} className="flex justify-between items-center text-xs">
                  <span className="text-[var(--text-muted)] capitalize">{tier}</span>
                  <span className="font-theme-data text-[var(--text)]">{count}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      ) : null,
      actionsContent: (
        <div className="space-y-2">
          <button
            onClick={() => setShowAddFact(true)}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
          >
            + ADD FACT
          </button>
          <button
            onClick={() => setShowIndexRepo(true)}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            INDEX REPO
          </button>
          <button
            onClick={() => setShowStalePanel(true)}
            className="block w-full px-3 py-2 text-xs font-theme-data text-center bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
          >
            CHECK STALE
          </button>
        </div>
      ),
    });

    return () => clearContext();
  }, [stats, setContext, clearContext, setShowAddFact, setShowIndexRepo, setShowStalePanel]);

  // Load nodes on mount and when filters change
  const refreshNodes = useCallback(() => {
    if (searchQuery.trim()) {
      executeQuery(searchQuery, {
        limit: 50,
        nodeTypes: typeFilter !== 'all' ? [typeFilter] : undefined,
      });
    } else {
      loadNodes({
        tier: tierFilter !== 'all' ? (tierFilter as never) : undefined,
        nodeTypes: typeFilter !== 'all' ? ([typeFilter] as never) : undefined,
      });
    }
  }, [searchQuery, tierFilter, typeFilter, executeQuery, loadNodes]);

  useEffect(() => {
    refreshNodes();
  }, [refreshNodes]);

  useEffect(() => {
    if (selectedNode) {
      getNodeRelationships(selectedNode.id)
        .then((rels) => {
          setRelationships(rels.map(normalizeKnowledgeRelationship));
        })
        .catch((err) => {
          logger.error('Failed to load node relationships:', err);
          setRelationships([]);
        });
      setVerificationResult(null);
      setContradictions([]);
    } else {
      setRelationships([]);
    }
  }, [selectedNode, getNodeRelationships]);

  useEffect(() => {
    if (selectedNode && !nodes.some((node) => node.id === selectedNode.id)) {
      setSelectedNode(null);
    }
  }, [nodes, selectedNode]);

  // Verify a fact with AI agents
  const verifyFact = useCallback(async (factId: string) => {
    setVerifying(true);
    setVerificationResult(null);
    try {
      const response = await fetch(`${API_BASE_URL}/api/knowledge/facts/${factId}/verify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (response.ok) {
        const data = await response.json();
        setVerificationResult(data);
      }
    } catch (err) {
      logger.error('Verification failed:', err);
    } finally {
      setVerifying(false);
    }
  }, []);

  // Fetch contradictions for a fact
  const fetchContradictions = useCallback(async (factId: string) => {
    setLoadingContradictions(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/knowledge/facts/${factId}/contradictions`);
      if (response.ok) {
        const data = await response.json();
        setContradictions(data.contradictions || []);
      }
    } catch (err) {
      logger.error('Failed to fetch contradictions:', err);
    } finally {
      setLoadingContradictions(false);
    }
  }, []);

  // Add a new fact
  const addFact = useCallback(async () => {
    if (!newFactContent.trim()) return;

    setAddingFact(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/knowledge/facts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: newFactContent.trim(),
          source: newFactSource.trim() || undefined,
          topics: newFactTopics
            .split(',')
            .map((t) => t.trim())
            .filter(Boolean),
        }),
      });
      if (response.ok) {
        setNewFactContent('');
        setNewFactSource('');
        setNewFactTopics('');
        setShowAddFact(false);
        refreshNodes();
        loadStats();
      }
    } catch (err) {
      logger.error('Failed to add fact:', err);
    } finally {
      setAddingFact(false);
    }
  }, [newFactContent, newFactSource, newFactTopics, refreshNodes, loadStats]);

  // Index a repository
  const indexRepository = useCallback(async () => {
    if (!repoUrl.trim()) return;

    setIndexing(true);
    setIndexingStatus('Starting indexing...');
    try {
      const response = await fetch(`${API_BASE_URL}/api/knowledge/mound/index/repository`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repository_url: repoUrl.trim() }),
      });
      if (response.ok) {
        const data = await response.json();
        setIndexingStatus(
          `Indexed ${data.files_indexed || 0} files, ${data.nodes_created || 0} knowledge nodes created.`,
        );
        setRepoUrl('');
        refreshNodes();
        loadStats();
      } else {
        setIndexingStatus('Indexing failed. Check repository URL and permissions.');
      }
    } catch (err) {
      setIndexingStatus('Indexing failed. Check network connection.');
      logger.error('Failed to index repository:', err);
    } finally {
      setIndexing(false);
    }
  }, [repoUrl, refreshNodes, loadStats]);

  // Fetch stale items
  const fetchStaleItems = useCallback(async () => {
    setLoadingStale(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/knowledge/mound/stale`);
      if (response.ok) {
        const data = await response.json();
        setStaleItems(data.stale_items || []);
      } else {
        setStaleItems([]);
      }
    } catch (err) {
      logger.error('Failed to fetch stale items:', err);
      setStaleItems([]);
    } finally {
      setLoadingStale(false);
    }
  }, []);

  // Export graph
  const exportGraph = useCallback(async (format: 'd3' | 'graphml') => {
    setExporting(true);
    try {
      const response = await fetch(`${API_BASE_URL}/api/knowledge/mound/export/${format}`);
      if (!response.ok) {
        throw new Error(`Export failed: ${response.status}`);
      }

      const data = await response.json();
      let content: string;
      let mimeType: string;
      let filename: string;

      if (format === 'graphml') {
        content = data.graphml || data.content || JSON.stringify(data);
        mimeType = 'application/xml';
        filename = `knowledge-graph-${new Date().toISOString().slice(0, 10)}.graphml`;
      } else {
        content = JSON.stringify(data, null, 2);
        mimeType = 'application/json';
        filename = `knowledge-graph-${new Date().toISOString().slice(0, 10)}.json`;
      }

      const blob = new Blob([content], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    } catch (err) {
      logger.error('Export failed:', err);
    } finally {
      setExporting(false);
    }
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    refreshNodes();
  };

  return (
    <main className="min-h-screen bg-bg p-6">
      <PanelErrorBoundary panelName="Knowledge Mound">
        <div className="max-w-7xl mx-auto">
          {/* Header */}
          <div className="mb-8">
            <h1 className="text-3xl font-theme-data font-bold text-text mb-2">Knowledge Mound</h1>
            <p className="text-text-muted">
              Explore the unified knowledge superstructure across all memory systems
            </p>
          </div>

          {/* Stats Bar */}
          {stats && (
            <div className="grid grid-cols-6 gap-4 mb-6">
              <div className="p-4 bg-surface border border-border rounded-lg text-center">
                <div className="text-2xl font-theme-data text-[var(--accent)]">
                  {stats.totalNodes}
                </div>
                <div className="text-xs text-text-muted">Total Nodes</div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg text-center">
                <div className="text-2xl font-theme-data text-blue-400">
                  {stats.nodesBySource['continuum'] || 0}
                </div>
                <div className="text-xs text-text-muted">Continuum</div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg text-center">
                <div className="text-2xl font-theme-data text-green-400">
                  {stats.nodesBySource['consensus'] || 0}
                </div>
                <div className="text-xs text-text-muted">Consensus</div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg text-center">
                <div className="text-2xl font-theme-data text-yellow-400">
                  {stats.nodesBySource['fact'] || 0}
                </div>
                <div className="text-xs text-text-muted">Facts</div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg text-center">
                <div className="text-2xl font-theme-data text-purple-400">
                  {stats.nodesBySource['evidence'] || 0}
                </div>
                <div className="text-xs text-text-muted">Evidence</div>
              </div>
              <div className="p-4 bg-surface border border-border rounded-lg text-center">
                <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                  {stats.totalRelationships}
                </div>
                <div className="text-xs text-text-muted">Relationships</div>
              </div>
            </div>
          )}

          {/* Action Buttons */}
          <div className="flex flex-wrap gap-3 mb-6">
            <button
              onClick={() => setShowAddFact(!showAddFact)}
              className="px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data rounded-lg hover:bg-[var(--accent)]/30 transition-colors"
            >
              + Add Fact
            </button>
            <button
              onClick={() => setShowIndexRepo(!showIndexRepo)}
              className="px-4 py-2 bg-[var(--acid-cyan)]/20 border border-[var(--acid-cyan)] text-[var(--acid-cyan)] font-theme-data rounded-lg hover:bg-[var(--acid-cyan)]/30 transition-colors"
            >
              Index Repository
            </button>
            <button
              onClick={() => {
                setShowStalePanel(!showStalePanel);
                if (!showStalePanel) fetchStaleItems();
              }}
              className="px-4 py-2 bg-yellow-500/20 border border-yellow-500 text-yellow-400 font-theme-data rounded-lg hover:bg-yellow-500/30 transition-colors"
            >
              {showStalePanel ? 'Hide' : 'Check'} Staleness
            </button>
            {/* View Toggle */}
            <div className="flex gap-1 border border-border rounded-lg overflow-hidden">
              {(['list', 'graph', 'flow', 'adapters', 'contradictions'] as const).map((mode) => (
                <button
                  key={mode}
                  onClick={() => setViewMode(mode)}
                  className={`px-4 py-2 font-theme-data text-sm transition-colors ${
                    viewMode === mode
                      ? 'bg-[var(--accent)] text-bg'
                      : 'bg-surface text-text-muted hover:bg-surface/80'
                  }`}
                >
                  {mode.charAt(0).toUpperCase() + mode.slice(1)}
                </button>
              ))}
            </div>

            <div className="flex gap-2 ml-auto">
              <button
                onClick={() => exportGraph('d3')}
                disabled={exporting}
                className="px-4 py-2 bg-purple-500/20 border border-purple-500 text-purple-400 font-theme-data rounded-lg hover:bg-purple-500/30 transition-colors disabled:opacity-50"
              >
                Export D3 JSON
              </button>
              <button
                onClick={() => exportGraph('graphml')}
                disabled={exporting}
                className="px-4 py-2 bg-purple-500/20 border border-purple-500 text-purple-400 font-theme-data rounded-lg hover:bg-purple-500/30 transition-colors disabled:opacity-50"
              >
                Export GraphML
              </button>
            </div>
          </div>

          {/* Staleness Panel */}
          {showStalePanel && (
            <div className="mb-6 p-4 bg-surface border border-yellow-500/30 rounded-lg">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-theme-data text-yellow-400 uppercase">
                  Stale Knowledge Items
                </h3>
                <button
                  onClick={fetchStaleItems}
                  disabled={loadingStale}
                  className="text-xs font-theme-data text-yellow-400 hover:text-yellow-300 disabled:opacity-50"
                >
                  {loadingStale ? 'Checking...' : 'Refresh'}
                </button>
              </div>

              {loadingStale ? (
                <div className="text-center py-4 text-text-muted font-theme-data">
                  Checking for stale items...
                </div>
              ) : staleItems.length === 0 ? (
                <div className="text-center py-4 text-text-muted font-theme-data">
                  No stale knowledge items found. All items are fresh.
                </div>
              ) : (
                <div className="space-y-3 max-h-64 overflow-y-auto">
                  {staleItems.map((item) => {
                    const stalenessLevel =
                      item.staleness_score >= 0.8
                        ? 'expired'
                        : item.staleness_score >= 0.5
                          ? 'stale'
                          : 'aging';

                    const stalenessColors = {
                      expired: 'bg-red-900/30 text-red-400 border-red-500/30',
                      stale: 'bg-yellow-900/30 text-yellow-400 border-yellow-500/30',
                      aging: 'bg-blue-900/30 text-blue-400 border-blue-500/30',
                    };

                    return (
                      <div
                        key={item.node_id}
                        className="p-3 bg-bg border border-border rounded-lg hover:border-yellow-500/50 cursor-pointer"
                        onClick={() => {
                          const node = nodes.find((n) => n.id === item.node_id);
                          if (node) setSelectedNode(node);
                        }}
                      >
                        <div className="flex items-center justify-between mb-2">
                          <span className="font-theme-data text-xs text-text-muted">
                            {item.node_id}
                          </span>
                          <span
                            className={`px-2 py-0.5 text-xs font-theme-data rounded border ${stalenessColors[stalenessLevel]}`}
                          >
                            {stalenessLevel.toUpperCase()} ({Math.round(item.staleness_score * 100)}
                            %)
                          </span>
                        </div>
                        <div className="text-xs text-text-muted mb-2">
                          {item.reasons.join(', ')}
                        </div>
                        <div className="flex items-center justify-between text-xs">
                          <span className="text-text-muted">
                            Last validated:{' '}
                            {item.last_validated_at
                              ? new Date(item.last_validated_at).toLocaleDateString()
                              : 'Never'}
                          </span>
                          <span className="text-[var(--acid-cyan)]">{item.recommended_action}</span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          )}

          {/* Add Fact Form */}
          {showAddFact && (
            <div className="mb-6 p-4 bg-surface border border-[var(--accent)]/30 rounded-lg">
              <h3 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-3">
                Add New Fact
              </h3>
              <div className="space-y-3">
                <textarea
                  value={newFactContent}
                  onChange={(e) => setNewFactContent(e.target.value)}
                  placeholder="Enter fact content..."
                  className="w-full px-3 py-2 bg-bg border border-border rounded-lg text-text focus:border-[var(--accent)] focus:outline-none font-theme-data h-24"
                />
                <div className="grid grid-cols-2 gap-3">
                  <input
                    type="text"
                    value={newFactSource}
                    onChange={(e) => setNewFactSource(e.target.value)}
                    placeholder="Source (optional)"
                    className="px-3 py-2 bg-bg border border-border rounded-lg text-text focus:border-[var(--accent)] focus:outline-none font-theme-data"
                  />
                  <input
                    type="text"
                    value={newFactTopics}
                    onChange={(e) => setNewFactTopics(e.target.value)}
                    placeholder="Topics (comma-separated)"
                    className="px-3 py-2 bg-bg border border-border rounded-lg text-text focus:border-[var(--accent)] focus:outline-none font-theme-data"
                  />
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={addFact}
                    disabled={addingFact || !newFactContent.trim()}
                    className="px-4 py-2 bg-[var(--accent)] text-bg font-theme-data rounded-lg hover:bg-[var(--accent)]/80 disabled:opacity-50"
                  >
                    {addingFact ? 'Adding...' : 'Add Fact'}
                  </button>
                  <button
                    onClick={() => setShowAddFact(false)}
                    className="px-4 py-2 border border-border text-text-muted font-theme-data rounded-lg hover:border-text-muted"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Index Repository Form */}
          {showIndexRepo && (
            <div className="mb-6 p-4 bg-surface border border-[var(--acid-cyan)]/30 rounded-lg">
              <h3 className="text-sm font-theme-data text-[var(--acid-cyan)] uppercase mb-3">
                Index Repository
              </h3>
              <div className="space-y-3">
                <input
                  type="text"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                  placeholder="https://github.com/owner/repo or /path/to/local/repo"
                  className="w-full px-3 py-2 bg-bg border border-border rounded-lg text-text focus:border-[var(--acid-cyan)] focus:outline-none font-theme-data"
                />
                {indexingStatus && (
                  <div
                    className={`text-sm font-theme-data ${indexingStatus.includes('failed') ? 'text-red-400' : 'text-[var(--accent)]'}`}
                  >
                    {indexingStatus}
                  </div>
                )}
                <div className="flex gap-3">
                  <button
                    onClick={indexRepository}
                    disabled={indexing || !repoUrl.trim()}
                    className="px-4 py-2 bg-[var(--acid-cyan)] text-bg font-theme-data rounded-lg hover:bg-[var(--acid-cyan)]/80 disabled:opacity-50"
                  >
                    {indexing ? 'Indexing...' : 'Index Repository'}
                  </button>
                  <button
                    onClick={() => {
                      setShowIndexRepo(false);
                      setIndexingStatus(null);
                    }}
                    className="px-4 py-2 border border-border text-text-muted font-theme-data rounded-lg hover:border-text-muted"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Search and Filters */}
          <form onSubmit={handleSearch} className="mb-6">
            <div className="flex gap-3 mb-4">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search knowledge semantically..."
                className="flex-1 px-4 py-3 bg-surface border border-border rounded-lg text-text focus:border-[var(--accent)] focus:outline-none font-theme-data"
              />
              <button
                type="submit"
                className="px-6 py-3 bg-[var(--accent)] text-bg font-theme-data font-bold rounded-lg hover:bg-[var(--accent)]/80 transition-colors"
              >
                Search
              </button>
            </div>

            <div className="flex flex-wrap gap-3">
              <select
                value={sourceFilter}
                onChange={(e) => setSourceFilter(e.target.value)}
                className="px-3 py-2 bg-surface border border-border rounded text-text focus:border-[var(--accent)] focus:outline-none"
              >
                <option value="all">All Sources</option>
                <option value="continuum">Continuum Memory</option>
                <option value="consensus">Consensus</option>
                <option value="fact">Facts</option>
                <option value="evidence">Evidence</option>
                <option value="critique">Critique</option>
              </select>

              <select
                value={tierFilter}
                onChange={(e) => setTierFilter(e.target.value)}
                className="px-3 py-2 bg-surface border border-border rounded text-text focus:border-[var(--accent)] focus:outline-none"
              >
                <option value="all">All Tiers</option>
                <option value="fast">Fast (1h)</option>
                <option value="medium">Medium (24h)</option>
                <option value="slow">Slow (7d)</option>
                <option value="glacial">Glacial (30d)</option>
              </select>

              <select
                value={typeFilter}
                onChange={(e) => setTypeFilter(e.target.value)}
                className="px-3 py-2 bg-surface border border-border rounded text-text focus:border-[var(--accent)] focus:outline-none"
              >
                <option value="all">All Types</option>
                <option value="memory">Memory</option>
                <option value="consensus">Consensus</option>
                <option value="fact">Fact</option>
                <option value="evidence">Evidence</option>
                <option value="critique">Critique</option>
                <option value="claim">Claim</option>
              </select>
            </div>
          </form>

          {/* View Mode Content */}
          {viewMode === 'flow' && (
            <div className="space-y-6">
              <KnowledgeFlowDiagram />
              <KnowledgeConfidenceHistory />
            </div>
          )}
          {viewMode === 'adapters' && <AdapterHealthGrid />}
          {viewMode === 'contradictions' && (
            <PanelErrorBoundary panelName="Contradictions Browser">
              <ContradictionsBrowser />
            </PanelErrorBoundary>
          )}
          {viewMode === 'graph' && (
            /* Graph View */
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="lg:col-span-1">
                <h2 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
                  Knowledge Graph
                </h2>
                <KnowledgeGraphView
                  nodes={nodes}
                  selectedNode={selectedNode}
                  onNodeSelect={setSelectedNode}
                  searchQuery={searchQuery}
                />
              </div>

              {/* Node Details (shared with list view) */}
              <div>
                <h2 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
                  Node Details & Provenance
                </h2>

                {selectedNode ? (
                  <div className="bg-surface border border-border rounded-lg p-4">
                    {/* Node Header */}
                    <div className="flex items-center gap-2 mb-4">
                      <span className="text-2xl">
                        {NODE_TYPE_ICONS[selectedNode.nodeType] || '📦'}
                      </span>
                      <div>
                        <div className="font-theme-data font-bold text-text">
                          {selectedNode.nodeType}
                        </div>
                        <div className="text-xs text-text-muted">{selectedNode.id}</div>
                      </div>
                    </div>

                    {/* Content */}
                    <div className="p-3 bg-bg border border-border rounded-lg mb-4">
                      <p className="text-sm text-text whitespace-pre-wrap">
                        {selectedNode.content}
                      </p>
                    </div>

                    {/* Metadata Grid */}
                    <div className="grid grid-cols-2 gap-3 mb-4">
                      <div className="p-2 bg-bg rounded">
                        <div className="text-xs text-text-muted">Confidence</div>
                        <div
                          className={`font-theme-data font-bold ${getConfidenceColor(selectedNode.confidence)}`}
                        >
                          {Math.round(selectedNode.confidence * 100)}%
                        </div>
                      </div>
                      <div className="p-2 bg-bg rounded">
                        <div className="text-xs text-text-muted">Tier</div>
                        <div className="font-theme-data font-bold text-text">
                          {selectedNode.tier}
                        </div>
                      </div>
                      <div className="p-2 bg-bg rounded">
                        <div className="text-xs text-text-muted">Source</div>
                        <div className="font-theme-data font-bold text-text">
                          {selectedNode.sourceType}
                        </div>
                      </div>
                      <div className="p-2 bg-bg rounded">
                        <div className="text-xs text-text-muted">Created</div>
                        <div className="font-theme-data text-text text-sm">
                          {formatRelativeDate(selectedNode.createdAt)}
                        </div>
                      </div>
                    </div>

                    {/* Relationships in graph view */}
                    {relationships.length > 0 && (
                      <div className="border-t border-border pt-4 mt-4">
                        <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase mb-3">
                          Relationships ({relationships.length})
                        </h3>
                        <div className="space-y-2 max-h-48 overflow-y-auto">
                          {relationships.map((rel) => (
                            <div
                              key={rel.id}
                              className="p-2 bg-bg rounded-lg flex items-center justify-between"
                            >
                              <div>
                                <span className="text-xs text-text-muted">
                                  {rel.relationshipType}
                                </span>
                                <div className="font-theme-data text-xs text-[var(--acid-cyan)]">
                                  {rel.sourceId === selectedNode.id ? rel.targetId : rel.sourceId}
                                </div>
                              </div>
                              <div className="text-xs text-text-muted">
                                {Math.round(rel.strength * 100)}%
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Topics */}
                    {selectedNode.topics && selectedNode.topics.length > 0 && (
                      <div className="border-t border-border pt-4 mt-4">
                        <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase mb-3">
                          Topics
                        </h3>
                        <div className="flex flex-wrap gap-2">
                          {selectedNode.topics.map((topic) => (
                            <span
                              key={topic}
                              className="px-2 py-1 text-xs bg-bg text-text-muted rounded"
                            >
                              {topic}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="bg-surface border border-border rounded-lg p-8 text-center text-text-muted">
                    Click a node in the graph to view details
                  </div>
                )}
              </div>
            </div>
          )}
          {viewMode === 'list' && (
            /* List View (original) */
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Nodes List */}
              <div>
                <h2 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
                  Knowledge Nodes ({nodes.length})
                </h2>

                {loading ? (
                  <div className="text-center py-8 text-text-muted font-theme-data">Loading...</div>
                ) : errorMessage ? (
                  <EmptyState
                    icon="⚠️"
                    title={isSearching ? 'Search failed' : 'Knowledge Mound unavailable'}
                    description={errorMessage}
                    action={{ label: 'RETRY', onClick: refreshNodes }}
                    secondaryAction={
                      isSearching
                        ? { label: 'Clear search', onClick: () => setSearchQuery('') }
                        : undefined
                    }
                  />
                ) : nodes.length === 0 ? (
                  isSearching ? (
                    <SearchEmptyState query={searchQuery} />
                  ) : hasActiveFilters ? (
                    <EmptyState
                      icon="🗂️"
                      title="No knowledge matches these filters"
                      description="Try broadening the source, tier, or node type filters."
                      action={{
                        label: 'CLEAR FILTERS',
                        onClick: () => {
                          setSourceFilter('all');
                          setTierFilter('all');
                          setTypeFilter('all');
                        },
                      }}
                    />
                  ) : (
                    <KnowledgeEmptyState onRunDebate={() => (window.location.href = '/')} />
                  )
                ) : (
                  <div className="space-y-3 max-h-[600px] overflow-y-auto pr-2">
                    {nodes.map((node) => {
                      const sourceColors = SOURCE_COLORS[node.sourceType] || {
                        bg: 'bg-gray-900/30',
                        text: 'text-gray-400',
                      };
                      const tierColors = TIER_COLORS[node.tier] || {
                        bg: 'bg-gray-900/30',
                        text: 'text-gray-400',
                      };

                      return (
                        <div
                          key={node.id}
                          onClick={() => setSelectedNode(node)}
                          className={`p-4 bg-surface border rounded-lg cursor-pointer transition-all ${
                            selectedNode?.id === node.id
                              ? 'border-[var(--accent)]'
                              : 'border-border hover:border-text-muted'
                          }`}
                        >
                          <div className="flex items-start justify-between mb-2">
                            <div className="flex items-center gap-2">
                              <span className="text-lg">
                                {NODE_TYPE_ICONS[node.nodeType] || '📦'}
                              </span>
                              <span className="font-theme-data text-xs text-text-muted">
                                {node.id}
                              </span>
                            </div>
                            <div className="flex gap-2">
                              <span
                                className={`px-2 py-0.5 text-xs font-theme-data rounded ${sourceColors.bg} ${sourceColors.text}`}
                              >
                                {node.sourceType}
                              </span>
                              <span
                                className={`px-2 py-0.5 text-xs font-theme-data rounded ${tierColors.bg} ${tierColors.text}`}
                              >
                                {node.tier}
                              </span>
                            </div>
                          </div>

                          <p className="text-sm text-text line-clamp-2 mb-2">{node.content}</p>

                          <div className="flex items-center justify-between text-xs text-text-muted">
                            <span className={getConfidenceColor(node.confidence)}>
                              {Math.round(node.confidence * 100)}% confidence
                            </span>
                            <span>{formatRelativeDate(node.createdAt)}</span>
                          </div>

                          <DebatePrecedent
                            debateId={node.debateId}
                            confidence={node.confidence}
                            showFallback={isSearching}
                          />

                          {node.topics && node.topics.length > 0 && (
                            <div className="flex flex-wrap gap-1 mt-2">
                              {node.topics.slice(0, 3).map((topic) => (
                                <span
                                  key={topic}
                                  className="px-2 py-0.5 text-xs bg-bg text-text-muted rounded"
                                >
                                  {topic}
                                </span>
                              ))}
                              {node.topics.length > 3 && (
                                <span className="text-xs text-text-muted">
                                  +{node.topics.length - 3}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Node Details / Provenance */}
              <div>
                <h2 className="text-sm font-theme-data text-[var(--accent)] uppercase mb-4">
                  Node Details & Provenance
                </h2>

                {selectedNode ? (
                  <div className="bg-surface border border-border rounded-lg p-4">
                    {/* Node Header */}
                    <div className="flex items-center gap-2 mb-4">
                      <span className="text-2xl">
                        {NODE_TYPE_ICONS[selectedNode.nodeType] || '📦'}
                      </span>
                      <div>
                        <div className="font-theme-data font-bold text-text">
                          {selectedNode.nodeType}
                        </div>
                        <div className="text-xs text-text-muted">{selectedNode.id}</div>
                      </div>
                    </div>

                    {/* Content */}
                    <div className="p-3 bg-bg border border-border rounded-lg mb-4">
                      <p className="text-sm text-text whitespace-pre-wrap">
                        {selectedNode.content}
                      </p>
                    </div>

                    {/* Metadata Grid */}
                    <div className="grid grid-cols-2 gap-3 mb-4">
                      <div className="p-2 bg-bg rounded">
                        <div className="text-xs text-text-muted">Confidence</div>
                        <div
                          className={`font-theme-data font-bold ${getConfidenceColor(selectedNode.confidence)}`}
                        >
                          {Math.round(selectedNode.confidence * 100)}%
                        </div>
                      </div>
                      <div className="p-2 bg-bg rounded">
                        <div className="text-xs text-text-muted">Tier</div>
                        <div className="font-theme-data font-bold text-text">
                          {selectedNode.tier}
                        </div>
                      </div>
                      <div className="p-2 bg-bg rounded">
                        <div className="text-xs text-text-muted">Source</div>
                        <div className="font-theme-data font-bold text-text">
                          {selectedNode.sourceType}
                        </div>
                      </div>
                      <div className="p-2 bg-bg rounded">
                        <div className="text-xs text-text-muted">Created</div>
                        <div className="font-theme-data text-text text-sm">
                          {formatRelativeDate(selectedNode.createdAt)}
                        </div>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="border-t border-border pt-4">
                      <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase mb-3">
                        Actions
                      </h3>
                      <div className="flex flex-wrap gap-2">
                        <button
                          onClick={() => verifyFact(selectedNode.id)}
                          disabled={verifying}
                          className="px-3 py-1.5 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] text-xs font-theme-data rounded hover:bg-[var(--accent)]/30 disabled:opacity-50"
                        >
                          {verifying ? 'Verifying...' : 'Verify with AI'}
                        </button>
                        <button
                          onClick={() => fetchContradictions(selectedNode.id)}
                          disabled={loadingContradictions}
                          className="px-3 py-1.5 bg-yellow-500/20 border border-yellow-500 text-yellow-500 text-xs font-theme-data rounded hover:bg-yellow-500/30 disabled:opacity-50"
                        >
                          {loadingContradictions ? 'Checking...' : 'Find Contradictions'}
                        </button>
                      </div>

                      {/* Verification Result */}
                      {verificationResult && (
                        <div className="mt-3 p-3 bg-bg border border-border rounded-lg">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-xs text-text-muted">Verification Status</span>
                            <span
                              className={`text-xs font-theme-data px-2 py-0.5 rounded ${
                                verificationResult.status === 'verified'
                                  ? 'bg-green-900/30 text-green-400'
                                  : verificationResult.status === 'disputed'
                                    ? 'bg-red-900/30 text-red-400'
                                    : 'bg-yellow-900/30 text-yellow-400'
                              }`}
                            >
                              {verificationResult.status}
                            </span>
                          </div>
                          <div className="text-xs text-text-muted mb-1">
                            Confidence:{' '}
                            <span className={getConfidenceColor(verificationResult.confidence)}>
                              {Math.round(verificationResult.confidence * 100)}%
                            </span>
                          </div>
                          {verificationResult.verified_by &&
                            verificationResult.verified_by.length > 0 && (
                              <div className="text-xs text-text-muted mb-1">
                                Verified by:{' '}
                                <span className="text-[var(--acid-cyan)]">
                                  {verificationResult.verified_by.join(', ')}
                                </span>
                              </div>
                            )}
                          {verificationResult.verification_notes && (
                            <p className="text-xs text-text-muted mt-2">
                              {verificationResult.verification_notes}
                            </p>
                          )}
                        </div>
                      )}

                      {/* Contradictions */}
                      {contradictions.length > 0 && (
                        <div className="mt-3 p-3 bg-red-900/10 border border-red-900/30 rounded-lg">
                          <h4 className="text-xs font-theme-data text-red-400 uppercase mb-2">
                            Contradictions Found ({contradictions.length})
                          </h4>
                          <div className="space-y-2">
                            {contradictions.map((c, idx) => (
                              <div key={c.fact_id || idx} className="p-2 bg-bg rounded text-xs">
                                <div className="flex items-center justify-between mb-1">
                                  <span className="text-red-400">{c.contradiction_type}</span>
                                  <span
                                    className={`px-1.5 py-0.5 rounded text-[10px] ${
                                      c.severity === 'high'
                                        ? 'bg-red-900/30 text-red-400'
                                        : c.severity === 'medium'
                                          ? 'bg-yellow-900/30 text-yellow-400'
                                          : 'bg-blue-900/30 text-blue-400'
                                    }`}
                                  >
                                    {c.severity}
                                  </span>
                                </div>
                                <p className="text-text-muted line-clamp-2">{c.content}</p>
                                {c.explanation && (
                                  <p className="text-text-muted/70 mt-1 text-[10px]">
                                    {c.explanation}
                                  </p>
                                )}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>

                    {/* Provenance */}
                    <div className="border-t border-border pt-4 mt-4">
                      <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase mb-3">
                        Provenance
                      </h3>
                      <div className="space-y-2 text-sm">
                        {selectedNode.debateId && (
                          <div className="flex items-center gap-2">
                            <span className="text-text-muted">Debate:</span>
                            <Link
                              href={getDebateHref(selectedNode.debateId)}
                              className="font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] hover:underline"
                            >
                              {selectedNode.debateId}
                            </Link>
                          </div>
                        )}
                        {selectedNode.documentId && (
                          <div className="flex items-center gap-2">
                            <span className="text-text-muted">Document:</span>
                            <span className="font-theme-data text-[var(--acid-cyan)]">
                              {selectedNode.documentId}
                            </span>
                          </div>
                        )}
                        {selectedNode.agentId && (
                          <div className="flex items-center gap-2">
                            <span className="text-text-muted">Agent:</span>
                            <span className="font-theme-data text-[var(--acid-cyan)]">
                              {selectedNode.agentId}
                            </span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Relationships */}
                    {relationships.length > 0 && (
                      <div className="border-t border-border pt-4 mt-4">
                        <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase mb-3">
                          Relationships ({relationships.length})
                        </h3>
                        <div className="space-y-2">
                          {relationships.map((rel) => (
                            <div
                              key={rel.id}
                              className="p-2 bg-bg rounded-lg flex items-center justify-between"
                            >
                              <div>
                                <span className="text-xs text-text-muted">
                                  {rel.relationshipType}
                                </span>
                                <div className="font-theme-data text-xs text-[var(--acid-cyan)]">
                                  {rel.sourceId === selectedNode.id ? rel.targetId : rel.sourceId}
                                </div>
                              </div>
                              <div className="text-xs text-text-muted">
                                {Math.round(rel.strength * 100)}%
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Additional Metadata */}
                    {selectedNode.metadata && Object.keys(selectedNode.metadata).length > 0 && (
                      <div className="border-t border-border pt-4 mt-4">
                        <h3 className="text-xs font-theme-data text-[var(--accent)] uppercase mb-3">
                          Metadata
                        </h3>
                        <pre className="p-2 bg-bg rounded text-xs text-text-muted overflow-x-auto">
                          {JSON.stringify(selectedNode.metadata, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="bg-surface border border-border rounded-lg p-8 text-center text-text-muted">
                    Select a node to view details and provenance
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </PanelErrorBoundary>
    </main>
  );
}
