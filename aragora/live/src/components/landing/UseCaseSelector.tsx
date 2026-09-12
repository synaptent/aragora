'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useAdaptiveMode } from '@/context/AdaptiveModeContext';

/**
 * Use case category with sub-items
 */
export interface UseCase {
  id: string;
  title: string;
  icon: string;
  description: string;
  color: string;
  items: UseCaseItem[];
  endpoints: string[];
}

export interface UseCaseItem {
  id: string;
  label: string;
  description: string;
  href: string;
  advancedOnly?: boolean;
}

/**
 * Primary use case categories from the unified platform plan
 */
export const USE_CASES: UseCase[] = [
  {
    id: 'security',
    title: 'Security',
    icon: '🛡️',
    description: 'Code review, API scanning, and red team analysis',
    color: 'text-red-400 bg-red-500/10 border-red-500/30',
    endpoints: ['/api/reviews/*', '/api/gauntlet/*', '/api/redteam/*'],
    items: [
      {
        id: 'code-review',
        label: 'Code Review',
        description: 'Multi-agent security review of code changes',
        href: '/reviews',
      },
      {
        id: 'api-scan',
        label: 'API Scan',
        description: 'Automated API vulnerability analysis',
        href: '/gauntlet?mode=api',
      },
      {
        id: 'red-team',
        label: 'Red Team',
        description: 'Adversarial testing and attack simulation',
        href: '/red-team',
        advancedOnly: true,
      },
      {
        id: 'probes',
        label: 'Capability Probes',
        description: 'Test model capabilities and boundaries',
        href: '/probe',
        advancedOnly: true,
      },
    ],
  },
  {
    id: 'compliance',
    title: 'Compliance',
    icon: '📋',
    description: 'GDPR, HIPAA, SOX, and regulatory audits',
    color: 'text-blue-400 bg-blue-500/10 border-blue-500/30',
    endpoints: ['/api/gauntlet/gdpr', '/api/audit/*'],
    items: [
      {
        id: 'gdpr',
        label: 'GDPR Check',
        description: 'European data protection compliance',
        href: '/gauntlet?mode=gdpr',
      },
      {
        id: 'hipaa',
        label: 'HIPAA Audit',
        description: 'Healthcare data privacy review',
        href: '/gauntlet?mode=hipaa',
      },
      {
        id: 'sox',
        label: 'SOX Compliance',
        description: 'Financial reporting controls',
        href: '/audit?type=sox',
        advancedOnly: true,
      },
      {
        id: 'audit-log',
        label: 'Audit Trail',
        description: 'View all compliance audit history',
        href: '/audit',
        advancedOnly: true,
      },
    ],
  },
  {
    id: 'architecture',
    title: 'Architecture',
    icon: '🏗️',
    description: 'Stress testing and system design analysis',
    color: 'text-purple-400 bg-purple-500/10 border-purple-500/30',
    endpoints: ['/api/gauntlet/*', '/api/debates/graph/*'],
    items: [
      {
        id: 'stress-test',
        label: 'Stress Test',
        description: 'Multi-perspective system stress analysis',
        href: '/gauntlet',
      },
      {
        id: 'incident',
        label: 'Incident Analysis',
        description: 'Post-mortem and root cause debates',
        href: '/debates?type=incident',
      },
      {
        id: 'graph-debate',
        label: 'Graph Debates',
        description: 'Visualize argument structure',
        href: '/debates/graph',
        advancedOnly: true,
      },
      {
        id: 'modes',
        label: 'Debate Modes',
        description: 'Configure debate protocols',
        href: '/modes',
        advancedOnly: true,
      },
    ],
  },
  {
    id: 'research',
    title: 'Research',
    icon: '🔬',
    description: 'Literature review and knowledge synthesis',
    color: 'text-green-400 bg-green-500/10 border-green-500/30',
    endpoints: ['/api/knowledge/*', '/api/evidence/*'],
    items: [
      {
        id: 'literature',
        label: 'Literature Review',
        description: 'Synthesize research from multiple sources',
        href: '/knowledge',
      },
      {
        id: 'evidence',
        label: 'Evidence Collection',
        description: 'Gather and verify supporting data',
        href: '/evidence',
      },
      {
        id: 'citations',
        label: 'Citation Check',
        description: 'Verify references and sources',
        href: '/verification',
      },
      {
        id: 'pulse',
        label: 'Trending Topics',
        description: 'Discover what is being discussed',
        href: '/pulse',
      },
    ],
  },
  {
    id: 'decisions',
    title: 'Decisions',
    icon: '⚖️',
    description: 'Vendor comparison and contract review',
    color: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30',
    endpoints: ['/api/debates/matrix/*', '/api/receipts/*'],
    items: [
      {
        id: 'vendor',
        label: 'Vendor Compare',
        description: 'Multi-criteria vendor evaluation',
        href: '/compare',
      },
      {
        id: 'contract',
        label: 'Contract Review',
        description: 'Legal document analysis',
        href: '/debates?type=contract',
      },
      {
        id: 'matrix',
        label: 'Matrix Debates',
        description: 'Multi-dimensional decision analysis',
        href: '/debates/matrix',
        advancedOnly: true,
      },
      {
        id: 'receipts',
        label: 'Decision Receipts',
        description: 'Documented reasoning trails',
        href: '/receipts',
        advancedOnly: true,
      },
    ],
  },
  {
    id: 'industry',
    title: 'Industry',
    icon: '🏢',
    description: 'Domain-specific agents and compliance',
    color: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/30',
    endpoints: ['/api/verticals/*'],
    items: [
      {
        id: 'healthcare',
        label: 'Healthcare',
        description: 'Clinical and HIPAA specialists',
        href: '/verticals?category=healthcare',
      },
      {
        id: 'finance',
        label: 'Finance',
        description: 'Financial analysis and SOX',
        href: '/verticals?category=finance',
      },
      {
        id: 'legal',
        label: 'Legal',
        description: 'Contract and compliance experts',
        href: '/verticals?category=legal',
      },
      {
        id: 'all-verticals',
        label: 'All Verticals',
        description: 'Browse domain specialists',
        href: '/verticals',
      },
    ],
  },
];

