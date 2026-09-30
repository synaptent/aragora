'use client';

import { useState, useEffect, useCallback } from 'react';

interface SecurityFinding {
  id: string;
  severity: 'critical' | 'high' | 'medium' | 'low' | 'info';
  category: string;
  title: string;
  description: string;
  file_path: string;
  line_start: number;
  line_end?: number;
  code_snippet?: string;
  recommendation?: string;
  cwe_id?: string;
  owasp_category?: string;
}

interface SecurityReport {
  repo_path: string;
  scan_id: string;
  findings: SecurityFinding[];
  summary: {
    total: number;
    critical: number;
    high: number;
    medium: number;
    low: number;
    info: number;
  };
  scanned_files: number;
  scanned_at: string;
}

interface SecurityFindingsPanelProps {
  apiBase: string;
  repoPath?: string;
}

type FilterSeverity = 'all' | 'critical' | 'high' | 'medium' | 'low' | 'info';

export function SecurityFindingsPanel({ apiBase, repoPath }: SecurityFindingsPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const [report, setReport] = useState<SecurityReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState(repoPath || '');
  const [filter, setFilter] = useState<FilterSeverity>('all');
  const [expandedFindings, setExpandedFindings] = useState<Set<string>>(new Set());

  const runSecurityScan = useCallback(async () => {
    if (!selectedPath) return;
    setLoading(true);
    setError(null);
    try {
      const response = await fetch(`${apiBase}/api/codebase/audit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ repo_path: selectedPath }),
      });
      if (!response.ok) throw new Error('Security scan failed');
      const data = await response.json();
      setReport(data.data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Scan failed');
    } finally {
      setLoading(false);
    }
  }, [apiBase, selectedPath]);

  useEffect(() => {
    if (repoPath) {
      setSelectedPath(repoPath);
    }
  }, [repoPath]);

  const getSeverityColor = (severity: SecurityFinding['severity']) => {
    switch (severity) {
      case 'critical':
        return 'text-red-500 border-red-500/50 bg-red-500/10';
      case 'high':
        return 'text-orange-500 border-orange-500/50 bg-orange-500/10';
      case 'medium':
        return 'text-yellow-500 border-yellow-500/50 bg-yellow-500/10';
      case 'low':
        return 'text-blue-400 border-blue-400/50 bg-blue-400/10';
      case 'info':
        return 'text-text-muted border-text-muted/50 bg-text-muted/10';
      default:
        return 'text-text-muted border-text-muted/50';
    }
  };

  const getSeverityBadgeColor = (severity: SecurityFinding['severity']) => {
    switch (severity) {
      case 'critical':
        return 'bg-red-500';
      case 'high':
        return 'bg-orange-500';
      case 'medium':
        return 'bg-yellow-500';
      case 'low':
        return 'bg-blue-400';
      case 'info':
        return 'bg-text-muted';
      default:
        return 'bg-text-muted';
    }
  };

  const filteredFindings =
    report?.findings.filter((f) => filter === 'all' || f.severity === filter) || [];

  const toggleFinding = (id: string) => {
    const newExpanded = new Set(expandedFindings);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedFindings(newExpanded);
  };

  return (
    <div className="panel" style={{ padding: 0 }}>
      {/* Header */}
      <button onClick={() => setExpanded(!expanded)} className="panel-collapsible-header w-full">
        <div className="flex items-center gap-2">
          <span className="text-warning font-theme-data text-sm">[SECURITY]</span>
          <span className="text-text-muted text-xs">Vulnerability scanner</span>
          {report && report.summary.critical + report.summary.high > 0 && (
            <span className="bg-red-500 text-white text-[10px] px-1 rounded">
              {report.summary.critical + report.summary.high} issues
            </span>
          )}
        </div>
        <span className="panel-toggle">{expanded ? '[-]' : '[+]'}</span>
      </button>

      {expanded && (
        <div className="px-4 pb-4 space-y-3">
          {/* Scan Input */}
          <div className="flex gap-2">
            <input
              type="text"
              placeholder="Enter repository path..."
              value={selectedPath}
              onChange={(e) => setSelectedPath(e.target.value)}
              className="flex-1 bg-bg border border-warning/30 px-2 py-1 text-xs font-theme-data text-text focus:border-warning focus:outline-none"
            />
            <button
              onClick={runSecurityScan}
              disabled={!selectedPath || loading}
              className="px-3 py-1 bg-warning/20 text-warning text-xs font-theme-data hover:bg-warning/30 disabled:opacity-50"
            >
              {loading ? 'SCANNING...' : 'SCAN'}
            </button>
          </div>

          {/* Error */}
          {error && (
            <div className="text-warning text-xs text-center py-2 border border-warning/30 bg-warning/5">
              {error}
            </div>
          )}

          {/* Report */}
          {report && (
            <>
              {/* Summary */}
              <div className="grid grid-cols-5 gap-1 text-xs">
                {(['critical', 'high', 'medium', 'low', 'info'] as const).map((sev) => (
                  <button
                    key={sev}
                    onClick={() => setFilter(filter === sev ? 'all' : sev)}
                    className={`p-2 text-center border transition-all ${
                      filter === sev
                        ? getSeverityColor(sev) + ' ring-1 ring-current'
                        : 'border-text-muted/20 bg-surface hover:border-text-muted/40'
                    }`}
                  >
                    <div
                      className={`text-lg font-theme-data font-bold ${
                        filter === sev
                          ? ''
                          : sev === 'critical'
                            ? 'text-red-500'
                            : sev === 'high'
                              ? 'text-orange-500'
                              : sev === 'medium'
                                ? 'text-yellow-500'
                                : sev === 'low'
                                  ? 'text-blue-400'
                                  : 'text-text-muted'
                      }`}
                    >
                      {report.summary[sev]}
                    </div>
                    <div className="text-[10px] text-text-muted uppercase">{sev}</div>
                  </button>
                ))}
              </div>

              {/* Stats Bar */}
              <div className="flex justify-between text-xs text-text-muted border-b border-text-muted/20 pb-2">
                <span>Scanned: {report.scanned_files} files</span>
                <span>Total: {report.summary.total} findings</span>
                {filter !== 'all' && (
                  <button
                    onClick={() => setFilter('all')}
                    className="text-[var(--acid-cyan)] hover:underline"
                  >
                    Clear filter
                  </button>
                )}
              </div>

              {/* Findings List */}
              <div className="space-y-2 max-h-80 overflow-y-auto">
                {filteredFindings.length === 0 ? (
                  <div className="text-[var(--accent)] text-xs text-center py-4">
                    {filter === 'all'
                      ? 'No security issues found!'
                      : `No ${filter} severity issues`}
                  </div>
                ) : (
                  filteredFindings.map((finding) => (
                    <div
                      key={finding.id}
                      className={`border ${getSeverityColor(finding.severity)} text-xs`}
                    >
                      {/* Finding Header */}
                      <button
                        onClick={() => toggleFinding(finding.id)}
                        className="w-full p-2 text-left flex items-start gap-2"
                      >
                        <span
                          className={`${getSeverityBadgeColor(finding.severity)} text-white text-[10px] px-1 uppercase font-bold`}
                        >
                          {finding.severity}
                        </span>
                        <div className="flex-1 min-w-0">
                          <div className="font-theme-data font-medium">{finding.title}</div>
                          <div className="text-text-muted/60 text-[10px] truncate">
                            {finding.file_path}:{finding.line_start}
                            {finding.cwe_id && ` | CWE-${finding.cwe_id}`}
                          </div>
                        </div>
                        <span className="text-text-muted">
                          {expandedFindings.has(finding.id) ? '[-]' : '[+]'}
                        </span>
                      </button>

                      {/* Finding Details */}
                      {expandedFindings.has(finding.id) && (
                        <div className="px-2 pb-2 space-y-2 border-t border-current/20">
                          <div className="text-text-muted mt-2">{finding.description}</div>

                          {finding.code_snippet && (
                            <div className="bg-bg p-2 font-theme-data text-[10px] overflow-x-auto">
                              <pre className="whitespace-pre">{finding.code_snippet}</pre>
                            </div>
                          )}

                          {finding.recommendation && (
                            <div className="border-l-2 border-[var(--accent)]/50 pl-2">
                              <div className="text-[var(--accent)] text-[10px] font-bold">
                                Recommendation
                              </div>
                              <div className="text-text-muted">{finding.recommendation}</div>
                            </div>
                          )}

                          <div className="flex gap-3 text-[10px] text-text-muted/50">
                            <span>Category: {finding.category}</span>
                            {finding.owasp_category && <span>OWASP: {finding.owasp_category}</span>}
                          </div>
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </>
          )}

          {/* Initial State */}
          {!report && !loading && !error && (
            <div className="text-text-muted text-xs text-center py-4">
              Enter a repository path and click SCAN to check for vulnerabilities
            </div>
          )}

          {/* Loading State */}
          {loading && (
            <div className="text-warning text-xs text-center py-4 animate-pulse">
              Scanning for security vulnerabilities...
            </div>
          )}
        </div>
      )}
    </div>
  );
}
