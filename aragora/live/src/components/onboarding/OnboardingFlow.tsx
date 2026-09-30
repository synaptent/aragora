'use client';

import { useCallback } from 'react';
import { getRuntimeBackendConfig } from '@/components/BackendSelector';
import { useRouter } from 'next/navigation';
import { logger } from '@/utils/logger';
import {
  useOnboardingStore,
  useOnboardingStep,
  useOnboardingProgress,
  selectIsOnboardingNeeded,
  SelectedTemplate,
} from '@/store/onboardingStore';
import { WelcomeStep, UseCaseStep, OrganizationStep, TemplateStep, CompletionStep } from './steps';

interface OnboardingFlowProps {
  onComplete?: () => void;
  onSkip?: () => void;
}

export function OnboardingFlow({ onComplete, onSkip }: OnboardingFlowProps) {
  const router = useRouter();
  const apiBase = getRuntimeBackendConfig().config.api;
  const {
    currentStep,
    nextStep,
    previousStep,
    completeOnboarding,
    skipOnboarding,
    setFirstDebateId,
    setDebateStatus,
  } = useOnboardingStore();

  const { stepIndex, totalSteps } = useOnboardingStep();
  const { percentage } = useOnboardingProgress();
  const needsOnboarding = useOnboardingStore(selectIsOnboardingNeeded);

  // Handle skip
  const handleSkip = useCallback(() => {
    skipOnboarding();
    onSkip?.();
  }, [skipOnboarding, onSkip]);

  // Handle completion
  const handleComplete = useCallback(() => {
    completeOnboarding();
    onComplete?.();
    router.push('/');
  }, [completeOnboarding, onComplete, router]);

  // Handle use case selection
  const handleUseCaseNext = useCallback(
    (_useCase: string) => {
      nextStep();
    },
    [nextStep],
  );

  // Handle template selection and start debate
  const handleTemplateNext = useCallback(
    async (template: SelectedTemplate) => {
      setDebateStatus('creating');

      try {
        // Create first debate via API
        const response = await fetch(`${apiBase}/api/v1/onboarding/first-debate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ template_id: template.id, use_example: true }),
        });

        if (response.ok) {
          const data = await response.json();
          setFirstDebateId(data.debate_id);
          setDebateStatus('running');

          // Navigate to debate page
          router.push(`/debate/${data.debate_id}`);
        } else {
          setDebateStatus('error');
        }
      } catch (error) {
        logger.error('Failed to create first debate:', error);
        setDebateStatus('error');
      }

      nextStep();
    },
    [apiBase, nextStep, router, setFirstDebateId, setDebateStatus],
  );

  // Don't render if onboarding not needed
  if (!needsOnboarding) return null;

  const renderStep = () => {
    switch (currentStep) {
      case 'welcome':
        return <WelcomeStep onNext={nextStep} onSkip={handleSkip} />;
      case 'organization':
        return <UseCaseStep onNext={handleUseCaseNext} onBack={previousStep} />;
      case 'team-invite':
        return <OrganizationStep onNext={nextStep} onBack={previousStep} />;
      case 'template-select':
        return <TemplateStep onNext={handleTemplateNext} onBack={previousStep} />;
      case 'completion':
        return <CompletionStep onComplete={handleComplete} />;
      default:
        // For other steps, show a simple next/back UI
        return (
          <div className="space-y-6">
            <div>
              <h2 className="text-xl font-theme-data text-[var(--accent)] mb-2">
                {currentStep.replace(/-/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase())}
              </h2>
              <p className="font-theme-data text-text-muted text-sm">
                Continue setting up your Aragora experience
              </p>
            </div>
            <div className="flex gap-3 pt-4">
              <button
                onClick={previousStep}
                className="px-4 py-2 font-theme-data text-sm border border-[var(--accent)]/30 text-text-muted hover:border-[var(--accent)] hover:text-[var(--accent)] transition-colors"
              >
                Back
              </button>
              <div className="flex-1" />
              <button
                onClick={nextStep}
                className="px-6 py-2 font-theme-data text-sm bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
              >
                Continue
              </button>
            </div>
          </div>
        );
    }
  };

  return (
    <div className="fixed inset-0 z-[100] bg-bg/95 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="max-w-lg w-full border border-[var(--accent)]/50 bg-surface p-6">
        {/* Progress Bar */}
        <div className="mb-6">
          <div className="flex justify-between items-center mb-2">
            <span className="text-xs font-theme-data text-text-muted">
              STEP {stepIndex + 1} OF {totalSteps}
            </span>
            {currentStep !== 'completion' && (
              <button
                onClick={handleSkip}
                className="text-xs font-theme-data text-text-muted hover:text-[var(--accent)] transition-colors"
              >
                [SKIP]
              </button>
            )}
          </div>
          <div className="h-1 bg-surface border border-[var(--accent)]/20">
            <div
              className="h-full bg-[var(--accent)] transition-all duration-300"
              style={{ width: `${percentage}%` }}
            />
          </div>
        </div>

        {/* Step Content */}
        {renderStep()}

        {/* Step Indicators */}
        <div className="flex justify-center gap-2 mt-6">
          {Array.from({ length: totalSteps }).map((_, idx) => (
            <div
              key={idx}
              className={`w-2 h-2 transition-colors ${
                idx === stepIndex
                  ? 'bg-[var(--accent)]'
                  : idx < stepIndex
                    ? 'bg-[var(--accent)]/50'
                    : 'bg-surface border border-[var(--accent)]/30'
              }`}
            />
          ))}
        </div>
      </div>
    </div>
  );
}

export function useOnboarding() {
  const { isComplete, isSkipped, resetOnboarding } = useOnboardingStore();
  const needsOnboarding = useOnboardingStore(selectIsOnboardingNeeded);

  return { showOnboarding: needsOnboarding, isComplete, isSkipped, resetOnboarding };
}

export default OnboardingFlow;
