'use client';

import Link from 'next/link';
import { useOnboardingStore } from '@/store/onboardingStore';

export function YourTurnStep() {
  const chosenTemplateId = useOnboardingStore((s) => s.chosenTemplateId);
  const selectedIndustry = useOnboardingStore((s) => s.selectedIndustry);

  const arenaUrl = chosenTemplateId
    ? `/arena?template=${encodeURIComponent(chosenTemplateId)}${selectedIndustry ? `&vertical=${selectedIndustry}` : ''}`
    : `/arena${selectedIndustry ? `?vertical=${selectedIndustry}` : ''}`;

  return (
    <div className="space-y-6 text-center py-4">
      <div>
        <h2 className="text-xl font-theme-data text-[var(--acid-green)] mb-2">Your Turn</h2>
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          You have seen how AI agents collaborate. Now run your own debate in the arena.
        </p>
      </div>

      {/* What you'll get */}
      <div className="text-left space-y-3 border border-[var(--border)] bg-[var(--surface)] p-4">
        <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
          What happens next
        </div>
        {[
          'Multiple AI models debate your question adversarially',
          'Each agent proposes, critiques, and refines positions',
          'You get an audit-ready decision receipt with confidence scores',
        ].map((item) => (
          <div key={item} className="flex items-start gap-2 text-sm font-theme-data">
            <span className="text-[var(--acid-green)] mt-0.5">{'>'}</span>
            <span className="text-[var(--text)]">{item}</span>
          </div>
        ))}
      </div>

      {/* CTA */}
      <div className="flex flex-col gap-3">
        <Link
          href={arenaUrl}
          className="px-8 py-4 bg-[var(--acid-green)] text-[var(--bg)] font-theme-data font-bold text-sm hover:opacity-90 transition-opacity inline-block text-center"
        >
          START MY FIRST DEBATE
        </Link>
        <p className="text-[10px] font-theme-data text-[var(--text-muted)]">
          Or continue to set up channels and finish onboarding
        </p>
      </div>
    </div>
  );
}
