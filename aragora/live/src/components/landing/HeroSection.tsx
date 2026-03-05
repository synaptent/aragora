'use client';

import { useState, useRef, useEffect, useCallback, type FormEvent } from 'react';
import { useTheme } from '@/context/ThemeContext';
import { DebateResultPreview, RETURN_URL_KEY, PENDING_DEBATE_KEY, type DebateResponse } from '../DebateResultPreview';
import { getCurrentReturnUrl, normalizeReturnUrl } from '@/utils/returnUrl';
import { useBackend, BACKENDS } from '../BackendSelector';
import { DebateInput } from '../DebateInput';
import type { HeroSectionProps } from './types';

const ASCII_BANNER = `    \u2584\u2584\u2584       \u2588\u2588\u2580\u2588\u2588\u2588   \u2584\u2584\u2584        \u2584\u2588\u2588\u2588\u2588  \u2592\u2588\u2588\u2588\u2588\u2588   \u2588\u2588\u2580\u2588\u2588\u2588   \u2584\u2584\u2584
   \u2592\u2588\u2588\u2588\u2588\u2584    \u2593\u2588\u2588 \u2592 \u2588\u2588\u2592\u2592\u2588\u2588\u2588\u2588\u2584     \u2588\u2588\u2592 \u2580\u2588\u2592\u2592\u2588\u2588\u2592  \u2588\u2588\u2592\u2593\u2588\u2588 \u2592 \u2588\u2588\u2592\u2592\u2588\u2588\u2588\u2588\u2584
   \u2592\u2588\u2588  \u2580\u2588\u2584  \u2593\u2588\u2588 \u2591\u2584\u2588 \u2592\u2592\u2588\u2588  \u2580\u2588\u2584  \u2592\u2588\u2588\u2591\u2584\u2584\u2584\u2591\u2592\u2588\u2588\u2591  \u2588\u2588\u2592\u2593\u2588\u2588 \u2591\u2584\u2588 \u2592\u2592\u2588\u2588  \u2580\u2588\u2584
   \u2591\u2588\u2588\u2584\u2584\u2584\u2584\u2588\u2588 \u2592\u2588\u2588\u2580\u2580\u2588\u2584  \u2591\u2588\u2588\u2584\u2584\u2584\u2584\u2588\u2588 \u2591\u2593\u2588  \u2588\u2588\u2593\u2592\u2588\u2588   \u2588\u2588\u2591\u2592\u2588\u2588\u2580\u2580\u2588\u2584  \u2591\u2588\u2588\u2584\u2584\u2584\u2584\u2588\u2588
    \u2593\u2588   \u2593\u2588\u2588\u2592\u2591\u2588\u2588\u2593 \u2592\u2588\u2588\u2592 \u2593\u2588   \u2593\u2588\u2588\u2592\u2591\u2592\u2593\u2588\u2588\u2588\u2580\u2592\u2591 \u2588\u2588\u2588\u2588\u2593\u2592\u2591\u2591\u2588\u2588\u2593 \u2592\u2588\u2588\u2592 \u2593\u2588   \u2593\u2588\u2588\u2592
    \u2592\u2592   \u2593\u2592\u2588\u2591\u2591 \u2592\u2593 \u2591\u2592\u2593\u2591 \u2592\u2592   \u2593\u2592\u2588\u2591 \u2591\u2592   \u2592 \u2591 \u2592\u2591\u2592\u2591\u2592\u2591 \u2591 \u2592\u2593 \u2591\u2592\u2593\u2591 \u2592\u2592   \u2593\u2592\u2588\u2591
     \u2592   \u2592\u2592 \u2591  \u2591\u2592 \u2591 \u2592\u2591  \u2592   \u2592\u2592 \u2591  \u2591   \u2591   \u2591 \u2592 \u2592\u2591   \u2591\u2592 \u2591 \u2592\u2591  \u2592   \u2592\u2592 \u2591
     \u2591   \u2592     \u2591\u2591   \u2591   \u2591   \u2592   \u2591 \u2591   \u2591 \u2591 \u2591 \u2591 \u2592    \u2591\u2591   \u2591   \u2591   \u2592
         \u2591  \u2591   \u2591           \u2591  \u2591      \u2591     \u2591 \u2591     \u2591           \u2591  \u2591`;

