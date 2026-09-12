'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';

// ---------------------------------------------------------------------------
// Cached Demo Debate Data
// ---------------------------------------------------------------------------

interface DemoEvent {
  type: 'proposal' | 'critique' | 'vote' | 'consensus';
  agent: string;
  model: string;
  content: string;
  round: number;
  timestamp: number;
  confidence?: number;
  vote?: 'support' | 'oppose' | 'neutral';
}

interface DemoDebate {
  id: string;
  topic: string;
  agents: string[];
  rounds: number;
  consensus_reached: boolean;
  confidence: number;
  verdict: string;
  events: DemoEvent[];
}

const DEMO_DEBATE: DemoDebate = {
  id: 'demo_showcase_001',
  topic:
    'Should our startup adopt AI-powered code review as a mandatory step in our CI/CD pipeline?',
  agents: ['claude-sonnet', 'gpt-4o', 'gemini-pro', 'mistral-large', 'grok-2'],
  rounds: 2,
  consensus_reached: true,
  confidence: 0.82,
  verdict:
    'Adopt AI code review as an advisory layer with human override, not a blocking gate. Start with security-critical paths only, expand based on measured false-positive rates.',
  events: [
    {
      type: 'proposal',
      agent: 'claude-sonnet',
      model: 'Claude Sonnet',
      content:
        'Yes, adopt it as mandatory. AI code review catches security vulnerabilities that human reviewers miss 34% of the time. The key is treating it as a complement, not a replacement — flag issues for human judgment, not auto-reject.',
      round: 1,
      timestamp: 0,
      confidence: 0.85,
    },
    {
      type: 'proposal',
      agent: 'gpt-4o',
      model: 'GPT-4o',
      content:
        'Mandatory is too strong. AI review tools have 15-25% false positive rates on complex codebases. Making it mandatory creates alert fatigue and slows velocity. Better as advisory with opt-in enforcement for security-critical paths.',
      round: 1,
      timestamp: 2000,
      confidence: 0.78,
    },
    {
      type: 'critique',
      agent: 'gemini-pro',
      model: 'Gemini Pro',
      content:
        'Both proposals miss the cost dimension. AI review at scale costs $0.02-0.15 per PR. For a team doing 200 PRs/week, that is $200-1,500/month. The ROI depends on your current bug escape rate — if it is below 2%, the investment may not justify mandatory adoption.',
      round: 1,
      timestamp: 4000,
      confidence: 0.72,
    },
    {
      type: 'critique',
      agent: 'mistral-large',
      model: 'Mistral Large',
      content:
        'I challenge the 34% claim. That statistic comes from controlled benchmarks, not production codebases. In practice, AI reviewers excel at pattern-matching (SQL injection, XSS) but struggle with business logic flaws and architectural issues — the bugs that actually cause outages.',
      round: 1,
      timestamp: 6000,
      confidence: 0.76,
    },
    {
      type: 'proposal',
      agent: 'grok-2',
      model: 'Grok 2',
      content:
        'The framing is wrong. The question is not mandatory vs optional — it is which paths are mandatory. Security-critical code (auth, payments, data access) should require AI review. Feature code should get advisory review. This reduces false-positive fatigue while protecting high-risk surfaces.',
      round: 2,
      timestamp: 8000,
      confidence: 0.88,
    },
    {
      type: 'vote',
      agent: 'claude-sonnet',
      model: 'Claude Sonnet',
      content: 'I revise my position. Path-based mandatory review is the pragmatic middle ground.',
      round: 2,
      timestamp: 10000,
      vote: 'support',
      confidence: 0.84,
    },
    {
      type: 'vote',
      agent: 'gpt-4o',
      model: 'GPT-4o',
      content:
        'Agreed. Tiered enforcement addresses my velocity concern while maintaining security coverage.',
      round: 2,
      timestamp: 11000,
      vote: 'support',
      confidence: 0.81,
    },
    {
      type: 'vote',
      agent: 'gemini-pro',
      model: 'Gemini Pro',
      content:
        'Support, with the caveat that ROI should be measured after 90 days to validate the cost-benefit.',
      round: 2,
      timestamp: 12000,
      vote: 'support',
      confidence: 0.79,
    },
    {
      type: 'vote',
      agent: 'mistral-large',
      model: 'Mistral Large',
      content:
        'Conditional support. The path classification must be reviewed quarterly as the codebase evolves.',
      round: 2,
      timestamp: 13000,
      vote: 'support',
      confidence: 0.74,
    },
    {
      type: 'consensus',
      agent: 'system',
      model: 'Consensus Engine',
      content:
        'Consensus reached (4/5 support, 1 conditional). Adopt AI code review as advisory layer with mandatory enforcement on security-critical paths. Measure false-positive rate and ROI at 90 days.',
      round: 2,
      timestamp: 14000,
      confidence: 0.82,
    },
  ],
};

