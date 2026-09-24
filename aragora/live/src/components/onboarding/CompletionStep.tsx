'use client';

import { API_BASE_URL } from '@/config';
import { useOnboardingStore } from '@/store';

interface CompletionStepProps {
  onComplete?: () => void;
}

export function CompletionStep({ onComplete }: CompletionStepProps) {
  const { organizationName, firstDebateId, firstReceiptId, teamMembers } = useOnboardingStore();

  return (
    <div className="space-y-6 text-center">
      <div>
        <div className="text-6xl mb-4">
          <span role="img" aria-label="party">
            &#127881;
          </span>
        </div>
        <h3 className="text-xl font-theme-data text-[var(--accent)] mb-2">You&apos;re All Set!</h3>
        <p className="text-sm text-text-muted">Welcome to Aragora, {organizationName || 'team'}!</p>
      </div>

      {/* Summary */}
      <div className="p-4 border border-[var(--accent)]/20 rounded-lg bg-surface text-left">
        <div className="text-sm font-theme-data text-[var(--accent)] mb-3">Onboarding Summary</div>
        <div className="space-y-2 text-sm text-text">
          <div className="flex items-center gap-2">
            <span className="text-[var(--accent)]">&#10003;</span>
            <span>Workspace created: {organizationName || 'My Workspace'}</span>
          </div>
          {teamMembers.length > 0 && (
            <div className="flex items-center gap-2">
              <span className="text-[var(--accent)]">&#10003;</span>
              <span>{teamMembers.length} team member(s) invited</span>
            </div>
          )}
          {firstDebateId && (
            <div className="flex items-center gap-2">
              <span className="text-[var(--accent)]">&#10003;</span>
              <span>First debate completed</span>
            </div>
          )}
        </div>
      </div>

      {/* Next Steps */}
      <div>
        <div className="text-sm font-theme-data text-text mb-3">What&apos;s Next?</div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <NextStepCard
            icon="&#128196;"
            title="View Receipt"
            description="See your decision summary"
            href={
              firstReceiptId
                ? `${API_BASE_URL}/api/v2/receipts/${encodeURIComponent(firstReceiptId)}/export?format=html&raw=true`
                : firstDebateId
                  ? `/debate/${firstDebateId}`
                  : '/debates'
            }
          />
          <NextStepCard
            icon="&#9881;"
            title="Settings"
            description="Configure integrations"
            href="/settings"
          />
          <NextStepCard
            icon="&#128218;"
            title="Templates"
            description="Explore debate templates"
            href="/templates"
          />
        </div>
      </div>

      {/* CTA */}
      <button
        onClick={onComplete}
        className="w-full px-6 py-3 bg-[var(--accent)] text-bg font-theme-data text-sm hover:bg-[var(--accent)]/90 transition-colors"
      >
        GO TO DASHBOARD
      </button>
    </div>
  );
}

interface NextStepCardProps {
  icon: string;
  title: string;
  description: string;
  href: string;
}

function NextStepCard({ icon, title, description, href }: NextStepCardProps) {
  return (
    <a
      href={href}
      className="p-3 border border-[var(--accent)]/20 rounded-lg hover:border-[var(--accent)]/50 hover:bg-[var(--accent)]/5 transition-colors block"
    >
      <div className="text-xl mb-1">{icon}</div>
      <div className="text-sm font-theme-data text-[var(--accent)]">{title}</div>
      <div className="text-xs text-text-muted">{description}</div>
    </a>
  );
}
