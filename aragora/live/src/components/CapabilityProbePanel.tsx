'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { withErrorBoundary } from './PanelErrorBoundary';
import { fetchWithRetry } from '@/utils/retry';
import { API_BASE_URL } from '@/config';
import { extractLeaderboardAgentNames } from '@/lib/leaderboard';

interface ProbeResult {
  probe_id: string;
  type: string;
  passed: boolean;
  severity?: string;
  description: string;
  details?: string;
}

interface ProbeReport {
  report_id: string;
  target_agent: string;
  probes_configured: number;
  by_type: Record<string, ProbeResult[]>;
  summary?: { total: number; passed: number; failed: number; pass_rate: number };
}

interface CapabilityProbePanelProps {
  apiBase?: string;
  onComplete?: (report: ProbeReport) => void;
}

const DEFAULT_API_BASE = API_BASE_URL;

const PROBE_TYPES = [
  {
    value: 'contradiction',
    label: 'Contradiction',
    description: 'Test for logical inconsistencies',
    icon: '🔀',
  },
  {
    value: 'hallucination',
    label: 'Hallucination',
    description: 'Test for fabricated information',
    icon: '👻',
  },
  {
    value: 'sycophancy',
    label: 'Sycophancy',
    description: 'Test for excessive agreement',
    icon: '🙇',
  },
  {
    value: 'persistence',
    label: 'Persistence',
    description: 'Test for position stability',
    icon: '🎯',
  },
  {
    value: 'confidence_calibration',
    label: 'Calibration',
    description: 'Test confidence accuracy',
    icon: '📊',
  },
  {
    value: 'reasoning_depth',
    label: 'Reasoning Depth',
    description: 'Test multi-step reasoning',
    icon: '🧠',
  },
  { value: 'edge_case', label: 'Edge Cases', description: 'Test boundary handling', icon: '⚠️' },
];

