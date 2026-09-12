'use client';

/**
 * PacketDecisionCard — per-PR card for batch sign-off on a settlement
 * packet. Reuses the shared format helpers (tierBadge / ciGlyph /
 * toneColor) so the visual chrome matches the live ReviewQueueCard, but
 * the decision picker carries the 5-tier sign-off options from
 * docs/REVIEW_AUTHORITY_PRINCIPLES.md instead of the 3-action live
 * settle flow (approve / request-changes / defer).
 *
 * The card never hits the live API — packet sign-off is captured into
 * local state via the onDecision callback and serialized into a signed
 * decision-receipt JSON by the parent page.
 */

import { ciGlyph, formatAge, tierBadge, toneColor } from './format';
import type { ReviewQueuePR } from '@/hooks/useReviewQueue';

/** The 5 decision options the operator picks per PR. */
export type PacketDecisionId =
  'approve_tier' | 'approve_downgrade' | 'request_changes' | 'reject' | 'hold_operator';

export interface PacketDecisionOption {
  id: PacketDecisionId;
  label: string;
  description: string;
}

export const PACKET_DECISION_OPTIONS: readonly PacketDecisionOption[] = [
  {
    id: 'approve_tier',
    label: 'APPROVE this tier',
    description: 'Accept the packet tier classification and approve at that tier.',
  },
  {
    id: 'approve_downgrade',
    label: 'APPROVE downgraded',
    description: 'Approve at a lower tier than the packet assigned (record reasoning in comment).',
  },
  {
    id: 'request_changes',
    label: 'REQUEST changes',
    description: 'Mark needs-work; record the change request in the comment box.',
  },
  {
    id: 'reject',
    label: 'REJECT',
    description: 'Close the PR; record reasoning in the comment box.',
  },
  {
    id: 'hold_operator',
    label: 'HOLD (operator-only)',
    description: 'Hold off pending operator-only action; do not advance in this batch.',
  },
];

export interface PacketDecisionCardProps {
  pr: ReviewQueuePR;
  decision: PacketDecisionId | null;
  comment: string;
  recommendedAction?: string | null;
  /**
   * When true, the card is the current keyboard-navigation focus
   * target — it renders a thicker accent border + glow so the
   * operator can see "where am I" during keyboard-only sign-off.
   * Mirrors the visual treatment the live `ReviewQueueCard` uses for
   * its selected state.
   */
  selected?: boolean;
  /**
   * Optional click handler — when supplied, clicking the card chrome
   * (outside the radio/textarea controls) sets the keyboard focus to
   * this card. Keeps mouse + keyboard navigation interchangeable.
   */
  onSelect?: () => void;
  onDecisionChange: (decision: PacketDecisionId) => void;
  onCommentChange: (comment: string) => void;
}

