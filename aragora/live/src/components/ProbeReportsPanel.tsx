'use client';

import { useState, useEffect, useCallback } from 'react';
import { withErrorBoundary } from './PanelErrorBoundary';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { logger } from '@/utils/logger';

interface ProbeReportSummary {
  report_id: string;
  target_agent: string;
  probes_run: number;
  vulnerabilities_found: number;
  vulnerability_rate: number;
  created_at: string;
  file_name: string;
}

interface ProbeResult {
  probe_id: string;
  type: string;
  passed: boolean;
  severity?: string;
  description: string;
  details?: string;
  response_time_ms?: number;
}

interface ProbeReport {
  report_id: string;
  target_agent: string;
  probes_run: number;
  vulnerabilities_found: number;
  vulnerability_rate: number;
  elo_penalty: number;
  by_type: Record<string, ProbeResult[]>;
  summary: {
    total: number;
    passed: number;
    failed: number;
    pass_rate: number;
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
  recommendations: string[];
  created_at: string;
}

interface ProbeReportsPanelProps {
  apiBase?: string;
  agentFilter?: string;
}

const DEFAULT_API_BASE = API_BASE_URL;

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'text-red-500',
  high: 'text-orange-400',
  medium: 'text-yellow-400',
  low: 'text-blue-400',
};

