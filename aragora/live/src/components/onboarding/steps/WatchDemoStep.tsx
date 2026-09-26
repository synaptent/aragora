'use client';

import { useState, useEffect } from 'react';
import { useOnboardingStore } from '@/store/onboardingStore';

interface DemoMessage {
  agent: string;
  model: string;
  role: 'propose' | 'critique' | 'revise';
  content: string;
  delay: number;
}

const DEMO_MESSAGES: DemoMessage[] = [
  {
    agent: 'Claude',
    model: 'anthropic',
    role: 'propose',
    content:
      'I recommend a modular monolith as the starting architecture. It gives you clean boundaries without the operational overhead of distributed services. You can extract microservices later when individual modules need independent scaling.',
    delay: 0,
  },
  {
    agent: 'GPT-4',
    model: 'openai',
    role: 'critique',
    content:
      'The modular monolith approach has merit, but underestimates the team scaling challenge. With 4+ squads working on the same deployable, merge conflicts and release coordination become bottlenecks. A service-oriented split along domain boundaries would better support parallel development.',
    delay: 1500,
  },
  {
    agent: 'Gemini',
    model: 'google',
    role: 'revise',
    content:
      'Both perspectives have validity. The data suggests starting monolithic and splitting at the domain boundary where team contention emerges first. This gives you a concrete, evidence-based trigger for extraction rather than speculative pre-optimization. Confidence: 82%.',
    delay: 3000,
  },
];

const AGENT_COLORS: Record<string, string> = {
  anthropic: 'var(--acid-green)',
  openai: 'var(--acid-cyan)',
  google: 'var(--acid-purple, #a855f7)',
};

const ROLE_LABELS: Record<string, string> = {
  propose: 'PROPOSAL',
  critique: 'CRITIQUE',
  revise: 'SYNTHESIS',
};

export function WatchDemoStep() {
  const setDemoWatched = useOnboardingStore((s) => s.setDemoWatched);
  const [visibleMessages, setVisibleMessages] = useState<number>(0);
  const [showConsensus, setShowConsensus] = useState(false);

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];

    DEMO_MESSAGES.forEach((msg, i) => {
      timers.push(
        setTimeout(() => {
          setVisibleMessages(i + 1);
        }, msg.delay),
      );
    });

    // Show consensus after all messages
    timers.push(
      setTimeout(() => {
        setShowConsensus(true);
        setDemoWatched(true);
      }, 4500),
    );

    return () => timers.forEach(clearTimeout);
  }, [setDemoWatched]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-theme-data text-[var(--acid-green)] mb-2">
          Watch a Demo Debate
        </h2>
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          See how multiple AI agents collaborate to stress-test a decision.
        </p>
      </div>

      {/* Mini debate topic */}
      <div className="border border-[var(--border)] bg-[var(--surface)] p-3">
        <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-1">
          Topic
        </div>
        <p className="text-sm font-theme-data text-[var(--text)]">
          Should we use microservices or a monolith for our new product?
        </p>
      </div>

      {/* Messages */}
      <div className="space-y-3">
        {DEMO_MESSAGES.slice(0, visibleMessages).map((msg, i) => (
          <div
            key={i}
            className="border border-[var(--border)] bg-[var(--surface)] p-4 animate-in fade-in slide-in-from-bottom-2 duration-300"
          >
            <div className="flex items-center gap-2 mb-2">
              <span
                className="w-6 h-6 flex items-center justify-center text-[10px] font-theme-data font-bold"
                style={{
                  backgroundColor: `color-mix(in srgb, ${AGENT_COLORS[msg.model]} 20%, transparent)`,
                  color: AGENT_COLORS[msg.model],
                }}
              >
                {msg.agent[0]}
              </span>
              <span className="text-sm font-theme-data font-bold text-[var(--text)]">
                {msg.agent}
              </span>
              <span
                className="text-[10px] font-theme-data px-1.5 py-0.5 border"
                style={{
                  borderColor: `color-mix(in srgb, ${AGENT_COLORS[msg.model]} 30%, transparent)`,
                  color: AGENT_COLORS[msg.model],
                }}
              >
                {ROLE_LABELS[msg.role]}
              </span>
            </div>
            <p className="text-xs font-theme-data text-[var(--text-muted)] leading-relaxed">
              {msg.content}
            </p>
          </div>
        ))}

        {/* Loading indicator while messages are appearing */}
        {visibleMessages < DEMO_MESSAGES.length && (
          <div className="flex items-center gap-3 py-2 px-4">
            <div className="w-4 h-4 border-2 border-[var(--acid-green)]/30 border-t-[var(--acid-green)] rounded-full animate-spin" />
            <span className="text-xs font-theme-data text-[var(--text-muted)]">
              Agent is responding...
            </span>
          </div>
        )}
      </div>

      {/* Consensus result */}
      {showConsensus && (
        <div className="border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/5 p-4 animate-in fade-in duration-500">
          <div className="flex items-center gap-2 mb-2">
            <span className="text-[var(--acid-green)] font-theme-data font-bold text-sm">
              CONSENSUS REACHED
            </span>
            <span className="text-xs font-theme-data px-2 py-0.5 border border-green-500/30 text-green-400 bg-green-500/10">
              82% CONFIDENCE
            </span>
          </div>
          <p className="text-xs font-theme-data text-[var(--text)] leading-relaxed">
            Start with a modular monolith. Extract services when team contention provides a concrete
            trigger. This balances development velocity with future scalability.
          </p>
          <p className="text-xs font-theme-data text-[var(--acid-cyan)] mt-2">
            This is how Aragora turns complex decisions into clear, defensible outcomes.
          </p>
        </div>
      )}
    </div>
  );
}
