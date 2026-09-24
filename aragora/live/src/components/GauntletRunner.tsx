'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAragoraClient } from '@/hooks/useAragoraClient';
import { useGauntletWebSocket } from '@/hooks/useGauntletWebSocket';
import { LoadingSpinner } from './LoadingSpinner';
import { ApiError } from './ApiError';
import type { GauntletPersona, GauntletResult, GauntletReceipt } from '@/lib/aragora-client';

interface GauntletRunnerProps {
  initialDecision?: string;
}

export function GauntletRunner({ initialDecision }: GauntletRunnerProps) {
  const client = useAragoraClient();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'run' | 'results' | 'receipt'>('run');

  // Form state
  const [decision, setDecision] = useState(initialDecision || '');
  const [selectedPersonas, setSelectedPersonas] = useState<string[]>([]);
  const [rounds, setRounds] = useState(3);
  const [stressLevel, setStressLevel] = useState(5);
  const [isRunning, setIsRunning] = useState(false);
  const [activeGauntletId, setActiveGauntletId] = useState<string | null>(null);

  // Data state
  const [personas, setPersonas] = useState<GauntletPersona[]>([]);
  const [results, setResults] = useState<GauntletResult[]>([]);
  const [selectedResult, setSelectedResult] = useState<GauntletResult | null>(null);
  const [receipt, setReceipt] = useState<GauntletReceipt | null>(null);

  // WebSocket for real-time gauntlet updates (replaces polling)
  const {
    status: wsStatus,
    progress: wsProgress,
    error: wsError,
  } = useGauntletWebSocket({
    gauntletId: activeGauntletId || '',
    enabled: !!activeGauntletId && isRunning,
  });

  const fetchData = useCallback(async () => {
    if (!client) return;
    setLoading(true);
    setError(null);

    try {
      const [personasRes, resultsRes] = await Promise.all([
        client.gauntlet.personas().catch(() => ({ personas: [] })),
        client.gauntlet.results({ limit: 10 }).catch(() => ({ results: [] })),
      ]);

      setPersonas(personasRes.personas || []);
      setResults(resultsRes.results || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load gauntlet data');
    } finally {
      setLoading(false);
    }
  }, [client]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Handle WebSocket completion (replaces polling)
  useEffect(() => {
    if (!activeGauntletId || !isRunning) return;

    if (wsStatus === 'complete' || wsStatus === 'error') {
      // Fetch final result
      client?.gauntlet
        .get(activeGauntletId)
        .then((res) => {
          setSelectedResult(res.gauntlet);
          setActiveTab('results');
          // Refresh results list
          return client.gauntlet.results({ limit: 10 });
        })
        .then((resultsRes) => {
          setResults(resultsRes?.results || []);
        })
        .catch((e) => {
          setError(e instanceof Error ? e.message : 'Failed to fetch result');
        })
        .finally(() => {
          setIsRunning(false);
          setActiveGauntletId(null);
        });
    }

    if (wsError) {
      setError(wsError);
    }
  }, [wsStatus, wsError, activeGauntletId, isRunning, client]);

  const runGauntlet = async () => {
    if (!client || !decision.trim()) return;
    setIsRunning(true);
    setError(null);

    try {
      const res = await client.gauntlet.run({
        decision: decision.trim(),
        personas: selectedPersonas.length > 0 ? selectedPersonas : undefined,
        rounds,
        stress_level: stressLevel,
      });

      // Set active gauntlet ID to enable WebSocket streaming
      setActiveGauntletId(res.gauntlet_id);
      // WebSocket will handle completion via useEffect above
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to run gauntlet');
      setIsRunning(false);
    }
  };

  const viewResult = async (result: GauntletResult) => {
    setSelectedResult(result);
    setActiveTab('results');
  };

  const viewReceipt = async (gauntletId: string) => {
    if (!client) return;
    try {
      const res = await client.gauntlet.receipt(gauntletId);
      setReceipt(res.receipt);
      setActiveTab('receipt');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load receipt');
    }
  };

  const togglePersona = (personaId: string) => {
    setSelectedPersonas((prev) =>
      prev.includes(personaId) ? prev.filter((id) => id !== personaId) : [...prev, personaId],
    );
  };

  const tabs = [
    { id: 'run' as const, label: 'Run Gauntlet' },
    { id: 'results' as const, label: 'Results' },
    { id: 'receipt' as const, label: 'Receipt' },
  ];

  if (loading && personas.length === 0) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <LoadingSpinner />
      </div>
    );
  }

  if (error && personas.length === 0) {
    return (
      <div className="p-4 bg-slate-900 rounded-lg border border-slate-700">
        <ApiError error={error} onRetry={fetchData} />
      </div>
    );
  }

  return (
    <div className="bg-slate-900 rounded-lg border border-slate-700 overflow-hidden">
      {/* Header */}
      <div className="p-4 border-b border-slate-700">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <span className="text-red-400">&#x2694;&#xFE0F;</span>
          Decision Gauntlet
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          Stress-test your decisions with adversarial personas
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-700">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? 'text-red-400 border-b-2 border-red-400 bg-slate-800/50'
                : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4">
        {/* Run Tab */}
        {activeTab === 'run' && (
          <div className="space-y-6">
            {/* Decision Input */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Decision to Test
              </label>
              <textarea
                value={decision}
                onChange={(e) => setDecision(e.target.value)}
                placeholder="Enter the decision you want to stress-test..."
                className="w-full p-3 bg-slate-800 border border-slate-600 rounded-lg text-white placeholder-slate-500 focus:border-red-400 focus:ring-1 focus:ring-red-400 outline-none"
                rows={4}
              />
            </div>

            {/* Persona Selection */}
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-2">
                Select Personas (optional)
              </label>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
                {personas.map((persona) => (
                  <button
                    key={persona.id}
                    onClick={() => togglePersona(persona.id)}
                    className={`p-3 rounded-lg text-left transition-colors ${
                      selectedPersonas.includes(persona.id)
                        ? 'bg-red-900/30 border border-red-600'
                        : 'bg-slate-800 border border-slate-700 hover:border-slate-600'
                    }`}
                  >
                    <p className="text-white font-medium text-sm">{persona.name}</p>
                    <p className="text-xs text-slate-400 mt-1">{persona.description}</p>
                    <div className="flex items-center gap-2 mt-2">
                      <DifficultyBadge difficulty={persona.difficulty} />
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Configuration */}
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label
                  htmlFor="gauntlet-rounds"
                  className="block text-sm font-medium text-slate-300 mb-2"
                >
                  Rounds: {rounds}
                </label>
                <input
                  id="gauntlet-rounds"
                  type="range"
                  min="1"
                  max="10"
                  value={rounds}
                  onChange={(e) => setRounds(parseInt(e.target.value))}
                  className="w-full accent-red-500"
                  aria-label={`Gauntlet rounds: ${rounds}`}
                />
              </div>
              <div>
                <label
                  htmlFor="gauntlet-stress"
                  className="block text-sm font-medium text-slate-300 mb-2"
                >
                  Stress Level: {stressLevel}
                </label>
                <input
                  id="gauntlet-stress"
                  type="range"
                  min="1"
                  max="10"
                  value={stressLevel}
                  onChange={(e) => setStressLevel(parseInt(e.target.value))}
                  className="w-full accent-red-500"
                  aria-label={`Stress level: ${stressLevel}`}
                />
              </div>
            </div>

            {/* Run Button */}
            <button
              onClick={runGauntlet}
              disabled={!decision.trim() || isRunning}
              className={`w-full py-3 rounded-lg font-medium transition-colors ${
                !decision.trim() || isRunning
                  ? 'bg-slate-700 text-slate-400 cursor-not-allowed'
                  : 'bg-red-600 hover:bg-red-500 text-white'
              }`}
            >
              {isRunning ? (
                <span className="flex items-center justify-center gap-2">
                  <LoadingSpinner />
                  Running Gauntlet... {wsProgress > 0 && `(${Math.round(wsProgress * 100)}%)`}
                </span>
              ) : (
                'Run Gauntlet'
              )}
            </button>

            {/* Progress bar during run */}
            {isRunning && wsProgress > 0 && (
              <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                <div
                  className="bg-red-500 h-full transition-all duration-300"
                  style={{ width: `${wsProgress * 100}%` }}
                />
              </div>
            )}

            {error && <p className="text-red-400 text-sm text-center">{error}</p>}
          </div>
        )}

        {/* Results Tab */}
        {activeTab === 'results' && (
          <div className="space-y-4">
            {selectedResult ? (
              <ResultDetail
                result={selectedResult}
                onViewReceipt={() => viewReceipt(selectedResult.gauntlet_id)}
                onBack={() => setSelectedResult(null)}
              />
            ) : (
              <div className="space-y-2">
                <h3 className="text-sm font-medium text-slate-300 mb-3">Recent Results</h3>
                {results.length === 0 ? (
                  <p className="text-slate-400 text-center py-4">No results yet</p>
                ) : (
                  results.map((result) => (
                    <ResultCard
                      key={result.gauntlet_id}
                      result={result}
                      onView={() => viewResult(result)}
                    />
                  ))
                )}
              </div>
            )}
          </div>
        )}

        {/* Receipt Tab */}
        {activeTab === 'receipt' && (
          <div>
            {receipt ? (
              <ReceiptView receipt={receipt} />
            ) : (
              <div className="text-center py-8">
                <p className="text-slate-400 mb-4">
                  Select a completed gauntlet to view its receipt
                </p>
                <div className="flex flex-wrap justify-center gap-2">
                  {results
                    .filter((r) => r.status === 'completed')
                    .slice(0, 3)
                    .map((r) => (
                      <button
                        key={r.gauntlet_id}
                        onClick={() => viewReceipt(r.gauntlet_id)}
                        className="px-3 py-1 bg-slate-800 hover:bg-slate-700 rounded text-sm text-white transition-colors"
                      >
                        {r.gauntlet_id.slice(0, 8)}...
                      </button>
                    ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function DifficultyBadge({ difficulty }: { difficulty: string }) {
  const colors = {
    easy: 'bg-green-600 text-white',
    medium: 'bg-yellow-600 text-black',
    hard: 'bg-orange-600 text-white',
    extreme: 'bg-red-600 text-white',
  };
  const color = colors[difficulty as keyof typeof colors] || colors.medium;
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${color}`}>{difficulty}</span>;
}

function ResultCard({ result, onView }: { result: GauntletResult; onView: () => void }) {
  return (
    <button
      onClick={onView}
      className="w-full text-left p-3 bg-slate-800 rounded-lg hover:bg-slate-700 transition-colors"
    >
      <div className="flex items-center justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-white truncate">{result.decision}</p>
          <p className="text-xs text-slate-400 mt-1">
            {result.rounds_completed} rounds &bull; {result.personas_used.length} personas
          </p>
        </div>
        <div className="flex items-center gap-3">
          <RiskScore score={result.risk_score} />
          <StatusBadge status={result.status} />
        </div>
      </div>
    </button>
  );
}

function ResultDetail({
  result,
  onViewReceipt,
  onBack,
}: {
  result: GauntletResult;
  onViewReceipt: () => void;
  onBack: () => void;
}) {
  return (
    <div className="space-y-4">
      <button
        onClick={onBack}
        className="text-sm text-blue-400 hover:text-blue-300 flex items-center gap-1"
      >
        &#x2190; Back to results
      </button>

      <div className="bg-slate-800 rounded-lg p-4">
        <h3 className="text-lg font-medium text-white mb-2">{result.decision}</h3>
        <div className="flex items-center gap-4">
          <StatusBadge status={result.status} />
          <RiskScore score={result.risk_score} large />
        </div>
      </div>

      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-slate-800 rounded-lg p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-2">Personas Used</h4>
          <div className="flex flex-wrap gap-1">
            {result.personas_used.map((persona) => (
              <span key={persona} className="px-2 py-1 bg-slate-700 rounded text-xs text-white">
                {persona}
              </span>
            ))}
          </div>
        </div>

        <div className="bg-slate-800 rounded-lg p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-2">Stats</h4>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <span className="text-slate-400">Rounds:</span>
              <span className="text-white ml-2">{result.rounds_completed}</span>
            </div>
            <div>
              <span className="text-slate-400">Vulnerabilities:</span>
              <span className="text-white ml-2">{result.vulnerabilities.length}</span>
            </div>
          </div>
        </div>
      </div>

      {result.vulnerabilities.length > 0 && (
        <div className="bg-slate-800 rounded-lg p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-2">Vulnerabilities</h4>
          <div className="space-y-2">
            {result.vulnerabilities.map((vuln, i) => (
              <div key={i} className="flex items-start gap-3 p-2 bg-slate-900 rounded">
                <SeverityBadge severity={vuln.severity} />
                <div>
                  <p className="text-white text-sm">{vuln.category}</p>
                  <p className="text-xs text-slate-400">{vuln.description}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="bg-slate-800 rounded-lg p-4">
        <h4 className="text-sm font-medium text-slate-300 mb-2">Recommendation</h4>
        <p className="text-white">{result.recommendation}</p>
      </div>

      {result.status === 'completed' && (
        <button
          onClick={onViewReceipt}
          className="w-full py-2 bg-blue-600 hover:bg-blue-500 rounded-lg text-white font-medium transition-colors"
        >
          View Decision Receipt
        </button>
      )}
    </div>
  );
}

function ReceiptView({ receipt }: { receipt: GauntletReceipt }) {
  const verdictColors = {
    approved: 'bg-green-600 text-white',
    rejected: 'bg-red-600 text-white',
    needs_review: 'bg-yellow-600 text-black',
    pass: 'bg-green-600 text-white',
    conditional: 'bg-yellow-600 text-black',
    fail: 'bg-red-600 text-white',
  };
  const verdictKey = String(receipt.verdict || '').toLowerCase();
  const verdictClass =
    verdictColors[verdictKey as keyof typeof verdictColors] || 'bg-slate-700 text-white';
  const summaryText = receipt.input_summary || receipt.decision || 'Receipt summary unavailable.';
  const riskFactors = receipt.risk_factors || [];
  const signatures = receipt.signatures || [];
  const agentResponses = receipt.agent_responses || [];

  return (
    <div className="space-y-4">
      <div className="bg-slate-800 rounded-lg p-4 border-l-4 border-blue-500">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-medium text-white">Decision Receipt</h3>
          <span className={`px-3 py-1 rounded font-medium ${verdictClass}`}>
            {String(receipt.verdict || 'unknown')
              .replace('_', ' ')
              .toUpperCase()}
          </span>
        </div>
        <p className="text-slate-300">{summaryText}</p>
        <div className="mt-4">
          <span className="text-slate-400">Confidence:</span>
          <span className="text-white ml-2 font-semibold">
            {(receipt.confidence * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      {riskFactors.length > 0 && (
        <div className="bg-slate-800 rounded-lg p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-3">Risk Factors</h4>
          <div className="space-y-2">
            {riskFactors.map((factor, i) => (
              <div key={i} className="flex items-center justify-between p-2 bg-slate-900 rounded">
                <div>
                  <p className="text-white text-sm">{factor.factor}</p>
                  <p className="text-xs text-slate-400">{factor.assessment}</p>
                </div>
                <span className="text-sm text-slate-300">
                  Weight: {(factor.weight * 100).toFixed(0)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {agentResponses.length > 0 && (
        <div className="bg-slate-800 rounded-lg p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-3">Agent Responses</h4>
          <div className="space-y-3">
            {agentResponses.map((response, i) => (
              <div key={i} className="p-3 bg-slate-900 rounded border border-slate-700">
                <div className="flex flex-wrap items-center gap-2 mb-2">
                  <span className="text-sm font-medium text-white">{response.agent}</span>
                  {response.llm_label && (
                    <span className="text-xs font-theme-data text-cyan-300">
                      {response.llm_label}
                    </span>
                  )}
                  {response.role && (
                    <span className="text-xs text-slate-400 uppercase">{response.role}</span>
                  )}
                  {response.round ? (
                    <span className="text-xs text-slate-500">Round {response.round}</span>
                  ) : null}
                </div>
                <p className="text-sm text-slate-300 whitespace-pre-wrap">{response.response}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {signatures.length > 0 && (
        <div className="bg-slate-800 rounded-lg p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-2">Signatures</h4>
          <div className="flex flex-wrap gap-2">
            {signatures.map((sig, i) => (
              <span
                key={i}
                className="px-2 py-1 bg-slate-700 rounded text-xs font-theme-data text-slate-300"
              >
                {sig}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function RiskScore({ score, large }: { score: number; large?: boolean }) {
  const color =
    score < 0.3
      ? 'text-green-400'
      : score < 0.6
        ? 'text-yellow-400'
        : score < 0.8
          ? 'text-orange-400'
          : 'text-red-400';

  return (
    <div className={`text-right ${large ? '' : ''}`}>
      <span className={`${large ? 'text-2xl' : 'text-lg'} font-bold ${color}`}>
        {(score * 100).toFixed(0)}
      </span>
      <span className={`${large ? 'text-sm' : 'text-xs'} text-slate-400 ml-1`}>risk</span>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors = {
    pending: 'bg-slate-600 text-slate-200',
    running: 'bg-blue-600 text-white',
    completed: 'bg-green-600 text-white',
    failed: 'bg-red-600 text-white',
  };
  const color = colors[status as keyof typeof colors] || colors.pending;
  return <span className={`px-2 py-1 rounded text-xs font-medium ${color}`}>{status}</span>;
}

function SeverityBadge({ severity }: { severity: string }) {
  const colors = {
    low: 'bg-green-600 text-white',
    medium: 'bg-yellow-600 text-black',
    high: 'bg-orange-600 text-white',
    critical: 'bg-red-600 text-white',
  };
  const color = colors[severity.toLowerCase() as keyof typeof colors] || colors.medium;
  return <span className={`px-2 py-0.5 rounded text-xs font-medium ${color}`}>{severity}</span>;
}

export default GauntletRunner;
