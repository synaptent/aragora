'use client';

import { useState, useCallback } from 'react';
import { API_BASE_URL } from '@/config';

interface RedTeamFinding {
  attack_type: string;
  severity: string;
  description: string;
  recommendation?: string;
}

interface RedTeamResult {
  session_id: string;
  findings: RedTeamFinding[];
  robustness_score: number;
  attack_summary?: Record<string, number>;
}

interface ProbeResult {
  report_id: string;
  target_agent: string;
  probes_run: number;
  vulnerabilities_found: number;
  vulnerability_rate: number;
  elo_penalty: number;
  by_type: Record<
    string,
    Array<{
      probe_id: string;
      type: string;
      passed: boolean;
      severity: string | null;
      description: string;
      details: string;
    }>
  >;
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
}

interface RedTeamAnalysisPanelProps {
  debateId?: string;
  apiBase?: string;
  onComplete?: (result: RedTeamResult | ProbeResult) => void;
}

const DEFAULT_API_BASE = API_BASE_URL;

// Probe types for standalone agent analysis (maps to ProbeType enum in backend)
const PROBE_TYPES = [
  {
    value: 'contradiction',
    label: 'Contradiction',
    description: 'Test for self-contradictory statements',
  },
  { value: 'hallucination', label: 'Hallucination', description: 'Detect fabricated information' },
  { value: 'sycophancy', label: 'Sycophancy', description: 'Check for excessive agreement' },
  { value: 'persistence', label: 'Persistence', description: 'Test reasoning stability' },
  {
    value: 'confidence_calibration',
    label: 'Confidence',
    description: 'Verify confidence matches accuracy',
  },
  { value: 'edge_case', label: 'Edge Cases', description: 'Test boundary conditions' },
];

// Attack types for debate-specific analysis
const ATTACK_TYPES = [
  { value: 'logical_fallacy', label: 'Logical Fallacy', description: 'Test for flawed reasoning' },
  { value: 'edge_case', label: 'Edge Cases', description: 'Find boundary condition issues' },
  {
    value: 'unstated_assumption',
    label: 'Unstated Assumptions',
    description: 'Expose hidden assumptions',
  },
  { value: 'counterexample', label: 'Counterexamples', description: 'Find contradicting cases' },
  { value: 'scalability', label: 'Scalability', description: 'Test at scale limitations' },
  { value: 'security', label: 'Security', description: 'Security vulnerability analysis' },
];

const AVAILABLE_AGENTS = [
  'anthropic-api',
  'openai-api',
  'grok',
  'deepseek',
  'mistral',
  'codex',
  'gemini',
];

const SEVERITY_COLORS: Record<string, string> = {
  critical:
    'bg-red-100 dark:bg-red-900/30 border-red-300 dark:border-red-700 text-red-700 dark:text-red-400',
  high: 'bg-orange-100 dark:bg-orange-900/30 border-orange-300 dark:border-orange-700 text-orange-700 dark:text-orange-400',
  medium:
    'bg-yellow-100 dark:bg-yellow-900/30 border-yellow-300 dark:border-yellow-700 text-yellow-700 dark:text-yellow-400',
  low: 'bg-blue-100 dark:bg-blue-900/30 border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-400',
  info: 'bg-zinc-100 dark:bg-zinc-800 border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400',
};

