'use client';

import { useState, useRef, useEffect, useCallback, type FormEvent } from 'react';
import { useRouter } from 'next/navigation';
import { useTheme } from '@/context/ThemeContext';
import { RETURN_URL_KEY, PENDING_DEBATE_KEY, type DebateResponse } from '../DebateResultPreview';
import { CompactDebateResult } from './CompactDebateResult';
import { getCurrentReturnUrl, normalizeReturnUrl } from '@/utils/returnUrl';
import { useBackend, BACKENDS } from '../BackendSelector';
import { DebateInput } from '../DebateInput';
import { ConnectOpenRouterButton } from '../openrouter/ConnectOpenRouterButton';
import type {
  HeroSectionProps,
  LandingDebatePreflight,
  LandingPreparedDebateOption,
} from './types';
import { submitLandingFeedback, trackLandingEvent } from './landingTelemetry';
import { useLandingDebateProgress } from '@/hooks/useLandingDebateProgress';

const ASCII_BANNER = `    \u2584\u2584\u2584       \u2588\u2588\u2580\u2588\u2588\u2588   \u2584\u2584\u2584        \u2584\u2588\u2588\u2588\u2588  \u2592\u2588\u2588\u2588\u2588\u2588   \u2588\u2588\u2580\u2588\u2588\u2588   \u2584\u2584\u2584
   \u2592\u2588\u2588\u2588\u2588\u2584    \u2593\u2588\u2588 \u2592 \u2588\u2588\u2592\u2592\u2588\u2588\u2588\u2588\u2584     \u2588\u2588\u2592 \u2580\u2588\u2592\u2592\u2588\u2588\u2592  \u2588\u2588\u2592\u2593\u2588\u2588 \u2592 \u2588\u2588\u2592\u2592\u2588\u2588\u2588\u2588\u2584
   \u2592\u2588\u2588  \u2580\u2588\u2584  \u2593\u2588\u2588 \u2591\u2584\u2588 \u2592\u2592\u2588\u2588  \u2580\u2588\u2584  \u2592\u2588\u2588\u2591\u2584\u2584\u2584\u2591\u2592\u2588\u2588\u2591  \u2588\u2588\u2592\u2593\u2588\u2588 \u2591\u2584\u2588 \u2592\u2592\u2588\u2588  \u2580\u2588\u2584
   \u2591\u2588\u2588\u2584\u2584\u2584\u2584\u2588\u2588 \u2592\u2588\u2588\u2580\u2580\u2588\u2584  \u2591\u2588\u2588\u2584\u2584\u2584\u2584\u2588\u2588 \u2591\u2593\u2588  \u2588\u2588\u2593\u2592\u2588\u2588   \u2588\u2588\u2591\u2592\u2588\u2588\u2580\u2580\u2588\u2584  \u2591\u2588\u2588\u2584\u2584\u2584\u2584\u2588\u2588
    \u2593\u2588   \u2593\u2588\u2588\u2592\u2591\u2588\u2588\u2593 \u2592\u2588\u2588\u2592 \u2593\u2588   \u2593\u2588\u2588\u2592\u2591\u2592\u2593\u2588\u2588\u2588\u2580\u2592\u2591 \u2588\u2588\u2588\u2588\u2593\u2592\u2591\u2591\u2588\u2588\u2593 \u2592\u2588\u2588\u2592 \u2593\u2588   \u2593\u2588\u2588\u2592
    \u2592\u2592   \u2593\u2592\u2588\u2591\u2591 \u2592\u2593 \u2591\u2592\u2593\u2591 \u2592\u2592   \u2593\u2592\u2588\u2591 \u2591\u2592   \u2592 \u2591 \u2592\u2591\u2592\u2591\u2592\u2591 \u2591 \u2592\u2593 \u2591\u2592\u2593\u2591 \u2592\u2592   \u2593\u2592\u2588\u2591
     \u2592   \u2592\u2592 \u2591  \u2591\u2592 \u2591 \u2592\u2591  \u2592   \u2592\u2592 \u2591  \u2591   \u2591   \u2591 \u2592 \u2592\u2591   \u2591\u2592 \u2591 \u2592\u2591  \u2592   \u2592\u2592 \u2591
     \u2591   \u2592     \u2591\u2591   \u2591   \u2591   \u2592   \u2591 \u2591   \u2591 \u2591 \u2591 \u2591 \u2592    \u2591\u2591   \u2591   \u2591   \u2592
         \u2591  \u2591   \u2591           \u2591  \u2591      \u2591     \u2591 \u2591     \u2591           \u2591  \u2591`;

