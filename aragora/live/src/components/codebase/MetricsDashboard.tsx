'use client';

import { useState, useEffect, useCallback } from 'react';

// Types matching backend models
interface FunctionMetrics {
  name: string;
  start_line: number;
  end_line: number;
  lines_of_code: number;
  cyclomatic_complexity: number;
  cognitive_complexity: number;
  parameter_count: number;
  nested_depth: number;
}

interface _FileMetrics {
  file_path: string;
  language: string;
  lines_of_code: number;
  lines_of_comments: number;
  blank_lines: number;
  classes: number;
  imports: number;
  avg_complexity: number;
  max_complexity: number;
  maintainability_index: number;
  functions: FunctionMetrics[];
}

interface HotspotFinding {
  file_path: string;
  function_name?: string;
  class_name?: string;
  start_line: number;
  end_line: number;
  complexity: number;
  lines_of_code: number;
  cognitive_complexity?: number;
  change_frequency: number;
  contributors: string[];
  risk_score: number;
}

interface DuplicateOccurrence {
  file: string;
  start: number;
  end: number;
}

interface DuplicateBlock {
  hash: string;
  lines: number;
  occurrences: DuplicateOccurrence[];
}

interface MetricsSummary {
  total_files: number;
  total_lines: number;
  total_code_lines: number;
  total_comment_lines: number;
  total_blank_lines: number;
  total_functions: number;
  total_classes: number;
  avg_complexity: number;
  max_complexity: number;
  maintainability_index: number;
}

interface MetricsReport {
  repository: string;
  scan_id: string;
  scanned_at: string;
  summary: MetricsSummary;
  hotspots: HotspotFinding[];
  duplicates: DuplicateBlock[];
  metrics: Array<{
    type: string;
    value: number;
    unit: string;
    status: string;
    details?: Record<string, unknown>;
  }>;
}

interface MetricsDashboardProps {
  apiBase: string;
  workspaceId: string;
  repositoryId?: string;
  authToken?: string;
}

// Demo data
const DEMO_REPORT: MetricsReport = {
  repository: 'aragora/main',
  scan_id: 'metrics_demo_001',
  scanned_at: new Date().toISOString(),
  summary: {
    total_files: 142,
    total_lines: 28450,
    total_code_lines: 21200,
    total_comment_lines: 4120,
    total_blank_lines: 3130,
    total_functions: 485,
    total_classes: 62,
    avg_complexity: 4.2,
    max_complexity: 18,
    maintainability_index: 72.5,
  },
  hotspots: [
    {
      file_path: 'src/services/auth.ts',
      function_name: 'validateAndRefreshToken',
      start_line: 45,
      end_line: 145,
      complexity: 15,
      lines_of_code: 100,
      cognitive_complexity: 22,
      change_frequency: 18,
      contributors: ['alice', 'bob'],
      risk_score: 78,
    },
    {
      file_path: 'src/handlers/webhook.ts',
      function_name: 'processPayload',
      start_line: 10,
      end_line: 95,
      complexity: 12,
      lines_of_code: 85,
      cognitive_complexity: 18,
      change_frequency: 15,
      contributors: ['carol'],
      risk_score: 65,
    },
    {
      file_path: 'src/utils/parser.py',
      function_name: 'parse_config',
      start_line: 1,
      end_line: 60,
      complexity: 8,
      lines_of_code: 60,
      cognitive_complexity: 12,
      change_frequency: 8,
      contributors: ['alice', 'dave'],
      risk_score: 45,
    },
  ],
  duplicates: [
    {
      hash: 'a1b2c3d4',
      lines: 12,
      occurrences: [
        { file: 'src/components/Button.tsx', start: 15, end: 27 },
        { file: 'src/components/IconButton.tsx', start: 10, end: 22 },
        { file: 'src/components/LinkButton.tsx', start: 8, end: 20 },
      ],
    },
    {
      hash: 'e5f6g7h8',
      lines: 8,
      occurrences: [
        { file: 'src/api/users.ts', start: 45, end: 53 },
        { file: 'src/api/teams.ts', start: 38, end: 46 },
      ],
    },
  ],
  metrics: [
    { type: 'complexity', value: 4.2, unit: 'cyclomatic', status: 'ok', details: { max: 18 } },
    { type: 'maintainability', value: 72.5, unit: 'index', status: 'ok' },
    {
      type: 'lines_of_code',
      value: 21200,
      unit: 'lines',
      status: 'ok',
      details: { comments: 4120, blank: 3130, total: 28450 },
    },
    { type: 'documentation', value: 19.4, unit: 'percent', status: 'ok' },
    {
      type: 'duplication',
      value: 2.3,
      unit: 'percent',
      status: 'ok',
      details: { duplicate_blocks: 2 },
    },
  ],
};