export function RedTeamAnalysisPanel({
  debateId,
  apiBase = DEFAULT_API_BASE,
  onComplete,
}: RedTeamAnalysisPanelProps) {
  const [isExpanded, setIsExpanded] = useState(true); // Start expanded for better UX
  const [mode, setMode] = useState<'debate' | 'standalone'>(debateId ? 'debate' : 'standalone');
  const [selectedAttacks, setSelectedAttacks] = useState<string[]>([
    'logical_fallacy',
    'edge_case',
  ]);
  const [selectedProbes, setSelectedProbes] = useState<string[]>([
    'contradiction',
    'hallucination',
    'sycophancy',
  ]);
  const [selectedAgent, setSelectedAgent] = useState('anthropic-api');
  const [probesPerType, setProbesPerType] = useState(3);
  const [maxRounds, setMaxRounds] = useState(3);
  const [focusProposal, setFocusProposal] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RedTeamResult | null>(null);
  const [probeResult, setProbeResult] = useState<ProbeResult | null>(null);

  const toggleAttackType = (type: string) => {
    setSelectedAttacks((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  };

  const toggleProbeType = (type: string) => {
    setSelectedProbes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type],
    );
  };

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setProbeResult(null);

    try {
      if (mode === 'debate' && debateId) {
        // Debate-specific red team analysis
        const response = await fetch(`${apiBase}/api/debates/${debateId}/red-team`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            attack_types: selectedAttacks.length > 0 ? selectedAttacks : undefined,
            max_rounds: maxRounds,
            focus_proposal: focusProposal || undefined,
          }),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || `Analysis failed: ${response.statusText}`);
        }

        const data = await response.json();
        setResult(data);
        onComplete?.(data);
      } else {
        // Standalone capability probe
        const response = await fetch(`${apiBase}/api/probes/capability`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            agent_name: selectedAgent,
            probe_types: selectedProbes.length > 0 ? selectedProbes : undefined,
            probes_per_type: probesPerType,
            model_type: selectedAgent,
          }),
        });

        if (!response.ok) {
          const data = await response.json().catch(() => ({}));
          throw new Error(data.error || data.hint || `Probe failed: ${response.statusText}`);
        }

        const data = await response.json();
        setProbeResult(data);
        onComplete?.(data);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Analysis failed');
    } finally {
      setLoading(false);
    }
  }, [
    mode,
    debateId,
    selectedAttacks,
    selectedProbes,
    selectedAgent,
    probesPerType,
    maxRounds,
    focusProposal,
    apiBase,
    onComplete,
  ]);

  const getRobustnessColor = (score: number) => {
    if (score >= 0.8) return 'text-green-400';
    if (score >= 0.6) return 'text-yellow-400';
    if (score >= 0.4) return 'text-orange-400';
    return 'text-red-400';
  };

  const hasResult = result || probeResult;
  const robustnessScore =
    result?.robustness_score ?? (probeResult ? 1 - probeResult.vulnerability_rate : null);
  const findingsCount = result?.findings?.length ?? probeResult?.vulnerabilities_found ?? 0;

  // Collapsed view
  if (!isExpanded) {
    return (
      <div className="panel panel-compact cursor-pointer" onClick={() => setIsExpanded(true)}>
        <div className="flex items-center justify-between">
          <h3 className="panel-title-sm flex items-center gap-2">
            <span className="text-accent">{'>'}</span>
            RED_TEAM_ANALYSIS{' '}
            {robustnessScore !== null ? `[${Math.round(robustnessScore * 100)}% robust]` : ''}
          </h3>
          <div className="flex items-center gap-2">
            {hasResult && (
              <span className="text-xs font-theme-data text-text-muted">
                {findingsCount} vulnerabilities
              </span>
            )}
            <span className="panel-toggle">[EXPAND]</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header mb-4">
        <h3 className="panel-title-sm flex items-center gap-2">
          <span>🛡️</span> RED_TEAM_ANALYSIS
        </h3>
        <button onClick={() => setIsExpanded(false)} className="panel-toggle hover:text-accent">
          [COLLAPSE]
        </button>
      </div>

      {/* Mode Selector */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setMode('standalone')}
          className={`flex-1 py-2 px-4 rounded border text-sm font-medium ${
            mode === 'standalone'
              ? 'border-warning bg-warning/20 text-warning'
              : 'border-zinc-200 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400 hover:border-warning/50'
          }`}
        >
          Agent Probe
        </button>
        <button
          onClick={() => setMode('debate')}
          disabled={!debateId}
          className={`flex-1 py-2 px-4 rounded border text-sm font-medium ${
            mode === 'debate'
              ? 'border-warning bg-warning/20 text-warning'
              : 'border-zinc-200 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400 hover:border-warning/50'
          } ${!debateId ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          Debate Analysis {!debateId && '(select debate)'}
        </button>
      </div>

      {/* Configuration - Standalone Mode */}
      {mode === 'standalone' && (
        <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4 mb-4">
          <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-400 mb-3">
            Target Agent
          </h4>
          <select
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
            className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded px-3 py-2 text-zinc-700 dark:text-zinc-300 mb-4"
          >
            {AVAILABLE_AGENTS.map((agent) => (
              <option key={agent} value={agent}>
                {agent}
              </option>
            ))}
          </select>

          <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-400 mb-3">Probe Types</h4>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-4">
            {PROBE_TYPES.map((probe) => (
              <button
                key={probe.value}
                onClick={() => toggleProbeType(probe.value)}
                className={`p-2 rounded border text-left text-sm ${
                  selectedProbes.includes(probe.value)
                    ? 'border-warning bg-warning/10 text-warning'
                    : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300 dark:hover:border-zinc-600 text-zinc-600 dark:text-zinc-400'
                }`}
              >
                <div className="font-medium">{probe.label}</div>
                <div className="text-xs opacity-70">{probe.description}</div>
              </button>
            ))}
          </div>

          <div>
            <label className="block text-sm text-zinc-500 dark:text-zinc-400 mb-1">
              Probes Per Type (1-10)
            </label>
            <input
              type="number"
              min={1}
              max={10}
              value={probesPerType}
              onChange={(e) =>
                setProbesPerType(Math.min(10, Math.max(1, parseInt(e.target.value) || 3)))
              }
              className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded px-3 py-2 text-zinc-700 dark:text-zinc-300"
            />
          </div>
        </div>
      )}

      {/* Configuration - Debate Mode */}
      {mode === 'debate' && (
        <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4 mb-4">
          <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-400 mb-3">
            Attack Types
          </h4>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2 mb-4">
            {ATTACK_TYPES.map((attack) => (
              <button
                key={attack.value}
                onClick={() => toggleAttackType(attack.value)}
                className={`p-2 rounded border text-left text-sm ${
                  selectedAttacks.includes(attack.value)
                    ? 'border-red-500 bg-red-500/10 text-red-600 dark:text-red-400'
                    : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300 dark:hover:border-zinc-600 text-zinc-600 dark:text-zinc-400'
                }`}
              >
                <div className="font-medium">{attack.label}</div>
                <div className="text-xs opacity-70">{attack.description}</div>
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm text-zinc-500 dark:text-zinc-400 mb-1">
                Max Rounds
              </label>
              <input
                type="number"
                min={1}
                max={5}
                value={maxRounds}
                onChange={(e) =>
                  setMaxRounds(Math.min(5, Math.max(1, parseInt(e.target.value) || 1)))
                }
                className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded px-3 py-2 text-zinc-700 dark:text-zinc-300"
              />
            </div>
            <div>
              <label className="block text-sm text-zinc-500 dark:text-zinc-400 mb-1">
                Focus Proposal (optional)
              </label>
              <input
                type="text"
                value={focusProposal}
                onChange={(e) => setFocusProposal(e.target.value)}
                placeholder="Specific proposal to analyze"
                className="w-full bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded px-3 py-2 text-zinc-700 dark:text-zinc-300"
              />
            </div>
          </div>
        </div>
      )}

      {/* Run Button */}
      <button
        onClick={runAnalysis}
        disabled={
          loading ||
          (mode === 'standalone' ? selectedProbes.length === 0 : selectedAttacks.length === 0)
        }
        className="w-full py-3 bg-warning hover:bg-warning/80 disabled:opacity-50 text-black rounded-lg font-medium mb-4"
      >
        {loading
          ? 'Running Analysis...'
          : mode === 'standalone'
            ? 'Run Capability Probe'
            : 'Run Red Team Analysis'}
      </button>

      {/* Error Display */}
      {error && (
        <div className="mb-4 p-3 bg-red-900/20 border border-red-800 rounded text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          {/* Robustness Score */}
          <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
            <div className="flex items-center justify-between">
              <span className="text-zinc-500 dark:text-zinc-400">Robustness Score</span>
              <span className={`text-2xl font-bold ${getRobustnessColor(result.robustness_score)}`}>
                {(result.robustness_score * 100).toFixed(0)}%
              </span>
            </div>
            <div className="mt-2 bg-zinc-200 dark:bg-zinc-900 rounded-full h-2 overflow-hidden">
              <div
                className={`h-full ${
                  result.robustness_score >= 0.8
                    ? 'bg-green-500'
                    : result.robustness_score >= 0.5
                      ? 'bg-yellow-500'
                      : 'bg-red-500'
                }`}
                style={{ width: `${result.robustness_score * 100}%` }}
              />
            </div>
          </div>

          {/* Findings */}
          <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
            <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-400 mb-3">
              Findings ({result.findings?.length || 0})
            </h4>
            {result.findings && result.findings.length > 0 ? (
              <div className="space-y-2">
                {result.findings.map((finding, idx) => (
                  <div
                    key={idx}
                    className={`p-3 rounded border ${SEVERITY_COLORS[finding.severity] || SEVERITY_COLORS.info}`}
                  >
                    <div className="flex items-center justify-between mb-1">
                      <span className="font-medium">{finding.attack_type}</span>
                      <span className="text-xs uppercase px-2 py-0.5 rounded bg-black/20">
                        {finding.severity}
                      </span>
                    </div>
                    <p className="text-sm opacity-90">{finding.description}</p>
                    {finding.recommendation && (
                      <p className="text-xs mt-2 opacity-70">💡 {finding.recommendation}</p>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-zinc-500 text-center py-4">No vulnerabilities found</div>
            )}
          </div>

          {/* Session Info */}
          <div className="text-xs text-zinc-500 text-center">Session ID: {result.session_id}</div>
        </div>
      )}

      {/* Probe Results (Standalone Mode) */}
      {probeResult && (
        <div className="space-y-4">
          {/* Summary Stats */}
          <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
              <div className="text-center">
                <span className="text-zinc-500 dark:text-zinc-400 text-xs">Probes Run</span>
                <p className="text-2xl font-bold text-[var(--acid-cyan)]">
                  {probeResult.probes_run}
                </p>
              </div>
              <div className="text-center">
                <span className="text-zinc-500 dark:text-zinc-400 text-xs">Passed</span>
                <p className="text-2xl font-bold text-green-500">{probeResult.summary.passed}</p>
              </div>
              <div className="text-center">
                <span className="text-zinc-500 dark:text-zinc-400 text-xs">Vulnerabilities</span>
                <p className="text-2xl font-bold text-red-500">
                  {probeResult.vulnerabilities_found}
                </p>
              </div>
              <div className="text-center">
                <span className="text-zinc-500 dark:text-zinc-400 text-xs">ELO Penalty</span>
                <p
                  className={`text-2xl font-bold ${probeResult.elo_penalty > 0 ? 'text-red-500' : 'text-green-500'}`}
                >
                  {probeResult.elo_penalty > 0 ? '-' : ''}
                  {Math.abs(probeResult.elo_penalty).toFixed(0)}
                </p>
              </div>
            </div>

            {/* Pass Rate Bar */}
            <div className="flex items-center justify-between mb-1">
              <span className="text-zinc-500 dark:text-zinc-400 text-xs">Pass Rate</span>
              <span
                className={`text-sm font-bold ${getRobustnessColor(probeResult.summary.pass_rate)}`}
              >
                {(probeResult.summary.pass_rate * 100).toFixed(0)}%
              </span>
            </div>
            <div className="bg-zinc-200 dark:bg-zinc-900 rounded-full h-3 overflow-hidden">
              <div
                className={`h-full ${
                  probeResult.summary.pass_rate >= 0.8
                    ? 'bg-green-500'
                    : probeResult.summary.pass_rate >= 0.5
                      ? 'bg-yellow-500'
                      : 'bg-red-500'
                }`}
                style={{ width: `${probeResult.summary.pass_rate * 100}%` }}
              />
            </div>
          </div>

          {/* Severity Breakdown */}
          <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
            <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-400 mb-3">
              Severity Breakdown
            </h4>
            <div className="grid grid-cols-4 gap-2">
              <div className="p-2 rounded bg-red-900/20 border border-red-800 text-center">
                <span className="text-red-400 text-xs">Critical</span>
                <p className="text-xl font-bold text-red-400">{probeResult.summary.critical}</p>
              </div>
              <div className="p-2 rounded bg-orange-900/20 border border-orange-800 text-center">
                <span className="text-orange-400 text-xs">High</span>
                <p className="text-xl font-bold text-orange-400">{probeResult.summary.high}</p>
              </div>
              <div className="p-2 rounded bg-yellow-900/20 border border-yellow-800 text-center">
                <span className="text-yellow-400 text-xs">Medium</span>
                <p className="text-xl font-bold text-yellow-400">{probeResult.summary.medium}</p>
              </div>
              <div className="p-2 rounded bg-blue-900/20 border border-blue-800 text-center">
                <span className="text-blue-400 text-xs">Low</span>
                <p className="text-xl font-bold text-blue-400">{probeResult.summary.low}</p>
              </div>
            </div>
          </div>

          {/* Results by Type */}
          <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
            <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-400 mb-3">
              Results by Probe Type
            </h4>
            {Object.entries(probeResult.by_type).map(([probeType, results]) => (
              <div key={probeType} className="mb-4 last:mb-0">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-medium text-sm capitalize">
                    {probeType.replace('_', ' ')}
                  </span>
                  <span className="text-xs text-zinc-500">
                    {results.filter((r) => r.passed).length}/{results.length} passed
                  </span>
                </div>
                <div className="space-y-1">
                  {results.map((r, idx) => (
                    <div
                      key={r.probe_id || idx}
                      className={`p-2 rounded text-xs ${
                        r.passed
                          ? 'bg-green-900/20 border border-green-800 text-green-400'
                          : `${SEVERITY_COLORS[r.severity || 'info']}`
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span>
                          {r.passed ? '✓ Passed' : `✗ ${r.severity?.toUpperCase() || 'FAILED'}`}
                        </span>
                      </div>
                      {r.description && !r.passed && (
                        <p className="mt-1 opacity-80">{r.description}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {/* Recommendations */}
          {probeResult.recommendations && probeResult.recommendations.length > 0 && (
            <div className="bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-4">
              <h4 className="text-sm font-medium text-zinc-500 dark:text-zinc-400 mb-3">
                Recommendations
              </h4>
              <ul className="space-y-2">
                {probeResult.recommendations.map((rec, idx) => (
                  <li
                    key={idx}
                    className="text-sm text-zinc-600 dark:text-zinc-400 flex items-start gap-2"
                  >
                    <span className="text-warning">{'>'}</span>
                    {rec}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Report Info */}
          <div className="text-xs text-zinc-500 text-center space-y-1">
            <div>Report ID: {probeResult.report_id}</div>
            <div>Target: {probeResult.target_agent}</div>
          </div>
        </div>
      )}

      <div className="mt-3 text-[10px] text-text-muted font-theme-data">
        Adversarial red team analysis for debate robustness
      </div>
    </div>
  );
}

export default RedTeamAnalysisPanel;
