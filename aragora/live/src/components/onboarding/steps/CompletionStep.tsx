'use client';

import { useOnboardingStore } from '@/store/onboardingStore';

interface CompletionStepProps {
  onComplete: () => void;
}

export function CompletionStep({ onComplete }: CompletionStepProps) {
  const { organizationName, selectedTemplate, firstDebateId } = useOnboardingStore();

  return (
    <div className="space-y-6 text-center">
      <div>
        <div className="inline-block p-4 bg-[var(--accent)]/10 border border-[var(--accent)]/30 mb-4">
          <span className="text-4xl">&#x2705;</span>
        </div>
        <h2 className="text-2xl font-theme-data text-[var(--accent)] mb-2">You&apos;re all set!</h2>
        <p className="font-theme-data text-text-muted text-sm">
          {organizationName ? `Welcome to Aragora, ${organizationName}!` : 'Welcome to Aragora!'}
        </p>
      </div>

      <div className="space-y-3 text-left">
        <div className="p-4 bg-surface border border-[var(--accent)]/20">
          <h3 className="font-theme-data text-sm text-[var(--accent)] mb-2">
            What you&apos;ve accomplished
          </h3>
          <ul className="space-y-2 font-theme-data text-text-muted text-sm">
            <li className="flex items-center gap-2">
              <span className="text-[var(--accent)]">&#x2713;</span>
              Set up your organization
            </li>
            {selectedTemplate && (
              <li className="flex items-center gap-2">
                <span className="text-[var(--accent)]">&#x2713;</span>
                Selected {selectedTemplate.name} template
              </li>
            )}
            {firstDebateId && (
              <li className="flex items-center gap-2">
                <span className="text-[var(--accent)]">&#x2713;</span>
                Started your first debate
              </li>
            )}
          </ul>
        </div>

        <div className="p-4 bg-[var(--acid-cyan)]/5 border border-[var(--acid-cyan)]/20">
          <h3 className="font-theme-data text-sm text-[var(--acid-cyan)] mb-2">Next steps</h3>
          <ul className="space-y-2 font-theme-data text-text-muted text-sm">
            <li className="flex items-start gap-2">
              <span className="text-[var(--acid-cyan)]">&#x2192;</span>
              <span>Invite team members to collaborate</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-[var(--acid-cyan)]">&#x2192;</span>
              <span>Explore templates for different use cases</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-[var(--acid-cyan)]">&#x2192;</span>
              <span>Review decision receipts after debates</span>
            </li>
          </ul>
        </div>
      </div>

      <div className="pt-4">
        <button
          onClick={onComplete}
          className="w-full px-6 py-3 font-theme-data text-sm bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
        >
          Go to Dashboard
        </button>
      </div>
    </div>
  );
}

export default CompletionStep;
