'use client';

import { useOnboardingStore } from '@/store/onboardingStore';
import { CATEGORY_META, type TemplateCategory } from '@/components/templates/templateData';

const INDUSTRIES: { key: TemplateCategory; description: string }[] = [
  { key: 'code', description: 'Architecture reviews, tech stack decisions, code audits' },
  { key: 'legal', description: 'Contract analysis, regulatory compliance, due diligence' },
  { key: 'finance', description: 'Risk assessment, investment analysis, budget decisions' },
  { key: 'healthcare', description: 'Clinical decisions, HIPAA compliance, patient safety' },
  { key: 'compliance', description: 'SOX audits, policy reviews, governance checks' },
  { key: 'business', description: 'Strategy decisions, vendor selection, market analysis' },
  { key: 'general', description: 'Team decisions, brainstorming, problem solving' },
];

/**
 * Step 1: Industry selection (no auth required).
 * Maps to deliberation template categories so the trial debate
 * can auto-select a relevant template.
 */
export function IndustryStep() {
  const selectedIndustry = useOnboardingStore((s) => s.selectedIndustry);
  const setSelectedIndustry = useOnboardingStore((s) => s.setSelectedIndustry);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-theme-data text-[var(--acid-green)] mb-2">
          What brings you to Aragora?
        </h2>
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          Select your industry so we can tailor the experience. No account needed for this step.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {INDUSTRIES.map(({ key, description }) => {
          const meta = CATEGORY_META[key];
          const isSelected = selectedIndustry === key;

          return (
            <button
              key={key}
              onClick={() => setSelectedIndustry(key)}
              className={`text-left p-4 border transition-colors ${
                isSelected
                  ? 'border-[var(--acid-green)] bg-[var(--acid-green)]/10'
                  : 'border-[var(--border)] bg-[var(--surface)] hover:border-[var(--acid-green)]/50'
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <span className="text-sm font-theme-data text-[var(--acid-cyan)]">{meta.icon}</span>
                <span
                  className={`text-sm font-theme-data font-bold ${
                    isSelected ? 'text-[var(--acid-green)]' : 'text-[var(--text)]'
                  }`}
                >
                  {meta.label}
                </span>
              </div>
              <p className="text-xs font-theme-data text-[var(--text-muted)]">{description}</p>
            </button>
          );
        })}
      </div>
    </div>
  );
}
