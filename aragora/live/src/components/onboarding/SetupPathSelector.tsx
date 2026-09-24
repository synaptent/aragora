'use client';

import { useState } from 'react';

export type SetupPath = 'automation' | 'decisions' | 'compliance' | 'comprehensive';

interface SetupPathSelectorProps {
  selectedPath: SetupPath | null;
  onSelect: (path: SetupPath) => void;
  businessType?: string | null;
}

const SETUP_PATHS: Array<{
  path: SetupPath;
  icon: string;
  title: string;
  subtitle: string;
  description: string;
  features: string[];
  timeEstimate: string;
  recommended?: string[];
}> = [
  {
    path: 'automation',
    icon: '⚡',
    title: 'Automate Business Processes',
    subtitle: 'Save hours every week',
    description:
      'Set up automated workflows for recurring tasks like invoicing, follow-ups, and reports.',
    features: [
      'Invoice generation workflows',
      'Customer follow-up automation',
      'Scheduled reporting',
      'Inventory alerts',
    ],
    timeEstimate: '~10 min setup',
    recommended: ['retail', 'professional_services', 'manufacturing'],
  },
  {
    path: 'decisions',
    icon: '🎯',
    title: 'Make Better Decisions',
    subtitle: 'AI-powered consensus',
    description:
      'Run debates with multiple AI agents to stress-test ideas and reach informed decisions.',
    features: [
      'Architecture reviews',
      'Feature prioritization',
      'Vendor evaluation',
      'Strategic planning',
    ],
    timeEstimate: '~5 min setup',
    recommended: ['saas', 'professional_services', 'finance'],
  },
  {
    path: 'compliance',
    icon: '🛡️',
    title: 'Ensure Compliance',
    subtitle: 'Security & audit ready',
    description: 'Run security assessments and compliance reviews with full audit trails.',
    features: ['Security assessments', 'Policy reviews', 'Risk analysis', 'Audit documentation'],
    timeEstimate: '~8 min setup',
    recommended: ['healthcare', 'finance', 'saas'],
  },
  {
    path: 'comprehensive',
    icon: '🚀',
    title: 'Full Platform Setup',
    subtitle: 'Everything at once',
    description: 'Set up automation, decision-making, and compliance together.',
    features: [
      'All workflow templates',
      'Full debate capabilities',
      'Complete audit system',
      'Team collaboration',
    ],
    timeEstimate: '~15 min setup',
    recommended: [],
  },
];

export function SetupPathSelector({
  selectedPath,
  onSelect,
  businessType,
}: SetupPathSelectorProps) {
  const [expandedPath, setExpandedPath] = useState<SetupPath | null>(null);

  // Get recommended path based on business type
  const recommendedPath = SETUP_PATHS.find((p) =>
    p.recommended?.includes(businessType || ''),
  )?.path;

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h3 className="text-xl font-theme-data text-[var(--accent)] mb-2">
          What would you like to do first?
        </h3>
        <p className="text-sm text-text-muted">
          Choose your starting point - you can always explore other features later
        </p>
      </div>

      <div className="space-y-3">
        {SETUP_PATHS.map((setup) => {
          const isRecommended = setup.path === recommendedPath;
          const isSelected = selectedPath === setup.path;
          const isExpanded = expandedPath === setup.path;

          return (
            <div
              key={setup.path}
              className={`border rounded-lg transition-all ${
                isSelected
                  ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                  : 'border-border hover:border-[var(--accent)]/50'
              }`}
            >
              <button
                onClick={() => onSelect(setup.path)}
                onMouseEnter={() => setExpandedPath(setup.path)}
                onMouseLeave={() => setExpandedPath(null)}
                className="w-full p-4 text-left"
              >
                <div className="flex items-start gap-4">
                  <span className="text-3xl">{setup.icon}</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="font-theme-data text-sm text-text">{setup.title}</span>
                      {isRecommended && (
                        <span className="text-xs px-2 py-0.5 bg-[var(--accent)]/20 text-[var(--accent)] rounded">
                          Recommended
                        </span>
                      )}
                    </div>
                    <div className="text-xs text-[var(--acid-cyan)] mt-0.5">{setup.subtitle}</div>
                    <div className="text-xs text-text-muted mt-1">{setup.description}</div>
                    <div className="text-xs text-text-muted mt-2">{setup.timeEstimate}</div>
                  </div>
                  {isSelected && <span className="text-[var(--accent)] text-xl">✓</span>}
                </div>

                {/* Expanded features */}
                {(isExpanded || isSelected) && (
                  <div className="mt-4 pt-4 border-t border-border/50">
                    <div className="text-xs text-text-muted mb-2">Includes:</div>
                    <div className="grid grid-cols-2 gap-2">
                      {setup.features.map((feature) => (
                        <div key={feature} className="flex items-center gap-1.5">
                          <span className="text-[var(--accent)] text-xs">•</span>
                          <span className="text-xs text-text">{feature}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </button>
            </div>
          );
        })}
      </div>

      <div className="text-center">
        <p className="text-xs text-text-muted">
          All paths include full access to Aragora - this just sets your starting templates
        </p>
      </div>
    </div>
  );
}
