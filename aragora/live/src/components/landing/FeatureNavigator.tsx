'use client';

import { useState } from 'react';
import Link from 'next/link';

interface Feature {
  name: string;
  path: string;
  description: string;
  badge?: 'new' | 'beta' | 'pro';
}

interface FeatureCategory {
  id: string;
  name: string;
  description: string;
  icon: React.ReactNode;
  color: string;
  features: Feature[];
}

const FEATURE_CATEGORIES: FeatureCategory[] = [
  {
    id: 'run',
    name: 'Run Debates',
    description: 'Start multi-agent debates on any topic',
    color: 'from-blue-500 to-cyan-500',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-6 h-6"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 010 1.972l-11.54 6.347a1.125 1.125 0 01-1.667-.986V5.653z"
        />
      </svg>
    ),
    features: [
      { name: 'Single Debate', path: '/debate', description: 'Run a focused debate on one topic' },
      {
        name: 'Gauntlet',
        path: '/gauntlet',
        description: 'Stress-test answers with adversarial validation',
        badge: 'pro',
      },
      {
        name: 'Graph Debate',
        path: '/debates/graph',
        description: 'Visualize argument structure as a graph',
      },
      {
        name: 'Matrix Debate',
        path: '/debates/matrix',
        description: 'Compare multiple perspectives simultaneously',
      },
      {
        name: 'Batch Processing',
        path: '/batch',
        description: 'Run debates on multiple topics at once',
      },
      {
        name: 'Templates',
        path: '/templates',
        description: 'Start from pre-configured debate templates',
      },
    ],
  },
  {
    id: 'browse',
    name: 'Browse & Discover',
    description: 'Explore past debates and knowledge',
    color: 'from-purple-500 to-pink-500',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-6 h-6"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
        />
      </svg>
    ),
    features: [
      {
        name: 'Debate History',
        path: '/debates',
        description: 'Browse all past debates and outcomes',
      },
      { name: 'Gallery', path: '/gallery', description: 'Visual showcase of debate highlights' },
      { name: 'Replays', path: '/replays', description: 'Watch debates unfold step by step' },
      {
        name: 'Documents',
        path: '/documents',
        description: 'Manage uploaded documents and context',
      },
      {
        name: 'Knowledge Mound',
        path: '/knowledge',
        description: 'Accumulated insights from all debates',
      },
      {
        name: 'Evidence Library',
        path: '/evidence',
        description: 'Browse sourced evidence and citations',
      },
    ],
  },
  {
    id: 'monitor',
    name: 'Monitor & Analyze',
    description: 'Track performance and extract insights',
    color: 'from-green-500 to-emerald-500',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-6 h-6"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 013 19.875v-6.75zM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V8.625zM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 01-1.125-1.125V4.125z"
        />
      </svg>
    ),
    features: [
      {
        name: 'Analytics',
        path: '/analytics',
        description: 'Debate performance metrics and trends',
      },
      { name: 'Insights', path: '/insights', description: 'AI-extracted patterns and learnings' },
      {
        name: 'Quality Dashboard',
        path: '/quality',
        description: 'Monitor answer quality over time',
      },
      { name: 'Calibration', path: '/calibration', description: 'Track confidence vs accuracy' },
      { name: 'Memory Timeline', path: '/memory', description: 'Visualize organizational memory' },
      { name: 'Crux Analysis', path: '/crux', description: 'Identify key decision points' },
    ],
  },
  {
    id: 'compete',
    name: 'Compete & Evaluate',
    description: 'Rank agents and test capabilities',
    color: 'from-orange-500 to-amber-500',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-6 h-6"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M16.5 18.75h-9m9 0a3 3 0 013 3h-15a3 3 0 013-3m9 0v-3.375c0-.621-.503-1.125-1.125-1.125h-.871M7.5 18.75v-3.375c0-.621.504-1.125 1.125-1.125h.872m5.007 0H9.497m5.007 0a7.454 7.454 0 01-.982-3.172M9.497 14.25a7.454 7.454 0 00.981-3.172M5.25 4.236c-.982.143-1.954.317-2.916.52A6.003 6.003 0 007.73 9.728M5.25 4.236V4.5c0 2.108.966 3.99 2.48 5.228M5.25 4.236V2.721C7.456 2.41 9.71 2.25 12 2.25c2.291 0 4.545.16 6.75.47v1.516M7.73 9.728a6.726 6.726 0 002.748 1.35m8.272-6.842V4.5c0 2.108-.966 3.99-2.48 5.228m2.48-5.492a46.32 46.32 0 012.916.52 6.003 6.003 0 01-5.395 4.972m0 0a6.726 6.726 0 01-2.749 1.35m0 0a6.772 6.772 0 01-3.044 0"
        />
      </svg>
    ),
    features: [
      { name: 'Leaderboard', path: '/leaderboard', description: 'ELO rankings of all agents' },
      {
        name: 'Agent Profiles',
        path: '/agents',
        description: 'Detailed agent capabilities and history',
      },
      {
        name: 'Tournaments',
        path: '/tournaments',
        description: 'Organize competitive agent tournaments',
        badge: 'beta',
      },
      { name: 'Compare', path: '/compare', description: 'Side-by-side agent comparison' },
      { name: 'Probe Testing', path: '/probe', description: 'Test specific agent capabilities' },
      {
        name: 'Red Team',
        path: '/red-team',
        description: 'Adversarial testing and vulnerability discovery',
      },
    ],
  },
  {
    id: 'integrate',
    name: 'Integrate & Automate',
    description: 'Connect aragora to your workflows',
    color: 'from-indigo-500 to-violet-500',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-6 h-6"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M13.19 8.688a4.5 4.5 0 011.242 7.244l-4.5 4.5a4.5 4.5 0 01-6.364-6.364l1.757-1.757m13.35-.622l1.757-1.757a4.5 4.5 0 00-6.364-6.364l-4.5 4.5a4.5 4.5 0 001.242 7.244"
        />
      </svg>
    ),
    features: [
      { name: 'API Explorer', path: '/api-explorer', description: 'Interactive API documentation' },
      { name: 'Webhooks', path: '/webhooks', description: 'Configure event notifications' },
      { name: 'Connectors', path: '/connectors', description: 'Data source integrations' },
      {
        name: 'Workflows',
        path: '/workflows',
        description: 'Multi-step automation pipelines',
        badge: 'new',
      },
      {
        name: 'Integrations',
        path: '/integrations',
        description: 'Third-party platform connections',
      },
    ],
  },
  {
    id: 'train',
    name: 'Train & Export',
    description: 'Improve agents and export data',
    color: 'from-rose-500 to-red-500',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-6 h-6"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M4.26 10.147a60.436 60.436 0 00-.491 6.347A48.627 48.627 0 0112 20.904a48.627 48.627 0 018.232-4.41 60.46 60.46 0 00-.491-6.347m-15.482 0a50.57 50.57 0 00-2.658-.813A59.905 59.905 0 0112 3.493a59.902 59.902 0 0110.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.697 50.697 0 0112 13.489a50.702 50.702 0 017.74-3.342M6.75 15a.75.75 0 100-1.5.75.75 0 000 1.5zm0 0v-3.675A55.378 55.378 0 0112 8.443m-7.007 11.55A5.981 5.981 0 006.75 15.75v-1.5"
        />
      </svg>
    ),
    features: [
      {
        name: 'Training Data',
        path: '/training',
        description: 'Export debate data for fine-tuning',
      },
      {
        name: 'Evolution',
        path: '/evolution',
        description: 'Evolve agent populations',
        badge: 'beta',
      },
      { name: 'A/B Testing', path: '/ab-testing', description: 'Compare agent configurations' },
      { name: 'ML Export', path: '/ml', description: 'Export to ML frameworks' },
      { name: 'Laboratory', path: '/laboratory', description: 'Experimental agent development' },
    ],
  },
];