function ProbeReportsPanelInner({
  apiBase = DEFAULT_API_BASE,
  agentFilter,
}: ProbeReportsPanelProps) {
  const [reports, setReports] = useState<ProbeReportSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedReport, setSelectedReport] = useState<ProbeReport | null>(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [offset, setOffset] = useState(0);
  const limit = 20;

  const fetchReports = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      let url = `${apiBase}/api/probes/reports?limit=${limit}&offset=${offset}`;
      if (agentFilter) {
        url += `&agent=${encodeURIComponent(agentFilter)}`;
      }
      const response = await fetchWithRetry(url);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      setReports(data.reports || []);
      setTotal(data.total || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load reports');
    } finally {
      setLoading(false);
    }
  }, [apiBase, agentFilter, offset]);

  const fetchReportDetails = useCallback(
    async (reportId: string) => {
      setLoadingDetails(true);
      try {
        const response = await fetchWithRetry(`${apiBase}/api/probes/reports/${reportId}`);
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const data: ProbeReport = await response.json();
        setSelectedReport(data);
      } catch (err) {
        logger.error('Failed to load report details:', err);
      } finally {
        setLoadingDetails(false);
      }
    },
    [apiBase],
  );

  useEffect(() => {
    fetchReports();
  }, [fetchReports]);

  const formatDate = (dateStr: string) => {
    if (!dateStr) return 'Unknown';
    const date = new Date(dateStr);
    return date.toLocaleDateString() + ' ' + date.toLocaleTimeString();
  };

  const getPassRateColor = (rate: number) => {
    if (rate >= 0.9) return 'text-green-400';
    if (rate >= 0.7) return 'text-yellow-400';
    if (rate >= 0.5) return 'text-orange-400';
    return 'text-red-400';
  };

  return (
    <div className="font-theme-data text-sm">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-green-400 text-lg">PROBE REPORTS</h3>
        <button
          onClick={() => fetchReports()}
          disabled={loading}
          className="px-3 py-1 border border-green-500/30 hover:bg-green-500/10 text-green-400 disabled:opacity-50"
        >
          {loading ? 'Loading...' : 'Refresh'}
        </button>
      </div>

      {error && (
        <div className="p-2 mb-4 border border-red-500/30 bg-red-500/10 text-red-400">
          Error: {error}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Reports List */}
        <div className="space-y-2">
          {reports.length === 0 && !loading && (
            <div className="text-gray-500 text-center py-8">No probe reports found</div>
          )}

          {reports.map((report) => (
            <div
              key={report.report_id}
              onClick={() => fetchReportDetails(report.report_id)}
              className={`p-3 border cursor-pointer transition-colors ${
                selectedReport?.report_id === report.report_id
                  ? 'border-green-500/50 bg-green-500/10'
                  : 'border-green-500/20 hover:border-green-500/40'
              }`}
            >
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-white/80">{report.target_agent}</div>
                  <div className="text-gray-500 text-xs">{formatDate(report.created_at)}</div>
                </div>
                <div className="text-right">
                  <div className={getPassRateColor(1 - report.vulnerability_rate)}>
                    {((1 - report.vulnerability_rate) * 100).toFixed(0)}% pass
                  </div>
                  <div className="text-gray-500 text-xs">{report.probes_run} probes</div>
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Report Details */}
        <div className="border border-green-500/20 p-4">
          {loadingDetails ? (
            <div className="text-gray-500 text-center py-8">Loading...</div>
          ) : selectedReport ? (
            <div className="space-y-4">
              <div>
                <div className="text-green-400 text-lg mb-2">{selectedReport.target_agent}</div>
                <div className="text-gray-500 text-xs">{formatDate(selectedReport.created_at)}</div>
              </div>

              {/* Summary Stats */}
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div className="p-2 bg-green-500/10 border border-green-500/20">
                  <div className="text-gray-500">Total Probes</div>
                  <div className="text-white text-lg">{selectedReport.summary.total}</div>
                </div>
                <div className="p-2 bg-green-500/10 border border-green-500/20">
                  <div className="text-gray-500">Pass Rate</div>
                  <div className={`text-lg ${getPassRateColor(selectedReport.summary.pass_rate)}`}>
                    {(selectedReport.summary.pass_rate * 100).toFixed(0)}%
                  </div>
                </div>
                <div className="p-2 bg-red-500/10 border border-red-500/20">
                  <div className="text-gray-500">ELO Penalty</div>
                  <div className="text-red-400 text-lg">
                    -{selectedReport.elo_penalty.toFixed(1)}
                  </div>
                </div>
                <div className="p-2 bg-yellow-500/10 border border-yellow-500/20">
                  <div className="text-gray-500">Vulnerabilities</div>
                  <div className="text-yellow-400 text-lg">
                    {selectedReport.vulnerabilities_found}
                  </div>
                </div>
              </div>

              {/* Severity Breakdown */}
              {(selectedReport.summary.critical > 0 ||
                selectedReport.summary.high > 0 ||
                selectedReport.summary.medium > 0 ||
                selectedReport.summary.low > 0) && (
                <div className="flex gap-4 text-xs">
                  {selectedReport.summary.critical > 0 && (
                    <span className="text-red-500">
                      Critical: {selectedReport.summary.critical}
                    </span>
                  )}
                  {selectedReport.summary.high > 0 && (
                    <span className="text-orange-400">High: {selectedReport.summary.high}</span>
                  )}
                  {selectedReport.summary.medium > 0 && (
                    <span className="text-yellow-400">Medium: {selectedReport.summary.medium}</span>
                  )}
                  {selectedReport.summary.low > 0 && (
                    <span className="text-blue-400">Low: {selectedReport.summary.low}</span>
                  )}
                </div>
              )}

              {/* Results by Type */}
              <div className="space-y-2">
                <div className="text-gray-500">Results by Type:</div>
                {Object.entries(selectedReport.by_type).map(([type, results]) => (
                  <div key={type} className="border border-green-500/10 p-2">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-white/80 capitalize">{type.replace('_', ' ')}</span>
                      <span
                        className={getPassRateColor(
                          results.filter((r) => r.passed).length / results.length,
                        )}
                      >
                        {results.filter((r) => r.passed).length}/{results.length} passed
                      </span>
                    </div>
                    <div className="space-y-1">
                      {results.slice(0, 3).map((result) => (
                        <div key={result.probe_id} className="text-xs flex items-start gap-2">
                          <span className={result.passed ? 'text-green-400' : 'text-red-400'}>
                            {result.passed ? '✓' : '✗'}
                          </span>
                          <span className="text-gray-400">{result.description}</span>
                          {result.severity && (
                            <span className={SEVERITY_COLORS[result.severity] || 'text-gray-500'}>
                              [{result.severity}]
                            </span>
                          )}
                        </div>
                      ))}
                      {results.length > 3 && (
                        <div className="text-gray-500 text-xs">+{results.length - 3} more</div>
                      )}
                    </div>
                  </div>
                ))}
              </div>

              {/* Recommendations */}
              {selectedReport.recommendations.length > 0 && (
                <div className="space-y-1">
                  <div className="text-gray-500">Recommendations:</div>
                  {selectedReport.recommendations.map((rec, i) => (
                    <div key={i} className="text-yellow-400/80 text-xs">
                      {rec}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <div className="text-gray-500 text-center py-8">Select a report to view details</div>
          )}
        </div>
      </div>

      {/* Pagination */}
      {total > limit && (
        <div className="flex items-center justify-between mt-4 pt-4 border-t border-green-500/20">
          <span className="text-gray-500">
            Showing {offset + 1}-{Math.min(offset + limit, total)} of {total}
          </span>
          <div className="flex gap-2">
            <button
              onClick={() => setOffset(Math.max(0, offset - limit))}
              disabled={offset === 0}
              className="px-3 py-1 border border-green-500/30 hover:bg-green-500/10 text-green-400 disabled:opacity-30"
            >
              Previous
            </button>
            <button
              onClick={() => setOffset(offset + limit)}
              disabled={offset + limit >= total}
              className="px-3 py-1 border border-green-500/30 hover:bg-green-500/10 text-green-400 disabled:opacity-30"
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

export const ProbeReportsPanel = withErrorBoundary(ProbeReportsPanelInner, 'ProbeReportsPanel');

export default ProbeReportsPanel;
