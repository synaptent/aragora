'use client';

import { useMemo, useState, useEffect } from 'react';
import type { StreamEvent } from '@/types/events';
import { logger } from '@/utils/logger';

interface VerdictCardProps {
  events: StreamEvent[];
  debateId?: string;
  apiUrl?: string;
}

interface Verdict {
  recommendation: string;
  confidence: number;
  grounding: number;
  unanimousIssues: string[];
  splitOpinions: string[];
  riskAreas: string[];
  citationCount: number;
  crossExamination?: string;
  timestamp: number;
}

interface DebateSummary {
  one_liner: string;
  key_points: string[];
  agreement_areas: string[];
  disagreement_areas: string[];
  confidence: number;
  confidence_label: string;
  consensus_strength: string;
  next_steps: string[];
  caveats: string[];
  rounds_used: number;
  agents_participated: number;
  duration_seconds: number;
}

export function VerdictCard({ events, debateId, apiUrl }: VerdictCardProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [summary, setSummary] = useState<DebateSummary | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);

  // Fetch summary when debate is complete and we have a debateId
  useEffect(() => {
    if (!debateId) return;

    // Check if debate is complete (has verdict/consensus event)
    const isComplete = events.some(
      (e) =>
        e.type === 'grounded_verdict' ||
        e.type === 'verdict' ||
        e.type === 'consensus' ||
        e.type === 'debate_end',
    );

    if (!isComplete) return;

    const fetchSummary = async () => {
      setSummaryLoading(true);
      try {
        const baseUrl = apiUrl || '';
        const response = await fetch(`${baseUrl}/api/debates/${debateId}/summary`);
        if (response.ok) {
          const data = await response.json();
          setSummary(data.summary);
        }
      } catch (error) {
        logger.error('Failed to fetch debate summary:', error);
      } finally {
        setSummaryLoading(false);
      }
    };

    fetchSummary();
  }, [debateId, apiUrl, events]);

  // Extract verdict from consensus/verdict events
  const verdict = useMemo<Verdict | null>(() => {
    // Look for verdict or consensus events (prefer most recent)
    const verdictEvents = events.filter(
      (e) => e.type === 'grounded_verdict' || e.type === 'verdict' || e.type === 'consensus',
    );

    if (verdictEvents.length === 0) return null;

    const latest = verdictEvents[verdictEvents.length - 1];
    // Cast to Record since verdict data can have various fields depending on event type
    const data = latest.data as Record<string, unknown>;

    return {
      recommendation: (data.recommendation || data.answer || data.content || '') as string,
      confidence: (data.confidence ?? 0.5) as number,
      grounding: (data.grounding_score ?? data.evidence_grounding ?? 0) as number,
      unanimousIssues: (data.unanimous_issues || []) as string[],
      splitOpinions: (data.split_opinions || []) as string[],
      riskAreas: (data.risk_areas || []) as string[],
      citationCount: Array.isArray(data.all_citations)
        ? (data.all_citations as unknown[]).length
        : ((data.citation_count || 0) as number),
      crossExamination: data.cross_examination_notes as string | undefined,
      timestamp: latest.timestamp,
    };
  }, [events]);

  if (!verdict) {
    return null;
  }

  const confidenceColor =
    verdict.confidence >= 0.8
      ? 'text-green-400'
      : verdict.confidence >= 0.6
        ? 'text-yellow-400'
        : 'text-red-400';

  const groundingColor =
    verdict.grounding >= 0.7
      ? 'text-green-400'
      : verdict.grounding >= 0.5
        ? 'text-yellow-400'
        : 'text-orange-400';

  return (
    <div className="bg-gradient-to-br from-accent/10 to-purple-500/10 border-2 border-accent/50 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="bg-accent/20 px-4 py-3 border-b border-accent/30">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">⚖️</span>
            <h3 className="text-sm font-semibold uppercase tracking-wider text-accent">
              Debate Verdict
            </h3>
          </div>
          <span className="text-xs text-text-muted">
            {new Date(verdict.timestamp * 1000).toLocaleTimeString()}
          </span>
        </div>
      </div>

      {/* Hollow Consensus Warning */}
      {events.filter((e) => e.type === 'hollow_consensus').length > 0 && (
        <div className="mx-4 mt-3 p-3 border border-acid-yellow/50 bg-acid-yellow/10 rounded">
          <div className="flex items-center gap-2">
            <span className="text-[var(--acid-yellow)] font-theme-data text-sm font-bold">
              [!] HOLLOW CONSENSUS
            </span>
          </div>
          <p className="text-xs font-theme-data text-[var(--acid-yellow)]/80 mt-1">
            Agents may have converged superficially without genuine agreement. Review individual
            positions carefully.
          </p>
        </div>
      )}

      {/* Content */}
      <div className="p-4">
        {/* Recommendation */}
        <div className="mb-4">
          <p className="agent-output text-text">
            {isExpanded
              ? verdict.recommendation
              : verdict.recommendation.slice(0, 300) +
                (verdict.recommendation.length > 300 ? '...' : '')}
          </p>
          {verdict.recommendation.length > 300 && (
            <button
              onClick={() => setIsExpanded(!isExpanded)}
              className="text-xs text-accent hover:underline mt-1"
            >
              {isExpanded ? 'Show less' : 'Show more'}
            </button>
          )}
        </div>

        {/* Metrics Row */}
        <div className="flex items-center gap-4 mb-4">
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-muted">Confidence:</span>
            <span className={`text-sm font-theme-data font-bold ${confidenceColor}`}>
              {Math.round(verdict.confidence * 100)}%
            </span>
          </div>
          {verdict.grounding > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">Evidence:</span>
              <span className={`text-sm font-theme-data font-bold ${groundingColor}`}>
                {Math.round(verdict.grounding * 100)}%
              </span>
            </div>
          )}
          {verdict.citationCount > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-xs text-text-muted">📚</span>
              <span className="text-sm font-theme-data text-text">{verdict.citationCount}</span>
            </div>
          )}
        </div>

        {/* Issues Summary */}
        <div className="space-y-2">
          {/* Unanimous Issues */}
          {verdict.unanimousIssues.length > 0 && (
            <div className="flex items-start gap-2">
              <span className="text-green-400 flex-shrink-0">✓</span>
              <div>
                <span className="text-xs font-medium text-green-400">
                  {verdict.unanimousIssues.length} Unanimous Issue
                  {verdict.unanimousIssues.length !== 1 ? 's' : ''}
                </span>
                <ul className="text-xs text-text-muted mt-0.5">
                  {verdict.unanimousIssues.slice(0, 2).map((issue, i) => (
                    <li key={i} className="truncate">
                      • {issue}
                    </li>
                  ))}
                  {verdict.unanimousIssues.length > 2 && (
                    <li className="text-text-muted">+{verdict.unanimousIssues.length - 2} more</li>
                  )}
                </ul>
              </div>
            </div>
          )}

          {/* Split Opinions */}
          {verdict.splitOpinions.length > 0 && (
            <div className="flex items-start gap-2">
              <span className="text-yellow-400 flex-shrink-0">⚠</span>
              <div>
                <span className="text-xs font-medium text-yellow-400">
                  {verdict.splitOpinions.length} Split Opinion
                  {verdict.splitOpinions.length !== 1 ? 's' : ''}
                </span>
                <ul className="text-xs text-text-muted mt-0.5">
                  {verdict.splitOpinions.slice(0, 2).map((opinion, i) => (
                    <li key={i} className="truncate">
                      • {opinion}
                    </li>
                  ))}
                  {verdict.splitOpinions.length > 2 && (
                    <li className="text-text-muted">+{verdict.splitOpinions.length - 2} more</li>
                  )}
                </ul>
              </div>
            </div>
          )}

          {/* Risk Areas */}
          {verdict.riskAreas.length > 0 && (
            <div className="flex items-start gap-2">
              <span className="text-red-400 flex-shrink-0">!</span>
              <div>
                <span className="text-xs font-medium text-red-400">
                  {verdict.riskAreas.length} Risk Area{verdict.riskAreas.length !== 1 ? 's' : ''}
                </span>
                <ul className="text-xs text-text-muted mt-0.5">
                  {verdict.riskAreas.slice(0, 2).map((risk, i) => (
                    <li key={i} className="truncate">
                      • {risk}
                    </li>
                  ))}
                  {verdict.riskAreas.length > 2 && (
                    <li className="text-text-muted">+{verdict.riskAreas.length - 2} more</li>
                  )}
                </ul>
              </div>
            </div>
          )}
        </div>

        {/* Cross-Examination Notes */}
        {verdict.crossExamination && (
          <details className="mt-4">
            <summary className="text-xs text-text-muted cursor-pointer hover:text-text">
              Cross-Examination Notes
            </summary>
            <div className="mt-2 p-2 bg-bg rounded text-xs text-text-muted whitespace-pre-wrap">
              {verdict.crossExamination.slice(0, 500)}
              {verdict.crossExamination.length > 500 && '...'}
            </div>
          </details>
        )}

        {/* AI Summary Section */}
        {(summary || summaryLoading) && (
          <div className="mt-4 pt-4 border-t border-accent/20">
            <h4 className="text-xs font-semibold uppercase tracking-wider text-accent mb-3 flex items-center gap-2">
              <span>📋</span>
              Summary
              {summaryLoading && (
                <span className="animate-pulse text-text-muted">(loading...)</span>
              )}
            </h4>

            {summary && (
              <div className="space-y-3">
                {/* One-liner */}
                {summary.one_liner && (
                  <p className="text-sm text-text font-medium border-l-2 border-accent/50 pl-3">
                    {summary.one_liner}
                  </p>
                )}

                {/* Key Points */}
                {summary.key_points.length > 0 && (
                  <div>
                    <span className="text-xs font-medium text-accent">Key Points:</span>
                    <ul className="mt-1 space-y-1">
                      {summary.key_points.slice(0, 3).map((point, i) => (
                        <li key={i} className="text-xs text-text-muted flex items-start gap-2">
                          <span className="text-accent">•</span>
                          <span>{point}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Agreement/Disagreement */}
                <div className="flex gap-4 text-xs">
                  {summary.agreement_areas.length > 0 && (
                    <div className="flex-1">
                      <span className="font-medium text-green-400">✓ Agreements:</span>
                      <ul className="mt-1 text-text-muted">
                        {summary.agreement_areas.slice(0, 2).map((area, i) => (
                          <li key={i} className="truncate">
                            • {area}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {summary.disagreement_areas.length > 0 && (
                    <div className="flex-1">
                      <span className="font-medium text-yellow-400">⚠ Disagreements:</span>
                      <ul className="mt-1 text-text-muted">
                        {summary.disagreement_areas.slice(0, 2).map((area, i) => (
                          <li key={i} className="truncate">
                            • {area}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>

                {/* Next Steps */}
                {summary.next_steps.length > 0 && (
                  <div>
                    <span className="text-xs font-medium text-accent">Next Steps:</span>
                    <ul className="mt-1 space-y-1">
                      {summary.next_steps.slice(0, 3).map((step, i) => (
                        <li key={i} className="text-xs text-text-muted flex items-start gap-2">
                          <span className="text-blue-400">→</span>
                          <span>{step}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Caveats */}
                {summary.caveats.length > 0 && (
                  <div className="bg-orange-500/10 border border-orange-500/20 rounded p-2">
                    <span className="text-xs font-medium text-orange-400">⚠ Caveats:</span>
                    <ul className="mt-1">
                      {summary.caveats.map((caveat, i) => (
                        <li key={i} className="text-xs text-orange-300/80">
                          • {caveat}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Metadata */}
                <div className="flex gap-4 text-xs text-text-muted pt-2 border-t border-accent/10">
                  <span>{summary.agents_participated} agents</span>
                  <span>{summary.rounds_used} rounds</span>
                  <span>{summary.duration_seconds.toFixed(1)}s</span>
                  {summary.consensus_strength !== 'none' && (
                    <span
                      className={
                        summary.consensus_strength === 'strong'
                          ? 'text-green-400'
                          : summary.consensus_strength === 'medium'
                            ? 'text-yellow-400'
                            : 'text-text-muted'
                      }
                    >
                      {summary.consensus_strength} consensus
                    </span>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// Mini verdict badge for use in headers/lists
export function VerdictBadge({ confidence }: { confidence: number }) {
  const color =
    confidence >= 0.8
      ? 'bg-green-500/20 text-green-400 border-green-500/30'
      : confidence >= 0.6
        ? 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
        : 'bg-red-500/20 text-red-400 border-red-500/30';

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 text-xs rounded border ${color}`}>
      ⚖️ {Math.round(confidence * 100)}%
    </span>
  );
}
