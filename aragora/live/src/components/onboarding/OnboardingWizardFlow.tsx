'use client';

import { useCallback } from 'react';
import Link from 'next/link';
import { useOnboardingStore, useOnboardingStep } from '@/store';
import { useAuth } from '@/context/AuthContext';
import { IndustryStep } from './steps/IndustryStep';
import { TryDebateStep } from './steps/TryDebateStep';
import { ChooseTemplateStep } from './steps/ChooseTemplateStep';
import { WatchDemoStep } from './steps/WatchDemoStep';
import { YourTurnStep } from './steps/YourTurnStep';
import { ConnectChannelsStep } from './steps/ConnectChannelsStep';
import { OnboardingChecklist } from './OnboardingChecklist';
import { ProgressBar } from './ProgressBar';

interface OnboardingWizardFlowProps {
  onComplete?: () => void;
  onSkip?: () => void;
}

const STEP_LABELS: Record<string, string> = {
  industry: '1. INDUSTRY',
  'try-debate': '2. TRY IT',
  'create-account': '3. ACCOUNT',
  'choose-template': '4. TEMPLATE',
  'watch-demo': '5. DEMO',
  'your-turn': '6. YOUR TURN',
  'connect-channels': '7. CHANNELS',
  launch: '8. LAUNCH',
};

/**
 * Progressive commitment onboarding flow.
 * Steps 1-2 require no auth. Step 3 is the auth transition.
 * Steps 4-8 guide the user through their first debate experience.
 */
