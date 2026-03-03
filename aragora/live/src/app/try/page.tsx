'use client';

import { useState, useRef, useEffect } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { TeaserResult } from '@/components/try/TeaserResult';
import { API_BASE_URL } from '@/config';

const EXAMPLE_QUESTIONS = [
  'Should we migrate our monolithic app to microservices?',
  'Is it better to build our own auth system or use Auth0?',
  'Should we switch from REST to GraphQL for our mobile API?',
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

export default function TryPage() {
  const [question, setQuestion] = useState('');
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [result, setResult] = useState<DebateResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState('');
  const abortRef = useRef<AbortController | null>(null);
  const progressIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
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
    setProgress('Assembling agent panel...');

    abortRef.current = new AbortController();

    try {
      const response = await fetch(`${API_BASE_URL}/api/v1/playground/debate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question.trim(), source: 'landing' }),
        signal: abortRef.current.signal,
      });

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

        if (reader) {
          const progressMessages = [
            'Agents debating...',
            'Analyzing arguments...',
            'Building consensus...',
            'Generating verdict...',
          ];
          let progressIdx = 0;
          progressIntervalRef.current = setInterval(() => {
            if (progressIdx < progressMessages.length) {
              setProgress(progressMessages[progressIdx]);
              progressIdx++;
            }
          }, 3000);

          try {
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              accumulated += decoder.decode(value, { stream: true });
            }
          } finally {
            if (progressIntervalRef.current) clearInterval(progressIntervalRef.current);
          }

          // Parse the accumulated SSE data for the final result
          const lines = accumulated.split('\n');
          for (const line of lines) {
            if (line.startsWith('data: ')) {
              try {
                const parsed = JSON.parse(line.slice(6));
                if (parsed.verdict || parsed.result) {
                  const r = parsed.result ?? parsed;
                  setResult({
                    verdict: r.verdict ?? r.consensus ?? 'Analysis Complete',
                    confidence: r.confidence ?? r.consensus_confidence ?? 0.75,
                    explanation: r.explanation ?? r.summary ?? r.consensus_text ?? '',
                    debateId: r.id,
                    topic: r.topic,
                    participants: r.participants,
                    proposals: r.proposals,
                    receiptHash: r.receipt_hash,
                  });
                }
              } catch {
                // Not JSON, skip
              }
            }
          }

          // If no structured result found from SSE, make a plain result
          if (!result) {
            setResult({
              verdict: 'Analysis Complete',
              confidence: 0.75,
              explanation: accumulated.slice(0, 500) || 'The agents have completed their analysis. Sign up to see the full debate transcript and decision receipt.',
            });
          }
        }
      } else {
        // Standard JSON response
        setProgress('Generating verdict...');
        const data = await response.json();
        const r = data.result ?? data;
        setResult({
          verdict: r.verdict ?? r.consensus ?? 'Analysis Complete',
          confidence: r.confidence ?? r.consensus_confidence ?? 0.75,
          explanation: r.explanation ?? r.summary ?? r.consensus_text ?? '',
          debateId: r.id,
          topic: r.topic,
          participants: r.participants,
          proposals: r.proposals,
          receiptHash: r.receipt_hash,
        });
      }
    } catch (e) {
      if (e instanceof Error && e.name === 'AbortError') return;
      setError('Could not connect to the analysis server. Please try again later.');
    } finally {
      setIsAnalyzing(false);
      setProgress('');
    }
  };

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
              placeholder="Enter your decision question..."
              rows={3}
              disabled={isAnalyzing}
              className="w-full px-4 py-3 font-mono text-sm bg-[var(--surface)] border border-[var(--acid-green)]/30
                       text-[var(--text)] placeholder-[var(--text-muted)]/50 focus:border-[var(--acid-green)] focus:outline-none
                       resize-none disabled:opacity-50"
            />

            {/* Example Questions */}
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

          {/* Progress */}
          {isAnalyzing && (
            <div className="mt-6 flex flex-col items-center justify-center gap-2">
              <div className="flex items-center gap-3">
                <div className="w-5 h-5 border-2 border-[var(--acid-green)]/30 border-t-[var(--acid-green)] rounded-full animate-spin" />
                <span className="text-sm font-mono text-[var(--acid-green)] animate-pulse">{progress}</span>
              </div>
              <span className="text-xs font-mono text-[var(--text-muted)]/60">Usually takes 15-30 seconds</span>
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

              {/* Share + Upgrade CTAs */}
              <div className="mt-6 flex flex-col gap-3 items-center">
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