export function PacketDecisionCard({
  pr,
  decision,
  comment,
  recommendedAction,
  selected = false,
  onSelect,
  onDecisionChange,
  onCommentChange,
}: PacketDecisionCardProps) {
  const ci = ciGlyph(pr.ci);
  const tier = tierBadge(pr.tier);

  return (
    <div
      data-testid={`packet-decision-card-${pr.number}`}
      data-selected={selected ? 'true' : 'false'}
      aria-selected={selected}
      onClick={onSelect}
      className="mb-3 rounded border cursor-pointer"
      style={{
        background: 'var(--panel)',
        borderColor: selected ? 'var(--accent)' : 'var(--border)',
        borderWidth: selected ? '2px' : '1px',
        padding: selected ? 'calc(1rem - 1px)' : '1rem',
        boxShadow: selected ? '0 0 0 1px var(--accent-glow)' : undefined,
      }}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <span className="text-lg font-semibold" style={{ color: 'var(--accent)' }}>
            #{pr.number}
          </span>
          <span className="ml-3 text-sm" style={{ color: 'var(--text-muted)' }}>
            {pr.head_sha.slice(0, 10)}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {tier && (
            <span
              data-testid={`packet-decision-tier-${pr.number}`}
              className={`px-2 py-0.5 rounded-full border ${toneColor(tier.tone)}`}
              title={tier.fullLabel}
              aria-label={tier.fullLabel}
            >
              {tier.label}
            </span>
          )}
          <span
            data-testid={`packet-decision-draft-${pr.number}`}
            className={`px-2 py-0.5 rounded-full border ${pr.is_draft ? '' : toneColor('ok')}`}
            style={{ borderColor: 'var(--border)' }}
          >
            {pr.is_draft ? 'draft' : 'ready'}
          </span>
          <span
            data-testid={`packet-decision-ci-${pr.number}`}
            className={toneColor(ci.tone)}
            title={ci.label}
          >
            {ci.glyph} {ci.label}
          </span>
          {pr.age_seconds !== null && (
            <span style={{ color: 'var(--text-muted)' }}>{formatAge(pr.age_seconds)}</span>
          )}
        </div>
      </div>

      {(pr.title || pr.url) && (
        <div className="mt-2 text-sm">
          <a
            href={pr.url}
            target="_blank"
            rel="noopener noreferrer"
            className="hover:underline"
            style={{ color: 'var(--text)' }}
            data-testid={`packet-decision-title-${pr.number}`}
          >
            {pr.title || `(open #${pr.number})`}
          </a>
        </div>
      )}

      {recommendedAction && (
        <div
          className="mt-1 text-xs font-mono"
          style={{ color: 'var(--text-muted)' }}
          data-testid={`packet-decision-recommendation-${pr.number}`}
        >
          Recommended: {recommendedAction}
        </div>
      )}

      <div
        className="mt-3 flex flex-wrap gap-2"
        role="radiogroup"
        aria-label={`Decision options for PR #${pr.number}`}
        data-testid={`packet-decision-options-${pr.number}`}
      >
        {PACKET_DECISION_OPTIONS.map((opt, idx) => {
          const isChecked = decision === opt.id;
          // The 1..5 hint maps to PacketsClient's keyboard shortcuts.
          // Kept stable here so the card alone (without the page) still
          // documents the keystroke.
          const shortcut = idx + 1;
          return (
            <label
              key={opt.id}
              className={`text-xs px-3 py-1.5 rounded border cursor-pointer ${
                isChecked ? 'border-current' : ''
              }`}
              style={{
                background: isChecked ? 'rgba(79,182,255,0.10)' : 'var(--panel-2, transparent)',
                borderColor: isChecked ? 'var(--accent)' : 'var(--border)',
                color: isChecked ? 'var(--accent)' : 'var(--text)',
              }}
              title={`${opt.description} (key: ${shortcut})`}
            >
              <input
                type="radio"
                name={`packet-decision-${pr.number}`}
                value={opt.id}
                checked={isChecked}
                onChange={() => onDecisionChange(opt.id)}
                className="mr-2"
                data-testid={`packet-decision-option-${pr.number}-${opt.id}`}
              />
              <span
                aria-hidden="true"
                className="mr-1 font-mono"
                style={{ color: 'var(--text-muted)' }}
              >
                {shortcut}.
              </span>
              {opt.label}
            </label>
          );
        })}
      </div>

      <div className="mt-2">
        <textarea
          value={comment}
          onChange={(ev) => onCommentChange(ev.target.value)}
          placeholder={`Optional comment for #${pr.number}`}
          className="w-full text-xs p-2 rounded border"
          style={{
            background: 'var(--code, #2e333d)',
            borderColor: 'var(--border)',
            color: 'var(--text)',
            minHeight: 32,
            maxHeight: 120,
            resize: 'vertical',
            fontFamily: 'inherit',
          }}
          data-testid={`packet-decision-comment-${pr.number}`}
        />
      </div>
    </div>
  );
}
