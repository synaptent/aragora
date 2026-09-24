'use client';

import { useEffect, useMemo, useState } from 'react';

import { DebateThisButton } from '../DebateThisButton';

export interface TransitionData {
  id: string;
  from_stage: string;
  to_stage: string;
  ai_rationale?: string;
  confidence?: number;
  status?: string;
  human_notes?: string;
  reviewed_at?: number | null;
}

export interface TransitionProvenanceLink {
  source_node_id: string;
  target_node_id: string;
  content_hash: string;
  method?: string;
}

export interface StageTransitionNodeLookup {
  [nodeId: string]: { label: string; stage?: string };
}

export interface StageTransitionGateProps {
  transition: TransitionData;
  pipelineId: string;
  provenance?: TransitionProvenanceLink[];
  nodeLookup?: StageTransitionNodeLookup;
  questions?: string[];
  focusLabel?: string;
  onApprove?: (pipelineId: string, transitionId: string) => void;
  onReject?: (pipelineId: string, transitionId: string) => void;
}

const STATUS_META: Record<string, { label: string; className: string }> = {
  pending: {
    label: 'Awaiting approval',
    className: 'bg-yellow-500/15 text-yellow-300 border-yellow-500/40',
  },
  approved: {
    label: 'Approved',
    className: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/40',
  },
  rejected: { label: 'Rejected', className: 'bg-red-500/15 text-red-300 border-red-500/40' },
  revised: {
    label: 'Needs revision',
    className: 'bg-blue-500/15 text-blue-300 border-blue-500/40',
  },
};

function formatReviewedAt(timestamp: number | null | undefined): string | null {
  if (!timestamp) return null;
  const normalized = timestamp > 1_000_000_000_000 ? timestamp : timestamp * 1000;
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(new Date(normalized));
}

