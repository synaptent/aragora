'use client';

import { SectionHeader } from './SectionHeader';

const TRUST_POINTS = [
  {
    title: 'TRANSPARENCY',
    accent: 'acid-green',
    content:
      'Every stress-test is fully auditable. See exact prompts, responses, critiques, and votes. No black boxes.',
  },
  {
    title: 'DISSENT PRESERVED',
    accent: 'acid-cyan',
    content:
      "Minority opinions recorded with full reasoning chains. Consensus doesn't mean unanimity was forced.",
  },
  {
    title: 'EVIDENCE CHAINS',
    accent: 'acid-green',
    content:
      'Claims linked to supporting/refuting evidence. Citation grounding with scholarly rigor.',
  },
  {
    title: 'TRACK RECORDS',
    accent: 'acid-cyan',
    content:
      'Agent personas built from verified stress-test outcomes. Not self-reported traits — empirical performance.',
  },
];

export function TrustSection() {
  return (
    <section className="py-12 border-t border-[var(--accent)]/20">
      <div className="container mx-auto px-4">
        <SectionHeader title="WHY TRUST ARAGORA?" />

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 max-w-5xl mx-auto">
          {TRUST_POINTS.map((point) => (
            <div key={point.title} className={`border-l-2 border-${point.accent} pl-4 py-2`}>
              <h3 className={`text-${point.accent} font-theme-data text-xs mb-2`}>{point.title}</h3>
              <p className="text-text-muted text-xs font-theme-data leading-relaxed">
                {point.content}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
