'use client';

import { useState, useRef, useEffect, Suspense } from 'react';
import { useSearchParams } from 'next/navigation';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { TeaserResult } from '@/components/try/TeaserResult';
import { API_BASE_URL } from '@/config';

const EXAMPLE_QUESTIONS = [
  'Should we migrate our monolithic app to microservices?',
  'Is it better to build our own auth system or use Auth0?',
  'Should we switch from REST to GraphQL for our mobile API?',
  'Should we raise prices 15% or expand to a new market first?',
  'Build vs buy: should we develop our own data warehouse?',
];

const FOLLOW_UP_SUGGESTIONS = [
  'What are the main risks if we get this wrong?',
  'How should we phase the implementation over 6 months?',
  'What metrics should we track to evaluate success?',
  'Which team should own this decision?',
  'What would change your mind on this?',
];

// Stepped progress messages paired with rough time windows
const PROGRESS_STEPS = [
  { label: 'Assembling agent panel', subtext: 'Selecting specialists for your question' },
  { label: 'Strategic Analyst weighing in', subtext: 'Evaluating market dynamics and tradeoffs' },
  { label: 'Devil\'s Advocate probing risks', subtext: 'Stress-testing assumptions and blind spots' },
  { label: 'Implementation Expert reviewing', subtext: 'Assessing practical feasibility' },
  { label: 'Building consensus', subtext: 'Agents voting on the strongest position' },
  { label: 'Generating verdict', subtext: 'Synthesizing into a decision receipt' },
];

interface DebateResult {
  verdict: string;
  confidence: number;
  explanation: string;
  debateId?: string;
  topic?: string;
  participants?: string[];
  proposals?: Record<string, string>;
  receiptHash?: string;
}