function parseRetryAfterSeconds(retryAfter: string | null): number {
  if (!retryAfter) return 60;

  const deltaSeconds = Number.parseInt(retryAfter, 10);
  if (Number.isFinite(deltaSeconds) && deltaSeconds >= 0) {
    return deltaSeconds;
  }

  const retryTime = Date.parse(retryAfter);
  if (Number.isNaN(retryTime)) return 60;

  return Math.max(1, Math.ceil((retryTime - Date.now()) / 1000));
}

function buildLandingErrorMessage(status: number, data: Record<string, unknown> | null): string {
  const message = typeof data?.message === 'string' ? data.message.trim() : '';
  const error = typeof data?.error === 'string' ? data.error.trim() : '';
  const code = typeof data?.code === 'string' ? data.code : '';
  const timeoutSeconds =
    typeof data?.timeout_seconds === 'number' ? Math.round(data.timeout_seconds) : null;

  if (code === 'request_timeout' && timeoutSeconds !== null) {
    return `Request timed out after ${timeoutSeconds}s. The landing page works best with one focused question. Shorten the prompt, pick one interpretation, or retry with a narrower scope.`;
  }

  if (code === 'landing_preview_timeout') {
    if (message) return message;
    if (timeoutSeconds !== null) {
      return `The landing preview timed out after ${timeoutSeconds}s. Shorten the prompt or pick one interpretation first.`;
    }
    return error || 'The landing preview timed out before the models returned a clean result.';
  }

  if (code === 'landing_preview_needs_clarification') {
    return (
      message ||
      error ||
      'The fast preview drifted away from your question. Tighten the wording or pick one interpretation first.'
    );
  }

  if (code === 'timeout') {
    return message || error || 'The live debate timed out. Try a shorter, more focused question.';
  }

  if (message) return message;
  if (error) return error;
  return `Something went wrong (${status}). Please try again.`;
}

/**
 * HeroSection supports two modes:
 * - Landing mode (no props): self-contained debate form with tri-theme styling
 * - Dashboard mode (with apiBase prop): full DebateInput with auth-gated functionality
 */
const DEMO_TOPIC = 'Should we migrate our monolithic app to microservices?';

