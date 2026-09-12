'use client';

import { useState, useEffect } from 'react';
import { useOnboardingStore, SelectedTemplate } from '@/store/onboardingStore';

interface TemplateStepProps {
  onNext: (template: SelectedTemplate) => void;
  onBack: () => void;
}

// Starter templates matching backend
const STARTER_TEMPLATES: SelectedTemplate[] = [
  {
    id: 'arch_review_starter',
    name: 'Architecture Review',
    description: 'Have AI agents review your system architecture',
    agentsCount: 4,
    rounds: 3,
    estimatedDurationMinutes: 5,
  },
  {
    id: 'security_scan_starter',
    name: 'Security Assessment',
    description: 'Identify potential security vulnerabilities',
    agentsCount: 5,
    rounds: 3,
    estimatedDurationMinutes: 7,
  },
  {
    id: 'team_decision_starter',
    name: 'Team Decision',
    description: 'Facilitate team decisions with AI debate',
    agentsCount: 3,
    rounds: 2,
    estimatedDurationMinutes: 3,
  },
  {
    id: 'vendor_eval_starter',
    name: 'Vendor Evaluation',
    description: 'Compare vendors with multi-perspective analysis',
    agentsCount: 4,
    rounds: 3,
    estimatedDurationMinutes: 5,
  },
  {
    id: 'quick_question_starter',
    name: 'Quick Question',
    description: 'Get rapid answers to any question',
    agentsCount: 3,
    rounds: 2,
    estimatedDurationMinutes: 2,
  },
];

export function TemplateStep({ onNext, onBack }: TemplateStepProps) {
  const { selectedTemplate, setSelectedTemplate, setAvailableTemplates, useCase } =
    useOnboardingStore();
  const [selected, setSelected] = useState<SelectedTemplate | null>(selectedTemplate);

  useEffect(() => {
    setAvailableTemplates(STARTER_TEMPLATES);
  }, [setAvailableTemplates]);

  // Prioritize templates based on use case
  const sortedTemplates = [...STARTER_TEMPLATES].sort((a, b) => {
    const useCaseMap: Record<string, string[]> = {
      team_decisions: ['team_decision_starter', 'vendor_eval_starter'],
      architecture_review: ['arch_review_starter', 'security_scan_starter'],
      security_audit: ['security_scan_starter', 'arch_review_starter'],
      vendor_selection: ['vendor_eval_starter', 'team_decision_starter'],
      policy_review: ['team_decision_starter', 'security_scan_starter'],
      general: ['quick_question_starter', 'team_decision_starter'],
    };

    const priority = useCaseMap[useCase || 'general'] || [];
    const aIdx = priority.indexOf(a.id);
    const bIdx = priority.indexOf(b.id);

    if (aIdx !== -1 && bIdx !== -1) return aIdx - bIdx;
    if (aIdx !== -1) return -1;
    if (bIdx !== -1) return 1;
    return 0;
  });

  const handleSelect = (template: SelectedTemplate) => {
    setSelected(template);
    setSelectedTemplate(template);
  };

  const handleNext = () => {
    if (selected) {
      onNext(selected);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-theme-data text-[var(--accent)] mb-2">
          Choose a template to start
        </h2>
        <p className="font-theme-data text-text-muted text-sm">
          Templates are pre-configured for common use cases
        </p>
      </div>

      <div className="space-y-2 max-h-80 overflow-y-auto pr-2">
        {sortedTemplates.map((template, idx) => (
          <button
            key={template.id}
            onClick={() => handleSelect(template)}
            className={`w-full p-4 text-left border transition-colors ${
              selected?.id === template.id
                ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                : 'border-[var(--accent)]/20 hover:border-[var(--accent)]/50 bg-surface'
            }`}
          >
            <div className="flex items-start justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-theme-data text-sm text-[var(--accent)]">
                    {template.name}
                  </span>
                  {idx === 0 && (
                    <span className="px-2 py-0.5 bg-[var(--acid-cyan)]/10 border border-[var(--acid-cyan)]/30 font-theme-data text-xs text-[var(--acid-cyan)]">
                      Recommended
                    </span>
                  )}
                </div>
                <p className="font-theme-data text-xs text-text-muted mt-1">
                  {template.description}
                </p>
              </div>
              <div className="text-right shrink-0 ml-4">
                <div className="font-theme-data text-xs text-[var(--acid-cyan)]">
                  ~{template.estimatedDurationMinutes} min
                </div>
                <div className="font-theme-data text-xs text-text-muted">
                  {template.agentsCount} agents, {template.rounds} rounds
                </div>
              </div>
            </div>
          </button>
        ))}
      </div>

      <div className="flex gap-3 pt-4">
        <button
          onClick={onBack}
          className="px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
        >
          Back
        </button>
        <div className="flex-1" />
        <button
          onClick={handleNext}
          disabled={!selected}
          className={`px-6 py-2 font-theme-data text-sm transition-colors ${
            selected
              ? 'bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80'
              : 'bg-surface text-text-muted border border-[var(--accent)]/20 cursor-not-allowed'
          }`}
        >
          Start debate
        </button>
      </div>
    </div>
  );
}

export default TemplateStep;
