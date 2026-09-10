'use client';

interface WelcomeStepProps {
  onNext: () => void;
  onSkip: () => void;
}

export function WelcomeStep({ onNext, onSkip }: WelcomeStepProps) {
  return (
    <div className="space-y-6">
      <div className="text-center">
        <div className="inline-block p-4 bg-[var(--accent)]/10 border border-[var(--accent)]/30 mb-4">
          <span className="text-4xl">&#x2694;</span>
        </div>
        <h2 className="text-2xl font-theme-data text-[var(--accent)] mb-2">Welcome to Aragora</h2>
        <p className="font-theme-data text-text-muted text-sm">
          AI models that debate your decisions
        </p>
      </div>

      <div className="space-y-4">
        <div className="p-4 bg-surface border border-[var(--accent)]/20">
          <h3 className="font-theme-data text-[var(--acid-cyan)] text-sm mb-2">How it works</h3>
          <ol className="space-y-2 font-theme-data text-text-muted text-sm">
            <li className="flex items-start gap-2">
              <span className="text-[var(--accent)]">1.</span>
              <span>Ask a question or describe a decision</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-[var(--accent)]">2.</span>
              <span>Multiple AI agents debate your topic</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-[var(--accent)]">3.</span>
              <span>Watch consensus emerge with full reasoning</span>
            </li>
            <li className="flex items-start gap-2">
              <span className="text-[var(--accent)]">4.</span>
              <span>Get a defensible decision with audit trail</span>
            </li>
          </ol>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div className="p-3 bg-[var(--accent)]/5 border border-[var(--accent)]/20 text-center">
            <div className="text-2xl font-theme-data text-[var(--accent)] mb-1">15+</div>
            <div className="text-xs font-theme-data text-text-muted">AI Models</div>
          </div>
          <div className="p-3 bg-[var(--accent)]/5 border border-[var(--accent)]/20 text-center">
            <div className="text-2xl font-theme-data text-[var(--accent)] mb-1">100%</div>
            <div className="text-xs font-theme-data text-text-muted">Auditable</div>
          </div>
        </div>
      </div>

      <div className="flex gap-3 pt-4">
        <button
          onClick={onSkip}
          className="px-4 py-2 font-theme-data text-sm text-text-muted hover:text-[var(--accent)] transition-colors"
        >
          Skip tutorial
        </button>
        <div className="flex-1" />
        <button
          onClick={onNext}
          className="px-6 py-2 font-theme-data text-sm bg-[var(--accent)] text-bg hover:bg-[var(--accent)]/80 transition-colors"
        >
          Get started
        </button>
      </div>
    </div>
  );
}

export default WelcomeStep;
