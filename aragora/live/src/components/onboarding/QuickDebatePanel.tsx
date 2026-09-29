'use client';

import { useState } from 'react';
import { useOnboardingStore } from '@/store/onboardingStore';
import { getRuntimeBackendConfig } from '@/components/BackendSelector';
import { logger } from '@/utils/logger';

const DEFAULT_QUESTIONS: Record<string, string> = {
  hiring: 'Should we hire a senior engineer or two junior engineers for our growing team?',
  'contract-review': 'What are the key risks in this SaaS vendor contract?',
  budget: 'How should we allocate our Q2 marketing budget across channels?',
  'feature-priority': 'Should we prioritize mobile app or API improvements this quarter?',
  'vendor-selection': 'Which project management tool should our team adopt?',
  compliance: 'Are we meeting GDPR requirements for our customer data handling?',
};

export function QuickDebatePanel() {
  const apiBase = getRuntimeBackendConfig().config.api;
  const selectedTemplate = useOnboardingStore((s) => s.selectedTemplate);
  const debateStatus = useOnboardingStore((s) => s.debateStatus);
  const debateError = useOnboardingStore((s) => s.debateError);
  const firstDebateTopic = useOnboardingStore((s) => s.firstDebateTopic);
  const setFirstDebateTopic = useOnboardingStore((s) => s.setFirstDebateTopic);
  const setDebateStatus = useOnboardingStore((s) => s.setDebateStatus);
  const setDebateError = useOnboardingStore((s) => s.setDebateError);
  const setFirstDebateId = useOnboardingStore((s) => s.setFirstDebateId);
  const updateProgress = useOnboardingStore((s) => s.updateProgress);

  const [result, setResult] = useState<string | null>(null);

  const defaultQuestion = selectedTemplate?.id
    ? (DEFAULT_QUESTIONS[selectedTemplate.id] ?? '')
    : '';
  const question = firstDebateTopic || defaultQuestion;

  const handleStartDebate = async () => {
    if (!question.trim()) return;

    setDebateStatus('creating');
    setDebateError(null);
    setFirstDebateTopic(question);

    try {
      const res = await fetch(`${apiBase}/api/v1/debates`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: question.trim(),
          template_id: selectedTemplate?.id,
          rounds: selectedTemplate?.rounds ?? 5,
        }),
      });

      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }

      const data = await res.json();
      setFirstDebateId(data.id || data.debate_id);
      setDebateStatus('running');
      updateProgress({ firstDebateStarted: true });

      // Poll for completion
      pollForResult(data.id || data.debate_id);
    } catch (e) {
      logger.error('Failed to start debate:', e);
      setDebateStatus('error');
      setDebateError('Failed to start debate. You can skip this step.');
    }
  };

  const pollForResult = async (debateId: string) => {
    const maxAttempts = 60;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const res = await fetch(`${apiBase}/api/v1/debates/${debateId}`);
        if (!res.ok) continue;
        const data = await res.json();
        if (data.status === 'completed') {
          setResult(
            data.verdict ||
              data.final_answer ||
              data.consensus?.final_answer ||
              data.consensus?.conclusion ||
              'Debate completed.',
          );
          setDebateStatus('completed');
          updateProgress({ firstDebateCompleted: true, receiptViewed: true });
          return;
        }
        if (data.status === 'failed') {
          setDebateStatus('error');
          setDebateError('Debate failed. You can skip this step.');
          return;
        }
      } catch {
        // keep polling
      }
    }
    // Timed out - treat as done so user can proceed
    setDebateStatus('completed');
    setResult('Debate is still running. You can view results later from the dashboard.');
    updateProgress({ firstDebateCompleted: true, receiptViewed: true });
  };

  return (
    <div className="bg-[var(--surface)] border border-[var(--border)] p-6">
      <h2 className="text-lg font-theme-data text-[var(--acid-green)] mb-4">
        {'>'} YOUR FIRST DEBATE
      </h2>

      {debateStatus === 'idle' || debateStatus === 'error' ? (
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-theme-data text-[var(--text-muted)] mb-2">
              QUESTION
            </label>
            <textarea
              value={question}
              onChange={(e) => setFirstDebateTopic(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 text-sm font-theme-data bg-[var(--bg)] text-[var(--text)] border border-[var(--border)] focus:border-[var(--acid-green)]/60 focus:outline-none transition-colors resize-none"
              placeholder="Enter a question for AI agents to debate..."
            />
          </div>

          {debateError && (
            <div className="text-xs font-theme-data text-[var(--warning)] p-2 border border-[var(--warning)]/30 bg-[var(--warning)]/5">
              {debateError}
            </div>
          )}

          <button
            onClick={handleStartDebate}
            disabled={!question.trim()}
            className="w-full px-4 py-3 text-sm font-theme-data bg-[var(--acid-green)]/10 text-[var(--acid-green)] border border-[var(--acid-green)]/40 hover:bg-[var(--acid-green)]/20 transition-colors disabled:opacity-30 disabled:cursor-not-allowed"
          >
            START DEBATE
          </button>
        </div>
      ) : debateStatus === 'creating' || debateStatus === 'running' ? (
        <div className="py-8 text-center">
          <div className="text-sm font-theme-data text-[var(--acid-green)] animate-pulse mb-2">
            {debateStatus === 'creating' ? '> ASSEMBLING AGENTS...' : '> AGENTS ARE DEBATING...'}
          </div>
          <p className="text-xs font-theme-data text-[var(--text-muted)]">
            {debateStatus === 'running'
              ? 'Multiple AI models are analyzing your question from different angles.'
              : 'Setting up the debate environment.'}
          </p>
          <div className="mt-4 flex justify-center gap-1">
            {[0, 1, 2, 3, 4].map((i) => (
              <div
                key={i}
                className="w-2 h-2 bg-[var(--acid-green)]/60 animate-pulse"
                style={{ animationDelay: `${i * 200}ms` }}
              />
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="text-xs font-theme-data text-[var(--acid-green)] mb-2">
            {'>'} DEBATE COMPLETE
          </div>
          {result && (
            <div className="p-3 bg-[var(--bg)] border border-[var(--acid-green)]/30">
              <p className="text-sm font-theme-data text-[var(--text)]">{result}</p>
            </div>
          )}
          <p className="text-xs font-theme-data text-[var(--text-muted)]">
            You can review full results, agent arguments, and the decision receipt from the
            dashboard.
          </p>
        </div>
      )}
    </div>
  );
}