export function OnboardingWizardFlow({ onComplete, onSkip }: OnboardingWizardFlowProps) {
  const { currentStep, isFirstStep, isLastStep, canProceed, stepIndex, totalSteps } =
    useOnboardingStep();

  const { isAuthenticated } = useAuth();

  const {
    selectedIndustry,
    trialDebateResult,
    nextStep,
    previousStep,
    skipOnboarding,
    completeOnboarding,
    updateChecklist,
  } = useOnboardingStore();

  const handleNext = useCallback(() => {
    // Mark account as created when passing the create-account step while authenticated
    if (currentStep === 'create-account' && isAuthenticated) {
      updateChecklist({ accountCreated: true });
    }
    if (isLastStep) {
      completeOnboarding();
      onComplete?.();
    } else {
      nextStep();
    }
  }, [
    currentStep,
    isAuthenticated,
    isLastStep,
    completeOnboarding,
    onComplete,
    nextStep,
    updateChecklist,
  ]);

  const handleBack = useCallback(() => {
    previousStep();
  }, [previousStep]);

  const handleSkip = useCallback(() => {
    skipOnboarding();
    onSkip?.();
  }, [skipOnboarding, onSkip]);

  const renderStep = () => {
    switch (currentStep) {
      case 'industry':
        return <IndustryStep />;
      case 'try-debate':
        return <TryDebateStep />;
      case 'create-account':
        return <CreateAccountStep isAuthenticated={isAuthenticated} />;
      case 'choose-template':
        return <ChooseTemplateStep />;
      case 'watch-demo':
        return <WatchDemoStep />;
      case 'your-turn':
        return <YourTurnStep />;
      case 'connect-channels':
        return <ConnectChannelsStep />;
      case 'launch':
        return (
          <LaunchStep
            selectedIndustry={selectedIndustry}
            trialDebateResult={trialDebateResult}
            onComplete={onComplete}
          />
        );
      default:
        return <IndustryStep />;
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-bg/95 backdrop-blur-sm">
      <div className="w-full max-w-2xl mx-4 border border-[var(--accent)]/30 bg-surface rounded-lg overflow-hidden">
        {/* Header */}
        <div className="border-b border-[var(--accent)]/20 px-6 py-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-lg font-theme-data text-[var(--accent)]">
              GET STARTED WITH ARAGORA
            </h2>
            <button
              onClick={handleSkip}
              className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
            >
              [SKIP FOR NOW]
            </button>
          </div>

          {/* Step indicator pills */}
          <div className="flex items-center gap-0.5 mb-2">
            {Object.entries(STEP_LABELS).map(([key, label], i) => (
              <div
                key={key}
                className={`flex-1 text-center text-[10px] font-theme-data py-1 border-b-2 transition-colors ${
                  i < stepIndex
                    ? 'text-[var(--accent)] border-[var(--accent)]'
                    : i === stepIndex
                      ? 'text-[var(--accent)] border-[var(--accent)]'
                      : 'text-text-muted border-border'
                }`}
              >
                {label}
              </div>
            ))}
          </div>

          <ProgressBar current={stepIndex + 1} total={totalSteps} />
        </div>

        {/* Content */}
        <div className="p-6 min-h-[300px] max-h-[60vh] overflow-y-auto">{renderStep()}</div>

        {/* Footer */}
        {currentStep !== 'launch' && (
          <div className="border-t border-[var(--accent)]/20 px-6 py-4 flex items-center justify-between">
            <button
              onClick={handleBack}
              disabled={isFirstStep}
              className="px-4 py-2 text-sm font-theme-data text-text-muted hover:text-[var(--accent)] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              &larr; BACK
            </button>

            {/* For create-account step, show login link instead of continue when not authed */}
            {currentStep === 'create-account' && !isAuthenticated ? (
              <Link
                href="/signup"
                className="px-6 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm hover:bg-[var(--accent)]/90 transition-colors inline-block text-center"
              >
                CREATE ACCOUNT &rarr;
              </Link>
            ) : (
              <button
                onClick={handleNext}
                disabled={!canProceed}
                className="px-6 py-2 bg-[var(--accent)] text-bg font-theme-data text-sm hover:bg-[var(--accent)]/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {isLastStep ? 'FINISH' : 'CONTINUE \u2192'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Step 3: Create Account -- auth transition.
 * Shows value proposition and links to register/login.
 */
function CreateAccountStep({ isAuthenticated }: { isAuthenticated: boolean }) {
  if (isAuthenticated) {
    return (
      <div className="space-y-4 text-center py-6">
        <div className="text-3xl">&#10003;</div>
        <h2 className="text-lg font-theme-data text-[var(--acid-green)]">You&apos;re Signed In</h2>
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          Great -- you&apos;re ready to choose a template and run your first debate.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-theme-data text-[var(--acid-green)] mb-2">Save Your Results</h2>
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          Create a free account to unlock real AI models and save your debate history.
        </p>
      </div>

      <div className="space-y-3">
        {[
          'Real AI models (Claude, GPT, Mistral, Gemini)',
          'Multi-round adversarial debates',
          'Audit-ready decision receipts',
          'Knowledge Mound integration',
          'Team collaboration and sharing',
        ].map((feature) => (
          <div key={feature} className="flex items-center gap-2 text-sm font-theme-data">
            <span className="text-[var(--acid-green)]">+</span>
            <span className="text-[var(--text)]">{feature}</span>
          </div>
        ))}
      </div>

      <div className="flex flex-col sm:flex-row gap-3 pt-2">
        <Link
          href="/signup"
          className="flex-1 px-6 py-3 bg-[var(--acid-green)] text-[var(--bg)] font-theme-data font-bold text-sm text-center hover:opacity-90 transition-opacity"
        >
          CREATE FREE ACCOUNT
        </Link>
        <Link
          href="/auth/login"
          className="flex-1 px-6 py-3 border border-[var(--acid-green)]/30 text-[var(--acid-green)] font-theme-data text-sm text-center hover:border-[var(--acid-green)] transition-colors"
        >
          SIGN IN
        </Link>
      </div>
    </div>
  );
}

/**
 * Step 8: Launch -- finalize onboarding with checklist summary.
 */
function LaunchStep({
  selectedIndustry,
  trialDebateResult,
  onComplete,
}: {
  selectedIndustry: string | null;
  trialDebateResult: Record<string, unknown> | null;
  onComplete?: () => void;
}) {
  const completeOnboarding = useOnboardingStore((s) => s.completeOnboarding);
  const chosenTemplateId = useOnboardingStore((s) => s.chosenTemplateId);

  const trialTopic = trialDebateResult
    ? String((trialDebateResult as Record<string, unknown>).topic || '')
    : '';

  const handleLaunch = () => {
    completeOnboarding();
    onComplete?.();
  };

  const arenaUrl = chosenTemplateId
    ? `/arena?template=${encodeURIComponent(chosenTemplateId)}${selectedIndustry ? `&vertical=${selectedIndustry}` : ''}`
    : trialTopic
      ? `/arena?topic=${encodeURIComponent(trialTopic)}${selectedIndustry ? `&vertical=${selectedIndustry}` : ''}`
      : `/arena${selectedIndustry ? `?vertical=${selectedIndustry}` : ''}`;

  return (
    <div className="space-y-6 py-4">
      <div className="text-center">
        <h2 className="text-xl font-theme-data text-[var(--acid-green)] mb-2">Ready to Launch</h2>
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          Everything is set up. Here is your onboarding progress.
        </p>
      </div>

      {/* Onboarding checklist */}
      <OnboardingChecklist />

      {trialTopic && (
        <div className="border border-[var(--border)] bg-[var(--surface)] p-4 text-left">
          <div className="text-[10px] font-theme-data text-[var(--text-muted)] uppercase mb-1">
            Your Topic
          </div>
          <p className="text-sm font-theme-data text-[var(--text)]">{trialTopic}</p>
        </div>
      )}

      <div className="flex flex-col gap-3 text-center">
        <Link
          href={arenaUrl}
          onClick={handleLaunch}
          className="px-8 py-4 bg-[var(--acid-green)] text-[var(--bg)] font-theme-data font-bold text-sm hover:opacity-90 transition-opacity"
        >
          LAUNCH REAL DEBATE
        </Link>
        <button
          onClick={handleLaunch}
          className="px-4 py-2 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
        >
          Skip to dashboard
        </button>
      </div>
    </div>
  );
}

export default OnboardingWizardFlow;