export function HeroSection(props: Partial<HeroSectionProps> & Record<string, unknown> = {}) {
  const isDashboardMode = 'apiBase' in props && props.apiBase;
  const { theme } = useTheme();
  const isDark = theme === 'dark';
  const router = useRouter();

  // All hooks must be called before any early return (Rules of Hooks)
  const [question, setQuestion] = useState('');
  const [isRunning, setIsRunning] = useState(false);
  const [isDemoRunning, setIsDemoRunning] = useState(false);
  const [result, setResult] = useState<DebateResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editorNotice, setEditorNotice] = useState<string | null>(null);
  const [lastTopic, setLastTopic] = useState('');
  const [lastPreparedOption, setLastPreparedOption] = useState<LandingPreparedDebateOption | null>(
    null,
  );
  const [pendingPreflight, setPendingPreflight] = useState<LandingDebatePreflight | null>(null);
  const [debateId, setDebateId] = useState<string | null>(null);
  const [shareCopied, setShareCopied] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const resultRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  // Cycling placeholder examples
  const PLACEHOLDER_EXAMPLES = [
    'Should we use Redis or Memcached for our session cache?',
    'Is it worth switching from React to Svelte for our dashboard?',
    'Should we raise prices 15% or expand to a new market?',
    'Should I negotiate the non-compete clause in this job offer?',
    'Should we hire a CFO now or outsource to a fractional one?',
    'Is it safe to refreeze chicken that was thawed in the fridge?',
    'Should we open-source our internal tool or keep it proprietary?',
  ];
  const [placeholderIdx, setPlaceholderIdx] = useState(0);
  const cycleTimer = useRef<ReturnType<typeof setInterval>>(null);
  const cyclePlaceholder = useCallback(() => {
    setPlaceholderIdx((i) => (i + 1) % PLACEHOLDER_EXAMPLES.length);
  }, [PLACEHOLDER_EXAMPLES.length]);

  useEffect(() => {
    if (question || isRunning) return; // stop cycling when user types
    cycleTimer.current = setInterval(cyclePlaceholder, 3500);
    return () => {
      if (cycleTimer.current) clearInterval(cycleTimer.current);
    };
  }, [question, isRunning, cyclePlaceholder]);

  // Scroll to results when they appear
  useEffect(() => {
    if (result && resultRef.current) {
      resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [result]);

  const { config: backendConfig } = useBackend();
  const apiBase = isDashboardMode
    ? ((props.apiBase as string | undefined) ?? BACKENDS.production.api)
    : backendConfig.api;
  const playgroundDebateUrl =
    apiBase === '' ? '/api/v1/playground/debate/' : `${apiBase}/api/v1/playground/debate`;
  const spectateWsUrl = backendConfig.ws
    ? backendConfig.ws.replace(/\/ws\/?$/, '') + '/ws/spectate'
    : 'ws://localhost:8765/ws/spectate';
  const progress = useLandingDebateProgress({ debateId, wsUrl: spectateWsUrl, enabled: isRunning });
  const trackEvent = useCallback(
    (
      eventType: Parameters<typeof trackLandingEvent>[1],
      data: Parameters<typeof trackLandingEvent>[2] = {},
    ) => {
      trackLandingEvent(apiBase, eventType, data);
    },
    [apiBase],
  );
  const focusComposer = useCallback(() => {
    const focus = () => {
      textareaRef.current?.focus();
      textareaRef.current?.scrollIntoView?.({ behavior: 'smooth', block: 'center' });
    };
    if (typeof window !== 'undefined' && typeof window.requestAnimationFrame === 'function') {
      window.requestAnimationFrame(focus);
      return;
    }
    setTimeout(focus, 0);
  }, []);
  const handleWrongAnswer = useCallback(
    (currentResult: DebateResponse) => {
      const sourceQuestion =
        currentResult.original_question || question || lastTopic || currentResult.topic;
      const rewritten =
        Boolean(currentResult.interpreted_question) &&
        currentResult.interpreted_question !==
          (currentResult.original_question || currentResult.topic);

      setQuestion(sourceQuestion);
      setResult(null);
      setError(null);
      setLastTopic(sourceQuestion);
      setLastPreparedOption(null);
      setPendingPreflight(null);
      setEditorNotice('Edit the wording below and rerun the debate with one more specific detail.');

      submitLandingFeedback(apiBase, {
        question: sourceQuestion,
        interpreted_question: currentResult.interpreted_question || currentResult.topic,
        final_answer: currentResult.final_answer,
        result_warning: currentResult.result_warning || null,
        result_mode: currentResult.result_mode || 'full',
        debate_id: currentResult.id || null,
        verdict: currentResult.verdict || null,
        participant_count: currentResult.participants.length,
        rewritten,
      });
      trackEvent('wrong_answer_clicked', {
        result_mode: currentResult.result_mode || 'full',
        rewritten,
      });
      focusComposer();
    },
    [apiBase, focusComposer, lastTopic, question, trackEvent],
  );

  // Dashboard mode — preserves original behavior from old HeroSection
  if (isDashboardMode) {
    return (
      <div className="flex flex-col items-center justify-center px-4 py-12 sm:py-16">
        <pre className="text-[var(--accent)] text-[6px] sm:text-[7px] font-theme-data text-center mb-6 hidden sm:block leading-tight">
          {ASCII_BANNER}
        </pre>

        <h1 className="text-base sm:text-2xl font-theme-data text-center mb-4 text-text">
          What decision should AI debate for you?
        </h1>

        <p className="text-[var(--acid-cyan)] font-theme-data text-xs sm:text-sm text-center mb-10 max-w-xl">
          Ask any question. Multiple AI models will argue every angle and deliver a verdict with
          confidence scores.
        </p>

        {props.error && (
          <div className="w-full max-w-3xl mb-6 bg-warning/10 border border-warning/30 p-4 flex items-center justify-between">
            <span className="text-warning font-theme-data text-sm">
              {(props.error as string).toLowerCase().includes('authentication') ||
              (props.error as string).toLowerCase().includes('unauthorized') ? (
                <>
                  Please{' '}
                  <a href="/login" className="underline hover:text-warning/80 font-bold">
                    Log In
                  </a>{' '}
                  to start debating with real AI models.
                </>
              ) : (
                (props.error as string)
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
          <div className="w-full max-w-3xl mb-6 bg-[var(--accent)]/10 border border-[var(--accent)]/30 p-4">
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2 h-2 bg-[var(--accent)] rounded-full animate-pulse"></span>
              <span className="text-[var(--accent)] font-theme-data text-sm font-bold">
                DECISION IN PROGRESS
              </span>
            </div>
            <p className="text-text font-theme-data text-sm truncate">
              {props.activeQuestion as string}
            </p>
            <p className="text-text-muted font-theme-data text-xs mt-2">
              ID: {props.activeDebateId as string} | Events streaming via WebSocket
            </p>
          </div>
        )}

        <DebateInput
          apiBase={props.apiBase as string}
          onDebateStarted={
            props.onDebateStarted as ((debateId: string, question: string) => void) | undefined
          }
          onError={props.onError as ((err: string) => void) | undefined}
        />
      </div>
    );
  }

  // Landing mode — self-contained debate form with tri-theme styling

  function saveDebateBeforeLogin() {
    if (result) {
      sessionStorage.setItem(PENDING_DEBATE_KEY, JSON.stringify(result));
      const debateDestination = result.id
        ? `/debates/${encodeURIComponent(result.id)}`
        : getCurrentReturnUrl();
      sessionStorage.setItem(RETURN_URL_KEY, normalizeReturnUrl(debateDestination));
    }
  }

  async function executeDebate(option: LandingPreparedDebateOption) {
    const nextDebateId = `LV-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${crypto.randomUUID().slice(0, 6)}`;
    setDebateId(nextDebateId);
    progress.reset();
    setIsRunning(true);
    setError(null);
    setEditorNotice(null);
    setResult(null);
    setPendingPreflight(null);
    setLastTopic(option.originalQuestion);
    setLastPreparedOption(option);

    trackEvent('preflight_selected', {
      option_id: option.id,
      recommended: Boolean(option.recommended),
      rewritten: option.interpretedQuestion !== option.originalQuestion,
      agents: option.agents,
      rounds: option.rounds,
      question_length: option.originalQuestion.length,
    });

    const controller = new AbortController();
    abortRef.current = controller;
    const timeoutId = setTimeout(() => controller.abort(), 180_000);

    try {
      const res = await fetch(playgroundDebateUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: option.debatePrompt,
          question: option.debatePrompt,
          original_question: option.originalQuestion,
          interpreted_question: option.interpretedQuestion,
          rounds: option.rounds,
          agents: option.agents,
          source: 'landing',
          debate_id: nextDebateId,
        }),
        signal: controller.signal,
      });

      if (res.status === 429) {
        const retryAfter = parseRetryAfterSeconds(res.headers.get('Retry-After'));
        const waitText =
          retryAfter > 60 ? `${Math.ceil(retryAfter / 60)} minutes` : `${retryAfter} seconds`;
        setError(`Rate limit reached. Please try again in ${waitText}.`);
        return;
      }

      if (!res.ok) {
        const data = await res.json().catch(() => null);
        const code = typeof data?.code === 'string' ? data.code : '';
        if (code === 'landing_preview_timeout') {
          trackEvent('preview_timeout', {
            timeout_seconds:
              typeof data?.timeout_seconds === 'number' ? Math.round(data.timeout_seconds) : null,
            rewritten: option.interpretedQuestion !== option.originalQuestion,
            question_length: option.originalQuestion.length,
          });
        } else if (code === 'landing_preview_needs_clarification') {
          trackEvent('preview_clarification_requested', {
            rewritten: option.interpretedQuestion !== option.originalQuestion,
            question_length: option.originalQuestion.length,
          });
        }
        setError(buildLandingErrorMessage(res.status, data));
        return;
      }

      const data: DebateResponse = await res.json();
      const nextResult: DebateResponse = {
        ...data,
        original_question: option.originalQuestion,
        interpreted_question: option.interpretedQuestion,
        result_warning:
          data.result_warning ||
          (option.interpretedQuestion !== option.originalQuestion
            ? 'Aragora debated the focused interpretation you chose before opening the full transcript.'
            : undefined),
      };
      trackEvent('preview_rendered', {
        result_mode: nextResult.result_mode || 'full',
        rewritten: option.interpretedQuestion !== option.originalQuestion,
        participant_count: nextResult.participants.length,
        has_warning: Boolean(nextResult.result_warning),
      });
      setResult(nextResult);
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') {
        setError(
          'The debate is taking longer than expected. Please try a shorter question or try again.',
        );
        return;
      }
      setError('Could not connect to the server. Check your connection and try again.');
    } finally {
      clearTimeout(timeoutId);
      setIsRunning(false);
    }
  }

  async function runDebate(rawQuestion: string) {
    setError(null);
    setEditorNotice(null);
    setResult(null);
    setLastTopic(rawQuestion);
    setIsRunning(true);

    const fallbackOption: LandingPreparedDebateOption = {
      id: 'original',
      label: rawQuestion,
      description: rawQuestion,
      originalQuestion: rawQuestion,
      interpretedQuestion: rawQuestion,
      debatePrompt: rawQuestion,
      agents: 3,
      rounds: 2,
    };

    try {
      const assessUrl =
        apiBase === '' ? '/api/v1/playground/assess' : `${apiBase}/api/v1/playground/assess`;

      const assessRes = await fetch(assessUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: rawQuestion }),
        signal: AbortSignal.timeout(8000),
      });

      if (!assessRes.ok) {
        // Assess failed -- debate raw question directly
        setPendingPreflight(null);
        setIsRunning(false);
        void executeDebate(fallbackOption);
        return;
      }

      const assessment = await assessRes.json();

      if (assessment.type === 'confirm') {
        setPendingPreflight(assessment.preflight);
        setIsRunning(false);
        trackEvent('preflight_shown', {
          option_count: assessment.preflight.options.length,
          question_length: rawQuestion.length,
        });
        return;
      }

      // Clear -- proceed directly
      setPendingPreflight(null);
      setIsRunning(false);
      void executeDebate(assessment.option ?? fallbackOption);
    } catch {
      // Assess call failed -- debate raw question directly
      setIsRunning(false);
      setPendingPreflight(null);
      void executeDebate(fallbackOption);
    }
  }

  async function runDemoDebate() {
    const nextDebateId = `LV-${new Date().toISOString().slice(0, 10).replace(/-/g, '')}-${crypto.randomUUID().slice(0, 6)}`;
    setDebateId(nextDebateId);
    progress.reset();
    setIsDemoRunning(true);
    setIsRunning(true);
    setError(null);
    setEditorNotice(null);
    setResult(null);
    setPendingPreflight(null);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = await fetch(playgroundDebateUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: DEMO_TOPIC,
          question: DEMO_TOPIC,
          rounds: 2,
          agents: 3,
          source: 'demo',
          debate_id: nextDebateId,
        }),
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

      const data: DebateResponse = await res.json();
      if (data.id) {
        router.push(`/debate/${data.id}`);
      } else {
        // Fallback: show inline if no ID returned
        setResult(data);
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      setError('Could not connect to the server. Check your connection and try again.');
    } finally {
      setIsRunning(false);
      setIsDemoRunning(false);
    }
  }

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (question.trim()) {
      void runDebate(question.trim());
    }
  }

  return (
    <section
      className="relative px-4 flex flex-col items-center justify-center"
      style={{ minHeight: 'calc(100vh - 52px)', fontFamily: 'var(--font-landing)' }}
    >
      {/* CRT scanline overlay — dark theme only */}
      {isDark && (
        <div
          className="pointer-events-none fixed inset-0 z-[9999]"
          style={{ background: 'var(--scanline)', opacity: 0.03 }}
        />
      )}

      <div className="max-w-xl mx-auto text-center w-full">
        {/* Mobile-only brand text (ASCII banner is hidden on small screens) */}
        <div className="block sm:hidden text-center mb-4">
          <span className="text-[var(--acid-green)] font-theme-data font-bold text-2xl tracking-[0.3em]">
            ARAGORA
          </span>
        </div>

        {/* ASCII banner — dark theme only, desktop */}
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
              ref={textareaRef}
              value={question}
              onChange={(e) => {
                setQuestion(e.target.value);
                if (editorNotice) setEditorNotice(null);
              }}
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
            {isRunning && !isDemoRunning
              ? 'Agents debating...'
              : isDark
                ? '> Start Debate'
                : 'Start Debate'}
          </button>
        </form>

        {editorNotice && (
          <div
            className="mt-4 text-left"
            style={{
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-landing)',
              fontSize: '13px',
            }}
          >
            {editorNotice}
          </div>
        )}

        {pendingPreflight && !isRunning && !result && (
          <div
            className="mt-6 text-left"
            style={{
              backgroundColor: 'var(--surface)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-card)',
              padding: '20px',
            }}
          >
            <h2
              className="mb-2"
              style={{
                color: 'var(--accent)',
                fontFamily: 'var(--font-display, var(--font-landing))',
                fontSize: '18px',
                fontWeight: 600,
              }}
            >
              {pendingPreflight.title}
            </h2>
            <p
              className="mb-4"
              style={{
                color: 'var(--text)',
                fontFamily: 'var(--font-landing)',
                fontSize: '14px',
                lineHeight: 1.6,
              }}
            >
              {pendingPreflight.prompt}
            </p>
            {pendingPreflight.warning && (
              <p
                className="mb-4"
                style={{
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-landing)',
                  fontSize: '12px',
                  lineHeight: 1.5,
                }}
              >
                {pendingPreflight.warning}
              </p>
            )}
            <div className="space-y-3">
              {pendingPreflight.options.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => {
                    void executeDebate(option);
                  }}
                  className="w-full text-left transition-all hover:opacity-90 cursor-pointer"
                  style={{
                    backgroundColor: 'transparent',
                    border: '1px solid var(--border)',
                    borderRadius: 'var(--radius-button)',
                    padding: '16px',
                  }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <span
                      style={{
                        color: 'var(--text)',
                        fontFamily: 'var(--font-landing)',
                        fontSize: '14px',
                        fontWeight: 600,
                      }}
                    >
                      {option.label}
                    </span>
                    {option.recommended && (
                      <span
                        style={{
                          color: 'var(--accent)',
                          fontFamily: 'var(--font-landing)',
                          fontSize: '11px',
                          fontWeight: 700,
                          letterSpacing: '0.08em',
                          textTransform: 'uppercase',
                        }}
                      >
                        Recommended
                      </span>
                    )}
                  </div>
                  <p
                    className="mt-2"
                    style={{
                      color: 'var(--text-muted)',
                      fontFamily: 'var(--font-landing)',
                      fontSize: '13px',
                      lineHeight: 1.5,
                    }}
                  >
                    {option.description}
                  </p>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Demo CTA — runs a preset topic against the real backend, no typing needed */}
        {!isRunning && !result && !pendingPreflight && (
          <button
            onClick={runDemoDebate}
            className="w-full text-sm font-bold transition-all hover:scale-[1.01] active:scale-[0.99] cursor-pointer"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--accent)',
              fontFamily: 'var(--font-landing)',
              fontSize: '14px',
              borderRadius: 'var(--radius-button)',
              padding: '14px 32px',
              marginTop: '8px',
              border: '1px solid var(--accent)',
            }}
          >
            {isDark ? '> Try a Demo Debate' : 'Try a Demo Debate'}
          </button>
        )}
        {!isRunning && !result && !pendingPreflight && (
          <p
            className="text-center"
            style={{
              fontSize: '12px',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-landing)',
              marginTop: '8px',
              opacity: 0.6,
            }}
          >
            No account needed -- watch AI agents debate a real question
          </p>
        )}
        {!isRunning && !result && !pendingPreflight && (
          <div className="text-center mt-4">
            <ConnectOpenRouterButton compact />
          </div>
        )}

        {/* Loading state — real streaming progress */}
        {isRunning && (
          <div
            className="mt-6 max-w-xl mx-auto p-5 rounded-2xl border border-[var(--border)] bg-[var(--surface)]"
            style={{ fontFamily: 'var(--font-landing)' }}
          >
            {isDemoRunning && (
              <p
                className="text-center mb-3"
                style={{
                  fontSize: '13px',
                  color: 'var(--accent)',
                  fontFamily: 'var(--font-landing)',
                }}
              >
                Debating: &quot;{DEMO_TOPIC}&quot;
              </p>
            )}
            <div className="flex items-center gap-3 mb-3">
              <div className="w-3 h-3 rounded-full bg-[var(--accent)] animate-pulse" />
              <span className="text-sm font-medium text-[var(--text)]">
                {progress.latestEvent?.phase === 'proposing' && progress.latestEvent.agent
                  ? `${progress.latestEvent.agent} is responding...`
                  : progress.latestEvent?.phase === 'critiquing'
                    ? `Round ${progress.latestEvent.round || 1}: Critiques...`
                    : progress.latestEvent?.phase === 'voting'
                      ? 'Building consensus...'
                      : progress.latestEvent?.phase === 'consensus'
                        ? 'Consensus reached!'
                        : 'Asking agents...'}
              </span>
              <span className="ml-auto text-xs text-[var(--text-muted)]">{progress.elapsed}s</span>
            </div>
            {/* Show streaming content preview if available */}
            {progress.latestEvent?.content && (
              <div
                className="text-xs text-[var(--text-muted)] leading-relaxed mt-2 max-h-24 overflow-hidden"
                style={{ maskImage: 'linear-gradient(to bottom, black 60%, transparent)' }}
              >
                {progress.latestEvent.content.slice(0, 300)}
              </div>
            )}
          </div>
        )}

        {/* Error state */}
        {error && (
          <div
            className="mt-6 text-left max-w-xl mx-auto"
            style={{
              padding: '20px 24px',
              border: '1px solid var(--crimson)',
              borderRadius: 'var(--radius-card)',
              backgroundColor: isDark ? 'rgba(255,0,64,0.05)' : 'rgba(163,59,59,0.05)',
            }}
          >
            <p
              className="text-sm mb-4"
              style={{ color: 'var(--crimson)', fontFamily: 'var(--font-landing)' }}
            >
              {error}
            </p>
            <button
              onClick={() => {
                trackEvent('retry_clicked', {
                  has_prepared_option: Boolean(lastPreparedOption),
                  has_question: Boolean(lastTopic || question.trim()),
                });
                setError(null);
                if (lastPreparedOption) {
                  void executeDebate(lastPreparedOption);
                  return;
                }
                if (lastTopic) {
                  runDebate(lastTopic);
                  return;
                }
                if (question.trim()) runDebate(question.trim());
              }}
              className="text-xs px-5 py-2.5 transition-colors hover:opacity-80 cursor-pointer"
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
        {result && (
          <div ref={resultRef}>
            <CompactDebateResult
              result={result}
              onWrongAnswer={handleWrongAnswer}
              onShare={(debateResult) => {
                trackEvent('share_clicked', { result_mode: debateResult.result_mode || 'full' });
              }}
            />
          </div>
        )}

        {/* Post-debate CTAs */}
        {result && (
          <div className="mt-6 max-w-xl mx-auto space-y-3">
            <div
              className="rounded-2xl p-4 space-y-3"
              style={{ border: '1px solid var(--border)', backgroundColor: 'var(--surface)' }}
            >
              <div className="space-y-1">
                <p
                  className="text-xs uppercase tracking-[0.18em] font-bold"
                  style={{ color: 'var(--accent)' }}
                >
                  Save this result
                </p>
                <p
                  className="text-sm leading-relaxed"
                  style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-landing)' }}
                >
                  Keep this debate and continue from the full transcript after you sign in.
                </p>
              </div>
              <div className="flex flex-col gap-3 sm:flex-row">
                <button
                  type="button"
                  onClick={() => {
                    saveDebateBeforeLogin();
                    router.push('/login');
                  }}
                  className="flex-1 text-sm font-bold font-mono py-3 transition-all hover:opacity-90 cursor-pointer"
                  style={{
                    backgroundColor: 'transparent',
                    color: 'var(--accent)',
                    border: '1px solid var(--accent)',
                    borderRadius: 'var(--radius-button)',
                  }}
                >
                  {isDark ? '> Log In To Save' : 'Log In To Save'}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    saveDebateBeforeLogin();
                    router.push('/signup');
                  }}
                  className="flex-1 text-sm font-bold font-mono py-3 transition-all hover:opacity-90 cursor-pointer"
                  style={{
                    backgroundColor: 'var(--accent)',
                    color: 'var(--bg)',
                    borderRadius: 'var(--radius-button)',
                    boxShadow: isDark
                      ? '0 0 20px var(--accent-glow)'
                      : '0 2px 8px var(--accent-glow)',
                  }}
                >
                  {isDark ? '> Sign Up Free' : 'Sign Up Free'}
                </button>
              </div>
            </div>
            {/* Primary: View full debate page */}
            {result.id && (
              <button
                type="button"
                onClick={() => {
                  trackEvent('open_full_debate_clicked', {
                    result_mode: result.result_mode || 'full',
                    surface: 'quick_read',
                  });
                  router.push(`/debate/${result.id}`);
                }}
                className="w-full text-sm font-bold font-theme-data py-3 transition-all hover:opacity-90 cursor-pointer"
                style={{
                  backgroundColor: 'var(--accent)',
                  color: 'var(--bg)',
                  borderRadius: 'var(--radius-button)',
                  boxShadow: isDark
                    ? '0 0 20px var(--accent-glow)'
                    : '0 2px 8px var(--accent-glow)',
                }}
              >
                {isDark ? '> View Full Debate' : 'View Full Debate'}
              </button>
            )}
            {/* Secondary row: Try Another + Share */}
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => {
                  setResult(null);
                  setQuestion('');
                  setError(null);
                  setEditorNotice(null);
                  setPendingPreflight(null);
                  setLastPreparedOption(null);
                  setLastTopic('');
                }}
                className="flex-1 text-sm font-bold font-theme-data py-3 transition-all hover:opacity-90 cursor-pointer"
                style={{
                  backgroundColor: result.id ? 'transparent' : 'var(--accent)',
                  color: result.id ? 'var(--accent)' : 'var(--bg)',
                  border: result.id ? '1px solid var(--accent)' : 'none',
                  borderRadius: 'var(--radius-button)',
                }}
              >
                Try Another
              </button>
              <button
                type="button"
                onClick={async () => {
                  const shareUrl = result.id
                    ? `${window.location.origin}/debate/${result.id}`
                    : window.location.href;
                  try {
                    await navigator.clipboard.writeText(shareUrl);
                  } catch {
                    const ta = document.createElement('textarea');
                    ta.value = shareUrl;
                    ta.style.position = 'fixed';
                    ta.style.opacity = '0';
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                  }
                  setShareCopied(true);
                  setTimeout(() => setShareCopied(false), 2000);
                  trackEvent('share_clicked', { result_mode: result.result_mode || 'full' });
                }}
                className="flex-1 text-sm font-bold font-theme-data py-3 transition-all hover:opacity-80 cursor-pointer"
                style={{
                  backgroundColor: 'transparent',
                  color: 'var(--accent)',
                  border: '1px solid var(--accent)',
                  borderRadius: 'var(--radius-button)',
                  opacity: shareCopied ? 0.7 : 1,
                }}
              >
                {shareCopied ? 'Copied!' : 'Share'}
              </button>
            </div>
          </div>
        )}
      </div>
    </section>
  );
}
