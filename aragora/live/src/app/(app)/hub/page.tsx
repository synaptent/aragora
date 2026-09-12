'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useState, useCallback } from 'react';
import { useBackend } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';
import { DEFAULT_AGENTS } from '@/config';

interface UseCaseCard {
  id: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  href: string;
  color: string;
  features: string[];
  cta: string;
}

const useCases: UseCaseCard[] = [
  {
    id: 'debate',
    title: 'Run a Debate',
    description:
      'Multi-agent adversarial reasoning on any topic. Get balanced perspectives from AI agents with different viewpoints.',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-8 h-8"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M20.25 8.511c.884.284 1.5 1.128 1.5 2.097v4.286c0 1.136-.847 2.1-1.98 2.193-.34.027-.68.052-1.02.072v3.091l-3-3c-1.354 0-2.694-.055-4.02-.163a2.115 2.115 0 01-.825-.242m9.345-8.334a2.126 2.126 0 00-.476-.095 48.64 48.64 0 00-8.048 0c-1.131.094-1.976 1.057-1.976 2.192v4.286c0 .837.46 1.58 1.155 1.951m9.345-8.334V6.637c0-1.621-1.152-3.026-2.76-3.235A48.455 48.455 0 0011.25 3c-2.115 0-4.198.137-6.24.402-1.608.209-2.76 1.614-2.76 3.235v6.226c0 1.621 1.152 3.026 2.76 3.235.577.075 1.157.14 1.74.194V21l4.155-4.155"
        />
      </svg>
    ),
    href: '/arena',
    color: 'accent',
    features: [
      'Multi-agent reasoning',
      'Consensus detection',
      'Evidence citations',
      'Shareable results',
    ],
    cta: 'Start Debate',
  },
  {
    id: 'gauntlet',
    title: 'Stress-Test',
    description:
      'Red-team your decisions with adversarial validation. Uncover blind spots and edge cases before they become problems.',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-8 h-8"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M9 12.75L11.25 15 15 9.75m-3-7.036A11.959 11.959 0 013.598 6 11.99 11.99 0 003 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285z"
        />
      </svg>
    ),
    href: '/gauntlet',
    color: 'gold',
    features: [
      'Adversarial testing',
      'Risk assessment',
      'Vulnerability detection',
      'Detailed reports',
    ],
    cta: 'Run Gauntlet',
  },
  {
    id: 'review',
    title: 'Review Code',
    description:
      'Get multi-perspective code reviews from specialized AI agents. Catch bugs, security issues, and design problems.',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-8 h-8"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5"
        />
      </svg>
    ),
    href: '/reviews',
    color: 'acid-cyan',
    features: [
      'Security analysis',
      'Performance review',
      'Architecture critique',
      'Best practices',
    ],
    cta: 'Review Code',
  },
  {
    id: 'audit',
    title: 'Audit Document',
    description:
      'Deep document analysis with multi-agent verification. Extract insights, verify claims, and identify inconsistencies.',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-8 h-8"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m5.231 13.481L15 17.25m-4.5-15H5.625c-.621 0-1.125.504-1.125 1.125v16.5c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9zm3.75 11.625a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z"
        />
      </svg>
    ),
    href: '/audit',
    color: 'acid-purple',
    features: [
      'Claim verification',
      'Citation checking',
      'Contradiction detection',
      'Summary generation',
    ],
    cta: 'Audit Document',
  },
  {
    id: 'knowledge',
    title: 'Query Knowledge',
    description:
      'Search the consensus knowledge base built from past debates. Find verified information and insights.',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-8 h-8"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M12 18v-5.25m0 0a6.01 6.01 0 001.5-.189m-1.5.189a6.01 6.01 0 01-1.5-.189m3.75 7.478a12.06 12.06 0 01-4.5 0m3.75 2.383a14.406 14.406 0 01-3 0M14.25 18v-.192c0-.983.658-1.823 1.508-2.316a7.5 7.5 0 10-7.517 0c.85.493 1.509 1.333 1.509 2.316V18"
        />
      </svg>
    ),
    href: '/knowledge',
    color: 'success',
    features: ['Semantic search', 'Consensus tracking', 'Source verification', 'Related debates'],
    cta: 'Search Knowledge',
  },
  {
    id: 'documents',
    title: 'Manage Documents',
    description:
      'Upload, organize, and analyze your documents. Support for PDFs, audio, video, and transcriptions.',
    icon: (
      <svg
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
        strokeWidth={1.5}
        stroke="currentColor"
        className="w-8 h-8"
      >
        <path
          strokeLinecap="round"
          strokeLinejoin="round"
          d="M2.25 12.75V12A2.25 2.25 0 014.5 9.75h15A2.25 2.25 0 0121.75 12v.75m-8.69-6.44l-2.12-2.12a1.5 1.5 0 00-1.061-.44H4.5A2.25 2.25 0 002.25 6v12a2.25 2.25 0 002.25 2.25h15A2.25 2.25 0 0021.75 18V9a2.25 2.25 0 00-2.25-2.25h-5.379a1.5 1.5 0 01-1.06-.44z"
        />
      </svg>
    ),
    href: '/documents',
    color: 'text',
    features: [
      'Drag & drop upload',
      'Audio/video transcription',
      'YouTube import',
      'Folder support',
    ],
    cta: 'Manage Documents',
  },
];