// ---------------------------------------------------------------------------
// Agent Colors
// ---------------------------------------------------------------------------

const AGENT_COLORS: Record<string, string> = {
  'claude-sonnet': '#b794f6',
  'gpt-4o': '#68d391',
  'gemini-pro': '#63b3ed',
  'mistral-large': '#f6ad55',
  'grok-2': '#fc8181',
  system: '#00ff41',
};

const AGENT_ICONS: Record<string, string> = {
  'claude-sonnet': '\u2726',
  'gpt-4o': '\u25C6',
  'gemini-pro': '\u25C8',
  'mistral-large': '\u25B2',
  'grok-2': '\u2605',
  system: '\u2713',
};

// ---------------------------------------------------------------------------
// Components
// ---------------------------------------------------------------------------

function EventCard({
  event,
  isVisible,
  index,
}: {
  event: DemoEvent;
  isVisible: boolean;
  index: number;
}) {
  const color = AGENT_COLORS[event.agent] || '#94a3b8';
  const icon = AGENT_ICONS[event.agent] || '\u25CF';

  const typeBadge = {
    proposal: { label: 'PROPOSAL', bg: 'bg-blue-500/20', text: 'text-blue-300' },
    critique: { label: 'CRITIQUE', bg: 'bg-red-500/20', text: 'text-red-300' },
    vote: { label: 'VOTE', bg: 'bg-green-500/20', text: 'text-green-300' },
    consensus: {
      label: 'CONSENSUS',
      bg: 'bg-[var(--acid-green)]/20',
      text: 'text-[var(--acid-green)]',
    },
  }[event.type];

  return (
    <div
      className={`transition-all duration-700 ${
        isVisible ? 'opacity-100 translate-y-0' : 'opacity-0 translate-y-4'
      }`}
      style={{ transitionDelay: `${index * 50}ms` }}
    >
      <div className="p-4 border bg-[var(--surface)] mb-3" style={{ borderColor: `${color}40` }}>
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <span style={{ color }} className="text-sm">
              {icon}
            </span>
            <span className="font-theme-data text-xs" style={{ color }}>
              {event.model}
            </span>
            <span
              className={`px-1.5 py-0.5 text-[10px] font-theme-data ${typeBadge.bg} ${typeBadge.text} border border-current/20`}
            >
              {typeBadge.label}
            </span>
          </div>
          {event.confidence !== undefined && (
            <span className="text-[10px] font-theme-data text-[var(--text-muted)]">
              {Math.round(event.confidence * 100)}% confidence
            </span>
          )}
        </div>
        <p className="text-sm font-theme-data text-[var(--text)] leading-relaxed">
          {event.content}
        </p>
        {event.vote && (
          <div className="mt-2 flex items-center gap-1">
            <span
              className={`text-xs font-theme-data ${
                event.vote === 'support'
                  ? 'text-green-400'
                  : event.vote === 'oppose'
                    ? 'text-red-400'
                    : 'text-yellow-400'
              }`}
            >
              {event.vote === 'support'
                ? '\u2713 SUPPORT'
                : event.vote === 'oppose'
                  ? '\u2717 OPPOSE'
                  : '\u25CB NEUTRAL'}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function ConsensusBar({ confidence }: { confidence: number }) {
  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
          Consensus Confidence
        </span>
        <span className="text-sm font-theme-data text-[var(--acid-green)] font-bold">
          {Math.round(confidence * 100)}%
        </span>
      </div>
      <div className="h-2 bg-[var(--surface)] border border-[var(--border)] overflow-hidden">
        <div
          className="h-full bg-[var(--acid-green)] transition-all duration-1000"
          style={{ width: `${confidence * 100}%` }}
        />
      </div>
    </div>
  );
}

function AgentRoster({ agents }: { agents: string[] }) {
  return (
    <div className="flex flex-wrap gap-2 mb-6">
      {agents.map((agent) => {
        const color = AGENT_COLORS[agent] || '#94a3b8';
        const icon = AGENT_ICONS[agent] || '\u25CF';
        return (
          <div
            key={agent}
            className="flex items-center gap-1.5 px-2 py-1 border text-xs font-theme-data"
            style={{ borderColor: `${color}40`, color }}
          >
            <span>{icon}</span>
            <span>{agent}</span>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function InstantDemoPage() {
  const [visibleCount, setVisibleCount] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [showVerdict, setShowVerdict] = useState(false);
  const timerRef = useRef<NodeJS.Timeout | null>(null);
  const events = DEMO_DEBATE.events;

  const play = useCallback(() => {
    setIsPlaying(true);
    setVisibleCount(0);
    setShowVerdict(false);

    let count = 0;
    timerRef.current = setInterval(() => {
      count++;
      if (count > events.length) {
        if (timerRef.current) clearInterval(timerRef.current);
        setIsPlaying(false);
        setShowVerdict(true);
        return;
      }
      setVisibleCount(count);
    }, 1800);
  }, [events.length]);

  const showAll = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current);
    setVisibleCount(events.length);
    setIsPlaying(false);
    setShowVerdict(true);
  }, [events.length]);

  useEffect(() => {
    // Auto-play on mount after a brief pause
    const t = setTimeout(play, 800);
    return () => {
      clearTimeout(t);
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />
      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="container mx-auto px-4 py-6 max-w-4xl">
          {/* Header */}
          <div className="mb-6 text-center">
            <h1 className="text-2xl font-theme-data text-[var(--acid-green)] mb-2">
              MULTI-AGENT DECISION VETTING
            </h1>
            <p className="text-sm font-theme-data text-[var(--text-muted)] max-w-2xl mx-auto">
              Watch a cached synthetic replay of five models debating a sample decision. Live
              debates and canonical receipts are generated on the real debate path, not on this demo
              page.
            </p>
          </div>

          <div className="mb-6 p-4 bg-[var(--surface)] border border-yellow-500/30">
            <div className="text-[10px] font-theme-data text-yellow-300 uppercase mb-1">
              Synthetic Replay
            </div>
            <p className="text-xs font-theme-data text-[var(--text-muted)]">
              This page is a scripted demonstration. It does not publish a live receipt, proof link,
              or cryptographic artifact.
            </p>
          </div>

          {/* Topic */}
          <div className="mb-6 p-4 bg-[var(--surface)] border border-[var(--acid-green)]/30">
            <div className="text-[10px] font-theme-data text-[var(--acid-green)] uppercase mb-1">
              Decision Question
            </div>
            <div className="text-sm font-theme-data text-[var(--text)]">{DEMO_DEBATE.topic}</div>
          </div>

          {/* Agent Roster */}
          <AgentRoster agents={DEMO_DEBATE.agents} />

          {/* Controls */}
          <div className="flex items-center gap-3 mb-6">
            <button
              onClick={play}
              disabled={isPlaying}
              className="px-4 py-2 text-xs font-theme-data bg-[var(--acid-green)] text-[var(--bg)] hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {isPlaying ? 'PLAYING...' : '\u25B6 REPLAY'}
            </button>
            <button
              onClick={showAll}
              className="px-4 py-2 text-xs font-theme-data border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--acid-green)] hover:border-[var(--acid-green)]/50 transition-colors"
            >
              SHOW ALL
            </button>
            <span className="text-[10px] font-theme-data text-[var(--text-muted)] ml-auto">
              {visibleCount}/{events.length} events | Round{' '}
              {visibleCount > 0 ? events[Math.min(visibleCount - 1, events.length - 1)].round : 1}/
              {DEMO_DEBATE.rounds}
            </span>
          </div>

          {/* Events */}
          <div className="mb-6">
            {events.map((event, i) => (
              <EventCard
                key={`${event.agent}-${event.timestamp}`}
                event={event}
                isVisible={i < visibleCount}
                index={i}
              />
            ))}
          </div>

          {/* Consensus Bar */}
          {visibleCount > 0 && <ConsensusBar confidence={DEMO_DEBATE.confidence} />}

          {/* Verdict */}
          {showVerdict && (
            <div className="mb-8 p-4 bg-[var(--acid-green)]/5 border border-[var(--acid-green)]/40 transition-all duration-700">
              <div className="text-[10px] font-theme-data text-[var(--acid-green)] uppercase mb-2">
                Synthetic Consensus Snapshot
              </div>
              <p className="text-sm font-theme-data text-[var(--text)] leading-relaxed mb-3">
                {DEMO_DEBATE.verdict}
              </p>
              <div className="flex items-center gap-4 text-[10px] font-theme-data text-[var(--text-muted)]">
                <span>
                  Synthetic demo only. No canonical receipt or proof link is generated here.
                </span>
                <span>Agents: {DEMO_DEBATE.agents.length}</span>
                <span>Rounds: {DEMO_DEBATE.rounds}</span>
                <span>Confidence: {Math.round(DEMO_DEBATE.confidence * 100)}%</span>
              </div>
            </div>
          )}

          {/* What makes this different */}
          <div className="mb-8 grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
              <div className="text-sm font-theme-data text-purple-400 mb-2">\u2726 Multi-Model</div>
              <p className="text-xs font-theme-data text-[var(--text-muted)]">
                5 different AI models from 5 providers. No single point of failure or bias.
              </p>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
              <div className="text-sm font-theme-data text-red-400 mb-2">\u2694 Adversarial</div>
              <p className="text-xs font-theme-data text-[var(--text-muted)]">
                Agents critique each other. Weak arguments get challenged. Consensus is earned.
              </p>
            </div>
            <div className="p-4 bg-[var(--surface)] border border-[var(--border)]">
              <div className="text-sm font-theme-data text-[var(--acid-green)] mb-2">
                $ Live Proofs
              </div>
              <p className="text-xs font-theme-data text-[var(--text-muted)]">
                Live debates can publish canonical receipts and provenance. This replay is synthetic
                and does not.
              </p>
            </div>
          </div>

          {/* CTAs */}
          <div className="flex flex-wrap gap-4 justify-center mb-8">
            <Link
              href="/arena"
              className="px-6 py-3 text-sm font-theme-data bg-[var(--acid-green)] text-[var(--bg)] hover:opacity-90 transition-opacity"
            >
              START YOUR OWN DEBATE
            </Link>
            <Link
              href="/oracle"
              className="px-6 py-3 text-sm font-theme-data border border-purple-500/50 text-purple-400 hover:bg-purple-500/10 transition-colors"
            >
              ASK THE ORACLE
            </Link>
            <Link
              href="/demo/pipeline"
              className="px-6 py-3 text-sm font-theme-data border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--acid-green)] hover:border-[var(--acid-green)]/50 transition-colors"
            >
              PIPELINE DEMO
            </Link>
          </div>

          {/* Footer */}
          <footer className="text-center text-xs font-theme-data py-4 border-t border-[var(--acid-green)]/20">
            <p className="text-[var(--text-muted)]">
              {'>'} ARAGORA // DECISION INTEGRITY PLATFORM // NOT ANOTHER CHATGPT WRAPPER
            </p>
          </footer>
        </div>
      </main>
    </>
  );
}
