'use client';

import { SectionHeader } from './SectionHeader';

const STEPS = [
  {
    id: '01',
    title: 'PROPOSE',
    accent: 'acid-green',
    content:
      'Agents generate diverse approaches and assumptions. Claude might suggest caution. GPT might go bold.',
  },
  {
    id: '02',
    title: 'VALIDATE',
    accent: 'acid-cyan',
    content:
      "Adversarial validation: rival models red-team each proposal for security, logic, compliance, and scale. Agents rotate through cognitive roles: Analyst, Skeptic, Devil's Advocate.",
  },
  {
    id: '03',
    title: 'ADAPT',
    accent: 'acid-green',
    content:
      'Agents update positions based on valid critiques. We track who changed their mind and why.',
  },
  {
    id: '04',
    title: 'CONVERGE',
    accent: 'acid-cyan',
    content:
      'Semantic similarity detection finds natural consensus. Dissenting views preserved with full reasoning chains.',
  },
  {
    id: '05',
    title: 'RECEIPT',
    accent: 'acid-green',
    content:
      'Cryptographic decision receipts with evidence chains and audit trails. Outcomes feed into agent memory and ELO ratings.',
  },
];

export function DebateProtocolSection() {
  return (
    <section className="py-12 border-t border-[var(--accent)]/20">
      <div className="container mx-auto px-4">
        <SectionHeader title="THE DELIBERATION PROTOCOL" />

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4 max-w-6xl mx-auto">
          {STEPS.map((step) => (
            <div key={step.id} className={`border border-${step.accent}/20 p-4 bg-surface/30`}>
              <h3 className={`text-${step.accent} font-theme-data text-sm mb-2`}>
                [{step.id}] {step.title}
              </h3>
              <p className="text-text-muted text-xs font-theme-data leading-relaxed">
                {step.content}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
