'use client';

import Link from 'next/link';

type DifficultyLevel = 'beginner' | 'intermediate' | 'advanced';

interface DebateTemplate {
  id: string;
  title: string;
  description: string;
  category: string;
  difficulty: DifficultyLevel;
  isPro: boolean;
}

const DIFFICULTY_STYLES: Record<DifficultyLevel, { label: string; className: string }> = {
  beginner: { label: 'BEGINNER', className: 'bg-green-500/20 text-green-400 border-green-500/30' },
  intermediate: {
    label: 'INTERMEDIATE',
    className: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  },
  advanced: { label: 'ADVANCED', className: 'bg-red-500/20 text-red-400 border-red-500/30' },
};

const CURATED_TEMPLATES: DebateTemplate[] = [
  {
    id: 'architecture_decision',
    title: 'Architecture Decision',
    description:
      'Microservices vs Monolith -- multi-agent trade-off analysis with consensus-driven recommendation.',
    category: 'Decision Making',
    difficulty: 'intermediate',
    isPro: false,
  },
  {
    id: 'code_review',
    title: 'Code Review',
    description:
      'Should we approve this PR? Adversarial review across security, performance, and maintainability.',
    category: 'Technical',
    difficulty: 'beginner',
    isPro: false,
  },
  {
    id: 'hiring_decision',
    title: 'Candidate Assessment',
    description:
      'Evaluate a hiring candidate with multi-perspective analysis on skills, culture fit, and growth.',
    category: 'Hiring',
    difficulty: 'intermediate',
    isPro: false,
  },
  {
    id: 'risk_assessment',
    title: 'Risk Analysis',
    description:
      'New product launch risk assessment with mitigation strategies and probability scoring.',
    category: 'Risk',
    difficulty: 'intermediate',
    isPro: false,
  },
  {
    id: 'budget_allocation',
    title: 'Budget Allocation',
    description: 'Q3 marketing budget prioritization across channels with ROI projections.',
    category: 'Strategy',
    difficulty: 'advanced',
    isPro: false,
  },
  {
    id: 'soc2_audit',
    title: 'Compliance Audit',
    description:
      'SOC 2 readiness evaluation with gap analysis, evidence review, and remediation plan.',
    category: 'Compliance',
    difficulty: 'advanced',
    isPro: true,
  },
  {
    id: 'vendor_evaluation',
    title: 'Vendor Selection',
    description: 'Choose between cloud providers with cost, performance, and lock-in analysis.',
    category: 'Decision Making',
    difficulty: 'beginner',
    isPro: false,
  },
  {
    id: 'incident_postmortem',
    title: 'Incident Postmortem',
    description:
      'Root cause analysis for production outages with blameless timeline reconstruction.',
    category: 'Technical',
    difficulty: 'advanced',
    isPro: true,
  },
];

const CATEGORY_ACCENTS: Record<string, string> = {
  'Decision Making':
    'text-[var(--acid-green)] bg-[var(--acid-green)]/10 border-[var(--acid-green)]/30',
  Technical: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
  Hiring: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
  Risk: 'text-red-400 bg-red-500/10 border-red-500/30',
  Strategy: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
  Compliance: 'text-pink-400 bg-pink-500/10 border-pink-500/30',
};

export function TemplateMarketplace() {
  return (
    <div className="mt-8">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-theme-data text-[var(--acid-green)]">{'>'} DEBATE TEMPLATES</h3>
        <Link
          href="/templates"
          className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
        >
          BROWSE ALL
        </Link>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        {CURATED_TEMPLATES.map((template) => {
          const diffStyle = DIFFICULTY_STYLES[template.difficulty];
          const catStyle =
            CATEGORY_ACCENTS[template.category] ?? CATEGORY_ACCENTS['Decision Making'];

          return (
            <Link
              key={template.id}
              href={`/arena?template=${template.id}`}
              className="group bg-[var(--surface)] border border-[var(--border)] p-4 hover:border-[var(--acid-green)]/50 transition-all flex flex-col"
            >
              {/* Category + Pro badge row */}
              <div className="flex items-center justify-between mb-2">
                <span className={`px-2 py-0.5 text-[10px] font-theme-data border ${catStyle}`}>
                  {template.category.toUpperCase()}
                </span>
                {template.isPro && (
                  <span className="flex items-center gap-1 px-2 py-0.5 text-[10px] font-theme-data bg-yellow-500/15 text-yellow-400 border border-yellow-500/30">
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 16 16"
                      fill="currentColor"
                      className="w-3 h-3"
                    >
                      <path
                        fillRule="evenodd"
                        d="M8 1a3.5 3.5 0 0 0-3.5 3.5V7A1.5 1.5 0 0 0 3 8.5v5A1.5 1.5 0 0 0 4.5 15h7a1.5 1.5 0 0 0 1.5-1.5v-5A1.5 1.5 0 0 0 11.5 7V4.5A3.5 3.5 0 0 0 8 1Zm2 6V4.5a2 2 0 1 0-4 0V7h4Z"
                        clipRule="evenodd"
                      />
                    </svg>
                    PRO
                  </span>
                )}
              </div>

              {/* Title */}
              <h4 className="text-sm font-theme-data text-[var(--text)] group-hover:text-[var(--acid-green)] transition-colors mb-1">
                {template.title}
              </h4>

              {/* Description */}
              <p className="text-[11px] font-theme-data text-[var(--text-muted)] leading-relaxed mb-3 flex-1 line-clamp-2">
                {template.description}
              </p>

              {/* Footer: difficulty + CTA */}
              <div className="flex items-center justify-between mt-auto pt-2 border-t border-[var(--border)]">
                <span
                  className={`px-2 py-0.5 text-[10px] font-theme-data border ${diffStyle.className}`}
                >
                  {diffStyle.label}
                </span>
                <span className="text-[10px] font-theme-data text-[var(--text-muted)] group-hover:text-[var(--acid-green)] transition-colors">
                  START {'>'}
                </span>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}

export default TemplateMarketplace;