function TryPageInner() {
  const searchParams = useSearchParams();
  const [question, setQuestion] = useState(searchParams.get('topic') || '');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [result, setResult] = useState<DebateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progressStep, setProgressStep] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const abortRef = useRef<AbortController | null>(null);
  const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
      if (elapsedIntervalRef.current) clearInterval(elapsedIntervalRef.current);
    };
  }, []);

  const handleAnalyze = async () => {
    if (!question.trim() || question.length < 10) {
      setError('Question must be at least 10 characters.');
      return;
    }

    setIsAnalyzing(true);
    setError(null);
    setResult(null);
    setProgressStep(0);
    setElapsed(0);

    abortRef.current = new AbortController();
    startTimeRef.current = Date.now();

    // Step through progress at staggered intervals to convey activity
    const STEP_DELAYS = [0, 3000, 6500, 10000, 14000, 18000];
    const stepTimers: ReturnType<typeof setTimeout>[] = [];
    STEP_DELAYS.forEach((delay, i) => {
      stepTimers.push(setTimeout(() => setProgressStep(i), delay));
    });

    // Elapsed time ticker
    elapsedIntervalRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);

    const clearTimers = () => {
      stepTimers.forEach(clearTimeout);
      if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
      if (elapsedIntervalRef.current) clearInterval(elapsedIntervalRef.current);
    };

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/playground/debate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.trim(), source: 'landing' }),
        signal: abortRef.current.signal,
      });

      clearTimers();

      if (response.status === 429) {
        const retryAfter = response.headers.get('Retry-After');
        const waitSec = retryAfter ? parseInt(retryAfter, 10) : 60;
        setError(`Rate limit reached. Please try again in ${waitSec > 60 ? `${Math.ceil(waitSec / 60)} minutes` : `${waitSec} seconds`}.`);
        setIsAnalyzing(false);
        return;
      }

      if (!response.ok) {
        const text = await response.text().catch(() => '');
        setError(text || `Server error (${response.status}). Please try again.`);
        setIsAnalyzing(false);
        return;
      }

      // Try streaming response
      if (response.headers.get('content-type')?.includes('text/event-stream')) {
        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        let accumulated = '';
        let parsedResult: DebateResult | null = null;

        if (reader) {
          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              accumulated += decoder.decode(value, { stream: true });
            }
          } finally {
            // nothing to clear here, already cleared above
          }

          // Parse the accumulated SSE data for the final result
          const lines = accumulated.split('\n');
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const parsed = JSON.parse(line.slice(6));
                if (parsed.verdict || parsed.result || parsed.final_answer) {
                  const r = parsed.result ?? parsed;
                  parsedResult = {
                    verdict: r.verdict ?? r.consensus ?? 'Analysis Complete',
                    confidence: r.confidence ?? r.consensus_confidence ?? 0.75,
                    explanation: r.explanation ?? r.summary ?? r.final_answer ?? r.consensus_text ?? '',
                    debateId: r.id,
                    topic: r.topic,
                    participants: r.participants,
                    proposals: r.proposals,
                    receiptHash: r.receipt_hash,
                  };
                }
              } catch {
                // Not JSON, skip
              }
            }
          }

          if (parsedResult) {
            setResult(parsedResult);
          } else {
            // Fallback when SSE didn't contain structured data
            setResult({
              verdict: 'Analysis Complete',
              confidence: 0.75,
              explanation: accumulated.slice(0, 800) || 'The agents have completed their analysis. Sign up to see the full debate transcript and decision receipt.',
            });
          }
        }
      } else {
        // Standard JSON response
        const data = await response.json();
        const r = data.result ?? data;
        setResult({
          verdict: r.verdict ?? r.consensus ?? 'Analysis Complete',
          confidence: r.confidence ?? r.consensus_confidence ?? 0.75,
          explanation: r.explanation ?? r.summary ?? r.final_answer ?? r.consensus_text ?? '',
          debateId: r.id,
          topic: r.topic,
          participants: r.participants,
          proposals: r.proposals,
          receiptHash: r.receipt_hash,
        });
      }
    } catch (e) {
      clearTimers();
      if (e instanceof Error && e.name === 'AbortError') return;
      setError('Could not connect to the analysis server. Please try again later.');
    } finally {
      setIsAnalyzing(false);
      setProgressStep(PROGRESS_STEPS.length - 1);
      setElapsed(0);
    }
  };

  const currentStep = PROGRESS_STEPS[Math.min(progressStep, PROGRESS_STEPS.length - 1)];

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <div className="min-h-[calc(100vh-48px)] bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="max-w-2xl mx-auto px-4 py-12">
          {/* Headline */}
          <div className="text-center mb-10">
            <h1 className="text-3xl md:text-4xl font-mono text-[var(--acid-green)] mb-4">
              Test a decision with AI experts
            </h1>
            <p className="text-sm font-mono text-[var(--text-muted)] max-w-lg mx-auto">
              Pose any question and watch multiple AI models debate it from different angles.
              Get a consensus verdict in seconds.
            </p>
          </div>

          {/* Input Area */}
          <div className="mb-6">
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && question.trim().length >= 10) {
                  e.preventDefault();
                  handleAnalyze();
                }
              }}
              placeholder="Enter your decision question..."
              rows={3}
              disabled={isAnalyzing}
              className="w-full px-4 py-3 font-mono text-sm bg-[var(--surface)] border border-[var(--acid-green)]/30
                       text-[var(--text)] placeholder-[var(--text-muted)]/50 focus:border-[var(--acid-green)] focus:outline-none
                       resize-none disabled:opacity-50"
            />

            {/* Example Questions */}
            {!result && !isAnalyzing && (
              <div className="mt-3">
                <span className="text-xs font-mono text-[var(--text-muted)] block mb-2">
                  Or try one of these:
                </span>
                <div className="flex flex-col gap-2">
                  {EXAMPLE_QUESTIONS.map((eq) => (
                    <button
                      key={eq}
                      onClick={() => setQuestion(eq)}
                      disabled={isAnalyzing}
                      className="text-left px-3 py-2 text-xs font-mono border border-[var(--acid-cyan)]/20
                               text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors
                               disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {eq}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Error */}
          {error && (
            <div className="mb-6 p-3 border border-[var(--warning)]/30 bg-[var(--warning)]/10">
              <p className="text-sm font-mono text-[var(--warning)] mb-2">{error}</p>
              <button
                onClick={() => { setError(null); handleAnalyze(); }}
                disabled={question.length < 10}
                className="text-xs font-mono px-4 py-1.5 border border-[var(--warning)]/40 text-[var(--warning)] hover:bg-[var(--warning)]/10 transition-colors disabled:opacity-50"
              >
                Try again
              </button>
            </div>
          )}

          {/* Analyze Button */}
          {!result && (
            <button
              onClick={handleAnalyze}
              disabled={isAnalyzing || question.length < 10}
              className="w-full py-3 font-mono font-bold text-sm bg-[var(--acid-green)] text-[var(--bg)]
                       hover:bg-[var(--acid-green)]/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isAnalyzing ? 'ANALYZING...' : 'ANALYZE'}
            </button>
          )}

          {/* Progress — stepped indicator */}
          {isAnalyzing && (
            <div className="mt-6 space-y-4">
              {/* Step list */}
              <div className="space-y-2">
                {PROGRESS_STEPS.map((step, i) => {
                  const isActive = i === progressStep;
                  const isDone = i < progressStep;
                  return (
                    <div
                      key={i}
                      className="flex items-center gap-3 transition-opacity duration-300"
                      style={{ opacity: isDone ? 0.4 : isActive ? 1 : 0.2 }}
                    >
                      <div
                        className="w-5 h-5 flex items-center justify-center shrink-0 text-xs font-bold font-mono rounded-full border-2 transition-all"
                        style={{
                          borderColor: isActive || isDone ? 'var(--acid-green)' : 'rgba(57,255,20,0.2)',
                          color: isDone ? 'var(--bg)' : isActive ? 'var(--acid-green)' : 'rgba(57,255,20,0.3)',
                          backgroundColor: isDone ? 'var(--acid-green)' : 'transparent',
                        }}
                      >
                        {isDone ? '✓' : i + 1}
                      </div>
                      <div className="flex-1 min-w-0">
                        <span className="text-xs font-mono" style={{ color: isActive ? 'var(--text)' : 'var(--text-muted)' }}>
                          {step.label}
                        </span>
                        {isActive && (
                          <p className="text-xs font-mono text-[var(--text-muted)]/60 mt-0.5">{step.subtext}</p>
                        )}
                      </div>
                      {isActive && (
                        <svg className="animate-spin h-4 w-4 shrink-0 text-[var(--acid-green)]" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                      )}
                    </div>
                  );
                })}
              </div>
              {/* Progress bar */}
              <div className="h-1 bg-[var(--acid-green)]/10 overflow-hidden">
                <div
                  className="h-full bg-[var(--acid-green)] transition-all duration-1000 ease-out"
                  style={{ width: `${Math.min(((progressStep + 1) / PROGRESS_STEPS.length) * 100, 95)}%` }}
                />
              </div>
              <div className="flex justify-between text-xs font-mono text-[var(--text-muted)]/60">
                <span>{elapsed}s elapsed</span>
                <span>~20s remaining</span>
              </div>
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="mt-8">
              <TeaserResult
                verdict={result.verdict}
                confidence={result.confidence}
                explanation={result.explanation}
                debateId={result.debateId}
                topic={result.topic}
                participants={result.participants}
                proposals={result.proposals}
                receiptHash={result.receiptHash}
              />

              {/* Follow-up suggestions */}
              <div className="mt-6 border border-[var(--acid-green)]/20 p-4">
                <p className="text-xs font-mono text-[var(--text-muted)] mb-3">
                  Follow-up questions to explore:
                </p>
                <div className="flex flex-col gap-2">
                  {FOLLOW_UP_SUGGESTIONS.map((q) => (
                    <button
                      key={q}
                      onClick={() => {
                        setQuestion(q);
                        setResult(null);
                        window.scrollTo({ top: 0, behavior: 'smooth' });
                      }}
                      className="text-left px-3 py-2 text-xs font-mono border border-[var(--acid-cyan)]/20
                               text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              </div>

              {/* Share + Upgrade CTAs */}
              <div className="mt-4 flex flex-col gap-3 items-center">
                <a
                  href="/signup"
                  className="w-full py-3 font-mono font-bold text-sm bg-[var(--acid-green)] text-[var(--bg)]
                             hover:bg-[var(--acid-green)]/80 transition-colors text-center"
                >
                  Sign up for full debate transcripts
                </a>
                <p className="text-xs font-mono text-[var(--text-muted)]/60">
                  Free tier includes 5 debates/day with full receipts
                </p>
              </div>
            </div>
          )}

          {/* Result: try another */}
          {result && (
            <div className="mt-4 text-center">
              <button
                onClick={() => {
                  setResult(null);
                  setQuestion('');
                  window.scrollTo({ top: 0, behavior: 'smooth' });
                }}
                className="text-xs font-mono text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
              >
                [TRY ANOTHER QUESTION]
              </button>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export default function TryPage() {
  return (
    <Suspense>
      <TryPageInner />
    </Suspense>
  );
}