const DEBATE_PHASES = [
  { label: 'Assembling panel', agents: ['Claude', 'GPT-4', 'Gemini'], duration: 3000 },
  { label: 'Opening arguments', agents: ['Claude', 'GPT-4', 'Gemini'], duration: 5000 },
  { label: 'Cross-examination', agents: ['GPT-4', 'Claude'], duration: 4000 },
  { label: 'Building consensus', agents: ['Gemini', 'Claude', 'GPT-4'], duration: 4000 },
  { label: 'Rendering verdict', agents: [], duration: 3000 },
];

const AGENT_DOT_COLORS: Record<string, string> = {
  'Claude': 'var(--acid-cyan, #00e5ff)',
  'GPT-4': 'var(--acid-green, #39ff14)',
  'Gemini': 'var(--acid-magenta, #ff00ff)',
  'Mistral': 'var(--acid-yellow, #ffd700)',
};

/**
 * HeroSection supports two modes:
 * - Landing mode (no props): self-contained debate form with tri-theme styling
 * - Dashboard mode (with apiBase prop): full DebateInput with auth-gated functionality
 */
export function HeroSection(props: Partial<HeroSectionProps> & Record<string, unknown> = {}) {
  const isDashboardMode = 'apiBase' in props && props.apiBase;
  const { theme } = useTheme();
  const isDark = theme === 'dark';

  // All hooks must be called before any early return (Rules of Hooks)
  const [question, setQuestion] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<DebateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [phaseIndex, setPhaseIndex] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const startTimeRef = useRef<number>(0);

  // Phase progression during debate
  useEffect(() => {
    if (!isRunning) {
      setPhaseIndex(0);
      setElapsed(0);
      return;
    }
    startTimeRef.current = Date.now();
    let cumulative = 0;
    const timeouts: ReturnType<typeof setTimeout>[] = [];
    DEBATE_PHASES.forEach((phase, i) => {
      if (i > 0) {
        cumulative += DEBATE_PHASES[i - 1].duration;
        timeouts.push(setTimeout(() => setPhaseIndex(i), cumulative));
      }
    });
    const ticker = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);
    return () => {
      timeouts.forEach(clearTimeout);
      clearInterval(ticker);
    };
  }, [isRunning]);
  // Cycling placeholder examples
  const PLACEHOLDER_EXAMPLES = [
    'Should we migrate to microservices or keep our monolith?',
    'Is this contract clause a liability risk?',
    'Should we raise prices 15% or expand to a new market?',
    'What are the security risks in our OAuth implementation?',
    'Should we build or buy our analytics platform?',
  ];
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const cycleTimer = useRef<ReturnType<typeof setInterval>>(null);
  const cyclePlaceholder = useCallback(() => {
    setPlaceholderIdx((i) => (i + 1) % PLACEHOLDER_EXAMPLES.length);
  }, [PLACEHOLDER_EXAMPLES.length]);

  useEffect(() => {
    if (question || isRunning) return; // stop cycling when user types
    cycleTimer.current = setInterval(cyclePlaceholder, 3500);
    return () => { if (cycleTimer.current) clearInterval(cycleTimer.current); };
  }, [question, isRunning, cyclePlaceholder]);

  const { config: backendConfig } = useBackend();
  const apiBase = (isDashboardMode ? props.apiBase as string : backendConfig.api) || BACKENDS.production.api;

  // Dashboard mode — preserves original behavior from old HeroSection
  if (isDashboardMode) {
    return (
      <div className="flex flex-col items-center justify-center px-4 py-12 sm:py-16">
        <pre className="text-acid-green text-[6px] sm:text-[7px] font-mono text-center mb-6 hidden sm:block leading-tight">
          {ASCII_BANNER}
        </pre>

        <h1 className="text-base sm:text-2xl font-mono text-center mb-4 text-text">
          What decision should AI debate for you?
        </h1>

        <p className="text-acid-cyan font-mono text-xs sm:text-sm text-center mb-10 max-w-xl">
          Ask any question. Multiple AI models will argue every angle and deliver a verdict with confidence scores.
        </p>

        {props.error && (
          <div className="w-full max-w-3xl mb-6 bg-warning/10 border border-warning/30 p-4 flex items-center justify-between">
            <span className="text-warning font-mono text-sm">
              {(props.error as string).toLowerCase().includes('authentication') || (props.error as string).toLowerCase().includes('unauthorized') ? (
                <>
                  Please{' '}
                  <a href="/login" className="underline hover:text-warning/80 font-bold">
                    Log In
                  </a>
                  {' '}to start debating with real AI models.
                </>
              ) : (
                props.error as string
              )}
            </span>
            <button
              onClick={props.onDismissError as (() => void) | undefined}
              className="text-warning hover:text-warning/80"
              aria-label="Dismiss error"
            >
              x
            </button>
          </div>
        )}

        {props.activeDebateId && (
          <div className="w-full max-w-3xl mb-6 bg-acid-green/10 border border-acid-green/30 p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2 h-2 bg-acid-green rounded-full animate-pulse"></span>
              <span className="text-acid-green font-mono text-sm font-bold">DECISION IN PROGRESS</span>
            </div>
            <p className="text-text font-mono text-sm truncate">{props.activeQuestion as string}</p>
            <p className="text-text-muted font-mono text-xs mt-2">
              ID: {props.activeDebateId as string} | Events streaming via WebSocket
            </p>
          </div>
        )}

        <DebateInput
          apiBase={props.apiBase as string}
          onDebateStarted={props.onDebateStarted as ((debateId: string, question: string) => void) | undefined}
          onError={props.onError as ((err: string) => void) | undefined}
        />
      </div>
    );
  }

  // Landing mode — self-contained debate form with tri-theme styling

  function saveDebateBeforeLogin() {
    if (result) {
      sessionStorage.setItem(PENDING_DEBATE_KEY, JSON.stringify(result));
      const debateDestination = result.id ? `/debates/${encodeURIComponent(result.id)}` : getCurrentReturnUrl();
      sessionStorage.setItem(RETURN_URL_KEY, normalizeReturnUrl(debateDestination));
    }
  }

  async function runDebate(topic: string) {
    setIsRunning(true);
    setError(null);
    setResult(null);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(`${apiBase}/api/v1/playground/debate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic, question: topic, rounds: 2, agents: 3, source: 'landing' }),
        signal: controller.signal,
      });

      if (res.status === 429) {
        const data = await res.json().catch(() => null);
        const retryAfter = data?.retry_after || 60;
        setError(`Rate limit reached. Please try again in ${retryAfter} seconds.`);
        return;
      }

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        setError(data?.error || 'Something went wrong. Please try again.');
        return;
      }

      setResult(await res.json());
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      setError('Could not connect to the server. Check your connection and try again.');
    } finally {
      setIsRunning(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (question.trim()) {
      runDebate(question.trim());
    }
  }

  // Keep the saveDebateBeforeLogin available for external use (not currently wired but preserving)
  void saveDebateBeforeLogin;

  return (
    <section
      className="relative px-4 flex flex-col items-center justify-center"
      style={{
        minHeight: 'calc(100vh - 52px)',
        fontFamily: 'var(--font-landing)',
      }}
    >
      {/* CRT scanline overlay — dark theme only */}
      {isDark && (
        <div
          className="pointer-events-none fixed inset-0 z-[9999]"
          style={{
            background: 'var(--scanline)',
            opacity: 0.03,
          }}
        />
      )}

      <div className="max-w-xl mx-auto text-center w-full">
        {/* ASCII banner — dark theme only */}
        {isDark && (
          <pre
            className="text-[6px] sm:text-[7px] text-center mb-10 hidden sm:block leading-tight"
            style={{ color: 'var(--accent)', fontFamily: "'JetBrains Mono', monospace" }}
          >
            {ASCII_BANNER}
          </pre>
        )}

        {/* Headline */}
        <h1
          className="leading-tight"
          style={{
            fontSize: isDark ? '38px' : '44px',
            fontWeight: isDark ? 700 : 400,
            color: 'var(--text)',
            fontFamily: 'var(--font-display, var(--font-landing))',
            marginBottom: '16px',
            letterSpacing: isDark ? '0' : '-0.02em',
          }}
        >
          Don&apos;t trust one AI.
          <br />
          <span
            style={{
              color: 'var(--accent)',
              textShadow: isDark ? '0 0 10px var(--accent), 0 0 20px var(--accent)' : 'none',
            }}
          >
            Make them compete.
          </span>
        </h1>

        {/* Subtitle */}
        <p
          className="mx-auto leading-relaxed"
          style={{
            fontSize: '14px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '48px',
          }}
        >
          Multiple AI models debate your question and deliver an audit-ready verdict.
        </p>

        {/* Debate input form */}
        <form onSubmit={handleSubmit} className="text-left">
          <div className="relative">
            {isDark && (
              <span
                className="absolute left-4 top-5 text-base select-none"
                style={{ color: 'var(--accent)', fontFamily: "'JetBrains Mono', monospace" }}
              >
                &gt;
              </span>
            )}
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder={PLACEHOLDER_EXAMPLES[placeholderIdx]}
              disabled={isRunning}
              rows={3}
              className="w-full placeholder:opacity-40 focus:outline-none transition-all resize-none disabled:opacity-50"
              style={{
                backgroundColor: 'var(--surface)',
                border: '2px solid var(--border)',
                color: 'var(--text)',
                fontFamily: 'var(--font-landing)',
                fontSize: '16px',
                lineHeight: '1.6',
                borderRadius: 'var(--radius-input)',
                padding: isDark ? '18px 20px 18px 36px' : '18px 20px',
                boxShadow: isDark ? 'none' : 'var(--shadow-card-hover)',
              }}
              onFocus={(e) => {
                e.currentTarget.style.borderColor = 'var(--accent)';
                e.currentTarget.style.boxShadow = isDark
                  ? '0 0 0 1px var(--accent), 0 0 20px var(--accent-glow)'
                  : '0 0 0 3px var(--accent-glow), var(--shadow-card-hover)';
              }}
              onBlur={(e) => {
                e.currentTarget.style.borderColor = 'var(--border)';
                e.currentTarget.style.boxShadow = isDark ? 'none' : 'var(--shadow-card-hover)';
              }}
            />
          </div>
          <button
            type="submit"
            disabled={isRunning || !question.trim()}
            className="w-full text-sm font-bold transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
            style={{
              backgroundColor: 'var(--accent)',
              color: 'var(--bg)',
              fontFamily: 'var(--font-landing)',
              fontSize: '15px',
              borderRadius: 'var(--radius-button)',
              padding: '16px 32px',
              marginTop: '12px',
              boxShadow: isDark ? '0 0 20px var(--accent-glow)' : '0 2px 8px var(--accent-glow)',
            }}
          >
            {isRunning ? 'Agents debating...' : isDark ? '> Start Debate' : 'Start Debate'}
          </button>
        </form>

        {/* Secondary CTA — no account needed */}
        {!isRunning && !result && (
          <div className="mt-3 text-center">
            <a
              href="/demo"
              className="inline-flex items-center text-sm text-gray-400 hover:text-white transition-colors"
            >
              Try a live debate — no account needed →
            </a>
          </div>
        )}

        {/* Loading state — phased progress */}
        {isRunning && (
          <div className="mt-8 max-w-xl mx-auto">
            <div
              className="p-5 text-left"
              style={{
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-card, 8px)',
                backgroundColor: 'var(--surface)',
              }}
            >
              {/* Phase steps */}
              <div className="space-y-3 mb-4">
                {DEBATE_PHASES.map((phase, i) => {
                  const isActive = i === phaseIndex;
                  const isDone = i < phaseIndex;
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 transition-opacity duration-300"
                      style={{ opacity: isDone ? 0.4 : isActive ? 1 : 0.25 }}
                    >
                      {/* Step indicator */}
                      <div
                        className="w-6 h-6 flex items-center justify-center shrink-0 text-xs font-bold"
                        style={{
                          borderRadius: '50%',
                          border: `2px solid ${isActive ? 'var(--accent)' : isDone ? 'var(--accent)' : 'var(--border)'}`,
                          color: isActive || isDone ? 'var(--accent)' : 'var(--text-muted)',
                          backgroundColor: isDone ? 'var(--accent)' : 'transparent',
                          ...(isDone ? { color: 'var(--bg)' } : {}),
                          fontFamily: 'var(--font-landing)',
                        }}
                      >
                        {isDone ? '\u2713' : i + 1}
                      </div>
                      {/* Label + agents */}
                      <div className="flex-1 min-w-0">
                        <span
                          className="text-sm font-medium"
                          style={{
                            color: isActive ? 'var(--text)' : 'var(--text-muted)',
                            fontFamily: 'var(--font-landing)',
                          }}
                        >
                          {phase.label}
                        </span>
                        {isActive && phase.agents.length > 0 && (
                          <div className="flex items-center gap-2 mt-1">
                            {phase.agents.map((agent) => (
                              <span
                                key={agent}
                                className="flex items-center gap-1 text-xs"
                                style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-landing)' }}
                              >
                                <span
                                  className="w-2 h-2 rounded-full inline-block animate-pulse"
                                  style={{ backgroundColor: AGENT_DOT_COLORS[agent] || 'var(--accent)' }}
                                />
                                {agent}
                              </span>
                            ))}
                          </div>
                        )}
                      </div>
                      {/* Active spinner */}
                      {isActive && (
                        <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none" style={{ color: 'var(--accent)' }}>
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                      )}
                    </div>
                  );
                })}
              </div>
              {/* Progress bar */}
              <div
                className="h-1 rounded-full overflow-hidden"
                style={{ backgroundColor: 'var(--border)' }}
              >
                <div
                  className="h-full rounded-full transition-all duration-1000 ease-out"
                  style={{
                    backgroundColor: 'var(--accent)',
                    width: `${Math.min(((phaseIndex + 1) / DEBATE_PHASES.length) * 100, 100)}%`,
                    boxShadow: isDark ? '0 0 8px var(--accent-glow)' : 'none',
                  }}
                />
              </div>
              <div
                className="flex justify-between mt-2 text-xs"
                style={{ color: 'var(--text-muted)', opacity: 0.6, fontFamily: 'var(--font-landing)' }}
              >
                <span>{elapsed}s elapsed</span>
                <span>~15s remaining</span>
              </div>
            </div>
          </div>
        )}

        {/* Error state */}
        {error && (
          <div
            className="p-4 mt-6 text-left max-w-xl mx-auto"
            style={{
              border: '1px solid var(--crimson)',
              borderRadius: 'var(--radius-card)',
              backgroundColor: isDark ? 'rgba(255,0,64,0.05)' : 'rgba(163,59,59,0.05)',
            }}
          >
            <p className="text-sm mb-3" style={{ color: 'var(--crimson)', fontFamily: 'var(--font-landing)' }}>
              {error}
            </p>
            <button
              onClick={() => { setError(null); if (question.trim()) runDebate(question.trim()); }}
              className="text-xs px-4 py-2 transition-colors hover:opacity-80 cursor-pointer"
              style={{
                fontFamily: 'var(--font-landing)',
                border: '1px solid var(--crimson)',
                borderRadius: 'var(--radius-button)',
                color: 'var(--crimson)',
                backgroundColor: 'transparent',
              }}
            >
              Try again
            </button>
          </div>
        )}

        {/* Result preview */}
        {result && <DebateResultPreview result={result} />}
      </div>
    </section>
  );
}
