'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { AsciiBannerCompact } from '@/components/AsciiBanner';
import { useBackend } from '@/components/BackendSelector';
import { UseCaseSelector, QuickStartCards } from '@/components/landing';
import { AdaptiveModeToggle } from '@/components/ui/AdaptiveModeToggle';
import { useAdaptiveMode } from '@/context/AdaptiveModeContext';

interface LiveDebate {
  id: string;
  topic: string;
  agents: string[];
  round: number;
  totalRounds: number;
  status: 'active' | 'completed';
}

export default function PortalPage() {
  const { config } = useBackend();
  const { mode } = useAdaptiveMode();
  const [liveDebates, setLiveDebates] = useState<LiveDebate[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Fetch recent/live debates for preview
    async function fetchLiveDebates() {
      try {
        const response = await fetch(`${config.api}/api/debates?limit=5&status=active`);
        if (response.ok) {
          const data = await response.json();
          setLiveDebates(data.debates || []);
        }
      } catch {
        // Silently fail - preview is optional
      } finally {
        setLoading(false);
      }
    }
    fetchLiveDebates();
  }, [config.api]);

  return (
    <div className="min-h-screen bg-bg text-text relative overflow-hidden">
      <Scanlines opacity={0.02} />
      <CRTVignette />

      {/* Hero Section */}
      <section className="relative z-10 py-16 px-4 border-b border-[var(--accent)]/20">
        <div className="container mx-auto max-w-6xl text-center">
          <div className="mb-6">
            <Link href="/" className="inline-flex hover:opacity-80 transition-opacity">
              <AsciiBannerCompact connected={true} />
            </Link>
          </div>
          <h1 className="text-4xl md:text-5xl font-theme-data font-bold text-[var(--accent)] mb-4">
            Multi Agent Decision Making
          </h1>
          <p className="text-text-muted font-theme-data max-w-2xl mx-auto mb-8">
            Multi-agent stress testing, compliance auditing, and decision validation. Watch AI
            agents debate, critique, and forge consensus on your toughest problems.
          </p>
          <div className="flex flex-wrap justify-center gap-4">
            <Link
              href="/hub"
              className="px-6 py-3 bg-[var(--accent)]/20 border-2 border-[var(--accent)] text-[var(--accent)] font-theme-data font-bold rounded hover:bg-[var(--accent)]/30 transition-colors"
            >
              Try It Now - No Account
            </Link>
            <Link
              href="/about"
              className="px-6 py-3 border border-[var(--accent)]/50 text-[var(--accent)] font-theme-data rounded hover:bg-[var(--accent)]/10 transition-colors"
            >
              Watch Demo
            </Link>
          </div>
          <div className="mt-6 flex justify-center">
            <AdaptiveModeToggle />
          </div>
        </div>
      </section>

      {/* Use Case Selection */}
      <section className="relative z-10 py-12 px-4 bg-surface/30">
        <div className="container mx-auto max-w-6xl">
          <h2 className="text-2xl font-theme-data font-bold text-[var(--accent)] text-center mb-8">
            What do you need to solve?
          </h2>
          <UseCaseSelector className="mb-8" />
        </div>
      </section>

      {/* Quick Start Wizards */}
      <section className="relative z-10 py-12 px-4">
        <div className="container mx-auto max-w-5xl">
          <h2 className="text-xl font-theme-data font-bold text-[var(--accent)] text-center mb-6">
            Quick Start
          </h2>
          <QuickStartCards />
        </div>
      </section>

      {/* Live Preview */}
      <section className="relative z-10 py-12 px-4 bg-surface/30">
        <div className="container mx-auto max-w-5xl">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-xl font-theme-data font-bold text-[var(--accent)]">Live Debates</h2>
            <Link
              href="/debates"
              className="text-sm font-theme-data text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              View All
            </Link>
          </div>

          {loading ? (
            <div className="text-center py-8">
              <div className="text-[var(--accent)] font-theme-data animate-pulse">Loading...</div>
            </div>
          ) : liveDebates.length === 0 ? (
            <div className="text-center py-8 border border-[var(--accent)]/20 rounded-lg bg-bg/50">
              <p className="text-text-muted font-theme-data mb-4">No live debates right now</p>
              <Link
                href="/hub"
                className="inline-block px-4 py-2 bg-[var(--accent)]/20 border border-[var(--accent)] text-[var(--accent)] font-theme-data text-sm rounded hover:bg-[var(--accent)]/30 transition-colors"
              >
                Start a Debate
              </Link>
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {liveDebates.map((debate) => (
                <Link
                  key={debate.id}
                  href={`/debate/${debate.id}`}
                  className="p-4 bg-bg border border-[var(--accent)]/20 rounded-lg hover:border-[var(--accent)]/50 transition-colors group"
                >
                  <div className="flex items-center justify-between mb-2">
                    <span
                      className={`text-xs font-theme-data px-2 py-0.5 rounded ${
                        debate.status === 'active'
                          ? 'bg-[var(--accent)]/20 text-[var(--accent)]'
                          : 'bg-text-muted/20 text-text-muted'
                      }`}
                    >
                      {debate.status === 'active' ? 'LIVE' : 'COMPLETED'}
                    </span>
                    <span className="text-xs font-theme-data text-text-muted">
                      Round {debate.round}/{debate.totalRounds}
                    </span>
                  </div>
                  <h3 className="font-theme-data text-sm text-text group-hover:text-[var(--accent)] transition-colors line-clamp-2">
                    {debate.topic}
                  </h3>
                  <div className="mt-2 flex flex-wrap gap-1">
                    {debate.agents.slice(0, 3).map((agent, i) => (
                      <span
                        key={i}
                        className="text-xs font-theme-data text-text-muted bg-surface px-1 rounded"
                      >
                        {agent}
                      </span>
                    ))}
                    {debate.agents.length > 3 && (
                      <span className="text-xs font-theme-data text-text-muted">
                        +{debate.agents.length - 3}
                      </span>
                    )}
                  </div>
                </Link>
              ))}
            </div>
          )}
        </div>
      </section>

      {/* Features Overview - Simple Mode */}
      {mode === 'simple' && (
        <section className="relative z-10 py-12 px-4">
          <div className="container mx-auto max-w-5xl">
            <h2 className="text-xl font-theme-data font-bold text-[var(--accent)] text-center mb-8">
              How It Works
            </h2>
            <div className="grid md:grid-cols-3 gap-6">
              <div className="text-center p-6 border border-[var(--accent)]/20 rounded-lg">
                <div className="text-4xl mb-4">1</div>
                <h3 className="font-theme-data font-bold text-[var(--acid-cyan)] mb-2">
                  Describe Your Challenge
                </h3>
                <p className="text-sm text-text-muted font-theme-data">
                  Enter a topic, upload documents, or paste code for review.
                </p>
              </div>
              <div className="text-center p-6 border border-[var(--accent)]/20 rounded-lg">
                <div className="text-4xl mb-4">2</div>
                <h3 className="font-theme-data font-bold text-[var(--acid-cyan)] mb-2">
                  Agents Deliberate
                </h3>
                <p className="text-sm text-text-muted font-theme-data">
                  Multiple AI perspectives debate, critique, and refine positions.
                </p>
              </div>
              <div className="text-center p-6 border border-[var(--accent)]/20 rounded-lg">
                <div className="text-4xl mb-4">3</div>
                <h3 className="font-theme-data font-bold text-[var(--acid-cyan)] mb-2">
                  Get Decision Receipt
                </h3>
                <p className="text-sm text-text-muted font-theme-data">
                  Receive documented reasoning and consensus with full audit trail.
                </p>
              </div>
            </div>
          </div>
        </section>
      )}

      {/* Advanced Features - Advanced Mode */}
      {mode === 'advanced' && (
        <section className="relative z-10 py-12 px-4">
          <div className="container mx-auto max-w-6xl">
            <h2 className="text-xl font-theme-data font-bold text-[var(--accent)] text-center mb-8">
              Advanced Capabilities
            </h2>
            <div className="grid md:grid-cols-4 gap-4">
              {[
                {
                  icon: '*',
                  title: 'Graph Debates',
                  href: '/debates/graph',
                  desc: 'Multi-dimensional argument topology',
                },
                {
                  icon: '#',
                  title: 'Matrix Mode',
                  href: '/debates/matrix',
                  desc: 'Cross-perspective evaluation',
                },
                {
                  icon: '%',
                  title: 'Gauntlet',
                  href: '/gauntlet',
                  desc: 'Stress-test decision resilience',
                },
                {
                  icon: '!',
                  title: 'Red Team',
                  href: '/red-team',
                  desc: 'Adversarial challenge generation',
                },
                { icon: '?', title: 'Probes', href: '/probe', desc: 'Capability boundary testing' },
                { icon: '=', title: 'Memory', href: '/memory', desc: 'Cross-session learning' },
                { icon: '~', title: 'Workflows', href: '/workflows', desc: 'Automated pipelines' },
                { icon: '>', title: 'API', href: '/developer', desc: 'Programmatic access' },
              ].map((item) => (
                <Link
                  key={item.title}
                  href={item.href}
                  className="p-4 border border-[var(--accent)]/20 rounded hover:border-[var(--accent)]/50 hover:bg-[var(--accent)]/5 transition-colors"
                >
                  <div className="text-2xl font-theme-data text-[var(--accent)] mb-2">
                    {item.icon}
                  </div>
                  <h3 className="font-theme-data font-bold text-sm text-[var(--acid-cyan)] mb-1">
                    {item.title}
                  </h3>
                  <p className="text-xs text-text-muted font-theme-data">{item.desc}</p>
                </Link>
              ))}
            </div>
          </div>
        </section>
      )}

      {/* Footer */}
      <footer className="relative z-10 text-center text-xs font-theme-data py-12 border-t border-[var(--accent)]/20">
        <div className="container mx-auto px-4">
          <div className="text-[var(--accent)]/50 mb-4">{'═'.repeat(40)}</div>
          <div className="flex justify-center gap-6 mb-6">
            <Link
              href="/about"
              className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              About
            </Link>
            <Link
              href="/security"
              className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              Security
            </Link>
            <Link
              href="/privacy"
              className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              Privacy
            </Link>
            <Link
              href="/developer"
              className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              API
            </Link>
            <Link
              href="/pricing"
              className="text-[var(--acid-cyan)] hover:text-[var(--accent)] transition-colors"
            >
              Pricing
            </Link>
          </div>
          <p className="text-text-muted">Real-time AI stress-testing for decisions that matter.</p>
          <div className="text-[var(--accent)]/50 mt-4">{'═'.repeat(40)}</div>
        </div>
      </footer>
    </div>
  );
}
