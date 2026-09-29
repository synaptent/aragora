'use client';

import { useOnboardingStore } from '@/store/onboardingStore';

interface DebateTemplate {
  id: string;
  name: string;
  description: string;
  icon: string;
  agents: number;
  rounds: number;
}

const CURATED_TEMPLATES: DebateTemplate[] = [
  {
    id: 'architecture_decision',
    name: 'Architecture Decision: Microservices vs Monolith',
    description:
      'Have AI agents debate the trade-offs of microservices versus monolithic architecture for your use case.',
    icon: '</>',
    agents: 5,
    rounds: 5,
  },
  {
    id: 'hiring_decision',
    name: 'Hiring: Should we hire this candidate?',
    description:
      'Multi-perspective evaluation of a candidate across culture fit, skills, and growth potential.',
    icon: '#',
    agents: 4,
    rounds: 3,
  },
  {
    id: 'risk_assessment',
    name: 'Risk Assessment: Launch new product now or wait?',
    description:
      'Agents stress-test the decision to launch now versus waiting, weighing market timing and readiness.',
    icon: '!',
    agents: 5,
    rounds: 4,
  },
  {
    id: 'code_review',
    name: 'Code Review: Approve this PR?',
    description:
      'Security, performance, and maintainability review of a pull request by diverse AI models.',
    icon: '%',
    agents: 3,
    rounds: 3,
  },
];

export function ChooseTemplateStep() {
  const chosenTemplateId = useOnboardingStore((s) => s.chosenTemplateId);
  const setChosenTemplateId = useOnboardingStore((s) => s.setChosenTemplateId);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-theme-data text-[var(--acid-green)] mb-2">Choose a Template</h2>
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          Pick a debate template to see how Aragora handles real decisions.
        </p>
      </div>

      <div className="space-y-3">
        {CURATED_TEMPLATES.map((template) => {
          const isSelected = chosenTemplateId === template.id;
          return (
            <button
              key={template.id}
              onClick={() => setChosenTemplateId(template.id)}
              className={`w-full text-left p-4 border transition-colors ${
                isSelected
                  ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10'
                  : 'border-[var(--border)] bg-[var(--surface)] hover:border-[var(--acid-green)]/50'
              }`}
            >
              <div className="flex items-start gap-3">
                <span
                  className={`w-8 h-8 flex items-center justify-center text-xs font-theme-data font-bold shrink-0 ${
                    isSelected
                      ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)]'
                      : 'bg-[var(--border)] text-[var(--text-muted)]'
                  }`}
                >
                  {template.icon}
                </span>
                <div className="flex-1 min-w-0">
                  <div
                    className={`text-sm font-theme-data font-bold mb-1 ${
                      isSelected ? 'text-[var(--acid-green)]' : 'text-[var(--text)]'
                    }`}
                  >
                    {template.name}
                  </div>
                  <p className="text-xs font-theme-data text-[var(--text-muted)] leading-relaxed">
                    {template.description}
                  </p>
                  <div className="flex items-center gap-4 mt-2 text-[10px] font-theme-data text-[var(--text-muted)]">
                    <span>{template.agents} agents</span>
                    <span>{template.rounds} rounds</span>
                  </div>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
