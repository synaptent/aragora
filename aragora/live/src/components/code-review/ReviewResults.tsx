'use client';

import { useState } from 'react';
import type { ReviewResult, ReviewFinding } from './CodeReviewWorkflow';

interface ReviewResultsProps {
  result: ReviewResult;
  onNewReview?: () => void;
}

const VERDICT_CONFIG = {
  approve: {
    icon: '✅',
    label: 'APPROVE',
    color: 'text-green-400 bg-green-500/10 border-green-500/30',
  },
  comment: {
    icon: '💬',
    label: 'COMMENT',
    color: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
  },
  request_changes: {
    icon: '❌',
    label: 'REQUEST CHANGES',
    color: 'text-red-400 bg-red-500/10 border-red-500/30',
  },
};

const SEVERITY_STYLES = {
  critical: 'text-red-400 bg-red-500/10 border-red-500/30',
  high: 'text-orange-400 bg-orange-500/10 border-orange-500/30',
  medium: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
  low: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
  info: 'text-gray-400 bg-gray-500/10 border-gray-500/30',
};

const CATEGORY_ICONS = { security: '🔒', performance: '⚡', quality: '✨', architecture: '🏗️' };

export function ReviewResults({ result, onNewReview }: ReviewResultsProps) {
  const [expandedFinding, setExpandedFinding] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'summary' | 'findings' | 'debate'>('summary');

  const verdictConfig = VERDICT_CONFIG[result.verdict];

  // Count findings by severity
  const severityCounts = result.findings.reduce(
    (acc, f) => {
      acc[f.severity] = (acc[f.severity] || 0) + 1;
      return acc;
    },
    {} as Record<string, number>,
  );

  return (
    <div className="space-y-6">
      {/* Verdict Card */}
      <div className={`p-6 border rounded ${verdictConfig.color}`}>
        <div className="flex items-center gap-4">
          <span className="text-5xl">{verdictConfig.icon}</span>
          <div>
            <div className="text-lg font-theme-data">{verdictConfig.label}</div>
            <p className="text-sm text-[var(--text-muted)] mt-1">{result.summary}</p>
          </div>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <MetricCard label="Files Reviewed" value={result.metrics.filesReviewed} />
        <MetricCard label="Lines Analyzed" value={result.metrics.linesAnalyzed.toLocaleString()} />
        <MetricCard label="Agents" value={result.metrics.agentsParticipated} />
        <MetricCard label="Debate Rounds" value={result.metrics.debateRounds} />
        <MetricCard label="Duration" value={`${(result.metrics.duration / 1000).toFixed(1)}s`} />
      </div>

      {/* Severity Summary */}
      <div className="flex gap-3">
        {['critical', 'high', 'medium', 'low', 'info'].map((severity) => {
          const count = severityCounts[severity] || 0;
          if (count === 0) return null;
          return (
            <div
              key={severity}
              className={`px-3 py-1 rounded border ${SEVERITY_STYLES[severity as keyof typeof SEVERITY_STYLES]}`}
            >
              <span className="font-theme-data text-sm uppercase">{severity}</span>
              <span className="ml-2 font-bold">{count}</span>
            </div>
          );
        })}
      </div>

      {/* Tabs */}
      <div className="border-b border-[var(--border)]">
        <div className="flex gap-4">
          {(['summary', 'findings', 'debate'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`py-2 px-4 text-sm font-theme-data transition-colors ${
                activeTab === tab
                  ? 'text-[var(--acid-green)] border-b-2 border-[var(--acid-green)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]'
              }`}
            >
              {tab.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Tab Content */}
      {activeTab === 'summary' && (
        <div className="space-y-4">
          <div className="p-4 bg-[var(--surface)] border border-[var(--border)] rounded">
            <h3 className="text-sm font-theme-data text-[var(--acid-green)] mb-3">Summary</h3>
            <p className="text-sm text-[var(--text)]">{result.summary}</p>
          </div>
        </div>
      )}

      {activeTab === 'findings' && (
        <div className="space-y-3 max-h-[500px] overflow-y-auto">
          {result.findings.length === 0 ? (
            <div className="p-4 text-center text-[var(--text-muted)]">No findings to display</div>
          ) : (
            result.findings.map((finding) => (
              <FindingCard
                key={finding.id}
                finding={finding}
                isExpanded={expandedFinding === finding.id}
                onToggle={() =>
                  setExpandedFinding(expandedFinding === finding.id ? null : finding.id)
                }
              />
            ))
          )}
        </div>
      )}

      {activeTab === 'debate' && (
        <div className="space-y-4 max-h-[500px] overflow-y-auto">
          {result.debateRounds.map((round) => (
            <div
              key={round.round}
              className="p-4 bg-[var(--surface)] border border-[var(--border)] rounded"
            >
              <div className="flex items-center gap-2 mb-3">
                <span className="text-xs font-theme-data text-[var(--acid-cyan)]">
                  Round {round.round}
                </span>
                <span className="text-xs text-[var(--text-muted)]">{round.topic}</span>
              </div>
              <div className="space-y-2">
                {round.messages.map((msg, i) => (
                  <div key={i} className="p-2 bg-[var(--bg)] rounded">
                    <span className="text-xs font-theme-data text-[var(--acid-green)]">
                      {msg.agent}:
                    </span>
                    <p className="text-sm text-[var(--text)] mt-1">{msg.content}</p>
                  </div>
                ))}
              </div>
              {round.consensus && (
                <div className="mt-3 p-2 bg-[var(--acid-green)]/10 border border-[var(--acid-green)]/30 rounded">
                  <span className="text-xs font-theme-data text-[var(--acid-green)]">
                    Consensus:
                  </span>
                  <p className="text-sm text-[var(--text)] mt-1">{round.consensus}</p>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Actions */}
      {onNewReview && (
        <button
          onClick={onNewReview}
          className="w-full py-3 text-sm font-theme-data text-[var(--acid-green)] border border-[var(--acid-green)]/30
                     hover:bg-[var(--acid-green)]/10 transition-colors rounded"
        >
          Start New Review
        </button>
      )}
    </div>
  );
}

interface MetricCardProps {
  label: string;
  value: string | number;
}

function MetricCard({ label, value }: MetricCardProps) {
  return (
    <div className="p-3 bg-[var(--surface)] border border-[var(--border)] rounded text-center">
      <div className="text-lg font-theme-data text-[var(--acid-green)]">{value}</div>
      <div className="text-xs text-[var(--text-muted)]">{label}</div>
    </div>
  );
}

interface FindingCardProps {
  finding: ReviewFinding;
  isExpanded: boolean;
  onToggle: () => void;
}

function FindingCard({ finding, isExpanded, onToggle }: FindingCardProps) {
  const severityStyle = SEVERITY_STYLES[finding.severity];
  const categoryIcon = CATEGORY_ICONS[finding.category] || '📋';

  return (
    <div className={`border rounded ${severityStyle}`}>
      <button onClick={onToggle} className="w-full p-4 text-left flex items-start gap-3">
        <span className="text-xl flex-shrink-0">{categoryIcon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-theme-data uppercase">{finding.severity}</span>
            <span className="text-xs text-[var(--text-muted)]">by {finding.agent}</span>
          </div>
          <h4 className="font-theme-data text-sm">{finding.title}</h4>
          {finding.file && (
            <p className="text-xs text-[var(--text-muted)] mt-1">
              {finding.file}
              {finding.line ? `:${finding.line}` : ''}
            </p>
          )}
        </div>
        <span className="text-[var(--text-muted)]">{isExpanded ? '▲' : '▼'}</span>
      </button>

      {isExpanded && (
        <div className="p-4 pt-0 border-t border-[var(--border)]">
          <p className="text-sm text-[var(--text)] mb-3">{finding.description}</p>

          {finding.codeSnippet && (
            <pre className="p-3 bg-[var(--bg)] rounded text-xs overflow-x-auto mb-3">
              <code>{finding.codeSnippet}</code>
            </pre>
          )}

          {finding.suggestion && (
            <div className="p-3 bg-[var(--acid-green)]/10 rounded">
              <span className="text-xs font-theme-data text-[var(--acid-green)]">Suggestion:</span>
              <p className="text-sm text-[var(--text)] mt-1">{finding.suggestion}</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default ReviewResults;
