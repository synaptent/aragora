'use client';

import { useState, useCallback } from 'react';

type Persona = 'stress-test' | 'security' | 'compliance' | 'explore';

interface PersonaOption {
  id: Persona;
  label: string;
  description: string;
  examplePrompt: string;
}

const PERSONAS: PersonaOption[] = [
  {
    id: 'explore',
    label: 'Just Exploring',
    description: 'See how multi-agent debate works',
    examplePrompt: 'Is it better to build or buy an internal analytics platform?',
  },
  {
    id: 'stress-test',
    label: 'Architecture Review',
    description: 'Stress-test technical decisions before launch',
    examplePrompt:
      'Should we use microservices or a monolith for a new e-commerce platform expecting 10M users?',
  },
  {
    id: 'security',
    label: 'Security Review',
    description: 'Find vulnerabilities in API designs and systems',
    examplePrompt: 'Review the security of our JWT-based auth system with refresh token rotation.',
  },
  {
    id: 'compliance',
    label: 'Compliance Check',
    description: 'Pre-audit GDPR, HIPAA, or SOX requirements',
    examplePrompt:
      'Assess our user data handling for GDPR Article 17 (Right to Erasure) compliance.',
  },
];

interface OnboardingWizardProps {
  onComplete: (persona: Persona, startWithPrompt?: string) => void;
  onSkip: () => void;
}

export function OnboardingWizard({ onComplete, onSkip }: OnboardingWizardProps) {
  const [step, setStep] = useState(1);
  const [selectedPersona, setSelectedPersona] = useState<Persona | null>(null);

  const handlePersonaSelect = useCallback((persona: Persona) => {
    setSelectedPersona(persona);
    setStep(2);
  }, []);

  const handleStartWithExample = useCallback(() => {
    if (!selectedPersona) return;
    const persona = PERSONAS.find((p) => p.id === selectedPersona);
    onComplete(selectedPersona, persona?.examplePrompt);
  }, [selectedPersona, onComplete]);

  const handleStartBlank = useCallback(() => {
    if (!selectedPersona) return;
    onComplete(selectedPersona);
  }, [selectedPersona, onComplete]);

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-bg/95 backdrop-blur-sm">
      <div className="w-full max-w-xl mx-4 border border-[var(--accent)]/30 bg-surface rounded-lg overflow-hidden">
        {/* Header */}
        <div className="border-b border-[var(--accent)]/20 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-theme-data text-[var(--accent)]">WELCOME TO ARAGORA</h2>
            <p className="text-xs font-theme-data text-text-muted mt-1">Step {step} of 2</p>
          </div>
          <button
            onClick={onSkip}
            className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
          >
            [SKIP]
          </button>
        </div>

        {/* Content */}
        <div className="p-6">
          {step === 1 && (
            <div className="space-y-4">
              <p className="text-sm font-theme-data text-text mb-2">
                What would you like to stress-test?
              </p>
              <p className="text-xs font-theme-data text-text-muted mb-4">
                Pick a use case and we&apos;ll run your first AI debate in under 30 seconds.
              </p>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {PERSONAS.map((persona) => (
                  <button
                    key={persona.id}
                    onClick={() => handlePersonaSelect(persona.id)}
                    className="p-4 border border-[var(--accent)]/20 rounded-lg text-left hover:border-[var(--accent)]/50 hover:bg-[var(--accent)]/5 transition-all group"
                  >
                    <div className="font-theme-data text-sm text-[var(--accent)] group-hover:text-[var(--accent)]">
                      {persona.label}
                    </div>
                    <div className="text-xs text-text-muted mt-1">{persona.description}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {step === 2 && selectedPersona && (
            <div className="space-y-6">
              <div>
                <p className="text-sm font-theme-data text-text mb-2">
                  Ready to run your first debate:
                </p>
                <div className="p-4 border border-[var(--acid-cyan)]/30 rounded-lg bg-[var(--acid-cyan)]/5">
                  <p className="text-sm font-theme-data text-[var(--acid-cyan)]">
                    &quot;{PERSONAS.find((p) => p.id === selectedPersona)?.examplePrompt}&quot;
                  </p>
                </div>
              </div>

              <div className="flex flex-col sm:flex-row gap-3">
                <button
                  onClick={handleStartWithExample}
                  className="flex-1 px-4 py-3 bg-[var(--accent)] text-bg font-theme-data text-sm hover:bg-[var(--accent)]/90 transition-colors"
                >
                  RUN THIS DEBATE
                </button>
                <button
                  onClick={handleStartBlank}
                  className="flex-1 px-4 py-3 border border-[var(--accent)]/30 text-[var(--accent)] font-theme-data text-sm hover:bg-[var(--accent)]/10 transition-colors"
                >
                  WRITE MY OWN QUESTION
                </button>
              </div>

              <button
                onClick={() => setStep(1)}
                className="w-full text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                ← Back to persona selection
              </button>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-[var(--accent)]/20 px-6 py-3 bg-surface/50">
          <p className="text-xs font-theme-data text-text-muted text-center">
            42 AI agents will debate, critique, and converge on a verdict for you.
          </p>
        </div>
      </div>
    </div>
  );
}

export default OnboardingWizard;
