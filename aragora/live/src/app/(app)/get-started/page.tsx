'use client';

import Link from 'next/link';
import { useState, useEffect, useCallback } from 'react';
import { Scanlines, CRTVignette } from '@/components/MatrixRain';
import { API_BASE_URL } from '@/config';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ConnectionStatus = 'checking' | 'online' | 'offline';

interface HealthInfo {
  status: ConnectionStatus;
  serverVersion?: string;
  uptime?: number;
}

interface ProviderStatus {
  name: string;
  configured: boolean;
}

interface DebateResult {
  debateId: string;
  question: string;
  consensus?: string;
  confidence?: number;
  agents?: string[];
  winningProposal?: string;
}

type OnboardingStep = 1 | 2 | 3;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TEMPLATE_QUESTION = 'Should we adopt TypeScript for our backend?';

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

function StepIndicator({ current }: { current: OnboardingStep }) {
  const steps = [
    { num: 1 as const, label: 'CHECK CONNECTION' },
    { num: 2 as const, label: 'RUN DEBATE' },
    { num: 3 as const, label: 'VIEW RESULTS' },
  ];

  return (
    <div className="flex items-center gap-1 mb-6">
      {steps.map((step, idx) => {
        const isActive = step.num === current;
        const isCompleted = step.num < current;

        return (
          <div key={step.num} className="flex items-center gap-1">
            {idx > 0 && (
              <div
                className={`w-8 h-px mx-1 ${
                  isCompleted ? 'bg-[var(--acid-green)]' : 'bg-[var(--border)]'
                }`}
              />
            )}
            <div className="flex items-center gap-2">
              <span
                className={`flex items-center justify-center w-6 h-6 font-theme-data text-xs font-bold border transition-colors ${
                  isActive
                    ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/60'
                    : isCompleted
                      ? 'bg-[var(--acid-green)] text-[var(--bg)] border-[var(--acid-green)]'
                      : 'bg-transparent text-[var(--text-muted)] border-[var(--border)]'
                }`}
              >
                {isCompleted ? '\u2713' : step.num}
              </span>
              <span
                className={`text-[10px] font-theme-data uppercase tracking-wider hidden sm:inline ${
                  isActive
                    ? 'text-[var(--acid-green)]'
                    : isCompleted
                      ? 'text-[var(--acid-green)]/70'
                      : 'text-[var(--text-muted)]'
                }`}
              >
                {step.label}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status dot
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: 'ok' | 'error' | 'checking' }) {
  if (status === 'checking') {
    return (
      <span className="relative flex h-2.5 w-2.5">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-amber-400 opacity-75" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-amber-400" />
      </span>
    );
  }

  return (
    <span
      className={`inline-flex h-2.5 w-2.5 rounded-full ${
        status === 'ok' ? 'bg-[var(--acid-green)]' : 'bg-red-500'
      }`}
    />
  );
}

// ---------------------------------------------------------------------------
// Spinner
// ---------------------------------------------------------------------------

function _Spinner({ className = 'w-4 h-4' }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className}`}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Pulsing progress bar
// ---------------------------------------------------------------------------

function DebateProgress({ elapsed }: { elapsed: number }) {
  // Approximate progress: debate takes ~30-120s typically
  const estimatedTotal = 60;
  const pct = Math.min(95, (elapsed / estimatedTotal) * 100);

  const phases = [
    { label: 'Selecting agents', threshold: 10 },
    { label: 'Running proposals', threshold: 30 },
    { label: 'Critiques & revisions', threshold: 60 },
    { label: 'Building consensus', threshold: 90 },
  ];

  const currentPhase = phases.findLast((p) => pct >= p.threshold)?.label ?? 'Initializing debate';

  return (
    <div className="space-y-2">
      <div className="flex justify-between text-[10px] font-theme-data text-[var(--text-muted)]">
        <span>{currentPhase}...</span>
        <span>{Math.round(pct)}%</span>
      </div>
      <div className="h-1 bg-[var(--border)] overflow-hidden">
        <div
          className="h-full bg-[var(--acid-green)] transition-all duration-1000 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-[10px] font-theme-data text-[var(--text-muted)]">
        Elapsed: {elapsed}s — AI agents are debating your question
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function GetStartedPage() {
  const [currentStep, setCurrentStep] = useState<OnboardingStep>(1);
  const [health, setHealth] = useState<HealthInfo>({ status: 'checking' });
  const [providers, setProviders] = useState<ProviderStatus[]>([]);
  const [providersLoading, setProvidersLoading] = useState(true);

  // Step 2 state
  const [userQuestion, setUserQuestion] = useState(TEMPLATE_QUESTION);
  const [debateLoading, setDebateLoading] = useState(false);
  const [debateError, setDebateError] = useState<string | null>(null);
  const [debateResult, setDebateResult] = useState<DebateResult | null>(null);
  const [elapsed, setElapsed] = useState(0);

  // ── Step 1: Check backend health ────────────────────────────────────────
  const checkHealth = useCallback(async () => {
    setHealth({ status: 'checking' });
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      const response = await fetch(`${API_BASE_URL}/api/health`, { signal: controller.signal });
      clearTimeout(timeoutId);

      if (response.ok) {
        const data = await response.json().catch(() => ({}));
        setHealth({ status: 'online', serverVersion: data.version, uptime: data.uptime_seconds });
      } else {
        setHealth({ status: 'offline' });
      }
    } catch {
      setHealth({ status: 'offline' });
    }
  }, []);

  // ── Step 1: Check provider/API key status ──────────────────────────────
  const checkProviders = useCallback(async () => {
    setProvidersLoading(true);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      const response = await fetch(`${API_BASE_URL}/api/health/detailed`, {
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (response.ok) {
        const data = await response.json().catch(() => ({}));
        // Extract provider availability from detailed health
        const providerList: ProviderStatus[] = [];
        const knownProviders = [
          { key: 'ANTHROPIC_API_KEY', name: 'Anthropic (Claude)' },
          { key: 'OPENAI_API_KEY', name: 'OpenAI (GPT)' },
          { key: 'OPENROUTER_API_KEY', name: 'OpenRouter (Fallback)' },
          { key: 'GEMINI_API_KEY', name: 'Google (Gemini)' },
          { key: 'MISTRAL_API_KEY', name: 'Mistral' },
        ];

        // If detailed health returns providers info, use it
        if (data.providers && typeof data.providers === 'object') {
          for (const p of knownProviders) {
            providerList.push({ name: p.name, configured: !!data.providers[p.key] });
          }
        } else {
          // Fallback: just show that the server is up (no per-key detail available)
          for (const p of knownProviders) {
            providerList.push({ name: p.name, configured: false });
          }
        }
        setProviders(providerList);
      }
    } catch {
      // Non-critical - we already have health status
    } finally {
      setProvidersLoading(false);
    }
  }, []);

  useEffect(() => {
    checkHealth();
    checkProviders();
  }, [checkHealth, checkProviders]);

  // ── Step 2: Run first debate ────────────────────────────────────────────
  const runFirstDebate = useCallback(async () => {
    const question = userQuestion.trim() || TEMPLATE_QUESTION;

    setDebateLoading(true);
    setDebateError(null);
    setElapsed(0);

    // Start elapsed timer
    const startTime = Date.now();
    const timer = setInterval(() => {
      setElapsed(Math.round((Date.now() - startTime) / 1000));
    }, 1000);

    try {
      // Try standard debate endpoint first
      const response = await fetch(`${API_BASE_URL}/api/v1/debates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, rounds: 4, debate_format: 'light', auto_select: true }),
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));

        // If server suggests playground fallback (no API keys), try that
        if (errorData.use_playground) {
          const pgResponse = await fetch(`${API_BASE_URL}/api/v1/playground/debate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ topic: question, rounds: 4, agents: 3 }),
          });
          if (pgResponse.ok) {
            const pgData = await pgResponse.json();
            const debateId = pgData.debate_id || pgData.id;
            if (debateId) {
              clearInterval(timer);
              setDebateResult({
                debateId,
                question,
                consensus: pgData.consensus_reached ? 'Reached' : 'Partial',
                confidence: pgData.confidence,
                agents: pgData.agents,
                winningProposal: pgData.winning_proposal,
              });
              setDebateLoading(false);
              setCurrentStep(3);
              return;
            }
          }
        }

        throw new Error(
          errorData.error || errorData.message || `Server returned ${response.status}`,
        );
      }

      const data = await response.json();
      const debateId = data.debate_id || data.id;

      if (!debateId) {
        throw new Error('No debate ID returned from server');
      }

      clearInterval(timer);
      setDebateResult({
        debateId,
        question,
        consensus: data.consensus_reached ? 'Reached' : 'Partial',
        confidence: data.confidence,
        agents: data.agents,
        winningProposal: data.winning_proposal,
      });
      setDebateLoading(false);
      setCurrentStep(3);
    } catch (err) {
      clearInterval(timer);
      setDebateLoading(false);
      setDebateError(err instanceof Error ? err.message : 'Failed to start debate');
    }
  }, [userQuestion]);

  // Determine if the user can proceed to step 2
  const canStartDebate = health.status === 'online';
  const hasAnyProvider = providers.some((p) => p.configured);

  return (
    <>
      <Scanlines opacity={0.02} />
      <CRTVignette />

      <main className="min-h-screen bg-[var(--bg)] text-[var(--text)] relative z-10">
        <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">
          {/* Breadcrumb */}
          <div className="flex items-center gap-3 mb-2">
            <Link
              href="/dashboard"
              className="text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
            >
              DASHBOARD
            </Link>
            <span className="text-xs font-theme-data text-[var(--text-muted)]">/</span>
            <span className="text-xs font-theme-data text-[var(--acid-green)]">GET STARTED</span>
          </div>

          {/* Page header */}
          <div className="mb-2">
            <h1 className="text-2xl font-theme-data text-[var(--acid-green)] mb-1">
              {'>'} GET STARTED
            </h1>
            <p className="text-sm font-theme-data text-[var(--text-muted)] max-w-2xl">
              Connect to the backend, run your first AI debate, and see the results. Three steps to
              experience the Decision Integrity Platform.
            </p>
          </div>

          {/* Step indicator */}
          <StepIndicator current={currentStep} />

          {/* ============================================================ */}
          {/* Step 1: Check Connection                                      */}
          {/* ============================================================ */}
          <section
            className={`bg-[var(--surface)] border p-5 transition-colors ${
              currentStep === 1 ? 'border-[var(--acid-green)]/40' : 'border-[var(--border)]'
            }`}
          >
            <div className="flex items-center gap-3 mb-4">
              <span
                className={`flex items-center justify-center w-7 h-7 font-theme-data text-sm font-bold border ${
                  currentStep > 1
                    ? 'bg-[var(--acid-green)] text-[var(--bg)] border-[var(--acid-green)]'
                    : 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/40'
                }`}
              >
                {currentStep > 1 ? '\u2713' : '1'}
              </span>
              <h2 className="text-sm font-theme-data text-[var(--acid-green)] uppercase tracking-wider">
                Check Connection
              </h2>
            </div>

            {/* Backend health */}
            <div className="space-y-3">
              <div className="flex items-center justify-between bg-[var(--bg)] border border-[var(--border)] p-3">
                <div className="flex items-center gap-3">
                  <StatusDot
                    status={
                      health.status === 'checking'
                        ? 'checking'
                        : health.status === 'online'
                          ? 'ok'
                          : 'error'
                    }
                  />
                  <div>
                    <span className="text-xs font-theme-data text-[var(--text)]">
                      Backend Server
                    </span>
                    <span className="text-[10px] font-theme-data text-[var(--text-muted)] ml-2">
                      {API_BASE_URL || 'localhost:8080'}
                    </span>
                  </div>
                </div>
                <span
                  className={`text-xs font-theme-data font-bold ${
                    health.status === 'checking'
                      ? 'text-amber-400'
                      : health.status === 'online'
                        ? 'text-[var(--acid-green)]'
                        : 'text-red-400'
                  }`}
                >
                  {health.status === 'checking'
                    ? 'CHECKING...'
                    : health.status === 'online'
                      ? 'ONLINE'
                      : 'OFFLINE'}
                </span>
              </div>

              {/* Provider status */}
              {!providersLoading && providers.length > 0 && (
                <div className="bg-[var(--bg)] border border-[var(--border)] p-3">
                  <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-2">
                    AI Providers
                    {hasAnyProvider && (
                      <span className="text-[var(--acid-green)] ml-2">
                        ({providers.filter((p) => p.configured).length} configured)
                      </span>
                    )}
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                    {providers.map((provider) => (
                      <div key={provider.name} className="flex items-center gap-2">
                        <StatusDot status={provider.configured ? 'ok' : 'error'} />
                        <span
                          className={`text-xs font-theme-data ${
                            provider.configured ? 'text-[var(--text)]' : 'text-[var(--text-muted)]'
                          }`}
                        >
                          {provider.name}
                        </span>
                      </div>
                    ))}
                  </div>
                  {!hasAnyProvider && health.status === 'online' && (
                    <div className="mt-2 space-y-1.5">
                      <p className="text-[10px] font-theme-data text-amber-400">
                        No API keys detected. The playground will be used for your first debate.
                      </p>
                      <p className="text-[10px] font-theme-data text-[var(--text-muted)]">
                        To use real AI providers, add keys to your{' '}
                        <code className="text-[var(--acid-cyan)]">.env</code> file:
                      </p>
                      <code className="block text-[10px] font-theme-data bg-[var(--surface)] text-[var(--text-muted)] p-2 border border-[var(--border)]">
                        ANTHROPIC_API_KEY=sk-...{'\n'}
                        OPENAI_API_KEY=sk-...
                      </code>
                    </div>
                  )}
                </div>
              )}

              {/* Offline instructions */}
              {health.status === 'offline' && (
                <div className="bg-red-500/5 border border-red-500/20 p-3">
                  <p className="text-xs font-theme-data text-red-400 mb-2">
                    Cannot reach the Aragora backend. Make sure it is running:
                  </p>
                  <code className="block text-[10px] font-theme-data bg-[var(--bg)] text-[var(--text-muted)] p-2 border border-[var(--border)]">
                    aragora serve --api-port 8080 --ws-port 8765
                  </code>
                  <button
                    onClick={() => {
                      checkHealth();
                      checkProviders();
                    }}
                    className="mt-3 px-3 py-1.5 text-xs font-theme-data font-bold bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 hover:text-[var(--text)] transition-colors"
                  >
                    RETRY CONNECTION
                  </button>
                </div>
              )}

              {/* Continue button */}
              {health.status === 'online' && currentStep === 1 && (
                <button
                  onClick={() => setCurrentStep(2)}
                  className="mt-2 px-4 py-2 text-xs font-theme-data font-bold bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors"
                >
                  CONTINUE
                </button>
              )}
            </div>
          </section>

          {/* ============================================================ */}
          {/* Step 2: Run Your First Debate                                 */}
          {/* ============================================================ */}
          <section
            className={`bg-[var(--surface)] border p-5 transition-colors ${
              currentStep === 2
                ? 'border-[var(--acid-green)]/40'
                : currentStep > 2
                  ? 'border-[var(--border)]'
                  : 'border-[var(--border)] opacity-50'
            }`}
          >
            <div className="flex items-center gap-3 mb-4">
              <span
                className={`flex items-center justify-center w-7 h-7 font-theme-data text-sm font-bold border ${
                  currentStep > 2
                    ? 'bg-[var(--acid-green)] text-[var(--bg)] border-[var(--acid-green)]'
                    : currentStep === 2
                      ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/40'
                      : 'bg-transparent text-[var(--text-muted)] border-[var(--border)]'
                }`}
              >
                {currentStep > 2 ? '\u2713' : '2'}
              </span>
              <h2
                className={`text-sm font-theme-data uppercase tracking-wider ${
                  currentStep >= 2 ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'
                }`}
              >
                Run Your First Debate
              </h2>
            </div>

            {currentStep >= 2 && (
              <div className="space-y-4">
                <p className="text-xs font-theme-data text-[var(--text-muted)] max-w-2xl">
                  Launch a multi-agent debate where AI models propose, critique, and synthesize a
                  decision. Enter your own question or use the suggestion below.
                </p>

                {/* Debate topic card */}
                <div className="bg-[var(--bg)] border border-[var(--acid-green)]/30 p-4">
                  <div className="mb-3">
                    <label
                      htmlFor="debate-question"
                      className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block mb-1"
                    >
                      Your Question
                    </label>
                    <textarea
                      id="debate-question"
                      value={userQuestion}
                      onChange={(e) => setUserQuestion(e.target.value)}
                      disabled={debateLoading}
                      rows={2}
                      placeholder="e.g. Should we adopt TypeScript for our backend?"
                      className="w-full bg-[var(--surface)] text-sm font-theme-data text-[var(--text)] border border-[var(--border)] focus:border-[var(--acid-green)]/60 focus:outline-none p-2 resize-none placeholder:text-[var(--text-muted)]/50 disabled:opacity-50"
                    />
                    {userQuestion !== TEMPLATE_QUESTION && userQuestion.trim() !== '' && (
                      <button
                        type="button"
                        onClick={() => setUserQuestion(TEMPLATE_QUESTION)}
                        className="text-[10px] font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors mt-1"
                      >
                        Reset to suggestion
                      </button>
                    )}
                  </div>

                  {/* Configuration */}
                  <div className="flex items-center gap-4 mb-4 text-[10px] font-theme-data text-[var(--text-muted)]">
                    <span>Format: Quick (4 rounds)</span>
                    <span>Agent selection: Auto</span>
                    <span>Consensus: Majority</span>
                  </div>

                  {/* Debate loading state */}
                  {debateLoading && <DebateProgress elapsed={elapsed} />}

                  {/* Error state */}
                  {debateError && (
                    <div className="bg-red-500/5 border border-red-500/20 p-3 mb-3">
                      <p className="text-xs font-theme-data text-red-400">{debateError}</p>
                    </div>
                  )}

                  {/* Action button */}
                  {!debateLoading && currentStep === 2 && (
                    <button
                      onClick={runFirstDebate}
                      disabled={!canStartDebate || !userQuestion.trim()}
                      className="inline-flex items-center gap-2 px-4 py-2 text-xs font-theme-data font-bold bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                      {debateError ? 'RETRY DEBATE' : 'START DEBATE'}
                    </button>
                  )}
                </div>
              </div>
            )}
          </section>

          {/* ============================================================ */}
          {/* Step 3: View Results                                          */}
          {/* ============================================================ */}
          <section
            className={`bg-[var(--surface)] border p-5 transition-colors ${
              currentStep === 3
                ? 'border-[var(--acid-green)]/40'
                : 'border-[var(--border)] opacity-50'
            }`}
          >
            <div className="flex items-center gap-3 mb-4">
              <span
                className={`flex items-center justify-center w-7 h-7 font-theme-data text-sm font-bold border ${
                  currentStep === 3
                    ? 'bg-[var(--acid-green)]/20 text-[var(--acid-green)] border-[var(--acid-green)]/40'
                    : 'bg-transparent text-[var(--text-muted)] border-[var(--border)]'
                }`}
              >
                3
              </span>
              <h2
                className={`text-sm font-theme-data uppercase tracking-wider ${
                  currentStep === 3 ? 'text-[var(--acid-green)]' : 'text-[var(--text-muted)]'
                }`}
              >
                View Results
              </h2>
            </div>

            {currentStep === 3 && debateResult && (
              <div className="space-y-4">
                {/* Success banner */}
                <div className="bg-[var(--acid-green)]/5 border border-[var(--acid-green)]/30 p-4">
                  <div className="flex items-center gap-2 mb-3">
                    <StatusDot status="ok" />
                    <span className="text-xs font-theme-data font-bold text-[var(--acid-green)]">
                      DEBATE COMPLETED
                    </span>
                  </div>

                  <div className="space-y-3">
                    {/* Question */}
                    <div>
                      <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                        Question
                      </span>
                      <p className="text-xs font-theme-data text-[var(--text)] mt-0.5">
                        {debateResult.question}
                      </p>
                    </div>

                    {/* Result stats */}
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                      <div className="bg-[var(--bg)] border border-[var(--border)] p-2.5">
                        <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block">
                          Debate ID
                        </span>
                        <span className="text-xs font-theme-data text-[var(--acid-cyan)] font-bold">
                          {debateResult.debateId.slice(0, 8)}...
                        </span>
                      </div>

                      {debateResult.consensus && (
                        <div className="bg-[var(--bg)] border border-[var(--border)] p-2.5">
                          <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block">
                            Consensus
                          </span>
                          <span className="text-xs font-theme-data text-[var(--acid-green)] font-bold">
                            {debateResult.consensus}
                          </span>
                        </div>
                      )}

                      {debateResult.confidence != null && (
                        <div className="bg-[var(--bg)] border border-[var(--border)] p-2.5">
                          <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase block">
                            Confidence
                          </span>
                          <span className="text-xs font-theme-data text-amber-400 font-bold">
                            {(debateResult.confidence * 100).toFixed(0)}%
                          </span>
                        </div>
                      )}
                    </div>

                    {/* Winning proposal preview */}
                    {debateResult.winningProposal && (
                      <div>
                        <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                          Winning Proposal
                        </span>
                        <p className="text-xs font-theme-data text-[var(--text)] mt-0.5 line-clamp-3">
                          {debateResult.winningProposal}
                        </p>
                      </div>
                    )}

                    {/* Agents */}
                    {debateResult.agents && debateResult.agents.length > 0 && (
                      <div>
                        <span className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase">
                          Participating Agents
                        </span>
                        <div className="flex flex-wrap gap-1.5 mt-1">
                          {debateResult.agents.map((agent) => (
                            <span
                              key={agent}
                              className="px-2 py-0.5 text-[10px] font-theme-data bg-[var(--bg)] text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/30"
                            >
                              {agent}
                            </span>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* Action links */}
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/debates/${debateResult.debateId}`}
                    className="px-4 py-2 text-xs font-theme-data font-bold bg-[var(--acid-green)] text-[var(--bg)] hover:bg-[var(--acid-green)]/80 transition-colors"
                  >
                    VIEW FULL DEBATE
                  </Link>
                  <Link
                    href="/receipts"
                    className="px-4 py-2 text-xs font-theme-data font-bold bg-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] border border-[var(--acid-cyan)]/40 hover:bg-[var(--acid-cyan)]/30 transition-colors"
                  >
                    VIEW RECEIPTS
                  </Link>
                  <Link
                    href="/arena"
                    className="px-4 py-2 text-xs font-theme-data font-bold bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 hover:text-[var(--text)] transition-colors"
                  >
                    START ANOTHER DEBATE
                  </Link>
                </div>
              </div>
            )}
          </section>

          {/* ============================================================ */}
          {/* What's Next */}
          {/* ============================================================ */}
          {currentStep === 3 && (
            <section className="bg-[var(--surface)] border border-[var(--border)] p-5 transition-colors hover:border-[var(--acid-green)]/40">
              <h2 className="text-sm font-theme-data text-[var(--acid-green)] uppercase tracking-wider mb-4">
                What&apos;s Next?
              </h2>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <Link
                  href="/arena"
                  className="bg-[var(--bg)] border border-[var(--border)] p-4 hover:border-[var(--acid-green)]/40 transition-colors group"
                >
                  <div className="text-[var(--acid-green)] font-theme-data text-sm mb-1 group-hover:text-[var(--acid-green)]">
                    {'>'}
                  </div>
                  <h3 className="text-xs font-theme-data text-[var(--text)] font-bold mb-1">
                    Debate Arena
                  </h3>
                  <p className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    Ask your own question and customize agents, rounds, and debate format.
                  </p>
                </Link>

                <Link
                  href="/self-improve"
                  className="bg-[var(--bg)] border border-[var(--border)] p-4 hover:border-[var(--acid-cyan)]/40 transition-colors group"
                >
                  <div className="text-[var(--acid-cyan)] font-theme-data text-sm mb-1 group-hover:text-[var(--acid-cyan)]">
                    {'@'}
                  </div>
                  <h3 className="text-xs font-theme-data text-[var(--text)] font-bold mb-1">
                    Self-Improvement
                  </h3>
                  <p className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    Use the Nomic Loop to let agents autonomously improve the platform.
                  </p>
                </Link>

                <Link
                  href="/pipeline"
                  className="bg-[var(--bg)] border border-[var(--border)] p-4 hover:border-amber-400/40 transition-colors group"
                >
                  <div className="text-amber-400 font-theme-data text-sm mb-1 group-hover:text-amber-400">
                    {'^'}
                  </div>
                  <h3 className="text-xs font-theme-data text-[var(--text)] font-bold mb-1">
                    Pipeline Canvas
                  </h3>
                  <p className="text-[10px] font-theme-data text-[var(--text-muted)]">
                    Transform ideas into goals, actions, and orchestrated agent workflows.
                  </p>
                </Link>
              </div>
            </section>
          )}

          {/* Footer navigation */}
          <div className="flex items-center gap-2 pt-4 border-t border-[var(--border)]">
            <span className="text-xs font-theme-data text-[var(--text-muted)]">Navigate:</span>
            <Link
              href="/dashboard"
              className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              DASHBOARD
            </Link>
            <Link
              href="/arena"
              className="px-3 py-1 text-xs font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/30 hover:bg-[var(--acid-green)]/20 transition-colors"
            >
              NEW DEBATE
            </Link>
            <Link
              href="/marketplace"
              className="px-3 py-1 text-xs font-theme-data bg-[var(--surface)] text-[var(--text-muted)] border border-[var(--border)] hover:border-[var(--acid-green)]/30 transition-colors"
            >
              MARKETPLACE
            </Link>
          </div>
        </div>
      </main>
    </>
  );
}