export interface UseCaseSelectorProps {
  /** Called when a use case card is selected */
  onSelect?: (useCase: UseCase) => void;
  /** Show items inline vs expandable */
  expandable?: boolean;
  /** Additional CSS classes */
  className?: string;
}

/**
 * Use case selector grid for the landing page
 */
export function UseCaseSelector({
  onSelect,
  expandable = true,
  className = '',
}: UseCaseSelectorProps) {
  const { mode } = useAdaptiveMode();
  const isAdvanced = mode === 'advanced';
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const handleCardClick = (useCase: UseCase) => {
    if (expandable) {
      setExpandedId(expandedId === useCase.id ? null : useCase.id);
    }
    onSelect?.(useCase);
  };

  return (
    <div className={`grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 ${className}`}>
      {USE_CASES.map((useCase) => {
        const isExpanded = expandedId === useCase.id;
        const visibleItems = isAdvanced
          ? useCase.items
          : useCase.items.filter((item) => !item.advancedOnly);

        return (
          <div
            key={useCase.id}
            className={`rounded-lg border transition-all duration-200 ${useCase.color} ${
              isExpanded ? 'ring-2 ring-offset-2 ring-offset-gray-900' : ''
            }`}
          >
            {/* Header */}
            <button onClick={() => handleCardClick(useCase)} className="w-full p-6 text-left">
              <div className="flex items-center gap-3 mb-2">
                <span className="text-3xl">{useCase.icon}</span>
                <h3 className="text-xl font-bold">{useCase.title}</h3>
              </div>
              <p className="text-sm opacity-80">{useCase.description}</p>

              {expandable && (
                <div className="mt-4 flex items-center gap-2 text-xs opacity-60">
                  <span>{visibleItems.length} features</span>
                  <svg
                    className={`w-4 h-4 transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M19 9l-7 7-7-7"
                    />
                  </svg>
                </div>
              )}
            </button>

            {/* Expanded items */}
            {(isExpanded || !expandable) && (
              <div className="border-t border-current/20 p-4 space-y-2">
                {visibleItems.map((item) => (
                  <Link
                    key={item.id}
                    href={item.href}
                    className="block p-3 rounded bg-black/20 hover:bg-black/30 transition-colors"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{item.label}</span>
                      <svg
                        className="w-4 h-4 opacity-60"
                        fill="none"
                        viewBox="0 0 24 24"
                        stroke="currentColor"
                      >
                        <path
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          strokeWidth={2}
                          d="M9 5l7 7-7 7"
                        />
                      </svg>
                    </div>
                    <p className="text-xs opacity-60 mt-1">{item.description}</p>
                  </Link>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/**
 * Quick start cards for most common workflows
 */
export function QuickStartCards() {
  const quickStarts = [
    {
      title: 'Code Security',
      description: 'Review code for vulnerabilities',
      href: '/reviews',
      icon: '🔐',
    },
    {
      title: 'GDPR Check',
      description: 'Assess data protection compliance',
      href: '/gauntlet?mode=gdpr',
      icon: '🇪🇺',
    },
    {
      title: 'Stress Test',
      description: 'Multi-agent stress analysis',
      href: '/gauntlet',
      icon: '🏋️',
    },
    { title: 'Research', description: 'Literature synthesis', href: '/knowledge', icon: '📚' },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
      {quickStarts.map((qs) => (
        <Link
          key={qs.title}
          href={qs.href}
          className="p-4 rounded-lg border border-gray-700 bg-gray-800/50 hover:bg-gray-800 hover:border-blue-500/50 transition-all group"
        >
          <span className="text-2xl block mb-2">{qs.icon}</span>
          <h4 className="font-medium group-hover:text-blue-400 transition-colors">{qs.title}</h4>
          <p className="text-xs text-gray-400 mt-1">{qs.description}</p>
        </Link>
      ))}
    </div>
  );
}

export default UseCaseSelector;
