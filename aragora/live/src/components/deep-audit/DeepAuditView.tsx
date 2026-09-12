'use client';

import { useState } from 'react';
import { useAuditData } from './useAuditData';
import { RoundTimeline } from './RoundTimeline';
import { FindingsSection } from './FindingsSection';
import { VerdictSection } from './VerdictSection';
import { CrossExamNotes } from './CrossExamNotes';
import type { DeepAuditViewProps } from './types';
import { AUDIT_ROUNDS } from './types';

export function DeepAuditView({ events, isActive, onToggle }: DeepAuditViewProps) {
  const [expandedRound, setExpandedRound] = useState<number | null>(null);
  const [showFindings, setShowFindings] = useState(false);
  const { roundData, auditState } = useAuditData(events);

  const completedRounds = roundData.filter((r) => r.status === 'complete').length;
  const activeRound = roundData.find((r) => r.status === 'active');

  if (!isActive) {
    return (
      <button
        onClick={onToggle}
        className="px-3 py-1.5 text-sm bg-purple-500/20 text-purple-400 border border-purple-500/30 rounded hover:bg-purple-500/30 flex items-center gap-2"
      >
        <span>🔬</span>
        <span>Deep Audit Mode</span>
      </button>
    );
  }

  return (
    <div className="bg-gradient-to-br from-purple-500/5 to-indigo-500/5 border border-purple-500/30 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="bg-purple-500/10 px-4 py-3 border-b border-purple-500/20 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="text-lg">🔬</span>
          <div>
            <h3 className="text-sm font-semibold text-purple-400">Deep Audit Mode</h3>
            <p className="text-xs text-text-muted">{completedRounds}/6 rounds complete</p>
          </div>
        </div>
        <button
          onClick={onToggle}
          className="px-2 py-1 text-xs bg-surface border border-border rounded hover:bg-surface-hover"
        >
          Exit
        </button>
      </div>

      <RoundTimeline
        roundData={roundData}
        expandedRound={expandedRound}
        onExpandRound={setExpandedRound}
      />

      {/* Active Round Summary */}
      {activeRound && (
        <div className="px-4 pb-4">
          <div className="p-3 bg-accent/10 border border-accent/30 rounded-lg">
            <div className="flex items-center gap-2 mb-1">
              <span className="w-2 h-2 bg-accent rounded-full animate-pulse" />
              <span className="text-sm font-medium text-accent">
                Currently: {AUDIT_ROUNDS.find((r) => r.round === activeRound.round)?.name}
              </span>
            </div>
            <p className="text-xs text-text-muted">
              {activeRound.messages.length} agents have responded in this round
            </p>
          </div>
        </div>
      )}

      <FindingsSection
        findings={auditState.findings}
        showFindings={showFindings}
        onToggle={() => setShowFindings(!showFindings)}
      />

      {auditState.verdict && <VerdictSection verdict={auditState.verdict} />}

      {auditState.crossExamNotes && <CrossExamNotes notes={auditState.crossExamNotes} />}
    </div>
  );
}
