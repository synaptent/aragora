'use client';

import { useState, useCallback, useEffect } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/context/AuthContext';
import { useBackend, BACKENDS } from '@/components/BackendSelector';
import { useDashboardPreferences } from '@/hooks/useDashboardPreferences';
import { useOnboarding } from '@/hooks/useOnboarding';

type WizardStep = 'role' | 'question' | 'launch';

const ROLES = [
  { value: 'ceo', label: 'CEO / Founder', icon: '>' },
  { value: 'product', label: 'Product Manager', icon: '#' },
  { value: 'engineer', label: 'Engineer / Developer', icon: '/' },
  { value: 'analyst', label: 'Analyst / Researcher', icon: '%' },
  { value: 'legal', label: 'Legal / Compliance', icon: '!' },
  { value: 'other', label: 'Other', icon: '?' },
];

const SUGGESTED_QUESTIONS: Record<string, string[]> = {
  ceo: [
    'Should we raise our next round now or wait 6 months?',
    'Should we expand into the European market this year?',
    'Should we acquire a competitor or build in-house?',
  ],
  product: [
    'Should we build this feature in-house or buy a solution?',
    'Which user segment should we prioritize next quarter?',
    'Should we sunset our legacy product line?',
  ],
  engineer: [
    'Should we migrate our monolith to microservices?',
    'Is it better to build our own auth or use Auth0?',
    'Should we switch from REST to GraphQL?',
  ],
  analyst: [
    'What are the key risks in our current market strategy?',
    'Should we invest in AI-driven analytics?',
    'How should we weight qualitative vs quantitative data?',
  ],
  legal: [
    'What are the compliance risks of deploying AI in production?',
    'Should we adopt a data retention policy shorter than 3 years?',
    'How should we handle cross-border data transfers post-GDPR?',
  ],
  other: [
    'Should we adopt AI-first workflows?',
    'What are the biggest risks in our current strategy?',
    'Should we restructure our team for remote work?',
  ],
};

/**
 * Streamlined onboarding wizard: 3 steps to first debate.
 *
 * Role -> Question -> Launch Debate
 *
 * For authenticated users: launches the debate directly.
 * For unauthenticated users: saves the question and redirects to signup.
 */
