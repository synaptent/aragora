'use client';

import { useState } from 'react';
import Link from 'next/link';

interface Feature {
  name: string;
  path: string;
  description: string;
}

interface UseCase {
  id: string;
  title: string;
  subtitle: string;
  description: string;
  icon: string;
  color: string;
  borderColor: string;
  features: Feature[];
}

const USE_CASES: UseCase[] = [
  {
    id: 'compliance',
    title: 'COMPLIANCE & AUDITING',
    subtitle: 'For Auditors & Compliance Officers',
    description:
      'Stress-test decisions with full audit trails. Every debate produces verifiable receipts for regulatory review.',
    icon: '[]',
    color: 'text-[var(--acid-cyan)]',
    borderColor: 'border-[var(--acid-cyan)]/30',
    features: [
      { name: 'Audit Sessions', path: '/audit', description: 'Structured audit workflows' },
      { name: 'Evidence Library', path: '/evidence', description: 'Sourced citations and proof' },
      { name: 'Policy Analysis', path: '/policy', description: 'Policy compliance checking' },
      { name: 'Document Upload', path: '/documents', description: 'Upload documents for context' },
      { name: 'Export Reports', path: '/training', description: 'Export audit-ready reports' },
    ],
  },
  {
    id: 'security',
    title: 'SECURITY TESTING',
    subtitle: 'For Security Engineers & Pentesters',
    description:
      'Red-team AI responses before deployment. Find failure modes and adversarial vulnerabilities.',
    icon: '{}',
    color: 'text-warning',
    borderColor: 'border-warning/30',
    features: [
      { name: 'Gauntlet', path: '/gauntlet', description: 'Adversarial stress testing' },
      { name: 'Red Team', path: '/red-team', description: 'Vulnerability discovery' },
      { name: 'Capability Probes', path: '/probe', description: 'Test specific capabilities' },
      { name: 'Formal Verification', path: '/verify', description: 'Z3/Lean proofs' },
      { name: 'Risk Warnings', path: '/risk', description: 'Automated risk detection' },
    ],
  },
  {
    id: 'research',
    title: 'RESEARCH & ANALYSIS',
    subtitle: 'For Researchers & Analysts',
    description:
      'Multi-model consensus on complex questions. Extract insights from diverse AI perspectives.',
    icon: '<>',
    color: 'text-[var(--accent)]',
    borderColor: 'border-[var(--accent)]/30',
    features: [
      { name: 'Debates', path: '/debate', description: 'AI models debate your question' },
      { name: 'Knowledge Mound', path: '/knowledge', description: 'Accumulated insights' },
      { name: 'Memory System', path: '/memory', description: 'Cross-session learning' },
      { name: 'Insights', path: '/insights', description: 'AI-extracted patterns' },
      { name: 'Analytics', path: '/analytics', description: 'Performance metrics' },
    ],
  },
  {
    id: 'development',
    title: 'DEV & INTEGRATION',
    subtitle: 'For Developers & Integrators',
    description:
      'API-first workflows and extensible plugins. Build on aragora with full programmatic access.',
    icon: '//',
    color: 'text-acid-purple',
    borderColor: 'border-acid-purple/30',
    features: [
      { name: 'API Explorer', path: '/api-explorer', description: 'Interactive API docs' },
      { name: 'Workflows', path: '/workflows', description: 'Multi-step automation' },
      { name: 'Connectors', path: '/connectors', description: 'Data source integrations' },
      { name: 'Webhooks', path: '/webhooks', description: 'Event notifications' },
      { name: 'Plugins', path: '/plugins', description: 'Extend functionality' },
    ],
  },
];

interface UseCaseCardProps {
  useCase: UseCase;
  isExpanded: boolean;
  onToggle: () => void;
}

function UseCaseCard({ useCase, isExpanded, onToggle }: UseCaseCardProps) {
  return (
    <div
      className={`
        border ${useCase.borderColor} bg-surface/30 transition-all duration-300
        ${isExpanded ? 'ring-1 ring-acid-green/50' : 'hover:bg-surface/50'}
      `}
    >
      {/* Card Header */}
      <button onClick={onToggle} className="w-full p-4 text-left group">
        <div className="flex items-start gap-3">
          {/* Icon */}
          <div className={`font-theme-data text-lg ${useCase.color} opacity-60`}>
            {useCase.icon}
          </div>

          {/* Content */}
          <div className="flex-1 min-w-0">
            <h3 className={`font-theme-data text-xs font-bold ${useCase.color} tracking-wider`}>
              {useCase.title}
            </h3>
            <p className="text-[10px] font-theme-data text-text-muted/70 mt-0.5">
              {useCase.subtitle}
            </p>
            <p className="text-[10px] font-theme-data text-text-muted/50 mt-2 leading-relaxed">
              {useCase.description}
            </p>
          </div>

          {/* Expand indicator */}
          <span
            className={`text-[10px] font-theme-data ${useCase.color} opacity-50 transition-transform ${isExpanded ? 'rotate-90' : ''}`}
          >
            {'>'}
          </span>
        </div>
      </button>

      {/* Expanded Feature List */}
      <div
        className={`
          overflow-hidden transition-all duration-300
          ${isExpanded ? 'max-h-80 opacity-100' : 'max-h-0 opacity-0'}
        `}
      >
        <div className="px-4 pb-4 space-y-1 border-t border-[var(--accent)]/10 pt-3">
          {useCase.features.map((feature) => (
            <Link
              key={feature.path}
              href={feature.path}
              className="flex items-center justify-between p-2 hover:bg-surface/50 transition-colors group/link rounded"
            >
              <div>
                <span
                  className={`font-theme-data text-[10px] ${useCase.color} group-hover/link:text-[var(--accent)] transition-colors`}
                >
                  {feature.name}
                </span>
                <p className="text-[9px] font-theme-data text-text-muted/40 mt-0.5">
                  {feature.description}
                </p>
              </div>
              <span className="text-[10px] font-theme-data text-text-muted/30 group-hover/link:text-[var(--accent)] transition-colors">
                {'>'}
              </span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}

export function UseCaseCards() {
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <section className="py-8">
      {/* Section Header */}
      <div className="text-center mb-6">
        <h2 className="text-[var(--accent)]/80 font-theme-data text-xs tracking-widest mb-2">
          WHO IS ARAGORA FOR?
        </h2>
        <p className="text-text-muted/50 font-theme-data text-[10px]">
          Click to explore features for your role
        </p>
      </div>

      {/* Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
        {USE_CASES.map((useCase) => (
          <UseCaseCard
            key={useCase.id}
            useCase={useCase}
            isExpanded={expandedId === useCase.id}
            onToggle={() => setExpandedId(expandedId === useCase.id ? null : useCase.id)}
          />
        ))}
      </div>
    </section>
  );
}

export { USE_CASES };
export type { UseCase, Feature };
