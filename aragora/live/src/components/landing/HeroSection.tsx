'use client';

import { useState, useRef, type FormEvent } from 'react';
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

const PROGRESS_MESSAGES = [
  'Assembling analyst panel...',
  'Agents debating your question...',
  'Analyzing arguments...',
  'Building consensus...',
  'Generating verdict...',
];

const EXAMPLE_TOPICS = [
  'Should we build or buy our analytics platform?',
  'Is remote work better for a 50-person company?',
  'Should we adopt microservices or keep our monolith?',
];

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
  const [progressMsg, setProgressMsg] = useState(PROGRESS_MESSAGES[0]);
  const abortRef = useRef<AbortController | null>(null);
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

    let progressIdx = 0;
    const progressInterval = setInterval(() => {
      progressIdx = (progressIdx + 1) % PROGRESS_MESSAGES.length;
      setProgressMsg(PROGRESS_MESSAGES[progressIdx]);
    }, 4000);

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
      clearInterval(progressInterval);
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

      <div className="max-w-2xl mx-auto text-center w-full">
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
            fontWeight: isDark ? 700 : 600,
            color: 'var(--text)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '16px',
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

        {/* Subtitle — short, one line on desktop */}
        <p
          className="max-w-2xl mx-auto leading-relaxed"
          style={{
            fontSize: '14px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-landing)',
            marginBottom: '48px',
          }}
        >
          Multiple AI models debate your question and deliver an audit-ready verdict.
        </p>

        {/* Debate input form — THE CENTERPIECE */}
        <form onSubmit={handleSubmit} className="text-left max-w-xl mx-auto">
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
              placeholder="What decision are you facing?"
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

        {/* Example topic chips — reduce blank-textarea friction */}
        {!isRunning && !result && (
          <div className="flex flex-wrap justify-center gap-2 mt-6 max-w-xl mx-auto">
            {EXAMPLE_TOPICS.map((topic) => (
              <button
                key={topic}
                type="button"
                onClick={() => { setQuestion(topic); }}
                className="text-xs transition-all hover:scale-[1.02] cursor-pointer"
                style={{
                  fontFamily: 'var(--font-landing)',
                  color: 'var(--text-muted)',
                  backgroundColor: 'var(--surface)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-button)',
                  padding: '8px 14px',
                  opacity: 0.7,
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.borderColor = 'var(--accent)';
                  e.currentTarget.style.color = 'var(--accent)';
                  e.currentTarget.style.opacity = '1';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.borderColor = 'var(--border)';
                  e.currentTarget.style.color = 'var(--text-muted)';
                  e.currentTarget.style.opacity = '0.7';
                }}
              >
                {isDark ? `> ${topic}` : topic}
              </button>
            ))}
          </div>
        )}

                {/* Loading state */}
        {isRunning && (
          <div className="flex flex-col items-center py-8 gap-3">
            <div className="flex items-center gap-3" style={{ color: 'var(--accent)' }}>
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              <span className="text-sm" style={{ fontFamily: 'var(--font-landing)' }}>{progressMsg}</span>
            </div>
            <span
              className="text-xs"
              style={{ color: 'var(--text-muted)', opacity: 0.6, fontFamily: 'var(--font-landing)' }}
            >
              Usually takes 10-20 seconds
            </span>
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
