'use client';

import { SectionHeader } from './SectionHeader';

const CARDS = [
  {
    title: 'DIVERSE AI MODELS',
    accent: 'acid-green',
    indicator: 'acid-cyan',
    content:
      "7+ distinct AI providers act as adversaries, not echoes. Claude's caution vs GPT's creativity vs Gemini's speed, with Mistral bringing an EU perspective and Chinese models like DeepSeek, Qwen, and Kimi bringing a Chinese perspective. Real diversity. Real disagreement. Real risk signal.",
  },
  {
    title: 'SELF-IMPROVING FRAMEWORK',
    accent: 'acid-cyan',
    indicator: 'acid-green',
    content:
      'Aragora runs the "Nomic Loop" -- agents red-team improvements to their own framework, implement code, verify changes. The arena evolves through its own critiques (sandboxed + human-reviewed).',
  },
  {
    title: 'CALIBRATED TRUST',
    accent: 'acid-green',
    indicator: 'acid-cyan',
    content:
      'We track prediction accuracy over time. Know which agents are confidently wrong vs genuinely uncertain. Trust earned through track record, not marketing.',
  },
];

export function WhyAragoraSection() {
  return (
    <section className="py-12 border-t border-[var(--accent)]/20">
      <div className="container mx-auto px-4">
        <SectionHeader title="WHY ARAGORA?" />

        <p className="text-text-muted font-theme-data text-xs text-center mb-8 max-w-xl mx-auto">
          Unlike single-model chatbots, Aragora orchestrates 15+ AI models to debate every angle of
          your question and deliver a verdict with confidence scores, minority opinions, and a full
          audit trail.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 max-w-5xl mx-auto">
          {CARDS.map((card) => (
            <div key={card.title} className={`border border-${card.accent}/30 p-4 bg-surface/30`}>
              <h3
                className={`text-${card.accent} font-theme-data text-sm mb-3 flex items-center gap-2`}
              >
                <span className={`text-${card.indicator}`}>{'>'}</span> {card.title}
              </h3>
              <p className="text-text-muted text-xs font-theme-data leading-relaxed">
                {card.content}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
