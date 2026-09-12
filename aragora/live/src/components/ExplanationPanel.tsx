'use client';

import { useState } from 'react';
import { useExplanation } from '@/hooks/useExplanation';
import type {
  ExplanationData,
  EvidenceLink,
  ConfidenceAttribution,
  Counterfactual,
} from '@/hooks/useExplanation';

// ---------------------------------------------------------------------------
// Collapsible Section
// ---------------------------------------------------------------------------

function Section({
  title,
  defaultOpen = false,
  count,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  count?: number;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="border border-[var(--border)]">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 bg-[var(--surface)] text-left hover:bg-[var(--acid-green)]/5 transition-colors"
      >
        <span className="text-xs font-theme-data text-[var(--acid-green)]">
          {open ? '[-]' : '[+]'} {title}
        </span>
        {count !== undefined && (
          <span className="text-xs font-theme-data text-[var(--text-muted)]">{count}</span>
        )}
      </button>
      {open && (
        <div className="px-4 py-3 bg-[var(--bg)] border-t border-[var(--border)]">{children}</div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function SummarySection({ data }: { data: ExplanationData }) {
  return (
    <Section title="SUMMARY" defaultOpen={true}>
      <div className="space-y-3">
        {data.conclusion && (
          <p className="text-sm font-theme-data text-[var(--text)] whitespace-pre-wrap leading-relaxed">
            {data.conclusion}
          </p>
        )}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2">
          <div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">CONFIDENCE</div>
            <div className="text-sm font-theme-data text-[var(--acid-green)]">
              {Math.round(data.confidence * 100)}%
            </div>
          </div>
          <div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">CONSENSUS</div>
            <div className="text-sm font-theme-data text-[var(--text)]">
              {data.consensus_reached ? 'Yes' : 'No'}{' '}
              <span className="text-[var(--text-muted)]">({data.consensus_type})</span>
            </div>
          </div>
          <div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">EVIDENCE QUALITY</div>
            <div className="text-sm font-theme-data text-[var(--acid-cyan)]">
              {Math.round(data.evidence_quality_score * 100)}%
            </div>
          </div>
          <div>
            <div className="text-xs font-theme-data text-[var(--text-muted)]">AGENT AGREEMENT</div>
            <div className="text-sm font-theme-data text-[var(--acid-cyan)]">
              {Math.round(data.agent_agreement_score * 100)}%
            </div>
          </div>
        </div>
      </div>
    </Section>
  );
}

function FactorsSection({ factors }: { factors: ConfidenceAttribution[] }) {
  if (factors.length === 0) return null;

  return (
    <Section title="CONTRIBUTING FACTORS" count={factors.length}>
      <div className="space-y-2">
        {factors.map((f, i) => (
          <div key={i} className="flex items-center gap-3">
            <div className="flex-shrink-0 w-12 text-right">
              <span className="text-xs font-theme-data text-[var(--acid-green)]">
                {Math.round(f.contribution * 100)}%
              </span>
            </div>
            <div className="flex-1 h-1.5 bg-[var(--border)] overflow-hidden">
              <div
                className="h-full bg-[var(--acid-green)]"
                style={{ width: `${Math.round(f.contribution * 100)}%` }}
              />
            </div>
            <div className="flex-1">
              <div className="text-xs font-theme-data text-[var(--text)]">
                {f.factor.replace(/_/g, ' ').toUpperCase()}
              </div>
              <div className="text-xs font-theme-data text-[var(--text-muted)]">
                {f.explanation}
              </div>
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function EvidenceSection({ evidence }: { evidence: EvidenceLink[] }) {
  if (evidence.length === 0) return null;

  // Sort by relevance descending and take top 10
  const sorted = [...evidence].sort((a, b) => b.relevance_score - a.relevance_score).slice(0, 10);

  return (
    <Section title="EVIDENCE CHAIN" count={evidence.length}>
      <div className="space-y-2">
        {sorted.map((e) => (
          <div key={e.id} className="bg-[var(--surface)] border border-[var(--border)] p-3">
            <div className="flex items-center gap-2 mb-1">
              <span className="px-1.5 py-0.5 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)]">
                {e.source}
              </span>
              <span className="text-xs font-theme-data text-[var(--text-muted)]">
                {e.grounding_type}
              </span>
              <span className="ml-auto text-xs font-theme-data text-[var(--acid-cyan)]">
                {Math.round(e.relevance_score * 100)}% relevant
              </span>
            </div>
            <p className="text-xs font-theme-data text-[var(--text)] whitespace-pre-wrap line-clamp-3">
              {e.content}
            </p>
            {e.cited_by.length > 0 && (
              <div className="mt-1 text-xs font-theme-data text-[var(--text-muted)]">
                Cited by: {e.cited_by.join(', ')}
              </div>
            )}
          </div>
        ))}
      </div>
    </Section>
  );
}

function CounterfactualsSection({ counterfactuals }: { counterfactuals: Counterfactual[] }) {
  if (counterfactuals.length === 0) return null;

  return (
    <Section title="COUNTERFACTUALS" count={counterfactuals.length}>
      <div className="space-y-2">
        {counterfactuals.map((c, i) => (
          <div key={i} className="bg-[var(--surface)] border border-[var(--border)] p-3">
            <div className="text-xs font-theme-data text-[var(--warning)] mb-1">{c.condition}</div>
            <div className="text-xs font-theme-data text-[var(--text)]">{c.outcome_change}</div>
            <div className="flex gap-4 mt-2 text-xs font-theme-data text-[var(--text-muted)]">
              <span>Sensitivity: {Math.round(c.sensitivity * 100)}%</span>
              <span>Likelihood: {Math.round(c.likelihood * 100)}%</span>
            </div>
            {c.affected_agents.length > 0 && (
              <div className="flex flex-wrap gap-1 mt-2">
                {c.affected_agents.map((a, j) => (
                  <span
                    key={j}
                    className="px-1 py-0.5 text-xs font-theme-data bg-[var(--warning)]/10 text-[var(--warning)] border border-[var(--warning)]/30"
                  >
                    {a}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

interface ExplanationPanelProps {
  debateId: string;
}

export function ExplanationPanel({ debateId }: ExplanationPanelProps) {
  const { explanation, loading, error, fetchExplanation } = useExplanation(debateId);
  const [expanded, setExpanded] = useState(false);

  // Collapsed state: show a toggle button
  if (!expanded) {
    return (
      <button
        onClick={() => setExpanded(true)}
        className="w-full px-4 py-3 text-xs font-theme-data text-[var(--acid-cyan)] bg-[var(--surface)] border border-[var(--acid-cyan)]/30 hover:bg-[var(--acid-cyan)]/10 transition-colors text-left"
      >
        {'>'} WHY THIS DECISION?
        <span className="ml-2 text-[var(--text-muted)]">
          Expand to see factors, evidence, and counterfactuals
        </span>
      </button>
    );
  }

  return (
    <div className="space-y-0">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-[var(--surface)] border border-[var(--acid-cyan)]/40">
        <div className="text-xs font-theme-data text-[var(--acid-cyan)]">
          {'>'} WHY THIS DECISION?
        </div>
        <div className="flex items-center gap-2">
          {error && (
            <button
              onClick={fetchExplanation}
              className="text-xs font-theme-data text-[var(--warning)] hover:text-[var(--acid-green)] transition-colors"
            >
              RETRY
            </button>
          )}
          <button
            onClick={() => setExpanded(false)}
            className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--text)] transition-colors"
          >
            COLLAPSE
          </button>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-8 bg-[var(--bg)] border border-t-0 border-[var(--border)]">
          <div className="text-[var(--acid-cyan)] font-theme-data text-xs animate-pulse">
            {'>'} ANALYZING DECISION...
          </div>
        </div>
      )}

      {/* Error */}
      {error && !loading && (
        <div className="px-4 py-4 bg-[var(--bg)] border border-t-0 border-[var(--border)]">
          <div className="text-xs font-theme-data text-[var(--warning)]">
            {'>'} {error}
          </div>
          <p className="text-xs font-theme-data text-[var(--text-muted)] mt-1">
            Explanation data may not be available for this debate.
          </p>
        </div>
      )}

      {/* Content */}
      {explanation && !loading && (
        <div className="space-y-0 border border-t-0 border-[var(--border)]">
          <SummarySection data={explanation} />
          <FactorsSection factors={explanation.confidence_attribution} />
          <EvidenceSection evidence={explanation.evidence_chain} />
          <CounterfactualsSection counterfactuals={explanation.counterfactuals} />
        </div>
      )}
    </div>
  );
}