export function StageTransitionGate({
  transition,
  pipelineId,
  provenance = [],
  nodeLookup = {},
  questions = [],
  focusLabel,
  onApprove,
  onReject,
}: StageTransitionGateProps) {
  const confidence = transition.confidence ?? 0;
  const confidencePct = Math.round(confidence * 100);
  const initialStatus = transition.status ?? 'pending';
  const [decisionStatus, setDecisionStatus] = useState(initialStatus);
  const [reviewedAt, setReviewedAt] = useState<number | null>(transition.reviewed_at ?? null);

  useEffect(() => {
    setDecisionStatus(initialStatus);
    setReviewedAt(transition.reviewed_at ?? null);
  }, [initialStatus, transition.reviewed_at, transition.id]);

  const statusMeta = STATUS_META[decisionStatus] ?? STATUS_META.pending;
  const canReview = decisionStatus === 'pending';
  const reviewedLabel = formatReviewedAt(reviewedAt);

  const provenanceSummary = useMemo(() => {
    const sourceIds = Array.from(new Set(provenance.map((link) => link.source_node_id)));
    const targetIds = Array.from(new Set(provenance.map((link) => link.target_node_id)));
    return {
      sourceLabels: sourceIds.map((id) => nodeLookup[id]?.label ?? id).slice(0, 3),
      targetLabels: targetIds.map((id) => nodeLookup[id]?.label ?? id).slice(0, 3),
      sourceCount: sourceIds.length,
      targetCount: targetIds.length,
    };
  }, [nodeLookup, provenance]);

  const questionList = useMemo(
    () =>
      Array.from(new Set(questions.map((question) => question.trim()).filter(Boolean))).slice(0, 3),
    [questions],
  );

  const handleApprove = () => {
    setDecisionStatus('approved');
    setReviewedAt(Date.now());
    onApprove?.(pipelineId, transition.id);
  };

  const handleReject = () => {
    setDecisionStatus('rejected');
    setReviewedAt(Date.now());
    onReject?.(pipelineId, transition.id);
  };

  return (
    <div
      className="bg-surface border border-border rounded-lg p-3 max-w-sm"
      data-testid={`stage-transition-gate-${transition.id}`}
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <div className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
          <span className="text-xs font-theme-data font-bold text-text uppercase">
            {transition.from_stage} &rarr; {transition.to_stage}
          </span>
        </div>
        <span
          className={`px-2 py-1 rounded-full border text-[10px] font-theme-data uppercase tracking-wide ${statusMeta.className}`}
          data-testid={`transition-status-${transition.id}`}
        >
          {statusMeta.label}
        </span>
      </div>

      {focusLabel && (
        <p
          className="text-xs font-theme-data text-text-muted mb-2"
          data-testid={`transition-focus-${transition.id}`}
        >
          {focusLabel}
        </p>
      )}

      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs text-text-muted font-theme-data">Confidence</span>
        <div className="w-24 h-1 bg-gray-700 rounded-full overflow-hidden">
          <div
            className="h-full bg-emerald-400 rounded-full"
            style={{ width: `${confidencePct}%` }}
          />
        </div>
        <span className="text-xs text-text font-theme-data">{confidencePct}%</span>
      </div>

      {transition.ai_rationale && (
        <p className="text-xs text-text-muted mb-2">{transition.ai_rationale}</p>
      )}

      {provenanceSummary.sourceCount > 0 && (
        <div
          className="mb-2 rounded border border-border bg-bg/60 p-2"
          data-testid={`transition-provenance-${transition.id}`}
        >
          <p className="text-[11px] font-theme-data uppercase tracking-wide text-text-muted mb-1">
            Provenance
          </p>
          <p className="text-xs text-text-muted font-theme-data">
            {provenanceSummary.sourceCount} source{provenanceSummary.sourceCount === 1 ? '' : 's'}{' '}
            {'->'} {provenanceSummary.targetCount} draft
            {provenanceSummary.targetCount === 1 ? '' : 's'}
          </p>
          {provenanceSummary.sourceLabels.length > 0 && (
            <p className="text-xs text-text mt-1">
              From: {provenanceSummary.sourceLabels.join(', ')}
            </p>
          )}
          {provenanceSummary.targetLabels.length > 0 && (
            <p className="text-xs text-text mt-1">
              To: {provenanceSummary.targetLabels.join(', ')}
            </p>
          )}
        </div>
      )}

      {questionList.length > 0 && (
        <div
          className="mb-2 rounded border border-border bg-bg/60 p-2"
          data-testid={`transition-questions-${transition.id}`}
        >
          <p className="text-[11px] font-theme-data uppercase tracking-wide text-text-muted mb-1">
            Clarify Before Promotion
          </p>
          <ul className="space-y-1 text-xs text-text-muted">
            {questionList.map((question) => (
              <li key={question}>{question}</li>
            ))}
          </ul>
        </div>
      )}

      {transition.human_notes && (
        <p
          className="text-xs text-text-muted mb-2"
          data-testid={`transition-note-${transition.id}`}
        >
          Note: {transition.human_notes}
        </p>
      )}

      <div className="flex gap-2 mt-2">
        {canReview && onApprove && (
          <button
            onClick={handleApprove}
            className="flex-1 px-2 py-1 bg-emerald-600 text-white text-xs font-theme-data rounded hover:bg-emerald-500 transition-colors"
            data-testid={`transition-approve-${transition.id}`}
          >
            Approve
          </button>
        )}
        {canReview && onReject && (
          <button
            onClick={handleReject}
            className="flex-1 px-2 py-1 bg-red-600 text-white text-xs font-theme-data rounded hover:bg-red-500 transition-colors"
            data-testid={`transition-reject-${transition.id}`}
          >
            Reject
          </button>
        )}
      </div>

      {!canReview && reviewedLabel && (
        <p
          className="mt-2 text-[11px] font-theme-data text-text-muted"
          data-testid={`transition-reviewed-${transition.id}`}
        >
          Reviewed {reviewedLabel}
        </p>
      )}

      {/* Debate this transition before approving */}
      <div className="mt-2 pt-2 border-t border-border">
        <DebateThisButton
          question={`Should we transition from ${transition.from_stage} to ${transition.to_stage}? ${transition.ai_rationale || ''}`}
          context={`Pipeline transition gate. Confidence: ${confidencePct}%. Rationale: ${transition.ai_rationale || 'none provided'}`}
          source="pipeline"
          variant="inline"
        />
      </div>
    </div>
  );
}

export default StageTransitionGate;
