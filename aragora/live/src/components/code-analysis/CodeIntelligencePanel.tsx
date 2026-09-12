'use client';

import { useState, useEffect, useCallback } from 'react';

interface CodeSymbol {
  name: string;
  kind: 'function' | 'class' | 'method' | 'variable' | 'import';
  line: number;
  end_line?: number;
  complexity?: number;
  parameters?: string[];
  return_type?: string;
  docstring?: string;
}

interface CodeAnalysis {
  file_path: string;
  language: string;
  symbols: CodeSymbol[];
  imports: string[];
  metrics: {
    lines_of_code: number;
    comment_lines: number;
    function_count: number;
    class_count: number;
    avg_complexity: number;
  };
  analyzed_at: string;
}

interface DeadCode {
  name: string;
  kind: string;
  file_path: string;
  line: number;
  reason: string;
}

interface CallGraphNode {
  id: string;
  name: string;
  file_path: string;
  callees: string[];
  callers: string[];
  is_entry_point: boolean;
}

interface CodeIntelligencePanelProps {
  apiBase: string;
  repoPath?: string;
}

type TabType = 'overview' | 'symbols' | 'call-graph' | 'dead-code';

export function CodeIntelligencePanel({ apiBase, repoPath }: CodeIntelligencePanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [analysis, setAnalysis] = useState<CodeAnalysis | null>(null);
  const [deadCode, setDeadCode] = useState<DeadCode[]>([]);
  const [callGraph, setCallGraph] = useState<CallGraphNode[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedFile, setSelectedFile] = useState<string>('');

  const fetchAnalysis = useCallback(
    async (filePath: string) => {
      if (!filePath) return;
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${apiBase}/api/codebase/analyze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ path: filePath }),
        });
        if (!response.ok) throw new Error('Failed to analyze file');
        const data = await response.json();
        setAnalysis(data.data);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Analysis failed');
      } finally {
        setLoading(false);
      }
    },
    [apiBase],
  );

  const fetchDeadCode = useCallback(async () => {
    if (!repoPath) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/codebase/dead-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: repoPath }),
      });
      if (!response.ok) throw new Error('Failed to find dead code');
      const data = await response.json();
      setDeadCode(data.data?.dead_code || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Dead code analysis failed');
    } finally {
      setLoading(false);
    }
  }, [apiBase, repoPath]);

  const fetchCallGraph = useCallback(async () => {
    if (!repoPath) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/codebase/callgraph`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: repoPath }),
      });
      if (!response.ok) throw new Error('Failed to build call graph');
      const data = await response.json();
      setCallGraph(data.data?.nodes || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Call graph failed');
    } finally {
      setLoading(false);
    }
  }, [apiBase, repoPath]);

  useEffect(() => {
    if (expanded && activeTab === 'dead-code') {
      fetchDeadCode();
    } else if (expanded && activeTab === 'call-graph') {
      fetchCallGraph();
    }
  }, [expanded, activeTab, fetchDeadCode, fetchCallGraph]);

  const getSymbolIcon = (kind: CodeSymbol['kind']) => {
    switch (kind) {
      case 'function':
        return 'fn';
      case 'class':
        return 'C';
      case 'method':
        return 'M';
      case 'variable':
        return 'v';
      case 'import':
        return 'i';
      default:
        return '?';
    }
  };

  const getSymbolColor = (kind: CodeSymbol['kind']) => {
    switch (kind) {
      case 'function':
        return 'text-[var(--acid-cyan)]';
      case 'class':
        return 'text-purple-400';
      case 'method':
        return 'text-[var(--accent)]';
      case 'variable':
        return 'text-yellow-400';
      case 'import':
        return 'text-text-muted';
      default:
        return 'text-text-muted';
    }
  };

  return (
    <div className="panel" style={{ padding: 0 }}>
      {/* Header */}
      <button onClick={() => setExpanded(!expanded)} className="panel-collapsible-header w-full">
        <div className="flex items-center gap-2">
          <span className="text-[var(--acid-cyan)] font-theme-data text-sm">[CODE INTEL]</span>
          <span className="text-text-muted text-xs">AST analysis & call graphs</span>
        </div>
        <span className="panel-toggle">{expanded ? '[-]' : '[+]'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {/* File Input */}
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Enter file path to analyze..."
              value={selectedFile}
              onChange={(e) => setSelectedFile(e.target.value)}
              className="flex-1 bg-bg border border-[var(--accent)]/30 px-2 py-1 text-xs font-theme-data text-text focus:border-[var(--accent)] focus:outline-none"
            />
            <button
              onClick={() => fetchAnalysis(selectedFile)}
              disabled={!selectedFile || loading}
              className="px-3 py-1 bg-[var(--accent)]/20 text-[var(--accent)] text-xs font-theme-data hover:bg-[var(--accent)]/30 disabled:opacity-50"
            >
              ANALYZE
            </button>
          </div>

          {/* Tabs */}
          <div className="flex flex-wrap gap-1 border-b border-[var(--acid-cyan)]/20 pb-2">
            {(['overview', 'symbols', 'call-graph', 'dead-code'] as TabType[]).map((tab) => (
              <button
                key={tab}
                onClick={() => setActiveTab(tab)}
                className={`px-2 py-1 text-xs font-theme-data transition-colors whitespace-nowrap ${
                  activeTab === tab
                    ? 'bg-[var(--acid-cyan)] text-bg'
                    : 'text-text-muted hover:text-[var(--acid-cyan)]'
                }`}
              >
                {tab.toUpperCase()}
              </button>
            ))}
          </div>

          {/* Content */}
          {loading ? (
            <div className="text-text-muted text-xs text-center py-4 animate-pulse">
              Analyzing code...
            </div>
          ) : error ? (
            <div className="text-warning text-xs text-center py-4">{error}</div>
          ) : (
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {activeTab === 'overview' &&
                (analysis ? (
                  <div className="space-y-3">
                    {/* File Info */}
                    <div className="border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 p-2 text-xs">
                      <div className="font-theme-data text-[var(--acid-cyan)] truncate">
                        {analysis.file_path}
                      </div>
                      <div className="text-text-muted mt-1">Language: {analysis.language}</div>
                    </div>

                    {/* Metrics Grid */}
                    <div className="grid grid-cols-3 gap-2">
                      <div className="border border-[var(--accent)]/30 bg-surface p-2 text-xs text-center">
                        <div className="text-text-muted">Lines</div>
                        <div className="text-[var(--accent)] text-lg font-theme-data">
                          {analysis.metrics.lines_of_code}
                        </div>
                      </div>
                      <div className="border border-[var(--acid-cyan)]/30 bg-surface p-2 text-xs text-center">
                        <div className="text-text-muted">Functions</div>
                        <div className="text-[var(--acid-cyan)] text-lg font-theme-data">
                          {analysis.metrics.function_count}
                        </div>
                      </div>
                      <div className="border border-purple-500/30 bg-surface p-2 text-xs text-center">
                        <div className="text-text-muted">Classes</div>
                        <div className="text-purple-400 text-lg font-theme-data">
                          {analysis.metrics.class_count}
                        </div>
                      </div>
                    </div>

                    {/* Complexity */}
                    <div className="border border-warning/30 bg-surface p-2 text-xs">
                      <div className="flex justify-between items-center">
                        <span className="text-text-muted">Avg Cyclomatic Complexity</span>
                        <span
                          className={`font-theme-data text-lg ${
                            analysis.metrics.avg_complexity > 10
                              ? 'text-warning'
                              : analysis.metrics.avg_complexity > 5
                                ? 'text-yellow-400'
                                : 'text-[var(--accent)]'
                          }`}
                        >
                          {analysis.metrics.avg_complexity.toFixed(1)}
                        </span>
                      </div>
                    </div>

                    {/* Imports */}
                    {analysis.imports.length > 0 && (
                      <div className="border border-text-muted/30 bg-surface p-2 text-xs">
                        <div className="text-text-muted mb-1">
                          Imports ({analysis.imports.length})
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {analysis.imports.slice(0, 10).map((imp, i) => (
                            <span
                              key={i}
                              className="text-[var(--acid-cyan)]/70 font-theme-data bg-[var(--acid-cyan)]/10 px-1"
                            >
                              {imp}
                            </span>
                          ))}
                          {analysis.imports.length > 10 && (
                            <span className="text-text-muted">
                              +{analysis.imports.length - 10} more
                            </span>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-text-muted text-xs text-center py-4">
                    Enter a file path and click ANALYZE to inspect code
                  </div>
                ))}

              {activeTab === 'symbols' &&
                (analysis && analysis.symbols.length > 0 ? (
                  <div className="space-y-1">
                    {analysis.symbols.map((sym, i) => (
                      <div
                        key={i}
                        className="flex items-start gap-2 border border-text-muted/20 bg-surface p-2 text-xs"
                      >
                        <span
                          className={`font-theme-data font-bold w-6 text-center ${getSymbolColor(sym.kind)}`}
                        >
                          [{getSymbolIcon(sym.kind)}]
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className={`font-theme-data truncate ${getSymbolColor(sym.kind)}`}>
                            {sym.name}
                            {sym.parameters && (
                              <span className="text-text-muted">({sym.parameters.join(', ')})</span>
                            )}
                            {sym.return_type && (
                              <span className="text-text-muted"> -&gt; {sym.return_type}</span>
                            )}
                          </div>
                          <div className="flex gap-2 text-text-muted/70 mt-0.5">
                            <span>
                              L{sym.line}
                              {sym.end_line ? `-${sym.end_line}` : ''}
                            </span>
                            {sym.complexity !== undefined && (
                              <span className={sym.complexity > 10 ? 'text-warning' : ''}>
                                complexity: {sym.complexity}
                              </span>
                            )}
                          </div>
                          {sym.docstring && (
                            <div className="text-text-muted/50 mt-1 truncate">{sym.docstring}</div>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-text-muted text-xs text-center py-4">
                    {analysis ? 'No symbols found' : 'Analyze a file to see symbols'}
                  </div>
                ))}

              {activeTab === 'call-graph' &&
                (callGraph.length > 0 ? (
                  <div className="space-y-1">
                    {callGraph.slice(0, 20).map((node) => (
                      <div
                        key={node.id}
                        className={`border p-2 text-xs ${
                          node.is_entry_point
                            ? 'border-[var(--accent)]/50 bg-[var(--accent)]/5'
                            : 'border-text-muted/20 bg-surface'
                        }`}
                      >
                        <div className="flex items-center gap-2">
                          {node.is_entry_point && (
                            <span className="text-[var(--accent)] text-[10px]">[ENTRY]</span>
                          )}
                          <span className="font-theme-data text-[var(--acid-cyan)]">
                            {node.name}
                          </span>
                        </div>
                        <div className="text-text-muted/50 text-[10px] truncate">
                          {node.file_path}
                        </div>
                        <div className="flex gap-4 mt-1 text-text-muted">
                          <span>
                            callers:{' '}
                            <span className="text-[var(--accent)]">{node.callers.length}</span>
                          </span>
                          <span>
                            callees:{' '}
                            <span className="text-[var(--acid-cyan)]">{node.callees.length}</span>
                          </span>
                        </div>
                        {node.callees.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {node.callees.slice(0, 5).map((callee, i) => (
                              <span
                                key={i}
                                className="text-[var(--acid-cyan)]/60 font-theme-data bg-[var(--acid-cyan)]/10 px-1 text-[10px]"
                              >
                                {callee}
                              </span>
                            ))}
                            {node.callees.length > 5 && (
                              <span className="text-text-muted text-[10px]">
                                +{node.callees.length - 5}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    ))}
                    {callGraph.length > 20 && (
                      <div className="text-text-muted text-xs text-center py-2">
                        Showing 20 of {callGraph.length} functions
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="text-text-muted text-xs text-center py-4">
                    {repoPath ? 'Click refresh to build call graph' : 'Set repo path to analyze'}
                  </div>
                ))}

              {activeTab === 'dead-code' &&
                (deadCode.length > 0 ? (
                  <div className="space-y-1">
                    {deadCode.map((dc, i) => (
                      <div key={i} className="border border-warning/30 bg-warning/5 p-2 text-xs">
                        <div className="flex items-center gap-2">
                          <span className="text-warning font-theme-data">{dc.name}</span>
                          <span className="text-text-muted/50 text-[10px]">{dc.kind}</span>
                        </div>
                        <div className="text-text-muted/50 text-[10px] truncate">
                          {dc.file_path}:{dc.line}
                        </div>
                        <div className="text-warning/70 mt-1 text-[10px]">{dc.reason}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="text-text-muted text-xs text-center py-4">
                    {repoPath ? 'No dead code detected' : 'Set repo path to analyze'}
                  </div>
                ))}
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-2 border-t border-text-muted/20">
            <button
              onClick={() => {
                if (activeTab === 'dead-code') fetchDeadCode();
                else if (activeTab === 'call-graph') fetchCallGraph();
                else if (selectedFile) fetchAnalysis(selectedFile);
              }}
              disabled={loading}
              className="flex-1 text-xs text-text-muted hover:text-[var(--acid-cyan)] transition-colors py-1"
            >
              [REFRESH]
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