interface FeatureNavigatorProps {
  onEnterDashboard?: () => void;
}

export function FeatureNavigator({ onEnterDashboard }: FeatureNavigatorProps) {
  const [expandedCategory, setExpandedCategory] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Filter features by search query
  const filteredCategories = FEATURE_CATEGORIES.map((category) => ({
    ...category,
    features: category.features.filter(
      (feature) =>
        feature.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        feature.description.toLowerCase().includes(searchQuery.toLowerCase()),
    ),
  })).filter((category) => category.features.length > 0 || searchQuery === '');

  const getBadgeStyles = (badge: 'new' | 'beta' | 'pro') => {
    switch (badge) {
      case 'new':
        return 'bg-green-500/20 text-green-400 border-green-500/30';
      case 'beta':
        return 'bg-amber-500/20 text-amber-400 border-amber-500/30';
      case 'pro':
        return 'bg-purple-500/20 text-purple-400 border-purple-500/30';
    }
  };

  return (
    <div className="space-y-8">
      {/* Header with search and dashboard button */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold text-text">Explore Features</h2>
          <p className="text-text-muted mt-1">Discover what you can do with aragora</p>
        </div>

        <div className="flex items-center gap-3 w-full sm:w-auto">
          {/* Search */}
          <div className="relative flex-1 sm:flex-initial">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search features..."
              className="w-full sm:w-64 px-4 py-2 pl-10 bg-surface border border-border rounded-lg text-text placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
            />
            <svg
              xmlns="http://www.w3.org/2000/svg"
              fill="none"
              viewBox="0 0 24 24"
              strokeWidth={1.5}
              stroke="currentColor"
              className="w-5 h-5 absolute left-3 top-1/2 -translate-y-1/2 text-text-muted"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
              />
            </svg>
          </div>

          {/* Enter Dashboard button */}
          {onEnterDashboard && (
            <button
              onClick={onEnterDashboard}
              className="px-4 py-2 bg-accent hover:bg-accent/80 text-white font-medium rounded-lg transition-colors whitespace-nowrap"
            >
              Enter Dashboard
            </button>
          )}
        </div>
      </div>

      {/* Category cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {filteredCategories.map((category) => (
          <div
            key={category.id}
            className={`
              panel overflow-hidden transition-all duration-300
              ${expandedCategory === category.id ? 'ring-2 ring-accent' : ''}
            `}
          >
            {/* Category header */}
            <button
              onClick={() =>
                setExpandedCategory(expandedCategory === category.id ? null : category.id)
              }
              className="w-full p-4 flex items-start gap-3 text-left hover:bg-surface/50 transition-colors"
            >
              <div
                className={`p-2 rounded-lg bg-gradient-to-br ${category.color} text-white flex-shrink-0`}
              >
                {category.icon}
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="font-semibold text-text">{category.name}</h3>
                <p className="text-sm text-text-muted mt-0.5">{category.description}</p>
                <div className="text-xs text-text-muted mt-1">
                  {category.features.length} feature{category.features.length !== 1 ? 's' : ''}
                </div>
              </div>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
                strokeWidth={2}
                stroke="currentColor"
                className={`w-5 h-5 text-text-muted flex-shrink-0 transition-transform duration-200 ${
                  expandedCategory === category.id ? 'rotate-180' : ''
                }`}
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  d="M19.5 8.25l-7.5 7.5-7.5-7.5"
                />
              </svg>
            </button>

            {/* Expanded feature list */}
            <div
              className={`
                overflow-hidden transition-all duration-300
                ${expandedCategory === category.id ? 'max-h-96' : 'max-h-0'}
              `}
            >
              <div className="p-4 pt-0 space-y-1 border-t border-border">
                {category.features.map((feature) => (
                  <Link
                    key={feature.path}
                    href={feature.path}
                    className="flex items-center justify-between p-2 rounded-lg hover:bg-surface transition-colors group"
                  >
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm text-text group-hover:text-accent transition-colors">
                          {feature.name}
                        </span>
                        {feature.badge && (
                          <span
                            className={`text-[10px] px-1.5 py-0.5 rounded border ${getBadgeStyles(
                              feature.badge,
                            )}`}
                          >
                            {feature.badge.toUpperCase()}
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-text-muted mt-0.5">{feature.description}</p>
                    </div>
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      fill="none"
                      viewBox="0 0 24 24"
                      strokeWidth={2}
                      stroke="currentColor"
                      className="w-4 h-4 text-text-muted group-hover:text-accent transition-colors"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        d="M8.25 4.5l7.5 7.5-7.5 7.5"
                      />
                    </svg>
                  </Link>
                ))}
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* No results message */}
      {filteredCategories.length === 0 && (
        <div className="text-center py-12">
          <p className="text-text-muted">No features found matching &quot;{searchQuery}&quot;</p>
          <button
            onClick={() => setSearchQuery('')}
            className="mt-2 text-sm text-accent hover:underline"
          >
            Clear search
          </button>
        </div>
      )}

      {/* Quick start section */}
      <div className="panel p-6">
        <h3 className="font-semibold text-text mb-4">Quick Start</h3>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <Link
            href="/debate"
            className="p-4 bg-surface rounded-lg border border-border hover:border-accent transition-colors group"
          >
            <div className="text-2xl mb-2">1</div>
            <h4 className="font-medium text-text group-hover:text-accent transition-colors">
              Run Your First Debate
            </h4>
            <p className="text-sm text-text-muted mt-1">
              Enter a question and watch agents deliberate
            </p>
          </Link>
          <Link
            href="/leaderboard"
            className="p-4 bg-surface rounded-lg border border-border hover:border-accent transition-colors group"
          >
            <div className="text-2xl mb-2">2</div>
            <h4 className="font-medium text-text group-hover:text-accent transition-colors">
              Explore the Leaderboard
            </h4>
            <p className="text-sm text-text-muted mt-1">
              See which agents perform best on different topics
            </p>
          </Link>
          <Link
            href="/api-explorer"
            className="p-4 bg-surface rounded-lg border border-border hover:border-accent transition-colors group"
          >
            <div className="text-2xl mb-2">3</div>
            <h4 className="font-medium text-text group-hover:text-accent transition-colors">
              Integrate via API
            </h4>
            <p className="text-sm text-text-muted mt-1">Connect aragora to your applications</p>
          </Link>
        </div>
      </div>
    </div>
  );
}

export { FEATURE_CATEGORIES };
export type { Feature, FeatureCategory };
