'use client';

import { useTheme } from '@/context/ThemeContext';

interface Step {
  number: string;
  title: string;
  description: string;
}

const STEPS: Step[] = [
  {
    number: '01',
    title: 'You ask a question',
    description: 'Any decision, strategy, or architecture question you need vetted.',
  },
  {
    number: '02',
    title: 'AI agents debate it',
    description: 'Claude, GPT, Gemini, Mistral, and others argue every angle. Different models catch different blind spots.',
  },
  {
    number: '03',
    title: 'You get a decision receipt',
    description: 'An audit-ready verdict with evidence chains, confidence scores, and dissenting views preserved.',
  },
];

export function HowItWorksSection() {
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  return (
    <section
      id="how-it-works"
      className="px-4"
      style={{
        paddingTop: '120px',
        paddingBottom: '120px',
        borderTop: '1px solid var(--border)',
        fontFamily: 'var(--font-landing)',
      }}
    >
      <div className="max-w-xl mx-auto">
        {/* Section label */}
        <p
          className="text-center uppercase tracking-widest"
          style={{
            fontSize: isDark ? '16px' : '18px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '48px',
          }}
        >
          {isDark ? '> HOW IT WORKS' : 'HOW IT WORKS'}
        </p>

        {/* Steps */}
        <div>
          {STEPS.map((step, idx) => (
            <div key={step.number} className="relative">
              {/* Vertical connector line between steps */}
              {idx < STEPS.length - 1 && (
                <div
                  className="absolute w-px"
                  style={{
                    left: '23px',
                    top: '48px',
                    bottom: '0',
                    backgroundColor: 'var(--border)',
                  }}
                />
              )}

              <div className="flex gap-8 items-start" style={{ paddingBottom: '48px' }}>
                {/* Circular badge */}
                <div
                  className="flex-shrink-0 w-12 h-12 rounded-full flex items-center justify-center"
                  style={{
                    backgroundColor: 'var(--accent-glow)',
                    color: 'var(--accent)',
                    fontSize: '15px',
                    fontWeight: 700,
                    fontFamily: isDark ? "'JetBrains Mono', monospace" : 'var(--font-landing)',
                  }}
                >
                  {step.number}
                </div>

                <div style={{ paddingTop: '2px' }}>
                  {/* Title */}
                  <h3
                    style={{
                      fontSize: isDark ? '17px' : '19px',
                      fontWeight: 600,
                      color: 'var(--text)',
                      fontFamily: 'var(--font-landing)',
                      marginBottom: '8px',
                    }}
                  >
                    {isDark ? `> ${step.title}` : step.title}
                  </h3>

                  {/* Description */}
                  <p
                    className="leading-relaxed"
                    style={{
                      fontSize: isDark ? '14px' : '16px',
                      color: 'var(--text-muted)',
                      fontFamily: 'var(--font-landing)',
                      lineHeight: '1.7',
                    }}
                  >
                    {step.description}
                  </p>
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
