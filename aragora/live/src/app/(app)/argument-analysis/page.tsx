'use client';

import { useState, useCallback } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { ArgumentMap } from '@/components/visualization/ArgumentMap';
import type { GraphData, ArgumentNode } from '@/components/visualization/ArgumentMap';
import { ExplainabilityPanel } from '@/components/ExplainabilityPanel';
import { API_BASE_URL } from '@/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface GraphStats {
  node_count: number;
  edge_count: number;
  depth: number;
  clusters: number;
  avg_branching_factor: number;
  avg_path_length: number;
}

type DetailTab = 'explainability' | 'node-detail' | 'statistics';

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ArgumentAnalysisPage() {
  const [debateId, setDebateId] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [stats, setStats] = useState<GraphStats | null>(null);
  const [selectedNode, setSelectedNode] = useState<ArgumentNode | null>(null);
  const [activeTab, setActiveTab] = useState<DetailTab>('explainability');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ---- Fetch graph + stats ------------------------------------------------

  const loadDebate = useCallback(async (id: string) => {
    if (!id.trim()) return;
    setLoading(true);
    setError(null);
    setSelectedNode(null);

    try {
      const [graphRes, statsRes] = await Promise.allSettled([
        fetch(
          `${API_BASE_URL}/api/v1/debates/${encodeURIComponent(id)}/argument-graph?format=json`,
        ),
        fetch(`${API_BASE_URL}/api/v1/debates/${encodeURIComponent(id)}/graph/stats`),
      ]);

      // Graph data
      if (graphRes.status === 'fulfilled' && graphRes.value.ok) {
        const body = await graphRes.value.json();
        const graph: GraphData = body.graph ?? body;
        // Ensure debate_id is set
        if (!graph.debate_id) graph.debate_id = id;
        if (!graph.topic) graph.topic = id;
        setGraphData(graph);
      } else {
        const msg =
          graphRes.status === 'rejected'
            ? 'Network error fetching graph'
            : `HTTP ${graphRes.value.status}`;
        setError(msg);
        setGraphData(null);
      }

      // Stats
      if (statsRes.status === 'fulfilled' && statsRes.value.ok) {
        const statsBody = await statsRes.value.json();
        setStats(statsBody.data ?? statsBody);
      } else {
        setStats(null);
      }
    } finally {
      setLoading(false);
      setDebateId(id);
    }
  }, []);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    loadDebate(searchInput);
  };

  const handleNodeClick = useCallback((node: ArgumentNode) => {
    setSelectedNode(node);
    setActiveTab('node-detail');
  }, []);

  // ---- Export helpers ------------------------------------------------------

  const exportJSON = () => {
    if (!graphData) return;
    const blob = new Blob([JSON.stringify(graphData, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `argument-graph-${debateId}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportMermaid = () => {
    if (!graphData) return;
    const lines = ['graph TD'];
    for (const n of graphData.nodes) {
      const label = n.summary.slice(0, 40).replace(/"/g, "'");
      lines.push(`  ${n.id}["${n.agent}: ${label}"]`);
    }
    for (const e of graphData.edges) {
      const arrow = e.relation === 'refutes' ? '-.->|refutes|' : '-->|' + e.relation + '|';
      lines.push(`  ${e.source_id} ${arrow} ${e.target_id}`);
    }
    const blob = new Blob([lines.join('\n')], { type: 'text/plain' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `argument-graph-${debateId}.mmd`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const exportHTML = () => {
    if (!graphData) return;
    const escHtml = (s: string) =>
      s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const nodeRows = graphData.nodes
      .map(
        (n) =>
          `<tr><td>${escHtml(n.agent)}</td><td>${escHtml(n.node_type)}</td><td>R${n.round_num}</td><td>${escHtml(n.summary)}</td></tr>`,
      )
      .join('\n');
    const edgeRows = graphData.edges
      .map(
        (e) =>
          `<tr><td>${escHtml(e.source_id)}</td><td>${escHtml(e.relation)}</td><td>${escHtml(e.target_id)}</td><td>${e.weight}</td></tr>`,
      )
      .join('\n');
    const html = [
      '<!DOCTYPE html>',
      '<html lang="en"><head><meta charset="utf-8"/>',
      `<title>Argument Graph - ${escHtml(debateId)}</title>`,
      '<style>body{font-family:monospace;background:#0a0a0a;color:#e0e0e0;padding:2rem}',
      'table{border-collapse:collapse;width:100%;margin:1rem 0}',
      'th,td{border:1px solid #333;padding:0.5rem;text-align:left}',
      'th{background:#1a1a1a;color:#39ff14}h1,h2{color:#39ff14}</style></head>',
      `<body><h1>Argument Graph: ${escHtml(graphData.topic)}</h1>`,
      `<p>Debate ID: ${escHtml(debateId)}</p>`,
      `<h2>Nodes (${graphData.nodes.length})</h2>`,
      `<table><tr><th>Agent</th><th>Type</th><th>Round</th><th>Summary</th></tr>${nodeRows}</table>`,
      `<h2>Edges (${graphData.edges.length})</h2>`,
      `<table><tr><th>Source</th><th>Relation</th><th>Target</th><th>Weight</th></tr>${edgeRows}</table>`,
      '</body></html>',
    ].join('\n');
    const blob = new Blob([html], { type: 'text/html' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `argument-graph-${debateId}.html`;
    a.click();
    URL.revokeObjectURL(url);
  };

  // ---- Render --------------------------------------------------------------

  const tabs: { key: DetailTab; label: string }[] = [
    { key: 'explainability', label: 'EXPLAIN' },
    { key: 'node-detail', label: 'NODE' },
    { key: 'statistics', label: 'STATS' },
  ];

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-bg text-text relative z-10 font-theme-data">
        {/* Header */}
        <header className="border-b border-[var(--accent)]/30 bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="container mx-auto px-4 py-3 flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs text-text-muted">
              <Link href="/" className="hover:text-[var(--accent)] transition-colors">
                DASHBOARD
              </Link>
              <span>/</span>
              <span className="text-[var(--accent)]">ARGUMENT ANALYSIS</span>
            </div>
            <div className="flex items-center gap-3">
              <Link
                href="/insights"
                className="text-xs text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [INSIGHTS]
              </Link>
              <Link
                href="/evidence"
                className="text-xs text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [EVIDENCE]
              </Link>
            </div>
          </div>
        </header>

        <div className="container mx-auto px-4 py-6">
          {/* Search */}
          <form onSubmit={handleSearch} className="mb-6 flex gap-2">
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Enter debate ID..."
              className="flex-1 bg-surface border border-[var(--accent)]/30 px-4 py-2 text-sm text-text placeholder:text-text-muted/50 focus:outline-none focus:border-[var(--accent)]"
            />
            <button
              type="submit"
              disabled={loading || !searchInput.trim()}
              className="px-6 py-2 border border-[var(--accent)] text-[var(--accent)] text-sm hover:bg-[var(--accent)]/10 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? 'LOADING...' : '[LOAD]'}
            </button>
          </form>

          {/* Error */}
          {error && (
            <div className="mb-6 p-4 border border-red-500/50 bg-red-500/10 text-red-400 text-sm">
              Error: {error}
            </div>
          )}

          {/* Empty state */}
          {!graphData && !loading && !error && (
            <div className="flex items-center justify-center h-96 border border-[var(--accent)]/20 bg-surface/30">
              <div className="text-center text-text-muted">
                <p className="text-lg mb-2">&gt; ARGUMENT ANALYSIS</p>
                <p className="text-sm">Enter a debate ID above to visualize the argument graph</p>
              </div>
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div className="flex items-center justify-center h-96 border border-[var(--accent)]/20 bg-surface/30">
              <div className="text-center text-[var(--accent)] animate-pulse">
                Loading argument graph...
              </div>
            </div>
          )}

          {/* Main content: 2-column layout */}
          {graphData && !loading && (
            <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
              {/* Left: Argument Map (60%) */}
              <div className="lg:col-span-3">
                <div className="border border-[var(--accent)]/20 bg-surface/30 p-1">
                  <div className="flex items-center justify-between px-3 py-2 border-b border-[var(--accent)]/20">
                    <span className="text-xs text-[var(--accent)]">
                      &gt; ARGUMENT MAP &mdash; {graphData.nodes.length} nodes,{' '}
                      {graphData.edges.length} edges
                    </span>
                    <div className="flex gap-2">
                      <button
                        onClick={exportMermaid}
                        className="text-xs px-2 py-1 border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] hover:border-[var(--accent)] transition-colors"
                      >
                        [MERMAID]
                      </button>
                      <button
                        onClick={exportJSON}
                        className="text-xs px-2 py-1 border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] hover:border-[var(--accent)] transition-colors"
                      >
                        [JSON]
                      </button>
                      <button
                        onClick={exportHTML}
                        className="text-xs px-2 py-1 border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)] hover:border-[var(--accent)] transition-colors"
                      >
                        [HTML]
                      </button>
                    </div>
                  </div>
                  <ArgumentMap
                    data={graphData}
                    width={800}
                    height={550}
                    onNodeClick={handleNodeClick}
                    selectedNodeId={selectedNode?.id ?? null}
                  />
                </div>
              </div>

              {/* Right: Tabbed detail panel (40%) */}
              <div className="lg:col-span-2">
                {/* Tab bar */}
                <div className="flex border border-[var(--accent)]/20 border-b-0">
                  {tabs.map((tab) => (
                    <button
                      key={tab.key}
                      onClick={() => setActiveTab(tab.key)}
                      className={`flex-1 px-3 py-2 text-xs transition-colors ${
                        activeTab === tab.key
                          ? 'bg-[var(--accent)]/20 text-[var(--accent)] border-b-2 border-[var(--accent)]'
                          : 'text-text-muted hover:text-[var(--accent)]'
                      }`}
                    >
                      [{tab.label}]
                    </button>
                  ))}
                </div>

                {/* Tab content */}
                <div className="border border-[var(--accent)]/20 bg-surface/30 min-h-[550px]">
                  {/* Explainability tab */}
                  {activeTab === 'explainability' && debateId && (
                    <div className="p-4">
                      <ExplainabilityPanel debateId={debateId} />
                    </div>
                  )}
                  {activeTab === 'explainability' && !debateId && (
                    <div className="p-6 text-center text-text-muted text-sm">
                      Load a debate to view explainability analysis.
                    </div>
                  )}

                  {/* Node detail tab */}
                  {activeTab === 'node-detail' && selectedNode && (
                    <div className="p-4 space-y-4">
                      <div className="flex items-center gap-2 mb-4">
                        <span className="text-xs text-[var(--accent)]">&gt; NODE DETAIL</span>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <span className="text-xs text-text-muted">Agent</span>
                          <p className="text-sm text-[var(--acid-cyan)]">{selectedNode.agent}</p>
                        </div>
                        <div>
                          <span className="text-xs text-text-muted">Type</span>
                          <p className="text-sm">
                            <span className="px-2 py-0.5 bg-[var(--accent)]/20 text-[var(--accent)] text-xs uppercase">
                              {selectedNode.node_type}
                            </span>
                          </p>
                        </div>
                        <div>
                          <span className="text-xs text-text-muted">Round</span>
                          <p className="text-sm text-text">{selectedNode.round_num}</p>
                        </div>
                        <div>
                          <span className="text-xs text-text-muted">Summary</span>
                          <p className="text-sm text-text">{selectedNode.summary}</p>
                        </div>
                        {selectedNode.full_content && (
                          <div>
                            <span className="text-xs text-text-muted">Full Content</span>
                            <div className="mt-1 p-3 bg-bg border border-[var(--accent)]/10 text-xs text-text whitespace-pre-wrap max-h-64 overflow-y-auto">
                              {selectedNode.full_content}
                            </div>
                          </div>
                        )}
                        {selectedNode.metadata && Object.keys(selectedNode.metadata).length > 0 && (
                          <div>
                            <span className="text-xs text-text-muted">Metadata</span>
                            <pre className="mt-1 p-3 bg-bg border border-[var(--accent)]/10 text-xs text-text-muted overflow-x-auto">
                              {JSON.stringify(selectedNode.metadata, null, 2)}
                            </pre>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                  {activeTab === 'node-detail' && !selectedNode && (
                    <div className="p-6 text-center text-text-muted text-sm">
                      Click a node on the argument map to view its details.
                    </div>
                  )}

                  {/* Statistics tab */}
                  {activeTab === 'statistics' && stats && (
                    <div className="p-4 space-y-4">
                      <div className="flex items-center gap-2 mb-4">
                        <span className="text-xs text-[var(--accent)]">&gt; GRAPH STATISTICS</span>
                      </div>

                      <div className="grid grid-cols-2 gap-3">
                        {(
                          [
                            ['Nodes', stats.node_count],
                            ['Edges', stats.edge_count],
                            ['Depth', stats.depth],
                            ['Clusters', stats.clusters],
                            ['Avg Branching', stats.avg_branching_factor?.toFixed(2) ?? '-'],
                            ['Avg Path Length', stats.avg_path_length?.toFixed(2) ?? '-'],
                          ] as [string, string | number][]
                        ).map(([label, value]) => (
                          <div key={label} className="p-3 border border-[var(--accent)]/20 bg-bg">
                            <div className="text-xs text-text-muted">{label}</div>
                            <div className="text-lg text-[var(--accent)]">{value}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {activeTab === 'statistics' && !stats && (
                    <div className="p-6 text-center text-text-muted text-sm">
                      {graphData
                        ? 'Statistics not available for this debate.'
                        : 'Load a debate to view graph statistics.'}
                    </div>
                  )}
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </>
  );
}
