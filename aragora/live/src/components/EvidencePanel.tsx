'use client';

import { useState, memo } from 'react';
import {
  useEvidence,
  type CitedClaim,
  type EvidenceCitation,
  type RelatedEvidence,
} from '@/hooks/useEvidence';

interface EvidencePanelProps {
  debateId: string;
}

const QUALITY_COLORS: Record<string, { text: string; bg: string }> = {
  authoritative: { text: 'text-[var(--accent)]', bg: 'bg-[var(--accent)]/10' },
  reputable: { text: 'text-[var(--acid-cyan)]', bg: 'bg-[var(--acid-cyan)]/10' },
  mixed: { text: 'text-[var(--acid-yellow)]', bg: 'bg-acid-yellow/10' },
  unverified: { text: 'text-text-muted', bg: 'bg-surface' },
};

const TYPE_ICONS: Record<string, string> = {
  web_page: 'W',
  documentation: 'D',
  code_repository: 'C',
  academic: 'A',
  unknown: '?',
};

function GroundingScoreBar({ score }: { score: number }) {
  const percentage = Math.round(score * 100);
  const getColor = () => {
    if (percentage >= 80) return 'bg-[var(--accent)]';
    if (percentage >= 60) return 'bg-[var(--acid-cyan)]';
    if (percentage >= 40) return 'bg-acid-yellow';
    return 'bg-acid-red';
  };

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-surface rounded overflow-hidden">
        <div
          className={`h-full ${getColor()} transition-all duration-300`}
          style={{ width: `${percentage}%` }}
        />
      </div>
      <span className="text-xs font-theme-data text-text-muted w-10 text-right">{percentage}%</span>
    </div>
  );
}

const CitationCard = memo(function CitationCard({ citation }: { citation: EvidenceCitation }) {
  const [expanded, setExpanded] = useState(false);
  const quality = QUALITY_COLORS[citation.quality] || QUALITY_COLORS.unverified;
  const typeIcon = TYPE_ICONS[citation.citation_type] || '?';

  return (
    <div className={`p-3 rounded border border-[var(--accent)]/20 ${quality.bg}`}>
      <div className="flex items-start gap-2">
        <span
          className={`flex-shrink-0 w-5 h-5 flex items-center justify-center text-xs font-theme-data ${quality.text} border border-current rounded`}
          title={citation.citation_type}
        >
          {typeIcon}
        </span>
        <div className="flex-1 min-w-0">
          <a
            href={citation.url}
            target="_blank"
            rel="noopener noreferrer"
            className={`text-sm font-theme-data ${quality.text} hover:underline block truncate`}
            title={citation.title}
          >
            {citation.title || citation.url}
          </a>
          <div className="flex items-center gap-2 mt-1 text-xs font-theme-data text-text-muted">
            <span className={`uppercase ${quality.text}`}>{citation.quality}</span>
            <span>|</span>
            <span>Relevance: {Math.round(citation.relevance_score * 100)}%</span>
          </div>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
          aria-label={expanded ? 'Collapse' : 'Expand'}
        >
          {expanded ? '[-]' : '[+]'}
        </button>
      </div>
      {expanded && citation.excerpt && (
        <div className="mt-2 p-2 bg-bg/50 rounded text-xs font-theme-data text-text-muted line-clamp-4">
          {citation.excerpt}
        </div>
      )}
    </div>
  );
});

function ClaimCard({ claim }: { claim: CitedClaim }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="p-3 bg-surface rounded border border-[var(--acid-cyan)]/20">
      <div
        className="flex items-start justify-between gap-2 cursor-pointer"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex-1 min-w-0">
          <p className="text-sm font-theme-data text-text line-clamp-2">{claim.claim_text}</p>
          <div className="flex items-center gap-3 mt-2">
            <div className="flex-1 max-w-32">
              <GroundingScoreBar score={claim.grounding_score} />
            </div>
            <span className="text-xs font-theme-data text-text-muted">
              {claim.citations.length} source{claim.citations.length !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
        <span className="text-xs font-theme-data text-text-muted">{expanded ? '[-]' : '[+]'}</span>
      </div>
      {expanded && claim.citations.length > 0 && (
        <div className="mt-3 space-y-2 pl-2 border-l-2 border-[var(--acid-cyan)]/30">
          {claim.citations.map((citation, idx) => (
            <CitationCard key={citation.id || idx} citation={citation} />
          ))}
        </div>
      )}
    </div>
  );
}

function RelatedEvidenceCard({ evidence }: { evidence: RelatedEvidence }) {
  return (
    <div className="p-2 bg-surface/50 rounded border border-[var(--accent)]/10">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase">
          {evidence.source}
        </span>
        <span className="text-xs font-theme-data text-text-muted">
          {Math.round(evidence.importance * 100)}% imp
        </span>
      </div>
      <p className="text-xs font-theme-data text-text-muted line-clamp-2">{evidence.content}</p>
    </div>
  );
}

