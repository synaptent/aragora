'use client';

import { useState, useCallback } from 'react';
import { getRuntimeBackendConfig } from '@/components/BackendSelector';
import { useOnboardingStore } from '@/store/onboardingStore';
import { TEMPLATES, type TemplateCategory } from '@/components/templates/templateData';

/**
 * Step 2: Try a Debate (no auth required).
 * Runs a playground debate using a template from the selected industry.
 */
export function TryDebateStep() {
  const selectedIndustry = useOnboardingStore((s) => s.selectedIndustry);
  const trialDebateResult = useOnboardingStore((s) => s.trialDebateResult);
  const setTrialDebateResult = useOnboardingStore((s) => s.setTrialDebateResult);

  const [topic, setTopic] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Get templates for the selected industry
  const industryTemplates = TEMPLATES.filter(
    (t) => t.category === (selectedIndustry as TemplateCategory),
  );
  const fallbackTemplates = TEMPLATES.filter((t) => t.category === 'general');
  const templates = industryTemplates.length > 0 ? industryTemplates : fallbackTemplates;

  const apiBase = getRuntimeBackendConfig().config.api;

  const runTrial = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(`${apiBase}/api/v1/playground/debate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          topic: topic || templates[0]?.exampleTopics[0] || 'Should we adopt this approach?',
          rounds: 2,
          agents: 3,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        setError(data.error || `Request failed (${res.status})`);
        return;
      }

      setTrialDebateResult(data);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : 'Network error';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [apiBase, topic, templates, setTrialDebateResult]);

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-lg font-theme-data text-[var(--acid-green)] mb-2">Try a Free Debate</h2>
        <p className="text-sm font-theme-data text-[var(--text-muted)]">
          See how AI agents stress-test a decision. Pick a topic or use one of ours.
        </p>
      </div>

      {/* Topic input */}
      <div>
        <input
          type="text"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          placeholder={templates[0]?.exampleTopics[0] || 'Enter a decision to debate...'}
          className="w-full bg-[var(--surface)] border border-[var(--border)] text-[var(--text)] px-4 py-3 font-theme-data text-sm placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--acid-green)] transition-colors"
          disabled={loading}
        />

        {/* Suggested topics from templates */}
        <div className="flex flex-wrap gap-2 mt-2">
          {templates
            .slice(0, 3)
            .flatMap((t) => t.exampleTopics.slice(0, 1))
            .map((ex) => (
              <button
                key={ex}
                onClick={() => setTopic(ex)}
                disabled={loading}
                className="text-xs px-2 py-1 border border-[var(--border)] text-[var(--text-muted)] hover:text-[var(--acid-green)] hover:border-[var(--acid-green)] transition-colors disabled:opacity-50"
              >
                {ex}
              </button>
            ))}
        </div>
      </div>

      {/* Run button */}
      {!trialDebateResult && (
        <button
          onClick={runTrial}
          disabled={loading}
          className="w-full px-6 py-3 bg-[var(--acid-green)] text-[var(--bg)] font-theme-data font-bold text-sm hover:opacity-90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {loading ? 'Agents are debating...' : 'RUN FREE DEBATE'}
        </button>
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-6">
          <div className="flex items-center gap-3 text-[var(--acid-green)]">
            <div className="w-5 h-5 border-2 border-[var(--acid-green)]/30 border-t-[var(--acid-green)] rounded-full animate-spin" />
            <span className="text-sm font-theme-data">MockAgents are debating...</span>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="border border-[var(--crimson)] bg-[var(--crimson)]/10 p-3">
          <p className="text-sm font-theme-data text-[var(--crimson)]">{error}</p>
          <button
            onClick={runTrial}
            className="mt-2 text-xs font-theme-data text-[var(--text-muted)] hover:text-[var(--acid-green)] transition-colors"
          >
            Try again
          </button>
        </div>
      )}

      {/* Compact result */}
      {trialDebateResult && (
        <div className="border border-[var(--acid-green)]/30 bg-[var(--acid-green)]/5 p-4 space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-[var(--acid-green)] font-theme-data font-bold text-sm">
              Debate Complete
            </span>
            <span
              className={`text-xs font-theme-data px-2 py-0.5 border ${
                (trialDebateResult as Record<string, unknown>).consensus_reached
                  ? 'border-green-500/30 text-green-400 bg-green-500/10'
                  : 'border-yellow-500/30 text-yellow-400 bg-yellow-500/10'
              }`}
            >
              {(trialDebateResult as Record<string, unknown>).consensus_reached
                ? 'CONSENSUS'
                : 'NO CONSENSUS'}
            </span>
          </div>

          {/* Verdict summary */}
          {(trialDebateResult as Record<string, unknown>).final_answer ? (
            <p className="text-xs font-theme-data text-[var(--text)] leading-relaxed line-clamp-3">
              {String((trialDebateResult as Record<string, unknown>).final_answer)}
            </p>
          ) : null}

          <div className="flex items-center gap-4 text-xs font-theme-data text-[var(--text-muted)]">
            <span>
              {(Number((trialDebateResult as Record<string, unknown>).confidence) * 100).toFixed(0)}
              % confidence
            </span>
            <span>{String((trialDebateResult as Record<string, unknown>).rounds_used)} rounds</span>
            <span>
              {((trialDebateResult as Record<string, unknown>).participants as string[])?.length ||
                0}{' '}
              agents
            </span>
          </div>

          <p className="text-xs font-theme-data text-[var(--acid-cyan)]">
            Want deeper analysis with real AI models? Continue to create your account.
          </p>
        </div>
      )}
    </div>
  );
}
