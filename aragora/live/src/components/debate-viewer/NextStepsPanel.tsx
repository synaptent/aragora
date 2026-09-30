'use client';

import { useState } from 'react';
import Link from 'next/link';
import { apiFetch } from '@/lib/api';

interface NextStepsPanelProps {
  debateId: string;
}

export function NextStepsPanel({ debateId }: NextStepsPanelProps) {
  const [saveStatus, setSaveStatus] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleSaveToKnowledge = async () => {
    setSaveStatus('loading');
    setSaveError(null);
    try {
      await apiFetch('/api/v1/knowledge/from-debate', {
        method: 'POST',
        body: JSON.stringify({ debate_id: debateId }),
      });
      setSaveStatus('success');
    } catch (err) {
      setSaveStatus('error');
      setSaveError(err instanceof Error ? err.message : 'Failed to save to knowledge');
    }
  };

  return (
    <section className="container mx-auto px-4 mt-8 mb-4">
      <div className="text-[var(--accent)] font-theme-data text-sm mb-4">{'>'} NEXT STEPS</div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* Send to Pipeline */}
        <Link
          href={`/pipeline?from=debate&id=${debateId}`}
          className="group block bg-surface border border-[var(--accent)]/30 rounded p-4 hover:border-[var(--accent)] hover:bg-[var(--accent)]/5 transition-all"
        >
          <div className="flex items-start gap-3">
            <span className="text-[var(--accent)] font-theme-data text-lg shrink-0">
              {'\u25B6'}
            </span>
            <div>
              <div className="text-sm font-theme-data text-[var(--accent)] group-hover:text-[var(--accent)] transition-colors">
                SEND TO PIPELINE
              </div>
              <div className="text-xs font-theme-data text-text-muted mt-1">
                Execute this debate&apos;s outcome through the Idea-to-Execution pipeline.
              </div>
            </div>
          </div>
        </Link>

        {/* Save to Knowledge */}
        <button
          onClick={handleSaveToKnowledge}
          disabled={saveStatus === 'loading' || saveStatus === 'success'}
          className="group text-left bg-surface border border-[var(--accent)]/30 rounded p-4 hover:border-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/5 transition-all disabled:opacity-70 disabled:cursor-not-allowed"
        >
          <div className="flex items-start gap-3">
            <span className="text-[var(--acid-cyan)] font-theme-data text-lg shrink-0">
              {saveStatus === 'loading' ? '\u2026' : saveStatus === 'success' ? '\u2713' : '\u25C6'}
            </span>
            <div>
              <div className="text-sm font-theme-data text-[var(--acid-cyan)] transition-colors">
                {saveStatus === 'loading'
                  ? 'SAVING...'
                  : saveStatus === 'success'
                    ? 'SAVED TO KNOWLEDGE'
                    : 'SAVE TO KNOWLEDGE'}
              </div>
              <div className="text-xs font-theme-data text-text-muted mt-1">
                {saveStatus === 'error'
                  ? saveError || 'Failed to save. Try again.'
                  : saveStatus === 'success'
                    ? 'Debate outcome persisted to the Knowledge Mound.'
                    : 'Persist this debate\u2019s findings to the Knowledge Mound for future reference.'}
              </div>
            </div>
          </div>
        </button>

        {/* Self-Improve from This */}
        <Link
          href={`/self-improve?from=debate&id=${debateId}`}
          className="group block bg-surface border border-[var(--accent)]/30 rounded p-4 hover:border-accent hover:bg-accent/5 transition-all"
        >
          <div className="flex items-start gap-3">
            <span className="text-accent font-theme-data text-lg shrink-0">{'\u21BB'}</span>
            <div>
              <div className="text-sm font-theme-data text-accent group-hover:text-accent transition-colors">
                SELF-IMPROVE FROM THIS
              </div>
              <div className="text-xs font-theme-data text-text-muted mt-1">
                Feed this debate into the Nomic Loop for autonomous self-improvement.
              </div>
            </div>
          </div>
        </Link>

        {/* View Receipt */}
        <Link
          href={`/debates/${debateId}?tab=receipt`}
          className="group block bg-surface border border-[var(--accent)]/30 rounded p-4 hover:border-[var(--accent)] hover:bg-[var(--accent)]/5 transition-all"
        >
          <div className="flex items-start gap-3">
            <span className="text-[var(--accent)] font-theme-data text-lg shrink-0">
              {'\u2637'}
            </span>
            <div>
              <div className="text-sm font-theme-data text-[var(--accent)] group-hover:text-[var(--accent)] transition-colors">
                VIEW RECEIPT
              </div>
              <div className="text-xs font-theme-data text-text-muted mt-1">
                View the cryptographic decision receipt and audit trail.
              </div>
            </div>
          </div>
        </Link>
      </div>
    </section>
  );
}