/**
 * Panel displaying evidence and citations for a debate
 *
 * Shows:
 * - Overall grounding score
 * - Claims with linked citations
 * - Related evidence from memory
 */
export function EvidencePanel({ debateId }: EvidencePanelProps) {
  const {
    evidence,
    loading,
    error,
    refetch,
    hasEvidence,
    groundingScore,
    claimsCount,
    citationsCount,
  } = useEvidence(debateId);

  const [activeTab, setActiveTab] = useState<'claims' | 'citations' | 'related'>('claims');

  if (loading) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/50">
        <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {'>'} EVIDENCE
          </span>
        </div>
        <div className="p-4 flex items-center gap-2">
          <div className="w-4 h-4 border-2 border-[var(--accent)]/40 border-t-acid-green rounded-full animate-spin" />
          <span className="text-xs font-theme-data text-text-muted">Loading evidence...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/50">
        <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {'>'} EVIDENCE
          </span>
        </div>
        <div className="p-4">
          <div className="p-3 text-xs font-theme-data text-warning bg-warning/10 border border-warning/30">
            {'>'} {error}
          </div>
          <button
            onClick={refetch}
            className="mt-3 px-3 py-1 text-xs font-theme-data border border-[var(--accent)]/40 hover:bg-[var(--accent)]/10"
          >
            [RETRY]
          </button>
        </div>
      </div>
    );
  }

  if (!hasEvidence) {
    return (
      <div className="border border-[var(--accent)]/30 bg-surface/50">
        <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50">
          <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
            {'>'} EVIDENCE
          </span>
        </div>
        <div className="p-4 text-center">
          <p className="text-xs font-theme-data text-text-muted">
            No evidence citations available for this debate.
          </p>
          <p className="text-xs font-theme-data text-text-muted mt-1">
            Evidence is collected when agents cite external sources.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="border border-[var(--accent)]/30 bg-surface/50">
      {/* Header */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/20 bg-bg/50 flex items-center justify-between">
        <span className="text-xs font-theme-data text-[var(--accent)] uppercase tracking-wider">
          {'>'} EVIDENCE
        </span>
        <button
          onClick={refetch}
          className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)]"
          aria-label="Refresh evidence"
        >
          [REFRESH]
        </button>
      </div>

      {/* Grounding Score */}
      <div className="px-4 py-3 border-b border-[var(--accent)]/10">
        <div className="text-xs font-theme-data text-text-muted mb-2">Grounding Score</div>
        <GroundingScoreBar score={groundingScore} />
        <div className="flex items-center gap-4 mt-2 text-xs font-theme-data text-text-muted">
          <span>
            {claimsCount} claim{claimsCount !== 1 ? 's' : ''}
          </span>
          <span>
            {citationsCount} citation{citationsCount !== 1 ? 's' : ''}
          </span>
          <span>{evidence?.evidence_count ?? 0} related</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-[var(--accent)]/10">
        {(['claims', 'citations', 'related'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={`flex-1 px-4 py-2 text-xs font-theme-data uppercase transition-colors ${
              activeTab === tab
                ? 'text-[var(--accent)] border-b-2 border-[var(--accent)] bg-[var(--accent)]/5'
                : 'text-text-muted hover:text-text'
            }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="p-4 max-h-96 overflow-y-auto">
        {activeTab === 'claims' && (
          <div className="space-y-3">
            {evidence?.claims && evidence.claims.length > 0 ? (
              evidence.claims.map((claim, idx) => <ClaimCard key={idx} claim={claim} />)
            ) : (
              <p className="text-xs font-theme-data text-text-muted text-center py-4">
                No claims extracted from this debate.
              </p>
            )}
          </div>
        )}

        {activeTab === 'citations' && (
          <div className="space-y-2">
            {evidence?.citations && evidence.citations.length > 0 ? (
              evidence.citations.map((citation, idx) => (
                <CitationCard key={citation.id || idx} citation={citation} />
              ))
            ) : (
              <p className="text-xs font-theme-data text-text-muted text-center py-4">
                No citations found for this debate.
              </p>
            )}
          </div>
        )}

        {activeTab === 'related' && (
          <div className="space-y-2">
            {evidence?.related_evidence && evidence.related_evidence.length > 0 ? (
              evidence.related_evidence.map((ev, idx) => (
                <RelatedEvidenceCard key={ev.id || idx} evidence={ev} />
              ))
            ) : (
              <p className="text-xs font-theme-data text-text-muted text-center py-4">
                No related evidence in memory.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