const quickActions = [
  { label: 'View Debates', href: '/debates', icon: '#' },
  { label: 'Leaderboard', href: '/leaderboard', icon: '^' },
  { label: 'Analytics', href: '/analytics', icon: '~' },
  { label: 'Workflows', href: '/workflows', icon: '>' },
  { label: 'Connectors', href: '/connectors', icon: '<' },
  { label: 'Settings', href: '/settings', icon: '*' },
];

export default function HubPage() {
  const router = useRouter();
  const { config: backendConfig } = useBackend();
  const [quickDebateTopic, setQuickDebateTopic] = useState('');
  const [isStarting, setIsStarting] = useState(false);

  const handleQuickDebate = useCallback(async () => {
    if (!quickDebateTopic.trim() || isStarting) return;

    setIsStarting(true);
    try {
      const response = await fetch(`${backendConfig.api}/api/debate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: quickDebateTopic.trim(),
          agents: DEFAULT_AGENTS,
          rounds: 3,
        }),
      });

      const data = await response.json();
      if (data.success && data.debate_id) {
        router.push(`/debate/${data.debate_id}`);
      }
    } catch (error) {
      logger.error('Failed to start debate:', error);
    } finally {
      setIsStarting(false);
    }
  }, [quickDebateTopic, backendConfig.api, router, isStarting]);

  return (
    <main className="min-h-screen bg-bg">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12">
        {/* Hero Section */}
        <div className="text-center mb-12">
          <h1 className="text-3xl sm:text-4xl lg:text-5xl font-bold text-text mb-4">
            What do you want to do?
          </h1>
          <p className="text-lg text-text-muted max-w-2xl mx-auto">
            Multiple AI models debate your decisions. Choose a use case below or start with a quick
            debate.
          </p>
        </div>

        {/* Quick Debate Input */}
        <div className="max-w-2xl mx-auto mb-12">
          <div className="flex gap-2">
            <input
              type="text"
              value={quickDebateTopic}
              onChange={(e) => setQuickDebateTopic(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleQuickDebate()}
              placeholder="Enter a topic to debate..."
              className="flex-1 px-4 py-3 rounded-lg border border-border bg-surface text-text placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent focus:border-transparent"
            />
            <button
              onClick={handleQuickDebate}
              disabled={!quickDebateTopic.trim() || isStarting}
              className={`px-6 py-3 rounded-lg font-medium transition-colors ${
                quickDebateTopic.trim() && !isStarting
                  ? 'bg-accent text-white hover:bg-accent/80'
                  : 'bg-surface-elevated text-text-muted cursor-not-allowed'
              }`}
            >
              {isStarting ? 'Starting...' : 'Debate'}
            </button>
          </div>
          <p className="text-xs text-text-muted mt-2 text-center">
            Press Enter to start a multi-agent debate on any topic
          </p>
        </div>

        {/* Use Case Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 mb-12">
          {useCases.map((useCase) => (
            <Link
              key={useCase.id}
              href={useCase.href}
              className="group block p-6 rounded-xl border border-border bg-surface hover:border-accent/50 hover:shadow-lg transition-all"
            >
              <div
                className={`inline-flex p-3 rounded-lg bg-${useCase.color}/10 text-${useCase.color} mb-4 group-hover:bg-${useCase.color}/20 transition-colors`}
              >
                {useCase.icon}
              </div>
              <h2 className="text-xl font-semibold text-text mb-2 group-hover:text-accent transition-colors">
                {useCase.title}
              </h2>
              <p className="text-text-muted text-sm mb-4 line-clamp-2">{useCase.description}</p>
              <ul className="space-y-1 mb-4">
                {useCase.features.map((feature) => (
                  <li key={feature} className="flex items-center gap-2 text-xs text-text-muted">
                    <span className="text-accent">+</span>
                    {feature}
                  </li>
                ))}
              </ul>
              <span className="inline-flex items-center gap-1 text-sm font-medium text-accent">
                {useCase.cta}
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  fill="none"
                  viewBox="0 0 24 24"
                  strokeWidth={2}
                  stroke="currentColor"
                  className="w-4 h-4 group-hover:translate-x-1 transition-transform"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3"
                  />
                </svg>
              </span>
            </Link>
          ))}
        </div>

        {/* Quick Access Bar */}
        <div className="border-t border-border pt-8">
          <h3 className="text-sm font-medium text-text-muted mb-4 text-center">Quick Access</h3>
          <div className="flex flex-wrap justify-center gap-3">
            {quickActions.map((action) => (
              <Link
                key={action.href}
                href={action.href}
                className="px-4 py-2 rounded-lg border border-border text-sm text-text-muted hover:text-accent hover:border-accent/50 transition-colors flex items-center gap-2"
              >
                <span className="text-accent font-theme-data">{action.icon}</span>
                {action.label}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