type TabType = 'overview' | 'hotspots' | 'duplicates' | 'files';

const getStatusColor = (status: string): string => {
  switch (status) {
    case 'ok':
      return 'text-green-400';
    case 'warning':
      return 'text-yellow-400';
    case 'error':
      return 'text-red-400';
    default:
      return 'text-gray-400';
  }
};

const getRiskColor = (score: number): string => {
  if (score >= 70) return 'text-red-400';
  if (score >= 50) return 'text-orange-400';
  if (score >= 30) return 'text-yellow-400';
  return 'text-green-400';
};

const getMIColor = (mi: number): string => {
  if (mi >= 80) return 'text-green-400';
  if (mi >= 65) return 'text-yellow-400';
  if (mi >= 50) return 'text-orange-400';
  return 'text-red-400';
};

export function MetricsDashboard({
  apiBase,
  workspaceId: _workspaceId,
  repositoryId,
  authToken,
}: MetricsDashboardProps) {
  const [activeTab, setActiveTab] = useState<TabType>('overview');
  const [report, setReport] = useState<MetricsReport | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedFile, setExpandedFile] = useState<string | null>(null);

  const fetchMetrics = useCallback(async () => {
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(
        `${apiBase}/api/v1/codebase/${repositoryId || 'default'}/metrics`,
        { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} },
      );

      if (!response.ok) {
        setReport(DEMO_REPORT);
        return;
      }

      const data = await response.json();
      setReport(data.report);
    } catch {
      setReport(DEMO_REPORT);
    } finally {
      setIsLoading(false);
    }
  }, [apiBase, repositoryId, authToken]);

  const triggerAnalysis = async () => {
    setIsAnalyzing(true);
    setError(null);

    try {
      const response = await fetch(
        `${apiBase}/api/v1/codebase/${repositoryId || 'default'}/metrics/analyze`,
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            ...(authToken ? { Authorization: `Bearer ${authToken}` } : {}),
          },
          body: JSON.stringify({ repo_path: '.' }),
        },
      );

      if (!response.ok) {
        setTimeout(() => {
          setReport({
            ...DEMO_REPORT,
            scan_id: `metrics_${Date.now()}`,
            scanned_at: new Date().toISOString(),
          });
          setIsAnalyzing(false);
        }, 2000);
        return;
      }

      // Poll for completion
      const pollInterval = setInterval(async () => {
        const statusResponse = await fetch(
          `${apiBase}/api/v1/codebase/${repositoryId || 'default'}/metrics`,
          { headers: authToken ? { Authorization: `Bearer ${authToken}` } : {} },
        );

        if (statusResponse.ok) {
          const data = await statusResponse.json();
          if (data.report) {
            clearInterval(pollInterval);
            setReport(data.report);
            setIsAnalyzing(false);
          }
        }
      }, 2000);

      setTimeout(() => {
        clearInterval(pollInterval);
        setIsAnalyzing(false);
      }, 300000);
    } catch {
      setError('Failed to trigger analysis');
      setIsAnalyzing(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
  }, [fetchMetrics]);

  const formatNumber = (num: number): string => {
    if (num >= 1000000) return `${(num / 1000000).toFixed(1)}M`;
    if (num >= 1000) return `${(num / 1000).toFixed(1)}K`;
    return num.toString();
  };

  const formatTimeAgo = (dateString: string): string => {
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now.getTime() - date.getTime();
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMins / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    return `${diffDays}d ago`;
  };

  if (isLoading) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/50 p-4 rounded">
        <div className="text-center py-8 text-text-muted font-theme-data text-sm animate-pulse">
          Loading metrics dashboard...
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="border-b border-[var(--accent)]/30 p-4 bg-surface/50">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-theme-data text-[var(--accent)]">Code Metrics</h2>
            {report && (
              <div className="text-xs text-text-muted mt-1">
                Repository: <span className="text-[var(--acid-cyan)]">{report.repository}</span>
              </div>
            )}
          </div>
          <div className="flex items-center gap-3">
            {report && (
              <div className="text-xs text-text-muted">
                Last analysis: {formatTimeAgo(report.scanned_at)}
              </div>
            )}
            <button
              onClick={triggerAnalysis}
              disabled={isAnalyzing}
              className={`px-4 py-2 text-sm font-theme-data rounded transition-colors ${
                isAnalyzing
                  ? 'bg-[var(--accent)]/20 text-[var(--accent)]/50 cursor-not-allowed'
                  : 'bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80'
              }`}
            >
              {isAnalyzing ? 'Analyzing...' : 'Run Analysis'}
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex gap-2">
          {(['overview', 'hotspots', 'duplicates', 'files'] as TabType[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-4 py-2 text-sm font-theme-data rounded-t transition-colors ${
                activeTab === tab
                  ? 'bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] border-b-0'
                  : 'bg-surface/50 border border-[var(--accent)]/30 text-text-muted hover:text-[var(--accent)]'
              }`}
            >
              {tab.charAt(0).toUpperCase() + tab.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {error && (
        <div className="p-3 bg-red-500/10 border-b border-red-500/30 text-red-400 text-sm font-theme-data">
          {error}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4">
        {/* Overview Tab */}
        {activeTab === 'overview' && report && (
          <div className="space-y-6">
            {/* Key Metrics Cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30">
                <div className="text-2xl font-theme-data text-[var(--accent)]">
                  {formatNumber(report.summary.total_files)}
                </div>
                <div className="text-xs text-text-muted mt-1">Total Files</div>
              </div>
              <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30">
                <div className="text-2xl font-theme-data text-[var(--acid-cyan)]">
                  {formatNumber(report.summary.total_code_lines)}
                </div>
                <div className="text-xs text-text-muted mt-1">Lines of Code</div>
              </div>
              <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30">
                <div className="text-2xl font-theme-data text-purple-400">
                  {report.summary.total_functions}
                </div>
                <div className="text-xs text-text-muted mt-1">Functions</div>
              </div>
              <div className="p-4 border border-[var(--accent)]/30 rounded bg-surface/30">
                <div className="text-2xl font-theme-data text-blue-400">
                  {report.summary.total_classes}
                </div>
                <div className="text-xs text-text-muted mt-1">Classes</div>
              </div>
            </div>

            {/* Maintainability Index */}
            <div className="border border-[var(--accent)]/30 rounded p-4 bg-surface/30">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
                Maintainability Index
              </h3>
              <div className="flex items-center gap-6">
                <div
                  className={`text-5xl font-theme-data ${getMIColor(report.summary.maintainability_index)}`}
                >
                  {report.summary.maintainability_index.toFixed(1)}
                </div>
                <div className="flex-1">
                  <div className="h-4 bg-surface rounded-full overflow-hidden">
                    <div
                      className={`h-full transition-all ${
                        report.summary.maintainability_index >= 80
                          ? 'bg-green-500'
                          : report.summary.maintainability_index >= 65
                            ? 'bg-yellow-500'
                            : report.summary.maintainability_index >= 50
                              ? 'bg-orange-500'
                              : 'bg-red-500'
                      }`}
                      style={{ width: `${report.summary.maintainability_index}%` }}
                    />
                  </div>
                  <div className="flex justify-between text-xs text-text-muted mt-1">
                    <span>Poor (0)</span>
                    <span>Fair (50)</span>
                    <span>Good (65)</span>
                    <span>Excellent (100)</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Complexity */}
            <div className="border border-[var(--accent)]/30 rounded p-4 bg-surface/30">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">Complexity</h3>
              <div className="grid grid-cols-2 gap-8">
                <div>
                  <div className="text-xs text-text-muted mb-1">Average Cyclomatic</div>
                  <div className="text-3xl font-theme-data text-[var(--acid-cyan)]">
                    {report.summary.avg_complexity.toFixed(1)}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-text-muted mb-1">Maximum Complexity</div>
                  <div
                    className={`text-3xl font-theme-data ${
                      report.summary.max_complexity > 20
                        ? 'text-red-400'
                        : report.summary.max_complexity > 10
                          ? 'text-yellow-400'
                          : 'text-green-400'
                    }`}
                  >
                    {report.summary.max_complexity}
                  </div>
                </div>
              </div>
            </div>

            {/* All Metrics */}
            <div className="border border-[var(--accent)]/30 rounded p-4 bg-surface/30">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">Quality Metrics</h3>
              <div className="space-y-3">
                {report.metrics.map((metric, idx) => (
                  <div key={idx} className="flex items-center justify-between p-2 bg-bg/30 rounded">
                    <div className="flex items-center gap-3">
                      <span
                        className={`w-2 h-2 rounded-full ${
                          metric.status === 'ok'
                            ? 'bg-green-500'
                            : metric.status === 'warning'
                              ? 'bg-yellow-500'
                              : 'bg-red-500'
                        }`}
                      />
                      <span className="text-sm capitalize">{metric.type.replace(/_/g, ' ')}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`font-theme-data ${getStatusColor(metric.status)}`}>
                        {metric.value.toFixed(1)}
                      </span>
                      <span className="text-xs text-text-muted">{metric.unit}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Quick Stats */}
            <div className="grid grid-cols-3 gap-4">
              <div className="border border-[var(--accent)]/30 rounded p-3 bg-surface/30 text-center">
                <div className="text-lg font-theme-data text-[var(--accent)]">
                  {report.hotspots.length}
                </div>
                <div className="text-xs text-text-muted">Hotspots</div>
              </div>
              <div className="border border-[var(--accent)]/30 rounded p-3 bg-surface/30 text-center">
                <div className="text-lg font-theme-data text-orange-400">
                  {report.duplicates.length}
                </div>
                <div className="text-xs text-text-muted">Duplicate Blocks</div>
              </div>
              <div className="border border-[var(--accent)]/30 rounded p-3 bg-surface/30 text-center">
                <div className="text-lg font-theme-data text-blue-400">
                  {(
                    (report.summary.total_comment_lines / report.summary.total_code_lines) *
                    100
                  ).toFixed(1)}
                  %
                </div>
                <div className="text-xs text-text-muted">Documentation</div>
              </div>
            </div>
          </div>
        )}

        {/* Hotspots Tab */}
        {activeTab === 'hotspots' && report && (
          <div className="space-y-4">
            <p className="text-sm text-text-muted mb-4">
              Complexity hotspots are high-risk areas that may benefit from refactoring.
            </p>

            {report.hotspots.length === 0 ? (
              <div className="text-center py-8 text-text-muted font-theme-data text-sm">
                No complexity hotspots detected.
              </div>
            ) : (
              <div className="space-y-3">
                {report.hotspots.map((hotspot, idx) => (
                  <div
                    key={idx}
                    className="border border-[var(--accent)]/30 rounded p-4 bg-surface/30"
                  >
                    <div className="flex items-start justify-between mb-3">
                      <div>
                        <div className="font-theme-data text-sm text-[var(--acid-cyan)]">
                          {hotspot.file_path}:{hotspot.start_line}-{hotspot.end_line}
                        </div>
                        {hotspot.function_name && (
                          <div className="text-xs text-text-muted mt-1">
                            Function:{' '}
                            <span className="text-[var(--accent)]">{hotspot.function_name}</span>
                            {hotspot.class_name && (
                              <span className="ml-2">in {hotspot.class_name}</span>
                            )}
                          </div>
                        )}
                      </div>
                      <div className="text-right">
                        <div
                          className={`text-2xl font-theme-data ${getRiskColor(hotspot.risk_score)}`}
                        >
                          {hotspot.risk_score.toFixed(0)}
                        </div>
                        <div className="text-xs text-text-muted">Risk Score</div>
                      </div>
                    </div>

                    <div className="grid grid-cols-4 gap-4 text-sm">
                      <div>
                        <div className="text-text-muted text-xs">Cyclomatic</div>
                        <div
                          className={`font-theme-data ${
                            hotspot.complexity > 15
                              ? 'text-red-400'
                              : hotspot.complexity > 10
                                ? 'text-yellow-400'
                                : 'text-green-400'
                          }`}
                        >
                          {hotspot.complexity}
                        </div>
                      </div>
                      <div>
                        <div className="text-text-muted text-xs">Cognitive</div>
                        <div className="font-theme-data">
                          {hotspot.cognitive_complexity || 'N/A'}
                        </div>
                      </div>
                      <div>
                        <div className="text-text-muted text-xs">Lines</div>
                        <div className="font-theme-data">{hotspot.lines_of_code}</div>
                      </div>
                      <div>
                        <div className="text-text-muted text-xs">Changes</div>
                        <div className="font-theme-data">{hotspot.change_frequency}</div>
                      </div>
                    </div>

                    {hotspot.contributors.length > 0 && (
                      <div className="mt-3 flex items-center gap-2">
                        <span className="text-xs text-text-muted">Contributors:</span>
                        {hotspot.contributors.map((contributor) => (
                          <span
                            key={contributor}
                            className="px-2 py-0.5 text-xs bg-[var(--accent)]/10 text-[var(--accent)] rounded"
                          >
                            {contributor}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Duplicates Tab */}
        {activeTab === 'duplicates' && report && (
          <div className="space-y-4">
            <p className="text-sm text-text-muted mb-4">
              Code duplicates can increase maintenance burden and bug risk.
            </p>

            {report.duplicates.length === 0 ? (
              <div className="text-center py-8 text-text-muted font-theme-data text-sm">
                No significant code duplication detected.
              </div>
            ) : (
              <div className="space-y-3">
                {report.duplicates.map((dup, idx) => {
                  const isExpanded = expandedFile === dup.hash;

                  return (
                    <div key={idx} className="border border-orange-500/30 rounded bg-surface/30">
                      <button
                        onClick={() => setExpandedFile(isExpanded ? null : dup.hash)}
                        className="w-full p-4 text-left"
                      >
                        <div className="flex items-center justify-between">
                          <div className="flex items-center gap-3">
                            <span className="px-2 py-0.5 text-xs bg-orange-500/20 text-orange-400 rounded">
                              {dup.lines} lines
                            </span>
                            <span className="text-sm font-theme-data">
                              Duplicated in {dup.occurrences.length} locations
                            </span>
                          </div>
                          <span className="text-xs text-text-muted">
                            {isExpanded ? '[-]' : '[+]'}
                          </span>
                        </div>
                      </button>

                      {isExpanded && (
                        <div className="px-4 pb-4 border-t border-[var(--accent)]/20 pt-3">
                          <div className="space-y-2">
                            {dup.occurrences.map((occ, occIdx) => (
                              <div
                                key={occIdx}
                                className="flex items-center justify-between p-2 bg-bg/30 rounded text-sm"
                              >
                                <span className="font-theme-data text-[var(--acid-cyan)]">
                                  {occ.file}
                                </span>
                                <span className="text-text-muted">
                                  Lines {occ.start}-{occ.end}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {/* Files Tab */}
        {activeTab === 'files' && report && (
          <div className="space-y-4">
            <p className="text-sm text-text-muted mb-4">Line count breakdown by category.</p>

            {/* Line Distribution */}
            <div className="border border-[var(--accent)]/30 rounded p-4 bg-surface/30">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-4">
                Line Distribution
              </h3>
              <div className="flex h-8 rounded overflow-hidden mb-3">
                <div
                  className="bg-[var(--accent)]"
                  style={{
                    width: `${(report.summary.total_code_lines / report.summary.total_lines) * 100}%`,
                  }}
                  title={`Code: ${formatNumber(report.summary.total_code_lines)}`}
                />
                <div
                  className="bg-blue-500"
                  style={{
                    width: `${(report.summary.total_comment_lines / report.summary.total_lines) * 100}%`,
                  }}
                  title={`Comments: ${formatNumber(report.summary.total_comment_lines)}`}
                />
                <div
                  className="bg-gray-600"
                  style={{
                    width: `${(report.summary.total_blank_lines / report.summary.total_lines) * 100}%`,
                  }}
                  title={`Blank: ${formatNumber(report.summary.total_blank_lines)}`}
                />
              </div>
              <div className="flex gap-4 text-xs">
                <div className="flex items-center gap-1">
                  <span className="w-3 h-3 bg-[var(--accent)] rounded" />
                  <span>Code ({formatNumber(report.summary.total_code_lines)})</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="w-3 h-3 bg-blue-500 rounded" />
                  <span>Comments ({formatNumber(report.summary.total_comment_lines)})</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="w-3 h-3 bg-gray-600 rounded" />
                  <span>Blank ({formatNumber(report.summary.total_blank_lines)})</span>
                </div>
              </div>
            </div>

            {/* Analysis Details */}
            <div className="border border-[var(--accent)]/30 rounded p-4 bg-surface/30">
              <h3 className="text-sm font-theme-data text-[var(--accent)] mb-3">
                Analysis Details
              </h3>
              <div className="grid grid-cols-2 gap-4 text-sm">
                <div>
                  <span className="text-text-muted">Analysis ID:</span>
                  <span className="ml-2 font-theme-data">{report.scan_id}</span>
                </div>
                <div>
                  <span className="text-text-muted">Scanned:</span>
                  <span className="ml-2">{new Date(report.scanned_at).toLocaleString()}</span>
                </div>
                <div>
                  <span className="text-text-muted">Total Lines:</span>
                  <span className="ml-2 font-theme-data">
                    {formatNumber(report.summary.total_lines)}
                  </span>
                </div>
                <div>
                  <span className="text-text-muted">Files Analyzed:</span>
                  <span className="ml-2 font-theme-data">{report.summary.total_files}</span>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default MetricsDashboard;