export default function OnboardingPage() {
  const router = useRouter();
  const { isAuthenticated, tokens } = useAuth();
  const { config: backendConfig } = useBackend();
  const apiBase = backendConfig?.api ?? BACKENDS.production.api;
  const { markOnboardingComplete } = useDashboardPreferences();
  const {
    setSelectedIndustry,
    setFirstDebateTopic,
    setFirstDebateId,
    setDebateStatus,
    updateProgress,
    updateChecklist,
    completeOnboarding,
    skipOnboarding,
    initFlow,
  } = useOnboarding();

  const [step, setStep] = useState<WizardStep>('role');
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [question, setQuestion] = useState('');
  const [isLaunching, setIsLaunching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Restore saved question from signup flow (user started onboarding -> signed up -> came back)
  useEffect(() => {
    const savedQuestion = sessionStorage.getItem('aragora_onboarding_question');
    const savedRole = sessionStorage.getItem('aragora_onboarding_role');
    if (savedQuestion) {
      setQuestion(savedQuestion);
      setFirstDebateTopic(savedQuestion);
      if (savedRole) {
        setSelectedRole(savedRole);
        setSelectedIndustry(savedRole);
      }
      // Jump straight to the launch step since they already picked a question
      setStep('launch');
      // Clean up
      sessionStorage.removeItem('aragora_onboarding_question');
      sessionStorage.removeItem('aragora_onboarding_role');
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const suggestions = SUGGESTED_QUESTIONS[selectedRole || 'other'] || SUGGESTED_QUESTIONS.other;

  const handleRoleSelect = useCallback(
    (role: string) => {
      setSelectedRole(role);
      setSelectedIndustry(role);
      initFlow(role);
      setStep('question');
    },
    [setSelectedIndustry, initFlow],
  );

  const handleQuestionNext = useCallback(() => {
    if (question.trim().length >= 5) {
      setFirstDebateTopic(question.trim());
      setStep('launch');
    }
  }, [question, setFirstDebateTopic]);

  const handleLaunchDebate = useCallback(async () => {
    if (!question.trim()) return;

    // Unauthenticated users: save question for post-signup, redirect to signup
    if (!isAuthenticated) {
      sessionStorage.setItem('aragora_onboarding_question', question.trim());
      sessionStorage.setItem('aragora_onboarding_role', selectedRole || 'other');
      router.push('/signup');
      return;
    }

    setIsLaunching(true);
    setError(null);
    setDebateStatus('creating');

    try {
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (tokens?.access_token) {
        headers['Authorization'] = `Bearer ${tokens.access_token}`;
      }

      const response = await fetch(`${apiBase}/api/debate`, {
        method: 'POST',
        headers,
        body: JSON.stringify({
          question: question.trim(),
          agents: ['anthropic-api', 'openai-api', 'mistral'],
          rounds: 3,
          enable_receipt_generation: true,
          metadata: { source: 'onboarding', user_role: selectedRole },
        }),
      });

      const data = await response.json();

      if (data.success && data.debate_id) {
        setFirstDebateId(data.debate_id);
        setDebateStatus('running');
        updateProgress({ firstDebateStarted: true });
        updateChecklist({ accountCreated: true, firstDebateRun: true });
        completeOnboarding();
        markOnboardingComplete();
        router.push(`/debate/${data.debate_id}`);
      } else {
        setDebateStatus('error');
        setError(data.error || 'Failed to start debate');
      }
    } catch (err) {
      setDebateStatus('error');
      setError(err instanceof Error ? err.message : 'Network error. Please try again.');
    } finally {
      setIsLaunching(false);
    }
  }, [
    question,
    isAuthenticated,
    tokens,
    apiBase,
    selectedRole,
    markOnboardingComplete,
    router,
    setDebateStatus,
    setFirstDebateId,
    updateProgress,
    updateChecklist,
    completeOnboarding,
  ]);

  const handleSkip = useCallback(() => {
    skipOnboarding();
    markOnboardingComplete();
    router.push('/');
  }, [skipOnboarding, markOnboardingComplete, router]);

  return (
    <main className="min-h-screen bg-bg text-text">
      {/* Minimal nav */}
      <nav className="border-b border-border bg-surface/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <Link
            href="/"
            className="font-theme-data text-[var(--accent)] font-bold text-sm tracking-wider"
          >
            ARAGORA
          </Link>
          <div className="flex items-center gap-3">
            {!isAuthenticated && (
              <>
                <Link
                  href="/login"
                  className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
                >
                  LOG IN
                </Link>
                <Link
                  href="/signup"
                  className="text-xs font-theme-data px-3 py-1.5 bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors font-bold"
                >
                  SIGN UP
                </Link>
              </>
            )}
          </div>
        </div>
      </nav>

      <div className="flex items-center justify-center px-4 py-12 min-h-[calc(100vh-49px)]">
        <div className="w-full max-w-xl">
          {/* Progress dots */}
          <div className="flex items-center justify-center gap-2 mb-8">
            {(['role', 'question', 'launch'] as WizardStep[]).map((s, i) => (
              <div
                key={s}
                className={`h-2 rounded-full transition-all ${
                  s === step
                    ? 'w-8 bg-[var(--accent)]'
                    : i < ['role', 'question', 'launch'].indexOf(step)
                      ? 'w-2 bg-[var(--accent)]/60'
                      : 'w-2 bg-border'
                }`}
              />
            ))}
          </div>

          <div className="border border-[var(--accent)]/30 bg-surface/50 p-8">
            {/* ── STEP 1: Role ── */}
            {step === 'role' && (
              <div className="space-y-6">
                <div className="text-center">
                  <h1 className="text-xl font-theme-data text-[var(--accent)] mb-2">
                    Welcome to Aragora
                  </h1>
                  <p className="text-sm font-theme-data text-text-muted">
                    What is your role? This helps us tailor suggestions for you.
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  {ROLES.map((role) => (
                    <button
                      key={role.value}
                      onClick={() => handleRoleSelect(role.value)}
                      className={`text-left p-4 border transition-colors ${
                        selectedRole === role.value
                          ? 'border-[var(--accent)] bg-[var(--accent)]/10'
                          : 'border-border bg-surface hover:border-[var(--accent)]/50'
                      }`}
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-theme-data text-[var(--acid-cyan)] text-lg">
                          {role.icon}
                        </span>
                        <span className="font-theme-data text-sm text-text">{role.label}</span>
                      </div>
                    </button>
                  ))}
                </div>

                <div className="text-center">
                  <button
                    onClick={handleSkip}
                    className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
                  >
                    [SKIP TO DASHBOARD]
                  </button>
                </div>
              </div>
            )}

            {/* ── STEP 2: Question ── */}
            {step === 'question' && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-xl font-theme-data text-[var(--accent)] mb-2">
                    What decision do you need help with?
                  </h2>
                  <p className="text-sm font-theme-data text-text-muted">
                    Type a question or pick one of our suggestions. AI agents will debate it from
                    every angle.
                  </p>
                </div>

                <div>
                  <textarea
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    placeholder="e.g., Should we migrate to microservices?"
                    rows={3}
                    className="w-full bg-bg border border-[var(--accent)]/30 text-text px-4 py-3 font-theme-data text-sm placeholder:text-text-muted/50 focus:outline-none focus:border-[var(--accent)] transition-colors resize-none"
                    autoFocus
                  />
                </div>

                {/* Suggestions */}
                <div>
                  <span className="text-xs font-theme-data text-text-muted block mb-2">
                    SUGGESTED QUESTIONS:
                  </span>
                  <div className="flex flex-col gap-2">
                    {suggestions.map((s) => (
                      <button
                        key={s}
                        onClick={() => setQuestion(s)}
                        className="text-left px-3 py-2 text-xs font-theme-data border border-[var(--acid-cyan)]/20 text-[var(--acid-cyan)] hover:bg-[var(--acid-cyan)]/10 transition-colors"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex items-center justify-between">
                  <button
                    onClick={() => setStep('role')}
                    className="text-sm font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
                  >
                    &larr; BACK
                  </button>
                  <button
                    onClick={handleQuestionNext}
                    disabled={question.trim().length < 5}
                    className="px-6 py-2.5 bg-[var(--accent)] text-bg font-theme-data text-sm font-bold hover:bg-[var(--accent)]/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    CONTINUE &rarr;
                  </button>
                </div>
              </div>
            )}

            {/* ── STEP 3: Launch ── */}
            {step === 'launch' && (
              <div className="space-y-6">
                <div className="text-center">
                  <h2 className="text-xl font-theme-data text-[var(--accent)] mb-2">
                    Launch Your First Debate
                  </h2>
                  <p className="text-sm font-theme-data text-text-muted">
                    Three AI agents will debate your question from different angles, then deliver a
                    verdict with evidence.
                  </p>
                </div>

                {/* Preview */}
                <div className="border border-border bg-bg p-4">
                  <div className="text-[10px] font-theme-data text-text-muted uppercase mb-1">
                    YOUR QUESTION
                  </div>
                  <p className="text-sm font-theme-data text-text">{question}</p>
                </div>

                {/* What happens next */}
                <div className="space-y-2">
                  <div className="text-xs font-theme-data text-text-muted uppercase mb-1">
                    WHAT HAPPENS NEXT:
                  </div>
                  {[
                    'Claude, GPT, and Mistral will each propose an answer',
                    'They will critique and red-team each other',
                    'A consensus verdict will be generated with confidence scores',
                    'You will receive an audit-ready decision receipt',
                  ].map((s, i) => (
                    <div key={i} className="flex items-start gap-2 text-xs font-theme-data">
                      <span className="text-[var(--accent)] mt-0.5">{i + 1}.</span>
                      <span className="text-text-muted">{s}</span>
                    </div>
                  ))}
                </div>

                {/* Auth prompt for unauthenticated users */}
                {!isAuthenticated && (
                  <div className="border border-[var(--acid-cyan)]/30 bg-[var(--acid-cyan)]/5 p-3">
                    <p className="text-xs font-theme-data text-[var(--acid-cyan)]">
                      You will need to sign up (free) to launch the debate. Your question will be
                      saved.
                    </p>
                  </div>
                )}

                {/* Error */}
                {error && (
                  <div className="border border-[var(--crimson)]/50 bg-[var(--crimson)]/10 p-3 text-sm font-theme-data text-[var(--crimson)]">
                    {error}
                  </div>
                )}

                <div className="flex items-center justify-between">
                  <button
                    onClick={() => setStep('question')}
                    disabled={isLaunching}
                    className="text-sm font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors disabled:opacity-50"
                  >
                    &larr; EDIT QUESTION
                  </button>
                  <button
                    onClick={handleLaunchDebate}
                    disabled={isLaunching}
                    className="px-8 py-3 bg-[var(--accent)] text-bg font-theme-data text-sm font-bold hover:bg-[var(--accent)]/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {isLaunching
                      ? 'LAUNCHING...'
                      : isAuthenticated
                        ? 'LAUNCH DEBATE'
                        : 'SIGN UP & LAUNCH'}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