function CapabilityProbePanelComponent({
  apiBase = DEFAULT_API_BASE,
  onComplete,
}: CapabilityProbePanelProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [availableAgents, setAvailableAgents] = useState<string[]>([]);
  const [selectedAgent, setSelectedAgent] = useState('');
  const [selectedProbes, setSelectedProbes] = useState<string[]>([
    'contradiction',
    'hallucination',
  ]);
  const [probesPerType, setProbesPerType] = useState(3);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ProbeReport | null>(null);
  const initialFetchDone = useRef(false);

  // Fetch available agents - only once on mount
  useEffect(() => {
    if (initialFetchDone.current) return;
    initialFetchDone.current = true;

    fetch(`${apiBase}/api/leaderboard?limit=20`)
      .then((res) => {
        // Don't retry on rate limit - gracefully handle
        if (res.status === 429) return { agents: [] };
        return res.json();
      })
      .then((data: { agents?: Array<{ name: string }>; leaderboard?: Array<{ name: string }> }) => {
        const agents = extractLeaderboardAgentNames(data);
        setAvailableAgents(agents);
        if (agents.length > 0 && !selectedAgent) {
          setSelectedAgent(agents[0]);
        }
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Intentionally exclude selectedAgent to prevent re-fetching on selection
  }, [apiBase]);

  const toggleProbeType = (type: string) => {
    setSelectedProbes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  };

  const runProbes = useCallback(async () => {
    if (!selectedAgent) return;

    setLoading(true);
    setError(null);
    setReport(null);

    try {
      const response = await fetchWithRetry(
        `${apiBase}/api/probes/run`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_name: selectedAgent,
            probe_types: selectedProbes.length > 0 ? selectedProbes : undefined,
            probes_per_type: probesPerType,
          }),
        },
        { maxRetries: 2, baseDelayMs: 2000 }, // Longer delay for heavy operations
      );

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.error || `Probing failed: ${response.statusText}`);
      }

      const data = await response.json();
      setReport(data);
      onComplete?.(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Probing failed');
    } finally {
      setLoading(false);
    }
  }, [selectedAgent, selectedProbes, probesPerType, apiBase, onComplete]);

  const getPassRateColor = (rate: number) => {
    if (rate >= 0.8) return 'text-green-400';
    if (rate >= 0.6) return 'text-yellow-400';
    return 'text-red-400';
  };

  // Collapsed view
  if (!isExpanded) {
    return (
      <div
        className="panel panel-compact cursor-pointer"
        onClick={() => setIsExpanded(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            setIsExpanded(true);
          }
        }}
        role="button"
        tabIndex={0}
        aria-expanded={false}
        aria-label="Expand capability probes panel"
      >
        <div className="flex items-center justify-between">
          <h3 className="panel-title-sm flex items-center gap-2">
            <span className="text-accent">{'>'}</span>
            CAPABILITY_PROBES{' '}
            {report
              ? `[${report.summary?.pass_rate ? Math.round(report.summary.pass_rate * 100) : 0}% pass]`
              : ''}
          </h3>
          <span className="panel-toggle" aria-hidden="true">
            [EXPAND]
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header mb-4">
        <h3 className="panel-title-sm flex items-center gap-2">
          <span>🔬</span> CAPABILITY_PROBES
        </h3>
        <button
          onClick={() => setIsExpanded(false)}
          aria-label="Collapse capability probes panel"
          className="panel-toggle hover:text-accent"
        >
          [COLLAPSE]
        </button>
      </div>

      {/* Configuration */}
      <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4 mb-4">
        {/* Agent Selection */}
        <div className="mb-4">
          <label className="block text-sm text-zinc-500 dark:text-zinc-400 mb-1">
            Target Agent
          </label>
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded px-3 py-2 text-zinc-700 dark:text-zinc-300"
          >
            <option value="">Select an agent...</option>
            {availableAgents.map((agent) => (
              <option key={agent} value={agent}>
                {agent}
              </option>
            ))}
          </select>
        </div>

        {/* Probe Types */}
        <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-400 mb-2">Probe Types</h4>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-4">
          {PROBE_TYPES.map((probe) => (
            <button
              key={probe.value}
              onClick={() => toggleProbeType(probe.value)}
              aria-pressed={selectedProbes.includes(probe.value)}
              aria-label={`${probe.label}: ${probe.description}`}
              className={`p-2 rounded border text-left text-sm ${
                selectedProbes.includes(probe.value)
                  ? 'border-purple-500 bg-purple-500/10 text-purple-600 dark:text-purple-400'
                  : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300 dark:hover:border-zinc-600 text-zinc-600 dark:text-zinc-400'
              }`}
            >
              <div className="font-medium flex items-center gap-1">
                <span aria-hidden="true">{probe.icon}</span> {probe.label}
              </div>
              <div className="text-xs opacity-70">{probe.description}</div>
            </button>
          ))}
        </div>

        {/* Probes Per Type */}
        <div>
          <label className="block text-sm text-zinc-500 dark:text-zinc-400 mb-1">
            Probes per Type (max 10)
          </label>
          <input
            type="number"
            min={1}
            max={10}
            value={probesPerType}
            onChange={(e) =>
              setProbesPerType(Math.min(10, Math.max(1, parseInt(e.target.value) || 1)))
            }
            className="w-32 bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded px-3 py-2 text-zinc-700 dark:text-zinc-300"
          />
        </div>
      </div>

      {/* Run Button */}
      <button
        onClick={runProbes}
        disabled={loading || !selectedAgent || selectedProbes.length === 0}
        aria-busy={loading}
        className="w-full py-3 bg-purple-600 hover:bg-purple-700 disabled:opacity-50 text-white rounded-lg font-medium mb-4"
      >
        {loading ? 'Running Probes...' : 'Run Capability Probes'}
      </button>

      {/* Error Display */}
      {error && (
        <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Results */}
      {report && (
        <div className="space-y-4">
          {/* Summary */}
          {report.summary && (
            <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
              <div className="grid grid-cols-4 gap-4 text-center">
                <div>
                  <div className="text-2xl font-bold text-white">{report.summary.total}</div>
                  <div className="text-xs text-zinc-500">Total Probes</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-green-400">{report.summary.passed}</div>
                  <div className="text-xs text-zinc-500">Passed</div>
                </div>
                <div>
                  <div className="text-2xl font-bold text-red-400">{report.summary.failed}</div>
                  <div className="text-xs text-zinc-500">Failed</div>
                </div>
                <div>
                  <div
                    className={`text-2xl font-bold ${getPassRateColor(report.summary.pass_rate)}`}
                  >
                    {(report.summary.pass_rate * 100).toFixed(0)}%
                  </div>
                  <div className="text-xs text-zinc-500">Pass Rate</div>
                </div>
              </div>
            </div>
          )}

          {/* Results by Type */}
          {report.by_type && Object.keys(report.by_type).length > 0 && (
            <div className="space-y-3">
              {Object.entries(report.by_type).map(([type, results]) => {
                const probeInfo = PROBE_TYPES.find((p) => p.value === type);
                const passed = results.filter((r) => r.passed).length;
                const total = results.length;

                return (
                  <div
                    key={type}
                    className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4"
                  >
                    <div className="flex items-center justify-between mb-2">
                      <h4 className="font-medium text-white flex items-center gap-2">
                        <span>{probeInfo?.icon || '🔍'}</span>
                        {probeInfo?.label || type}
                      </h4>
                      <span
                        className={`text-sm ${
                          passed === total ? 'text-green-400' : 'text-yellow-400'
                        }`}
                      >
                        {passed}/{total} passed
                      </span>
                    </div>

                    <div className="space-y-1">
                      {results.map((result, idx) => (
                        <div
                          key={idx}
                          className={`p-2 rounded text-sm ${
                            result.passed
                              ? 'bg-green-900/20 text-green-400'
                              : 'bg-red-900/20 text-red-400'
                          }`}
                        >
                          <div className="flex items-center justify-between">
                            <span>
                              {result.passed ? '✓' : '✗'} {result.description}
                            </span>
                            {result.severity && (
                              <span className="text-xs opacity-70 uppercase">
                                {result.severity}
                              </span>
                            )}
                          </div>
                          {result.details && (
                            <p className="text-xs mt-1 opacity-70">{result.details}</p>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          {/* Report Info */}
          <div className="text-xs text-zinc-500 text-center">
            Report ID: {report.report_id} | Agent: {report.target_agent}
          </div>
        </div>
      )}

      <div className="mt-3 text-[10px] text-text-muted font-theme-data">
        Adversarial capability testing for agent vulnerabilities
      </div>
    </div>
  );
}

// Wrap with error boundary for graceful error handling
export const CapabilityProbePanel = withErrorBoundary(
  CapabilityProbePanelComponent,
  'Capability Probe',
);
export default CapabilityProbePanel;
