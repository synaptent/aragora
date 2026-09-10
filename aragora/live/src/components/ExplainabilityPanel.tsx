'use client';

import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '@/lib/api';

interface Factor {
  name: string;
  contribution: number;
  description: string;
}

interface Counterfactual {
  scenario: string;
  outcome: string;
  probability: number;
}

interface ProvenanceEntry {
  step: number;
  action: string;
  timestamp: string;
  agent?: string;
  confidence?: number;
}

interface Explanation {
  debate_id: string;
  narrative: string;
  confidence: number;
  factors: Factor[];
  counterfactuals: Counterfactual[];
  provenance: ProvenanceEntry[];
  generated_at: string;
}

interface ExplainabilityPanelProps {
  debateId: string;
}

export function ExplainabilityPanel({ debateId }: ExplainabilityPanelProps) {
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    'narrative' | 'factors' | 'counterfactual' | 'provenance'
  >('narrative');

  const fetchExplanation = useCallback(async () => {
    if (!debateId) return;

    setLoading(true);
    setError(null);

    try {
      const data = await apiFetch<Explanation>(`/api/debates/${debateId}/explainability`);
      setExplanation(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch explanation');
    } finally {
      setLoading(false);
    }
  }, [debateId]);

  useEffect(() => {
    fetchExplanation();
  }, [fetchExplanation]);

  if (loading) {
    return (
      <div className="card p-6">
        <div className="text-center text-text-muted font-theme-data">
          <span className="animate-pulse">Generating explanation...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="card p-6">
        <div className="text-center text-red-400 font-theme-data">
          <p>Error: {error}</p>
          <button
            onClick={fetchExplanation}
            className="mt-4 px-4 py-2 border border-[var(--accent)]/50 text-[var(--accent)] hover:bg-[var(--accent)]/10"
          >
            [RETRY]
          </button>
        </div>
      </div>
    );
  }

  if (!explanation) {
    return (
      <div className="card p-6">
        <div className="text-center text-text-muted font-theme-data">
          No explanation available for this debate.
        </div>
      </div>
    );
  }

  return (
    <div className="card p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <h3 className="font-theme-data text-[var(--accent)] text-lg">
          {'>'} DECISION EXPLAINABILITY
        </h3>
        <div className="text-xs font-theme-data text-text-muted">
          Confidence: {(explanation.confidence * 100).toFixed(1)}%
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-2 mb-6 border-b border-[var(--accent)]/20 pb-2">
        {(['narrative', 'factors', 'counterfactual', 'provenance'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`px-3 py-1 text-xs font-theme-data transition-colors ${
              activeTab === tab
                ? 'border border-[var(--accent)] bg-[var(--accent)]/20 text-[var(--accent)]'
                : 'border border-transparent text-text-muted hover:text-[var(--accent)]'
            }`}
          >
            [{tab.toUpperCase()}]
          </button>
        ))}
      </div>

      {/* Narrative Tab */}
      {activeTab === 'narrative' && (
        <div className="space-y-4">
          <div className="bg-bg border border-[var(--accent)]/20 p-4">
            <p className="font-theme-data text-sm text-text whitespace-pre-wrap">
              {explanation.narrative}
            </p>
          </div>
          <div className="text-xs font-theme-data text-text-muted text-right">
            Generated: {new Date(explanation.generated_at).toLocaleString()}
          </div>
        </div>
      )}

      {/* Factors Tab */}
      {activeTab === 'factors' && (
        <div className="space-y-4">
          {explanation.factors.map((factor, idx) => (
            <div key={idx} className="border border-[var(--accent)]/20 p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="font-theme-data text-[var(--acid-cyan)] text-sm">
                  {factor.name}
                </span>
                <span
                  className={`font-theme-data text-sm ${
                    factor.contribution > 0 ? 'text-green-400' : 'text-red-400'
                  }`}
                >
                  {factor.contribution > 0 ? '+' : ''}
                  {(factor.contribution * 100).toFixed(1)}%
                </span>
              </div>
              <p className="font-theme-data text-xs text-text-muted">{factor.description}</p>
              {/* Contribution bar */}
              <div className="mt-2 h-1 bg-surface rounded">
                <div
                  className={`h-full rounded ${factor.contribution > 0 ? 'bg-green-400' : 'bg-red-400'}`}
                  style={{ width: `${Math.abs(factor.contribution) * 100}%` }}
                />
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Counterfactual Tab */}
      {activeTab === 'counterfactual' && (
        <div className="space-y-4">
          <p className="text-xs font-theme-data text-text-muted mb-4">
            What-if scenarios showing how different inputs might have changed the outcome.
          </p>
          {explanation.counterfactuals.map((cf, idx) => (
            <div key={idx} className="border border-[var(--accent)]/20 p-4">
              <div className="mb-2">
                <span className="font-theme-data text-xs text-text-muted">IF:</span>
                <p className="font-theme-data text-sm text-text">{cf.scenario}</p>
              </div>
              <div className="mb-2">
                <span className="font-theme-data text-xs text-text-muted">THEN:</span>
                <p className="font-theme-data text-sm text-[var(--acid-cyan)]">{cf.outcome}</p>
              </div>
              <div className="flex items-center gap-2">
                <span className="font-theme-data text-xs text-text-muted">Probability:</span>
                <div className="flex-1 h-1 bg-surface rounded">
                  <div
                    className="h-full bg-[var(--acid-cyan)] rounded"
                    style={{ width: `${cf.probability * 100}%` }}
                  />
                </div>
                <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                  {(cf.probability * 100).toFixed(0)}%
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Provenance Tab */}
      {activeTab === 'provenance' && (
        <div className="space-y-2">
          <p className="text-xs font-theme-data text-text-muted mb-4">
            Decision chain showing how the conclusion was reached.
          </p>
          {explanation.provenance.map((entry, idx) => (
            <div
              key={idx}
              className="flex items-start gap-4 border-l-2 border-[var(--accent)]/30 pl-4 py-2"
            >
              <div className="w-6 h-6 flex items-center justify-center bg-[var(--accent)]/20 text-[var(--accent)] font-theme-data text-xs">
                {entry.step}
              </div>
              <div className="flex-1">
                <p className="font-theme-data text-sm text-text">{entry.action}</p>
                <div className="flex gap-4 mt-1">
                  {entry.agent && (
                    <span className="font-theme-data text-xs text-[var(--acid-cyan)]">
                      {entry.agent}
                    </span>
                  )}
                  {entry.confidence !== undefined && (
                    <span className="font-theme-data text-xs text-text-muted">
                      {(entry.confidence * 100).toFixed(0)}% confidence
                    </span>
                  )}
                  <span className="font-theme-data text-xs text-text-muted/50">
                    {new Date(entry.timestamp).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export default ExplainabilityPanel;
